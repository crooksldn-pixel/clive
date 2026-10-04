"""The money boundary. Each test names the real-world situation it protects against."""

from datetime import timedelta

import pytest

from shipping.models import CustomsMode, DocumentKind, OpState, ProviderOp
from shipping.models import ShipmentStatus as S
from shipping.money import Money
from shipping.purchase import ActionError, Stale
from shipping.store import OpenOperationExists

from .conftest import SHOP, make_shipment


def buy(purchases, sid="shp_1", key="k1", shop=SHOP):
    b = purchases.preview(shop, sid)["basis"]
    return purchases.buy(shop, sid, b, "george", key)


def test_preview_explains_and_spends_nothing(purchases, store, provider):
    make_shipment(store, provider)
    pv = purchases.preview(SHOP, "shp_1")
    assert pv["will"][0] == "Buy DPD Classic for £10.69 from Parcel2Go"
    assert pv["money"] == {"shipping_minor": 1069, "currency": "GBP"}
    assert pv["basis"].startswith("b1_")
    assert "create_order" not in provider.calls and not provider.charges


def test_happy_path_buys_exactly_one_label(purchases, store, provider):
    make_shipment(store, provider)
    out = buy(purchases)
    assert out["status"] == "label_purchased" and out["charged"] and not out["error"]
    s = out["shipment"]
    assert s.label.amount == Money(minor=1069) and s.label.tracking_number
    assert {d.kind for d in s.label.documents} == {
        DocumentKind.shipping_label,
        DocumentKind.commercial_invoice,
    }
    assert s.label.complete and s.label.customs == CustomsMode.electronic
    assert provider.charges == ["fake:91234"]
    assert [e.type for e in s.timeline][-3:] == [
        "purchase_authorised",
        "label_purchased",
        "documents_stored",
    ]


def test_same_key_replays_and_never_buys_twice(purchases, store, provider):
    make_shipment(store, provider)
    first = buy(purchases, key="k1")
    again = purchases.buy(SHOP, "shp_1", "anything", "george", "k1")
    assert again["replayed"] and again["operation"] == first["operation"]
    assert provider.calls.count("create_order") == 1 and len(provider.charges) == 1


def test_double_click_with_a_new_key_cannot_buy_again(purchases, store, provider):
    make_shipment(store, provider)
    b = purchases.preview(SHOP, "shp_1")["basis"]
    purchases.buy(SHOP, "shp_1", b, "george", "k1")
    with pytest.raises(ActionError):
        purchases.buy(SHOP, "shp_1", b, "george", "k2")
    assert len(provider.charges) == 1


def test_lost_payment_reply_is_reconciled_not_repaid(purchases, store, provider):
    """Charged, reply lost. The classic double-charge trap."""
    make_shipment(store, provider)
    provider.lose_pay_reply = True
    out = buy(purchases)
    # The immediate read-back found the payment.
    assert out["status"] == "label_purchased" and out["charged"]
    assert provider.calls.count("pay") == 1 and provider.charges == ["fake:91234"]
    assert any(e.type == "payment_outcome_unknown" for e in out["shipment"].timeline)


def test_lost_reply_while_readback_lags_waits_and_blocks_rebuying(purchases, store, provider):
    make_shipment(store, provider)
    provider.lose_pay_reply = True
    provider.readback_lags = 1  # the first read still says unpaid
    out = buy(purchases)
    assert out["status"] == "reconciliation_required" and out["may_have_been_charged"]
    assert "Don't buy again" in out["error"]
    with pytest.raises(ActionError, match="checking"):
        purchases.buy(SHOP, "shp_1", "b", "george", "k2")
    purchases.reconcile_all()  # the next read shows the charge
    s = store.get(SHOP, "shp_1")
    assert s.status == S.label_purchased and s.label.complete
    assert provider.calls.count("pay") == 1 and len(provider.charges) == 1


