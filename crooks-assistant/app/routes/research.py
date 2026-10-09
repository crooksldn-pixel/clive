"""The owner's research, on the Builds screen: give CLIVE a file, see what it made of it, answer each proposal.

Included in the objectives router (app/routes/objectives.py), so every route here is the owner's
alone, under the same rule (app/routes/actions.py principal_check), and sits at /objectives/research:

    GET  /objectives/research           the Research section (app/builds/research.py); reading it
                                        also takes in what was put in the server folder and starts
                                        reading anything queued
    POST /objectives/research/upload    a research file from the screen (multipart, field "file"),
                                        refused from its Content-Length before the form is parsed
    POST /objectives/research/answer    Adopt, Park or Reject on one proposal, bound to its fingerprint;
                                        Adopt also prepares its build request on a card he holds
    POST /objectives/research/prepare   an adopted proposal's build request again, when its card has gone

Once a synthesis is live (DEC-078, app/research/synthesis), the section is CLIVE's ideas
(app/builds/research_ideas.py), and the old proposals can't be answered any more (409 "superseded"):

    POST /objectives/research/idea/answer   Approve the work, Not now or Not for CLIVE on one idea, bound
                                            to its fingerprint; Approve also prepares its build request
    POST /objectives/research/idea/prepare  an approved idea's build request again

Nothing here files, sends or changes anything outside CLIVE's own records: a build request is only
ever prepared, and filing it is his hold on its card (POST /actions/{id}/commit), as for every change.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.routes.actions import principal_check

router = APIRouter(prefix="/research")

_SESSION = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
# What an upload of one research file may declare beyond the file itself: the multipart wrapping
# around it (boundaries, the part's headers with its file name), a few hundred bytes in practice.
UPLOAD_WRAPPING_BYTES = 64 << 10


class AnswerBody(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=300)
    fingerprint: str = Field(min_length=64, max_length=64)
    answer: str = Field(min_length=1, max_length=20)
    session_id: str = Field(default="", max_length=100)


class PrepareBody(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=300)
    session_id: str = Field(default="", max_length=100)


class IdeaAnswerBody(BaseModel):
    idea_id: str = Field(min_length=1, max_length=40)
    fingerprint: str = Field(min_length=64, max_length=64)
    answer: str = Field(min_length=1, max_length=20)
    session_id: str = Field(default="", max_length=100)


class IdeaPrepareBody(BaseModel):
    idea_id: str = Field(min_length=1, max_length=40)
    session_id: str = Field(default="", max_length=100)


SUPERSEDED = {"code": "superseded", "detail": "Your research is read as ideas now, so the old recommendations "
              "can't be answered any more. Answer the ideas instead."}


def _store():
    from app.research.store import store

    return store()


async def _section() -> dict:
    from app.builds import decisions, research_ideas
    from app.builds import research as section

    store = _store()
    ideas = await research_ideas.current(store, decisions.ledger())
    if ideas is not None:
        return ideas
    return {**await section.current(store, decisions.ledger()), **research_ideas.not_live(store)}


def _live() -> str:
    from app.research.synthesis.store import synthesis_store

    return synthesis_store(_store()).live()


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
async def upload(request: Request) -> dict | JSONResponse:
    """A file George gave on the screen: kept, queued, and read in the background.

    Its size is checked from Content-Length before the form is parsed (review note 8, 8 Oct): parsing
    spools the whole body to disk before anything sees the file, so a check after it comes too late.
    An upload that does not declare its length is refused too; the screen's always does."""
    from starlette.datastructures import UploadFile
    from starlette.exceptions import HTTPException
    from starlette.formparsers import MultiPartException

    from app.research import flow
    from app.research.convert import MAX_FILE_BYTES

    declared = request.headers.get("content-length", "")
    if not declared.isdigit():
        return JSONResponse(status_code=411, content={"code": "no_length", "detail": "The upload didn't say how big it is, "
                                                      "so CLIVE didn't take it. Add it again from the Builds screen."})
    if int(declared) > MAX_FILE_BYTES + UPLOAD_WRAPPING_BYTES:
        return JSONResponse(status_code=413, content={"code": "too_large", "detail": f"That file is over {MAX_FILE_BYTES >> 20} MB; "
                                                      f"research files are taken up to {MAX_FILE_BYTES >> 20} MB."})
    try:
        form = await request.form(max_files=1, max_fields=1)
    except (HTTPException, MultiPartException):
        return JSONResponse(status_code=400, content={"code": "unreadable", "detail": "The upload couldn't be read, so nothing was taken in."})
    try:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            return JSONResponse(status_code=400, content={"code": "no_file", "detail": "No file came with the upload."})
        data = await file.read(MAX_FILE_BYTES + 1)
        name = file.filename or "research"
    finally:
        await form.close()
    store = _store()
    try:
        record = flow.receive(store, name, data, via="screen")
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"code": "refused", "detail": str(exc)})
    flow.kick(store)
    return {"received": {"id": record["id"], "name": record["name"]}, "section": await _section()}


