"""Supervisory interpretation of structured worker progress.

This module tells a polling supervisor how to use its observation window. It
does not launch workers or widen authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .contracts import ProgressHealth, ProgressSnapshot
from .progress import assess_progress


class SupervisorAction(StrEnum):
    ADVANCE_COMPLETED = "advance_completed"
    OBSERVE = "observe"
    SCHEDULE_AROUND = "schedule_around"
    INVESTIGATE_NO_PROGRESS = "investigate_no_progress"
    RECONCILE_STALE = "reconcile_stale"
    PARK_BLOCKED = "park_blocked"


@dataclass(frozen=True, slots=True)
class SupervisorHint:
    action: SupervisorAction
    reason: str
    may_schedule_unrelated_work: bool
    must_not_duplicate_current_attempt: bool = True


def choose_supervisor_hint(
    snapshot: ProgressSnapshot,
    *,
    now: datetime,
    other_eligible_work_exists: bool,
    spare_worker_capacity: bool,
) -> SupervisorHint:
    health = assess_progress(snapshot, now=now)

    if health is ProgressHealth.COMPLETE:
        return SupervisorHint(
            SupervisorAction.ADVANCE_COMPLETED,
            "attempt is complete; evaluate its result/next_action immediately",
            may_schedule_unrelated_work=spare_worker_capacity and other_eligible_work_exists,
        )

    if health is ProgressHealth.STALE:
        return SupervisorHint(
            SupervisorAction.RECONCILE_STALE,
            "liveness is stale; reconcile process/worktree/result identity before any retry",
            may_schedule_unrelated_work=spare_worker_capacity and other_eligible_work_exists,
        )

    if health is ProgressHealth.WORKING_NO_RECENT_PROGRESS:
        return SupervisorHint(
            SupervisorAction.INVESTIGATE_NO_PROGRESS,
            "worker is alive but has not produced meaningful progress recently; inspect progress/log evidence without restarting it",
            may_schedule_unrelated_work=spare_worker_capacity and other_eligible_work_exists,
        )

    if health is ProgressHealth.BLOCKED:
        return SupervisorHint(
            SupervisorAction.PARK_BLOCKED,
            "current attempt is blocked; park this stream until its blocker changes",
            may_schedule_unrelated_work=spare_worker_capacity and other_eligible_work_exists,
        )

    if health is ProgressHealth.WAITING:
        if spare_worker_capacity and other_eligible_work_exists:
            return SupervisorHint(
                SupervisorAction.SCHEDULE_AROUND,
                "current attempt is waiting; use spare capacity for other eligible work",
                may_schedule_unrelated_work=True,
            )
        return SupervisorHint(
            SupervisorAction.OBSERVE,
            "current attempt is waiting and no safe spare-capacity work is available",
            may_schedule_unrelated_work=False,
        )

    if spare_worker_capacity and other_eligible_work_exists:
        return SupervisorHint(
            SupervisorAction.SCHEDULE_AROUND,
            "current attempt is progressing; leave it intact and use spare capacity elsewhere",
            may_schedule_unrelated_work=True,
        )

    return SupervisorHint(
        SupervisorAction.OBSERVE,
        "current attempt is progressing; no additional safe work is currently schedulable",
        may_schedule_unrelated_work=False,
    )
