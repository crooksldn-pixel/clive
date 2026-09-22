"""The gate in front of acceptance: stale and late results are refused before a verdict counts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.orchestrator.review_acceptance import (
    AcceptanceTarget,
    ReviewEvidence,
    ReviewVerdict,
    evidence_fingerprint,
)
from app.orchestrator.review_result_gate import ReviewResultEnvelope, gate_review_result
from app.orchestrator.routing import Party, Principal, PrincipalKind, SessionContext, Workspace

SHA = "a" * 40
STARTED_AT = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
PAYLOAD = b"independent review evidence"


def _party(principal: str, session: str, workspace: str, *, read_only: bool) -> Party:
    return Party(
        principal=Principal(
            principal_id=principal, kind=PrincipalKind.MODEL, model_family="independent-model"
        ),
        session=SessionContext(session_id=session, context_is_fresh=True, started_at=STARTED_AT),
        workspace=Workspace(
            workspace_id=workspace,
            branch="claude/candidate",
            head_sha=SHA,
            read_only=read_only,
            clean=True,
        ),
    )


def _author() -> Party:
    return _party("builder-principal", "build-session", "build-workspace", read_only=False)


def _other_author() -> Party:
    return _party("other-author", "build-session", "build-workspace", read_only=False)


def _reviewer() -> Party:
    return _party("reviewer-principal", "review-session", "review-workspace", read_only=True)


def _target() -> AcceptanceTarget:
    return AcceptanceTarget(
        task_id="task-1",
        task_revision=3,
        attempt_id="attempt-7",
        candidate_sha=SHA,
        author=_author(),
    )


def _envelope(target: AcceptanceTarget | None = None) -> ReviewResultEnvelope:
    target = target or _target()
    evidence = ReviewEvidence(
        task_id=target.task_id,
        task_revision=target.task_revision,
        attempt_id=target.attempt_id,
        candidate_sha=target.candidate_sha,
        author=target.author,
        reviewer=_reviewer(),
        verdict=ReviewVerdict.READY,
        evidence_sha256=evidence_fingerprint(PAYLOAD),
        observed_candidate_sha=target.candidate_sha,
        completed_at=COMPLETED_AT,
    )
    return ReviewResultEnvelope(target=target, evidence=evidence, evidence_payload=PAYLOAD)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("task_id", "task-old", "stale_task_id"),
        ("task_revision", 2, "stale_task_revision"),
        ("attempt_id", "attempt-old", "stale_attempt_id"),
        ("candidate_sha", "b" * 40, "stale_candidate_sha"),
        ("author", _other_author(), "stale_author_provenance"),
    ],
)
def test_gate_rejects_stale_envelope_before_acceptance(
    field: str, value: object, reason: str
) -> None:
    current = _target()
    stale = current.model_copy(update={field: value})

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
    assert "current_candidate_sha_drift" in decision.reasons
