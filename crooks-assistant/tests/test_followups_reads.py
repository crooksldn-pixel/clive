"""The round-12 deploy review's follow-ups: every read says only what it read.

Eight reads answered the owner with more certainty than they had. The rule for each: say only
what was read, and when a read was cut short or limited to a window, the spoken words and the
card say so — or the read covers the whole scope. Each test here fails on the code at the base
commit (ca90e2b3) and holds the fix to the behaviour, through the real read wherever there is
one: the order cache over a fake shop, `gmail_search` over a faked message listing, the read
scheduler and the anticipation layer themselves.

Every name, address and order below is invented.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app import recipes
from app.analytics.cache import OrderCache
from app.anticipation import engine as anticipation
from app.anticipation.models import Signal
from app.families import abandoned, landings, load_all
from app.presentation import present
from app.reads.scheduler import Read, ReadPlan, ReadResult, run_plan
from app.recipes import Ctx
from app.session.models import Session
from app.tools import analytics_tools, gmail_tools, registry, shopify_tools
from app.tools.dispatch import dispatch
from app.tools.registry import ToolError
from tests.test_abandoned import AbandonedStore
from tests.test_analytics import JEANS, JOGGERS, NOW, node
from tests.test_analytics_tools import ORDER_NODES, Store, london_now

load_all()


def _session(name: str) -> Session:
    session = Session(session_id=name)
    session.turn_id = f"turn_{name}"
    return session


def _bind_shop(nodes: list[dict]) -> Store:
    """The read tools over these orders, at the clock the fixtures were built at."""
    store = Store(nodes)
    analytics_tools.bind(OrderCache(lambda: store, clock=lambda: NOW.timestamp()))
    return store


@pytest.fixture()
def shop(monkeypatch):
    london_now(monkeypatch)
    yield _bind_shop
    analytics_tools.bind(None)


def _open(number: int, days_ago: float, who: str) -> dict:
    """An order still to go out, placed `days_ago` days before the fixture clock."""
    return node(number, days_ago=days_ago, items=[(*JEANS, "Blue", "M", 1, 90.0)],
                customer=(f"gid://shopify/Customer/{number}", who, 1, 90.0))


def _shipped(number: int, days_ago: float) -> dict:
    return node(number, days_ago=days_ago, items=[(*JOGGERS, "Black", "L", 1, 45.0)],
                customer=(f"gid://shopify/Customer/{number}", "Rae Shaw", 1, 45.0), fulfillment="FULFILLED")


async def _landing(recipe_id: str, session: Session):
    ctx = Ctx(runtime=None, session=session, branch=session.branch())
    return await recipes.run(recipes.RECIPES[recipe_id], ctx)


def _cards(answer, session: Session) -> list[dict]:
    """What the tap puts on the glass: the recipe's own cards in front of the ones drawn from
    the reads it names (app/routes/command.py)."""
    calls = list(answer.calls if answer.drawn is None else answer.drawn)
    return [s.as_ui() for s in answer.surfaces] + [i for i in present(calls, session=session) if i["type"] != "context_stack"]


def _older_read(monkeypatch, *, fail: bool = False, complete: bool = True) -> None:
    """The Orders landing's read of the months before its 30-day list fails, or answers
    incomplete — the order cache still filling them after a restart. Every other read runs."""
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        period = (args or {}).get("period")
        if name == "commerce_query" and isinstance(period, dict) and period.get("days_ago"):
            if fail:
                raise ToolError("Shopify did not answer in time.")
            result = await real(name, args, timeout_s=timeout_s)
            return {**result, "complete": complete,
                    "note": "" if complete else "The server is still reading older orders."}
        return await real(name, args, timeout_s=timeout_s)

    monkeypatch.setattr(registry, "invoke", invoke)


def _numbers(item: dict) -> list[str]:
    return [str(o.get("order_number") or "") for o in item["data"].get("orders") or []]


# ===================================================== F-02: the Orders landing's window


@pytest.mark.usefixtures("owner_asking")
async def test_an_order_older_than_the_orders_window_is_listed_not_answered_as_nothing(shop):
    """An unfulfilled order 45 days old and one 120 days old, nothing waiting in the last 30
    days. The landing read only `last_30_days` and said "Nothing is waiting to go out."; both
    are now counted, the oldest is named, and a card lists them. A shop with no open order at
    all still gets the plain answer."""
    shop([_open(3101, 45, "Nell Oakes"), _open(3102, 120, "Pip Quill"), _shipped(3103, 2), _shipped(3104, 0.2)])
    session = _session("f02a")
    answer = await _landing("landing_orders", session)
    assert not answer.deferred, answer.defer
    assert "Nothing is waiting to go out" not in answer.answer, answer.answer
    assert answer.answer.startswith("2 orders to go out; the oldest is CROOKS-3102 at 120 days."), answer.answer
    assert answer.partial is False, "both reads were whole"
    listed = [n for item in _cards(answer, session) if item["type"] == "order_list" for n in _numbers(item)]
    assert any("3101" in n for n in listed) and any("3102" in n for n in listed), listed

    shop([_shipped(3105, 40), _shipped(3106, 3), _shipped(3107, 0.2)])
    plain = await _landing("landing_orders", _session("f02b"))
    assert plain.answer.startswith("Nothing is waiting to go out."), plain.answer
    assert plain.partial is False


@pytest.mark.usefixtures("owner_asking")
async def test_an_unread_or_incomplete_older_read_still_draws_a_card_saying_so(shop, monkeypatch):
    """Nothing in the last 30 days, and the read of the months before failed: the answer is
    not "Nothing is waiting to go out." and the landing does not draw zero cards — one card
    says nothing in the window is waiting and older orders could not be checked."""
    shop([_open(3111, 45, "Nell Oakes"), _shipped(3112, 2)])
    real = registry.invoke
    _older_read(monkeypatch, fail=True)
    session = _session("f02c")
    answer = await _landing("landing_orders", session)
    assert "Nothing is waiting to go out" not in answer.answer, answer.answer
    assert answer.answer.startswith("Nothing in the last 30 days is waiting to go out, but older orders could not be checked."), answer.answer
    assert answer.partial is True
    cards = _cards(answer, session)
    assert cards, "never zero cards"
    (card,) = [c for c in cards if c["type"] == "order_list"]
    assert card["freshness"]["complete"] is False and card["data"]["complete"] is False
    assert "older orders could not be checked" in card["data"]["note"], card["data"]
    assert card["data"]["orders"] == []

    # The same with the older read answering but incomplete, on a shop with nothing open.
    shop([_shipped(3113, 50), _shipped(3114, 2)])
    monkeypatch.setattr(registry, "invoke", real)
    _older_read(monkeypatch, complete=False)
    session = _session("f02d")
    answer = await _landing("landing_orders", session)
    assert "Nothing is waiting to go out" not in answer.answer, answer.answer
    assert "the read of older orders is not complete" in answer.answer, answer.answer
    assert answer.partial is True
    (card,) = [c for c in _cards(answer, session) if c["type"] == "order_list"]
    assert card["freshness"]["complete"] is False and "not complete" in card["data"]["note"]


@pytest.mark.usefixtures("owner_asking")
async def test_orders_waiting_beside_an_incomplete_older_read_are_on_a_card_marked_incomplete(shop, monkeypatch):
    shop([_open(3121, 10, "Nell Oakes"), _open(3122, 45, "Pip Quill"), _shipped(3123, 0.2)])
    _older_read(monkeypatch, complete=False)
    session = _session("f02e")
    answer = await _landing("landing_orders", session)
    assert answer.answer.startswith("2 orders to go out; the oldest is CROOKS-3122 at 45 days. "
                                    "The read of older orders is not complete, so more may be waiting."), answer.answer
    assert answer.partial is True
    # The landing's own card, in place of the 30-day list's: the same orders, marked incomplete.
    (card,) = [s.as_ui() for s in answer.surfaces]
    assert card["type"] == "order_list"
    assert card["freshness"]["complete"] is False and card["data"]["complete"] is False
    assert "not complete" in card["data"]["note"], card["data"]
    assert sorted(n[-4:] for n in _numbers(card)) == ["3121", "3122"], _numbers(card)
    drawn = present(list(answer.drawn), session=session)
    assert not [c for c in drawn if c["type"] == "order_list" and "3121" in str(_numbers(c))], \
        "the 30-day list is not also drawn as though it were whole"


@pytest.mark.usefixtures("owner_asking")
async def test_waiting_orders_with_both_reads_incomplete_have_both_gaps_on_the_card(shop, monkeypatch):
    """Orders waiting, and the 30-day read and the read of older orders both incomplete: the
    landing's own card used to carry only the older read's caveat, so the owner was not told
    the 30-day list itself may be short. The card's note and its freshness caveat say both."""
    shop([_open(3125, 10, "Nell Oakes"), _open(3126, 45, "Pip Quill"), _shipped(3127, 0.2)])
    _older_read(monkeypatch, complete=False)
    older = registry.invoke

    async def invoke(name, args, *, timeout_s):
        result = await older(name, args, timeout_s=timeout_s)
        if name == "commerce_query" and (args or {}).get("period") == "last_30_days":
            return {**result, "complete": False, "note": "The server is still reading recent orders."}
        return result

    monkeypatch.setattr(registry, "invoke", invoke)
    session = _session("f02e2")
    answer = await _landing("landing_orders", session)
    assert answer.partial is True
    assert "The read of older orders is not complete" in answer.answer, answer.answer
    assert "The server is still reading recent orders." in answer.answer, answer.answer
    (card,) = [s.as_ui() for s in answer.surfaces]
    assert card["type"] == "order_list"
    assert card["freshness"]["complete"] is False and card["data"]["complete"] is False
    note = card["data"]["note"]
    assert "The read of the last 30 days is not complete" in note, note
    assert "The read of older orders is not complete" in note, note
    # The subtitle and freshness line are cut at 80 characters, so they carry one short line
    # that still names both reads, whole rather than cut off.
    for said in (card["freshness"]["caveat"], card["subtitle"]):
        assert said == "The last 30 days read and the older orders read are both incomplete.", said
    assert sorted(n[-4:] for n in _numbers(card)) == ["3125", "3126"], _numbers(card)


