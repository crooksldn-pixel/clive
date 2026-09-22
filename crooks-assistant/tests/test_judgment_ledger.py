"""The append-only ledger: what it refuses, and that it never rewrites."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.actions.judgment import (
    JudgmentRecord,
    OwnerDecision,
    OwnerProvenance,
    ReasonCode,
    proposal_fingerprint,
)
from app.actions.judgment_ledger import JudgmentLedger, JudgmentLedgerError

DECIDED_AT = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)
FP_ONE = proposal_fingerprint(b"proposal one")
FP_TWO = proposal_fingerprint(b"proposal two")


def judgment(**overrides) -> JudgmentRecord:
    values = dict(
        judgment_id="judgment-1",
        task_id="task-1",
        action_id="action-1",
        proposal_id="proposal-1",
        proposal_fingerprint=FP_ONE,
        decision=OwnerDecision.APPROVED,
        reason_code=ReasonCode.ACCEPTED_AS_PROPOSED,
        provenance=OwnerProvenance(principal_id="owner", session_id="session-1"),
        decided_at=DECIDED_AT,
    )
    values.update(overrides)
    return JudgmentRecord(**values)


def test_append_returns_a_new_ledger_and_leaves_the_old_one_alone() -> None:
    empty = JudgmentLedger()
    one = empty.append(judgment())
    assert empty.records == ()
    assert [entry.judgment_id for entry in one.records] == ["judgment-1"]


def test_identical_replay_of_a_judgment_is_refused() -> None:
    ledger = JudgmentLedger().append(judgment())
    with pytest.raises(JudgmentLedgerError, match="replay"):
        ledger.append(judgment())


def test_same_judgment_id_with_divergent_content_is_refused() -> None:
    ledger = JudgmentLedger().append(judgment())
    with pytest.raises(JudgmentLedgerError, match="collision"):
        ledger.append(judgment(decision=OwnerDecision.DECLINED, reason_code=ReasonCode.NOT_NOW))


def test_a_proposal_gets_exactly_one_owner_judgment() -> None:
    ledger = JudgmentLedger().append(judgment())
    with pytest.raises(JudgmentLedgerError, match="already has"):
        ledger.append(
            judgment(
                judgment_id="judgment-2",
                decision=OwnerDecision.DECLINED,
                reason_code=ReasonCode.NOT_NOW,
            )
        )


def test_a_proposal_id_cannot_be_rebound_to_different_content() -> None:
    """An approval replayed against a different fingerprint is the attack the contract names."""

    ledger = JudgmentLedger().append(judgment())
    with pytest.raises(JudgmentLedgerError, match="different proposal fingerprint"):
        ledger.append(judgment(judgment_id="judgment-2", proposal_fingerprint=FP_TWO))


def test_an_edit_and_the_judgment_on_its_replacement_are_two_entries() -> None:
    edited = judgment(
        decision=OwnerDecision.EDITED,
        reason_code=ReasonCode.NEEDS_CHANGES,
        superseding_proposal_id="proposal-2",
        replacement_fingerprint=FP_TWO,
    )
    approved_replacement = judgment(
        judgment_id="judgment-2", proposal_id="proposal-2", proposal_fingerprint=FP_TWO
    )
    ledger = JudgmentLedger.from_records([edited, approved_replacement])
    assert [entry.proposal_id for entry in ledger.records] == ["proposal-1", "proposal-2"]
    # Approving the replacement did not reach back and touch the original judgment.
    assert ledger.records[0].decision is OwnerDecision.EDITED


def test_the_ledger_itself_is_immutable() -> None:
    ledger = JudgmentLedger().append(judgment())
    with pytest.raises((AttributeError, TypeError)):
        ledger.records = ()  # type: ignore[misc]
