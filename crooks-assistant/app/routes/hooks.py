"""The one public door for messages coming in: GET and POST /hooks/wecom.

Why it exists: WeCom delivers a message by calling an address on the internet, so CLIVE needs one
address the public can reach. Everything else CLIVE serves stays behind the door in app/main.py
(the owner, or a member of the team he let in, through Tailscale); only the paths in HOOK_PATHS
skip it, and they carry no authority of any kind: no tool can run from here.

What it promises, in this order, for every request:
1. A body larger than MAX_BODY_BYTES is refused before it is read whole.
2. The channel's adapter checks the signature before anything else is done with the request,
   then the timestamp window and that it is new (app/messaging/guard.py), then decrypts it.
3. Anything refused gets 403 with an empty body: no reason, no echo, nothing to learn from.
4. WeCom's URL check (the GET when the URL is saved) gets the decrypted echo, as plain text.
5. A message gets 200 with an empty body at once, as WeCom asks (answer in five seconds; 90238),
   and is stored and translated after (app/messaging/ingest.py). A repeat of one already
   accepted gets the same 200 and is dropped.
6. Nothing a request carried is logged: app/logging/quiet.py keeps the query off the access line.

WhatsApp and Instagram add their own paths here when they land, each with its own adapter.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from app.messaging import adapter as adapters
from app.messaging import ingest
from app.messaging.guard import GUARD, MAX_BODY_BYTES

log = logging.getLogger("crooks.hooks")

router = APIRouter()

# The only paths the door in app/main.py lets through without an owner or a member of the team.
# Exact paths, never prefixes: /hooks/wecom/x and /hooks/other stay behind the door.
HOOK_PATHS = frozenset({"/hooks/wecom"})
CHANNEL_OF = {"/hooks/wecom": "wecom"}


def is_hook(path: str) -> bool:
    return path in HOOK_PATHS


def _refused() -> Response:
    return Response(status_code=403, content=b"", headers={"Cache-Control": "no-store"})


async def _bounded_body(request: Request) -> bytes | None:
    """The body, or None when it is (or claims to be) larger than MAX_BODY_BYTES."""
    declared = request.headers.get("content-length", "")
    if declared:
        try:
            if int(declared) > MAX_BODY_BYTES:
                return None
        except ValueError:
            return None
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > MAX_BODY_BYTES:
            return None
    return bytes(received)


async def _door(request: Request) -> Response:
    channel = CHANNEL_OF.get(request.url.path, "")
    adapter = adapters.get(channel)
    if adapter is None:
        return _refused()
    body = b""
    if request.method == "POST":
        held = await _bounded_body(request)
        if held is None:
            GUARD.refuse(channel, "size")
            return _refused()
        body = held
    try:
        inbound = adapter.verify_inbound(request.method, request.query_params, body)
    except adapters.Refused as refused:
        GUARD.refuse(channel, refused.why)
        return _refused()
    if inbound.echo is not None:
        return PlainTextResponse(inbound.echo, headers={"Cache-Control": "no-store"})
    if inbound.fields.get("_repeat"):
        ingest.COUNTS["repeats"] += 1
        return Response(status_code=200, content=b"")
    ingest.start(adapter, inbound)
    return Response(status_code=200, content=b"")


@router.get("/hooks/wecom", include_in_schema=True)
async def wecom_url_check(request: Request) -> Response:
    """WeCom's URL check, sent when the callback URL is saved in its admin console."""
    return await _door(request)


@router.post("/hooks/wecom", include_in_schema=True)
async def wecom_callback(request: Request) -> Response:
    """WeCom's callback: a message or an event, signed and encrypted."""
    return await _door(request)
