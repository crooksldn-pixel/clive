"""The owner's screens: a device opens /display, names itself, and asks every couple of
seconds what it should show (app/displays/store.py). Every route here is the owner's alone:
a proxied caller on the allow-list whose device Tailscale confirms, or the server itself only
when CROOKS_LOCAL_OWNER says it is him (app/routes/actions.py principal_verdict).

Naming a screen is not enough to be shown anything (round 8, B-02): a new screen is given a key
and a six-digit code, and shows the code until the owner reads it off that device and tells
CLIVE (the screen_pair tool). At MAX_SCREENS a new name is refused, and nothing is removed to
make room (NEW-B-CAP).

What a screen does after that, it does with its own key: ask what to show, acknowledge each page
it puts up — the next page of the plan the server holds for it, and not faster than one a second
— and say "done" from its button, which is the screen's own word and is recorded as that (B-04).
Replacing a screen that lost its key is the owner removing the old one explicitly, which clears
what it showed (round 7, B-02). A deletion that is made but not yet durable is answered 503, never
as done (B-03).

The key is a cookie the page's own script cannot read (round 9, B2-01): `POST /displays/register`
sets `clive_screen` — HttpOnly, Secure, SameSite=Strict, for /displays only, kept 400 days — and
never puts the key in its answer, and every screen request (the ask, /seen, /done, /video) is
known by that cookie and nothing else. A page from before holds its key in its own storage: it
names itself once more with `X-Screen-Key`, which is read on /register alone and only for that,
and if the key holds the screen of that name the screen is handed the cookie with a new key and
stays approved. Such a page still open when CLIVE is updated asks with that header and no cookie:
it is refused as any device without the key is, but answered `reload` rather than
`not_this_screen`, which would make it throw its key away (_not_this_screen).

A screen shows up to two things at once (round 9): the screen names the pane, and that pane's
own version, when it acknowledges a page or says done. And the owner's app can be the remote
for a screen (web/remote.js): `GET /displays/{id}/remote` is his view of it, and the
`/remote/...` routes tick items, turn pages, mark a pane done, put an objective up again, play,
pause and turn up a video (`/remote/video`), and take things off. A screen playing a video tells
CLIVE how it is playing (`/displays/{id}/video`, with its key), which is held in memory only.
They are his routes like every other here, answered for his own devices and nobody else's, and
need no screen key: the remote is not the screen. Each names what it was made for — a pane and
its version, or for the whole screen off the screen's version (round 9, B-REMOTE-OFF) — so a
tap on an older view moves nothing: a pane or screen that has moved on is 409 (`stale`), a
screen still waiting for approval is 409 (`not_approved`), and a deletion not yet durable is
503.

What a screen can have from here (round 9, F-A3B-SCREEN-EVIDENCE; tests/test_screen_paths.py and
tests/test_r11_screens_server.py). With its cookie, its own record and nothing else: what it
shows (both panes, the customer's details on an order slip included), its version, its name and
its last done row's title and time — each pane cut to the fields its kind has and nothing more,
whatever the record on disk holds (round 11, DisplayStore._for_screen). A key is in no answer at
all, only in the cookie, and no answer carries any screen's key hash or approval-code hash; an
approval code is in the answer to its own naming, for that screen to show, and nowhere else.
Another screen's record needs that screen's key. What every one of the owner's devices has from
the owner's routes here, a screen too — it is one of his devices by its Tailscale login — is the
list of screens (names, whether each is on, the titles up), the done record (kind, reference,
title, screen, time, login, how), and the remote's view of a screen, pane by pane: an order's
items (title, variant, quantity, image), a list's lines, an objective's words, a video's id and
how it plays — never who an order goes to, where, their phone or their note. Nothing here reads
a conversation, its words or live voice. (What else a device on the owner's login can reach is
every other owner route of the app: the screens do not change that, app/main.py.)

A screen using the remote's routes is still a screen (round 11, B-04): a done it marks there is
recorded as a screen's word, not the owner's remote (DisplayStore.screen_device, told by the key
it carries or the tailnet address its key-holder asks from)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.displays import views
from app.displays.store import (
    MAX_JUMP_S,
    MAX_PANES,
    DisplayError,
    Full,
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
from app.identity import forwarded_address
from app.routes.actions import TAILSCALE, principal_check, proxy_state, require_principal

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
    # Strictly the JSON value true: a string or a number is not the tap. It is the page's word
    # that its button was pressed, not evidence of it (round 9, B-04): the done row says it was
    # marked on the screen (`how` "screen").
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


class VideoBody(BaseModel):
    """What the owner asks of the video on one pane: play, pause, mute, unmute, a volume (0 to
    100), louder or quieter (by a step, 10 unsaid), a skip (seconds either way) or a jump (to a
    point, in seconds from the start)."""
    pane: int = Field(ge=0, le=MAX_PANES - 1, strict=True)
    version: int = Field(ge=0, strict=True)
    action: Literal["play", "pause", "mute", "unmute", "volume", "louder", "quieter", "skip", "jump"]
    value: int | None = Field(default=None, ge=-MAX_JUMP_S, le=MAX_JUMP_S, strict=True)


class PlayingBody(BaseModel):
    """The screen's own word on how the video on one pane is playing (round 9, YouTube): a
    state from YouTube's own list, numbers in their bounds, and true or false — strictly, and
    nothing else at all (round 11: a field the page does not send is refused, 422, so no word
    of a screen's reaches CLIVE or the remote through here)."""

    model_config = ConfigDict(extra="forbid")

    pane: int = Field(ge=0, le=MAX_PANES - 1, strict=True)
    version: int = Field(ge=0, strict=True)
    state: Literal["unstarted", "cued", "buffering", "playing", "paused", "ended"]
    at: float = Field(ge=0, le=MAX_JUMP_S * 2, strict=True)
    duration: float | None = Field(default=None, ge=0, le=MAX_JUMP_S * 2, strict=True)
    volume: int | None = Field(default=None, ge=0, le=100, strict=True)
    muted: bool = Field(default=False, strict=True)
    # The screen could play it only muted until someone there presses a button (a browser's rule).
    blocked: bool = Field(default=False, strict=True)
    # YouTube's own error number, when the player would not play it (not embeddable, gone, ...).
    error: int | None = Field(default=None, ge=0, le=999, strict=True)


class OffBody(BaseModel):
    """One pane, with the version it was put up at; or the whole screen, with the screen's
    version the remote was showing when it was tapped (its view's top-level `version`, round 9,
    B-REMOTE-OFF). Nothing else: a whole-screen off that names no version is refused (422)."""

    model_config = ConfigDict(extra="forbid")

    pane: int | None = Field(default=None, ge=0, le=MAX_PANES - 1, strict=True)
    version: int | None = Field(default=None, ge=0, strict=True)
    screen_version: int | None = Field(default=None, ge=0, strict=True)


# The screen's key, as the cookie POST /displays/register sets (round 9, B2-01): the page's
# script cannot read it, it goes only to the screen's own routes, never cross-site, and it is kept
# 400 days (as long as a browser keeps any cookie).
SCREEN_COOKIE = "clive_screen"
SCREEN_COOKIE_MAX_AGE = 34_560_000


def _screen_key(request: Request) -> str:
    """The key the device was given when it named itself (app/displays/store.py): its cookie,
    and only its cookie. `X-Screen-Key` is not read here."""
    return request.cookies.get(SCREEN_COOKIE, "")[:200]


def _old_screen_key(request: Request) -> str:
    """A key a page kept in its own storage from before the key became a cookie. Read by
    /register alone, and only so that screen can name itself again and be handed the cookie."""
    return request.headers.get("x-screen-key", "")[:200]


def _device(request: Request) -> str:
    """The tailnet address of the device asking, for a request that came through Tailscale
    (proxy_state, the same decision the owner rule read to let it in); "" for any other. What
    the store tells a screen from the owner's other devices by, in the remote's routes (round
    11, B-04, app/displays/store.py screen_device): a page can leave its cookie out, but not
    change the address Tailscale says it asks from."""
    if proxy_state(request)[0] != TAILSCALE:
        return ""
    return forwarded_address(request.headers.get("x-forwarded-for", ""))[:64]


def _handed(content: dict, key: str) -> JSONResponse:
    """An answer that hands the device its key, as the cookie and nowhere else."""
    response = JSONResponse(content=content, headers={"Cache-Control": "no-store"})
    response.headers.append("set-cookie", f"{SCREEN_COOKIE}={key}; HttpOnly; Secure; SameSite=Strict; Path=/displays; "
                                          f"Max-Age={SCREEN_COOKIE_MAX_AGE}")
    return response


def _not_this_screen(request: Request, exc: NotThisScreen) -> JSONResponse:
    """A device that does not hold this screen's key. One that sent no cookie but did send the
    header every page from before the cookie sends (round 9, B2-01) is such a page, still open
    since CLIVE was updated: it is told to reload (`reload`), not that it is not the screen —
    that page throws its key away when told the latter, and would then have to be named and
    approved all over again, where reloaded it moves over by itself (/register). Only whether the
    header was sent is looked at, never its value, and nothing is served either way."""
    if SCREEN_COOKIE not in request.cookies and "x-screen-key" in request.headers:
        return JSONResponse(status_code=403, content={
            "code": "reload", "detail": "This screen's page is from before an update to CLIVE. Reload it: it keeps its name "
                                        "and its approval."})
    return JSONResponse(status_code=403, content={"code": "not_this_screen", "detail": str(exc)})


def _not_saved(exc: NotSaved) -> JSONResponse:
    return JSONResponse(status_code=503, content={"code": "not_saved", "detail": str(exc)})


def _full(exc: Full) -> JSONResponse:
    """The record would pass its bound: refused, nothing changed (round 9, B-NEW-DONE-LOSS)."""
    return JSONResponse(status_code=409, content={"code": "full", "detail": str(exc)})


def _not_approved(exc: NotPaired) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": "not_approved", "detail": str(exc)})


def _too_soon(exc: TooSoon) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": "too_soon", "detail": str(exc), "retry_after_ms": exc.retry_after_ms})


def _remote_refusal(exc: DisplayError) -> JSONResponse:
    """How a remote route says no (round 9): the screen is gone (404), not approved (409), the
    pane or screen moved on (409 stale), an item is not ticked (409), the record is full (409),
    a deletion not yet durable (503), or anything else, plainly (409)."""
    if isinstance(exc, NoSuchScreen):
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": str(exc)})
    if isinstance(exc, NotPaired):
        return _not_approved(exc)
    if isinstance(exc, NotSaved):
        return _not_saved(exc)
    if isinstance(exc, Full):
        return _full(exc)
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
    """A device names itself a screen, or the screen it holds names itself again (a new key,
    and for one still waiting, a new code). The key it holds is its cookie, or, once, a key a
    page kept from before the cookie (`X-Screen-Key`, round 9, B2-01)."""
    try:
        screen = store().register(body.name, screen_key=_screen_key(request), old_key=_old_screen_key(request),
                                  device=_device(request))
    except NameTaken as exc:
        return JSONResponse(status_code=409, content={"code": "name_taken", "detail": str(exc)})
    except TooMany as exc:
        return JSONResponse(status_code=409, content={"code": "too_many_screens", "detail": str(exc)})
    except NotSaved as exc:
        return _not_saved(exc)
    except Full as exc:
        return _full(exc)
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "refused", "detail": str(exc)})
    # The key is the cookie and nowhere else (round 9, B2-01); the code is in this answer and
    # nowhere else, for the screen to show. The store keeps only their hashes.
    content = {"id": screen["id"], "name": screen["name"], "pending": screen["pending"]}
    if screen.get("code"):
        content.update(code=screen["code"], code_expires_in=screen["code_expires_in"])
    return _handed(content, screen["screen_key"])


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
        now = store().poll(screen_id, _screen_key(request), device=_device(request))
    except NotThisScreen as exc:
        return _not_this_screen(request, exc)
    if now is None:
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": "No such screen."})
    # Which build of CLIVE answered, so a screen left open across a deploy reloads itself once it
    # is resting (web/display.js), rather than waiting for someone to reload it by hand.
    build = {"X-Clive-Build": str(getattr(getattr(request.app.state, "runtime", None), "build", "") or "")[:80]}
    # A screen waiting for approval is answered in full each time: it shows how long its code has.
    if int(now["version"]) == int(v) and not now["pending"]:
        return Response(status_code=204, headers=build)
    return JSONResponse(content=now, headers=build)


