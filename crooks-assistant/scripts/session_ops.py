#!/usr/bin/env python3
"""An hour with the tablet, as three buttons instead of four typed commands.

`scripts/test_session.py` is the typed CLI for this and stays exactly as it is; this module is
the same workflow shaped as documents (it was drawn by the CROOKS Control menu-bar app until
that went with the Mac runtime, DEC-071 ruling 38): start with a label, watch it while it runs,
and one stop at the end that keeps the raw timeline and runs the analysis that already exists.

Three things it deliberately does NOT do:

  * reimplement the analyser. `app/observability/report.py` and `app/observability/proposals.py`
    are the analysis, they are long, they are tested, and the worst possible outcome of this
    phase would be a second one that says something slightly different. They are called.
  * touch the raw timeline. The JSONL is the session; a report is a reading of it. The path is
    returned so that it can be kept, and nothing here ever writes to it.
  * claim the analysis ran when it did not. A report that could not be written comes back
    `ok: false` with the reason, and the stop is still a success — because the session really
    did stop, and pretending otherwise would lose the recording as well as the report.

Start, status and stop prefer the running backend on loopback, exactly as the CLI does, and
fall back to the session files on disk when nothing is answering — an hour of testing should
not be lost because the Mac was restarted in the middle of it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))      # launch_common, as the other scripts import it

# Reading a timeline to count turns costs a pass over the file. A long session is megabytes,
# and the Control app asks every few seconds while one is running. Above this the counts are
# reported as NOT MEASURED rather than silently guessed or silently omitted — §26: a thing
# that cannot be measured says so.
COUNT_LIMIT_BYTES = 8 * 1024 * 1024
# What the timeline calls the two events this layer counts. From app/routes/turn.py and
# app/observability/feedback.py; if either is renamed the count goes to zero and the test
# below (which writes real events and expects real counts) is what catches it.
TURN_EVENT = "turn_started"
FEEDBACK_EVENT = "owner_feedback"


def settings():
    from config.settings import get_settings

    return get_settings()


# How long a call to the backend waits for its answer.
TIMEOUT_S = 5.0
# The key an answer carries when there was none: the call timed out or failed some other way.
FAILED = "call_failed"


def call(port: int, method: str, path: str, body: dict | None = None, *, timeout_s: float | None = None) -> dict | None:
    """The backend on loopback. The same endpoints the typed CLI uses, so a button and a command
    cannot start different things.

    None means one thing only (round 8, F-10): nothing is listening on the port — the connection
    was refused, which on loopback is the kernel's own answer. A call that timed out, was cut off,
    or came back as something that is not an answer is NOT that: the backend may be running and
    may have done what was asked. It comes back as {FAILED: why}, and failed() says so. Before,
    both came back None, and a stop that timed out was reported as a stop with no backend, whose
    count is final.

    It is sent by launch_common.call_service (round 10, S1-KEY-SENDER): the server's own key for
    the test-session routes (app/local_cli.py) goes only down a connection the kernel says the
    service itself took, never through a proxy the environment names and never on to a redirect —
    urllib, which this used, did all three. A redirect is an answer here, not a place to go."""
    import launch_common as lc

    data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    wait = TIMEOUT_S if timeout_s is None else timeout_s
    try:
        status, raw = lc.call_service(port, method, path, data, timeout_s=wait)
    except Exception as exc:  # noqa: BLE001 — every way a call can fail is one of the two below
        if _refused(exc):
            return None
        return {FAILED: _why(exc, wait)}
    try:
        answer = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        answer = None
    if status >= 300:
        # A refusal (or a redirect, never followed) is still an answer: its body, or its code.
        return answer if isinstance(answer, dict) and answer else {"code": f"http {status}"}
    return answer if isinstance(answer, dict) else {FAILED: "its answer was not one this understands"}


def failed(answer: dict | None) -> str:
    """Why a call got no answer, when it timed out or failed; '' for an answer, or for None (no
    backend running)."""
    return str(answer.get(FAILED) or "") if isinstance(answer, dict) else ""


def _refused(exc: BaseException) -> bool:
    import errno

    for reason in (exc, getattr(exc, "reason", None)):
        if isinstance(reason, ConnectionRefusedError):
            return True
        if isinstance(reason, OSError) and reason.errno == errno.ECONNREFUSED:
            return True
    return False


def _why(exc: BaseException, wait: float) -> str:
    import socket

    reason = getattr(exc, "reason", None)
    for cause in (exc, reason):
        if isinstance(cause, (TimeoutError, socket.timeout)):
            return f"it did not answer within {wait:g} s"
    return f"the call failed ({type(reason if isinstance(reason, BaseException) else exc).__name__})"


def store(log_dir: Path | None = None):
    from app.observability.session import TestSessions

    if log_dir:
        return TestSessions(Path(log_dir))
    return TestSessions.from_settings(settings(), always=False)


def _number(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def progress(path: Path, *, started_at: float, now: float) -> dict:
    """How the session is going, live: how long it has been running, how many turns the owner
    has taken, and how many times he has told it something about itself.

    Every number here is counted from the FILE rather than from a counter in memory, for the
    reason app/observability/timeline.py gives about its own counts: the backend can restart
    mid-session and the timeline keeps growing underneath it, and a counter that zeroed there
    once reported "0 events" against a session holding a thousand.
    """
    # `started_at or now` would be the natural way to write that fallback and would be wrong:
    # a started_at of 0.0 is falsy, so every elapsed figure taken from one would read as zero
    # seconds. A number's absence is None, not its value being small.
    out = {"elapsed_s": round(max(0.0, now - _number(started_at, now)), 1),
           "turns": None, "owner_feedback": None, "measured": False,
           "why": "", "events": 0}
    try:
        size = Path(path).stat().st_size
    except OSError:
        out["why"] = "the timeline has not been written to yet"
        out["measured"] = True
        out["turns"] = out["owner_feedback"] = 0
        return out
    if size > COUNT_LIMIT_BYTES:
        out["why"] = f"the timeline is {size // (1024 * 1024)} MB; counting it on every poll would cost more than it tells you"
        return out
    from app.observability.timeline import read_events

    events = read_events(Path(path))
    out.update({
        "events": len(events), "measured": True, "why": "",
        "turns": sum(1 for event in events if event.get("kind") == TURN_EVENT),
        "owner_feedback": sum(1 for event in events if event.get("kind") == FEEDBACK_EVENT),
    })
    return out


def start(port: int, *, label: str = "", log_dir: Path | None = None) -> dict:
    """Begin, with an optional short label. The label is what the report is called afterwards
    and what the session id is built from, so "first hour" becomes ts-…-first-hour."""
    from app.observability.session import AlreadyActive

    name = (label or "").strip()[:80] or "session"
    answer = call(port, "POST", "/test-session/start", {"name": name})
    if why := failed(answer):
        # Running but not answering is not "not running" (round 8, F-10): it may have started the
        # session, so nothing is marked on disk over it and nothing is claimed either way.
        return {"ok": False, "active": False, "test_session_id": "", "name": name, "path": "", "started_at": None,
                "where": "backend",
                "human": f"CROOKS OS did not answer ({why}), so whether the session started is not known. "
                         "Check its status before starting another."}
    if answer is not None:
        if answer.get("started"):
            return {"ok": True, "active": True, "test_session_id": answer.get("test_session_id", ""),
                    "name": answer.get("name", name), "path": answer.get("path", ""),
                    "started_at": answer.get("started_at"), "where": "backend",
                    "human": f"Recording {answer.get('test_session_id')}."}
        return {"ok": False, "active": False, "test_session_id": str(answer.get("test_session_id") or ""),
                "name": name, "path": "", "started_at": None, "where": "backend",
                "human": str(answer.get("detail") or "A test session could not be started.")}
    try:
        session = store(log_dir).start(name)
    except AlreadyActive as exc:
        return {"ok": False, "active": True, "test_session_id": str(exc), "name": name, "path": "",
                "started_at": None, "where": "disk",
                "human": f"A test session is already running: {exc}. Stop it first."}
    return {"ok": True, "active": True, "test_session_id": session.test_session_id, "name": session.name,
            "path": str(store(log_dir).timeline_path(session)), "started_at": session.started_at, "where": "disk",
            "human": "CROOKS OS is not running, so the session is marked on disk and starts recording when it is."}


def status(port: int, *, log_dir: Path | None = None, now: float | None = None) -> dict:
    """What is running, and how it is going. Safe to poll."""
    import time

    now = time.time() if now is None else now
    sessions = store(log_dir)
    answer = call(port, "GET", "/test-session/status")
    if why := failed(answer):
        # What the files on disk say, as that, and never "CROOKS OS is not running" (round 8, F-10).
        active = sessions.active()
        if active is None:
            return {"ok": True, "active": False, "test_session_id": "", "name": "", "path": "", "where": "disk",
                    "events": {}, "progress": {}, "last": {},
                    "human": f"CROOKS OS did not answer ({why}); no test session is marked running on disk."}
        path = sessions.timeline_path(active)
        return {"ok": True, "active": True, "test_session_id": active.test_session_id, "name": active.name,
                "path": str(path), "where": "disk", "events": {},
                "progress": progress(path, started_at=active.started_at, now=now),
                "human": f"CROOKS OS did not answer ({why}); {active.test_session_id} is marked running on disk."}
    if answer is not None and answer.get("active"):
        path = Path(answer.get("path") or "")
        return {"ok": True, "active": True, "test_session_id": answer.get("test_session_id", ""),
                "name": answer.get("name", ""), "path": str(path), "where": "backend",
                "events": answer.get("events") or {},
                "progress": progress(path, started_at=_number(answer.get("started_at"), now), now=now),
                "human": f"Recording {answer.get('test_session_id')}."}
    if answer is not None:
        last = answer.get("last") or {}
        return {"ok": True, "active": False, "test_session_id": "", "name": "", "path": "", "where": "backend",
                "events": {}, "progress": {}, "last": last,
                "human": "No test session is running." + (f" The last was {last.get('test_session_id')}." if last else "")}
    active = sessions.active()
    if active is None:
        last = sessions.last()
        return {"ok": True, "active": False, "test_session_id": "", "name": "", "path": "", "where": "disk",
                "events": {}, "progress": {}, "last": ({"test_session_id": last.test_session_id} if last else {}),
                "human": "No test session is running, and CROOKS OS is not running either."}
    path = sessions.timeline_path(active)
    return {"ok": True, "active": True, "test_session_id": active.test_session_id, "name": active.name,
            "path": str(path), "where": "disk", "events": {},
            "progress": progress(path, started_at=active.started_at, now=now),
            "human": f"{active.test_session_id} is marked on disk; CROOKS OS is not running."}


def _settle(path: Path, *, sleep, now, timeout_s: float = 3.0) -> int:
    """Wait for the timeline to stop growing. The backend writes events from a queue on its
    own thread, so the last few lines of a session land a moment after stop returns; running
    the analyser before they do would leave the final turns out of the report."""
    from app.observability.timeline import count_events

    deadline = now() + timeout_s
    held = count_events(path)
    while now() < deadline:
        sleep(0.2)
        again = count_events(path)
        if again == held:
            return held
        held = again
    return held


def stop_and_analyse(port: int, *, log_dir: Path | None = None, analyse: bool = True,
                     out_dir: Path | None = None, sleep=None, now=None) -> dict:
    """Stop cleanly, keep the raw timeline, and run the analysis that already exists.

    The order matters and is the reason this is one operation rather than three buttons: the
    session has to be stopped before the timeline is complete, the timeline has to have
    settled before it is read, and the report has to be written from the file rather than
    from anything held in memory — because the file is the only copy that survives.
    """
    import time

    sleep = sleep or time.sleep
    now = now or time.monotonic
    sessions = store(log_dir)
    asked_at = sessions.clock()
    answer = call(port, "POST", "/test-session/stop")
    why_failed = failed(answer)
    if answer is not None and not why_failed and not answer.get("stopped"):
        return {"ok": False, "stopped": False, "test_session_id": "", "paths": {}, "artefacts": [],
                "human": str(answer.get("detail") or "No test session is running.")}
    if answer is None or why_failed:
        session = stop_on_disk(sessions, asked_at=asked_at if why_failed else None)
        if session is None:
            human = "No test session is running." if answer is None else (
                f"CROOKS OS did not answer the stop ({why_failed}), and no test session is marked running on disk.")
            return {"ok": False, "stopped": False, "test_session_id": "", "paths": {}, "artefacts": [], "human": human}
        ident, path, where = session.test_session_id, sessions.timeline_path(session), "disk"
    else:
        ident = str(answer.get("test_session_id") or "")
        path = Path(answer.get("path") or sessions.timeline_path(ident))
        where = "backend"
    from app.observability.timeline import stop_is_final, unsettled_reasons

    # The file's count is the session's total only when an answer says so with authority, or when
    # nothing can still be writing it (round 8, F-10). Two equal counts of the file are never
    # that: a stalled writer gives exactly two equal counts. With nothing answering, whether a
    # writer is alive is asked first and the file counted after: once none is, it cannot grow.
    if answer is None:
        final, reasons = no_backend_verdict(sessions, sleep=sleep, now=now, since=now())
        held = _settle(path, sleep=sleep, now=now)
    elif why_failed:
        held = _settle(path, sleep=sleep, now=now)
        final, reasons = False, [f"CROOKS OS did not answer the stop ({why_failed}), so what it still had to write "
                                 "is not known; the session was stopped on disk"]
    else:
        held = _settle(path, sleep=sleep, now=now)
        final = stop_is_final(answer)
        reasons = [] if final else unsettled_reasons(answer)
    reports = Path(out_dir) if out_dir else ROOT / "reports"
    paths = {"raw": str(path), "folder": str(reports), "report": "", "proposals": ""}
    artefacts: list[dict] = []
    if analyse:
        for name, write in (("report", _write_report), ("proposals", _write_proposals)):
            try:
                written = write(path, reports)
            except Exception as exc:  # noqa: BLE001 — a failed analysis must not lose the session
                artefacts.append({"name": name, "ok": False, "path": "", "detail": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            paths[name] = str(written)
            artefacts.append({"name": name, "ok": True, "path": str(written), "detail": ""})
    else:
        artefacts.append({"name": "analysis", "ok": False, "path": "", "detail": "not asked for"})
    unwritten = [a["name"] for a in artefacts if not a["ok"] and a["detail"] != "not asked for"]
    if final:
        human = f"Recorded {held} event(s) in {ident}."
    else:
        human = (f"{held} event(s) on disk in {ident} so far — an on-disk snapshot, not final: {'; '.join(reasons)}. "
                 "More may yet land or be dropped. The report is of what was on disk.")
    if unwritten:
        human += " The session is saved; " + ", ".join(unwritten) + " could not be written."
    return {"ok": True, "stopped": True, "test_session_id": ident, "where": where, "events": held, "final": final,
            "not_final_because": reasons, "paths": paths, "artefacts": artefacts, "human": human}


def stop_on_disk(sessions, *, asked_at: float | None = None):
    """The session stopped by its file, with no backend answer to go on. `asked_at`, when the
    backend was asked first and did not answer: a stop it carried out before its answer was lost
    has already moved the session to last.json, and that session is the one stopped, not "none"
    (round 8, F-10). A last session stopped before the ask is not."""
    session = sessions.stop()
    if session is None and asked_at is not None:
        last = sessions.last()
        if last is not None and last.stopped_at is not None and last.stopped_at >= asked_at:
            session = last
    return session


def no_backend_verdict(sessions, *, sleep, now, since: float) -> tuple[bool, list[str]]:
    """Whether a count read with nothing answering on the port is final: only when no process
    still holds the session folder's timeline writer (round 8, F-10). A backend stops listening
    before its own shutdown has flushed, so a refused connection alone is not that. Asked after
    RECHECK_S has passed since the session was stopped on disk: a backend holding the session in
    its one-second cache has either queued its last event by then, holding the writer, or never
    will. (final, reasons)."""
    from app.observability.session import RECHECK_S
    from app.observability.timeline import writer_alive

    left = RECHECK_S + 0.2 - (now() - since)
    if left > 0:
        sleep(left)
    alive = writer_alive(sessions.root)
    if alive is False:
        return True, []
    if alive is True:
        return False, ["CROOKS OS is not answering on its port, but a process still holds the timeline's writer, "
                       "so events may still land"]
    return False, ["CROOKS OS is not answering on its port, and whether anything still holds the timeline's "
                   "writer could not be checked"]


def _write_report(path: Path, out_dir: Path) -> Path:
    from app.observability.report import write_report

    return write_report(path, out_dir)


def _write_proposals(path: Path, out_dir: Path) -> Path:
    from app.observability.proposals import write_proposals

    return write_proposals(path, out_dir)
