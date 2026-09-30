"""A draft order's payment link, read from Shopify and handed back exactly.

The owner asked for a draft order's payment link and was told it could not be found: no tool
read a draft's invoice URL. `shopify_find_order` now answers a draft's name ("D12", "#D12",
"draft 12") or its id with the draft's `invoiceUrl` as Shopify gives it — a read the gate
already runs, never a link made up.
"""

from __future__ import annotations

import pytest

from app.tools import registry, shopify_tools
from app.tools.gate import Disposition, classify
from tests.conftest import FakeShopify

INVOICE_URL = "https://crooks-ldn.myshopify.com/68123456789/invoices/5b1c9e0d2f7a4e8b9c3d1a2b3c4d5e6f"

DRAFT_NODE = {
    "id": "gid://shopify/DraftOrder/1122334455",
    "name": "#D12",
    "status": "OPEN",
    "invoiceUrl": INVOICE_URL,
    "totalPriceSet": {"shopMoney": {"amount": "120.00", "currencyCode": "GBP"}},
    "customer": {"id": "gid://shopify/Customer/77", "displayName": "Anna Denning"},
    "order": None,
}


def _drafts(*nodes: dict) -> dict:
    return {"data": {"draftOrders": {"edges": [{"node": node} for node in nodes]}}}


class DraftStore(FakeShopify):
    """A store that holds the drafts made in it, and answers a draft search from them the way
    Shopify does — by name — so a draft made a moment ago can be asked for by its name."""

    def __init__(self) -> None:
        super().__init__([])
        self.drafts: list[dict] = []

    def made(self, node: dict) -> None:
        self.drafts.append(node)

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        self.queries.append((query, variables))
        if "draftOrders(" in query:
            wanted = str(variables.get("q") or "").removeprefix("name:").upper()
            return _drafts(*[d for d in self.drafts if d["name"].lstrip("#").upper() == wanted])
        if "draftOrder(" in query:
            found = [d for d in self.drafts if d["id"] == variables.get("id")]
            return {"data": {"draftOrder": found[0] if found else None}}
        raise AssertionError(f"DraftStore was asked something else: {query}")


# --------------------------------------------------------------------- the link, as Shopify gave it

async def test_a_drafts_name_returns_its_invoice_url():
    client = FakeShopify([_drafts(DRAFT_NODE)])
    shopify_tools.bind(client)
    result = await shopify_tools.shopify_find_order("#D12")
    assert [d["invoice_url"] for d in result["drafts"]] == [INVOICE_URL]
    draft = result["drafts"][0]
    assert draft["draft_name"] == "#D12" and draft["draft_id"] == DRAFT_NODE["id"]
    assert draft["status"] == "OPEN" and draft["total"] == "120.00 GBP"
    assert INVOICE_URL in result["note"]
    assert "never make one up" in result["instruction"]
    # One read, of draft orders, by the name asked for: nothing is sent, nothing is searched as an order.
    assert len(client.queries) == 1
    query, variables = client.queries[0]
    assert "draftOrders(" in query and "invoiceUrl" in query and "mutation" not in query
    assert variables["q"] == "name:D12"
    assert result["orders"] == []


@pytest.mark.parametrize("said", ["D12", "#D12", "d12", "draft 12", "Draft #D12", "draft order D12", "draft order 12"])
async def test_every_way_of_saying_the_draft_finds_it(said):
    client = FakeShopify([_drafts(DRAFT_NODE)])
    shopify_tools.bind(client)
    result = await shopify_tools.shopify_find_order(said)
    assert result["matched_on"] == "draft D12"
    assert result["drafts"][0]["invoice_url"] == INVOICE_URL


