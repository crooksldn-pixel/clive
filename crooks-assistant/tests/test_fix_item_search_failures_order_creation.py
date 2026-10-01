"""An item variant search finds goes on a new order by the same words; a custom item goes on too.

The owner, 1 October: adding an item to a new order by name, the words that already match in
variant search failed to add it — an active, in-stock item, again and again, and the order card
stayed empty. Variant search is asked the product, the colour and the size apart, so Shopify is
asked "OG tee"; an item added to an order arrives as one phrase, "black OG tee M", and Shopify's
search ANDs every word against titles and tags, where a colour and a size are not. What was
asked next was the longest words one at a time — "t-shirt", "black" — and neither is this tee.

And ten sticker packs, no longer an active product, go on a NEW order as a custom item: a title
and the owner's price, and no variant — none required, none invented. An existing order is not
this build's (a custom line there is a reviewed mutation of its own).

The shop is tests/test_r12_orders.py's, with a product search that behaves as Shopify's does:
every word of the query begins a word of the title or a tag, and a product of any status comes
back (the catalogue keeps only the ACTIVE ones). Every name here is invented.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest

from app.actions.ledger import ActionLedger
from app.main import app
from app.session.manager import SessionManager
from app.tools import shopify_tools
from app.tools.shopify_tools import MAX_PHRASE_SEARCHES, _search_terms
from tests import test_r12_orders as r12
from tests.test_context import inbox
from tests.test_r12_orders import THEO, Counter, Scripted, _variant, card, last, rows, say, tap, vid

OG_TEE = {"id": "gid://shopify/Product/9006", "title": "OG Tee", "status": "ACTIVE", "tags": ["tee"], "variants": [
    _variant(9601, "Black", "S", "CRK-OG-BLK-S", "25.00", 3),
    _variant(9602, "Black", "M", "CRK-OG-BLK-M", "25.00", 8),
    _variant(9603, "Black", "L", "CRK-OG-BLK-L", "25.00", 4),
]}
# In stock and in the catalogue, and not sold any more: archived.
STICKERS = {"id": "gid://shopify/Product/9007", "title": "Sticker Pack", "status": "ARCHIVED", "tags": [], "variants": [
    _variant(9701, "Mixed", None, "CRK-STICK-10", "2.00", 40),
]}
CATALOGUE = [*r12.CATALOGUE, OG_TEE, STICKERS]


class Shop(Counter):
    """The order shop, searched as Shopify searches products."""

    def __init__(self) -> None:
        super().__init__()
        self.searched: list[str] = []

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = dict(variables or {})
        term = str(variables.get("q") or "").strip()
        if "CrooksVariantSearch" in query and not term.lower().startswith("sku:"):
            self.queries.append((query, variables))
            self.searched.append(term)
            found = [p for p in CATALOGUE if all(_said_of(word, p) for word in term.lower().split())]
            size = int(variables.get("n") or 10)
            return {"data": {"products": {"pageInfo": {"hasNextPage": len(found) > size},
                                          "edges": [{"node": self._product(p)} for p in found[:size]]}}}
        return await super().graphql(query, variables)


def _said_of(word: str, product: dict[str, Any]) -> bool:
    """A word of a Shopify product search: the beginning of a word of the title, or of a tag."""
    begins = re.compile(rf"(?<![a-z0-9]){re.escape(word)}")
    return bool(begins.search(product["title"].lower())) or any(begins.match(t.lower()) for t in product.get("tags") or [])


@pytest.fixture()
async def shop(monkeypatch, tmp_path):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    # The shop prices and reads a variant from the one table; the new products are in it.
    for product in (OG_TEE, STICKERS):
        for variant in product["variants"]:
            monkeypatch.setitem(r12.VARIANTS, variant["id"], (product, variant))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        store = Shop()
        runtime.shopify = store
        shopify_tools.bind(store, threads_for=inbox())
        runtime.actions.ledger = ActionLedger(tmp_path)
        runtime.sessions = SessionManager()
        runtime.sessions.on_drop.append(runtime.actions.forget_session)
        runtime.provider = Scripted(runtime)
        runtime.settings = runtime.settings.model_copy(
            update={"writes_enabled": True, "allowed_logins": "owner@example.com", "writes_local_owner": False,
                    "tailscale_verify": False})
        app.state.allowed_logins = runtime.allowed_logins
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            client.runtime, client.store, client.model = runtime, store, runtime.provider
            yield client


async def open_for_theo(shop) -> str:
    body = await say(shop, "a new order for Theo Marsh", ("shopify_order_open", {"customer": "Theo Marsh"}))
    data = card(body)
    assert data["rows"] == [] and "It has nothing on it" in data["blocked"]
    return data["workspace_id"]


def _draft_lines(shop) -> list[dict[str, Any]]:
    created = [variables for name, variables in shop.store.mutations if name == "draft_order_create"]
    assert len(created) == 1, shop.store.mutations
    return created[0]["input"]["lineItems"]


# ============================================================ 1. the same words, the same item


async def test_variant_search_finds_the_tee_by_its_words(shop):
    """What the owner saw work: the product, the colour and the size apart, one confident match."""
    await say(shop, "find the black OG tee in medium",
              ("shopify_variant_search", {"product": "OG tee", "colour": "black", "size": "M"}))
    found = last(shop.model.calls, "shopify_variant_search")
    assert found["confident"] is True
    assert [c["variant_id"] for c in found["candidates"]] == [vid(9602)]


@pytest.mark.parametrize("said", ["black OG tee M", "OG tee black medium", "OG tee in black, size M", "OG Tee - Black / M"])
async def test_the_same_words_add_the_tee_to_a_new_order(shop, said):
    """The words variant search matched go on the order card as the one line, at the catalogue's
    price, in stock — not "nothing in the catalogue", and not an empty card."""
    await open_for_theo(shop)
    body = await say(shop, f"add a {said}", ("shopify_order_build", {"add": [{"item": said}]}))
    data = card(body)
    assert rows(data) == [("OG Tee", "Black / M", "× 1", "£25.00")], last(shop.model.calls, "shopify_order_build")["not_done"]
    assert data["rows"][0]["stock"] == "8 in stock"
    assert data["blocked"] == "", data["blocked"]
    built = last(shop.model.calls, "shopify_order_build")
    assert built["not_done"] == [] and built["items"][0]["variant_id"] == vid(9602)
    assert "OG tee" in shop.store.searched or "OG Tee" in shop.store.searched


async def test_the_same_words_said_when_the_order_is_opened(shop):
    body = await say(shop, "start an order for Theo Marsh with a black OG tee in medium",
                     ("shopify_order_open", {"customer": "Theo Marsh", "item": "black OG tee medium"}))
    data = card(body)
    assert rows(data) == [("OG Tee", "Black / M", "× 1", "£25.00")]
    assert data["blocked"] == ""


async def test_the_same_words_typed_on_the_card(shop):
    """The thumb's way: typed into "Add an item" and Add tapped, the same item goes on."""
    ident = await open_for_theo(shop)
    await tap(shop, "order.field", workspace_id=ident, field="item", value="black OG tee M")
    added = await tap(shop, "order.additem", workspace_id=ident)
    assert rows(card(added)) == [("OG Tee", "Black / M", "× 1", "£25.00")]


