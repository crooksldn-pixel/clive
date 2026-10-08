"""Where a change goes, held to what the owner said and what he tapped (the round-12 deploy
review of 361b0138, RC-4a).

Every sentence is the model's (the owner's decision of 28 September 2026). What these hold is the
check that runs AFTER the model, on what it did (`app/routes/turn.py` `_off_target`):

* when the owner's words name an order, the change is on an order they name, tapped or not;
  nothing the change itself writes excuses a number he said. On the order he tapped he is asked
  which order it is for, and "on this one" places it. So "add a note to order 1940: 1940 goes
  with the gift box" still names #1940 as where it goes, and the model's own words — "1940:
  fragile", a refund's reason repeating 1940, his own sentence copied onto #1938 — excuse
  nothing (S2a-01, R9-I-tests2-I-01, R9-I-tests5-I-03);
* a change made under a tapped control — Add a note, Reply — lands on the record the tap bound,
  unless his own words named another; after a tapped Reply, anything written is in the tapped
  thread (R9-D1-D1-02, R9-D2-D2-04);
* a new email goes to an order he named and a person he named; when he named two people he is
  asked which it is to;
* a change on a person — store credit — goes only to the person he named, and not at all when
  the name he said is two people's (R9-D2-D2-05);
* the model is told, once, at the next question, what was withdrawn and what he was asked.

The routes, the gate, the dispatcher, the action engine and the presentation are the real ones,
against the fake shop of tests/test_r11_turn.py; the only stand-in is Claude, a scripted model
making real tool calls. Where the model's choice matters, the script names it and the assertion
is about what the Mac does with that choice.
"""

from __future__ import annotations

import pytest

from app.tools.dispatch import dispatch
from tests import test_r11_turn
from tests.test_r11_turn import MIA_JONES, bind_note, confirmation, no_confirmation, notes
from tests.test_turn_boundary import (
    DANIEL,
    MIA,
    A,
    B,
    _order,
    found_customer,
    found_order,
    reads,
    say,
    show_order,
    tap,
)

# The desk of tests/test_r11_turn.py: two orders (#1938 Daniel's, #1940 Mia Kowalski's), their
# customers, a second Mia, store credit, and one change the shop will take, an order's note.
desk = test_r11_turn.desk

WITHDRAWN_1940 = ("You said #1940, but the change I'd prepared was for #1938, so I've withdrawn it. "
                  "Say which order you want it on.")
# The same, after Add a note was tapped on #1938: he is asked, not corrected.
ASKED_AFTER_THE_TAP_1940 = ("You'd tapped Add a note on #1938 and said #1940, so I haven't put it on #1938. "
                            "Say which order it's for.")
# A third order, for Daniel: an order the owner neither names nor is looking at.
C = "gid://shopify/Order/1941"


async def _on_1938_with_1940_held(desk, sid: str) -> None:
    """#1940 read, then #1938: both orders held, the cursor on #1938."""
    desk.model.steps[:0] = [show_order("1940"), show_order("1938")]
    await say(desk, "show me order 1940", sid)
    shown = await say(desk, "show me order 1938", sid)
    assert shown["branch"]["entity"]["ref"] == A


def _only(desk, sid: str):
    (proposal,) = desk.runtime.sessions.get(sid).proposals
    return proposal


# ============================= a number said as where, and again inside what is written (#11-#13)


@pytest.mark.parametrize("tapped", [False, True], ids=["said", "said-after-add-a-note-on-1938"])
async def test_an_order_named_as_where_and_again_in_the_note_still_holds_the_note_to_it(desk, tapped):
    """S2a-01 and R9-I-tests2-I-01. "Add a note to order 1940: 1940 goes with the gift box", and
    the model puts that note on #1938. The number is said twice — once as where the note goes,
    once inside it — and the note carries it once. The old check took away every number the note
    carried, so #1940 was no longer named and the change stood on #1938."""
    sid = f"twice-{int(tapped)}"
    await _on_1938_with_1940_held(desk, sid)
    if tapped:
        assert (await bind_note(desk, sid, kind="order", ref=A))["ok"] is True
    desk.model.steps = [notes(A, "1940 goes with the gift box")]
    body = await say(desk, "add a note to order 1940: 1940 goes with the gift box", sid)

    proposal = _only(desk, sid)
    assert proposal.entity_ref == A
    assert proposal.status.value == "REVOKED" and proposal.reason == "not the order the owner named", proposal.status
    assert proposal.delivered_at is None and no_confirmation(body)
    assert body["answer"] == (ASKED_AFTER_THE_TAP_1940 if tapped else WITHDRAWN_1940), body["answer"]
    assert desk.store.mutations == []


