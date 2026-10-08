"""A search in progress never takes the screen, and the screen is only what the answer is about.

George, 7 October 2026 (DEC-069): "today I asked for the email reply to [a customer] and it
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


async def test_the_first_answer_about_a_customer_offers_to_email_them(world):
    """The checker's defect 2 (8 Oct): the workspace offers "Email <name>" only over a record the
    Mac is holding (app/workspace.py `_still_held`), and the turn kept what the model read only
    after drawing the cards — so the first answer composing her workspace had no way to write to
    her, and asking a second time did. What was read is kept before the cards are drawn now."""
    said = await world.ask(
        "pull up priya's history and see if she's in gmail", ("shopify_find_customer", {"query": "Priya Raman"}),
        ("shopify_customer_history", {"customer_id": data.PRIYA.customer_id}),
        ("gmail_search", {"query": f"from:{data.PRIYA.email}"}), session_id="first", reply="Here's Priya.")
    (workspace,) = [c for c in _cards(said) if c["type"] == "customer_workspace"]
    write = [a for a in workspace["data"].get("actions") or [] if a.get("command") == "compose.to_person"]
    assert write and write[0]["label"] == "Email Priya Raman" and write[0]["enabled"] is True, workspace["data"].get("actions")


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


def test_beside_a_change_its_own_records_attention_and_a_screens_remote_stay():
    """Review note 4: a change wins the screen, but the risk lines of the record the change is to
    are what he reads before he holds it ("Chargeback open" beside a refund of that order), and a
    screen's remote is a control, not a search. Another order's lines are still set aside."""
    change = {"type": "confirmation", "data": {"proposal_id": "p1", "entity_ref": "gid://shopify/Order/1940"}}
    mine = {"type": "attention", "data": {"for": "gid://shopify/Order/1940", "items": [{"title": "Chargeback open"}]}}
    theirs = {"type": "attention", "data": {"for": "gid://shopify/Order/1938", "items": [{"title": "Unpaid"}]}}
    remote = {"type": "screen_remote", "data": {"screen_id": "scr_1"}}
    order = {"type": "order", "data": {"order_id": "gid://shopify/Order/1940", "detail": True}}
    listing = {"type": "order_list", "data": {"orders": [{"order_id": "gid://shopify/Order/1940"}]}}
    why: dict = {}
    kept = focus.answer_cards([listing, order, mine, theirs, remote, change], why)
    # The change first, then what stays beside it (8 October, flow's second review, note 1).
    assert kept == [change, mine, remote], [c["type"] for c in kept]
    assert why == {"rule": "change", "set_aside": ["order_list", "order", "attention"]}
    # A change to nothing named keeps no attention line at all.
    assert focus.answer_cards([mine, {"type": "confirmation", "data": {"proposal_id": "p2"}}])[0]["type"] == "confirmation"


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


# ---- Two orders up (round 12's C3, 8 October): what he asked for, and what he had up, stay.


def _numbers(said) -> list[str]:
    """The order numbers on the answer's order cards, in order."""
    return [str(c["data"].get("order_number") or "") for c in said.ui if c.get("type") == "order"]


def _accepting_notes(world):
    """The golden world refuses every change; for one test it takes an order's note, as Shopify
    would, so the hold can be followed to what the shop holds (as tests/test_r12_browser.py)."""
    notes = {name: data.BY_NAME[name].note for name in ("#1938", "#1940")}
    refuse = world.store.mutate

    async def mutate(name: str, variables: dict) -> dict:
        if name != "order_note_set":
            return await refuse(name, variables)
        found = next(s for s in data.BY_NAME.values() if s.order_id == variables["id"])
        found.note = str(variables["note"])
        return {"data": {"orderUpdate": {"order": {"id": variables["id"], "name": f"#{found.number}", "note": found.note},
                                         "userErrors": []}}}

    def put_back() -> None:
        world.store.mutate = refuse
        for name, note in notes.items():
            data.BY_NAME[name].note = note

    world.store.mutate = mutate
    return put_back