@router.post("/{screen_id}/seen", response_model=None)
async def seen(screen_id: str, body: SeenBody, request: Request) -> dict | JSONResponse:
    """The screen says it has put items [start, end) up, for the version it was given: the next
    page of the server's plan (round 8 and round 9, B-04). The answer says the plan."""
    try:
        held = store().acknowledge(screen_id, body.version, screen_key=_screen_key(request), start=body.start, end=body.end,
                                   pane=body.pane)
    except NotThisScreen as exc:
        return _not_this_screen(request, exc)
    except NotPaired as exc:
        return _not_approved(exc)
    except TooSoon as exc:
        return _too_soon(exc)
    except OutOfOrder as exc:
        return JSONResponse(status_code=409, content={"code": "out_of_order", "detail": str(exc), "covered": exc.covered,
                                                      "size": exc.size, "next": list(exc.next_page) if exc.next_page else None})
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "refused", "detail": str(exc)})
    # The server's plan of the pane's pages, as it now holds it (round 9, B-04).
    return {"seen": held, "plan": store().page_plan(screen_id, body.version, body.pane)}


@router.post("/{screen_id}/video", response_model=None)
async def video_playing(screen_id: str, body: PlayingBody, request: Request) -> dict | JSONResponse:
    """The screen holding this key says how a video is playing. Kept in memory only, for the
    remote and CLIVE; one told sooner than the store takes them is dropped, not refused."""
    try:
        heard = store().report_playing(screen_id, body.pane, body.version, screen_key=_screen_key(request),
                                       state=body.state, at=body.at, duration=body.duration, volume=body.volume,
                                       muted=body.muted, blocked=body.blocked, error=body.error)
    except NotThisScreen as exc:
        return _not_this_screen(request, exc)
    except NotPaired as exc:
        return _not_approved(exc)
    except NoSuchScreen:
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": "No such screen."})
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "stale", "detail": str(exc)})
    return {"heard": heard}