async def test_the_same_note_on_the_order_he_named_is_his_card(desk):
    """The control: the model notes #1940, as asked. The card stands and names #1940."""
    await _on_1938_with_1940_held(desk, "twice-right")
    desk.model.steps = [notes(B, "1940 goes with the gift box")]
    card = confirmation(await say(desk, "add a note to order 1940: 1940 goes with the gift box", "twice-right"))
    proposal = desk.runtime.actions.find(card["proposal_id"])
    assert proposal.entity_ref == B and proposal.status.value == "PENDING"


async def test_a_refund_whose_reason_repeats_the_order_number_is_held_to_that_order(desk):
    """R9-I-tests5-I-03 on money. "Refund twenty pounds on 1940, the reason is 1940 arrived torn",
    and the model prepares the refund on #1938 with that reason. The reason carries 1940 once; he
    said it twice. The refund is withdrawn before it is shown."""
    await _on_1938_with_1940_held(desk, "refund-twice")
    desk.model.steps = [reads(("shopify_refund_create", {"order_id": A, "amount": "20.00", "reason": "1940 arrived torn"}))]
    body = await say(desk, "refund twenty pounds on 1940, the reason is 1940 arrived torn", "refund-twice")

    proposal = _only(desk, "refund-twice")
    assert proposal.tool_name == "shopify_refund_create" and proposal.entity_ref == A
    assert proposal.status.value == "REVOKED" and proposal.delivered_at is None
    assert no_confirmation(body) and body["answer"] == WITHDRAWN_1940, body["answer"]
    assert desk.store.mutations == []


async def test_with_nothing_tapped_a_note_naming_another_order_is_asked_about_then_lands_where_he_says(desk):
    """With #1938 in front of him and nothing tapped, "add a note: swap it for the one on order
    1940". Round 11 let a note on #1938 stand here, reading 1940 as what the note says. Round 13's
    two independent checks showed the other side of that reading: "can you add a note to order
    1940 saying fragile", copied word for word onto #1938, is the same sentence to any check that
    cannot parse it, and it stood. Which of his numbers is where a note goes is the sentence's
    structure — the model's to read, and exactly what is checked here — so with nothing tapped,
    a change on an order he did not name is withdrawn and he is asked. "On this one" puts it on
    #1938. (After Add a note is tapped on #1938 he is asked the same way: see
    test_after_add_a_note_a_dictation_naming_another_order_is_asked_about_then_placed.)"""
    await _on_1938_with_1940_held(desk, "content-only")
    desk.model.steps = [notes(A, "Swap it for the one on order 1940")]
    body = await say(desk, "add a note: swap it for the one on order 1940", "content-only")
    proposal = _only(desk, "content-only")
    assert proposal.entity_ref == A and proposal.status.value == "REVOKED" and no_confirmation(body)
    assert body["answer"] == WITHDRAWN_1940, body["answer"]

    desk.model.steps = [notes(A, "Swap it for the one on order 1940")]
    card = confirmation(await say(desk, "on this one", "content-only"))
    placed = desk.runtime.actions.find(card["proposal_id"])
    assert placed.entity_ref == A and placed.status.value == "PENDING"


@pytest.mark.parametrize(("said", "note"), [
    ("can you add a note to order 1940 saying fragile", "Add a note to order 1940 saying fragile"),
    ("please add a note to order 1940 saying fragile", "add a note to order 1940 saying fragile"),
    ("can you put a note on order 1940 that she wants it gift wrapped", "note on order 1940 that she wants it gift wrapped"),
    ("right, the parcel for order 1940 came back, stick a note on it", "The parcel for order 1940 came back"),
])
async def test_with_nothing_tapped_his_own_words_copied_onto_the_order_on_screen_do_not_move_where_he_said(desk, said, note):
    """Round 13's second independent check: each of these stood on #1938, the note copying a run
    of his words that carried "order 1940"."""
    sid = f"copied-{abs(hash(said)) % 1000}"
    await _on_1938_with_1940_held(desk, sid)
    desk.model.steps = [notes(A, note)]
    body = await say(desk, said, sid)
    proposal = _only(desk, sid)
    assert proposal.entity_ref == A and proposal.status.value == "REVOKED", (said, proposal.status)
    assert no_confirmation(body) and body["answer"] == WITHDRAWN_1940, body["answer"]
    assert desk.store.mutations == []


