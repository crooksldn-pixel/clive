"""A search in progress never takes the screen, and the screen is only what the answer is about.

George, 7 October 2026 (DEC-067): "today I asked for the email reply to [a customer] and it
showed [a customer]'s total orders as a customer, then some random email from someone else,
today's email threads and today's orders when all I wanted to see was the reply to [a customer]."

The golden world stands Priya in for that customer: she wrote about the cap on order 1940,
and a search for "cap" also finds Mia's email about adding a cap to 1938 — somebody else's email,
as his search found. The turn is the one he described, read for read: the customer looked up,
the inbox searched, today's threads, today's orders, then the reply. Scripted through the real
gate, action engine and presenters (`experience/harness.py`): what is held is what the Mac does
with those calls, not that Claude would make them.
"""

from __future__ import annotations

import pytest

from app import focus, progressive
from experience.fixtures import data
from experience.harness import harness

PRIYAS_THREAD = "c28cf65d31fe6cbb"       # "Cap" — her question about order 1940
MIAS_THREAD = "aa70d3f83dbef06e"         # "Order 1938 — can I add to it?" — somebody else's email
REPLY = "Hi Priya, yes: the black cap is the adjustable one."


@pytest.fixture()
async def world():
    progressive.reset()
    async with harness(admitted=True) as h:
        yield h
    progressive.reset()


def _the_reply_turn(reply_tool: str) -> tuple[tuple[str, dict], ...]:
    """His turn, read for read: who he is, the inbox searched for him, today's threads, today's
    orders — and then the reply."""
    return (
        ("shopify_find_customer", {"query": "Priya Raman"}),
        ("gmail_search", {"query": "cap"}),
        ("gmail_search", {"query": "newer_than:1d"}),
        ("shopify_list_orders", {"days": 1}),
        (reply_tool, {"thread_id": PRIYAS_THREAD, "body": REPLY}),
    )


def _cards(said) -> list[dict]:
    return [item for item in said.ui if item.get("type") != "context_stack"]


def _nothing_staged_before_the_answer(session_id: str) -> None:
    """Every patch the glass was given for this turn came with the answer: none while it read."""
    workspace = progressive.current(session_id)
    assert workspace is not None and workspace.quiet and workspace.finished
    assert workspace.patches, "the answer itself reached the glass"
    early = [f"{p.op}:{p.type}" for p in workspace.patches if p.at_ms is not None and p.at_ms < workspace.complete_ms]
    assert early == [], f"a search in progress took the screen: {early}"


@pytest.mark.parametrize("reply_tool", ["gmail_send_reply", "gmail_draft_reply"])
async def test_the_reply_to_the_customer_and_nothing_else(world, reply_tool):
    sid = f"reply-{reply_tool.split('_')[1]}"
    said = await world.ask("show me the email reply to priya", *_the_reply_turn(reply_tool), session_id=sid,
                           reply="Here's the reply to Priya.")
    tools = [c.get("name") for c in said.raw.get("tool_calls") or []]
    assert tools == [name for name, _ in _the_reply_turn(reply_tool)], tools
    assert all(c.get("ok") for c in said.raw["tool_calls"]), said.raw["tool_calls"]

    cards = _cards(said)
    assert [c["type"] for c in cards] == ["confirmation"], [c["type"] for c in cards]
    card = cards[0]["data"]
    assert card["entity_ref"] == PRIYAS_THREAD
    message = card["message"]
    assert message["channel"] == "email" and message["kind"] == "reply" and message["editable"] == ["body"]
    assert message["body"] == REPLY and data.PRIYA.email in message["to"]
    # Nothing of the search is anywhere on the answer: not her order count, not Mia's email, not
    # today's threads, not today's orders.
    flat = repr(said.ui)
    assert MIAS_THREAD not in flat and data.MIA.email not in flat
    assert "order_list" not in flat and "email_list" not in flat
    _nothing_staged_before_the_answer(sid)


async def test_the_reply_card_is_the_send_and_the_gate_holds_it_as_outward(world):
    """The card the model's reply lands on is the send itself: RED, so his hold, and it says so."""
    sid = "reply-gate"
    said = await world.ask("reply to priya", *_the_reply_turn("gmail_send_reply"), session_id=sid)
    card = _cards(said)[0]["data"]
    assert card["risk"] == "red" and card["interaction"]["kind"] == "hold_to_arm"
    assert card["interaction"]["label"] == "Hold, then tap to send"
    assert card["message"]["sending"] is True and card["message"]["other"]["label"] == "Save as draft"
    (proposal,) = [p for p in world.runtime.sessions.get(sid).proposals if p.status.value == "PENDING"]
    assert proposal.operation == "gmail_send_reply" and proposal.risk == "RED"


async def test_a_plain_question_still_shows_its_answer(world):
    """No change and no record read in full: the listing IS the answer, and it is on the screen."""
    said = await world.ask("how many orders today", ("shopify_list_orders", {"days": 1}), session_id="plain",
                           reply="Four today.")
    assert [c["type"] for c in _cards(said)] == ["order_list"]
    assert _cards(said)[0]["data"]["orders"], "today's orders are on it"
    _nothing_staged_before_the_answer("plain")


async def test_a_question_answered_by_two_listings_keeps_both(world):
    """Two listings asked for at once, and a workspace composed over one of their rows from the
    words: no read returned that record whole, so it is not a record read in full and the
    listings — today's orders, today's inbox — stay the answer."""
    said = await world.ask("orders today and what's in the inbox", ("shopify_list_orders", {"days": 1}),
                           ("gmail_search", {"query": "newer_than:1d"}), session_id="two-lists", reply="Four orders; three emails.")
    kinds = [c["type"] for c in _cards(said)]
    assert "order_list" in kinds and "email_list" in kinds, kinds


