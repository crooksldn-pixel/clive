from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.orchestrator.review_acceptance import (
    AcceptanceTarget,
    ReviewEvidence,
    ReviewVerdict,
    evaluate_review_acceptance,
    evidence_fingerprint,
)
from app.orchestrator.routing import Party, Principal, PrincipalKind, SessionContext, Workspace

SHA = "a" * 40
OTHER_SHA = "b" * 40
PAYLOAD = b"independent-review-evidence"
STARTED_AT = datetime(2026, 9, 22, 8, 0, tzinfo=UTC)


def party(*, principal: str, session: str, workspace: str, writable: bool = False) -> Party:
    """A principal in a session in a workspace: the three that routing keeps apart.

    ``writable`` is the author's side of things, since an author's workspace can
    mutate the candidate. A reviewer's must not, and the test that hands a
    reviewer ``writable=True`` expects to be refused for exactly that.
    """

    return Party(
        principal=Principal(
            principal_id=principal, kind=PrincipalKind.MODEL, model_family="test-model"
        ),
        session=SessionContext(session_id=session, context_is_fresh=True, started_at=STARTED_AT),
        workspace=Workspace(
            workspace_id=workspace,
            branch="claude/candidate",
            head_sha=SHA,
            read_only=not writable,
            clean=True,
        ),
    )


def fixtures():
    author = party(principal="author", session="author-session", workspace="author-ws", writable=True)
    reviewer = party(principal="reviewer", session="review-session", workspace="review-ws")
    target = AcceptanceTarget(
        task_id="task-1",
        task_revision=3,
        attempt_id="attempt-7",
        candidate_sha=SHA,
        author=author,
    )
    evidence = ReviewEvidence(
        task_id=target.task_id,
        task_revision=target.task_revision,
        attempt_id=target.attempt_id,
        candidate_sha=SHA,
        author=author,
        reviewer=reviewer,
        verdict=ReviewVerdict.READY,
        evidence_sha256=evidence_fingerprint(PAYLOAD),
        observed_candidate_sha=SHA,
        completed_at=datetime.now(UTC),
    )
    return target, evidence


def decide(target, evidence, *, current_sha=SHA, payload=PAYLOAD):
    return evaluate_review_acceptance(
        target=target,
        evidence=evidence,
        current_candidate_sha=current_sha,
        evidence_payload=payload,
    )


def test_exact_bound_independent_ready_evidence_is_accepted():
    target, evidence = fixtures()
    decision = decide(target, evidence)
    assert decision.accepted is True
    assert decision.accepted_sha == SHA
    assert decision.reasons == ()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("task_id", "task-2", "task_id_drift"),
        ("task_revision", 4, "task_revision_drift"),
        ("attempt_id", "attempt-8", "attempt_id_drift"),
        ("candidate_sha", OTHER_SHA, "evidence_candidate_sha_drift"),
        ("observed_candidate_sha", OTHER_SHA, "review_observed_sha_drift"),
    ],
)
def test_identity_and_candidate_drift_fail_closed(field, value, reason):
    target, evidence = fixtures()
    mutated = evidence.model_copy(update={field: value})
    decision = decide(target, mutated)
    assert decision.accepted is False
    assert reason in decision.reasons


def test_current_candidate_sha_drift_rejects_late_result():
    target, evidence = fixtures()
    decision = decide(target, evidence, current_sha=OTHER_SHA)
    assert decision.accepted is False
    assert "current_candidate_sha_drift" in decision.reasons


def test_malformed_current_sha_fails_closed():
    target, evidence = fixtures()
    decision = decide(target, evidence, current_sha="not-a-sha")
    assert decision.accepted is False
    assert decision.reasons == ("malformed_current_candidate_sha",)


def test_evidence_payload_mutation_is_rejected():
    target, evidence = fixtures()
    decision = decide(target, evidence, payload=PAYLOAD + b"-tampered")
    assert decision.accepted is False
    assert "evidence_fingerprint_mismatch" in decision.reasons


def test_repair_required_never_counts_as_acceptance():
    target, evidence = fixtures()
    evidence = evidence.model_copy(update={"verdict": ReviewVerdict.REPAIR_REQUIRED})
    decision = decide(target, evidence)
    assert decision.accepted is False
    assert "verdict_not_ready" in decision.reasons


def test_same_principal_fresh_session_cannot_launder_self_review():
    target, evidence = fixtures()
    reviewer = party(principal="author", session="fresh-session", workspace="fresh-ws")
    evidence = evidence.model_copy(update={"reviewer": reviewer})
    decision = decide(target, evidence)
    assert decision.accepted is False
    assert any(reason.startswith("reviewer_ineligible:") for reason in decision.reasons)


def test_reviewer_with_candidate_mutation_capability_is_ineligible():
    target, evidence = fixtures()
    reviewer = party(principal="reviewer", session="review-session", workspace="review-ws", writable=True)
    evidence = evidence.model_copy(update={"reviewer": reviewer})
    decision = decide(target, evidence)
    assert decision.accepted is False
    assert any(reason.startswith("reviewer_ineligible:") for reason in decision.reasons)


def test_author_provenance_drift_is_rejected():
    target, evidence = fixtures()
    other_author = party(principal="other-author", session="author-session", workspace="author-ws", writable=True)
    evidence = evidence.model_copy(update={"author": other_author})
    decision = decide(target, evidence)
    assert decision.accepted is False
    assert "author_provenance_drift" in decision.reasons
