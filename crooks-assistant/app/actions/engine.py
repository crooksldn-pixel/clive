"""Staging, authorisation and execution of proposals: the loop every future action uses.

    tool call → gate → stage (this) → card → tap → commit (this) → verify (this) → ledger

Two invariants live here and nowhere else:

  - A proposal executes at most once. The claim from PENDING to EXECUTING is synchronous —
    no await between the checks and the write of the status — so two commits that arrive
    together cannot both pass it. A second commit that lands while the first is executing or
    being proven waits for the first's outcome and returns it; a settled proposal is never
    re-opened, whoever asks and whatever they saw.
  - An ambiguous mutation is settled by looking, not guessing. If the request to Shopify
    fails after it was sent, the entity is re-read once: the fingerprint says whether the
    change landed, did not, or cannot be told — and the card says exactly that.
  - Nothing is sent that was not stored at staging time. `commit` takes a proposal id and a
    session id; the arguments come from the proposal.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import secrets
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app import readonly
from app.actions.grammar import ARMED_FOR_S, dwell_ms, gesture_for
from app.actions.ledger import ActionLedger, NullLedger
from app.actions.models import (
    PROPOSAL_TTL_S,
    UNDO_TTL_S,
    ActionProposal,
    ActionStatus,
    Observed,
    Prepared,
    args_fingerprint,
    new_proposal_id,
)
from app.clients.shopify import ShopifyPreconditionFailed
from app.session.models import Session
from app.tools.context import acting_branch
from app.tools.registry import ToolSpec

log = logging.getLogger("crooks.actions")

# A commit that finds the proposal already executing waits this long for the outcome.
WAIT_FOR_OUTCOME_S = 25.0
# A commit after an arming may arrive this much later than the armed window, for the
# tablet's own round trip and a slow hand.
ARM_SLACK_MS = 2500

# Codes the tablet turns into calm states. The set is closed; a new code is a new line here.
CODES = frozenset({
    "proposed", "verified", "unverified", "failed", "stale", "expired", "revoked",
    "already_executed", "in_progress", "unknown", "wrong_session", "service_unavailable", "not_armed",
    "batch_member",
})

# A settled proposal is kept in the index this long after it finished, so the tablet can
# still ask about it; then it goes, and its session's copy of the note text with it.
SETTLED_RETENTION_S = 900.0


@dataclass(slots=True)
class CommitResult:
    proposal: ActionProposal | None
    code: str
    spoken: str
    detail: str = ""

    @property
    def status(self) -> str:
        return self.proposal.status.value.lower() if self.proposal else "unknown"


class ActionEngine:
    def __init__(
        self,
        *,
        ledger: ActionLedger | None = None,
        ttl_s: float = PROPOSAL_TTL_S,
        clock=time.time,
    ) -> None:
        self.ledger = ledger or NullLedger()
        self.ttl_s = ttl_s
        self.clock = clock
        # proposal id → session, so a commit can find its proposal without a session lookup
        # that might resurrect an idle session. A session that has gone takes its proposals.
        self._index: dict[str, Session] = {}
        self.executions = 0   # every mutation this engine has sent

    # ------------------------------------------------------------- staging

    def stage(
        self, session: Session, spec: ToolSpec, model_args: dict[str, Any], prepared: Prepared, *, batch_id: str = "",
    ) -> tuple[ActionProposal, bool]:
        """Record a prepared change against the session's current epoch. Returns the proposal
        and whether it is new: the same request twice in one epoch is one proposal."""
        assert spec.write is not None
        now = self.clock()
        self.prune(now)
        fingerprint = args_fingerprint(spec.name, model_args)
        # The half that asked, read once: it stamps a new proposal below, and it decides whether
        # a waiting one is the same request. The same change asked for in BOTH halves of a
        # divided orb in one position used to come back to the second half as the first half's
        # proposal — its card drawn over there, stamped over here, withdrawn by the other
        # half's next question and never by its own (the 2026-09-28 deploy review, round 9,
        # D2-03). Each half's request is its own proposal, and each is held to its own
        # precondition at commit: once one has changed the entity, the other finds it moved.
        asking = acting_branch(session)
        for existing in session.proposals:
            if (
                existing.status is ActionStatus.PENDING
                and existing.proposal_id in self._index      # ours: never a proposal this engine cannot execute
                and existing.epoch == session.epoch
                and existing.fingerprint == fingerprint
                and str(getattr(existing, "branch_id", "") or "") == asking
                and not existing.expired(now)
            ):
                # The same proposal, not a second one: the ledger already has its line.
                return existing, False
        risk = spec.tier.value
        if spec.write.risk is not None:
            try:
                raised = spec.write.risk(prepared)
            except Exception as exc:  # noqa: BLE001 — a risk hook that fails escalates, never relaxes
                log.warning("risk hook for %s failed (%s); treating as RED", spec.name, exc)
                raised = "RED"
            if str(getattr(raised, "value", raised) or "").upper() == "RED":
                risk = "RED"   # only ever upward: a tool's own tier is its floor
        interaction = gesture_for(risk, spec.write.kind)
        proposal = ActionProposal(
            proposal_id=new_proposal_id(),
            session_id=session.session_id,
            epoch=session.epoch,
            # The half that ASKED, not the half in focus. They differ whenever the tablet
            # posts a branch_id for a half that is not on screen, and everything that reads
            # this field assumes the asking one: a spoken "yes" is matched against the
            # speaking branch, `revoke_pending` withdraws by branch, `/branches/{id}
            # /background` refuses a half with a change waiting, and a BACKGROUND half is
            # never allowed to commit. Stamped with the focused branch, all four inverted.
            branch_id=asking,
            tool_name=spec.name,
            operation=spec.write.operation,
            risk=risk,
            model_args=MappingProxyType(copy.deepcopy(model_args)),
            execution=MappingProxyType(copy.deepcopy(prepared.execution)),
            entity_kind=spec.write.entity_kind,
            entity_ref=prepared.entity_ref,
            entity_label=prepared.entity_label,
            interaction=interaction,
            reversible=spec.write.reversible,
            before=dict(prepared.before),
            expected_after=dict(prepared.expected_after),
            summary=dict(prepared.summary),
            fingerprint=fingerprint,
            created_at=now,
            expires_at=now + self.ttl_s,
            turn_id=str(getattr(session, "turn_id", "") or ""),
            batch_id=str(batch_id or ""),
        )
        session.stage(proposal)
        self._index[proposal.proposal_id] = session
        self.ledger.record("PROPOSED", proposal, payload_len=_payload_len(prepared), facts=_ledger_facts(prepared))
        return proposal, True

    def stage_undo(self, session: Session, spec: ToolSpec, done: ActionProposal) -> ActionProposal | None:
        """A server-generated proposal that puts the entity back exactly as it was. Bound to
        the same session and epoch, with its own expiry, executed by the same path."""
        write = spec.write
        if write is None or not write.reversible or write.undo is None:
            return None
        try:
            reverse = write.undo(dict(done.execution))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not build the undo for %s: %s", done.proposal_id, exc)
            return None
        now = self.clock()
        undo = ActionProposal(
            proposal_id=new_proposal_id(),
            session_id=session.session_id,
            # The half of the orb the change it reverses was asked for in: an undo belongs
            # exactly where its forward change did, and is held to the same branch rules.
            branch_id=str(getattr(done, "branch_id", "") or ""),
            # The epoch the owner authorised the change in. If they moved on while it was
            # being applied, the undo is already behind them and a tap on it is refused.
            epoch=done.epoch,
            tool_name=spec.name,
            operation=f"{write.operation}_undo",
            risk=done.risk,
            model_args=MappingProxyType({}),
            execution=MappingProxyType(copy.deepcopy(reverse)),
            entity_kind=done.entity_kind,
            entity_ref=done.entity_ref,
            entity_label=done.entity_label,
            # The undo is as grave as the change it reverses: the same tier, the same gesture.
            interaction=gesture_for(done.risk, write.kind),
            reversible=False,
            # It may only run while the entity still shows what this action wrote.
            before=dict(done.after or done.expected_after),
            expected_after=dict(done.before),
            summary={"undo": True},
            fingerprint=args_fingerprint(f"undo:{spec.name}", {"of": done.proposal_id}),
            created_at=now,
            # An offer has its own clock (UNDO_TTL_S), longer than a card waiting for a tap:
            # wanting something back takes longer to decide than doing it did. Nothing is
            # waiting on it, so nothing is hurried by it.
            expires_at=now + UNDO_TTL_S,
            undo_of=done.proposal_id,
            turn_id=done.turn_id,
            # The undo of a batch member is a batch member from birth: never committable on
            # its own, even before the batch engine gathers the undos into their own batch.
            batch_id=done.batch_id,
        )
        session.stage(undo)
        self._index[undo.proposal_id] = session
        done.undo_id = undo.proposal_id
        self.ledger.record("PROPOSED", undo)
        return undo

    # -------------------------------------------------------- invalidation

    def advance_epoch(self, session: Session, reason: str, *, branch_id: str = "") -> int:
        """A new instruction from the owner. Everything still waiting IN THE HALF HE SPOKE TO
        belongs to the last one and is revoked; a proposal never outlives the conversation
        position it was made in.

        Two exceptions, and both are about not taking away a card nobody replaced:

        * an undo belongs to the change that was just made, not to an instruction, and
          "okay" said to "Note added" must not withdraw it;
        * a change waiting in the OTHER half of a divided orb was asked for there, and a
          question asked over here is not a new instruction to it.

        Both are carried to the new position rather than left behind at the old one, because
        the position is the conversation's and the commit is checked against it.
        """
        session.epoch += 1
        self.revoke_pending(session, reason, branch_id=branch_id)
        for proposal in session.proposals:
            if proposal.status is ActionStatus.PENDING:
                proposal.epoch = session.epoch
        return session.epoch

    def revoke_pending(self, session: Session, reason: str, *, undos: bool = False, branch_id: str = "") -> list[str]:
        """Withdraw the proposals still waiting in this session (the undos only when asked:
        a new instruction keeps them, a reset or a cancel takes everything). Returns their
        ids, so the turn that withdrew them can tell the tablet which cards are dead.

        With `branch_id`, only that half's: a change belongs to the half of the orb it was
        asked for in, and a question asked in the other half withdraws nothing of it. Without
        it — a reset, a cancel, a session going — the whole conversation's.
        """
        revoked: list[str] = []
        running = _running_batches(session)
        for proposal in session.proposals:
            if proposal.status is ActionStatus.PENDING and (undos or proposal.undo_of is None):
                if proposal.batch_id and proposal.batch_id in running:
                    # A member of a batch the owner has already gestured for: the batch is
                    # applying it now, and a word spoken meanwhile withdraws nothing of it.
                    continue
                if branch_id and str(getattr(proposal, "branch_id", "") or "") not in ("", branch_id):
                    continue
                self._finish(proposal, ActionStatus.REVOKED, "revoked", reason=reason)
                revoked.append(proposal.proposal_id)
        return revoked

    def dismiss_undo(self, proposal_id: str) -> bool:
        """Let an undo OFFER go. Not a revocation of work — there is no work: the change it
        would reverse is finished and proven, and this only takes away the way back.

        The tablet calls it when the offer's own clock runs out on the glass, so that the
        Mac's copy stops being something the owner could still be waiting on. Anything that
        is not an undo is refused: a change waiting for a gesture is never dismissed by this
        door."""
        proposal = self.find(proposal_id)
        if proposal is None or proposal.undo_of is None or proposal.status is not ActionStatus.PENDING:
            return False
        self._finish(proposal, ActionStatus.EXPIRED, "expired", reason="the offer was let go")
        return True

    def revoke_ids(self, proposal_ids: list[str], reason: str) -> int:
        """Withdraw these proposals, if still waiting, whatever epoch they were staged in."""
        count = 0
        for pid in proposal_ids:
            proposal = self.find(pid)
            if proposal is not None and proposal.status is ActionStatus.PENDING:
                self._finish(proposal, ActionStatus.REVOKED, "revoked", reason=reason)
                count += 1
        return count

    def deliver(self, proposal_id: str) -> ActionProposal | None:
        """The card is on its way to the tablet. The wait for the tap starts now, not when
        the model asked: the answer and the spoken line came between, and the owner had no
        card to tap during them. Still the server's clock; still one TTL."""
        proposal = self.find(proposal_id)
        if proposal is None or proposal.status is not ActionStatus.PENDING or proposal.delivered_at is not None:
            return proposal   # once: a card shown again is not a card shown afresh
        now = self.clock()
        proposal.delivered_at = now
        proposal.expires_at = max(proposal.expires_at, now + self.ttl_s)
        self.ledger.record("DELIVERED", proposal)
        return proposal

    def forget_session(self, session_id: str) -> None:
        """The session is gone (reset, restart, idled out): nothing of it may stay tappable
        or in memory. Called by the session manager whenever it drops one."""
        for pid, session in list(self._index.items()):
            if session.session_id == session_id:
                for proposal in session.proposals:
                    if proposal.status is ActionStatus.PENDING:
                        self._finish(proposal, ActionStatus.REVOKED, "revoked", reason="session ended")
                del self._index[pid]

    def prune(self, now: float | None = None) -> int:
        """Drop settled proposals the tablet has had long enough to ask about, and any whose
        session no longer holds them. The index is the only thing keeping an old session —
        and the note text inside its proposals — alive."""
        now = self.clock() if now is None else now
        dropped = 0
        for pid, session in list(self._index.items()):
            proposal = session.proposal(pid)
            if proposal is None:
                del self._index[pid]
                dropped += 1
                continue
            if proposal.terminal and proposal.finished_at is not None and now - proposal.finished_at > SETTLED_RETENTION_S:
                del self._index[pid]
                # And out of the session, so the words the owner dictated go with it.
                session.proposals[:] = [p for p in session.proposals if p.proposal_id != pid]
                dropped += 1
        return dropped

    # ---------------------------------------------------------------- look up

    def find(self, proposal_id: str) -> ActionProposal | None:
        session = self._index.get(proposal_id)
        if session is None:
            return None
        proposal = session.proposal(proposal_id)
        if proposal is not None and proposal.status is ActionStatus.PENDING and proposal.expired(self.clock()):
            self._finish(proposal, ActionStatus.EXPIRED, "expired")
        return proposal

    def state(self, proposal_id: str, session_id: str) -> ActionProposal | None:
        proposal = self.find(proposal_id)
        if proposal is None or proposal.session_id != session_id:
            return None
        return proposal

    # ------------------------------------------------------------------- arming

    def arm(self, proposal_id: str, session_id: str) -> tuple[ActionProposal | None, str]:
        """The owner's hold began. For a change whose gesture is a hold, the Mac remembers when,
        and hands the tablet a single-use token; the commit that follows must carry it, and
        must come after the hold's dwell and before the arming lapses. So a hold is a fact on
        the Mac, and a stray request — an Android double-fire, a script — is not a gesture."""
        proposal = self.find(proposal_id)
        if proposal is None:
            return None, "unknown"
        if proposal.session_id != session_id:
            return None, "wrong_session"
        if proposal.batch_id:
            # A member of a batch is armed by the batch's own gesture, never on its own.
            return proposal, "batch_member"
        if proposal.status is not ActionStatus.PENDING:
            return proposal, proposal.code or proposal.status.value.lower()
        proposal.armed_at = self.clock()
        proposal.arm_nonce = secrets.token_urlsafe(12)
        self.ledger.record("ARMED", proposal)
        return proposal, ""

    # ----------------------------------------------------------------- commit

    async def commit(self, proposal_id: str, session_id: str, *, caller: str, spec_lookup, nonce: str = "", via_batch: str = "") -> CommitResult:
        """The owner tapped. Validate, claim atomically, check the entity has not moved, send
        the one reviewed mutation with the stored arguments, prove it, record it.

        A member of a batch is committed only by its batch (`via_batch` names it): the
        batch's gesture authorised it, so no arming of its own is looked for; and a commit
        that names the member directly is refused, whatever it carries."""
        if readonly.active():
            # A process latched read-only refuses here as well as at the client, so that the
            # card says why in the owner's words and the ledger records a refusal rather than
            # a failed send. Nothing is claimed and the proposal stays exactly as it was.
            return CommitResult(self.find(proposal_id), "read_only", "")
        proposal = self.find(proposal_id)
        if proposal is None:
            return CommitResult(None, "unknown", "")
        if proposal.session_id != session_id:
            return CommitResult(None, "wrong_session", "")
        if proposal.batch_id and via_batch != proposal.batch_id:
            return CommitResult(proposal, "batch_member", "")
        spec = spec_lookup(proposal.tool_name)
        write = spec.write if spec is not None else None
        if proposal.status is ActionStatus.PENDING and not via_batch and not self._armed(proposal, nonce):
            # A hold kind, without the hold: nothing is claimed, nothing settles. The card
            # stays live for the hold that was meant.
            return CommitResult(proposal, "not_armed", "")

        if proposal.status in (ActionStatus.EXECUTING, ActionStatus.EXECUTED):
            # Someone else's tap, a retried request, an Android double-fire — arriving while
            # the first commit is sending the change or proving it: wait for the outcome the
            # first commit produces and hand back that, never a second mutation.
            try:
                await asyncio.wait_for(proposal.done.wait(), timeout=WAIT_FOR_OUTCOME_S)
            except TimeoutError:
                return CommitResult(proposal, "in_progress", "")
            return self._terminal(proposal, write)
        if proposal.terminal:
            return self._terminal(proposal, write)

        session = self._index.get(proposal_id)
        # A batch member's position is the batch's: it was checked when the batch was
        # claimed, and a turn that arrives while the batch runs does not move it.
        if session is None or (not via_batch and proposal.epoch != session.epoch):
            self._finish(proposal, ActionStatus.REVOKED, "revoked", reason="the owner moved on")
            return self._terminal(proposal, write)
        if write is None or not write.complete:
            self._finish(proposal, ActionStatus.FAILED, "failed", reason="no write definition")
            return self._terminal(proposal, write)

        # --- the claim. Nothing may await between the checks above and this line. ---
        proposal.status = ActionStatus.EXECUTING
        proposal.caller = caller
        proposal.executed_at = None
        self.ledger.record("EXECUTING", proposal)

        started = time.perf_counter()
        sent = False   # True from the moment the mutation leaves; after that, nothing is assumed
        try:
            execution = dict(proposal.execution)
            # Precondition: the entity must still be what it was when the change was decided.
            # A write may name the keys that count (a courtesy read that can fail on its own
            # must not make a change it does not touch look changed).
            observed = await write.observe(execution)
            if not _same_state(observed.fingerprint, proposal.before, write.precondition_keys):
                self._finish(proposal, ActionStatus.STALE, "stale", reason="entity changed since staging")
                return CommitResult(proposal, "stale", _stale_words(proposal, write))

            self.executions += 1
            sent = True
            answer = await write.execute(execution)
            proposal.sent = _public_answer(answer)
            proposal.executed_at = self.clock()
            proposal.status = ActionStatus.EXECUTED
            self.ledger.record("EXECUTED", proposal, ms=round((time.perf_counter() - started) * 1000, 1), job=(proposal.sent or {}).get("job_id"))

            # Some changes finish later on Shopify's side: wait for that, bounded, first.
            if write.settle is not None:
                await write.settle(execution, proposal.sent or {})
            # Verification: a 200 is not proof; the re-read is.
            proven = await write.observe(execution)
            return await self._prove(proposal, proven, session, spec, write, courtesy=not via_batch)
        except (PreconditionFailed, ShopifyPreconditionFailed) as exc:
            # Shopify itself said the entity was not as expected (a compare-and-swap that
            # found another number, an order already cancelled). Nothing was applied: stale.
            self._finish(proposal, ActionStatus.STALE, "stale", reason=_short(exc))
            return CommitResult(proposal, "stale", _stale_words(proposal, write), detail=_short(exc))
        except asyncio.CancelledError as exc:
            # The task was cancelled (a shutdown, a client that went away) between sending the
            # change and proving it. It must not be left claimed for ever: look once, record
            # what was seen, then let the cancellation continue.
            if sent:
                await self._settle_by_observation(proposal, execution, session, spec, write, exc, courtesy=not via_batch)
            else:
                self._finish(proposal, ActionStatus.FAILED, "service_unavailable", reason="cancelled before sending")
            raise
        except Exception as exc:  # noqa: BLE001 — every failure is a recorded outcome
            if not sent:
                # Nothing left this process: the precondition read failed. Proven unchanged.
                log.warning("action %s could not check the entity: %s", proposal.proposal_id, exc)
                self._finish(proposal, ActionStatus.FAILED, "service_unavailable", reason=_short(exc))
                return CommitResult(proposal, "service_unavailable", _failure_words(proposal, write), detail=_short(exc))
            # The mutation left, or its answer did not come back, or the proving read failed.
            # Shopify may or may not hold the change. Look once; say what was seen.
            log.warning("action %s is ambiguous after sending: %s", proposal.proposal_id, exc)
            return await self._settle_by_observation(proposal, execution, session, spec, write, exc, courtesy=not via_batch)

    async def _prove(self, proposal, proven, session, spec, write, *, courtesy: bool = True) -> CommitResult:
        proposal.after = dict(proven.fingerprint)
        proposal.entity = proven.entity
        if write.verify is not None and proposal.undo_of is None:
            ok, note = write.verify(proposal.before, proven.fingerprint, dict(proposal.execution))
        else:
            ok, note = proven.fingerprint == proposal.expected_after, ""
        if ok:
            proposal.verified = True
            proposal.note = str(note or "")
            # The fuller read is for the card of a single change; a batch's card shows counts,
            # and fifty courtesy reads would cost Shopify more than the changes did.
            if write.entity is not None and courtesy:
                # The card shows the entity as it now is: a fuller read than the proof needed.
                try:
                    proposal.entity = await write.entity(dict(proposal.execution))
                except Exception as exc:  # noqa: BLE001 — proven is proven; the card is a courtesy
                    log.warning("could not re-read %s for the card: %s", proposal.proposal_id, _short(exc))
            self._finish(proposal, ActionStatus.VERIFIED, "verified", reason=proposal.note or "")
            spoken = (write.spoken_undo_success if proposal.undo_of else write.spoken_success)
            # The line names what it touched: "{label}" is the entity as a person says it, and
            # "{amount}" the money a change moved, as the tool summarised it.
            spoken = spoken.replace("{label}", str(proposal.entity_label).lstrip("#"))
            if "{amount}" in spoken:
                spoken = spoken.replace("{amount}", _spoken_amount(proposal.summary))
            if "{to}" in spoken:
                # The recipient, or the number a change ends on, as the tool summarised it; for
                # an undo, which has no summary of its own, the number its reverse ends on.
                spoken = spoken.replace("{to}", str(proposal.summary.get("spoken_to") or proposal.execution.get("to") or "them"))
            if proposal.note:
                spoken = f"{spoken} {proposal.note}"
            if proposal.undo_of is None:
                self.stage_undo(session, spec, proposal)
            return CommitResult(proposal, "verified", spoken)
        proposal.verified = False
        self._finish(proposal, ActionStatus.UNVERIFIED, "unverified", reason="re-read does not match")
        return CommitResult(proposal, "unverified", _failure_words(proposal, write))

    async def _settle_by_observation(self, proposal, execution, session, spec, write, exc, *, courtesy: bool = True) -> CommitResult:
        """One re-read decides an ambiguous mutation. Landed: verified, as if the answer had
        come back. Untouched: failed, and 'nothing was changed' is now a fact — except for a
        change Shopify finishes later (a cancel's job), where an unchanged re-read proves
        nothing yet: that one is waited for, bounded, and then unverified if still unchanged,
        never "nothing was changed". Neither, or the re-read fails too: unverified — the card
        says to check the order, never that nothing happened."""
        if write.settle is not None and proposal.status is ActionStatus.EXECUTING:
            # The send may have landed even though its answer did not: give Shopify the time
            # the change takes before looking.
            try:
                await write.settle(execution, proposal.sent or {})
            except Exception as waiting:  # noqa: BLE001
                log.warning("action %s: the wait after an ambiguous send failed: %s", proposal.proposal_id, _short(waiting))
        try:
            proven = await write.observe(execution)
        except Exception as again:  # noqa: BLE001
            proposal.verified = False
            self._finish(proposal, ActionStatus.UNVERIFIED, "unverified", reason=_short(again))
            return CommitResult(proposal, "unverified", _failure_words(proposal, write), detail=_short(exc))
        if proven.fingerprint == proposal.before and proposal.status is ActionStatus.EXECUTING:
            if getattr(exc, "refused", False):
                # The service answered and said no, and the re-read shows nothing moved: a
                # refusal, with the reason it gave — not "could not be reached", which is false.
                reason = _short(exc, 140)
                self._finish(proposal, ActionStatus.FAILED, "refused", reason=reason)
                service = "Gmail" if str(proposal.tool_name).startswith("gmail_") else "Shopify"
                return CommitResult(proposal, "refused", f"{service} refused that: {reason}. Nothing was changed.", detail=reason)
            if write.settle is not None:
                # Unchanged after the wait — but a job Shopify accepted may still be running.
                # Saying "nothing was changed" would be a guess about the future.
                proposal.verified = False
                self._finish(proposal, ActionStatus.UNVERIFIED, "unverified", reason=f"unchanged after an ambiguous send: {_short(exc)}")
                return CommitResult(proposal, "unverified", _failure_words(proposal, write), detail=_short(exc))
            self._finish(proposal, ActionStatus.FAILED, "service_unavailable", reason=_short(exc))
            return CommitResult(proposal, "service_unavailable", _failure_words(proposal, write), detail=_short(exc))
        if proposal.status is ActionStatus.EXECUTING:
            proposal.executed_at = self.clock()
            proposal.status = ActionStatus.EXECUTED
            self.ledger.record("EXECUTED", proposal, reason="settled by re-read")
        return await self._prove(proposal, proven, session, spec, write, courtesy=courtesy)

    # ---------------------------------------------------------------- helpers

    def _armed(self, proposal: ActionProposal, nonce: str) -> bool:
        """Whether a commit may proceed for this gesture: a tap or a swipe needs no arming; a
        hold needs the token the arming handed out, after the dwell, before the arming lapses."""
        required_ms = dwell_ms(proposal.interaction)
        if required_ms <= 0:
            return True
        if not nonce or not proposal.arm_nonce or proposal.armed_at is None:
            return False
        if not secrets.compare_digest(str(nonce), proposal.arm_nonce):
            return False
        held_ms = (self.clock() - proposal.armed_at) * 1000
        return required_ms <= held_ms <= (ARMED_FOR_S * 1000 + required_ms + ARM_SLACK_MS)

    def _terminal(self, proposal: ActionProposal, write) -> CommitResult:
        """What to say about a proposal that is already settled. Never a second mutation."""
        status = proposal.status
        if status in (ActionStatus.VERIFIED, ActionStatus.EXECUTED):
            return CommitResult(proposal, "already_executed", "")
        if status is ActionStatus.UNVERIFIED:
            # Sent, and not proven. Saying "already applied" would claim more than was seen.
            return CommitResult(proposal, "unverified", _failure_words(proposal, write) if write else "")
        if status is ActionStatus.STALE:
            return CommitResult(proposal, "stale", _stale_words(proposal, write) if write else "")
        if status is ActionStatus.EXPIRED:
            return CommitResult(proposal, "expired", "That action expired. Ask again.")
        if status is ActionStatus.REVOKED:
            return CommitResult(proposal, "revoked", "")
        return CommitResult(proposal, proposal.code or "failed", "")

    def _finish(self, proposal: ActionProposal, status: ActionStatus, code: str, *, reason: str = "") -> None:
        if proposal.terminal:
            # Settled is settled. A late caller cannot turn a verified change into anything else.
            log.warning("ignored %s → %s for settled proposal %s", proposal.status.value, status.value, proposal.proposal_id)
            return
        proposal.status = status
        proposal.code = code
        proposal.reason = reason
        proposal.finished_at = self.clock()
        self.ledger.record(status.value, proposal, reason=reason or None)
        proposal.done.set()
        if status in (ActionStatus.VERIFIED, ActionStatus.EXECUTED, ActionStatus.UNVERIFIED):
            _forget_what_changed(proposal)


