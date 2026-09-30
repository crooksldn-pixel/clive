"""A draft order's payment link: "what's the link for D12" answered with the real URL.

Shopify hosts an invoice page for every draft order, and its `invoiceUrl` is the link the
customer pays through. `shopify_find_order` given a draft's name or id reads that draft and
returns the URL exactly as Shopify gave it — never one made up from a name or an id.
"""

from __future__ import annotations

import pytest

from app.tools import registry, shopify_tools
from app.tools.gate import Tier, classify
from tests.conftest import FakeShopify

INVOICE_URL = "https://crooks-ldn.myshopify.com/68831502560/invoices/5f1d0c7e2a9b4e33b1c0a7d9e6f41b2c"


def _draft(number: int = 12, *, url: str | None = INVOICE_URL, status: str = "OPEN", order: dict | None = None) -> dict:
    return {
        "id": f"gid://shopify/DraftOrder/{1000 + number}",
        "name": f"#D{number}",
        "status": status,
        "createdAt": "2026-09-30T10:00:00Z",
        "invoiceUrl": url,
        "invoiceSentAt": None,
        "totalPriceSet": {"shopMoney": {"amount": "85.00", "currencyCode": "GBP"}},
        "customer": {"id": "gid://shopify/Customer/77", "displayName": "Anna Denning",
                     "defaultEmailAddress": {"emailAddress": "anna@example.com"}},
        "order": order,
    }


def _named(*nodes: dict) -> dict:
    return {"data": {"draftOrders": {"edges": [{"node": n} for n in nodes]}}}


@pytest.mark.parametrize("said", ["#D12", "D12", "d 12", "#d12", "draft 12", "draft #D12", "draft order D12", "Draft order #D012"])
def test_a_draft_is_recognised_by_its_name_however_it_is_said(said):
    assert shopify_tools._draft_ref(said) == ("name", "#D12")


@pytest.mark.parametrize("said", ["1928", "#1928", "CROOKS-1928", "Anna Denning", "anna@example.com", "Dan", ""])
def test_an_order_or_a_person_is_not_taken_for_a_draft(said):
    assert shopify_tools._draft_ref(said) is None


async def test_the_payment_link_is_the_invoice_url_shopify_returned():
    client = FakeShopify([_named(_draft(120), _draft(12))])
    shopify_tools.bind(client)
    result = await shopify_tools.shopify_find_order("#D12")

    (draft,) = result["draft_orders"]
    assert draft["invoice_url"] == INVOICE_URL
    assert draft["draft_name"] == "#D12"
    assert draft["draft_order_id"] == "gid://shopify/DraftOrder/1012"
    assert draft["status"] == "OPEN"
    assert draft["total"] == "85.00 GBP"
    assert result["orders"] == []
    assert "exactly" in result["instruction"]
    # One read, of drafts, by the name — no order search, and nothing written.
    ((query, variables),) = client.queries
    assert "draftOrders(" in query and "invoiceUrl" in query
    assert "mutation" not in query.lower()
    assert variables["q"] == "D12"


async def test_a_draft_is_read_by_its_id_too():
    client = FakeShopify([{"data": {"draftOrder": _draft(12)}}])
    shopify_tools.bind(client)
    result = await shopify_tools.shopify_find_order("gid://shopify/DraftOrder/1012")

    assert result["draft_orders"][0]["invoice_url"] == INVOICE_URL
    ((query, variables),) = client.queries
    assert "draftOrder(id: $id)" in query
    assert variables == {"id": "gid://shopify/DraftOrder/1012"}


async def test_a_near_name_is_not_the_draft_and_no_link_is_guessed():
    """Free-text search finds D120 for "D12"; it is not D12, so nothing is returned."""
    shopify_tools.bind(FakeShopify([_named(_draft(120))]))
    result = await shopify_tools.shopify_find_order("D12")

    assert result["draft_orders"] == []
    assert "No draft order" in result["note"]
    assert "invoices" not in str(result)


async def test_a_draft_the_store_does_not_have_is_said_as_not_found():
    shopify_tools.bind(FakeShopify([{"data": {"draftOrder": None}}]))
    result = await shopify_tools.shopify_find_order("gid://shopify/DraftOrder/999")
    assert result["draft_orders"] == []
    assert "No draft order" in result["note"]


async def test_no_link_from_shopify_is_said_and_never_filled_in():
    shopify_tools.bind(FakeShopify([_named(_draft(12, url=None))]))
    result = await shopify_tools.shopify_find_order("#D12")

    assert result["draft_orders"][0]["invoice_url"] is None
    assert "no invoice link" in result["note"]
    assert "instruction" not in result


async def test_a_completed_draft_names_the_order_it_became():
    order = {"id": "gid://shopify/Order/5001", "name": "CROOKS-1990"}
    shopify_tools.bind(FakeShopify([_named(_draft(12, status="COMPLETED", order=order))]))
    result = await shopify_tools.shopify_find_order("#D12")

    draft = result["draft_orders"][0]
    assert draft["status"] == "COMPLETED"
    assert draft["order_number"] == "CROOKS-1990"
    assert draft["invoice_url"] == INVOICE_URL


async def test_an_order_number_still_searches_orders():
    client = FakeShopify([{"data": {"orders": {"edges": []}}}])
    shopify_tools.bind(client)
    result = await shopify_tools.shopify_find_order("1928")
    assert result["matched_on"] == "name:1928"
    assert "draft_orders" not in result


# ----------------------------------------------------------- through a tool call, after creation


def test_the_gate_runs_a_draft_lookup_as_a_read():
    decision = classify("shopify_find_order", {"query": "#D12"})
    assert decision.executes
    assert decision.tier is Tier.GREEN


async def test_asking_for_a_created_drafts_link_through_the_tool_returns_it():
    """The order family prepares a draft (draftOrderCreate) and keeps its name, "#D7"
    (app/families/order_create.py). Asked afterwards for that draft's payment link, the
    registered tool returns the invoice URL of THAT draft, as Shopify holds it."""
    created = _draft(7, url="https://crooks-ldn.myshopify.com/68831502560/invoices/0a1b2c3d4e5f")
    client = FakeShopify([_named(created)])
    shopify_tools.bind(client)

    decision = classify("mcp__crooks__shopify_find_order", {"query": created["name"]})
    assert decision.executes
    result = await registry.invoke("shopify_find_order", {"query": created["name"]}, timeout_s=5)

    assert result["draft_orders"][0]["invoice_url"] == created["invoiceUrl"]
    assert result["draft_orders"][0]["draft_order_id"] == created["id"]
    assert client.queries[0][1]["q"] == "D7"


def test_the_tool_says_it_gives_a_drafts_payment_link():
    spec = registry.get("shopify_find_order")
    assert "invoice_url" in spec.description and "#D12" in spec.description
    assert len(spec.description) <= 600
