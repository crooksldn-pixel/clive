"""Append-only, redacted Judgment Ledger primitives.

The ledger stores validated OwnerDecision records only. It does not execute actions,
convert expiry into a decision, or grant deployment/adoption authority.

Two kinds of second entry about one proposal are told apart on purpose:

- an EDIT is a new *proposal*: the record carries ``superseding_proposal_id``, and
  the judgment on the replacement is a first judgment about a different
  ``proposal_id``;
- a CORRECTION is a new *judgment* about the same proposal, referencing the entry it
  corrects through ``corrects_judgment_id``. It judges exactly what the corrected
  entry judged: the same proposal, fingerprint, action and task, at the same task
  revision and attempt (each present or absent exactly as there), so a correction
  can never move an owner's judgment to another revision or attempt. The corrected
  entry stays in the ledger byte for byte; it simply stops being the effective
  judgment for that proposal.

Anything else that looks like a second judgment on one proposal is refused, so at
every point there is exactly one effective judgment per judged proposal.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .judgment import JudgmentRecord, JudgmentValidationError, validate_judgment


class JudgmentLedgerError(ValueError):
    """An append would violate an immutable ledger invariant."""


# The fields a correction must differ in, on at least one of them. A correction
# that repeats the judgment it corrects is a replay wearing a new id.
_JUDGMENT_CONTENT_FIELDS = (
    "decision",
    "reason_code",
    "superseding_proposal_id",
    "replacement_fingerprint",
    "redacted_explanation",
)


@dataclass(frozen=True, slots=True)
class JudgmentLedger:
    records: tuple[JudgmentRecord, ...] = ()

    @classmethod
    def from_records(cls, records: Iterable[JudgmentRecord]) -> JudgmentLedger:
        ledger = cls()
        for record in records:
            ledger = ledger.append(record)
        return ledger

    # ------------------------------------------------------------------ queries

    def by_id(self, judgment_id: str) -> JudgmentRecord | None:
        for existing in self.records:
            if existing.judgment_id == judgment_id:
                return existing
        return None

    def correction_of(self, judgment_id: str) -> JudgmentRecord | None:
        """The entry that corrects ``judgment_id``, if one has been appended."""
        for existing in self.records:
            if existing.corrects_judgment_id == judgment_id:
                return existing
        return None

    def effective_judgments(self) -> tuple[JudgmentRecord, ...]:
        """Every entry that no later entry corrects: one per judged proposal."""
        corrected = {r.corrects_judgment_id for r in self.records if r.corrects_judgment_id}
        return tuple(r for r in self.records if r.judgment_id not in corrected)

    def effective_judgment_for(self, proposal_id: str) -> JudgmentRecord | None:
        for record in self.effective_judgments():
            if record.proposal_id == proposal_id:
                return record
        return None

    # ------------------------------------------------------------------- append

    def append(self, record: JudgmentRecord) -> JudgmentLedger:
        """Return a new ledger with one validated record appended, or fail closed."""
        # A JudgmentRecord validates itself at construction. This re-check is the
        # ledger's own line of defence against a record it did not see built.
        try:
            validate_judgment(record)
        except JudgmentValidationError as exc:
            raise JudgmentLedgerError(str(exc)) from exc

        same_id = self.by_id(record.judgment_id)
        if same_id is not None:
            if same_id == record:
                raise JudgmentLedgerError("duplicate judgment_id replay is not appendable")
            raise JudgmentLedgerError("judgment_id collision with divergent content")

        if record.corrects_judgment_id is not None:
            self._check_correction(record)

        # One effective owner judgment per proposal. A later edit is represented
        # by a new proposal and a new judgment, never by mutation. So a
        # proposal_id that reappears with a different fingerprint is either a
        # proposal mutated after judgment or an approval replayed against new
        # content, and both are refused; a same-fingerprint reappearance is
        # admissible only as a correction of the current judgment, which
        # _check_correction has already established.
        for existing in self.records:
            if existing.proposal_id != record.proposal_id:
                continue
            if existing.proposal_fingerprint != record.proposal_fingerprint:
                raise JudgmentLedgerError(
                    "proposal_id is already bound to a different proposal fingerprint"
                )
            if record.corrects_judgment_id is None:
                raise JudgmentLedgerError("proposal already has an owner judgment")

        return JudgmentLedger(records=(*self.records, record))

    def _check_correction(self, record: JudgmentRecord) -> None:
        """A correction points at exactly one existing, current judgment of the same
        proposal at the same task revision and attempt."""
        target = self.by_id(record.corrects_judgment_id or "")
        if target is None:
            raise JudgmentLedgerError(
                "correction references a judgment this ledger does not hold"
            )
        if (
            target.proposal_id != record.proposal_id
            or target.proposal_fingerprint != record.proposal_fingerprint
            or target.action_id != record.action_id
            or target.task_id != record.task_id
        ):
            raise JudgmentLedgerError(
                "a correction must judge the same proposal, action and task as the "
                "judgment it corrects"
            )
        # J-02: task_revision and attempt_id are part of what was judged. A
        # correction that changes, adds or drops either would move the owner's
        # judgment to a different revision or attempt under the same proposal id,
        # so both must match the corrected entry exactly, None included.
        if target.task_revision != record.task_revision or target.attempt_id != record.attempt_id:
            raise JudgmentLedgerError(
                "a correction must judge the same task revision and attempt as the "
                f"judgment it corrects (corrected entry: revision {target.task_revision!r}, "
                f"attempt {target.attempt_id!r}; correction: revision "
                f"{record.task_revision!r}, attempt {record.attempt_id!r})"
            )
        already = self.correction_of(target.judgment_id)
        if already is not None:
            raise JudgmentLedgerError(
                f"judgment {target.judgment_id} is already corrected by "
                f"{already.judgment_id}; correct the current judgment instead"
            )
        if record.decided_at < target.decided_at:
            raise JudgmentLedgerError("a correction cannot predate the judgment it corrects")
        if all(getattr(record, f) == getattr(target, f) for f in _JUDGMENT_CONTENT_FIELDS):
            raise JudgmentLedgerError(
                "a correction must change the judgment; this one changes nothing"
            )
