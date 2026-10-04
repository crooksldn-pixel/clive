"""Unsafe assumptions on the purchase path, found reviewing its type errors (2026-10-05).

Each test is a way money could move without the record saying so."""

import pytest

from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.models import OpState
from shipping.models import ShipmentStatus as S
from shipping.providers.base import ProviderRefused
from shipping.purchase import Purchases
from shipping.service import ShippingService
from shipping.store import Conflict

from .conftest import SHOP, make_shipment
from .test_stage2 import answer_all_first_time, only


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


def test_a_slow_refresh_cannot_overwrite_a_purchase_made_meanwhile(svc, shopify, provider):
    # prepare() reads the shipment, asks the provider for quotes over the network, then saves.
    # If a buy completes in that window, saving the old copy would put a paid shipment back to
    # "ready" with no label, and the next click would buy (and charge) again.
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    assert s.status == S.ready
    real_quotes = provider.quotes

    def quotes_while_someone_buys(shipment):
        b = svc.preview(SHOP, s.id)["basis"]
        assert svc.buy(SHOP, s.id, b, "george", "k1")["charged"]
        return real_quotes(shipment)

    provider.quotes = quotes_while_someone_buys
    with pytest.raises(Conflict):
        svc.prepare(SHOP, s.id)
    provider.quotes = real_quotes
    after = svc.store.get(SHOP, s.id)
    assert after.status in (S.label_purchased, S.fulfilled) and after.label is not None
    assert len(provider.charges) == 1


def test_the_tick_skips_a_shipment_that_changed_under_it(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    real_quotes = provider.quotes

    def quotes_while_someone_buys(shipment):
        provider.quotes = real_quotes
        b = svc.preview(SHOP, s.id)["basis"]
        svc.buy(SHOP, s.id, b, "george", "k1")
        return real_quotes(shipment)

    provider.quotes = quotes_while_someone_buys
    svc.tick(SHOP)  # must not raise, and must not undo the purchase
    assert svc.store.get(SHOP, s.id).label is not None
    assert len(provider.charges) == 1


def test_a_shipment_changed_after_authorising_is_not_bought(
    purchases, store, provider, monkeypatch
):
    # The provider order is built after the buy is authorised and saved. If the shipment no
    # longer matches what was authorised by then, nothing is ordered or paid.
    s = make_shipment(store, provider)
    b = purchases.preview(SHOP, s.id)["basis"]
    real_advance = purchases._advance

    def edit_then_advance(op):
        fresh = store.get(SHOP, s.id)
        fresh.lines[0].quantity = 5  # e.g. an order edit landing in that instant
        store.save(fresh)
        real_advance(op)

    monkeypatch.setattr(purchases, "_advance", edit_then_advance)
    out = purchases.buy(SHOP, s.id, b, "george", "k1")
    assert out["operation_state"] == "failed" and not out["charged"]
    assert "changed after the label was authorised" in out["error"]
    assert "create_order" not in provider.calls and provider.charges == []


def test_the_label_records_what_was_authorised(purchases, store, provider, clock):
    # After a lost reply the label is recorded during reconcile. It must come from the
    # authorised operation, not from whatever quote the shipment holds by then.
    s = make_shipment(store, provider)
    b = purchases.preview(SHOP, s.id)["basis"]
    provider.lose_pay_reply = True
    provider.readback_lags = 1  # the first read-back doesn't show the payment yet
    out = purchases.buy(SHOP, s.id, b, "george", "k1")
    assert out["status"] == "reconciliation_required"
    fresh = store.get(SHOP, s.id)
    fresh.quote = None
    store.save(fresh)
    purchases.reconcile(store.op_by_key(SHOP, "k1"))
    label = store.get(SHOP, s.id).label
    assert label is not None and label.carrier == "DPD" and label.service_name == "Classic"
    assert len(provider.charges) == 1


def test_a_garbled_payment_reply_is_unknown_not_failed(purchases, store, provider):
    # Anything unexpected after the payment request went out may mean it was taken.
    s = make_shipment(store, provider)
    b = purchases.preview(SHOP, s.id)["basis"]
    real_pay = provider.pay

    def pay_then_garble(ref):
        real_pay(ref)
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    provider.pay = pay_then_garble
    out = purchases.buy(SHOP, s.id, b, "george", "k1")
    assert out["charged"] and out["status"] == "label_purchased"
    assert len(provider.charges) == 1  # read back, never paid again


def test_a_garbled_order_reply_pays_nothing(purchases, store, provider):
    s = make_shipment(store, provider)
    b = purchases.preview(SHOP, s.id)["basis"]

    def broken(*a, **kw):
        raise KeyError("OrderId")

    provider.create_order = broken
    out = purchases.buy(SHOP, s.id, b, "george", "k1")
    assert out["operation_state"] == "failed" and out["status"] == "ready"
    assert provider.charges == [] and "Nothing was paid" in out["error"]


def test_one_broken_operation_does_not_stop_the_others_reconciling(store, provider, clock):
    purchases = Purchases(store, provider, clock=clock)
    first = make_shipment(store, provider, sid="shp_1", fo="gid://shopify/FulfillmentOrder/1")
    second = make_shipment(store, provider, sid="shp_2", fo="gid://shopify/FulfillmentOrder/2")
    for s, key in ((first, "k1"), (second, "k2")):
        b = purchases.preview(SHOP, s.id)["basis"]
        provider.lose_pay_reply = True
        provider.readback_lags = 1  # stays unknown until a later sweep
        purchases.buy(SHOP, s.id, b, "george", key)
    stuck = [op for op in store.open_ops() if op.state == OpState.pay_unknown]
    assert len(stuck) == 2
    real_read = provider.read_order
    bad = stuck[0].provider_ref

    def read(ref):
        if ref == bad:
            raise RuntimeError("adapter bug")
        return real_read(ref)

    provider.read_order = read
    purchases.reconcile_all()  # must not raise
    states = {op.provider_ref: op.state for op in (store.op_by_key(SHOP, k) for k in ("k1", "k2"))}
    assert states[bad] == OpState.pay_unknown  # still unknown, still checked next time
    assert OpState.done in states.values()
    assert len(provider.charges) == 2  # one each, never more


def test_parcel2go_says_plainly_when_there_is_no_package(store, provider):
    from shipping.models import ShopConfig
    from shipping.providers.parcel2go import Parcel2Go

    p2g = Parcel2Go("https://p2g.test", "id", "secret", config=lambda shop: ShopConfig(shop=shop))
    s = make_shipment(store, provider)
    s.package = None
    with pytest.raises(ProviderRefused, match="package"):
        p2g._parcel(s)
