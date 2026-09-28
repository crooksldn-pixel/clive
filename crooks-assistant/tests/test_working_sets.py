"""Working sets: the exact things a listing found, held on the Mac under a short id. They
are immutable, bound to one conversation, expire when it goes quiet, remember where they
came from, and are what "these" means — to a follow-up query, to the inbox beside them, and
(later) to a change applied to all of them at once."""

from __future__ import annotations

import pytest

from app.analytics import sets
from app.analytics.cache import OrderCache
from app.analytics.present import working_set_items
from app.presentation import present
from app.session.models import Session
from app.tools import analytics_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_analytics_tools import NOW, Clock, Store, london_now

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")


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


class Ticking:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


# ------------------------------------------------------------------------------- the store


def test_a_set_is_immutable_issued_and_in_focus():
    session = Session(session_id="s1")
    session.turn_id = "turn_1"
    clock = Ticking()
    ws = sets.create(session, kind="orders", members=["gid://shopify/Order/1", "gid://shopify/Order/2", "gid://shopify/Order/1"], label="  unfulfilled older than  5 days ", provenance={"tool": "commerce_query", "step": "query"}, sample=[{"ref": "gid://shopify/Order/1", "label": "#1001"}], totals={"revenue": 155.0, "orders": 2}, clock=clock)
    assert ws.set_id.startswith("set_") and ws.count == 2 and ws.members == ("gid://shopify/Order/1", "gid://shopify/Order/2") and ws.label == "unfulfilled older than 5 days"
    assert ws.session_id == "s1" and ws.turn_id == "turn_1" and ws.step == "query" and ws.parent is None
    assert session.sets[ws.set_id] is ws and session.focus["set"] == ws.set_id
    assert ws.set_id in session.issued_ids and "gid://shopify/Order/1" not in session.issued_ids, "the set's id is issued; being in a set is not being looked up"
    with pytest.raises((AttributeError, TypeError)):
        ws.members = ()  # type: ignore[misc]
    public = ws.public()
    assert public["count"] == 2 and public["sample"] == [{"ref": "gid://shopify/Order/1", "label": "#1001"}] and public["totals"] == {"revenue": 155.0, "orders": 2} and "members" not in public
    assert sets.members_by_id(session) == {ws.set_id: frozenset({"gid://shopify/Order/1", "gid://shopify/Order/2"})}
    line = sets.prompt_line(session, clock=clock)
    assert ws.set_id in line and "2 orders" in line and "in_set" in line


def test_a_derived_set_remembers_its_parent_and_the_step():
    session = Session(session_id="s1")
    clock = Ticking()
    parent = sets.create(session, kind="orders", members=[f"gid://shopify/Order/{i}" for i in range(5)], label="delayed", clock=clock)
    child = sets.derive(session, parent, members=["gid://shopify/Order/1", "gid://shopify/Order/3"], label="delayed — UK", step="filter", detail={"tool": "commerce_query", "filters": {"country_code": "GB"}}, clock=clock)
    assert child.parent == parent.set_id and child.step == "filter" and child.provenance["parent_label"] == "delayed" and child.provenance["detail"]["filters"] == {"country_code": "GB"}
    assert child.count == 2 and parent.count == 5, "the parent is untouched"
    assert session.focus["set"] == child.set_id and sets.latest(session) is child
    grand = sets.derive(session, child, members=["gid://shopify/Order/3"], label="delayed — UK — emailed", step="correlate", kind="orders", clock=clock)
    assert grand.parent == child.set_id


