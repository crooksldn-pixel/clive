from __future__ import annotations

from dataclasses import dataclass

from app.orchestrator.review_acceptance import (
    AcceptanceDecision,
    AcceptanceTarget,
    ReviewEvidence,
    evaluate_review_acceptance,
)


@dataclass(frozen=True)
class ReviewResultEnvelope:
    """Immutable result presented by a reviewer attempt."""

    target: AcceptanceTarget
    evidence: ReviewEvidence
    evidence_payload: bytes


@dataclass(frozen=True)
class ReviewResultGateDecision:
    accepted: bool
    accepted_sha: str | None
    reasons: tuple[str, ...]


def gate_review_result(
    *,
    envelope: ReviewResultEnvelope,
    current_target: AcceptanceTarget,
    current_candidate_sha: str,
) -> ReviewResultGateDecision:
    """Fence stale/late review results before they can become acceptance.

    The current authoritative target is supplied by CLIVE. A result for any
    superseded task revision, attempt, or candidate is rejected before the
    acceptance evaluator is consulted. This module deliberately performs no
    dispatch, branch mutation, deployment, or owner-authorisation action.
    """

    submitted = envelope.target
    reasons: list[str] = []
    if submitted.task_id != current_target.task_id:
        reasons.append("stale_task_id")
    if submitted.task_revision != current_target.task_revision:
        reasons.append("stale_task_revision")
    if submitted.attempt_id != current_target.attempt_id:
        reasons.append("stale_attempt_id")
    if submitted.candidate_sha != current_target.candidate_sha:
        reasons.append("stale_candidate_sha")
    if submitted.author != current_target.author:
        reasons.append("stale_author_provenance")

    if reasons:
        return ReviewResultGateDecision(False, None, tuple(reasons))

    decision: AcceptanceDecision = evaluate_review_acceptance(
        target=current_target,
        evidence=envelope.evidence,
        current_candidate_sha=current_candidate_sha,
        evidence_payload=envelope.evidence_payload,
    )
    return ReviewResultGateDecision(
        accepted=decision.accepted,
        accepted_sha=decision.accepted_sha,
        reasons=decision.reasons,
    )
