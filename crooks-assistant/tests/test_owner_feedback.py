"""What the owner says about the product, while he is testing it (§16).

Twice in the live hour:

    "please log that your split function is broken. It just shows two of the same thing, and
     the applying button is also broken"
    → "I've no tool for logging a product bug like that."

    "Log--a lot of your functions are broken… especially with the back button, back to
     assistant button and the next button"
    → "I still have no tool that logs product feedback."

Both sentences are in this file. They are recognised, and `feedback.record` writes one down
against the screen he was on for the report to surface verbatim (tests/test_experience_analyser.py
holds that half). Since the word-matching lane was removed (28 September 2026) a spoken report
is a model turn; `feedback.at_turn` records it at turn time, before the model answers, and tells
the model what it did (tests/test_owner_feedback_turn.py holds that, and the report's read-back
from the transcript remains the safety net).

The other half of the file is the bound: nothing reaches Shopify or Gmail, nothing is
proposed, approved or armed, no customer's name or address is written down, and outside a
test session nothing is recorded at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.observability import feedback, timeline
from app.observability.session import TestSessions

# The two sentences, as the tablet heard them.
SPLIT_BUG = ("Okay, uh, please log that your split function is broken. It just so shows two of "
             "the same thing, and the applying button is also broken, and it just is a "
             "continuous applying animation")
REGRESSIONS = ("Log--a lot of your functions are broken or halfway there. It seems as if they've "
               "regressed, um, especially with the back button, back to assistant button and the "
               "next button.")


class FakeBranch:
    """A half of the conversation, as much of one as this needs."""

    def __init__(self) -> None:
        self.branch_id = "br_left"
        self.status = "ACTIVE"
        self.tab = "shipping"
        self.entity = {"kind": "email_thread", "ref": "aa70d3f83dbef06e", "label": "Anna Example"}
        self.recent_entities = [{"kind": "order", "ref": "gid://shopify/Order/1938", "label": "#1938"}]
        self.last_ui = [{"type": "email_thread", "data": {}}, {"type": "confirmation", "data": {}}]


@pytest.fixture()
def recording(tmp_path, monkeypatch):
    """A test session, running, writing to a temporary directory."""
    store = TestSessions(Path(tmp_path))
    line = timeline.install(timeline.Timeline(store))
    session = line.start("the live hour")
    yield line, store, session
    line.stop()
    timeline.install(timeline.NullTimeline())


def _events(store, session) -> list[dict]:
    path = store.timeline_path(session)
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


# ------------------------------------------------------------------- what is recognised


@pytest.mark.parametrize(("said", "kind"), [
    (SPLIT_BUG, "log"),
    (REGRESSIONS, "log"),
    ("please log that the applying button never stops", "log"),
    ("note that the split shows two of the same thing", "note"),
    ("note this bug: home does nothing", "note"),
    ("record that the next button does nothing", "record"),
    ("write that down, back is broken", "record"),
    ("save this as a test", "save_as_test"),
    ("turn that into a test", "save_as_test"),
    ("the back button is broken", "broken"),
    ("the split doesn't work at all", "broken"),
    ("that's a bug", "broken"),
])
def test_the_sentences_a_tester_uses_are_recognised(said, kind):
    got = feedback.recognise(said)
    assert got is not None, said
    assert got.kind == kind, (said, got.kind)
    assert got.text.startswith(said.split(".")[0][:20])


@pytest.mark.parametrize("said", [
    "log in to shopify",
    "the log says the token expired",
    "the order is wrong",
    "that customer's address is broken",
    "the delivery is broken",
    "show me today's orders",
    "refund the postage on 1938",
    "",
])
def test_a_sentence_about_the_shop_is_not_a_bug_report(said):
    """"The order is wrong" is a job. "The back button is broken" is a defect. A rule that
    could not tell them apart would turn every complaint about a parcel into a bug."""
    assert feedback.recognise(said) is None, said


# ------------------------------------------------------- D-12: said plainly, without "log"


@pytest.mark.parametrize(("said", "kind"), [
    # The one that was missed, verbatim from 20:16:48. He said it plainly, was not recorded,
    # and had to repeat it sixteen seconds later starting with the word "log".
    ("Logical error here. You just pulled up two Rowan screens for no reason", "wrong"),
    # The loudest negative signal of the evening, 23:08:27, which reached the report only as
    # an unrouted "other" request with an STT_ERROR beside it.
    ("What is it? What... There is just bullshit Yo, uh, what, why is there bullshit on the "
     "screen right now?", "why_is_it"),
    # What the acceptance script's step 9 asks him to say.
    ("that's wrong, it's showing me two of the same thing", "wrong"),
    ("that's not what I asked for", "wrong"),
    ("You just pulled up two in the same UI", "did_the_wrong_thing"),
    ("it showed me somebody else", "did_the_wrong_thing"),
    ("why can't I press anything", "why_is_it"),
    ("why is nothing happening", "why_is_it"),
])
def test_a_defect_stated_plainly_is_recorded_without_the_magic_word(said, kind):
    """D-12. BEFORE: the family keyed on log / record / note / broken, so "logical error here,
    you just pulled up two screens for no reason" was filed as an unrouted 'orders' request and
    nothing wrote it down. He had to say it twice, the second time with the word "log" in
    front.

    NOW: a defect report is recognised by its shape — a statement that the system did something
    wrong — and none of these contains an instruction to record anything.
    """
    got = feedback.recognise(said)
    assert got is not None, said
    assert got.kind == kind, (said, got.kind)
    assert got.text, said



@pytest.mark.parametrize("said", ["what is it doing?", "What is it doing?",
                                  "what is this doing", "what is this?", "what is on this screen?"])
def test_a_question_the_product_can_answer_is_not_filed_as_a_complaint(said):
    """The D-11/D-12 boundary, in the one place the two workstreams collided.

    `what is (?:it|this) doing` was an alternative in the `why_is_it` shape. It was the only
    one there that is not a "why", and it is step 7 of the physical acceptance script: a
    question about what is on the glass. When recognised feedback took a turn before anything
    else did, the shape won: the owner asked what was in front of him and was told his
    complaint had been recorded.

    The rule this pins: BOTH readings of that sentence are fair, and the tie-break is that one
    of them can be ANSWERED. A product able to say what is on its own glass should say it.

    The other half of the boundary is `test_a_defect_stated_plainly_is_recorded_without_the_magic_word`
    above, which still holds every genuine complaint including the owner's own "why is there
    bullshit on the screen right now?" — so this test cannot be satisfied by narrowing the
    shapes generally, only by narrowing this one alternative.
    """
    assert feedback.recognise(said) is None, said


@pytest.mark.parametrize("said", [
    # Approval, from the same session. 23:11:44 and 23:06:34.
    "Is that not nice? It's actually like",
    "I actually like",
    # What step 9 of the acceptance script asks him to say next, which must NOT be filed.
    "that's quite good actually",
    "that's better",
    "perfect, thank you",
    "yes, that's it",
    # Not about the product at all, all from the same evening.
    "Hi",
    "Crooks OS",
    "Are you working right now?",
    "Stop",
    "White",
    "Broad",
    # Ordinary work.
    "Has anyone bought today that has bought before?",
    "Pull up Rowan's orders",
    "how many orders today?",
    "ignore all of that, ignore all of that",
    # A complaint about the SHOP, in the new shapes' own words.
    "that's the wrong address",
    "you sent the wrong order",
])
def test_conversation_and_approval_are_never_filed_as_defects(said):
    """The bound on D-12, and the reason it is conservative. A tester whose compliments are
    filed as bug reports stops trusting the record, so the shape rules have to fail every one
    of these — and half of them are sentences the owner actually said on 11 September.

    The three tests a stated defect has to pass, and an imperative does not: it must not be
    about the shop, it must not be approval, and it must not be a greeting or a check that the
    thing is awake.
    """
    assert feedback.recognise(said) is None, said


def test_the_boundary_the_shop_test_draws_and_what_it_costs():
    """Where the conservative rule is known to under-capture, written down rather than left to
    be rediscovered.

    "This is the wrong customer" is, in the 11 September session, a report of the worst defect
    of the evening (D-14: it answered about somebody else). The shop test blocks it, because
    the identical sentence about an order the shop got wrong is a job and not a bug. The shape
    rules choose to miss this one rather than file every complaint about a parcel as a defect,
    and one word from the owner — "log", "note", any imperative — recovers it.
    """
    assert feedback.recognise("this is the wrong customer") is None
    assert feedback.recognise("log that this is the wrong customer") is not None
    # And the same defect said about the SCREEN rather than about the record is captured.
    assert feedback.recognise("you just pulled up the wrong one") is not None


def test_an_imperative_still_skips_the_conservative_tests():
    """The oracle that stops the rule above from swallowing real feedback: a man who says "log
    that" has already said what he wants done with it, so none of the three extra tests applies
    to him. "Log that the order is wrong" is about the shop AND is feedback."""
    assert feedback.recognise("log that the refund did not go through") is not None
    assert feedback.recognise("note that the address field is quite good but wrong") is not None
    # And the same sentence WITHOUT the imperative is about the shop, so it is not filed.
    assert feedback.recognise("the refund did not go through") is None


# ------------------------------------------------------------------------ what is written


def test_the_feedback_is_appended_with_the_screen_the_owner_was_on(recording):
    line, store, session = recording
    event = feedback.record(feedback.recognise(SPLIT_BUG), branch=FakeBranch(),
                            session_id="s1", turn_id="turn_7afa465dda1d")
    assert event is not None
    line.flush()

    written = [e for e in _events(store, session) if e["kind"] == "owner_feedback"]
    assert len(written) == 1
    got = written[0]
    # Timestamp, branch, visible screen, entity refs, the words, and the ids nearby.
    assert got["ts"] > 0 and got["iso"]
    assert got["branch_id"] == "br_left" and got["branch_status"] == "ACTIVE"
    assert got["turn_id"] == "turn_7afa465dda1d" and got["session_id"] == "s1"
    assert got["kind"] == "owner_feedback" and got["shape"] == "log"
    assert got["text"].startswith("Okay, uh, please log that")
    assert got["screen"] == ["email_thread", "confirmation"]
    assert {"kind": "email_thread", "ref": "aa70d3f83dbef06e"} in got["entities"]
    assert {"kind": "order", "ref": "gid://shopify/Order/1938"} in got["entities"]
    assert got["tab"] == "shipping"


def test_the_words_are_kept_verbatim_and_the_labels_are_not(recording):
    """The owner's own words about his own product, as he said them — that is what the report
    prints. Everything AROUND them is an id: no customer's name, no address, no label."""
    line, store, session = recording
    feedback.record(feedback.recognise(REGRESSIONS), branch=FakeBranch(), session_id="s1")
    line.flush()
    got = next(e for e in _events(store, session) if e["kind"] == "owner_feedback")

    assert got["text"] == " ".join(REGRESSIONS.split())
    blob = json.dumps(got)
    assert "Anna Example" not in blob and "#1938" not in blob, "labels are not ids"
    for entity in got["entities"]:
        assert set(entity) == {"kind", "ref"}