async def _hold(world, session_id: str, proposal_id: str) -> dict:
    """His gesture on the card, as the tablet makes it: arm, the dwell, commit."""
    from experience.harness import TABLET_HEADERS

    headers = dict(TABLET_HEADERS)
    armed = await world.client.post(f"/actions/{proposal_id}/arm", data={"session_id": session_id}, headers=headers)
    if armed.status_code == 200 and armed.json().get("nonce"):
        world.runtime.actions.find(proposal_id).armed_at -= 1.0
        headers["X-Crooks-Arm"] = armed.json()["nonce"]
    done = await world.client.post(f"/actions/{proposal_id}/commit", data={"session_id": session_id}, headers=headers)
    assert done.status_code == 200, done.text
    return done.json()


async def _side_by_side(world, sid: str):
    """"Put 1938 and 1940 side by side", read for read as round 12's walk scripts it
    (tests/test_r12_browser.py): each order looked up by its number, then read. The scripted read
    is of the order the turn's FIRST lookup found (experience/harness.py `_found_order`), so #1938
    is read whole twice and #1940 is drawn as the line its own number's lookup returned: an order
    asked for by its number and drawn without detail, which is the case rule 2 must keep."""
    from experience.harness import order_reads

    await world.open_order("1940", session_id=sid)
    return await world.ask("put 1938 and 1940 side by side", *order_reads("1938"), *order_reads("1940"),
                           session_id=sid, reply="Both are up.")


def test_an_order_asked_for_by_its_number_is_never_a_find_even_drawn_as_its_line():
    """Rule 2 sets aside the finds a record read in full was found by. An order asked for by its
    own number is not one, drawn whole or as its line: "put 1938 and 1940 side by side"."""
    read = {"type": "order", "data": {"order_id": "o1938", "detail": True}}
    lines = {"type": "attention", "data": {"for": "o1938", "items": [{"title": "x"}]}}
    asked = {"type": "order", "data": {"order_id": "o1940", "detail": False}}
    found = {"type": "order", "data": {"order_id": "o1955", "detail": False}}
    listing = {"type": "order_list", "data": {"orders": [{"order_id": "o1940"}]}}
    why: dict = {}
    kept = focus.answer_cards([read, lines, asked, found, listing], why, asked=frozenset({"o1938", "o1940"}))
    assert kept == [read, lines, asked], [c["data"].get("order_id") for c in kept]
    assert why == {"rule": "record", "set_aside": ["order", "order_list"]}


def test_which_orders_a_turn_asked_for_by_their_own_id_or_number():
    """Read from the calls the model made and what they returned, never from his words."""
    from app.providers.base import ToolCall

    def find(query: str, *ids: str, matched: str = "") -> ToolCall:
        return ToolCall(name="shopify_find_order", args={"query": query}, ok=True,
                        result={"query": query, "matched_on": matched, "orders": [{"order_id": i} for i in ids]})

    calls = [
        ToolCall(name="shopify_order_detail", args={"order_id": "o1938"}, ok=True, result={"order_id": "o1938"}),
        find("1940", "o1940", matched="name:1940"),                      # by its number, found alone
        find("Priya Raman", "o1941", matched="(customer_id:7)"),          # a search by a person
        find("1950", "o1950", "o1951", matched="name:1950"),              # by number, but two came back
        ToolCall(name="shopify_order_detail", args={"order_id": "o1960"}, ok=False, error="failed"),
    ]
    assert focus.records_asked_for(calls) == frozenset({"o1938", "o1940"})


async def test_two_orders_asked_for_side_by_side_are_both_on_the_screen(world):
    """Round 12's C3 in a real turn: both orders were asked for, by number, so neither is a
    search result, and both cards are the answer — whichever of them is drawn as its line."""
    said = await _side_by_side(world, "side")
    assert sorted(_numbers(said)) == ["#1938", "#1940"], [c.get("type") for c in said.ui]


