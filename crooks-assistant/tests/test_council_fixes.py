"""What the council found and what was changed for it — each held by a test so it cannot
come back: members survive the batch's own clock and a word spoken mid-run; undo members
are batch members from birth; a batch skips the courtesy read; Shopify's bucket paces a
run; a page Shopify can afford, halved when it says otherwise; stale rows kept and re-read;
coverage that admits a partial walk; sets that hold every match unless a number was asked
for, and issue only their own id; a declined answer after a tool that ran is not a false
claim; the inbox read says who it could not check."""

from __future__ import annotations

import time

import pytest

from app.actions import batch as batch_module
from app.analytics import cache as cache_module
from app.analytics import periods, sets
from app.analytics.cache import OrderCache
from app.analytics.engine import aggregate
from app.analytics.query import parse
from app.clients.shopify import ShopifyError
from app.observability import claims
from app.tools import analytics_tools
from app.tools.dispatch import dispatch
from tests import test_batch as tb
from tests.test_analytics import HOODIE, JEANS, JOGGERS, NOW, node
from tests.test_analytics_tools import ORDER_NODES, Store, london_now
from tests.test_batch import gesture, gid, lookup, orders_set, stage, store_of

# The admitted owner calling tools directly, as a request the door let through would — granted
# per test, to the tests that call a tool, and to no others (the 2026-09-28 deploy review, round
# 9, F-A2-FIXTURE and I-tests5 I-04). The tests of the cache, the walk and the prompt run with
# none, which is production's default; what a bulk change with none gets is held in
# tests/test_r11_no_authority.py.
AS_THE_OWNER = pytest.mark.usefixtures("owner_asking")

# The batch suite's fixtures, under their own names.
clock = tb.clock
engine = tb.engine
batches = tb.batches
session = tb.session
client = tb.client

LONDON = "Europe/London"


# ------------------------------------------------------------------------ the batch run


@AS_THE_OWNER
async def test_members_are_not_expired_by_the_cards_clock_while_the_batch_runs(engine, batches, session, clock):
    store = store_of(6)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    # Every Shopify call takes five seconds on this clock; the card had a minute left, and
    # eighteen calls take ninety.
    original = store.graphql

    async def slow(query, variables=None):
        clock.now += 5.0
        return await original(query, variables)

    store.graphql = slow  # type: ignore[method-assign]
    batch.expires_at = clock.now + 60.0
    for child in batch.eligible:
        session.proposal(child.proposal_id).expires_at = batch.expires_at
    result = await gesture(batches, batch)
    assert result.code == "done" and batch.counts["verified"] == 6 and batch.counts["not_attempted"] == 0, batch.counts
    assert len(store.mutations) == 6


@AS_THE_OWNER
async def test_a_word_spoken_while_the_batch_runs_withdraws_none_of_it_and_the_undo_survives(engine, batches, session):
    store = store_of(6)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    spoken = {"done": False}
    original = store.mutate

    async def mutate(name, variables):
        if not spoken["done"]:
            spoken["done"] = True
            # The next question arrives mid-run: what /turn does to the session.
            engine.revoke_pending(session, "new instruction")
            batches.revoke_pending(session, "new instruction")
            engine.advance_epoch(session, "new instruction")
            batches.advance_epoch(session)
        return await original(name, variables)

    store.mutate = mutate  # type: ignore[method-assign]
    result = await gesture(batches, batch)
    assert result.code == "done" and batch.counts["verified"] == 6, (batch.counts, [(c.label, c.code, session.proposal(c.proposal_id).reason) for c in batch.children])
    assert all(store.orders[gid(1000 + i)]["tags"] == ["hold"] for i in range(1, 7))
    undo = session.batches[batch.undo_id]
    assert undo.epoch == session.epoch, "the undo lives at the conversation's position now"
    back = await gesture(batches, undo)
    assert back.code == "done" and undo.counts["verified"] == 6


