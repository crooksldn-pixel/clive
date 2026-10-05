"""Every open international order through preparation and Check price. Buys nothing.

    docker compose exec -T shipping python -m shipping.tools.dry_run
    docker compose exec -T shipping python -m shipping.tools.dry_run --probe-easyship

For each open international order: refresh it from Shopify (what the app's own sync does),
show its status and any genuine questions, the chosen service, and run Check price (the
provider's exact price; for Parcel2Go its full order check). No label is bought: Check price
never buys, and buying needs the order in SHIPPING_AUTHORISED_ORDERS and a click in the app.

--probe-easyship also asks Easyship to accept the booking itself, where Easyship validates
more than it does for a price: it creates the shipment exactly as Buy would, WITHOUT a label
(no money moves), reports Easyship's verdict, and deletes that shipment again. Prints no
customer details beyond the country and postcode area.
"""

from __future__ import annotations

import sys
from typing import Any

from shipping import contacts
from shipping.app import build_service
from shipping.models import Shipment
from shipping.providers.base import ProviderError, ProviderRefused
from shipping.purchase import ActionError
from shipping.service import PRE_PURCHASE
from shipping.settings import Settings
from shipping.shopify import ShopifyError


def area(s: Shipment) -> str:
    return f"{s.destination.country} {(s.destination.postcode or '').split(' ')[0]}*"


def probe(es: Any, s: Shipment) -> str:
    """Create the Easyship shipment Buy would create, without a label, then delete it."""
    try:
        order = es.create_order(s, s.quote, f"dry-run {s.order_name}")
    except ProviderRefused as exc:
        return f"REFUSED by Easyship: {exc}"
    except ProviderError as exc:
        return f"no clear answer ({exc}); check Easyship for a draft {s.order_name} shipment"
    try:
        es.discard(order.ref)
        gone = "deleted again"
    except ProviderError as exc:
        gone = f"NOT deleted ({exc}); delete draft {order.ref[3:]} in Easyship (no label)"
    return f"accepted at {order.amount_minor / 100:.2f} {order.currency}, no label; {gone}"


def main(argv: list[str]) -> int:
    settings = Settings()
    svc = build_service(settings)
    shop = settings.shop_domain
    found = svc.sync(shop)
    providers = getattr(svc.provider, "providers", None) or [svc.provider]
    es: Any = next((p for p in providers if p.name == "Easyship"), None)
    want_probe = "--probe-easyship" in argv and es is not None
    cfg = svc.store.config(shop)
    open_ = sorted(
        svc.store.shipments(shop, [x.value for x in PRE_PURCHASE]), key=lambda s: s.order_name
    )
    print(f"Open international orders: {len(open_)} (Shopify sync: {found})")
    blockers = 0
    for s in open_:
        print(f"\n{s.order_name}  {area(s)}  {s.status.value}")
        for q in s.questions:
            blockers += 1
            print(f"  BLOCKER [{q.kind}] {q.text}")
        if s.quote is None:
            continue
        q = s.quote
        tracked = {True: "tracked", False: "untracked", None: "tracking ?"}[q.tracked]
        print(f"  service  {q.provider} · {q.title} · {q.amount} · {tracked}")
        note = contacts.note(contacts.recipient(s.destination, cfg.origin)[1])
        if note:
            print(f"  note     {note}")
        try:
            pv = svc.preview(shop, s.id)
            price = pv["money"]["shipping_minor"] / 100
            print(f"  Check price  OK: {price:.2f} {pv['money']['currency']} (nothing bought)")
        except (ActionError, ProviderError, ShopifyError) as exc:
            blockers += 1
            print(f"  Check price  BLOCKER: {exc}")
            continue
        if want_probe and q.provider == "Easyship":
            fresh = svc.store.get(shop, s.id)
            if fresh is not None and fresh.quote is not None:
                verdict = probe(es, fresh)
                if verdict.startswith("REFUSED"):
                    blockers += 1
                print(f"  Easyship booking  {verdict}")
    print(f"\nGenuine blockers: {blockers}. Nothing was bought.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
