"""The owner's screens: a device opens /display, names itself, and asks every couple of
seconds what it should show (app/displays/store.py). Every route here is the owner's alone:
a proxied caller on the allow-list whose device Tailscale confirms, or the server itself only
when CROOKS_LOCAL_OWNER says it is him (app/routes/actions.py principal_verdict) — so naming a
screen is the owner's own device asking, and nobody else can pair one.

What a screen does after that, it does with its own key (X-Screen-Key): ask what to show,
acknowledge each page it puts up, and say "done". Replacing a screen that lost its key is the
owner removing the old one explicitly, which clears what it showed (round 7, B-02)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.displays.store import DisplayError, NameTaken, NotSaved, NotSeen, NotThisScreen, store
from app.routes.actions import principal_check, require_principal

router = APIRouter(prefix="/displays", dependencies=[Depends(require_principal)])


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ForgetBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SeenBody(BaseModel):
    version: int = Field(ge=0)
    start: int = Field(ge=0, le=10_000)
    end: int = Field(ge=1, le=10_000)


class DoneBody(BaseModel):
    version: int = Field(ge=0)
    # Sent by pages from before round 7 and ignored: what was on the screen is what the screen
    # acknowledged, page by page (/displays/{id}/seen), not a number it asserts.
    items_seen: int | None = Field(default=None, ge=0, le=10_000)


def _screen_key(request: Request) -> str:
    """The key the device was given when it named itself (app/displays/store.py)."""
    return request.headers.get("x-screen-key", "")[:200]


def _not_this_screen(exc: NotThisScreen) -> JSONResponse:
    return JSONResponse(status_code=403, content={"code": "not_this_screen", "detail": str(exc)})


@router.get("")
async def screens() -> dict:
    s = store()
    return {"screens": s.screens(), "done": s.done()}


def _not_saved(exc: NotSaved) -> JSONResponse:
    return JSONResponse(status_code=503, content={"code": "not_saved", "detail": str(exc)})


@router.post("/register", response_model=None)
async def register(body: RegisterBody, request: Request) -> dict | JSONResponse:
    try:
        screen = store().register(body.name, screen_key=_screen_key(request))
    except NameTaken as exc:
        return JSONResponse(status_code=409, content={"code": "name_taken", "detail": str(exc)})
    except NotSaved as exc:
        return _not_saved(exc)
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "refused", "detail": str(exc)})
    # The key is in this answer and nowhere else: the device keeps it, the store keeps its hash.
    return JSONResponse(content={"id": screen["id"], "name": screen["name"], "key": screen["screen_key"]},
                        headers={"Cache-Control": "no-store"})


@router.post("/forget", response_model=None)
async def forget(body: ForgetBody) -> dict | JSONResponse:
    """The owner removes the screen of this exact name, and whatever it was showing, so that a
    device can be named it afresh (round 7, B-02)."""
    s = store()
    try:
        screen = s.find(body.name, exact=True)
        s.forget(screen["id"])
    except NotSaved as exc:
        return _not_saved(exc)
    except DisplayError as exc:
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": str(exc)})
    return {"forgotten": screen["name"]}


@router.get("/{screen_id}", response_model=None)
async def poll(screen_id: str, request: Request, v: int = -1) -> dict | Response:
    """What to show. 204 when nothing has changed since version `v`."""
    try:
        now = store().poll(screen_id, _screen_key(request))
    except NotThisScreen as exc:
        return _not_this_screen(exc)
    if now is None:
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": "No such screen."})
    if int(now["version"]) == int(v):
        return Response(status_code=204)
    return now


@router.post("/{screen_id}/seen", response_model=None)
async def seen(screen_id: str, body: SeenBody, request: Request) -> dict | JSONResponse:
    """The screen has put items [start, end) up, for the version it was given (a page at most)."""
    try:
        held = store().acknowledge(screen_id, body.version, screen_key=_screen_key(request), start=body.start, end=body.end)
    except NotThisScreen as exc:
        return _not_this_screen(exc)
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "refused", "detail": str(exc)})
    return {"seen": held}


@router.post("/{screen_id}/done", response_model=None)
async def done(screen_id: str, body: DoneBody, request: Request) -> dict | JSONResponse:
    who, _ = principal_check(request)
    key = _screen_key(request)
    try:
        store().mark_done(screen_id, body.version, screen_key=key, by=who)
    except NotThisScreen as exc:
        return _not_this_screen(exc)
    except NotSeen as exc:
        return JSONResponse(status_code=409, content={"code": "not_seen", "detail": str(exc)})
    except NotSaved as exc:
        return _not_saved(exc)
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "stale", "detail": str(exc)})
    return store().poll(screen_id, key) or {}
