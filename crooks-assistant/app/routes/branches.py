"""The orb, divided.

  POST /branches/fork              {session_id, from}      two-finger pull apart
  POST /branches/{id}/focus        {session_id}            tap the one you want
  POST /branches/{id}/background   {session_id}            drag it aside
  POST /branches/{id}/merge        {session_id}            pinch together
  POST /branches/{id}/cancel       {session_id}            flick it away
  POST /branches/{id}/mark         {session_id, tab, scroll}
  POST /branches/{id}/back         {session_id}
  POST /branches/{id}/forward      {session_id}
  GET  /branches                   ?session_id=            what there is

Two branches at most. What they share is what is safe to share — the read caches, the source
clients, the issued-id ledger, because they are one conversation and one login. What they
never share is a position, a proposal or an approval:

* A branch's pending changes are its own. A merge brings back a structured summary of what
  the other half FOUND; every proposal stays where it was staged, exact, and unapproved.
* A branch working in the background cannot commit anything. The commit route refuses it,
  and this route refuses to background a branch with a change waiting rather than leaving
  a card that a gesture could no longer apply.
* Cancelling one branch cancels its work and nothing else: the other half is untouched.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from app.observability import timeline
from app.routes.actions import session_matches
from app.session.branch import MAX_BRANCHES, Branch, fork_from

log = logging.getLogger("crooks.branches")

router = APIRouter(prefix="/branches", tags=["branches"])


def _refuse(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _session(request: Request, session_id: str):
    runtime = request.app.state.runtime
    session_id = (session_id or "").strip()
    if not session_id:
        return None, _refuse(400, "wrong_session", "The session is missing.")
    # Created on demand, as /turn creates it: the first thing an idle tablet does may be to
    # divide the orb, before any question has made the conversation exist on the Mac. A
    # refusal here ("that conversation has gone") was the split's first failure on the bench.
    session = runtime.sessions.get_or_create(session_id)
    if not session_matches(session, request):
        return None, _refuse(403, "wrong_session", "That conversation belongs to another login.")
    return session, None


def _live(session) -> list[Branch]:
    return [b for b in session.branches.values() if b.status in ("ACTIVE", "BACKGROUND")]


# Halves that are over are kept only long enough for a card still on the tablet to be settled
# against them, then dropped. Without this a fork/close loop would grow the session for as
# long as it lasted.
KEEP_CLOSED = 2


def _prune(session) -> None:
    closed = [b for b in session.branches.values() if b.status in ("MERGED", "CANCELLED")]
    for branch in sorted(closed, key=lambda b: b.created_at)[: max(0, len(closed) - KEEP_CLOSED)]:
        session.branches.pop(branch.branch_id, None)


def _shape(session) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "focused": session.focused_branch,
        "branches": [b.public() for b in _live(session)],
        "can_fork": len(_live(session)) < MAX_BRANCHES,
    }


def _waiting(session, branch_id: str) -> list[str]:
    """Every change staged in this branch that is still WAITING for a gesture: work the owner
    has not decided about.

    An undo offer is not that (see `_undoable`), and neither is a proposal whose time has run
    out. On 11 September a merge said "2 changes still waiting over there" when both were undo
    offers for changes already made, and the older of the two had expired two minutes before.
    """
    from app.actions.engine import waiting_ids

    return waiting_ids(session, branch_id=branch_id)


def _undoable(session, branch_id: str) -> list[str]:
    """The undo offers standing in this branch: changes that are DONE and can still be put
    back. Named so the owner can be told they exist, and never counted as work outstanding."""
    from app.actions.engine import undoable_ids

    return undoable_ids(session, branch_id=branch_id)


@router.get("", response_model=None)
async def listing(request: Request, session_id: str = "") -> JSONResponse | dict:
    session, refusal = _session(request, session_id)
    if refusal is not None:
        return refusal
    session.branch()      # the first branch exists from the first question
    return _shape(session)


@router.post("/fork", response_model=None)
async def fork(request: Request, session_id: str = Form(default=""), label: str = Form(default="")) -> JSONResponse | dict:
    """The orb divides. The new half INHERITS what the old one holds — the record it is on,
    the set, what it has already looked at — and shows none of what the old one is showing.

    What each half holds is `app/session/branch.py:fork_from`, which is one function so that
    the contract has one test. Both halves are named here, because a chip reading "First" beside
    a chip reading "Second" is not a difference the owner can see on an eight-inch screen —
    each says what it is looking at, and what it is doing."""
    session, refusal = _session(request, session_id)
    if refusal is not None:
        return refusal
    parent = session.branch()
    if len(_live(session)) >= MAX_BRANCHES:
        return _refuse(409, "too_many_branches", f"The orb divides once. Merge or close one of the {MAX_BRANCHES} first.")
    child = fork_from(parent, label=label)
    if not parent.label:
        parent.label = "first"
    session.branches[child.branch_id] = child
    timeline.emit("branch_forked", session_id=session.session_id, branch_id=child.branch_id,
                  parent_branch_id=parent.branch_id,
                  # What each half now says it is, so a fork that produced two identical
                  # screens is visible in the timeline rather than only in the owner's face.
                  headline=child.headline()["title"], parent_headline=parent.headline()["title"])
    log.info("branch %s forked from %s", child.branch_id, parent.branch_id)
    return {**_shape(session), "branch_id": child.branch_id}


@router.post("/{branch_id}/focus", response_model=None)
async def focus(request: Request, branch_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    session, refusal = _session(request, session_id)
    if refusal is not None:
        return refusal
    if branch_id not in session.branches:
        return _refuse(404, "unknown_branch", "There is no such branch in this conversation.")
    branch = session.branches[branch_id]
    if branch.status in ("MERGED", "CANCELLED"):
        # A half that is over is kept for a while only so a card still on the glass can be
        # settled against it. A stale chip tapped after a merge or a close used to make it the
        # focused half again: the next sentence posted without a half was then answered on a
        # half nobody could see, and any change it staged could never be applied ("that half
        # is closed"). Showing it is already refused (`branch.show`), and so is moving its
        # trail (`_step`); focusing it is refused the same way (round 9, I-tests3 I-03).
        return _refuse(409, "branch_closed", f"That half is {branch.status.lower()}. Tap the one that is open.")
    if branch.status == "BACKGROUND":
        branch.status = "ACTIVE"
    session.focus_branch(branch_id)
    # What the tablet is about to draw, named on the event itself. The live session recorded
    # six `branch_focused` in nine seconds and the report could only say "focus changed with
    # nothing redrawn"; with the headline here, a focus that changes nothing visible is a
    # difference two events apart rather than something only the owner can see.
    timeline.emit("branch_focused", session_id=session.session_id, branch_id=branch_id,
                  headline=branch.headline()["title"], state=branch.state(),
                  workspace=bool(branch.last_ui or branch.last_answer))
    return _shape(session)


@router.post("/{branch_id}/background", response_model=None)
async def background(request: Request, branch_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    """Put a branch to one side. It carries on reading; it can never commit while it is there,
    so a change waiting for a gesture stops it rather than being left unappliable.

    An undo offer does not stop it: the change it would reverse is done, and an offer nobody
    has to answer is not a reason to keep a half in front of the owner."""
    session, refusal = _session(request, session_id)
    if refusal is not None:
        return refusal
    if branch_id not in session.branches:
        return _refuse(404, "unknown_branch", "There is no such branch in this conversation.")
    branch = session.branches[branch_id]
    if branch.status in ("MERGED", "CANCELLED"):
        # Over is over. Putting a merged or cancelled half aside used to make it BACKGROUND —
        # live again — and a tap on its chip then made it the focused half (round 13, S2Bb-03).
        return _refuse(409, "branch_closed", f"That half is {branch.status.lower()}. Tap the one that is open.")
    waiting = _waiting(session, branch_id)
    if waiting:
        return _refuse(409, "change_waiting", "That half has a change waiting for you. Apply it or let it go first.")
    branch.status = "BACKGROUND"
    if session.focused_branch == branch_id:
        other = next((b.branch_id for b in _live(session) if b.branch_id != branch_id and b.status == "ACTIVE"), "")
        if other:
            session.focused_branch = other
        else:
            branch.status = "ACTIVE"
            return _refuse(409, "last_branch", "That is the only half there is; there is nothing to put it behind.")
    timeline.emit("branch_backgrounded", session_id=session.session_id, branch_id=branch_id)
    return _shape(session)


@router.post("/{branch_id}/merge", response_model=None)
async def merge(request: Request, branch_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    """Pinch together. What comes back is a STRUCTURED SUMMARY of what that half found — the
    entities it looked at, the reads it made, the set it holds — never a transcript stitched
    onto another. Its pending changes are not brought over and are not approved: a change
    belongs to the branch it was asked for in, and a merge is not a gesture."""
    session, refusal = _session(request, session_id)
    if refusal is not None:
        return refusal
    if branch_id not in session.branches:
        return _refuse(404, "unknown_branch", "There is no such branch in this conversation.")
    branch = session.branches[branch_id]
    if branch.status in ("MERGED", "CANCELLED"):
        return _refuse(409, "branch_closed", f"That half is {branch.status.lower()}. Tap the one that is open.")
    if len(_live(session)) <= 1:
        # A merge brings one half back into the other. With only one there is nothing to bring
        # it into, and merging it anyway left the conversation with no live half (S2Bb-03).
        return _refuse(409, "last_branch", "That is the only half there is; there is nothing to merge it into.")
    if branch.branch_id == session.focused_branch:
        return _refuse(409, "merge_into_itself", "Tap the half you want to keep first, then pinch.")
    waiting = _waiting(session, branch_id)
    undoable = _undoable(session, branch_id)
    summary = {
        "branch_id": branch.branch_id,
        "label": branch.label,
        # What that half WAS, in the line the tablet had been drawing on it, so the owner is
        # told what came back in the same words he had been reading.
        "headline": branch.headline(),
        "state": branch.state(),
        "entity": branch.entity,
        "set_id": branch.set_id or None,
        "workflow": branch.workflow.public() if branch.workflow else None,
        "looked_at": list(branch.recent_entities[:6]),
        "read": [{"tool": r["tool"], "summary": r["summary"], "cached": r["cached"]} for r in branch.recent_results[:6]],
        "actions": list(branch.recent_actions[:4]),
        # Named, not moved: the owner is told what is still waiting over there and where.
        "still_waiting": waiting,
        # And, separately, what is merely on offer: an undo of something already done over
        # there. It is not waiting on him, and the toast must not say that it is.
        "undoable": undoable,
    }
    branch.status = "MERGED"
    _prune(session)
    keeper = session.branch()
    for entity in reversed(branch.recent_entities[:6]):
        keeper.remember_entity(entity["kind"], entity["ref"], entity["label"])
    timeline.emit("branch_merged", session_id=session.session_id, branch_id=branch_id, into=keeper.branch_id,
                  looked_at=len(summary["looked_at"]), read=len(summary["read"]), still_waiting=len(waiting) or None,
                  undoable=len(undoable) or None)
    return {**_shape(session), "merged": summary}


@router.post("/{branch_id}/cancel", response_model=None)
async def cancel(request: Request, branch_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    """Flick it away. Its speculative reads are dropped and its pending changes withdrawn —
    and nothing of the other half is touched. That is the whole point of the scoping."""
    runtime = request.app.state.runtime
    session, refusal = _session(request, session_id)
    if refusal is not None:
        return refusal
    if branch_id not in session.branches:
        return _refuse(404, "unknown_branch", "There is no such branch in this conversation.")
    if len(_live(session)) <= 1:
        return _refuse(409, "last_branch", "That is the only half there is.")
    branch = session.branches[branch_id]
    branch.status = "CANCELLED"
    branch.task = None
    from app.memory.prefetch import current as prefetcher

    dropped = prefetcher().cancel_branch(branch_id)
    # The ids first, so the answer can name exactly which cards the tablet must settle. A
    # half that is closing takes its undo offers with it as well as its waiting changes:
    # nothing of a closed half may stay tappable, whichever kind of card it is.
    revoked = _waiting(session, branch_id) + _undoable(session, branch_id)
    runtime.actions.revoke_ids(revoked, "that half was closed")
    if session.focused_branch == branch_id:
        session.focused_branch = next((b.branch_id for b in _live(session)), "")
        if not session.focused_branch:
            session.branch()
    _prune(session)
    timeline.emit("branch_cancelled", session_id=session.session_id, branch_id=branch_id, prefetches=dropped, revoked=len(revoked) or None)
    return {**_shape(session), "revoked": revoked, "prefetches_stopped": dropped}


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
