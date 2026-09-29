"""Customer names and the owner's own words in the always-on timeline (the round-12 deploy review
of 361b0138, RC-5: S1-NEW-02, R9-D1-D1-01).

Test mode is always on in production: every turn is written to the day's automatic session
(`app/observability/session.py` AUTO_NAME). What reached it in the clear:

* a read's `tool_finished` event carried the customer's name (`_result_shape` kept a top-level
  `name`), written before the turn had told the timeline that name, so nothing redacted it;
* an argument nested under a key the dispatcher did not recognise was written as it was said;
* a name the owner said that no read returned was never known to the timeline, so the words
  heard (`stt.text`), the model's answer and `turn_finished.question` kept it.

Now a read's names are given to the timeline before any event of that read is written;
`name` is written by its shape; every free string in a tool's arguments is written by its shape
unless it is an id, a catalogue word or a word of the query language's own; and in the automatic
session the owner's words — and the answers to them — are written as their shape (length and
digest). A session the owner starts by name keeps the words, as it always has: it is his
walkthrough, and the names its reads return are still taken out.

The routes, dispatcher and timeline are the real ones, against the fake shop of
tests/test_r11_turn.py; the only stand-ins are Claude (a scripted model making real tool calls)
and the recogniser.
"""

from __future__ import annotations

import json
import re

import pytest

from app.observability import timeline
from app.observability.session import AUTO_NAME, TestSessions, is_automatic
from app.tools import authority, registry
from app.tools.dispatch import dispatch, loggable_args
from tests import test_r11_turn
from tests.test_turn_boundary import PROXIED, A, Heard, _customer, found_customer, reads

desk = test_r11_turn.desk

ZOE = "gid://shopify/Customer/11"
SHAPE = re.compile(r"<\d+ chars ~[0-9a-f]{8}>")


@pytest.fixture()
def always_on(tmp_path):
    """The day's automatic session, as production runs it (CROOKS_TEST_SESSION_ALWAYS)."""
    timeline.forget_names()
    store = TestSessions(tmp_path / "sessions", always=True)
    line = timeline.install(timeline.Timeline(store))
    session = store.active()
    assert session is not None and session.name == AUTO_NAME
    yield line, store, session
    timeline.install(timeline.NullTimeline())
    timeline.forget_names()


@pytest.fixture()
def walkthrough(tmp_path):
    """A session the owner started by name."""
    timeline.forget_names()
    store = TestSessions(tmp_path / "sessions", always=True)
    line = timeline.install(timeline.Timeline(store))
    session = line.start("friday walkthrough")
    assert session.name != AUTO_NAME
    yield line, store, session
    line.stop()
    timeline.install(timeline.NullTimeline())
    timeline.forget_names()


def _events(line, store, session) -> list[dict]:
    assert line.flush(5.0)
    return timeline.read_events(store.timeline_path(session))


async def _heard(desk, words: str, sid: str) -> dict:
    """The owner saying `words` to the tablet: audio in, the recogniser hears exactly this."""
    desk.runtime.transcriber = Heard(words)
    response = await desk.post("/turn", data={"session_id": sid}, headers=PROXIED,
                               files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 64, "audio/webm")})
    assert response.status_code == 200, response.text
    return response.json()


def _zoe(desk) -> None:
    desk.store.customers[ZOE] = _customer(ZOE, "Zoe Quill", "zoe.quill@example.com", A, "1938")


def looks_her_up(answer: str):
    lookup = reads(("shopify_find_customer", {"query": "Quill"}),
                   ("shopify_customer_history", {"customer_id": found_customer}))

    async def step(session, calls, text):
        await lookup(session, calls, text)
        return answer
    return step


def says(answer: str):
    async def step(session, calls, text):
        return answer
    return step


def _nowhere(events: list[dict], *parts: str) -> None:
    written = json.dumps(events).lower()
    for part in parts:
        assert part.lower() not in written, [e["kind"] for e in events if part.lower() in json.dumps(e).lower()]


# ================================================================ the automatic session


