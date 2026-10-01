"""The round-12 deploy review's follow-ups: reads that answered with more certainty than they had.

The rule for every one of them is the same: say only what was read. When a read was cut short
or limited to a window, the words and the card say so — or the read covers the whole scope.
Each test names the finding it holds, and each fails on the tree the findings were filed
against (b577bc97):

* **F/F-02** — the Orders landing listed only the last 30 days and said "Nothing is waiting to
  go out" over a 45-day-old unfulfilled order; the unqualified attention summary read 90 days
  and said nothing of it.
* **F/F-03** — the recent-inbox read takes the newest twelve, and said nobody had written this
  week when those twelve were bulk mail; its empty answer dropped the read's partial flag.
* **F/F-04** — an abandoned checkout's line items past the twentieth were never read, and the
  ranking was drawn as whole.
* **AC1/AC1-NEW-01** — `inventory_query(max_days_cover=N)` attached a working set made before
  the bound was applied, so "these" held variants the rows had left out.
* **AC1-F-01** — `email_query` answered a customer with no email address as checked, with no
  threads, and put them in "not contacted".
* **S5/S5-02** — the read scheduler ran a read whose `after` named a read the plan did not hold.
* **S5/S5-03** — `forget(scope)` left the per-half positions behind, so the next signal learned
  a transition from before the conversation ended.

Every name, address and order here is invented.
"""

from __future__ import annotations

import asyncio

import pytest

from app import recipes
from app.analytics.cache import OrderCache
from app.families import abandoned, landings, load_all
from app.presentation import MAX_THREADS
from app.providers.base import ToolCall
from app.reads.scheduler import Read, ReadPlan, ReadResult, run_plan
from app.session.branch import Branch
from app.session.models import Session
from app.tools import analytics_tools, shopify_tools
from app.tools.dispatch import dispatch
from tests.test_abandoned import AbandonedStore
from tests.test_analytics import HOODIE, JEANS, JOGGERS, node
from tests.test_analytics_tools import NOW, ORDER_NODES, Clock, Store, london_now

load_all()


def _bind(nodes) -> Store:
    store = Store(nodes)
    analytics_tools.bind(OrderCache(lambda: store, clock=Clock(NOW.timestamp())))
    return store


@pytest.fixture()
def unbind():
    yield
    analytics_tools.bind(None)


def _session(name: str) -> Session:
    session = Session(session_id=name)
    session.turn_id = f"turn_{name}"
    return session


# ================================================================ F/F-02: the Orders landing

# Two unfulfilled orders older than the landing's thirty days — one 45 days old, one 120 — and
# a shipped order this week. Nothing placed in the last thirty days is waiting.
OLD_OPEN = [
    node(2101, days_ago=45, items=[(*JEANS, "Blue", "M", 1, 90.0)], customer=("gid://shopify/Customer/7101", "Nell Price", 1, 90.0)),
    node(2102, days_ago=120, items=[(*HOODIE, "Grey", "L", 1, 70.0)], customer=("gid://shopify/Customer/7102", "Otto Vance", 1, 70.0)),
    node(2103, days_ago=3, items=[(*JOGGERS, "Black", "M", 1, 45.0)], customer=("gid://shopify/Customer/7103", "Pip Quarles", 2, 95.0),
         fulfillment="FULFILLED"),
]
# The same shop with nothing open at all.
NOTHING_OPEN = [OLD_OPEN[2]]


async def _land(name: str):
    session = _session(name)
    ctx = recipes.Ctx(runtime=None, session=session, branch=session.branch())
    answer = await recipes.run(recipes.RECIPES["landing_orders"], ctx)
    assert not answer.deferred, answer.defer
    return answer, ctx