async def test_the_name_is_held_to_exactly():
    """A search for D12 that also brings back D120 answers with D12 alone."""
    other = {**DRAFT_NODE, "id": "gid://shopify/DraftOrder/9", "name": "#D120",
             "invoiceUrl": "https://crooks-ldn.myshopify.com/68123456789/invoices/other"}
    shopify_tools.bind(FakeShopify([_drafts(other, DRAFT_NODE)]))
    result = await shopify_tools.shopify_find_order("D12")
    assert [d["draft_name"] for d in result["drafts"]] == ["#D12"]
    assert "other" not in result["note"]


async def test_a_draft_id_reads_that_draft():
    client = FakeShopify([{"data": {"draftOrder": DRAFT_NODE}}])
    shopify_tools.bind(client)
    result = await shopify_tools.shopify_find_order(DRAFT_NODE["id"])
    assert result["drafts"][0]["invoice_url"] == INVOICE_URL
    query, variables = client.queries[0]
    assert "draftOrder(id: $id)" in query and variables == {"id": DRAFT_NODE["id"]}


async def test_no_link_is_invented_when_shopify_gives_none():
    shopify_tools.bind(FakeShopify([_drafts({**DRAFT_NODE, "invoiceUrl": None})]))
    result = await shopify_tools.shopify_find_order("D12")
    assert result["drafts"][0]["invoice_url"] is None
    assert "no payment link" in result["note"] and "http" not in result["note"]
    assert "do not make one up" in result["instruction"]


async def test_a_draft_that_is_not_there_is_said_so():
    shopify_tools.bind(FakeShopify([_drafts()]))
    result = await shopify_tools.shopify_find_order("D404")
    assert result["drafts"] == [] and result["orders"] == []
    assert "No draft order D404" in result["note"]
    assert "http" not in str(result)


async def test_a_completed_draft_says_the_order_it_became():
    node = {**DRAFT_NODE, "status": "COMPLETED", "order": {"id": "gid://shopify/Order/4832", "name": "CROOKS-4832"}}
    shopify_tools.bind(FakeShopify([_drafts(node)]))
    result = await shopify_tools.shopify_find_order("D12")
    draft = result["drafts"][0]
    assert draft["invoice_url"] == INVOICE_URL
    assert draft["order_id"] == "gid://shopify/Order/4832" and "CROOKS-4832" in result["note"]


async def test_a_bare_number_is_still_an_order():
    client = FakeShopify([{"data": {"orders": {"edges": []}}}])
    shopify_tools.bind(client)
    result = await shopify_tools.shopify_find_order("1928")
    assert result["matched_on"] == "name:1928"
    assert "drafts" not in result and "draftOrders" not in client.queries[0][0]


# ------------------------------------------------------------ after the draft is made, asked for

async def test_asking_for_a_drafts_link_after_it_is_made_returns_that_url():
    """The order being made becomes a draft (draftOrderCreate, app/families/order_create.py),
    and the owner is shown its name. Asked for its payment link afterwards, the tool the gate
    already runs reads that draft and returns the URL the store holds for it."""
    store = DraftStore()
    shopify_tools.bind(store)
    made = {**DRAFT_NODE, "id": "gid://shopify/DraftOrder/5566", "name": "#D31",
            "invoiceUrl": "https://crooks-ldn.myshopify.com/68123456789/invoices/d31c0ffee"}
    store.made(made)

    # The call as the model makes it, through the gate and the registry.
    args = {"query": made["name"]}
    decision = classify("mcp__crooks__shopify_find_order", args, issued_ids=())
    assert decision.disposition is Disposition.EXECUTE_NOW
    result = await registry.invoke("shopify_find_order", args, timeout_s=5)
    assert result["drafts"][0]["invoice_url"] == made["invoiceUrl"]
    assert made["invoiceUrl"] in result["note"]

    # And by its id, as the card holds it.
    by_id = await shopify_tools.shopify_find_order(made["id"])
    assert by_id["drafts"][0]["invoice_url"] == made["invoiceUrl"]


def test_the_tool_says_it_gives_a_drafts_payment_link():
    description = registry.get("shopify_find_order").description
    assert "draft" in description and "payment link" in description
    assert len(description) <= 600
