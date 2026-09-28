"""What the removed fast lane used to refuse, held again on the path every sentence now takes.

The 2026-09-28 deploy review, round 9, I-tests3 I-03. Four sets of refusals went with the
word-matching lane and its tests: a tab sentence about an order other than the one on screen
must not move the screen (`test_navigation_extras`), "the other half" must not move focus when
there is nothing unambiguous to move to or the other half is closed (same file), a spoken
cancel or refund must not be something the lane could answer (`test_order_create`), and "who
needs a reply?" must not be refused as a request for a change (`test_needs_reply_routing`).
None of it is restored by bringing the lane back. What is asserted instead is the turn itself,
through `POST /turn` on an admitted harness:

* no sentence moves a tab, a record or a half before the model has been asked — and an
  unscripted model that calls nothing leaves all three exactly where they were;
* when the model DOES read the other order, what is drawn is that order's own record under its
  own number — never the open order's card moved to a tab. Nothing the model can call moves a
  tab or the focus: `commands.run` is reached only from the tap route (app/routes/command.py)
  and the focus only from the branch routes (app/routes/branches.py);
* a cancel the model reaches for comes back as a card held to the graver gesture, a spoken yes
  does not apply it, and nothing reaches the shop;
* a question about who is waiting on a reply reaches the model as a question: nothing in front
  of it refuses it, stages anything, or tells the model it asks for an email to be drafted or
  sent.

The touch half of the closed-half rule is `tests/test_split_workspaces.py::
test_a_closed_half_cannot_be_shown`.
"""

from __future__ import annotations

import pytest

from experience.fixtures import world
from experience.harness import TABLET_HEADERS, harness, order_reads

MIA_ORDER = world.order("1938").order_id


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        yield h


async def test_a_tab_sentence_about_another_order_moves_nothing_before_the_model(stage):
    await stage.open_order("1938", session_id="tabs")
    branch = stage.branch("tabs")
    tab, entity = branch.tab, dict(branch.entity or {})
    said = await stage.say("show me the shipping on 1936", session_id="tabs")
    assert said.lane == "NORMAL" and said.model_calls == 1, "a sentence is the model's, asked once"
    assert stage.branch("tabs").tab == tab, "the tab was moved by words about another order"
    assert (stage.branch("tabs").entity or {}).get("ref") == entity.get("ref") == MIA_ORDER
    assert not said.surfaces, "nothing was drawn for the other order without a read"


async def test_what_the_model_reads_for_another_order_is_drawn_as_that_order(stage):
    """The model does what the lane refused to guess at: it finds 1936 and reads it. What is
    drawn is 1936's own card, numbered 1936, and the half moves to 1936 because that is what
    was read — while 1938 keeps the tab it was left on. The lane's failure was the other way
    round: 1938's card moved to its shipping tab, confidently, for a question about 1936."""
    await stage.open_order("1938", session_id="tabs2")
    kept = dict(stage.branch("tabs2").tabs)
    other = world.order("1936")
    said = await stage.ask("show me the shipping on 1936", *order_reads("1936"),
                           reply="That's 1936 — the address is on the card.", session_id="tabs2")
    assert said.model_calls == 1 and said.scripted == ["shopify_find_order", "shopify_order_detail"]
    orders = [item for item in said.surfaces if item.get("type") == "order"]
    assert orders and all((item.get("data") or {}).get("order_number") == "#1936" for item in orders), \
        [(item.get("data") or {}).get("order_number") for item in orders]
    assert (stage.branch("tabs2").entity or {}).get("ref") == other.order_id
    assert {k: v for k, v in stage.branch("tabs2").tabs.items() if MIA_ORDER in k} == \
        {k: v for k, v in kept.items() if MIA_ORDER in k}, "1938's own tab was not moved"


async def test_the_other_half_said_out_loud_moves_no_focus(stage):
    await stage.open_order("1938", session_id="halves")
    session = stage.runtime.sessions.get("halves")
    focused = session.focused_branch
    for sentence in ("the other half", "switch to the other half"):
        said = await stage.say(sentence, session_id="halves")
        assert said.model_calls == 1
        assert session.focused_branch == focused, f"{sentence!r} moved the focus with nothing to move to"
    # Two halves, one closed: still nothing moves on words.
    forked = await stage.client.post("/branches/fork", data={"session_id": "halves"}, headers=TABLET_HEADERS)
    other = forked.json()["branch_id"]
    session.branches[other].status = "MERGED"
    session.focused_branch = focused
    await stage.say("the other half", session_id="halves")
    assert session.focused_branch == focused


@pytest.mark.parametrize(("said", "tool", "args"), [
    # A refund is the same engine and the same gesture; the fixture shop cannot price one
    # (it has no answer for Shopify's suggested-refund read), so it is held at the tool in
    # tests/test_refund.py, where a fake store can.
    ("cancel order 1938", "shopify_order_cancel", {"reason": "customer"}),
    ("cancel that order, the customer changed their mind", "shopify_order_cancel", {"reason": "customer", "staff_note": "Changed their mind."}),
])
async def test_a_spoken_cancel_is_a_held_card_that_a_spoken_yes_cannot_apply(stage, said, tool, args):
    session_id = f"cancel{len(said)}"
    await stage.open_order("1938", session_id=session_id)
    asked = await stage.ask(said, ("shopify_find_order", {"query": "1938"}),
                            (tool, lambda calls: {"order_id": MIA_ORDER, **args}),
                            reply="It's on the card — hold it if you want it done.", session_id=session_id)
    assert asked.model_calls == 1
    card = asked.data("confirmation")
    assert card.get("status") == "pending" and card.get("risk") == "red", card
    assert (card.get("interaction") or {}).get("kind") not in (None, "", "tap_commit"), "a graver gesture than a tap"
    conversation = stage.runtime.sessions.get(session_id)
    (proposal,) = [p for p in conversation.proposals if p.tool_name == tool]
    yes = await stage.say("yes", session_id=session_id)
    assert yes.model_calls == 0, "a bare yes is answered by the Mac, never by a model that could act on it"
    assert proposal.status.value == "PENDING" and proposal.executed_at is None
    assert getattr(stage.store, "mutations_sent", -1) == 0, "nothing reached the shop"


# The ways of asking who is waiting that the word-matching router once refused as a change
# (tests/test_needs_reply_routing.py holds them against the report's contract).
WHO_IS_WAITING = ("any customers who need a reply", "customers who need a reply?", "is anyone waiting on me",
                  "who needs a reply")


@pytest.mark.parametrize("said", WHO_IS_WAITING)
async def test_asking_who_is_waiting_on_a_reply_is_a_question_to_the_model(stage, said):
    session_id = f"reply{len(said)}"
    asked = await stage.say(said, session_id=session_id)
    assert asked.status == 200 and asked.model_calls == 1 and asked.lane == "NORMAL", "a model turn, not refused"
    prompt = stage.provider.calls[-1]
    assert "This asks for a DRAFT" not in prompt and "This asks for the email to GO" not in prompt, \
        "the Mac told the model a question was a request to write"
    assert not stage.runtime.sessions.get(session_id).proposals, "nothing was staged for a question"
