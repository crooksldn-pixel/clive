"""Staff issue a return for a customer themselves: the items, the refund, and a drop-off label
(QR code and the nearest drop-off points) emailed to the customer.

It goes through the same steps as a customer's return (the Shopify return, the label bought
once through the same ledger, the refund when it arrives), with three differences a person
decides: the return window isn't applied, the refund is the amount staff enter, and the
customer is emailed the QR code, drop-off points, items and refund by CROOKS.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from returns.fake import FakeLabels
from returns.mailer import RecordingMailer
from returns.models import Reason, Selection, Status
from returns.service import ActionError, ReturnsService
from returns.store import Store

from .conftest import RecordingNotifier

TEE, JEANS = "gid://shopify/FulfillmentLineItem/1", "gid://shopify/FulfillmentLineItem/2"
ORDER = "gid://shopify/Order/1939"


@pytest.fixture
def labels() -> FakeLabels:
    return FakeLabels(drop_off=True)


@pytest.fixture
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture
def svc(settings, shop, labels, clock, mailer) -> ReturnsService:
    return ReturnsService(
        settings,
        Store(settings.db_path),
        shop,
        labels,
        RecordingNotifier(settings),
        clock=clock,
        mailer=mailer,
    )


def tee(qty: int = 1, reason: Reason = Reason.faulty) -> list[Selection]:
    return [Selection(fulfillment_line_item_id=TEE, quantity=qty, reason=reason)]


def create(svc, key="new-1", refund=2500, courier="evri", sel=None, actor="Sam (staff)"):
    return svc.create_for_customer(ORDER, sel or tee(), refund, courier, actor, key)


# --------------------------------------------------------------------------- the return


def test_a_staff_return_is_approved_with_a_label_and_the_customer_is_emailed(
    svc, shop, labels, mailer
):
    ret = create(svc)
    assert ret.origin == "staff" and ret.status == Status.awaiting_shipment
    assert ret.money.refund_pence == 2500 and ret.postage.service == "evri"
    assert [c[0] for c in shop.calls].count("returnCreate") == 1
    assert labels.made == [ret.id]  # one label, through the normal approval
    assert ret.postage.qr_file_id and ret.postage.drop_off_text
    assert ret.postage.shops and ret.postage.shops[0]["name"]
    # One CROOKS email with the QR code, the drop-off points, the item and the refund.
    (mail,) = mailer.sent
    assert mail["to"] == "customer@example.com"
    assert "Docket Tee" in mail["text"] and "£25.00" in mail["text"]
    assert ret.postage.shops[0]["name"] in mail["text"]
    assert ret.postage.drop_off_text in mail["text"]
    assert {a["filename"] for a in mail["attachments"]} == {"return-qr.png", "return-label.pdf"}
    assert 'src="cid:return-qr"' in mail["html"]
    assert ret.email is not None and ret.email.status == "sent"
    # Shopify's own label email isn't sent as well: the customer gets one email.
    attach = next(c[1] for c in shop.calls if c[0] == "reverseDeliveryCreateWithShipping")
    assert attach["notify"] is False
    assert any(e.type == "requested" and e.actor == "Sam (staff)" for e in ret.timeline)


def test_the_same_request_again_is_the_same_return(svc, labels, mailer):
    first = create(svc, key="dbl")
    again = create(svc, key="dbl")
    assert again.id == first.id
    assert labels.made == [first.id] and len(mailer.sent) == 1


def test_a_second_click_with_a_new_key_cannot_return_the_item_twice(svc, labels):
    create(svc, key="click-1")
    with pytest.raises(ActionError, match="can be returned"):
        create(svc, key="click-2")
    assert len(labels.made) == 1


def test_a_key_reused_for_a_different_request_is_refused(svc):
    create(svc, key="k")
    with pytest.raises(ActionError, match="different request"):
        create(svc, key="k", refund=1000)


def test_the_return_window_is_not_applied_but_quantities_are(svc, shop, clock):
    clock.now += timedelta(days=400)  # long after any window
    ret = create(svc, sel=tee(reason=Reason.changed_mind))
    assert ret.status == Status.awaiting_shipment
    with pytest.raises(ActionError, match="can be returned"):
        create(
            svc,
            key="more",
            sel=[Selection(fulfillment_line_item_id=TEE, quantity=2, reason=Reason.faulty)],
        )


def test_the_refund_defaults_to_the_policy_and_is_capped_at_what_was_paid(svc, shop):
    q = svc.staff_quote(ORDER, tee())
    assert q["default_refund_pence"] == 2500  # the item, as a customer would be offered
    # Item and the order's shipping is the most that can be given back for this item.
    assert q["max_refund_pence"] == 2500 + shop.orders[ORDER].shipping_pence
    with pytest.raises(ActionError, match="at most"):
        create(svc, refund=q["max_refund_pence"] + 1)
    with pytest.raises(ActionError, match="refund"):
        create(svc, refund=-1)


def test_the_refund_staff_set_is_what_is_refunded_when_it_arrives(svc, shop):
    ret = create(svc, refund=1800)
    ret = svc.execute(ret.id, "receive", {"condition": "ok"}, "Sam", "rcv")["return_doc"]
    process = next(c[1]["input"] for c in shop.calls if c[0] == "returnProcess")
    sent = process["financialTransfer"]["issueRefund"]["orderTransactions"]
    assert sum(float(t["transactionAmount"]["amount"]) for t in sent) == 18.0
    assert "refundShipping" not in process


def test_a_refund_above_the_item_refunds_the_rest_as_shipping(svc, shop):
    ret = create(svc, refund=2500 + 395)
    assert ret.money.shipping_refund_pence == 395
    svc.execute(ret.id, "receive", {"condition": "ok"}, "Sam", "rcv")
    process = next(c[1]["input"] for c in shop.calls if c[0] == "returnProcess")
    assert process["refundShipping"]["shippingRefundAmount"]["amount"] == "3.95"


def test_the_drop_off_must_be_one_offered(svc, labels):
    with pytest.raises(ActionError, match="drop-off"):
        create(svc, courier="dhl")
    assert labels.made == []


def test_a_lost_label_reply_settles_and_never_buys_twice(svc, labels, mailer):
    labels.lose_next = True
    ret = create(svc, key="lost")
    assert ret.status == Status.awaiting_label and mailer.sent == []
    ret = svc.execute(ret.id, "label", {}, "Sam", "label-again")["return_doc"]
    assert len(labels.made) == 1 and ret.status == Status.awaiting_shipment
    svc.tick()
    assert len(mailer.sent) == 1  # emailed once the label exists, and only once


# --------------------------------------------------------------------------- the email


def test_a_lost_email_reply_is_retried_with_the_same_key_and_delivered_once(svc, mailer):
    mailer.fail_next = "unknown"
    ret = create(svc)
    assert ret.email.status == "unknown"
    svc.tick()
    svc.tick()
    ret = svc.store.get(ret.id)
    assert ret.email.status == "sent"
    assert len(mailer.sent) == 1 and len({m["key"] for m in mailer.sent}) == 1


def test_an_unconfirmed_email_isnt_retried_after_a_day(svc, mailer, clock):
    mailer.fail_next = "unknown"
    ret = create(svc)
    mailer.delivered_keys.discard(ret.email.key)  # pretend it never arrived
    mailer.sent.clear()
    clock.now += timedelta(hours=25)  # past what the provider remembers a key for
    svc.tick()
    ret = svc.store.get(ret.id)
    assert ret.email.status == "unconfirmed" and mailer.sent == []


def test_a_refused_email_says_so_and_resend_sends_one_more(svc, mailer):
    mailer.fail_next = "refused"
    ret = create(svc)
    assert ret.email.status == "failed" and ret.email.error
    svc.tick()
    assert mailer.sent == []  # a refusal isn't retried by itself
    ret = svc.resend_label_email(ret.id, "Sam")
    assert ret.email.status == "sent" and len(mailer.sent) == 1


def test_resend_sends_another_copy_with_a_new_key(svc, mailer):
    ret = create(svc)
    ret = svc.resend_label_email(ret.id, "Sam")
    assert len(mailer.sent) == 2 and mailer.sent[0]["key"] != mailer.sent[1]["key"]
    assert any(e.type == "label_emailed" and e.actor == "Sam" for e in ret.timeline)


def test_email_off_leaves_shopifys_label_email_and_says_so(settings, shop, labels, clock):
    svc = ReturnsService(
        settings, Store(settings.db_path), shop, labels, RecordingNotifier(settings), clock=clock
    )
    ret = create(svc)
    assert ret.email is not None and ret.email.status == "off"
    attach = next(c[1] for c in shop.calls if c[0] == "reverseDeliveryCreateWithShipping")
    assert attach["notify"] is settings.shopify_notify_customer


def test_no_customer_email_is_said_plainly(svc, shop, mailer):
    shop.orders[ORDER].email = None
    shop.orders[ORDER].customer_email = None
    ret = create(svc)
    assert ret.email.status == "no_address" and mailer.sent == []


def test_a_customer_return_is_never_emailed_by_crooks(svc, shop, mailer):
    session, _ = svc.lookup("1939", "customer@example.com", "1.2.3.4")
    from returns.models import Postage, Resolution

    ret = svc.submit(
        svc.order_for_session(session), tee(), Resolution.refund, Postage.free_label, courier="evri"
    )
    ret = svc.execute(ret.id, "approve", {"postage_mode": "label_now"}, "Sam", "ap")["return_doc"]
    assert ret.status == Status.awaiting_shipment and ret.email is None and mailer.sent == []


# --------------------------------------------------------------------------- the screen's API


def test_the_admin_routes_find_quote_create_and_resend(svc, mailer):
    from fastapi.testclient import TestClient

    from returns.app import create_app

    from .test_admin import SHOP, token

    svc.s.shopify_client_id, svc.s.shop_domain = "app-id", SHOP
    c = TestClient(create_app(svc.s, svc))
    c.headers["Authorization"] = f"Bearer {token()}"
    found = c.get("/admin/api/new-return/order", params={"ref": "#1939"}).json()
    assert found["order_id"] == ORDER and found["email"] == "customer@example.com"
    assert [ln["title"] for ln in found["lines"]] == ["Docket Tee", "Yard Jeans"]
    assert [d["courier"] for d in found["drop_offs"]] == ["evri", "inpost"]
    assert found["drop_offs"][0]["shops"][0]["name"] and found["email_on"] is True
    lines = [{"id": TEE, "quantity": 1, "reason": "faulty"}]
    q = c.post("/admin/api/new-return/quote", json={"order_id": ORDER, "lines": lines}).json()
    assert q["default_refund_pence"] == 2500 and q["default_refund"] == "£25.00"
    body = {
        "order_id": ORDER,
        "lines": lines,
        "refund_pence": 2500,
        "courier": "evri",
        "idempotency_key": "screen-key-1",
    }
    made = c.post("/admin/api/new-return", json=body).json()
    assert made["origin"] == "staff" and made["email"]["ok"] is True
    assert "resend_email" in made["actions"]
    again = c.post("/admin/api/new-return", json=body).json()
    assert again["id"] == made["id"] and len(mailer.sent) == 1
    resent = c.post(f"/admin/api/returns/{made['id']}/resend-email").json()
    assert resent["email"]["ok"] and len(mailer.sent) == 2
    assert c.get("/admin/api/new-return/order", params={"ref": "999999"}).status_code == 404