@AS_THE_OWNER
async def test_undo_members_are_batch_members_from_birth_and_the_batch_skips_the_courtesy_read(engine, batches, session):
    store = store_of(3)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    reads_before = store.reads
    await gesture(batches, batch)
    for child in batch.eligible:
        forward = session.proposal(child.proposal_id)
        undo = session.proposal(forward.undo_id)
        assert undo.batch_id == batch.undo_id and undo.batch_id != ""
        alone = await engine.commit(undo.proposal_id, "b1", caller="o", spec_lookup=lookup)
        assert alone.code == "batch_member"
    # Two reads per member (the precondition and the proof), never the order card's fuller read.
    assert store.reads - reads_before == 6 and store.tag_reads == {gid(1001): 3, gid(1002): 3, gid(1003): 3}


@AS_THE_OWNER
async def test_the_run_waits_for_shopifys_bucket_when_the_client_last_saw_it_low(engine, batches, session, monkeypatch):
    store = store_of(3)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    store.last_cost = {"requested": 100.0, "available": 20.0, "restore_rate": 50.0}
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(batch_module, "_sleep", fake_sleep)
    result = await gesture(batches, batch)
    assert result.code == "done" and batch.counts["verified"] == 3
    assert slept and all(0 < s <= batch_module.PACE_MAX_S for s in slept) and batch.paced_s == pytest.approx(sum(slept))
    store.last_cost = {"requested": 100.0, "available": 900.0, "restore_rate": 50.0}
    assert await batch_module.pace("shopify_order_tags_add") == 0.0
    assert await batch_module.pace("gmail_thread_archive") == 0.0


@AS_THE_OWNER
async def test_the_spoken_count_uses_what_the_owner_gestured_for(engine, batches, session):
    store = store_of(4, tagged={4: ["hold"]})
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    result = await gesture(batches, batch)
    assert result.spoken == "Tagged 3 of the 3 orders." and batch.all_verified and batch.public()["spoken"] == result.spoken
    from app.presentation import present_batch_state

    card = present_batch_state(batch, session=session, code="done")[0]["data"]
    assert card["title"] == "Tags added: 3 of 3" and card["all_verified"] is True and "1 excluded before the gesture" in card["detail"] and card["note"] == ""


# ------------------------------------------------------------------------ the cache


class CostlyStore(Store):
    """Shopify's own view of a page: it refuses one that would cost too much, and reports
    the bucket after each answer."""

    def __init__(self, nodes, *, max_n: int = 10) -> None:
        super().__init__(nodes)
        self.max_n = max_n
        self.sizes: list[int] = []
        self.last_cost: dict[str, float] = {}

    async def graphql(self, query, variables=None):
        v = variables or {}
        if "CrooksOrderRows" in query:
            n = int(v.get("n") or 0)
            self.sizes.append(n)
            if n > self.max_n:
                raise ShopifyError("That query was too expensive for Shopify; narrow it.")
        return await super().graphql(query, variables)


async def test_the_order_page_is_one_shopify_can_afford_and_halves_when_it_says_otherwise():
    nodes = [node(2000 + i, days_ago=i * 0.5 + 0.1, items=[(*JOGGERS, "Black", "L", 1, 45.0)]) for i in range(30)]
    assert cache_module.PAGE * (1 + 10 + 3 + 1 + 2 + 2 + cache_module.ITEMS_PER_ORDER * 6) < 1000, "ten orders of ten items is under Shopify's cost cap by the module's own arithmetic"
    store = CostlyStore(nodes, max_n=4)
    cache = OrderCache(lambda: store, clock=lambda: NOW.timestamp())
    view = await cache.view(periods.resolve("last_30_days", now=NOW), timeout_s=5)
    assert view.complete and len(view.rows) == 30
    assert cache.page == 4 and store.sizes[:2] == [8, 4] and all(n == 4 for n in store.sizes[1:]), "halved until Shopify accepted it, then kept"
    # A re-read by id asks for one order, whatever the page is.
    cache.invalidate(nodes[0]["id"])
    store.sizes.clear()
    view = await cache.view(periods.resolve("last_30_days", now=NOW), timeout_s=5)
    assert store.sizes == [1] and view.complete


