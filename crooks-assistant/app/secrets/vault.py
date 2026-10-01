"""Keys the owner stores from the app (the Connections screen): the third tier, encrypted on this machine.

Tier A (systemd credentials) is read-only to the service: changing one means the terminal, a new
unit and a restart. Tier B (the 0600 directory) is plain text on the disk. Neither suits a key
typed into the Connections screen (app/connections), which must work at once and must not sit on
the disk in the clear. So a key stored from the app is encrypted with `systemd-creds encrypt`,
the machine-bound key systemd itself uses for Tier A, into <secret dir>/app/<key>.cred, and
decrypted on read with `systemd-creds decrypt`. A copy of the file taken off this machine is
inert. The plain value never touches the disk and never appears in a process's arguments: it
goes in on stdin and comes back on stdout.

Which tier wins (app/secrets/linux_store.py): this one, then A, then B. A key stored from the app
is the owner's latest explicit choice, made with a passkey, so it wins. Disconnecting from the
app leaves a mark here (<key>.off) that wins the same way, so a key the server still holds in A
or B reads as absent until the owner connects it again. Storing a key at the server prompt
(scripts/provision_secrets.py) clears this tier first, so the latest choice wins whichever door
it came through; a systemd credential stored there reaches the service only at its next start, so
for one of those this tier steps aside at that start and not before (yield_at_restart), and
removing one leaves it disconnected here, so the running service never falls back to it. A value this machine can no longer decrypt (a new TPM state, a restored disk)
reads as absent, never as the older key underneath it: the owner may have replaced that one
because it leaked.

The running service writes here itself when a key it renews lives here (an Instagram token), so
a renewal lands where the next read looks.

On macOS the login Keychain is already encrypted by the system, so there this tier is the
Keychain itself and nothing is written to a file.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.secrets import linux_store

DIR_NAME = "app"           # under the writable tier: <secret dir>/app, 0700
SUFFIX = ".cred"           # an encrypted value
OFF_SUFFIX = ".off"        # disconnected from the app: an empty mark
PROMPT_SUFFIX = ".prompt"  # the server prompt stored a new systemd credential: step aside once it is loaded
TIMEOUT_S = 20.0
MAX_VALUE = 16 * 1024      # an API key, an id, an OAuth token: never more than this
PROBE_KEY = "clive-vault-probe"

DIR_MODE = 0o700
FILE_MODE = 0o600
# A machine that could not encrypt is asked again after this long; one that could is not asked again.
RECHECK_S = 60.0


def _process_started() -> float:
    """When this process was started, as wall-clock seconds: the kernel's own record (boot time plus
    the process's start in clock ticks), so the few seconds of imports before this module loads are
    not counted as "after". The import time when /proc cannot say."""
    try:
        ticks = int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19])
        boot = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines()
                    if line.startswith("btime "))
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return time.time()


# When this process started. A .prompt mark written before it means the systemd credential the mark
# waits for is the one this process was given.
_STARTED = _process_started()
# Whether this process is the service itself (serving(), from app/main.py's startup). Only the
# service settles a prompt's mark: a deploy check run in a transient unit with its own credentials
# (scripts/live_key_check.py) also holds the key, but the service beside it still runs on the old one.
_SERVING = [False]


def serving() -> None:
    """Called once, by the service as it starts (app/main.py): this process may settle prompt marks."""
    _SERVING[0] = True


class VaultUnavailable(RuntimeError):
    """This machine cannot encrypt or decrypt a key for the app tier, and says why."""


@dataclass(frozen=True)
class Entry:
    """What the app tier holds for one key. `kind` is "value", "off" (disconnected from the
    app), "unreadable" (a file this machine cannot decrypt), or "none". Never logged."""

    kind: str
    value: str = ""
    why: str = ""


class Cipher(Protocol):
    def why_not(self) -> str: ...
    def encrypt(self, key: str, plain: bytes) -> bytes: ...
    def decrypt(self, key: str, blob: bytes) -> bytes: ...


class SystemdCreds:
    """`systemd-creds`, run as the service (root today), with systemd's own choice of key: the
    machine's host key, and the TPM as well when there is one, exactly as for Tier A. `--name`
    binds each blob to its key, so a file renamed to another key's name does not decrypt."""

    def __init__(self, binary: str | None = None, runner=subprocess.run) -> None:
        self._binary = binary
        self._runner = runner

    def _path(self) -> str | None:
        return self._binary or shutil.which("systemd-creds")

    def why_not(self) -> str:
        return "" if self._path() else "systemd-creds is not installed on this server"

    def encrypt(self, key: str, plain: bytes) -> bytes:
        return self._run("encrypt", key, plain)

    def decrypt(self, key: str, blob: bytes) -> bytes:
        return self._run("decrypt", key, blob)

    def _run(self, verb: str, key: str, data: bytes) -> bytes:
        binary = self._path()
        if not binary:
            raise VaultUnavailable(self.why_not())
        try:
            done = self._runner([binary, verb, f"--name={key}", "-", "-"], input=data,
                                capture_output=True, timeout=TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            raise VaultUnavailable(f"systemd-creds {verb} did not finish in {TIMEOUT_S:.0f}s") from None
        except OSError as exc:
            raise VaultUnavailable(f"systemd-creds {verb} could not run ({type(exc).__name__})") from None
        if done.returncode != 0:
            # systemd-creds names what went wrong on stderr; it never echoes the input there.
            lines = (done.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
            why = lines[-1][:200] if lines else f"exit {done.returncode}"
            raise VaultUnavailable(f"systemd-creds {verb} failed: {why}")
        return done.stdout or b""


_LOCK = threading.RLock()
_CIPHER: list[Cipher] = [SystemdCreds()]
_FILES_ON_MAC = [False]            # tests run the file tier on any platform
_CACHE: dict[str, tuple[tuple[int, int, int], str]] = {}
# A file that would not decrypt, by the same signature, so a read does not run systemd-creds again
# until the file changes.
_BAD: dict[str, tuple[tuple[int, int, int], str]] = {}
_CHECKED: dict[str, tuple[bool, str, float]] = {}


def bind(cipher: Cipher | None = None, *, files_everywhere: bool | None = None) -> None:
    """Tests: a stand-in cipher, and the file tier even on a Mac (never the owner's Keychain).
    No arguments puts production back."""
    with _LOCK:
        _CIPHER[0] = cipher or SystemdCreds()
        _FILES_ON_MAC[0] = bool(files_everywhere) if files_everywhere is not None else cipher is not None
        _CACHE.clear()
        _BAD.clear()
        _CHECKED.clear()


def _keychain_tier() -> bool:
    """On a Mac the app tier is the login Keychain, unless a test has bound the file tier."""
    return sys.platform == "darwin" and not _FILES_ON_MAC[0]


def directory() -> Path:
    return linux_store.store_dir() / DIR_NAME


def _blob(key: str) -> Path:
    return directory() / f"{key}{SUFFIX}"


def _off(key: str) -> Path:
    return directory() / f"{key}{OFF_SUFFIX}"


def _prompt(key: str) -> Path:
    return directory() / f"{key}{PROMPT_SUFFIX}"


def _settle(key: str) -> None:
    """Under _LOCK: step aside for a systemd credential the server prompt stored (yield_at_restart),
    and only in the one process that can know it has that credential: the service (serving()), started
    after the prompt stored it, with the key among the credentials systemd loaded for it. Any other
    process (the prompt's own status listing, the doctor, a deploy check in a transient unit) never settles,
    so it cannot lift the app tier's answer from under a service still running on the old credential;
    and a restart whose unit does not load the key yet (no `make install` since) settles nothing
    either. Until then this tier's answer stands."""
    mark = _prompt(key)
    try:
        written = mark.stat().st_mtime
    except OSError:
        return                          # no mark, or none this process may see: the answer stands
    if not _SERVING[0] or written >= _STARTED or not linux_store.provisioned_by_systemd(key):
        return                          # not the restarted service, or it did not load the new credential
    try:
        _blob(key).unlink(missing_ok=True)
        _off(key).unlink(missing_ok=True)
        mark.unlink(missing_ok=True)
    except OSError:
        return
    _CACHE.pop(key, None)
    _BAD.pop(key, None)


def _signature(path: Path) -> tuple[int, int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_ino, info.st_size, info.st_mtime_ns)


def _exists(path: Path) -> bool:
    """Path.exists() raises for a directory this process may not read (a shell that is not root,
    looking into the 0700 secret directory); this tier then simply has nothing to say."""
    try:
        return path.exists()
    except OSError:
        return False


def clean(value: str) -> str:
    """The value as it will be stored: surrounding whitespace gone, and refused (ValueError,
    which never quotes it) when empty, too long, or holding a control character, which an arrow
    key or a terminal's escape code leaves behind and which no key ever holds."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("nothing was entered")
    if len(text) > MAX_VALUE:
        raise ValueError(f"longer than {MAX_VALUE} characters, which no key is")
    if any(ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0 for ch in text):
        raise ValueError("it holds a control character, which no key does: paste it again")
    return text


def entry(key: str) -> Entry:
    """What this tier holds for `key`, decrypting at most once per change of the file."""
    if _keychain_tier():
        return Entry("none")
    with _LOCK:
        _settle(key)
        blob = _blob(key)
        signature = _signature(blob)
        if signature is None:
            _CACHE.pop(key, None)
            _BAD.pop(key, None)
            return Entry("off") if _exists(_off(key)) else Entry("none")
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == signature:
            return Entry("value", cached[1])
        bad = _BAD.get(key)
        if bad is not None and bad[0] == signature:
            return Entry("unreadable", why=bad[1])
        try:
            plain = _CIPHER[0].decrypt(key, blob.read_bytes())
            value = plain.decode("utf-8").strip()
            if not value:
                raise VaultUnavailable("the stored value is empty")
        except (VaultUnavailable, OSError, UnicodeDecodeError) as exc:
            why = str(exc) if isinstance(exc, VaultUnavailable) else type(exc).__name__
            _BAD[key] = (signature, why)
            return Entry("unreadable", why=why)
        _CACHE[key] = (signature, value)
        _BAD.pop(key, None)
        return Entry("value", value)


def holds(key: str) -> bool:
    """Whether this tier speaks for `key`: a value, an unreadable value, or a disconnection."""
    return entry(key).kind != "none"


def _ensure_directory() -> Path:
    folder = directory()
    linux_store.ensure_store_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    if stat.S_IMODE(folder.stat().st_mode) != DIR_MODE:
        folder.chmod(DIR_MODE)
    return folder


def _write_atomically(target: Path, data: bytes) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        os.fchmod(handle, FILE_MODE)
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(target)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def store(key: str, value: str) -> None:
    """Encrypt `value` for `key` and keep it; it is read at the next call, with no restart.
    Raises VaultUnavailable (nothing written) when this machine cannot encrypt, and ValueError
    for a value no key could be."""
    from app.secrets import keychain

    keychain._validate(key)
    text = clean(value)
    if _keychain_tier():
        import keyring

        keyring.set_password(keychain.SERVICE, key, text)
        return
    with _LOCK:
        cipher = _CIPHER[0]
        plain = text.encode("utf-8")
        blob = cipher.encrypt(key, plain)
        # Proved before it replaces anything: a blob this machine cannot read back would leave the
        # owner with no key at all, which is worse than the key they had.
        if not blob or cipher.decrypt(key, blob) != plain:
            raise VaultUnavailable("the encrypted key did not decrypt back to what was entered")
        _ensure_directory()
        target = _blob(key)
        _write_atomically(target, blob)
        _off(key).unlink(missing_ok=True)
        _prompt(key).unlink(missing_ok=True)       # the owner's latest choice, made after the prompt's
        _BAD.pop(key, None)
        signature = _signature(target)
        if signature is not None:
            _CACHE[key] = (signature, text)


def disconnect(key: str) -> None:
    """Forget the app's value and mark `key` disconnected, so it reads as absent even where the
    server still holds it in Tier A or B, until the owner connects it again."""
    from app.secrets import keychain

    keychain._validate(key)
    if _keychain_tier():
        import keyring

        try:
            keyring.delete_password(keychain.SERVICE, key)
        except Exception:  # noqa: BLE001 - keyring raises its own type for "absent"
            pass
        return
    with _LOCK:
        _ensure_directory()
        _blob(key).unlink(missing_ok=True)
        _prompt(key).unlink(missing_ok=True)
        _CACHE.pop(key, None)
        _BAD.pop(key, None)
        _write_atomically(_off(key), b"")


def clear(key: str) -> None:
    """Take this tier out of the answer for `key` altogether (its value and any disconnection):
    what the server prompt does before it stores or removes a key, so the latest choice wins."""
    if _keychain_tier():
        return
    with _LOCK:
        _blob(key).unlink(missing_ok=True)
        _off(key).unlink(missing_ok=True)
        _prompt(key).unlink(missing_ok=True)
        _CACHE.pop(key, None)
        _BAD.pop(key, None)


def yield_at_restart(key: str) -> None:
    """The server prompt has just stored a new systemd credential (Tier A) for `key`, which the
    service loads only when it next starts. Until then this tier's answer stands: a key the owner
    disconnected in the app stays disconnected, instead of the old credential the running service
    still holds coming back, which may be the very key he disconnected because it leaked. Once the
    service has started after this, the tier steps aside and the new credential is read (the
    1 October review, finding 2). Nothing to do when this tier holds nothing for the key."""
    if _keychain_tier():
        return
    with _LOCK:
        if not (_exists(_blob(key)) or _exists(_off(key))):
            return
        _ensure_directory()
        _write_atomically(_prompt(key), b"")


def check() -> tuple[bool, str]:
    """Whether this machine can keep a key for the app, proved by encrypting and decrypting a
    probe (never a real key): once per process when it can, again after a minute when it cannot.
    (True, "") or (False, why)."""
    if _keychain_tier():
        return True, ""
    with _LOCK:
        known = _CHECKED.get("probe")
        if known is not None and (known[0] or time.monotonic() - known[2] < RECHECK_S):
            return known[0], known[1]
        cipher = _CIPHER[0]
        why = cipher.why_not()
        if not why:
            try:
                sample = os.urandom(16).hex().encode()
                if cipher.decrypt(PROBE_KEY, cipher.encrypt(PROBE_KEY, sample)) != sample:
                    why = "a probe did not decrypt to what was encrypted"
            except VaultUnavailable as exc:
                why = str(exc)
        _CHECKED["probe"] = (not why, why, time.monotonic())
        return not why, why