async def test_a_customer_a_read_returns_is_nowhere_in_the_automatic_session(desk, always_on):
    """S1-NEW-02. "What did Zoe Quill order?", the model finds her and reads her history, and
    answers with her name. The history read's `tool_finished` carried "Zoe Quill" as its result's
    `name`, written before the turn had noted her. Her name, first or last, is in no event."""
    line, store, session = always_on
    _zoe(desk)
    desk.model.steps = [looks_her_up("Zoe Quill has one order, #1938.")]
    body = await _heard(desk, "What did Zoe Quill order?", "after-a-read")
    assert body["question"] == "What did Zoe Quill order?", "the owner still sees his own words"
    assert body["answer"] == "Zoe Quill has one order, #1938."

    events = _events(line, store, session)
    finished = [e for e in events if e.get("kind") == "tool_finished" and e.get("tool") == "shopify_customer_history"]
    assert finished and finished[0]["result"]["name"] == "<9 chars>", finished
    _nowhere(events, "Quill", "Zoe")


async def test_a_name_said_that_no_read_returns_is_nowhere_in_the_automatic_session(desk, always_on):
    """R9-D1-D1-01. The same question, and the model reads nothing and repeats the name. No read
    ever tells the timeline who Zoe Quill is, so the words heard, the question and the answer are
    written by their shape: how long, and a digest that tells one sentence from another."""
    line, store, session = always_on
    desk.model.steps = [says("I couldn't find anyone called Zoe Quill.")]
    await _heard(desk, "What did Zoe Quill order?", "no-read")

    events = [e for e in _events(line, store, session) if e.get("session_id") == "no-read"]
    _nowhere(events, "Quill", "Zoe")
    heard = next(e for e in events if e["kind"] == "stt")
    finished = next(e for e in events if e["kind"] == "turn_finished")
    model = next(e for e in events if e["kind"] == "model")
    assert SHAPE.fullmatch(heard["text"]) and SHAPE.fullmatch(heard["raw_text"]), heard
    assert heard["text"].startswith(f"<{len('What did Zoe Quill order?')} chars")
    assert SHAPE.fullmatch(finished["question"]) and SHAPE.fullmatch(finished["answer"]), finished
    assert SHAPE.fullmatch(model["answer"]), model
    assert heard["text"] == finished["question"], "the same words digest alike, so a report can pair them"


async def test_a_typed_question_is_written_by_its_shape_in_the_automatic_session_too(desk, always_on):
    line, store, session = always_on
    desk.model.steps = [says("Nobody by that name.")]
    response = await desk.post("/turn", json={"text": "orders for Zoe Quill", "session_id": "typed"}, headers=PROXIED)
    assert response.status_code == 200
    events = [e for e in _events(line, store, session) if e.get("session_id") == "typed"]
    _nowhere(events, "Quill")
    assert SHAPE.fullmatch(next(e for e in events if e["kind"] == "turn_finished")["question"])


# ============================================================ a session he started by name


async def test_a_session_started_by_name_keeps_his_words_and_still_loses_the_names_reads_return(desk, walkthrough):
    """The product decision, held both ways: his own walkthrough keeps what he said (a name no
    read returned stays in his words), and a name a read returned is still taken out wherever it
    is — the result's `name` included."""
    line, store, session = walkthrough
    _zoe(desk)
    desk.model.steps = [says("Nobody by that name."), looks_her_up("Zoe Quill has one order, #1938.")]
    await _heard(desk, "What did Zoe Quill order?", "named-unread")
    await _heard(desk, "What did Zoe Quill order?", "named-read")

    events = _events(line, store, session)
    unread = next(e for e in events if e.get("kind") == "turn_finished" and e.get("session_id") == "named-unread")
    assert unread["question"] == "What did Zoe Quill order?", unread["question"]
    read = [e for e in events if e.get("session_id") == "named-read"]
    _nowhere(read, "Quill")
    finished = next(e for e in read if e["kind"] == "turn_finished")
    assert finished["question"] == "What did [name] order?", finished["question"]