async def test_stale_rows_are_kept_re_read_in_full_and_the_view_says_so_meanwhile():
    nodes = [node(3000 + i, days_ago=i * 0.2 + 0.1, items=[(*JEANS, "Blue", "M", 1, 90.0)]) for i in range(45)]
    store = Store(nodes)
    cache = OrderCache(lambda: store, clock=lambda: NOW.timestamp())
    period = periods.resolve("last_30_days", now=NOW)
    await cache.view(period, timeout_s=5)
    for n in nodes:
        cache.invalidate(n["id"])
    assert cache.size == 45, "nothing dropped"
    assert all(cache._orders[n["id"]].get("stale") for n in nodes)
    view = await cache.view(period, timeout_s=5)
    # Twenty re-read per sync; the rest stay marked and the view is honest about it.
    assert len(view.rows) == 45
    remaining = cache.status()["stale"]
    assert remaining == 25 and not view.complete and "being read again" in view.note
    await cache.view(period, timeout_s=5)
    await cache.view(period, timeout_s=5)
    view = await cache.view(period, timeout_s=5)
    assert cache.status()["stale"] == 0 and view.complete and not any(r.get("stale") for r in view.rows)


async def test_a_walk_that_stops_at_its_page_bound_is_not_reported_complete(monkeypatch):
    nodes = [node(4000 + i, days_ago=i + 0.1, items=[(*HOODIE, "Grey", "M", 1, 70.0)]) for i in range(30)]
    store = Store(nodes, page=5)
    monkeypatch.setattr(cache_module, "MAX_PAGES", 2)
    cache = OrderCache(lambda: store, clock=lambda: NOW.timestamp())
    view = await cache.view(periods.resolve("last_30_days", now=NOW), timeout_s=5)
    assert len(view.rows) == 10 and not view.complete and "reading further back" in view.note
    assert cache.status()["partial"] is True
    monkeypatch.setattr(cache_module, "MAX_PAGES", 60)
    view = await cache.view(periods.resolve("last_30_days", now=NOW), timeout_s=5)
    assert len(view.rows) == 30 and view.complete


# ------------------------------------------------------------------------ the figures


def test_money_by_product_is_the_lines_own_and_a_shared_refund_is_derived():
    rows = [node(5001, days_ago=1, items=[(*JOGGERS, "Black", "L", 1, 40.0), (*JEANS, "Blue", "M", 1, 60.0)], refunded=50.0)]
    q = parse({"period": "last_7_days", "group_by": ["product"], "metrics": ["revenue", "unfulfilled_value", "refunded"]}, now=NOW, tz=LONDON, default_entity="order_line_items")
    from app.analytics.cache import shape_order

    shaped = [shape_order(n, read_at=NOW.timestamp()) for n in rows]
    out = aggregate(q, shaped, now=NOW.timestamp(), tz=LONDON)
    by = {r["label"]: r for r in out["rows"]}
    assert by["Convict Joggers"]["unfulfilled_value"] == 40.0 and by["Yard Jeans"]["unfulfilled_value"] == 60.0, "each line's own value, not the order's on both"
    assert by["Convict Joggers"]["refunded"] == 20.0 and by["Yard Jeans"]["refunded"] == 30.0, "the order's refund shared by value"
    assert "refunded" in out["derived"] and "unfulfilled_value" in out["measured"] and out["item_level"] and "line items" in out["revenue_basis"]
    whole = aggregate(parse({"entity": "orders", "period": "last_7_days", "metrics": ["revenue", "refunded"], "view": "metrics"}, now=NOW, tz=LONDON, default_entity="orders"), shaped, now=NOW.timestamp(), tz=LONDON)
    assert whole["totals"]["refunded"] == 50.0 and "order totals" in whole["revenue_basis"]


