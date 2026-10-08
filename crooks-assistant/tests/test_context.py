"""The order read model: one nested read, the customer's history and the inbox beside it
under a budget, and the rest collected by the tablet afterwards. Nothing here reaches a
network; the store and the inbox are fakes."""

from __future__ import annotations

import asyncio

import pytest

from app.context import order as context
from app.context.order import Hydrator, correlate_threads, shape_customer_history, shape_order
from app.presentation import present, present_extension
from app.providers.base import ToolCall
from app.session.models import Session
from app.tools import shopify_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.conftest import FakeShopify

ORDER = "gid://shopify/Order/1938"
CUSTOMER = "gid://shopify/Customer/7"
IMAGE = "https://cdn.shopify.com/s/files/1/0001/products/yard-jeans.jpg?v=1"

ORDER_NODE = {
    "id": ORDER, "name": "CROOKS-1938", "createdAt": "2026-09-07T10:00:00Z", "processedAt": "2026-09-07T10:00:00Z",
    "cancelledAt": None, "cancelReason": None, "closedAt": None,
    "displayFulfillmentStatus": "UNFULFILLED", "displayFinancialStatus": "PAID", "fullyPaid": True,
    "tags": ["vip"], "note": "Leave with the neighbour", "refundable": True,
    "currentTotalPriceSet": {"shopMoney": {"amount": "60.00", "currencyCode": "GBP"}},
    "subtotalPriceSet": {"shopMoney": {"amount": "55.00", "currencyCode": "GBP"}},
    "totalShippingPriceSet": {"shopMoney": {"amount": "5.00", "currencyCode": "GBP"}},
    "totalTaxSet": {"shopMoney": {"amount": "9.17", "currencyCode": "GBP"}},
    "totalDiscountsSet": {"shopMoney": {"amount": "0.00", "currencyCode": "GBP"}},
    "totalRefundedSet": {"shopMoney": {"amount": "0.00", "currencyCode": "GBP"}},
    "totalOutstandingSet": {"shopMoney": {"amount": "0.00", "currencyCode": "GBP"}},
    "shippingLine": {"title": "Royal Mail Tracked 24"},
    "shippingAddress": {"firstName": "Daniel", "lastName": "Stub", "company": None, "address1": "12 Somewhere Street", "address2": "Flat 3",
                        "city": "Windsor", "province": "England", "provinceCode": "ENG", "zip": "SL4 1AA", "country": "United Kingdom", "countryCodeV2": "GB"},
    "customer": {"id": CUSTOMER, "displayName": "Daniel Stub", "numberOfOrders": 3, "createdAt": "2025-01-02T00:00:00Z",
                 "amountSpent": {"amount": "410.00", "currencyCode": "GBP"}, "defaultEmailAddress": {"emailAddress": "daniel@example.com"}},
    "lineItems": {"edges": [{"node": {
        "id": "gid://shopify/LineItem/1", "title": "Yard Jeans", "quantity": 1, "currentQuantity": 1, "refundableQuantity": 1, "unfulfilledQuantity": 1,
        "variantTitle": "Blue Wash / M", "sku": "YJ-M",
        "originalTotalSet": {"shopMoney": {"amount": "55.00", "currencyCode": "GBP"}},
        "discountedTotalSet": {"shopMoney": {"amount": "55.00", "currencyCode": "GBP"}},
        "image": {"url": IMAGE, "width": 1200, "height": 1600},
        "variant": {"id": "gid://shopify/ProductVariant/11", "inventoryQuantity": 3, "inventoryItem": {"id": "gid://shopify/InventoryItem/21", "tracked": True},
                    "selectedOptions": [{"name": "Colour", "value": "Blue Wash"}, {"name": "Size", "value": "M"}]},
        "product": {"id": "gid://shopify/Product/31", "title": "Yard Jeans"},
    }}]},
    "fulfillments": [], "refunds": [],
    "events": {"edges": [{"node": {"id": "e1", "message": "Confirmation email was sent to the customer.", "createdAt": "2026-09-07T10:00:05Z"}}]},
}