@pytest.mark.usefixtures("owner_asking")
async def test_the_oldest_named_is_the_oldest_of_every_order_the_answer_counts(shop):
    """Orders 5, 45, 200 and 362 days old: the count covers all four and "the oldest" is the
    362-day one, so no sentence can name an order older than the one called the oldest."""
    shop([_open(3131, 5, "Nell Oakes"), _open(3132, 45, "Pip Quill"), _open(3133, 200, "Una Vale"),
          _open(3134, 362, "Wyn Xu"), _shipped(3135, 0.2)])
    answer = await _landing("landing_orders", _session("f02f"))
    assert answer.answer.startswith("4 orders to go out; the oldest is CROOKS-3134 at 362 days."), answer.answer
    ages = [int(n) for n in re.findall(r"at (\d+) days", answer.answer)]
    assert ages and max(ages) == 362 and ages[0] == 362, answer.answer


# ============================================ F-02: the summary's lookback, said as one


async def _attention(session: Session) -> tuple[dict, dict]:
    calls: list = []
    await dispatch("commerce_summary", {"task": "orders_attention", "limit": 12}, session=session, timeout_s=6.0, calls=calls)
    assert calls and calls[-1].ok, calls
    (card,) = [i for i in present(calls, session=session) if i["type"] == "summary_list"]
    return calls[-1].result, card


