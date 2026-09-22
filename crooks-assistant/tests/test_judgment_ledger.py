"""Regression tests for the append-only Judgment Ledger invariants."""

import pytest

from app.actions.judgment import (
    JudgmentRecord,
    OwnerDecision,
    OwnerProvenance,
    ReasonCode,
    proposal_fingerprint,
)
from app.actions.judgment_ledger import JudgmentLedger


def _record(*, judgment_id="j-1", proposal="proposal-a", decision=OwnerDecision.APPROVED, superseding=None):
    return JudgmentRecord(
        judgment_id=judgment_id,
        proposal_id=proposal,
        proposal_fingerprint=proposal_fingerprint(proposal.encode()),
        decision=decision,
        reason_code=ReasonCode.OWNER_CONFIRMED,
        explanation=None,
        redacted_delta=None,
        superseding_proposal_fingerprint=superseding,
        provenance=OwnerProvenance(owner_id="owner", session_id="session", source="owner-ui"),
        redaction_version=1,
        schema_version=1,
    )


def test_append_returns_new_ledger_without_mutating_prior_state():
    ledger = JudgmentLedger()
    updated = ledger.append(_record())
    assert len(ledger.records) == 0
    assert len(updated.records) == 1


def test_exact_judgment_id_replay_is_rejected():
    ledger = JudgmentLedger().append(_record())
    with pytest.raises(ValueError):
        ledger.append(_record())


def test_divergent_judgment_id_reuse_is_rejected():
    ledger = JudgmentLedger().append(_record())
    with pytest.raises(ValueError):
        ledger.append(_record(judgment_id="j-1", proposal="proposal-b"))


def test_second_judgment_for_same_proposal_fingerprint_is_rejected():
    ledger = JudgmentLedger().append(_record(judgment_id="j-1"))
    with pytest.raises(ValueError):
        ledger.append(_record(judgment_id="j-2"))


def test_distinct_proposals_can_be_appended():
    ledger = JudgmentLedger().append(_record(judgment_id="j-1", proposal="proposal-a"))
    updated = ledger.append(_record(judgment_id="j-2", proposal="proposal-b"))
    assert len(updated.records) == 2


def test_edited_judgment_requires_distinct_superseding_fingerprint():
    original = proposal_fingerprint(b"proposal-a")
    replacement = proposal_fingerprint(b"proposal-b")
    ledger = JudgmentLedger()
    updated = ledger.append(
        _record(
            judgment_id="j-edit",
            proposal="proposal-a",
            decision=OwnerDecision.EDITED,
            superseding=replacement,
        )
    )
    assert updated.records[0].proposal_fingerprint == original
    assert updated.records[0].superseding_proposal_fingerprint == replacement
