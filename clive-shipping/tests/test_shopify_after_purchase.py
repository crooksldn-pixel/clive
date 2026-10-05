"""After the label is bought, only Shopify is ever retried (Stage 4).

The label purchase and the Shopify update are separate steps with separate states: label
purchased, Shopify fulfilment created (with the tracking number in the same mutation), and
verified by reading the fulfillment order back. If Shopify fails after the purchase, the label
is never bought again: retries (the merchant's button or the timer) touch Shopify only.
"""

import pytest

from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.models import ShipmentStatus as S
from shipping.purchase import ActionError, Purchases
from shipping.service import ShippingService
from shipping.shopify import ShopifyError

from .conftest import SHOP
from .test_stage2 import answer_all_first_time, only


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


@pytest.fixture
def bought_but_shopify_refused(svc, shopify):
    """A label bought once; Shopify refused the fulfilment. Returns (shipment id, basis)."""
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    shopify.refuse_fulfillment = 1
    b = svc.preview(SHOP, s.id)["basis"]
    out = svc.buy(SHOP, s.id, b, "george", "k1")
    assert out["charged"] and out["status"] == "fulfillment_failed"
    return s.id, b


def test_retrying_the_shopify_update_never_reaches_the_provider(
    svc, shopify, provider, bought_but_shopify_refused
):
    sid, _ = bought_but_shopify_refused
    provider_calls = list(provider.calls)
    shopify.refuse_fulfillment = 2
    for _ in range(2):  # Shopify still refuses: the merchant clicks Retry twice
        assert svc.fulfil(SHOP, sid, "george").status == S.fulfillment_failed
    s = svc.fulfil(SHOP, sid, "george")
    assert s.status == S.fulfilled
    assert provider.calls == provider_calls  # not a quote, not an order, not a payment
    assert len(provider.charges) == 1 and len(shopify.fulfillments) == 1


def test_buying_again_after_shopify_failed_never_buys_a_second_label(
    svc, provider, bought_but_shopify_refused
):
    sid, b = bought_but_shopify_refused
    with pytest.raises(ActionError):
        svc.buy(SHOP, sid, b, "george", "k2")  # a second click with a fresh key
    with pytest.raises(ActionError):
        svc.preview(SHOP, sid)
    again = svc.buy(SHOP, sid, b, "george", "k1")  # the same click replayed
    assert again["replayed"]  # the one purchase reported again, not a new one
    assert len(provider.charges) == 1


def test_the_steps_are_recorded_separately(svc, shopify):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    b = svc.preview(SHOP, s.id)["basis"]
    s = svc.buy(SHOP, s.id, b, "george", "k1")["shipment"]
    kinds = [e.type for e in s.timeline]
    assert kinds.index("label_purchased") < kinds.index("fulfillment_created")
    assert kinds.index("fulfillment_created") < kinds.index("fulfilled")
    assert s.fulfillment_id == shopify.fulfillments[0]["id"]
    fulfilled = next(e for e in s.timeline if e.type == "fulfilled")
    assert fulfilled.verified and fulfilled.detail["tracking"] == s.label.tracking_number


