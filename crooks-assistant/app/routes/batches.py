"""POST /batches/{batch_id}/arm, /commit and GET /batches/{batch_id} — the owner's gesture on
a bulk change.

The same boundary as /actions, for a card that stands for many proposals: a batch id and the
session it belongs to, nothing else. The membership, the arguments and the checks were all
decided on the Mac when the batch was staged. Refusals are the same controlled codes.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from app import readonly, screen
from app.actions import grammar
from app.observability import timeline
from app.presentation import present_batch, present_batch_state
from app.routes.actions import (
    _authorise,
    _refuse,
    _write_status_soon,
    session_matches,
    writes_context,
)
from app.speech.speakable import to_speakable

log = logging.getLogger("crooks.actions")

router = APIRouter(prefix="/batches")


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _owner_session(runtime, session_id: str):
    try:
        return runtime.sessions.peek(session_id)
    except KeyError:
        return None


@router.post("/{batch_id}/arm", response_model=None)
async def arm(request: Request, batch_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    runtime = request.app.state.runtime
    caller, refusal = _authorise(request)
    if refusal is not None:
        return refusal
    session_id = session_id.strip()
    if not session_id:
        return _refuse(400, "wrong_session", "The session is missing.")
    owner_session = _owner_session(runtime, session_id)
    if owner_session is not None and not session_matches(owner_session, request):
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")
    pending = runtime.batches.state(batch_id, session_id)
    status = await _write_status_soon(runtime, pending.child_operation if pending is not None else None)
    if not status.ready:
        log.warning("batch arm refused: %s — %s (caller=%s)", status.code, status.detail, caller)
        timeline.emit("batch_arm_refused", session_id=session_id, batch_id=batch_id, code=status.code, detail=status.detail)
        return _refuse(403, status.code, status.detail, status.code)
    batch, code = runtime.batches.arm(batch_id, session_id)
    if batch is None:
        return _refuse(404 if code == "unknown" else 403, code, "No such batch for this session.")
    if code:
        return _refuse(409, code, "That batch is no longer waiting.")
    log.info("batch %s armed by %s", batch.batch_id, caller)
    return {"batch_id": batch.batch_id, "nonce": batch.arm_nonce, "hold_ms": grammar.HOLD_MS, "armed_for_s": grammar.ARMED_FOR_S}


@router.post("/{batch_id}/commit", response_model=None)
async def commit(request: Request, batch_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    started = time.perf_counter()
    runtime = request.app.state.runtime
    caller, refusal = _authorise(request)
    if refusal is not None:
        timeline.emit("batch_commit_refused", session_id=session_id.strip(), batch_id=batch_id, code=getattr(refusal, "crooks_code", ""), ms=_elapsed(started))
        return refusal
    session_id = session_id.strip()
    if not session_id:
        return _refuse(400, "wrong_session", "The session is missing.")
    owner_session = _owner_session(runtime, session_id)
    if owner_session is not None and not session_matches(owner_session, request):
        log.warning("batch commit refused: wrong_session — another login's conversation (caller=%s)", caller)
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")
    pending = runtime.batches.state(batch_id, session_id)
    status = await _write_status_soon(runtime, pending.child_operation if pending is not None else None)
    if not status.ready:
        log.warning("batch commit refused: %s — %s (caller=%s)", status.code, status.detail, caller)
        timeline.emit("batch_commit_refused", session_id=session_id, batch_id=batch_id, code=status.code, detail=status.detail, ms=_elapsed(started))
        return _refuse(403, status.code, status.detail, status.code)

    from app.tools import registry

    def spec_lookup(name: str):
        try:
            return registry.get(name)
        except KeyError:
            return None

    nonce = request.headers.get("x-crooks-arm", "").strip()[:64]
    result = await runtime.batches.commit(batch_id, session_id, caller=caller, spec_lookup=spec_lookup, nonce=nonce)
    if result.batch is None:
        timeline.emit("batch_commit_refused", session_id=session_id, batch_id=batch_id, code=result.code, detail="no such batch", ms=_elapsed(started))
        return _refuse(404 if result.code == "unknown" else 403, result.code, "No such batch for this session.")
    if result.code == "read_only":
        # A backend latched read-only for an acceptance run. Nothing was claimed, so the batch
        # is still PENDING and can be committed for real on a backend that may write.
        log.warning("batch commit refused: read_only — %s", readonly.reason())
        timeline.emit("batch_commit_refused", session_id=session_id, batch_id=batch_id, turn_id=result.batch.turn_id or None, code="read_only", ms=_elapsed(started))
        return _refuse(403, "read_only", "This backend is in read-only test mode and cannot apply changes.")
    if result.code == "not_armed":
        timeline.emit("batch_commit_refused", session_id=session_id, batch_id=batch_id, turn_id=result.batch.turn_id or None, code="not_armed", nonce_present=bool(nonce), ms=_elapsed(started))
        return _refuse(409, "not_armed", "Hold the card first.")
    batch = result.batch
    log.info("batch %s %s → %s (%s) %s", batch.batch_id, batch.operation, batch.status.value, result.code, batch.counts)
    timeline.emit(
        "batch_commit", session_id=session_id, batch_id=batch.batch_id, turn_id=batch.turn_id or None, operation=batch.operation,
        code=result.code, status=batch.status.value, counts=dict(batch.counts) or None, spoken=result.spoken, nonce_present=bool(nonce), undo_id=batch.undo_id, ms=_elapsed(started),
    )
    if result.spoken:
        runtime.voice.prefetch(to_speakable(result.spoken, max_chars=runtime.voice.max_chars), pin=False)
    session = _owner_session(runtime, session_id)
    if session is not None and result.code == "done":
        # The next question is asked with the outcome in hand: "did that work?" is answered
        # from what the Mac counted, never guessed (app/routes/turn.py).
        session.last_outcome = result.spoken
    # The half's own copy of its screen settled to what the tablet now draws: the count in the
    # batch card's place, and the list it was about still there (app/screen.py).
    ui = screen.after_gesture(present_batch(result, session=session, writes=await writes_context(request, batch.child_operation)),
                              session=session, proposal_id=batch.batch_id, undo_of=batch.undo_of or "")
    return {
        **batch.public(),
        "code": result.code,
        "spoken": result.spoken,
        "ui": ui,
        "undo": _undo_of(batch, session),
    }


def _undo_of(batch, session) -> dict | None:
    if not batch.undo_id or session is None:
        return None
    undo_batch = session.batches.get(batch.undo_id)
    return undo_batch.public() if undo_batch is not None and undo_batch.status.value == "PENDING" else None


@router.get("/{batch_id}", response_model=None)
async def state(request: Request, batch_id: str, session_id: str = "") -> JSONResponse | dict:
    runtime = request.app.state.runtime
    batch = runtime.batches.state(batch_id, session_id.strip())
    if batch is None:
        return _refuse(404, "unknown", "No such batch for this session.")
    session = _owner_session(runtime, session_id.strip())
    if session is not None and not session_matches(session, request):
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")
    writes = await writes_context(request, batch.child_operation)
    # A tablet that lost the connection mid-run gets what the answer would have carried:
    # the counted line and the undo, not only the status.
    return {**batch.public(), "ui": present_batch_state(batch, session=session, writes=writes), "undo": _undo_of(batch, session)}