@pytest.mark.usefixtures("owner_asking", "unbind")
async def test_the_orders_landing_never_says_nothing_is_waiting_over_an_older_open_order(monkeypatch):
    london_now(monkeypatch)
    _bind(OLD_OPEN)
    answer, ctx = await _land("f02-old")
    assert "Nothing is waiting to go out" not in answer.answer, answer.answer
    # Listed: both older orders are on the list that is said, drawn and walked.
    assert answer.answer.startswith("2 orders to go out; the oldest is CROOKS-2102 at 120 days"), answer.answer
    assert "placed before the last 30 days" in answer.answer, answer.answer
    listing = answer.drawn[0].result
    assert [r["order_number"] for r in listing["rows"]] == ["CROOKS-2102", "CROOKS-2101"], listing["rows"]
    assert "last 360 days" in listing["title"], "the card says the window it read"
    walked = ctx.session.sets[ctx.branch.workflow.set_id].members
    assert walked == ("gid://shopify/Order/2102", "gid://shopify/Order/2101"), walked
    assert answer.partial is False, "both reads were whole"

    # A shop with no open order at all still gets the plain answer.
    _bind(NOTHING_OPEN)
    plain, _ctx = await _land("f02-none")
    assert plain.answer.startswith("Nothing is waiting to go out."), plain.answer
    assert plain.partial is False


@pytest.mark.usefixtures("owner_asking", "unbind")
async def test_the_unqualified_attention_summary_says_how_far_back_it_read(monkeypatch):
    """The 45-day order is inside the summary's lookback and is listed; the 120-day one is not,
    so the card and the words the model reads say where the read began."""
    from app.presentation import compact, present

    london_now(monkeypatch)
    _bind(OLD_OPEN)
    session = _session("f02-summary")
    calls: list = []
    await dispatch("commerce_summary", {"task": "orders_attention", "limit": 12}, session=session, timeout_s=6.0, calls=calls)
    assert calls and calls[-1].ok, calls
    result = calls[-1].result
    assert "Only orders placed since 11 Jun were read" in result["note"], result["note"]
    (card,) = [item for item in compact(present(calls, session=session)) if item["type"] == "summary_list"]
    data = card["data"]
    labels = [row["label"] for row in data["rows"]]
    assert "#2101" in labels and "#2102" not in labels, labels
    assert "placed since 11 Jun" in data["note"] and "before then is not in this" in data["note"], data["note"]
    assert data["empty_words"] == "Nothing placed since 11 Jun needs attention.", data["empty_words"]


# An unfulfilled order 362 days old: before the long read's 360 days, inside the year the order
# cache keeps. Nothing else is waiting.
YEAR_OLD = [
    node(2104, days_ago=362, items=[(*JOGGERS, "Pink", "S", 1, 45.0)], customer=("gid://shopify/Customer/7104", "Rue Sutton", 1, 45.0)),
    OLD_OPEN[2],
]


@pytest.mark.usefixtures("owner_asking", "unbind")
async def test_the_orders_landing_reads_the_whole_year_the_cache_keeps(monkeypatch):
    """Round 13, F-01: the long read stopped at 360 days, so an order older than that was read
    by nothing and the landing still said nothing was waiting."""
    london_now(monkeypatch)
    _bind(YEAR_OLD)
    answer, ctx = await _land("f01-year")
    assert "Nothing is waiting to go out" not in answer.answer, answer.answer
    assert answer.answer.startswith(
        "Nothing placed in the last 360 days is waiting to go out. 1 order placed before the last 360 days is still "
        "to go out; the oldest is CROOKS-2104 at 362 days."), answer.answer
    listing = answer.drawn[0].result
    assert [r["order_number"] for r in listing["rows"]] == ["CROOKS-2104"], listing["rows"]
    walked = ctx.session.sets[ctx.branch.workflow.set_id].members
    assert walked == ("gid://shopify/Order/2104",), walked
    assert answer.partial is False, "every read was whole"