CUSTOMER_NODE = {
    "id": CUSTOMER, "displayName": "Daniel Stub", "numberOfOrders": 3, "createdAt": "2025-01-02T00:00:00Z", "tags": [],
    "amountSpent": {"amount": "410.00", "currencyCode": "GBP"}, "defaultEmailAddress": {"emailAddress": "daniel@example.com"},
    "lastOrder": {"id": ORDER, "name": "CROOKS-1938"},
    "firstOrder": {"edges": [{"node": {"id": "gid://shopify/Order/1800", "name": "#1800", "processedAt": "2025-01-02T10:00:00Z", "createdAt": "2025-01-02T10:00:00Z"}}]},
    "openOrders": {"edges": [
        {"node": {"id": ORDER, "name": "CROOKS-1938", "cancelledAt": None, "displayFulfillmentStatus": "UNFULFILLED"}},
        {"node": {"id": "gid://shopify/Order/1901", "name": "CROOKS-1901", "cancelledAt": None, "displayFulfillmentStatus": "UNFULFILLED"}},
    ]},
    "orders": {"edges": [
        {"node": {"id": ORDER, "name": "CROOKS-1938", "createdAt": "2026-09-07T10:00:00Z", "processedAt": "2026-09-07T10:00:00Z", "cancelledAt": None,
                  "displayFulfillmentStatus": "UNFULFILLED", "displayFinancialStatus": "PAID",
                  "currentTotalPriceSet": {"shopMoney": {"amount": "60.00", "currencyCode": "GBP"}}, "lineItems": {"edges": [{"node": {"title": "Yard Jeans", "quantity": 1}}]}}},
        {"node": {"id": "gid://shopify/Order/1901", "name": "CROOKS-1901", "createdAt": "2026-08-20T10:00:00Z", "processedAt": "2026-08-20T10:00:00Z", "cancelledAt": None,
                  "displayFulfillmentStatus": "UNFULFILLED", "displayFinancialStatus": "PAID",
                  "currentTotalPriceSet": {"shopMoney": {"amount": "200.00", "currencyCode": "GBP"}}, "lineItems": {"edges": [{"node": {"title": "Convict Hoodie", "quantity": 2}}]}}},
        {"node": {"id": "gid://shopify/Order/1800", "name": "#1800", "createdAt": "2025-01-02T10:00:00Z", "processedAt": "2025-01-02T10:00:00Z", "cancelledAt": None,
                  "displayFulfillmentStatus": "FULFILLED", "displayFinancialStatus": "PAID",
                  "currentTotalPriceSet": {"shopMoney": {"amount": "150.00", "currencyCode": "GBP"}}, "lineItems": {"edges": []}}},
    ]},
}

THREADS = [
    {"thread_id": "18f2a9c0b1d2e3f4", "from": "Daniel Stub", "from_email": "daniel@example.com", "subject": "Address for 1938", "date": "Mon, 8 Sep 2026 10:12:00 +0100", "snippet": "Please send it to my work instead", "likely_bulk": False, "authenticated": True},
    {"thread_id": "18f2a9c0b1d2e3f5", "from": "Someone Else", "from_email": "other@example.com", "subject": "Re: CROOKS-1938", "date": "Mon", "snippet": "is 1938 mine?", "likely_bulk": False},
    {"thread_id": "18f2a9c0b1d2e3f6", "from": "Nobody", "from_email": "nobody@example.com", "subject": "Hello", "date": "Mon", "snippet": "unrelated", "likely_bulk": False},
]


class Store(FakeShopify):
    """Answers the two context documents by name, however many times they are asked."""

    def __init__(self, *, order=ORDER_NODE, customer=CUSTOMER_NODE, delay_customer_s: float = 0.0) -> None:
        super().__init__([])
        self.order_node = order
        self.customer_node = customer
        self.delay_customer_s = delay_customer_s

    async def graphql(self, query, variables=None):
        self.queries.append((query, variables or {}))
        if "CrooksOrderByName" in query:
            digits = str((variables or {}).get("q", "")).split(":")[-1]
            return {"data": {"orders": {"edges": [{"node": self.order_node}] if digits and self.order_node["name"].endswith(digits) else []}}}
        if "CrooksOrderContext" in query:
            return {"data": {"order": self.order_node if (variables or {}).get("id") == self.order_node["id"] else None}}
        if "CrooksCustomerOrders" in query:
            if self.delay_customer_s:
                await asyncio.sleep(self.delay_customer_s)
            return {"data": {"customer": self.customer_node if (variables or {}).get("id") == self.customer_node["id"] else None}}
        raise AssertionError(f"unexpected query: {query[:60]}")


