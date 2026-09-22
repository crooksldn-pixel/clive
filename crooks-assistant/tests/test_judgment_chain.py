from dataclasses import replace

import pytest

from app.actions.judgment import JudgmentRecord, OwnerDecision, OwnerProvenance, proposal_fingerprint
from app.actions.judgment_chain import chain_ledger, verify_chain
from app.actions.judgment_ledger import JudgmentLedger, JudgmentLedgerError


def _record(n: int) -> JudgmentRecord:
    return JudgmentRecord(
        judgment_id=f"j-{n}", task_id="task-1", action_id=f"action-{n}",
        proposal_id=f"proposal-{n}", proposal_fingerprint=proposal_fingerprint({"n": n}),
        decision=OwnerDecision.APPROVED, reason_code="ACCEPT_AS_PROPOSED",
        provenance=OwnerProvenance(principal_id="owner-1", source="owner-ui"),
        decided_at=f"2026-09-22T20:4{n}:00Z",
    )


def test_chain_round_trip_is_deterministic():
    ledger = JudgmentLedger.from_records([_record(1), _record(2)])
    entries = chain_ledger(ledger)
    assert entries == chain_ledger(ledger)
    assert verify_chain(entries) == ledger
    assert entries[1].previous_hash == entries[0].entry_hash


def test_mutated_record_fails_closed():
    entries = list(chain_ledger(JudgmentLedger.from_records([_record(1), _record(2)])))
    entries[0] = replace(entries[0], record=replace(entries[0].record, reason_code="OTHER_BOUNDED"))
    with pytest.raises(JudgmentLedgerError, match="entry hash mismatch"):
        verify_chain(tuple(entries))


def test_reordered_entries_fail_closed():
    entries = chain_ledger(JudgmentLedger.from_records([_record(1), _record(2)]))
    with pytest.raises(JudgmentLedgerError, match="predecessor mismatch"):
        verify_chain(tuple(reversed(entries)))


def test_removed_middle_entry_fails_closed():
    entries = chain_ledger(JudgmentLedger.from_records([_record(1), _record(2), _record(3)]))
    with pytest.raises(JudgmentLedgerError, match="predecessor mismatch"):
        verify_chain((entries[0], entries[2]))


def test_forged_entry_hash_fails_closed():
    entries = list(chain_ledger(JudgmentLedger.from_records([_record(1)])))
    entries[0] = replace(entries[0], entry_hash="f" * 64)
    with pytest.raises(JudgmentLedgerError, match="entry hash mismatch"):
        verify_chain(tuple(entries))
