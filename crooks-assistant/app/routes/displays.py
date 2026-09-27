"""The owner's screens: a device opens /display, names itself, and asks every couple of
seconds what it should show (app/displays/store.py). Every route here is the owner's alone:
a proxied caller on the allow-list whose device Tailscale confirms, or the server itself only
when CROOKS_WRITES_LOCAL_OWNER says it is him (app/routes/actions.py principal_check)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.displays.store import DisplayError, store
from app.routes.actions import principal_check, require_principal

router = APIRouter(prefix="/displays", dependencies=[Depends(require_principal)])


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DoneBody(BaseModel):
    version: int = Field(ge=0)


@router.get("")
async def screens() -> dict:
    s = store()
    return {"screens": s.screens(), "done": s.done()}


@router.post("/register", response_model=None)
async def register(body: RegisterBody) -> dict | JSONResponse:
    try:
        screen = store().register(body.name)
    except DisplayError as exc:
        return JSONResponse(status_code=400, content={"code": "refused", "detail": str(exc)})
    return {"id": screen["id"], "name": screen["name"]}


@router.get("/{screen_id}", response_model=None)
async def poll(screen_id: str, v: int = -1) -> dict | Response:
    """What to show. 204 when nothing has changed since version `v`."""
    now = store().poll(screen_id)
    if now is None:
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": "No such screen."})
    if int(now["version"]) == int(v):
        return Response(status_code=204)
    return now


@router.post("/{screen_id}/done", response_model=None)
async def done(screen_id: str, body: DoneBody, request: Request) -> dict | JSONResponse:
    who, _ = principal_check(request)
    try:
        store().mark_done(screen_id, body.version, by=who)
    except DisplayError as exc:
        return JSONResponse(status_code=409, content={"code": "stale", "detail": str(exc)})
    return store().poll(screen_id) or {}
