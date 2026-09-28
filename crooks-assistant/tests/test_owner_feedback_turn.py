"""A defect the owner says out loud is written down at turn time again, and he is told so truthfully.

The 2026-09-28 deploy review, round 9, E-03 and I-tests4 I-02. The only caller of
`feedback.record` was the word-matching family `owner_feedback`, deleted with the fast lane on
28 September. From then on "log that the split is broken" reached the model like every other
sentence and nothing wrote it down: it survived only as OWNER_FEEDBACK_IGNORED in the report,
read back from the transcript, and the model — which has no tool for it — was free to answer
"I've no tool for logging a product bug", which is the exact D-7 failure the family was built
to end.

`feedback.at_turn` is the recorder restored without the lane. It recognises the sentence,
records it against the screen the owner was on BEFORE the answer replaced it, and returns the
line the model is given — "it is logged" when it was, "nothing wrote it down" when no test
session is running — so the confirmation he hears is the truth. Nothing here answers the
sentence: it still goes to the model.

The first tests hold the recorder and its whole transcript→report path through a real timeline
file and the real report builder. The last drives `POST /turn` end to end and needs one line in
`app/routes/turn.py` that belongs to the turn route's owner this round; it is marked as a
strict expected failure until that line lands, so the moment it does the marker has to come off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.observability import feedback, timeline
from app.observability.report import build_report
from app.observability.session import TestSessions

SAID = "log that the back button is broken, it takes me to the wrong order"


class Half:
    """A half of the conversation, holding what was on the glass when he spoke."""

    branch_id = "br_left"
    status = "ACTIVE"
    tab = ""
    entity = {"kind": "order", "ref": "gid://shopify/Order/1938", "label": "#1938 Mia Jones"}
    recent_entities: list = []
    last_ui = [{"type": "order", "data": {"customer_name": "Mia Jones"}}]


@pytest.fixture()
def recording(tmp_path):
    store = TestSessions(Path(tmp_path))
    line = timeline.install(timeline.Timeline(store))
    session = line.start("round ten")
    yield line, store, session
    line.stop()
    timeline.install(timeline.NullTimeline())


def _events(store, session) -> list[dict]:
    path = store.timeline_path(session)
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_a_defect_said_at_turn_time_is_recorded_and_the_model_is_told_it_was(recording):
    line, store, session = recording
    told = feedback.at_turn(SAID, branch=Half(), session_id="s1", turn_id="turn_r10")
    assert told == feedback.RECORDED_LINE
    assert "Do not say there is no tool" in told, "the D-7 answer is ruled out in so many words"
    line.flush()
    (event,) = [e for e in _events(store, session) if e["kind"] == "owner_feedback"]
    assert event["text"] == SAID, "verbatim"
    assert event["turn_id"] == "turn_r10" and event["branch_id"] == "br_left"
    assert event["screen"] == ["order"], "the screen he was complaining about"
    assert event["entities"] == [{"kind": "order", "ref": "gid://shopify/Order/1938"}]
    assert "Mia" not in json.dumps(event), "ids around his words, never a customer's name"


def test_an_ordinary_sentence_is_not_feedback_and_nothing_is_written(recording):
    line, store, session = recording
    assert feedback.at_turn("show me today's orders", branch=Half(), session_id="s1", turn_id="t") == ""
    assert feedback.at_turn("the order is wrong", branch=Half(), session_id="s1", turn_id="t") == ""
    line.flush()
    assert not [e for e in _events(store, session) if e["kind"] == "owner_feedback"]


def test_with_no_test_session_the_model_is_told_nothing_wrote_it_down():
    """The one thing worse than not recording a defect is saying it was recorded."""
    timeline.install(timeline.NullTimeline())
    told = feedback.at_turn(SAID, branch=Half(), session_id="s1", turn_id="t")
    assert told == feedback.NOT_RECORDED_LINE
    assert "never say it was logged" in told


def test_a_recorder_that_fails_never_fails_the_turn(recording, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(feedback, "record", broken)
    assert feedback.at_turn(SAID, branch=Half(), session_id="s1", turn_id="t") == ""


def test_what_at_turn_recorded_is_what_the_report_prints_as_recorded(recording):
    """The transcript→report path, through a real timeline file and the real report builder:
    the turn as the turn route writes it, with the feedback recorded in the middle of it. Not
    OWNER_FEEDBACK_IGNORED, and his words verbatim in section 15."""
    line, store, session = recording
    timeline.current().emit("turn_started", session_id="s1", turn_id="turn_r10", input="text", turns_before=0, epoch=1)
    feedback.at_turn(SAID, branch=Half(), session_id="s1", turn_id="turn_r10")
    timeline.current().emit("turn_finished", session_id="s1", turn_id="turn_r10", question=SAID,
                            answer="Logged, with the order you were on.", ui=["assistant"], ms=900.0,
                            timings={"total": 900.0})
    line.flush()
    rec, markdown = build_report(store.timeline_path(session))
    turn = rec.turn("turn_r10")
    assert turn is not None and "OWNER_FEEDBACK_IGNORED" not in turn.classes, turn.classes
    assert len(rec.experience.feedback) == 1 and rec.experience.ignored_feedback == []
    assert "1 recorded during the session" in markdown
    assert SAID in markdown
    assert "on screen: order" in markdown


# ------------------------------------------------------------------------ through /turn


async def test_a_spoken_defect_through_the_turn_route_is_recorded_before_the_model_answers(tmp_path):
    """I-tests4 I-02: a plain spoken defect sent through `POST /turn`, with no call to
    `feedback.record` in the test — the route's own recorder must write it, against the turn,
    and the model must be handed the line saying so."""
    from experience.harness import harness

    async with harness(admitted=True) as h:
        store = TestSessions(Path(tmp_path))
        line = timeline.install(timeline.Timeline(store))
        session = line.start("round ten, through the door")
        try:
            said = "the split doesn't work at all, it just shows two of the same thing"
            capture = await h.say(said, session_id="fb1")
            line.flush()
            events = _events(store, session)
        finally:
            line.stop()
            timeline.install(timeline.NullTimeline())
    assert capture.status == 200 and capture.model_calls == 1, "it is still a model turn"
    turn_id = str(capture.raw.get("turn_id") or "")
    recorded = [e for e in events if e["kind"] == "owner_feedback"]
    assert [e.get("turn_id") for e in recorded] == [turn_id], recorded
    assert recorded[0]["text"] == said
    assert feedback.RECORDED_LINE in h.provider.calls[-1], "the model is told it was logged"


async def test_a_spoken_defect_through_the_turn_route_reaches_the_report_in_his_words(tmp_path):
    """What holds today, hook or no hook, through the same door and the same report builder,
    with nothing called in the route's place: a defect said out loud is not lost. Before the
    turn route calls `feedback.at_turn` the report finds it in the transcript and prints it
    among the defects NOTHING recorded; once the route calls it, among those recorded. Either
    way his words are in the report verbatim, against that turn — and never both, and never
    neither."""
    from experience.harness import harness

    said = SAID
    async with harness(admitted=True) as h:
        store = TestSessions(Path(tmp_path))
        line = timeline.install(timeline.Timeline(store))
        session = line.start("round ten, the report")
        try:
            capture = await h.say(said, session_id="fb2")
            line.flush()
        finally:
            line.stop()
            timeline.install(timeline.NullTimeline())
    assert capture.status == 200 and capture.model_calls == 1, "it is a model turn"
    rec, markdown = build_report(store.timeline_path(session))
    turn = rec.turn(str(capture.raw.get("turn_id") or ""))
    assert turn is not None, "the turn is in the transcript the report read"
    recorded, ignored = len(rec.experience.feedback), len(rec.experience.ignored_feedback)
    assert (recorded, ignored) in ((1, 0), (0, 1)), (recorded, ignored)
    assert ("OWNER_FEEDBACK_IGNORED" in turn.classes) == bool(ignored), turn.classes
    assert said in markdown, "his words, verbatim"