async def test_a_session_he_named_always_on_is_his_and_keeps_his_words(desk, tmp_path):
    """The name is not what makes the day's session (O2-N-01, `session.is_automatic`): a session
    he started and called "always-on" is his walkthrough, and keeps what he said like any other
    he named. Words are kept or shaped by the same rule housekeeping keeps or prunes by."""
    timeline.forget_names()
    store = TestSessions(tmp_path / "sessions", always=True)
    line = timeline.install(timeline.Timeline(store))
    try:
        session = line.start("always-on")
        assert session.name == AUTO_NAME and not is_automatic(session), session.test_session_id
        desk.model.steps = [says("Nobody by that name.")]
        await _heard(desk, "What did Zoe Quill order?", "named-always-on")
        events = [e for e in _events(line, store, session) if e.get("session_id") == "named-always-on"]
        finished = next(e for e in events if e["kind"] == "turn_finished")
        assert finished["question"] == "What did Zoe Quill order?", finished["question"]
    finally:
        line.stop()
        timeline.install(timeline.NullTimeline())
        timeline.forget_names()


# =========================================================== what a tool call is written as


@pytest.fixture()
def reads_answered(monkeypatch):
    async def answered(name, args, *, timeout_s):
        return {"count": 0, "orders": [], "customers": []}

    monkeypatch.setattr(registry, "invoke", answered)


async def test_every_free_string_in_a_read_s_arguments_is_written_by_its_shape(always_on, reads_answered):
    """A nested argument under a key the dispatcher did not list was written as it was said
    (S1-NEW-02): a city, a tag, a list of words. So was a top-level string under such a key: the
    item an order was searched by. Every free string is its shape now; an id, a catalogue word and a word
    of the query language's own are kept, because a report needs them and they are not his words
    about a person."""
    from app.session.models import Session

    line, store, session = always_on
    conversation = Session(session_id="s-args")
    calls = (
        ("commerce_query", {"entity": "orders", "period": "last_week",
                            "filters": {"city": "Quillhampton", "fulfillment": "unfulfilled", "tags": ["for Zoe Quill"]}}),
        ("commerce_query", {"entity": "orders", "filters": {"product": "Yard Jeans", "customer_id": ZOE,
                                                            "nested": {"deeper": {"note": "Zoe Quill"}}}}),
        ("shopify_find_order", {"item": "the jacket Zoe Quill bought", "email": "zoe.quill@example.com"}),
    )
    with authority.acting_as(authority.for_owner("owner@example.com")):
        for tool, args in calls:
            await dispatch(tool, args, session=conversation, timeout_s=5)
    events = [e for e in _events(line, store, session) if e.get("kind") == "tool_requested"]
    _nowhere(events, "Quill", "Zoe")
    first, second, search = (e["args"] for e in events)
    assert first["entity"] == "orders" and first["period"] == "last_week"
    assert "'fulfillment': 'unfulfilled'" in first["filters"], first["filters"]
    assert "'product': 'Yard Jeans'" in second["filters"] and ZOE in second["filters"], second["filters"]
    assert SHAPE.fullmatch(search["item"]) and search["email"] == "[redacted]", search


@pytest.mark.parametrize(("filters", "kept"), [
    ({"fulfillment": "unfulfilled", "payment": "paid", "city": "Quillhampton"}, ("'fulfillment': 'unfulfilled'", "'payment': 'paid'")),
    ({"size": "M", "colour": "Blue Wash", "tags": ["Zoe Quill"]}, ("'size': 'M'", "'colour': 'Blue Wash'")),
    ({"customer_id": ZOE, "who": {"name": "Zoe Quill"}}, (f"'customer_id': '{ZOE}'",)),
])
def test_a_structured_argument_keeps_ids_catalogue_and_query_words_and_shapes_the_rest(filters, kept):
    written = loggable_args("commerce_query", {"filters": filters})["filters"]
    assert len(written) < 120, "the case must fit the written length, or a cut could pass for a shape"
    assert "Quill" not in written and "Zoe" not in written, written
    for word in kept:
        assert word in written, written


async def test_an_error_that_quotes_what_he_said_is_written_with_those_words_by_their_shape(always_on, monkeypatch):
    """A refusal can quote the words it was given: the composer's "'Zoe Quill' is not an address
    I can send to", a query's "customer_id='Zoe Quill' is not a Shopify Customer id". The error is
    the Mac's, and a report needs it; the words it quotes are his, and are written by their shape
    as they are in the call's own arguments."""
    from app.session.models import Session
    from app.tools.registry import ToolError

    line, store, session = always_on

    async def refused(name, args, *, timeout_s):
        raise ToolError(f"{str(args.get('item'))[:80]!r} is not an item I can search by, so nothing was read.")

    monkeypatch.setattr(registry, "invoke", refused)
    with authority.acting_as(authority.for_owner("owner@example.com")):
        told = await dispatch("shopify_find_order", {"item": "the jacket Zoe Quill bought"},
                              session=Session(session_id="s-error"), timeout_s=5)
    assert "Zoe Quill" in told, "the model is still told the error as it was"
    (finished,) = [e for e in _events(line, store, session) if e.get("kind") == "tool_finished"]
    _nowhere([finished], "Quill", "Zoe")
    assert finished["error"].endswith("is not an item I can search by, so nothing was read."), finished["error"]
    assert SHAPE.search(finished["error"]), finished["error"]


