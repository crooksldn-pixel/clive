"""The owner's screens: a device opens /display, names itself, and asks every couple of
seconds what it should show (app/displays/store.py). Every route here is the owner's alone:
a proxied caller on the allow-list whose device Tailscale confirms, or the server itself only
when CROOKS_LOCAL_OWNER says it is him (app/routes/actions.py principal_verdict).

Naming a screen is not enough to be shown anything (round 8, B-02): a new screen is given a key
and a six-digit code, and shows the code until the owner reads it off that device and tells
CLIVE (the screen_pair tool). At MAX_SCREENS a new name is refused, and nothing is removed to
make room (NEW-B-CAP).

What a screen does after that, it does with its own key (X-Screen-Key): ask what to show,
acknowledge each page it puts up — in order, and not faster than one a second — and say "done"
from the tap that means it (B-04). Replacing a screen that lost its key is the owner removing
the old one explicitly, which clears what it showed (round 7, B-02). A deletion that is made but
not yet durable is answered 503, never as done (B-03)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.displays.store import (
    DisplayError,
    NameTaken,
    NotConfirmed,
    NotPaired,
    NotSaved,
    NotSeen,
    NotThisScreen,
    OutOfOrder,
    TooMany,
    TooSoon,
    store,
)
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
    # Sent only by the Mark packed tap (web/display.js markDone), and required (round 8, B-04).
    # Strictly the JSON value true: a string or a number is not the tap.
    confirm: bool = Field(default=False, strict=True)


def _screen_key(request: Request) -> str:
    """The key the device was given when it named itself (app/displays/store.py)."""
    return request.headers.get("x-screen-key", "")[:200]


def _not_this_screen(exc: NotThisScreen) -> JSONResponse:
    return JSONResponse(status_code=403, content={"code": "not_this_screen", "detail": str(exc)})


def _not_saved(exc: NotSaved) -> JSONResponse:
    return JSONResponse(status_code=503, content={"code": "not_saved", "detail": str(exc)})


def _not_approved(exc: NotPaired) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": "not_approved", "detail": str(exc)})


def _too_soon(exc: TooSoon) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": "too_soon", "detail": str(exc), "retry_after_ms": exc.retry_after_ms})


@router.get("")
async def screens() -> dict:
    s = store()
    return {"screens": s.screens(), "done": s.done()}


@router.post("/register", response_model=None)
async def register(body: RegisterBody, request: Request) -> dict | JSONResponse:
    try:
        screen = store().register(body.name, screen_key=_screen_key(request))
    except NameTaken as exc:
        return JSONResponse(status_code=409, content={"code": "name_taken", "detail": str(exc)})
    except TooMany as exc:
        return JSONResponse(status_code=409, content={"code": "too_many_screens", "detail": str(exc)})
    except NotSaved as exc:
        return _not_saved(exc)
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "refused", "detail": str(exc)})
    # The key and the code are in this answer and nowhere else: the device keeps the key and
    # shows the code, and the store keeps only their hashes.
    content = {"id": screen["id"], "name": screen["name"], "key": screen["screen_key"], "pending": screen["pending"]}
    if screen.get("code"):
        content.update(code=screen["code"], code_expires_in=screen["code_expires_in"])
    return JSONResponse(content=content, headers={"Cache-Control": "no-store"})


@router.post("/forget", response_model=None)
async def forget(body: ForgetBody) -> dict | JSONResponse:
    """The owner removes the screen of this exact name, and whatever it was showing, so that a
    device can be named it afresh (round 7, B-02), or so that there is room for another
    (round 8, NEW-B-CAP)."""
    try:
        name = store().forget_named(body.name)
    except NotSaved as exc:
        return _not_saved(exc)
    except DisplayError as exc:
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": str(exc)})
    return {"forgotten": name}


@router.get("/{screen_id}", response_model=None)
async def poll(screen_id: str, request: Request, v: int = -1) -> dict | Response:
    """What to show. 204 when nothing has changed since version `v`."""
    try:
        now = store().poll(screen_id, _screen_key(request))
    except NotThisScreen as exc:
        return _not_this_screen(exc)
    if now is None:
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": "No such screen."})
    # A screen waiting for approval is answered in full each time: it shows how long its code has.
    if int(now["version"]) == int(v) and not now["pending"]:
        return Response(status_code=204)
    return now


@router.post("/{screen_id}/seen", response_model=None)
async def seen(screen_id: str, body: SeenBody, request: Request) -> dict | JSONResponse:
    """The screen has put items [start, end) up, for the version it was given (a page at most,
    carrying on from the last, round 8, B-04)."""
    try:
        held = store().acknowledge(screen_id, body.version, screen_key=_screen_key(request), start=body.start, end=body.end)
    except NotThisScreen as exc:
        return _not_this_screen(exc)
    except NotPaired as exc:
        return _not_approved(exc)
    except TooSoon as exc:
        return _too_soon(exc)
    except OutOfOrder as exc:
        return JSONResponse(status_code=409, content={"code": "out_of_order", "detail": str(exc),
                                                      "covered": exc.covered, "size": exc.size})
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "refused", "detail": str(exc)})
    return {"seen": held}


@router.post("/{screen_id}/done", response_model=None)
async def done(screen_id: str, body: DoneBody, request: Request) -> dict | JSONResponse:
    who, _ = principal_check(request)
    key = _screen_key(request)
    try:
        store().mark_done(screen_id, body.version, screen_key=key, confirmed=body.confirm, by=who)
    except NotThisScreen as exc:
        return _not_this_screen(exc)
    except NotPaired as exc:
        return _not_approved(exc)
    except NotConfirmed as exc:
        return JSONResponse(status_code=409, content={"code": "not_confirmed", "detail": str(exc)})
    except TooSoon as exc:
        return _too_soon(exc)
    except NotSeen as exc:
        return JSONResponse(status_code=409, content={"code": "not_seen", "detail": str(exc)})
    except NotSaved as exc:
        return _not_saved(exc)
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "stale", "detail": str(exc)})
    return store().poll(screen_id, key) or {}
