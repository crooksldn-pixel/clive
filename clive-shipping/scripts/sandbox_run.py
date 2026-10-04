"""End-to-end against the real Parcel2Go SANDBOX (fake money), with a simulated Shopify.

    SHIPPING_P2G_BASE_URL=https://sandbox.parcel2go.com SHIPPING_P2G_CLIENT_ID=... \
    SHIPPING_P2G_CLIENT_SECRET=... python scripts/sandbox_run.py OUT_DIR

Refuses to run against anything but the sandbox.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.models import Address
from shipping.providers.parcel2go import Parcel2Go, balance
from shipping.purchase import Purchases
from shipping.service import ShippingService
from shipping.store import Store

SHOP = "crooks-sandbox.myshopify.com"


def main(out_dir: str) -> None:
    base = os.environ["SHIPPING_P2G_BASE_URL"]
    if "sandbox" not in base:
        sys.exit("sandbox_run only talks to the Parcel2Go sandbox.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    store = Store(str(Path(tempfile.mkdtemp()) / "s.sqlite3"))
    p2g = Parcel2Go(
        base,
        os.environ["SHIPPING_P2G_CLIENT_ID"],
        os.environ["SHIPPING_P2G_CLIENT_SECRET"],
        config=store.config,
    )
    shopify = FakeShopify()
    svc = ShippingService(store, shopify, p2g, Purchases(store, p2g))
    before = balance(p2g)

    shopify.add(fo(2145, [tee_line(qty=2)]))
    svc.sync(SHOP)
    cfg = store.config(SHOP)
    cfg.origin = Address(
        name="CROOKS LDN",
        company="CROOKS LDN",
        line1="Unit M (Oairo UK Offices)",
        line2="Bourne End Business Park",
        city="Bourne End",
        postcode="SL8 5AS",
        country="GB",
        phone="07700900000",
        email="team@crooksldn.com",
    )
    store.save_config(cfg)
    (s,) = store.shipments(SHOP)
    print("1. discovered", s.order_name, "->", s.status.value, [q.kind for q in s.questions])
    svc.answer(
        SHOP,
        s.id,
        "package",
        "first_package",
        {
            "name": "Sandbox mailer",
            "length_cm": 38,
            "width_cm": 28,
            "height_cm": 8,
            "empty_weight_g": 40,
        },
        "george",
    )
    svc.answer(
        SHOP,
        s.id,
        "customs",
        "gid://shopify/Product/tee",
        {"hs_code": "6109100010", "description": "Men's cotton T-shirt"},
        "george",
    )
    s = svc.answer(SHOP, s.id, "origin", "gid://shopify/Product/tee", {"country": "PT"}, "george")
    print(
        "2. answered once ->",
        s.status.value,
        "|",
        s.quote.title,
        s.quote.amount,
        f"~{s.quote.est_days_max}d",
    )
    pv = svc.preview(SHOP, s.id)
    print("3. preview:")
    for line in pv["will"]:
        print("     -", line)
    result = svc.buy(SHOP, s.id, pv["basis"], "george", "sandbox-k1")
    s = result["shipment"]
    print(
        "4. buy ->",
        s.status.value,
        "| charged",
        result["charged"],
        "|",
        s.label.amount,
        "| tracking",
        s.label.tracking_number,
        "| ref",
        s.label.provider_ref.split(":")[1],
    )
    for kind, art in s.label.artifacts.items():
        _, _, body = store.get_artifact(SHOP, art)
        (out / f"{s.order_name}-{kind}.pdf").write_bytes(body)
    print(
        "   Shopify fulfillment:",
        shopify.fulfillments[-1]["company"],
        shopify.fulfillments[-1]["number"],
        "| verified",
        s.timeline[-1].verified,
    )
    again = svc.buy(SHOP, s.id, pv["basis"], "george", "sandbox-k1")
    print("5. same key again -> replayed", again["replayed"], "| status", again["status"])

    shopify.add(fo(2151, [tee_line(n=7, qty=2)]))
    svc.sync(SHOP)
    second = next(x for x in store.shipments(SHOP) if x.order_name == "CROOKS-2151")
    print(
        "6. second identical order ->",
        second.status.value,
        "| questions",
        [q.kind for q in second.questions],
        "| package",
        second.package.source,
    )
    after = balance(p2g)
    print("7. sandbox PrePay", before, "->", after)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sandbox-out")
