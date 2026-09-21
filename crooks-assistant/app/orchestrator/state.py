"""Pure active-state projection for the Phase 1 control-plane simulator."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

from .contracts import (
    ActiveState,
    BlockerClass,
    EngineeringResult,
    EngineeringTask,
    NextActionKind,
    StreamState,
    TaskStatus,
)
from .store import latest_result_by_task_revision


def _stage_from_result(task: EngineeringTask, result: EngineeringResult | None) -> TaskStatus:
    if result is None:
        return task.status

    if result.owner_decision_required or result.next_action.kind is NextActionKind.OWNER_GATE:
        return TaskStatus.OWNER_GATE
    if result.blocker_class is not BlockerClass.NONE or result.next_action.kind is NextActionKind.BLOCKED:
        return TaskStatus.BLOCKED
    if result.next_action.kind is NextActionKind.DONE:
        return TaskStatus.DONE
    if result.next_action.kind is NextActionKind.REVIEW:
        return TaskStatus.REVIEWING
    if result.next_action.kind in {
        NextActionKind.REPAIR,
        NextActionKind.CONTINUE,
        NextActionKind.EVIDENCE,
    }:
        return TaskStatus.READY
    if result.next_action.kind is NextActionKind.INTEGRATE:
        return TaskStatus.ACCEPTED
    return task.status


def build_active_state(
    *,
    tasks: Sequence[EngineeringTask],
    results: Sequence[EngineeringResult],
    branch_heads: Mapping[str, str],
    generated_at: datetime,
) -> ActiveState:
    latest = latest_result_by_task_revision(results)
    streams: list[StreamState] = []

    for task in sorted(tasks, key=lambda item: (item.stream_id, item.task_id, item.revision)):
        head = branch_heads.get(task.target_branch)
        if head is None:
            raise ValueError(f"missing branch head for {task.target_branch}")

        result = latest.get((task.task_id, task.revision))
        if result is not None and result.result_sha is not None and result.result_sha != head:
            stage = TaskStatus.OBSOLETE
            blocker_class = BlockerClass.OBSOLETE
        else:
            stage = _stage_from_result(task, result)
            blocker_class = result.blocker_class if result else BlockerClass.NONE

        streams.append(
            StreamState(
                stream_id=task.stream_id,
                objective=task.objective,
                branch=task.target_branch,
                head_sha=head,
                stage=stage,
                task_id=task.task_id,
                attempt_id=result.attempt_id if result else None,
                worker_id=result.worker_id if result else None,
                blocker_class=blocker_class,
                owner_gate=bool(result and result.owner_decision_required),
                last_transition_at=result.completed_at if result else task.created_at,
            )
        )

    queued = sum(1 for stream in streams if stream.stage is TaskStatus.READY)
    active = sum(
        1
        for stream in streams
        if stream.stage in {TaskStatus.ASSIGNED, TaskStatus.RUNNING, TaskStatus.REVIEWING}
    )
    return ActiveState(
        generated_at=generated_at,
        streams=tuple(streams),
        queue_depth=queued,
        active_worker_count=active,
    )
