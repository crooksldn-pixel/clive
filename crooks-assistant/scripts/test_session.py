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
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _settings():
    from config.settings import get_settings

    return get_settings()


def _call(port: int, method: str, path: str, body: dict | None = None) -> dict | None:
    """The backend on loopback, or None when it is not running."""
    data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 — loopback only
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8") or "{}")
        except ValueError:
            return {"code": f"http {exc.code}"}
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def cmd_start(args) -> int:
    from app.observability.session import AlreadyActive, TestSessions

    settings = _settings()
    name = (args.name or "session").strip()
    answer = _call(settings.port, "POST", "/test-session/start", {"name": name})
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
    if answer is None:
        store = TestSessions.from_settings(settings, always=False)
        active = store.active()
        if active is None:
            last = store.last()
            print("no test session running (backend not running)" + (f"; last: {last.test_session_id}" if last else ""))
            return 0
        from app.observability.timeline import count_events

        held = count_events(store.timeline_path(active))
        print(f"{active.test_session_id}  events={held}  (marked on disk; backend not running)")
        return 0
    if not answer.get("active"):
        last = answer.get("last") or {}
        print("no test session running" + (f"; last: {last.get('test_session_id')}" if last else ""))
        return 0
    counts = answer.get("events") or {}
    written, queued = counts.get("written", "?"), counts.get("queued", "?")
    dropped, mine = counts.get("dropped", "?"), counts.get("this_process", "?")
    print(f"{answer['test_session_id']}  name={answer.get('name')!r}  events={written} (on disk {counts.get('on_disk', '?')}, queued {queued}, dropped {dropped}; {mine} written by the backend running now)")
    print(f"timeline: {answer.get('path')}")
    return 0


def cmd_stop(args) -> int:
    from app.observability.session import TestSessions

    settings = _settings()
    answer = _call(settings.port, "POST", "/test-session/stop")
    if answer is None:
        session = TestSessions.from_settings(settings, always=False).stop()
        if session is None:
            print("no test session running", file=sys.stderr)
            return 1
        print(session.test_session_id)
        return 0
    if not answer.get("stopped"):
        print(answer.get("detail") or "no test session running", file=sys.stderr)
        return 1
    print(answer["test_session_id"])
    counts = answer.get("events") or {}
    print(f"{counts.get('written', '?')} events in {answer.get('path')}", file=sys.stderr)
    print(f"next: make test-session-report SESSION={answer['test_session_id']}", file=sys.stderr)
    return 0


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
    out_dir = Path(args.out) if args.out else ROOT / "reports"
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
    out_dir = Path(args.out) if args.out else ROOT / "reports"
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
    out_dir = Path(args.out) if args.out else ROOT / "reports" / f"{path.stem}{SCREENS_SUFFIX}"
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
