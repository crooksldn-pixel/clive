"""The returns / exchanges foundation (§21).

Two kinds of oracle. The first is about the part that exists: a request shape that validates
what can be validated without a store — an order that shipped, lines that shipped, quantities
that exist, a reason from Shopify's own list — and the exact server-side arguments a future
`returnCreate` would be staged with. The second is about the part that deliberately does not
exist: nothing may execute, nothing may be registered that could, and the refusal must name the
scope. The second kind is what fails if somebody rushes an unsafe mutation in.
"""

from __future__ import annotations

import pytest

from app.returns import contract
from app.returns.contract import (
    InvalidRequest,
    NotAvailable,
    ReturnLine,
    ReturnRequest,
)

FULFILLED_ORDER = {
    "order_id": "gid://shopify/Order/1",
    "fulfillment": "FULFILLED",
    "fulfillments": [
        {"fulfillment_id": "gid://shopify/Fulfillment/1",
         "line_items": [{"fulfillment_line_item_id": "gid://shopify/FulfillmentLineItem/1", "quantity": 2}]},
    ],
}


def _request(**over) -> ReturnRequest:
    base = dict(
        order_id="gid://shopify/Order/1",
        lines=(ReturnLine("gid://shopify/FulfillmentLineItem/1", 1, reason="SIZE_TOO_SMALL"),),
    )
    base.update(over)
    return ReturnRequest(**base)


# ------------------------------------------------------------------ the part that exists


def test_a_return_needs_an_order_that_shipped():
    unfulfilled = dict(FULFILLED_ORDER, fulfillment="UNFULFILLED")
    with pytest.raises(InvalidRequest, match="nothing has shipped"):
        _request().validate(order=unfulfilled)
    _request().validate(order=FULFILLED_ORDER)


def test_a_return_cannot_ask_for_more_than_shipped():
    with pytest.raises(InvalidRequest, match="only 2 of that line shipped"):
        _request(lines=(ReturnLine("gid://shopify/FulfillmentLineItem/1", 3),)).validate(order=FULFILLED_ORDER)
    with pytest.raises(InvalidRequest, match="did not ship on this order"):
        _request(lines=(ReturnLine("gid://shopify/FulfillmentLineItem/9", 1),)).validate(order=FULFILLED_ORDER)


def test_what_shipped_is_unknown_on_this_build_and_unknown_is_not_nothing():
    """The order read asks a fulfilment for its id, status and tracking — not for its LINE
    ITEMS, which is what a return is against. So for an order as the Mac reads it today the
    quantity check cannot be made, and treating that as "nothing shipped" would refuse every
    honest return for the wrong reason. It is named as missing instead."""
    as_read_today = {
        "order_id": "gid://shopify/Order/1", "fulfillment": "FULFILLED",
        "fulfillments": [{"fulfillment_id": "gid://shopify/Fulfillment/1", "status": "SUCCESS",
                          "carrier": "Royal Mail", "number": "AB1"}],
    }
    assert contract._shipped_lines(as_read_today) is None
    _request().validate(order=as_read_today)        # not refused for the wrong reason
    assert any("fulfillmentLineItems" in item for item in contract.RETURN.missing)
    assert any("fulfillmentLineItems" in item for item in contract.EXCHANGE.missing)
    # And with the line items present, the check is made.
    assert contract._shipped_lines(FULFILLED_ORDER) == {"gid://shopify/FulfillmentLineItem/1": 2}


def test_a_reason_must_be_one_of_shopifys_own():
    with pytest.raises(InvalidRequest, match="not one of Shopify's return reasons"):
        _request(lines=(ReturnLine("gid://shopify/FulfillmentLineItem/1", 1, reason="HE_DIDNT_LIKE_IT"),)).validate()
    assert "SIZE_TOO_SMALL" in contract.REASONS and "UNWANTED" in contract.REASONS


def test_the_same_line_cannot_be_listed_twice_and_a_quantity_must_be_real():
    line = ReturnLine("gid://shopify/FulfillmentLineItem/1", 1)
    with pytest.raises(InvalidRequest, match="listed twice"):
        _request(lines=(line, line)).validate(order=FULFILLED_ORDER)
    with pytest.raises(InvalidRequest, match="quantity of at least one"):
        _request(lines=(ReturnLine("gid://shopify/FulfillmentLineItem/1", 0),)).validate()
    with pytest.raises(InvalidRequest, match="at least one line"):
        ReturnRequest(order_id="gid://shopify/Order/1").validate()


def test_the_plan_is_the_arguments_the_mutation_would_take():
    planned = contract.plan("return_create", _request(notify_customer=True), order=FULFILLED_ORDER)
    assert planned["mutation"] == "returnCreate"
    assert planned["arguments"] == {
        "orderId": "gid://shopify/Order/1",
        "returnLineItems": [{"fulfillmentLineItemId": "gid://shopify/FulfillmentLineItem/1",
                             "quantity": 1, "returnReason": "SIZE_TOO_SMALL"}],
        "notifyCustomer": True,
    }
    assert planned["available"] is False
    assert "write_returns" in planned["scopes"]
    # And the preconditions and the proof are named, because that is what makes it reviewable.
    assert any("shipped" in p for p in planned["preconditions"])
    assert "read the order's returns back" in planned["verification"]


