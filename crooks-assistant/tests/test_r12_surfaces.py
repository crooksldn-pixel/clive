"""What stays on the owner's screen while he works on it — round 12, George's own words.

    "A task is asked, a screen is shown, an edit is asked, the edit succeeds, however the screen
    disappears. This is a persistent issue."

Each test here is that sentence, driven through the real routes the tablet uses: the sentence to
`POST /turn` (a scripted model making real tool calls through the real gate and dispatcher), the
gesture to `POST /actions/{id}/commit`, a tap to `POST /command`. What is asserted is what the
Mac hands the tablet to draw: the record he was working on is still in the answer, marked as the
card already on the glass (`kept`), beside whatever the change put there — and the half's own
copy of its screen (`branch.show`, which a reload or a switch of halves draws) agrees.

The only things that clear the screen are his own close or back, a genuinely new subject, and
the privacy rules that already exist. Each of those is held here too, so that keeping the screen
never turns into keeping the wrong one.
"""

from __future__ import annotations

import pytest

from app.tools.dispatch import dispatch
from tests import test_r11_turn
from tests.test_r11_turn import commit, confirmation
from tests.test_turn_boundary import A, B, reads, say, show_order, tap

# The desk of tests/test_r11_turn.py: the real routes, the real gate and engine, a scripted model
# and a fake shop that takes one change, an order's note, so a tapped change can be followed to
# what the shop is sent.
desk = test_r11_turn.desk


def notes_the_open_order(note: str):
    """Claude adding a note to the order on screen, by the id the conversation already holds —
    what it does when the owner says "add a note: …" with the order in front of him."""
    async def step(session, calls, text):
        await dispatch("shopify_order_note_append", {"order_id": session.branch().entity["ref"], "note": note},
                       session=session, timeout_s=5, calls=calls)
        return "The note is ready on the card; tap to apply."
    return step


def notes_order(ref: str, note: str):
    async def step(session, calls, text):
        await dispatch("shopify_order_note_append", {"order_id": ref, "note": note}, session=session, timeout_s=5, calls=calls)
        return "The note is ready on the card; tap to apply."
    return step


def answers(words: str):
    """Claude answering from what it already knows, reading nothing and drawing nothing."""
    async def step(session, calls, text):
        return words
    return step


def cards(body: dict) -> list[dict]:
    return [item for item in body.get("ui") or [] if item.get("type") != "context_stack"]


def kinds(body: dict) -> list[str]:
    return [item["type"] for item in cards(body)]


def the_order(body: dict, ref: str) -> dict:
    found = [item for item in cards(body) if item["type"] == "order" and item["data"].get("order_id") == ref]
    assert len(found) == 1, f"order {ref} is not on the screen once: {kinds(body)}"
    return found[0]


# ================================================= the order stays through the whole change


async def test_the_order_stays_on_screen_while_a_note_is_prepared_and_after_it_is_applied(desk):
    """George's complaint, whole: the order is shown, a note is asked for, the note is applied.
    At every step the order is on the screen — beside the card while it waits, and redrawn with
    the note once the change is proven — and the half's own copy of its screen agrees."""
    desk.model.steps = [show_order("1938"), notes_the_open_order("Gift wrap it")]
    shown = await say(desk, "show me order 1938", "keep")
    assert kinds(shown)[0] == "order"

    noted = await say(desk, "add a note saying gift wrap it", "keep")
    order = the_order(noted, A)
    assert order.get("kept") is True, "the order was not carried: it is the card already on the glass"
    # The card to tap comes first, where his eye goes; the order is under it, as it stood.
    assert kinds(noted)[0] == "confirmation", kinds(noted)
    card = confirmation(noted)

    applied = await commit(desk, card["proposal_id"], "keep")
    body = applied.json()
    assert applied.status_code == 200 and body["status"] == "verified", applied.text
    fresh = the_order(body, A)
    assert "Gift wrap it" in (fresh["data"].get("note") or ""), fresh["data"].get("note")

    # A reload, or a tap back onto this half, draws the Mac's copy of the screen: the order with
    # its note and the proof, never the card as it stood before the gesture.
    again = await tap(desk, "branch.show", "keep")
    assert "Gift wrap it" in (the_order(again, A)["data"].get("note") or "")
    assert "success" in kinds(again), kinds(again)
    assert not [c for c in cards(again) if c["type"] == "confirmation" and c["data"].get("status") == "pending"], kinds(again)


