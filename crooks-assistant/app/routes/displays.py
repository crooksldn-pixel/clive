"""The owner's screens: a device opens /display, names itself, and asks every couple of
seconds what it should show (app/displays/store.py). Every route here is the owner's alone:
a proxied caller on the allow-list whose device Tailscale confirms, or the server itself only
when CROOKS_WRITES_LOCAL_OWNER says it is him (app/routes/actions.py principal_check)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.displays.store import DisplayError, NotThisScreen, store
from app.routes.actions import principal_check, require_principal

router = APIRouter(prefix="/displays", dependencies=[Depends(require_principal)])


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DoneBody(BaseModel):
    version: int = Field(ge=0)
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


@router.post("/register", response_model=None)
async def register(body: RegisterBody) -> dict | JSONResponse:
    try:
        screen = store().register(body.name)
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "refused", "detail": str(exc)})
    # The key is in this answer and nowhere else: the device keeps it, the store keeps its hash.
    return JSONResponse(content={"id": screen["id"], "name": screen["name"], "key": screen["screen_key"]},
                        headers={"Cache-Control": "no-store"})


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


@router.post("/{screen_id}/done", response_model=None)
async def done(screen_id: str, body: DoneBody, request: Request) -> dict | JSONResponse:
    who, _ = principal_check(request)
    key = _screen_key(request)
    try:
        store().mark_done(screen_id, body.version, screen_key=key, items_seen=body.items_seen, by=who)
    except NotThisScreen as exc:
        return _not_this_screen(exc)
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "stale", "detail": str(exc)})
    return store().poll(screen_id, key) or {}
