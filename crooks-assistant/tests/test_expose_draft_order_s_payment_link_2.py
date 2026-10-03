"""A draft order's payment link: asked for, it is found and given — Shopify's own invoice URL,
read from the draft, never made up.

There was no way to get it: no tool read a draft order at all, so "what's the payment link for
#D12" was answered with "I can't find that". shopify_find_order now takes a draft's name (or
its id) and returns the draft with the `invoiceUrl` Shopify holds for it.
"""

from __future__ import annotations

import json

import pytest

from app.tools import registry, shopify_tools
from app.tools.gate import Disposition, classify
from tests.conftest import FakeShopify

INVOICE_URL = "https://crooks-ldn.myshopify.com/58817151183/invoices/2a1b3c4d5e6f7a8b9c0d"

DRAFT_NODE = {
    "id": "gid://shopify/DraftOrder/1024",
    "name": "#D12",
    "status": "OPEN",
    "createdAt": "2026-09-30T10:02:00Z",
    "invoiceUrl": INVOICE_URL,
    "totalPriceSet": {"shopMoney": {"amount": "95.00", "currencyCode": "GBP"}},
    "customer": {"id": "gid://shopify/Customer/77", "displayName": "Anna Denning"},
    "order": None,
}


def drafts(*nodes: dict) -> dict:
    return {"data": {"draftOrders": {"edges": [{"node": n} for n in nodes]}}}


def bind(*responses: dict) -> FakeShopify:
    client = FakeShopify(list(responses))
    shopify_tools.bind(client, threads_for=lambda *a, **k: [])
    return client


@pytest.mark.parametrize("said", ["#D12", "D12", "d12", "draft 12", "Draft order #D12", "draft #12"])
async def test_a_draft_named_as_the_owner_says_it_returns_its_real_invoice_url(said):
    client = bind(drafts(DRAFT_NODE))

    result = await shopify_tools.shopify_find_order(said)

    assert result["payment_link"] == INVOICE_URL
    assert result["draft_orders"][0]["invoice_url"] == INVOICE_URL
    assert result["draft_orders"][0]["name"] == "#D12"
    assert result["draft_orders"][0]["draft_order_id"] == "gid://shopify/DraftOrder/1024"
    assert INVOICE_URL in result["note"]
    # One read, of drafts, asking Shopify for the invoice URL — a read, never a mutation.
    [(query, variables)] = client.queries
    assert "draftOrders(" in query and "invoiceUrl" in query
    assert "mutation" not in query
    assert variables["q"] == "D12"


async def test_a_draft_by_its_id_is_read_directly():
    client = bind({"data": {"draftOrder": DRAFT_NODE}})

    result = await shopify_tools.shopify_find_order("gid://shopify/DraftOrder/1024")

    assert result["payment_link"] == INVOICE_URL
    [(query, variables)] = client.queries
    assert "draftOrder(id: $id)" in query and "invoiceUrl" in query
    assert variables == {"id": "gid://shopify/DraftOrder/1024"}


async def test_only_the_draft_of_exactly_that_name_is_taken():
    """The search returns #D120 and #D121 for "D12"; neither is #D12, so the newest drafts are
    looked through, and #D12's own link is the one given."""
    other = {**DRAFT_NODE, "id": "gid://shopify/DraftOrder/2000", "name": "#D120",
             "invoiceUrl": "https://crooks-ldn.myshopify.com/58817151183/invoices/ffffffffffffffff"}
    client = bind(drafts(other, {**other, "name": "#D121"}), drafts(other, DRAFT_NODE))

    result = await shopify_tools.shopify_find_order("#D12")

    assert result["payment_link"] == INVOICE_URL
    assert len(client.queries) == 2
    assert client.queries[1][1] == {"q": None, "n": shopify_tools.MAX_DRAFTS_SCANNED}


async def test_a_draft_that_is_not_there_gets_no_link_and_says_so():
    bind(drafts(), drafts())

    result = await shopify_tools.shopify_find_order("#D99")

    assert result["payment_link"] is None
    assert result["draft_orders"] == []
    assert "No draft order #D99" in result["note"]
    assert "http" not in json.dumps(result), "a link that Shopify did not give is never made"


async def test_a_draft_with_no_invoice_url_is_said_to_have_none():
    bind(drafts({**DRAFT_NODE, "invoiceUrl": None}))

    result = await shopify_tools.shopify_find_order("#D12")

    assert result["payment_link"] is None
    assert "no payment link" in result["note"]
    assert "http" not in json.dumps(result)


async def test_a_completed_draft_says_which_order_it_became():
    completed = {**DRAFT_NODE, "status": "COMPLETED", "order": {"id": "gid://shopify/Order/9", "name": "CROOKS-1930"}}
    bind(drafts(completed))

    result = await shopify_tools.shopify_find_order("#D12")

    assert result["payment_link"] == INVOICE_URL
    assert result["draft_orders"][0]["completed_as_order"] == "CROOKS-1930"
    assert "CROOKS-1930" in result["note"]


