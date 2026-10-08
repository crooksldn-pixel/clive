""""It's on your screen", and an answer that lands after the owner has moved on (the round-12
deploy review of 361b0138, RC-4b).

S2T-01: the on-screen claim repair (`app/routes/turn.py` `_hold_to_the_screen`) drew the record the
model's sentence named, in place of the record the turn had actually read. "Show me order 1940",
the model reads #1940 and says "Order #1938 is on your screen": #1940's card was swapped for
#1938's and the cursor followed it. The repair never replaces what the turn read with a record it
did not read; the false sentence is taken out instead.

R9-D2-D2-01: `_answer` decided once, before its awaits, that the turn was still current. The claim
repair can wait on the shop; a newer sentence to the same half that finished in that wait was then
overwritten: the older answer moved the cursor and the half's stored screen back to its record, so
the next tapped Add a note bound an order the owner had moved off. After every await the turn is
asked again whether it is still the half's current one.

The real routes, gate, engine, presentation and read scheduler, against the fake shop of
tests/test_r11_turn.py; the only stand-in is Claude, a scripted model making real tool calls.
"""

from __future__ import annotations

import asyncio

from app.observability import claims
from tests import test_r11_turn
from tests.test_r11_turn import notes
from tests.test_turn_boundary import A, B, reads, records, say, show_order

desk = test_r11_turn.desk


def reads_then_says(step, words: str):
    """Claude making these reads, then saying `words` — whatever they were."""
    async def said(session, calls, text):
        await step(session, calls, text)
        return words
    return said


def says(words: str):
    """Claude saying `words`, and reading and drawing nothing."""
    async def said(session, calls, text):
        return words
    return said


def orders_on(body: dict) -> set[str]:
    return {ref for kind, ref in records(body) if kind in ("order", "order_workspace")}


# ================================================= the claim never replaces what was read (#17)


async def test_a_claim_about_another_order_does_not_replace_the_order_the_turn_read(desk):
    """S2T-01, as the finding gives it. #1938 was up; "show me order 1940"; the model reads #1940
    and says "Order #1938 is on your screen." #1940's card is what he asked for and what the turn
    read: it stays, the cursor goes to #1940, and the false sentence is not spoken."""
    desk.model.steps = [show_order("1938"), reads_then_says(show_order("1940"), "Order #1938 is on your screen.")]
    await say(desk, "show me order 1938", "claim")
    body = await say(desk, "show me order 1940", "claim")

    assert orders_on(body) == {B}, records(body)
    assert body["branch"]["entity"]["ref"] == B, body["branch"]["entity"]
    assert "#1938 is on your screen" not in body["answer"], body["answer"]
    assert body["answer"] == "#1940 is on your screen.", body["answer"]
    half = desk.runtime.sessions.get("claim").branch()
    assert {u["data"].get("order_id") for u in half.last_ui if u["type"] == "order"} == {B}


async def test_with_nothing_named_the_claim_still_cannot_move_the_cursor_to_a_record_not_read(desk):
    """The same slip with no order named: "and the newest one?" is read as #1940, and the answer
    claims #1938. The cursor used to follow the drawn #1938. What the turn read stands, and so
    does the rest of what the model said."""
    desk.model.steps = [show_order("1938"),
                        reads_then_says(show_order("1940"), "Paid yesterday. Order #1938 is on your screen.")]
    await say(desk, "show me order 1938", "unnamed")
    body = await say(desk, "and the newest one?", "unnamed")

    assert orders_on(body) == {B}, records(body)
    assert body["branch"]["entity"]["ref"] == B
    assert body["answer"] == "Paid yesterday.", body["answer"]
    assert claims.NOT_ON_SCREEN not in body["answer"]