async def test_a_number_said_only_in_the_note_does_not_let_the_note_land_on_a_third_order(desk):
    """The same words, and the model notes #1941 — an order he neither named nor is looking at.
    He named an order, only inside the note, and the change is on none he named and not on the
    record he is on: it is withdrawn."""
    desk.store.orders[C] = _order(C, "1941", DANIEL, "Daniel Sear", "daniel@example.com")
    desk.model.steps = [show_order("1941")]
    await say(desk, "show me order 1941", "third")
    await _on_1938_with_1940_held(desk, "third")
    desk.model.steps = [notes(C, "Swap it for the one on order 1940")]
    body = await say(desk, "add a note: swap it for the one on order 1940", "third")

    proposal = _only(desk, "third")
    assert proposal.entity_ref == C and proposal.status.value == "REVOKED" and proposal.delivered_at is None
    assert no_confirmation(body)
    assert body["answer"] == ("You said #1940, but the change I'd prepared was for #1941, so I've withdrawn it. "
                              "Say which order you want it on."), body["answer"]


# ====================== the model's own words cancel nothing (round 13's independent checks)
#
# Round 13 first counted the numbers the change's own words carry against the places he said
# them, then matched his words word for word. The model controls those words: every "1940" it
# copied into a note or a reason cancelled a place where he named #1940 as where the change goes,
# and the change stood on #1938. Now nothing the change writes excuses a number he said.


@pytest.mark.parametrize("reason", ["1940 arrived torn", "Order 1940, it arrived torn", "it arrived torn, order 1940"])
async def test_a_refund_whose_reason_copies_the_order_he_named_is_withdrawn(desk, reason):
    """"Refund twenty pounds on order 1940, it arrived torn", the refund prepared on #1938 with a
    reason that repeats 1940, in the model's words or in his. Before, the reason's 1940 cancelled
    his, and the refund card on #1938 was delivered."""
    sid = f"refund-copies-{abs(hash(reason)) % 1000}"
    await _on_1938_with_1940_held(desk, sid)
    desk.model.steps = [reads(("shopify_refund_create", {"order_id": A, "amount": "20.00", "reason": reason}))]
    body = await say(desk, "refund twenty pounds on order 1940, it arrived torn", sid)

    proposal = _only(desk, sid)
    assert proposal.entity_ref == A and proposal.status.value == "REVOKED", (reason, proposal.status)
    assert proposal.delivered_at is None and no_confirmation(body)
    assert body["answer"] == WITHDRAWN_1940, body["answer"]
    assert desk.store.mutations == []


@pytest.mark.parametrize("note", ["1940: fragile", "Fragile (order 1940)", "Add a note to order 1940 saying fragile",
                                  "order 1940 saying fragile"])
async def test_a_note_that_copies_the_order_he_named_is_withdrawn(desk, note):
    """"Add a note to order 1940 saying fragile", noted on #1938 with 1940 in the note: in the
    model's own words, as his whole request, or as his words starting at the order. None of them
    is something he dictated with 1940 inside it."""
    sid = f"note-copies-{abs(hash(note)) % 1000}"
    await _on_1938_with_1940_held(desk, sid)
    desk.model.steps = [notes(A, note)]
    body = await say(desk, "add a note to order 1940 saying fragile", sid)

    proposal = _only(desk, sid)
    assert proposal.entity_ref == A and proposal.status.value == "REVOKED", (note, proposal.status)
    assert no_confirmation(body) and body["answer"] == WITHDRAWN_1940, body["answer"]


async def test_after_add_a_note_on_1938_a_note_that_is_not_his_words_cannot_carry_1940_onto_it(desk):
    """Add a note tapped on #1938, then "add a note to order 1940 saying fragile", and the model
    notes #1938 with words he did not say. His 1940 is where it goes: withdrawn."""
    await _on_1938_with_1940_held(desk, "tapped-not-his")
    assert (await bind_note(desk, "tapped-not-his", kind="order", ref=A))["ok"] is True
    desk.model.steps = [notes(A, "1940 goes with the gift box")]
    body = await say(desk, "add a note to order 1940 saying fragile", "tapped-not-his")

    proposal = _only(desk, "tapped-not-his")
    assert proposal.entity_ref == A and proposal.status.value == "REVOKED" and no_confirmation(body)


