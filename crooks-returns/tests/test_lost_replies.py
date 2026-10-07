"""A change whose answer is lost is UNKNOWN, never repeated blindly.

Shopify can make a return or hand a label to the customer and then drop the connection (or
answer 502). Sending it again would make a second return, or email the customer twice; losing
our record after a label is paid would buy a second label. Each case here reads Shopify back,
or keeps what was done, instead.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from returns.models import Postage, Reason, Resolution, Selection, Status
from returns.service import ActionError, ReturnsService
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


def later(clock, minutes=3):
    # Past the time an unanswered request could still be landing in Shopify.
    clock.now = clock.now + timedelta(minutes=minutes)


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


def test_a_lost_return_create_that_made_nothing_is_sent_once_more(svc, shop, clock, monkeypatch):
    ret = submit(svc, Postage.self_ship)
    real = shop.create_return

    def no_answer(*args, **kwargs):  # the request never reached Shopify
        monkeypatch.setattr(shop, "create_return", real)
        raise ShopifyUncertain("no answer (test)")

    monkeypatch.setattr(shop, "create_return", no_answer)
    assert act(svc, ret, "approve", key="k1")["status"] == "requested"
    soon = act(svc, ret, "approve", key="k2")  # straight away: it could still be landing
    assert soon["status"] == "requested" and "still be finishing" in soon["error"]
    assert shop.returns == {}
    later(clock)
    out = act(svc, ret, "approve", key="k3")
    assert out["status"] == "awaiting_shipment"
    assert len(shop.returns) == 1  # proven absent, then made exactly once


def test_a_return_made_just_before_the_process_stopped_is_adopted(svc, shop, clock, monkeypatch):
    """The answer came back but the process died before saving it: the intent was written down
    before sending, so the next approval reads Shopify instead of making a second return."""
    ret = submit(svc, Postage.self_ship)
    real = shop.create_return

    def made_then_died(*args, **kwargs):
        real(*args, **kwargs)
        raise KeyboardInterrupt  # not an Exception: nothing after this point runs or saves

    monkeypatch.setattr(shop, "create_return", made_then_died)
    with pytest.raises(KeyboardInterrupt):
        act(svc, ret, "approve", key="k1")
    monkeypatch.setattr(shop, "create_return", real)
    restarted = ReturnsService(svc.s, svc.store, shop, svc.labels, svc.notifier, clock=clock)
    stored = restarted.store.get(ret.id)
    assert stored is not None and stored.shopify.create_unknown_at is not None
    out = act(restarted, ret, "approve", key="k2")
    assert out["status"] == "awaiting_shipment"
    assert len(shop.called("returnCreate")) == 1 and len(shop.returns) == 1


def test_a_definite_refusal_is_not_left_unknown(svc, shop):
    ret = submit(svc, Postage.self_ship)
    shop.fail.add("create_return")
    out = act(svc, ret, "approve", key="k1")
    assert out["status"] == "requested" and "did not create" in out["error"]
    assert svc.store.get(ret.id).shopify.create_unknown_at is None  # retry may create at once


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

    out = act(svc, ret, "label", key="k2")  # a person tries the label again: found, adopted
    assert out["status"] == "awaiting_shipment"
    assert len(shop.called("reverseDeliveryCreateWithShipping")) == 1  # never sent again
    assert len(labels.made) == 1  # the paid label is settled, not bought again
    saved = svc.store.get(ret.id)
    assert saved.shopify.reverse_delivery_id and saved.shopify.attach_unknown_at is None


# ------------------------------------------------------------------ an unexpected failure


def test_a_lost_label_handover_that_sent_nothing_is_sent_once_after_settling(
    svc, shop, labels, clock, monkeypatch
):
    ret = submit(svc)
    real = shop.attach_shipping

    def no_answer(*args, **kwargs):  # the request never reached Shopify
        monkeypatch.setattr(shop, "attach_shipping", real)
        raise ShopifyUncertain("no answer (test)")

    monkeypatch.setattr(shop, "attach_shipping", no_answer)
    assert act(svc, ret, "approve", key="k1")["status"] == "awaiting_label"
    soon = act(svc, ret, "label", key="k2")
    assert (
        soon["status"] == "awaiting_label"
        and shop.called("reverseDeliveryCreateWithShipping") == []
    )
    later(clock)
    out = act(svc, ret, "label", key="k3")
    assert out["status"] == "awaiting_shipment"
    assert len(shop.called("reverseDeliveryCreateWithShipping")) == 1
    assert len(labels.made) == 1


def test_a_failure_after_the_label_is_paid_keeps_it(svc, shop, labels, clock, monkeypatch):
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

    later(clock)  # the hand-over may have been sent before the failure: checked, then sent
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


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, content=b"<html>gateway</html>"),
        httpx.Response(200, json={"errors": [{"message": "Internal error"}]}),
        httpx.Response(200, json={"data": None}),
        httpx.Response(200, json=["not", "an", "object"]),
    ],
    ids=["not-json", "internal-error", "no-data", "wrong-shape"],
)
def test_an_unreadable_answer_to_a_change_is_unknown_not_failed(answer, monkeypatch):
    sent = []

    def handler(request):
        sent.append(request)
        return answer

    c = client(handler, monkeypatch)
    with pytest.raises(ShopifyUncertain):
        c._call("mutation M { returnCreate(returnInput: {}) { return { id } } }")
    assert len(sent) == 1
    with pytest.raises(ShopifyError):  # a read with the same answer is a plain error
        c._call("query Q { shop { id } }")


def test_a_change_answered_without_its_result_is_unknown(svc, monkeypatch):
    ret = submit(svc, Postage.self_ship)
    answers = {
        "returnCreate": {"returnCreate": {"return": None, "userErrors": []}},
        "reverseDeliveryCreateWithShipping": {"reverseDeliveryCreateWithShipping": None},
    }
    c = client(
        lambda r: ok(answers[next(k for k in answers if k in r.content.decode())]), monkeypatch
    )
    with pytest.raises(ShopifyUncertain):
        c.create_return(svc.store.get(ret.id), {})
    with pytest.raises(ShopifyUncertain):
        c.attach_shipping("gid://shopify/ReverseFulfillmentOrder/1", "T1", None, None, False)


def test_user_errors_are_a_refusal_not_unknown(svc, monkeypatch):
    ret = submit(svc, Postage.self_ship)
    refused = {"returnCreate": {"return": None, "userErrors": [{"message": "Not returnable"}]}}
    c = client(lambda r: ok(refused), monkeypatch)
    with pytest.raises(ShopifyError) as caught:
        c.create_return(svc.store.get(ret.id), {})
    assert not isinstance(caught.value, ShopifyUncertain)


# ------------------------------------------------------------------ ending it after an unknown


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_ending_a_return_after_a_lost_create_cancels_what_shopify_made(action, svc, shop):
    ret = submit(svc, Postage.self_ship)
    shop.lose_reply.add("create_return")
    act(svc, ret, "approve", key="k1")  # Shopify made it; the answer was lost
    (made,) = shop.returns
    out = act(svc, ret, action, key="k2")
    assert out["status"] == ("declined" if action == "decline" else "cancelled")
    assert shop.returns[made]["status"] == "CANCELED"  # no open return left behind in Shopify
    assert len(shop.called("returnCancel")) == 1


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_ending_a_return_too_soon_after_a_lost_create_waits(action, svc, shop, clock, monkeypatch):
    ret = submit(svc, Postage.self_ship)

    def no_answer(*args, **kwargs):
        raise ShopifyUncertain("no answer (test)")

    monkeypatch.setattr(shop, "create_return", no_answer)
    act(svc, ret, "approve", key="k1")
    with pytest.raises(ActionError) as caught:
        act(svc, ret, action, key="k2")
    assert caught.value.status == 409 and "still be finishing" in str(caught.value)
    assert svc.store.get(ret.id).status == Status.requested
    later(clock)
    out = act(svc, ret, action, key="k3")
    assert out["status"] in ("declined", "cancelled") and shop.called("returnCancel") == []


def test_a_cancel_without_an_answer_is_not_called_a_failure(svc, shop, monkeypatch):
    ret = submit(svc, Postage.self_ship)
    act(svc, ret, "approve", key="k1")

    def no_answer(return_id):
        raise ShopifyUncertain("no answer (test)")

    monkeypatch.setattr(shop, "cancel_return", no_answer)
    out = act(svc, ret, "cancel", key="k2")
    assert out["status"] == "awaiting_shipment" and "may already be cancelled" in out["error"]
    assert svc.store.get(ret.id).timeline[-1].type == "cancel_unknown"
