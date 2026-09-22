from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.orchestrator.contracts import (
    BlockerClass,
    EngineeringResult,
    EngineeringTask,
    NextAction,
    NextActionKind,
    TaskKind,
    TaskRuntimeState,
    TaskStatus,
    WorkerProfile,
)
from app.orchestrator.policy import evaluate_obvious_continuation
from app.orchestrator.scheduler import ContinuationCandidate, select_obvious_dispatch
from app.orchestrator.state import build_active_state
from app.orchestrator.store import (
    JsonRecordStore,
    RecordConflictError,
    StateConflictError,
    latest_result_by_task_revision,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
NOW = datetime(2026, 9, 21, 9, 30, tzinfo=UTC)


def make_task(**overrides) -> EngineeringTask:
    data = {
        "task_id": "freeze-repair-008",
        "revision": 1,
        "stream_id": "stream-a",
        "kind": TaskKind.REPAIR,
        "objective": "Repair one bounded evaluator defect",
        "repository": "crooksldn-pixel/clive",
        "base_sha": SHA_A,
        "target_branch": "chatgpt/orchestrator-v1-freeze-candidate-2026-09-20",
        "product_memory_sha": SHA_C,
        "allowed_paths": ("crooks-assistant/tests",),
        "prohibited_actions": ("deployment", "business_write"),
        "required_evidence": ("pytest", "secret_scan"),
        "reviewer_must_be_independent": True,
        "authorising_reference": "DEC-054",
        "created_at": NOW,
    }
    data.update(overrides)
    return EngineeringTask(**data)


def make_result(**overrides) -> EngineeringResult:
    data = {
        "task_id": "freeze-repair-008",
        "task_revision": 1,
        "attempt_id": "attempt-1",
        "worker_id": "claude-builder-1",
        "base_sha": SHA_A,
        "result_sha": SHA_B,
        "changed_paths": ("crooks-assistant/tests/test_orchestrator_freeze_spec.py",),
        "evidence_satisfied": ("pytest", "secret_scan"),
        "clean_worktree": True,
        "runtime_effects": "none",
        "blocker_class": BlockerClass.NONE,
        "owner_decision_required": False,
        "next_action": NextAction(
            kind=NextActionKind.REVIEW,
            reason="bounded repair complete; exact SHA requires fresh review",
            subject_sha=SHA_B,
            mechanically_authorised=True,
            required_role="independent-reviewer",
            required_reviewer_independence=True,
        ),
        "completed_at": NOW + timedelta(minutes=10),
    }
    data.update(overrides)
    return EngineeringResult(**data)


def test_exact_sha_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(ValidationError):
        make_task(base_sha="abc")

    task = make_task()
    payload = task.model_dump()
    payload["surprise"] = "silent widening"
    with pytest.raises(ValidationError):
        EngineeringTask.model_validate(payload)


def test_candidate_actions_require_exact_subject_sha() -> None:
    with pytest.raises(ValidationError):
        NextAction(
            kind=NextActionKind.REVIEW,
            reason="review it",
            mechanically_authorised=True,
        )


def test_bounded_repair_can_flow_directly_to_independent_review() -> None:
    decision = evaluate_obvious_continuation(
        make_task(),
        make_result(),
        candidate_worker_id="claude-reviewer-2",
        current_branch_head=SHA_B,
    )
    assert decision.allowed is True
    assert "same authorised bounded workflow" in decision.reason


def test_author_cannot_satisfy_independent_review() -> None:
    decision = evaluate_obvious_continuation(
        make_task(),
        make_result(),
        candidate_worker_id="claude-builder-1",
        current_branch_head=SHA_B,
    )
    assert decision.allowed is False
    assert "cannot satisfy independent review" in decision.reason


def test_review_waits_only_for_reviewer_resolution_not_hourly_owner_poll() -> None:
    unresolved = evaluate_obvious_continuation(
        make_task(), make_result(), current_branch_head=SHA_B
    )
    assert unresolved.allowed is False
    assert "reviewer identity" in unresolved.reason

    resolved = evaluate_obvious_continuation(
        make_task(),
        make_result(),
        candidate_worker_id="fresh-review-session",
        current_branch_head=SHA_B,
    )
    assert resolved.allowed is True


def test_stale_subject_sha_cannot_continue() -> None:
    result = make_result(
        next_action=NextAction(
            kind=NextActionKind.REVIEW,
            reason="wrong subject",
            subject_sha=SHA_C,
            mechanically_authorised=True,
            required_reviewer_independence=True,
        )
    )
    decision = evaluate_obvious_continuation(
        make_task(),
        result,
        candidate_worker_id="fresh-review-session",
        current_branch_head=SHA_B,
    )
    assert decision.allowed is False
    assert "stale or mismatched" in decision.reason


def test_result_from_wrong_task_revision_or_base_cannot_continue() -> None:
    wrong_revision = make_result(task_revision=2)
    assert evaluate_obvious_continuation(
        make_task(), wrong_revision, candidate_worker_id="reviewer", current_branch_head=SHA_B
    ).allowed is False

    wrong_base = make_result(base_sha=SHA_C)
    assert evaluate_obvious_continuation(
        make_task(), wrong_base, candidate_worker_id="reviewer", current_branch_head=SHA_B
    ).allowed is False


def test_out_of_scope_changed_path_fails_closed() -> None:
    result = make_result(changed_paths=("crooks-assistant/app/main.py",))
    decision = evaluate_obvious_continuation(
        make_task(),
        result,
        candidate_worker_id="fresh-review-session",
        current_branch_head=SHA_B,
    )
    assert decision.allowed is False
    assert "outside task scope" in decision.reason


def test_scope_match_is_a_path_boundary_not_a_string_prefix() -> None:
    """A sibling directory sharing a scope's name prefix is out of scope.

    ``crooks-assistant/application`` merely *starts with* ``crooks-assistant/app``.
    Matching on the raw string prefix would let it through; the boundary-aware
    match requires the allowed path to be the whole path or a real parent of it.
    """

    task = make_task(allowed_paths=("crooks-assistant/app",))

    sibling = evaluate_obvious_continuation(
        task,
        make_result(changed_paths=("crooks-assistant/application/secrets.py",)),
        candidate_worker_id="fresh-review-session",
        current_branch_head=SHA_B,
    )
    assert sibling.allowed is False
    assert "outside task scope" in sibling.reason
    assert "crooks-assistant/application/secrets.py" in sibling.reason

    # Load-bearing control: the scope itself, and paths genuinely inside it,
    # still pass — so the denial above is the boundary rule, not a broken scope.
    inside = evaluate_obvious_continuation(
        task,
        make_result(changed_paths=("crooks-assistant/app", "crooks-assistant/app/main.py")),
        candidate_worker_id="fresh-review-session",
        current_branch_head=SHA_B,
    )
    assert inside.allowed is True


def test_missing_required_evidence_blocks_review_but_allows_evidence_stage() -> None:
    missing = make_result(evidence_satisfied=("pytest",))
    review = evaluate_obvious_continuation(
        make_task(),
        missing,
        candidate_worker_id="fresh-review-session",
        current_branch_head=SHA_B,
    )
    assert review.allowed is False
    assert "required evidence remains incomplete" in review.reason

    evidence = make_result(
        evidence_satisfied=("pytest",),
        next_action=NextAction(
            kind=NextActionKind.EVIDENCE,
            reason="secret scan remains",
            subject_sha=SHA_B,
            mechanically_authorised=True,
            remaining_evidence=("secret_scan",),
        ),
    )
    decision = evaluate_obvious_continuation(
        make_task(), evidence, current_branch_head=SHA_B
    )
    assert decision.allowed is True


def test_owner_gate_and_deterministic_blocker_never_auto_continue() -> None:
    owner_gate = make_result(
        blocker_class=BlockerClass.OWNER_ONLY,
        blocker_reason="deployment authority required",
        owner_decision_required=True,
        next_action=NextAction(
            kind=NextActionKind.OWNER_GATE,
            reason="owner must approve deployment",
            mechanically_authorised=False,
        ),
    )
    assert evaluate_obvious_continuation(make_task(), owner_gate).allowed is False

    deterministic = make_result(
        blocker_class=BlockerClass.DETERMINISTIC,
        blocker_reason="workspace is dirty",
        next_action=NextAction(
            kind=NextActionKind.BLOCKED,
            reason="clean workspace required",
            mechanically_authorised=False,
        ),
    )
    assert evaluate_obvious_continuation(make_task(), deterministic).allowed is False


def test_done_is_terminal_not_an_excuse_to_invent_more_work() -> None:
    done = make_result(
        next_action=NextAction(
            kind=NextActionKind.DONE,
            reason="bounded objective is complete",
            mechanically_authorised=True,
        )
    )
    decision = evaluate_obvious_continuation(make_task(), done)
    assert decision.allowed is False
    assert "terminal/gated" in decision.reason



def test_record_identities_reject_path_traversal_components() -> None:
    for bad in ("..", ".", "../escape", "nested/attempt"):
        with pytest.raises(ValidationError):
            make_result(attempt_id=bad)

    for bad in ("..", "."):
        with pytest.raises(ValidationError):
            make_result(task_id=bad)
        with pytest.raises(ValidationError):
            make_task(task_id=bad)
        with pytest.raises(ValidationError):
            TaskRuntimeState(
                task_id=bad,
                task_revision=1,
                status=TaskStatus.READY,
                transition_seq=0,
                updated_at=NOW,
            )


def test_changed_paths_reject_traversal_and_require_result_sha() -> None:
    for bad in (
        "crooks-assistant/tests/../app/main.py",
        "crooks-assistant/tests/../../../../etc/passwd",
        "/absolute/path.py",
        "crooks-assistant\\tests\\file.py",
    ):
        with pytest.raises(ValidationError):
            make_result(changed_paths=(bad,))

    with pytest.raises(ValidationError):
        make_result(
            result_sha=None,
            changed_paths=("crooks-assistant/tests/test_safe.py",),
            next_action=NextAction(
                kind=NextActionKind.CONTINUE,
                reason="continue after edit",
                mechanically_authorised=True,
            ),
        )


def test_fresh_remote_head_is_required_before_candidate_continuation() -> None:
    unresolved = evaluate_obvious_continuation(
        make_task(),
        make_result(),
        candidate_worker_id="fresh-review-session",
    )
    assert unresolved.allowed is False
    assert "fresh branch HEAD" in unresolved.reason

    malformed = evaluate_obvious_continuation(
        make_task(),
        make_result(),
        candidate_worker_id="fresh-review-session",
        current_branch_head="not-a-sha",
    )
    assert malformed.allowed is False
    assert "not an exact Git SHA" in malformed.reason

    moved = evaluate_obvious_continuation(
        make_task(),
        make_result(),
        candidate_worker_id="fresh-review-session",
        current_branch_head=SHA_C,
    )
    assert moved.allowed is False
    assert "current branch HEAD differs" in moved.reason


def test_worker_cannot_invent_invalid_next_stage_for_task_kind() -> None:
    review_task = make_task(kind=TaskKind.REVIEW)
    looping_review = make_result(
        next_action=NextAction(
            kind=NextActionKind.REVIEW,
            reason="review myself again",
            subject_sha=SHA_B,
            mechanically_authorised=True,
            required_reviewer_independence=True,
        )
    )
    decision = evaluate_obvious_continuation(
        review_task,
        looping_review,
        candidate_worker_id="fresh-review-session",
        current_branch_head=SHA_B,
    )
    assert decision.allowed is False
    assert "not a valid next stage" in decision.reason


def test_branch_movement_after_result_blocks_otherwise_valid_review() -> None:
    decision = evaluate_obvious_continuation(
        make_task(),
        make_result(),
        candidate_worker_id="fresh-review-session",
        current_branch_head=SHA_C,
    )
    assert decision.allowed is False
    assert "current branch HEAD differs" in decision.reason

def test_record_store_is_idempotent_but_rejects_identity_reuse(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    task = make_task()

    first = store.put_task(task)
    second = store.put_task(task)
    assert first == second
    assert len(store.read_tasks()) == 1

    conflicting = make_task(objective="Different objective under the same immutable revision")
    with pytest.raises(RecordConflictError):
        store.put_task(conflicting)


def test_result_publication_is_idempotent_and_round_trips(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    result = make_result()

    store.put_result(result)
    store.put_result(result)

    loaded = store.read_results()
    assert loaded == (result,)



def test_runtime_state_compare_and_swap_rejects_stale_writer(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    initial = TaskRuntimeState(
        task_id="freeze-repair-008",
        task_revision=1,
        status=TaskStatus.READY,
        transition_seq=0,
        updated_at=NOW,
    )
    store.write_task_state(initial, expected_previous_seq=None)

    running = TaskRuntimeState(
        task_id="freeze-repair-008",
        task_revision=1,
        status=TaskStatus.RUNNING,
        transition_seq=1,
        attempt_id="attempt-1",
        worker_id="claude-builder-1",
        updated_at=NOW + timedelta(seconds=1),
    )
    store.write_task_state(running, expected_previous_seq=0)
    assert store.read_task_states() == (running,)

    # transition_seq=2 is a valid increment. Only the stale expected_previous_seq
    # should reject this write; deleting the CAS comparison must make this test fail.
    stale_but_well_formed = TaskRuntimeState(
        task_id="freeze-repair-008",
        task_revision=1,
        status=TaskStatus.BLOCKED,
        transition_seq=2,
        blocker_class=BlockerClass.DETERMINISTIC,
        blocker_reason="stale writer should not win",
        updated_at=NOW + timedelta(seconds=2),
    )
    with pytest.raises(StateConflictError, match="stale task state"):
        store.write_task_state(stale_but_well_formed, expected_previous_seq=0)


def test_runtime_state_initial_sequence_must_start_at_zero(tmp_path) -> None:
    store = JsonRecordStore(tmp_path)
    invalid = TaskRuntimeState(
        task_id="freeze-repair-008",
        task_revision=1,
        status=TaskStatus.READY,
        transition_seq=2,
        updated_at=NOW,
    )
    with pytest.raises(StateConflictError):
        store.write_task_state(invalid, expected_previous_seq=None)


def test_scheduler_dispatches_obvious_review_without_hourly_poll() -> None:
    candidate = ContinuationCandidate(
        task=make_task(),
        result=make_result(),
        current_branch_head=SHA_B,
    )
    workers = [
        WorkerProfile(worker_id="claude-builder-1", roles=("builder",)),
        WorkerProfile(
            worker_id="claude-reviewer-2",
            roles=("independent-reviewer",),
        ),
    ]
    dispatch = select_obvious_dispatch(candidates=[candidate], workers=workers)
    assert dispatch is not None
    assert dispatch.worker_id == "claude-reviewer-2"
    assert dispatch.action is NextActionKind.REVIEW
    assert dispatch.subject_sha == SHA_B


def test_scheduler_skips_policy_denied_stream_instead_of_starving_other_stream() -> None:
    denied_first = ContinuationCandidate(
        task=make_task(
            task_id="a-denied",
            stream_id="stream-a",
            kind=TaskKind.EVIDENCE,
            priority=10,
            required_evidence=("pytest",),
        ),
        result=make_result(
            task_id="a-denied",
            clean_worktree=False,
            evidence_satisfied=("pytest",),
            next_action=NextAction(
                kind=NextActionKind.CONTINUE,
                reason="would continue if policy allowed it",
                mechanically_authorised=True,
                required_role="builder",
            ),
        ),
        current_branch_head=SHA_B,
        stream_last_dispatched_at=None,
    )
    useful_second = ContinuationCandidate(
        task=make_task(
            task_id="b-evidence",
            stream_id="stream-b",
            kind=TaskKind.EVIDENCE,
            required_evidence=("pytest", "secret_scan"),
        ),
        result=make_result(
            task_id="b-evidence",
            evidence_satisfied=("pytest",),
            next_action=NextAction(
                kind=NextActionKind.EVIDENCE,
                reason="finish the already-required evidence",
                subject_sha=SHA_B,
                mechanically_authorised=True,
                required_role="builder",
                remaining_evidence=("secret_scan",),
            ),
        ),
        current_branch_head=SHA_B,
        stream_last_dispatched_at=NOW,
    )
    workers = [WorkerProfile(worker_id="builder-2", roles=("builder",))]
    dispatch = select_obvious_dispatch(
        candidates=[denied_first, useful_second],
        workers=workers,
    )
    assert dispatch is not None
    assert dispatch.stream_id == "stream-b"
    assert dispatch.task_id == "b-evidence"



def test_scheduler_respects_controller_owned_owner_gate() -> None:
    task = make_task(task_id="owner-gated", stream_id="stream-a")
    runtime = TaskRuntimeState(
        task_id=task.task_id,
        task_revision=task.revision,
        status=TaskStatus.OWNER_GATE,
        transition_seq=3,
        blocker_class=BlockerClass.OWNER_ONLY,
        blocker_reason="owner paused this stream",
        owner_gate=True,
        updated_at=NOW + timedelta(minutes=11),
    )
    candidate = ContinuationCandidate(
        task=task,
        result=make_result(task_id=task.task_id),
        current_branch_head=SHA_B,
        runtime_state=runtime,
        latest_task_revision=task.revision,
    )
    dispatch = select_obvious_dispatch(
        candidates=[candidate],
        workers=[WorkerProfile(worker_id="reviewer-1", roles=("independent-reviewer",))],
    )
    assert dispatch is None


def _controller_dispatch(runtime: TaskRuntimeState, task: EngineeringTask):
    candidate = ContinuationCandidate(
        task=task,
        result=make_result(task_id=task.task_id),
        current_branch_head=SHA_B,
        runtime_state=runtime,
        latest_task_revision=task.revision,
    )
    return select_obvious_dispatch(
        candidates=[candidate],
        workers=[WorkerProfile(worker_id="reviewer-1", roles=("independent-reviewer",))],
    )


def test_owner_gate_alone_stops_an_otherwise_dispatchable_task() -> None:
    """``owner_gate`` must block on its own, with no other hostile signal.

    Status is dispatchable and the blocker class is NONE, so the only thing
    standing between this task and a worker is the owner's gate.
    """

    task = make_task(task_id="owner-gate-only", stream_id="stream-a")
    gated = TaskRuntimeState(
        task_id=task.task_id,
        task_revision=task.revision,
        status=TaskStatus.EVIDENCE_READY,
        transition_seq=3,
        blocker_class=BlockerClass.NONE,
        owner_gate=True,
        updated_at=NOW + timedelta(minutes=11),
    )
    assert _controller_dispatch(gated, task) is None

    # Load-bearing control: lower the gate and nothing else, and the very same
    # task dispatches — so the refusal above is the owner_gate guard alone.
    ungated = gated.model_copy(update={"owner_gate": False})
    assert _controller_dispatch(ungated, task) is not None


def test_deterministic_blocker_alone_stops_an_otherwise_dispatchable_task() -> None:
    """``blocker_class`` must block on its own, with no owner gate and no
    undispatchable status to hide behind."""

    task = make_task(task_id="blocker-only", stream_id="stream-a")
    blocked = TaskRuntimeState(
        task_id=task.task_id,
        task_revision=task.revision,
        status=TaskStatus.EVIDENCE_READY,
        transition_seq=3,
        blocker_class=BlockerClass.DETERMINISTIC,
        blocker_reason="controller recorded a reproducible failure",
        owner_gate=False,
        updated_at=NOW + timedelta(minutes=11),
    )
    assert _controller_dispatch(blocked, task) is None

    # Load-bearing control: clear the blocker and nothing else, and the very
    # same task dispatches — so the refusal above is the blocker_class guard.
    cleared = blocked.model_copy(
        update={"blocker_class": BlockerClass.NONE, "blocker_reason": None}
    )
    assert _controller_dispatch(cleared, task) is not None


UNDISPATCHABLE_STATUSES = (
    TaskStatus.OWNER_GATE,
    TaskStatus.BLOCKED,
    TaskStatus.OBSOLETE,
    TaskStatus.CANCELLED,
    TaskStatus.DONE,
    TaskStatus.ASSIGNED,
    TaskStatus.RUNNING,
    TaskStatus.REVIEWING,
)


@pytest.mark.parametrize("status", UNDISPATCHABLE_STATUSES, ids=lambda s: s.value)
def test_undispatchable_status_alone_stops_an_otherwise_dispatchable_task(
    status: TaskStatus,
) -> None:
    """``status`` must block on its own, the way ``owner_gate`` and
    ``blocker_class`` already do.

    Until this test existed the status guard was the one signal nothing stood
    on: every case that reached it had an owner gate or a blocker to be refused
    for first, so deleting the guard outright left the suite green. Here the
    gate is down, the blocker class is NONE, and the controller's recorded
    status is the only thing in the way.

    ``OWNER_GATE`` is included deliberately: the contract lets that status sit
    on a state whose ``owner_gate`` flag is false — only an ``OWNER_ONLY``
    blocker forces the flag — so the status alone has to be enough.
    """

    task = make_task(task_id="status-only", stream_id="stream-a")
    runtime = TaskRuntimeState(
        task_id=task.task_id,
        task_revision=task.revision,
        status=status,
        transition_seq=3,
        blocker_class=BlockerClass.NONE,
        blocker_reason=None,
        owner_gate=False,
        updated_at=NOW + timedelta(minutes=11),
    )
    assert _controller_dispatch(runtime, task) is None

    # The policy must refuse for the status itself, not incidentally.
    decision = evaluate_obvious_continuation(
        task,
        make_result(task_id=task.task_id),
        candidate_worker_id="reviewer-1",
        current_branch_head=SHA_B,
        runtime_state=runtime,
        latest_task_revision=task.revision,
    )
    assert not decision.allowed
    assert status.value in decision.reason

    # Load-bearing control: move the status to a dispatchable one and change
    # nothing else, and the very same task dispatches — so the refusal above
    # is the status guard alone.
    dispatchable = runtime.model_copy(update={"status": TaskStatus.EVIDENCE_READY})
    assert _controller_dispatch(dispatchable, task) is not None


def test_scheduler_rejects_superseded_task_revision() -> None:
    task = make_task(task_id="old-revision", revision=1)
    candidate = ContinuationCandidate(
        task=task,
        result=make_result(task_id=task.task_id, task_revision=1),
        current_branch_head=SHA_B,
        latest_task_revision=2,
    )
    dispatch = select_obvious_dispatch(
        candidates=[candidate],
        workers=[WorkerProfile(worker_id="reviewer-1", roles=("independent-reviewer",))],
    )
    assert dispatch is None

def test_scheduler_fairness_prefers_least_recently_dispatched_equal_priority_stream() -> None:
    worker = WorkerProfile(worker_id="reviewer", roles=("independent-reviewer",))
    recent = ContinuationCandidate(
        task=make_task(task_id="recent", stream_id="stream-a"),
        result=make_result(task_id="recent"),
        current_branch_head=SHA_B,
        stream_last_dispatched_at=NOW,
    )
    waiting = ContinuationCandidate(
        task=make_task(task_id="waiting", stream_id="stream-b"),
        result=make_result(task_id="waiting"),
        current_branch_head=SHA_B,
        stream_last_dispatched_at=NOW - timedelta(hours=1),
    )
    dispatch = select_obvious_dispatch(candidates=[recent, waiting], workers=[worker])
    assert dispatch is not None
    assert dispatch.stream_id == "stream-b"


def test_scheduler_priority_can_override_fairness_deliberately() -> None:
    worker = WorkerProfile(worker_id="reviewer", roles=("independent-reviewer",))
    high = ContinuationCandidate(
        task=make_task(task_id="high", stream_id="stream-a", priority=10),
        result=make_result(task_id="high"),
        current_branch_head=SHA_B,
        stream_last_dispatched_at=NOW,
    )
    low_waiting = ContinuationCandidate(
        task=make_task(task_id="low", stream_id="stream-b", priority=0),
        result=make_result(task_id="low"),
        current_branch_head=SHA_B,
        stream_last_dispatched_at=None,
    )
    dispatch = select_obvious_dispatch(candidates=[low_waiting, high], workers=[worker])
    assert dispatch is not None
    assert dispatch.task_id == "high"

def test_latest_result_uses_revision_then_timestamp_then_attempt_identity() -> None:
    older = make_result(attempt_id="attempt-1", completed_at=NOW)
    newer = make_result(attempt_id="attempt-2", completed_at=NOW + timedelta(seconds=1))
    latest = latest_result_by_task_revision([newer, older])
    assert latest[("freeze-repair-008", 1)] == newer

    tie_a = make_result(attempt_id="attempt-a", completed_at=NOW)
    tie_b = make_result(attempt_id="attempt-b", completed_at=NOW)
    latest = latest_result_by_task_revision([tie_a, tie_b])
    assert latest[("freeze-repair-008", 1)] == tie_b

    late_old_revision = make_result(
        task_revision=1,
        attempt_id="attempt-z",
        completed_at=NOW + timedelta(hours=1),
    )
    current_revision = make_result(
        task_revision=2,
        attempt_id="attempt-current",
        completed_at=NOW + timedelta(minutes=1),
    )
    latest = latest_result_by_task_revision([late_old_revision, current_revision])
    assert latest[("freeze-repair-008", 1)] == late_old_revision
    assert latest[("freeze-repair-008", 2)] == current_revision


def test_active_state_is_generated_from_exact_branch_and_result_state(tmp_path) -> None:
    task = make_task()
    result = make_result()

    state = build_active_state(
        tasks=[task],
        results=[result],
        branch_heads={task.target_branch: SHA_B},
        generated_at=NOW + timedelta(minutes=11),
    )

    assert state.streams[0].head_sha == SHA_B
    assert state.streams[0].stage is TaskStatus.REVIEWING
    assert state.streams[0].worker_id == "claude-builder-1"
    assert state.active_worker_count == 1
    assert state.queue_depth == 0

    store = JsonRecordStore(tmp_path)
    store.write_active_state(state)
    assert store.read_active_state() == state




def test_active_state_uses_runtime_state_when_present() -> None:
    task = make_task()
    result = make_result()
    runtime = TaskRuntimeState(
        task_id=task.task_id,
        task_revision=task.revision,
        status=TaskStatus.RUNNING,
        transition_seq=1,
        attempt_id="attempt-live",
        worker_id="worker-live",
        updated_at=NOW + timedelta(minutes=20),
    )
    state = build_active_state(
        tasks=[task],
        results=[result],
        task_states=[runtime],
        branch_heads={task.target_branch: SHA_B},
        generated_at=NOW + timedelta(minutes=21),
    )
    assert state.streams[0].stage is TaskStatus.RUNNING
    assert state.streams[0].attempt_id == "attempt-live"
    assert state.streams[0].worker_id == "worker-live"

def test_active_state_marks_result_obsolete_if_branch_has_advanced() -> None:
    task = make_task()
    result = make_result()
    state = build_active_state(
        tasks=[task],
        results=[result],
        branch_heads={task.target_branch: SHA_C},
        generated_at=NOW + timedelta(minutes=11),
    )
    assert state.streams[0].stage is TaskStatus.OBSOLETE
    assert state.streams[0].blocker_class is BlockerClass.OBSOLETE


def test_active_state_ignores_late_result_from_old_task_revision() -> None:
    task = make_task(revision=2)
    old = make_result(
        task_revision=1,
        attempt_id="late-old",
        completed_at=NOW + timedelta(hours=1),
    )
    current = make_result(
        task_revision=2,
        attempt_id="current",
        completed_at=NOW + timedelta(minutes=1),
    )
    state = build_active_state(
        tasks=[task],
        results=[old, current],
        branch_heads={task.target_branch: SHA_B},
        generated_at=NOW + timedelta(hours=2),
    )
    assert state.streams[0].attempt_id == "current"
    assert state.streams[0].stage is TaskStatus.REVIEWING


def test_active_state_defaults_contract_only_task_to_ready() -> None:
    task = make_task()
    state = build_active_state(
        tasks=[task],
        results=[],
        branch_heads={task.target_branch: SHA_A},
        generated_at=NOW,
    )
    assert state.streams[0].stage is TaskStatus.READY
    assert state.queue_depth == 1

def test_active_state_refuses_to_invent_missing_branch_truth() -> None:
    with pytest.raises(ValueError, match="missing branch head"):
        build_active_state(
            tasks=[make_task()],
            results=[],
            branch_heads={},
            generated_at=NOW,
        )