async def test_after_add_a_note_a_dictation_naming_another_order_is_asked_about_then_placed(desk):
    """Add a note tapped on #1938, and he dictates "swap it for the one on order 1940". Round 11
    let the note stand at once, reading 1940 as what the tap made the note say. Round 13's third
    check showed a tap cannot tell that from a redirect either: "no, put it on order 1940,
    fragile", with "order 1940, fragile" noted on #1938, stood the same way. So after a tap too,
    his words naming another order are asked about — neutrally, not as a correction — and "on
    this one" places the note on #1938."""
    await _on_1938_with_1940_held(desk, "tapped-dictation")
    assert (await bind_note(desk, "tapped-dictation", kind="order", ref=A))["ok"] is True
    desk.model.steps = [notes(A, "Swap it for the one on order 1940.")]
    body = await say(desk, "swap it for the one on order 1940", "tapped-dictation")
    proposal = _only(desk, "tapped-dictation")
    assert proposal.entity_ref == A and proposal.status.value == "REVOKED" and no_confirmation(body)
    assert body["answer"] == ASKED_AFTER_THE_TAP_1940, body["answer"]

    desk.model.steps = [notes(A, "Swap it for the one on order 1940.")]
    card = confirmation(await say(desk, "on this one", "tapped-dictation"))
    placed = desk.runtime.actions.find(card["proposal_id"])
    assert placed.entity_ref == A and placed.status.value == "PENDING"


@pytest.mark.parametrize(("said", "note"), [
    ("no, put it on order 1940, fragile", "order 1940, fragile"),
    ("add a note to 1940", "note to 1940"),
])
async def test_after_add_a_note_his_own_words_copied_onto_the_tapped_order_do_not_move_where_he_said(desk, said, note):
    """Round 13's third check: after a tap on #1938, these stood on #1938 with his words copied."""
    sid = f"tapped-copied-{abs(hash(said)) % 1000}"
    await _on_1938_with_1940_held(desk, sid)
    assert (await bind_note(desk, sid, kind="order", ref=A))["ok"] is True
    desk.model.steps = [notes(A, note)]
    body = await say(desk, said, sid)
    proposal = _only(desk, sid)
    assert proposal.entity_ref == A and proposal.status.value == "REVOKED", (said, proposal.status)
    assert no_confirmation(body) and body["answer"] == ASKED_AFTER_THE_TAP_1940, body["answer"]
    assert desk.store.mutations == []


# ============================================ a tapped control binds the record (#14, #15)


async def test_words_after_add_a_note_on_1940_that_name_no_order_cannot_note_1938(desk):
    """R9-D1-D1-02. #1938 is the cursor; Add a note is tapped naming #1940; he says "fragile". The
    binding rode that sentence only as a note to the model, so a model that noted #1938 — the
    order open — gave #1938's card. It is withdrawn now, and he is told what he tapped."""
    await _on_1938_with_1940_held(desk, "bound-b")
    assert (await tap(desk, "voice.bind", "bound-b", family="order.add_note", kind="order", ref=B))["ok"] is True
    desk.model.steps = [notes(A, "Fragile")]
    body = await say(desk, "fragile", "bound-b")

    proposal = _only(desk, "bound-b")
    assert proposal.entity_ref == A and proposal.status.value == "REVOKED" and proposal.delivered_at is None
    assert proposal.reason == "not the record the owner tapped"
    assert no_confirmation(body)
    assert body["answer"] == ("You'd tapped Add a note on #1940, but the change I'd prepared was for #1938, so I've "
                              "withdrawn it. Say which order you want it on."), body["answer"]
    assert desk.runtime.sessions.get("bound-b").branch().voice_target() is None
    assert desk.store.mutations == []


async def test_words_after_add_a_note_on_1940_land_on_1940(desk):
    """The control: the model notes the bound order. The card stands, and the commit sends #1940's
    note and nothing to #1938."""
    await _on_1938_with_1940_held(desk, "bound-b-right")
    assert (await tap(desk, "voice.bind", "bound-b-right", family="order.add_note", kind="order", ref=B))["ok"] is True
    desk.model.steps = [notes(B, "Fragile")]
    card = confirmation(await say(desk, "fragile", "bound-b-right"))
    applied = await test_r11_turn.commit(desk, card["proposal_id"], "bound-b-right")
    assert applied.json()["status"] == "verified", applied.text
    assert [(n, v["id"]) for n, v in desk.store.mutations] == [("order_note_set", B)]