@pytest.mark.usefixtures("owner_asking", "unbind")
async def test_an_unread_oldest_stretch_is_said_in_the_words_and_on_the_card(monkeypatch):
    """When the days before the long read could not be read, the plain answer is not given:
    the words and the long read's card say how far back the read went."""
    from app.presentation import compact, present
    from app.tools import registry
    from app.tools.registry import ToolError

    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        period = (args or {}).get("period")
        if name == "commerce_query" and isinstance(period, dict) and period.get("days_ago"):
            raise ToolError("Shopify did not answer in time.")
        return await real(name, args, timeout_s=timeout_s)

    monkeypatch.setattr(registry, "invoke", invoke)
    london_now(monkeypatch)
    _bind(NOTHING_OPEN)
    session = _session("f01-unread")
    ctx = recipes.Ctx(runtime=None, session=session, branch=session.branch())
    answer = await recipes.run(recipes.RECIPES["landing_orders"], ctx)
    assert not answer.deferred, answer.defer
    assert "Nothing is waiting to go out" not in answer.answer, answer.answer
    assert answer.answer.startswith("Nothing placed in the last 360 days is waiting to go out, and orders placed "
                                    "before then could not be checked."), answer.answer
    assert answer.partial is True
    (reach,) = [c for c in answer.drawn if c.result.get("title") == "To go out, last 360 days"]
    assert "could not be checked" in reach.result["note"] and reach.result["coverage"]["complete"] is False
    # The screen as the tap draws it (app/routes/command.py): the landing's own cards, then the
    # reads', compacted.
    screen = compact([s.as_ui() for s in answer.surfaces] + present(answer.drawn, session=session))
    (card,) = [item for item in screen if item["data"].get("title") == "To go out, last 360 days"]
    assert card["type"] == "order_list" and card["data"]["empty"] is True, card
    assert card["data"]["note"] == ("Nothing placed in the last 360 days is waiting to go out. "
                                    "Orders placed before the last 360 days could not be checked."), card
    assert card["freshness"]["complete"] is False, card

    # With older orders in the long read, the list is drawn as read, marked partial.
    _bind(OLD_OPEN)
    session = _session("f01-unread-older")
    ctx = recipes.Ctx(runtime=None, session=session, branch=session.branch())
    answer = await recipes.run(recipes.RECIPES["landing_orders"], ctx)
    assert answer.answer.startswith("2 orders to go out; the oldest is CROOKS-2102 at 120 days, placed before the last 30 days. "
                                    "Orders placed before the last 360 days could not be checked."), answer.answer
    assert answer.partial is True
    screen = compact([s.as_ui() for s in answer.surfaces] + present(answer.drawn, session=session))
    (listing,) = [item for item in screen if item["data"].get("title") == "To go out, last 360 days"]
    assert listing["type"] == "order_list" and "partial" in listing["data"]["query"], listing["data"]


# ================================================================ F/F-03: the recent inbox


def _bulk(n: int) -> list[dict]:
    return [{"thread_id": f"18f1000000000{i:03d}", "from": "Weekly Drops", "from_email": "news@drops.example",
             "subject": f"New in, week {i}", "likely_bulk": True} for i in range(n)]


def test_twelve_bulk_threads_are_not_nobody_writing_this_week():
    ctx = recipes.Ctx(runtime=None, session=_session("f03"), branch=Branch(branch_id="b", session_id="f03"))
    full = landings._recent_render(ctx, ReadResult(values={"inbox": {"threads": _bulk(landings.RECENT_LIMIT), "count": 12}}))
    assert "Nothing from a person in the inbox" not in full.answer, full.answer
    assert full.answer.startswith(f"None of the {landings.RECENT_LIMIT} newest threads this week is from a person"), full.answer
    assert full.partial is True, "a read that came back at its limit did not cover the week"

    # Nothing listed at all says how far the read goes, and is partial when the read was.
    empty = landings._recent_render(ctx, ReadResult(values={"inbox": {"threads": [], "count": 0}}, partial=True))
    assert "Nothing from a person in the inbox" not in empty.answer, empty.answer
    assert f"the read takes the {landings.RECENT_LIMIT} newest" in empty.answer, empty.answer
    assert empty.partial is True, "the read was partial, so the empty answer is"


