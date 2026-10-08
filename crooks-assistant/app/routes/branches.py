"""Where a conversation's screen is: its branch, and the trail it moves along.

  GET  /branches                   ?session_id=            what there is
  POST /branches/{id}/mark         {session_id, tab, scroll, of}
  POST /branches/{id}/back         {session_id}
  POST /branches/{id}/forward      {session_id}

A conversation has one branch from its first question (app/session/branch.py): the record it is
on, its working set, the tab chosen on each record and how far the screen was scrolled, and the
trail of what it has looked at. The tablet asks for it after a reload, marks it as the screen
moves, and steps its trail with Back and Forward.

The user-facing Split — dividing the orb in two with fork, then focus, background, merge and
cancel on the halves — was retired by DEC-050 and its five routes were deleted on the owner's
ruling of 8 October (DEC-071, ruling 37). What a branch keeps for itself stays, as DEC-050 allows
for internal branch mechanics with a responsibility of their own.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from app.observability import timeline
from app.routes.actions import session_matches
from app.session.branch import Branch

router = APIRouter(prefix="/branches", tags=["branches"])


def _refuse(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _session(request: Request, session_id: str):
    runtime = request.app.state.runtime
    session_id = (session_id or "").strip()
    if not session_id:
        return None, _refuse(400, "wrong_session", "The session is missing.")
    # Created on demand, as /turn creates it: the first thing a reloaded tablet does is ask
    # where it was, which may be before any question has made the conversation exist.
    session = runtime.sessions.get_or_create(session_id)
    if not session_matches(session, request):
        return None, _refuse(403, "wrong_session", "That conversation belongs to another login.")
    return session, None


def _live(session) -> list[Branch]:
    return [b for b in session.branches.values() if b.status in ("ACTIVE", "BACKGROUND")]


def _shape(session) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "focused": session.focused_branch,
        "branches": [b.public() for b in _live(session)],
    }


@router.get("", response_model=None)
async def listing(request: Request, session_id: str = "") -> JSONResponse | dict:
    session, refusal = _session(request, session_id)
    if refusal is not None:
        return refusal
    session.branch()      # the first branch exists from the first question
    return _shape(session)


@router.post("/{branch_id}/mark", response_model=None)
async def mark(request: Request, branch_id: str, session_id: str = Form(default=""), tab: str = Form(default=""), scroll: str = Form(default=""), of: str = Form(default="")) -> JSONResponse | dict:
    """The screen moved: a tab was chosen, or it was scrolled. Kept against the branch's
    current stop so that going back and coming forward again puts it where it was.

    `of` is the RECORD the tab belongs to, as a render identity ("customer:cus_1"). Without
    it a tab was branch state, and the tablet handed one value to every card that had tabs:
    one tap on Email put twenty-three later cards on Email, for records the owner had never
    opened (D-2). A tab is one record's.
    """
    session, refusal = _session(request, session_id)
    if refusal is not None:
        return refusal
    if branch_id not in session.branches:
        return _refuse(404, "unknown_branch", "There is no such branch in this conversation.")
    try:
        depth = int(scroll) if scroll not in (None, "") else None
    except (TypeError, ValueError):
        depth = None
    session.branches[branch_id].mark(tab=tab or None, scroll=depth, of=str(of or "")[:160])
    return {"branch": session.branches[branch_id].public()}


@router.post("/{branch_id}/back", response_model=None)
async def back(request: Request, branch_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    return await _step(request, branch_id, session_id, forward=False)


@router.post("/{branch_id}/forward", response_model=None)
async def forward(request: Request, branch_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    return await _step(request, branch_id, session_id, forward=True)


async def _step(request: Request, branch_id: str, session_id: str, *, forward: bool) -> JSONResponse | dict:
    """Move one branch's trail, for a caller that wants the position and not the card.

    The move itself is `app/commands.py:move_nav` — the same arithmetic `POST /command` uses.
    It called `branch.back()`/`branch.forward()` directly
    until now, which made this the second implementation of Back that `app/commands.py`'s
    docstring names by path and says it removed; the two were free to drift, and this one had
    no branch-status check, so it would walk the trail of a branch that had been merged away.

    What it deliberately does NOT do is draw. A caller that wants the record wants
    `POST /command`, which replays it, reads it when memory has dropped it, and says a
    sentence. This returns where the branch now is, and nothing else.
    """
    from app import commands

    session, refusal = _session(request, session_id)
    if refusal is not None:
        return refusal
    if branch_id not in session.branches:
        return _refuse(404, "unknown_branch", "There is no such branch in this conversation.")
    branch = session.branches[branch_id]
    if branch.status != "ACTIVE":
        return _refuse(409, "branch_closed", f"That half is {branch.status.lower()} and no longer moves.")
    moved = commands.move_nav(branch, "forward" if forward else "back")
    entry = branch.nav[branch.nav_index] if moved.get("landed") and 0 <= branch.nav_index < len(branch.nav) else None
    timeline.emit("branch_navigated", session_id=session.session_id, branch_id=branch_id,
                  nav="forward" if forward else "back", landed=bool(entry), depth=max(0, branch.nav_index))
    return {"branch": branch.public(), "landed": entry.public() if entry is not None else None}
