"""Gaps found by the Stage 3 reviews (2026-10-05): service-level conflicts after money moved,
and protocol branches no test would have caught if broken."""

import pytest

from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.models import OpState
from shipping.models import ShipmentStatus as S
from shipping.purchase import ActionError, Purchases, Stale
from shipping.service import ShippingService
from shipping.shopify import ShopifyRefused
from shipping.store import Conflict

from .conftest import SHOP, make_shipment
from .test_purchase import ProcessKilled
from .test_stage2 import answer_all_first_time, only


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


def touch(store, sid):
    """Someone else saves the shipment (a sync, a timer) in the middle of our work."""
    fresh = store.get(SHOP, sid)
    store.save(fresh)


# ------------------------------------------------------------------ service conflicts


def test_a_paid_buy_never_ends_in_an_error_because_fulfilment_raced(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    real = shopify.create_fulfillment

    def create_while_something_saves(*args, **kwargs):
        touch(svc.store, s.id)
        return real(*args, **kwargs)

    shopify.create_fulfillment = create_while_something_saves
    b = svc.preview(SHOP, s.id)["basis"]
    out = svc.buy(SHOP, s.id, b, "george", "k1")  # must not raise
    assert out["charged"] and out["shipment"].label is not None
    shopify.create_fulfillment = real
    svc.tick(SHOP)  # the timer finishes the fulfilment
    assert svc.store.get(SHOP, s.id).status == S.fulfilled
    assert len(shopify.fulfillments) == 1 and len(provider.charges) == 1


def test_the_timer_skips_a_fulfilment_that_raced_and_retries(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    shopify.refuse_fulfillment = 1  # the first fulfilment fails; the timer retries it
    b = svc.preview(SHOP, s.id)["basis"]
    svc.buy(SHOP, s.id, b, "george", "k1")
    real = shopify.create_fulfillment

    def create_while_something_saves(*args, **kwargs):
        touch(svc.store, s.id)
        return real(*args, **kwargs)

    shopify.create_fulfillment = create_while_something_saves
    svc.tick(SHOP)  # must not raise
    shopify.create_fulfillment = real
    svc.tick(SHOP)
    assert svc.store.get(SHOP, s.id).status == S.fulfilled and len(shopify.fulfillments) == 1


def test_an_answers_alert_survives_a_save_in_the_meantime(svc, shopify):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = only(svc)
    svc.answer(
        SHOP,
        s.id,
        "package",
        "first_package",
        {"name": "Mailer", "length_cm": 38, "width_cm": 28, "height_cm": 8, "empty_weight_g": 40},
        "george",
    )

    def refuse_after_a_sync_saved(*args, **kwargs):
        touch(svc.store, s.id)
        raise ShopifyRefused("Access denied for inventoryItemUpdate")

    shopify.update_item = refuse_after_a_sync_saved
    after = svc.answer(
        SHOP,
        s.id,
        "customs",
        "gid://shopify/Product/tee",
        {"hs_code": "6109.10", "description": "Men's cotton T-shirt"},
        "george",
    )
    stored = svc.store.get(SHOP, s.id)
    assert any("Shopify didn't store it" in a for a in stored.alerts)
    assert any(e.type == "answered" for e in stored.timeline)
    assert after.id == s.id


def test_a_preview_that_races_a_save_says_look_again(purchases, store, provider):
    s = make_shipment(store, provider)
    provider.price_minor = 1199  # the price moved: preview saves the new price

    real_verify = provider.verify

    def verify_while_something_saves(shipment, quote):
        touch(store, s.id)
        return real_verify(shipment, quote)

    provider.verify = verify_while_something_saves
    with pytest.raises(ActionError) as e:
        purchases.preview(SHOP, s.id)
    assert e.value.status == 409 and "look" in str(e.value).lower()


def test_refreshing_a_bought_shipment_with_nothing_new_doesnt_save_it(svc, shopify):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    b = svc.preview(SHOP, s.id)["basis"]
    svc.buy(SHOP, s.id, b, "george", "k1")
    version = svc.store.get(SHOP, s.id).version
    svc.prepare(SHOP, s.id)
    assert svc.store.get(SHOP, s.id).version == version


# ------------------------------------------------------------------ protocol branches


def test_a_key_from_another_shipment_is_never_replayed_as_this_ones(purchases, store, provider):
    a = make_shipment(store, provider, sid="shp_a", fo="gid://shopify/FulfillmentOrder/a")
    b = make_shipment(store, provider, sid="shp_b", fo="gid://shopify/FulfillmentOrder/b")
    purchases.buy(SHOP, a.id, purchases.preview(SHOP, a.id)["basis"], "george", "k1")
    with pytest.raises(ActionError, match="another shipment"):
        purchases.buy(SHOP, b.id, purchases.preview(SHOP, b.id)["basis"], "george", "k1")
    assert store.get(SHOP, b.id).label is None and len(provider.charges) == 1


def test_an_order_edited_during_the_price_check_is_refused(purchases, store, provider):
    s = make_shipment(store, provider)
    b = purchases.preview(SHOP, s.id)["basis"]
    real_verify = provider.verify

    def verify_while_the_order_is_edited(shipment, quote):
        fresh = store.get(SHOP, s.id)
        fresh.lines[0].quantity = 3
        store.save(fresh)
        return real_verify(shipment, quote)

    provider.verify = verify_while_the_order_is_edited
    with pytest.raises(Stale, match="a moment ago"):
        purchases.buy(SHOP, s.id, b, "george", "k1")
    assert "create_order" not in provider.calls and provider.charges == []


def test_a_crash_after_pay_sent_but_before_sending_reconciles_to_not_charged(
    purchases, store, provider, monkeypatch, clock
):
    s = make_shipment(store, provider)
    b = purchases.preview(SHOP, s.id)["basis"]
    monkeypatch.setattr(provider, "pay", lambda ref: (_ for _ in ()).throw(ProcessKilled()))
    with pytest.raises(ProcessKilled):
        purchases.buy(SHOP, s.id, b, "george", "k1")
    monkeypatch.undo()
    assert store.op_by_key(SHOP, "k1").state == OpState.pay_sent
    clock.advance(minutes=6)  # its thread is clearly gone
    purchases.reconcile_all()
    assert store.get(SHOP, s.id).status == S.reconciliation_required
    clock.advance(minutes=3)
    purchases.reconcile_all()
    after = store.get(SHOP, s.id)
    assert after.status == S.ready and "weren't charged" in after.last_error
    assert provider.charges == []


def test_fetching_documents_again_keeps_the_first_copies(purchases, store, provider, clock):
    s = make_shipment(store, provider)
    purchases.buy(SHOP, s.id, purchases.preview(SHOP, s.id)["basis"], "george", "k1")
    first = {d.kind: d.artifact_id for d in store.get(SHOP, s.id).label.documents}
    clock.advance(minutes=3)
    purchases.reconcile_all()  # the confirming look fetches documents again
    again = {d.kind: d.artifact_id for d in store.get(SHOP, s.id).label.documents}
    assert again == first


# ------------------------------------------------------------------ compare-and-set details


def test_a_refused_save_leaves_the_copy_usable_after_a_fresh_read(store, provider):
    s = make_shipment(store, provider)
    stale = store.get(SHOP, s.id)
    touch(store, s.id)
    version = stale.version
    with pytest.raises(Conflict):
        store.save(stale)
    assert stale.version == version  # not bumped by the refused save
    fresh = store.get(SHOP, s.id)
    fresh.last_error = "ok"
    store.save(fresh)
    assert store.get(SHOP, s.id).last_error == "ok"


def test_a_row_saved_before_versions_existed_is_still_protected(store, provider):
    s = make_shipment(store, provider)
    doc = s.model_dump()
    doc.pop("version")
    import json

    store._db.execute(
        "UPDATE shipments SET doc=? WHERE shop=? AND id=?",
        (json.dumps(doc, default=str), SHOP, s.id),
    )
    old = store.get(SHOP, s.id)
    assert old.version == 0
    other = store.get(SHOP, s.id)
    store.save(old)  # the first save from a pre-version row works
    with pytest.raises(Conflict):
        store.save(other)  # and a second copy of that old row is refused