def test_people_among_a_read_cut_at_its_limit_are_not_everyone_this_week():
    """Round 13, F-02: with a person among the twelve, the answer said "threads from people this
    week" as though the week had been read."""
    ctx = recipes.Ctx(runtime=None, session=_session("f03-people"), branch=Branch(branch_id="b", session_id="f03-people"))
    person = {"thread_id": "18f2000000000001", "from": "Tess Ward", "from_email": "tess@example.com",
              "subject": "Size swap", "likely_bulk": False}
    threads = [person, *_bulk(landings.RECENT_LIMIT - 1)]
    full = landings._recent_render(ctx, ReadResult(values={"inbox": {"threads": threads, "count": 12}}))
    assert full.answer == (f"1 of the {landings.RECENT_LIMIT} newest threads this week is from a person; the newest is "
                           f"Tess Ward about Size swap. Mail before those {landings.RECENT_LIMIT} was not read."), full.answer
    assert full.partial is True, "a read that came back at its limit did not cover the week"

    # Under the limit the read was not cut, and the answer is the one it always was.
    short = landings._recent_render(ctx, ReadResult(values={"inbox": {"threads": [person], "count": 1}}))
    assert "was not read" not in short.answer and short.answer.endswith("the newest is Tess Ward about Size swap."), short.answer
    assert short.partial is False


def _inbox_screen(name: str, threads: list[dict]):
    """The Inbox landing's answer and its screen as the tap draws it (app/routes/command.py):
    the landing's own cards, then the reads', compacted."""
    from app.presentation import compact, present

    session = _session(name)
    ctx = recipes.Ctx(runtime=None, session=session, branch=session.branch())
    body = {"query": "newer_than:7d", "count": len(threads), "threads": threads, "note": ""}
    call = ToolCall(name="gmail_search", args={"query": "", "days": landings.RECENT_DAYS, "limit": landings.RECENT_LIMIT},
                    result=body)
    answer = landings._inbox_render(ctx, ReadResult(values={"inbox": body}, calls=[call]))
    assert not answer.deferred, answer.defer
    return answer, compact([s.as_ui() for s in answer.surfaces] + present(answer.drawn, session=session))


def test_a_recent_inbox_read_cut_at_its_limit_says_so_on_its_card():
    """Round 13, F-03-CARD: the words said only the newest twelve were read, while the card was
    the search read's own, which says neither how many were checked nor that older mail was not."""
    person = {"thread_id": "18f2000000000001", "from": "Tess Ward", "from_email": "tess@example.com",
              "subject": "Size swap", "likely_bulk": False}
    note = f"Only the {landings.RECENT_LIMIT} newest threads were checked; mail before them was not read."
    for threads in (_bulk(landings.RECENT_LIMIT), [person, *_bulk(landings.RECENT_LIMIT - 1)]):
        answer, screen = _inbox_screen("f03-card", threads)
        assert answer.partial is True
        assert answer.drawn == [], "the search read's own card does not say the read stopped short"
        (card,) = [item for item in screen if item["type"] == "email_list"]
        assert card["data"]["note"] == note, card["data"]
        assert card["data"]["checked"] == landings.RECENT_LIMIT and card["data"]["complete"] is False, card["data"]
        assert card["freshness"]["complete"] is False and card["freshness"]["caveat"] == note, card
        # The rows are the search read's, as its own card would draw them.
        assert card["data"]["count"] == landings.RECENT_LIMIT, card["data"]
        assert [t["thread_id"] for t in card["data"]["threads"]] == [t["thread_id"] for t in threads][:MAX_THREADS], card["data"]

    # Under the limit the week was read, and the search read's own card is drawn as it was.
    answer, screen = _inbox_screen("f03-card-short", [person])
    assert [c.name for c in answer.drawn] == ["gmail_search"] and answer.surfaces == []
    (card,) = [item for item in screen if item["type"] == "email_list"]
    assert "note" not in card["data"] and "checked" not in card["data"], card["data"]


