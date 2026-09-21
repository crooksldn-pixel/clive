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
    TaskStatus,
)
from .policy import ContinuationDecision, evaluate_obvious_continuation

__all__ = [
    "ActiveState",
    "BlockerClass",
    "ContinuationDecision",
    "EngineeringResult",
    "EngineeringTask",
    "NextAction",
    "NextActionKind",
    "StreamState",
    "TaskKind",
    "TaskStatus",
    "evaluate_obvious_continuation",
]
