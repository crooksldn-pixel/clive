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
not yet durable is answered 503, never as done (B-03).

A screen shows up to two things at once (round 9): the screen names the pane, and that pane's
own version, when it acknowledges a page or says done. And the owner's app can be the remote
for a screen (web/remote.js): `GET /displays/{id}/remote` is his view of it, and the
`/remote/...` routes tick items, turn pages, mark a pane done, put an objective up again and take
things off. They are his routes like every other here, answered for his own devices and nobody
else's, and need no screen key: the remote is not the screen. A pane that has moved on is 409
(`stale`), a screen still waiting for approval is 409 (`not_approved`), and a deletion not yet
durable is 503."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.displays import views
from app.displays.store import (
    MAX_PANES,
    DisplayError,
    NameTaken,
    NoSuchScreen,
    NotConfirmed,
    NotPaired,
    NotSaved,
    NotSeen,
    NotThisScreen,
    NotTicked,
    OutOfOrder,
    Stale,
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
    # Which pane (round 9); `version` is that pane's own. A page from before panes means the first.
    pane: int = Field(default=0, ge=0, le=MAX_PANES - 1)


class DoneBody(BaseModel):
    version: int = Field(ge=0)
    # Sent by pages from before round 7 and ignored: what was on the screen is what the screen
    # acknowledged, page by page (/displays/{id}/seen), not a number it asserts.
    items_seen: int | None = Field(default=None, ge=0, le=10_000)
    # Sent only by the Mark packed tap (web/display.js markDone), and required (round 8, B-04).
    # Strictly the JSON value true: a string or a number is not the tap.
    confirm: bool = Field(default=False, strict=True)
    # Which pane (round 9); `version` is that pane's own.
    pane: int = Field(default=0, ge=0, le=MAX_PANES - 1)


# ---- the owner's remote (round 9) ----------------------------------------------------------
# Every body names the pane and the version it was put up at, strictly as numbers and a real
# true or false, so a remote working from an old view is told so (409 stale) and nothing moves.


class TickBody(BaseModel):
    pane: int = Field(ge=0, le=MAX_PANES - 1, strict=True)
    item: int = Field(ge=0, le=views.MAX_ITEMS, strict=True)
    packed: bool = Field(strict=True)
    version: int = Field(ge=0, strict=True)


class PageBody(BaseModel):
    pane: int = Field(ge=0, le=MAX_PANES - 1, strict=True)
    delta: int = Field(ge=-1, le=1, strict=True)
    version: int = Field(ge=0, strict=True)


class PaneBody(BaseModel):
    pane: int = Field(ge=0, le=MAX_PANES - 1, strict=True)
    version: int = Field(ge=0, strict=True)


class OffBody(BaseModel):
    # One pane (with the version it was put up at), or, with neither, the whole screen.
    pane: int | None = Field(default=None, ge=0, le=MAX_PANES - 1, strict=True)
    version: int | None = Field(default=None, ge=0, strict=True)


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


def _remote_refusal(exc: DisplayError) -> JSONResponse:
    """How a remote route says no (round 9): the screen is gone (404), not approved (409), the
    pane moved on (409 stale), an item is not ticked (409), a deletion not yet durable (503), or
    anything else, plainly (409)."""
    if isinstance(exc, NoSuchScreen):
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": str(exc)})
    if isinstance(exc, NotPaired):
        return _not_approved(exc)
    if isinstance(exc, NotSaved):
        return _not_saved(exc)
    code = "stale" if isinstance(exc, Stale) else "not_ticked" if isinstance(exc, NotTicked) else "refused"
    return JSONResponse(status_code=409, content={"code": code, "detail": str(exc)})


def _fresh(content: dict) -> JSONResponse:
    return JSONResponse(content=content, headers={"Cache-Control": "no-store"})


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
        held = store().acknowledge(screen_id, body.version, screen_key=_screen_key(request), start=body.start, end=body.end,
                                   pane=body.pane)
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
        store().mark_done(screen_id, body.version, screen_key=key, confirmed=body.confirm, by=who, pane=body.pane)
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


# ---- the owner's remote (round 9) ----------------------------------------------------------


@router.get("/{screen_id}/remote", response_model=None)
async def remote(screen_id: str) -> dict | JSONResponse:
    """The owner's view of a screen for his remote, asked about once a second: pane by pane what
    it shows, an order's items without who they go to, and each item's tick."""
    try:
        return _fresh(store().remote(screen_id))
    except DisplayError as exc:
        return _remote_refusal(exc)


@router.post("/{screen_id}/remote/tick", response_model=None)
async def remote_tick(screen_id: str, body: TickBody) -> dict | JSONResponse:
    """One item packed, or not after all. The screen shows the tick on its next ask."""
    try:
        return _fresh(store().tick(screen_id, body.pane, body.item, body.packed, body.version))
    except DisplayError as exc:
        return _remote_refusal(exc)


@router.post("/{screen_id}/remote/page", response_model=None)
async def remote_page(screen_id: str, body: PageBody) -> dict | JSONResponse:
    """The screen's page for that pane, one on or one back."""
    if body.delta == 0:
        return JSONResponse(status_code=422, content={"code": "refused", "detail": "Pages turn one at a time."})
    try:
        return _fresh(store().turn_page(screen_id, body.pane, body.delta, body.version))
    except DisplayError as exc:
        return _remote_refusal(exc)


@router.post("/{screen_id}/remote/done", response_model=None)
async def remote_done(screen_id: str, body: PaneBody, request: Request) -> dict | JSONResponse:
    """Packed (or done), from the remote: once every item to send is ticked for this version."""
    who, _ = principal_check(request)
    try:
        store().done_from_remote(screen_id, body.pane, body.version, by=who)
        return _fresh(store().remote(screen_id))
    except DisplayError as exc:
        return _remote_refusal(exc)


@router.post("/{screen_id}/remote/again", response_model=None)
async def remote_again(screen_id: str, body: PaneBody) -> dict | JSONResponse:
    """An objective put up again from CLIVE's own record, in the same place."""
    from app.objectives.store import ObjectiveError
    from app.objectives.store import store as objectives

    try:
        kind, ref = store().pane_ref(screen_id, body.pane, body.version)
        if kind != "objective":
            raise DisplayError("Only an objective is put up again from here.")
        try:
            obj = objectives().get(ref)
        except ObjectiveError as exc:
            raise DisplayError(str(exc)) from None
        store().show(screen_id, views.objective_view(obj.summary(), obj.items), by="clive", replace=body.pane,
                     expect=body.version)
        return _fresh(store().remote(screen_id))
    except DisplayError as exc:
        return _remote_refusal(exc)


@router.post("/{screen_id}/remote/off", response_model=None)
async def remote_off(screen_id: str, body: OffBody) -> dict | JSONResponse:
    """One pane taken off the screen (the other fills it), or, with no pane, everything: the
    screen goes back to its clock. 503 until the deletion is durable."""
    if (body.pane is None) != (body.version is None):
        return JSONResponse(status_code=422, content={"code": "refused", "detail": "Name the pane and its version, or neither."})
    try:
        store().take_off(screen_id, body.pane, expect=body.version)
        return _fresh(store().remote(screen_id))
    except DisplayError as exc:
        return _remote_refusal(exc)
