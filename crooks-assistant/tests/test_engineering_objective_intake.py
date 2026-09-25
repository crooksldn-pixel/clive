"""Objective intake: durable, structured, bounded, and written through the kernel's own lock and journal."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.orchestrator.contracts import TaskKind, TaskStatus
from app.orchestrator.lifecycle import (
    GitFacts,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
)
from app.orchestrator.objectives import (
    DEFAULT_PROHIBITED_ACTIONS,
    Check,
    Objective,
    ObjectiveStore,
    OwnerEntry,
    intake,
)
from app.orchestrator.store import RecordConflictError

REGISTRY = Path(__file__).resolve().parent.parent / "config" / "review_principals.json"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "a.txt").write_text("a\n")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    return root, _git(root, "rev-parse", "HEAD")


def objective(base: str, **overrides) -> Objective:
    fields = dict(
        objective_id="support-queue", title="Support queue",
        requested_outcome="Show unanswered Crooks order enquiries, newest first.",
        acceptance_criteria=("every unanswered thread is listed",),
        checks=(Check(name="tests", argv=("python", "-m", "pytest", "-q"), cwd="crooks-assistant"),),
        repository="crooksldn-pixel/clive", base_ref="main", base_sha=base, target_branch="clive/objective/support-queue",
        product_memory_sha=base, allowed_paths=("crooks-assistant/app/support",),
        owner=OwnerEntry(os_user="george", host="builder"), created_at=NOW,
    )
    fields.update(overrides)
    return Objective(**fields)


def kernel_for(store_root: Path, repo: Path, *, journal: bool = False) -> tuple[Kernel, ObjectiveStore]:
    store = LifecycleStore(store_root)
    kernel = Kernel(store=store, registry=PrincipalRegistry.load(REGISTRY), git=GitFacts(repo), operator="test",
                    journal=journal, clock=lambda: NOW)
    return kernel, ObjectiveStore(store, journal=journal)


def test_intake_records_the_objective_then_task_revision_one(repo, tmp_path):
    root, base = repo
    kernel, objectives = kernel_for(tmp_path / "engineering", root)
    out = intake(objective(base), kernel=kernel, objectives=objectives)
    assert out["stage"] == "ready" and out["task_revision"] == 1
    stored = objectives.read("support-queue")
    assert stored.requested_outcome.startswith("Show unanswered") and stored.authority_class == "repository_only"
    assert stored.owner.origin_verified is False
    task = kernel.store.read_task("support-queue", 1)
    assert task.kind is TaskKind.BUILD and task.base_sha == base and task.allowed_paths == ("crooks-assistant/app/support",)
    assert task.required_evidence == ("worker_report", "worker_transcript", "check-tests")
    assert set(DEFAULT_PROHIBITED_ACTIONS) <= set(task.prohibited_actions)
    assert out["objective_sha256"] in task.authorising_reference and "origin not verified" in task.authorising_reference
    assert kernel.store.read_task_state("support-queue", 1).status is TaskStatus.READY


def test_intake_is_idempotent_and_an_objective_is_immutable(repo, tmp_path):
    root, base = repo
    kernel, objectives = kernel_for(tmp_path / "engineering", root)
    first = intake(objective(base), kernel=kernel, objectives=objectives)
    assert intake(objective(base), kernel=kernel, objectives=objectives) == first
    with pytest.raises(RecordConflictError):
        intake(objective(base, requested_outcome="something else"), kernel=kernel, objectives=objectives)


def test_a_base_that_is_not_a_commit_is_refused_before_anything_is_written(repo, tmp_path):
    root, _ = repo
    kernel, objectives = kernel_for(tmp_path / "engineering", root)
    with pytest.raises(LifecycleError):
        intake(objective("f" * 40), kernel=kernel, objectives=objectives)
    assert objectives.read("support-queue") is None


@pytest.mark.parametrize("path", [
    "crooks-assistant/app/orchestrator/lifecycle.py",
    "crooks-assistant/app/orchestrator",
    "crooks-assistant/config/review_principals.json",
    "crooks-assistant",
    ".github/workflows",
    "engineering",
    "crooks-assistant/app/orchestrator/workers/claude.py",
])
def test_scope_can_never_cover_an_authority_or_runtime_surface(repo, path):
    _, base = repo
    with pytest.raises(ValidationError, match="no objective may put in scope"):
        objective(base, allowed_paths=(path,))


@pytest.mark.parametrize("path", ["", "/etc", "../x", "a/../b", "a//b"])
def test_scope_is_repository_relative_and_bounded(repo, path):
    _, base = repo
    with pytest.raises(ValidationError):
        objective(base, allowed_paths=(path,))


def test_an_unbounded_objective_is_refused(repo):
    _, base = repo
    with pytest.raises(ValidationError):
        objective(base, allowed_paths=())


def test_default_prohibitions_cannot_be_dropped_and_only_repository_authority_exists(repo):
    _, base = repo
    with pytest.raises(ValidationError, match="cannot be removed"):
        objective(base, prohibited_actions=("nothing",))
    with pytest.raises(ValidationError):
        objective(base, authority_class="deploy")
    with pytest.raises(ValidationError):
        Objective(**{**objective(base).model_dump(), "owner": {**objective(base).owner.model_dump(),
                                                               "origin_verified": True}})


def test_unknown_fields_and_unsafe_branches_are_refused(repo):
    _, base = repo
    with pytest.raises(ValidationError):
        Objective(**{**objective(base).model_dump(), "deploy_after": True})
    for branch in ("../main", "-x", "a..b", "main.lock"):
        with pytest.raises(ValidationError):
            objective(base, target_branch=branch)


def test_checks_are_argv_with_a_workspace_relative_cwd(repo):
    _, base = repo
    with pytest.raises(ValidationError):
        Check(name="x", argv=())
    with pytest.raises(ValidationError):
        Check(name="x", argv=("true",), cwd="../outside")
    with pytest.raises(ValidationError, match="unique"):
        objective(base, checks=(Check(name="x", argv=("true",)), Check(name="x", argv=("false",))))


def test_journaled_intake_commits_the_objective_and_the_task_under_the_kernel_lock(repo, tmp_path):
    root, base = repo
    state = tmp_path / "state"
    state.mkdir()
    _git(state, "init", "-q", "-b", "clive/engineering-state")
    _git(state, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root")
    kernel, objectives = kernel_for(state / "engineering", root, journal=True)
    intake(objective(base), kernel=kernel, objectives=objectives)
    log = _git(state, "log", "--format=%an|%s").splitlines()
    assert log[0].startswith("CLIVE kernel|kernel: task support-queue r1 created")
    assert log[1].startswith("CLIVE kernel|objective support-queue entered: Support queue")
    assert _git(state, "status", "--porcelain") == ""
    shown = _git(state, "show", "--name-only", "--format=", "HEAD~1").splitlines()
    assert shown == ["engineering/.kernel.lock", "engineering/objectives/support-queue.json"]


def test_journaled_intake_refuses_a_dirty_store_and_writes_nothing(repo, tmp_path):
    root, base = repo
    state = tmp_path / "state"
    (state / "engineering").mkdir(parents=True)
    _git(state, "init", "-q", "-b", "s")
    _git(state, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root")
    (state / "engineering" / "stray.json").write_text("{}")
    kernel, objectives = kernel_for(state / "engineering", root, journal=True)
    with pytest.raises(LifecycleError, match="uncommitted"):
        intake(objective(base), kernel=kernel, objectives=objectives)
    assert objectives.read("support-queue") is None
