"""Fail-closed acceptance of independent engineering review evidence.

This module deliberately does not dispatch reviewers or grant release/deployment
authority. It validates whether a review verdict may count as engineering
acceptance for one exact task revision, attempt and candidate SHA.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .contracts import ExactSha, StrictRecord, validate_exact_sha
from .routing import Party, ReviewAssignment, evaluate_review_eligibility


class ReviewVerdict(StrEnum):
    READY = "ready"
    REPAIR_REQUIRED = "repair_required"


class ReviewEvidence(StrictRecord):
    schema_version: Literal["clive.review_evidence.v1"] = "clive.review_evidence.v1"
    task_id: str = Field(min_length=1, max_length=120)
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120)
    candidate_sha: ExactSha
    author: Party
    reviewer: Party
    verdict: ReviewVerdict
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_candidate_sha: ExactSha
    completed_at: datetime

    @field_validator("candidate_sha", "observed_candidate_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)

    @field_validator("completed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class AcceptanceTarget(StrictRecord):
    task_id: str
    task_revision: int = Field(ge=1)
    attempt_id: str
    candidate_sha: ExactSha
    author: Party

    @field_validator("candidate_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)


class AcceptanceDecision(StrictRecord):
    accepted: bool
    reasons: tuple[str, ...] = ()
    accepted_sha: ExactSha | None = None

    @model_validator(mode="after")
    def accepted_sha_matches_state(self) -> "AcceptanceDecision":
        if self.accepted != (self.accepted_sha is not None):
            raise ValueError("accepted_sha must exist iff accepted=true")
        return self


def evidence_fingerprint(payload: bytes) -> str:
    """Fingerprint raw evidence bytes; callers persist bytes separately."""
    return hashlib.sha256(payload).hexdigest()


def evaluate_review_acceptance(
    *,
    target: AcceptanceTarget,
    evidence: ReviewEvidence,
    current_candidate_sha: str,
    evidence_payload: bytes,
) -> AcceptanceDecision:
    """Return acceptance only when every identity and evidence fence still holds."""
    reasons: list[str] = []
    try:
        current_sha = validate_exact_sha(current_candidate_sha)
    except (TypeError, ValueError):
        return AcceptanceDecision(accepted=False, reasons=("malformed_current_candidate_sha",))

    if evidence.task_id != target.task_id:
        reasons.append("task_id_drift")
    if evidence.task_revision != target.task_revision:
        reasons.append("task_revision_drift")
    if evidence.attempt_id != target.attempt_id:
        reasons.append("attempt_id_drift")
    if evidence.candidate_sha != target.candidate_sha:
        reasons.append("evidence_candidate_sha_drift")
    if evidence.observed_candidate_sha != target.candidate_sha:
        reasons.append("review_observed_sha_drift")
    if current_sha != target.candidate_sha:
        reasons.append("current_candidate_sha_drift")
    if evidence.author != target.author:
        reasons.append("author_provenance_drift")
    if evidence.evidence_sha256 != evidence_fingerprint(evidence_payload):
        reasons.append("evidence_fingerprint_mismatch")
    if evidence.verdict is not ReviewVerdict.READY:
        reasons.append("verdict_not_ready")

    assignment = ReviewAssignment(
        candidate_sha=target.candidate_sha,
        author=target.author,
        reviewer=evidence.reviewer,
    )
    eligibility = evaluate_review_eligibility(
        assignment,
        observed_candidate_sha=current_sha,
    )
    if not eligibility.eligible:
        reasons.extend(f"reviewer_ineligible:{reason.value}" for reason in eligibility.reasons)

    if reasons:
        return AcceptanceDecision(accepted=False, reasons=tuple(dict.fromkeys(reasons)))
    return AcceptanceDecision(accepted=True, accepted_sha=target.candidate_sha)
