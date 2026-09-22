#!/usr/bin/env python3
"""Store this host's secrets — the Linux half of `make secrets`.

The Mac has a Keychain and `scripts/set_secrets.py` puts secrets in it. This machine has no
Keychain, so a secret goes to one of the two tiers described in app/secrets/linux_store.py,
and which one it goes to is decided by whether the running application ever writes it back:

    static   — encrypted at rest with `systemd-creds encrypt`, mounted read-only for the
               service alone. The ElevenLabs key, the Shopify client id and secret.
    mutable  — a root-only 0600 file under /etc/crooks-os/secrets. The Gmail token, which
               google-auth rewrites after every refresh, and the media signing key, which is
               generated here once and must then survive every restart.

    python scripts/provision_secrets.py                    what is stored, and where
    python scripts/provision_secrets.py elevenlabs_api_key store one (typed, never echoed)
    python scripts/provision_secrets.py <key> --plain      force the writable tier
    python scripts/provision_secrets.py media_signing_key --generate
    python scripts/provision_secrets.py <key> --remove

The value is typed at this prompt, never echoed, never written to the repository, never
passed as an argument (which would put it in the shell history and in `ps`), and never
printed back. This command prints which tier holds a secret and never its contents.
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets as stdlib_secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.secrets import keychain, linux_store  # noqa: E402

# Where the encrypted blobs live. systemd decrypts them into the service's own credentials
# directory at start; they are host-bound, so a copy taken off this machine is inert.
CRED_DIR = Path(os.environ.get("CROOKS_CRED_DIR") or "/etc/crooks-os/credentials")

HELP = {
    "claude_oauth_token": (
        "Optional, and normally not needed: the assistant uses the login already made with "
        "`claude`. Only if you want a stored token instead: `claude setup-token`, paste it."
    ),
    "shopify_client_id": "Dev Dashboard app -> Client ID (older docs call this the API key).",
    "shopify_client_secret": "Dev Dashboard app -> Client secret.",
    "shopify_static_token": "Legacy shpat_ Admin API token. Fallback only.",
    "gmail_token": "Written by `make gmail`; you never type this one.",
    "elevenlabs_api_key": "ElevenLabs -> Profile -> API key. This hears you and speaks (Derek).",
    "media_signing_key": "Generated here, not typed: use --generate.",
}

# What `make secrets` walks through on this host, in the order production needs them.
WALKTHROUGH = ("shopify_client_id", "shopify_client_secret", "elevenlabs_api_key")


def have_systemd_creds() -> bool:
    return shutil.which("systemd-creds") is not None


def encrypted_path(key: str) -> Path:
    return CRED_DIR / f"{key}.cred"


def provisioned_encrypted(key: str) -> bool:
    return encrypted_path(key).is_file()


def encrypt(key: str, value: str) -> None:
    """Encrypt a static secret to a host-bound blob systemd can read and nothing else can.

    The value goes in on stdin, so it never appears in the process table. `--name` binds the
    blob to the credential name: systemd refuses to load it under any other, which is what
    stops a swapped file handing the ElevenLabs key to the Shopify client.
    """
    CRED_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = encrypted_path(key)
    completed = subprocess.run(
        ["systemd-creds", "encrypt", f"--name={key}", "-", str(target)],
        input=value, text=True, capture_output=True, timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip()[:300] or "systemd-creds failed")
    target.chmod(0o600)


def store_one(key: str, *, plain: bool) -> int:
    tier_is_static = key in linux_store.STATIC_KEYS and not plain
    if tier_is_static and not have_systemd_creds():
        print("  systemd-creds is not available; storing in the writable tier instead.")
        tier_is_static = False

    existing = where(key)
    if existing:
        print(f"\n{key} is already stored ({existing}).")
        if input("Replace it? [y/N] ").strip().lower() != "y":
            print("Kept.")
            return 0

    print(f"\n{key}\n{HELP.get(key, '')}\nThe value is hidden as you type or paste it.\n")
    value = getpass.getpass("value: ").strip()
    if not value:
        print("Nothing entered — skipped.")
        return 1

    if tier_is_static:
        encrypt(key, value)
        print(f"  stored  {key} -> encrypted credential ({encrypted_path(key)})")
        print("          it reaches the service on its next restart.")
    else:
        keychain.set_secret(key, value)
        print(f"  stored  {key} -> {linux_store.store_dir() / key} (0600)")
    return 0


def generate_media_key() -> int:
    """The media signing key, made once here and kept. app/media.py would generate one itself
    if it found none, but a key made at boot is a key that changes at every boot — which
    invalidates every signed image path the tablet has cached. Made here, it persists."""
    key = "media_signing_key"
    if keychain.present(key):
        print(f"{key} is already stored ({where(key)}). Leaving it alone — replacing it")
        print("would invalidate every image path the tablet has cached.")
        return 0
    keychain.set_secret(key, stdlib_secrets.token_hex(32))
    print(f"  stored  {key} -> {linux_store.store_dir() / key} (0600, generated here)")
    return 0


def remove_one(key: str) -> int:
    if provisioned_encrypted(key):
        encrypted_path(key).unlink()
        print(f"  removed {key} (encrypted credential; restart the service to drop it)")
        return 0
    keychain.delete(key)
    print(f"  removed {key}")
    return 0


def where(key: str) -> str:
    """Which tier holds this secret, as a phrase for a person. Never the value.

    The encrypted blob is reported even when this process cannot see the decrypted credential:
    only the service gets a credentials directory, so from a shell a provisioned static secret
    is otherwise invisible and would read as missing.
    """
    live = keychain.where(key)
    if live == "systemd-credential":
        return "encrypted credential (loaded)"
    if provisioned_encrypted(key):
        return "encrypted credential (on disk; the service sees it)"
    if live == "file":
        return "file, 0600"
    return ""


def status() -> int:
    print("\nCROOKS Assistant — secrets on this host\n" + "-" * 74)
    print(f"  encrypted credentials  {CRED_DIR}")
    print(f"  writable store         {linux_store.store_dir()}")
    print("-" * 74)
    for key in keychain.KNOWN_KEYS:
        tier = "static " if key in linux_store.STATIC_KEYS else "mutable"
        held = where(key)
        print(f"  [{'ok  ' if held else '--  '}] {tier}  {key:<22} {held or 'not stored'}")
    print("-" * 74)
    print("  Store one with: python scripts/provision_secrets.py <key>")
    print("  A static secret reaches the service on its next restart.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("key", nargs="?", help="which secret; omit for the status of every one")
    parser.add_argument("--all", action="store_true", help="walk through the ones production needs")
    parser.add_argument("--plain", action="store_true", help="force the writable tier, not an encrypted credential")
    parser.add_argument("--generate", action="store_true", help="generate the value (media_signing_key only)")
    parser.add_argument("--remove", action="store_true", help="delete it from this host")
    args = parser.parse_args(argv)

    if sys.platform == "darwin":
        print("This is the Linux provisioning command. On the Mac use: make secrets")
        return 1

    if args.all:
        for key in WALKTHROUGH:
            store_one(key, plain=args.plain)
        generate_media_key()
        return status()
    if not args.key:
        return status()
    if args.key not in keychain.KNOWN_KEYS:
        print(f"Unknown secret {args.key!r}. Known: {', '.join(keychain.KNOWN_KEYS)}")
        return 2
    if args.remove:
        return remove_one(args.key)
    if args.generate:
        if args.key != "media_signing_key":
            print("--generate is only for media_signing_key; every other secret is issued elsewhere.")
            return 2
        return generate_media_key()
    return store_one(args.key, plain=args.plain)


if __name__ == "__main__":
    raise SystemExit(main())
