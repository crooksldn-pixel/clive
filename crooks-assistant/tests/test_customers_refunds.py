"""Has the refund landed? Shopify's own answer, said plainly (app/customers/payments.py).

George, 2 October 2026: "Clive cannot confirm a refund has landed (but I do confirm refunds through
Clive's work)."

A refund in Shopify is a record; the money going back is a transaction under it, which the payment
provider answers. The order read now carries each refund's transactions — status, gateway, card,
amount, when Shopify processed it — and each refund says, in one sentence, whether the money has
gone back. Every sentence here is built from what the fixture's Shopify reported and nothing else.
"""

from __future__ import annotations

import pytest

from app.customers import payments
from app.tools import shopify_tools
from tests.customers_world import cards, hold, result, say, world_fixture

world = pytest.fixture(world_fixture)

POLICY = "An approved refund lands on the original payment method within five to seven days."


async def _detail(world, number: int) -> tuple[dict, dict]:
    body = await say(world, f"has the refund on {number} landed?", ("shopify_find_order", {"query": str(number)}),
                     ("shopify_order_detail", lambda calls: {"order_id": calls[0].result["orders"][0]["order_id"]}))
    return body, result(world, "shopify_order_detail")


async def test_a_refund_that_succeeded_says_to_which_card_and_when(world):
    body, told = await _detail(world, 2201)
    (refund,) = told["refunds"]
    assert refund["state"] == "succeeded"
    assert refund["landed"].startswith("Refund of £45.00 to Visa ending 4242 succeeded on ")
    assert refund["landed"].endswith(" at 14:02.")
    # What it means for her: what Shopify reported, and the shop's own published line, as it is.
    assert refund["means"].startswith("Shopify shows the payment provider accepted it back to Visa ending 4242 on ")
    assert refund["means"].endswith(f"The shop's policy: {POLICY}")
    # On the card, under the money: the same sentence.
    (order,) = cards(body, "order")
    assert order["refunds"][0]["landed"] == refund["landed"] and order["refunds"][0]["state"] == "succeeded"


async def test_a_refund_still_with_the_provider_is_pending_and_says_so(world):
    _body, told = await _detail(world, 2202)
    (refund,) = told["refunds"]
    assert refund["state"] == "pending"
    assert refund["landed"].startswith("Refund of £20.00 to Visa ending 4242 is pending at the payment provider (since ")
    assert "has not confirmed the money went back" in refund["means"]


async def test_a_refund_the_provider_refused_says_why(world):
    _body, told = await _detail(world, 2190)
    (refund,) = told["refunds"]
    assert refund["state"] == "failed"
    assert refund["landed"] == "Refund of £65.00 to Visa ending 4242 failed: the card was declined."
    assert refund["means"] == "The money has not gone back: the provider refused it (the card was declined)."


def test_only_what_shopify_reports():
    """No transaction, no claim; no card details, the gateway's own name; an unknown code in its own words."""
    bare = {"createdAt": "2026-10-01T13:02:00Z", "totalRefundedSet": {"shopMoney": {"amount": "0.00", "currencyCode": "GBP"}},
            "transactions": {"edges": []}}
    assert payments.refund_state(bare)["state"] == "recorded"
    assert "Shopify shows no payment sent back for it" in payments.refund_state(bare)["landed"]
    paypal = {"createdAt": "2026-10-01T13:02:00Z", "totalRefundedSet": {"shopMoney": {"amount": "10.00", "currencyCode": "GBP"}},
              "transactions": {"edges": [{"node": {"kind": "REFUND", "status": "FAILURE", "gateway": "paypal", "formattedGateway": "PayPal",
                                                   "processedAt": "2026-10-01T13:02:00Z", "errorCode": "AMAZON_PAYMENTS_STALE",
                                                   "amountSet": {"shopMoney": {"amount": "10.00", "currencyCode": "GBP"}}, "paymentDetails": None}}]}}
    said = payments.refund_state(paypal)
    assert said["landed"] == "Refund of £10.00 to PayPal failed: amazon payments stale."
    assert payments.refund_state({"createdAt": None, "totalRefundedSet": None})["state"] == "recorded"


async def test_after_a_refund_through_clive_it_can_say_whether_it_landed(world):
    """The refund is made through CLIVE's card and his hold, proven by the refunded total moving —
    then "has it landed?" is answered from the payment provider's state, which moves on its own."""
    found = await say(world, "refund ten pounds on 2203", ("shopify_find_order", {"query": "2203"}),
                      ("shopify_refund_create", lambda calls: {"order_id": calls[0].result["orders"][0]["order_id"], "amount": "10.00"}))
    (card,) = [i["data"] for i in found["ui"] if i["type"] == "confirmation"]
    done = await hold(world, card["proposal_id"])
    assert done["status"] == "verified", done
    assert [m[0] for m in world.store.mutations] == ["refund_create"]
    shopify_tools.hydrator().forget("gid://shopify/Order/2203")
    _body, told = await _detail(world, 2203)
    assert told["refunds"][-1]["state"] == "pending"
    assert "is pending at the payment provider" in told["refunds"][-1]["landed"]
    # The provider answers later; asked again after the reads CLIVE holds have aged out, it says so.
    world.store.settle_refunds("SUCCESS")
    from app.memory.store import invalidate_for_write

    invalidate_for_write("order", "gid://shopify/Order/2203")
    shopify_tools.hydrator().forget("gid://shopify/Order/2203")
    _body, told = await _detail(world, 2203)
    assert told["refunds"][-1]["state"] == "succeeded"
    assert told["refunds"][-1]["landed"].startswith("Refund of £10.00 to Visa ending 4242 succeeded on ")