async def test_a_mixed_screen_s_listening_chip_binds_the_cursor_and_a_note_elsewhere_is_withdrawn(desk):
    """R9-D2-D2-04. #1938 and #1940 side by side, the cursor on #1938, and #1938's Add a note —
    the one listening chip — tapped. "Gift wrap it", and the model notes #1940: withdrawn, because
    the tap bound #1938 and the words named nothing else."""
    desk.model.steps = [
        show_order("1938"),
        reads(("shopify_order_detail", {"order_id": A}), ("shopify_find_order", {"query": "1940"}),
              ("shopify_order_detail", {"order_id": found_order})),
    ]
    await say(desk, "show me order 1938", "mixed")
    both = await say(desk, "put 1938 and 1940 side by side", "mixed")
    entity = both["branch"]["entity"]
    assert entity["ref"] == A
    assert (await bind_note(desk, "mixed", kind=entity["kind"], ref=entity["ref"]))["ok"] is True
    desk.model.steps = [notes(B, "Gift wrap it")]
    body = await say(desk, "gift wrap it", "mixed")
    proposal = _only(desk, "mixed")
    assert proposal.entity_ref == B and proposal.status.value == "REVOKED" and no_confirmation(body)
    assert "tapped Add a note on #1938" in body["answer"], body["answer"]


async def test_after_add_a_note_the_order_he_names_still_wins(desk):
    """Unless his own words named another: Add a note bound to #1938, "add a note to order 1940:
    fragile", and the model notes #1940. That is his card."""
    await _on_1938_with_1940_held(desk, "named-wins")
    assert (await bind_note(desk, "named-wins", kind="order", ref=A))["ok"] is True
    desk.model.steps = [notes(B, "Fragile")]
    card = confirmation(await say(desk, "add a note to order 1940: fragile", "named-wins"))
    assert desk.runtime.actions.find(card["proposal_id"]).entity_ref == B


# ------------------------------------------------------------------ the Reply binding (#14)

HER_1938_THREAD = "aa70d3f83dbef06e"     # the golden world's "Order 1938 — can I add to it?"
HER_1912_THREAD = "fe128e8f1ec5a51e"     # "Order 1912 arrived"


@pytest.fixture()
async def world():
    from experience.harness import harness

    async with harness(admitted=True) as h:
        yield h


async def _card_collected(h, order_id: str, session: str) -> None:
    """The model's own read waits only MODEL_BUDGET_S for an order's inbox; on a busy machine its
    threads reach the conversation through the rest of the card, collected as the tablet does."""
    _, extension = await h.enrich(order_id, session_id=session)
    assert extension.get("pending") == [], extension


@pytest.mark.parametrize(("replied_in", "stands"), [(HER_1938_THREAD, False), (HER_1912_THREAD, True)],
                         ids=["another-thread", "the-tapped-thread"])
async def test_a_reply_after_reply_was_tapped_on_one_thread_is_prepared_only_in_that_thread(world, replied_in, stands):
    """R9-D1-D1-02, the Reply binding. Mia has two threads; Reply is tapped on the one about
    #1912 and he says what to tell her. A model that prepares the reply in her OTHER thread is a
    reply in a conversation he did not tap — the wrong subject line, the wrong history under it —
    and it is withdrawn before it is shown. In the thread he tapped, it is his card."""
    sid = f"reply-{replied_in[-4:]}"
    await world.open_order("1938", session_id=sid)
    await _card_collected(world, "gid://shopify/Order/1938", sid)
    bound = await world.touch("voice.bind", session_id=sid, family="email.reply", kind="email_thread", ref=HER_1912_THREAD)
    assert bound.raw.get("ok") is True, bound.raw
    said = await world.ask("tell her it went out this morning",
                           ("gmail_draft_reply", {"thread_id": replied_in, "body": "It went out this morning."}),
                           session_id=sid)
    made = [c for c in said.raw.get("tool_calls") or [] if c.get("name") == "gmail_draft_reply"]
    assert len(made) == 1 and made[0]["ok"] is True, said.raw.get("tool_calls")
    (proposal,) = world.runtime.sessions.get(sid).proposals
    assert proposal.entity_ref == replied_in
    if stands:
        assert proposal.status.value == "PENDING" and said.surface("confirmation"), said.surface_types
    else:
        assert proposal.status.value == "REVOKED" and proposal.delivered_at is None
        assert proposal.reason == "not the record the owner tapped"
        assert not said.surface("confirmation"), said.surface_types
        assert said.answer.startswith("You'd tapped Reply to this"), said.answer
    assert getattr(world.store, "mutations_sent", -1) == 0


