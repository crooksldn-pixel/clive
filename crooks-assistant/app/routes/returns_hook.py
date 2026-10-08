"""CROOKS Returns' doorbell at the public door: POST /hooks/returns (DEC-077, the owner's ruling 20).

Why it exists: the returns service runs beside CLIVE, not in it, and reaches CLIVE the way WeCom and
Meta do, through hooks.crooksldn.com. This is its one address. Like the other doors (app/routes/
hooks.py) it is on the exact-path list app/main.py lets through without an owner (HOOK_PATHS), and it
carries no authority of any kind: no tool can run from here, and all an event can do is make CLIVE
read the service again with its own key (app/returns/events.py).

What it promises, for every request:
1. A body larger than 4 KB (said or sent) is refused before it is read whole, and at most four are
   read at once (the same count as each messaging door).
2. The signature is checked before anything else is done with the body; then its shape, then that it
   was sent within five minutes, then that it is new (app/returns/events.py `verify`, `first_time`).
3. Anything refused gets 403 with an empty body; a GET always does. No reason, no echo.
4. An accepted event, or a repeat of one, gets 200 with an empty body at once: the reads it starts
   run after the answer, so the service is never kept waiting on the service.
5. Nothing a request carried is logged; refusals are counted by kind (app/messaging/guard.py).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.messaging.guard import GUARD
from app.returns import events
from app.routes import hooks

router = APIRouter()
CHANNEL = "returns"


@router.get(hooks.RETURNS_HOOK, include_in_schema=True)
async def returns_hook_get(request: Request) -> Response:
    """Nothing to check here: the service only ever posts."""
    GUARD.refuse(CHANNEL, "method")
    return hooks._refused()


@router.post(hooks.RETURNS_HOOK, include_in_schema=True)
async def returns_hook(request: Request) -> Response:
    """An event CROOKS Returns recorded: its id, type, return and time, signed."""
    if not hooks._reading(CHANNEL):
        GUARD.refuse(CHANNEL, "busy")
        return hooks._refused()
    try:
        raw = await hooks._bounded_body(request, events.MAX_BODY)
        if raw is None:
            GUARD.refuse(CHANNEL, "size")
            return hooks._refused()
        try:
            event = events.verify(raw, request.headers.get(events.SIGNATURE_HEADER, ""),
                                  key=events.secret(), now=time.time())
        except events.Refused as refused:
            GUARD.refuse(CHANNEL, refused.why)
            return hooks._refused()
        except Exception:  # noqa: BLE001 - anyone can post here: whatever went wrong, an empty 403, never a 500
            GUARD.refuse(CHANNEL, "error")
            return hooks._refused()
        if not events.DOOR.first_time(event.id):
            events.DOOR.counts["repeats"] += 1
            return Response(status_code=200, content=b"")
        events.DOOR.ring(event)
        return Response(status_code=200, content=b"")
    finally:
        hooks._done_reading(CHANNEL)
