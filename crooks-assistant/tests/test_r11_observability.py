"""The report and what it reads (the 2026-09-28 deploy review, round 10, answered in round 11):

- R9-F-observability1-F-03 and O2-F-02: "Give Alice £15 of store credit" held no mutation word —
  "give" fetches, as in "give me the sales" — so it was graded a read and never set against the
  store-credit family that carried it out. A grant of credit is a change now; a question about a
  balance is still a read.
- R9-F-observability2-F-OBS2-01: the rules in visible.py wrote a page's own values — the field the
  keyboard left (`tablet_focus.name`), why (`cause`), a control's name — into findings, and so into
  the report's tables. What a page sent leaves visible.py only as an identifier.
- O2-F-01: "Show me the log for order #1938" matched the bare `log` rule and was recorded as a
  defect. A log is an instruction only at the head of a sentence or with what to log after it.
- R9-F-observability1-F-02: the mark on the ask bar's live words is kept in a screen copy and its
  value never is.
- R9-E-families1-E-03: a defect said through POST /turn during a test session is an owner_feedback
  event against that turn, and the report prints it among those RECORDED, in his words.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.observability import contract, feedback, semantics, timeline, visible
from app.observability.report import _spoken_capability, build_report, reconstruct
from app.observability.screens import sanitise_markup
from app.observability.session import TestSessions
from app.observability.timeline import read_events
from tests.fake_credentials import shopify_token

# ------------------------------------------------------------------ store credit (F-03, O2-F-02)

GRANTS = [
    "Give Alice £15 of store credit",
    "Please give her fifteen pounds store credit",
    "Give Alice store credit",
    "Issue Alice a £20 gift card",
    "Credit Alice's account with £15",
    "Top up Alice's store credit by £10",
    "Add £15 store credit to Alice",
]
BALANCE_QUESTIONS = [
    "How much store credit does Alice have?",
    "What's Alice's store credit balance?",
    "Give me Alice's store credit balance",
    "Show me Alice's store credit",
    "Does Alice have any store credit left?",
    "Tell me her store credit balance",
    "Has Alice used her store credit?",
    "What's the balance on her gift card?",
    "Show me the gift cards",
]


@pytest.mark.parametrize("said", GRANTS)
def test_a_grant_of_store_credit_is_a_change_to_the_contract_and_to_the_semantic_verdict(said):
    assert contract.contract_of(said) == contract.WRITE_INTENT, said
    verdict = semantics.read_request(said)
    assert verdict.mutation and verdict.change is not None and verdict.change.key == "store_credit", verdict.as_dict()
    assert verdict.change.capability == "store_credit"


@pytest.mark.parametrize("said", BALANCE_QUESTIONS)
def test_a_question_about_store_credit_is_still_a_read(said):
    assert contract.contract_of(said) == contract.READ_INTENT, said
    verdict = semantics.read_request(said)
    assert not verdict.mutation and verdict.change is None, verdict.as_dict()


def test_give_still_fetches_when_what_it_gives_is_not_credit():
    for said in ("give me the sales", "give me today's orders", "give her a call", "give me a gift card report"):
        assert not contract.grants_credit(tuple(said.lower().split())), said
    assert contract.contract_of("give me the sales") == contract.READ_INTENT


def _store_credit_turn(tmp_path: Path, said: str) -> Path:
    """A store-credit request as a turn is written today: no router `lane` event (the word-matching
    router is gone), the model staging the change, and the owner's hold applying and proving it."""
    from tests.test_analyser import Tape, _finished, _tool, _turn

    tape = Tape("ts-20260928-120000-credit")
    t = _turn(tape, "turn_credit", said=said, input_="text")
    _tool(tape, t, "shopify_store_credit_add", outcome="staged", result={"proposal_id": "prop_credit"})
    tape.add("action_commit", session_id="s1", turn_id=t, proposal_id="prop_credit", operation="store_credit_credit",
             status="VERIFIED", code="verified", verified=True, ms=900.0)
    _finished(tape, t, answer="Fifteen pounds of store credit is on Alice's account.", question=said, ui=["action"])
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tape.write(tmp_path)