def test_a_workspace_is_a_record_read_in_full_only_over_a_record_a_read_returned_whole():
    order = {"type": "order", "data": {"order_id": "o1", "detail": True}}
    composed = {"type": "order_workspace", "data": {"ref": "o1", "kind": "order"}}
    listing = {"type": "order_list", "data": {"orders": [{"order_id": "o1"}, {"order_id": "o2"}]}}
    read = focus.records_read_whole([order, listing])
    assert read == frozenset({"o1"})
    assert focus.answer_cards([composed, listing], read_whole=read) == [composed]
    assert focus.answer_cards([composed, listing], read_whole=focus.records_read_whole([listing])) == [composed, listing]


async def test_the_thread_he_asked_for_and_not_the_searches_that_found_it(world):
    """No change: the record read in full wins over the lookups on the way to it."""
    said = await world.ask(
        "what did priya say", ("shopify_find_customer", {"query": "Priya Raman"}), ("gmail_search", {"query": "cap"}),
        ("gmail_read_thread", {"thread_id": PRIYAS_THREAD}), session_id="thread", reply="She asked about the cap.")
    assert [c["type"] for c in _cards(said)] == ["email_thread"], [c["type"] for c in _cards(said)]
    assert _cards(said)[0]["data"]["thread_id"] == PRIYAS_THREAD


async def test_a_failure_is_never_set_aside(world):
    """A read that failed is said on the screen whatever the answer is about."""
    said = await world.ask(
        "reply to priya", ("gmail_read_thread", {"thread_id": "0000000000000000"}),
        ("gmail_search", {"query": "cap"}), ("gmail_send_reply", {"thread_id": PRIYAS_THREAD, "body": REPLY}),
        session_id="failed")
    kinds = [c["type"] for c in _cards(said)]
    assert "confirmation" in kinds and "error" in kinds and "email_list" not in kinds, kinds


def test_the_rules_in_order_change_then_record_then_listing():
    """The three rules over cards alone (app/focus.py), with the kinds they set aside said."""
    change = {"type": "confirmation", "data": {"proposal_id": "p1"}}
    thread = {"type": "email_thread", "data": {"thread_id": "t1", "messages": [{"body": "x"}]}}
    listing = {"type": "email_list", "data": {"threads": [{"thread_id": "t1"}]}}
    found = {"type": "customer", "data": {"customer_id": "c1"}}
    history = {"type": "customer", "data": {"customer_id": "c1", "history": {"orders": 2}}}
    numbers = {"type": "metric_group", "data": {"metrics": [{"label": "Orders", "value": "4"}]}}
    error = {"type": "error", "data": {"service": "gmail"}}
    stack = {"type": "context_stack", "data": {"entries": []}}

    why: dict = {}
    assert focus.answer_cards([found, listing, thread, change, error, stack], why) == [change, error, stack]
    assert why == {"rule": "change", "set_aside": ["customer", "email_list", "email_thread"]}
    why = {}
    assert focus.answer_cards([found, listing, thread, numbers], why) == [thread, numbers]
    assert why["rule"] == "record" and why["set_aside"] == ["customer", "email_list"]
    assert focus.answer_cards([listing, history]) == [history]
    why = {}
    assert focus.answer_cards([listing, found, numbers], why) == [listing, found, numbers]
    assert why == {"rule": "listing", "set_aside": []}


def test_an_order_read_whole_keeps_its_own_attention_and_drops_another_orders():
    order = {"type": "order", "data": {"order_id": "o1", "detail": True}}
    line = {"type": "order", "data": {"order_id": "o2", "detail": False}}
    mine = {"type": "attention", "data": {"for": "o1", "items": [{"title": "x"}]}}
    theirs = {"type": "attention", "data": {"for": "o2", "items": [{"title": "y"}]}}
    assert focus.answer_cards([line, theirs, order, mine]) == [order, mine]


def test_the_interaction_record_says_which_rule_chose_the_screen_and_what_it_set_aside(tmp_path):
    """"Look at our interaction" can say why the screen was only the reply: the rule, and the kinds
    of card it set aside as the searches that found it — kinds only, never what was on them."""
    import time

    from app.observability import interactions
    from app.observability.interactions import InteractionDays, InteractionRecord
    from app.observability.timeline import read_events
    from app.providers.base import ToolCall

    record = interactions.install(InteractionRecord(InteractionDays(tmp_path / "logs"), clock=time.time))
    try:
        staged = ToolCall(name="gmail_send_reply", args={}, ok=True, proposal_id="prop_1")
        reply = {"type": "confirmation", "data": {"proposal_id": "prop_1", "title": "Send the reply"}}
        interactions.after_turn(
            session_id="s1", turn_id="turn_reply", question="the reply to priya", transcript=None, answer="Ready.",
            ui=[reply], calls=[staged], screen_state="new", carry=["nothing_up"], error_kind=None, abandoned=False,
            timings={"total": 900.0}, focus={"rule": "change", "set_aside": ["customer", "email_list", "email_list", "order_list"]})
        record.flush()
        (turn,) = [e for e in read_events(record.sessions.timeline_path(record.active_id)) if e["kind"] == "interaction_turn"]
        assert turn["why"]["focus"] == {"rule": "change", "set_aside": ["customer", "email_list", "email_list", "order_list"]}
    finally:
        interactions.install(None)