def test_a_running_period_compares_with_the_same_stretch_before():
    rows = [node(6001, days_ago=1, items=[(*JOGGERS, "Black", "L", 1, 45.0)]), node(6002, days_ago=8, items=[(*JOGGERS, "Black", "L", 1, 45.0)]), node(6003, days_ago=12, items=[(*JOGGERS, "Black", "L", 1, 45.0)])]
    from app.analytics.cache import shape_order

    shaped = [shape_order(n, read_at=NOW.timestamp()) for n in rows]
    q = parse({"entity": "orders", "period": "this_week", "metrics": ["orders"], "compare": True, "view": "comparison"}, now=NOW, tz=LONDON, default_entity="orders")
    out = aggregate(q, shaped, now=NOW.timestamp(), tz=LONDON, previous_rows=shaped)
    # Wednesday afternoon: this week holds one order; last week to Wednesday afternoon held one
    # (8 days ago), not the two the whole of last week held.
    assert out["totals"]["orders"] == 1 and out["compare"]["totals"]["orders"] == 1 and out["compare"]["period"]["label"] == "last week to this point"
    assert periods.resolve("last_7_days", now=NOW).whole_days == 7 and periods.resolve("last_week", now=NOW).whole_days == 7 and periods.resolve("today", now=NOW).whole_days == 1


# ------------------------------------------------------------------------ the sets


@AS_THE_OWNER
async def test_a_set_holds_every_match_unless_a_number_was_asked_for_and_issues_only_its_id(session, monkeypatch):
    london_now(monkeypatch)
    store = Store(ORDER_NODES)
    cache = OrderCache(lambda: store, clock=lambda: NOW.timestamp())
    analytics_tools.bind(cache)
    try:
        calls: list = []
        await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled"}, "limit": 2}, session=session, timeout_s=5, calls=calls)
        two = calls[-1].result["set"]
        assert two["count"] == 2 and calls[-1].result["row_count"] == 3, "a number was asked for: the set is the rows shown"
        await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled"}}, session=session, timeout_s=5, calls=calls)
        every = calls[-1].result["set"]
        assert every["count"] == 3
        assert every["set_id"] in session.issued_ids
        shown = {r["order_id"] for r in calls[-1].result["rows"]}
        assert shown <= session.issued_ids, "the rows the owner saw are issued as any listing's are"
        # A ranking of customers with no limit holds every customer who matched, not ten.
        await dispatch("commerce_aggregate", {"entity": "customers", "period": "last_90_days", "metrics": ["lifetime_spent"], "limit": 2}, session=session, timeout_s=5, calls=calls)
        assert calls[-1].result["set"]["count"] == 2
        session.plan = None
        await dispatch("commerce_aggregate", {"entity": "customers", "period": "last_90_days", "metrics": ["lifetime_spent"], "filters": {"min_spent": 100}}, session=session, timeout_s=5, calls=calls)
        assert calls[-1].result["set"]["count"] == calls[-1].result["row_count"] and calls[-1].result["set"]["count"] > 2
    finally:
        analytics_tools.bind(None)


@AS_THE_OWNER
async def test_the_inbox_read_names_the_members_it_could_not_check(session, monkeypatch):
    london_now(monkeypatch)
    store = Store(ORDER_NODES)
    cache = OrderCache(lambda: store, clock=lambda: NOW.timestamp())
    analytics_tools.bind(cache)

    async def threads_for(**kwargs):
        return {"available": True, "threads": []}

    async def replied(thread_id):
        return False

    analytics_tools.bind_email(threads_for, replied)
    try:
        ws = sets.create(session, kind="orders", members=["gid://shopify/Order/1007", "gid://shopify/Order/1009", "gid://shopify/Order/9999"], label="delayed")
        calls: list = []
        await dispatch("email_query", {"set_id": ws.set_id, "days": 30}, session=session, timeout_s=5, calls=calls)
        result = calls[-1].result
        assert result["counts"] == {"contacted": 0, "not_contacted": 2, "replied": 0, "needs_reply": 0, "unchecked": 1}
        assert "1 of the set's orders are outside the 90 days" in result["note"]
        assert session.focus["set"] == ws.set_id, "the set the owner asked about stays in focus"
        assert result["set_not_contacted"]["count"] == 2 and "set_contacted" not in result
        assert analytics_tools.EMAIL_MAX_CUSTOMERS == batch_module.MAX_BATCH
    finally:
        analytics_tools.bind_email(None, None)
        analytics_tools.bind(None)