def test_a_successful_store_credit_turn_is_set_against_the_live_family_not_no_family(tmp_path):
    """The report, on a turn with no router verdict to lean on: the request is a change, the change
    is store credit, the family serving it is READY — never NO_FAMILY — and nothing in the report
    proposes building it or calls it missing."""
    said = "Give Alice £15 of store credit"
    rec, markdown = build_report(_store_credit_turn(tmp_path, said))
    turn = rec.turn("turn_credit")
    assert turn.verdict is not None and turn.verdict.mutation_source == "report"
    assert turn.verdict.change is not None and turn.verdict.change.key == "store_credit"
    assert turn.contract == contract.WRITE_INTENT
    spoken = _spoken_capability(turn)
    assert spoken is not None and spoken["state"] == "READY" and spoken["state"] != semantics.NO_FAMILY, spoken
    assert "MISSING_CAPABILITY" not in turn.classes and "UNFULFILLED_ACTION" not in turn.classes, turn.classes
    assert "no capability family claims it" not in markdown


# ------------------------------------------------------------------ what a page sent (F-OBS2-01)

NAME = "Greg Hartley"


def _page_tape(tmp_path: Path) -> Path:
    """Telemetry from a page carrying a customer's name (and an address, and a token) in every
    field the rules read: the field the keyboard left and why, the control two fingers landed on,
    the two controls that overlap, a notification's name, a composer field, a disabled chip."""
    from tests.test_analyser import Tape, _finished, _turn

    token = shopify_token("page")
    tape = Tape("ts-20260928-130000-page")
    t = _turn(tape, "turn_page", said="show me the orders", input_="text")
    tape.add("tablet_focus", source="tablet", turn_id=t, state="lost", name=f"{NAME}'s note field",
             cause=f"a render replaced {NAME}'s card")
    tape.add("tablet_focus", source="tablet", turn_id=t, state="blur", name="greg@example.com", cause=token)
    tape.add("tablet_hold", source="tablet", turn_id=t, phase="multitouch", fingers=2, target=f"{NAME} orb")
    tape.add("tablet_collision", source="tablet", turn_id=t, a=f"{NAME}'s row", b="Refund Greg", overlap=12)
    tape.add("tablet_notify", source="tablet", turn_id=t, name=f"{NAME} alert")
    tape.add("tablet_compose_field", source="tablet", turn_id=t, name=f"{NAME} body", chars=12)
    tape.add("tablet_compose_field", source="tablet", turn_id=t, name=f"{NAME} body", chars=0)
    tape.add("tablet_rail_tap", source="tablet", turn_id=t, state="disabled", action=f"Refund {NAME}")
    # And identifiers, which a finding may name as they are.
    tape.add("tablet_focus", source="tablet", turn_id=t, state="lost", name="composer-subject", cause="render")
    _finished(tape, t, answer="Three orders came in.", question="show me the orders")
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tape.write(tmp_path)


def test_a_customers_name_a_page_put_in_its_telemetry_never_leaves_visible(tmp_path):
    token = shopify_token("page")
    rec = reconstruct(read_events(_page_tape(tmp_path)))
    reading = visible.apply(rec)
    names = {f.name for f in reading.findings}
    assert {"FOCUS_LOST", "COLLISION", "EMPTY_NOTIFICATION", "FAKE_CONTROL"} <= names, names
    carried = json.dumps([f.as_dict() for f in reading.findings]) + json.dumps(
        [row.__dict__ for row in reading.rows]) + json.dumps([t.signals for t in rec.turns])
    for leak in ("Greg", "Hartley", "greg@example.com", token):
        assert leak not in carried, leak
    assert "[withheld]" in carried
    signals = [f.signal for f in reading.findings if f.name == "FOCUS_LOST"]
    assert "the keyboard left composer-subject when render" in signals, "an identifier is named as it is"


def test_the_report_built_from_that_timeline_carries_none_of_it_either(tmp_path):
    _rec, markdown = build_report(_page_tape(tmp_path))
    assert "Greg" not in markdown and "Hartley" not in markdown and "greg@example.com" not in markdown