@router.post("/answer", response_model=None)
async def answer(request: Request, body: AnswerBody) -> dict | JSONResponse:
    """His answer to one proposal, recorded only when it is still the proposal he was shown."""
    from app.builds import decisions
    from app.builds import research as section

    if _live():
        return JSONResponse(status_code=409, content=SUPERSEDED)
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

    if _live():
        return JSONResponse(status_code=409, content=SUPERSEDED)
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


# ------------------------------------------------------------------ ideas (DEC-078)


def _idea(idea_id: str):
    """(store, synthesis store, live generation, the idea) or a 409 saying why there is none."""
    from app.research.synthesis.store import ReadProblem, synthesis_store

    store = _store()
    synth = synthesis_store(store)
    gen = synth.live()
    if not gen:
        return JSONResponse(status_code=409, content={"code": "not_live", "detail": "Your research isn't read as ideas yet."})
    try:
        idea = synth.read_json(synth.idea_path(gen, idea_id), None)
    except (ValueError, ReadProblem) as exc:
        return JSONResponse(status_code=409, content={"code": "gone", "detail": f"That idea couldn't be read: {exc}"})
    if not idea:
        return JSONResponse(status_code=409, content={"code": "gone", "detail": "That idea isn't in CLIVE's ideas any more."})
    if idea.get("status") != "active":
        return JSONResponse(status_code=409, content={"code": "merged", "detail": f"That idea joined {idea.get('merged_into')}: "
                                                      "answer it there."})
    return store, synth, gen, idea


@router.post("/idea/answer", response_model=None)
async def idea_answer(request: Request, body: IdeaAnswerBody) -> dict | JSONResponse:
    """His answer to one idea, recorded only when it is still the idea he was shown. Approve the work
    also prepares its build request on a card; nothing is filed until he holds it."""
    from app.builds import decisions
    from app.research.synthesis import answers as idea_answers

    found = _idea(body.idea_id)
    if isinstance(found, JSONResponse):
        return found
    store, synth, gen, idea = found
    if idea.get("fingerprint") != body.fingerprint:
        return JSONResponse(status_code=409, content={"code": "moved_on", "detail": "That idea changed since you saw it, so "
                                                      "nothing was recorded.", "section": await _section()})
    who, _why = principal_check(request)
    session = body.session_id if _SESSION.fullmatch(body.session_id or "") else f"builds-{uuid.uuid4().hex[:12]}"
    try:
        judged, added = decisions.decide(decisions.ledger(), idea_answers.question(idea), body.answer,
                                         principal=who, session_id=session)
    except decisions.DecisionError as exc:
        return JSONResponse(status_code=400, content={"code": "refused", "detail": str(exc)})
    chosen = decisions.chosen(judged)
    if added:
        synth.event(gen, "owner_answered", idea=idea["id"], answer=body.answer, fingerprint=idea["fingerprint"],
                    said=f"You chose {chosen['label'] if chosen else body.answer}.")
    staged = None
    if body.answer == "go":
        staged = await _prepare_idea(request, store, synth, gen, idea, body.session_id)
    return {"recorded": added, "chosen": chosen, "staged": staged, "section": await _section()}


@router.post("/idea/prepare", response_model=None)
async def idea_prepare(request: Request, body: IdeaPrepareBody) -> dict | JSONResponse:
    """The build request for an idea he approved, prepared again on a card."""
    from app.builds import decisions
    from app.research.synthesis import answers as idea_answers

    found = _idea(body.idea_id)
    if isinstance(found, JSONResponse):
        return found
    store, synth, gen, idea = found
    try:
        latest = idea_answers.latest(decisions.ledger().effective()).get(idea["id"])
    except decisions.DecisionError as exc:
        return JSONResponse(status_code=409, content={"code": "unreadable", "detail": str(exc)})
    owner = idea_answers.said(latest, idea) if latest is not None else None
    if not owner or owner["key"] != "go" or not owner["current"]:
        return JSONResponse(status_code=409, content={"code": "not_approved", "detail": "Only an idea you approved, as it "
                                                      "stands now, has a build request."})
    staged = await _prepare_idea(request, store, synth, gen, idea, body.session_id)
    return {"staged": staged, "section": await _section()}


async def _prepare_idea(request: Request, store, synth, gen: str, idea: dict, session_id: str) -> dict:
    from app.builds import research as section
    from app.builds import research_ideas

    session_id = session_id if _SESSION.fullmatch(session_id or "") else ""
    names = [c.get("document") or "" for c in synth.claims(gen).values()] + [r.get("name") or "" for r in store.documents()]

    def args_for(inbox: str, the_map) -> dict:
        return research_ideas.filing_args(idea, inbox, gen=gen, names=names, the_map=the_map)

    staged = await section.prepare(request, {"id": gen}, {"touches": idea.get("touches") or []}, session_id=session_id,
                                   args_for=args_for)
    if staged.get("ok") and staged.get("request_id"):
        synth.note_prepared(idea["id"], staged["request_id"])
        synth.event(gen, "prepared", idea=idea["id"], request_id=staged["request_id"],
                    said="Its build request was prepared on a card, waiting for your hold.")
    return staged
