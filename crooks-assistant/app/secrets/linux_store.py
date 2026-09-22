"""Secret storage on Linux, where there is no Keychain.

Two tiers, and the difference between them is the whole point of this module: a secret that
is never written at runtime is not the same kind of thing as one the application refreshes
by itself, and storing both the same way gets one of them wrong.

  Tier A — systemd credentials, `$CREDENTIALS_DIRECTORY/<key>`.
      READ-ONLY. Provisioned by `LoadCredential=` in the unit, decrypted by systemd from a
      host-bound `systemd-creds encrypt` blob, and mounted on a tmpfs visible to this service
      and nothing else. Encrypted at rest, so a disk image or a VM snapshot does not carry
      the credential. Right for a static secret: the ElevenLabs key, the Shopify client id
      and secret.

  Tier B — a root-only directory, /etc/crooks-os/secrets/<key>, dir 0700, files 0600.
      READ-WRITE. Right for anything the application itself rewrites — the Gmail token, which
      google-auth refreshes about once an hour — and for anything generated once at install
      and then needed unchanged for the life of the machine, such as the media signing key.

Reads look in A and then B. Writes go to B. A write to a key that Tier A already provides
would be read back as the Tier A value and the caller would never know, so it raises
SecretShadowed instead — loudly, naming the key and what to do about it. That is the one
place this backend's contract differs from keyring's, and it is a refusal, never a silence.

Nothing here is used on macOS. `app/secrets/keychain.py` dispatches on the platform and the
Mac keeps the Keychain exactly as it always had it.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

# Where a systemd unit's LoadCredential= entries are mounted. systemd sets this; nothing else
# does, so its absence simply means "not running under a unit that provisions credentials".
CREDENTIALS_ENV = "CREDENTIALS_DIRECTORY"

# The writable tier. Overridable so the test suite — and a developer without root — can point
# it somewhere harmless; production uses the default and the installer creates it 0700.
STORE_DIR_ENV = "CROOKS_SECRET_DIR"
DEFAULT_STORE_DIR = Path("/etc/crooks-os/secrets")

DIR_MODE = 0o700
FILE_MODE = 0o600

# Which tier each secret belongs in, decided by one question: does anything in the running
# application ever write it? The answer was read out of the code, not assumed —
#
#   STATIC    read through keychain.get/get_optional and never written outside the installer.
#             app/clients/elevenlabs.py, elevenlabs_tts.py (the one key, read and cached in
#             memory), app/clients/shopify.py (client id and secret, read to mint an access
#             token that is then held in memory only), app/providers/max_agent_sdk.py (the
#             optional stored token; absent is the normal path, where the claude CLI's own
#             login is used instead).
#
#   MUTABLE   written by the application at runtime. Exactly two things qualify:
#             gmail_token, which app/clients/gmail.py rewrites after every OAuth refresh —
#             about hourly — and media_signing_key, which app/media.py generates the first
#             time it is needed and must then keep for the life of the machine, because the
#             tablet's thumbnail cache is keyed on paths signed with it.
#
# A STATIC secret may be provisioned into Tier A, where it is encrypted at rest and read-only.
# A MUTABLE one may not: the write would be refused and the credential could never be renewed.
STATIC_KEYS = frozenset({
    "elevenlabs_api_key",
    "shopify_client_id",
    "shopify_client_secret",
    "shopify_static_token",
    "claude_oauth_token",
})
MUTABLE_KEYS = frozenset({
    "gmail_token",
    "media_signing_key",
})


class SecretShadowed(RuntimeError):
    """A write to a key that systemd provisions read-only.

    Raised rather than writing somewhere the next read would ignore. The caller is told which
    key, and that re-provisioning is an operator action on the unit, not an application one.
    """

    def __init__(self, key: str) -> None:
        super().__init__(
            f"Secret {key!r} is provisioned read-only by systemd (LoadCredential) and cannot "
            f"be written from the application: the next read would return the systemd value "
            f"and this write would be invisible. Re-provision it with "
            f"`python scripts/provision_secrets.py {key}` and restart the service."
        )
        self.key = key


def store_dir() -> Path:
    """The writable tier's directory, read from the environment each call so a test can move
    it without re-importing the module."""
    configured = os.environ.get(STORE_DIR_ENV)
    return Path(configured) if configured else DEFAULT_STORE_DIR


def credentials_dir() -> Path | None:
    """The systemd credentials directory, when this process is running under a unit that has
    one. Never created by us — systemd owns it."""
    raw = os.environ.get(CREDENTIALS_ENV)
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def _read_file(path: Path) -> str | None:
    """A secret file's contents, or None when it is absent or empty.

    The trailing newline goes: `systemd-creds encrypt` round-trips whatever it was given, and
    a key pasted through a here-doc or `echo` carries one. A credential with a stray newline
    fails authentication in a way that reads like a wrong key, which is an afternoon lost.
    """
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    value = value.strip()
    return value or None


def provisioned_by_systemd(key: str) -> bool:
    """Whether Tier A supplies this key. The test `set` and `delete` make before writing."""
    directory = credentials_dir()
    return directory is not None and (directory / key).is_file()


def read(key: str) -> str | None:
    """The secret, from systemd credentials first and the writable store second."""
    directory = credentials_dir()
    if directory is not None:
        found = _read_file(directory / key)
        if found is not None:
            return found
    return _read_file(store_dir() / key)


def where(key: str) -> str:
    """Which tier holds this secret: "systemd-credential", "file", or "" when neither does.
    Used by the doctor and the installer to show the operator what is provisioned how."""
    directory = credentials_dir()
    if directory is not None and _read_file(directory / key) is not None:
        return "systemd-credential"
    if _read_file(store_dir() / key) is not None:
        return "file"
    return ""


def ensure_store_dir() -> Path:
    """The writable directory, created 0700 if it is not there. Tightens the mode of a
    directory that already exists with a looser one rather than trusting whoever made it."""
    directory = store_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    try:
        current = stat.S_IMODE(directory.stat().st_mode)
        if current != DIR_MODE:
            directory.chmod(DIR_MODE)
    except OSError:
        # Cannot inspect or tighten it; the write below will fail loudly if it matters.
        pass
    return directory


def write(key: str, value: str) -> None:
    """Store a secret in the writable tier, 0600, atomically.

    Written to a temporary file in the same directory, chmod'ed before it holds anything
    anyone would want, then renamed over the target: a reader never sees a half-written
    credential, and the secret is never briefly world-readable.
    """
    if provisioned_by_systemd(key):
        raise SecretShadowed(key)
    directory = ensure_store_dir()
    target = directory / key
    handle, temporary = tempfile.mkstemp(dir=str(directory), prefix=f".{key}.", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        os.fchmod(handle, FILE_MODE)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(target)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def remove(key: str) -> None:
    """Delete a secret from the writable tier. Absent is not an error — keyring's delete is
    forgiving in the same way, and every caller here treats "gone" as the outcome it wanted."""
    if provisioned_by_systemd(key):
        raise SecretShadowed(key)
    (store_dir() / key).unlink(missing_ok=True)
