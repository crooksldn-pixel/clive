"""Ledger integrity under crashes and races (Stage 3 review, 2026-10-05).

Each test is a scenario the reviewers reproduced: a paid purchase recorded wrongly, or left open
with no way back. Money may move once; the record must always catch up with the truth."""

import pytest

from shipping.models import OpState
from shipping.models import ShipmentStatus as S
from shipping.providers.base import ProviderRefused
from shipping.purchase import ActionError
from shipping.store import Conflict

from .conftest import SHOP, make_shipment
from .test_purchase import ProcessKilled


def authorise(purchases, store, provider, key="k1"):
    s = make_shipment(store, provider)
    return s, purchases.preview(SHOP, s.id)["basis"]


def test_a_crash_after_paying_before_the_label_is_recorded_is_repaired(
    purchases, store, provider, monkeypatch, clock
):
    s, b = authorise(purchases, store, provider)
    monkeypatch.setattr(
        purchases, "_label_bought", lambda op, how: (_ for _ in ()).throw(ProcessKilled())
    )
    with pytest.raises(ProcessKilled):
        purchases.buy(SHOP, s.id, b, "george", "k1")
    assert store.op_by_key(SHOP, "k1").state == OpState.paid  # money moved, label not recorded
    monkeypatch.undo()
    clock.advance(minutes=1)
    purchases.reconcile_all()
    after = store.get(SHOP, s.id)
    assert after.status == S.label_purchased and after.label is not None
    assert after.label.complete and store.op_by_key(SHOP, "k1").state == OpState.done
    assert len(provider.charges) == 1


def test_a_crash_between_closing_the_operation_and_freeing_the_shipment_cannot_strand_it(
    purchases, store, provider, monkeypatch, clock
):
    # The refusal closes the operation and returns the shipment to "ready" as one transaction:
    # a crash in between leaves neither half.
    s, b = authorise(purchases, store, provider)
    provider.refuse_pay = True
    real_save = store.save

    def save_then_die(shipment):
        if shipment.status == S.ready and shipment.last_error:
            raise ProcessKilled
        return real_save(shipment)

    monkeypatch.setattr(store, "save", save_then_die)
    with pytest.raises(ProcessKilled):
        purchases.buy(SHOP, s.id, b, "george", "k1")
    monkeypatch.undo()
    op = store.op_by_key(SHOP, "k1")
    assert op.state in (OpState.pay_sent, OpState.pay_unknown)  # rolled back, still open
    for _ in range(3):
        clock.advance(minutes=6)
        purchases.reconcile_all()
    after = store.get(SHOP, s.id)
    assert after.status == S.ready and "weren't charged" in after.last_error
    assert store.open_op(SHOP, s.id) is None and provider.charges == []
    out = purchases.buy(SHOP, s.id, purchases.preview(SHOP, s.id)["basis"], "george", "k2")
    assert out["charged"] and len(provider.charges) == 1  # and it can be bought again


def test_the_timer_leaves_a_payment_in_flight_alone(purchases, store, provider, clock):
    s, b = authorise(purchases, store, provider)
    real_pay = provider.pay

    def slow_pay(ref):
        purchases.reconcile_all()  # a tick while the payment is still on the wire
        clock.advance(minutes=3)
        purchases.reconcile_all()  # and another, past the "confirmed unpaid" window
        real_pay(ref)

    provider.pay = slow_pay
    out = purchases.buy(SHOP, s.id, b, "george", "k1")
    after = store.get(SHOP, s.id)
    assert out["charged"] and after.status == S.label_purchased and after.label is not None
    assert not after.last_error and len(provider.charges) == 1


def test_an_operation_the_timer_gave_up_on_is_never_then_paid(purchases, store, provider, clock):
    # create_order stalls past the "interrupted" window; the timer gives the decision back. When
    # the stalled call returns, it must not go on to pay.
    s, b = authorise(purchases, store, provider)
    real_create = provider.create_order

    def stalled(shipment, quote, reference):
        clock.advance(minutes=10)
        purchases.reconcile_all()  # sees an old 'authorised' op and abandons it
        return real_create(shipment, quote, reference)

    provider.create_order = stalled
    purchases.buy(SHOP, s.id, b, "george", "k1")
    assert provider.charges == [] and "pay" not in provider.calls
    after = store.get(SHOP, s.id)
    assert after.status == S.ready and "weren't charged" in after.last_error


