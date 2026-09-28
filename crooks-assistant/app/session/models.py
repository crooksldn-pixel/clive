"""Session state: what the assistant is currently talking about, and what it is allowed to
look up. The issued-id ledger is a security control, not a convenience — see app/tools/gate.py.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.actions.models import ActionProposal

# Proposals kept per session: two full batches (app/actions/batch.py MAX_BATCH) with their
# undos, and the single cards around them.
MAX_PROPOSALS = 240


@dataclass(slots=True)
class Refusal:
    """A tool call the gate denied. Recorded so the log shows what was attempted. Never
    executable: a refusal has no proposal, no arguments to run and no path to Shopify."""

    refusal_id: str
    tool_name: str
    args: dict[str, Any]
    reason: str
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class Session:
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)

    # Ids handed to the assistant by a search result this session. Detail-style tools accept
    # nothing else, so the assistant cannot look up a record it was never shown.
    issued_ids: set[str] = field(default_factory=set)

    # Whose conversation this is: the Tailscale login that started it, or "local" for one
    # started on the Mac itself. A session id is a bearer the tablet made up; this is what
    # stops another login on the tailnet using it. Empty only for a session made outside a
    # request (tests), which binds to the first caller.
    login: str = ""

    # What "that order" / "that customer" currently refers to, for conversational follow-ups.
    focus: dict[str, str] = field(default_factory=dict)

    turns: int = 0
    # The conversation's position. Advanced by every new instruction from the owner; a
    # proposal is bound to the epoch it was staged in and dies when the epoch moves on.
    epoch: int = 0
    # Changes the assistant proposed this session, waiting for or settled by the owner.
    proposals: list[ActionProposal] = field(default_factory=list)
    # Calls the gate denied. Kept apart from proposals: a refusal can never be authorised.
    refusals: list[Refusal] = field(default_factory=list)

    # Personal strings tool results exposed this session (customer names, sender addresses).
    # The turn log scrubs these from the free-text answer and question before writing, so a
    # name Claude reads aloud never lands on disk.
    pii_seen: set[str] = field(default_factory=set)

    # What the assistant is doing right now, driven by the tool actually executing — never
    # guessed from the question. The tablet polls this during a turn (M11).
    state: str = "READY"
    state_detail: str = ""
    # The question as transcribed, for the tablet to show while the answer is being worked out.
    heard: str = ""
    # Set by /cancel while a turn is in flight: the owner has moved on. The turn still ends,
    # but its answer is not synthesised for a tablet that will never ask for it.
    abandoned: bool = False
    # Why a tap from the tablet asking this turn would be refused, if it would: set by /turn
    # before the model runs, so a change proposed while changes are off is never announced as
    # something to tap. Empty when a tap would work.
    writes_blocked: str = ""

    # An order's full read started beside the model by /turn (app/routes/turn.py); collected
    # by the same turn when it lands in time, dropped otherwise. Never awaited by a turn.
    hydrating: Any = None
    # The turn being answered (turn_…), for the test-session timeline: every tool call and
    # every proposal made while it runs is written against it. Empty between turns.
    turn_id: str = ""
    # The turn's reading plan (app/analytics/plan.py): how many queries it has run, at what
    # cost, and their answers, so the same query is not run twice. A view of `read_budgets`
    # below; set to None to clear the budgets, which is what the benches do between rows.
    plan: Any = None
    # This conversation's read budgets, one per lane (app/reads/budget.py). Five bounds
    # rather than one, because a guess must not be able to spend the owner's and a tap must
    # not inherit a turn's — which is D-4.
    read_budgets: Any = None
    # The working sets this conversation holds (app/analytics/sets.py): what "these" means.
    sets: dict[str, Any] = field(default_factory=dict)
    # Bulk changes proposed this session (app/actions/batch.py), by batch id. Their
    # children are ordinary proposals in `proposals`.
    batches: dict[str, Any] = field(default_factory=dict)
    # What the Mac said about the last gesture's outcome ("Tagged 20 of the 21 orders…"),
    # told to the model once at the next question and then cleared: "did that work?" is
    # answered from the count, never guessed.
    last_outcome: str = ""
    # The last read-layer query, as the Mac ran it, so "just this week" and "by size" keep
    # its shape rather than starting over.
    last_query: dict[str, Any] | None = None
    # Whether this turn's question was answered with a capability hint on the prompt, so a
    # refusal after it is filed apart from an unaided one.
    hinted: bool = False

    # The entities this conversation has touched — an order, a customer, an email thread, a
    # product — most recent first. Presentation state for the tablet's context stack and
    # nothing else: no permission decision reads it (that is issued_ids, above).
    context: list[dict[str, str]] = field(default_factory=list)

    # The branches of this conversation (app/session/branch.py), by id, and which of them the
    # owner is talking to. One to begin with; two at most, when the orb is pulled apart.
    # Branch state is position and presentation — never permission: the gate reads
    # `issued_ids`, above, which every branch shares because they are one conversation.
    branches: dict[str, Any] = field(default_factory=dict)
    focused_branch: str = ""
    # Which half THIS turn is addressed to, which is not always the focused one: the tablet
    # posts a branch_id, and a question asked of the half that was put aside must not be
    # filed against the half on screen. Set once per turn beside `turn_id`, and read by the
    # layers that only ever receive a session — the action engine, and working sets. Without
    # it a change proposed by one half was stamped with the other, and a "yes" spoken to the
    # wrong half applied it. It is ONE field for both halves, so it holds whichever half spoke
    # last: the authority for a proposal is the request's own half, held on its task
    # (`app/tools/context.py` CURRENT_BRANCH, set by /turn, /command and the provider around
    # each tool call), and this is only the fallback for code that runs with no request.
    acting_branch: str = ""
    # When "who needs replying to" was last answered in this conversation, on the Mac's clock.
    # The same question again within a few minutes gets the short form ("Still just Mia.")
    # rather than the scope sentence read out a second time. Presentation state only.
    last_needs_reply_at: float = 0.0

    def set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.state_detail = detail
        self.touch()

    def touch(self) -> None:
        self.last_seen_at = time.time()

    def idle_s(self) -> float:
        return time.time() - self.last_seen_at

    def remember_pii(self, *values: str) -> None:
        for value in values:
            value = (value or "").strip()
            if len(value) >= 3:
                self.pii_seen.add(value)

    def issue(self, *ids: str) -> None:
        for value in ids:
            if value:
                self.issued_ids.add(str(value))

    def refuse(self, tool_name: str, args: dict[str, Any], reason: str) -> Refusal:
        refusal = Refusal(
            refusal_id=f"ref_{uuid.uuid4().hex[:12]}",
            tool_name=tool_name,
            args=dict(args or {}),
            reason=reason,
        )
        self.refusals.append(refusal)
        del self.refusals[:-50]
        return refusal

    def stage(self, proposal: ActionProposal) -> ActionProposal:
        """Hold a staged proposal. Only the action engine builds one (app/actions/engine.py);
        the session is where it lives so that it goes when the session goes."""
        self.proposals.append(proposal)
        # Room for a batch's children and their undos beside the cards that came before.
        del self.proposals[:-MAX_PROPOSALS]
        return proposal

    def proposal(self, proposal_id: str) -> ActionProposal | None:
        for candidate in self.proposals:
            if candidate.proposal_id == proposal_id:
                return candidate
        return None

    def remember_context(self, kind: str, label: str, ref: str, *, limit: int = 6) -> None:
        """Bring an entity to the front of the context stack (or add it), keeping the stack
        short: six entries is already more than a screen can usefully show."""
        if not (kind and label and ref):
            return
        ref = str(ref)
        self.context = [c for c in self.context if not (c["kind"] == kind and c["ref"] == ref)]
        self.context.insert(0, {"kind": kind, "label": str(label)[:80], "ref": ref})
        del self.context[limit:]

    def set_focus(self, kind: str, value: str) -> None:
        if value:
            self.focus[kind] = str(value)

    # ------------------------------------------------------------------ branches

    def branch(self, branch_id: str = "") -> Any:
        """A branch of this conversation. With no id, the focused one, made if this is the
        first question. An id that is not this conversation's gets the focused branch: a
        branch id is a position, and a stale one must not create a second empty history."""
        from app.session.branch import Branch, new_branch_id

        if branch_id and branch_id in self.branches:
            return self.branches[branch_id]
        if self.focused_branch and self.focused_branch in self.branches:
            return self.branches[self.focused_branch]
        created = Branch(branch_id=new_branch_id(), session_id=self.session_id, label="main")
        self.branches[created.branch_id] = created
        self.focused_branch = created.branch_id
        return created

    def branch_ids(self) -> list[str]:
        return [b.branch_id for b in self.branches.values() if b.status in ("ACTIVE", "BACKGROUND")]

    def focus_branch(self, branch_id: str) -> Any:
        """Move the owner's attention. The branch left behind keeps everything it had."""
        if branch_id in self.branches:
            self.focused_branch = branch_id
        return self.branch()
