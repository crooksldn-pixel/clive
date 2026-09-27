"""Owner objective intake: the one door an engineering objective comes in by.

An objective is the owner's intent, persisted as a record before anything acts on
it. The owner's words are kept verbatim as ``requested_outcome``; everything that
decides authority or state (base, scope, prohibited actions, checks, authority
class, limits) is a structured field, never parsed out of prose.

Intake writes two things, in order, and nothing else:

    objectives/<objective_id>.json      the Objective (immutable, this module)
    tasks/<objective_id>.r1.json        the kernel's task revision 1 (``Kernel.create_task``)

The objective lives under the kernel's store root and is written under the
kernel's own writer lock and journal (``LifecycleStore.exclusive_writer``,
``journal_preconditions``, ``git_journal``), so there is one store, one lock and
one git history; the kernel's code is used, not changed. Nothing here launches a
worker: the dispatcher reads what intake wrote.

Owner provenance is recorded as declared, with ``origin_verified: false``. A CLI
run by whoever holds a shell on the host proves the host account, not the owner;
the same limit the kernel states for owner judgments applies here, which is why
an objective can only ever authorise ``repository_only`` work.
"""

from __future__ import annotations

import getpass
import json
import re
import socket
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .contracts import (
    EngineeringTask,
    ExactSha,
    StrictRecord,
    TaskKind,
    validate_exact_sha,
)
from .lifecycle import (
    Kernel,
    LifecycleError,
    LifecycleStore,
    git_journal,
    journal_preconditions,
    sha256_of,
)
from .store import JsonRecordStore, RecordConflictError

__all__ = [
    "Check",
    "DEFAULT_PROHIBITED_ACTIONS",
    "Objective",
    "ObjectiveStore",
    "OwnerEntry",
    "PROTECTED_PATHS",
    "RECORDED",
    "intake",
    "owner_entry_from_host",
    "protected_paths_in",
    "required_evidence_for",
    "task_from_objective",
]

_SAFE_ID = r"^[a-z0-9][a-z0-9.-]{2,79}$"