def test_created_but_not_yet_readable_is_not_called_fulfilled(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    real_create = shopify.create_fulfillment

    def create_then_shopify_unreadable(*args, **kwargs):
        fid = real_create(*args, **kwargs)
        shopify.fo_reads_fail = 1  # the read-back fails
        return fid

    shopify.create_fulfillment = create_then_shopify_unreadable
    b = svc.preview(SHOP, s.id)["basis"]
    s = svc.buy(SHOP, s.id, b, "george", "k1")["shipment"]
    assert s.status == S.fulfillment_failed  # created, but not verified
    assert s.fulfillment_id and "accepted" in (s.last_error or "")
    shopify.create_fulfillment = real_create
    svc.tick(SHOP)  # reads first: finds it, doesn't create a second
    assert only(svc).status == S.fulfilled and len(shopify.fulfillments) == 1
    assert len(provider.charges) == 1


def test_an_order_closed_in_shopify_without_this_label_is_not_retried_blindly(svc, shopify):
    snap = shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    shopify.refuse_fulfillment = 1
    b = svc.preview(SHOP, s.id)["basis"]
    svc.buy(SHOP, s.id, b, "george", "k1")
    snap.status = "CLOSED"  # someone fulfilled it by hand with another number
    snap.tracking_numbers.append("HANDWRITTEN1")
    s = svc.fulfil(SHOP, s.id, "george")
    assert s.status == S.fulfillment_failed and len(shopify.fulfillments) == 0
    assert "without this label" in (s.last_error or "")


def test_repeated_failures_dont_grow_the_timeline(svc, shopify, bought_but_shopify_refused):
    sid, _ = bought_but_shopify_refused
    shopify.refuse_fulfillment = 5
    svc.tick(SHOP)
    size = len(svc.store.get(SHOP, sid).timeline)
    for _ in range(3):
        svc.tick(SHOP)  # same refusal each time
    assert len(svc.store.get(SHOP, sid).timeline) == size


def test_shopify_down_after_purchase_leaves_the_label_and_retries_later(
    svc, shopify, provider, monkeypatch
):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    b = svc.preview(SHOP, s.id)["basis"]
    real_buy = svc.purchases.buy

    def buy_then_shopify_goes_down(*args, **kwargs):
        out = real_buy(*args, **kwargs)
        monkeypatch.setattr(
            shopify,
            "create_fulfillment",
            lambda *a, **k: (_ for _ in ()).throw(ShopifyError("timed out")),
        )
        shopify.fo_reads_fail = 99
        return out

    svc.purchases.buy = buy_then_shopify_goes_down
    out = svc.buy(SHOP, s.id, b, "george", "k1")
    assert out["charged"] and out["status"] == "fulfillment_failed"
    assert out["shipment"].label is not None
    monkeypatch.undo()
    shopify.fo_reads_fail = 0
    svc.fulfil(SHOP, s.id, "george")
    assert only(svc).status == S.fulfilled and len(provider.charges) == 1


def test_a_fulfilment_shopify_accepted_but_not_yet_shows_is_never_called_closed_elsewhere(
    svc, shopify, provider
):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    real_create = shopify.create_fulfillment

    def created_but_tracking_lags(fo_id, *args, **kwargs):
        fid = real_create(fo_id, *args, **kwargs)
        shopify.fos[fo_id].tracking_numbers.clear()  # CLOSED, number not readable yet
        return fid

    shopify.create_fulfillment = created_but_tracking_lags
    b = svc.preview(SHOP, s.id)["basis"]
    s = svc.buy(SHOP, s.id, b, "george", "k1")["shipment"]
    s = svc.fulfil(SHOP, s.id, "george")  # the retry
    assert s.status == S.fulfillment_failed
    assert "without this label" not in (s.last_error or "")
    assert len(shopify.fulfillments) == 1
    shopify.fos["gid://shopify/FulfillmentOrder/2145"].tracking_numbers.append(
        s.label.tracking_number
    )
    assert svc.fulfil(SHOP, s.id, "george").status == S.fulfilled
    assert len(shopify.fulfillments) == 1 and len(provider.charges) == 1


def test_shopify_unreadable_means_no_fulfilment_is_created_blind(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    real_buy = svc.purchases.buy

    def buy_then_shopify_unreadable(*args, **kwargs):
        out = real_buy(*args, **kwargs)
        shopify.fo_reads_fail = 1
        return out

    svc.purchases.buy = buy_then_shopify_unreadable
    out = svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "george", "k1")
    assert out["status"] == "fulfillment_failed" and shopify.fulfillments == []
    assert "without this label" not in (out["error"] or "")  # unreadable isn't "closed"
    assert svc.fulfil(SHOP, s.id, "george").status == S.fulfilled  # readable again
    assert len(shopify.fulfillments) == 1


def test_a_refusal_after_an_earlier_lost_reply_reads_back_first(svc, shopify, provider):
    snap = shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    real_create = shopify.create_fulfillment

    def already_done_then_refused(fo_id, lines, company, number, *rest):
        snap.tracking_numbers.append(number)  # an earlier attempt landed meanwhile
        from shipping.shopify import ShopifyRefused

        raise ShopifyRefused("no remaining quantity")

    shopify.create_fulfillment = already_done_then_refused
    out = svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "george", "k1")
    assert out["status"] == "fulfilled"
    shopify.create_fulfillment = real_create