def _forget_what_changed(proposal: ActionProposal) -> None:
    """A change landed (or may have): nothing the read caches hold about the thing it touched
    may be handed out as current again. Marking, not deleting — a card can still say what it
    was before — and never in the other direction: no write has ever read from that cache.
    See app/memory/store.py. Never raises; a cache that cannot be told is a slow next read,
    not a failed change."""
    try:
        from app.memory import invalidate_for_write

        invalidate_for_write(str(proposal.entity_kind or ""), str(proposal.entity_ref or ""))
    except Exception as exc:  # noqa: BLE001 — observability of a cache is not the change
        log.debug("could not invalidate the read caches: %s", exc)


def waiting_ids(session: Session, *, branch_id: str = "", now: float | None = None) -> list[str]:
    """The changes in this conversation that are still waiting for the owner.

    A change waiting is work he has not decided about. Two things are NOT that, and the live
    session counted both:

    * an UNDO — an offer against a change that is finished; "2 changes still waiting over
      there" at the merge was two undo offers for two completed changes;
    * a proposal whose time has run out. Expiry is the Mac's clock, and a proposal is marked
      EXPIRED only when something next looks at it, so a proposal nobody has asked about is
      still stamped PENDING long after it stopped being anything. One of the two the merge
      toast counted had been staged three minutes earlier, and the TTL is sixty seconds.

    With `branch_id`, only that half of the orb's.
    """
    moment = time.time() if now is None else now
    return [
        p.proposal_id for p in session.proposals
        if p.status is ActionStatus.PENDING and p.undo_of is None and not p.expired(moment)
        and (not branch_id or str(getattr(p, "branch_id", "") or "") == branch_id)
    ]


