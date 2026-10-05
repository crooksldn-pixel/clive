"""Compare live rates for one prepared order, from every provider. READ-ONLY: quotes only.

    docker compose exec -T shipping python -m shipping.tools.compare_rates 2142

Uses the order exactly as Shipping prepared it (address, package, weight, customs lines) and
asks each provider for prices: no order, shipment or label is created, nothing is paid, and
nothing is saved. Prints each provider's services, the unified recommendation, and Easyship
diagnostics (shipping rules on, a smaller box, the account's courier services) to explain any
difference from prices seen in Easyship's dashboard. Prints no secrets or customer details.
"""

from __future__ import annotations

import sys
import time
from typing import Any

from shipping.app import build_service
from shipping.models import PackagePlan, Quote, Shipment
from shipping.money import Money
from shipping.providers.base import ProviderError
from shipping.settings import Settings


def find(svc, shop: str, number: str) -> Shipment:
    for s in svc.store.shipments(shop):
        if s.order_name.split("-")[-1].lstrip("#") == number.lstrip("#"):
            return s
    sys.exit(f"No prepared shipment for order {number}. Check Shopify for orders in the app first.")


def line(q: Quote, tag: str = "") -> str:
    days = f"{q.est_days_min or '?'}-{q.est_days_max}d" if q.est_days_max else "days ?"
    tracked = {True: "tracked", False: "UNTRACKED", None: "tracking ?"}[q.tracked]
    hand = q.handover or "handover ?"
    return f"  {tag:<12}{q.provider:<10} {q.title[:52]:<52} {str(q.amount):>8}  {days:<7} {tracked:<10} {hand}"


def easyship_raw(es, body: dict[str, Any]) -> list[tuple[str, str, float, Any]]:
    got = es._call("POST", "/rates", writes=False, json=body)
    out = []
    for r in got.get("rates") or []:
        cs = r.get("courier_service") or {}
        out.append(
            (cs.get("umbrella_name"), cs.get("name"), r.get("total_charge"), r.get("currency"))
        )
    return sorted(out, key=lambda x: (x[2] is None, x[2] or 0))


def main(number: str) -> None:
    settings = Settings()
    svc = build_service(settings)
    s = find(svc, settings.shop_domain, number)
    p = s.package
    print(
        f"Order {s.order_name} -> {s.destination.country} {s.destination.postcode.split(' ')[0]}*  status {s.status.value}"
    )
    if p is None or s.questions:
        sys.exit(f"Not ready: {[q.kind for q in s.questions] or 'no package'}")
    value = Money(
        minor=sum(ln.unit_value.minor * ln.quantity for ln in s.lines), currency=s.currency
    )
    print(
        f"Parcel {p.length_mm / 10:g}x{p.width_mm / 10:g}x{p.height_mm / 10:g} cm, {p.total_weight_g} g; "
        f"customs {sum(ln.quantity for ln in s.lines)} item(s) {value}; "
        f"HS {[ln.hs_code for ln in s.lines]} origin {[ln.origin_country for ln in s.lines]}"
    )
    providers = getattr(svc.provider, "providers", None) or [svc.provider]
    everything: list[Quote] = []
    for prov in providers:
        t0 = time.time()
        try:
            qs = prov.quotes(s)
        except ProviderError as exc:
            print(f"\n{prov.name}: UNAVAILABLE ({exc})")
            continue
        print(f"\n{prov.name}: {len(qs)} services ({time.time() - t0:.1f}s)")
        for q in sorted(qs, key=lambda q: q.amount.minor)[:15]:
            print(line(q))
        everything.extend(qs)
    if not everything:
        sys.exit("No rates from any provider.")
    probe = s.model_copy(deep=True)
    probe.rates = everything
    rec = svc.recommendation(probe)
    print("\nUnified (what the Shipping screen shows):")
    for tag, o in (
        ("Recommended", rec.recommended),
        ("Cheapest", rec.cheapest),
        ("Fastest", rec.fastest),
    ):
        if o:
            print(line(o.quote, tag) + f"\n  {'':<12}{o.reason}  [{o.paperwork.summary}]")
    es: Any = next((x for x in providers if x.name == "Easyship"), None)
    if es is None:
        return
    print("\nEasyship diagnostics (read-only rate requests):")
    try:
        body = es._rates_body(s)
        body["courier_settings"]["apply_shipping_rules"] = True
        print("  with the account's shipping rules applied:")
        for row in easyship_raw(es, body)[:6]:
            print("   ", row)
        small = s.model_copy(deep=True)
        small.package = PackagePlan(
            name="probe",
            length_mm=250,
            width_mm=180,
            height_mm=40,
            empty_weight_g=20,
            items_weight_g=min(p.items_weight_g, 480),
        )
        print("  same order in a 25x18x4 cm mailer (to test size sensitivity):")
        for row in easyship_raw(es, es._rates_body(small))[:6]:
            print("   ", row)
    except ProviderError as exc:
        print("  diagnostic rate request failed:", exc)
    try:
        got = es._call("GET", "/courier_services", writes=False, params={"per_page": "100"})
        names = [
            f"{c.get('umbrella_name')} / {c.get('name')}" for c in got.get("courier_services") or []
        ]
        hits = [
            n
            for n in names
            if any(
                k in n.lower()
                for k in ("royal mail", "channel", "guernsey", "jersey", "evri", "dpd")
            )
        ]
        print(f"  courier services on the account: {len(names)}; relevant: {hits[:20]}")
    except ProviderError as exc:
        print("  courier services list not available:", exc)
    try:
        print("  account credit:", es.account())
    except ProviderError as exc:
        print("  credit not available:", exc)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m shipping.tools.compare_rates <order number>")
    main(sys.argv[1])
