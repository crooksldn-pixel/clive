"""Deterministic Phase 1 scheduler simulation.

This module does not launch Claude or mutate runtime services. It proves the core
routing rule: when a result has an obvious policy-valid next action, choose an
eligible worker immediately and fairly across streams instead of waiting for an
hourly supervisor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from .contracts import (
    EngineeringResult,
    EngineeringTask,
    NextActionKind,
    TaskRuntimeState,
    WorkerProfile,
)
from .policy import evaluate_obvious_continuation


_EPOCH = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ContinuationCandidate:
    task: EngineeringTask
    result: EngineeringResult
    current_branch_head: str
    runtime_state: TaskRuntimeState | None = None
    latest_task_revision: int | None = None
    stream_last_dispatched_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DispatchDecision:
    stream_id: str
    task_id: str
    task_revision: int
    action: NextActionKind
    worker_id: str
    subject_sha: str | None
    reason: str


def _worker_supports(worker: WorkerProfile, required_role: str | None) -> bool:
    if not worker.available:
        return False
    if required_role is None:
        return True
    return required_role in worker.roles


def select_obvious_dispatch(
    *,
    candidates: Sequence[ContinuationCandidate],
    workers: Sequence[WorkerProfile],
) -> DispatchDecision | None:
    """Select one immediately dispatchable continuation.

    Ordering is deterministic:
    1. higher explicit task priority;
    2. stream least recently dispatched (never-dispatched first);
    3. older task creation;
    4. stable stream/task/revision identity.

    A blocked/unroutable stream is skipped so it cannot starve another eligible
    stream.
    """

    ordered = sorted(
        candidates,
        key=lambda candidate: (
            -candidate.task.priority,
            candidate.stream_last_dispatched_at or _EPOCH,
            candidate.task.created_at,
            candidate.task.stream_id,
            candidate.task.task_id,
            candidate.task.revision,
        ),
    )

    available_workers = sorted(
        (worker for worker in workers if worker.available),
        key=lambda worker: worker.worker_id,
    )

    for candidate in ordered:
        action = candidate.result.next_action
        for worker in available_workers:
            if not _worker_supports(worker, action.required_role):
                continue
            decision = evaluate_obvious_continuation(
                candidate.task,
                candidate.result,
                candidate_worker_id=worker.worker_id,
                current_branch_head=candidate.current_branch_head,
                runtime_state=candidate.runtime_state,
                latest_task_revision=candidate.latest_task_revision,
            )
            if not decision.allowed:
                continue
            return DispatchDecision(
                stream_id=candidate.task.stream_id,
                task_id=candidate.task.task_id,
                task_revision=candidate.task.revision,
                action=action.kind,
                worker_id=worker.worker_id,
                subject_sha=action.subject_sha,
                reason=decision.reason,
            )

    return None