def inbox(threads=THREADS, *, delay_s: float = 0.0, available: bool = True):
    calls = []

    async def threads_for(**kwargs):
        calls.append(kwargs)
        if delay_s:
            await asyncio.sleep(delay_s)
        if not available:
            return {"available": False, "reason": "Gmail is not configured on this backend.", "threads": []}
        return {"available": True, "threads": list(threads)}

    threads_for.calls = calls
    return threads_for


# --------------------------------------------------------------------------- shaping


def test_the_order_read_model_carries_money_address_items_and_stock():
    o = shape_order(ORDER_NODE)
    assert o["order_number"] == "CROOKS-1938" and o["total"] == "60.00 GBP"
    assert o["money"] == {"subtotal": "55.00 GBP", "shipping": "5.00 GBP", "tax": "9.17 GBP", "discounts": "0.00 GBP",
                          "refunded": "0.00 GBP", "outstanding": "0.00 GBP", "total": "60.00 GBP", "currency": "GBP"}
    assert o["shipping_address"]["lines"] == ["12 Somewhere Street", "Flat 3"] and o["shipping_address"]["zip"] == "SL4 1AA"
    assert o["shipping_address"]["country_code"] == "GB" and o["ships_to"] == "Windsor, United Kingdom"
    item = o["items"][0]
    assert item["image_url"] == IMAGE and item["variant_id"] == "gid://shopify/ProductVariant/11"
    assert item["stock"] == {"tracked": True, "available": 3, "inventory_item_id": "gid://shopify/InventoryItem/21"}
    assert item["options"] == [{"name": "Colour", "value": "Blue Wash"}, {"name": "Size", "value": "M"}]
    assert o["customer"]["orders"] == 3 and o["customer"]["spent"] == "410.00 GBP"
    assert o["shipping_method"] == "Royal Mail Tracked 24" and o["refundable"] is True
    assert o["events"][0]["message"].startswith("Confirmation email")


def test_the_read_model_is_bounded_and_tolerates_a_thin_node():
    node = dict(ORDER_NODE)
    node["lineItems"] = {"edges": [ORDER_NODE["lineItems"]["edges"][0]] * 40}
    node["tags"] = [f"t{i}" for i in range(40)]
    node["note"] = "x" * 5000
    o = shape_order(node)
    assert len(o["items"]) == context.MAX_ITEMS and o["items_truncated"] is True
    assert len(o["tags"]) == 10 and len(o["note"]) <= 1200
    thin = shape_order({"id": ORDER, "name": "#1"})
    assert thin["items"] == [] and thin["shipping_address"] is None and thin["customer"] is None and thin["money"]["total"] is None


def test_the_customer_history_answers_the_five_questions():
    h = shape_customer_history(CUSTOMER_NODE, current_order_id=ORDER)
    assert h["orders"] == 3 and h["spent"] == "410.00 GBP" and h["standing"] == "returning"
    assert h["first_order_at"] == "2025-01-02T10:00:00Z"          # every order was fetched, so the first is known
    assert h["last_order"] == {"order_id": ORDER, "order_number": "CROOKS-1938"}
    assert [r["order_number"] for r in h["recent"]] == ["CROOKS-1938", "CROOKS-1901", "#1800"]
    assert h["recent"][0]["current"] is True and h["recent"][1]["items_brief"] == "Convict Hoodie ×2"
    assert h["other_unfulfilled"] == ["CROOKS-1901"]
    many = shape_customer_history(dict(CUSTOMER_NODE, numberOfOrders=12))
    # A regular's first order and open orders come from their own connections, not from the five shown.
    assert many["first_order_at"] == "2025-01-02T10:00:00Z" and many["standing"] == "regular" and many["recent_truncated"] is True
    older = dict(CUSTOMER_NODE, numberOfOrders=12, firstOrder={"edges": []}, openOrders=None)
    assert shape_customer_history(older)["first_order_at"] is None


