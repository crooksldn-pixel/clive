"""The CROOKS PAD's own two routes.

  POST /pad/heartbeat  {app_version, device_model, os_version, at, boot_id, events?}
  GET  /pad            what the server knows about the pad

Both are the owner's (the 2026-09-27 deploy review, F-NEW-PAD): the door in app/main.py refuses
anyone else before either runs, and each checks again itself, so neither rests on the other.

Why a route of its own rather than another field on /telemetry
--------------------------------------------------------------
/telemetry is the WEB PAGE's account of itself, and it is silent unless a test session is
running — which is right for it, because what it reports is what the page rendered. The
appliance's liveness is a different thing: it has to be true at three in the morning with no
session running, because the whole point of it is that the Control app on the Mac can say
whether the tablet in the shop is alive. So a heartbeat is taken whatever is or is not being
recorded, and the `pad_*` events that may ride along with it are handed to the timeline, which
decides — exactly as it does for everything else — whether there is anywhere to put them.

What this route will not do
---------------------------
It stages nothing, executes nothing and holds no nonce. It writes two things: the registry's
in-memory view of the pad, and (at most) timeline events. There is no field it accepts that
reaches an action, a tool or a shell. The identity strings it stores are filtered to a safe
character set and then passed through the timeline's own scrub, because they end up on /health,
in the Control app and in reports.

The answer is deliberately small and deliberately useful: it tells the appliance the cadence
this backend expects, so the interval is one number in one place rather than a constant copied
into Kotlin, and whether a test session is running, so the pad can turn its own telemetry on
within one beat without a second request.

How far the heartbeat can be trusted
------------------------------------
As far as the owner rule (app/routes/actions.py principal_verdict): a heartbeat is believed
only from a device Tailscale says is one of the owner's, or — when CROOKS_LOCAL_OWNER is set —
from the server itself. A process on the server that is not him, with that switch off (as in
production), is refused: it can neither write pad events into a test session nor learn whether
one is recording. Nothing is authorised by a heartbeat either way: it moves no money, stages no
action and unlocks no route.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.observability import pad as pad_module

log = logging.getLogger("crooks.observe")

router = APIRouter()

# A heartbeat is a few short strings and, at most, fifty small events. Anything larger is not a
# heartbeat, and is refused before it is parsed.
MAX_BODY_BYTES = 16_000


def _refused(request: Request) -> JSONResponse | None:
    """The owner rule, as a 403 with its code; None when the caller is the owner. The same rule
    the door applies — kept here as well so this route does not depend on the door's list."""
    from app.routes.actions import principal_verdict

    _who, code, why = principal_verdict(request)
    if code:
        log.warning("pad route refused: %s (path=%s)", code, request.url.path)
        return JSONResponse(status_code=403, content={"code": code, "detail": why})
    return None


@router.post("/pad/heartbeat", response_model=None)
async def heartbeat(request: Request) -> JSONResponse | dict:
    """The pad saying it is alive, and what it is.

    Answers 200 with the cadence and the recording state, or 400 for a body that is not a
    heartbeat. It answers rather than 204ing because the appliance USES the answer — a 4xx or a
    connection failure here is precisely how the pad learns the backend has gone, which is what
    `pad_backend_unreachable` is reporting when it arrives.
    """
    if (refused := _refused(request)) is not None:
        return refused
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return JSONResponse(status_code=400, content={"code": "too_large", "detail": "A heartbeat is small."})
    try:
        body = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        return JSONResponse(status_code=400, content={"code": "not_json", "detail": "A heartbeat is one JSON object."})
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"code": "not_json", "detail": "A heartbeat is one JSON object."})

    registry = pad_module.current()
    status = registry.heartbeat(
        app_version=body.get("app_version"),
        device_model=body.get("device_model"),
        os_version=body.get("os_version"),
        boot_id=body.get("boot_id"),
        at=body.get("at"),
        # What the shell says is on its screen. Optional, and unguessed when absent: see
        # WEBVIEW_STATES in app/observability/pad.py for why a live app is not a loaded CROOKS.
        webview=body.get("webview"),
    )
    # The events, if the appliance batched any onto this beat. Bounded, collapsed and scrubbed by
    # the registry and the timeline; nothing here decides what a field may say.
    taken = registry.record(body.get("events"))

    runtime = request.app.state.runtime
    timeline = getattr(runtime, "timeline", None)
    session = timeline.active if timeline is not None else None
    return {
        "ok": True,
        "build": getattr(runtime, "build", ""),
        # One number in one place: the appliance reads its own cadence from the backend rather
        # than carrying a constant that can drift away from STALE_AFTER_S.
        "interval_s": pad_module.HEARTBEAT_INTERVAL_S,
        "stale_after_s": pad_module.STALE_AFTER_S,
        # So the pad can start and stop its own telemetry within one beat and without a second
        # request. Never the session's NAME — that is the owner's words, and the pad has no use
        # for it.
        "recording": session is not None,
        "events": taken,
        "pad": {"state": status["state"], "connected": status["connected"], "showing_crooks": status["showing_crooks"]},
    }


@router.get("/pad", response_model=None)
async def pad(request: Request) -> JSONResponse | dict:
    """What the server knows about the pad, with no network call and no cache behind it.

    The owner's only. /health carries the same block for the Control app's ordinary poll;
    this is here for when something wants the liveness answer on its own, without paying for a
    Shopify query and a Gmail profile to get it.
    """
    if (refused := _refused(request)) is not None:
        return refused
    return pad_module.current().status()
