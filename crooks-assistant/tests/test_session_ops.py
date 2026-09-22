"""An hour with the tablet, as documents: start with a label, watch it, stop and analyse.

The thing most worth protecting here is that the ANALYSIS IS NOT REIMPLEMENTED. The report
and the proposals are long, tested, and already the product's own reading of a session;
writing a second, shorter one for a button to call would give the owner two answers and no
way to tell which was right. Two of the tests below run the real
`app/observability/report.py` and `app/observability/proposals.py` over a real timeline and
assert that real files come out — and one of them breaks the analyser deliberately, to check
that a session is never lost because the reading of it failed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from scripts import session_ops

PORT = 8000


@pytest.fixture(autouse=True)
def no_backend(monkeypatch):
    """Nothing answering on loopback unless a test says otherwise. The alternative is a suite
    whose result depends on whether the author's own Mac happens to be running."""
    answers: dict = {"reply": None}
    monkeypatch.setattr(session_ops, "call", lambda *a, **kw: answers["reply"])
    return answers


@pytest.fixture()
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(session_ops, "settings", lambda: _Settings(tmp_path / "logs"))
    return tmp_path / "logs"


class _Settings:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.port = PORT


def event(kind: str, seq: int, **fields) -> str:
    return json.dumps({"ts": 1_700_000_000.0 + seq, "iso": "2026-09-12T10:00:00", "seq": seq,
                       "test_session_id": "ts-x", "source": "mac", "kind": kind, **fields})