def test_the_ids_of_what_was_happening_nearby_travel_with_it(recording):
    """"The applying button is broken" is worth far more with the ids of the taps and the
    changes either side of it."""
    line, store, session = recording
    timeline.emit("command", session_id="s1", branch_id="br_left", command="navigation.home", ok=True, ms=0.2)
    timeline.emit("action_verified", session_id="s1", proposal_id="prop_037e20c6ea04",
                  operation="gmail_send_reply", status="VERIFIED", verified=True)
    timeline.emit("tablet_reconcile", source="tablet", session_id="s1", reason="turn", count=2, kept=2)
    # Something that is not a correlation worth keeping.
    timeline.emit("tablet_scroll", source="tablet", session_id="s1", depth=1400)

    feedback.record(feedback.recognise(SPLIT_BUG), branch=FakeBranch(), session_id="s1")
    line.flush()
    got = next(e for e in _events(store, session) if e["kind"] == "owner_feedback")
    kinds = [row["kind"] for row in got["nearby"]]
    assert "command" in kinds and "action_verified" in kinds and "tablet_reconcile" in kinds
    assert "tablet_scroll" not in kinds, "a scroll is not what somebody was doing"
    ids = [row["id"] for row in got["nearby"]]
    assert "prop_037e20c6ea04" in ids and "navigation.home" in ids


def test_a_stale_command_is_not_reported_as_nearby(recording):
    line, _store, _session = recording
    timeline.emit("command", session_id="s1", command="navigation.home", ok=True, ts=1_000.0)
    assert line.recent(within_s=90.0, now=1_000_000.0) == []
    assert [r["id"] for r in line.recent(within_s=90.0, now=1_000.5)] == ["navigation.home"]


def test_nothing_is_recorded_when_no_session_is_being_tested():
    """On an ordinary day there is nowhere to put this, and the honest answer is the one the
    assistant already gives."""
    timeline.install(timeline.NullTimeline())
    assert feedback.active() is False
    assert feedback.record(feedback.recognise(SPLIT_BUG), branch=FakeBranch()) is None


# ------------------------------------------------------------ what it cannot possibly do


def test_recording_feedback_reaches_neither_shopify_nor_gmail_nor_the_engine():
    """A bug report is not a change. This module imports no tool, no client and no part of
    the action engine, and nothing in it can arm or commit."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(feedback))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    for module in imported:
        assert not module.startswith(("app.actions", "app.tools", "app.clients", "app.providers")), module
    assert imported <= {"__future__", "re", "dataclasses", "typing", "app.observability"}
