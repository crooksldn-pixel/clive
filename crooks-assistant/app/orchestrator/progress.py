"""Progress/event projection for observable engineering work.

This module exposes operational telemetry only: what step is active, what was
completed, evidence produced, waiting/blocking state, and liveness. It does not
record or expose hidden model reasoning.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from .contracts import (
    EngineeringTask,
    ProgressEvent,
    ProgressEventKind,
    ProgressHealth,
    ProgressSnapshot,
    ProgressState,
)


_PROGRESS_KINDS = frozenset(
    {
        ProgressEventKind.ATTEMPT_STARTED,
        ProgressEventKind.STEP_COMPLETED,
        ProgressEventKind.EVIDENCE_RECORDED,
        ProgressEventKind.WAITING,
        ProgressEventKind.RESUMED,
        ProgressEventKind.BLOCKED,
        ProgressEventKind.ATTEMPT_COMPLETED,
    }
)


def project_progress(
    *,
    task: EngineeringTask,
    events: Sequence[ProgressEvent],
) -> ProgressSnapshot:
    if not events:
        raise ValueError("at least one progress event is required")

    ordered = sorted(events, key=lambda event: event.sequence)
    first = ordered[0]
    identity = (
        first.task_id,
        first.task_revision,
        first.attempt_id,
        first.worker_id,
    )

    expected_sequence = 0
    previous_time: datetime | None = None
    completed_seen = False
    for event in ordered:
        if (
            event.task_id,
            event.task_revision,
            event.attempt_id,
            event.worker_id,
        ) != identity:
            raise ValueError("progress stream contains mixed task/attempt/worker identity")
        if event.sequence != expected_sequence:
            raise ValueError(
                f"progress sequence gap: expected {expected_sequence}, got {event.sequence}"
            )
        if previous_time is not None and event.occurred_at < previous_time:
            raise ValueError("progress event time cannot move backwards")
        if completed_seen:
            raise ValueError("progress stream contains events after attempt completion")
        if event.kind is ProgressEventKind.ATTEMPT_COMPLETED:
            completed_seen = True
        previous_time = event.occurred_at
        expected_sequence += 1

    if first.task_id != task.task_id or first.task_revision != task.revision:
        raise ValueError("progress stream does not belong to supplied task revision")

    state = ProgressState.WORKING
    current_activity = first.activity
    active_step_id: str | None = None
    active_step_label: str | None = None
    completed_ids: list[str] = []
    completed_labels: list[str] = []
    evidence_refs: list[str] = []
    waiting_on: str | None = None
    next_known_action: str | None = None
    last_activity_change_at = first.occurred_at
    last_meaningful_progress_at = first.occurred_at
    last_heartbeat_at: datetime | None = None

    for event in ordered:
        if event.kind is not ProgressEventKind.HEARTBEAT:
            current_activity = event.activity
            last_activity_change_at = event.occurred_at

        if event.kind in _PROGRESS_KINDS:
            last_meaningful_progress_at = event.occurred_at

        if event.kind is ProgressEventKind.HEARTBEAT:
            last_heartbeat_at = event.occurred_at
        elif event.kind is ProgressEventKind.STEP_STARTED:
            state = ProgressState.WORKING
            waiting_on = None
            active_step_id = event.step_id
            active_step_label = event.step_label
        elif event.kind is ProgressEventKind.STEP_COMPLETED:
            state = ProgressState.WORKING
            waiting_on = None
            if event.step_id not in completed_ids:
                completed_ids.append(event.step_id or "")
                completed_labels.append(event.step_label or "")
            if active_step_id == event.step_id:
                active_step_id = None
                active_step_label = None
        elif event.kind is ProgressEventKind.EVIDENCE_RECORDED:
            if event.evidence_ref and event.evidence_ref not in evidence_refs:
                evidence_refs.append(event.evidence_ref)
        elif event.kind is ProgressEventKind.WAITING:
            state = ProgressState.WAITING
            waiting_on = event.waiting_on
        elif event.kind is ProgressEventKind.RESUMED:
            state = ProgressState.WORKING
            waiting_on = None
        elif event.kind is ProgressEventKind.BLOCKED:
            state = ProgressState.BLOCKED
            waiting_on = event.waiting_on
        elif event.kind is ProgressEventKind.ATTEMPT_COMPLETED:
            state = ProgressState.COMPLETE
            active_step_id = None
            active_step_label = None
            waiting_on = None

        if event.next_known_action is not None:
            next_known_action = event.next_known_action

    return ProgressSnapshot(
        stream_id=task.stream_id,
        task_id=task.task_id,
        task_revision=task.revision,
        attempt_id=first.attempt_id,
        worker_id=first.worker_id,
        objective=task.objective,
        state=state,
        current_activity=current_activity,
        active_step_id=active_step_id,
        active_step_label=active_step_label,
        completed_steps=tuple(completed_ids),
        completed_step_labels=tuple(completed_labels),
        evidence_refs=tuple(evidence_refs),
        waiting_on=waiting_on,
        next_known_action=next_known_action,
        last_event_at=ordered[-1].occurred_at,
        last_activity_change_at=last_activity_change_at,
        last_meaningful_progress_at=last_meaningful_progress_at,
        last_heartbeat_at=last_heartbeat_at,
    )


def assess_progress(
    snapshot: ProgressSnapshot,
    *,
    now: datetime,
    heartbeat_stale_after: timedelta = timedelta(minutes=15),
    progress_stall_after: timedelta = timedelta(minutes=45),
) -> ProgressHealth:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if now < snapshot.last_event_at:
        raise ValueError("now cannot precede the latest progress event")

    if snapshot.state is ProgressState.COMPLETE:
        return ProgressHealth.COMPLETE
    if snapshot.state is ProgressState.BLOCKED:
        return ProgressHealth.BLOCKED
    if snapshot.state is ProgressState.WAITING:
        return ProgressHealth.WAITING

    latest_liveness = snapshot.last_heartbeat_at or snapshot.last_event_at
    if now - latest_liveness > heartbeat_stale_after:
        return ProgressHealth.STALE
    if now - snapshot.last_meaningful_progress_at > progress_stall_after:
        return ProgressHealth.WORKING_NO_RECENT_PROGRESS
    return ProgressHealth.PROGRESSING


def render_progress_table(
    snapshots: Sequence[ProgressSnapshot],
    *,
    now: datetime,
) -> str:
    """Render a compact Markdown table suitable for Termius/controller output."""

    header = (
        "| Stream | Task | Worker | Health | Current activity | Completed | Evidence | "
        "Waiting / next | Last progress |\n"
        "| --- | --- | --- | --- | --- | --- | ---: | --- | --- |"
    )
    rows: list[str] = []

    for snapshot in sorted(snapshots, key=lambda item: (item.stream_id, item.task_id)):
        health = assess_progress(snapshot, now=now).value
        waiting_next = snapshot.waiting_on or snapshot.next_known_action or "—"
        if snapshot.completed_step_labels:
            recent_completed = snapshot.completed_step_labels[-2:]
            completed_text = "; ".join(recent_completed)
            hidden_count = len(snapshot.completed_step_labels) - len(recent_completed)
            if hidden_count > 0:
                completed_text += f" (+{hidden_count})"
        else:
            completed_text = "—"
        age = now - snapshot.last_meaningful_progress_at
        total_seconds = max(0, int(age.total_seconds()))
        if total_seconds < 60:
            age_text = f"{total_seconds}s ago"
        elif total_seconds < 3600:
            age_text = f"{total_seconds // 60}m ago"
        else:
            age_text = f"{total_seconds // 3600}h {(total_seconds % 3600) // 60}m ago"

        def clean(value: str) -> str:
            return value.replace("|", "/").replace("\n", " ").strip()

        rows.append(
            "| "
            + " | ".join(
                [
                    clean(snapshot.stream_id),
                    clean(snapshot.task_id),
                    clean(snapshot.worker_id),
                    clean(health),
                    clean(snapshot.current_activity),
                    clean(completed_text),
                    str(len(snapshot.evidence_refs)),
                    clean(waiting_next),
                    age_text,
                ]
            )
            + " |"
        )

    return header + ("\n" + "\n".join(rows) if rows else "")