def undoable_ids(session: Session, *, branch_id: str = "", now: float | None = None) -> list[str]:
    """The undo offers still standing: changes that are DONE and can still be put back. Named
    separately from what is waiting, everywhere, because they are not the same thing."""
    moment = time.time() if now is None else now
    return [
        p.proposal_id for p in session.proposals
        if p.status is ActionStatus.PENDING and p.undo_of is not None and not p.expired(moment)
        and (not branch_id or str(getattr(p, "branch_id", "") or "") == branch_id)
    ]


class PreconditionFailed(RuntimeError):
    """Shopify refused the change because the entity was not as the proposal expected — a
    compare-and-swap that found a different quantity, an order that is already cancelled.
    Nothing was applied. Raised by a write's execute; the engine settles it as STALE."""


def _running_batches(session: Session) -> set[str]:
    """The batches of this session that the owner has gestured for and that are applying
    their members now (app/actions/batch.py)."""
    batches = getattr(session, "batches", None)
    if not isinstance(batches, dict):
        return set()
    return {bid for bid, b in batches.items() if str(getattr(getattr(b, "status", None), "value", "")) == "EXECUTING"}


def _stale_words(proposal: ActionProposal, write) -> str:
    """The tool's own stale line — or, for an undo, words about the undo: "nothing was saved"
    said of a draft delete would be false."""
    if proposal.undo_of:
        return "That can't be undone now: it changed since. Nothing was touched."
    return write.spoken_stale