def test_a_stale_copy_of_an_operation_cannot_overwrite_a_newer_one(purchases, store, provider):
    s, b = authorise(purchases, store, provider)
    purchases.buy(SHOP, s.id, b, "george", "k1")
    old = store.op_by_key(SHOP, "k1").model_copy(update={"state": OpState.pay_sent, "version": 0})
    with pytest.raises(Conflict):
        store.save_op(old)
    assert store.op_by_key(SHOP, "k1").state == OpState.done


def test_documents_saying_unpaid_after_a_paid_reply_go_back_to_the_read_back(
    purchases, store, provider, clock
):
    # The pay call answered 2xx, but the provider later says the order isn't paid. Don't keep
    # saying "documents haven't arrived": let the read-back rule decide, and never pay again.
    s, b = authorise(purchases, store, provider)
    real_pay = provider.pay

    def pay_that_did_not_take(ref):
        provider.calls.append("pay")  # answered OK, but nothing was charged

    provider.pay = pay_that_did_not_take
    out = purchases.buy(SHOP, s.id, b, "george", "k1")
    op = store.op_by_key(SHOP, "k1")
    assert op.state == OpState.pay_unknown and out["status"] == "reconciliation_required"
    for _ in range(2):
        clock.advance(minutes=3)
        purchases.reconcile_all()
    after = store.get(SHOP, s.id)
    assert after.status == S.ready and "weren't charged" in after.last_error
    assert provider.charges == [] and provider.calls.count("pay") == 1
    provider.pay = real_pay


def test_a_read_back_that_keeps_failing_is_escalated_never_paid(purchases, store, provider, clock):
    s, b = authorise(purchases, store, provider)
    provider.lose_pay_reply = True
    provider.read_down = 1000
    purchases.buy(SHOP, s.id, b, "george", "k1")
    for _ in range(5):
        clock.advance(minutes=20)
        purchases.reconcile_all()
    after = store.get(SHOP, s.id)
    assert after.status == S.reconciliation_required
    assert any("couldn't confirm the payment" in a for a in after.alerts)
    assert len(after.alerts) == 1  # said once, not every sweep
    assert len(provider.charges) == 1 and provider.calls.count("pay") == 1


def test_customs_still_unknown_after_an_hour_is_escalated(purchases, store, provider, clock):
    provider.customs = "unknown"
    s, b = authorise(purchases, store, provider)
    purchases.buy(SHOP, s.id, b, "george", "k1")
    for _ in range(4):
        clock.advance(minutes=20)
        purchases.reconcile_all()
    after = store.get(SHOP, s.id)
    assert any("customs paperwork" in a.lower() for a in after.alerts)
    assert len(provider.charges) == 1


def test_two_clicks_that_both_pass_the_price_check_buy_once(purchases, store, provider):
    s, b = authorise(purchases, store, provider)
    real_verify = provider.verify
    state = {"inner": False}

    def verify_while_another_click_buys(shipment, quote):
        price = real_verify(shipment, quote)
        if not state["inner"] and provider.calls.count("verify") == 2:  # the outer buy
            state["inner"] = True
            purchases.buy(SHOP, s.id, b, "george", "k2")
        return price

    provider.verify = verify_while_another_click_buys
    with pytest.raises(ActionError):
        purchases.buy(SHOP, s.id, b, "george", "k1")
    assert len(provider.charges) == 1 and store.open_op(SHOP, s.id) is None
    assert store.op_by_key(SHOP, "k1") is None  # no orphan operation was left behind


def test_an_unexpected_state_when_recording_a_paid_label_is_made_visible(
    purchases, store, provider, monkeypatch
):
    s, b = authorise(purchases, store, provider)
    real_label = purchases._label_bought

    def shipment_moved_meanwhile(op, how):
        fresh = store.get(SHOP, s.id)
        fresh.status = S.ready  # e.g. an old record repaired by hand
        store.save(fresh)
        real_label(op, how)

    monkeypatch.setattr(purchases, "_label_bought", shipment_moved_meanwhile)
    purchases.buy(SHOP, s.id, b, "george", "k1")
    after = store.get(SHOP, s.id)
    assert any("paid for" in a.lower() for a in after.alerts)


def test_a_refused_payment_with_a_reason_is_still_not_a_charge(purchases, store, provider):
    s, b = authorise(purchases, store, provider)

    def refuse(ref):
        provider.calls.append("pay")
        raise ProviderRefused("Not enough PrePay balance", code="400")

    provider.pay = refuse
    out = purchases.buy(SHOP, s.id, b, "george", "k1")
    assert out["operation_state"] == "failed" and provider.charges == []
