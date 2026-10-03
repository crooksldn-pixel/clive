from datetime import timedelta

import pytest

from returns.models import Postage, Reason, Resolution, Selection, Status
from returns.service import ActionError

TEE, JEANS = "gid://shopify/FulfillmentLineItem/1", "gid://shopify/FulfillmentLineItem/2"
LARGE = "gid://shopify/ProductVariant/tee-L"


def order(svc, name="1939"):
    session, _ = svc.lookup(name, "customer@example.com", "1.2.3.4")
    return svc.order_for_session(session)


def submit(svc, resolution, postage, reason=Reason.too_small, fli=TEE, exchange=None):
    return svc.submit(
        order(svc),
        [Selection(fulfillment_line_item_id=fli, quantity=1, reason=reason)],
        resolution,
        postage,
        exchange,
    )


def act(svc, ret, action, key=None, actor="clive", **params):
    return svc.execute(ret.id, action, params, actor, key or f"{action}-{ret.id}")


def test_size_exchange_end_to_end(svc, shop):
    ret = submit(svc, Resolution.exchange, Postage.free_label, exchange={TEE: LARGE})
    assert ret.status == Status.requested
    assert ret.lines[0].exchange_direction == "size_up"
    assert ret.money.fee_pence == 0

    out = act(svc, ret, "approve")
    assert out["status"] == "awaiting_shipment" and out["verified"]
    created = shop.called("returnCreate")[0]
    assert created["exchangeLineItems"] == [{"variantId": LARGE, "quantity": 1}]
    assert created["returnLineItems"][0]["returnReasonDefinitionId"].endswith("/1")
    attached = shop.called("reverseDeliveryCreateWithShipping")[0]
    assert attached["tracking"].startswith("RT") and "/files/" in attached["label"]

    out = act(svc, ret, "receive", condition="ok")
    assert out["status"] == "completed" and out["verified"]
    processed = shop.called("returnProcess")[0]["input"]
    assert processed["exchangeLineItems"][0]["quantity"] == 1
    assert "financialTransfer" not in processed


def test_store_credit_with_bonus(svc, shop):
    ret = submit(
        svc, Resolution.store_credit, Postage.free_label, reason=Reason.changed_mind, fli=JEANS
    )
    assert ret.money.credit_pence == 7000 and ret.money.bonus_pence == 1000
    act(svc, ret, "approve")
    out = act(svc, ret, "receive")
    assert out["status"] == "completed"
    transfer = shop.called("returnProcess")[0]["input"]["financialTransfer"]["issueRefund"]
    assert transfer["refundMethods"][0]["storeCreditRefund"]["amount"]["amount"] == "60.00"
    bonus = shop.called("storeCreditAccountCredit")[0]
    assert bonus["pence"] == 1000 and bonus["id"] == "gid://shopify/Customer/77"


def test_change_of_mind_refund_with_paid_label(svc, shop):
    ret = submit(svc, Resolution.refund, Postage.paid_label, reason=Reason.changed_mind)
    assert ret.money.refund_pence == 2150 and ret.postage.paid_by == "customer"
    act(svc, ret, "approve")
    fee = shop.called("returnCreate")[0]["returnShippingFee"]["amount"]
    assert fee == {"amount": "3.50", "currencyCode": "GBP"}
    act(svc, ret, "receive")
    refund = shop.called("returnProcess")[0]["input"]["financialTransfer"]["issueRefund"]
    assert refund["orderTransactions"][0]["transactionAmount"]["amount"] == "21.50"


def test_self_ship_customer_adds_tracking(svc, shop):
    ret = submit(svc, Resolution.refund, Postage.self_ship, reason=Reason.changed_mind)
    act(svc, ret, "approve")
    assert svc.store.get(ret.id).status == Status.awaiting_shipment
    assert svc.public(svc.store.get(ret.id))["needs_tracking"]
    done = svc.customer_tracking(order(svc), ret.id, "ab 123 456 789 gb")
    assert done.status == Status.in_transit and done.postage.tracking == "AB123456789GB"
    assert shop.called("reverseDeliveryCreateWithShipping")[0]["tracking"] == "AB123456789GB"


def test_approve_without_a_label_is_explicit_and_flagged(svc, shop, labels, clock):
    labels.ok = False
    ret = submit(svc, Resolution.exchange, Postage.free_label, exchange={TEE: LARGE})
    out = act(svc, ret, "approve")
    assert out["status"] == "awaiting_label"
    assert "not connected" in out["error"]
    assert svc.tick() == []
    clock.now += timedelta(hours=25)
    assert svc.tick() == [ret.id]
    assert "awaiting_label_overdue" in svc.staff(svc.store.get(ret.id))["attention"]
    assert svc.tick() == []  # flagged once

    out = act(svc, ret, "label", tracking="RN111222333GB")
    assert out["status"] == "awaiting_shipment"
    assert out["error"] is None