# Paths no objective may put in scope. Each is an authority or runtime surface the
# dispatcher must never be able to change on its own: the frozen kernel and the
# records it reads, who may review, how CI judges, and anything that installs or
# runs services. The owner changes these by hand, outside this door.
#
# Entries are repository-root relative; a directory entry protects everything beneath
# it (``_overlaps``). The block after ``set_secrets.py`` joined on the owner's loop
# update (OWNER_DECISIONS_2026-09-25.md): the product safety core (the action gate, the
# read-only guard, the Shopify and Gmail write funnels, ``app/actions``), the evidence
# tools (acceptance provenance, the secret-scan rules and baseline, the package and
# test configuration) and the loop's own code (the remote inbox adapter and its CLI,
# and the GitHub acceptance gate); then the tests that hold all of these. CLIVE's own
# engineering bridge joined on 2026-09-27 (the deploy review's F-ENG): it decides what a
# request CLIVE files may name, which checks judge it, which base it starts from and where it
# is written, so a build CLIVE files must not be able to change it for the next one.
PROTECTED_PATHS: tuple[str, ...] = (
    "crooks-assistant/app/orchestrator/lifecycle.py",
    "crooks-assistant/app/orchestrator/contracts.py",
    "crooks-assistant/app/orchestrator/policy.py",
    "crooks-assistant/app/orchestrator/routing.py",
    "crooks-assistant/app/orchestrator/review_acceptance.py",
    "crooks-assistant/app/orchestrator/review_result_gate.py",
    "crooks-assistant/app/orchestrator/store.py",
    "crooks-assistant/app/orchestrator/state.py",
    "crooks-assistant/app/orchestrator/objectives.py",
    "crooks-assistant/app/orchestrator/dispatcher.py",
    "crooks-assistant/app/orchestrator/workspaces.py",
    "crooks-assistant/app/orchestrator/checks.py",
    "crooks-assistant/app/orchestrator/workers",
    "crooks-assistant/app/orchestrator/reviewers",
    "crooks-assistant/scripts/engineering_kernel.py",
    "crooks-assistant/scripts/engineering_dispatcher.py",
    "crooks-assistant/config/review_principals.json",
    "crooks-assistant/config/agent_roster.json",
    "crooks-assistant/launchd",
    "crooks-assistant/scripts/install_launchd.py",
    "crooks-assistant/scripts/set_secrets.py",
    "crooks-assistant/app/tools/gate.py",
    "crooks-assistant/app/readonly.py",
    "crooks-assistant/app/tools/shopify_writes.py",
    "crooks-assistant/app/tools/gmail_writes.py",
    "crooks-assistant/app/actions",
    "crooks-assistant/scripts/acceptance_provenance.py",
    ".gitleaks.toml",
    ".gitleaks-baseline.json",
    "crooks-assistant/pyproject.toml",
    "crooks-assistant/app/remote_engineering",
    "crooks-assistant/scripts/remote_engineering.py",
    "crooks-assistant/app/orchestrator/github_acceptance.py",
    "crooks-assistant/app/engineering_bridge",
    "crooks-assistant/app/tools/engineering_tools.py",
    # The tests that hold the protected code, chosen by what each one imports and exercises (not by
    # a glob over tests/, so an objective may still name any ordinary test file): a builder that
    # cannot change the safety core must not be able to weaken what proves it either. conftest.py
    # is here because its autouse fixtures run inside every one of them.
    "crooks-assistant/tests/conftest.py",
    "crooks-assistant/tests/test_gate.py",                      # app/tools/gate.py
    "crooks-assistant/tests/test_readonly.py",                  # app/readonly.py
    "crooks-assistant/tests/test_cancel.py",                    # app/tools/shopify_writes.py: cancel
    "crooks-assistant/tests/test_refund.py",                    # ... refund
    "crooks-assistant/tests/test_address.py",                   # ... shipping address
    "crooks-assistant/tests/test_fulfil.py",                    # ... fulfilment
    "crooks-assistant/tests/test_inventory.py",                 # ... stock adjustment
    "crooks-assistant/tests/test_tracking.py",                  # ... tracking
    "crooks-assistant/tests/test_order_edit.py",                # ... adding an item
    "crooks-assistant/tests/test_gmail_writes.py",              # app/tools/gmail_writes.py
    "crooks-assistant/tests/test_compose.py",                   # ... a new email to any address
    "crooks-assistant/tests/test_actions.py",                   # app/actions/engine.py, ledger.py, models.py
    "crooks-assistant/tests/test_actions_routes.py",            # ... the action endpoint, the write boundary
    "crooks-assistant/tests/test_engine_hooks.py",              # ... the engine's hooks
    "crooks-assistant/tests/test_batch.py",                     # app/actions/batch.py
    "crooks-assistant/tests/test_available.py",                 # app/actions/available.py
    "crooks-assistant/tests/test_judgment.py",                  # app/actions/judgment.py
    "crooks-assistant/tests/test_judgment_construction.py",     # ...
    "crooks-assistant/tests/test_judgment_chain.py",            # app/actions/judgment_chain.py
    "crooks-assistant/tests/test_judgment_ledger.py",           # app/actions/judgment_ledger.py
    "crooks-assistant/tests/test_acceptance_provenance.py",     # scripts/acceptance_provenance.py
    "crooks-assistant/tests/test_ci_workflow.py",               # .github/workflows/acceptance.yml
    "crooks-assistant/tests/test_lifecycle_kernel.py",          # app/orchestrator/lifecycle.py
    "crooks-assistant/tests/test_orchestrator_control_plane.py",  # contracts, policy, state, store
    "crooks-assistant/tests/test_review_acceptance.py",         # review_acceptance.py
    "crooks-assistant/tests/test_review_result_gate.py",        # review_result_gate.py
    "crooks-assistant/tests/test_review_routing.py",            # routing.py
    "crooks-assistant/tests/test_engineering_objective_intake.py",  # objectives.py
    "crooks-assistant/tests/test_engineering_dispatcher.py",    # dispatcher.py, workspaces.py
    "crooks-assistant/tests/test_engineering_kernel_gate.py",   # scripts/engineering_kernel.py
    "crooks-assistant/tests/test_check_sandbox.py",             # checks.py
    "crooks-assistant/tests/test_builder_check_server.py",      # workers/check_server.py
    "crooks-assistant/tests/test_claude_worker_adapter.py",     # workers/claude.py
    "crooks-assistant/tests/test_gpt_reviewer.py",              # reviewers/gpt.py
    "crooks-assistant/tests/test_remote_engineering.py",        # app/remote_engineering, its CLI
    "crooks-assistant/tests/test_github_acceptance.py",         # github_acceptance.py
    "crooks-assistant/tests/test_engineering_bridge.py",        # app/engineering_bridge, engineering_tools.py
    "crooks-assistant/tests/test_build_from_clive.py",          # ... the base, the checks, the areas
    "crooks-assistant/tests/test_engineering_bridge_bounds.py",  # ... what it can and cannot reach
    ".github",
    "engineering",
)

