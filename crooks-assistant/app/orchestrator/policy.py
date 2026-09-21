"""Deterministic continuation policy.

The worker may *suggest* a next action. This module decides whether the action is
mechanically eligible to continue without owner/hourly intervention.

It intentionally does not dispatch anything and has no runtime/service effects.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    BlockerClass,
    EngineeringResult,
    EngineeringTask,
    NextActionKind,
)


_AUTO_CONTINUE_KINDS = frozenset(
    {
        NextActionKind.CONTINUE,
        NextActionKind.REVIEW,
        NextActionKind.REPAIR,
        NextActionKind.EVIDENCE,
    }
)


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    allowed: bool
    reason: str


def evaluate_obvious_continuation(
    task: EngineeringTask,
    result: EngineeringResult,
    *,
    candidate_worker_id: str | None = None,
) -> ContinuationDecision:
    """Return whether the proposed next action can advance mechanically.

    The policy fails closed on identity drift, incomplete evidence, owner gates,
    deterministic/obsolete blockers, and reviewer self-certification.
    """

    if result.task_id != task.task_id or result.task_revision != task.revision:
        return ContinuationDecision(False, "task identity or revision mismatch")

    if result.base_sha != task.base_sha:
        return ContinuationDecision(False, "result base SHA does not match task revision")

    if result.runtime_effects != "none":
        return ContinuationDecision(False, "repository-only task reported runtime effects")

    if result.owner_decision_required:
        return ContinuationDecision(False, "owner decision is explicitly required")

    if result.blocker_class is not BlockerClass.NONE:
        return ContinuationDecision(False, f"blocked: {result.blocker_class.value}")

    action = result.next_action
    if action.kind in {NextActionKind.OWNER_GATE, NextActionKind.BLOCKED, NextActionKind.DONE}:
        return ContinuationDecision(False, f"next action is terminal/gated: {action.kind.value}")

    if action.kind not in _AUTO_CONTINUE_KINDS:
        return ContinuationDecision(False, f"{action.kind.value} is not auto-continuable in V1")

    if not action.mechanically_authorised:
        return ContinuationDecision(False, "worker did not mark next action mechanically authorised")

    if not result.clean_worktree:
        return ContinuationDecision(False, "worker result is not from a clean worktree")

    missing_evidence = set(task.required_evidence) - set(result.evidence_satisfied)
    if action.kind is not NextActionKind.EVIDENCE and missing_evidence:
        return ContinuationDecision(
            False,
            "required evidence remains incomplete: " + ", ".join(sorted(missing_evidence)),
        )

    if action.subject_sha is not None:
        if result.result_sha is None:
            return ContinuationDecision(False, "next action has a subject but result has no result SHA")
        if action.subject_sha != result.result_sha:
            return ContinuationDecision(False, "next action subject SHA is stale or mismatched")

    if (
        action.kind is NextActionKind.REVIEW
        and (task.reviewer_must_be_independent or action.required_reviewer_independence)
    ):
        if not candidate_worker_id:
            return ContinuationDecision(False, "independent reviewer identity is not yet resolved")
        if candidate_worker_id == result.worker_id:
            return ContinuationDecision(False, "repair/build author cannot satisfy independent review")

    return ContinuationDecision(True, "same authorised bounded workflow may continue")