async def test_an_answer_in_words_keeps_the_record_on_screen(desk):
    """"What's the note on it?" answered in words draws nothing new, so nothing replaces the
    order: it stays, as the card already on the glass."""
    desk.model.steps = [show_order("1938"), answers("It says leave with the neighbour.")]
    await say(desk, "show me order 1938", "words")
    said = await say(desk, "what's the note on it?", "words")
    assert the_order(said, A).get("kept") is True, kinds(said)


async def test_a_change_that_could_not_be_prepared_keeps_the_record_and_says_why(desk):
    """The gate refuses a note on an order the conversation never looked up. The order he is
    looking at stays; the refusal is beside it rather than instead of it."""
    desk.model.steps = [show_order("1938"), notes_order("gid://shopify/Order/9999", "Gift wrap it")]
    await say(desk, "show me order 1938", "refused")
    body = await say(desk, "add a note saying gift wrap it", "refused")
    assert the_order(body, A).get("kept") is True, kinds(body)


async def test_a_change_to_another_order_is_not_drawn_over_this_one(desk):
    """A card for #1940 while #1938 is on screen is not about #1938, and #1938 must not stand
    above it looking like the order it changes: the screen is the card for #1940."""
    desk.model.steps = [show_order("1940"), show_order("1938"), notes_order(B, "Fragile")]
    await say(desk, "show me order 1940", "other")
    await say(desk, "show me order 1938", "other")
    body = await say(desk, "add a note to 1940 saying fragile", "other")
    assert confirmation(body)["entity_ref"] == B
    assert "order" not in kinds(body), kinds(body)


async def test_a_new_subject_replaces_the_screen(desk):
    """Asking for another order is a new subject: it replaces the screen and nothing is kept."""
    desk.model.steps = [show_order("1938"), show_order("1940")]
    await say(desk, "show me order 1938", "new")
    body = await say(desk, "show me order 1940", "new")
    assert [c["data"].get("order_id") for c in cards(body) if c["type"] == "order"] == [B]
    assert not [c for c in cards(body) if c.get("kept")], kinds(body)


async def test_the_order_stays_when_the_applied_change_is_refused_as_stale(desk):
    """The order changed in Shopify between the card and the gesture: nothing is applied, and
    the order he was working on stays on the half's screen beside the reason."""
    desk.model.steps = [show_order("1938"), notes_the_open_order("Gift wrap it")]
    await say(desk, "show me order 1938", "stale")
    card = confirmation(await say(desk, "add a note saying gift wrap it", "stale"))
    desk.store.orders[A]["note"] = "Changed in Shopify meanwhile"
    applied = await commit(desk, card["proposal_id"], "stale")
    assert applied.json()["status"] == "stale", applied.text
    again = await tap(desk, "branch.show", "stale")
    assert "order" in kinds(again), kinds(again)
    assert desk.store.mutations == []


async def test_the_order_workspace_stays_and_is_recomposed_after_the_change(desk):
    """An order shown as its workspace keeps being its workspace: beside the card while the note
    waits, and recomposed from the fresh read once it is applied — not swapped for a plainer
    card of the same order."""
    desk.model.steps = [show_order("1940"), notes_the_open_order("Fragile")]
    shown = await say(desk, "show me the items and the shipping on order 1940", "ws")
    assert kinds(shown)[0] == "order_workspace", kinds(shown)
    noted = await say(desk, "add a note saying fragile", "ws")
    (kept,) = [c for c in cards(noted) if c["type"] == "order_workspace"]
    assert kept.get("kept") is True and kept["data"]["ref"] == B
    body = (await commit(desk, confirmation(noted)["proposal_id"], "ws")).json()
    assert body["status"] == "verified", body
    (fresh,) = [c for c in cards(body) if c["type"] == "order_workspace"]
    facts = {f["key"]: f["value"] for f in fresh["data"]["sections"]["overview"]["facts"]}
    assert "Fragile" in facts.get("Note", ""), facts
    assert "order" not in kinds(body), "the workspace was swapped for a plainer card of the same order"