async def test_a_size_said_in_two_words_is_the_size(shop):
    """Variant search takes "extra small" as the size XS; in an item's words it is XS too."""
    await open_for_theo(shop)
    body = await say(shop, "a Convict hoodie in black, extra small",
                     ("shopify_order_build", {"add": [{"item": "Convict hoodie black extra small"}]}))
    assert rows(card(body)) == [("Convict Hoodie", "Black / XS", "× 1", "£60.00")]


async def test_several_matches_are_still_a_choice_and_nothing_is_guessed(shop):
    await open_for_theo(shop)
    body = await say(shop, "add a black OG tee", ("shopify_order_build", {"add": [{"item": "black OG tee"}]}))
    data = card(body)
    assert data["rows"] == [] and len(data["picks"]) == 3
    assert "3 items match" in last(shop.model.calls, "shopify_order_build")["not_done"][0]["why"]


def test_the_runs_of_the_words_are_asked_before_single_words_and_are_bounded():
    terms = _search_terms("black OG tee M")
    assert terms[:4] == ["black OG tee M", "black OG tee", "black OG", "OG tee"]
    assert terms[4:] == ["t-shirt", "black"], "the single words, as before, after the runs"
    long = _search_terms("washed black heavyweight boxy fit OG tee in large")
    assert len(long) <= 1 + MAX_PHRASE_SEARCHES + 3
    # The words already Shopify's own are asked once, as they always were.
    assert _search_terms("Convict hoodie") == ["Convict hoodie", "convict", "hoodie"]