def test_email_is_correlated_by_sender_first_and_order_number_second_never_by_name():
    threads = correlate_threads(THREADS, customer_email="Daniel@Example.com", digits="1938")
    assert [t["thread_id"] for t in threads] == ["18f2a9c0b1d2e3f4", "18f2a9c0b1d2e3f5"]
    assert threads[0]["sender_match"] is True and threads[0]["verified_sender"] is True and threads[0]["match"] == "both" and threads[0]["provenance"] == "CUSTOMER_EMAIL"
    assert threads[1]["sender_match"] is False and threads[1]["verified_sender"] is False and threads[1]["match"] == "order_number" and threads[1]["provenance"] == "UNKNOWN"
    # A From line that matches is a match; only the mail server's own authentication makes it verified.
    unauthenticated = correlate_threads([dict(THREADS[0], authenticated=False)], customer_email="daniel@example.com", digits="1938")
    assert unauthenticated[0]["sender_match"] is True and unauthenticated[0]["verified_sender"] is False
    # "1938" inside a longer number is not this order.
    assert correlate_threads([{"from_email": "x@y.z", "subject": "ref 119384", "snippet": ""}], customer_email=None, digits="1938") == []


def test_the_model_reads_the_town_and_the_facts_never_the_street_or_the_image():
    from app.context.order import model_view

    o = shape_order(ORDER_NODE)
    o["pending"] = ["email"]
    o["history"] = None
    o["email"] = None
    m = model_view(o)
    assert "shipping_address" not in m and m["ships_to"] == "Windsor, SL4, United Kingdom"
    assert "image_url" not in m["items"][0] and m["items"][0]["variant_id"] == "gid://shopify/ProductVariant/11"
    assert "inventory_item_id" not in m["items"][0]["stock"] and m["items"][0]["stock"]["available"] == 3
    assert m["email"].startswith("still being read") and m["history"] is None
    assert m["money"]["shipping"] == "5.00 GBP" and m["refundable"] is True
    # The card is built from the full result; the model's text is built from the view.
    assert o["shipping_address"]["lines"] == ["12 Somewhere Street", "Flat 3"]


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_model_never_sees_the_street_through_dispatch():
    store = Store()
    shopify_tools.bind(store, threads_for=inbox())
    session = Session(session_id="m")
    session.issue(ORDER)
    calls: list[ToolCall] = []
    text = await dispatch("shopify_order_detail", {"order_id": ORDER}, session=session, timeout_s=5, calls=calls)
    assert "Somewhere Street" not in text and "SL4 1AA" not in text and "cdn.shopify.com" not in text
    assert "Windsor" in text and "410.00" in text and "CROOKS-1901" in text
    assert calls[0].result["shipping_address"]["zip"] == "SL4 1AA"


# --------------------------------------------------------------------------- hydration


async def test_the_order_arrives_with_its_history_and_inbox_when_they_are_quick():
    store = Store()
    h = Hydrator(lambda: store, threads_for=inbox())
    o = await h.order(ORDER)
    assert o["pending"] == []
    assert o["history"]["other_unfulfilled"] == ["CROOKS-1901"]
    assert o["email"]["available"] is True and o["email"]["threads"][0]["verified_sender"] is True
    assert store.queries[0][0].strip().startswith("query CrooksOrderContext")
    assert store.queries[1][0].strip().startswith("query CrooksCustomerOrders")


async def test_a_slow_inbox_is_not_waited_for_and_is_collected_afterwards():
    store = Store()
    slow = inbox(delay_s=0.3)
    h = Hydrator(lambda: store, threads_for=slow)
    o = await h.order(ORDER, budget_s=0.05)
    assert o["pending"] == ["email"] and o["history"] is not None and o["email"] is None
    later = await h.extension(ORDER, wait_s=1.0)
    assert later["pending"] == [] and later["email"]["threads"]
    # The order itself was read once for the turn and not again for the extension.
    assert sum(1 for q, _ in store.queries if "CrooksOrderContext" in q) == 1


