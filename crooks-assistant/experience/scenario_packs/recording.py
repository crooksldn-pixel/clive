"""Recording is observability, not fixture mode (brief §26).

Everything else about the recorder is held in `tests/test_recorder.py`, where a file on disk
can be read back and searched. What belongs HERE is the one part of it that is a turn's
behaviour: with a recording running, the turn must be the same turn.

Same cards, same answer, the same one model call, nothing staged that was not staged — and a recording on disk afterwards holding the interaction with
no customer's words or address in it. The comparison is made against the same sentence asked
with recording off, in the same run, so the two are not two different afternoons.
"""

from __future__ import annotations

from typing import Any

from app.observability import recorder as recorder_module
from app.observability import timeline as timeline_module
from app.observability.timeline import read_events
from experience.harness import Harness
from experience.scenarios import Result, a_model_turn, a_surface, check, grounded

# The fixture world's own order, and the customer whose name must not reach the file.
ORDER = "1938"
CUSTOMER = "Mia"


def _cards(capture: Any) -> list[str]:
    return [str(i.get("type") or "") for i in (capture.ui or []) if isinstance(i, dict)]


async def recording_changes_nothing_about_a_turn(h: Harness) -> Result:
    r = Result("recording_is_observability", "A turn with the recorder running is the same turn")
    h.configure()

    # The same sentence twice: once as production runs, once with a recording on.
    plain = await h.open_order(ORDER, scenario="recording_off", session_id="rec_off")
    r.captures.append(plain)
    r.checks += a_surface(plain, "order", what="draws the order with recording off")

    log_dir = h.runtime.settings.log_dir
    recordings = recorder_module.Recordings(log_dir)
    recorder = recorder_module.Recorder(recordings, keep_transcripts=False)
    timeline = timeline_module.current()
    was = getattr(timeline, "mirror", None)
    session = recorder.start("experience pack")
    timeline.mirror = recorder
    try:
        taped = await h.open_order(ORDER, scenario="recording_on", session_id="rec_on")
        recorder.flush()
    finally:
        timeline.mirror = was
        recorder.stop()
    r.captures.append(taped)

    r.checks += a_surface(taped, "order", what="draws the order with recording on")
    r.checks.append(check("the same path", taped.lane == plain.lane, f"{plain.lane!r} → {taped.lane!r}"))
    r.checks.append(check("the same cards, in the same order", _cards(taped) == _cards(plain), f"{_cards(plain)} → {_cards(taped)}"))
    r.checks.append(check("no model call was added", taped.model_calls == plain.model_calls, f"{plain.model_calls} → {taped.model_calls}"))
    r.checks.append(a_model_turn(taped))
    if grounded(h):
        r.checks.append(check("the same answer, word for word", taped.answer == plain.answer,
                              f"{len(plain.answer)} vs {len(taped.answer)} characters"))
    r.checks.append(check("nothing was staged by recording",
                          not list(getattr(h.runtime.sessions.get("rec_on"), "proposals", ()) or []),
                          "a recording cannot authorise a change"))

    path = recordings.timeline_path(session)
    events = read_events(path)
    kinds = {str(e.get("kind") or "") for e in events}
    r.checks.append(check("the interaction reached the recording", {"turn_started", "model", "turn_finished"} <= kinds,
                          f"kinds={sorted(kinds)}"))
    r.checks.append(check("every event is marked as recorded", all(e.get("recorded") is True for e in events if e.get("kind") != "session_started"),
                          f"{len(events)} event(s)"))
    finished = next((e for e in events if e.get("kind") == "turn_finished"), {})
    r.checks.append(check("what was said is a shape and not a sentence",
                          "answer" not in finished and "question" not in finished and finished.get("answer_chars", 0) > 0,
                          f"keys={sorted(finished)[:12]}"))
    raw = path.read_text(encoding="utf-8")
    if grounded(h):
        r.checks.append(check("the customer is not in the file", CUSTOMER not in raw, "a recording holds ids and counts"))
    r.checks.append(check("no credential and no nonce in the file",
                          "nonce" not in raw and "shpat_" not in raw and "Bearer" not in raw))

    # And the test session's own directory is untouched: a recording is not a test session.
    tests_dir = log_dir / "test-sessions"
    r.checks.append(check("no test session was started", not (tests_dir / "active.json").exists(),
                          f"{tests_dir}"))
    return r


SCENARIOS = (
    ("recording_is_observability", recording_changes_nothing_about_a_turn),
)