def timeline(path: Path, *events: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(events) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- start


def test_a_session_starts_on_disk_when_the_backend_is_not_running(log_dir):
    """An hour of testing must not be impossible because the Mac is between restarts. The
    session is marked on disk and the backend picks it up when it next writes an event —
    which is exactly what the typed CLI does, and for the same reason."""
    out = session_ops.start(PORT, label="first hour", log_dir=log_dir)
    assert out["ok"] is True and out["active"] is True and out["where"] == "disk"
    assert out["test_session_id"].startswith("ts-") and out["test_session_id"].endswith("first-hour")
    assert "not running" in out["human"]
    assert session_ops.store(log_dir).active().test_session_id == out["test_session_id"]


def test_the_label_is_optional_and_becomes_the_name(log_dir):
    unlabelled = session_ops.start(PORT, log_dir=log_dir)
    assert unlabelled["ok"] is True and unlabelled["test_session_id"].endswith("session")


def test_a_second_session_is_refused_rather_than_starting_one_over_another(log_dir):
    first = session_ops.start(PORT, label="one", log_dir=log_dir)
    second = session_ops.start(PORT, label="two", log_dir=log_dir)
    assert second["ok"] is False
    assert first["test_session_id"] in second["human"] and "Stop it first" in second["human"]


def test_the_running_backend_is_asked_first(log_dir, no_backend):
    no_backend["reply"] = {"started": True, "test_session_id": "ts-live", "name": "an hour",
                           "path": "/x/ts-live.jsonl", "started_at": 1.0}
    out = session_ops.start(PORT, label="an hour", log_dir=log_dir)
    assert out["where"] == "backend" and out["test_session_id"] == "ts-live"
    assert session_ops.store(log_dir).active() is None, "the backend owns it; nothing was written twice"


# --------------------------------------------------------------------------- progress


def test_progress_counts_turns_and_owner_feedback_from_the_file(tmp_path):
    """From the FILE, for the reason the timeline's own `counts` gives about itself: the
    backend can restart mid-session and the timeline keeps growing underneath it. An
    in-memory counter reported "0 events" against a session holding a thousand."""
    path = timeline(
        tmp_path / "ts-x.jsonl",
        event("turn_started", 1), event("stt", 2), event("turn_started", 3),
        event("owner_feedback", 4, kind_of="missing_tool"), event("tool_call", 5),
        event("turn_started", 6), event("owner_feedback", 7),
    )
    progress = session_ops.progress(path, started_at=100.0, now=4_000.0)
    assert progress["measured"] is True and progress["why"] == ""
    assert progress["turns"] == 3 and progress["owner_feedback"] == 2 and progress["events"] == 7
    assert progress["elapsed_s"] == 3900.0


def test_a_timeline_not_written_to_yet_is_zero_and_not_a_mystery(tmp_path):
    progress = session_ops.progress(tmp_path / "nothing.jsonl", started_at=10.0, now=20.0)
    assert progress["measured"] is True and progress["turns"] == 0 and progress["events"] == 0
    assert progress["elapsed_s"] == 10.0


def test_a_count_too_expensive_to_take_says_so_rather_than_reporting_zero(tmp_path, monkeypatch):
    """§26 applied to a number instead of a test: a count that was not taken must never be
    drawn as a count of nothing. The app shows "—" and the reason, and the owner is not told
    his session has recorded no turns when nobody has looked."""
    monkeypatch.setattr(session_ops, "COUNT_LIMIT_BYTES", 200)
    path = timeline(tmp_path / "ts-big.jsonl", *[event("turn_started", n) for n in range(20)])
    progress = session_ops.progress(path, started_at=0.0, now=60.0)
    assert progress["measured"] is False
    assert progress["turns"] is None and progress["owner_feedback"] is None
    assert "counting it on every poll" in progress["why"]
    assert progress["elapsed_s"] == 60.0, "the clock is still cheap, so it is still reported"


def test_status_reports_what_is_running_and_its_progress(log_dir):
    started = session_ops.start(PORT, label="first hour", log_dir=log_dir)
    path = Path(started["path"])
    timeline(path, event("turn_started", 1), event("owner_feedback", 2))
    out = session_ops.status(PORT, log_dir=log_dir, now=started["started_at"] + 90.0)
    assert out["active"] is True and out["test_session_id"] == started["test_session_id"]
    assert out["progress"]["turns"] == 1 and out["progress"]["owner_feedback"] == 1
    assert out["progress"]["elapsed_s"] == 90.0


def test_status_with_nothing_running_says_nothing_is_running(log_dir):
    out = session_ops.status(PORT, log_dir=log_dir)
    assert out["ok"] is True and out["active"] is False
    assert "No test session is running" in out["human"]


# ------------------------------------------------------------------ stop and analyse


def real_timeline(path: Path) -> Path:
    """A short session the real analyser can read: two turns, a tool call and one piece of
    owner feedback."""
    return timeline(
        path,
        event("turn_started", 1, session_id="s1", turn_id="turn_a", input="audio"),
        event("stt", 2, session_id="s1", turn_id="turn_a", ok=True, engine="scribe", text="how many orders today"),
        event("tool_call", 3, session_id="s1", turn_id="turn_a", tool="orders_recent", ok=True, ms=120),
        event("answer", 4, session_id="s1", turn_id="turn_a", text="Eleven orders today.", ms=900),
        event("turn_started", 5, session_id="s1", turn_id="turn_b", input="audio"),
        event("owner_feedback", 6, session_id="s1", turn_id="turn_b", text="it should say the total too",
              feedback_kind="missing_information"),
        event("answer", 7, session_id="s1", turn_id="turn_b", text="Noted.", ms=300),
    )


def test_stop_keeps_the_raw_timeline_and_runs_the_analysis_that_already_exists(log_dir, tmp_path):
    """The real `write_report` and the real `write_proposals`, over a real timeline. If this
    ever starts passing against a reimplementation, the reimplementation is the bug."""
    started = session_ops.start(PORT, label="first hour", log_dir=log_dir)
    path = real_timeline(Path(started["path"]))
    raw_before = path.read_bytes()
    out = session_ops.stop_and_analyse(PORT, log_dir=log_dir, out_dir=tmp_path / "reports",
                                       sleep=lambda s: None, now=_ticking())
    assert out["ok"] is True and out["stopped"] is True
    assert out["test_session_id"] == started["test_session_id"]
    assert out["events"] == 7 and "Recorded 7 event(s)" in out["human"]
    assert path.read_bytes() == raw_before, "the session itself is never rewritten by a reading of it"
    assert out["paths"]["raw"] == str(path)
    assert Path(out["paths"]["report"]).is_file() and Path(out["paths"]["report"]).stat().st_size > 0
    assert Path(out["paths"]["proposals"]).is_file()
    assert Path(out["paths"]["folder"]) == tmp_path / "reports"
    assert [a["name"] for a in out["artefacts"]] == ["report", "proposals"]
    assert all(a["ok"] for a in out["artefacts"])
    assert session_ops.store(log_dir).active() is None, "and it really stopped"


def test_the_analyser_is_the_one_that_already_exists_and_is_not_a_second_opinion():
    """Named directly, because the failure this guards against is the kind that gets written
    by accident in an afternoon and disagrees with the real report for a year."""
    from app.observability.proposals import write_proposals
    from app.observability.report import write_report

    assert session_ops._write_report.__code__.co_names[-1] == "write_report"
    assert session_ops._write_proposals.__code__.co_names[-1] == "write_proposals"
    source = (Path(session_ops.__file__)).read_text(encoding="utf-8")
    assert "def write_report" not in source and "def write_proposals" not in source
    assert callable(write_report) and callable(write_proposals)


def test_a_report_that_cannot_be_written_never_loses_the_session(log_dir, tmp_path, monkeypatch):
    """The session is the thing. A failed reading of it is a missing report; a stop that
    refused to finish because the report failed would be a missing hour."""
    started = session_ops.start(PORT, label="first hour", log_dir=log_dir)
    real_timeline(Path(started["path"]))
    monkeypatch.setattr(session_ops, "_write_report",
                        lambda path, out: (_ for _ in ()).throw(ValueError("a section blew up")))
    out = session_ops.stop_and_analyse(PORT, log_dir=log_dir, out_dir=tmp_path / "reports",
                                       sleep=lambda s: None, now=_ticking())
    assert out["ok"] is True and out["stopped"] is True
    assert session_ops.store(log_dir).active() is None
    report = next(a for a in out["artefacts"] if a["name"] == "report")
    assert report["ok"] is False and "a section blew up" in report["detail"]
    assert out["paths"]["report"] == "" and Path(out["paths"]["proposals"]).is_file()
    assert "report could not be written" in out["human"]
    assert Path(out["paths"]["raw"]).is_file(), "and the hour is still on disk"


def test_stopping_when_nothing_is_running_is_refused_rather_than_inventing_a_session(log_dir):
    out = session_ops.stop_and_analyse(PORT, log_dir=log_dir, sleep=lambda s: None, now=_ticking())
    assert out["ok"] is False and out["stopped"] is False
    assert out["human"] == "No test session is running."
    assert out["paths"] == {} and out["artefacts"] == []


def test_the_last_events_of_a_session_are_waited_for_before_it_is_read(tmp_path):
    """The backend writes events from a queue on its own thread, so the final turns of a
    session land a moment after stop returns. Reading it immediately leaves them out of the
    report, and the turn most worth reading is usually the last one."""
    path = tmp_path / "ts-settle.jsonl"
    timeline(path, event("turn_started", 1))
    clock = {"t": 0.0}
    writes = {"n": 0}

    def sleep(seconds):
        clock["t"] += seconds
        writes["n"] += 1
        if writes["n"] <= 2:    # two more batches arrive after the stop
            with path.open("a", encoding="utf-8") as handle:
                handle.write(event("answer", writes["n"] + 1) + "\n")

    held = session_ops._settle(path, sleep=sleep, now=lambda: clock["t"])
    assert held == 3, "it waited for the queue to land rather than reading a truncated session"


def test_settling_gives_up_rather_than_waiting_for_ever(tmp_path):
    """A timeline that never stops growing is a session somebody forgot to stop, not a reason
    for the button to hang."""
    path = tmp_path / "ts-forever.jsonl"
    timeline(path, event("turn_started", 1))
    clock = {"t": 0.0}

    def sleep(seconds):
        clock["t"] += seconds
        with path.open("a", encoding="utf-8") as handle:
            handle.write(event("answer", int(clock["t"] * 10)) + "\n")

    held = session_ops._settle(path, sleep=sleep, now=lambda: clock["t"], timeout_s=1.0)
    assert clock["t"] <= 1.4 and held >= 2


def _ticking():
    clock = {"t": 0.0}

    def now():
        clock["t"] += 0.2
        return clock["t"]

    return now


def test_no_document_here_carries_anything_the_app_cannot_decode(log_dir, tmp_path):
    started = session_ops.start(PORT, label="first hour", log_dir=log_dir)
    real_timeline(Path(started["path"]))
    for doc in (session_ops.status(PORT, log_dir=log_dir),
                session_ops.stop_and_analyse(PORT, log_dir=log_dir, out_dir=tmp_path / "reports",
                                             sleep=lambda s: None, now=_ticking())):
        json.dumps(doc)


def test_the_clock_used_for_elapsed_is_the_wall_clock_and_not_a_monotonic_one(log_dir):
    """`started_at` is written to disk by the session store as a wall-clock time. Measuring
    against `time.monotonic()` would make every elapsed figure the age of the process."""
    started = session_ops.start(PORT, label="x", log_dir=log_dir)
    assert abs(started["started_at"] - time.time()) < 60
    out = session_ops.status(PORT, log_dir=log_dir)
    assert 0 <= out["progress"]["elapsed_s"] < 60
