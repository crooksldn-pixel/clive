"""The session a tool call runs for, reachable from inside the handler without passing it
through every signature: the dispatcher sets it around the call, on the task the call runs
in. A tool that needs the conversation's working sets, or the turn's id, reads it here."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

CURRENT_SESSION: ContextVar[Any] = ContextVar("crooks_current_session", default=None)
# Which half of the orb the running work acts for. Set on the request's own task by /turn,
# /command and /actions/row, and by the provider around each tool call the Agent SDK makes on a
# task of its own, so that two halves thinking at once cannot stamp each other's proposals,
# working sets or glass: the session's own `acting_branch` is one field for both halves and
# holds whichever spoke last. Empty outside a request — then the session's field is the only
# word there is.
CURRENT_BRANCH: ContextVar[str] = ContextVar("crooks_current_branch", default="")


def current_session() -> Any:
    return CURRENT_SESSION.get()


def acting_branch(session: Any) -> str:
    """The branch a proposal, a working set or a binding made now belongs to: the running
    tool call's half when there is one, else the half the request said it was speaking to,
    else the focused half."""
    return str(CURRENT_BRANCH.get() or getattr(session, "acting_branch", "") or getattr(session, "focused_branch", "") or "")
