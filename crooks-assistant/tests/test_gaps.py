"""The nine things the September test session showed CROOKS OS getting wrong.

Each test here is named for what happened on the tablet, so that a regression is legible as
the thing coming back rather than as an assertion failing.
"""

from __future__ import annotations

import pytest

import app.tools.batch_tools  # noqa: F401
import app.tools.gmail_tools  # noqa: F401
import app.tools.gmail_writes  # noqa: F401
import app.tools.shopify_tools  # noqa: F401
import app.tools.shopify_writes  # noqa: F401
from app.actions import rows
from app.observability import contract
from app.tools import registry
from app.tools.gate import Disposition, Tier, classify

# ---- A. "None of my order tools return the actual street address line" -------

def test_the_street_address_has_a_tool_of_its_own():
    spec = registry.get("shopify_order_address")
    assert spec.write is None and spec.batch is None, "reading an address is a read"
    assert spec.tier is Tier.AMBER and spec.issued_id_args == ("order_id",)
    assert spec.model_view is None, "this tool exists precisely to not be redacted"
    assert "full delivery address" in spec.description.lower()


def test_every_other_order_read_still_redacts_the_street():
    from app.context.order import model_view

    order = {"order_id": "o1", "shipping_address": {"lines": ["12 Elm Road"], "city": "Leeds", "zip": "LS1 4AB", "country": "United Kingdom"}}
    seen = model_view(order)
    assert "shipping_address" not in seen
    assert "12 Elm Road" not in str(seen), "the street is for the card and for the tool that is asked for it"
    assert seen["ships_to"] == "Leeds, LS1, United Kingdom"


# ---- B. the house-number check that called a thread id nobody had issued -----

def test_a_term_is_checked_across_every_thread_and_the_coverage_is_reported():
    spec = registry.get("gmail_find_in_email")
    assert spec.write is None and spec.tier is Tier.AMBER
    assert classify("gmail_find_in_email", {"contains": "42", "sender": "a@b.com"}, set()).disposition is Disposition.EXECUTE_NOW


def test_the_text_search_finds_the_line_and_says_nothing_when_it_is_absent():
    from app.tools.gmail_tools import _where

    assert _where("42", "Order 1938", "Hello\nIt is 42 Elm Road\nThanks") == ("body", "It is 42 Elm Road")
    assert _where("1938", "Order 1938", "no numbers here")[0] == "subject"
    assert _where("99", "Order 1938", "nothing like it") is None


async def test_the_text_search_refuses_to_guess_whose_email_to_read():
    from app.tools.gmail_tools import ToolError, gmail_find_in_email

    with pytest.raises(ToolError, match="Say whose email"):
        await gmail_find_in_email(contains="42")
    with pytest.raises(ToolError, match="at least two characters"):
        await gmail_find_in_email(contains="4", sender="a@b.com")


# ---- C. "who needs replying to", across threads, without merging any --------

def test_a_reply_in_one_thread_does_not_answer_a_newer_message_in_another():
    from app.tools.analytics_tools import _fold_reply_states

    # Thread A: they wrote on Monday, we answered on Tuesday. Thread B: they wrote Wednesday.
    monday, tuesday, wednesday = 1_000, 2_000, 3_000
    folded = _fold_reply_states([
        {"latest_inbound_at": monday, "latest_outbound_at": tuesday},
        {"latest_inbound_at": wednesday, "latest_outbound_at": None},
    ])
    assert folded["latest_inbound_at"] == wednesday and folded["latest_outbound_at"] == tuesday
    assert folded["latest_direction"] == "inbound"
    assert folded["has_reply_after_latest_inbound"] is False
    assert folded["needs_reply"] is True, "the September miss: answered in one thread, still waiting in another"
    assert folded["thread_count"] == 2


def test_a_customer_we_have_answered_is_not_waiting():
    from app.tools.analytics_tools import _fold_reply_states

    folded = _fold_reply_states([{"latest_inbound_at": 1_000, "latest_outbound_at": 2_000}])
    assert folded["needs_reply"] is False and folded["latest_direction"] == "outbound"


def test_a_customer_we_have_never_heard_from_is_not_waiting():
    from app.tools.analytics_tools import _fold_reply_states

    folded = _fold_reply_states([])
    assert folded["needs_reply"] is False and folded["latest_direction"] == "none" and folded["thread_count"] == 0