# ``ObjectiveStore`` reads records with this validation context. An objective recorded
# before a path joined PROTECTED_PATHS must still load, or one old record would stop the
# dispatcher reading any objective at all; the dispatcher then refuses to advance it
# (``protected_paths_in``). Every new objective is validated without it.
RECORDED = {"recorded_objective": True}

DEFAULT_PROHIBITED_ACTIONS: tuple[str, ...] = (
    "deploy, promote to production, restart services or change systemd/launchd/watchers",
    "read, add or change secrets, credentials or tokens",
    "Shopify, Gmail, Stripe or any other business write, or any external send",
    "change reviewer principals, owner authority, permissions or connector/MCP access",
    "pay-as-you-go spend",
    "destructive repository cleanup or history rewriting",
    "change the frozen engineering lifecycle kernel",
)


class Check(StrictRecord):
    """A command CLIVE runs in the candidate workspace; its outcome is evidence CLIVE produced.

    ``argv`` runs without a shell, from ``cwd`` inside the workspace, in the worker's
    sanitised environment. A check passes only on exit status 0.
    """

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    argv: tuple[str, ...] = Field(min_length=1)
    cwd: str = "."
    timeout_s: int = Field(default=900, ge=1, le=7200)

    @field_validator("cwd")
    @classmethod
    def relative_cwd(cls, value: str) -> str:
        if value != "." and (value.startswith("/") or ".." in value.split("/") or "\\" in value):
            raise ValueError("check cwd must be a workspace-relative path without '..'")
        return value


class OwnerEntry(StrictRecord):
    """Who entered the objective, as the host saw it. Declared, never verified."""

    declared_principal: Literal["owner"] = "owner"
    channel: Literal["cli"] = "cli"
    os_user: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=255)
    origin_verified: Literal[False] = False


