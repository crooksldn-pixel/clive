#!/usr/bin/env python3
"""The test session, from the Mac's terminal.

    make test-session-start [NAME="first hour"]   begin; prints the session id
    make test-session-status                       what is running, and how many events so far
    make test-session-stop                         end it
    make test-session-report [SESSION=ts-…]        write reports/<session>.md from the timeline
    make test-session-screens [SESSION=ts-…]       draw the screens the page sent (CROOKS_SCREEN_SNAPSHOTS)
                                                   as reports/<session>-screens/index.html

Start, status and stop talk to the running backend on loopback, so nothing restarts. When the
backend is not running they work the session file directly (logs/test-sessions/active.json),
and the backend picks the state up within a second of its next event. The report needs no
backend at all: it reads the JSONL and writes the Markdown.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _settings():
    from config.settings import get_settings

    return get_settings()


def _call(port: int, method: str, path: str, body: dict | None = None) -> dict | None:
    """The backend on loopback: its answer; None only when nothing is listening (the connection
    was refused); {"call_failed": why} when it timed out or failed some other way, which is not
    "not running" (round 8, F-10). The Control app's own call (scripts/session_ops.py), so the
    two can never tell these apart differently. It carries the server's own key for these
    commands (app/local_cli.py) when this user can read it: root on the server."""
    from scripts import session_ops

    return session_ops.call(port, method, path, body)


def _failed(answer: dict | None) -> str:
    from scripts import session_ops

    return session_ops.failed(answer)


def cmd_start(args) -> int:
    from app.observability.session import AlreadyActive, TestSessions

    settings = _settings()
    name = (args.name or "session").strip()
    answer = _call(settings.port, "POST", "/test-session/start", {"name": name})
    if why := _failed(answer):
        # Running but not answering: it may have started it, so nothing is marked on disk over it.
        print(f"CROOKS OS did not answer ({why}), so whether the session started is not known; "
              "run make test-session-status before starting another", file=sys.stderr)
        return 1
    if answer is not None:
        if answer.get("started"):
            print(answer["test_session_id"])
            print(f"recording to {answer['path']}", file=sys.stderr)
            return 0
        print(answer.get("detail") or answer, file=sys.stderr)
        return 1
    # No backend: mark the session on disk; the backend reads it when it next writes an event.
    try:
        store = TestSessions.from_settings(settings, always=False)
        store.prune()
        session = store.start(name)
    except AlreadyActive as exc:
        print(f"A test session is already running: {exc}. Stop it first.", file=sys.stderr)
        return 1
    print(session.test_session_id)
    print("the backend is not running here; the session is marked on disk and starts recording when it is (make up)", file=sys.stderr)
    return 0


def cmd_status(args) -> int:
    from app.observability.session import TestSessions

    settings = _settings()
    answer = _call(settings.port, "GET", "/test-session/status")
    why = _failed(answer)
    if answer is None or why:
        # The files on disk, said as that; "backend not running" only when nothing is listening.
        backend = f"backend did not answer: {why}" if why else "backend not running"
        store = TestSessions.from_settings(settings, always=False)
        active = store.active()
        if active is None:
            last = store.last()
            print(f"no test session running ({backend})" + (f"; last: {last.test_session_id}" if last else ""))
            return 0
        from app.observability.timeline import count_events

        held = count_events(store.timeline_path(active))
        print(f"{active.test_session_id}  events on disk={held}  (marked on disk; {backend})")
        return 0
    _say_recording(answer)
    if not answer.get("active"):
        last = answer.get("last") or {}
        print("no test session running" + (f"; last: {last.get('test_session_id')}" if last else ""))
        return 0
    counts = answer.get("events") or {}
    written, pending = counts.get("written", "?"), counts.get("pending", counts.get("queued", "?"))
    dropped, mine = counts.get("dropped", "?"), counts.get("this_process", "?")
    print(f"{answer['test_session_id']}  name={answer.get('name')!r}  events on disk={written} (still to write {pending}, "
          f"which may yet be dropped; dropped {dropped}; {mine} written by the backend running now)")
    print(f"timeline: {answer.get('path')}")
    return 0


def _say_recording(answer: dict) -> None:
    """The interaction record, said apart from any test (app/observability/interactions.py)."""
    held = answer.get("recording") if isinstance(answer.get("recording"), dict) else None
    if held:
        print(f"interaction record: on, today's day {held.get('day')}, {held.get('keep_days')} days kept, "
              f"words {held.get('words')} ({held.get('folder')})")


def cmd_stop(args) -> int:
    import time

    from app.observability.session import TestSessions
    from scripts import session_ops

    settings = _settings()
    store = TestSessions.from_settings(settings, always=False)
    asked_at = store.clock()
    answer = _call(settings.port, "POST", "/test-session/stop")
    why = _failed(answer)
    if answer is None or why:
        # Stopped by its file. Its count is final only when nothing can still be writing it:
        # with nothing listening, once no process holds the timeline's writer; with a backend that
        # did not answer, never (round 8, F-10).
        session = session_ops.stop_on_disk(store, asked_at=asked_at if why else None)
        if session is None:
            print(f"CROOKS OS did not answer the stop ({why}), and no test session is marked running on disk"
                  if why else "no test session running", file=sys.stderr)
            return 1
        print(session.test_session_id)
        path = store.timeline_path(session)
        if why:
            final, reasons = False, [f"CROOKS OS did not answer the stop ({why}), so what it still had to write is "
                                     "not known; the session was stopped on disk"]
        else:
            final, reasons = session_ops.no_backend_verdict(store, sleep=time.sleep, now=time.monotonic,
                                                            since=time.monotonic())
        from app.observability.timeline import count_events

        held = count_events(path)
        if final:
            print(f"{held} events in {path} (final; stopped on disk, and nothing is still writing it)", file=sys.stderr)
        else:
            print(f"{held} events in {path} so far, an on-disk snapshot, not final: {'; '.join(reasons)}. "
                  "More may yet land or be dropped.", file=sys.stderr)
        return 0
    if not answer.get("stopped"):
        print(answer.get("detail") or "no test session running", file=sys.stderr)
        return 1
    print(answer["test_session_id"])
    print(stopped_line(answer), file=sys.stderr)
    print(f"next: make test-session-report SESSION={answer['test_session_id']}", file=sys.stderr)
    return 0


def stopped_line(answer: dict) -> str:
    """What a stop says about the count: final only when the backend said nothing was still being
    written (the 2026-09-27 deploy review, round 6, F-10). Otherwise the file's count so far, and
    how many events were still pending, which may yet land or be dropped."""
    from app.observability.timeline import stop_is_final, unsettled_reasons

    counts = answer.get("events") if isinstance(answer.get("events"), dict) else {}
    on_disk = counts.get("on_disk", counts.get("written", "?"))
    path = answer.get("path")
    if stop_is_final(answer):
        return f"{on_disk} events in {path} (final; {counts.get('dropped', 0)} dropped)"
    # The same reasons the Control app gives (round 8, F-10): a flush that did not settle is
    # said as that, never as a pending count that has since reached nought.
    return (f"{on_disk} events in {path} so far, an on-disk snapshot, not final: {'; '.join(unsettled_reasons(answer))}. "
            "More may yet land or be dropped. Run make test-session-status to see it settle.")


def _prune_reports(out_dir: Path, settings) -> None:
    """Reports go when the sessions they were drawn from would (test_session_keep_named_days)."""
    from app.observability.session import KEEP_NAMED_DAYS, prune_reports

    prune_reports(out_dir, int(getattr(settings, "test_session_keep_named_days", KEEP_NAMED_DAYS) or KEEP_NAMED_DAYS))


def cmd_report(args) -> int:
    from app.observability.report import write_report
    from app.observability.session import TestSessions

    settings = _settings()
    store = TestSessions.from_settings(settings, always=False)
    path = Path(args.session) if args.session and args.session.endswith(".jsonl") and Path(args.session).exists() else store.find(args.session or "")
    if path is None:
        print("no timeline found" + (f" for {args.session!r}" if args.session else ": start and stop a session first"), file=sys.stderr)
        return 1
    out_dir = Path(args.out) if args.out else Path(getattr(settings, "reports_dir", ROOT / "reports"))
    _prune_reports(out_dir, settings)
    written = write_report(path, out_dir)
    print(written)
    return 0


def cmd_proposals(args) -> int:
    from app.observability.proposals import write_proposals
    from app.observability.session import TestSessions

    settings = _settings()
    store = TestSessions.from_settings(settings, always=False)
    path = Path(args.session) if args.session and args.session.endswith(".jsonl") and Path(args.session).exists() else store.find(args.session or "")
    if path is None:
        print("no timeline found" + (f" for {args.session!r}" if args.session else ": start and stop a session first"), file=sys.stderr)
        return 1
    out_dir = Path(args.out) if args.out else Path(getattr(settings, "reports_dir", ROOT / "reports"))
    _prune_reports(out_dir, settings)
    written = write_proposals(path, out_dir)
    print(written)
    return 0


def cmd_screens(args) -> int:
    """Draw the session's screen copies with Playwright (scripts/browser/session_screens.js)."""
    import subprocess

    from app.observability.session import SCREENS_SUFFIX, TestSessions, private_dir

    settings = _settings()
    store = TestSessions.from_settings(settings, always=False)
    path = Path(args.session) if args.session and args.session.endswith(".jsonl") and Path(args.session).exists() else store.find(args.session or "")
    if path is None:
        print("no timeline found" + (f" for {args.session!r}" if args.session else ""), file=sys.stderr)
        return 1
    screens = path.with_name(path.stem + SCREENS_SUFFIX)
    if not screens.is_dir() or not any(screens.glob("*.json")):
        print(f"no screens were kept for {path.stem}: is CROOKS_SCREEN_SNAPSHOTS=true, and has the page been used since?", file=sys.stderr)
        return 1
    out_dir = Path(args.out) if args.out else Path(getattr(settings, "reports_dir", ROOT / "reports")) / f"{path.stem}{SCREENS_SUFFIX}"
    _prune_reports(out_dir.parent, settings)
    private_dir(out_dir)   # the drawing script writes its pictures 0600 inside it (umask 077)
    script = ROOT / "scripts" / "browser" / "session_screens.js"
    done = subprocess.run(["node", str(script), str(screens), str(out_dir), str(ROOT / "web")], check=False)
    if done.returncode != 0:
        print("drawing failed: is Playwright installed (npm install -g playwright, then npx playwright install chromium)?", file=sys.stderr)
        return done.returncode
    print(out_dir / "index.html")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="begin a named test session")
    start.add_argument("--name", default="session")
    sub.add_parser("status", help="the session in progress")
    sub.add_parser("stop", help="end the session in progress")
    report = sub.add_parser("report", help="write reports/<session>.md")
    report.add_argument("session", nargs="?", default="", help="a session id, its prefix, or a .jsonl path; default: the active or last session")
    report.add_argument("--out", default="", help="directory for the report (default: reports/)")
    proposals = sub.add_parser("proposals", help="write reports/<session>-proposals.md: improvement candidates, cited by turn, never applied")
    proposals.add_argument("session", nargs="?", default="", help="a session id, its prefix, or a .jsonl path; default: the active or last session")
    proposals.add_argument("--out", default="", help="directory for the file (default: reports/)")
    screens = sub.add_parser("screens", help="draw the session's screens as reports/<session>-screens/index.html")
    screens.add_argument("session", nargs="?", default="", help="a session id, its prefix, or a .jsonl path; default: the active or last session")
    screens.add_argument("--out", default="", help="directory for the pictures (default: reports/<session>-screens/)")
    args = parser.parse_args(argv)
    return {"start": cmd_start, "status": cmd_status, "stop": cmd_stop, "report": cmd_report, "proposals": cmd_proposals,
            "screens": cmd_screens}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
