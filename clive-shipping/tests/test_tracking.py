"""Where a bought parcel is, from Shopify's carrier tracking (shipping.tracking).

A fulfilment "SUCCESS" is never taken for delivery; CLIVE's own fulfilment is found by its id or
its tracking number, never by being first; parcels are re-read at a modest pace, delivered ones
never again, and the pace survives a restart.
"""

import pytest

from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.purchase import Purchases
from shipping.service import ShippingService
from shipping.shopify import FulfillmentTracking
from shipping.tracking import match, stage_of

from .conftest import SHOP
from .test_stage2 import answer_all_first_time, only


def f(display=None, *, id="gid://shopify/Fulfillment/1", number="VU1GB", **when):
    return FulfillmentTracking(
        id=id,
        status="SUCCESS",
        display_status=display,
        in_transit_at=when.get("in_transit_at"),
        delivered_at=when.get("delivered_at"),
        estimated_delivery_at=None,
        updated_at=None,
        numbers=[number],
    )


# ------------------------------------------------------------------ the mapping


@pytest.mark.parametrize(
    ("display", "when", "stage"),
    [
        ("CONFIRMED", {}, "pre_transit"),  # SUCCESS + confirmed: not moving, not delivered
        ("LABEL_PURCHASED", {}, "pre_transit"),
        ("FULFILLED", {}, "pre_transit"),
        ("IN_TRANSIT", {"in_transit_at": "2026-10-07T05:11:05Z"}, "in_transit"),
        ("CARRIER_PICKED_UP", {}, "in_transit"),
        ("OUT_FOR_DELIVERY", {}, "out_for_delivery"),
        ("ATTEMPTED_DELIVERY", {}, "delivery_attempted"),
        ("READY_FOR_PICKUP", {}, "ready_for_pickup"),
        ("DELIVERED", {}, "delivered"),
        ("IN_TRANSIT", {"delivered_at": "2026-10-01T09:48:22Z"}, "delivered"),
        ("DELAYED", {}, "exception"),
        ("FAILURE", {}, "exception"),
        ("NOT_DELIVERED", {}, "exception"),
        ("CANCELED", {}, "cancelled"),
        (None, {}, "unknown"),
        (None, {"in_transit_at": "2026-10-07T05:11:05Z"}, "in_transit"),
        ("SOMETHING_NEW", {}, "unknown"),
    ],
)
def test_shopify_display_status_maps_to_one_stage(display, when, stage):
    assert stage_of(f(display, **when)) == stage


def test_a_successful_fulfilment_is_not_delivery():
    assert stage_of(f("CONFIRMED")) != "delivered"
    assert stage_of(f(None)) != "delivered"


def test_cliv_es_fulfilment_is_found_by_id_then_number_never_by_position():
    theirs = f("DELIVERED", id="gid://shopify/Fulfillment/1", number="OTHER1GB")
    ours = f("IN_TRANSIT", id="gid://shopify/Fulfillment/2", number="XX 000 000 040 GB")
    assert match([theirs, ours], "gid://shopify/Fulfillment/2", None) is ours
    assert match([theirs, ours], None, "xx000000040gb") is ours  # spacing and case ignored
    assert match([theirs, ours], None, "NOPE") is None
    assert match([theirs, ours], None, None) is None  # never "the first one"
    twin = f("CONFIRMED", id="gid://shopify/Fulfillment/3", number="XX000000040GB")
    assert match([theirs, ours, twin], None, "XX000000040GB") is None  # ambiguous: don't guess


# ------------------------------------------------------------------ reading it for real


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


