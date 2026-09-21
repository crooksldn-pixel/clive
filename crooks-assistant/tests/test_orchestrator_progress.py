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
    TaskRuntimeState,
    TaskStatus,
)
from app.orchestrator.progress import assess_progress, project_progress, render_progress_table
from app.orchestrator.reporter import ProgressReporter
from app.orchestrator.state import build_active_state
from app.orchestrator.store import JsonRecordStore, ProgressSequenceError, RecordConflictError
from app.orchestrator.supervision import SupervisorAction, choose_supervisor_hint
from scripts.orchestrator_progress import build_snapshots


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



def test_projector_rejects_time_reversal_and_events_after_completion() -> None:
    backwards = [
        event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"),
        event(
            1,
            ProgressEventKind.HEARTBEAT,
            "Earlier heartbeat",
            occurred_at=NOW - timedelta(seconds=1),
        ),
    ]
    with pytest.raises(ValueError, match="time cannot move backwards"):
        project_progress(task=make_task(), events=backwards)

    after_done = [
        event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"),
        event(1, ProgressEventKind.ATTEMPT_COMPLETED, "Done"),
        event(2, ProgressEventKind.HEARTBEAT, "Late heartbeat"),
    ]
    with pytest.raises(ValueError, match="after attempt completion"):
        project_progress(task=make_task(), events=after_done)

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
    assert "Resolve branch truth" in table
    assert "| 0 |" in table




