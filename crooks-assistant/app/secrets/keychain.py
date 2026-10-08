"""Thin secret-store wrapper. Every secret in this project is read through here and nowhere else.

Secrets are written once by scripts/set_secrets.py at an interactive local prompt (or, on
Linux, provisioned by scripts/provision_secrets.py). They are never written to a file the
repository can see, never committed, never echoed, and never included in a log line.

Two backends, chosen by platform and by nothing else:

  macOS   the login Keychain, through `keyring`. Unchanged, and the only backend the Mac has
          ever used.
  Linux   app/secrets/linux_store.py — systemd credentials for static secrets, a root-only
          0600 directory for the ones the application itself rewrites, and, asked first, the
          keys the owner stores from the Connections screen, encrypted on this machine
          (app/secrets/vault.py).

The public surface is the same on both: get, get_optional, set_secret, delete, present. The
one documented difference is that a Linux write to a key systemd provisions read-only raises
SecretShadowed rather than writing somewhere the next read would ignore.
"""

from __future__ import annotations

import os
import sys

# Pure stdlib inside, so importing it on macOS costs nothing and the exception it defines can
# be caught by name from either platform.
from app.secrets.linux_store import SecretDisconnected, SecretShadowed

SERVICE = "crooks-assistant"

__all__ = [
    "SERVICE", "KNOWN_KEYS", "SecretMissing", "KeychainUnavailable", "SecretShadowed", "SecretDisconnected",
    "get", "get_optional", "set_secret", "delete", "present", "where",
]

# The complete set of secrets this application will ever hold. Anything not on this list
# is a bug or a mistake, so lookups are validated against it.
KNOWN_KEYS = (
    "claude_oauth_token",
    "shopify_client_id",
    "shopify_client_secret",
    "shopify_static_token",  # legacy shpat_ fallback (M6 failure path only)
    "gmail_token",  # the authorised-user JSON (refresh token inside); token.json is the fallback
    # One key, two jobs: Scribe hears the owner and the voice answers him. Absent, the Mac
    # listens with whisper.cpp and the tablet answers in its own Android voice.
    "elevenlabs_api_key",
    # Signs the image paths the tablet is given (app/media.py). Read and written there from
    # the start but never listed here, so every lookup raised "unknown key", every store was
    # swallowed by that module's except, and the key was silently regenerated per boot on
    # BOTH platforms — which invalidated the tablet's thumbnail cache on every restart.
    # Listed now, so app/media.py does what its own docstring always said it did.
    "media_signing_key",
    # CLIVE's key to the engineering loop's inbox (app/engineering_bridge/github.py): a
    # fine-grained GitHub token for the clive repository, Contents read and write. Read by the
    # bridge from the start but never listed here, so every lookup raised "unknown key", the
    # bridge answered "not connected" whatever was provisioned, and the provisioning scripts
    # refused to store it at all.
    "github_engineering_inbox_token",
    # The key the server's own `make test-session-*` commands carry (app/local_cli.py): made by
    # the backend the first time it starts, read by the command line, opening the three
    # test-session routes and nothing else (the 2026-09-27 deploy review, round 6, F-05A).
    "local_cli_key",
    # Finds videos for the owner's screens (app/clients/youtube.py): a YouTube Data API v3 key,
    # read-only by what that API is. Absent, a YouTube link still plays; only search needs it.
    "youtube_api_key",
    # Tracks parcels by the carrier's own scans (app/clients/ship24.py): a Ship24 Tracking API key.
    # Absent, CLIVE says parcel tracking is not connected; nothing else needs it.
    "ship24_api_key",
    # CROOKS Returns, the owner's own returns service (app/clients/crooks_returns.py): the keys its
    # .env lists for CLIVE (RETURNS_CLIVE_READ_KEYS, RETURNS_CLIVE_WRITE_KEYS). The read key reads
    # returns; the write key is sent only with an action the owner approved on its card.
    "crooks_returns_read_key",
    "crooks_returns_write_key",
    # [messaging] George's own WeCom app (app/clients/wecom.py): its CorpID and AgentID (not secret,
    # shown on the Connections card), the app's Secret, a WeChat customer-service Secret when 微信客服
    # has one of its own, and the callback Token and EncodingAESKey that sign and seal what WeCom
    # sends to /hooks/wecom. Read at each call; tokens minted from the Secrets are held in memory only.
    "wecom_corp_id",
    "wecom_agent_id",
    "wecom_app_secret",
    "wecom_kf_secret",
    "wecom_callback_token",
    "wecom_encoding_aes_key",
    # CLIVE Shipping, the owner's international shipping service (app/clients/crooks_shipping.py):
    # the keys its .env lists for CLIVE (SHIPPING_CLIVE_READ_KEYS, SHIPPING_CLIVE_WRITE_KEYS). The
    # read key reads orders, prices and tracking; the write key is sent only with a label bought or
    # printed on the owner's card. No PrintNode key: printing is the service's own.
    "crooks_shipping_read_key",
    "crooks_shipping_write_key",
    # Reads the CROOKS Instagram account's messages and comments (app/clients/instagram.py): a
    # long-lived Instagram User access token, renewed by the application before its 60 days run
    # out. The app id and secret are the Meta app's, kept for exchanging a new short-lived token
    # by hand (scripts/instagram.py); nothing reads them on a normal call.
    "instagram_access_token",
    "instagram_app_id",
    "instagram_app_secret",
)


