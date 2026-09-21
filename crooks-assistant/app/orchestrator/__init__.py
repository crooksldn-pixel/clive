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
    StreamState,
    TaskKind,
    TaskRuntimeState,
    TaskStatus,
    WorkerProfile,
)
from .policy import ContinuationDecision, evaluate_obvious_continuation
from .scheduler import ContinuationCandidate, DispatchDecision, select_obvious_dispatch
from .state import build_active_state
from .store import JsonRecordStore, RecordConflictError, StateConflictError

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
    "JsonRecordStore",
    "RecordConflictError",
    "StateConflictError",
    "StreamState",
    "TaskKind",
    "TaskRuntimeState",
    "TaskStatus",
    "WorkerProfile",
    "build_active_state",
    "evaluate_obvious_continuation",
    "select_obvious_dispatch",
]