@router.post("/{screen_id}/done", response_model=None)
async def done(screen_id: str, body: DoneBody, request: Request) -> dict | JSONResponse:
    who, _ = principal_check(request)
    key = _screen_key(request)
    try:
        store().mark_done(screen_id, body.version, screen_key=key, confirmed=body.confirm, by=who, pane=body.pane)
    except NotThisScreen as exc:
        return _not_this_screen(request, exc)
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
    except Full as exc:
        return _full(exc)
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
    """Packed (or done), from the remote: once every item to send is ticked for this version.
    Asked from a device that is itself one of the screens, it is that screen's word, and the
    done row says so (round 11, B-04)."""
    who, _ = principal_check(request)
    from_screen = store().screen_device(_screen_key(request), _device(request)) is not None
    try:
        store().done_from_remote(screen_id, body.pane, body.version, by=who, from_screen=from_screen)
        return _fresh(store().remote(screen_id))
    except DisplayError as exc:
        return _remote_refusal(exc)


@router.post("/{screen_id}/remote/video", response_model=None)
async def remote_video(screen_id: str, body: VideoBody) -> dict | JSONResponse:
    """Play, pause, mute, the volume, a skip or a jump, for the video on one pane. The screen
    applies it on its next ask; the answer is the video's state as it now stands."""
    try:
        return _fresh(store().player(screen_id, body.pane, body.version, body.action, body.value))
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
    """One pane taken off the screen (the other fills it), named with the version it was put up
    at; or everything, named with the screen's version the remote was showing, and the screen
    goes back to its clock. Either only while that is still what is up (409 stale otherwise,
    and nothing is taken off, round 9, B-REMOTE-OFF). 503 until the deletion is durable."""
    one = body.pane is not None and body.version is not None and body.screen_version is None
    whole = body.pane is None and body.version is None and body.screen_version is not None
    if not (one or whole):
        return JSONResponse(status_code=422, content={"code": "refused",
                                                      "detail": "Name the pane and its version, or the screen's version."})
    try:
        if one:
            store().take_off(screen_id, body.pane, expect=body.version)
        else:
            store().take_off(screen_id, None, screen_version=body.screen_version)
        return _fresh(store().remote(screen_id))
    except DisplayError as exc:
        return _remote_refusal(exc)