@pytest.mark.usefixtures("owner_asking")
async def test_the_unqualified_attention_answer_says_the_ninety_days_it_read(shop):
    """`orders_attention` with no period reads ninety days. A 120-day-old order still waiting is
    not in it, so neither the words nor the card may say "Nothing needs attention" of the shop —
    and with no order in the window the note never says "Read from the 0 orders"."""
    shop([_open(3141, 120, "Pip Quill"), _shipped(3142, 150)])
    result, card = await _attention(_session("f02g"))
    assert "Only orders placed in the last 90 days were read" in result["note"], result["note"]
    data = card["data"]
    assert data["count"] == 0 and data["empty_words"] == "Nothing placed in the last 90 days needs attention.", data
    assert data["empty_words"] != "Nothing needs attention."
    assert "Read from the 0" not in data["note"] and "older orders were not checked" in data["note"], data["note"]

    shop([_open(3143, 45, "Nell Oakes"), _open(3144, 120, "Pip Quill")])
    result, card = await _attention(_session("f02h"))
    data = card["data"]
    assert data["count"] == 1 and [r["label"] for r in data["rows"]] == ["#3143"], data["rows"]
    assert "in the last 90 days" in card["spoken_summary"], card["spoken_summary"]
    assert data["note"].startswith("Read from the 1 order placed in the last 90 days;"), data["note"]


# ===================================================== F-03: the recent inbox, as listed


class _Request:
    def __init__(self, value) -> None:
        self.value = value

    def execute(self):
        return self.value