PRIYAS_THREAD = "c28cf65d31fe6cbb"        # the golden world's thread from Priya Raman


@pytest.mark.parametrize("tool", ["gmail_draft_new", "gmail_send_new"])
async def test_after_reply_was_tapped_an_order_he_dictates_does_not_send_it_to_that_order_s_customer(world, tool):
    """Round 13's third check. Reply tapped on Priya's email; he dictates "Hi Priya, so sorry,
    David's order 1939 went to you by mistake, we'll swap it", and the model writes a NEW email
    on #1939 — to David, with Priya's name and what happened to her. The Reply binding let an
    order his words named send it elsewhere. Now what is written after a tapped Reply is in the
    tapped thread, or withdrawn."""
    sid = f"reply-new-{tool[-3:]}"
    davids = (await world.open_order("1939", session_id=sid)).data("order")
    await world.open_order("1940", session_id=sid)
    await _card_collected(world, "gid://shopify/Order/1940", sid)
    bound = await world.touch("voice.bind", session_id=sid, family="email.reply", kind="email_thread", ref=PRIYAS_THREAD)
    assert bound.raw.get("ok") is True, bound.raw
    body = "Hi Priya, so sorry, David's order 1939 went to you by mistake, we'll swap it."
    said = await world.ask("reply to her: " + body,
                           (tool, {"order_id": davids["order_id"], "subject": "Your order", "body": body}),
                           session_id=sid)
    (proposal,) = [p for p in world.runtime.sessions.get(sid).proposals if p.tool_name == tool]
    assert proposal.status.value == "REVOKED" and proposal.delivered_at is None, proposal.status
    assert proposal.reason == "not the record the owner tapped"
    assert not said.surface("confirmation"), said.surface_types


@pytest.mark.parametrize("tool", ["gmail_draft_new", "gmail_send_new"])
async def test_a_new_email_is_held_to_the_order_he_named(world, tool):
    """Round 13's fourth check: a new email is written to an order's customer, and was held to no
    order. "Email the customer on order 1940 that it went out", written on #1939, went to David."""
    sid = f"new-order-{tool[-3:]}"
    davids = (await world.open_order("1939", session_id=sid)).data("order")
    await world.open_order("1940", session_id=sid)
    said = await world.ask("email the customer on order 1940 that it went out this morning",
                           (tool, {"order_id": davids["order_id"], "subject": "Your order",
                                   "body": "Your parcel went out this morning with Royal Mail."}), session_id=sid)
    (proposal,) = [p for p in world.runtime.sessions.get(sid).proposals if p.tool_name == tool]
    assert proposal.status.value == "REVOKED" and proposal.reason == "not the order the owner named", proposal.status
    assert not said.surface("confirmation") and said.answer.startswith("You said #1940"), said.answer


@pytest.mark.parametrize("tool", ["gmail_draft_new", "gmail_send_new"])
async def test_a_new_email_is_held_to_the_person_he_named(world, tool):
    """The same check, with nothing tapped: "email Priya: … David's order 1939 went to you by
    mistake", written on #1939 — he named #1939, so the order passed — goes to David, with
    Priya's name and what happened to her."""
    sid = f"new-person-{tool[-3:]}"
    davids = (await world.open_order("1939", session_id=sid)).data("order")
    await world.open_order("1940", session_id=sid)
    body = "Hi Priya, so sorry, David's order 1939 went to you by mistake, we'll swap it."
    said = await world.ask("email Priya: " + body,
                           (tool, {"order_id": davids["order_id"], "subject": "Your order", "body": body}), session_id=sid)
    (proposal,) = [p for p in world.runtime.sessions.get(sid).proposals if p.tool_name == tool]
    assert proposal.status.value == "REVOKED", proposal.status
    assert proposal.reason in ("not the person the owner named", "more than one person named"), proposal.reason
    assert not said.surface("confirmation"), said.surface_types
    assert said.answer.startswith("You named Priya and David"), said.answer