def test_reporter_emits_contiguous_operational_progress_end_to_end(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    task = make_task()
    store.put_task(task)

    times = iter(
        [
            NOW,
            NOW + timedelta(minutes=1),
            NOW + timedelta(minutes=2),
            NOW + timedelta(minutes=3),
            NOW + timedelta(minutes=4),
        ]
    )
    reporter = ProgressReporter(
        store=store,
        task=task,
        attempt_id="attempt-1",
        worker_id="worker-1",
        subject_sha=SHA_A,
        clock=lambda: next(times),
    )

    reporter.start("Resolving fresh Git truth", next_known_action="Inspect contracts")
    reporter.step_started("inspect", "Inspect contracts")
    reporter.step_completed(
        "inspect",
        "Inspect contracts",
        next_known_action="Run tests",
    )
    reporter.evidence(
        "pytest:test_orchestrator_progress",
        activity="Recorded targeted test evidence",
    )
    reporter.step_started(
        "tests",
        "Run tests",
        activity="Running targeted tests",
        next_known_action="Independent review",
    )

    events = store.read_progress_events(
        task_id=task.task_id,
        task_revision=task.revision,
        attempt_id="attempt-1",
    )
    assert [item.sequence for item in events] == [0, 1, 2, 3, 4]

    snapshots = build_snapshots(store)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.current_activity == "Running targeted tests"
    assert snapshot.completed_steps == ("inspect",)
    assert snapshot.evidence_refs == ("pytest:test_orchestrator_progress",)
    assert snapshot.next_known_action == "Independent review"


def test_reporter_rejects_worker_identity_takeover(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    task = make_task()
    store.put_task(task)

    first = ProgressReporter(
        store=store,
        task=task,
        attempt_id="attempt-1",
        worker_id="worker-1",
        clock=lambda: NOW,
    )
    first.start("Start")

    imposter = ProgressReporter(
        store=store,
        task=task,
        attempt_id="attempt-1",
        worker_id="worker-2",
        clock=lambda: NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="different worker"):
        imposter.heartbeat()


def test_progress_view_fails_closed_if_events_have_no_task_contract(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    store.put_progress_event(event(0, ProgressEventKind.ATTEMPT_STARTED, "Start"))

    with pytest.raises(ValueError, match="without immutable task contract"):
        build_snapshots(store)


def test_progress_view_prefers_runtime_current_attempt_over_newer_historical_event(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    task = make_task()
    store.put_task(task)

    current = ProgressEvent(
        task_id=task.task_id,
        task_revision=task.revision,
        attempt_id="attempt-current",
        worker_id="worker-current",
        sequence=0,
        kind=ProgressEventKind.ATTEMPT_STARTED,
        occurred_at=NOW,
        activity="Current attempt",
    )
    historical_but_later = ProgressEvent(
        task_id=task.task_id,
        task_revision=task.revision,
        attempt_id="attempt-old",
        worker_id="worker-old",
        sequence=0,
        kind=ProgressEventKind.ATTEMPT_STARTED,
        occurred_at=NOW + timedelta(minutes=10),
        activity="Late historical event",
    )
    store.put_progress_event(current)
    store.put_progress_event(historical_but_later)
    store.write_task_state(
        TaskRuntimeState(
            task_id=task.task_id,
            task_revision=task.revision,
            status=TaskStatus.RUNNING,
            transition_seq=0,
            attempt_id="attempt-current",
            worker_id="worker-current",
            updated_at=NOW,
        ),
        expected_previous_seq=None,
    )

    snapshots = build_snapshots(store)
    assert len(snapshots) == 1
    assert snapshots[0].attempt_id == "attempt-current"
    assert snapshots[0].current_activity == "Current attempt"

    history = build_snapshots(store, include_history=True)
    assert {snapshot.attempt_id for snapshot in history} == {
        "attempt-current",
        "attempt-old",
    }

def test_active_state_carries_current_attempt_progress_for_hourly_controller() -> None:
    task = make_task()
    events = [
        event(0, ProgressEventKind.ATTEMPT_STARTED, "Resolving Git truth"),
        event(
            1,
            ProgressEventKind.STEP_COMPLETED,
            "Git truth resolved",
            step_id="git",
            step_label="Resolve Git truth",
        ),
        event(
            2,
            ProgressEventKind.EVIDENCE_RECORDED,
            "Recorded branch evidence",
            evidence_ref="git:exact-head",
        ),
        event(
            3,
            ProgressEventKind.STEP_STARTED,
            "Running adversarial tests",
            step_id="tests",
            step_label="Run adversarial tests",
            next_known_action="Independent review",
        ),
    ]
    snapshot = project_progress(task=task, events=events)
    runtime = TaskRuntimeState(
        task_id=task.task_id,
        task_revision=task.revision,
        status=TaskStatus.RUNNING,
        transition_seq=1,
        attempt_id="attempt-1",
        worker_id="worker-1",
        updated_at=NOW + timedelta(minutes=3),
    )

    active = build_active_state(
        tasks=[task],
        results=[],
        task_states=[runtime],
        progress_snapshots=[snapshot],
        branch_heads={task.target_branch: SHA_A},
        generated_at=NOW + timedelta(minutes=4),
    )

    stream = active.streams[0]
    assert stream.progress_health is ProgressHealth.PROGRESSING
    assert stream.current_activity == "Running adversarial tests"
    assert stream.active_step_label == "Run adversarial tests"
    assert stream.completed_step_count == 1
    assert stream.completed_step_labels == ("Resolve Git truth",)
    assert stream.evidence_count == 1
    assert stream.evidence_refs == ("git:exact-head",)
    assert stream.next_known_action == "Independent review"
    assert stream.last_progress_at == NOW + timedelta(minutes=2)


def test_active_state_does_not_attach_progress_from_wrong_attempt() -> None:
    task = make_task()
    snapshot = project_progress(
        task=task,
        events=[event(0, ProgressEventKind.ATTEMPT_STARTED, "Old attempt")],
    )
    runtime = TaskRuntimeState(
        task_id=task.task_id,
        task_revision=task.revision,
        status=TaskStatus.RUNNING,
        transition_seq=1,
        attempt_id="attempt-2",
        worker_id="worker-2",
        updated_at=NOW + timedelta(minutes=1),
    )

    active = build_active_state(
        tasks=[task],
        results=[],
        task_states=[runtime],
        progress_snapshots=[snapshot],
        branch_heads={task.target_branch: SHA_A},
        generated_at=NOW + timedelta(minutes=2),
    )

    stream = active.streams[0]
    assert stream.current_activity is None
    assert stream.progress_health is None
    assert stream.completed_step_count == 0

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
