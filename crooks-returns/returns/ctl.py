"""Staff tool for the server: the same actions as the admin screen and CLIVE, from the command
line. Run inside the container:

    docker compose exec returns returns-ctl check
    docker compose exec returns returns-ctl labels E1 6AN    (label prices near a postcode)
    docker compose exec returns returns-ctl list
    docker compose exec returns returns-ctl show ret_1a2b3c4d5e
    docker compose exec returns returns-ctl approve ret_1a2b3c4d5e self_ship
    docker compose exec returns returns-ctl receive ret_1a2b3c4d5e

Every action prints what it will do and asks before doing it (add --yes to skip the question).
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys

from returns.app import build_service
from returns.models import Return
from returns.service import ActionError, ReturnsService
from returns.settings import get_settings

ACTIONS = {
    "approve": "approve RETURN_ID [label_now|self_ship|label_later|no_return]",
    "decline": "decline RETURN_ID [reason words...]",
    "label": "label RETURN_ID [TRACKING_NUMBER]  (no number: buy a Click & Drop label)",
    "receive": "receive RETURN_ID [ok|damaged|worn|missing]",
    "complete": "complete RETURN_ID  (process a return that arrived not as expected)",
    "cancel": "cancel RETURN_ID",
    "note": "note RETURN_ID words...",
}


def line(svc: ReturnsService, ret: Return) -> str:
    attention = ", ".join(svc.staff(ret)["attention"])
    flag = f"  [{attention}]" if attention else ""
    return f"{ret.id}  {ret.status.value:<18} {svc.summary(ret)}{flag}"


def params_for(action: str, extra: list[str]) -> dict:
    if action == "approve" and extra:
        return {"postage_mode": extra[0]}
    if action == "decline":
        return {"reason": " ".join(extra)}
    if action == "label" and extra:
        return {"tracking": extra[0]}
    if action == "receive":
        return {"condition": extra[0] if extra else "ok"}
    if action == "cancel":
        return {"reason": " ".join(extra)}
    if action == "note":
        return {"text": " ".join(extra)}
    return {}


def check(svc: ReturnsService) -> int:
    """Read-only: is everything connected and set the way the returns need it?"""
    group = None
    results = svc.checks()
    for c in results:
        if c["group"] != group:
            group = c["group"]
            print(group)
        print(f"  {c['state'].upper():<4} {c['text']}")
    problems = sum(c["state"] == "fix" for c in results)
    print("\n" + ("Ready." if not problems else f"{problems} thing(s) to fix."))
    return 1 if problems else 0


def labels(svc: ReturnsService, postcode: str) -> int:
    """Read-only: what a free return label would be from this postcode. Buys nothing."""
    ok, why = svc.labels.available()
    name = getattr(svc.labels, "name", "Labels")
    print(f"{name}: " + ("connected" if ok else f"off ({why})"))
    if not ok:
        return 1
    balance = getattr(svc.labels, "balance_pence", lambda: None)()
    if balance is not None:
        print(f"PrePay balance: £{balance / 100:.2f}")
    options_for = getattr(svc.labels, "options", None)
    if not options_for or not postcode:
        print("Give a postcode to see the drop-off options, e.g. returns-ctl labels E1 6AN")
        return 0
    try:
        found = options_for(postcode)
    except Exception as exc:  # noqa: BLE001 - show the reason, whatever it is
        print(f"Quote failed: {exc}")
        return 1
    if not found:
        print(f"No drop-off service near {postcode}.")
        return 1
    for o in found:
        how = "prints a label" if o.printer else "no printer, QR code"
        print(f"  {o.courier_name:<10} {o.service_name:<28} £{o.price_pence / 100:.2f}  ({how})")
        for shop in o.shops:
            far = f"{shop.distance_m / 1609.34:.1f} mi" if shop.distance_m is not None else ""
            print(f"      {far:>7}  {shop.name}, {shop.postcode}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="returns-ctl", description="CROOKS Returns staff tool")
    parser.add_argument(
        "command", help="check, list, show, labels POSTCODE, or an action: " + ", ".join(ACTIONS)
    )
    parser.add_argument("args", nargs="*")
    parser.add_argument("--all", action="store_true", help="list: include finished returns")
    parser.add_argument("--yes", action="store_true", help="act without asking")
    parser.add_argument("--as", dest="actor", default="staff", help="who is acting (timeline)")
    ns = parser.parse_args(argv)
    settings = get_settings()
    svc = build_service(settings)
    if ns.command == "check":
        return check(svc)

    if ns.command == "labels":
        return labels(svc, " ".join(ns.args))

    if ns.command == "list":
        rows = svc.store.search(open_only=not ns.all, limit=200)
        print("\n".join(line(svc, r) for r in rows) or "No returns.")
        return 0
    if ns.command == "show":
        ret = svc.store.get(ns.args[0]) if ns.args else None
        if ret is None:
            print("Return not found.")
            return 1
        print(json.dumps(svc.staff(ret), indent=2, default=str))
        return 0
    if ns.command not in ACTIONS or not ns.args:
        parser.print_usage()
        print("\n".join(f"  returns-ctl {usage}" for usage in ACTIONS.values()))
        return 2

    return_id, extra = ns.args[0], ns.args[1:]
    params = params_for(ns.command, extra)
    try:
        preview = svc.preview(return_id, ns.command, params)
    except ActionError as exc:
        print(f"Can't {ns.command}: {exc}")
        return 1
    print("This will:")
    for step in preview["will"]:
        print(f"  - {step}")
    if not ns.yes and input("Go ahead? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Nothing changed.")
        return 0
    try:
        out = svc.execute(return_id, ns.command, params, f"{ns.actor} (ctl)", secrets.token_hex(8))
    except ActionError as exc:
        print(f"Refused: {exc}")
        return 1
    print(
        f"{out['from']} -> {out['status']}"
        + ("  (confirmed in Shopify)" if out["verified"] else "")
    )
    if out.get("error"):
        print(f"Problem: {out['error']}")
    print(line(svc, out["return_doc"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