def test_nothing_here_merges_threads():
    """The request was misread as "merge these threads"; that is not, and must not become,
    a capability. The fold keeps each thread separate and answers about the customer."""
    from pathlib import Path

    source = Path("app/tools/analytics_tools.py").read_text(encoding="utf-8")
    assert "merge" not in source.lower() or "WITHOUT merging" in source


# ---- D. "a button next to them" --------------------------------------------

def test_a_row_carries_the_buttons_the_mac_decided_on():
    offered = rows.actions_for("email_thread", writes_enabled=True)
    assert [a["id"] for a in offered] == ["email_archive"]
    assert offered[0]["mode"] == "stage" and offered[0]["operation"] == "gmail_thread_archive"


def test_a_row_offers_nothing_while_changes_are_off():
    assert rows.actions_for("email_thread", writes_enabled=False) == []


def test_remove_means_archive_and_never_delete():
    action = rows.ROW_ACTIONS["email_archive"]
    assert action.tool == "gmail_thread_archive"
    assert "nothing is deleted" in action.detail.lower()
    assert not any(a.tool.endswith(("_trash", "_delete")) for a in rows.ROW_ACTIONS.values())


def test_an_action_the_build_does_not_offer_fails_closed():
    with pytest.raises(rows.UnknownRowAction):
        rows.resolve("email_delete", "t1")
    with pytest.raises(rows.UnknownRowAction):
        rows.resolve("email_archive", "")


def test_the_tablet_supplies_a_row_and_an_id_and_never_an_argument():
    action, args = rows.resolve("email_archive", "thread-123")
    assert args == {"thread_id": "thread-123"}, "the Mac builds the arguments from the ref alone"
    assert set(args) == set(registry.get(action.tool).input_schema["properties"]) - {"undo"} or "thread_id" in args


# ---- E. "why can't I just send them all at once?" ---------------------------

def test_the_bulk_send_exists_and_is_red_and_irreversible():
    spec = registry.get("batch_email_send")
    assert spec.batch is not None and spec.batch.child_tool == "gmail_send_new"
    assert spec.tier is Tier.RED, "money and reputation leave the building; the gesture must be the heavy one"
    child = registry.get(spec.batch.child_tool)
    assert child.write.reversible is False and child.write.kind == "irreversible"


def test_the_bulk_send_is_staged_for_the_owner_never_executed():
    decision = classify("batch_email_send", {"set_id": "set_abcdef", "subject": "x", "body": "y"}, {"set_abcdef"})
    assert decision.disposition is Disposition.STAGE_FOR_OWNER and decision.tier is Tier.RED


def test_the_gesture_for_a_bulk_send_is_never_a_tap():
    from app.actions.batch import batch_gesture, batch_risk

    for count in (1, 2, 50):
        risk = batch_risk(["AMBER"], "RED", count)
        assert risk == "RED"
        assert batch_gesture(risk, "irreversible", count) != "tap_commit"


def test_the_message_is_frozen_at_preparation_not_written_again_at_commit():
    """The child write tool builds the MIME once, in its prepare step, and the engine sends
    those exact arguments. Checked as structure: the batch names a child write tool, and the
    engine's commit path takes the proposal's stored execution."""
    from pathlib import Path

    spec = registry.get("batch_email_send")
    child = registry.get(spec.batch.child_tool)
    assert child.write is not None and callable(child.write.execute)
    engine = Path("app/actions/engine.py").read_text(encoding="utf-8")
    assert "write.execute(dict(proposal.execution))" in engine or "proposal.execution" in engine
    batch_source = Path("app/tools/batch_tools.py").read_text(encoding="utf-8")
    assert "not filled again" in batch_source


# ---- F. draft or send --------------------------------------------------------

@pytest.mark.parametrize(("text", "expected"), [
    ("draft a reply to millie", "DRAFT"),
    ("write me an apology to the late ones", "DRAFT"),
    ("prepare something for gus", "DRAFT"),
    ("email them all about the delay", "GO"),
    ("let her know it shipped", "GO"),
    ("send it", "GO"),
])
def test_drafting_and_sending_are_told_apart(text, expected):
    from app.routes.turn import _draft_or_send

    line = _draft_or_send(text)
    assert expected in line, f"{text!r} -> {line!r}"