def test_sets_expire_are_bounded_and_belong_to_their_conversation():
    session = Session(session_id="s1")
    clock = Ticking()
    first = sets.create(session, kind="customers", members=["gid://shopify/Customer/1"], label="first", clock=clock)
    clock.now += sets.TTL_S - 10
    assert sets.get(session, first.set_id, clock=clock) is not None, "asking for it keeps it"
    assert session.sets[first.set_id].expires_at == clock.now + sets.TTL_S
    clock.now += sets.TTL_S + 1
    assert sets.get(session, first.set_id, clock=clock) is None and first.set_id not in session.sets and "set" not in session.focus
    for i in range(sets.MAX_SETS + 3):
        clock.now += 1
        sets.create(session, kind="orders", members=[f"gid://shopify/Order/{i}"], label=f"set {i}", clock=clock)
    assert len(session.sets) == sets.MAX_SETS and sets.latest(session).label == f"set {sets.MAX_SETS + 2}"
    big = sets.create(session, kind="orders", members=[f"gid://shopify/Order/{i}" for i in range(sets.MAX_MEMBERS + 50)], label="big", clock=clock)
    assert big.count == sets.MAX_MEMBERS and big.truncated
    other = Session(session_id="s2")
    assert sets.get(other, big.set_id) is None, "another conversation knows nothing of it"
    with pytest.raises(ValueError):
        sets.create(session, kind="galaxies", members=["x"], label="no")


def test_the_gate_takes_a_set_id_only_when_the_conversation_was_given_it():
    assert classify("email_query", {"set_id": "set_abcdef123456"}, issued_ids={"set_abcdef123456"}).disposition is Disposition.EXECUTE_NOW
    assert classify("email_query", {"set_id": "set_abcdef123456"}).disposition is Disposition.DENY
    assert classify("email_query", {"set_id": "gid://shopify/Order/1"}, issued_ids={"gid://shopify/Order/1"}).disposition is Disposition.DENY, "not a set id"
    assert classify("email_query", {"set_id": "set_abcdef123456"}, issued_ids={"set_abcdef123456"}).tier is Tier.AMBER


# --------------------------------------------------------------------------- through the tools


@pytest.fixture()
def session():
    s = Session(session_id="a1")
    s.turn_id = "turn_ws"
    return s


async def test_a_listing_makes_a_set_and_a_follow_up_narrows_it(store, cache, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    text = await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled"}, "title": "Delayed orders"}, session=session, timeout_s=5, calls=calls)
    result = calls[-1].result
    made = result["set"]
    assert made["kind"] == "orders" and made["count"] == 3 and made["label"] == "Delayed orders" and made["step"] == "query" and made["set_id"] in text
    assert set(session.sets[made["set_id"]].members) == {"gid://shopify/Order/1002", "gid://shopify/Order/1007", "gid://shopify/Order/1009"}
    assert session.focus["set"] == made["set_id"] and made["set_id"] in session.issued_ids
    # "How much are these worth?"
    await dispatch("commerce_aggregate", {"entity": "orders", "period": "last_90_days", "filters": {"in_set": made["set_id"]}, "metrics": ["orders", "revenue", "unfulfilled_value"], "view": "metrics"}, session=session, timeout_s=5, calls=calls)
    assert calls[-1].result["totals"]["orders"] == 3 and calls[-1].result["totals"]["revenue"] == 295.0
    assert "set" not in calls[-1].result or calls[-1].result["set"]["count"] == 3
    # "Show only the UK ones": a derived set that remembers the parent.
    session.turn_id = "turn_ws2"
    await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"in_set": made["set_id"], "country_code": "GB"}, "title": "Delayed orders · UK"}, session=session, timeout_s=5, calls=calls)
    narrowed = calls[-1].result["set"]
    assert narrowed["count"] == 2 and narrowed["parent"] == made["set_id"] and narrowed["step"] == "filter" and narrowed["parent_label"] == "Delayed orders"
    assert session.focus["set"] == narrowed["set_id"]
    # A ranking of customers is a set of customers; a size breakdown is not a set.
    await dispatch("commerce_aggregate", {"entity": "customers", "period": "last_90_days", "metrics": ["lifetime_spent"], "limit": 3}, session=session, timeout_s=5, calls=calls)
    assert calls[-1].result["set"]["kind"] == "customers" and calls[-1].result["set"]["count"] == 3
    await dispatch("commerce_aggregate", {"entity": "variants", "period": "last_90_days", "group_by": ["size"], "metrics": ["units"]}, session=session, timeout_s=5, calls=calls)
    assert "set" not in calls[-1].result
    # The prompt line names the set in focus.
    line = sets.prompt_line(session)
    assert session.focus["set"] in line and "customers" in line