async def test_variant_search_asked_apart_asks_shopify_what_it_always_did(shop):
    """Nothing changes for words already said apart: one search, the product's words."""
    await say(shop, "a black medium Convict hoodie",
              ("shopify_variant_search", {"product": "Convict hoodie", "colour": "black", "size": "M"}))
    assert shop.store.searched == ["Convict hoodie"]
    assert last(shop.model.calls, "shopify_variant_search")["confident"] is True


# ============================================================ 2. a custom line on a new order


async def test_a_custom_item_with_a_title_and_a_price_goes_on_a_new_order(shop):
    ident = await open_for_theo(shop)
    body = await say(shop, "ten sticker packs at one fifty each",
                     ("shopify_order_build", {"add": [{"title": "Sticker pack", "price": 1.5, "quantity": 10}]}))
    data = card(body)
    assert rows(data) == [("Sticker pack", "", "× 10", "£15.00")]
    assert data["rows"][0]["stock"] == "custom item" and data["blocked"] == ""
    built = last(shop.model.calls, "shopify_order_build")
    assert built["items"] == [{"line": 1, "title": "Sticker pack", "variant": "", "custom": True, "quantity": 10,
                               "unit_price": "1.50", "discount": "", "stock": "custom item"}], "no variant_id"
    staged = await tap(shop, "order.stage", workspace_id=ident)
    assert [i for i in staged["ui"] if i["type"] == "confirmation"], staged
    assert _draft_lines(shop) == [{"title": "Sticker pack", "originalUnitPrice": "1.50", "quantity": 10}]


async def test_an_inactive_product_is_not_a_variant_and_goes_on_as_a_custom_item(shop):
    """The sticker packs are archived. No search hands out their variant, nothing adds it, and
    the model is told the way that works: a custom item, title and price, no variant_id."""
    ident = await open_for_theo(shop)
    await say(shop, "ten sticker packs", ("shopify_variant_search", {"product": "sticker pack"}))
    searched = last(shop.model.calls, "shopify_variant_search")
    assert searched["candidates"] == [] and "No variant matches" in searched["note"]
    assert "custom item" in searched["note"] and "no variant_id" in searched["note"]
    assert "cannot be added to an existing order" in searched["note"]
    session = shop.runtime.sessions.get("g1")
    assert vid(9701) not in session.issued_ids, "an archived product's variant is never handed out"

    body = await say(shop, "add them", ("shopify_order_build", {"add": [{"item": "sticker pack", "quantity": 10}]}))
    assert card(body)["rows"] == []
    assert "Nothing in the catalogue matches" in last(shop.model.calls, "shopify_order_build")["not_done"][0]["why"]

    body = await say(shop, "as a custom item, two pounds each",
                     ("shopify_order_build", {"add": [{"title": "Sticker pack", "price": 2, "quantity": 10}]}))
    assert rows(card(body)) == [("Sticker pack", "", "× 10", "£20.00")]
    await tap(shop, "order.stage", workspace_id=ident)
    assert _draft_lines(shop) == [{"title": "Sticker pack", "originalUnitPrice": "2.00", "quantity": 10}]


async def test_a_custom_item_and_the_tee_on_one_new_order(shop):
    """Both, on one card and one draft: the tee by its variant and priced by Shopify, the
    stickers by their title and the owner's price."""
    ident = await open_for_theo(shop)
    body = await say(shop, "a black OG tee in medium and ten sticker packs at £1.50",
                     ("shopify_order_build", {"add": [{"item": "black OG tee medium"},
                                                      {"title": "Sticker pack", "price": 1.5, "quantity": 10}]}))
    data = card(body)
    assert rows(data) == [("OG Tee", "Black / M", "× 1", "£25.00"), ("Sticker pack", "", "× 10", "£15.00")]
    assert data["subtitle"] == "2 lines, £40.00 of goods"
    await tap(shop, "order.stage", workspace_id=ident)
    assert _draft_lines(shop) == [{"variantId": vid(9602), "quantity": 1},
                                  {"title": "Sticker pack", "originalUnitPrice": "1.50", "quantity": 10}]
    assert shop.store.mutations[0][1]["input"]["customerId"] == THEO
