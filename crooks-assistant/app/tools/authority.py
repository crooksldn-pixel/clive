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
  (app/memory/prefetch.py). It carries a purpose and an explicit set of the tools it may call,
  which keeps only reads (round 8, F-NEW-TOOLS: SERVICE_READS that the gate also treats as reads,
  never a write or a bulk change, never one of the owner's screens), and expires on its own clock
  whether or not anything revokes it; the work that holds it revokes it when it ends.

Nothing else makes one. No authority, an expired one or a revoked one: the dispatcher refuses
the tool before its handler is reached (app/tools/dispatch.py), and so does the Agent SDK's
PreToolUse hook. A service authority is refused, in the same places and as early, any tool
outside its set, and any call of one the gate would not run at once. The real SDK path carries
the turn's authority across the SDK boundary itself (app/providers/max_agent_sdk.py
_Conversation.authority), because the SDK runs tool callbacks on tasks of its own that were not
started by the request.
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

# Everything bounded service work may ever call (round 8, F-NEW-TOOLS): reads of the shop and the
# inbox that return what they found and change nothing, here or anywhere. The gate runs more
# than these without staging them — tools that open a form, a composer or an objective on the
# Mac, note on an objective, or put something on one of the owner's screens — and those are the
# owner's to ask for, never work that runs on after his answer. Named one by one, like the gate's own allow-list:
# a tool added later is not service work's until it is written here. The prefetch reads exactly
# these (app/memory/prefetch.py).
SERVICE_READS = frozenset({
    "shopify_find_order", "shopify_order_detail", "shopify_find_customer",
    "shopify_customer_history", "shopify_product_info", "shopify_inventory",
    "gmail_search", "gmail_read_thread", "commerce_query", "commerce_aggregate",
    "inventory_query", "email_query",
})


@dataclass(eq=False)
class Authority:
    kind: str
    who: str
    purpose: str = ""
    expires_at: float = 0.0
    revoked: bool = field(default=False)
    # SERVICE only: the tools this work may call, fixed when it is made (round 8, F-NEW-TOOLS).
    # An owner's authority names none; the gate is its only limit.
    tools: frozenset[str] = field(default=frozenset())

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", frozenset(str(t) for t in (self.tools or ())))
        object.__setattr__(self, "_made", True)

    def __setattr__(self, name: str, value) -> None:
        # Once made, an authority can only narrow: revoked, or ending sooner. Who it is for, what it
        # is and which tools it may call never change, so nothing can widen one in place (round 8,
        # F-NEW-TOOLS).
        if getattr(self, "_made", False):
            if name == "revoked" and value is True:
                pass
            elif name == "expires_at" and float(value) <= self.expires_at:
                pass
            else:
                raise AttributeError(f"an authority's {name} cannot be changed once it is made")
        object.__setattr__(self, name, value)

    @property
    def active(self) -> bool:
        if self.revoked or time.monotonic() >= self.expires_at:
            return False
        if self.kind == OWNER:
            return True
        # A service authority that names no tool can do nothing, and is not held to be anything.
        return self.kind == SERVICE and bool(self.tools)

    def revoke(self) -> None:
        self.revoked = True

    def permits(self, tool_name: str) -> bool:
        """Whether this authority may call this tool at all, before the gate is asked about the
        call: an active owner, any tool; an active service authority, a tool in its set that is
        still a service read (read again now, so a set made by hand or a tool that has since
        become a write widens nothing)."""
        if not self.active:
            return False
        if self.kind == OWNER:
            return True
        from app.tools.registry import normalise_tool_name

        name = normalise_tool_name(str(tool_name or ""))
        return name in self.tools and service_read(name)

    def derive(self, purpose: str, ttl_s: float, *, tools) -> Authority | None:
        """A service authority for bounded work this owner request started, able to call only the
        named tools that are reads (service_read) — keyword-only and required, and never empty.
        None unless this is an active owner authority, a purpose is given, and at least one named
        tool is a read."""
        if self.kind != OWNER or not self.active or not purpose:
            return None
        if isinstance(tools, (str, bytes)) or tools is None:
            return None        # a name is not a set of names; nothing is guessed
        from app.tools.registry import normalise_tool_name

        kept = frozenset(normalise_tool_name(str(t)) for t in tools if service_read(str(t)))
        if not kept:
            return None
        ttl = max(0.0, min(float(ttl_s), MAX_SERVICE_S))
        return Authority(SERVICE, self.who, purpose=purpose, expires_at=time.monotonic() + ttl, tools=kept)


def _screen_tool(name: str, spec) -> bool:
    """One of the owner's screens (app/tools/display_tools.py): by its name, or by where its
    handler lives, so a screen tool added later under another name is still one."""
    module = str(getattr(spec.handler, "__module__", "") or "")
    return name.startswith("screen_") or module in ("app.tools.display_tools",) or module.startswith("app.displays")


def service_read(tool_name: str) -> bool:
    """Whether bounded service work may ever call this tool: one of SERVICE_READS, and a read as
    the gate decides a read (app/tools/gate.py) before it looks at any argument — registered with
    no write and no bulk definition, at GREEN or AMBER, on the gate's own allow-list and not a name
    the gate reads as a mutation — and not one of the owner's screens, which put things in front of
    people. Both, so that neither list can make the other wider. What the gate then says of each
    call is asked by the dispatcher, which never runs a service authority's call that the gate
    would stage for the owner."""
    from app.tools import gate, registry

    name = registry.normalise_tool_name(str(tool_name or ""))
    if name not in SERVICE_READS:
        return False
    try:
        spec = registry.get(name)
    except KeyError:
        return False
    if spec.write is not None or spec.batch is not None:
        return False
    if spec.tier not in (gate.Tier.GREEN, gate.Tier.AMBER):
        return False
    if name not in gate._KNOWN_TOOLS or gate._looks_like_mutation(name):   # the gate's own rules, read not copied
        return False
    return not _screen_tool(name, spec)


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
