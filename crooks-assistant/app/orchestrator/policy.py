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
    TaskKind,
    TaskRuntimeState,
    TaskStatus,
    validate_exact_sha,
)


_AUTO_CONTINUE_KINDS = frozenset(
    {
        NextActionKind.CONTINUE,
        NextActionKind.REVIEW,
        NextActionKind.REPAIR,
        NextActionKind.EVIDENCE,
    }
)

_ALLOWED_NEXT_BY_TASK_KIND = {
    TaskKind.BUILD: frozenset(
        {NextActionKind.CONTINUE, NextActionKind.EVIDENCE, NextActionKind.REVIEW}
    ),
    TaskKind.REPAIR: frozenset(
        {NextActionKind.CONTINUE, NextActionKind.EVIDENCE, NextActionKind.REVIEW}
    ),
    TaskKind.REVIEW: frozenset({NextActionKind.REPAIR, NextActionKind.EVIDENCE}),
    TaskKind.EVIDENCE: frozenset(
        {NextActionKind.CONTINUE, NextActionKind.EVIDENCE, NextActionKind.REVIEW}
    ),
    TaskKind.INTEGRATION: frozenset(
        {NextActionKind.CONTINUE, NextActionKind.EVIDENCE, NextActionKind.REVIEW}
    ),
}


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    allowed: bool
    reason: str


def evaluate_obvious_continuation(
    task: EngineeringTask,
    result: EngineeringResult,
    *,
    candidate_worker_id: str | None = None,
    current_branch_head: str | None = None,
    runtime_state: TaskRuntimeState | None = None,
    latest_task_revision: int | None = None,
) -> ContinuationDecision:
    """Return whether the proposed next action can advance mechanically.

    The policy fails closed on identity drift, incomplete evidence, owner gates,
    deterministic/obsolete blockers, and reviewer self-certification.
    """

    if result.task_id != task.task_id or result.task_revision != task.revision:
        return ContinuationDecision(False, "task identity or revision mismatch")

    if latest_task_revision is not None and task.revision != latest_task_revision:
        return ContinuationDecision(False, "task revision is obsolete")

    if runtime_state is not None:
        if (
            runtime_state.task_id != task.task_id
            or runtime_state.task_revision != task.revision
        ):
            return ContinuationDecision(False, "runtime state identity or revision mismatch")
        if runtime_state.owner_gate:
            return ContinuationDecision(False, "controller-owned owner gate is active")
        if runtime_state.blocker_class is not BlockerClass.NONE:
            return ContinuationDecision(
                False,
                f"controller-owned blocker: {runtime_state.blocker_class.value}",
            )
        if runtime_state.status in {
            TaskStatus.OWNER_GATE,
            TaskStatus.BLOCKED,
            TaskStatus.OBSOLETE,
            TaskStatus.CANCELLED,
            TaskStatus.DONE,
            TaskStatus.ASSIGNED,
            TaskStatus.RUNNING,
            TaskStatus.REVIEWING,
        }:
            return ContinuationDecision(
                False,
                f"controller-owned task state is not dispatchable: {runtime_state.status.value}",
            )

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

    if action.kind not in _ALLOWED_NEXT_BY_TASK_KIND[task.kind]:
        return ContinuationDecision(
            False,
            f"{action.kind.value} is not a valid next stage for {task.kind.value}",
        )

    if not action.mechanically_authorised:
        return ContinuationDecision(False, "worker did not mark next action mechanically authorised")

    if not result.clean_worktree:
        return ContinuationDecision(False, "worker result is not from a clean worktree")

    if task.allowed_paths:
        escaped = [
            path
            for path in result.changed_paths
            if not any(
                path == allowed.rstrip("/") or path.startswith(allowed.rstrip("/") + "/")
                for allowed in task.allowed_paths
            )
        ]
        if escaped:
            return ContinuationDecision(
                False,
                "result changed paths outside task scope: " + ", ".join(sorted(escaped)),
            )

    missing_evidence = set(task.required_evidence) - set(result.evidence_satisfied)
    if action.kind is not NextActionKind.EVIDENCE and missing_evidence:
        return ContinuationDecision(
            False,
            "required evidence remains incomplete: " + ", ".join(sorted(missing_evidence)),
        )

    if result.result_sha is not None:
        if current_branch_head is None:
            return ContinuationDecision(False, "fresh branch HEAD has not been resolved")
        try:
            current_branch_head = validate_exact_sha(current_branch_head)
        except ValueError:
            return ContinuationDecision(False, "current branch HEAD is not an exact Git SHA")
        if current_branch_head != result.result_sha:
            return ContinuationDecision(False, "current branch HEAD differs from result SHA")

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
