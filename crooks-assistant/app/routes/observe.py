"""The test session, controlled from the Mac, and the tablet's own account of what it did.

  POST /test-session/start   {name}   begin a named session (the owner only)
  GET  /test-session/status           the session in progress, if any (the owner only)
  POST /test-session/stop             end it (the owner only)
  POST /telemetry            {session_id, events: [...]}   the tablet's batch; always 204
  POST /telemetry/screen     {session_id, reason, html, …}  a copy of the screen; always 204
  GET  /anticipation                  why anything was prefetched (the owner only)
  POST /anticipation/reset            forget every learned pattern (the owner only)

Every route here is the owner's alone (the 2026-09-27 deploy review, F-05A), by the same rule
as his objectives and screens (app/routes/actions.py principal_check): one of his own devices,
confirmed by Tailscale, or the server itself when CROOKS_WRITES_LOCAL_OWNER says it is him.
Nothing else starts, reads or stops a session, reads or resets what anticipation learned, or
puts an event in the record, whatever it can reach the port from: the door refuses it first
(app/main.py, every route but the public ones), and each route here checks again. Telemetry
is bounded, and dropped without a word when it names a conversation that belongs to another
login. Nothing is ever
waited for by the tablet: the answer is 204 before the events are written."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.observability.screens import sanitise_markup, screen_metadata
from app.observability.session import AlreadyActive
from app.observability.timeline import scrub_text

log = logging.getLogger("crooks.observe")

router = APIRouter()

MAX_BODY_BYTES = 64_000
MAX_EVENTS = 200
MAX_STRING = 2_000
MAX_DEPTH = 6
_KIND = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# What a tablet event may carry. Anything else is dropped: the page is ours, but the route
# is reachable by every login the Mac admits, and the file is read by a report.
ALLOWED_FIELDS = frozenset({
    "kind", "t", "session_id", "turn_id", "proposal_id", "context_request_id", "screen", "entity", "entities", "items",
    "cards", "tabs", "actions", "confirmations", "viewport", "document", "overflow", "images", "from", "to", "label",
    "action", "gesture", "target", "state", "code", "reason", "message", "file", "line", "col", "src", "status",
    "ms", "via", "nav", "phase", "order_id", "question", "attention", "outcome", "depth", "count", "id", "name",
    "history", "mode", "skipped", "errors", "scroll", "height", "width", "aborted", "offline", "seq", "answer_chars",
    "audio_ms", "turns", "error_kind", "detail", "chars", "before", "after", "reachable", "elapsed_ms", "index",
    "fixture", "kept", "cancelled",
    # How many fingers were on the orb. A count, like every other field here, and the one
    # that lets the report tell a gesture that ended a recording from a recogniser that could
    # make nothing of it — six turns of the live session were filed as the recogniser's.
    "fingers", "relations", "fields", "cursor", "total", "entity_kind",
    # V0.5 invariant 11. What one interaction FELT like, so acknowledgement latency,
    # transcript correction, time-to-first-useful-result, progression, completion, errors and
    # abandonment can be assessed afterwards. Milliseconds and counts, every one of them:
    # `heard_chars` is how MUCH was said, and the tablet's state machine (web/live-state.js)
    # is never given a word of the conversation, so there is nothing here that could carry
    # one. This list is an allow-list precisely so that stays true.
    "ack_ms", "transcript_ms", "progress_ms", "useful_ms", "responding_ms",
    "partials", "heard_chars", "interruptions", "faults",
    # The phone's home, its bar and its sheets (web/alpha.js), and a request that came back
    # refused: where it was tapped, which control, what the server answered.
    "path", "control",
})

MAX_SCREEN_BYTES = 1_500_000
MAX_SCREENS = 600          # per session: a day of heavy use is a few hundred
_REASON = re.compile(r"[^a-z0-9_]+")


def _refused(request: Request) -> JSONResponse | None:
    """The owner-only rule, as a 403 with its reason; None when the caller is the owner, or is
    the server's own test-session command with its key (app/local_cli.py: those three routes
    only, and never an owner anywhere else)."""
    from app import local_cli
    from app.routes.actions import principal_check

    if local_cli.admits(request):
        return None
    who, why = principal_check(request)
    if why:
        log.warning("observe route refused: %s (path=%s)", why, request.url.path)
        return JSONResponse(status_code=403, content={"code": "not_owner", "detail": why})
    return None


def _summary(session) -> dict[str, Any]:
    return {"test_session_id": session.test_session_id, "name": session.name, "started_at": session.started_at, "stopped_at": session.stopped_at}


@router.post("/test-session/start", response_model=None)
async def start(request: Request) -> JSONResponse | dict:
    if (refused := _refused(request)) is not None:
        return refused
    runtime = request.app.state.runtime
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    name = str((body or {}).get("name") or "").strip()[:80] if isinstance(body, dict) else ""
    try:
        session = runtime.timeline.start(name or "session")
    except AlreadyActive as exc:
        return JSONResponse(status_code=409, content={"code": "already_active", "detail": f"A test session is already running: {exc}. Stop it first.", "test_session_id": str(exc)})
    log.info("test session started: %s", session.test_session_id)
    return {"started": True, **_summary(session), "path": str(runtime.tests.timeline_path(session))}


@router.get("/test-session/status", response_model=None)
async def status(request: Request) -> JSONResponse | dict:
    if (refused := _refused(request)) is not None:
        return refused
    runtime = request.app.state.runtime
    session = runtime.timeline.active
    if session is None:
        last = runtime.tests.last()
        return {"active": False, "last": _summary(last) if last else None}
    return {"active": True, **_summary(session), "path": str(runtime.tests.timeline_path(session)), "events": runtime.timeline.counts}


@router.post("/test-session/stop", response_model=None)
async def stop(request: Request) -> JSONResponse | dict:
    if (refused := _refused(request)) is not None:
        return refused
    runtime = request.app.state.runtime
    session = runtime.timeline.stop()
    if session is None:
        return {"stopped": False, "detail": "No test session is running."}
    log.info("test session stopped: %s", session.test_session_id)
    return {"stopped": True, **_summary(session), "path": str(runtime.tests.timeline_path(session)), "events": runtime.timeline.counts}


@router.get("/anticipation", response_model=None)
async def anticipation(request: Request, scope: str = "") -> JSONResponse | dict:
    """Why was this prefetched? (§19's debug view.)

    Every prediction the layer has made — the rule or the learned transition behind it, its
    confidence, how many observations were behind that, and whether it landed — beside the
    learned table itself with its arithmetic shown. The owner only: this is his view of what
    his machine has been guessing about him, and it is nobody else's business.
    """
    if (refused := _refused(request)) is not None:
        return refused
    from app.anticipation import engine as anticipation_mod

    return anticipation_mod.current().report(scope=str(scope or "")[:120])


@router.post("/anticipation/reset", response_model=None)
async def anticipation_reset(request: Request) -> JSONResponse | dict:
    """Forget every learned pattern. The owner only; §19 asks for resettable and this is it —
    the table goes, its file goes, and nothing that was learned survives."""
    if (refused := _refused(request)) is not None:
        return refused
    from app.anticipation import engine as anticipation_mod

    dropped = anticipation_mod.current().learner.reset()
    log.info("the learned anticipation table was reset (%s transitions)", dropped)
    return {"reset": True, "transitions_dropped": dropped, "learned": anticipation_mod.current().learner.inspect()}


@router.post("/telemetry")
async def telemetry(request: Request) -> Response:
    """The tablet's batch. 204 whatever happens: the page never learns anything from this
    route and never waits on it. Events are kept only while a session is active."""
    runtime = request.app.state.runtime
    timeline = runtime.timeline
    if timeline.active is None:
        return Response(status_code=204)
    from app.routes.actions import principal_check

    # The owner's devices only put events in the record (F-05A): anything else is dropped here.
    if principal_check(request)[1]:
        return Response(status_code=204)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return Response(status_code=204)
    try:
        import json

        body = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        return Response(status_code=204)
    if not isinstance(body, dict):
        return Response(status_code=204)
    session_id = str(body.get("session_id") or "")[:64]
    if session_id:
        from app.routes.actions import session_matches

        try:
            owner = runtime.sessions.peek(session_id)
        except KeyError:
            owner = None
        if owner is not None and not session_matches(owner, request):
            return Response(status_code=204)
    events = body.get("events")
    if not isinstance(events, list):
        return Response(status_code=204)
    received = 0
    appliance = 0
    for item in events[:MAX_EVENTS]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if not _KIND.match(kind):
            continue
        if kind.startswith("pad_"):
            # The appliance's prefix, and this is not the appliance's door. The pad's events
            # ride its own heartbeat (`app/routes/pad.py` -> `app/observability/pad.py`), where
            # they are checked against a vocabulary, bounded, collapsed, rate-limited, and
            # counted as accepted or refused on /health. Taken here they would be renamed
            # `tablet_pad_*` by the emit below: a kind no producer emits, which the analyser
            # files under the TABLET rather than the appliance because it matches the tablet
            # prefix first, which section 17 of the report therefore never sees, and which the
            # pad registry's counts know nothing about. One fact arriving by two doors under two
            # names is worse than one door, so this door says no — out loud, because a page
            # sending these is a producer that has the contract wrong and somebody has to be
            # able to find out.
            appliance += 1
            continue
        fields = {k: _bounded(v) for k, v in item.items() if k in ALLOWED_FIELDS and k != "kind"}
        fields.setdefault("session_id", session_id or None)
        timeline.emit(f"tablet_{kind}", source="tablet", **fields)
        received += 1
    if appliance:
        log.warning("%s appliance event(s) were POSTed to /telemetry and refused: pad_* events "
                    "belong on POST /pad/heartbeat", appliance)
    return Response(status_code=204, headers={"X-Crooks-Telemetry": str(received)})


@router.post("/telemetry/screen")
async def telemetry_screen(request: Request) -> Response:
    """A copy of what the page was showing (CROOKS_SCREEN_SNAPSHOTS), kept beside the test
    session's timeline so `make test-session-screens` can draw it as a picture. 204 whatever
    happens, and nothing kept unless snapshots are on and a test session of this timeline's own
    is running: a production recording never keeps a screen."""
    runtime = request.app.state.runtime
    timeline = runtime.timeline
    session = timeline.own
    if session is None or not getattr(runtime.settings, "screen_snapshots", False):
        return Response(status_code=204)
    from app.routes.actions import principal_check

    # Only the owner's own devices, confirmed, put a picture in the record (F-05).
    if principal_check(request)[1]:
        return Response(status_code=204)
    raw = await request.body()
    if not raw or len(raw) > MAX_SCREEN_BYTES:
        return Response(status_code=204)
    try:
        import json

        body = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        return Response(status_code=204)
    if not isinstance(body, dict) or not isinstance(body.get("html"), str):
        return Response(status_code=204)
    # Kept only for a conversation this caller holds (the 2026-09-26 deploy review, F-05): a copy
    # that names no conversation, or one this server does not know, or someone else's, is
    # dropped. Being on the tailnet's allow-list is not enough to put a picture in the record.
    session_id = str(body.get("session_id") or "")[:64]
    if not session_id:
        return Response(status_code=204)
    from app.routes.actions import session_matches

    try:
        owner = runtime.sessions.peek(session_id)
    except KeyError:
        owner = None
    if owner is None or not session_matches(owner, request):
        return Response(status_code=204)
    folder = runtime.tests.screens_dir(session)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
        if sum(1 for _ in folder.glob("*.json")) >= MAX_SCREENS:
            return Response(status_code=204)
        seq = sum(1 for _ in folder.glob("*.json")) + 1
        reason = _REASON.sub("_", str(body.get("reason") or "screen").lower())[:24].strip("_") or "screen"
        name = f"{seq:04d}-{reason}.json"
        keep = {
            "reason": reason,
            "t": body.get("t") if isinstance(body.get("t"), (int, float)) else None,
            "session_id": session_id or None,
            "turn_id": scrub_text(str(body.get("turn_id") or "")[:64]) or None,
            # Rebuilt from the keys the page sends, never copied (round 6, F-02).
            "trigger": screen_metadata("trigger", body.get("trigger")),
            "viewport": screen_metadata("viewport", body.get("viewport")),
            "body": screen_metadata("body", body.get("body")),
            "lite": bool(body.get("lite")),
            "html": scrub_screen(body["html"]),
        }
        import os

        fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(keep, ensure_ascii=False).encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        log.warning("a screen snapshot was not kept: %s", type(exc).__name__)
        return Response(status_code=204)
    timeline.emit("tablet_screen", source="tablet", session_id=session_id or None, turn_id=keep["turn_id"],
                  reason=reason, file=name)
    return Response(status_code=204)


def scrub_screen(html: str) -> str:
    """A copy of the screen, parsed and cleaned whatever the page sent (app/observability/screens.py)."""
    return sanitise_markup(html)


def _bounded(value: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        return None
    if isinstance(value, dict):
        return {str(k)[:40]: _bounded(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_bounded(v, depth + 1) for v in value[:100]]
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    return str(value)[:MAX_STRING]