def test_a_long_run_of_whitespace_is_read_at_once():
    """The draft's name is matched on the query with its whitespace collapsed. On the raw query,
    side-by-side `\\s*` runs made "draft" and a few hundred spaces take seconds, and a few
    thousand take hours, with the event loop blocked the whole time."""
    import time

    started = time.perf_counter()
    assert shopify_tools._draft_ref("draft" + " " * 5000 + "x") is None
    assert shopify_tools._draft_ref("#" + "\t" * 5000 + "D") is None
    assert shopify_tools._draft_ref("  draft   order \t #D12 ") == "#D12"
    assert time.perf_counter() - started < 1.0
    # A draft's number is a number of sensible length; anything longer is not a draft.
    assert shopify_tools._draft_ref("D" + "1" * 11) is None


async def test_order_numbers_and_names_are_not_taken_for_drafts():
    assert shopify_tools._draft_ref("1928") is None
    assert shopify_tools._draft_ref("#1928") is None
    assert shopify_tools._draft_ref("CROOKS-1928") is None
    assert shopify_tools._draft_ref("Dave") is None
    assert shopify_tools._draft_ref("gid://shopify/Order/1") is None
    # An order number still searches orders, as it always did.
    order = {"id": "gid://shopify/Order/1", "name": "CROOKS-1928", "createdAt": "2026-09-07T09:14:00Z",
             "processedAt": "2026-09-07T09:14:00Z", "displayFulfillmentStatus": "UNFULFILLED",
             "displayFinancialStatus": "PAID", "currentTotalPriceSet": {"shopMoney": {"amount": "1", "currencyCode": "GBP"}},
             "customer": None, "lineItems": {"edges": []}}
    client = bind({"data": {"orders": {"edges": [{"node": order}]}}}, {"data": {"orders": {"edges": []}}})
    await shopify_tools.shopify_find_order("1928")
    assert "draftOrder" not in client.queries[0][0]


def test_the_gate_runs_the_draft_lookup_as_a_read():
    decision = classify("shopify_find_order", {"query": "#D12"})
    assert decision.disposition is Disposition.EXECUTE_NOW


def test_the_model_is_told_where_a_payment_link_comes_from():
    spec = registry.get("shopify_find_order")
    said = spec.input_schema["properties"]["query"]["description"]
    assert "draft" in said and "payment link" in said


async def test_asking_for_the_payment_link_after_the_draft_is_made_returns_it():
    """The draft the order flow made is named as the flow names it ("#D12"); asked for through
    the tool call itself, its link comes back as Shopify holds it."""
    created = {"data": {"draftOrderCreate": {"draftOrder": DRAFT_NODE, "userErrors": []}}}
    name = created["data"]["draftOrderCreate"]["draftOrder"]["name"]
    bind(drafts(DRAFT_NODE))

    result = await registry.invoke("shopify_find_order", {"query": name}, timeout_s=5)

    assert result["payment_link"] == INVOICE_URL


def test_the_tool_block_stays_within_its_budget():
    """The ceiling tests/test_registry.py holds the block the model reads to: what this change
    added to shopify_find_order's schema was paid for in its own description."""
    from app.families import load_all
    from app.people import tools as _people_tools  # noqa: F401
    from app.providers.max_agent_sdk import withheld_tools
    from app.tools import (  # noqa: F401
        analytics_tools,
        batch_tools,
        close_screen,
        display_tools,
        engineering_tools,
        gmail_tools,
        gmail_writes,
        instagram_tools,
        interaction_tools,
        ship24_tools,
        shopify_writes,
        show_again,
    )
    from app.work import tools as _work_tools  # noqa: F401

    # The team's tools (app/people, app/work) are offered by app/runtime.py too: imported here so
    # the block is counted as tests/test_registry.py counts it.

    load_all()
    specs = registry.all_specs()
    offered = [s for s in specs if s.name not in withheld_tools(specs, writes_enabled=True)]
    total = sum(len(json.dumps({"name": s.name, "description": s.description, "input_schema": s.input_schema})) for s in offered)
    # The same ceiling as tests/test_registry.py, moved with it: 43,902 when this change fitted
    # alone, 43,918 once closing an objective out landed beside it (+16, measured; that file says
    # tool by tool where the bytes went), 46,131 with the team's four tools (+2,213, measured),
    # 46,787 with a custom item on an existing order (shopify_order_add_custom_item, +656, measured),
    # and 46,851 with work_note's `flag` (+64, measured), and 47,330 with parcel tracking
    # (track_parcel, +479, measured), and 47,708 with a number on an objective (objective_open and
    # objective_note's `number`, +378, measured), 48,272 with CLIVE looking at its own
    # interaction (interaction_review, +564, measured), and 49,272 with the customers workstream
    # (shopify_checkout_link_send and the lookup, history and refund fields, +1,000, measured).
    assert total <= 49_272, f"the tool block is {total} bytes"