def test_unknown_payment_that_never_went_through_is_abandoned_not_paid(
    purchases, store, provider, clock
):
    make_shipment(store, provider)
    provider.pay_uncertain_not_charged = True
    out = buy(purchases)
    assert out["status"] == "reconciliation_required"
    clock.advance(seconds=60)
    purchases.reconcile_all()  # second "unpaid", but too soon to believe
    assert store.get(SHOP, "shp_1").status == S.reconciliation_required
    clock.advance(seconds=90)
    purchases.reconcile_all()  # unpaid twice, 2+ minutes apart: abandon that order
    s = store.get(SHOP, "shp_1")
    assert s.status == S.ready and "weren't charged" in s.last_error
    old = store.ops_for(SHOP, "shp_1")[0]
    assert old.state == OpState.abandoned
    # Buying again is a fresh preview and a fresh order; the abandoned one is never paid.
    buy(purchases, key="k2")
    assert provider.charges_for(old.provider_ref) == 0
    assert len(provider.charges) == 1 and provider.calls.count("pay") == 2


def test_refused_payment_is_not_charged_and_can_be_bought_again(purchases, store, provider):
    make_shipment(store, provider)
    provider.refuse_pay = True
    out = buy(purchases)
    assert out["status"] == "ready" and not out["charged"]
    assert "weren't charged" in out["error"] and "Not enough" in out["error"]
    first = store.ops_for(SHOP, "shp_1")[0]
    buy(purchases, key="k2")
    assert provider.charges_for(first.provider_ref) == 0 and len(provider.charges) == 1


def test_unreachable_payment_is_not_charged(purchases, store, provider):
    make_shipment(store, provider)
    provider.pay_unreachable = True
    out = buy(purchases)
    assert out["status"] == "ready" and not provider.charges


def test_order_creation_timeout_leaves_an_orphan_that_is_never_paid(purchases, store, provider):
    make_shipment(store, provider)
    provider.create_uncertain = True
    out = buy(purchases)
    assert out["status"] == "ready" and "Nothing was paid" in out["error"]
    assert "pay" not in provider.calls
    buy(purchases, key="k2")
    assert len(provider.orders) == 2 and len(provider.charges) == 1  # orphan unpaid


def test_order_changed_after_preview_is_stale(purchases, store, provider):
    s = make_shipment(store, provider)
    b = purchases.preview(SHOP, "shp_1")["basis"]
    s = store.get(SHOP, "shp_1")
    s.lines[0].quantity = 3  # customer edited the order
    store.save(s)
    with pytest.raises(Stale, match="changed"):
        purchases.buy(SHOP, "shp_1", b, "george", "k1")
    assert "create_order" not in provider.calls


def test_price_moved_between_preview_and_buy_is_stale(purchases, store, provider):
    make_shipment(store, provider)
    b = purchases.preview(SHOP, "shp_1")["basis"]
    provider.price_minor = 1199
    with pytest.raises(Stale, match="£10.69 to £11.99"):
        purchases.buy(SHOP, "shp_1", b, "george", "k1")
    assert not provider.charges


def test_never_pays_more_than_authorised(purchases, store, provider, monkeypatch):
    make_shipment(store, provider)
    b = purchases.preview(SHOP, "shp_1")["basis"]
    real_create = provider.create_order

    def pricier(*a, **kw):
        order = real_create(*a, **kw)
        order.amount_minor = 1500
        return order

    monkeypatch.setattr(provider, "create_order", pricier)
    out = purchases.buy(SHOP, "shp_1", b, "george", "k1")
    assert out["status"] == "ready" and "more than the £10.69" in out["error"]
    assert not provider.charges


def test_documents_late_are_fetched_without_paying_again(purchases, store, provider):
    make_shipment(store, provider)
    provider.documents_down = 1
    out = buy(purchases)
    assert out["status"] == "label_purchased" and "don't buy again" in out["error"]
    assert not out["shipment"].label.documents
    purchases.reconcile_all()
    s = store.get(SHOP, "shp_1")
    assert s.label.complete and not s.last_error
    assert provider.calls.count("pay") == 1