# ============================================ "pull that up again" — the screen comes back


def again(said: list[str], **args):
    """Claude asked to put something back: it calls show_again, and what the tool told it is
    kept so the test can read it."""
    async def step(session, calls, text):
        said.append(await dispatch("show_again", dict(args), session=session, timeout_s=10, calls=calls))
        return "It's back on your screen."
    return step


async def test_pull_that_up_again_brings_back_the_order_the_screen_moved_on_from_read_again(desk):
    """#1938 is up, then #1940 replaces it. "Pull that up again" puts #1938 back — read again,
    so a note written in Shopify meanwhile is on it — and the half's cursor is on it, so the
    next "add a note" goes where the owner is looking."""
    told: list[str] = []
    desk.model.steps = [show_order("1938"), show_order("1940"), again(told)]
    await say(desk, "show me order 1938", "back")
    await say(desk, "show me order 1940", "back")
    desk.store.orders[A]["note"] = "Written in Shopify meanwhile"
    body = await say(desk, "pull that up again", "back")
    order = the_order(body, A)
    assert order["data"]["note"] == "Written in Shopify meanwhile", "shown as it was, not read again"
    assert order["data"].get("actions"), "the order came back without its rail"
    assert body["branch"]["entity"]["ref"] == A
    assert '"fresh": true' in told[0] and "#1938" in told[0], told


async def test_show_me_the_order_again_finds_it_by_kind_behind_a_customer(desk):
    told: list[str] = []
    desk.model.steps = [show_order("1938"),
                        reads(("shopify_find_customer", {"query": "Mia"})),
                        again(told, kind="order")]
    await say(desk, "show me order 1938", "kind")
    await say(desk, "who is Mia?", "kind")
    body = await say(desk, "show me the order again", "kind")
    assert the_order(body, A)
    assert "customer" not in kinds(body), kinds(body)


async def test_an_order_workspace_comes_back_as_its_workspace(desk):
    told: list[str] = []
    desk.model.steps = [show_order("1940"), show_order("1938"), again(told, ref=B)]
    await say(desk, "show me the items and the shipping on order 1940", "wsback")
    await say(desk, "show me order 1938", "wsback")
    body = await say(desk, "bring 1940 back up", "wsback")
    (workspace,) = [c for c in cards(body) if c["type"] == "order_workspace"]
    assert workspace["data"]["ref"] == B
    assert "order" not in kinds(body), "the workspace came back as a plainer card"


async def test_a_slow_or_failed_read_brings_back_the_copy_held_and_says_so(desk, monkeypatch):
    """Shopify does not answer the read: the order the Mac last read goes back up, and the model
    is told it is that, not the order as it is now."""
    told: list[str] = []
    desk.model.steps = [show_order("1938"), show_order("1940"), again(told, ref=A)]
    await say(desk, "show me order 1938", "slow")
    await say(desk, "show me order 1940", "slow")
    real = desk.store.graphql

    async def unanswered(query, variables=None):
        if (variables or {}).get("id") == A:
            raise TimeoutError("Shopify did not answer")
        return await real(query, variables)

    monkeypatch.setattr(desk.store, "graphql", unanswered)
    body = await say(desk, "show me 1938 again", "slow")
    assert the_order(body, A)
    assert '"fresh": false' in told[0] and "as I last read it" in told[0], told


async def test_an_id_this_conversation_was_never_given_is_not_shown(desk):
    """The gate's own rule: an id the conversation was not issued is refused before the tool
    runs, and nothing is drawn."""
    told: list[str] = []
    desk.model.steps = [show_order("1938"), again(told, ref="gid://shopify/Order/9999")]
    await say(desk, "show me order 1938", "stranger")
    body = await say(desk, "pull up order 9999 again", "stranger")
    (call,) = [c for c in body["tool_calls"] if c["name"] == "show_again"]
    assert call["ok"] is False
    assert not [c for c in cards(body) if c["type"] == "order" and c["data"].get("order_id") == "gid://shopify/Order/9999"]


