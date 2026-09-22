"""Append-only, redacted Judgment Ledger primitives.

The ledger stores validated OwnerDecision records only. It does not execute actions,
convert expiry into a decision, or grant deployment/adoption authority.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .judgment import JudgmentRecord, JudgmentValidationError, validate_judgment


class JudgmentLedgerError(ValueError):
    """An append would violate an immutable ledger invariant."""


@dataclass(frozen=True, slots=True)
class JudgmentLedger:
    records: tuple[JudgmentRecord, ...] = ()

    @classmethod
    def from_records(cls, records: Iterable[JudgmentRecord]) -> JudgmentLedger:
        ledger = cls()
        for record in records:
            ledger = ledger.append(record)
        return ledger

    def append(self, record: JudgmentRecord) -> JudgmentLedger:
        """Return a new ledger with one validated record appended, or fail closed."""
        # A JudgmentRecord validates itself at construction. This re-check is the
        # ledger's own line of defence against a record it did not see built.
        try:
            validate_judgment(record)
        except JudgmentValidationError as exc:
            raise JudgmentLedgerError(str(exc)) from exc

        by_id = {existing.judgment_id: existing for existing in self.records}
        if record.judgment_id in by_id:
            if by_id[record.judgment_id] == record:
                raise JudgmentLedgerError("duplicate judgment_id replay is not appendable")
            raise JudgmentLedgerError("judgment_id collision with divergent content")

        # One immutable owner judgment per proposal in V1. A later edit is
        # represented by a new proposal and a new judgment, never by mutation.
        # So a proposal_id that reappears with a different fingerprint is either
        # a proposal that was mutated after judgment or an approval being
        # replayed against new content, and both are refused.
        for existing in self.records:
            if existing.proposal_id != record.proposal_id:
                continue
            if existing.proposal_fingerprint == record.proposal_fingerprint:
                raise JudgmentLedgerError("proposal already has an owner judgment")
            raise JudgmentLedgerError(
                "proposal_id is already bound to a different proposal fingerprint"
            )

        return JudgmentLedger(records=(*self.records, record))
