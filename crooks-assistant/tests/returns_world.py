"""CROOKS Returns beside the customers' fixture shop (tests/customers_world.py), for a real browser.

The returns are made by the service's OWN code (tests/returns_service.py: its workflow, its fake
Shopify, its simulated Parcel2Go), on orders that mirror the customers' shop: the same numbers, the
same people, the same products. Every return got where it is the way a real one would: asked for
through the service's own submit, approved, labelled, posted, delivered or received by its own
actions and its Parcel2Go tracking webhook, each on its own day. Nothing about a return is written
by hand here. Every name, order and number is invented (the customers' world's own).

    Mia Jones      #2205  Convict T-Shirt too small, swap for M          asked yesterday: to approve
    Alicia Grant   #2201  Loopback Hoodie, store credit, Evri label     delivered back today: not checked
    Alison Grey    #2202  Loopback Hoodie faulty, refund, posted herself received today, damaged: a decision
    Elise Hart     #2190  Loopback Hoodie faulty, Evri label bought      never posted, 17 days: to cancel
    Alicia Grant   #2150  Convict T-Shirt too small, swapped up         completed 20 days ago

Not a test module: tests/test_returns_browser.py serves it.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from tests import customers_world as cw

# The customers' orders the returns are on, and the days ago each shipped (so a return on one is
# never on an order that has not gone out).
SHIPPED = {2201: 6, 2202: 7, 2190: 20, 2205: 11, 2150: 39}


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def at(self, days_ago: float) -> None:
        self.now = datetime.now(UTC) - timedelta(days=days_ago)


def ship_the_orders() -> list[tuple]:
    """The customers' world with these orders shipped. Returns what to put back."""
    before = list(cw.ORDERS)
    cw.ORDERS[:] = [(n, c, d, items, pc, town, {**extra, "shipped": SHIPPED[n]} if n in SHIPPED and not extra.get("shipped") else extra)
                    for n, c, d, items, pc, town, extra in cw.ORDERS]
    return before


def _variant(s, product: str, colour: str, size: str, price: int, sku: str):
    return s.models.Variant(id=f"gid://shopify/ProductVariant/{sku}", title=f"{colour} / {size}", sku=sku, price_pence=price,
                            available=True, options={"Colour": colour, "Size": size})


def _order(s, number: int, *, title: str, colour: str, size: str, price: int, sku_root: str, shipped_days: int) -> Any:
    _n, customer, days, _items, postcode, town, _extra = next(o for o in cw.ORDERS if o[0] == number)
    person = cw.PEOPLE[customer]
    first, _, last = person["name"].partition(" ")
    sizes = ["S", "M", "L"]
    siblings = [_variant(s, title, colour, z, price, f"{sku_root}-{z}") for z in sizes]
    mine = next(v for v in siblings if v.options["Size"] == size)
    now = datetime.now(UTC)
    line = s.models.OrderLine(
        fulfillment_line_item_id=f"gid://shopify/FulfillmentLineItem/{number}1", line_item_id=f"gid://shopify/LineItem/{number}0",
        title=title, variant_title=mine.title, sku=mine.sku, variant_id=mine.id, variant_price_pence=price,
        product_id=f"gid://shopify/Product/{sku_root}", ordered_qty=1, returnable_qty=1, unit_paid_pence=price,
        siblings=siblings, options=dict(mine.options), size_option="Size", sizes=sizes)
    return s.models.Order(
        id=f"gid://shopify/Order/{number}", name=f"CROOKS-{number}", created_at=now - timedelta(days=days),
        email=person["email"], phone=f"+44 7700 900{number % 1000:03d}",   # Ofcom's numbers for drama: never anyone's
        customer_id=customer, customer_name=person["name"], customer_email=person["email"],
        shipping_zip=postcode, shipping_pence=500,
        shipping_address={"firstName": first, "lastName": last, "address1": "1 Example Street", "city": town, "zip": postcode,
                          "countryCodeV2": "GB"},
        fulfilled_at=now - timedelta(days=shipped_days), delivered_at=now - timedelta(days=shipped_days - 1), lines=[line])


def _webhook(app_client, line_id: str, stage: str, hook_id: str, secret: str) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    message = f"{hook_id}:{stamp.replace('T', ' ')}:Tracking"
    body = {"Id": hook_id, "Timestamp": stamp, "Type": "Tracking",
            "Payload": {"OrderLineId": int(line_id), "TrackingStage": stage, "StatusDescription": stage},
            "Signature": hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()}
    assert app_client.post("/webhooks/parcel2go", json=body).status_code == 200


