"""A change whose answer is lost is UNKNOWN, never repeated blindly.

Shopify can make a return or hand a label to the customer and then drop the connection (or
answer 502). Sending it again would make a second return, or email the customer twice; losing
our record after a label is paid would buy a second label. Each case here reads Shopify back,
or keeps what was done, instead.
"""

from __future__ import annotations

import httpx
import pytest

from returns.models import Postage, Reason, Resolution, Selection, Status
from returns.service import ActionError
from returns.settings import Settings
from returns.shopify import GraphQLShopify, ShopifyError, ShopifyUncertain

from .test_service import TEE, act, order


def submit(svc, postage=Postage.free_label):
    # Store credit comes with a free label; a refund lets the customer post it themselves.
    return svc.submit(
        order(svc),
        [Selection(fulfillment_line_item_id=TEE, quantity=1, reason=Reason.too_small)],
        Resolution.store_credit if postage == Postage.free_label else Resolution.refund,
        postage,
        None,
    )


# ------------------------------------------------------------------ returnCreate


def test_a_lost_return_create_is_adopted_never_made_twice(svc, shop):
    ret = submit(svc, Postage.self_ship)
    shop.lose_reply.add("create_return")
    first = act(svc, ret, "approve", key="k1")
    assert first["status"] == "requested" and "may have created" in first["error"]
    assert len(shop.called("returnCreate")) == 1 and len(shop.returns) == 1

    second = act(svc, ret, "approve", key="k2")  # a person approves again
    assert second["status"] == "awaiting_shipment" and not second["error"]
    assert len(shop.called("returnCreate")) == 1  # never sent again
    assert shop.called("orderReturns")  # read back first
    saved = svc.store.get(ret.id)
    assert saved.shopify.return_id == next(iter(shop.returns))
    assert saved.shopify.create_unknown_at is None
    assert any(e.type == "approve_reconciled" and e.verified for e in saved.timeline)


def test_a_lost_return_create_that_made_nothing_is_sent_once_more(svc, shop, monkeypatch):
    ret = submit(svc, Postage.self_ship)
    real = shop.create_return

    def no_answer(*args, **kwargs):  # the request never reached Shopify
        monkeypatch.setattr(shop, "create_return", real)
        raise ShopifyUncertain("no answer (test)")

    monkeypatch.setattr(shop, "create_return", no_answer)
    assert act(svc, ret, "approve", key="k1")["status"] == "requested"
    out = act(svc, ret, "approve", key="k2")
    assert out["status"] == "awaiting_shipment"
    assert len(shop.returns) == 1  # proven absent, then made exactly once


def test_two_possible_returns_stop_for_a_person(svc, shop):
    ret = submit(svc, Postage.self_ship)
    shop.lose_reply.add("create_return")
    act(svc, ret, "approve", key="k1")
    (only,) = shop.returns.values()
    twin = {**only, "id": "gid://shopify/Return/twin"}
    twin["created"] = {**only["created"], "return_id": twin["id"]}
    shop.returns[twin["id"]] = twin
    out = act(svc, ret, "approve", key="k2")
    assert out["status"] == "requested" and "2 returns" in out["error"]
    assert len(shop.called("returnCreate")) == 1


def test_an_unreadable_shopify_never_sends_again(svc, shop, monkeypatch):
    ret = submit(svc, Postage.self_ship)
    shop.lose_reply.add("create_return")
    act(svc, ret, "approve", key="k1")

    def down(order_id):
        raise ShopifyError("Shopify is busy")

    monkeypatch.setattr(shop, "order_returns", down)
    out = act(svc, ret, "approve", key="k2")
    assert out["status"] == "requested" and "nothing was sent again" in out["error"]
    assert len(shop.called("returnCreate")) == 1


# ------------------------------------------------------------------ the label hand-over


def test_a_lost_label_handover_is_checked_never_emailed_twice(svc, shop, labels):
    ret = submit(svc)  # free label: bought at approval
    shop.lose_reply.add("attach_shipping")
    first = act(svc, ret, "approve", key="k1")
    assert (
        first["status"] == "awaiting_label" and "may already be with the customer" in first["error"]
    )
    assert len(labels.made) == 1

    out = act(svc, ret, "label", key="k2")  # a person tries the label again
    assert out["status"] == "awaiting_shipment"
    assert len(shop.called("reverseDeliveryCreateWithShipping")) == 1  # never sent again
    assert len(labels.made) == 1  # the paid label is settled, not bought again
    saved = svc.store.get(ret.id)
    assert saved.shopify.reverse_delivery_id and not saved.shopify.attach_unknown


# ------------------------------------------------------------------ an unexpected failure


def test_a_failure_after_the_label_is_paid_keeps_it(svc, shop, labels, monkeypatch):
    ret = submit(svc)
    real = shop.attach_shipping

    def crash(*args, **kwargs):  # e.g. a bug, or an error nobody expected
        monkeypatch.setattr(shop, "attach_shipping", real)
        raise RuntimeError("boom")

    monkeypatch.setattr(shop, "attach_shipping", crash)
    with pytest.raises(ActionError) as caught:
        act(svc, ret, "approve", key="k1")
    assert caught.value.status == 503 and "interrupted" in str(caught.value)
    saved = svc.store.get(ret.id)
    assert saved.postage.label_ref and saved.postage.label_file_id  # the paid label survives
    assert saved.shopify.return_id
    assert any(e.type == "action_interrupted" for e in saved.timeline)

    out = act(svc, ret, "approve", key="k2")
    assert out["status"] == "awaiting_shipment"
    assert len(labels.made) == 1  # settled, never bought twice
    assert len(shop.called("returnCreate")) == 1
    assert svc.store.get(ret.id).status == Status.awaiting_shipment


# ------------------------------------------------------------------ the HTTP client


def client(handler, monkeypatch) -> GraphQLShopify:
    monkeypatch.setattr("returns.shopify.time.sleep", lambda s: None)
    s = Settings(shopify_auth_mode="static_token", shopify_static_token="t", db_path=":memory:")
    c = GraphQLShopify(s)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def ok(data):
    return httpx.Response(200, json={"data": data})


@pytest.mark.parametrize("failure", ["502", "timeout", "dropped"])
def test_a_change_without_a_key_is_sent_once(failure, monkeypatch):
    sent = []

    def handler(request):
        sent.append(request)
        if failure == "502":
            return httpx.Response(502)
        if failure == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        raise httpx.RemoteProtocolError("closed", request=request)

    c = client(handler, monkeypatch)
    with pytest.raises(ShopifyUncertain):
        c._call("mutation M { returnCreate(returnInput: {}) { return { id } } }")
    assert len(sent) == 1


def test_a_change_with_a_key_and_a_read_are_retried(monkeypatch):
    answers = iter([httpx.Response(502), ok({"x": 1}), "timeout", ok({"y": 2})])

    def handler(request):
        a = next(answers)
        if a == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return a

    c = client(handler, monkeypatch)
    assert c._call(
        "mutation M($k: String!) { returnProcess(input: {}) @idempotent(key: $k) { x } }"
    ) == {"x": 1}
    assert c._call("query Q { shop { id } }") == {"y": 2}


def test_a_read_that_never_answers_is_an_error_not_a_crash(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ShopifyError):
        client(handler, monkeypatch)._call("query Q { shop { id } }")


def test_a_rate_limited_change_is_safe_to_repeat(monkeypatch):
    answers = iter([httpx.Response(429), ok({"returnCreate": {"return": {"id": "r"}}})])
    c = client(lambda r: next(answers), monkeypatch)
    assert c._call("mutation M { returnCreate(returnInput: {}) { return { id } } }")
