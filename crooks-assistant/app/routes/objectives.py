"""The owner's screen onto objectives: list, read, create, answer, authorise, tick a task, close.

These are the only callers that act as the owner (``by="owner"``): authorising a work item and
closing an objective are refused to the model's tools by the store itself. His touches on an
objective (make a stage now, tick or hand over a task, move the date it must land by) each answer
with the record and, when they changed something, an undo offer he has six seconds to take
(``POST /objectives/{id}/undo``); a touch that changed nothing says so instead, in ``said``. Access is the
application's: the tailnet allow-list middleware in app/main.py has already refused any caller
who is not one of the owner's logins. Nothing here reaches a store, an inbox or the outside world,
with one read-only exception: /objectives/builds and /objectives/gaps read the engineering loop's
published status and compare built candidates with the trunk (each at most once a minute).

The Builds screen (app/builds/) reads the same, plus each request's own file for its title, and
records one thing: George's answer to a build that waits on him, as an owner judgment in the
judgment ledger beside the objectives (POST /objectives/builds/decide). That answer is CLIVE's own
record; nothing is filed, sent or lifted by it. GET /objectives/builds/decisions reads it back.
"""

from __future__ import annotations

import asyncio
import re
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.objectives.store import ObjectiveError, store
from app.routes.actions import principal_check, require_principal

# The owner's records: every route here is his alone (app/routes/actions.py principal_check).
router = APIRouter(prefix="/objectives", dependencies=[Depends(require_principal)])


class TaskIn(BaseModel):
    who: str = Field(max_length=200)
    text: str = Field(max_length=2000)
    due: str | None = Field(default=None, max_length=10)