def _failure_words(proposal: ActionProposal, write) -> str:
    if proposal.undo_of:
        return "I couldn't confirm the undo. Check before asking again."
    return write.spoken_failure


def _same_state(observed: dict[str, Any], before: dict[str, Any], keys: tuple[str, ...] | None) -> bool:
    if not keys:
        return observed == before
    return all(observed.get(k) == before.get(k) for k in keys)


def _public_answer(answer: Any) -> dict[str, Any] | None:
    """What a mutation's answer leaves on the proposal: ids and flags, never content."""
    if not isinstance(answer, dict):
        return None
    out: dict[str, Any] = {}
    for key, value in answer.items():
        if isinstance(value, (str, int, float, bool)) and (key.endswith("_id") or key in ("done", "status")):
            out[key] = value
    return out or None


def _spoken_amount(summary: dict[str, Any]) -> str:
    """"£20.00" from the tool's summary, for the speakable layer to turn into words."""
    try:
        amount = float(summary.get("amount"))
    except (TypeError, ValueError):
        return "the amount"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(str(summary.get("currency") or "GBP").upper(), "")
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {summary.get('currency')}"


def _ledger_facts(prepared: Prepared) -> dict[str, Any] | None:
    """The amounts and flags a change turns on — a refund amount, a restock count — which the
    tool put under summary["ledger"]. Numbers and short words only; never a name, never text."""
    facts = prepared.summary.get("ledger")
    if not isinstance(facts, dict):
        return None
    return {str(k)[:24]: v for k, v in facts.items() if isinstance(v, (int, float, bool)) or (isinstance(v, str) and len(v) <= 24)} or None


def _payload_len(prepared: Prepared) -> int | None:
    value = prepared.summary.get("payload_len")
    return int(value) if isinstance(value, int) else None


def _short(exc: BaseException, limit: int = 120) -> str:
    return f"{type(exc).__name__}: {str(exc)[:limit]}"


# ------------------------------------------------------------ the process's engine
#
# One engine per process, installed by the runtime. The dispatcher reaches it here rather
# than through the runtime so that a tool call and a tap land in the same index.

_engine: ActionEngine | None = None


def install(engine: ActionEngine) -> ActionEngine:
    global _engine
    _engine = engine
    return engine


def current() -> ActionEngine:
    global _engine
    if _engine is None:
        _engine = ActionEngine()
    return _engine


__all__ = [
    "ActionEngine", "CommitResult", "CODES", "Observed", "Prepared", "PreconditionFailed",
    "current", "install", "undoable_ids", "waiting_ids",
]