class FakeGmail:
    """The two calls `gmail_search` makes of Gmail: the message listing, newest first and at
    most `maxResults` long, and each listed message's metadata. Nothing else is faked — the
    bulk filter, the fold to one entry per thread and the count are the tool's own."""

    def __init__(self, held: list[dict]) -> None:
        self.held = held
        self.asked: list[int] = []

    def service(self):
        return self

    def reset(self) -> None:
        pass

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId="me", q="", maxResults=10, **_k):  # noqa: N803 — Gmail's own names
        self.asked.append(maxResults)
        return _Request({"messages": [{"id": m["id"], "threadId": m["threadId"]} for m in self.held[:maxResults]]})

    def get(self, userId="me", id="", **_k):  # noqa: A002, N803
        return _Request(next(m for m in self.held if m["id"] == id))


def _email(mid: str, thread: str, sender: str, subject: str, *, bulk: bool = False) -> dict:
    headers = {"From": sender, "Subject": subject, "Date": "Tue, 8 Sep 2026 10:00:00 +0100"}
    if bulk:
        headers["List-Unsubscribe"] = "<mailto:leave@offers.example>"
    return {"id": mid, "threadId": thread, "snippet": subject,
            "payload": {"headers": [{"name": k, "value": v} for k, v in headers.items()]}}


def _bulk(n: int, start: int = 0) -> list[dict]:
    return [_email(f"b{start + i}", f"tb{start + i}", "Offers <offers@brand.example>", f"Sale {i}", bulk=True) for i in range(n)]


async def _recent(monkeypatch, held: list[dict], *, partial: bool = False):
    """The Inbox landing's recent read, made by the real `gmail_search` with the plan's own
    arguments over a faked listing, and the landing's answer to it."""
    fake = FakeGmail(held)
    monkeypatch.setattr(gmail_tools, "_client", fake)
    monkeypatch.setattr(gmail_tools, "_customer_lookup", None)
    session = _session("f03")
    ctx = Ctx(runtime=None, session=session, branch=session.branch())
    (args,) = [r.args for r in landings._inbox_plan(ctx).reads if r.name == "inbox"]
    body = await gmail_tools.gmail_search(**args)
    assert fake.asked == [landings.RECENT_LIMIT], fake.asked
    result = ReadResult(values={"inbox": body}, partial=partial)
    return body, landings._recent_render(ctx, result), landings._inbox_render(ctx, result), session


@pytest.mark.parametrize("held", [
    pytest.param(_bulk(6) + [_email("p1", "tp1", "Tess Ray <tess@example.com>", "My order")] + _bulk(5, 6), id="11-bulk-1-person"),
    pytest.param(_bulk(12), id="12-bulk"),
    pytest.param([_email(f"t{i}", "tlong", "Kim Lau <kim@example.com>", "Sizing") for i in range(6)]
                 + [_email(f"o{i}", f"to{i}", f"Ola {i} <ola{i}@example.com>", "Hello") for i in range(6)], id="6-in-one-thread-and-6"),
])
async def test_a_recent_read_that_reached_its_limit_says_it_was_the_newest_emails(monkeypatch, held):
    """Twelve messages listed is the listing's limit, whatever is left after bulk mail is
    dropped and a thread's messages are folded to one: the week was not read to its end. The
    answer is worded as among the 12 newest emails, is partial, and its card says so."""
    body, recent, inbox, _session = await _recent(monkeypatch, held)
    assert body["listed"] == 12, body
    assert recent.partial is True and inbox.partial is True
    assert "among the 12 newest emails" in recent.answer, recent.answer
    assert "this week" not in recent.answer.split(".")[0], recent.answer
    assert "Nothing from a person in the inbox this week" not in inbox.answer, inbox.answer
    (card,) = [s.as_ui() for s in inbox.surfaces if s.ui_type == "email_list"]
    assert card["freshness"]["complete"] is False and "12 newest emails" in card["data"]["note"], card
    assert inbox.drawn == [], "the search's own card would say nothing of where the read stopped"
    people = [t for t in body["threads"] if not t.get("likely_bulk")]
    assert [t["thread_id"] for t in card["data"]["threads"]] == [t["thread_id"] for t in people]