async def test_the_search_by_number_carries_the_whole_order_and_the_detail_that_follows_costs_nothing():
    store = Store()
    h = Hydrator(lambda: store, threads_for=inbox())
    found = await h.find_by_number("1938")
    assert len(found) == 1 and found[0]["order_id"] == ORDER and found[0]["money"]["total"] == "60.00 GBP"
    assert store.queries[0][0].strip().split("(")[0] == "query CrooksOrderByName"
    o = await h.order(ORDER, budget_s=1.0)
    assert o["history"]["orders"] == 3 and o["pending"] == []
    assert sum(1 for q, _ in store.queries if "CrooksOrderContext" in q) == 0, "the order was in hand from the search"
    assert sum(1 for q, _ in store.queries if "CrooksCustomerOrders" in q) == 1, "the enrichment began with the search"
    assert await h.find_by_number("0000") == []
    # After the reuse window the order is read afresh: its state is what every change turns on.
    h.clock = lambda: 1e12
    await h.order(ORDER, budget_s=0)
    assert sum(1 for q, _ in store.queries if "CrooksOrderContext" in q) == 1


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_models_own_detail_call_waits_only_a_moment_for_the_rest():
    import time as _time

    store = Store(delay_customer_s=0.6)
    shopify_tools.bind(store, threads_for=inbox(delay_s=0.6))
    session = Session(session_id="b")
    session.issue(ORDER)
    calls: list[ToolCall] = []
    started = _time.perf_counter()
    text = await dispatch("shopify_order_detail", {"order_id": ORDER}, session=session, timeout_s=5, calls=calls)
    waited = _time.perf_counter() - started
    assert waited < 0.5, waited
    assert "still being read" in text and calls[0].result["pending"] == ["history", "email"]


async def test_a_second_look_re_reads_the_order_but_reuses_the_history():
    store = Store()
    clock = [1000.0]
    h = Hydrator(lambda: store, threads_for=inbox(), clock=lambda: clock[0])
    await h.order(ORDER)
    clock[0] += 30   # past the few seconds an order is held, within the minute its history is
    await h.order(ORDER)
    assert sum(1 for q, _ in store.queries if "CrooksOrderContext" in q) == 2
    assert sum(1 for q, _ in store.queries if "CrooksCustomerOrders" in q) == 1


async def test_no_inbox_and_no_customer_still_gives_an_order():
    node = dict(ORDER_NODE, customer=None)
    h = Hydrator(lambda: Store(order=node), threads_for=None)
    o = await h.order(ORDER)
    assert o["customer"] is None and o["history"] is None
    assert o["email"] == {"available": False, "reason": "Gmail is not configured on this backend.", "threads": []}
    assert o["pending"] == []


async def test_an_inbox_that_fails_is_reported_not_raised():
    async def broken(**kwargs):
        raise RuntimeError("boom")

    h = Hydrator(lambda: Store(), threads_for=broken)
    o = await h.order(ORDER)
    assert o["email"]["available"] is False and o["pending"] == []


async def test_an_unknown_order_is_a_tool_error():
    from app.tools.registry import ToolError

    h = Hydrator(lambda: Store(), threads_for=inbox())
    with pytest.raises(ToolError):
        await h.order("gid://shopify/Order/999")


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_customer_history_tool_is_amber_needs_an_issued_customer_id_and_reads_the_inbox():
    store = Store()
    shopify_tools.bind(store, threads_for=inbox())
    assert classify("shopify_customer_history", {"customer_id": CUSTOMER}).disposition is Disposition.DENY
    decision = classify("shopify_customer_history", {"customer_id": CUSTOMER}, issued_ids={CUSTOMER})
    assert decision.tier is Tier.AMBER and decision.disposition is Disposition.EXECUTE_NOW
    assert classify("shopify_customer_history", {"customer_id": ORDER}, issued_ids={ORDER}).disposition is Disposition.DENY
    session = Session(session_id="c")
    session.issue(CUSTOMER)
    calls: list[ToolCall] = []
    text = await dispatch("shopify_customer_history", {"customer_id": CUSTOMER}, session=session, timeout_s=5, calls=calls)
    assert text.startswith("AMBER") and calls[0].ok
    result = calls[0].result
    assert result["orders"] == 3 and result["email_threads"]["threads"][0]["from_email"] == "daniel@example.com"
    # The orders it listed are now available to look at in detail.
    assert "gid://shopify/Order/1901" in session.issued_ids
    items = present(calls, session=session)
    assert items[0]["type"] == "customer" and items[0]["data"]["history"]["other_unfulfilled"] == ["#1938", "#1901"]
    assert items[0]["data"]["email"] == "daniel@example.com" and items[0]["data"]["related_email"]["threads"][0]["verified_sender"] is True


