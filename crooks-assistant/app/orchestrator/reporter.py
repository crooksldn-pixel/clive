"""Convenience API for emitting structured operational progress.

A runner can call this at task boundaries without exposing hidden reasoning.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from .contracts import EngineeringTask, ProgressEvent, ProgressEventKind
from .store import JsonRecordStore


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ProgressReporter:
    def __init__(
        self,
        *,
        store: JsonRecordStore,
        task: EngineeringTask,
        attempt_id: str,
        worker_id: str,
        subject_sha: str | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self.store = store
        self.task = task
        self.attempt_id = attempt_id
        self.worker_id = worker_id
        self.subject_sha = subject_sha
        self.clock = clock

    def _emit(
        self,
        *,
        kind: ProgressEventKind,
        activity: str,
        step_id: str | None = None,
        step_label: str | None = None,
        evidence_ref: str | None = None,
        waiting_on: str | None = None,
        next_known_action: str | None = None,
    ) -> ProgressEvent:
        existing = self.store.read_progress_events(
            task_id=self.task.task_id,
            task_revision=self.task.revision,
            attempt_id=self.attempt_id,
        )
        if existing and existing[0].worker_id != self.worker_id:
            raise ValueError("attempt is already bound to a different worker")

        event = ProgressEvent(
            task_id=self.task.task_id,
            task_revision=self.task.revision,
            attempt_id=self.attempt_id,
            worker_id=self.worker_id,
            sequence=len(existing),
            kind=kind,
            occurred_at=self.clock(),
            activity=activity,
            step_id=step_id,
            step_label=step_label,
            evidence_ref=evidence_ref,
            waiting_on=waiting_on,
            next_known_action=next_known_action,
            subject_sha=self.subject_sha,
        )
        self.store.put_progress_event(event)
        return event

    def start(self, activity: str, *, next_known_action: str | None = None) -> ProgressEvent:
        return self._emit(
            kind=ProgressEventKind.ATTEMPT_STARTED,
            activity=activity,
            next_known_action=next_known_action,
        )

    def step_started(
        self,
        step_id: str,
        step_label: str,
        *,
        activity: str | None = None,
        next_known_action: str | None = None,
    ) -> ProgressEvent:
        return self._emit(
            kind=ProgressEventKind.STEP_STARTED,
            activity=activity or step_label,
            step_id=step_id,
            step_label=step_label,
            next_known_action=next_known_action,
        )

    def step_completed(
        self,
        step_id: str,
        step_label: str,
        *,
        activity: str | None = None,
        next_known_action: str | None = None,
    ) -> ProgressEvent:
        return self._emit(
            kind=ProgressEventKind.STEP_COMPLETED,
            activity=activity or f"Completed: {step_label}",
            step_id=step_id,
            step_label=step_label,
            next_known_action=next_known_action,
        )

    def evidence(
        self,
        evidence_ref: str,
        *,
        activity: str,
        next_known_action: str | None = None,
    ) -> ProgressEvent:
        return self._emit(
            kind=ProgressEventKind.EVIDENCE_RECORDED,
            activity=activity,
            evidence_ref=evidence_ref,
            next_known_action=next_known_action,
        )

    def heartbeat(self, activity: str = "Worker alive") -> ProgressEvent:
        return self._emit(kind=ProgressEventKind.HEARTBEAT, activity=activity)

    def waiting(
        self,
        waiting_on: str,
        *,
        activity: str,
        next_known_action: str | None = None,
    ) -> ProgressEvent:
        return self._emit(
            kind=ProgressEventKind.WAITING,
            activity=activity,
            waiting_on=waiting_on,
            next_known_action=next_known_action,
        )

    def resumed(self, activity: str, *, next_known_action: str | None = None) -> ProgressEvent:
        return self._emit(
            kind=ProgressEventKind.RESUMED,
            activity=activity,
            next_known_action=next_known_action,
        )

    def blocked(
        self,
        blocker: str,
        *,
        activity: str,
        next_known_action: str | None = None,
    ) -> ProgressEvent:
        return self._emit(
            kind=ProgressEventKind.BLOCKED,
            activity=activity,
            waiting_on=blocker,
            next_known_action=next_known_action,
        )

    def completed(self, activity: str = "Attempt completed") -> ProgressEvent:
        return self._emit(kind=ProgressEventKind.ATTEMPT_COMPLETED, activity=activity)