async def test_a_claim_over_a_screen_the_turn_left_to_the_record_before_is_still_made_true(desk):
    """What must not get worse: a turn that read nothing, over the record kept up from before, and
    a claim naming the one other order the conversation holds — the turn read nothing to replace,
    so the claimed order is drawn and the sentence stands (round 12)."""
    desk.model.steps = [show_order("1940"), show_order("1938"), says("Confirmed, order 1940 on screen.")]
    await say(desk, "show me order 1940", "true")
    await say(desk, "show me order 1938", "true")
    body = await say(desk, "put 1940 up", "true")
    assert orders_on(body) == {B} and body["answer"] == "Confirmed, order 1940 on screen."


# =========================================== an answer that lands after it was replaced (#18)


async def _held_claim(desk, monkeypatch, sid: str):
    """#1938 then #1940 shown; #1938 put out of the Mac's copy so the claim's repair must read the
    shop for it, and that read held until the test lets it go. Returns (reached, release)."""
    from app.memory import ENTITY
    from app.memory import current as memory
    from app.reads import scheduler

    desk.model.steps = [show_order("1938"), show_order("1940")]
    await say(desk, "show me order 1938", sid)
    await say(desk, "show me order 1940", sid)
    memory().drop(ENTITY, f"order:{A}")
    reached, release = asyncio.Event(), asyncio.Event()
    real = scheduler.run_plan

    async def held(plan, **kwargs):
        if getattr(plan, "label", "") == "on_screen_claim":
            reached.set()
            await release.wait()
        return await real(plan, **kwargs)

    monkeypatch.setattr(scheduler, "run_plan", held)
    return reached, release


async def test_an_answer_replaced_while_its_claim_is_read_moves_neither_the_cursor_nor_the_screen(desk, monkeypatch):
    """R9-D2-D2-01. "Put 1938 back up" is answered "Order 1938 is on your screen." with nothing
    drawn, so the Mac reads #1938 to make that true — and while the shop is slow, "show me order
    1940" is asked of the same half and answered. The older answer then lands: it used to draw
    #1938, put the cursor on it and store #1938 as the half's screen over the newer answer, so
    the next Add a note bound #1938. It publishes nothing now."""
    sid = "late-claim"
    reached, release = await _held_claim(desk, monkeypatch, sid)
    desk.model.steps = [says("Order 1938 is on your screen."), show_order("1940")]
    older = asyncio.create_task(say(desk, "put 1938 back up", sid))
    await asyncio.wait_for(reached.wait(), 5)
    newer = await say(desk, "show me order 1940", sid)
    release.set()
    late = await asyncio.wait_for(older, 5)

    half = desk.runtime.sessions.get(sid).branch()
    assert orders_on(newer) == {B}
    assert late["ui"] == [], [i["type"] for i in late["ui"]]
    assert half.entity["ref"] == B, f"the late answer put the cursor on {half.entity}"
    assert half.last_question == "show me order 1940", half.last_question
    assert {u["data"].get("order_id") for u in half.last_ui if u["type"] == "order"} == {B}
    assert half.in_flight == 0 and half.state() != "WORKING"


async def test_a_change_staged_by_an_answer_replaced_while_its_claim_is_read_is_withdrawn(desk, monkeypatch):
    """The same wait, with a change in the older answer: a note on #1940 prepared, and the answer
    claiming #1938 is up. The newer sentence lands in the wait; the older answer's note is
    withdrawn, never shown, and nothing reaches the shop."""
    sid = "late-change"
    reached, release = await _held_claim(desk, monkeypatch, sid)
    # DEC-069 (7 Oct): a change waiting for him IS the screen, so a claim beside it is taken out
    # and the shop is never read to draw the record it names — that read is no longer where this
    # answer waits. Until 7 Oct the wait was the claim's read (`reached`); the same window is now
    # held open in the answer itself, after the note is prepared and before the words come back.
    prepared, go_on = asyncio.Event(), asyncio.Event()

    async def note_then_wait(session, calls, text):
        await notes(B, "Fragile")(session, calls, text)
        prepared.set()
        await go_on.wait()
        return "The note is ready. Order 1938 is on your screen."

    desk.model.steps = [note_then_wait, show_order("1940")]
    older = asyncio.create_task(say(desk, "add a note to 1940 saying fragile", sid))
    await asyncio.wait_for(prepared.wait(), 5)
    await say(desk, "show me order 1940", sid)
    go_on.set()
    release.set()
    late = await asyncio.wait_for(older, 5)

    (proposal,) = desk.runtime.sessions.get(sid).proposals
    assert proposal.entity_ref == B and proposal.status.value == "REVOKED"
    assert late["ui"] == []
    assert desk.runtime.sessions.get(sid).branch().entity["ref"] == B
    assert desk.store.mutations == []
    assert not reached.is_set(), "the shop was read to draw a record beside the change card"


