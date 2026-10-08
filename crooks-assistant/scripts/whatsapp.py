"""WhatsApp on this server: what Meta says the number can do, and the two set-up steps Meta only
takes through its API.

    python scripts/whatsapp.py check       what Meta says: the number and its status, whether the
                                           token may read the account, where its webhooks go
    python scripts/whatsapp.py register    join the number to the Cloud API, with its six-digit
                                           two-step PIN (asked for, hidden)
    python scripts/whatsapp.py subscribe   have Meta send the account's webhooks to the app

Store the five keys first, on CLIVE's Connections screen (WhatsApp) or with
`python scripts/provision_secrets.py <key>`; docs/WHATSAPP.md says where each is. Nothing here sends a
message, and nothing prints a token, a secret or anybody's number but the business's own.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.clients import whatsapp  # noqa: E402
from app.messaging import whatsapp as channel  # noqa: E402


async def check() -> int:
    missing = whatsapp.missing()
    if missing:
        print("Not all of WhatsApp's keys are stored. Missing: " + ", ".join(missing))
        return 1
    routes = await channel.probe_routes()
    for route in routes:
        print(f"  {route.state:<9} {route.label}: {route.can}")
        if route.switch_on and route.state != "ready":
            print(f"            to do: {route.switch_on}")
    return 0 if all(r.state in ("ready", "not_used") for r in routes) else 1


async def register() -> int:
    print("The number's six-digit two-step PIN (hidden). If it has none yet, the six digits you type become it.")
    pin = getpass.getpass("PIN: ").strip()
    try:
        done = await whatsapp.register(pin)
    except whatsapp.WhatsAppError as exc:
        print(f"Not registered: {exc}")
        return 1
    print("Registered." if done else "Meta did not confirm the registration; run check.")
    return 0 if done else 1


async def subscribe() -> int:
    try:
        done = await whatsapp.subscribe()
        apps = await whatsapp.subscribed_apps()
    except whatsapp.WhatsAppError as exc:
        print(f"Not subscribed: {exc}")
        return 1
    print(f"{'Subscribed' if done else 'Meta did not confirm it'}. Meta sends this account's webhooks to: "
          f"{', '.join(apps) or 'no app'}.")
    return 0 if done else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("check", "register", "subscribe"))
    args = parser.parse_args(argv)
    return asyncio.run({"check": check, "register": register, "subscribe": subscribe}[args.command]())


if __name__ == "__main__":
    raise SystemExit(main())
