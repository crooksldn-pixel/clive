"""The owner's research, on the Builds screen: give CLIVE a file, see what it made of it, answer each proposal.

Included in the objectives router (app/routes/objectives.py), so every route here is the owner's
alone, under the same rule (app/routes/actions.py principal_check), and sits at /objectives/research:

    GET  /objectives/research           the Research section (app/builds/research.py); reading it
                                        also takes in what was put in the server folder and starts
                                        reading anything queued
    POST /objectives/research/upload    a research file from the screen (multipart, field "file")
    POST /objectives/research/answer    Adopt, Park or Reject on one proposal, bound to its fingerprint;
                                        Adopt also prepares its build request on a card he holds
    POST /objectives/research/prepare   an adopted proposal's build request again, when its card has gone

Nothing here files, sends or changes anything outside CLIVE's own records: a build request is only
ever prepared, and filing it is his hold on its card (POST /actions/{id}/commit), as for every change.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.routes.actions import principal_check

router = APIRouter(prefix="/research")

_SESSION = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


class AnswerBody(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=300)
    fingerprint: str = Field(min_length=64, max_length=64)
    answer: str = Field(min_length=1, max_length=20)
    session_id: str = Field(default="", max_length=100)


class PrepareBody(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=300)
    session_id: str = Field(default="", max_length=100)


def _store():
    from app.research.store import store

    return store()


async def _section() -> dict:
    from app.builds import decisions
    from app.builds import research as section

    return await section.current(_store(), decisions.ledger())


@router.get("")
async def research(brief: int = 0) -> dict:
    """The Research section. The server folder is swept and anything queued starts being read."""
    from app.builds import research as section
    from app.research import flow

    store = _store()
    flow.sweep(store)
    flow.kick(store)
    payload = await _section()
    return section.brief(payload) if brief else payload


@router.post("/upload", response_model=None)
async def upload(file: UploadFile = File(...)) -> dict | JSONResponse:
    """A file George gave on the screen: kept, queued, and read in the background."""
    from app.research import flow
    from app.research.convert import MAX_FILE_BYTES

    data = await file.read(MAX_FILE_BYTES + 1)
    store = _store()
    try:
        record = flow.receive(store, file.filename or "research", data, via="screen")
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"code": "refused", "detail": str(exc)})
    flow.kick(store)
    return {"received": {"id": record["id"], "name": record["name"]}, "section": await _section()}


@router.post("/answer", response_model=None)
async def answer(request: Request, body: AnswerBody) -> dict | JSONResponse:
    """His answer to one proposal, recorded only when it is still the proposal he was shown."""
    from app.builds import decisions
    from app.builds import research as section

    store = _store()
    found = store.proposal(body.proposal_id)
    if found is None:
        return JSONResponse(status_code=409, content={"code": "gone", "detail": "That proposal isn't in the research record any more."})
    record, proposal = found
    if proposal.get("fingerprint") != body.fingerprint:
        return JSONResponse(status_code=409, content={"code": "moved_on", "detail": "That proposal changed since you saw it, so nothing was recorded.",
                                                      "section": await _section()})
    if proposal.get("duplicate_of"):
        return JSONResponse(status_code=409, content={"code": "repeat", "detail": "That one repeats earlier research: answer it there."})
    who, _why = principal_check(request)
    session = body.session_id if _SESSION.fullmatch(body.session_id or "") else f"builds-{uuid.uuid4().hex[:12]}"
    try:
        judged, added = decisions.decide(decisions.ledger(), section.question(record, proposal), body.answer,
                                         principal=who, session_id=session)
    except decisions.DecisionError as exc:
        return JSONResponse(status_code=400, content={"code": "refused", "detail": str(exc)})
    staged = None
    if body.answer == "adopt":
        staged = await _prepare(request, store, record, proposal, body.session_id)
    return {"recorded": added, "chosen": decisions.chosen(judged), "staged": staged, "section": await _section()}


@router.post("/prepare", response_model=None)
async def prepare(request: Request, body: PrepareBody) -> dict | JSONResponse:
    """The build request for a proposal he adopted, prepared again on a card."""
    from app.builds import decisions

    store = _store()
    found = store.proposal(body.proposal_id)
    if found is None:
        return JSONResponse(status_code=409, content={"code": "gone", "detail": "That proposal isn't in the research record any more."})
    record, proposal = found
    try:
        judged = decisions.ledger().effective().get(proposal["id"])
    except decisions.DecisionError as exc:
        return JSONResponse(status_code=409, content={"code": "unreadable", "detail": str(exc)})
    chosen = decisions.chosen(judged) if judged is not None and judged.proposal_fingerprint == proposal.get("fingerprint") else None
    if not chosen or chosen["key"] != "adopt":
        return JSONResponse(status_code=409, content={"code": "not_adopted", "detail": "Only a proposal you adopted has a build request."})
    staged = await _prepare(request, store, record, proposal, body.session_id)
    return {"staged": staged, "section": await _section()}


async def _prepare(request: Request, store, record: dict, proposal: dict, session_id: str) -> dict:
    from app.builds import research as section

    session_id = session_id if _SESSION.fullmatch(session_id or "") else ""
    staged = await section.prepare(request, record, proposal, session_id=session_id)
    if staged.get("ok") and staged.get("request_id"):
        store.note_prepared(record["id"], proposal["id"], staged["request_id"])
    return staged