# ================================================================ F/F-04: the 21st line item

LONG = "gid://shopify/AbandonedCheckout/900"
TEES = [f"gid://shopify/ProductVariant/{9500 + i}" for i in range(21)]


class LongCheckoutStore(AbandonedStore):
    """The usual checkouts, and one more of 21 different tees. Shopify serves the first 20 of
    its lines, as `lineItems(first: 20)` asks, and says it holds more."""

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        body = await super().graphql(query, variables)
        if "CrooksAbandonedCheckouts" not in query:
            return body
        served = TEES[:20]
        body["data"]["abandonedCheckouts"]["edges"].append({"node": {
            "id": LONG, "name": "#C900", "createdAt": "2026-09-08T10:00:00Z", "completedAt": None,
            "totalPriceSet": {"shopMoney": {"amount": "420.00", "currencyCode": "GBP"}},
            "customer": None,
            "lineItems": {"pageInfo": {"hasNextPage": True}, "edges": [
                {"node": {"title": f"Stripe Tee {i + 1}", "variantTitle": "White / M", "quantity": 1,
                          "variant": {"id": v}, "product": {"id": f"gid://shopify/Product/{9600 + i}", "title": f"Stripe Tee {i + 1}"}}}
                for i, v in enumerate(served)
            ]},
        }})
        return body


async def test_a_ranking_that_missed_a_checkouts_later_items_says_so():
    shopify_tools.bind(LongCheckoutStore())
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    counted = {i["variant_id"] for i in body["items"]}
    assert TEES[20] not in counted, "the 21st tee was never read"
    # So the ranking is not whole, in the words the model reads and on the card.
    assert body["items_complete"] is False, body
    assert "Partial ranking" in body["note"] and "first 20" in body["note"], body["note"]
    figures, ranking = abandoned.cards(body)
    assert figures.data["complete"] is True, "the count and the value are the checkouts' own and stand"
    assert ranking.data["complete"] is False and ranking.freshness.complete is False
    assert "first 20" in ranking.data["note"] and "first 20" in ranking.freshness.caveat
    assert ranking.data["subtitle"].endswith("of those read"), ranking.data["subtitle"]


# ================================================================ AC1/AC1-NEW-01: the cover bound


@pytest.mark.usefixtures("owner_asking", "unbind")
async def test_the_set_a_cover_bound_attaches_is_exactly_its_rows(monkeypatch):
    london_now(monkeypatch)
    store = _bind(ORDER_NODES)
    black_l = ORDER_NODES[0]["lineItems"]["edges"][0]["node"]["variant"]["id"]
    blue_m = ORDER_NODES[2]["lineItems"]["edges"][0]["node"]["variant"]["id"]
    store.stock[black_l] = 2      # 3.5 days of cover
    store.stock[blue_m] = 20      # about 47 days; every other variant is untracked, cover unknown
    session = _session("ac1")
    calls: list = []
    await dispatch("inventory_query", {"period": "last_7_days", "max_days_cover": 10}, session=session, timeout_s=5, calls=calls)
    assert calls and calls[-1].ok, calls
    result = calls[-1].result
    rows = result["rows"]
    assert [r["key"]["variant_id"] for r in rows] == [black_l], rows
    held = result["set"]
    ws = session.sets[held["set_id"]]
    assert ws.members == (black_l,), "the set is the rows: no variant with more cover, none with unknown cover"
    assert held["count"] == len(rows) == 1
    assert "10 days of cover or less" in held["label"], held["label"]
    assert held["totals"].get("units") == sum(r["units"] for r in rows), held["totals"]