# ================================ his words written from inside a tool (the round-13 check)
#
# The round-13 independent check found his words written from inside a tool, before any read had
# told the timeline a name: a listing's title, "in the owner's words", became a working set's
# label; a query the language refused quoted what was asked in its reason. In the automatic
# session those are written by their shape now, like everything else he said.


@pytest.fixture()
def listing(monkeypatch):
    """The order cache of tests/test_analytics_tools.py: Cy Cole and others, with a fixed now."""
    from app.analytics.cache import OrderCache
    from app.tools import analytics_tools
    from tests.test_analytics_tools import NOW, Clock, Store, london_now

    london_now(monkeypatch)
    cache = OrderCache(lambda: Store(), clock=Clock(NOW.timestamp()))
    analytics_tools.bind(cache)
    yield
    analytics_tools.bind(None)


async def test_a_listing_titled_in_his_words_is_written_by_its_shape(always_on, listing):
    """The check's own case: "Cy Cole's orders" as the title of a listing. The working set's label
    was written as given. So was a customer ranking's, before its names were noted."""
    from app.session.models import Session

    line, store, session = always_on
    conversation = Session(session_id="s-listing")
    with authority.acting_as(authority.for_owner("owner@example.com")):
        await dispatch("commerce_query", {"entity": "orders", "period": "last_90_days", "title": "Cy Cole's orders"},
                       session=conversation, timeout_s=5)
        await dispatch("commerce_aggregate", {"entity": "customers", "period": "last_90_days", "metrics": ["lifetime_spent"],
                                              "limit": 3, "title": "Top three, Cy Cole first"},
                       session=conversation, timeout_s=5)
    events = _events(line, store, session)
    sets = [e for e in events if e.get("kind") == "working_set"]
    assert len(sets) == 2 and all(SHAPE.fullmatch(e["label"]) for e in sets), sets
    _nowhere(events, "Cy Cole", "Cole's")


async def test_a_query_the_language_refused_is_written_without_what_was_asked(always_on, listing):
    from app.session.models import Session

    line, store, session = always_on
    with authority.acting_as(authority.for_owner("owner@example.com")):
        await dispatch("commerce_aggregate", {"entity": "orders", "period": "last_90_days", "group_by": ["zoe_quill"],
                                              "metrics": ["orders"]}, session=Session(session_id="s-refused"), timeout_s=5)
    events = _events(line, store, session)
    (refused,) = [e for e in events if e.get("kind") == "query_rejected"]
    assert SHAPE.fullmatch(refused["reason"]) and all(SHAPE.fullmatch(u) for u in refused["unknown"] or []), refused
    _nowhere(events, "zoe", "quill")


@pytest.mark.parametrize(("kind", "fields"), [
    ("action_commit", {"spoken": "Reply sent to David."}),
    ("branch_forked", {"headline": "Cy Cole's orders", "parent_headline": "Orders for Zoe"}),
    ("branch_focused", {"headline": "Cy Cole's orders"}),
])
def test_what_a_change_or_a_half_says_is_written_by_its_shape_in_the_automatic_session(always_on, kind, fields):
    line, store, session = always_on
    timeline.emit(kind, session_id="s-said", **fields)
    (event,) = [e for e in _events(line, store, session) if e.get("kind") == kind]
    assert all(SHAPE.fullmatch(event[k]) for k in fields), event


def test_what_a_change_says_is_kept_in_a_session_he_named(walkthrough):
    line, store, session = walkthrough
    timeline.emit("action_commit", session_id="s-named", spoken="Reply sent to David.")
    (event,) = [e for e in _events(line, store, session) if e.get("kind") == "action_commit"]
    assert event["spoken"] == "Reply sent to David."
