"""The judgment record's happy paths, and the refusals its adversarial suite leaves implicit.

``tests/test_judgment.py`` proves that malformed records are refused. Each of
those refusals means something only if the same helper, unmodified, builds a
valid record; otherwise a constructor that always raised would pass the whole
file. This file supplies that control, and the contract invariants the
adversarial suite does not reach.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.actions.judgment import (
    JudgmentRecord,
    JudgmentValidationError,
    OwnerDecision,
    OwnerProvenance,
    ReasonCode,
    proposal_fingerprint,
    validate_judgment,
)

DECIDED_AT = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)
ORIGINAL = proposal_fingerprint(b"original proposal")
REPLACEMENT = proposal_fingerprint(b"edited proposal")


def record(**overrides) -> JudgmentRecord:
    values = dict(
        judgment_id="judgment-1",
        task_id="task-1",
        action_id="action-1",
        proposal_id="proposal-1",
        proposal_fingerprint=ORIGINAL,
        decision=OwnerDecision.APPROVED,
        reason_code=ReasonCode.ACCEPTED_AS_PROPOSED,
        provenance=OwnerProvenance(principal_id="owner", session_id="session-1"),
        decided_at=DECIDED_AT,
    )
    values.update(overrides)
    return JudgmentRecord(**values)


def test_a_well_formed_record_constructs_and_revalidates() -> None:
    built = record()
    assert built.decision is OwnerDecision.APPROVED
    assert built.reason_code is ReasonCode.ACCEPTED_AS_PROPOSED
    assert (built.redaction_version, built.schema_version) == (1, 1)
    validate_judgment(built)


def test_edited_with_a_distinct_superseding_proposal_is_valid() -> None:
    edited = record(
        decision=OwnerDecision.EDITED,
        reason_code=ReasonCode.NEEDS_CHANGES,
        superseding_proposal_id="proposal-2",
        replacement_fingerprint=REPLACEMENT,
    )
    assert edited.superseding_proposal_id == "proposal-2"
    assert edited.replacement_fingerprint == REPLACEMENT


def test_edited_may_not_overwrite_the_original_proposal() -> None:
    with pytest.raises(JudgmentValidationError, match="overwrite"):
        record(
            decision=OwnerDecision.EDITED,
            superseding_proposal_id="proposal-1",
            replacement_fingerprint=REPLACEMENT,
        )


def test_edited_replacement_must_differ_from_the_original() -> None:
    with pytest.raises(JudgmentValidationError, match="differ"):
        record(
            decision=OwnerDecision.EDITED,
            superseding_proposal_id="proposal-2",
            replacement_fingerprint=ORIGINAL,
        )


def test_edited_without_a_replacement_fingerprint_fails_closed() -> None:
    with pytest.raises(JudgmentValidationError):
        record(decision=OwnerDecision.EDITED, superseding_proposal_id="proposal-2")


@pytest.mark.parametrize("decision", ["EXPIRED", "AUTO_APPROVED", "approved", "", None, 1])
def test_anything_outside_the_four_owner_decisions_is_refused(decision) -> None:
    with pytest.raises(JudgmentValidationError):
        record(decision=decision)


def test_vocabulary_given_as_string_values_is_coerced_to_the_enums() -> None:
    built = record(decision="DECLINED", reason_code="WRONG_SCOPE")
    assert built.decision is OwnerDecision.DECLINED
    assert built.reason_code is ReasonCode.WRONG_SCOPE


@pytest.mark.parametrize("code", ["ACCEPT_AS_PROPOSED", "LOOKS_FINE", "", None])
def test_reason_codes_outside_the_v1_vocabulary_are_refused(code) -> None:
    with pytest.raises(JudgmentValidationError):
        record(reason_code=code)


@pytest.mark.parametrize("name", ["judgment_id", "task_id", "action_id", "proposal_id"])
def test_blank_identity_fails_closed(name) -> None:
    with pytest.raises(JudgmentValidationError):
        record(**{name: "  "})


def test_naive_decision_timestamp_is_refused() -> None:
    with pytest.raises(JudgmentValidationError, match="timezone"):
        record(decided_at=datetime(2026, 9, 22, 18, 0))


def test_provenance_without_a_session_fails_closed() -> None:
    with pytest.raises(JudgmentValidationError):
        OwnerProvenance(principal_id="owner", session_id="")


def test_unsupported_schema_version_fails_closed() -> None:
    with pytest.raises(JudgmentValidationError):
        record(schema_version=2)


def test_explanation_at_the_bound_is_accepted_and_one_over_is_not() -> None:
    assert record(redacted_explanation="x" * 500).redacted_explanation == "x" * 500
    with pytest.raises(JudgmentValidationError):
        record(redacted_explanation="x" * 501)


@pytest.mark.parametrize("leak", ["Bearer abc", "PRIVATE KEY", "hidden-prompt leak", "ApiKey=1"])
def test_more_sensitive_labels_are_refused_case_insensitively(leak) -> None:
    with pytest.raises(JudgmentValidationError):
        record(redacted_explanation=leak)


def test_fingerprint_is_deterministic_over_bytes_and_over_mappings() -> None:
    assert proposal_fingerprint(b"abc") == proposal_fingerprint(b"abc")
    assert proposal_fingerprint({"b": 1, "a": 2}) == proposal_fingerprint({"a": 2, "b": 1})
    assert proposal_fingerprint(b"abc") != proposal_fingerprint({"payload": "abc"})


def test_fingerprint_refuses_a_bare_string() -> None:
    with pytest.raises(TypeError):
        proposal_fingerprint("abc")  # type: ignore[arg-type]


def test_records_are_immutable() -> None:
    built = record()
    with pytest.raises((AttributeError, TypeError)):
        built.decision = OwnerDecision.DECLINED  # type: ignore[misc]


def test_a_judgment_cannot_correct_itself() -> None:
    with pytest.raises(JudgmentValidationError, match="correct itself"):
        record(corrects_judgment_id="judgment-1")


def test_a_blank_correction_reference_fails_closed() -> None:
    with pytest.raises(JudgmentValidationError):
        record(corrects_judgment_id="  ")


def test_a_well_formed_correction_reference_is_carried() -> None:
    assert record(judgment_id="judgment-2", corrects_judgment_id="judgment-1").corrects_judgment_id == "judgment-1"