@pytest.mark.usefixtures("owner_asking", "unbind")
async def test_a_row_limited_cover_bound_with_nothing_cut_still_makes_the_set_from_its_rows(monkeypatch):
    """Round 13, F-03: when every row shown was within the bound, the set was left as the engine
    made it, and the engine's membership can run past the rows shown."""
    within, above, unknown = ("gid://shopify/ProductVariant/8801", "gid://shopify/ProductVariant/8802",
                              "gid://shopify/ProductVariant/8803")
    result = {
        "rows": [{"key": {"variant_id": within}, "label": "Stripe Tee · White / M", "days_cover": 2.5, "units": 4, "revenue": 120.0}],
        "row_count": 3, "truncated": True, "totals_scope": "period",
        "member_ids": [within, above, unknown],
        "member_labels": {within: "Stripe Tee · White / M", above: "Stripe Tee · Navy / L", unknown: "Stripe Tee · Red / S"},
        "member_totals": {"units": 30, "revenue": 900.0},
    }
    analytics_tools._within_cover(result, 10)
    assert result["member_ids"] == [within], "the set is the row shown: not the variant above the bound, nor the unknown one"
    assert result["member_labels"] == {within: "Stripe Tee · White / M"}
    assert result["member_totals"] == {"units": 4, "revenue": 120.0}
    assert [r["key"]["variant_id"] for r in result["rows"]] == [within]

    # And through the tool, with a row limit and more variants within the bound than it shows.
    london_now(monkeypatch)
    store = _bind(ORDER_NODES)
    black_l = ORDER_NODES[0]["lineItems"]["edges"][0]["node"]["variant"]["id"]
    blue_m = ORDER_NODES[2]["lineItems"]["edges"][0]["node"]["variant"]["id"]
    store.stock[black_l] = 2      # 3.5 days of cover
    store.stock[blue_m] = 20      # about 47 days
    session = _session("ac1-limit")
    calls: list = []
    await dispatch("inventory_query", {"period": "last_7_days", "max_days_cover": 60, "limit": 1}, session=session, timeout_s=5, calls=calls)
    assert calls and calls[-1].ok, calls
    rows = calls[-1].result["rows"]
    assert [r["key"]["variant_id"] for r in rows] == [black_l], rows
    held = calls[-1].result["set"]
    assert session.sets[held["set_id"]].members == (black_l,) and held["count"] == 1, held
    assert "60 days of cover or less" in held["label"], held["label"]
    assert held["totals"].get("units") == rows[0]["units"], held["totals"]


# ================================================================ AC1-F-01: no email address

BEN, FLO, GUS = "gid://shopify/Order/1002", "gid://shopify/Order/1007", "gid://shopify/Order/1009"


@pytest.mark.usefixtures("owner_asking", "unbind")
async def test_a_customer_with_no_address_is_never_in_the_rest(monkeypatch):
    london_now(monkeypatch)
    nodes = [dict(n) for n in ORDER_NODES]
    gus = next(i for i, n in enumerate(nodes) if n["id"] == GUS)
    nodes[gus] = {**nodes[gus], "customer": {**nodes[gus]["customer"], "defaultEmailAddress": None}}
    _bind(nodes)
    asked: list[dict] = []

    async def threads_for(**kwargs):
        asked.append(kwargs)
        return {"available": True, "threads": []}

    async def replied(thread_id):
        return False

    analytics_tools.bind_email(threads_for, replied)
    try:
        session = _session("ac1f01")
        calls: list = []
        await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled"},
                                          "title": "Delayed orders"}, session=session, timeout_s=5, calls=calls)
        set_id = calls[-1].result["set"]["set_id"]
        assert set(session.sets[set_id].members) == {BEN, FLO, GUS}
        await dispatch("email_query", {"set_id": set_id, "days": 30}, session=session, timeout_s=5, calls=calls)
        result = calls[-1].result
        assert calls[-1].ok, calls[-1]
    finally:
        analytics_tools.bind_email(None, None)
    assert {a["sender"] for a in asked} == {"ben@example.com", "flo@example.com"}, "no inbox was looked in for Gus"
    assert result["counts"]["not_contacted"] == 2 and result["counts"]["unchecked"] == 1, result["counts"]
    rest = session.sets[result["set_not_contacted"]["set_id"]]
    assert set(rest.members) == {BEN, FLO}, "the rest is only who was looked for and had not written"
    assert GUS in session.sets[result["set_unchecked"]["set_id"]].members
    assert "1 customer(s) have no email address" in result["note"], result["note"]
    gus_row = next(r for r in result["rows"] if r["customer_name"] == "Gus Gee")
    assert gus_row["checked"] is False and gus_row["latest_direction"] == "unknown", gus_row


