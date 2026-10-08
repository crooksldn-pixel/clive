"""The public doors for messages coming in: GET and POST /hooks/wecom, /hooks/whatsapp and
/hooks/instagram, one per channel.

Why it exists: WeCom and Meta deliver a message by calling an address on the internet, so CLIVE
needs one address per channel the public can reach. Everything else CLIVE serves stays behind the
door in app/main.py (the owner, or a member of the team he let in, through Tailscale); only the
paths in HOOK_PATHS skip it, and they carry no authority of any kind: no tool can run from here.

What it promises, in this order, for every request:
1. A body larger than the channel's cap (its adapter's `max_body`: 64 KB for WeCom, Meta's 3 MB
   for WhatsApp and Instagram) is refused before it is read whole.
2. The channel's adapter checks the signature before anything else is done with the request
   (WeCom's msg_signature; Meta's X-Hub-Signature-256, which is why the headers go to it), then
   the channel's own checks: WeCom's timestamp window, that a request is new (app/messaging/
   guard.py), decryption; Meta's body, and that the same body was not taken a moment ago.
3. Anything refused gets 403 with an empty body: no reason, no echo, nothing to learn from.
4. A URL check (WeCom's GET when the URL is saved, Meta's hub.challenge) gets its echo, as plain
   text, and only when it carried the stored token.
5. A message gets 200 with an empty body at once, as WeCom asks (answer in five seconds; 90238)
   and Meta asks (a 200, or it retries for days). What the callback carries itself (a team
   member's message; all of Meta's) is stored before that answer, however busy the server is;
   what has to be read from WeCom, every translation and every name, comes after
   (app/messaging/ingest.py). A repeat of one already accepted gets the same 200 and is dropped.
6. Nothing a request carried is logged: app/logging/quiet.py keeps the query off the access line.
7. [channels] At most MAX_READING bodies per channel are read and checked at once (review note 8):
   anyone can post here, before any signature is proved, up to 3 MB each on Meta's doors. One more
   meanwhile gets the same empty 403 at once, unread; Meta and WeCom send it again later. Each
   channel has its own count, so a flood at one door never shuts another.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from app.messaging import adapter as adapters
from app.messaging import ingest
from app.messaging import instagram as _ig  # noqa: F401 - registers the Instagram adapter
from app.messaging import wecom as _wecom_channel  # noqa: F401 - registers the WeCom adapter
from app.messaging import whatsapp as _wa  # noqa: F401 - registers the WhatsApp adapter
from app.messaging.guard import GUARD, MAX_BODY_BYTES

log = logging.getLogger("crooks.hooks")

router = APIRouter()

# The only paths the door in app/main.py lets through without an owner or a member of the team.
# Exact paths, never prefixes: /hooks/wecom/x and /hooks/other stay behind the door.
CHANNEL_OF = {"/hooks/wecom": "wecom", "/hooks/whatsapp": "whatsapp", "/hooks/instagram": "instagram"}
HOOK_PATHS = frozenset(CHANNEL_OF)


def is_hook(path: str) -> bool:
    return path in HOOK_PATHS


def routed_path(request: Request) -> str:
    """The path the request is routed by (the ASGI scope's), never request.url's, which an older
    Starlette built from the Host header (review note 8, 8 Oct)."""
    return str(request.scope.get("path") or "")


# [channels] How many POST bodies one door reads and checks at once: 4 x 3 MB on each Meta door.
MAX_READING = 4
_READING: dict[str, int] = {}


def _reading(channel: str) -> bool:
    """Take one of the channel's reading places, or say there is none free. One event loop serves
    every request, so a plain count is exact; nothing here waits."""
    if _READING.get(channel, 0) >= MAX_READING:
        return False
    _READING[channel] = _READING.get(channel, 0) + 1
    return True


def _done_reading(channel: str) -> None:
    _READING[channel] = max(0, _READING.get(channel, 0) - 1)


def _refused() -> Response:
    return Response(status_code=403, content=b"", headers={"Cache-Control": "no-store"})


async def _bounded_body(request: Request, cap: int = MAX_BODY_BYTES) -> bytes | None:
    """The body, or None when it is (or claims to be) larger than `cap`."""
    declared = request.headers.get("content-length", "")
    if declared:
        try:
            if int(declared) > cap:
                return None
        except ValueError:
            return None
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > cap:
            return None
    return bytes(received)


async def _door(request: Request) -> Response:
    channel = CHANNEL_OF.get(routed_path(request), "")
    adapter = adapters.get(channel)
    if adapter is None:
        return _refused()
    if request.method != "POST":
        return await _answer(request, channel, adapter)
    if not _reading(channel):
        GUARD.refuse(channel, "busy")
        return _refused()
    try:
        return await _answer(request, channel, adapter)
    finally:
        _done_reading(channel)


async def _answer(request: Request, channel: str, adapter) -> Response:
    body = b""
    if request.method == "POST":
        held = await _bounded_body(request, int(getattr(adapter, "max_body", MAX_BODY_BYTES)))
        if held is None:
            GUARD.refuse(channel, "size")
            return _refused()
        body = held
    try:
        inbound = adapter.verify_inbound(request.method, request.query_params, body, request.headers)
    except adapters.Refused as refused:
        GUARD.refuse(channel, refused.why)
        return _refused()
    except Exception:  # noqa: BLE001 - anyone can post here: whatever went wrong, an empty 403, never a 500
        GUARD.refuse(channel, "error")
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


@router.get("/hooks/whatsapp", include_in_schema=True)
async def whatsapp_url_check(request: Request) -> Response:
    """Meta's check when the WhatsApp callback URL is saved: hub.challenge, for the verify token."""
    return await _door(request)


@router.post("/hooks/whatsapp", include_in_schema=True)
async def whatsapp_callback(request: Request) -> Response:
    """WhatsApp's webhook: messages, and what became of the ones CLIVE sent, signed by Meta."""
    return await _door(request)


@router.get("/hooks/instagram", include_in_schema=True)
async def instagram_url_check(request: Request) -> Response:
    """Meta's check when the Instagram callback URL is saved: hub.challenge, for the verify token."""
    return await _door(request)


@router.post("/hooks/instagram", include_in_schema=True)
async def instagram_callback(request: Request) -> Response:
    """Instagram's webhook: direct messages, signed by Meta."""
    return await _door(request)