@pytest.mark.parametrize("tool", ["gmail_draft_new", "gmail_send_new"])
async def test_a_new_email_to_someone_he_did_not_name_is_withdrawn(world, tool):
    """He named only Priya, and the email was written on David's order."""
    sid = f"new-other-{tool[-3:]}"
    davids = (await world.open_order("1939", session_id=sid)).data("order")
    await world.open_order("1940", session_id=sid)
    said = await world.ask("email Priya that it went out this morning",
                           (tool, {"order_id": davids["order_id"], "subject": "Your order", "body": "It went out this morning."}),
                           session_id=sid)
    (proposal,) = [p for p in world.runtime.sessions.get(sid).proposals if p.tool_name == tool]
    assert proposal.status.value == "REVOKED" and proposal.reason == "not the person the owner named", proposal.status
    assert not said.surface("confirmation"), said.surface_types


async def test_a_new_email_to_the_person_and_order_he_named_is_his_card(world):
    sid = "new-right"
    await world.open_order("1939", session_id=sid)
    priyas = (await world.open_order("1940", session_id=sid)).data("order")
    said = await world.ask("email Priya that order 1940 went out this morning",
                           ("gmail_draft_new", {"order_id": priyas["order_id"], "subject": "Your order",
                                                "body": "Your order went out this morning."}), session_id=sid)
    (proposal,) = [p for p in world.runtime.sessions.get(sid).proposals if p.tool_name == "gmail_draft_new"]
    assert proposal.status.value == "PENDING" and said.surface("confirmation"), (proposal.status, said.surface_types)


async def test_after_reply_was_tapped_a_note_on_an_order_he_did_not_name_is_withdrawn(world):
    """Round 13's fourth check: under a tapped Reply, an order change was held to nothing."""
    sid = "reply-then-note"
    davids = (await world.open_order("1939", session_id=sid)).data("order")
    await world.open_order("1940", session_id=sid)
    await _card_collected(world, "gid://shopify/Order/1940", sid)
    bound = await world.touch("voice.bind", session_id=sid, family="email.reply", kind="email_thread", ref=PRIYAS_THREAD)
    assert bound.raw.get("ok") is True, bound.raw
    said = await world.ask("tell her it's on its way", ("shopify_order_note_append", {"order_id": davids["order_id"], "note": "On its way"}),
                           session_id=sid)
    notes_made = [p for p in world.runtime.sessions.get(sid).proposals if p.tool_name == "shopify_order_note_append"]
    assert notes_made and all(p.status.value == "REVOKED" for p in notes_made), [p.status for p in notes_made]
    assert notes_made[0].reason == "not the record the owner tapped" and not said.surface("confirmation")


async def test_the_model_is_told_what_was_withdrawn_once_at_the_next_question(desk):
    """Round 13's fourth check: the model's own last answer still said the card was ready, so
    "on this one" was only an answer if it knew the question."""
    await _on_1938_with_1940_held(desk, "told")
    desk.model.steps = [notes(A, "Swap it for the one on order 1940")]
    await say(desk, "add a note: swap it for the one on order 1940", "told")
    desk.model.steps = [notes(A, "Swap it for the one on order 1940")]
    await say(desk, "on this one", "told")
    assert "CLIVE withdrew the change you prepared last time" in desk.model.prompts[-1]
    assert WITHDRAWN_1940 in desk.model.prompts[-1]
    desk.model.steps = [reads()]
    await say(desk, "and its shipping?", "told")
    assert "CLIVE withdrew the change" not in desk.model.prompts[-1], "told once"


# ============================================ a change on a person, held to the person named (#16)


def credits(customer: str, amount: float = 15.0):
    """Claude opening a store credit for this customer and preparing it — whoever was named."""
    async def step(session, calls, text):
        await dispatch("shopify_store_credit", {"customer_id": customer, "amount": amount},
                       session=session, timeout_s=5, calls=calls)
        opened = calls[-1].result or {}
        await dispatch("shopify_store_credit_add", {"workspace_id": opened.get("workspace_id", "")},
                       session=session, timeout_s=5, calls=calls)
        return "The credit is on the card."
    return step


async def _daniel_and_mia_held(desk, sid: str, *, both_mias: bool = False) -> None:
    """Daniel's order, then Mia Kowalski looked up (and, when asked for, every Mia)."""
    desk.model.steps = [show_order("1938"),
                        reads(("shopify_find_customer", {"query": "Mia" if both_mias else "Kowalski"}),
                              ("shopify_customer_history", {"customer_id": found_customer}))]
    await say(desk, "show me order 1938", sid)
    await say(desk, "who's Mia?" if both_mias else "what has Mia Kowalski ordered?", sid)
    held = desk.runtime.sessions.get(sid).issued_ids
    assert {DANIEL, MIA} <= held and (MIA_JONES in held) == both_mias


