#!/usr/bin/env python3
"""Store a secret in the macOS Keychain. The Mac's command; on Linux see provision_secrets.py.

The value is typed at this prompt, never echoed, never written to a file, never passed as an
argument (which would put it in your shell history and in `ps`), and never printed back.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.secrets import keychain  # noqa: E402

HELP = {
    "claude_oauth_token": (
        "Optional. Normally not needed: the assistant uses the login you made with `claude` "
        "and `/login`. Only if you want a stored token instead: `claude setup-token`, paste it."
    ),
    "shopify_client_id": "Dev Dashboard app → Client ID (older docs call this the API key).",
    "shopify_client_secret": "Dev Dashboard app → Client secret.",
    "shopify_static_token": "Legacy shpat_… Admin API token. Fallback only — see the README's Shopify step.",
    "gmail_token": "Written by `make gmail`; you never type this one.",
    "elevenlabs_api_key": "ElevenLabs → Profile → API key. This is what hears you and what speaks (Derek).",
}


# The keys `make secrets` walks through, in the order the milestones need them. The two
# fallbacks are skipped unless asked for by name.
WALKTHROUGH = (
    "shopify_client_id",
    "shopify_client_secret",
    "elevenlabs_api_key",
)


def store_one(key: str) -> int:
    if keychain.present(key):
        print(f"\n{key} is already stored.")
        if input("Replace it? [y/N] ").strip().lower() != "y":
            print("Kept.")
            return 0
    print(f"\n{key}\n{HELP.get(key, '')}\nThe value is hidden as you type or paste it.\n")
    value = getpass.getpass("value: ").strip()
    if not value:
        print("Nothing entered — skipped.")
        return 1
    confirm = getpass.getpass("again:  ").strip()
    if value != confirm:
        print("The two entries do not match — skipped.")
        return 1
    keychain.set_secret(key, value)
    # Length only. Printing any part of a secret to a terminal defeats the point of getpass.
    print(f"Stored {key} ({len(value)} characters) in the macOS Keychain.")
    return 0


def main() -> int:
    # On Linux this would quietly work and do the wrong thing: keychain.set_secret writes to
    # the writable tier, so a static secret meant to be an encrypted, host-bound systemd
    # credential would land as a plain 0600 file instead — no error, no encryption at rest,
    # and nobody would know until a disk image walked. provision_secrets.py is the command
    # that knows which tier a secret belongs in, so send the operator there.
    if sys.platform.startswith("linux"):
        print("This is the macOS command. On this host use:\n")
        print("    python scripts/provision_secrets.py            what is stored, and where")
        print("    python scripts/provision_secrets.py --all      store what production needs\n")
        print("It picks the right tier per secret (encrypted credential vs writable file);")
        print("this one would store every secret as a plain file. See docs/DEPLOY_LINUX.md.")
        return 1

    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print("usage: python scripts/set_secrets.py --all | <key> [--delete]\n\nKeys:")
        for key in keychain.KNOWN_KEYS:
            mark = "stored" if keychain.present(key) else "not stored"
            print(f"  {key:<24} [{mark}]  {HELP.get(key, '')}")
        return 0

    if sys.argv[1] == "--all":
        print("Storing the secrets the assistant needs. Press Enter with nothing typed to skip one.")
        failures = 0
        for key in WALKTHROUGH:
            failures += store_one(key)
        print("\nDone." if not failures else f"\nDone, {failures} skipped — run `make secrets` again for those.")
        return 0

    key = sys.argv[1]
    if key not in keychain.KNOWN_KEYS:
        print(f"Unknown key {key!r}. Known: {', '.join(keychain.KNOWN_KEYS)}")
        return 1

    if "--delete" in sys.argv:
        keychain.delete(key)
        print(f"Deleted {key} from the {keychain.SERVICE} keychain entry.")
        return 0

    return store_one(key)


if __name__ == "__main__":
    raise SystemExit(main())
