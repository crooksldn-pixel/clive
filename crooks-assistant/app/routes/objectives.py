"""The owner's screen onto objectives: list, read, create, answer, authorise, tick a task, close.

These are the only callers that act as the owner (``by="owner"``): authorising a work item and
closing an objective are refused to the model's tools by the store itself. Access is the
application's: the tailnet allow-list middleware in app/main.py has already refused any caller
who is not one of the owner's logins. Nothing here reaches a store, an inbox or the outside world,
with one read-only exception: /objectives/builds and /objectives/gaps read the engineering loop's
published status and compare built candidates with the trunk (each at most once a minute).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.objectives.store import ObjectiveError, store
from app.routes.actions import require_principal

# The owner's records: every route here is his alone (app/routes/actions.py principal_check).
router = APIRouter(prefix="/objectives", dependencies=[Depends(require_principal)])


class CreateBody(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    title: str = Field(default="", max_length=120)
    deadline: str | None = Field(default=None, max_length=10)
    kind: str = Field(default="business", max_length=20)


class TextBody(BaseModel):
    text: str = Field(default="", max_length=2000)


class TaskBody(BaseModel):
    done: bool


class StatusBody(BaseModel):
    status: str = Field(max_length=20)
    text: str = Field(default="", max_length=2000)


def _refused(exc: ObjectiveError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": "refused", "detail": str(exc)})


def _full(obj) -> dict:
    # `card` is what the sheet draws the objective's shape from: the same payload as the
    # conversation's card (app/objectives/cards.py), so the two cannot show it differently.
    from app.objectives import cards

    return {**obj.to_dict(), "summary": obj.summary(), "card": cards.data(obj)}


@router.get("")
async def list_objectives(request: Request, session_id: str = "") -> dict:
    """The owner's live objectives. Asked with the conversation the owner's page is in, each one
    listed is shown to that conversation, so he can hold it and put it on a screen (round 12,
    app/displays/put.py)."""
    from app.displays.put import issue_listed

    live = store().live()
    issue_listed(request, session_id, [o.id for o in live])
    return {"objectives": [o.summary() for o in live],
            "needs_you": sum(len(o.open_("attention")) for o in live)}


@router.get("/builds")
async def builds() -> dict:
    """Each live build objective's latest engineering requests, in the loop's own words."""
    from app.tools.engineering_tools import build_progress

    live = [o for o in store().live() if o.kind == "build" and o.engineering]
    recent = {o.id: [str(e.get("request_id") or "") for e in o.engineering[-3:]] for o in live}
    rows = await build_progress([rid for ids in recent.values() for rid in ids])
    return {"builds": {oid: [rows[rid] for rid in ids if rid in rows] for oid, ids in recent.items()}}


@router.get("/gaps")
async def gaps() -> dict:
    """What CLIVE cannot do yet, the most frequent first, with what became of each gap: the
    builds proposed, filed, built and merged, and whether the gap came back after its fix."""
    from app.objectives import gaps as gap_record
    from app.tools.engineering_tools import refresh_gaps

    record = gap_record.ledger()
    if record is None:
        return {"summary": {"gaps": 0}, "gaps": [], "misjudged": []}
    await refresh_gaps()
    return record.report()


@router.get("/{objective_id}", response_model=None)
async def read_objective(objective_id: str) -> dict | JSONResponse:
    try:
        return _full(store().get(objective_id))
    except ObjectiveError as exc:
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": str(exc)})


@router.post("", response_model=None)
async def create_objective(body: CreateBody) -> dict | JSONResponse:
    title = body.title.strip() or " ".join(body.request.split()[:6])
    try:
        return _full(store().create(title=title, request=body.request, deadline=body.deadline, by="owner",
                                    kind=body.kind))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/note", response_model=None)
async def owner_note(objective_id: str, body: TextBody) -> dict | JSONResponse:
    try:
        return _full(store().owner_note(objective_id, body.text))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/answer/{entry_id}", response_model=None)
async def answer(objective_id: str, entry_id: str, body: TextBody) -> dict | JSONResponse:
    """The owner answers a question, or settles an unknown or blocker; the answer is kept as a fact."""
    s = store()
    try:
        if body.text.strip():
            s.owner_note(objective_id, body.text)
        return _full(s.resolve(objective_id, entry_id, note=body.text, by="owner"))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/items/{item_id}/authorise", response_model=None)
async def authorise(objective_id: str, item_id: str) -> dict | JSONResponse:
    try:
        return _full(store().authorise(objective_id, item_id))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/tasks/{task_id}", response_model=None)
async def tick(objective_id: str, task_id: str, body: TaskBody) -> dict | JSONResponse:
    """The owner ticks one of the delegated tasks done, or back to not done, on his screen. It
    changes CLIVE's list and nothing else: nobody is told."""
    try:
        return _full(store().task(objective_id, item_id=task_id, done=body.done, by="owner"))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/status", response_model=None)
async def status(objective_id: str, body: StatusBody) -> dict | JSONResponse:
    try:
        return _full(store().set_status(objective_id, body.status, note=body.text, by="owner"))
    except ObjectiveError as exc:
        return _refused(exc)
