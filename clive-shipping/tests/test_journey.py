"""The order's journey, as a person reads it: ordered, label bought, printed, in transit, out
for delivery, delivered, each with its time, plus the carrier's own updates and where the
parcel was last seen. Only what Shopify, the provider or the printer reported."""

from fastapi.testclient import TestClient

from shipping import views
from shipping.app import create_app
from shipping.settings import Settings
from shipping.shopify import parse_fulfillment

from . import test_tracking
from .conftest import SHOP

shopify = test_tracking.shopify
svc = test_tracking.svc
bought = test_tracking.bought

# The shape Shopify answers for a Royal Mail parcel to Guernsey (Admin API 2026-10), newest
# first as the query asks for them. Every identifier is made up: the repo is public.
LIVE_2120 = {
    "id": "gid://shopify/Fulfillment/9001",
    "status": "SUCCESS",
    "displayStatus": "IN_TRANSIT",
    "inTransitAt": "2026-10-07T05:57:26Z",
    "deliveredAt": None,
    "trackingInfo": [{"number": "XX000000010GB", "company": "Royal Mail"}],
    "events": {
        "nodes": [
            {"status": "IN_TRANSIT", "happenedAt": "2026-10-07T05:57:26Z",
             "message": "Item Received", "city": None, "province": None, "country": "GB"},
            {"status": "CONFIRMED", "happenedAt": "2026-10-06T11:22:43Z",
             "message": "Sender advised item dropped off at parcel locker", "city": None,
             "province": None, "country": "GB"},
        ]
    },
    "order": {"id": "gid://shopify/Order/9002", "displayFinancialStatus": "PAID",
              "createdAt": "2026-10-02T19:36:10Z"},
}  # fmt: skip


def test_the_live_shape_parses_oldest_first():
    f = parse_fulfillment(LIVE_2120)
    assert [e["message"] for e in f.events] == [
        "Sender advised item dropped off at parcel locker",
        "Item Received",
    ]
    assert f.order_created_at == "2026-10-02T19:36:10Z" and f.events[0]["country"] == "GB"


def steps(j):
    return {s["key"]: (s["state"], s["at"]) for s in j["steps"]}


def test_a_parcel_in_transit_shows_where_it_was_last_seen(svc, shopify, bought, clock):
    shopify.carrier(
        bought.label.tracking_number, "IN_TRANSIT", in_transit_at="2026-10-07T05:57:26Z"
    )
    shopify.scan(bought.label.tracking_number, "CONFIRMED", "Dropped off", "2026-10-06T11:22:43Z")
    shopify.scan(
        bought.label.tracking_number, "IN_TRANSIT", "Item Received", "2026-10-07T05:57:26Z"
    )
    s = svc.refresh_tracking(SHOP, bought.id)
    j = views.journey_view(s, None)
    got = steps(j)
    assert got["bought"][0] == "done" and got["in_transit"] == ("done", "2026-10-07T05:57:26Z")
    assert got["printed"][0] == "unrecorded"  # it moves, but no print was recorded here
    assert got["out_for_delivery"][0] == "next" and got["delivered"][0] == "later"
    assert j["last_seen"] == {"country": "GB", "city": None, "at": "2026-10-07T05:57:26Z"}
    assert [e["message"] for e in j["events"]] == ["Item Received", "Dropped off"]  # newest first
    # Each scan is in the history once, at its own time, in the carrier's words.
    scans = [e for e in s.timeline if e.type == "carrier_scan"]
    assert [e.detail["message"] for e in scans] == ["Dropped off", "Item Received"]
    svc.refresh_tracking(SHOP, bought.id)  # read again: nothing new, nothing repeated
    again = svc.store.get(SHOP, bought.id)
    assert len([e for e in again.timeline if e.type == "carrier_scan"]) == 2


def test_delivered_fills_every_carrier_step(svc, shopify, bought):
    n = bought.label.tracking_number
    shopify.carrier(n, "DELIVERED", delivered_at="2026-10-07T09:48:22Z")
    shopify.scan(n, "IN_TRANSIT", "Item Received", "2026-10-05T18:02:00Z", country="GB")
    shopify.scan(n, "OUT_FOR_DELIVERY", "Out for delivery", "2026-10-07T07:31:00Z", country="DE")
    shopify.scan(n, "DELIVERED", "Delivered", "2026-10-07T09:48:22Z", country="DE")
    j = views.journey_view(
        svc.refresh_tracking(SHOP, bought.id), {"state": "printed", "printed_at": "x"}
    )
    got = steps(j)
    assert all(
        got[k][0] == "done" for k in ("printed", "in_transit", "out_for_delivery", "delivered")
    )
    assert got["delivered"][1] == "2026-10-07T09:48:22Z" and j["last_seen"]["country"] == "DE"


def test_a_carrier_problem_is_said_in_the_carriers_words(svc, shopify, bought):
    n = bought.label.tracking_number
    shopify.carrier(n, "FAILURE")
    shopify.scan(n, "FAILURE", "Address not found", "2026-10-07T10:00:00Z")
    j = views.journey_view(svc.refresh_tracking(SHOP, bought.id), None)
    assert j["problem"] == "Address not found"
    assert steps(j)["delivered"][0] != "done"  # a problem is never delivered


def test_channel_islands_parcels_say_tracking_may_stop(svc, shopify, bought):
    s = svc.store.get(SHOP, bought.id)
    s.destination = s.destination.model_copy(update={"country": "GG"})
    svc.store.save(s)
    shopify.carrier(bought.label.tracking_number, "IN_TRANSIT")
    j = views.journey_view(svc.refresh_tracking(SHOP, bought.id), None)
    assert "may never say delivered" in j["note"] and j["going_to"] == "GG"


def test_history_shows_staff_names_not_ids(svc, shopify, bought, monkeypatch):
    # The session token is signed here as Shopify signs it (no JWT library needed).
    from .test_admin_api import token

    cfg = Settings(shop_domain=SHOP, provider="fake", tick_interval_s=0,
                   shopify_client_id="app", shopify_client_secret="secret")  # fmt: skip
    s = svc.store.get(SHOP, bought.id)
    s.timeline[-1].actor = "Staff 42"  # written before names were looked up
    svc.store.save(s)
    shopify.staff_name = "Sam Crooks"
    signed = token(shop=SHOP, secret="secret", aud="app")  # the staff member with id 42
    with TestClient(create_app(cfg, svc)) as c:
        auth = {"Authorization": f"Bearer {signed}"}
        d = c.get(f"/admin/api/shipments/{bought.id}", headers=auth)
        assert d.status_code == 200, d.text
        who = {e["who"] for e in d.json()["timeline"]}
        assert "Sam Crooks" in who and "Staff 42" not in who
        assert d.json()["journey"]["steps"][0]["title"] == "Order placed"


def test_staff_name_comes_from_the_token_exchange_or_nothing():
    import httpx

    from shipping.shopify import GraphQLShopify

    def answer(req):
        assert req.url.path == "/admin/oauth/access_token"
        return httpx.Response(
            200, json={"associated_user": {"first_name": "Sam", "last_name": "Crooks"}}
        )

    ok = GraphQLShopify(
        "crooks.myshopify.com",
        "id",
        "secret",
        http=httpx.Client(transport=httpx.MockTransport(answer)),
    )
    assert ok.staff_member("token") == "Sam Crooks"
    refused = GraphQLShopify(
        "crooks.myshopify.com",
        "id",
        "secret",
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={}))),
    )
    assert refused.staff_member("token") is None  # the history keeps "Staff <id>"