async def test_nothing_shown_is_nothing_to_bring_back_and_the_model_is_told_so(desk):
    told: list[str] = []
    desk.model.steps = [again(told)]
    await say(desk, "pull that up again", "empty")
    assert told and "nothing to put back" in told[0], told


# ================================================ an email thread, and the draft written on it


HER_1938_THREAD = "aa70d3f83dbef06e"     # the golden world's "Order 1938 — can I add to it?"


@pytest.fixture()
async def world():
    from experience.harness import harness

    async with harness(admitted=True) as h:
        yield h


async def _thread_up(h, session: str) -> None:
    await h.open_order("1938", session_id=session)
    thread = await h.ask("show me her email about it", ("gmail_read_thread", {"thread_id": HER_1938_THREAD}),
                         reply="She asked to add to it.", session_id=session)
    assert thread.surface_types[0] == "email_thread", thread.surface_types


async def test_the_email_thread_stays_on_screen_while_a_draft_is_prepared_on_it(world):
    """George's "an email thread after a draft": the reply is prepared, and the thread he was
    reading is still there under the card, as the card already on the glass."""
    from experience.fixtures import data

    await _thread_up(world, "draft")
    drafted = await world.ask("draft a reply saying it went out this morning",
                              ("gmail_draft_reply", {"thread_id": HER_1938_THREAD, "order_id": data.BY_NAME["#1938"].order_id,
                                                     "body": "It went out this morning."}),
                              reply="The draft is ready to tap.", session_id="draft")
    assert drafted.surface_types[:2] == ["confirmation", "email_thread"], drafted.surface_types
    (thread,) = [s for s in drafted.surfaces if s["type"] == "email_thread"]
    assert thread.get("kept") is True and thread["data"]["thread_id"] == HER_1938_THREAD


async def test_bring_back_the_draft_after_it_was_withdrawn_tells_the_model_exactly_what_to_prepare(world, monkeypatch):
    """"Bring back the draft" is itself a new instruction, and a new instruction withdraws the
    card that was waiting. A read cannot put a change back — only its write tool stages one —
    so show_again tells the model the tool and the words to prepare it again, and the thread
    stays up meanwhile."""
    from app.tools import dispatch as dispatch_module
    from experience.fixtures import data

    await _thread_up(world, "again")
    order_id = data.BY_NAME["#1938"].order_id
    await world.ask("draft a reply saying it went out this morning",
                    ("gmail_draft_reply", {"thread_id": HER_1938_THREAD, "order_id": order_id, "body": "It went out this morning."}),
                    reply="The draft is ready to tap.", session_id="again")
    told: list[str] = []
    real = dispatch_module.dispatch

    async def listening(name, args, **kwargs):
        text = await real(name, args, **kwargs)
        if name == "show_again":
            told.append(text)
        return text

    monkeypatch.setattr(dispatch_module, "dispatch", listening)
    back = await world.ask("bring back the draft", ("show_again", {"kind": "draft"}), reply="Here it is.", session_id="again")
    assert told and "gmail_draft_reply" in told[0] and "It went out this morning." in told[0], told
    assert "email_thread" in back.surface_types, back.surface_types


# ====================================== never "on screen" when nothing is (round 12, complaint 3)


def claims_only(words: str):
    """Claude saying something is on the screen, and reading and drawing nothing."""
    async def step(session, calls, text):
        return words
    return step


async def test_an_order_claimed_on_screen_and_not_drawn_is_drawn(desk):
    """"Put 1940 up" answered "Confirmed, order 1940 on screen." with nothing drawn: the Mac
    makes it true — #1940, the one order the answer names, is drawn from what the conversation
    holds — and the sentence stands, because it is now true."""
    from app.observability import claims

    desk.model.steps = [show_order("1940"), show_order("1938"), claims_only("Confirmed, order 1940 on screen.")]
    await say(desk, "show me order 1940", "claim")
    await say(desk, "show me order 1938", "claim")
    body = await say(desk, "put 1940 up", "claim")
    assert the_order(body, B)
    assert "order" not in [c["type"] for c in cards(body) if c["data"].get("order_id") == A]
    assert body["answer"] == "Confirmed, order 1940 on screen." and claims.NOT_ON_SCREEN not in body["answer"]
    assert body["branch"]["entity"]["ref"] == B


