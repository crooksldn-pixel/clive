"""The report and what it reads (the 2026-09-28 deploy review, round 10, answered in round 11):

- R9-F-observability1-F-03 and O2-F-02: "Give Alice £15 of store credit" held no mutation word —
  "give" fetches, as in "give me the sales" — so it was graded a read and never set against the
  store-credit family that carried it out. A grant of credit is a change now; a question about a
  balance is still a read.
- R9-F-observability2-F-OBS2-01: the rules in visible.py wrote a page's own values — the field the
  keyboard left (`tablet_focus.name`), why (`cause`), a control's name — into findings, and so into
  the report's tables. What a page sent leaves visible.py only as an identifier, however many
  strings it sent and in whatever script, and the report prints what a page sent only as an
  identifier, a number or a path of identifiers.
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


def _round11_first_rule(text: str, words: set[str]) -> str:
    """How round 11 first withheld page strings, kept here as the measure the rule is held to: one
    search a string, longest first, each replaced where it stands whole."""
    import re

    out = text
    for word in sorted(words, key=len, reverse=True):
        if word in out:
            out = re.sub(rf"(?<![0-9A-Za-z_]){re.escape(word)}(?![0-9A-Za-z_])", "[withheld]", out)
    return out


def _standing_whole(text: str, words: set[str]) -> list[str]:
    import re

    return [w for part in text.split("[withheld]") for w in words
            if re.search(rf"(?<![0-9A-Za-z_]){re.escape(w)}(?![0-9A-Za-z_])", part)]


def test_every_string_a_page_sent_is_withheld_however_many_it_sent():
    """R9-F-observability2-F-OBS2-01, finished. The first rule stopped collecting a page's strings
    at 20,000, so a customer's name sent after them reached the report as it was, and searched every
    signal once per string, some ten seconds for a day's signals. Every string is collected now and
    the search is one look at each place a string could begin: the name is withheld, and so is every
    label, in a small part of that time."""
    import time

    events = [{"source": "tablet", "kind": "tablet_focus", "turn_id": "t", "name": f"Label {n} Name"}
              for n in range(25_000)]
    events.append({"source": "tablet", "kind": "tablet_focus", "turn_id": "t", "name": NAME})
    words = visible.page_words(events)
    assert len(words) == 25_001
    signals = [f"the keyboard left {NAME}'s field when Label {n} Name was drawn" for n in range(3_000)]
    began = time.perf_counter()
    out = [visible.withheld(signal, words) for signal in signals]
    took = time.perf_counter() - began
    assert out[7] == "the keyboard left [withheld]'s field when [withheld] was drawn", out[7]
    assert not [s for s in out if "Greg" in s or "Label" in s]
    assert took < 5.0, f"{took:.1f} s to withhold 3,000 signals"


@pytest.mark.parametrize("sent, signal, expected", [
    ("Иван Петров", "the keyboard left Иван Петров's note", "the keyboard left [withheld]'s note"),
    ("Zoë Brandt", "a render replaced Zoë Brandt", "a render replaced [withheld]"),
    ("(Greg)", "two fingers on (Greg) orb", "two fingers on [withheld] orb"),
    ("Alice Smith", "Alice Smith's card, and Alice Smithson's", "[withheld]'s card, and Alice Smithson's"),
    ("Greg", "Greg_x and Greg", "Greg_x and [withheld]"),
])
def test_a_page_string_in_any_script_is_withheld_where_it_stands_whole_and_nowhere_else(sent, signal, expected):
    words = visible.page_words([{"source": "tablet", "kind": "tablet_focus", "name": sent}])
    assert visible.withheld(signal, words) == expected


def test_a_page_string_as_deep_as_telemetry_keeps_one_is_withheld_too():
    """What /telemetry keeps of a page's nesting (app/routes/observe.py _bounded, MAX_DEPTH) is all
    walked: a name at the deepest level the route lets through is still found and withheld. The
    first rule stopped four levels down, two short of what the route keeps."""
    from app.routes import observe

    deep: object = [NAME]
    for key in ("e", "d", "c", "b", "a"):
        deep = {key: deep}
    kept = observe._bounded(deep)
    assert json.dumps(kept).count(NAME) == 1, "the route keeps it at this depth"
    words = visible.page_words([{"source": "tablet", "kind": "tablet_render", "state": kept}])
    assert visible.withheld(f"a card in state {NAME} was drawn", words) == "a card in state [withheld] was drawn"


def test_what_is_left_holds_no_page_string_standing_whole_and_no_more_than_the_first_rule_left():
    """Over thousands of made-up signals and strings (letters of two scripts, digits, punctuation,
    strings that overlap and strings that stand whole only once a neighbour is withheld): nothing
    a page sent stands whole in what is left, and what is left is never more than the first rule
    left — every string that stood whole in a signal is withheld entire."""
    import random

    pick = random.Random(11)
    letters = list("abAB-_ .'é#Иx1")
    for _ in range(4_000):
        words = {"".join(pick.choice(letters) for _ in range(pick.randint(1, 4))).strip() for _ in range(pick.randint(1, 6))}
        words.discard("")
        text = "".join(pick.choice(letters) for _ in range(pick.randint(0, 25)))
        out = visible.PageWords(words).withhold(text)
        assert not _standing_whole(out, words), (text, words, out)
        first = _round11_first_rule(text, words)
        assert len("".join(out.split("[withheld]"))) <= len("".join(first.split("[withheld]"))), (text, words, out, first)


def _screens_tape(tmp_path: Path) -> Path:
    """Five turns whose renders carry a customer's name in every field section 7, the top problems,
    the table of cards and an ignored defect print: a card's type, its overflow, its rail action,
    the document's heights, the viewport, a card it could not draw, a failed image's path, a
    scroll's depth, the connection's state. And one of each that is an identifier."""
    from tests.test_analyser import Tape, _finished, _turn

    tape = Tape("ts-20260928-140000-screens")
    for n in range(5):
        t = _turn(tape, f"turn_s{n}", said="show me the orders", input_="text")
        tape.add("tablet_render", source="tablet", turn_id=t, screen="context",
                 cards=[{"type": f"{NAME} card", "clipped_x": NAME,
                         "actions": [{"id": f"Refund {NAME}", "enabled": True}, {"id": "order.add_note", "enabled": True}]},
                        {"type": "order", "clipped_x": 12}],
                 viewport={"w": NAME, "h": 889, "dpr": 1.33}, document={"cards_height": NAME, "cards_visible": 800},
                 overflow={"long_scroll": True}, skipped=[f"{NAME} card", "chart"], t=int(tape.now * 1000))
        tape.add("tablet_image_failed", source="tablet", turn_id=t, src=f"/media/{NAME}.jpg")
        tape.add("tablet_image_failed", source="tablet", turn_id=t, src="/media/shopify/3fa2/240")
        tape.add("tablet_scroll", source="tablet", turn_id=t, depth=NAME)
        tape.add("tablet_connectivity", source="tablet", turn_id=t, state=f"{NAME} offline")
        _finished(tape, t, answer="Three orders came in.", question="show me the orders")
    t = _turn(tape, "turn_defect", said="log that the back button is broken", input_="text")
    tape.add("tablet_render", source="tablet", turn_id=t, screen="context", cards=[{"type": f"{NAME} card"}],
             t=int(tape.now * 1000))
    _finished(tape, t, answer="Noted.", question="log that the back button is broken")
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tape.write(tmp_path)


def test_the_screens_section_and_the_top_problems_print_what_a_page_sent_only_as_identifiers(tmp_path):
    """F-OBS2-01, the rest of section 7 and what reads the same events: the failed images' paths,
    the clipped cards, the long scrolls, the viewports, the deepest scroll, the connection's
    states, the cards the page could not draw, the rail actions never used, and the cards on
    screen when a defect was said and nothing recorded it. A value a page sent is printed as an
    identifier, a number as a number and a path of identifiers as a path; anything else is
    withheld, and a word where a number belongs no longer stops the report."""
    rec, markdown = build_report(_screens_tape(tmp_path))
    assert "Greg" not in markdown and "Hartley" not in markdown
    assert "[withheld]" in markdown
    assert "/media/shopify/3fa2/240" in markdown, "a path of identifiers is printed as it is"
    assert "order.add_note" in markdown and "chart" in markdown, "identifiers are printed as they are"
    assert "Rail actions exposed but never used" in markdown
    assert [row["screen"] for row in rec.experience.ignored_feedback] == [["[withheld]"]]


# Every kind of page event the report, visible.py and touch.py read.
PAGE_KINDS = ("action_commit", "action_primed", "branch", "collision", "compose_field", "connectivity",
              "context_failed", "context_landed", "exception", "focus", "gesture", "hold", "image_failed",
              "keyboard", "navigate", "notify", "rail_tap", "reconcile", "recording_too_short", "render",
              "scroll", "speak", "tab", "turn_failed", "turn_response", "turn_submitted")


@pytest.mark.parametrize("shape", ["flat", "nested"])
def test_a_name_in_every_field_a_page_may_send_reaches_neither_the_report_nor_the_proposals(tmp_path, shape):
    """F-OBS2-01, over everything a page can send: every field /telemetry keeps (its allow-list,
    app/routes/observe.py ALLOWED_FIELDS) of every kind of page event read after, filled with a
    customer's name — as words where a word, a number or an id belongs and, in the nested shape,
    inside the cards, their actions, the entities, the viewport and the document too. Neither the
    report nor the proposals file carries it. A page's free text (an exception's message, its
    detail) is quoted by its words, scrubbed and bounded, as before, and is left out here."""
    from app.observability import proposals
    from app.routes.observe import ALLOWED_FIELDS
    from tests.test_analyser import Tape, _finished, _turn

    name = "Zed Quorra"
    fields = sorted(set(ALLOWED_FIELDS) - {"kind", "turn_id", "session_id", "t", "seq", "message", "detail",
                                           "text", "question"}) + ["a", "b", "cause", "overlap"]
    tape = Tape(f"ts-20260928-150000-{shape}")
    for n in range(6):
        t = _turn(tape, f"turn_p{n}", said="show me the orders", input_="text")
        for kind in PAGE_KINDS:
            event = {field: f"{name} {field}" for field in fields}
            if shape == "nested":
                event.update(
                    cards=[{"type": f"{name} c", "ref": f"{name} r", "tab_active": f"{name} t", "sections": [f"{name} s"],
                            "tabs": [f"{name} t"], "clipped_x": name, "proposal_id": name, "surface": {"state": name},
                            "actions": [{"id": f"{name} a", "enabled": True, "label": f"{name} l"}]}],
                    entities=[{"kind": f"{name} k", "ref": f"{name} r"}], entity={"kind": name, "ref": name},
                    viewport={"w": name, "h": name, "dpr": name}, document={"cards_height": name, "cards_visible": name},
                    overflow={"long_scroll": True, "clipped": name}, skipped=[f"{name} s"], errors=[f"{name} e"])
            tape.add(f"tablet_{kind}", source="tablet", turn_id=t, **event)
        _finished(tape, t, answer="Three orders came in.", question="show me the orders")
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tape.write(tmp_path)
    _rec, markdown = build_report(path)
    _rec, cands, proposals_markdown = proposals.build(path)
    for written in (markdown, json.dumps(cands, default=str), proposals_markdown):
        leaks = [line for line in written.splitlines() if "Zed" in line or "Quorra" in line]
        assert not leaks, leaks[:5]


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