def test_beside_a_change_to_a_record_he_had_up_the_records_he_had_up_stay():
    """Rule 1 (8 October): a change to one of the records on his screen as the turn began keeps
    the change card first and the records he had up beside it, as this turn read them, with their
    lines. This turn's searches still never show beside a change."""
    up_1938 = {"type": "order", "data": {"order_id": "gid://shopify/Order/1938", "detail": True}}
    up_1940 = {"type": "order", "data": {"order_id": "gid://shopify/Order/1940", "detail": False}}
    before = [up_1938, {"type": "attention", "data": {"for": "gid://shopify/Order/1938", "items": []}}, up_1940]

    again = {"type": "order", "data": {"order_id": "gid://shopify/Order/1940", "detail": True}}
    lines = {"type": "attention", "data": {"for": "gid://shopify/Order/1940", "items": [{"title": "Customer emailed"}]}}
    searched = {"type": "email_list", "data": {"threads": [{"thread_id": "t1"}]}}
    someone = {"type": "customer", "data": {"customer_id": "gid://shopify/Customer/9"}}
    other = {"type": "order", "data": {"order_id": "gid://shopify/Order/1955", "detail": True}}
    note = {"type": "confirmation", "data": {"proposal_id": "p1", "entity_ref": "gid://shopify/Order/1940"}}
    why: dict = {}
    kept = focus.answer_cards([searched, someone, other, again, lines, note], why, before=before)
    assert kept == [note, again, lines], [c["type"] for c in kept]
    assert why == {"rule": "change", "set_aside": ["email_list", "customer", "order"]}

    # The reply to a customer he did not have up is the reply alone, whatever was on his screen.
    reply = {"type": "confirmation", "data": {"proposal_id": "p2", "entity_ref": PRIYAS_THREAD}}
    assert focus.answer_cards([searched, someone, again, lines, reply], before=before) == [reply]
    # And nothing up at all: the change alone, as before.
    assert focus.answer_cards([again, note], before=[]) == [note]


def test_the_screen_stays_under_a_change_to_one_of_its_records_whatever_was_read_on_the_way():
    """`app/screen.py` `carry`, beside rule 1: a change to a record on the screen continues the
    screen when the model read something elsewhere to prepare it (those reads are this turn's
    finds, already off the answer), and the changed record's new attention lines go under it
    rather than replacing his screen as a subject of their own."""
    import time
    from types import SimpleNamespace

    from app import screen
    from app.providers.base import ToolCall

    o1938, o1940 = "gid://shopify/Order/1938", "gid://shopify/Order/1940"
    up = [{"type": "order", "data": {"order_id": o1938, "detail": True}},
          {"type": "order", "data": {"order_id": o1940, "detail": False}}]
    half = SimpleNamespace(last_at=time.time(), last_ui=up)
    note = {"type": "confirmation", "data": {"proposal_id": "p1", "entity_ref": o1940}}
    lines = {"type": "attention", "data": {"for": o1940, "items": [{"title": "Customer emailed"}]}}
    read = [ToolCall(name="gmail_read_thread", args={}, ok=True, result={"thread_id": PRIYAS_THREAD})]

    why: list = []
    out = screen.carry([lines, note], branch=half, calls=read, why=why)
    assert why == [screen.WHY_CONTINUED]
    assert [(c["type"], c["data"].get("order_id") or c["data"].get("for")) for c in out] == [
        ("confirmation", None), ("order", o1938), ("order", o1940), ("attention", o1940)]
    assert out[1].get("kept") and out[2].get("kept") and not out[3].get("kept")

    # Words with no change, after a read of something the screen does not show, still go.
    why = []
    assert screen.carry([], branch=half, calls=read, why=why) == [] and why == [screen.WHY_READ_ELSEWHERE]