def _on_linux() -> bool:
    """Which backend answers. Deliberately the platform and not "is keyring working": on the
    Mac, a keyring that cannot be reached means the process is outside the login session, and
    that must keep raising rather than quietly falling through to a file."""
    return sys.platform.startswith("linux")


class SecretMissing(RuntimeError):
    """Raised when a required secret has not been stored."""

    def __init__(self, key: str) -> None:
        how = (
            f"is not provisioned for this host. Store it with: "
            f"python scripts/provision_secrets.py {key}"
            if _on_linux()
            else f"is not in the {SERVICE} keychain entry. "
            f"Store it with: python scripts/set_secrets.py {key}"
        )
        super().__init__(f"Secret {key!r} {how}")
        self.key = key


def _validate(key: str) -> None:
    if key not in KNOWN_KEYS:
        raise ValueError(f"Unknown secret key {key!r}. Known keys: {', '.join(KNOWN_KEYS)}")


class KeychainUnavailable(SecretMissing):
    """No usable secret store.

    On macOS: a process running outside the login session (a system LaunchDaemon, an SSH
    shell, a LaunchAgent that fires before the user has logged in). A LaunchAgent in
    ~/Library/LaunchAgents runs inside the login session and normally reaches the login
    Keychain. On Linux: the secret directory is present but unreadable to this process, which
    is a permissions problem and not an absent secret. Treated as "secret missing" so callers
    fall back or fail with a message that names the real cause."""

    def __init__(self, key: str, cause: Exception | str) -> None:
        detail = cause if isinstance(cause, str) else f"{type(cause).__name__}: {cause}"
        explanation = (
            "On Linux this means the secret directory is present but unreadable to this "
            "process — check its owner and mode (it should be root-owned, 0700)."
            if _on_linux()
            else "On macOS this usually means the process is running outside your login "
            "session (SSH, a system daemon, or before login)."
        )
        RuntimeError.__init__(
            self,
            f"Secret {key!r} could not be read: the secret store is unavailable to this "
            f"process ({detail}). {explanation}",
        )
        self.key = key


def _linux_guard(key: str) -> None:
    """Turn an unreadable store into KeychainUnavailable rather than a bare "missing", so a
    permissions mistake during installation is diagnosable from the message alone."""
    from app.secrets import linux_store

    directory = linux_store.store_dir()
    if directory.exists() and not os.access(directory, os.R_OK | os.X_OK):
        raise KeychainUnavailable(key, f"{directory} is not readable by this process")


def get(key: str) -> str:
    """Return a secret, raising SecretMissing if absent. Never logs the value."""
    _validate(key)
    if _on_linux():
        from app.secrets import linux_store

        value = linux_store.read(key)
        if not value:
            _linux_guard(key)
            raise SecretMissing(key)
        return value

    import keyring

    try:
        value = keyring.get_password(SERVICE, key)
    except Exception as exc:  # noqa: BLE001 — every keyring backend raises its own type
        raise KeychainUnavailable(key, exc) from exc
    if not value:
        raise SecretMissing(key)
    return value


def get_optional(key: str) -> str | None:
    """Return a secret or None. Used where a credential is a documented fallback."""
    try:
        return get(key)
    except SecretMissing:
        return None


def set_secret(key: str, value: str) -> None:
    _validate(key)
    if not value.strip():
        raise ValueError("Refusing to store an empty secret.")
    if _on_linux():
        from app.secrets import linux_store

        linux_store.write(key, value)
        return

    import keyring

    keyring.set_password(SERVICE, key, value)


def delete(key: str) -> None:
    _validate(key)
    if _on_linux():
        from app.secrets import linux_store

        linux_store.remove(key)
        return

    import keyring

    try:
        keyring.delete_password(SERVICE, key)
    except Exception:  # noqa: BLE001 — keyring raises backend-specific errors for "absent"
        pass


def present(key: str) -> bool:
    """True if the secret exists. Deliberately returns a bool, never the value."""
    return get_optional(key) is not None


def where(key: str) -> str:
    """Which store holds this secret, for the doctor, the installer and the Connections screen
    to report. Never the value: "keychain", "app", "app-off", "app-unreadable",
    "systemd-credential", "file", or "" when it is not stored at all (linux_store.where)."""
    _validate(key)
    if _on_linux():
        from app.secrets import linux_store

        return linux_store.where(key)
    return "keychain" if present(key) else ""