def test_label_later_and_no_return(svc, shop):
    later = submit(svc, Resolution.exchange, Postage.free_label, exchange={TEE: LARGE})
    assert act(svc, later, "approve", postage_mode="label_later")["status"] == "awaiting_label"
    keep = submit(svc, Resolution.refund, Postage.free_label, reason=Reason.faulty, fli=JEANS)
    out = act(svc, keep, "approve", postage_mode="no_return")
    assert out["status"] == "completed"
    assert shop.called("reverseDeliveryCreateWithShipping") == []


def test_decline_only_before_approval(svc):
    ret = submit(svc, Resolution.refund, Postage.self_ship, reason=Reason.changed_mind)
    act(svc, ret, "approve")
    with pytest.raises(ActionError):
        act(svc, ret, "decline", reason="worn")
    other = submit(svc, Resolution.refund, Postage.self_ship, reason=Reason.changed_mind, fli=JEANS)
    assert act(svc, other, "decline", reason="Worn")["status"] == "declined"


def test_same_key_never_repeats_a_change(svc, shop):
    ret = submit(svc, Resolution.refund, Postage.self_ship, reason=Reason.changed_mind)
    first = act(svc, ret, "approve", key="k1")
    again = act(svc, ret, "approve", key="k1")
    assert again["replayed"] and again["status"] == first["status"]
    assert len(shop.called("returnCreate")) == 1


def test_failed_processing_can_be_completed_later(svc, shop):
    ret = submit(svc, Resolution.store_credit, Postage.free_label, reason=Reason.too_big)
    act(svc, ret, "approve")
    shop.fail.add("credit")
    out = act(svc, ret, "receive")
    assert out["status"] == "received" and "bonus" in out["error"]
    shop.fail.clear()
    out = act(svc, ret, "complete")
    assert out["status"] == "completed"
    assert len(shop.called("returnProcess")) == 1  # money moved once
    assert len(shop.called("storeCreditAccountCredit")) == 1


def test_damaged_on_arrival_waits_for_a_decision(svc, shop):
    ret = submit(svc, Resolution.refund, Postage.self_ship, reason=Reason.changed_mind)
    act(svc, ret, "approve")
    out = act(svc, ret, "receive", condition="worn", note="Tags removed, worn")
    assert out["status"] == "received"
    assert shop.called("returnProcess") == []
    assert "needs_decision" in svc.staff(svc.store.get(ret.id))["attention"]


def test_item_cannot_be_requested_twice(svc):
    submit(svc, Resolution.refund, Postage.self_ship, reason=Reason.changed_mind)
    with pytest.raises(ActionError):
        submit(svc, Resolution.refund, Postage.self_ship, reason=Reason.changed_mind)


def test_server_rejects_options_not_offered(svc):
    with pytest.raises(ActionError):  # free label on a change-of-mind refund
        submit(svc, Resolution.refund, Postage.free_label, reason=Reason.changed_mind)
    with pytest.raises(ActionError):  # exchange to an out-of-stock size
        submit(
            svc,
            Resolution.exchange,
            Postage.free_label,
            exchange={TEE: "gid://shopify/ProductVariant/tee-XL"},
        )


def test_wrong_proof_is_rate_limited(svc):
    for _ in range(5):
        with pytest.raises(ActionError) as e:
            svc.lookup("1939", "nobody@example.com", "9.9.9.9")
        assert e.value.status == 404
    with pytest.raises(ActionError) as e:
        svc.lookup("1939", "customer@example.com", "9.9.9.9")
    assert e.value.status == 429


def test_preview_states_money_without_changing_anything(svc, shop):
    ret = submit(svc, Resolution.store_credit, Postage.free_label, reason=Reason.too_big)
    act(svc, ret, "approve")
    preview = svc.preview(ret.id, "receive", {"condition": "ok"})
    assert any("£30.00" in line for line in preview["will"])
    assert preview["shopify_calls"] == ["returnProcess", "storeCreditAccountCredit"]
    assert shop.called("returnProcess") == []


def test_shopify_admin_changes_flow_back(svc, shop):
    ret = submit(svc, Resolution.refund, Postage.self_ship, reason=Reason.changed_mind)
    act(svc, ret, "approve")
    rid = svc.store.get(ret.id).shopify.return_id
    shop.returns[rid]["status"] = "CLOSED"
    synced = svc.shopify_changed(rid, "returns/close")
    assert synced.status == Status.completed and synced.timeline[-1].actor == "shopify_admin"


def test_pilot_mode_only_admits_listed_orders(svc):
    svc.s.pilot_order_numbers = "#1800, 1939"
    assert svc.lookup("1939", "customer@example.com", "1.1.1.1")[1].name == "#1939"
    with pytest.raises(ActionError) as e:
        svc.lookup("1950", "customer@example.com", "1.1.1.1")
    assert e.value.status == 403
