from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.orchestrator.contracts import (
    EngineeringTask,
    ProgressEvent,
    ProgressEventKind,
    ProgressHealth,
    ProgressState,
    TaskKind,
)
from app.orchestrator.progress import assess_progress, project_progress, render_progress_table
from app.orchestrator.store import JsonRecordStore, ProgressSequenceError, RecordConflictError
from app.orchestrator.supervision import SupervisorAction, choose_supervisor_hint


SHA_A = "a" * 40
SHA_B = "b" * 40
NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


def make_task(**overrides) -> EngineeringTask:
    data = {
        "task_id": "phase1-progress",
        "revision": 1,
        "stream_id": "control-plane",
        "kind": TaskKind.BUILD,
        "objective": "Add observable engineering progress",
        "repository": "crooksldn-pixel/clive",
        "base_sha": SHA_A,
        "target_branch": "chatgpt/control-plane-progress-v1",
        "product_memory_sha": SHA_B,
        "allowed_paths": ("crooks-assistant/app/orchestrator", "crooks-assistant/tests"),
        "required_evidence": ("pytest",),
        "authorising_reference": "DEC-054",
        "created_at": NOW,
    }
    data.update(overrides)
    return EngineeringTask(**data)


def event(
    sequence: int,
    kind: ProgressEventKind,
    activity: str,
    **overrides,
) -> ProgressEvent:
    data = {
        "task_id": "phase1-progress",
        "task_revision": 1,
        "attempt_id": "attempt-1",
        "worker_id": "worker-1",
        "sequence": sequence,
        "kind": kind,
        "occurred_at": NOW + timedelta(minutes=sequence),
        "activity": activity,
        "subject_sha": SHA_A,
    }
    data.update(overrides)
    return ProgressEvent(**data)


def test_progress_stream_must_start_with_attempt_started() -> None:
    with pytest.raises(ValidationError):
        event(0, ProgressEventKind.HEARTBEAT, "alive")

    with pytest.raises(ValidationError):
        event(1, ProgressEventKind.ATTEMPT_STARTED, "started again")


def test_step_evidence_and_waiting_events_require_structured_context() -> None:
    with pytest.raises(ValidationError):
        event(1, ProgressEventKind.STEP_STARTED, "working")

    with pytest.raises(ValidationError):
        event(1, ProgressEventKind.EVIDENCE_RECORDED, "evidence")

    with pytest.raises(ValidationError):
        event(1, ProgressEventKind.WAITING, "waiting")

    with pytest.raises(ValidationError):
        event(1, ProgressEventKind.BLOCKED, "blocked")


