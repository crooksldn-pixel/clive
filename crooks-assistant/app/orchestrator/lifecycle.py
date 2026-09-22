"""The write side of the engineering control plane: CLIVE authors its lifecycle.

Until now every record in this package had a reader and no producer, so a task's
stage could only be inferred from processes, branches and prose. This module is
the producer. It records, in order and fail-closed:

    task created -> assignment (attempt + lease + fencing token + dispatch identity)
    -> acknowledgement -> heartbeats / progress / evidence -> immutable candidate SHA
    -> independent review dispatch -> exact-SHA verdict admitted or refused
    -> repair cycle (new attempt or new revision) -> acceptance -> integration
    -> DONE, which the projection renders as COMPLETE only when every record exists.

What it reuses, deliberately: ``EngineeringTask`` and ``TaskRuntimeState`` (with
its compare-and-swap) for task identity and stage; ``EngineeringResult`` as the
immutable candidate record; ``ReviewEvidence`` as the verdict record; and the
existing eligibility, continuation, acceptance and stale-result gates, which are
consulted rather than re-implemented. What it adds is only what had no home:
attempts with leases and monotonic fencing tokens, an append-only event journal
per attempt, review dispatches, verdict admissions, acceptances and integrations.

What it refuses to be: a scheduler, a watcher, a service or a deployer. It runs
when a verb is invoked, writes files under one store root, optionally journals
each write as a git commit, and stops. Process and git probes are reconciliation
evidence for the projection; they are never consulted here to *decide* a stage.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .contracts import (
    BlockerClass,
    EngineeringResult,
    EngineeringTask,
    ExactSha,
    NextAction,
    NextActionKind,
    StrictRecord,
    TaskRuntimeState,
    TaskStatus,
    validate_exact_sha,
)
from .policy import evaluate_obvious_continuation
from .review_acceptance import (
    AcceptanceTarget,
    ReviewEvidence,
    ReviewVerdict,
    evidence_fingerprint,
)
from .review_result_gate import ReviewResultEnvelope, gate_review_result
from .routing import Party
from .state import build_active_state
from .store import JsonRecordStore, RecordConflictError, StateConflictError

__all__ = [
    "Acceptance",
    "Attempt",
    "AttemptEvent",
    "EventKind",
    "GitFacts",
    "Integration",
    "IntegrationMethod",
    "Kernel",
    "LifecycleError",
    "LifecycleStore",
    "PrincipalRegistry",
    "ReviewDispatch",
    "VerdictAdmission",
    "VerdictOutcome",
    "lifecycle_view",
    "sha256_of",
]

LIVE_STATUSES = frozenset(
    {
        TaskStatus.ASSIGNED,
        TaskStatus.RUNNING,
        TaskStatus.EVIDENCE_READY,
        TaskStatus.REVIEWING,
        TaskStatus.ACCEPTED,
        TaskStatus.BLOCKED,
        TaskStatus.OWNER_GATE,
    }
)
TERMINAL_STATUSES = frozenset({TaskStatus.DONE, TaskStatus.OBSOLETE, TaskStatus.CANCELLED})


class LifecycleError(ValueError):
    """A verb was refused. Nothing was written."""


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


# ------------------------------------------------------------------ records


class EventKind(StrEnum):
    OPENED = "opened"
    ACKNOWLEDGED = "acknowledged"
    HEARTBEAT = "heartbeat"
    PROGRESS = "progress"
    EVIDENCE = "evidence"
    CANDIDATE = "candidate"
    REVIEW_DISPATCHED = "review_dispatched"
    VERDICT_ADMITTED = "verdict_admitted"
    VERDICT_REFUSED = "verdict_refused"
    ACCEPTED = "accepted"
    INTEGRATED = "integrated"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    RESUMED = "resumed"


LIVENESS_EVENTS = frozenset(
    {EventKind.OPENED, EventKind.ACKNOWLEDGED, EventKind.HEARTBEAT, EventKind.PROGRESS,
     EventKind.EVIDENCE, EventKind.CANDIDATE}
)


class Attempt(StrictRecord):
    """One fenced try at one task revision by one dispatched worker.

    ``fencing_token`` is monotonic across every attempt of a task id, so a late
    result from an earlier attempt can be told apart from the current one by a
    number rather than by trusting who submits it. ``worker`` is the dispatch
    identity the kernel recorded, not something the worker asserts later.
    """

    schema_version: Literal["clive.attempt.v1"] = "clive.attempt.v1"
    task_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    fencing_token: int = Field(ge=1)
    worker_id: str = Field(min_length=1, max_length=200)
    worker: Party
    base_sha: ExactSha
    lease_duration_s: int = Field(ge=1)
    opened_at: datetime
    recorded_at: datetime
    backfilled: bool = False
    evidence_ref: str | None = Field(default=None, max_length=500)

    @field_validator("base_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)

    @field_validator("opened_at", "recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def backfill_needs_a_reference(self) -> Attempt:
        if self.backfilled and not self.evidence_ref:
            raise ValueError("a backfilled record must name the evidence it was taken from")
        if not self.backfilled and self.opened_at > self.recorded_at:
            raise ValueError("a live record cannot be dated after it was recorded")
        return self


class AttemptEvent(StrictRecord):
    """One line of an attempt's append-only journal."""

    schema_version: Literal["clive.attempt_event.v1"] = "clive.attempt_event.v1"
    task_id: str = Field(min_length=1, max_length=120)
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120)
    seq: int = Field(ge=1)
    kind: EventKind
    at: datetime
    recorded_at: datetime
    fencing_token: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=1000)
    sha: ExactSha | None = None
    evidence_name: str | None = Field(default=None, max_length=120)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_path: str | None = Field(default=None, max_length=500)
    backfilled: bool = False
    evidence_ref: str | None = Field(default=None, max_length=500)

    @field_validator("sha")
    @classmethod
    def exact_sha(cls, value: str | None) -> str | None:
        return None if value is None else validate_exact_sha(value)

    @field_validator("at", "recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def backfill_needs_a_reference(self) -> AttemptEvent:
        if self.backfilled and not self.evidence_ref:
            raise ValueError("a backfilled event must name the evidence it was taken from")
        return self


class ReviewDispatch(StrictRecord):
    """An exact candidate handed to a named independent reviewer principal."""

    schema_version: Literal["clive.review_dispatch.v1"] = "clive.review_dispatch.v1"
    task_id: str = Field(min_length=1, max_length=120)
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120)
    dispatch_seq: int = Field(ge=1)
    candidate_sha: ExactSha
    author: Party
    reviewer_principal_id: str = Field(min_length=1, max_length=200)
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    packet_path: str = Field(min_length=1, max_length=500)
    fencing_token: int = Field(ge=1)
    dispatched_at: datetime
    recorded_at: datetime
    backfilled: bool = False
    evidence_ref: str | None = Field(default=None, max_length=500)

    @field_validator("candidate_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)

    @field_validator("dispatched_at", "recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _aware(value)


class VerdictOutcome(StrEnum):
    ACCEPTED = "accepted"  # READY from an eligible reviewer at the exact candidate
    REJECTED_BY_VERDICT = "rejected_by_verdict"  # every fence held; the verdict says repair
    REFUSED = "refused"  # a fence failed: stale, drifted, ineligible, duplicate


class VerdictAdmission(StrictRecord):
    """What the kernel decided about one submitted verdict, and why, forever."""

    schema_version: Literal["clive.verdict_admission.v1"] = "clive.verdict_admission.v1"
    task_id: str = Field(min_length=1, max_length=120)
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120)
    dispatch_seq: int = Field(ge=1)
    admission_seq: int = Field(ge=1)
    evidence: ReviewEvidence
    payload_path: str = Field(min_length=1, max_length=500)
    current_candidate_sha: ExactSha | None
    outcome: VerdictOutcome
    reasons: tuple[str, ...] = ()
    admitted_at: datetime
    recorded_at: datetime
    backfilled: bool = False
    evidence_ref: str | None = Field(default=None, max_length=500)

    @field_validator("current_candidate_sha")
    @classmethod
    def exact_sha(cls, value: str | None) -> str | None:
        return None if value is None else validate_exact_sha(value)

    @field_validator("admitted_at", "recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def outcome_and_reasons_agree(self) -> VerdictAdmission:
        if self.outcome is VerdictOutcome.ACCEPTED and self.reasons:
            raise ValueError("an accepted verdict carries no refusal reasons")
        if self.outcome is not VerdictOutcome.ACCEPTED and not self.reasons:
            raise ValueError("a verdict that was not accepted must say why")
        return self


class Acceptance(StrictRecord):
    schema_version: Literal["clive.acceptance.v1"] = "clive.acceptance.v1"
    task_id: str = Field(min_length=1, max_length=120)
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120)
    accepted_sha: ExactSha
    admission_seq: int = Field(ge=1)
    reviewer_principal_id: str = Field(min_length=1, max_length=200)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_at: datetime
    recorded_at: datetime

    @field_validator("accepted_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)

    @field_validator("accepted_at", "recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _aware(value)


class IntegrationMethod(StrEnum):
    FAST_FORWARD = "fast_forward"
    MERGE = "merge"


class Integration(StrictRecord):
    schema_version: Literal["clive.integration.v1"] = "clive.integration.v1"
    task_id: str = Field(min_length=1, max_length=120)
    task_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=120)
    accepted_sha: ExactSha
    target_branch: str = Field(min_length=1, max_length=300)
    target_base_sha: ExactSha
    integration_sha: ExactSha
    method: IntegrationMethod
    ancestry_verified: bool
    remote_head_sha: ExactSha | None = None
    gates_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    integrated_by: str = Field(min_length=1, max_length=200)
    integrated_at: datetime
    recorded_at: datetime

    @field_validator("accepted_sha", "target_base_sha", "integration_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)

    @field_validator("remote_head_sha")
    @classmethod
    def optional_exact_sha(cls, value: str | None) -> str | None:
        return None if value is None else validate_exact_sha(value)

    @field_validator("integrated_at", "recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def integration_must_be_verified(self) -> Integration:
        if not self.ancestry_verified:
            raise ValueError("an integration is recorded only once ancestry is verified")
        return self


# ------------------------------------------------------------ the registry


@dataclass(frozen=True)
class PrincipalRegistry:
    """Who may review, per ``config/review_principals.json``. Identities only."""

    principals: dict[str, dict]

    @classmethod
    def load(cls, path: Path) -> PrincipalRegistry:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema") != "clive.review_principals.v1":
            raise LifecycleError(f"{path} is not a clive.review_principals.v1 document")
        return cls({p["principal_id"]: p for p in data.get("principals", [])})

    def may_review(self, principal_id: str) -> bool:
        return bool(self.principals.get(principal_id, {}).get("may_review", False))

    def known(self, principal_id: str) -> bool:
        return principal_id in self.principals


# -------------------------------------------------------------- git facts


class GitFacts:
    """The four git questions the kernel asks. Shell-free doubles replace it in tests."""

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo)

    def _run(self, *args: str) -> tuple[int, str]:
        proc = subprocess.run(
            ["git", *args], cwd=str(self.repo), capture_output=True, text=True, timeout=60
        )
        return proc.returncode, (proc.stdout or proc.stderr).strip()

    def commit_exists(self, sha: str) -> bool:
        rc, out = self._run("cat-file", "-t", sha)
        return rc == 0 and out == "commit"

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        rc, _ = self._run("merge-base", "--is-ancestor", ancestor, descendant)
        return rc == 0

    def rev_parse(self, ref: str) -> str | None:
        rc, out = self._run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        return out if rc == 0 and len(out) == 40 else None

    def remote_head(self, remote: str, branch: str) -> str | None:
        rc, out = self._run("ls-remote", "--heads", remote, branch)
        if rc != 0 or not out:
            return None
        sha = out.split()[0]
        return sha if len(sha) == 40 else None


# ------------------------------------------------------------- the store


class LifecycleStore(JsonRecordStore):
    """The Phase 1 store plus the record kinds that had nowhere to live."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.attempts_dir = self.root / "attempts"
        self.events_dir = self.root / "events"
        self.reviews_dir = self.root / "reviews"
        self.acceptances_dir = self.root / "acceptances"
        self.integrations_dir = self.root / "integrations"

    def ensure_layout(self) -> None:
        super().ensure_layout()
        for directory in (
            self.attempts_dir,
            self.events_dir,
            self.reviews_dir,
            self.acceptances_dir,
            self.integrations_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    # attempts ---------------------------------------------------------------
    def put_attempt(self, attempt: Attempt) -> Path:
        path = self.attempts_dir / attempt.task_id / f"{attempt.attempt_id}.json"
        self._put_immutable(path, attempt)
        return path

    def read_attempts(self, task_id: str | None = None) -> tuple[Attempt, ...]:
        if not self.attempts_dir.exists():
            return ()
        pattern = f"{task_id}/*.json" if task_id else "*/*.json"
        return tuple(
            Attempt.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.attempts_dir.glob(pattern))
        )

    # events -----------------------------------------------------------------
    def _events_path(self, task_id: str, attempt_id: str) -> Path:
        return self.events_dir / task_id / f"{attempt_id}.jsonl"

    def read_events(self, task_id: str, attempt_id: str) -> tuple[AttemptEvent, ...]:
        path = self._events_path(task_id, attempt_id)
        if not path.exists():
            return ()
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return tuple(AttemptEvent.model_validate_json(line) for line in lines)

    def append_event(self, event: AttemptEvent) -> Path:
        """Append one journal line. The seq must be exactly the next one."""
        self.ensure_layout()
        path = self._events_path(event.task_id, event.attempt_id)
        existing = self.read_events(event.task_id, event.attempt_id)
        expected = existing[-1].seq + 1 if existing else 1
        if event.seq != expected:
            raise StateConflictError(f"event seq must be {expected}, got {event.seq}")
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return path

    # reviews ----------------------------------------------------------------
    def _review_dir(self, task_id: str, attempt_id: str) -> Path:
        return self.reviews_dir / task_id / attempt_id

    def put_dispatch(self, dispatch: ReviewDispatch, packet: bytes) -> Path:
        directory = self._review_dir(dispatch.task_id, dispatch.attempt_id)
        packet_path = directory / f"dispatch.{dispatch.dispatch_seq}.packet.md"
        self.ensure_layout()
        packet_path.parent.mkdir(parents=True, exist_ok=True)
        if packet_path.exists() and packet_path.read_bytes() != packet:
            raise RecordConflictError(f"packet already recorded differently: {packet_path}")
        self._atomic_write(packet_path, packet)
        path = directory / f"dispatch.{dispatch.dispatch_seq}.json"
        self._put_immutable(path, dispatch)
        return path

    def read_dispatches(self, task_id: str, attempt_id: str) -> tuple[ReviewDispatch, ...]:
        directory = self._review_dir(task_id, attempt_id)
        if not directory.exists():
            return ()
        return tuple(
            ReviewDispatch.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("dispatch.*.json"), key=_numbered)
        )

    def put_admission(self, admission: VerdictAdmission, payload: bytes) -> Path:
        directory = self._review_dir(admission.task_id, admission.attempt_id)
        self.ensure_layout()
        directory.mkdir(parents=True, exist_ok=True)
        payload_path = directory / f"verdict.{admission.admission_seq}.evidence.txt"
        if payload_path.exists() and payload_path.read_bytes() != payload:
            raise RecordConflictError(f"verdict payload already recorded differently: {payload_path}")
        self._atomic_write(payload_path, payload)
        path = directory / f"verdict.{admission.admission_seq}.json"
        self._put_immutable(path, admission)
        return path

    def read_admissions(self, task_id: str, attempt_id: str) -> tuple[VerdictAdmission, ...]:
        directory = self._review_dir(task_id, attempt_id)
        if not directory.exists():
            return ()
        return tuple(
            VerdictAdmission.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("verdict.*.json"), key=_numbered)
        )

    # acceptances / integrations -------------------------------------------
    def put_acceptance(self, acceptance: Acceptance) -> Path:
        path = self.acceptances_dir / acceptance.task_id / f"{acceptance.attempt_id}.json"
        self._put_immutable(path, acceptance)
        return path

    def read_acceptances(self, task_id: str | None = None) -> tuple[Acceptance, ...]:
        if not self.acceptances_dir.exists():
            return ()
        pattern = f"{task_id}/*.json" if task_id else "*/*.json"
        return tuple(
            Acceptance.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.acceptances_dir.glob(pattern))
        )

    def put_integration(self, integration: Integration) -> Path:
        path = self.integrations_dir / f"{integration.task_id}.r{integration.task_revision}.json"
        self._put_immutable(path, integration)
        return path

    def read_integrations(self) -> tuple[Integration, ...]:
        if not self.integrations_dir.exists():
            return ()
        return tuple(
            Integration.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.integrations_dir.glob("*.json"))
        )

    # task state helpers -----------------------------------------------------
    def read_task_state(self, task_id: str, revision: int) -> TaskRuntimeState | None:
        path = self.task_states_dir / f"{task_id}.r{revision}.json"
        if not path.exists():
            return None
        return TaskRuntimeState.model_validate_json(path.read_text(encoding="utf-8"))

    def read_task(self, task_id: str, revision: int) -> EngineeringTask | None:
        path = self.tasks_dir / f"{task_id}.r{revision}.json"
        if not path.exists():
            return None
        return EngineeringTask.model_validate_json(path.read_text(encoding="utf-8"))


def _numbered(path: Path) -> int:
    try:
        return int(path.name.split(".")[1])
    except (IndexError, ValueError):
        return 0


# ---------------------------------------------------------------- journal


def git_journal(root: Path, message: str) -> str | None:
    """Commit the store root if it lives in a git worktree. Returns the commit SHA.

    The kernel is the author; the operator is named in the message. A store
    outside any repository journals nothing and returns None.
    """
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=str(root), capture_output=True, text=True
    )
    if proc.returncode != 0:
        return None
    toplevel = proc.stdout.strip()
    subprocess.run(["git", "add", "-A", "--", str(root)], cwd=toplevel, check=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", str(root)], cwd=toplevel
    )
    if staged.returncode == 0:
        return None  # nothing changed; identical bytes were written
    subprocess.run(
        [
            "git", "-c", "user.name=CLIVE kernel", "-c", "user.email=kernel@clive.invalid",
            "commit", "-q", "-m", message,
        ],
        cwd=toplevel,
        check=True,
    )
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=toplevel, capture_output=True, text=True)
    return out.stdout.strip()


# ---------------------------------------------------------------- kernel


@dataclass
class Kernel:
    """The verbs. Each validates everything, then writes; a refusal writes nothing.

    ``git`` answers the four repository questions (commit exists, ancestry, a
    ref's SHA, a remote branch head). ``clock`` is injectable so tests own time.
    ``operator`` names who is running the verb; it goes into every journal line.
    """

    store: LifecycleStore
    registry: PrincipalRegistry
    git: GitFacts
    operator: str = "unnamed operator"
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    journal: bool = True
    journal_shas: list[str] = field(default_factory=list)

    # ---- helpers -------------------------------------------------------
    def _now(self) -> datetime:
        return self.clock()

    def _when(self, at: datetime | None, backfilled: bool, evidence_ref: str | None) -> tuple[datetime, datetime]:
        now = self._now()
        if at is None:
            return now, now
        at = _aware(at)
        if at > now:
            raise LifecycleError("a record cannot be dated in the future")
        if at < now and not backfilled:
            raise LifecycleError(
                "a record dated in the past must be marked backfilled and name its evidence"
            )
        if backfilled and not evidence_ref:
            raise LifecycleError("a backfilled record must name the evidence it was taken from")
        return at, now

    def _commit(self, message: str) -> None:
        if not self.journal:
            return
        sha = git_journal(self.store.root, f"kernel: {message} (operator: {self.operator})")
        if sha:
            self.journal_shas.append(sha)

    def _task(self, task_id: str, revision: int) -> EngineeringTask:
        task = self.store.read_task(task_id, revision)
        if task is None:
            raise LifecycleError(f"no task {task_id} r{revision} is recorded")
        return task

    def _state(self, task_id: str, revision: int) -> TaskRuntimeState:
        state = self.store.read_task_state(task_id, revision)
        if state is None:
            raise LifecycleError(f"task {task_id} r{revision} has no runtime state")
        return state

    def _attempt(self, task_id: str, attempt_id: str) -> Attempt:
        for attempt in self.store.read_attempts(task_id):
            if attempt.attempt_id == attempt_id:
                return attempt
        raise LifecycleError(f"no attempt {attempt_id} is recorded for task {task_id}")

    def _find_attempt(self, attempt_id: str) -> Attempt:
        matches = [a for a in self.store.read_attempts() if a.attempt_id == attempt_id]
        if len(matches) != 1:
            raise LifecycleError(f"attempt {attempt_id} is not recorded exactly once")
        return matches[0]

    def _transition(self, state: TaskRuntimeState, **changes) -> TaskRuntimeState:
        data = state.model_dump()
        data.update(changes)
        data["transition_seq"] = state.transition_seq + 1
        data["updated_at"] = self._now()
        nxt = TaskRuntimeState(**data)
        self.store.write_task_state(nxt, expected_previous_seq=state.transition_seq)
        return nxt

    def _current(self, attempt: Attempt, allowed: Iterable[TaskStatus]) -> TaskRuntimeState:
        state = self._state(attempt.task_id, attempt.task_revision)
        if state.attempt_id != attempt.attempt_id:
            raise LifecycleError(
                f"attempt {attempt.attempt_id} is not the current attempt of "
                f"{attempt.task_id} r{attempt.task_revision} (current: {state.attempt_id})"
            )
        if state.status not in set(allowed):
            raise LifecycleError(
                f"task {attempt.task_id} r{attempt.task_revision} is {state.status.value}; "
                f"this verb needs one of {sorted(s.value for s in allowed)}"
            )
        return state

    def _fence(self, attempt: Attempt, token: int, at: datetime) -> None:
        if token != attempt.fencing_token:
            raise LifecycleError(
                f"fencing token {token} is not attempt {attempt.attempt_id}'s token "
                f"{attempt.fencing_token}; the submission is fenced"
            )
        lease = self.lease(attempt)
        if at > lease["expires_at"]:
            raise LifecycleError(
                f"lease of attempt {attempt.attempt_id} expired at {lease['expires_at'].isoformat()}; "
                "a timed-out worker cannot submit; open a new attempt"
            )

    def _event(self, attempt: Attempt, kind: EventKind, at: datetime, recorded_at: datetime,
               **fields_) -> AttemptEvent:
        existing = self.store.read_events(attempt.task_id, attempt.attempt_id)
        event = AttemptEvent(
            task_id=attempt.task_id,
            task_revision=attempt.task_revision,
            attempt_id=attempt.attempt_id,
            seq=(existing[-1].seq + 1) if existing else 1,
            kind=kind,
            at=at,
            recorded_at=recorded_at,
            fencing_token=attempt.fencing_token,
            **fields_,
        )
        self.store.append_event(event)
        return event

    def lease(self, attempt: Attempt) -> dict:
        """Where the lease stands, from the journal alone (restart-safe)."""
        events = self.store.read_events(attempt.task_id, attempt.attempt_id)
        liveness = [e.at for e in events if e.kind in LIVENESS_EVENTS]
        last = max(liveness) if liveness else attempt.opened_at
        expires = last + timedelta(seconds=attempt.lease_duration_s)
        return {"last_liveness_at": last, "expires_at": expires, "duration_s": attempt.lease_duration_s}

    def _result(self, attempt: Attempt) -> EngineeringResult | None:
        for result in self.store.read_results():
            if result.task_id == attempt.task_id and result.attempt_id == attempt.attempt_id:
                return result
        return None

    def _regenerate_active_state(self) -> None:
        tasks = self.store.read_tasks()
        heads: dict[str, str] = {}
        for task in tasks:
            if task.target_branch in heads:
                continue
            head = self.git.rev_parse(task.target_branch) or self.git.rev_parse(
                f"refs/remotes/origin/{task.target_branch}"
            )
            if head is None:
                return  # a missing branch truth is not invented; ACTIVE_STATE keeps its last value
            heads[task.target_branch] = head
        active = build_active_state(
            tasks=tasks,
            results=self.store.read_results(),
            task_states=self.store.read_task_states(),
            branch_heads=heads,
            generated_at=self._now(),
        )
        self.store.write_active_state(active)

    # ---- verbs ---------------------------------------------------------
    def create_task(self, task: EngineeringTask) -> TaskRuntimeState:
        """Record an authorised task revision. Revision N supersedes N-1."""
        if not self.git.commit_exists(task.base_sha):
            raise LifecycleError(f"base SHA {task.base_sha} is not a commit in the repository")
        previous_state = None
        if task.revision > 1:
            if self.store.read_task(task.task_id, task.revision - 1) is None:
                raise LifecycleError(
                    f"revision {task.revision} needs revision {task.revision - 1} to exist first"
                )
            previous_state = self._state(task.task_id, task.revision - 1)
            if previous_state.status in LIVE_STATUSES - {TaskStatus.BLOCKED, TaskStatus.OWNER_GATE}:
                raise LifecycleError(
                    f"revision {task.revision - 1} still has a live attempt "
                    f"({previous_state.status.value}); cancel or finish it first"
                )
        existing = self.store.read_task_state(task.task_id, task.revision)
        self.store.put_task(task)  # idempotent for identical bytes, refuses divergence
        if existing is not None:
            return existing
        state = TaskRuntimeState(
            task_id=task.task_id,
            task_revision=task.revision,
            status=TaskStatus.READY,
            transition_seq=0,
            updated_at=self._now(),
        )
        self.store.write_task_state(state, expected_previous_seq=None)
        if previous_state is not None and previous_state.status not in TERMINAL_STATUSES:
            self._transition(previous_state, status=TaskStatus.OBSOLETE, attempt_id=None,
                             blocker_class=BlockerClass.OBSOLETE,
                             blocker_reason=f"superseded by revision {task.revision}",
                             owner_gate=False)
        self._regenerate_active_state()
        self._commit(f"task {task.task_id} r{task.revision} created: {task.objective[:60]}")
        return state

    def assign(
        self,
        task_id: str,
        revision: int,
        *,
        worker_id: str,
        worker: Party,
        lease_duration_s: int = 900,
        attempt_id: str | None = None,
        at: datetime | None = None,
        backfilled: bool = False,
        evidence_ref: str | None = None,
    ) -> Attempt:
        """Assignment, fenced attempt, lease and dispatch identity, in one record."""
        task = self._task(task_id, revision)
        state = self._state(task_id, revision)
        if state.status not in {TaskStatus.READY, TaskStatus.REJECTED}:
            raise LifecycleError(
                f"task {task_id} r{revision} is {state.status.value}; only a READY or REJECTED "
                "task can be assigned"
            )
        if worker.workspace.head_sha != task.base_sha:
            raise LifecycleError(
                f"the worker's workspace is at {worker.workspace.head_sha}, not the task base "
                f"{task.base_sha}"
            )
        opened_at, recorded_at = self._when(at, backfilled, evidence_ref)
        token = max((a.fencing_token for a in self.store.read_attempts(task_id)), default=0) + 1
        # Attempt ids are unique across the whole store, not just within a task: every
        # later verb names an attempt by id alone, so two tasks must never share one.
        attempt = Attempt(
            task_id=task_id,
            task_revision=revision,
            attempt_id=attempt_id or f"{task_id}-a{token}",
            fencing_token=token,
            worker_id=worker_id,
            worker=worker,
            base_sha=task.base_sha,
            lease_duration_s=lease_duration_s,
            opened_at=opened_at,
            recorded_at=recorded_at,
            backfilled=backfilled,
            evidence_ref=evidence_ref,
        )
        if any(a.attempt_id == attempt.attempt_id for a in self.store.read_attempts()):
            raise LifecycleError(f"attempt id {attempt.attempt_id} already exists in this store")
        self.store.put_attempt(attempt)
        self._event(attempt, EventKind.OPENED, opened_at, recorded_at,
                    note=f"assigned to {worker_id} ({worker.principal.principal_id}) with lease "
                         f"{lease_duration_s}s and fencing token {token}",
                    backfilled=backfilled, evidence_ref=evidence_ref)
        self._transition(state, status=TaskStatus.ASSIGNED, attempt_id=attempt.attempt_id,
                         worker_id=worker_id, blocker_class=BlockerClass.NONE,
                         blocker_reason=None, owner_gate=False)
        self._regenerate_active_state()
        self._commit(f"{task_id} r{revision} assigned to {worker_id} as {attempt.attempt_id} token {token}")
        return attempt

    def acknowledge(self, attempt_id: str, *, token: int, base_sha: str, at: datetime | None = None,
                    backfilled: bool = False, evidence_ref: str | None = None) -> AttemptEvent:
        """The worker acknowledges revision, base SHA and token: BUILDING begins."""
        attempt = self._find_attempt(attempt_id)
        state = self._current(attempt, {TaskStatus.ASSIGNED})
        when, recorded = self._when(at, backfilled, evidence_ref)
        self._fence(attempt, token, when)
        if validate_exact_sha(base_sha) != attempt.base_sha:
            raise LifecycleError(
                f"acknowledged base {base_sha} is not the attempt's base {attempt.base_sha}"
            )
        event = self._event(attempt, EventKind.ACKNOWLEDGED, when, recorded, sha=attempt.base_sha,
                            note="worker acknowledged task revision, base SHA and fencing token",
                            backfilled=backfilled, evidence_ref=evidence_ref)
        self._transition(state, status=TaskStatus.RUNNING)
        self._regenerate_active_state()
        self._commit(f"{attempt.task_id} {attempt_id} acknowledged; building")
        return event

    def heartbeat(self, attempt_id: str, *, token: int, note: str | None = None,
                  at: datetime | None = None, backfilled: bool = False,
                  evidence_ref: str | None = None, progress: bool = False) -> AttemptEvent:
        """Liveness (or progress, when the worker says what moved). Renews the lease."""
        attempt = self._find_attempt(attempt_id)
        self._current(attempt, {TaskStatus.RUNNING, TaskStatus.EVIDENCE_READY, TaskStatus.REVIEWING})
        when, recorded = self._when(at, backfilled, evidence_ref)
        self._fence(attempt, token, when)
        kind = EventKind.PROGRESS if progress else EventKind.HEARTBEAT
        event = self._event(attempt, kind, when, recorded, note=note,
                            backfilled=backfilled, evidence_ref=evidence_ref)
        self._commit(f"{attempt.task_id} {attempt_id} {kind.value}")
        return event

    def record_evidence(self, attempt_id: str, *, token: int, name: str, payload: bytes,
                        path: str | None = None, at: datetime | None = None,
                        backfilled: bool = False, evidence_ref: str | None = None) -> AttemptEvent:
        """An artifact the worker produced, by name and digest. Claims come later."""
        attempt = self._find_attempt(attempt_id)
        self._current(attempt, {TaskStatus.RUNNING})
        when, recorded = self._when(at, backfilled, evidence_ref)
        self._fence(attempt, token, when)
        event = self._event(attempt, EventKind.EVIDENCE, when, recorded, evidence_name=name,
                            evidence_sha256=sha256_of(payload), evidence_path=path,
                            backfilled=backfilled, evidence_ref=evidence_ref)
        self._commit(f"{attempt.task_id} {attempt_id} evidence {name}")
        return event

    def record_candidate(
        self,
        attempt_id: str,
        *,
        token: int,
        sha: str,
        changed_paths: tuple[str, ...],
        evidence_satisfied: tuple[str, ...],
        clean_worktree: bool,
        remote: str | None = None,
        at: datetime | None = None,
        backfilled: bool = False,
        evidence_ref: str | None = None,
    ) -> EngineeringResult:
        """The immutable candidate: one per attempt, an existing commit, claims backed by records."""
        attempt = self._find_attempt(attempt_id)
        if self._result(attempt) is not None:
            raise LifecycleError(
                f"attempt {attempt_id} already recorded a candidate; a correction is a new attempt"
            )
        state = self._current(attempt, {TaskStatus.RUNNING})
        task = self._task(attempt.task_id, attempt.task_revision)
        when, recorded = self._when(at, backfilled, evidence_ref)
        self._fence(attempt, token, when)
        sha = validate_exact_sha(sha)
        if not self.git.commit_exists(sha):
            raise LifecycleError(f"candidate {sha} is not a commit in the repository")
        if not self.git.is_ancestor(attempt.base_sha, sha):
            raise LifecycleError(f"candidate {sha} does not descend from the attempt base {attempt.base_sha}")
        recorded_names = {
            e.evidence_name
            for e in self.store.read_events(attempt.task_id, attempt_id)
            if e.kind is EventKind.EVIDENCE
        }
        unbacked = sorted(set(evidence_satisfied) - recorded_names)
        if unbacked:
            raise LifecycleError(
                "evidence claimed but never recorded for this attempt: " + ", ".join(unbacked)
            )
        missing = sorted(set(task.required_evidence) - set(evidence_satisfied))
        if missing:
            raise LifecycleError("required evidence not satisfied: " + ", ".join(missing))
        published = None
        if remote is not None:
            head = self.git.remote_head(remote, task.target_branch)
            if head != sha:
                raise LifecycleError(
                    f"{remote}/{task.target_branch} resolves to {head}, not the candidate {sha}; "
                    "publish first"
                )
            published = head
        result = EngineeringResult(
            task_id=attempt.task_id,
            task_revision=attempt.task_revision,
            attempt_id=attempt_id,
            worker_id=attempt.worker_id,
            base_sha=attempt.base_sha,
            result_sha=sha,
            changed_paths=changed_paths,
            evidence_satisfied=evidence_satisfied,
            clean_worktree=clean_worktree,
            next_action=NextAction(
                kind=NextActionKind.REVIEW,
                reason="candidate recorded; the exact SHA requires independent review",
                subject_sha=sha,
                mechanically_authorised=True,
                required_role="independent-reviewer",
                required_reviewer_independence=task.reviewer_must_be_independent,
            ),
            completed_at=when,
        )
        self.store.put_result(result)
        self._event(attempt, EventKind.CANDIDATE, when, recorded, sha=sha,
                    note=("published at " + remote) if published else "candidate recorded (publication not verified)",
                    backfilled=backfilled, evidence_ref=evidence_ref)
        self._transition(state, status=TaskStatus.EVIDENCE_READY)
        self._regenerate_active_state()
        self._commit(f"{attempt.task_id} {attempt_id} candidate {sha[:12]}")
        return result

    def dispatch_review(
        self,
        attempt_id: str,
        *,
        reviewer_principal_id: str,
        packet: bytes,
        current_head: str,
        at: datetime | None = None,
        backfilled: bool = False,
        evidence_ref: str | None = None,
    ) -> ReviewDispatch:
        """Hand the exact candidate to an independent reviewer; the packet is kept."""
        attempt = self._find_attempt(attempt_id)
        state = self._current(attempt, {TaskStatus.EVIDENCE_READY})
        task = self._task(attempt.task_id, attempt.task_revision)
        result = self._result(attempt)
        if result is None or result.result_sha is None:
            raise LifecycleError("no candidate is recorded for this attempt")
        when, recorded = self._when(at, backfilled, evidence_ref)
        if not self.registry.known(reviewer_principal_id):
            raise LifecycleError(f"reviewer principal {reviewer_principal_id!r} is not registered")
        if not self.registry.may_review(reviewer_principal_id):
            raise LifecycleError(f"reviewer principal {reviewer_principal_id!r} may not review")
        author_principal = attempt.worker.principal.principal_id
        if author_principal.strip().casefold() == reviewer_principal_id.strip().casefold():
            raise LifecycleError(
                f"reviewer {reviewer_principal_id!r} is the author principal; "
                "the same principal never reviews its own candidate"
            )
        decision = evaluate_obvious_continuation(
            task,
            result,
            candidate_worker_id=reviewer_principal_id,
            current_branch_head=current_head,
            latest_task_revision=self._latest_revision(task.task_id),
        )
        if not decision.allowed:
            raise LifecycleError(f"continuation policy refuses review dispatch: {decision.reason}")
        seq = len(self.store.read_dispatches(attempt.task_id, attempt_id)) + 1
        dispatch = ReviewDispatch(
            task_id=attempt.task_id,
            task_revision=attempt.task_revision,
            attempt_id=attempt_id,
            dispatch_seq=seq,
            candidate_sha=result.result_sha,
            author=attempt.worker,
            reviewer_principal_id=reviewer_principal_id,
            packet_sha256=sha256_of(packet),
            packet_path=f"reviews/{attempt.task_id}/{attempt_id}/dispatch.{seq}.packet.md",
            fencing_token=attempt.fencing_token,
            dispatched_at=when,
            recorded_at=recorded,
            backfilled=backfilled,
            evidence_ref=evidence_ref,
        )
        self.store.put_dispatch(dispatch, packet)
        self._event(attempt, EventKind.REVIEW_DISPATCHED, when, recorded, sha=result.result_sha,
                    note=f"review of {result.result_sha[:12]} dispatched to {reviewer_principal_id}",
                    backfilled=backfilled, evidence_ref=evidence_ref)
        self._transition(state, status=TaskStatus.REVIEWING)
        self._regenerate_active_state()
        self._commit(f"{attempt.task_id} {attempt_id} review dispatched to {reviewer_principal_id}")
        return dispatch

    def _latest_revision(self, task_id: str) -> int:
        return max(t.revision for t in self.store.read_tasks() if t.task_id == task_id)

    def admit_verdict(
        self,
        attempt_id: str,
        *,
        reviewer: Party,
        verdict: ReviewVerdict,
        payload: bytes,
        observed_candidate_sha: str,
        current_head: str,
        at: datetime | None = None,
        backfilled: bool = False,
        evidence_ref: str | None = None,
    ) -> VerdictAdmission:
        """Admit or refuse one verdict. Every outcome is recorded; only two change the stage.

        The author identity comes from the attempt record, never from the caller,
        so a verdict cannot be laundered by restating who wrote the candidate.
        """
        attempt = self._find_attempt(attempt_id)
        state = self._current(attempt, {TaskStatus.REVIEWING})
        result = self._result(attempt)
        dispatches = self.store.read_dispatches(attempt.task_id, attempt_id)
        if result is None or result.result_sha is None or not dispatches:
            raise LifecycleError("no dispatched review exists for this attempt")
        dispatch = dispatches[-1]
        when, recorded = self._when(at, backfilled, evidence_ref)
        if any(a.outcome is VerdictOutcome.ACCEPTED for a in self.store.read_admissions(attempt.task_id, attempt_id)):
            raise LifecycleError("a final verdict was already accepted for this attempt; duplicates are refused")
        try:
            observed = validate_exact_sha(observed_candidate_sha)
        except ValueError as exc:
            raise LifecycleError(f"observed candidate SHA is malformed: {exc}") from exc
        evidence = ReviewEvidence(
            task_id=attempt.task_id,
            task_revision=attempt.task_revision,
            attempt_id=attempt_id,
            candidate_sha=result.result_sha,
            author=attempt.worker,
            reviewer=reviewer,
            verdict=verdict,
            evidence_sha256=evidence_fingerprint(payload),
            observed_candidate_sha=observed,
            completed_at=when,
        )
        target = AcceptanceTarget(
            task_id=attempt.task_id,
            task_revision=attempt.task_revision,
            attempt_id=attempt_id,
            candidate_sha=result.result_sha,
            author=attempt.worker,
        )
        try:
            current_sha: str | None = validate_exact_sha(current_head)
        except ValueError:
            current_sha = None
        reasons: list[str] = []
        if not self.registry.may_review(reviewer.principal.principal_id):
            reasons.append("reviewer_not_registered_to_review")
        if reviewer.principal.principal_id.strip().casefold() != dispatch.reviewer_principal_id.strip().casefold():
            reasons.append("reviewer_is_not_the_dispatched_principal")
        gate = gate_review_result(
            envelope=ReviewResultEnvelope(target=target, evidence=evidence, evidence_payload=payload),
            current_target=target,
            current_candidate_sha=current_sha or "",
        )
        reasons.extend(gate.reasons)
        reasons = list(dict.fromkeys(reasons))
        if gate.accepted and not reasons:
            outcome = VerdictOutcome.ACCEPTED
        elif reasons == ["verdict_not_ready"]:
            outcome = VerdictOutcome.REJECTED_BY_VERDICT
        else:
            outcome = VerdictOutcome.REFUSED
        seq = len(self.store.read_admissions(attempt.task_id, attempt_id)) + 1
        admission = VerdictAdmission(
            task_id=attempt.task_id,
            task_revision=attempt.task_revision,
            attempt_id=attempt_id,
            dispatch_seq=dispatch.dispatch_seq,
            admission_seq=seq,
            evidence=evidence,
            payload_path=f"reviews/{attempt.task_id}/{attempt_id}/verdict.{seq}.evidence.txt",
            current_candidate_sha=current_sha,
            outcome=outcome,
            reasons=tuple(reasons),
            admitted_at=when,
            recorded_at=recorded,
            backfilled=backfilled,
            evidence_ref=evidence_ref,
        )
        self.store.put_admission(admission, payload)
        if outcome is VerdictOutcome.ACCEPTED:
            acceptance = Acceptance(
                task_id=attempt.task_id,
                task_revision=attempt.task_revision,
                attempt_id=attempt_id,
                accepted_sha=result.result_sha,
                admission_seq=seq,
                reviewer_principal_id=reviewer.principal.principal_id,
                evidence_sha256=evidence.evidence_sha256,
                accepted_at=when,
                recorded_at=recorded,
            )
            self.store.put_acceptance(acceptance)
            self._event(attempt, EventKind.VERDICT_ADMITTED, when, recorded, sha=result.result_sha,
                        note=f"READY from {reviewer.principal.principal_id} admitted; candidate accepted",
                        backfilled=backfilled, evidence_ref=evidence_ref)
            self._event(attempt, EventKind.ACCEPTED, when, recorded, sha=result.result_sha,
                        note="acceptance recorded; eligible for integration only",
                        backfilled=backfilled, evidence_ref=evidence_ref)
            self._transition(state, status=TaskStatus.ACCEPTED)
        elif outcome is VerdictOutcome.REJECTED_BY_VERDICT:
            self._event(attempt, EventKind.VERDICT_ADMITTED, when, recorded, sha=result.result_sha,
                        note=f"REPAIR_REQUIRED from {reviewer.principal.principal_id} admitted; a correction needs a new candidate",
                        backfilled=backfilled, evidence_ref=evidence_ref)
            self._transition(state, status=TaskStatus.REJECTED)
        else:
            self._event(attempt, EventKind.VERDICT_REFUSED, when, recorded, sha=result.result_sha,
                        note="verdict refused: " + ", ".join(reasons),
                        backfilled=backfilled, evidence_ref=evidence_ref)
        self._regenerate_active_state()
        self._commit(f"{attempt.task_id} {attempt_id} verdict {verdict.value}: {outcome.value}")
        return admission

    def integrate(
        self,
        task_id: str,
        revision: int,
        *,
        integration_sha: str,
        target_base_sha: str,
        method: IntegrationMethod,
        integrated_by: str,
        remote: str | None = None,
        gates_evidence: bytes | None = None,
        at: datetime | None = None,
    ) -> Integration:
        """Integration of the accepted SHA, verified in git, then DONE."""
        task = self._task(task_id, revision)
        state = self._state(task_id, revision)
        if state.status is not TaskStatus.ACCEPTED or state.attempt_id is None:
            raise LifecycleError(f"task {task_id} r{revision} is {state.status.value}, not ACCEPTED")
        acceptances = [a for a in self.store.read_acceptances(task_id) if a.attempt_id == state.attempt_id]
        if not acceptances:
            raise LifecycleError("no acceptance record exists for the current attempt")
        accepted_sha = acceptances[-1].accepted_sha
        integration_sha = validate_exact_sha(integration_sha)
        target_base_sha = validate_exact_sha(target_base_sha)
        when, recorded = self._when(at, False, None)
        if not self.git.commit_exists(integration_sha):
            raise LifecycleError(f"integration SHA {integration_sha} is not a commit in the repository")
        if not self.git.is_ancestor(accepted_sha, integration_sha):
            raise LifecycleError(
                f"accepted candidate {accepted_sha} is not an ancestor of {integration_sha}; "
                "the integration does not contain the accepted work"
            )
        if method is IntegrationMethod.FAST_FORWARD and integration_sha != accepted_sha:
            raise LifecycleError("a fast-forward integration must land exactly the accepted SHA")
        remote_head = None
        if remote is not None:
            remote_head = self.git.remote_head(remote, task.target_branch)
            if remote_head != integration_sha:
                raise LifecycleError(
                    f"{remote}/{task.target_branch} is at {remote_head}, not {integration_sha}"
                )
        integration = Integration(
            task_id=task_id,
            task_revision=revision,
            attempt_id=state.attempt_id,
            accepted_sha=accepted_sha,
            target_branch=task.target_branch,
            target_base_sha=target_base_sha,
            integration_sha=integration_sha,
            method=method,
            ancestry_verified=True,
            remote_head_sha=remote_head,
            gates_evidence_sha256=sha256_of(gates_evidence) if gates_evidence else None,
            integrated_by=integrated_by,
            integrated_at=when,
            recorded_at=recorded,
        )
        self.store.put_integration(integration)
        attempt = self._attempt(task_id, state.attempt_id)
        self._event(attempt, EventKind.INTEGRATED, when, recorded, sha=integration_sha,
                    note=f"{accepted_sha[:12]} integrated into {task.target_branch} at {integration_sha[:12]} ({method.value})")
        self._transition(state, status=TaskStatus.DONE)
        self._regenerate_active_state()
        self._commit(f"{task_id} r{revision} integrated at {integration_sha[:12]}; done")
        return integration

    def cancel_attempt(self, attempt_id: str, *, reason: str, at: datetime | None = None) -> AttemptEvent:
        """Fence an attempt for good. Its token is dead; the task returns to READY."""
        attempt = self._find_attempt(attempt_id)
        state = self._current(attempt, LIVE_STATUSES - {TaskStatus.ACCEPTED})
        when, recorded = self._when(at, False, None)
        event = self._event(attempt, EventKind.CANCELLED, when, recorded, note=reason)
        self._transition(state, status=TaskStatus.READY, attempt_id=None, worker_id=None,
                         blocker_class=BlockerClass.NONE, blocker_reason=None, owner_gate=False)
        self._regenerate_active_state()
        self._commit(f"{attempt.task_id} {attempt_id} cancelled: {reason[:60]}")
        return event

    def block(self, task_id: str, revision: int, *, blocker_class: BlockerClass, reason: str,
              owner_gate: bool = False, at: datetime | None = None) -> TaskRuntimeState:
        """Record a blocker or an owner gate on the current stage. Nothing is retried."""
        state = self._state(task_id, revision)
        if state.status in TERMINAL_STATUSES:
            raise LifecycleError(f"task {task_id} r{revision} is {state.status.value}; nothing to block")
        if blocker_class is BlockerClass.NONE:
            raise LifecycleError("a block needs a blocker class")
        when, recorded = self._when(at, False, None)
        status = TaskStatus.OWNER_GATE if owner_gate or blocker_class is BlockerClass.OWNER_ONLY else TaskStatus.BLOCKED
        nxt = self._transition(state, status=status, blocker_class=blocker_class, blocker_reason=reason,
                               owner_gate=owner_gate or blocker_class is BlockerClass.OWNER_ONLY)
        if state.attempt_id:
            self._event(self._attempt(task_id, state.attempt_id), EventKind.BLOCKED, when, recorded, note=reason)
        self._regenerate_active_state()
        self._commit(f"{task_id} r{revision} {status.value}: {reason[:60]}")
        return nxt

    def resume(self, task_id: str, revision: int, *, note: str, at: datetime | None = None) -> TaskRuntimeState:
        """Lift a block or gate; the stage is recomputed from the records, not remembered."""
        state = self._state(task_id, revision)
        if state.status not in {TaskStatus.BLOCKED, TaskStatus.OWNER_GATE}:
            raise LifecycleError(f"task {task_id} r{revision} is not blocked or gated")
        when, recorded = self._when(at, False, None)
        status = TaskStatus.READY
        if state.attempt_id:
            attempt = self._attempt(task_id, state.attempt_id)
            kinds = {e.kind for e in self.store.read_events(task_id, attempt.attempt_id)}
            if self.store.read_acceptances(task_id) and any(a.attempt_id == attempt.attempt_id for a in self.store.read_acceptances(task_id)):
                status = TaskStatus.ACCEPTED
            elif self.store.read_dispatches(task_id, attempt.attempt_id):
                status = TaskStatus.REVIEWING
            elif self._result(attempt) is not None:
                status = TaskStatus.EVIDENCE_READY
            elif EventKind.ACKNOWLEDGED in kinds:
                status = TaskStatus.RUNNING
            else:
                status = TaskStatus.ASSIGNED
            self._event(attempt, EventKind.RESUMED, when, recorded, note=note)
        nxt = self._transition(state, status=status, blocker_class=BlockerClass.NONE,
                               blocker_reason=None, owner_gate=False)
        self._regenerate_active_state()
        self._commit(f"{task_id} r{revision} resumed as {status.value}")
        return nxt


# ------------------------------------------------------------ projection


def lifecycle_view(store: LifecycleStore, *, now: datetime) -> dict:
    """Everything the records say, read-only, for the state view and the environment.

    Stages come from the records. Nothing here looks at a process or a branch;
    that reconciliation belongs to the caller, which may only annotate.
    """
    tasks_out: list[dict] = []
    by_worker: dict[str, dict] = {}
    all_by_worker: dict[str, list[tuple[TaskStatus, dict]]] = {}
    reviewing_principals: dict[str, dict] = {}
    completed_by_worker: dict[str, dict] = {}
    acceptances = store.read_acceptances()
    integrations = {(i.task_id, i.task_revision): i for i in store.read_integrations()}
    results = {(r.task_id, r.attempt_id): r for r in store.read_results()}

    for task in sorted(store.read_tasks(), key=lambda t: (t.stream_id, t.task_id, t.revision)):
        state = store.read_task_state(task.task_id, task.revision)
        if state is None:
            continue
        # The current attempt places the task; a revision with none (superseded,
        # cancelled, done) is still described by its last attempt, so a repair
        # cycle's earlier candidates and verdicts stay visible in the history.
        attempts = [a for a in store.read_attempts(task.task_id) if a.task_revision == task.revision]
        attempt = None
        if state.attempt_id:
            attempt = next((a for a in attempts if a.attempt_id == state.attempt_id), None)
        if attempt is None and attempts:
            attempt = max(attempts, key=lambda a: a.fencing_token)
        events = store.read_events(task.task_id, attempt.attempt_id) if attempt else ()
        result = results.get((task.task_id, attempt.attempt_id)) if attempt else None
        dispatches = store.read_dispatches(task.task_id, attempt.attempt_id) if attempt else ()
        admissions = store.read_admissions(task.task_id, attempt.attempt_id) if attempt else ()
        acceptance = next((a for a in acceptances if attempt and a.task_id == task.task_id and a.attempt_id == attempt.attempt_id), None)
        integration = integrations.get((task.task_id, task.revision))
        liveness = [e.at for e in events if e.kind in LIVENESS_EVENTS]
        heartbeats = [e.at for e in events if e.kind in {EventKind.HEARTBEAT, EventKind.PROGRESS}]
        lease = None
        if attempt is not None:
            last = max(liveness) if liveness else attempt.opened_at
            expires = last + timedelta(seconds=attempt.lease_duration_s)
            lease = {
                "duration_s": attempt.lease_duration_s,
                "last_liveness_at": _iso(last),
                "expires_at": _iso(expires),
                "alive": now <= expires,
            }
        complete = (
            state.status is TaskStatus.DONE
            and acceptance is not None
            and integration is not None
            and integration.accepted_sha == acceptance.accepted_sha
        )
        stage = "COMPLETE" if complete else state.status.value.upper()
        if state.status is TaskStatus.DONE and not complete:
            stage = "UNKNOWN"
        record = {
            "task_id": task.task_id,
            "revision": task.revision,
            "stream": task.stream_id,
            "kind": task.kind.value,
            "objective": task.objective,
            "target_branch": task.target_branch,
            "base_sha": task.base_sha,
            "authorising_reference": task.authorising_reference,
            "stage": stage,
            "stage_reason": _stage_reason(state, attempt, result, dispatches, admissions, acceptance, integration, lease, complete),
            "worker_id": state.worker_id,
            "attempt_id": state.attempt_id,
            "fencing_token": attempt.fencing_token if attempt else None,
            "dispatch_identity": (
                {
                    "principal_id": attempt.worker.principal.principal_id,
                    "session_id": attempt.worker.session.session_id,
                    "workspace_id": attempt.worker.workspace.workspace_id,
                    "workspace_branch": attempt.worker.workspace.branch,
                }
                if attempt
                else None
            ),
            "lease": lease,
            "last_heartbeat": _iso(max(heartbeats)) if heartbeats else None,
            "acknowledged": any(e.kind is EventKind.ACKNOWLEDGED for e in events),
            "evidence": [
                {"name": e.evidence_name, "sha256": e.evidence_sha256, "path": e.evidence_path, "at": _iso(e.at)}
                for e in events
                if e.kind is EventKind.EVIDENCE
            ],
            "candidate_sha": result.result_sha if result else None,
            "candidate_recorded_at": _iso(result.completed_at) if result else None,
            "review": {
                "dispatched_to": dispatches[-1].reviewer_principal_id if dispatches else None,
                "dispatched_at": _iso(dispatches[-1].dispatched_at) if dispatches else None,
                "packet_sha256": dispatches[-1].packet_sha256 if dispatches else None,
                "verdicts": [
                    {
                        "outcome": a.outcome.value,
                        "verdict": a.evidence.verdict.value,
                        "reviewer": a.evidence.reviewer.principal.principal_id,
                        "reasons": list(a.reasons),
                        "at": _iso(a.admitted_at),
                        "backfilled": a.backfilled,
                    }
                    for a in admissions
                ],
            },
            "acceptance": (
                {"sha": acceptance.accepted_sha, "at": _iso(acceptance.accepted_at), "by": acceptance.reviewer_principal_id}
                if acceptance
                else None
            ),
            "integration": (
                {"sha": integration.integration_sha, "target_branch": integration.target_branch,
                 "method": integration.method.value, "at": _iso(integration.integrated_at),
                 "remote_head_sha": integration.remote_head_sha}
                if integration
                else None
            ),
            "blocker": state.blocker_reason,
            "blocker_class": state.blocker_class.value,
            "owner_gate": state.owner_gate,
            "last_transition_at": _iso(state.updated_at),
            "backfilled": bool(attempt and attempt.backfilled) or any(e.backfilled for e in events),
            "history": [
                {"seq": e.seq, "kind": e.kind.value, "at": _iso(e.at), "note": e.note, "sha": e.sha, "backfilled": e.backfilled}
                for e in events
            ],
        }
        tasks_out.append(record)

        if state.worker_id and state.status in LIVE_STATUSES | {TaskStatus.REJECTED}:
            # A worker may hold several live assignments. The one that says most about
            # what the worker is doing now wins; the rest are listed, not hidden.
            all_by_worker.setdefault(state.worker_id, []).append((state.status, record))
        if complete and state.worker_id and integration is not None:
            prev = completed_by_worker.get(state.worker_id)
            if prev is None or integration.integrated_at > datetime.fromisoformat(prev["integration"]["at"]):
                completed_by_worker[state.worker_id] = record
        if state.status is TaskStatus.REVIEWING and dispatches:
            reviewing_principals[dispatches[-1].reviewer_principal_id] = record

    for worker_id, held in all_by_worker.items():
        held.sort(key=lambda item: _ACTIVITY_RANK[item[0]], reverse=True)
        by_worker[worker_id] = held[0][1]
        by_worker[worker_id]["also_assigned"] = [
            f"{r['task_id']} r{r['revision']} ({r['stage']})" for _, r in held[1:]
        ]
    return {
        "store_root": str(store.root),
        "tasks": tasks_out,
        "assignments_by_worker": by_worker,
        "completed_by_worker": completed_by_worker,
        "reviewing_by_principal": reviewing_principals,
    }


# When one worker holds several live assignments, the one it is most actively in wins
# the worker's status; the others are listed as also_assigned.
_ACTIVITY_RANK = {
    TaskStatus.RUNNING: 7,
    TaskStatus.ASSIGNED: 6,
    TaskStatus.BLOCKED: 5,
    TaskStatus.OWNER_GATE: 5,
    TaskStatus.EVIDENCE_READY: 4,
    TaskStatus.REVIEWING: 3,
    TaskStatus.REJECTED: 2,
    TaskStatus.ACCEPTED: 1,
}


def _stage_reason(state, attempt, result, dispatches, admissions, acceptance, integration, lease, complete) -> str:
    s = state.status
    if complete:
        return (f"accepted {acceptance.accepted_sha[:12]} integrated into {integration.target_branch} "
                f"at {integration.integration_sha[:12]}; every record present")
    if s is TaskStatus.DONE:
        return "state says done but the acceptance or integration record is missing; not COMPLETE"
    if s is TaskStatus.READY:
        return "authorised and unassigned"
    if s is TaskStatus.ASSIGNED and attempt:
        return f"assigned to {attempt.worker_id} as {attempt.attempt_id} (token {attempt.fencing_token}); not yet acknowledged"
    if s is TaskStatus.RUNNING and lease:
        return ("building; lease alive until " + lease["expires_at"]) if lease["alive"] else (
            "lease expired at " + lease["expires_at"] + "; no heartbeat since " + lease["last_liveness_at"])
    if s is TaskStatus.EVIDENCE_READY and result:
        return f"candidate {result.result_sha[:12]} recorded; awaiting review dispatch"
    if s is TaskStatus.REVIEWING and dispatches:
        refused = [a for a in admissions if a.outcome is VerdictOutcome.REFUSED]
        tail = f"; {len(refused)} verdict(s) refused" if refused else ""
        return f"review of {dispatches[-1].candidate_sha[:12]} dispatched to {dispatches[-1].reviewer_principal_id}{tail}"
    if s is TaskStatus.REJECTED and admissions:
        return f"candidate rejected by {admissions[-1].evidence.reviewer.principal.principal_id}; a correction needs a new attempt or revision"
    if s is TaskStatus.ACCEPTED and acceptance:
        return f"candidate {acceptance.accepted_sha[:12]} accepted by {acceptance.reviewer_principal_id}; awaiting integration"
    if s in {TaskStatus.BLOCKED, TaskStatus.OWNER_GATE}:
        return f"{s.value}: {state.blocker_reason}"
    if s is TaskStatus.OBSOLETE:
        return state.blocker_reason or "superseded"
    return s.value


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
