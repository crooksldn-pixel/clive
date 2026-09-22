from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from app.orchestrator.review_acceptance import AcceptanceTarget, ReviewEvidence
from app.orchestrator.review_result_gate import ReviewResultEnvelope, gate_review_result
from app.orchestrator.reviewer_routing import ReviewerProvenance


SHA = "a" * 40


def _target() -> AcceptanceTarget:
    return AcceptanceTarget(
        task_id="task-1",
        task_revision=3,
        attempt_id="attempt-7",
        candidate_sha=SHA,
        author="builder-principal",
    )


def _reviewer() -> ReviewerProvenance:
    return ReviewerProvenance(
        principal_id="reviewer-principal",
        session_id="review-session",
        workspace_id="review-workspace",
        workspace_read_only=True,
        can_mutate_candidate=False,
        model_family="independent-model",
    )


def _envelope(target: AcceptanceTarget | None = None) -> ReviewResultEnvelope:
    target = target or _target()
    payload = b"independent review evidence"
    evidence = ReviewEvidence(
        task_id=target.task_id,
        task_revision=target.task_revision,
        attempt_id=target.attempt_id,
        candidate_sha=target.candidate_sha,
        author=target.author,
        reviewer=_reviewer(),
        verdict="READY",
        evidence_sha256=hashlib.sha256(payload).hexdigest(),
    )
    return ReviewResultEnvelope(target=target, evidence=evidence, evidence_payload=payload)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("task_id", "task-old", "stale_task_id"),
        ("task_revision", 2, "stale_task_revision"),
        ("attempt_id", "attempt-old", "stale_attempt_id"),
        ("candidate_sha", "b" * 40, "stale_candidate_sha"),
        ("author", "other-author", "stale_author_provenance"),
    ],
)
def test_gate_rejects_stale_envelope_before_acceptance(field: str, value: object, reason: str) -> None:
    current = _target()
    stale = replace(current, **{field: value})

    decision = gate_review_result(
        envelope=_envelope(stale),
        current_target=current,
        current_candidate_sha=SHA,
    )

    assert decision.accepted is False
    assert decision.accepted_sha is None
    assert reason in decision.reasons


def test_gate_accepts_only_current_exact_sha_result() -> None:
    current = _target()

    decision = gate_review_result(
        envelope=_envelope(current),
        current_target=current,
        current_candidate_sha=SHA,
    )

    assert decision.accepted is True
    assert decision.accepted_sha == SHA
    assert decision.reasons == ()


def test_gate_rejects_late_result_when_branch_has_moved() -> None:
    current = _target()

    decision = gate_review_result(
        envelope=_envelope(current),
        current_target=current,
        current_candidate_sha="c" * 40,
    )

    assert decision.accepted is False
    assert decision.accepted_sha is None
    assert "candidate_sha_drift" in decision.reasons
