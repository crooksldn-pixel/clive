"""The Resend request as Resend documents it, and what each kind of answer means."""

import base64
import json
from typing import Any

import httpx
import pytest

from pydantic import SecretStr

from returns.mailer import (
    EmailNotReached,
    EmailRefused,
    EmailUncertain,
    ResendMailer,
    build_mailer,
)
from returns.settings import Settings

MSG: dict[str, Any] = dict(
    to="customer@example.com",
    subject="Your CROOKS return label",
    text="hi",
    html_body='<img src="cid:return-qr">',
    key="ret_1:label-email:1",
    attachments=[
        {"filename": "return-qr.png", "content": b"\x89PNG", "content_id": "return-qr"},
        {"filename": "return-label.pdf", "content": b"%PDF"},
    ],
)


def mailer(handler) -> ResendMailer:
    return ResendMailer(
        "re_test",
        "CROOKS <orders@crooksldn.com>",
        "help@crooksldn.com",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_the_request_carries_the_key_and_the_inline_qr():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"], seen["body"] = request.headers, json.loads(request.content)
        return httpx.Response(200, json={"id": "em_123"})

    assert mailer(handler).send(**MSG) == "em_123"
    assert seen["headers"]["Idempotency-Key"] == "ret_1:label-email:1"
    assert seen["headers"]["Authorization"] == "Bearer re_test"
    body = seen["body"]
    assert body["to"] == ["customer@example.com"] and body["reply_to"] == "help@crooksldn.com"
    qr, pdf = body["attachments"]
    assert qr == {
        "filename": "return-qr.png",
        "content": base64.b64encode(b"\x89PNG").decode(),
        "content_id": "return-qr",
    }
    assert "content_id" not in pdf


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503])
def test_no_clear_answer_is_unknown(status):
    with pytest.raises(EmailUncertain):
        mailer(lambda r: httpx.Response(status)).send(**MSG)


def test_a_refusal_is_a_refusal():
    with pytest.raises(EmailRefused):
        mailer(lambda r: httpx.Response(422, json={"message": "bad"})).send(**MSG)


def test_never_connecting_is_not_sent_but_a_lost_reply_is_unknown():
    def refused(r):
        raise httpx.ConnectError("no route")

    def lost(r):
        raise httpx.ReadTimeout("timed out")

    with pytest.raises(EmailNotReached):
        mailer(refused).send(**MSG)
    with pytest.raises(EmailUncertain):
        mailer(lost).send(**MSG)


def test_email_is_off_unless_resend_and_a_key_are_set():
    assert build_mailer(Settings()).enabled is False
    assert build_mailer(Settings(email_provider="resend")).enabled is False
    assert (
        build_mailer(Settings(email_provider="resend", resend_api_key=SecretStr("re_x"))).enabled
        is True
    )