# ------------------------------------------------------------------ the log rule (O2-F-01)


@pytest.mark.parametrize("said", [
    "Show me the log for order #1938",
    "show me the log for order 1938",
    "Read me the order log for 1938",
    "What does the log say for 1938?",
    "Pull up the audit log",
    "Is there a log for this order?",
    "Open the change log",
    "Log of order 1938 please",
    "log for order 1938",
    "check the log on order 1938",
    "log into Shopify",
])
def test_reading_a_log_is_not_feedback(said):
    assert feedback.recognise(said) is None, said


@pytest.mark.parametrize("said", [
    "please log that the applying button never stops",
    "Log--a lot of your functions are broken or halfway there.",
    "Log your error there. You just pulled up two in the same UI",
    "can you log this",
    "Okay, uh, please log that your split function is broken.",
    "log this bug: the split shows twice",
    "log that the refund did not go through",
])
def test_an_instruction_to_log_is_still_feedback(said):
    found = feedback.recognise(said)
    assert found is not None and found.kind == "log", said


def test_asking_for_an_order_log_during_a_test_session_records_nothing_and_tells_the_model_nothing(tmp_path):
    store = TestSessions(Path(tmp_path))
    line = timeline.install(timeline.Timeline(store))
    session = line.start("reading a log")
    try:
        assert feedback.at_turn("Show me the log for order #1938", session_id="s1", turn_id="t1") == ""
        line.flush()
        events = read_events(store.timeline_path(session))
    finally:
        line.stop()
        timeline.install(timeline.NullTimeline())
    assert not [e for e in events if e.get("kind") == "owner_feedback"]


# ------------------------------------------------------------------ the live words' mark (F-02)


@pytest.mark.parametrize("value", ["rowan-mitcham-1930", "true", "leeds_shop", "move the hoodie"])
def test_the_live_words_mark_is_kept_and_its_value_never_is(value):
    copy = sanitise_markup(f'<span id="ask-words" data-spoken="{value}">move the hoodie to Leeds</span>')
    assert 'data-spoken=""' in copy and value not in copy and "hoodie" not in copy, copy


# ------------------------------------------------------------------ through /turn (E-03)


async def test_a_defect_said_through_the_turn_route_is_recorded_against_it_and_reported_as_recorded(tmp_path):
    """R9-E-families1-E-03, end to end: POST /turn with a plain spoken defect during a test session
    — nothing in the test calls the recorder — writes one owner_feedback event against that turn
    (app/routes/turn.py hands the words to feedback.at_turn before the model is asked), the model
    is told it was logged, and the report built from the file prints it among the defects
    RECORDED, verbatim, and not among those nothing recorded."""
    from experience.harness import harness

    said = "log that the back button is broken, it takes me to the wrong order"
    async with harness(admitted=True) as h:
        store = TestSessions(Path(tmp_path))
        line = timeline.install(timeline.Timeline(store))
        session = line.start("round eleven, through the door")
        try:
            capture = await h.say(said, session_id="fb11")
            line.flush()
        finally:
            line.stop()
            timeline.install(timeline.NullTimeline())
    assert capture.status == 200 and capture.model_calls == 1, "it is still a model turn"
    turn_id = str(capture.raw.get("turn_id") or "")
    path = store.timeline_path(session)
    recorded = [e for e in read_events(path) if e.get("kind") == "owner_feedback"]
    assert [(e.get("turn_id"), e.get("text"), e.get("shape")) for e in recorded] == [(turn_id, said, "log")]
    assert feedback.RECORDED_LINE in h.provider.calls[-1], "the model is told it was logged"
    rec, markdown = build_report(path)
    turn = rec.turn(turn_id)
    assert turn is not None and "OWNER_FEEDBACK_IGNORED" not in turn.classes, turn.classes
    assert (len(rec.experience.feedback), len(rec.experience.ignored_feedback)) == (1, 0)
    assert "1 recorded during the session" in markdown and said in markdown
