"""The read tools against a fake store: the cache reads pages once and answers from memory,
extends backwards for a longer period, refreshes what changed, serves what it has when
Shopify is slow and says so; the tools speak the language and refuse what is outside it;
a turn's queries are bounded and never repeated; the catalogue is what the model is told."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.analytics import cache as cache_module
from app.analytics import plan
from app.analytics.cache import OrderCache
from app.clients.shopify import ShopifyThrottled
from app.session.models import Session
from app.tools import analytics_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.conftest import FakeShopify
from tests.test_analytics import HOODIE, JEANS, JOGGERS, NOW, node

ORDER_NODES = [
    node(1001, days_ago=1, items=[(*JOGGERS, "Black", "L", 3, 45.0)], customer=("gid://shopify/Customer/1", "Ann Able", 3, 410.0), fulfillment="FULFILLED"),
    node(1002, days_ago=2, items=[(*JOGGERS, "Black", "M", 1, 45.0), (*JEANS, "Blue", "M", 1, 90.0)], customer=("gid://shopify/Customer/2", "Ben Bold", 1, 135.0)),
    node(1003, days_ago=3, items=[(*JEANS, "Blue", "M", 2, 90.0)], customer=("gid://shopify/Customer/3", "Cy Cole", 5, 900.0), fulfillment="FULFILLED"),
    node(1005, days_ago=6, items=[(*JOGGERS, "Black", "L", 1, 45.0), (*HOODIE, "Grey", "L", 1, 70.0)], customer=("gid://shopify/Customer/1", "Ann Able", 3, 410.0), fulfillment="FULFILLED"),
    node(1007, days_ago=9, items=[(*JEANS, "Black", "L", 1, 90.0)], customer=("gid://shopify/Customer/6", "Flo Fry", 1, 90.0), country="IE"),
    node(1009, days_ago=20, items=[(*HOODIE, "Grey", "M", 1, 70.0)], customer=("gid://shopify/Customer/7", "Gus Gee", 1, 70.0), tags=["delayed"]),
    node(1010, days_ago=38, items=[(*JEANS, "Blue", "M", 1, 90.0), (*JOGGERS, "Black", "L", 1, 45.0)], customer=("gid://shopify/Customer/3", "Cy Cole", 5, 900.0), fulfillment="FULFILLED"),
    node(1011, days_ago=45, items=[(*JOGGERS, "Pink", "M", 2, 45.0)], customer=("gid://shopify/Customer/8", "Hal Hood", 1, 90.0), fulfillment="FULFILLED"),
    node(1012, days_ago=120, items=[(*JEANS, "Blue", "L", 1, 90.0)], customer=("gid://shopify/Customer/9", "Ivy Ink", 1, 90.0), fulfillment="FULFILLED"),
]


def _bound(query: str, key: str) -> float | None:
    import re

    match = re.search(key + r":(>=|<)'([^']+)'", query)
    if not match:
        return None
    return datetime.fromisoformat(match.group(2).replace("Z", "+00:00")).timestamp()


class Store(FakeShopify):
    """Answers the cache's two queries from the nodes above, paged, with Shopify's own search
    semantics for created_at and updated_at bounds. Can be slow or throttled."""

    def __init__(self, nodes=ORDER_NODES, *, page=None) -> None:
        super().__init__([])
        self.nodes = [dict(n) for n in nodes]
        self.page = page
        self.delay_s = 0.0
        self.throttle_once = False
        self.throttled = 0
        self.pages = 0
        self.stock: dict[str, int] = {}
        self._tz = ZoneInfo("Europe/London")

    async def timezone(self):
        return self._tz

    async def graphql(self, query, variables=None):
        self.queries.append((query, variables or {}))
        v = variables or {}
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if "CrooksVariantStock" in query:
            nodes = []
            for vid in v.get("ids") or []:
                item = next((i for n in self.nodes for e in n["lineItems"]["edges"] for i in [e["node"]] if i["variant"]["id"] == vid), None)
                if item is None:
                    continue
                nodes.append({"id": vid, "title": item["variantTitle"], "inventoryQuantity": self.stock.get(vid), "inventoryItem": {"tracked": vid in self.stock}, "product": item["product"], "selectedOptions": item["variant"]["selectedOptions"]})
            return {"data": {"nodes": nodes}}
        if "CrooksOrderRows" not in query:
            raise AssertionError(f"unexpected query {query[:50]}")
        if self.throttle_once:
            self.throttle_once = False
            self.throttled += 1
            raise ShopifyThrottled("Shopify is rate-limiting us. Try again in a moment.", wait_s=0.01)
        q = str(v.get("q") or "")
        rows = self.nodes
        if q.startswith("id:"):
            rows = [n for n in self.nodes if n["id"].endswith("/" + q[3:])]
            q = ""
        lower, upper = _bound(q, "created_at"), None
        import re

        upper_match = re.search(r"created_at:<'([^']+)'", q)
        if upper_match:
            upper = datetime.fromisoformat(upper_match.group(1).replace("Z", "+00:00")).timestamp()
        updated = _bound(q, "updated_at")
        selected = []
        for n in rows:
            ts = datetime.fromisoformat(n["createdAt"].replace("Z", "+00:00")).timestamp()
            uts = datetime.fromisoformat(n["updatedAt"].replace("Z", "+00:00")).timestamp()
            if lower is not None and ts < lower:
                continue
            if upper is not None and ts >= upper:
                continue
            if updated is not None and uts < updated:
                continue
            selected.append(n)
        selected.sort(key=lambda n: n["createdAt"], reverse=True)
        size = self.page or int(v.get("n") or 40)
        start = int(v.get("after") or 0)
        page = selected[start : start + size]
        self.pages += 1
        return {"data": {"orders": {"edges": [{"cursor": str(start + i + 1), "node": n} for i, n in enumerate(page)], "pageInfo": {"hasNextPage": start + size < len(selected)}}}}


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def store():
    return Store()


@pytest.fixture()
def clock():
    return Clock(NOW.timestamp())


@pytest.fixture()
def cache(store, clock):
    c = OrderCache(lambda: store, clock=clock)
    analytics_tools.bind(c)
    yield c
    analytics_tools.bind(None)


@pytest.fixture()
def session():
    s = Session(session_id="a1")
    s.turn_id = "turn_test"
    return s


def london_now(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(analytics_tools, "datetime", FixedDatetime)


# --------------------------------------------------------------------------- the cache


async def test_the_cache_reads_the_window_once_and_answers_from_memory(store, cache, clock):
    from app.analytics.periods import resolve

    month = resolve("last_30_days", now=NOW)
    view = await cache.view(month)
    assert view.complete and len(view.rows) == 6 and store.pages == 1 and view.covered_days >= 29
    again = await cache.view(month)
    assert store.pages == 1 and again.complete and again.age_s == 0.0, "served from memory"
    # A longer period reaches further back, reading only the orders older than what is held.
    quarter = resolve("last_90_days", now=NOW)
    view = await cache.view(quarter)
    assert view.complete and len(view.rows) == 8 and store.pages == 2
    assert "created_at:<" in str(store.queries[-1][1]["q"]), "the backfill stops where the cache already reaches"
    # Time passes: a delta sync reads what changed, not the whole window again.
    clock.now += cache_module.TTL_S + 1
    store.nodes[0]["displayFulfillmentStatus"] = "FULFILLED"
    store.nodes[0]["updatedAt"] = datetime.fromtimestamp(clock.now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    view = await cache.view(month)
    assert store.pages == 3 and "updated_at:>=" in store.queries[-1][1]["q"] and view.complete
    assert next(o for o in view.rows if o["order_number"] == "CROOKS-1001")["fulfillment"] == "FULFILLED"
    assert cache.status()["orders"] == 8 and cache.status()["pages_read"] == 3


async def test_the_cache_pages_through_shopify_and_survives_a_throttle(store, cache):
    from app.analytics.periods import resolve

    store.page = 3
    store.throttle_once = True
    view = await cache.view(resolve("since_launch", now=NOW))
    assert view.complete and len(view.rows) == 9 and store.pages == 3 and store.throttled == 1, "three pages of three, after the throttled attempt"


async def test_a_slow_shopify_gets_what_the_cache_holds_and_an_honest_note(store, cache, clock):
    from app.analytics.periods import resolve

    store.delay_s = 0.3
    view = await cache.view(resolve("last_7_days", now=NOW), timeout_s=0.05)
    assert not view.complete and view.rows == [] and "still reading" in view.note
    await asyncio.sleep(0.4)
    view = await cache.view(resolve("last_7_days", now=NOW), timeout_s=0.05)
    assert view.complete and len(view.rows) == 4


async def test_an_applied_change_drops_the_order_until_it_is_read_again(store, cache, clock):
    from app.analytics.periods import resolve

    month = resolve("last_30_days", now=NOW)
    await cache.view(month)
    cache.invalidate("gid://shopify/Order/1001")
    assert cache.status()["orders"] == 6 and cache.status()["stale"] == 1, "kept, marked, read again — never dropped"
    view = await cache.view(month)
    assert len(view.rows) == 6 and store.pages == 2 and cache.status()["stale"] == 0, "the next view re-read what changed"


async def test_stock_is_read_in_one_call_per_chunk_and_held_briefly(store, cache, clock):
    vid = ORDER_NODES[0]["lineItems"]["edges"][0]["node"]["variant"]["id"]
    store.stock[vid] = 3
    stock = await cache.stock([vid, "gid://shopify/ProductVariant/999", "gid://shopify/Order/1"])
    assert stock[vid]["available"] == 3 and stock[vid]["tracked"] and stock[vid]["size"] == "L" and store.pages == 0
    reads = len(store.queries)
    await cache.stock([vid])
    assert len(store.queries) == reads, "held"
    clock.now += cache_module.STOCK_TTL_S + 1
    await cache.stock([vid])
    assert len(store.queries) == reads + 1


# --------------------------------------------------------------------------- the tools


def test_the_read_tools_are_green_or_amber_reads_never_writes():
    for name in ("commerce_aggregate", "inventory_query", "commerce_capabilities"):
        assert classify(name, {}).tier is Tier.GREEN and classify(name, {}).disposition is Disposition.EXECUTE_NOW
    assert classify("commerce_query", {}).tier is Tier.AMBER, "it names customers"
    from app.tools import registry

    for name in analytics_tools.PLANNED | {"commerce_capabilities"}:
        assert registry.get(name).write is None


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_best_sellers_through_the_tool(store, cache, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    text = await dispatch("commerce_aggregate", {"period": "last_30_days", "group_by": ["product"], "metrics": ["units", "revenue"], "view": "ranking", "title": "Best sellers"}, session=session, timeout_s=5, calls=calls)
    assert text.startswith("{") and '"Convict Joggers"' in text and '"units": 5' in text
    result = calls[-1].result
    assert result["rows"][0]["label"] == "Convict Joggers" and result["rows"][0]["units"] == 5 and result["coverage"]["complete"] and result["cost"] == 2
    assert result["view"] == "ranking" and result["title"] == "Best sellers" and "member_ids" not in text and "variant_ids" not in text
    assert result["source"].startswith("Shopify orders created in the period")


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_comparison_and_a_customer_ranking_through_the_tool(store, cache, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    await dispatch("commerce_aggregate", {"entity": "orders", "period": "this_week", "metrics": ["orders", "revenue", "aov"], "compare": True, "view": "comparison"}, session=session, timeout_s=5, calls=calls)
    result = calls[-1].result
    assert result["totals"]["orders"] == 2 and result["compare"]["totals"]["orders"] == 1 and result["compare"]["change"]["orders"]["delta"] == 1, "Monday to now against last week to the same point, never the whole of it"
    assert result["compare"]["period"]["label"] == "last week to this point"
    await dispatch("commerce_aggregate", {"entity": "customers", "period": "last_90_days", "filters": {"min_spent": 250}, "metrics": ["lifetime_spent", "lifetime_orders"]}, session=session, timeout_s=5, calls=calls)
    result = calls[-1].result
    assert [r["label"] for r in result["rows"]] == ["Cy Cole", "Ann Able"]
    assert "gid://shopify/Customer/3" in session.issued_ids, "the customers in the answer are issued to the conversation"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_restock_priority_through_the_tool(store, cache, session, monkeypatch):
    london_now(monkeypatch)
    black_l = ORDER_NODES[0]["lineItems"]["edges"][0]["node"]["variant"]["id"]
    blue_m = ORDER_NODES[2]["lineItems"]["edges"][0]["node"]["variant"]["id"]
    store.stock[black_l] = 2
    store.stock[blue_m] = 20
    calls = []
    text = await dispatch("inventory_query", {"period": "last_7_days", "limit": 5}, session=session, timeout_s=5, calls=calls)
    result = calls[-1].result
    first = result["rows"][0]
    assert first["label"] == "Convict Joggers · Black / L" and first["stock"] == 2 and first["units"] == 4 and first["velocity"] == 0.57 and first["days_cover"] == 3.5
    assert result["mode"] == "restock_priority" and "not a forecast" in result["note"] and result["measured"] == ["units", "stock"] and result["derived"] == ["velocity", "days_cover"]
    assert "not a forecast" in text
    only = await dispatch("inventory_query", {"period": "last_7_days", "product": "jeans", "max_days_cover": 60}, session=session, timeout_s=5, calls=calls)
    assert '"Yard Jeans' in only and "Joggers" not in only


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_listing_becomes_rows_the_tablet_can_show_and_ids_the_conversation_may_use(store, cache, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    text = await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled", "older_than_days": 5}, "title": "Delayed orders"}, session=session, timeout_s=5, calls=calls)
    result = calls[-1].result
    assert [r["order_number"] for r in result["rows"]] == ["CROOKS-1007", "CROOKS-1009"] and result["totals"]["orders"] == 2 and result["member_ids"] == ["gid://shopify/Order/1007", "gid://shopify/Order/1009"]
    assert "member_ids" not in text and "gid://shopify/Order/1009" in session.issued_ids and text.startswith("AMBER")
    refused = await dispatch("commerce_query", {"entity": "products"}, session=session, timeout_s=5, calls=calls)
    assert refused.startswith("ERROR") and "commerce_aggregate" in refused


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_queries_outside_the_language_are_refused_with_the_reason(store, cache, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    text = await dispatch("commerce_aggregate", {"group_by": ["region"]}, session=session, timeout_s=5, calls=calls)
    assert text.startswith("ERROR: Query not understood: Unknown group_by: region") and calls[-1].ok is False
    text = await dispatch("commerce_aggregate", {"filters": {"in_set": "set_deadbeef"}}, session=session, timeout_s=5, calls=calls)
    assert "no working set set_deadbeef" in text


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_turns_queries_are_bounded_and_the_same_one_is_not_run_twice(store, cache, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    args = {"period": "last_7_days", "group_by": ["product"], "metrics": ["units"]}
    first = await dispatch("commerce_aggregate", args, session=session, timeout_s=5, calls=calls)
    pages = store.pages
    second = await dispatch("commerce_aggregate", dict(args), session=session, timeout_s=5, calls=calls)
    assert second.startswith("(the same query already ran this turn") and second.endswith(first) and store.pages == pages
    assert calls[-1].result == {"reused": True} and session.plan.calls == 1
    # The bound itself lives with the lanes now (app/reads/budget.py): `plan.MAX_CALLS` is a
    # mirror of the foreground lane's, so a test that narrows the bound narrows the lane.
    from app.reads import budget as read_budget

    monkeypatch.setitem(read_budget.BUDGETS, read_budget.FOREGROUND,
                        read_budget.Budget(calls=2, cost=plan.TURN_COST, elapsed_s=plan.MAX_ELAPSED_S))
    await dispatch("commerce_aggregate", {"period": "last_7_days", "group_by": ["size"], "metrics": ["units"]}, session=session, timeout_s=5, calls=calls)
    refused = await dispatch("commerce_aggregate", {"period": "last_7_days", "group_by": ["colour"], "metrics": ["units"]}, session=session, timeout_s=5, calls=calls)
    assert refused.startswith("REFUSED: this turn has already run 2 queries") and calls[-1].ok is False
    session.turn_id = "turn_next"
    fresh = await dispatch("commerce_aggregate", {"period": "last_7_days", "group_by": ["colour"], "metrics": ["units"]}, session=session, timeout_s=5, calls=calls)
    assert not fresh.startswith("REFUSED"), "a new turn starts a new plan"
    monkeypatch.setitem(read_budget.BUDGETS, read_budget.FOREGROUND,
                        read_budget.Budget(calls=8, cost=3, elapsed_s=plan.MAX_ELAPSED_S))
    session.turn_id = "turn_costly"
    costly = await dispatch("commerce_aggregate", {"period": "last_90_days", "group_by": ["product"], "metrics": ["units"]}, session=session, timeout_s=5, calls=calls)
    assert "query budget is spent" in costly and calls[-1].ok is False


def test_the_catalogue_is_the_language_and_says_it_is_read_only():
    cat = analytics_tools.catalogue()
    assert cat["read_only"] is True and "order_line_items" in cat["entities"] and cat["filters"]["fulfillment"]["values"] == ["unfulfilled", "partial", "fulfilled", "any"]
    assert cat["bounds"]["limit"] == 50 and any(e["ask"].startswith("best sellers") for e in cat["examples"])
    assert "days_cover" in cat["metrics"] and "since_launch" in cat["periods"]