async def test_a_set_from_another_conversation_or_a_stale_one_is_refused(store, cache, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days"}, session=session, timeout_s=5, calls=calls)
    set_id = calls[-1].result["set"]["set_id"]
    stranger = Session(session_id="b1")
    stranger.turn_id = "turn_x"
    text = await dispatch("commerce_aggregate", {"entity": "orders", "filters": {"in_set": set_id}}, session=stranger, timeout_s=5, calls=calls)
    assert text.startswith("ERROR") and "no working set" in text
    del session.sets[set_id]
    text = await dispatch("commerce_aggregate", {"entity": "orders", "filters": {"in_set": set_id}}, session=session, timeout_s=5, calls=calls)
    assert "no working set" in text


async def test_the_set_is_a_card_after_the_listing(store, cache, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled"}, "title": "Delayed orders"}, session=session, timeout_s=5, calls=calls)
    items = present(calls, session=session)
    assert [i["type"] for i in items][:2] == ["order_list", "working_set"]
    card = items[1]["data"]
    assert card["count"] == 3 and card["kind"] == "orders" and card["label"] == "Delayed orders" and card["step"] == "query" and card["lines"][0] == {"label": "value", "value": "£295.00"}
    assert card["set_id"] == calls[-1].result["set"]["set_id"] and len(card["sample"]) == 3
    assert working_set_items({"set": None}) == []


# ------------------------------------------------------------------------- the inbox beside a set


@pytest.fixture()
def inbox():
    """Two of the delayed customers have written; we replied to one."""
    threads = {
        "ben@example.com": [{"thread_id": "18f0000000000001", "from_email": "ben@example.com", "subject": "Where is order 1002?", "date": "Mon, 7 Sep 2026 10:00:00 +0100", "snippet": "still waiting", "likely_bulk": False, "authenticated": True}],
        "flo@example.com": [{"thread_id": "18f0000000000002", "from_email": "flo@example.com", "subject": "Order 1007", "date": "Sun, 6 Sep 2026 10:00:00 +0100", "snippet": "any news", "likely_bulk": False, "authenticated": True}],
    }
    replied_threads = {"18f0000000000002"}
    calls = []

    async def threads_for(**kwargs):
        calls.append(kwargs)
        return {"available": True, "threads": list(threads.get(kwargs.get("sender", ""), []))}

    async def replied(thread_id):
        return thread_id in replied_threads

    analytics_tools.bind_email(threads_for, replied)
    threads_for.calls = calls
    yield threads_for
    analytics_tools.bind_email(None, None)


async def test_the_inbox_is_cross_referenced_with_the_set_and_makes_derived_sets(store, cache, inbox, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled"}, "title": "Delayed orders"}, session=session, timeout_s=5, calls=calls)
    set_id = calls[-1].result["set"]["set_id"]
    session.turn_id = "turn_mail"
    text = await dispatch("email_query", {"set_id": set_id, "days": 30}, session=session, timeout_s=5, calls=calls)
    result = calls[-1].result
    assert result["counts"] == {"contacted": 2, "not_contacted": 1, "replied": 1, "needs_reply": 0, "unchecked": 0} and result["customers"] == 3 and text.startswith("AMBER")
    rows = {r["customer_name"]: r for r in result["rows"]}
    assert rows["Ben Bold"]["emailed"] and rows["Ben Bold"]["replied"] is False and rows["Ben Bold"]["last_subject"] == "Where is order 1002?"
    assert rows["Flo Fry"]["emailed"] and rows["Flo Fry"]["replied"] is True and rows["Gus Gee"]["emailed"] is False
    assert [r["customer_name"] for r in result["rows"]][:2] == ["Ben Bold", "Flo Fry"], "those who wrote come first"
    contacted, quiet, replied = result["set_contacted"], result["set_not_contacted"], result["set_replied"]
    assert contacted["count"] == 2 and quiet["count"] == 1 and replied["count"] == 1 and quiet["parent"] == set_id and quiet["step"] == "correlate"
    assert set(session.sets[quiet["set_id"]].members) == {"gid://shopify/Order/1009"} and set(session.sets[replied["set_id"]].members) == {"gid://shopify/Order/1007"}
    assert session.focus["set"] == set_id, "the set the owner asked about stays in focus; the derived ones are named by id"
    threads = result["set_threads"]
    assert threads["kind"] == "emails" and threads["count"] == 2 and threads["parent"] == set_id and session.sets[threads["set_id"]].labels
    # One search per customer in the set, each for that customer's own order number over the
    # window asked for. Asserted sender by sender and term by term: this line used to end in
    # `or True` and asserted nothing (round 9, I-tests5 I-06).
    assert inbox.calls, "the inbox was never searched"
    searched = {c["sender"]: (c["terms"], c["days"]) for c in inbox.calls}
    assert len(inbox.calls) == len(searched) == 3, inbox.calls
    assert searched["ben@example.com"] == (["1002"], 30)
    assert searched["flo@example.com"] == (["1007"], 30)
    assert searched["gus@example.com"] == (["1009"], 30)
    # The cards: the counts, who wrote, and the two sets.
    items = present(calls[-1:], session=session)
    assert [i["type"] for i in items] == ["metric_group", "table", "working_set"], "the counts, the table, and one set card for the correlation"
    assert items[0]["data"]["metrics"][0] == {"key": "contacted", "label": "emailed us", "value": "2", "measured": True}
    assert items[1]["data"]["rows"][0]["cells"] == ["Ben Bold", "1002", "yes", "no", "Where is order 1002?"]
    assert items[2]["data"]["label"] == "Delayed orders" and items[2]["data"]["step"] == "correlate" and [x["value"] for x in items[2]["data"]["lines"]] == ["2", "1", "1"]
    # Asking again within the cache window does not search the inbox again.
    before = len(inbox.calls)
    session.turn_id = "turn_mail2"
    await dispatch("email_query", {"set_id": set_id, "days": 30}, session=session, timeout_s=5, calls=calls)
    assert len(inbox.calls) == before


async def test_a_set_too_large_for_the_inbox_or_of_the_wrong_kind_is_refused(store, cache, inbox, session, monkeypatch):
    london_now(monkeypatch)
    calls = []
    await dispatch("commerce_aggregate", {"entity": "variants", "period": "last_90_days", "group_by": ["variant"], "metrics": ["units"]}, session=session, timeout_s=5, calls=calls)
    variants = calls[-1].result["set"]["set_id"]
    text = await dispatch("email_query", {"set_id": variants}, session=session, timeout_s=5, calls=calls)
    assert text.startswith("ERROR") and "orders or customers" in text
    monkeypatch.setattr(analytics_tools, "EMAIL_MAX_CUSTOMERS", 2)
    await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days"}, session=session, timeout_s=5, calls=calls)
    text = await dispatch("email_query", {"set_id": calls[-1].result["set"]["set_id"]}, session=session, timeout_s=5, calls=calls)
    assert "at most 2 at a time" in text
    text = await dispatch("email_query", {"set_id": "set_000000000000"}, session=session, timeout_s=5, calls=calls)
    assert text.startswith("REFUSED") or text.startswith("NOT YET"), "an id the conversation was never given"


def test_a_stand_in_clock_is_the_tests_own():
    assert Clock(1.0)() == 1.0 and isinstance(Store(), Store)
