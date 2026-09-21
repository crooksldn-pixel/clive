"""Typed records for the repository-only control-plane foundation.

These records deliberately fail closed:
- unknown fields are rejected;
- SHA identities are exact 40-character hex strings;
- task revision and authority are explicit;
- a model-proposed next action is data, never authority by itself.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _validate_sha(value: str) -> str:
    value = value.lower()
    if not _SHA_RE.fullmatch(value):
        raise ValueError("must be an exact 40-character lowercase Git SHA")
    return value


ExactSha = Annotated[str, Field(min_length=40, max_length=40)]


class TaskKind(StrEnum):
    BUILD = "build"
    REPAIR = "repair"
    REVIEW = "review"
    EVIDENCE = "evidence"
    INTEGRATION = "integration"


class TaskStatus(StrEnum):
    PROPOSED = "proposed"
    READY = "ready"
    ASSIGNED = "assigned"
    RUNNING = "running"
    EVIDENCE_READY = "evidence_ready"
    REVIEWING = "reviewing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    OWNER_GATE = "owner_gate"
    DONE = "done"
    OBSOLETE = "obsolete"
    CANCELLED = "cancelled"


class BlockerClass(StrEnum):
    NONE = "none"
    TRANSIENT = "transient"
    DETERMINISTIC = "deterministic"
    OBSOLETE = "obsolete"
    OWNER_ONLY = "owner_only"


class NextActionKind(StrEnum):
    CONTINUE = "continue"
    REVIEW = "review"
    REPAIR = "repair"
    EVIDENCE = "evidence"
    INTEGRATE = "integrate"
    BLOCKED = "blocked"
    OWNER_GATE = "owner_gate"
    DONE = "done"


class ProgressEventKind(StrEnum):
    ATTEMPT_STARTED = "attempt_started"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    EVIDENCE_RECORDED = "evidence_recorded"
    WAITING = "waiting"
    RESUMED = "resumed"
    BLOCKED = "blocked"
    HEARTBEAT = "heartbeat"
    ATTEMPT_COMPLETED = "attempt_completed"


class ProgressState(StrEnum):
    WORKING = "working"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COMPLETE = "complete"


class ProgressHealth(StrEnum):
    PROGRESSING = "progressing"
    WORKING_NO_RECENT_PROGRESS = "working_no_recent_progress"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    STALE = "stale"


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EngineeringTask(StrictRecord):
    schema_version: Literal["clive.engineering_task.v1"] = "clive.engineering_task.v1"
    task_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    revision: int = Field(ge=1)
    stream_id: str = Field(min_length=1, max_length=120)
    kind: TaskKind
    objective: str = Field(min_length=1)
    repository: str = Field(min_length=3, pattern=r"^[^/\s]+/[^/\s]+$")
    base_sha: ExactSha
    target_branch: str = Field(min_length=1)
    product_memory_sha: ExactSha
    allowed_paths: tuple[str, ...] = ()
    prohibited_actions: tuple[str, ...] = ()
    predecessor_task_ids: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    reviewer_must_be_independent: bool = True
    authorising_reference: str = Field(min_length=1)
    priority: int = Field(default=0, ge=-100, le=100)
    created_at: datetime

    @field_validator("base_sha", "product_memory_sha")
    @classmethod
    def validate_sha(cls, value: str) -> str:
        return _validate_sha(value)

    @field_validator("created_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @field_validator("allowed_paths", "prohibited_actions", "required_evidence")
    @classmethod
    def no_empty_entries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("entries must not be empty")
        return value


class TaskRuntimeState(StrictRecord):
    schema_version: Literal["clive.task_runtime_state.v1"] = "clive.task_runtime_state.v1"
    task_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    task_revision: int = Field(ge=1)
    status: TaskStatus
    transition_seq: int = Field(ge=0)
    attempt_id: str | None = Field(
        default=None,
        max_length=120,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    worker_id: str | None = Field(default=None, max_length=200)
    blocker_class: BlockerClass = BlockerClass.NONE
    blocker_reason: str | None = None
    owner_gate: bool = False
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def blocker_fields_are_consistent(self) -> "TaskRuntimeState":
        if self.blocker_class is BlockerClass.NONE and self.blocker_reason is not None:
            raise ValueError("blocker_reason requires a non-none blocker_class")
        if self.blocker_class is not BlockerClass.NONE and not self.blocker_reason:
            raise ValueError("non-none blocker_class requires blocker_reason")
        if self.blocker_class is BlockerClass.OWNER_ONLY and not self.owner_gate:
            raise ValueError("owner_only blocker requires owner_gate=true")
        return self


class WorkerProfile(StrictRecord):
    worker_id: str = Field(min_length=1, max_length=200)
    roles: tuple[str, ...] = ()
    available: bool = True

    @field_validator("roles")
    @classmethod
    def roles_are_nonempty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not role.strip() for role in value):
            raise ValueError("worker roles must not be empty")
        return value


class ProgressEvent(StrictRecord):
    schema_version: Literal["clive.progress_event.v1"] = "clive.progress_event.v1"
    task_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    worker_id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=0)
    kind: ProgressEventKind
    occurred_at: datetime
    activity: str = Field(min_length=1, max_length=500)
    step_id: str | None = Field(
        default=None,
        max_length=120,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    step_label: str | None = Field(default=None, max_length=300)
    evidence_ref: str | None = Field(default=None, max_length=500)
    waiting_on: str | None = Field(default=None, max_length=500)
    next_known_action: str | None = Field(default=None, max_length=500)
    subject_sha: ExactSha | None = None

    @field_validator("occurred_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @field_validator("subject_sha")
    @classmethod
    def validate_optional_sha(cls, value: str | None) -> str | None:
        return None if value is None else _validate_sha(value)

    @model_validator(mode="after")
    def kind_specific_fields_are_consistent(self) -> "ProgressEvent":
        if self.kind in {ProgressEventKind.STEP_STARTED, ProgressEventKind.STEP_COMPLETED}:
            if not self.step_id or not self.step_label:
                raise ValueError("step events require step_id and step_label")
        if self.kind is ProgressEventKind.EVIDENCE_RECORDED and not self.evidence_ref:
            raise ValueError("evidence_recorded requires evidence_ref")
        if self.kind is ProgressEventKind.WAITING and not self.waiting_on:
            raise ValueError("waiting requires waiting_on")
        return self


class ProgressSnapshot(StrictRecord):
    schema_version: Literal["clive.progress_snapshot.v1"] = "clive.progress_snapshot.v1"
    stream_id: str = Field(min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=120)
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120)
    worker_id: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1)
    state: ProgressState
    current_activity: str = Field(min_length=1, max_length=500)
    active_step_id: str | None = None
    active_step_label: str | None = None
    completed_steps: tuple[str, ...] = ()
    completed_step_labels: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    waiting_on: str | None = None
    next_known_action: str | None = None
    last_event_at: datetime
    last_activity_change_at: datetime
    last_meaningful_progress_at: datetime
    last_heartbeat_at: datetime | None = None

    @field_validator(
        "last_event_at",
        "last_activity_change_at",
        "last_meaningful_progress_at",
        "last_heartbeat_at",
    )
    @classmethod
    def timestamps_timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class NextAction(StrictRecord):
    kind: NextActionKind
    reason: str = Field(min_length=1)
    subject_sha: ExactSha | None = None
    mechanically_authorised: bool = False
    required_role: str | None = None
    required_reviewer_independence: bool = False
    remaining_evidence: tuple[str, ...] = ()

    @field_validator("subject_sha")
    @classmethod
    def validate_optional_sha(cls, value: str | None) -> str | None:
        return None if value is None else _validate_sha(value)

    @model_validator(mode="after")
    def subject_required_for_candidate_actions(self) -> "NextAction":
        if self.kind in {
            NextActionKind.REVIEW,
            NextActionKind.REPAIR,
            NextActionKind.EVIDENCE,
            NextActionKind.INTEGRATE,
        } and self.subject_sha is None:
            raise ValueError(f"{self.kind.value} requires subject_sha")
        return self


class EngineeringResult(StrictRecord):
    schema_version: Literal["clive.engineering_result.v1"] = "clive.engineering_result.v1"
    task_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    worker_id: str = Field(min_length=1, max_length=200)
    base_sha: ExactSha
    result_sha: ExactSha | None = None
    changed_paths: tuple[str, ...] = ()
    evidence_satisfied: tuple[str, ...] = ()
    clean_worktree: bool
    runtime_effects: Literal["none"] = "none"
    blocker_class: BlockerClass = BlockerClass.NONE
    blocker_reason: str | None = None
    owner_decision_required: bool = False
    next_action: NextAction
    completed_at: datetime

    @field_validator("base_sha", "result_sha")
    @classmethod
    def validate_result_sha(cls, value: str | None) -> str | None:
        return None if value is None else _validate_sha(value)

    @field_validator("completed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def blocker_fields_are_consistent(self) -> "EngineeringResult":
        if self.blocker_class is BlockerClass.NONE and self.blocker_reason is not None:
            raise ValueError("blocker_reason requires a non-none blocker_class")
        if self.blocker_class is not BlockerClass.NONE and not self.blocker_reason:
            raise ValueError("non-none blocker_class requires blocker_reason")
        if self.blocker_class is BlockerClass.OWNER_ONLY and not self.owner_decision_required:
            raise ValueError("owner_only blocker requires owner_decision_required=true")
        return self


class StreamState(StrictRecord):
    stream_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    head_sha: ExactSha
    stage: TaskStatus
    task_id: str | None = None
    attempt_id: str | None = None
    worker_id: str | None = None
    blocker_class: BlockerClass = BlockerClass.NONE
    owner_gate: bool = False
    last_transition_at: datetime

    @field_validator("head_sha")
    @classmethod
    def validate_head_sha(cls, value: str) -> str:
        return _validate_sha(value)

    @field_validator("last_transition_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class ActiveState(StrictRecord):
    schema_version: Literal["clive.active_engineering_state.v1"] = (
        "clive.active_engineering_state.v1"
    )
    generated_at: datetime
    streams: tuple[StreamState, ...]
    queue_depth: int = Field(ge=0)
    active_worker_count: int = Field(ge=0)

    @field_validator("generated_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value
