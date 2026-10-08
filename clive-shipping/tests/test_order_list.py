"""The Shipping list reads like Shopify's Orders: when the customer ordered (Shopify's own
createdAt, in the store's time zone), who ordered, where it goes, what it costs, its stage and its
label. Selecting rows never buys: the bulk review re-checks each order and leaves out any that
changed since they were selected."""

from fastapi.testclient import TestClient

from shipping import views
from shipping.app import create_app
from shipping.fake_shopify import fo, tee_line
from shipping.settings import Settings
from shipping.shopify import ShopifyError, parse_fo

from . import test_operations
from .conftest import SHOP
from .test_operations import ready

shopify = test_operations.shopify
svc = test_operations.svc
ops = test_operations.ops
sender = test_operations.sender


def client(svc):
    cfg = Settings(shop_domain=SHOP, provider="fake", dev_skip_admin_auth=True, tick_interval_s=0)
    return TestClient(create_app(cfg, svc))


def test_the_row_carries_shopifys_order_time_and_customer(svc, shopify):
    snap = shopify.add(fo(2145, [tee_line()]))
    snap.order_created_at, snap.customer_name = "2026-10-07T12:06:00Z", "Davina Bird"
    svc.sync(SHOP)
    (s,) = svc.store.shipments(SHOP)
    r = views.row(s)
    assert r["purchased_at"] == "2026-10-07T12:06:00Z"  # Shopify's createdAt
    assert r["purchased_at"] != s.created_at.isoformat()  # never when CLIVE first saw it
    assert r["customer"] == "Davina Bird"


def test_guest_or_deleted_customer_falls_back_to_the_addressee(svc, shopify):
    snap = shopify.add(fo(2146, [tee_line()]))
    snap.customer_name = None  # a guest checkout, or the customer was deleted
    svc.sync(SHOP)
    (s,) = svc.store.shipments(SHOP)
    assert views.row(s)["customer"] == s.destination.name == "Max Muster"
    s.destination = s.destination.model_copy(update={"name": "  "})
    assert views.row(s)["customer"] == "No customer"


def test_a_long_name_is_kept_whole_for_the_screen_to_wrap(svc, shopify):
    snap = shopify.add(fo(2147, [tee_line()]))
    snap.customer_name = "Wolfeschlegelsteinhausenbergerdorff Hubert Blaine " * 3
    svc.sync(SHOP)
    (s,) = svc.store.shipments(SHOP)
    assert views.row(s)["customer"] == snap.customer_name.strip()


def test_customer_and_order_time_parse_from_shopify_shapes():
    node = {
        "id": "gid://shopify/FulfillmentOrder/1",
        "status": "OPEN",
        "order": {"id": "gid://shopify/Order/1", "name": "#1", "createdAt": "2026-10-07T12:06:00Z",
                  "customer": None},
        "destination": {"countryCode": "DE"},
        "lineItems": {"nodes": []},
    }  # fmt: skip
    assert parse_fo(node).customer_name is None  # guest: no crash, no "None" text
    node["order"]["customer"] = {"displayName": "Sam Lee"}
    snap = parse_fo(node)
    assert (snap.customer_name, snap.order_created_at) == ("Sam Lee", "2026-10-07T12:06:00Z")


def test_the_inbox_says_the_store_time_zone_and_falls_back_to_london(svc, shopify):
    shopify.timezone = "America/New_York"
    with client(svc) as c:
        assert c.get("/admin/api/inbox?stage=all").json()["timezone"] == "America/New_York"

    def down():
        raise ShopifyError("unreachable")

    shopify.shop_timezone = down
    with client(svc) as c:  # a fresh app: can't read it, shows London, the list still works
        r = c.get("/admin/api/inbox?stage=all")
        assert r.status_code == 200 and r.json()["timezone"] == "Europe/London"


def test_an_order_unpaid_since_selection_is_left_out_of_the_review(svc, shopify, ops):
    rows = ready(svc, shopify, 3)
    selected = [s.id for s in rows]  # as the browser selected them, all ready
    shopify.fos[rows[1].fulfillment_order_id].financial_status = "PENDING"  # then it changed
    b = ops.preview(SHOP, "buy", selected, "staff", "review-1")
    states = {c["shipment_id"]: c["state"] for c in b["children"]}
    assert states[rows[1].id] == "excluded" and list(states.values()).count("review") == 2
    changed = next(c for c in b["children"] if c["shipment_id"] == rows[1].id)
    assert "ayment" in changed["message"] and changed["provider"]  # says why, and what it was
    kept = [c["amount_minor"] for c in b["children"] if c["state"] == "review"]
    assert b["total_minor"] == sum(kept)


def test_selecting_and_reviewing_never_buys(svc, shopify, ops, provider):
    rows = ready(svc, shopify, 3)
    with client(svc) as c:
        inbox = c.get("/admin/api/inbox?stage=ready").json()
        assert all(r["can_select"] for r in inbox["rows"])
    ops.preview(SHOP, "buy", [s.id for s in rows], "staff", "review-2")  # the review itself
    assert provider.charges == [] and "pay" not in getattr(provider, "calls", [])
