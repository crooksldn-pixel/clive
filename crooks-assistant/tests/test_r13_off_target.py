"""Where a change goes, held to what the owner said and what he tapped (the round-12 deploy
review of 361b0138, RC-4a).

Every sentence is the model's (the owner's decision of 28 September 2026). What these hold is the
check that runs AFTER the model, on what it did (`app/routes/turn.py` `_off_target`):

* a number the owner said outside the change's own written content is where the change goes,
  counted place by place rather than subtracted as a set, so "add a note to order 1940: 1940 goes
  with the gift box" still names #1940 as where it goes (S2a-01, R9-I-tests2-I-01,
  R9-I-tests5-I-03);
* a change made under a tapped control — Add a note, Reply — lands on the record the tap bound,
  unless his own words named another (R9-D1-D1-02, R9-D2-D2-04);
* a change on a person — store credit — goes only to the person he named, and not at all when
  the name he said is two people's (R9-D2-D2-05).

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
    assert body["answer"] == WITHDRAWN_1940, body["answer"]
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


async def test_a_number_said_only_in_the_note_does_not_move_the_note_off_the_order_he_is_on(desk):
    """What must not get worse (the round-11 independent check): with #1938 in front of him and
    nothing tapped, "add a note: swap it for the one on order 1940" names #1940 only as what the
    note says. A model that notes #1938, the order he is looking at, gives #1938's card."""
    await _on_1938_with_1940_held(desk, "content-only")
    desk.model.steps = [notes(A, "Swap it for the one on order 1940")]
    card = confirmation(await say(desk, "add a note: swap it for the one on order 1940", "content-only"))
    assert desk.runtime.actions.find(card["proposal_id"]).entity_ref == A


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


@pytest.mark.parametrize(("replied_in", "stands"), [(HER_1938_THREAD, False), (HER_1912_THREAD, True)],
                         ids=["another-thread", "the-tapped-thread"])
async def test_a_reply_after_reply_was_tapped_on_one_thread_is_prepared_only_in_that_thread(world, replied_in, stands):
    """R9-D1-D1-02, the Reply binding. Mia has two threads; Reply is tapped on the one about
    #1912 and he says what to tell her. A model that prepares the reply in her OTHER thread is a
    reply in a conversation he did not tap — the wrong subject line, the wrong history under it —
    and it is withdrawn before it is shown. In the thread he tapped, it is his card."""
    sid = f"reply-{replied_in[-4:]}"
    await world.open_order("1938", session_id=sid)
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