@pytest.mark.parametrize("on_the_way", [
    ("shopify_order_detail", {"order_id": data.BY_NAME["#1940"].order_id}),   # the order read again first
    ("gmail_read_thread", {"thread_id": PRIYAS_THREAD}),                      # an email read to prepare it
])
async def test_a_note_on_one_of_two_orders_up_keeps_the_other_through_the_hold(world, on_the_way):
    """Round 12's C3: with #1938 and #1940 up, a note staged on #1940 is the card on top and both
    orders stay under it — whatever the model read on the way, which never shows — and after the
    hold the proof and both orders are his screen."""
    sid = f"note-{on_the_way[0]}"
    await _side_by_side(world, sid)
    put_back = _accepting_notes(world)
    try:
        staged = await world.ask("add a note to 1940 saying fragile", on_the_way,
                                 ("shopify_order_note_append", {"order_id": data.BY_NAME["#1940"].order_id, "note": "Fragile"}),
                                 session_id=sid, reply="The note is ready on #1940's card.")
        kinds = [c["type"] for c in _cards(staged)]
        assert kinds[0] == "confirmation", kinds
        assert sorted(_numbers(staged)) == ["#1938", "#1940"], kinds
        assert "email_thread" not in kinds and "email_list" not in kinds, kinds
        (card,) = [c["data"] for c in staged.ui if c["type"] == "confirmation"]
        await _hold(world, sid, card["proposal_id"])
        shown = world.branch(sid).last_ui
        assert "success" in [c.get("type") for c in shown]
        assert sorted(str(c["data"].get("order_number")) for c in shown if c.get("type") == "order") == ["#1938", "#1940"]
    finally:
        put_back()


async def test_a_change_that_replaces_the_screen_is_still_the_card_on_top(world):
    """Review note 1 of flow's second review (8 October): with #1938 and #1940 up, "add a note to
    1940 saying fragile, it goes with 1939" names an order the screen does not show (and the note
    does not carry it), so the answer replaces his screen (round 12) and `carry` hands back rule
    1's cards as they are. The model read #1939 and #1940 on the way. #1940 was up, so its full
    card stays beside the note; DEC-069 says the change card stays on top, so the note he holds
    comes first, above #1940's card, not under it where a 601x889 tablet hides it."""
    sid = "note-names-1939"
    await _side_by_side(world, sid)
    staged = await world.ask("add a note to 1940 saying fragile, it goes with 1939",
                             ("shopify_find_order", {"query": "1939"}),
                             ("shopify_order_detail", {"order_id": data.BY_NAME["#1939"].order_id}),
                             ("shopify_order_detail", {"order_id": data.BY_NAME["#1940"].order_id}),
                             ("shopify_order_note_append", {"order_id": data.BY_NAME["#1940"].order_id,
                                                            "note": "Fragile"}),
                             session_id=sid, reply="The note is ready on #1940's card.")
    assert all(c.get("ok") for c in staged.raw["tool_calls"]), staged.raw["tool_calls"]
    kinds = [c["type"] for c in _cards(staged)]
    assert "confirmation" in kinds, kinds
    assert kinds[0] == "confirmation", kinds
    # The screen was replaced (1939 was named and is not up): #1938 is gone, and #1940, the record
    # the note is to, is under the card it is being changed by.
    assert _numbers(staged) == ["#1940"], kinds
    assert kinds.index("order") > kinds.index("confirmation"), kinds


async def test_the_reply_with_another_order_up_is_still_the_reply_alone(world):
    """The reply to a customer found by searching, with an order of somebody else's up: the
    change is not to anything he had up, so it is the reply and nothing else (rule 1)."""
    sid = "reply-over-1938"
    await world.open_order("1938", session_id=sid)
    said = await world.ask("show me the email reply to priya", *_the_reply_turn("gmail_send_reply"), session_id=sid,
                           reply="Here's the reply to Priya.")
    assert [c["type"] for c in _cards(said)] == ["confirmation"], [c["type"] for c in _cards(said)]