async def test_a_recent_read_short_of_its_limit_is_the_week_and_its_empty_answer_keeps_partial(monkeypatch):
    """Fewer messages than the limit is the whole week, said as the week. And the empty answer
    carries the read's own partial flag: it used to drop it."""
    body, recent, _inbox, _s = await _recent(monkeypatch, [_email("p1", "tp1", "Tess Ray <tess@example.com>", "My order")] + _bulk(2))
    assert body["listed"] == 3 and recent.partial is False
    assert "this week; the newest is Tess Ray about My order." in recent.answer, recent.answer

    body, recent, _inbox, _s = await _recent(monkeypatch, _bulk(3), partial=True)
    assert recent.answer == "Nothing from a person in the inbox this week."
    assert recent.partial is True, "the empty answer is partial whenever the read was"


# ================================================ F-04: a checkout past its twentieth item


class LongCheckoutStore(AbandonedStore):
    """One checkout with 21 items, served as Shopify serves `lineItems(first: 20)`: twenty of
    them and `hasNextPage`. Its twenty-first, a scarf, is on no other checkout."""

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        if "CrooksAbandonedCheckouts" not in query:
            return await super().graphql(query, variables)
        items = [(f"gid://shopify/ProductVariant/77{i:02d}", f"Sample Tee {i}") for i in range(20)]
        items.append(("gid://shopify/ProductVariant/7799", "Lone Scarf"))

        def line(variant: str, title: str) -> dict:
            return {"node": {"title": title, "variantTitle": "One size", "quantity": 1, "variant": {"id": variant},
                             "product": {"id": "gid://shopify/Product/770", "title": title}}}

        long = {"id": "gid://shopify/AbandonedCheckout/77", "name": "#C77", "createdAt": "2026-09-08T10:00:00Z",
                "completedAt": None, "totalPriceSet": {"shopMoney": {"amount": "420.00", "currencyCode": "GBP"}},
                "customer": None,
                "lineItems": {"edges": [line(v, t) for v, t in items[:20]], "pageInfo": {"hasNextPage": True}}}
        short = {**long, "id": "gid://shopify/AbandonedCheckout/78", "name": "#C78",
                 "lineItems": {"edges": [line(*items[0])], "pageInfo": {"hasNextPage": False}}}
        return {"data": {"abandonedCheckouts": {"edges": [{"node": long}, {"node": short}], "pageInfo": {"hasNextPage": False}}}}


async def test_a_ranking_with_a_checkout_cut_at_twenty_items_is_marked_incomplete():
    shopify_tools.bind(LongCheckoutStore())
    body = await abandoned.shopify_abandoned_checkouts(days=14)
    assert "Lone Scarf" not in [i["item"] for i in body["items"]], "Shopify never sent the twenty-first"
    assert body.get("items_complete") is False, body
    assert "Items partial" in body["note"] and "first 20" in body["note"], body["note"]
    _figures, ranking = abandoned.cards(body)
    assert ranking.data["complete"] is False and ranking.freshness.complete is False
    assert "of the items read" in ranking.data["subtitle"], ranking.data["subtitle"]
    assert body["items_partial"] in ranking.data["note"]
    assert "pageInfo { hasNextPage }" in abandoned.ABANDONED_QUERY.split("lineItems", 1)[1], "the read asks whether there are more"


# ===================================== AC1-NEW-01: the restock set is the rows it returned


@pytest.mark.usefixtures("owner_asking")
async def test_a_cover_bound_restock_set_holds_exactly_the_rows_returned(shop):
    store = shop(ORDER_NODES)
    black_l = ORDER_NODES[0]["lineItems"]["edges"][0]["node"]["variant"]["id"]
    blue_m = ORDER_NODES[2]["lineItems"]["edges"][0]["node"]["variant"]["id"]
    store.stock[black_l] = 2      # about 3.5 days of cover
    store.stock[blue_m] = 20      # far more than ten
    session = _session("ac1new")
    calls: list = []
    await dispatch("inventory_query", {"period": "last_7_days", "max_days_cover": 10}, session=session, timeout_s=5, calls=calls)
    result = calls[-1].result
    rows = result["rows"]
    assert rows and all(isinstance(r["days_cover"], (int, float)) and r["days_cover"] <= 10 for r in rows), rows
    variants = [r["key"]["variant_id"] for r in rows]
    assert variants == [black_l], variants
    held = session.sets[result["set"]["set_id"]]
    assert list(held.members) == variants, "these is exactly the variants the answer lists"
    assert result["set"]["count"] == len(rows) == result["row_count"]
    assert result["set"]["label"] == "Restock priority, 10 days of cover or less", result["set"]["label"]
    assert held.totals.get("units") == sum(r["units"] for r in rows), held.totals