# --------------------------------------------------------------------------- the card


def test_the_card_carries_the_richer_order_bounded_and_whitelisted():
    from app import media

    o = shape_order(ORDER_NODE)
    o["history"] = shape_customer_history(CUSTOMER_NODE, current_order_id=ORDER)
    o["email"] = {"available": True, "threads": correlate_threads(THREADS, customer_email="daniel@example.com", digits="1938")}
    o["pending"] = []
    o["secret_field"] = "must not reach the screen"
    items = present([ToolCall(name="shopify_order_detail", args={}, ok=True, result=o)])
    data = items[0]["data"]
    assert "secret_field" not in data
    assert data["money"]["shipping"] == "£5.00" and data["shipping_address"]["lines"] == ["12 Somewhere Street", "Flat 3"]
    assert data["items"][0]["image"].startswith(media.PATH_PREFIX) and "cdn.shopify.com" in data["items"][0]["image"]
    assert data["items"][0]["stock"] == {"tracked": True, "available": 3}
    assert data["history"]["standing"] == "returning" and data["history"]["other_unfulfilled"] == ["#1901"]
    assert data["email"]["threads"][0]["verified_sender"] is True and data["email"]["threads"][0]["provenance"] == "CUSTOMER_EMAIL"
    assert data["pending"] == []


def test_an_image_from_anywhere_but_shopifys_cdn_is_no_image():
    o = shape_order(ORDER_NODE)
    o["items"][0]["image_url"] = "https://evil.example/cdn.shopify.com/x.jpg"
    items = present([ToolCall(name="shopify_order_detail", args={}, ok=True, result=o)])
    assert items[0]["data"]["items"][0]["image"] == ""


def test_the_extension_is_shaped_like_the_card():
    ext = present_extension({"order_id": ORDER, "pending": ["email"], "history": shape_customer_history(CUSTOMER_NODE), "email": None, "junk": 1})
    assert set(ext) == {"order_id", "pending", "history", "email", "failed"} and ext["history"]["orders"] == 3


# --------------------------------------------------------------------------- the routes


@pytest.fixture()
async def client(monkeypatch):
    import httpx

    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk
    from app.providers.base import TurnResult
    from app.session.manager import SessionManager

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    class Provider:
        prompts: list[str] = []
        async def start(self): pass
        async def stop(self): pass
        async def health(self): return True, "fake"
        async def reset_session(self, session_id): pass
        async def set_system_prompt(self, prompt): pass
        async def interrupt(self, session_id): return True
        async def turn(self, session_id, text):
            # Claude, as far as the route is concerned: every sentence is the model's, and for
            # an order it looks the order up and reads it, through the gate, one after the other.
            self.prompts.append(text)
            session = runtime.sessions.get_or_create(session_id)
            calls: list = []
            await dispatch("shopify_find_order", {"query": "1938"}, session=session, timeout_s=5, calls=calls)
            found = ((calls[-1].result or {}).get("orders") or [{}])[0] if calls and calls[-1].ok else {}
            await dispatch("shopify_order_detail", {"order_id": found.get("order_id") or ""}, session=session,
                           timeout_s=5, calls=calls)
            return TurnResult(text="Order 1938. Paid, not shipped.", tool_calls=calls, session_id=session_id)

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        store = Store()
        base = store.graphql

        async def graphql(query, variables=None):
            return await base(query, variables)

        store.graphql = graphql
        runtime.shopify = store
        runtime.provider = Provider()
        shopify_tools.bind(store, threads_for=inbox())
        runtime.sessions = SessionManager()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.runtime = runtime
            c.store = store
            yield c