def build(loaded: SimpleNamespace, folder: Path, *, read_key: str, write_key: str) -> SimpleNamespace:
    """The service with its five returns, and its app for CLIVE's client to reach."""
    from fastapi.testclient import TestClient

    from tests import returns_service

    s = loaded
    m = s.models
    settings = returns_service.settings(s, folder, read_key=read_key, write_key=write_key)
    settings.p2g_webhook_secret = "returns-world-hook"
    parcel2go = s.p2g.FakeParcel2Go()
    labels = s.parcel2go.Parcel2Go(settings, http=httpx.Client(transport=httpx.MockTransport(parcel2go)))
    orders = [
        _order(s, 2205, title="Convict T-Shirt", colour="Black", size="S", price=3000, sku_root="CV-TEE-BLK", shipped_days=11),
        _order(s, 2201, title="Loopback Hoodie", colour="Grey", size="M", price=6500, sku_root="LB-HOOD-GRY", shipped_days=6),
        _order(s, 2202, title="Loopback Hoodie", colour="Black", size="L", price=6500, sku_root="LB-HOOD-BLK", shipped_days=7),
        _order(s, 2190, title="Loopback Hoodie", colour="Grey", size="S", price=6500, sku_root="LB-HOOD-GRY", shipped_days=20),
        _order(s, 2150, title="Convict T-Shirt", colour="Grey", size="S", price=3000, sku_root="CV-TEE-GRY", shipped_days=39),
    ]
    shop = s.fake.FakeShopify(orders)
    clock = Clock()
    svc = s.service.ReturnsService(settings, s.store.Store(settings.db_path), shop, labels, clock=clock)
    app = s.app.create_app(settings, svc)
    staff = TestClient(app)

    def ask(number: int, reason, resolution, postage, *, swap: str = "", courier: str | None = None):
        order = svc.available(shop.get_order(f"gid://shopify/Order/{number}"))
        line = order.lines[0]
        exchange = {line.fulfillment_line_item_id: next(v.id for v in line.siblings if v.options["Size"] == swap)} if swap else {}
        return svc.submit(order, [m.Selection(fulfillment_line_item_id=line.fulfillment_line_item_id, quantity=1, reason=reason)],
                          resolution, postage, exchange, courier)

    def act(ret, action: str, key: str, **params):
        return svc.execute(ret.id, action, params, "George", key)

    # Alicia's grey T-shirt, too small: swapped up a size and finished, three weeks ago.
    clock.at(26)
    done = ask(2150, m.Reason.too_small, m.Resolution.exchange, m.Postage.self_ship, swap="M")
    clock.at(25)
    act(done, "approve", "w1", postage_mode="self_ship")
    clock.at(23)
    act(done, "tracking", "w2", number="RM558812044GB")
    clock.at(20)
    act(done, "receive", "w3", condition="ok")
    # Elise's hoodie, faulty: approved with an Evri label seventeen days ago, never posted.
    clock.at(18)
    unused = ask(2190, m.Reason.faulty, m.Resolution.refund, m.Postage.free_label, courier="evri")
    clock.at(17)
    act(unused, "approve", "w4", postage_mode="label_now")
    # Alison's black hoodie, faulty: she posted it herself; it came back today, damaged.
    clock.at(5)
    damaged = ask(2202, m.Reason.faulty, m.Resolution.refund, m.Postage.self_ship)
    clock.at(4)
    act(damaged, "approve", "w5", postage_mode="self_ship")
    clock.at(3)
    act(damaged, "tracking", "w6", number="RM771203559GB")
    clock.at(0.05)
    act(damaged, "receive", "w7", condition="damaged", note="Seam open at the left cuff; worn once at most.")
    # Alicia's grey hoodie: store credit, an Evri label, dropped off three days ago, delivered today.
    clock.at(5)
    credit = ask(2201, m.Reason.changed_mind, m.Resolution.store_credit, m.Postage.free_label, courier="evri")
    clock.at(4)
    act(credit, "approve", "w8", postage_mode="label_now")
    bought = svc.store.get(credit.id)
    assert bought.postage.label_ref, f"no label for #2201: {bought.status.value}, {bought.last_error}"
    line_id = bought.postage.label_ref.split(":")[2]
    clock.at(3)
    _webhook(staff, line_id, "DroppedOff", "h1", settings.p2g_webhook_secret)
    clock.at(0.1)
    _webhook(staff, line_id, "Delivered", "h2", settings.p2g_webhook_secret)
    # Mia's black T-shirt, too small: asked yesterday for the next size up.
    clock.at(1)
    asked = ask(2205, m.Reason.too_small, m.Resolution.exchange, m.Postage.free_label, swap="M", courier="evri")
    clock.now = datetime.now(UTC)
    return SimpleNamespace(svc=svc, app=app, shop=shop, parcel2go=parcel2go, clock=clock,
                           ids={"mia": asked.id, "alicia": credit.id, "alison": damaged.id, "elise": unused.id, "done": done.id})