def test_an_exchange_carries_what_goes_out_instead():
    planned = contract.plan(
        "return_exchange",
        _request(exchange_variants=(("gid://shopify/ProductVariant/7", 1),)),
        order=FULFILLED_ORDER,
    )
    assert planned["arguments"]["exchangeLineItems"] == [{"variantId": "gid://shopify/ProductVariant/7", "quantity": 1}]
    assert "write_order_edits" in planned["scopes"]
    with pytest.raises(InvalidRequest, match="variant and a quantity"):
        _request(exchange_variants=(("", 1),)).validate(order=FULFILLED_ORDER)


# ------------------------------------------------------------------ the part that does not


def test_nothing_can_be_staged_and_the_refusal_names_the_scope():
    for key, capability in contract.CAPABILITIES.items():
        with pytest.raises(NotAvailable) as raised:
            contract.stage(key, _request(), order=FULFILLED_ORDER)
        assert raised.value.missing, f"{key} refused without saying what is missing"
        assert capability.scopes, f"{key} does not name a scope"
        assert all(scope in capability.refusal() for scope in capability.scopes[:1])
        assert capability.available is False


def test_a_bad_request_is_refused_as_a_bad_request_before_availability():
    """Order matters: "that line did not ship" is more useful than "returns are not built",
    and it is the error the future implementation will raise too."""
    with pytest.raises(InvalidRequest):
        contract.stage("return_create", _request(lines=(ReturnLine("nope", 1),)), order=FULFILLED_ORDER)


def test_no_return_mutation_is_registered_anywhere():
    """The check that fails if somebody rushes it in: no registered write tool, and no
    reviewed Shopify operation, makes a return, an exchange, a replacement or a resend in Shopify
    itself. Unknown writes fail closed (invariant 14), so nothing CLIVE holds can execute one.

    Since 3 October (DEC-066) a return's changes go only through CROOKS Returns, the owner's own
    service, which makes the Shopify return itself: CLIVE's one return write is `return_action`,
    which calls that service's actions after the owner's approval and never Shopify. So the
    check is now exact rather than absent: that one operation, sent to CROOKS Returns, and the
    four returns tools by name, and no reviewed Shopify mutation whose document names a return,
    a reverse delivery or a reverse fulfilment."""
    import app.tools.batch_tools  # noqa: F401
    import app.tools.gmail_writes  # noqa: F401
    import app.tools.returns_tools  # noqa: F401
    import app.tools.shopify_writes  # noqa: F401
    from app.clients import crooks_returns
    from app.clients.shopify import REVIEWED_MUTATIONS
    from app.tools import registry

    specs = registry.all_specs()
    operations = {s.write.operation for s in specs if s.write is not None}
    operations |= {s.batch.operation for s in specs if s.batch is not None}
    for word in ("return", "exchange", "replacement", "resend"):
        named = [op for op in operations if word in op]
        assert named == (["return_action"] if word == "return" else []), f"a {word} mutation is registered: {named}"
    action = next(s for s in specs if s.write is not None and s.write.operation == "return_action")
    assert action.write.service == crooks_returns.NAME and action.write.mutation == "returns:action"
    assert sorted(s.name for s in specs if "return" in s.name or "exchange" in s.name) == [
        "return_action", "return_find", "returns_open", "returns_stats"]
    words = ("return", "reversedelivery", "reversefulfillment", "exchange")
    assert not [name for name, reviewed in REVIEWED_MUTATIONS.items()
                if any(word in reviewed.document.lower() for word in words)], "a Shopify return mutation is reviewed"


async def test_the_four_rows_say_not_implemented_and_name_the_scope_to_grant():
    from app.capabilities import families
    from app.families import load_all

    load_all()
    table = await families.states(None)
    for key, capability in contract.CAPABILITIES.items():
        row = table[key]
        assert row["state"] == "NOT_IMPLEMENTED" and row["offerable"] is False
        assert row["scope"] == capability.scopes[0]
        assert row["tools"] == [] and row["operations"] == []
        line = families.words({key: row})[0]
        # The instruction lives once at the head of the block (app/routes/turn.py
        # FAMILY_LINE_PREFIX), not on every line: with seven unavailable families it was
        # 287 characters a turn of the same sentence.
        assert capability.scopes[0] in line and "NOT_IMPLEMENTED" in line
        assert "Do not attempt" not in line, line


async def test_the_rows_carry_the_mutation_and_the_verification_for_whoever_builds_it():
    from app.capabilities import families
    from app.families import load_all

    load_all()
    family = families.get("return_create")
    assert family is not None
    assert family.extra["mutation"] == "returnCreate"
    assert family.extra["scopes_required"] == list(contract.RETURN.scopes)
    assert family.extra["verification"]
    assert family.extra["preconditions"]


def test_the_owner_can_be_told_all_four_in_a_sentence_each():
    lines = contract.words()
    assert len(lines) == 4
    assert all("not available" in line for line in lines)
    assert any("write_returns" in line for line in lines)
