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

from pydantic import Field, field_validator, model_validator

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
    "intake",
    "owner_entry_from_host",
    "required_evidence_for",
    "task_from_objective",
]

_SAFE_ID = r"^[a-z0-9][a-z0-9.-]{2,79}$"

# Paths no objective may put in scope. Each is an authority or runtime surface the
# dispatcher must never be able to change on its own: the frozen kernel and the
# records it reads, who may review, how CI judges, and anything that installs or
# runs services. The owner changes these by hand, outside this door.
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
    "crooks-assistant/app/orchestrator/workers",
    "crooks-assistant/app/orchestrator/reviewers",
    "crooks-assistant/scripts/engineering_kernel.py",
    "crooks-assistant/scripts/engineering_dispatcher.py",
    "crooks-assistant/config/review_principals.json",
    "crooks-assistant/config/agent_roster.json",
    "crooks-assistant/launchd",
    "crooks-assistant/scripts/install_launchd.py",
    "crooks-assistant/scripts/set_secrets.py",
    ".github",
    "engineering",
)

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
    def bounded_scope(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for raw in value:
            path = raw.strip().rstrip("/")
            if not path or path.startswith("/") or "\\" in path or any(
                part in {"", ".", ".."} for part in path.split("/")
            ):
                raise ValueError(f"allowed path {raw!r} is not a repository-relative path")
            for protected in PROTECTED_PATHS:
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
        return Objective.model_validate_json(path.read_text(encoding="utf-8"))

    def read_all(self) -> tuple[Objective, ...]:
        if not self.dir.exists():
            return ()
        return tuple(
            Objective.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(self.dir.glob("*.json"))
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