@pytest.fixture
def bought(svc, shopify):
    shopify.add(fo(2145, [tee_line(qty=2)]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    assert svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "george", "k1")["charged"]
    s = svc.store.get(SHOP, s.id)
    assert s.fulfillment_id and s.label.tracking_number
    return s


def test_tracking_follows_the_parcel_and_stops_once_delivered(svc, shopify, bought, clock):
    number = bought.label.tracking_number
    svc.tick(SHOP)
    s = svc.store.get(SHOP, bought.id)
    assert s.tracking.stage == "pre_transit" and s.tracking.fulfillment_id == bought.fulfillment_id

    shopify.carrier(number, "IN_TRANSIT", in_transit_at="2026-10-07T05:11:05Z")
    reads = len(shopify.tracking_reads)
    svc.tick(SHOP)  # not due yet: Shopify isn't asked again
    assert len(shopify.tracking_reads) == reads
    clock.advance(hours=2, minutes=1)
    svc.tick(SHOP)
    s = svc.store.get(SHOP, bought.id)
    assert s.tracking.stage == "in_transit"
    assert any(e.type == "carrier_in_transit" and e.verified for e in s.timeline)

    shopify.carrier(number, "DELIVERED", delivered_at="2026-10-08T09:48:22Z")
    clock.advance(hours=3)
    svc.tick(SHOP)
    s = svc.store.get(SHOP, bought.id)
    assert s.tracking.stage == "delivered" and s.tracking.next_check_at is None
    reads = len(shopify.tracking_reads)
    clock.advance(days=3)
    svc.tick(SHOP)
    assert len(shopify.tracking_reads) == reads  # delivered: never asked again


def test_a_carrier_problem_is_a_warning_not_delivered(svc, shopify, bought, clock):
    shopify.carrier(bought.label.tracking_number, "DELAYED")
    svc.tick(SHOP)
    s = svc.store.get(SHOP, bought.id)
    assert s.tracking.stage == "exception" and s.tracking.next_check_at is not None


def test_without_its_id_the_fulfilment_is_found_by_tracking_number(svc, shopify, bought, store):
    # Another fulfilment on the same order comes FIRST: it must not be taken.
    shopify.fulfillments.insert(
        0,
        {
            "id": "gid://shopify/Fulfillment/9",
            "fo": "x",
            "order_id": bought.order_id,
            "number": "SOMEONEELSE1GB",
            "display": "DELIVERED",
            "delivered_at": "2026-10-02T10:00:00Z",
        },
    )
    s = store.get(SHOP, bought.id)
    s.fulfillment_id = None
    store.save(s)
    shopify.carrier(bought.label.tracking_number, "IN_TRANSIT")
    s = svc.refresh_tracking(SHOP, bought.id)
    assert s.tracking.stage == "in_transit" and s.tracking.fulfillment_id != (
        "gid://shopify/Fulfillment/9"
    )


def test_a_channel_islands_parcel_stuck_in_transit_is_given_up_on_after_a_month(
    svc, shopify, bought, clock
):
    """Royal Mail hands Guernsey parcels to Guernsey Post; Shopify never hears 'delivered'."""
    shopify.carrier(bought.label.tracking_number, "IN_TRANSIT")
    svc.tick(SHOP)
    clock.advance(days=6)
    svc.tick(SHOP)
    s = svc.store.get(SHOP, bought.id)
    assert (s.tracking.next_check_at - clock()).total_seconds() == 12 * 3600  # quiet: twice a day
    clock.advance(days=25)
    svc.tick(SHOP)
    s = svc.store.get(SHOP, bought.id)
    assert s.tracking.stage == "in_transit" and s.tracking.next_check_at is None
    assert "no longer checked" in s.tracking.note


def test_a_parcel_that_moved_lately_is_still_checked_a_month_after_the_label(
    svc, shopify, bought, clock
):
    """Giving up is measured from the last carrier news, not from the label: a parcel that
    went out for delivery on day 25 is still followed on day 35."""
    shopify.carrier(bought.label.tracking_number, "IN_TRANSIT")
    svc.tick(SHOP)
    clock.advance(days=25)
    shopify.carrier(bought.label.tracking_number, "OUT_FOR_DELIVERY")
    svc.tick(SHOP)
    clock.advance(days=10)
    svc.tick(SHOP)
    s = svc.store.get(SHOP, bought.id)
    assert s.tracking.stage == "out_for_delivery" and s.tracking.next_check_at is not None
    clock.advance(days=60)  # however it moves, three months after the label it stops
    shopify.carrier(bought.label.tracking_number, "DELAYED")
    svc.tick(SHOP)
    s = svc.store.get(SHOP, bought.id)
    assert s.tracking.next_check_at is None and "90 days" in s.tracking.note


def test_the_pace_survives_a_restart(svc, shopify, bought, store, provider, clock):
    svc.tick(SHOP)
    reads = len(shopify.tracking_reads)
    again = ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )
    again.tick(SHOP)  # a fresh process: the stored next-check time still applies
    assert len(shopify.tracking_reads) == reads


def test_reading_tracking_never_buys_or_prints(svc, shopify, bought, provider):
    charges, calls = list(provider.charges), list(provider.calls)
    for _ in range(3):
        svc.refresh_tracking(SHOP, bought.id)
    assert provider.charges == charges and provider.calls == calls