async def test_a_claim_beside_a_change_waiting_for_him_is_taken_out_and_the_change_stays_the_screen(desk, monkeypatch):
    """DEC-069: the note on #1940 is prepared and the answer says "Order 1938 is on your screen".
    The change card is what he has to hold, so it stays the screen: #1938 is not read and not drawn
    in its place, the false sentence is not spoken, and the note is still waiting."""
    sid = "claim-beside-change"
    reached, release = await _held_claim(desk, monkeypatch, sid)
    release.set()
    desk.model.steps = [reads_then_says(notes(B, "Fragile"), "The note is ready. Order 1938 is on your screen.")]
    body = await say(desk, "add a note to 1940 saying fragile", sid)

    (proposal,) = desk.runtime.sessions.get(sid).proposals
    assert proposal.status.value == "PENDING"
    # The turn's own screen is the change; #1940, which he was looking at, is kept up beside it
    # (app/screen.py carries the half's screen under a change about what it shows). #1938 is not.
    own = [i["type"] for i in body["ui"] if i["type"] != "context_stack" and not i.get("kept") and not i.get("refreshed")]
    assert own == ["confirmation"], records(body)
    assert orders_on(body) <= {B}, records(body)
    assert "1938 is on your screen" not in body["answer"] and body["answer"] == "The note is ready.", body["answer"]
    assert not reached.is_set(), "the shop was read to draw a record beside the change card"
    assert desk.store.mutations == []


async def test_an_answer_nobody_replaced_still_waits_for_its_claim_and_draws_it(desk, monkeypatch):
    """The control: the same slow read, and nothing asked meanwhile. The claim is made true when
    the read lands — #1938 drawn and the cursor on it — as it always was."""
    sid = "slow-claim"
    reached, release = await _held_claim(desk, monkeypatch, sid)
    desk.model.steps = [says("Order 1938 is on your screen.")]
    asking = asyncio.create_task(say(desk, "put 1938 back up", sid))
    await asyncio.wait_for(reached.wait(), 5)
    release.set()
    body = await asyncio.wait_for(asking, 5)
    assert orders_on(body) == {A}, records(body)
    assert body["branch"]["entity"]["ref"] == A and body["answer"] == "Order 1938 is on your screen."


async def test_an_answer_to_one_half_is_not_abandoned_by_a_question_to_the_other(desk, monkeypatch):
    """The re-check is per half: a sentence to the OTHER half during the wait is not a newer
    question to this one, and this answer still lands whole."""
    sid = "two-halves"
    reached, release = await _held_claim(desk, monkeypatch, sid)
    left = desk.runtime.sessions.get(sid).focused_branch
    from tests.second_half import second_half  # the fork route went with Split (DEC-071, ruling 37)

    other = second_half(desk.runtime.sessions.get(sid))
    assert other != left
    desk.model.steps = [says("Order 1938 is on your screen."), reads()]
    asking = asyncio.create_task(say(desk, "put 1938 back up", sid, branch_id=left))
    await asyncio.wait_for(reached.wait(), 5)
    await say(desk, "how are sales today?", sid, branch_id=other)
    release.set()
    body = await asyncio.wait_for(asking, 5)
    assert orders_on(body) == {A}, records(body)
    assert desk.runtime.sessions.get(sid).branches[left].entity["ref"] == A