# ------------------------------------------------------------------------ the claim


def test_a_decline_after_the_tool_ran_is_not_a_false_claim():
    reg = frozenset({"commerce_query", "commerce_aggregate"})
    honest = claims.claim("which orders are older than five days", "I can't see any orders that old; everything has shipped.", [{"tool": "commerce_query", "ok": True}], reg)
    assert honest is not None and honest["false_unsupported"] is False and honest["attempted"] == ["commerce_query"]
    failed = claims.claim("which orders are older than five days", "I can't see any orders that old.", [{"tool": "commerce_query", "ok": False}], reg)
    assert failed["false_unsupported"] is True, "a tool that failed was not reached for successfully"
    hinted = claims.claim("what sold best by colour", "I can't break that down.", [], reg, hinted=True)
    assert hinted["false_unsupported"] is True and hinted["hinted"] is True


def test_the_context_lines_tell_the_model_what_the_mac_knows():
    from app.routes.turn import FAMILY_LINE_PREFIX, _context_lines
    from app.session.models import Session

    s = Session(session_id="x")
    s.last_outcome = "Tagged 3 of the 3 orders."
    s.last_query = {"tool": "commerce_aggregate", "entity": "order_line_items", "period": "this month", "group_by": ["product"], "metrics": ["units"], "filters": {}, "limit": 10}
    lines = _context_lines(s, "what sold best by colour last month")
    assert lines[0].startswith("[The last change, as CLIVE proved it: \"Tagged 3 of the 3 orders.\"") and s.last_outcome == ""
    assert lines[1].startswith("[Last read-layer query:") and "commerce_aggregate" in lines[1]
    assert lines[2].startswith("[This asks for") and "commerce_aggregate" in lines[2] and s.hinted
    s.last_query = None
    # Nothing of the CONVERSATION is left to say. What may still be there is the capability
    # family block: a fact about the Mac rather than about this session, added to every
    # question so the model stops attempting what this build cannot do
    # (app/routes/turn.py `_family_lines`). It must not be mistaken for state that failed to
    # clear, and it is only there at all when some family is unavailable.
    rest = [line for line in _context_lines(s, "hello") if not line.startswith(FAMILY_LINE_PREFIX)]
    assert rest == [] and not s.hinted


@AS_THE_OWNER
async def test_batch_state_after_a_lost_connection(client):
    from tests.test_actions_routes import PROXIED

    runtime = client.runtime
    s = runtime.sessions.get_or_create("s9")
    s.epoch = max(s.epoch, 1)
    ws = orders_set(s, client.store, clock=time.time)
    calls: list = []
    await dispatch("batch_order_tags_add", {"set_id": ws.set_id, "tags": ["hold"]}, session=s, timeout_s=10, calls=calls)
    batch_id = calls[-1].proposal_id
    done = await client.post(f"/batches/{batch_id}/commit", data={"session_id": "s9"}, headers=PROXIED)
    assert done.status_code == 200 and done.json()["undo"]["batch_id"]
    later = await client.get(f"/batches/{batch_id}", params={"session_id": "s9"}, headers=PROXIED)
    body = later.json()
    assert body["status"] == "done" and body["spoken"] == "Tagged 2 of the 2 orders." and body["undo"]["batch_id"] == done.json()["undo"]["batch_id"]
    assert body["ui"][0]["type"] == "batch_result" and s.last_outcome == "Tagged 2 of the 2 orders."