async def test_store_credit_for_the_person_he_named_is_not_given_to_another(desk):
    """R9-D2-D2-05. Daniel's order and Mia Kowalski both in this conversation. "Give Mia fifteen
    pounds store credit", and the model credits Daniel. Only orders were checked; a change on a
    person never was. Withdrawn before it is shown, and he is told whom it was for."""
    await _daniel_and_mia_held(desk, "credit")
    desk.model.steps = [credits(DANIEL)]
    body = await say(desk, "give Mia fifteen pounds store credit", "credit")

    proposal = _only(desk, "credit")
    assert proposal.entity_kind == "customer" and proposal.entity_ref == DANIEL
    assert proposal.status.value == "REVOKED" and proposal.delivered_at is None
    assert proposal.reason == "not the person the owner named"
    assert no_confirmation(body)
    assert body["answer"] == ("You said Mia, but the change I'd prepared was for Daniel Sear, so I've withdrawn it. "
                              "Say who it's for."), body["answer"]
    assert desk.store.mutations == []


async def test_store_credit_for_the_person_he_named_is_his_card(desk):
    """The control: the model credits Mia Kowalski. A red card, waiting for his hold."""
    await _daniel_and_mia_held(desk, "credit-right")
    desk.model.steps = [credits(MIA)]
    card = confirmation(await say(desk, "give Mia fifteen pounds store credit", "credit-right"))
    proposal = desk.runtime.actions.find(card["proposal_id"])
    assert proposal.entity_ref == MIA and proposal.status.value == "PENDING" and card["risk"] == "red"


async def test_store_credit_for_a_name_two_people_share_is_withdrawn_rather_than_guessed(desk):
    """Two Mias shown in this conversation. "Give Mia fifteen pounds" names either, and the Mac
    cannot tell which: whichever the model chose, the credit is withdrawn and he is asked which."""
    await _daniel_and_mia_held(desk, "two-mias", both_mias=True)
    desk.model.steps = [credits(MIA)]
    body = await say(desk, "give Mia fifteen pounds store credit", "two-mias")
    proposal = _only(desk, "two-mias")
    assert proposal.entity_ref == MIA and proposal.status.value == "REVOKED" and no_confirmation(body)
    assert proposal.reason == "a name two people share"
    assert body["answer"] == ("Mia could be more than one of your customers, so I've withdrawn the change rather "
                              "than guess. Say which one you mean."), body["answer"]


async def test_the_whole_name_settles_which_of_two_people_he_meant(desk):
    await _daniel_and_mia_held(desk, "one-mia", both_mias=True)
    desk.model.steps = [credits(MIA)]
    card = confirmation(await say(desk, "give Mia Kowalski fifteen pounds store credit", "one-mia"))
    assert desk.runtime.actions.find(card["proposal_id"]).entity_ref == MIA


async def test_store_credit_asked_for_without_a_name_is_the_model_s_to_place(desk):
    """Nobody named — "give her fifteen pounds credit" with Mia on screen — and nothing tapped:
    the Mac has nothing to hold the change to, and the card, which names her, is the check."""
    await _daniel_and_mia_held(desk, "no-name")
    desk.model.steps = [credits(MIA)]
    card = confirmation(await say(desk, "give her fifteen pounds credit", "no-name"))
    assert desk.runtime.actions.find(card["proposal_id"]).entity_ref == MIA


def test_what_was_withdrawn_is_told_only_to_the_half_it_happened_in():
    """Round 13's fifth check: the notice was the session's, and the other half's model was told
    about a change it never prepared, while the half it happened in lost it."""
    from types import SimpleNamespace

    from app.routes.turn import _context_lines
    from app.session.models import Session

    session = Session(session_id="halves")
    session.last_withdrawn = {"left": "You said #1940, but the change I'd prepared was for #1938."}
    right = _context_lines(session, "and the other one?", branch=SimpleNamespace(branch_id="right"))
    assert not any("CLIVE withdrew" in line for line in right)
    left = _context_lines(session, "on this one", branch=SimpleNamespace(branch_id="left"))
    assert any("CLIVE withdrew" in line and "#1940" in line for line in left)
    again = _context_lines(session, "and now?", branch=SimpleNamespace(branch_id="left"))
    assert not any("CLIVE withdrew" in line for line in again), "told once"
