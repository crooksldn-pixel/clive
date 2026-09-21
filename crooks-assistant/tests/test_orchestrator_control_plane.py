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
    TaskStatus,
)
from app.orchestrator.policy import evaluate_obvious_continuation
from app.orchestrator.state import build_active_state
from app.orchestrator.store import JsonRecordStore, RecordConflictError, latest_result_by_task_revision


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
        "status": TaskStatus.READY,
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



def test_result_identity_rejects_path_traversal_attempt_id() -> None:
    with pytest.raises(ValidationError):
        make_result(attempt_id="../escape")

    with pytest.raises(ValidationError):
        make_result(attempt_id="nested/attempt")


def test_fresh_remote_head_is_required_before_candidate_continuation() -> None:
    unresolved = evaluate_obvious_continuation(
        make_task(),
        make_result(),
        candidate_worker_id="fresh-review-session",
    )
    assert unresolved.allowed is False
    assert "fresh branch HEAD" in unresolved.reason

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

def test_active_state_refuses_to_invent_missing_branch_truth() -> None:
    with pytest.raises(ValueError, match="missing branch head"):
        build_active_state(
            tasks=[make_task()],
            results=[],
            branch_heads={},
            generated_at=NOW,
        )
