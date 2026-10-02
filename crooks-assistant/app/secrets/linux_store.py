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

  The app tier — <secret dir>/app/<key>.cred, app/secrets/vault.py.
      Keys the owner stores from the Connections screen, encrypted with the same machine-bound
      key as Tier A, written by the running service and read without a restart. It is asked
      first: a key stored from the app is the owner's latest explicit choice (made with a
      passkey), and a key disconnected there reads as absent even where A or B still holds it.

Reads ask the app tier, then A, then B. Writes go where the key lives now: to the app tier when
it holds the key (so a renewal lands where the next read looks), otherwise to B. A write to a
key that Tier A provides would be read back as the Tier A value and the caller would never know,
so it raises SecretShadowed instead — loudly, naming the key and what to do about it; a write to
a key disconnected in the app raises SecretDisconnected (a SecretShadowed), because it would
quietly connect it again. Those are the places this backend's contract differs from keyring's,
and each is a refusal, never a silence.

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
#   MUTABLE   written by the application at runtime. Exactly four things qualify:
#             gmail_token, which app/clients/gmail.py rewrites after every OAuth refresh —
#             about hourly — and media_signing_key, which app/media.py generates the first
#             time it is needed and must then keep for the life of the machine, because the
#             tablet's thumbnail cache is keyed on paths signed with it; local_cli_key,
#             which app/local_cli.py generates the same way for the server's own commands; and
#             instagram_access_token, which app/clients/instagram.py renews before its 60 days
#             run out.
#
# A STATIC secret may be provisioned into Tier A, where it is encrypted at rest and read-only.
# A MUTABLE one may not: the write would be refused and the credential could never be renewed.
STATIC_KEYS = frozenset({
    "elevenlabs_api_key",
    "shopify_client_id",
    "shopify_client_secret",
    "shopify_static_token",
    "claude_oauth_token",
    "github_engineering_inbox_token",
    # Read by app/clients/youtube.py for each search and never written by the application.
    "youtube_api_key",
    # Read by app/clients/ship24.py for each parcel looked up and never written by the application.
    "ship24_api_key",
    # The Meta app's id and secret: read by scripts/instagram.py when a new token is exchanged
    # by hand, never written by the application.
    "instagram_app_id",
    "instagram_app_secret",
})
MUTABLE_KEYS = frozenset({
    "gmail_token",
    "media_signing_key",
    # Generated by the backend the first time it starts (app/local_cli.py), like the media key.
    "local_cli_key",
    # Renewed by app/clients/instagram.py before its 60 days run out, and written back then.
    "instagram_access_token",
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


class SecretDisconnected(SecretShadowed):
    """A write to a key the owner disconnected in the app (Connections). Writing it would connect
    it again without the owner, so it is refused; connecting it is the owner's, from that screen."""

    def __init__(self, key: str) -> None:
        RuntimeError.__init__(
            self,
            f"Secret {key!r} was disconnected in the app (Connections), so it cannot be written: "
            f"that would connect it again without the owner. Connect it from the Connections "
            f"screen, or store it with `python scripts/provision_secrets.py {key}`.",
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
    """The secret: from the app tier when it speaks for the key (a value, or None when the key
    was disconnected there or can no longer be decrypted), else systemd credentials, else the
    writable store."""
    from app.secrets import vault

    held = vault.entry(key)
    if held.kind == "value":
        return held.value
    if held.kind != "none":
        return None
    directory = credentials_dir()
    if directory is not None:
        found = _read_file(directory / key)
        if found is not None:
            return found
    return _read_file(store_dir() / key)


def where(key: str) -> str:
    """Which tier holds this secret: "app" (stored from the Connections screen), "app-off"
    (disconnected there), "app-unreadable" (stored there, but this machine can no longer decrypt
    it), "systemd-credential", "file", or "" when none does. Used by the doctor, the installer
    and the Connections screen to show what is provisioned how; never the value."""
    from app.secrets import vault

    held = vault.entry(key).kind
    if held != "none":
        return {"value": "app", "off": "app-off"}.get(held, "app-unreadable")
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

    A key the app tier holds is written there instead, encrypted, so a renewal (the Instagram
    token's) lands where the next read looks; one disconnected there is refused.
    """
    from app.secrets import vault

    held = vault.entry(key).kind
    if held == "off":
        raise SecretDisconnected(key)
    if held != "none":
        vault.store(key, value)
        return
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
    """Delete a secret from the writable tier, and the app tier's say over it. Absent is not an
    error — keyring's delete is forgiving in the same way, and every caller here treats "gone"
    as the outcome it wanted."""
    from app.secrets import vault

    vault.clear(key)
    if provisioned_by_systemd(key):
        raise SecretShadowed(key)
    (store_dir() / key).unlink(missing_ok=True)
