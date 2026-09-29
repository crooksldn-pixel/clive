"""Round 13: one match on a page that is not the whole answer is not "one".

The round-12 deploy review, T1-02. `shopify_find_order` by evidence asks Shopify for a bounded
page of orders and checks each against what the owner said. When Shopify had more orders than
that page, a single match on it was still reported as `one` — "a clear answer" in the tool's own
description — and its customer was named as THE customer, although the next page could hold
another order that fits, for somebody else. The note that said the look was bounded appeared
only when some of the evidence had been checked here rather than searched by Shopify.

Now, whenever Shopify says there are more: `one` is false, no customer is inferred, and the
result is marked `incomplete` with a sentence saying how many were looked at.

Every call goes through the real `POST /turn`, with a scripted model making the one call, and
the fake shop of tests/test_r12_orders.py, which now reports `hasNextPage` as a real shop does.
"""

from __future__ import annotations

from app.tools import shopify_tools
from tests import test_r12_orders as r12
from tests.test_r12_orders import AVA, THEO, ZOE, last, say

# The shop the round-12 order tests run in, bound under this name so pytest finds it here.
shop = r12.shop


async def find(shop, text: str, **evidence) -> dict:
    await say(shop, text, ("shopify_find_order", evidence))
    return last(shop.model.calls, "shopify_find_order")


async def test_the_fake_shop_says_there_are_more_when_there_are(shop, monkeypatch):
    """The fake is honest now: a page shorter than what matches says so, as Shopify does."""
    monkeypatch.setattr(shopify_tools, "MAX_EVIDENCE_ORDERS", 2)
    payload = await shop.store.graphql(shopify_tools.ORDER_EVIDENCE_QUERY, {"q": None, "n": 2})
    assert payload["data"]["orders"]["pageInfo"]["hasNextPage"] is True
    payload = await shop.store.graphql(shopify_tools.ORDER_EVIDENCE_QUERY, {"q": None, "n": 50})
    assert payload["data"]["orders"]["pageInfo"]["hasNextPage"] is False


async def test_one_match_on_a_page_with_more_behind_it_is_not_one_and_names_nobody(shop, monkeypatch):
    """"SL6": the newest three orders hold one that went to SL6 — Zoë's — and Theo's order to
    SL6 2AB is older than the page. Before the repair that was `one`, and the customer was Zoë."""
    monkeypatch.setattr(shopify_tools, "MAX_EVIDENCE_ORDERS", 3)
    told = await find(shop, "who had something sent to SL6", address="SL6")
    assert [o["customer_id"] for o in told["orders"]] == [ZOE]
    assert told["one"] is False, told
    assert "customer" not in told, "the next page could be somebody else's"
    assert told["incomplete"] is True
    assert "3" in told["coverage"] and "older" in told["coverage"], told["coverage"]


async def test_a_search_shopify_answered_in_full_but_cut_at_the_page_is_incomplete_too(shop, monkeypatch):
    """Everything said was something Shopify searches (an email), so nothing was checked here —
    and the page was still cut short. It is still not `one`, and it still says so."""
    monkeypatch.setattr(shopify_tools, "MAX_EVIDENCE_ORDERS", 1)
    told = await find(shop, "ava's order", email=r12.PEOPLE[AVA]["email"])
    assert told["count"] == 1 and told["one"] is False and told["incomplete"] is True, told
    assert "customer" not in told
    assert "1 order" in told["coverage"], told["coverage"]


async def test_a_whole_answer_is_still_one_and_still_names_its_customer(shop):
    """The control: Shopify had nothing more, so one is one."""
    told = await find(shop, "who ordered the black hoodie to SL6 2AB", item="black hoodie", address="SL6 2AB")
    assert told["one"] is True and "incomplete" not in told, told
    assert told["customer"]["customer_id"] == THEO