# ================================================================ S5/S5-02: a missing dependency


async def test_a_read_waiting_on_a_read_the_plan_does_not_hold_never_runs(monkeypatch):
    import app.tools.shopify_tools  # noqa: F401 — registered so the plan can name them
    from app.providers.base import ToolCall

    ran: list[str] = []

    async def fake_dispatch(name, args, *, session, timeout_s, calls=None):  # noqa: ARG001
        ran.append(str(args.get("query") or args.get("order_id")))
        if calls is not None:
            calls.append(ToolCall(name=name, args=args, ok=True, result={"read": name}))
        return "{}"

    monkeypatch.setattr("app.tools.dispatch.dispatch", fake_dispatch)
    result = await run_plan(ReadPlan([
        Read("free", "shopify_find_order", {"query": "free"}),
        Read("orphan", "shopify_order_detail", {"order_id": "orphan"}, after=("ghost",)),
        Read("child", "shopify_order_detail", {"order_id": "child"}, after=("orphan",)),
    ], label="test"), session=_session("s5"))
    assert ran == ["free"], ran
    assert "ghost" in result.skipped["orphan"] and "does not hold" in result.skipped["orphan"], result.skipped
    assert "child" in result.skipped and "child" not in result.values, result.skipped
    assert result.groups == [["free"]]


# ================================================================ S5/S5-03: forgetting both halves


async def test_forgetting_a_conversation_forgets_both_halves(monkeypatch):
    import app.tools.gmail_tools  # noqa: F401 — registered so the predictions can name them
    import app.tools.shopify_tools  # noqa: F401
    from app.anticipation import engine as engine_mod
    from app.anticipation.learning import Learner
    from app.anticipation.models import Signal
    from app.memory import Memory
    from app.memory.prefetch import Prefetcher
    from app.providers.base import ToolCall

    async def fake_dispatch(name, args, *, session, timeout_s, calls=None):  # noqa: ARG001
        await asyncio.sleep(0.01)
        if calls is not None:
            calls.append(ToolCall(name=name, args=args, ok=True, result={"read": name}))
        return "{}"

    monkeypatch.setattr("app.tools.dispatch.dispatch", fake_dispatch)

    def opened(branch_id: str, n: int) -> Signal:
        return Signal(event="order_opened", session_id="s5-03", login="owner@example.com", branch_id=branch_id,
                      kind="order", ref=f"gid://shopify/Order/{n}", features=("unfulfilled",),
                      ids={"order_id": f"gid://shopify/Order/{n}"})

    layer = engine_mod.Anticipator(learner=Learner(clock=lambda: 1_000_000.0), prefetcher=Prefetcher(), memory=Memory())
    session = Session(session_id="s5-03", login="owner@example.com")
    await layer.on_signal(opened("b_left", 1), session=session)
    await layer.on_signal(opened("b_right", 2), session=session)
    scope = opened("b_left", 1).scope
    layer.forget(scope)
    assert not [key for key in layer._last if key == scope or key.startswith(f"{scope}|")], layer._last
    for branch_id, n in (("b_left", 3), ("b_right", 4)):
        decision = await layer.on_signal(opened(branch_id, n), session=session)
        assert decision.learned == "", f"{branch_id} learned {decision.learned} from before the forget"
    layer.forget(scope)
