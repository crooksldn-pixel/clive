"""Deterministic engineering control-plane primitives.

Repository-only foundation for Engineering Control Plane VNext.
No runtime watcher/service integration lives in this package.
"""

from .contracts import (
    ActiveState,
    BlockerClass,
    EngineeringResult,
    EngineeringTask,
    NextAction,
    NextActionKind,
    ProgressEvent,
    ProgressEventKind,
    ProgressHealth,
    ProgressSnapshot,
    ProgressState,
    StreamState,
    TaskKind,
    TaskRuntimeState,
    TaskStatus,
    WorkerProfile,
)
from .policy import ContinuationDecision, evaluate_obvious_continuation
from .progress import assess_progress, project_progress, render_progress_table
from .reporter import ProgressReporter
from .supervision import SupervisorAction, SupervisorHint, choose_supervisor_hint
from .scheduler import ContinuationCandidate, DispatchDecision, select_obvious_dispatch
from .state import build_active_state
from .store import (
    JsonRecordStore,
    ProgressSequenceError,
    RecordConflictError,
    StateConflictError,
)

__all__ = [
    "ActiveState",
    "BlockerClass",
    "ContinuationCandidate",
    "ContinuationDecision",
    "DispatchDecision",
    "EngineeringResult",
    "EngineeringTask",
    "NextAction",
    "NextActionKind",
    "ProgressEvent",
    "ProgressEventKind",
    "ProgressHealth",
    "ProgressSnapshot",
    "ProgressState",
    "ProgressReporter",
    "JsonRecordStore",
    "ProgressSequenceError",
    "RecordConflictError",
    "StateConflictError",
    "StreamState",
    "SupervisorAction",
    "SupervisorHint",
    "TaskKind",
    "TaskRuntimeState",
    "TaskStatus",
    "WorkerProfile",
    "assess_progress",
    "build_active_state",
    "choose_supervisor_hint",
    "evaluate_obvious_continuation",
    "project_progress",
    "render_progress_table",
    "select_obvious_dispatch",
]