# ============================ AC1-F-01: no address is not "not contacted"


@pytest.mark.usefixtures("owner_asking")
async def test_a_customer_with_no_email_address_is_not_in_the_rest(shop, monkeypatch):
    nameless = _open(3152, 8, "Nia Nash")
    nameless["customer"]["defaultEmailAddress"] = None
    shop([_open(3151, 6, "Ben Bold"), nameless])
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
        await dispatch("email_query", {"set_id": set_id, "days": 30}, session=session, timeout_s=5, calls=calls)
        result = calls[-1].result
    finally:
        analytics_tools.bind_email(None, None)
    assert [a["sender"] for a in asked] == ["ben@example.com"]
    assert result["counts"]["not_contacted"] == 1 and result["counts"]["unchecked"] == 1, result["counts"]
    assert result["no_address"] == 1 and "no email address" in result["note"], result
    rest = session.sets[result["set_not_contacted"]["set_id"]]
    assert set(rest.members) == {"gid://shopify/Order/3151"}, "the rest is only someone whose inbox was read"
    assert set(session.sets[result["set_unchecked"]["set_id"]].members) == {"gid://shopify/Order/3152"}
    nia = next(r for r in result["rows"] if r["customer_name"] == "Nia Nash")
    assert nia["checked"] is False and nia["latest_direction"] == "unknown", nia


# ======================================= S5-02: a dependency the plan does not hold


@pytest.mark.usefixtures("owner_asking")
async def test_a_read_waiting_on_a_read_the_plan_does_not_hold_is_never_dispatched(monkeypatch):
    dispatched: list[str] = []
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        dispatched.append(name)
        return await real(name, args, timeout_s=timeout_s)

    plan = ReadPlan([
        Read("orphan", "commerce_capabilities", {}, source="mac", after=("ghost",)),
        Read("child", "commerce_capabilities", {}, source="mac", after=("orphan",)),
        Read("free", "commerce_capabilities", {}, source="mac"),
    ], label="s5-02")
    monkeypatch.setattr(registry, "invoke", invoke)
    result = await run_plan(plan, session=_session("s502"))
    assert dispatched == ["commerce_capabilities"], dispatched
    assert "free" in result.values and "orphan" not in result.values and "child" not in result.values
    assert "ghost" in result.skipped["orphan"], result.skipped
    assert result.skipped["child"], result.skipped
    assert [g for g in result.groups if "orphan" in g or "child" in g] == []


# ============================================ S5-03: forgetting both halves of a conversation


class _Learner:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []
        self.observed = 0

    def observe(self, state: str, event: str):
        self.seen.append((state, event))
        self.observed += 1
        return SimpleNamespace(state=state, event=event)

    def likely(self, state: str, threshold: float | None = None):
        return []

    def save(self) -> None:
        pass


class _Prefetcher:
    def cancel_scope(self, scope: str, **_k) -> int:
        return 0

    def in_flight_for(self, scope: str, **_k) -> int:
        return 0

    def start(self, *_a, **_k) -> bool:
        return False

    def counts(self) -> dict:
        return {}


class _Memory:
    def get(self, *_a):
        return None


async def test_forgetting_a_conversation_forgets_both_its_halves():
    learner = _Learner()
    layer = anticipation.Anticipator(learner=learner, prefetcher=_Prefetcher(), memory=_Memory())

    def signal(branch: str, event: str, ref: str) -> Signal:
        return Signal(event=event, session_id="s503", login="owner@example.com", branch_id=branch, kind="order", ref=ref)

    await layer.on_signal(signal("b_left", "order_opened", "gid://shopify/Order/5101"), session=None)
    await layer.on_signal(signal("b_right", "order_opened", "gid://shopify/Order/5102"), session=None)
    assert learner.seen == [], "a first signal on each half has nothing before it"
    layer.forget(signal("b_left", "order_opened", "").scope)
    left = await layer.on_signal(signal("b_left", "next_record", "gid://shopify/Order/5103"), session=None)
    right = await layer.on_signal(signal("b_right", "next_record", "gid://shopify/Order/5104"), session=None)
    assert left.learned == "" and right.learned == "", (left.learned, right.learned)
    assert learner.seen == [], "nothing from before the forget was learned on either half"
