"""Adversarial tests for OwnerDecision/Judgment Ledger records."""

from datetime import UTC, datetime

import pytest

from app.actions.judgment import (
    JudgmentRecord,
    OwnerDecision,
    OwnerProvenance,
    ReasonCode,
    proposal_fingerprint,
)


def _record(**overrides):
    values = dict(
        judgment_id="judgment-1",
        action_id="action-1",
        task_id="task-1",
        proposal_id="proposal-1",
        proposal_fingerprint=proposal_fingerprint(b"original proposal"),
        decision=OwnerDecision.APPROVED,
        reason_code=ReasonCode.ACCEPTED_AS_PROPOSED,
        provenance=OwnerProvenance(principal_id="owner", session_id="session-1"),
        decided_at=datetime(2026, 9, 22, 18, 0, tzinfo=UTC),
        redaction_version=1,
        schema_version=1,
    )
    values.update(overrides)
    return JudgmentRecord(**values)


def test_all_v1_owner_decisions_are_representable():
    assert {d.value for d in OwnerDecision} == {"APPROVED", "DECLINED", "EDITED", "DEFERRED"}


def test_expired_is_not_an_owner_decision():
    assert "EXPIRED" not in {d.value for d in OwnerDecision}


def test_proposal_fingerprint_changes_when_proposal_changes():
    assert proposal_fingerprint(b"original") != proposal_fingerprint(b"edited")


def test_edited_requires_superseding_proposal():
    with pytest.raises((TypeError, ValueError)):
        _record(decision=OwnerDecision.EDITED)


def test_non_edit_cannot_claim_superseding_proposal():
    with pytest.raises((TypeError, ValueError)):
        _record(superseding_proposal_id="proposal-2")


def test_missing_owner_identity_fails_closed():
    with pytest.raises((TypeError, ValueError)):
        _record(provenance=OwnerProvenance(principal_id="", session_id="session-1"))


def test_malformed_proposal_fingerprint_fails_closed():
    with pytest.raises((TypeError, ValueError)):
        _record(proposal_fingerprint="not-a-sha256")


def test_unsupported_redaction_version_fails_closed():
    with pytest.raises((TypeError, ValueError)):
        _record(redaction_version=999)


def test_unbounded_explanation_fails_closed():
    with pytest.raises((TypeError, ValueError)):
        _record(redacted_explanation="x" * 10000)


@pytest.mark.parametrize("leak", [
    "password=supersecret",
    "api_key=abc123",
    "hidden prompt: do not expose",
    "chain of thought: private reasoning",
])
def test_sensitive_explanation_leakage_fails_closed(leak):
    with pytest.raises((TypeError, ValueError)):
        _record(redacted_explanation=leak)