async def test_the_models_two_reads_of_an_order_draw_the_whole_order(client):
    """A RENDERING test, through the route: given the model's find and detail of #1938, the
    card, the issued ids and where the branch now stands all come from those two reads, and
    nothing on the Mac looked the order up ahead of it.

    It is not evidence that the model chooses the order the words named — the provider above
    reads #1938 whatever it is asked (round 9, I-tests2 I-03). That claim is tested with a
    requested order different from the one in focus, where a fixed-order model would fail, in
    tests/test_turn_boundary.py (`test_a_number_that_is_not_the_open_order_is_drawn_from_what_was_read_for_it`
    and its neighbours)."""
    body = (await client.post("/turn", json={"text": "Show me order 1938", "session_id": "h1"})).json()
    assert body["lane"] == "NORMAL" and "recipe_id" not in body
    prompt = client.runtime.provider.prompts[-1]
    assert prompt.split("\n")[1] == "Show me order 1938" and "being read beside you" not in prompt
    assert [c["name"] for c in body["tool_calls"]] == ["shopify_find_order", "shopify_order_detail"]
    assert body["performance"]["model_calls"] == 1
    # One document for the search and the order; the customer's history once; nothing twice.
    kinds = [q.strip().split("(")[0].replace("query ", "") for q, _ in client.store.queries]
    assert kinds.count("CrooksOrderByName") == 1 and kinds.count("CrooksOrderContext") == 0 and kinds.count("CrooksCustomerOrders") == 1
    card = next(i for i in body["ui"] if i["type"] == "order")
    assert card["data"]["detail"] is True and card["data"]["history"]["orders"] == 3
    assert card["data"]["items"][0]["image"].startswith("/media/shopify/")
    session = client.runtime.sessions.peek("h1")
    assert "gid://shopify/ProductVariant/11" in session.issued_ids and CUSTOMER in session.issued_ids
    assert body["branch"]["entity"]["kind"] == "order", "the branch knows where it now is"
    # The street and the postcode are remembered as personal, so the log scrubs them by value.
    assert "12 Somewhere Street" in session.pii_seen and "SL4 1AA" in session.pii_seen
    # The turn log records which cards were shown, never the address on them.
    from pathlib import Path

    from config.settings import get_settings

    log_text = (Path(get_settings().log_dir) / "turns.jsonl").read_text(encoding="utf-8")
    assert "Somewhere Street" not in log_text and "SL4 1AA" not in log_text


async def test_the_context_route_is_bound_to_the_session_and_to_issued_orders(client):
    assert (await client.get(f"/context/order/{ORDER}", params={"session_id": "nope"})).status_code == 404
    session = client.runtime.sessions.get_or_create("c1")
    assert (await client.get(f"/context/order/{ORDER}", params={"session_id": "c1"})).status_code == 404
    session.issue(ORDER)
    response = await client.get(f"/context/order/{ORDER}", params={"session_id": "c1"})
    assert response.status_code == 200
    ext = response.json()
    assert ext["order_id"] == ORDER and ext["pending"] == [] and ext["history"]["orders"] == 3
    assert ext["email"]["threads"][0]["thread_id"] == "18f2a9c0b1d2e3f4"
    assert "18f2a9c0b1d2e3f4" in session.issued_ids
    assert (await client.get("/context/order/gid://shopify/Order/999", params={"session_id": "c1"})).status_code == 404
    # An issued id of another kind is not an order, however it was issued.
    session.issue(CUSTOMER)
    assert (await client.get(f"/context/order/{CUSTOMER}", params={"session_id": "c1"})).status_code == 404
    assert len(client.store.queries) == 2, "nothing was asked of Shopify for a customer id"


async def test_the_cross_site_guard_does_not_apply_to_the_context_read_but_the_login_gate_does(client):
    session = client.runtime.sessions.get_or_create("c2")
    session.issue(ORDER)
    client.runtime.settings = client.runtime.settings.model_copy(update={"allowed_logins": "owner@example.com"})
    from app.main import app

    app.state.allowed_logins = client.runtime.allowed_logins
    refused = await client.get(f"/context/order/{ORDER}", params={"session_id": "c2"}, headers={"Tailscale-User-Login": "x@y.z", "X-Forwarded-For": "100.64.0.2"})
    assert refused.status_code == 403
    app.state.allowed_logins = ()