async def test_a_claim_with_nothing_to_stand_on_is_corrected_before_it_is_spoken(desk, monkeypatch):
    """A fresh conversation, nothing shown, no record to be on, and "It's on your screen now."
    The Mac cannot tell what was meant, so the claim comes out of the answer — the rest of it
    stands — and the owner is told how to get it shown. The voice says the corrected words."""
    from app.observability import claims

    spoken: list[str] = []
    monkeypatch.setattr(desk.runtime.voice, "prefetch", lambda text, pin=False: spoken.append(text))
    desk.model.steps = [claims_only("Paid, not shipped. It's on your screen now.")]
    body = await say(desk, "is it paid?", "nothing", speak=True)
    assert body["answer"] == f"Paid, not shipped. {claims.NOT_ON_SCREEN}", body["answer"]
    assert kinds(body) == []
    assert spoken and "on your screen now" not in spoken[-1] and "show it" in spoken[-1], spoken


async def test_a_claim_over_the_record_kept_on_screen_is_true_and_left_alone(desk):
    desk.model.steps = [show_order("1938"), claims_only("It's on your screen.")]
    await say(desk, "show me order 1938", "true")
    body = await say(desk, "is it on screen?", "true")
    assert body["answer"] == "It's on your screen."
    assert the_order(body, A).get("kept") is True


async def test_two_orders_claimed_and_neither_drawn_is_corrected_not_guessed(desk):
    from app.observability import claims

    desk.model.steps = [show_order("1938"), show_order("1940"), claims_only("Orders 1938 and 1940 are both on your screen.")]
    await say(desk, "show me order 1938", "two")
    await say(desk, "show me order 1940", "two")
    body = await say(desk, "put order 1938 and order 1940 up", "two")
    assert body["answer"] == claims.NOT_ON_SCREEN, body["answer"]
    assert records_on(body) == set()


async def test_an_order_the_conversation_never_saw_is_not_drawn_to_make_a_claim_true(desk):
    from app.observability import claims

    desk.model.steps = [claims_only("Order 1999 is on your screen.")]
    body = await say(desk, "put 1999 up", "never")
    assert claims.NOT_ON_SCREEN in body["answer"] and kinds(body) == []


async def test_a_named_tv_screen_is_not_this_screen(desk):
    """"On the office screen" is one of his TVs and is not judged here; neither is a turn that
    used a screen tool, whatever words it used."""
    desk.model.steps = [claims_only("It's on the office screen.")]
    body = await say(desk, "put it on the office screen", "tv")
    assert body["answer"] == "It's on the office screen."


def records_on(body: dict) -> set[str]:
    return {c["data"].get("order_id") for c in cards(body) if c["type"] == "order"} - {None}


async def test_the_claim_is_written_to_the_timeline_beside_the_decline_claims(desk, tmp_path):
    import json
    from pathlib import Path

    from app.observability import timeline
    from app.observability.session import TestSessions

    timeline.forget_names()
    store = TestSessions(Path(tmp_path) / "sessions")
    line = timeline.install(timeline.Timeline(store))
    session = line.start("on-screen claims")
    try:
        desk.model.steps = [show_order("1940"), show_order("1938"), claims_only("Confirmed, order 1940 on screen."),
                            claims_only("It's up now for you.")]
        await say(desk, "show me order 1940", "tl")
        await say(desk, "show me order 1938", "tl")
        await say(desk, "put 1940 up", "tl")
        await say(desk, "put 1999 up", "tl-fresh")
        line.flush(2.0)
        events = [json.loads(x) for x in store.timeline_path(session).read_text(encoding="utf-8").splitlines() if x.strip()]
    finally:
        line.stop()
        timeline.install(timeline.NullTimeline())
        timeline.forget_names()
    claimed = [e for e in events if e.get("kind") == "unsupported_claim" and e.get("claim") == "on_screen"]
    assert [(e["session_id"], bool(e.get("drew")), e["corrected"]) for e in claimed] == [("tl", True, False), ("tl-fresh", False, True)], claimed