class CreateBody(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    title: str = Field(default="", max_length=120)
    deadline: str | None = Field(default=None, max_length=10)
    kind: str = Field(default="business", max_length=20)
    # A project is opened with its stages, in order, and a tasks objective with its tasks, each with
    # who does it (ObjectiveStore.create). Without them both kinds were always refused here. The
    # bounds only keep a request small: the store refuses past its own limits, whole and in words
    # (a project's eleventh stage, a sixty-first task), before anything is recorded.
    stages: list[str] = Field(default_factory=list, max_length=40)
    tasks: list[TaskIn] = Field(default_factory=list, max_length=200)


class TextBody(BaseModel):
    text: str = Field(default="", max_length=2000)


class TaskBody(BaseModel):
    # Ticked done or open, handed to someone else, or both; at least one (`tick`).
    done: bool | None = None
    who: str | None = Field(default=None, max_length=200)


class StageBody(BaseModel):
    stage: str = Field(min_length=1, max_length=120)


class DeadlineBody(BaseModel):
    deadline: str = Field(default="", max_length=10)


class TargetBody(BaseModel):
    # Bounded in words by the store (1 to 100,000), not here, so a target past it is refused as
    # every other touch is: a 400 that says why.
    target: int


class DecideBody(BaseModel):
    # Which build, and the question exactly as the screen drew it: an answer binds to what he saw.
    build: str = Field(min_length=1, max_length=80)
    proposal_id: str = Field(min_length=1, max_length=300)
    fingerprint: str = Field(min_length=64, max_length=64)
    answer: str = Field(min_length=1, max_length=20)
    session_id: str = Field(default="", max_length=100)


class UndoBody(BaseModel):
    token: str = Field(min_length=1, max_length=100)


class StatusBody(BaseModel):
    status: str = Field(max_length=20)
    text: str = Field(default="", max_length=2000)


def _refused(exc: ObjectiveError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": "refused", "detail": str(exc)})


async def _counted(obj) -> dict | None:
    """What has sold of the objective's number, read from the order cache; None without one."""
    from app.objectives import count

    return await count.count(obj.number, deadline=obj.deadline) if obj.number else None


def _summary(obj, tally: dict | None) -> dict:
    """The home row's summary, with where the number stands when it was counted."""
    from app.objectives import count

    summary = obj.summary()
    if summary.get("number") and tally is not None:
        summary["number"] = {**summary["number"], **count.short(tally)}
    return summary


async def _full(obj) -> dict:
    # `card` is what the sheet draws the objective's shape from: the same payload as the
    # conversation's card (app/objectives/cards.py), so the two cannot show it differently.
    from app.objectives import cards

    tally = await _counted(obj)
    return {**obj.to_dict(), "summary": _summary(obj, tally), "card": cards.data(obj, tally)}


async def _touched(answer) -> dict:
    """A touch's answer: the record, the undo offer for what it changed, or the line saying it
    changed nothing."""
    obj, undo, said = answer
    return {**await _full(obj), "undo": undo, "said": said}


@router.get("")
async def list_objectives(request: Request, session_id: str = "") -> dict:
    """The owner's live objectives. Asked with the conversation the owner's page is in, each one
    listed is shown to that conversation, so he can hold it and put it on a screen (round 12,
    app/displays/put.py)."""
    from app.displays.put import issue_listed

    live = store().live()
    issue_listed(request, session_id, [o.id for o in live])
    tallies = await asyncio.gather(*(_counted(o) for o in live))
    return {"objectives": [_summary(o, tally) for o, tally in zip(live, tallies, strict=True)],
            "needs_you": sum(len(o.open_("attention")) for o in live)}


@router.get("/builds")
async def builds() -> dict:
    """Each live build objective's latest engineering requests, in the loop's own words."""
    from app.tools.engineering_tools import build_progress

    live = [o for o in store().live() if o.kind == "build" and o.engineering]
    recent = {o.id: [str(e.get("request_id") or "") for e in o.engineering[-3:]] for o in live}
    rows = await build_progress([rid for ids in recent.values() for rid in ids])
    return {"builds": {oid: [rows[rid] for rid in ids if rid in rows] for oid, ids in recent.items()}}


@router.get("/builds/board")
async def builds_board(brief: int = 0) -> dict:
    """Every build of CLIVE itself in plain words, grouped for the Builds screen (app/builds/board.py);
    with `brief`, only the counts and the line the home's Builds row says."""
    from app.builds import read

    payload = await read.current()
    return read.brief(payload) if brief else payload


_SESSION = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


@router.post("/builds/decide", response_model=None)
async def builds_decide(request: Request, body: DecideBody) -> dict | JSONResponse:
    """George answers the question a build puts to him. Recorded only when the question is still the
    one he was shown; a build that moved on answers 409 with the question as it stands now."""
    from app.builds import decisions, read

    question = await read.question(body.build)
    if question is None:
        return JSONResponse(status_code=409, content={"code": "no_question",
                                                      "detail": "This build isn't waiting on your answer any more."})
    if (question["proposal_id"], question["fingerprint"]) != (body.proposal_id, body.fingerprint):
        return JSONResponse(status_code=409, content={
            "code": "moved_on", "detail": "This build moved on since you saw it, so nothing was recorded. "
                                          "Here is the question as it stands now.", "question": question})
    who, _why = principal_check(request)
    session = body.session_id if _SESSION.fullmatch(body.session_id or "") else f"builds-{uuid.uuid4().hex[:12]}"
    try:
        record, added = decisions.decide(decisions.ledger(), question, body.answer, principal=who, session_id=session)
    except decisions.DecisionError as exc:
        return JSONResponse(status_code=400, content={"code": "refused", "detail": str(exc)})
    return {"recorded": added, "chosen": decisions.chosen(record), "board": await read.current()}


@router.get("/builds/decisions", response_model=None)
async def builds_decisions() -> dict | JSONResponse:
    """Every answer George gave on a build, in the judgment ledger's own line form, for the
    Director and the loop to read back."""
    from app.builds import decisions

    try:
        return decisions.ledger().read_back()
    except decisions.DecisionError as exc:
        return JSONResponse(status_code=409, content={"code": "unreadable", "detail": str(exc)})


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
        return await _full(store().get(objective_id))
    except ObjectiveError as exc:
        return JSONResponse(status_code=404, content={"code": "not_found", "detail": str(exc)})


@router.post("", response_model=None)
async def create_objective(body: CreateBody) -> dict | JSONResponse:
    title = body.title.strip() or " ".join(body.request.split()[:6])
    try:
        return await _full(store().create(title=title, request=body.request, deadline=body.deadline, by="owner",
                                    kind=body.kind, stages=list(body.stages) or None,
                                    tasks=[task.model_dump() for task in body.tasks] or None))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/note", response_model=None)
async def owner_note(objective_id: str, body: TextBody) -> dict | JSONResponse:
    try:
        return await _full(store().owner_note(objective_id, body.text))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/answer/{entry_id}", response_model=None)
async def answer(objective_id: str, entry_id: str, body: TextBody) -> dict | JSONResponse:
    """The owner answers a question, or settles an unknown or blocker; the answer is kept as a fact."""
    s = store()
    try:
        if body.text.strip():
            s.owner_note(objective_id, body.text)
        return await _full(s.resolve(objective_id, entry_id, note=body.text, by="owner"))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/items/{item_id}/authorise", response_model=None)
async def authorise(objective_id: str, item_id: str) -> dict | JSONResponse:
    try:
        return await _full(store().authorise(objective_id, item_id))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/tasks/{task_id}", response_model=None)
async def tick(objective_id: str, task_id: str, body: TaskBody) -> dict | JSONResponse:
    """The owner ticks one of the delegated tasks done, or back to not done, on his screen, or
    hands it to someone else (`who`). It changes CLIVE's list and nothing else: nobody is told."""
    try:
        return await _touched(store().touch_task(objective_id, task_id, done=body.done, who=body.who))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/stage", response_model=None)
async def stage(objective_id: str, body: StageBody) -> dict | JSONResponse:
    """The owner makes a stage the one the project is at now (its name, or "next"). A record of
    where the project is: nothing is ordered, booked or sent by it."""
    try:
        return await _touched(store().touch_stage(objective_id, body.stage))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/deadline", response_model=None)
async def deadline(objective_id: str, body: DeadlineBody) -> dict | JSONResponse:
    """The owner moves the date the objective must land by; an empty date takes it off."""
    try:
        return await _touched(store().touch_deadline(objective_id, body.deadline))
    except ObjectiveError as exc:
        return _refused(exc)


@router.post("/{objective_id}/target", response_model=None)
async def target(objective_id: str, body: TargetBody) -> dict | JSONResponse:
    """The owner drags his number's target up or down. The bar says the new target and, from the
    count, where the pace now takes it; the record keeps only the target, and Undo puts it back."""
    from app.objectives import count

    try:
        answer = await _touched(store().touch_target(objective_id, body.target))
    except ObjectiveError as exc:
        return _refused(exc)
    tally = answer["card"].get("count")
    said = count.pace_words({**tally, "target": answer["number"]["target"], "deadline": answer["deadline"]}) \
        if tally and tally.get("counted") else ""
    if answer["undo"] and said:
        answer["undo"] = {**answer["undo"], "says": f"{answer['undo']['says']}. {said}"}
    return answer


@router.post("/{objective_id}/undo", response_model=None)
async def undo(objective_id: str, body: UndoBody) -> dict | JSONResponse:
    """The owner takes back his last touch on this objective, within its six seconds: what it
    changed is put back exactly, or, if the objective has changed since or the time is up, nothing
    is, and he is told why. `said` is what was put back, in words."""
    try:
        obj, said = store().undo(objective_id, body.token)
    except ObjectiveError as exc:
        return _refused(exc)
    return {**await _full(obj), "said": said}


@router.post("/{objective_id}/status", response_model=None)
async def status(objective_id: str, body: StatusBody) -> dict | JSONResponse:
    try:
        return await _full(store().set_status(objective_id, body.status, note=body.text, by="owner"))
    except ObjectiveError as exc:
        return _refused(exc)