class ProcessKilled(BaseException):
    """The process dying mid-call: not an error the code could catch and handle."""


def test_crash_after_sending_payment_is_reconciled(purchases, store, provider, monkeypatch, clock):
    make_shipment(store, provider)
    real_pay = provider.pay

    def pay_then_die(ref):
        real_pay(ref)
        raise ProcessKilled

    monkeypatch.setattr(provider, "pay", pay_then_die)
    with pytest.raises(ProcessKilled):
        buy(purchases)
    op = store.ops_for(SHOP, "shp_1")[0]
    assert op.state == OpState.pay_sent  # saved before the call
    monkeypatch.undo()
    purchases.reconcile_all()  # too soon: the payment could still be in flight
    assert store.get(SHOP, "shp_1").status == S.purchasing
    clock.advance(minutes=6)
    purchases.reconcile_all()
    assert store.get(SHOP, "shp_1").status == S.label_purchased
    assert len(provider.charges) == 1


def test_crash_before_paying_gives_the_decision_back(
    purchases, store, provider, clock, monkeypatch
):
    make_shipment(store, provider)
    monkeypatch.setattr(
        provider, "create_order", lambda *a, **k: (_ for _ in ()).throw(ProcessKilled())
    )
    with pytest.raises(ProcessKilled):
        buy(purchases)
    purchases.reconcile_all()
    assert store.get(SHOP, "shp_1").status == S.purchasing  # too soon to decide
    clock.advance(minutes=6)
    purchases.reconcile_all()
    s = store.get(SHOP, "shp_1")
    assert s.status == S.ready and "weren't charged" in s.last_error


def test_only_one_open_purchase_per_shipment_even_racing(store, provider, clock):
    make_shipment(store, provider)

    def op(key):
        return ProviderOp(
            id=f"op_{key}",
            shop=SHOP,
            shipment_id="shp_1",
            idempotency_key=key,
            basis="b",
            actor="x",
            amount=Money(minor=1),
            state=OpState.authorised,
            created_at=clock(),
            updated_at=clock(),
        )

    store.add_op(op("a"))
    with pytest.raises(OpenOperationExists):
        store.add_op(op("b"))


def test_needs_attention_cannot_be_bought(purchases, store, provider):
    make_shipment(store, provider, status=S.needs_attention)
    with pytest.raises(ActionError, match="needs a detail"):
        purchases.preview(SHOP, "shp_1")


def test_reprint_never_buys(purchases, store, provider):
    make_shipment(store, provider)
    buy(purchases)
    calls = list(provider.calls)
    kind, body = purchases.reprint(SHOP, "shp_1")
    kind2, body2 = purchases.reprint(SHOP, "shp_1")
    assert body == body2 and body.startswith(b"%PDF-1.4 4x6")
    assert provider.calls == calls and len(provider.charges) == 1


def test_shops_never_see_each_other(purchases, store, provider):
    make_shipment(store, provider, shop="other.myshopify.com")
    with pytest.raises(ActionError) as e:
        purchases.preview(SHOP, "shp_1")
    assert e.value.status == 404
    assert store.shipments(SHOP) == []


def test_reconcile_is_harmless_when_nothing_is_open(purchases, store, provider, clock):
    make_shipment(store, provider)
    buy(purchases)
    clock.advance(hours=1)
    assert purchases.reconcile_all() == 0
    assert len(provider.charges) == 1 and timedelta(0) == timedelta(0)


def test_a_refusal_at_verify_is_reported_as_the_providers_reason(purchases, store, provider):
    # e.g. the Canaries: "Receivers (DNI) Number is required". Retrying won't help.
    make_shipment(store, provider)
    provider.refuse_verify = "Receivers (DNI) Number is required"
    with pytest.raises(ActionError) as e:
        purchases.preview(SHOP, "shp_1")
    assert e.value.status == 422 and "DNI" in str(e.value) and "try again" not in str(e.value)
    assert provider.charges == [] and "create_order" not in provider.calls
