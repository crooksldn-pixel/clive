"""Who a tool call is being made for, carried explicitly and refused by default (the 2026-09-27
deploy review, round 7, F-NEW-TOOLS, F-NEW-TOOLS-PATH and B-01).

A tool runs only when the work it is part of holds an active Authority, and there are exactly
two ways to hold one:

- **owner**: made by the door in app/main.py for a request that passed the owner rule
  (principal_verdict), and revoked the moment that request's response has been sent. Every task
  the request starts copies the context and so sees the same object; revocation is on the object,
  so a task that outlives the request (a detached task, a late SDK callback) is refused from then
  on, whatever copy of the context it holds.
- **service**: derived explicitly from an active owner authority for a named, bounded piece of
  work the owner's request started and that may finish after it — a speculative read
  (app/memory/prefetch.py). It carries a purpose, is read-only by construction of its callers,
  and expires on its own clock whether or not anything revokes it.

Nothing else makes one. No authority, an expired one or a revoked one: the dispatcher refuses
the tool before its handler is reached (app/tools/dispatch.py), and so does the Agent SDK's
PreToolUse hook. The real SDK path carries the turn's authority across the SDK boundary itself
(app/providers/max_agent_sdk.py _Conversation.authority), because the SDK runs tool callbacks on
tasks of its own that were not started by the request.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

OWNER = "owner"
SERVICE = "service"
# An owner request that never finishes sending its answer still loses its authority at this age.
OWNER_BACKSTOP_S = 15 * 60
MAX_SERVICE_S = 120.0


@dataclass(eq=False)
class Authority:
    kind: str
    who: str
    purpose: str = ""
    expires_at: float = 0.0
    revoked: bool = field(default=False)

    @property
    def active(self) -> bool:
        return not self.revoked and self.kind in (OWNER, SERVICE) and time.monotonic() < self.expires_at

    def revoke(self) -> None:
        self.revoked = True

    def derive(self, purpose: str, ttl_s: float) -> Authority | None:
        """A service authority for bounded work this owner request started. None unless this
        is an active owner authority."""
        if self.kind != OWNER or not self.active or not purpose:
            return None
        ttl = max(0.0, min(float(ttl_s), MAX_SERVICE_S))
        return Authority(SERVICE, self.who, purpose=purpose, expires_at=time.monotonic() + ttl)


TOOL_AUTHORITY: ContextVar[Authority | None] = ContextVar("crooks_tool_authority", default=None)


def for_owner(who: str) -> Authority:
    """Only the door calls this, and only after the owner rule has passed."""
    return Authority(OWNER, str(who or "owner"), expires_at=time.monotonic() + OWNER_BACKSTOP_S)


def current() -> Authority | None:
    """The authority this work holds, if it is still active; None otherwise."""
    held = TOOL_AUTHORITY.get()
    return held if held is not None and held.active else None


@contextmanager
def acting_as(authority: Authority | None) -> Iterator[None]:
    """Run a block under this authority (None: under none, which refuses every tool)."""
    token = TOOL_AUTHORITY.set(authority)
    try:
        yield
    finally:
        TOOL_AUTHORITY.reset(token)