class Objective(StrictRecord):
    schema_version: Literal["clive.engineering_objective.v1"] = "clive.engineering_objective.v1"
    objective_id: str = Field(pattern=_SAFE_ID)
    title: str = Field(min_length=1, max_length=200)
    requested_outcome: str = Field(min_length=1, max_length=20000)
    acceptance_criteria: tuple[str, ...] = ()
    checks: tuple[Check, ...] = ()
    repository: str = Field(pattern=r"^[^/\s]+/[^/\s]+$")
    base_ref: str = Field(min_length=1, max_length=300)
    base_sha: ExactSha
    target_branch: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._/-]+$")
    product_memory_sha: ExactSha
    allowed_paths: tuple[str, ...] = Field(min_length=1)
    prohibited_actions: tuple[str, ...] = DEFAULT_PROHIBITED_ACTIONS
    authority_class: Literal["repository_only"] = "repository_only"
    max_repair_rounds: int = Field(default=2, ge=0, le=5)
    owner: OwnerEntry
    created_at: datetime
    # Who builds it: a Claude builder, or CLIVE's deterministic integrator merging the exact
    # accepted SHAs in ``integrates`` (workers/integrator.py). Both go through the same review.
    builder: Literal["claude", "integrator"] = "claude"
    integrates: tuple[ExactSha, ...] = ()

    @model_validator(mode="after")
    def integration_names_its_inputs(self) -> Objective:
        if (self.builder == "integrator") != bool(self.integrates):
            raise ValueError("an integrator objective, and only one, names the exact SHAs it integrates")
        for sha in self.integrates:
            validate_exact_sha(sha)
        return self

    @field_validator("base_sha", "product_memory_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)

    @field_validator("created_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @field_validator("target_branch")
    @classmethod
    def safe_branch(cls, value: str) -> str:
        if value.startswith(("/", "-")) or value.endswith(("/", ".lock")) or ".." in value or "//" in value:
            raise ValueError("target branch is not a safe git branch name")
        return value

    @field_validator("allowed_paths")
    @classmethod
    def bounded_scope(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        recorded = bool(info.context and info.context.get("recorded_objective"))
        cleaned: list[str] = []
        for raw in value:
            path = raw.strip().rstrip("/")
            if not path or path.startswith("/") or "\\" in path or any(
                part in {"", ".", ".."} for part in path.split("/")
            ):
                raise ValueError(f"allowed path {raw!r} is not a repository-relative path")
            for protected in () if recorded else PROTECTED_PATHS:
                if _overlaps(path, protected):
                    raise ValueError(
                        f"allowed path {path!r} covers {protected!r}, an authority or runtime surface "
                        "no objective may put in scope; the owner changes it by hand"
                    )
            cleaned.append(path)
        return tuple(cleaned)

    @field_validator("acceptance_criteria", "prohibited_actions")
    @classmethod
    def no_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("entries must not be empty")
        return value

    @model_validator(mode="after")
    def defaults_cannot_be_dropped(self) -> Objective:
        missing = [p for p in DEFAULT_PROHIBITED_ACTIONS if p not in self.prohibited_actions]
        if missing:
            raise ValueError("the default prohibited actions cannot be removed: " + "; ".join(missing))
        names = [c.name for c in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("check names must be unique")
        return self


def _overlaps(a: str, b: str) -> bool:
    """Either path is the other or contains it."""
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def protected_paths_in(paths: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """The PROTECTED_PATHS entries any of ``paths`` is, contains or lies beneath, in list order."""
    cleaned = [p.strip().rstrip("/") for p in paths]
    return tuple(protected for protected in PROTECTED_PATHS if any(_overlaps(p, protected) for p in cleaned if p))


def owner_entry_from_host() -> OwnerEntry:
    return OwnerEntry(os_user=getpass.getuser() or "unknown", host=socket.gethostname() or "unknown")


def slug(title: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (text or "objective")[:60].strip("-")


def required_evidence_for(objective: Objective) -> tuple[str, ...]:
    """What every candidate of this objective must carry, all of it produced or observed by CLIVE."""
    return ("worker_report", "worker_transcript", *(f"check-{c.name}" for c in objective.checks))


def task_from_objective(objective: Objective, *, objective_sha256: str) -> EngineeringTask:
    return EngineeringTask(
        task_id=objective.objective_id,
        revision=1,
        stream_id=f"objective:{objective.objective_id}",
        kind=TaskKind.BUILD,
        objective=f"{objective.title}: {objective.requested_outcome}",
        repository=objective.repository,
        base_sha=objective.base_sha,
        target_branch=objective.target_branch,
        product_memory_sha=objective.product_memory_sha,
        allowed_paths=objective.allowed_paths,
        prohibited_actions=objective.prohibited_actions,
        required_evidence=required_evidence_for(objective),
        reviewer_must_be_independent=True,
        authorising_reference=(
            f"objective {objective.objective_id} (objectives/{objective.objective_id}.json sha256 "
            f"{objective_sha256}) entered via {objective.owner.channel} by {objective.owner.os_user}@"
            f"{objective.owner.host} as the owner; origin not verified; authority repository_only"
        ),
        created_at=objective.created_at,
    )


class ObjectiveStore:
    """Objective records under the kernel's store root, written under the kernel's lock."""

    def __init__(self, store: LifecycleStore, *, journal: bool = True, lock_timeout_s: float = 10.0) -> None:
        self.store = store
        self.dir = store.root / "objectives"
        self.journal = journal
        self.lock_timeout_s = lock_timeout_s

    def path(self, objective_id: str) -> Path:
        return self.dir / f"{objective_id}.json"

    def read(self, objective_id: str) -> Objective | None:
        path = self.path(objective_id)
        if not path.exists():
            return None
        return Objective.model_validate_json(path.read_text(encoding="utf-8"), context=RECORDED)

    def read_all(self) -> tuple[Objective, ...]:
        if not self.dir.exists():
            return ()
        return tuple(
            Objective.model_validate_json(p.read_text(encoding="utf-8"), context=RECORDED)
            for p in sorted(self.dir.glob("*.json"))
        )

    def digest(self, objective_id: str) -> str:
        return sha256_of(self.path(objective_id).read_bytes())

    def put(self, objective: Objective, *, operator: str) -> str:
        """Write the objective once. Identical bytes are idempotent; different bytes are refused."""
        payload = JsonRecordStore._canonical_bytes(objective)
        path = self.path(objective.objective_id)
        with self.store.exclusive_writer(self.lock_timeout_s):
            if path.exists():
                if path.read_bytes() == payload:
                    return sha256_of(payload)
                raise RecordConflictError(
                    f"objective {objective.objective_id} is already recorded differently; an objective "
                    "is immutable: enter a new objective id"
                )
            if self.journal:
                journal_preconditions(self.store.root)
            JsonRecordStore._atomic_write(path, payload)
            try:
                if self.journal:
                    git_journal(
                        self.store.root,
                        f"objective {objective.objective_id} entered: {objective.title[:60]} (operator: {operator})",
                    )
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return sha256_of(payload)


def accepted_candidates(kernel: Kernel, objective_ids: tuple[str, ...]) -> tuple[str, ...]:
    """The exact SHA each objective's latest integration verified; refused unless every one has one."""
    out = []
    for objective_id in objective_ids:
        done = [i for i in kernel.store.read_integrations() if i.task_id == objective_id]
        if not done:
            raise LifecycleError(f"{objective_id} has no verified integration of an accepted candidate to integrate")
        out.append(max(done, key=lambda i: i.task_revision).accepted_sha)
    return tuple(out)


def integration_scope(kernel: Kernel, base_sha: str, shas: tuple[str, ...]) -> tuple[str, ...]:
    """Every path any of the candidates changed relative to the integration base: the integrator's scope."""
    paths: set[str] = set()
    for sha in shas:
        changed = kernel.git.changed_paths(base_sha, sha)
        if changed is None:
            raise LifecycleError(f"the repository cannot list the paths changed between {base_sha} and {sha}")
        paths.update(changed)
    if not paths:
        raise LifecycleError("the candidates change nothing relative to the integration base")
    return tuple(sorted(paths))


def intake(objective: Objective, *, kernel: Kernel, objectives: ObjectiveStore) -> dict:
    """Persist the objective, then create its task revision 1 in the kernel. Idempotent.

    Returns what was recorded. A kernel refusal leaves the objective recorded and
    the task absent; the dispatcher reports that as an objective with no task, and
    re-running intake with the same objective retries only the task.
    """
    if not kernel.git.commit_exists(objective.base_sha):
        raise LifecycleError(f"base {objective.base_sha} ({objective.base_ref}) is not a commit in the repository")
    digest = objectives.put(objective, operator=kernel.operator)
    task = task_from_objective(objective, objective_sha256=digest)
    existing = kernel.store.read_task(task.task_id, 1)
    if existing is not None and existing != task:
        raise RecordConflictError(f"task {task.task_id} r1 already exists and does not match this objective")
    state = kernel.create_task(task)
    return {
        "objective_id": objective.objective_id,
        "objective_path": str(objectives.path(objective.objective_id)),
        "objective_sha256": digest,
        "task_id": task.task_id,
        "task_revision": 1,
        "stage": state.status.value,
        "required_evidence": list(task.required_evidence),
    }


def objective_json(objective: Objective) -> str:
    return json.dumps(objective.model_dump(mode="json"), indent=2, sort_keys=True)
