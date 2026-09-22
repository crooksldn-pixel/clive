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
from .routing import (
    Ineligibility,
    Party,
    Principal,
    PrincipalKind,
    ReviewAssignment,
    ReviewEligibility,
    SessionContext,
    Workspace,
    evaluate_review_eligibility,
    select_eligible_reviewer,
)
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
    "Ineligibility",
    "NextAction",
    "NextActionKind",
    "JsonRecordStore",
    "Party",
    "Principal",
    "PrincipalKind",
    "RecordConflictError",
    "ReviewAssignment",
    "ReviewEligibility",
    "SessionContext",
    "StateConflictError",
    "StreamState",
    "TaskKind",
    "TaskRuntimeState",
    "TaskStatus",
    "WorkerProfile",
    "Workspace",
    "build_active_state",
    "evaluate_obvious_continuation",
    "evaluate_review_eligibility",
    "select_eligible_reviewer",
    "select_obvious_dispatch",
]
