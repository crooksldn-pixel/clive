from dataclasses import replace

import pytest

from app.actions.judgment import JudgmentRecord, OwnerDecision, OwnerProvenance, proposal_fingerprint
from app.actions.judgment_chain import JudgmentChainAnchor, chain_anchor, chain_ledger, verify_chain
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
    assert verify_chain(entries, expected_anchor=chain_anchor(entries)) == ledger
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


def test_tail_truncation_requires_and_fails_against_external_anchor():
    entries = chain_ledger(JudgmentLedger.from_records([_record(1), _record(2), _record(3)]))
    anchor = chain_anchor(entries)
    # A valid prefix is internally well-formed, so predecessor hashing alone cannot
    # prove that history was truncated.
    assert len(verify_chain(entries[:-1]).records) == 2
    with pytest.raises(JudgmentLedgerError, match="entry count does not match anchor"):
        verify_chain(entries[:-1], expected_anchor=anchor)


def test_anchor_head_mismatch_fails_closed():
    entries = chain_ledger(JudgmentLedger.from_records([_record(1)]))
    forged = JudgmentChainAnchor(entry_count=1, head_hash="f" * 64)
    with pytest.raises(JudgmentLedgerError, match="head does not match anchor"):
        verify_chain(entries, expected_anchor=forged)


def test_malformed_anchor_fails_closed():
    entries = chain_ledger(JudgmentLedger.from_records([_record(1)]))
    with pytest.raises(JudgmentLedgerError, match="non-negative"):
        verify_chain(entries, expected_anchor=JudgmentChainAnchor(entry_count=-1, head_hash="0" * 64))
    with pytest.raises(JudgmentLedgerError, match="full SHA-256"):
        verify_chain(entries, expected_anchor=JudgmentChainAnchor(entry_count=1, head_hash="abc"))