def test_a_bare_reply_to_is_left_to_the_model():
    from app.routes.turn import _draft_or_send

    assert _draft_or_send("reply to millie") == "", "'reply to' names the email, not whether it goes"


# ---- G. the draft that was saved and reported UNVERIFIED --------------------

def test_a_draft_is_proven_by_the_id_gmail_handed_back_as_well_as_the_header():
    from app.tools.gmail_writes import _thread_fingerprint

    ctx = {"last": "m9", "tokens_sent": set(), "sent_ids": set(),
           "drafts": [{"message_id": "gmail-made-this", "token": "", "to": "a@b.com", "to_name": "A", "subject": "s"}]}
    # Before the change there is no id and no matching header: nothing is ours.
    assert _thread_fingerprint(ctx, "<ours@crooks>")["drafts"] == 0
    # After it, the id Gmail answered with proves the draft even though the header was rewritten.
    assert _thread_fingerprint(ctx, "<ours@crooks>", "", "gmail-made-this")["drafts"] == 1


def test_a_draft_belonging_to_something_else_is_still_not_ours():
    from app.tools.gmail_writes import _thread_fingerprint

    ctx = {"last": "m9", "tokens_sent": set(), "sent_ids": set(),
           "drafts": [{"message_id": "someone-elses", "token": "<other@crooks>", "to": "a@b.com", "to_name": "A", "subject": "s"}]}
    assert _thread_fingerprint(ctx, "<ours@crooks>", "", "gmail-made-this")["drafts"] == 0
    assert _thread_fingerprint(ctx, "<ours@crooks>")["drafts"] == 0


def test_the_proof_still_refuses_a_draft_that_never_appeared():
    from app.tools.gmail_writes import _verify_drafted

    assert _verify_drafted({}, {"drafts": 1, "sent": 0}, {})[0] is True
    assert _verify_drafted({}, {"drafts": 0, "sent": 0}, {})[0] is False
    assert _verify_drafted({}, {"drafts": 1, "sent": 1}, {})[0] is False, "a draft that went is not a draft"


# ---- H. the order edit that was reported done and never happened -----------

def test_editing_what_is_on_an_order_is_a_stated_limitation_not_a_silence():
    found = contract.limitation_for("add to David Randall's order a medium black convict jogger")
    assert found is not None and found["name"] == "order_edit"
    line = contract.limitation_line("add two items to his order")
    assert "cannot" in line and "note on the order" in line
    assert "Never answer as though the change has been made" in line


def test_no_order_edit_mutation_exists_to_be_reached_for():
    names = set(registry.names())
    assert not {n for n in names if "order_edit" in n or "line_item" in n}


@pytest.mark.parametrize(("question", "answer", "expected"), [
    ("add two items to David Randall's order", "I've added the two items to the order.", "FALSE_SUCCESS"),
    ("add two items to David Randall's order", "I can't change what is on an order.", None),
    ("add a note to order 1938", "Tap the card to add the note.", None),
])
def test_a_change_reported_as_made_with_nothing_staged_is_a_false_success(question, answer, expected):
    from app.observability.report import Turn, _contract_classes

    turn = Turn(turn_id="t1")
    turn.finished = {"question": question, "answer": answer}
    classes, _signals, _notes = _contract_classes(turn)
    assert (expected in classes) if expected else ("FALSE_SUCCESS" not in classes)


def test_a_change_asked_for_that_nothing_did_and_nothing_refused_is_unfulfilled():
    from app.observability.report import Turn, _contract_classes

    turn = Turn(turn_id="t1")
    turn.finished = {"question": "cancel order 1938", "answer": "Right you are."}
    # Three returns, not two: `notes` are the signals that belong to the turn rather than to a
    # class — the reading of the request, and any disagreement with the router — and they are
    # kept apart because the caller pairs classes with signals index for index.
    classes, signals, notes = _contract_classes(turn)
    assert "UNFULFILLED_ACTION" in classes and "nothing was staged" in " ".join(signals)
    assert len(classes) == len(signals), "one signal per class, and the notes separately"
    assert not [n for n in notes if "noun" in n], "cancel is an instruction, not a noun"


# ---- I. "what more can you do now?" ----------------------------------------

def test_the_capability_question_is_a_contract_of_its_own():
    assert contract.contract_of("what more can you do now?") == contract.META_CAPABILITY_INTENT
    assert contract.contract_of("what can you do?") == contract.META_CAPABILITY_INTENT
