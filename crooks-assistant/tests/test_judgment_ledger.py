"""The append-only ledger: what it refuses, and that it never rewrites."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


# --- corrections: a later judgment about the same proposal, referencing the one it corrects


def corrected(**overrides) -> JudgmentRecord:
    """A DECLINED correction of the default APPROVED judgment-1, made an hour later."""

    values = dict(
        judgment_id="judgment-2",
        decision=OwnerDecision.DECLINED,
        reason_code=ReasonCode.RISK_TOO_HIGH,
        corrects_judgment_id="judgment-1",
        decided_at=DECIDED_AT + timedelta(hours=1),
    )
    values.update(overrides)
    return judgment(**values)


def test_a_correction_appends_and_leaves_the_original_byte_for_byte() -> None:
    original = judgment()
    ledger = JudgmentLedger().append(original).append(corrected())
    assert ledger.records[0] == original
    assert ledger.records[0].decision is OwnerDecision.APPROVED
    assert [entry.judgment_id for entry in ledger.records] == ["judgment-1", "judgment-2"]


def test_the_effective_judgment_is_the_correction_not_the_original() -> None:
    ledger = JudgmentLedger().append(judgment()).append(corrected())
    effective = ledger.effective_judgment_for("proposal-1")
    assert effective is not None and effective.judgment_id == "judgment-2"
    assert [entry.judgment_id for entry in ledger.effective_judgments()] == ["judgment-2"]
    assert ledger.correction_of("judgment-1") is not None
    assert ledger.correction_of("judgment-2") is None


def test_a_correction_of_a_judgment_the_ledger_does_not_hold_is_refused() -> None:
    with pytest.raises(JudgmentLedgerError, match="does not hold"):
        JudgmentLedger().append(corrected())


def test_a_correction_must_judge_the_same_proposal_action_and_task() -> None:
    ledger = JudgmentLedger().append(judgment())
    with pytest.raises(JudgmentLedgerError, match="same proposal"):
        ledger.append(corrected(proposal_id="proposal-9", proposal_fingerprint=FP_TWO))
    with pytest.raises(JudgmentLedgerError, match="same proposal"):
        ledger.append(corrected(task_id="task-9"))
    with pytest.raises(JudgmentLedgerError, match="same proposal"):
        ledger.append(corrected(action_id="action-9"))


def test_an_already_corrected_judgment_cannot_be_corrected_again() -> None:
    """Two corrections of one entry would leave two effective judgments. Chain instead."""

    ledger = JudgmentLedger().append(judgment()).append(corrected())
    with pytest.raises(JudgmentLedgerError, match="already corrected"):
        ledger.append(corrected(judgment_id="judgment-3", reason_code=ReasonCode.NOT_NOW))


def test_corrections_chain_through_the_current_judgment() -> None:
    ledger = JudgmentLedger().append(judgment()).append(corrected())
    third = corrected(
        judgment_id="judgment-3",
        corrects_judgment_id="judgment-2",
        decision=OwnerDecision.DEFERRED,
        reason_code=ReasonCode.NOT_NOW,
        decided_at=DECIDED_AT + timedelta(hours=2),
    )
    ledger = ledger.append(third)
    assert len(ledger.records) == 3
    assert [entry.judgment_id for entry in ledger.effective_judgments()] == ["judgment-3"]
    assert ledger.records[0] == judgment()
    assert ledger.records[1] == corrected()


def test_a_correction_cannot_predate_the_judgment_it_corrects() -> None:
    ledger = JudgmentLedger().append(judgment())
    with pytest.raises(JudgmentLedgerError, match="predate"):
        ledger.append(corrected(decided_at=DECIDED_AT - timedelta(minutes=1)))


def test_a_correction_that_changes_nothing_is_refused() -> None:
    ledger = JudgmentLedger().append(judgment())
    with pytest.raises(JudgmentLedgerError, match="changes nothing"):
        ledger.append(
            corrected(decision=OwnerDecision.APPROVED, reason_code=ReasonCode.ACCEPTED_AS_PROPOSED)
        )


def test_a_correction_cannot_be_replayed_either() -> None:
    ledger = JudgmentLedger().append(judgment()).append(corrected())
    with pytest.raises(JudgmentLedgerError, match="replay"):
        ledger.append(corrected())


def test_a_correction_may_itself_be_an_edit_with_its_own_replacement() -> None:
    ledger = JudgmentLedger().append(judgment())
    edit = corrected(
        decision=OwnerDecision.EDITED,
        reason_code=ReasonCode.NEEDS_CHANGES,
        superseding_proposal_id="proposal-2",
        replacement_fingerprint=FP_TWO,
    )
    ledger = ledger.append(edit)
    assert ledger.effective_judgment_for("proposal-1").decision is OwnerDecision.EDITED
    assert ledger.records[0].decision is OwnerDecision.APPROVED