def test_progress_store_is_append_only_contiguous_and_idempotent(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    started = event(
        0,
        ProgressEventKind.ATTEMPT_STARTED,
        "Resolving fresh branch truth",
        next_known_action="Inspect contracts",
    )
    step = event(
        1,
        ProgressEventKind.STEP_STARTED,
        "Inspecting contracts",
        step_id="inspect",
        step_label="Inspect current contracts",
    )

    first = store.put_progress_event(started)
    second = store.put_progress_event(started)
    assert first == second

    store.put_progress_event(step)
    assert store.read_progress_events(
        task_id="phase1-progress",
        task_revision=1,
        attempt_id="attempt-1",
    ) == (started, step)

    with pytest.raises(ProgressSequenceError):
        store.put_progress_event(
            event(
                3,
                ProgressEventKind.HEARTBEAT,
                "still alive",
            )
        )


def test_progress_store_rejects_conflicting_replay_and_time_reversal(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    store.put_progress_event(
        event(0, ProgressEventKind.ATTEMPT_STARTED, "Start")
    )

    conflicting = event(
        0,
        ProgressEventKind.ATTEMPT_STARTED,
        "Different content under same immutable event identity",
    )
    with pytest.raises(RecordConflictError):
        store.put_progress_event(conflicting)

    backwards = event(
        1,
        ProgressEventKind.HEARTBEAT,
        "heartbeat",
        occurred_at=NOW - timedelta(seconds=1),
    )
    with pytest.raises(ProgressSequenceError):
        store.put_progress_event(backwards)


def test_completed_attempt_rejects_further_progress(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    store.put_progress_event(event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"))
    store.put_progress_event(event(1, ProgressEventKind.ATTEMPT_COMPLETED, "Done"))

    with pytest.raises(ProgressSequenceError):
        store.put_progress_event(
            event(2, ProgressEventKind.HEARTBEAT, "impossible heartbeat after completion")
        )


def test_projection_exposes_current_work_completed_steps_evidence_and_next() -> None:
    events = [
        event(
            0,
            ProgressEventKind.ATTEMPT_STARTED,
            "Resolving fresh Git truth",
            next_known_action="Inspect progress contracts",
        ),
        event(
            1,
            ProgressEventKind.STEP_STARTED,
            "Inspecting progress contracts",
            step_id="inspect",
            step_label="Inspect progress contracts",
        ),
        event(
            2,
            ProgressEventKind.STEP_COMPLETED,
            "Progress contracts inspected",
            step_id="inspect",
            step_label="Inspect progress contracts",
            next_known_action="Run targeted tests",
        ),
        event(
            3,
            ProgressEventKind.EVIDENCE_RECORDED,
            "Recorded targeted test evidence",
            evidence_ref="pytest:test_orchestrator_progress",
        ),
        event(
            4,
            ProgressEventKind.STEP_STARTED,
            "Running targeted tests",
            step_id="tests",
            step_label="Run targeted tests",
        ),
        event(
            5,
            ProgressEventKind.HEARTBEAT,
            "heartbeat only; do not replace current activity",
        ),
    ]

    snapshot = project_progress(task=make_task(), events=events)

    assert snapshot.state is ProgressState.WORKING
    assert snapshot.current_activity == "Running targeted tests"
    assert snapshot.active_step_id == "tests"
    assert snapshot.completed_steps == ("inspect",)
    assert snapshot.evidence_refs == ("pytest:test_orchestrator_progress",)
    assert snapshot.next_known_action == "Run targeted tests"
    assert snapshot.last_heartbeat_at == NOW + timedelta(minutes=5)


def test_heartbeat_proves_liveness_but_does_not_fake_meaningful_progress() -> None:
    events = [
        event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"),
        event(
            1,
            ProgressEventKind.STEP_STARTED,
            "Long-running adversarial suite",
            step_id="adversarial",
            step_label="Run adversarial suite",
        ),
        event(
            2,
            ProgressEventKind.HEARTBEAT,
            "still alive",
            occurred_at=NOW + timedelta(minutes=50),
        ),
    ]
    snapshot = project_progress(task=make_task(), events=events)

    health = assess_progress(
        snapshot,
        now=NOW + timedelta(minutes=51),
        heartbeat_stale_after=timedelta(minutes=15),
        progress_stall_after=timedelta(minutes=45),
    )
    assert health is ProgressHealth.WORKING_NO_RECENT_PROGRESS


def test_stale_liveness_is_distinct_from_long_running_work() -> None:
    snapshot = project_progress(
        task=make_task(),
        events=[
            event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"),
            event(
                1,
                ProgressEventKind.STEP_STARTED,
                "Working",
                step_id="work",
                step_label="Work",
            ),
        ],
    )
    assert assess_progress(
        snapshot,
        now=NOW + timedelta(minutes=20),
        heartbeat_stale_after=timedelta(minutes=15),
    ) is ProgressHealth.STALE


def test_waiting_and_blocked_state_are_visible_not_flattened_to_running() -> None:
    waiting = project_progress(
        task=make_task(),
        events=[
            event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"),
            event(
                1,
                ProgressEventKind.WAITING,
                "Waiting for independent reviewer",
                waiting_on="independent reviewer",
                next_known_action="Review exact candidate when reviewer is eligible",
            ),
        ],
    )
    assert waiting.state is ProgressState.WAITING
    assert assess_progress(waiting, now=NOW + timedelta(minutes=2)) is ProgressHealth.WAITING

    blocked = project_progress(
        task=make_task(),
        events=[
            event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"),
            event(
                1,
                ProgressEventKind.BLOCKED,
                "Reviewer identity conflict",
                waiting_on="fresh independent reviewer identity",
            ),
        ],
    )
    assert blocked.state is ProgressState.BLOCKED
    assert assess_progress(blocked, now=NOW + timedelta(minutes=2)) is ProgressHealth.BLOCKED


def test_progress_table_shows_useful_operational_context() -> None:
    snapshot = project_progress(
        task=make_task(),
        events=[
            event(0, ProgressEventKind.ATTEMPT_STARTED, "Resolve branch truth"),
            event(
                1,
                ProgressEventKind.STEP_COMPLETED,
                "Branch truth resolved",
                step_id="git",
                step_label="Resolve branch truth",
            ),
            event(
                2,
                ProgressEventKind.STEP_STARTED,
                "Running mutation tests",
                step_id="mutation",
                step_label="Run mutation tests",
                next_known_action="Independent review",
            ),
        ],
    )
    table = render_progress_table([snapshot], now=NOW + timedelta(minutes=3))
    assert "Running mutation tests" in table
    assert "Independent review" in table
    assert "control-plane" in table
    assert "| 1 | 0 |" in table


def test_supervisor_uses_hourly_window_to_schedule_around_progress() -> None:
    snapshot = project_progress(
        task=make_task(),
        events=[
            event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"),
            event(
                1,
                ProgressEventKind.STEP_COMPLETED,
                "Initial inspection complete",
                step_id="inspect",
                step_label="Inspect",
            ),
            event(
                2,
                ProgressEventKind.STEP_STARTED,
                "Running long test suite",
                step_id="tests",
                step_label="Tests",
            ),
            event(
                3,
                ProgressEventKind.HEARTBEAT,
                "alive",
            ),
        ],
    )
    hint = choose_supervisor_hint(
        snapshot,
        now=NOW + timedelta(minutes=4),
        other_eligible_work_exists=True,
        spare_worker_capacity=True,
    )
    assert hint.action is SupervisorAction.SCHEDULE_AROUND
    assert hint.may_schedule_unrelated_work is True
    assert hint.must_not_duplicate_current_attempt is True


def test_supervisor_reconciles_stale_attempt_instead_of_restarting_it() -> None:
    snapshot = project_progress(
        task=make_task(),
        events=[
            event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"),
            event(
                1,
                ProgressEventKind.STEP_STARTED,
                "Working",
                step_id="work",
                step_label="Work",
            ),
        ],
    )
    hint = choose_supervisor_hint(
        snapshot,
        now=NOW + timedelta(minutes=30),
        other_eligible_work_exists=True,
        spare_worker_capacity=True,
    )
    assert hint.action is SupervisorAction.RECONCILE_STALE
    assert hint.must_not_duplicate_current_attempt is True


def test_supervisor_advances_completed_attempt_without_waiting_for_hourly_owner_prompt() -> None:
    snapshot = project_progress(
        task=make_task(),
        events=[
            event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"),
            event(1, ProgressEventKind.ATTEMPT_COMPLETED, "Candidate ready"),
        ],
    )
    hint = choose_supervisor_hint(
        snapshot,
        now=NOW + timedelta(minutes=2),
        other_eligible_work_exists=False,
        spare_worker_capacity=False,
    )
    assert hint.action is SupervisorAction.ADVANCE_COMPLETED
