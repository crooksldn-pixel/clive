"""The kernel writes the lifecycle; these tests are mostly about what it refuses to write.

Every verb is exercised against a fake git (four answers, no shell) and a fixed
clock, so the only things under test are the records, the fences and the order.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import app.orchestrator.lifecycle as lifecycle_module
from app.actions.judgment import JudgmentRecord, OwnerDecision, OwnerProvenance, ReasonCode
from app.orchestrator.contracts import (
    BlockerClass,
    EngineeringTask,
    TaskKind,
    TaskStatus,
)
from app.orchestrator.lifecycle import (
    Attempt,
    EventKind,
    GitFacts,
    IntegrationMethod,
    JournalError,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
    StoreBusyError,
    VerdictOutcome,
    judgment_to_dict,
    lifecycle_view,
)
from app.orchestrator.review_acceptance import ReviewVerdict
from app.orchestrator.routing import Party, Principal, PrincipalKind, SessionContext, Workspace
from app.orchestrator.store import JsonRecordStore, RecordConflictError, StateConflictError
from scripts import agent_state_view as view

BASE = "a" * 40
CAND = "b" * 40
CAND2 = "d" * 40
MERGED = "c" * 40
MEMORY = "e" * 40
T0 = datetime(2026, 9, 22, 22, 0, tzinfo=UTC)


@dataclass
class FakeGit:
    commits: set[str] = field(default_factory=lambda: {BASE, CAND, CAND2, MERGED, MEMORY})
    ancestry: set[tuple[str, str]] = field(
        default_factory=lambda: {(BASE, CAND), (BASE, CAND2), (CAND, MERGED), (BASE, MERGED), (CAND, CAND2)}
    )
    heads: dict[str, str] = field(default_factory=lambda: {"work": BASE})
    remote: dict[tuple[str, str], str] = field(default_factory=dict)
    diffs: dict[tuple[str, str], tuple[str, ...] | None] = field(default_factory=dict)

    def commit_exists(self, sha: str) -> bool:
        return sha in self.commits

    def changed_paths(self, base: str, head: str) -> tuple[str, ...] | None:
        return self.diffs.get((base, head), ("f.py",))

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return ancestor == descendant or (ancestor, descendant) in self.ancestry

    def rev_parse(self, ref: str) -> str | None:
        return self.heads.get(ref.removeprefix("refs/remotes/origin/"))

    def remote_head(self, remote: str, branch: str) -> str | None:
        return self.remote.get((remote, branch))


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> datetime:
        self.now = self.now + timedelta(seconds=seconds)
        return self.now


REGISTRY = PrincipalRegistry(
    {
        "claude": {"principal_id": "claude", "may_review": False},
        "gpt": {"principal_id": "gpt", "may_review": True},
        "owner": {"principal_id": "owner", "may_review": True, "roles": ["owner"]},
    }
)


def party(principal: str, session: str, workspace: str, head: str, *, read_only=False, clean=True, fresh=True) -> Party:
    return Party(
        principal=Principal(principal_id=principal, kind=PrincipalKind.MODEL),
        session=SessionContext(session_id=session, context_is_fresh=fresh, started_at=T0),
        workspace=Workspace(workspace_id=workspace, branch="work", head_sha=head, read_only=read_only, clean=clean),
    )


AUTHOR = party("claude", "session-author", "/w/author", BASE)
REVIEWER = party("gpt", "session-reviewer", "/w/reviewer", CAND, read_only=True)


def task(**overrides) -> EngineeringTask:
    data = dict(
        task_id="t-1", revision=1, stream_id="stream", kind=TaskKind.REPAIR,
        objective="repair one bounded defect", repository="o/r", base_sha=BASE,
        target_branch="work", product_memory_sha=MEMORY, required_evidence=("pytest",),
        authorising_reference="owner mandate", created_at=T0,
    )
    data.update(overrides)
    return EngineeringTask(**data)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def git() -> FakeGit:
    return FakeGit()


@pytest.fixture
def kernel(tmp_path, clock, git) -> Kernel:
    return Kernel(LifecycleStore(tmp_path / "engineering"), REGISTRY, git, operator="tests", clock=clock, journal=False)


def to_candidate(kernel: Kernel, clock: Clock, git: FakeGit, *, sha: str = CAND, task_id: str = "t-1") -> Attempt:
    """The happy path up to a recorded candidate, shared by the later tests."""
    if kernel.store.read_task(task_id, 1) is None:
        kernel.create_task(task(task_id=task_id))
    attempt = kernel.assign(task_id, 1, worker_id="w1", worker=AUTHOR, lease_duration_s=300)
    kernel.acknowledge(attempt.attempt_id, token=attempt.fencing_token, base_sha=BASE)
    clock.advance(10)
    kernel.record_evidence(attempt.attempt_id, token=attempt.fencing_token, name="pytest", payload=b"3000 passed")
    kernel.record_candidate(attempt.attempt_id, token=attempt.fencing_token, sha=sha, evidence_satisfied=("pytest",), clean_worktree=True)
    git.heads["work"] = sha
    return attempt


def to_review(kernel, clock, git, *, task_id: str = "t-1"):
    attempt = to_candidate(kernel, clock, git, task_id=task_id)
    kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"packet", current_head=CAND)
    return attempt


def state(kernel: Kernel) -> TaskStatus:
    return kernel.store.read_task_state("t-1", 1).status


def owner_judgment(kernel: Kernel, task_id: str, revision: int, *, judgment_id="j-gate-1", principal="owner",
                   session="owner-session-1", decision=OwnerDecision.APPROVED,
                   reason=ReasonCode.ACCEPTED_AS_PROPOSED, proposal=None, task_revision=None,
                   attempt_id="__the_gate__", explanation=None, corrects=None) -> JudgmentRecord:
    """A judgment about the gate of (task_id, revision), or about whatever a test says instead."""
    gate = proposal or kernel.gate_proposal(task_id, revision)
    current = kernel.store.read_task_state(task_id, revision)
    return JudgmentRecord(
        judgment_id=judgment_id, task_id=task_id, action_id=f"resume:{task_id}:r{revision}",
        proposal_id=gate["proposal_id"], proposal_fingerprint=gate["proposal_fingerprint"],
        decision=decision, reason_code=reason,
        provenance=OwnerProvenance(principal_id=principal, session_id=session, source="owner-ui"),
        decided_at=T0, task_revision=revision if task_revision is None else task_revision,
        attempt_id=current.attempt_id if attempt_id == "__the_gate__" else attempt_id,
        redacted_explanation=explanation, corrects_judgment_id=corrects,
    )


def owner_ledger(path: Path, *records: JudgmentRecord) -> str:
    """Write the owner's ledger file (JSON lines) and return the path as the kernel takes it."""
    path.write_text("".join(json.dumps(judgment_to_dict(r)) + "\n" for r in records), encoding="utf-8")
    return str(path)


def git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "--initial-branch=main", str(path)], check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    return path


def git_out(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


# ----------------------------------------------------------------- tasks


def test_create_task_records_ready_state_and_is_idempotent(kernel):
    first = kernel.create_task(task())
    again = kernel.create_task(task())
    assert first.status is TaskStatus.READY and first.transition_seq == 0
    assert again == first
    assert kernel.store.read_task("t-1", 1) == task()


def test_create_task_refuses_an_unknown_base_and_divergent_bytes(kernel):
    with pytest.raises(LifecycleError, match="not a commit"):
        kernel.create_task(task(base_sha="f" * 40))
    kernel.create_task(task())
    with pytest.raises(RecordConflictError):
        kernel.create_task(task(objective="the same identity, different words"))


def test_a_new_revision_needs_its_predecessor_and_obsoletes_it(kernel, clock, git):
    with pytest.raises(LifecycleError, match="needs revision 1"):
        kernel.create_task(task(revision=2))
    attempt = to_candidate(kernel, clock, git)
    with pytest.raises(LifecycleError, match="live attempt"):
        kernel.create_task(task(revision=2, base_sha=CAND))
    kernel.cancel_attempt(attempt.attempt_id, reason="abandoned")
    kernel.create_task(task(revision=2, base_sha=CAND))
    assert kernel.store.read_task_state("t-1", 1).status is TaskStatus.OBSOLETE
    assert kernel.store.read_task_state("t-1", 2).status is TaskStatus.READY
    superseded = lifecycle_view(kernel.store, now=clock())["tasks"][0]
    assert superseded["stage"] == "OBSOLETE" and superseded["candidate_sha"] == CAND
    assert [e["kind"] for e in superseded["history"]][-2:] == ["candidate", "cancelled"]


# ----------------------------------------------------------- assignment


def test_assign_records_attempt_lease_token_and_dispatch_identity(kernel):
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, lease_duration_s=300)
    assert attempt.fencing_token == 1 and attempt.attempt_id == "t-1-a1"
    assert attempt.worker == AUTHOR and attempt.worker_id == "w1"
    assert state(kernel) is TaskStatus.ASSIGNED
    runtime = kernel.store.read_task_state("t-1", 1)
    assert (runtime.attempt_id, runtime.worker_id) == ("t-1-a1", "w1")
    events = kernel.store.read_events("t-1", "t-1-a1")
    assert [e.kind for e in events] == [EventKind.OPENED]
    assert kernel.lease(attempt)["expires_at"] == T0 + timedelta(seconds=300)


def test_assign_refuses_a_second_live_attempt_and_a_workspace_off_base(kernel):
    kernel.create_task(task())
    with pytest.raises(LifecycleError, match="not the task base"):
        kernel.assign("t-1", 1, worker_id="w1", worker=party("claude", "s", "/w", CAND))
    kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    with pytest.raises(LifecycleError, match="only a READY or REJECTED"):
        kernel.assign("t-1", 1, worker_id="w2", worker=party("claude", "s2", "/w2", BASE))


def test_acknowledge_requires_the_right_token_and_base(kernel):
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    with pytest.raises(LifecycleError, match="fenced"):
        kernel.acknowledge(attempt.attempt_id, token=2, base_sha=BASE)
    with pytest.raises(LifecycleError, match="not the attempt's base"):
        kernel.acknowledge(attempt.attempt_id, token=1, base_sha=CAND)
    assert state(kernel) is TaskStatus.ASSIGNED
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    assert state(kernel) is TaskStatus.RUNNING


# ---------------------------------------------------------- liveness


def test_heartbeat_is_fenced_by_token_and_by_lease(kernel, clock):
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, lease_duration_s=60)
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    with pytest.raises(LifecycleError, match="fenced"):
        kernel.heartbeat(attempt.attempt_id, token=7)
    clock.advance(30)
    kernel.heartbeat(attempt.attempt_id, token=1)
    assert kernel.lease(attempt)["expires_at"] == T0 + timedelta(seconds=90)
    clock.advance(120)
    with pytest.raises(LifecycleError, match="lease .* expired"):
        kernel.heartbeat(attempt.attempt_id, token=1)
    with pytest.raises(LifecycleError, match="lease .* expired"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, evidence_satisfied=(), clean_worktree=True)


def test_the_lease_is_derived_from_the_journal_and_survives_a_restart(kernel, clock, git, tmp_path):
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, lease_duration_s=60)
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    clock.advance(45)
    kernel.heartbeat(attempt.attempt_id, token=1, note="still here", progress=True)
    reborn = Kernel(LifecycleStore(tmp_path / "engineering"), REGISTRY, git, clock=clock, journal=False)
    assert reborn.lease(attempt) == kernel.lease(attempt)
    assert reborn.lease(attempt)["last_liveness_at"] == T0 + timedelta(seconds=45)
    assert lifecycle_view(reborn.store, now=clock()) == lifecycle_view(kernel.store, now=clock())


# ---------------------------------------------------------- candidate


def test_candidate_requires_recorded_evidence_and_a_descendant_commit(kernel, git):
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    with pytest.raises(LifecycleError, match="claimed but never recorded"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, evidence_satisfied=("pytest",), clean_worktree=True)
    kernel.record_evidence(attempt.attempt_id, token=1, name="pytest", payload=b"ok")
    with pytest.raises(LifecycleError, match="required evidence not satisfied"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, evidence_satisfied=(), clean_worktree=True)
    with pytest.raises(LifecycleError, match="not a commit"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha="9" * 40, evidence_satisfied=("pytest",), clean_worktree=True)
    with pytest.raises(LifecycleError, match="does not descend"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=MEMORY, evidence_satisfied=("pytest",), clean_worktree=True)
    assert state(kernel) is TaskStatus.RUNNING


def test_one_candidate_per_attempt(kernel, clock, git):
    attempt = to_candidate(kernel, clock, git)
    with pytest.raises(LifecycleError, match="already recorded a candidate"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND2, evidence_satisfied=("pytest",), clean_worktree=True)
    assert state(kernel) is TaskStatus.EVIDENCE_READY


def test_candidate_publication_is_verified_against_the_remote(kernel, git):
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    kernel.record_evidence(attempt.attempt_id, token=1, name="pytest", payload=b"ok")
    with pytest.raises(LifecycleError, match="publish first"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, evidence_satisfied=("pytest",), clean_worktree=True, remote="origin")
    git.remote[("origin", "work")] = CAND
    result = kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, evidence_satisfied=("pytest",), clean_worktree=True, remote="origin")
    assert result.result_sha == CAND
    assert kernel.store.read_events("t-1", "t-1-a1")[-1].note == "published at origin"


def test_changed_paths_come_from_git_and_an_omitted_out_of_scope_change_cannot_reach_review(kernel, clock, git):
    """K-01. The candidate commit touches a file outside the task's scope. Declaring only the
    in-scope file is refused; declaring nothing records what git says, and the scope gate refuses
    the dispatch. Either way the out-of-scope change cannot reach review."""
    kernel.create_task(task(allowed_paths=("app",)))
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    kernel.record_evidence(attempt.attempt_id, token=1, name="pytest", payload=b"ok")
    git.diffs[(BASE, CAND)] = ("app/x.py", "ops/deploy.sh")
    with pytest.raises(LifecycleError, match="omitted: ops/deploy.sh"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, changed_paths=("app/x.py",),
                                evidence_satisfied=("pytest",), clean_worktree=True)
    assert kernel.store.read_results() == () and state(kernel) is TaskStatus.RUNNING
    result = kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, evidence_satisfied=("pytest",), clean_worktree=True)
    assert result.changed_paths == ("app/x.py", "ops/deploy.sh")
    git.heads["work"] = CAND
    with pytest.raises(LifecycleError, match="outside task scope: ops/deploy.sh"):
        kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"p", current_head=CAND)
    assert state(kernel) is TaskStatus.EVIDENCE_READY
    assert kernel.store.read_dispatches("t-1", attempt.attempt_id) == ()


def test_an_in_scope_candidate_declared_exactly_or_not_at_all_is_recorded_from_git(kernel, clock, git):
    kernel.create_task(task(allowed_paths=("app",)))
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    kernel.record_evidence(attempt.attempt_id, token=1, name="pytest", payload=b"ok")
    git.diffs[(BASE, CAND)] = ("app/x.py", "app/y.py")
    with pytest.raises(LifecycleError, match="not in the diff: app/z.py"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, changed_paths=("app/x.py", "app/y.py", "app/z.py"),
                                evidence_satisfied=("pytest",), clean_worktree=True)
    result = kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, changed_paths=("app/y.py", "app/x.py"),
                                     evidence_satisfied=("pytest",), clean_worktree=True)
    assert result.changed_paths == ("app/x.py", "app/y.py")
    git.heads["work"] = CAND
    kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"p", current_head=CAND)
    assert state(kernel) is TaskStatus.REVIEWING
    # a repository that cannot answer is a refusal, not an empty scope
    kernel.create_task(task(task_id="t-2"))
    other = kernel.assign("t-2", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(other.attempt_id, token=1, base_sha=BASE)
    kernel.record_evidence(other.attempt_id, token=1, name="pytest", payload=b"ok")
    git.diffs[(BASE, CAND2)] = None
    with pytest.raises(LifecycleError, match="cannot list the paths"):
        kernel.record_candidate(other.attempt_id, token=1, sha=CAND2, evidence_satisfied=("pytest",), clean_worktree=True)


# ------------------------------------------------------------ dispatch


def test_dispatch_refuses_the_author_an_unregistered_reviewer_and_a_moved_branch(kernel, clock, git):
    attempt = to_candidate(kernel, clock, git)
    with pytest.raises(LifecycleError, match="may not review"):
        kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="claude", packet=b"p", current_head=CAND)
    with pytest.raises(LifecycleError, match="not registered"):
        kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="nobody", packet=b"p", current_head=CAND)
    with pytest.raises(LifecycleError, match="continuation policy refuses"):
        kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"p", current_head=CAND2)
    assert state(kernel) is TaskStatus.EVIDENCE_READY
    dispatch = kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"packet", current_head=CAND)
    assert dispatch.candidate_sha == CAND and dispatch.author == AUTHOR
    assert (kernel.store.root / dispatch.packet_path).read_bytes() == b"packet"
    assert state(kernel) is TaskStatus.REVIEWING


def test_a_registered_reviewer_who_authored_the_attempt_is_still_refused(tmp_path, clock, git):
    registry = PrincipalRegistry({"gpt": {"principal_id": "gpt", "may_review": True}})
    kernel = Kernel(LifecycleStore(tmp_path / "e"), registry, git, clock=clock, journal=False)
    kernel.create_task(task())
    gpt_author = party("gpt", "s", "/w", BASE)
    attempt = kernel.assign("t-1", 1, worker_id="w-gpt", worker=gpt_author)
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    kernel.record_evidence(attempt.attempt_id, token=1, name="pytest", payload=b"ok")
    kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, evidence_satisfied=("pytest",), clean_worktree=True)
    git.heads["work"] = CAND
    with pytest.raises(LifecycleError, match="never reviews its own candidate"):
        kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"p", current_head=CAND)


# ------------------------------------------------------------ verdicts


def test_ready_from_an_eligible_reviewer_at_the_exact_sha_is_accepted(kernel, clock, git):
    attempt = to_review(kernel, clock, git)
    admission = kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                                     observed_candidate_sha=CAND, current_head=CAND)
    assert admission.outcome is VerdictOutcome.ACCEPTED and admission.reasons == ()
    assert state(kernel) is TaskStatus.ACCEPTED
    acceptance = kernel.store.read_acceptances("t-1")[0]
    assert acceptance.accepted_sha == CAND and acceptance.reviewer_principal_id == "gpt"
    assert (kernel.store.root / admission.payload_path).read_bytes() == b"READY"
    kinds = [e.kind for e in kernel.store.read_events("t-1", attempt.attempt_id)]
    assert kinds[-2:] == [EventKind.VERDICT_ADMITTED, EventKind.ACCEPTED]


def test_repair_required_is_admitted_as_a_rejection_not_refused(kernel, clock, git):
    attempt = to_review(kernel, clock, git)
    admission = kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.REPAIR_REQUIRED,
                                     payload=b"J-01", observed_candidate_sha=CAND, current_head=CAND)
    assert admission.outcome is VerdictOutcome.REJECTED_BY_VERDICT
    assert admission.reasons == ("verdict_not_ready",)
    assert state(kernel) is TaskStatus.REJECTED
    assert kernel.store.read_acceptances("t-1") == ()


@pytest.mark.parametrize(
    ("reviewer", "observed", "head", "expect"),
    [
        (REVIEWER, BASE, CAND, "review_observed_sha_drift"),
        (REVIEWER, CAND, CAND2, "current_candidate_sha_drift"),
        (party("claude", "fresh-session", "/w/fresh", CAND, read_only=True), CAND, CAND, "reviewer_ineligible:same_principal"),
        (party("gpt", "s", "/w/rw", CAND, read_only=False), CAND, CAND, "reviewer_ineligible:reviewer_workspace_is_writable"),
        (party("gpt", "s", "/w/dirty", CAND, read_only=True, clean=False), CAND, CAND, "reviewer_ineligible:reviewer_workspace_is_dirty"),
        (party("gpt", "s", "/w/old", BASE, read_only=True), CAND, CAND, "reviewer_ineligible:reviewer_not_at_candidate"),
        (party("gpt", "s", "/w/inherited", CAND, read_only=True, fresh=False), CAND, CAND, "reviewer_ineligible:stale_context"),
        (party("owner", "s", "/w/owner", CAND, read_only=True), CAND, CAND, "reviewer_is_not_the_dispatched_principal"),
    ],
)
def test_a_verdict_that_fails_any_fence_is_refused_and_changes_nothing(kernel, clock, git, reviewer, observed, head, expect):
    attempt = to_review(kernel, clock, git)
    admission = kernel.admit_verdict(attempt.attempt_id, reviewer=reviewer, verdict=ReviewVerdict.READY, payload=b"READY",
                                     observed_candidate_sha=observed, current_head=head)
    assert admission.outcome is VerdictOutcome.REFUSED
    assert expect in admission.reasons
    assert state(kernel) is TaskStatus.REVIEWING
    assert kernel.store.read_acceptances("t-1") == ()
    assert kernel.store.read_events("t-1", attempt.attempt_id)[-1].kind is EventKind.VERDICT_REFUSED


def test_a_duplicate_final_verdict_is_refused(kernel, clock, git):
    attempt = to_review(kernel, clock, git)
    kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                         observed_candidate_sha=CAND, current_head=CAND)
    with pytest.raises(LifecycleError, match="is accepted|duplicates are refused"):
        kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY again",
                             observed_candidate_sha=CAND, current_head=CAND)


def test_a_late_verdict_for_a_superseded_attempt_is_refused(kernel, clock, git):
    attempt = to_review(kernel, clock, git)
    kernel.cancel_attempt(attempt.attempt_id, reason="reviewer never answered; reassigning")
    git.heads["work"] = BASE
    second = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    assert second.fencing_token == 2
    with pytest.raises(LifecycleError, match="not the current attempt"):
        kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"late",
                             observed_candidate_sha=CAND, current_head=CAND)
    with pytest.raises(LifecycleError, match="not the current attempt"):
        kernel.heartbeat(attempt.attempt_id, token=1)


def test_the_repair_cycle_is_a_new_attempt_with_a_higher_token(kernel, clock, git):
    attempt = to_review(kernel, clock, git)
    kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.REPAIR_REQUIRED, payload=b"J-01",
                         observed_candidate_sha=CAND, current_head=CAND)
    git.heads["work"] = BASE
    repair = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    assert repair.fencing_token == 2 and repair.attempt_id == "t-1-a2"
    with pytest.raises(LifecycleError, match="not the current attempt"):
        kernel.heartbeat(attempt.attempt_id, token=1)
    kernel.acknowledge(repair.attempt_id, token=2, base_sha=BASE)
    kernel.record_evidence(repair.attempt_id, token=2, name="pytest", payload=b"ok")
    kernel.record_candidate(repair.attempt_id, token=2, sha=CAND2, evidence_satisfied=("pytest",), clean_worktree=True)
    git.heads["work"] = CAND2
    kernel.dispatch_review(repair.attempt_id, reviewer_principal_id="gpt", packet=b"packet 2", current_head=CAND2)
    admission = kernel.admit_verdict(repair.attempt_id, reviewer=party("gpt", "s2", "/w/r2", CAND2, read_only=True),
                                     verdict=ReviewVerdict.READY, payload=b"READY", observed_candidate_sha=CAND2, current_head=CAND2)
    assert admission.outcome is VerdictOutcome.ACCEPTED
    projected = lifecycle_view(kernel.store, now=clock())["tasks"][0]
    assert projected["attempt_id"] == "t-1-a2" and projected["fencing_token"] == 2
    assert projected["acceptance"]["sha"] == CAND2


# --------------------------------------------------------- integration


def test_integration_requires_acceptance_ancestry_and_the_remote_head(kernel, clock, git):
    attempt = to_review(kernel, clock, git)
    with pytest.raises(LifecycleError, match="not ACCEPTED"):
        kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests")
    kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                         observed_candidate_sha=CAND, current_head=CAND)
    with pytest.raises(LifecycleError, match="not an ancestor"):
        kernel.integrate("t-1", 1, integration_sha=MEMORY, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests")
    with pytest.raises(LifecycleError, match="must land exactly the accepted SHA"):
        kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.FAST_FORWARD, integrated_by="tests")
    with pytest.raises(LifecycleError, match="is at None"):
        kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests", remote="origin")
    git.heads["work"] = MERGED
    with pytest.raises(LifecycleError, match="not an ancestor of"):
        kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=MEMORY, method=IntegrationMethod.MERGE, integrated_by="tests")
    with pytest.raises(LifecycleError, match="none is recorded"):
        kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests")
    git.heads["work"] = BASE
    with pytest.raises(LifecycleError, match="resolves to"):
        kernel.integrate("t-1", 1, integration_sha=CAND, target_base_sha=BASE, method=IntegrationMethod.FAST_FORWARD, integrated_by="tests")
    assert state(kernel) is TaskStatus.ACCEPTED and kernel.store.read_integrations() == ()
    git.remote[("origin", "work")] = CAND
    integration = kernel.integrate("t-1", 1, integration_sha=CAND, target_base_sha=BASE, method=IntegrationMethod.FAST_FORWARD,
                                   integrated_by="tests", remote="origin", gates_evidence=b"all green")
    assert integration.ancestry_verified and integration.remote_head_sha == CAND and integration.integration_candidate is None
    assert state(kernel) is TaskStatus.DONE


def test_a_merge_result_completes_only_as_an_accepted_integration_candidate(kernel, clock, git):
    """K-04. Accepted A; a merge M = A plus work nobody reviewed. M cannot complete the task
    until M itself was recorded, reviewed at its exact SHA and accepted, built on the target base."""
    attempt = to_review(kernel, clock, git)
    kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                         observed_candidate_sha=CAND, current_head=CAND)
    git.heads["work"] = MERGED  # the target now carries the merge
    with pytest.raises(LifecycleError, match="lands more than the accepted candidate"):
        kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests")
    assert state(kernel) is TaskStatus.ACCEPTED and kernel.store.read_integrations() == ()
    assert lifecycle_view(kernel.store, now=clock())["tasks"][0]["stage"] == "ACCEPTED"

    # The merge result becomes a candidate of its own: a task at the target base, the exact SHA
    # M dispatched to an independent reviewer, READY admitted at M.
    kernel.create_task(task(task_id="t-1-integration", kind=TaskKind.INTEGRATION, objective="land t-1 on work", base_sha=BASE))
    merge = kernel.assign("t-1-integration", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(merge.attempt_id, token=1, base_sha=BASE)
    kernel.record_evidence(merge.attempt_id, token=1, name="pytest", payload=b"3085 passed")
    git.diffs[(BASE, MERGED)] = ("f.py", "g.py")
    kernel.record_candidate(merge.attempt_id, token=1, sha=MERGED, evidence_satisfied=("pytest",), clean_worktree=True)
    kernel.dispatch_review(merge.attempt_id, reviewer_principal_id="gpt", packet=b"packet: the merge", current_head=MERGED)
    kernel.admit_verdict(merge.attempt_id, reviewer=party("gpt", "s-m", "/w/m", MERGED, read_only=True), verdict=ReviewVerdict.READY,
                         payload=b"READY at M", observed_candidate_sha=MERGED, current_head=MERGED)
    # built on the wrong base: refused
    with pytest.raises(LifecycleError, match="not on the target base"):
        kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=CAND, method=IntegrationMethod.MERGE, integrated_by="tests")
    integration = kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests")
    assert integration.integration_candidate.task_id == "t-1-integration"
    assert integration.integration_candidate.accepted_sha == MERGED and integration.local_head_sha == MERGED
    assert state(kernel) is TaskStatus.DONE
    projected = lifecycle_view(kernel.store, now=clock())
    done = next(t for t in projected["tasks"] if t["task_id"] == "t-1")
    assert done["stage"] == "COMPLETE" and done["integration"]["integration_candidate"]["task_id"] == "t-1-integration"


def test_complete_needs_every_record_and_a_bare_done_state_is_unknown(kernel, clock, git):
    attempt = to_review(kernel, clock, git)
    kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                         observed_candidate_sha=CAND, current_head=CAND)
    kernel.integrate("t-1", 1, integration_sha=CAND, target_base_sha=BASE, method=IntegrationMethod.FAST_FORWARD, integrated_by="tests")
    projected = lifecycle_view(kernel.store, now=clock())["tasks"][0]
    assert projected["stage"] == "COMPLETE"
    assert projected["integration"]["sha"] == CAND and projected["acceptance"]["sha"] == CAND
    (kernel.store.integrations_dir / "t-1.r1.json").unlink()  # the state says done; the evidence is gone
    projected = lifecycle_view(kernel.store, now=clock())["tasks"][0]
    assert projected["stage"] == "UNKNOWN"
    assert "record is missing" in projected["stage_reason"]


# ------------------------------------------------------- block/resume


def test_block_and_resume_recompute_the_stage_from_the_records(kernel, clock, git, tmp_path):
    attempt = to_candidate(kernel, clock, git)
    kernel.block("t-1", 1, blocker_class=BlockerClass.OWNER_ONLY, reason="needs the owner", owner_gate=True)
    runtime = kernel.store.read_task_state("t-1", 1)
    assert runtime.status is TaskStatus.OWNER_GATE and runtime.owner_gate and runtime.attempt_id == attempt.attempt_id
    with pytest.raises(LifecycleError, match="needs one of"):
        kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"p", current_head=CAND)
    ledger = owner_ledger(tmp_path / "owner-judgments.jsonl",
                          owner_judgment(kernel, "t-1", 1, explanation="owner message 5: proceed with the fixture"))
    kernel.resume("t-1", 1, note="owner answered", owner_judgment_id="j-gate-1", owner_ledger_path=ledger)
    assert state(kernel) is TaskStatus.EVIDENCE_READY  # a candidate exists, no dispatch yet
    resolution = kernel.store.read_owner_resolutions("t-1", 1)[0]
    assert (resolution.resolved_by, resolution.gate_reason) == ("owner", "needs the owner")
    projected = lifecycle_view(kernel.store, now=clock())["tasks"][0]
    assert projected["owner_resolutions"][0]["resolution"] == "owner message 5: proceed with the fixture"
    assert projected["owner_resolutions"][0]["judgment_id"] == "j-gate-1"
    assert projected["history"][-1]["note"].startswith("owner gate lifted by judgment j-gate-1 of owner")
    with pytest.raises(LifecycleError, match="needs a blocker class"):
        kernel.block("t-1", 1, blocker_class=BlockerClass.NONE, reason="x")


def test_a_rejected_candidate_stays_rejected_across_block_and_resume(kernel, clock, git):
    """K-05. REVIEWING -> admitted REPAIR_REQUIRED -> BLOCKED -> resume -> REJECTED, never REVIEWING."""
    attempt = to_review(kernel, clock, git)
    kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.REPAIR_REQUIRED, payload=b"J-01",
                         observed_candidate_sha=CAND, current_head=CAND)
    assert state(kernel) is TaskStatus.REJECTED
    kernel.block("t-1", 1, blocker_class=BlockerClass.TRANSIENT, reason="CI runners down")
    kernel.resume("t-1", 1, note="runners back")
    assert state(kernel) is TaskStatus.REJECTED
    with pytest.raises(LifecycleError, match="needs one of"):  # the rejected candidate cannot take a late READY
        kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                             observed_candidate_sha=CAND, current_head=CAND)
    # a refused verdict decides nothing: a review with only a refused verdict resumes as REVIEWING
    kernel.create_task(task(task_id="t-2"))
    second = to_review(kernel, clock, git, task_id="t-2")
    kernel.admit_verdict(second.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                         observed_candidate_sha=BASE, current_head=CAND)  # observed the wrong SHA: refused
    kernel.block("t-2", 1, blocker_class=BlockerClass.TRANSIENT, reason="pause")
    kernel.resume("t-2", 1, note="go")
    assert kernel.store.read_task_state("t-2", 1).status is TaskStatus.REVIEWING
    # and an accepted one resumes as ACCEPTED
    kernel.admit_verdict(second.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                         observed_candidate_sha=CAND, current_head=CAND)
    kernel.block("t-2", 1, blocker_class=BlockerClass.TRANSIENT, reason="pause")
    kernel.resume("t-2", 1, note="go")
    assert kernel.store.read_task_state("t-2", 1).status is TaskStatus.ACCEPTED


def test_a_revision_cannot_supersede_an_owner_gate_without_the_owners_recorded_resolution(kernel, clock, git, tmp_path):
    """K-02. OWNER_GATE r1 -> create r2 -> refused, r1 unchanged. Only the owner's recorded
    resolution lifts the gate; then the live attempt is cancelled; only then does r2 supersede r1."""
    attempt = to_candidate(kernel, clock, git)
    kernel.block("t-1", 1, blocker_class=BlockerClass.OWNER_ONLY, reason="the owner must decide the fixture", owner_gate=True)
    state_path = kernel.store.task_states_dir / "t-1.r1.json"
    before = state_path.read_bytes()
    with pytest.raises(LifecycleError, match="cannot supersede an owner gate"):
        kernel.create_task(task(revision=2, base_sha=CAND))
    assert state_path.read_bytes() == before
    assert kernel.store.read_task("t-1", 2) is None and kernel.store.read_task_state("t-1", 2) is None
    with pytest.raises(LifecycleError, match="owner judgment the kernel can verify"):
        kernel.resume("t-1", 1, note="lifting")
    ledger = owner_ledger(tmp_path / "l.jsonl", owner_judgment(kernel, "t-1", 1, principal="gpt", session="gpt-s"))
    with pytest.raises(LifecycleError, match="not a registered owner principal"):
        kernel.resume("t-1", 1, note="lifting", owner_judgment_id="j-gate-1", owner_ledger_path=ledger)
    assert state_path.read_bytes() == before and kernel.store.read_owner_resolutions("t-1", 1) == ()
    ledger = owner_ledger(tmp_path / "l.jsonl", owner_judgment(kernel, "t-1", 1, explanation="owner message 5: use the fixture"))
    kernel.resume("t-1", 1, note="lifting", owner_judgment_id="j-gate-1", owner_ledger_path=ledger)
    assert kernel.store.read_owner_resolutions("t-1", 1)[0].resolution == "owner message 5: use the fixture"
    assert state(kernel) is TaskStatus.EVIDENCE_READY
    with pytest.raises(LifecycleError, match="live attempt"):
        kernel.create_task(task(revision=2, base_sha=CAND))
    kernel.cancel_attempt(attempt.attempt_id, reason="superseded by the owner's decision")
    kernel.create_task(task(revision=2, base_sha=CAND))
    assert kernel.store.read_task_state("t-1", 1).status is TaskStatus.OBSOLETE
    # a transient or deterministic blocker is not the owner's: a new revision at a new base repairs it
    kernel.create_task(task(task_id="t-3"))
    kernel.block("t-3", 1, blocker_class=BlockerClass.DETERMINISTIC, reason="base has the age-days defect")
    kernel.create_task(task(task_id="t-3", revision=2, base_sha=CAND))
    assert kernel.store.read_task_state("t-3", 1).status is TaskStatus.OBSOLETE


def test_an_owner_gate_is_lifted_only_by_an_owner_judgment_bound_to_the_gate(kernel, clock, git, tmp_path):
    """K-07. Naming the owner is not the owner. The gate lifts only for an effective APPROVED
    judgment, in the owner's ledger, by an owner-role principal in a named session, about
    exactly this gate (proposal id and fingerprint), for this task, revision and attempt."""
    to_candidate(kernel, clock, git)
    kernel.block("t-1", 1, blocker_class=BlockerClass.OWNER_ONLY, reason="the owner must decide the fixture", owner_gate=True)
    gate = kernel.gate_proposal("t-1", 1)
    assert gate["proposal_id"] == "owner-gate:t-1:r1:t4" and gate["payload"]["blocker_reason"] == "the owner must decide the fixture"
    state_path = kernel.store.task_states_dir / "t-1.r1.json"
    before = state_path.read_bytes()
    ledger_path = tmp_path / "owner-judgments.jsonl"

    def refused(match: str, judgment_id: str = "j-gate-1", *records: JudgmentRecord) -> None:
        ledger = owner_ledger(ledger_path, *records) if records else str(ledger_path)
        with pytest.raises(LifecycleError, match=match):
            kernel.resume("t-1", 1, note="lifting", owner_judgment_id=judgment_id, owner_ledger_path=ledger)
        assert state_path.read_bytes() == before
        assert kernel.store.read_owner_resolutions("t-1", 1) == ()

    with pytest.raises(LifecycleError, match="owner judgment the kernel can verify"):
        kernel.resume("t-1", 1, note="lifting")
    refused("cannot be read")  # no ledger file at all
    refused("not a registered owner principal", "j-gate-1", owner_judgment(kernel, "t-1", 1, principal="claude", session="claude-s"))
    refused("is not in the owner ledger", "j-someone-elses", owner_judgment(kernel, "t-1", 1))
    refused("not this gate", "j-gate-1", owner_judgment(kernel, "t-1", 1, task_revision=2))
    refused("not this gate", "j-gate-1", owner_judgment(kernel, "t-1", 1, attempt_id="t-1-a9"))
    refused("not this gate", "j-gate-1", owner_judgment(kernel, "t-1", 1, proposal={**gate, "proposal_fingerprint": "0" * 64}))
    refused("not this gate", "j-gate-1", owner_judgment(kernel, "t-1", 1, proposal={**gate, "proposal_id": "owner-gate:t-1:r1:t3"}))
    refused("the gate stays", "j-gate-1", owner_judgment(kernel, "t-1", 1, decision=OwnerDecision.DECLINED, reason=ReasonCode.NOT_NOW))
    approved = owner_judgment(kernel, "t-1", 1, judgment_id="j-first")
    withdrawn = owner_judgment(kernel, "t-1", 1, judgment_id="j-second", decision=OwnerDecision.DECLINED,
                               reason=ReasonCode.RISK_TOO_HIGH, corrects="j-first")
    refused("was corrected by 'j-second'", "j-first", approved, withdrawn)
    refused("the gate stays", "j-second", approved, withdrawn)
    (tmp_path / "bad.jsonl").write_text('{"judgment_id": "x"}\n')
    with pytest.raises(LifecycleError, match="not a valid judgment"):
        kernel.resume("t-1", 1, note="lifting", owner_judgment_id="x", owner_ledger_path=str(tmp_path / "bad.jsonl"))

    ledger = owner_ledger(ledger_path, owner_judgment(kernel, "t-1", 1, explanation="proceed with the fixture"))
    kernel.resume("t-1", 1, note="lifting", owner_judgment_id="j-gate-1", owner_ledger_path=ledger)
    resolution = kernel.store.read_owner_resolutions("t-1", 1)[0]
    assert (resolution.judgment_id, resolution.resolved_by, resolution.owner_session_id) == ("j-gate-1", "owner", "owner-session-1")
    assert resolution.ledger_sha256 == hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    assert (resolution.proposal_id, resolution.proposal_fingerprint) == (gate["proposal_id"], gate["proposal_fingerprint"])
    assert resolution.decision == "APPROVED" and resolution.resolution == "proceed with the fixture"
    assert state(kernel) is TaskStatus.EVIDENCE_READY
    with pytest.raises(LifecycleError, match="not owner-gated"):
        kernel.gate_proposal("t-1", 1)


def test_a_move_out_of_scope_is_seen_in_a_real_repository(tmp_path, clock):
    """K-06. A candidate that moves forbidden/secret.txt to allowed/secret.txt: git's rename
    detection would report only the destination; the kernel records both paths, and the scope
    gate refuses the dispatch because forbidden/ was touched."""
    repo = git_repo(tmp_path / "code")
    (repo / "forbidden").mkdir()
    (repo / "forbidden" / "secret.txt").write_text("the same bytes before and after\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    base = git_out(repo, "rev-parse", "HEAD")
    (repo / "allowed").mkdir()
    subprocess.run(["git", "mv", "forbidden/secret.txt", "allowed/secret.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "move"], cwd=repo, check=True)
    candidate = git_out(repo, "rev-parse", "HEAD")
    collapsed = git_out(repo, "diff", "--name-only", base, candidate).splitlines()
    assert "allowed/secret.txt" in collapsed  # what the old derivation saw; with rename detection it is all it saw
    facts = GitFacts(repo)
    assert facts.changed_paths(base, candidate) == ("allowed/secret.txt", "forbidden/secret.txt")

    kernel = Kernel(LifecycleStore(tmp_path / "engineering"), REGISTRY, facts, clock=clock, journal=False)
    kernel.create_task(task(base_sha=base, product_memory_sha=base, target_branch="main", allowed_paths=("allowed",)))
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=party("claude", "s", "/w", base))
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=base)
    kernel.record_evidence(attempt.attempt_id, token=1, name="pytest", payload=b"ok")
    with pytest.raises(LifecycleError, match="omitted: forbidden/secret.txt"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=candidate, changed_paths=("allowed/secret.txt",),
                                evidence_satisfied=("pytest",), clean_worktree=True)
    result = kernel.record_candidate(attempt.attempt_id, token=1, sha=candidate, evidence_satisfied=("pytest",), clean_worktree=True)
    assert result.changed_paths == ("allowed/secret.txt", "forbidden/secret.txt")
    with pytest.raises(LifecycleError, match="outside task scope: forbidden/secret.txt"):
        kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"p", current_head=candidate)
    assert kernel.store.read_task_state("t-1", 1).status is TaskStatus.EVIDENCE_READY
    assert kernel.store.read_dispatches("t-1", attempt.attempt_id) == ()


def test_a_journal_commit_failure_after_staging_leaves_tree_index_and_head_as_before(tmp_path, clock, git):
    """K-08. The commit fails after git add (a pre-commit hook refuses). The verb is refused, and
    the working tree, the index and HEAD are exactly what they were before it: nothing attempted
    is on disk and nothing attempted is staged."""
    repo = git_repo(tmp_path / "state")
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    kernel = Kernel(LifecycleStore(repo / "engineering"), REGISTRY, git, operator="tests", clock=clock, journal=True)
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    head_before = git_out(repo, "rev-parse", "HEAD")
    assert git_out(repo, "status", "--porcelain") == ""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(JournalError, match="git commit failed"):
        kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    assert git_out(repo, "status", "--porcelain") == ""  # working tree as before
    assert git_out(repo, "diff", "--cached", "--name-only") == ""  # index as before: nothing staged
    assert git_out(repo, "rev-parse", "HEAD") == head_before
    assert kernel.store.read_task_state("t-1", 1).status is TaskStatus.ASSIGNED
    assert [e.kind for e in kernel.store.read_events("t-1", attempt.attempt_id)] == [EventKind.OPENED]
    hook.unlink()
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    assert git_out(repo, "rev-parse", "HEAD") != head_before and git_out(repo, "status", "--porcelain") == ""
    assert kernel.store.read_task_state("t-1", 1).status is TaskStatus.RUNNING


def test_a_superseded_or_withdrawn_integration_candidate_acceptance_cannot_complete_a_merge(kernel, clock, git):
    """K-09. The integration candidate's acceptance is history once its revision is withdrawn
    (blocked) or superseded (r2); history authorises nothing."""
    attempt = to_review(kernel, clock, git)
    kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                         observed_candidate_sha=CAND, current_head=CAND)
    git.heads["work"] = MERGED
    kernel.create_task(task(task_id="t-1-integration", kind=TaskKind.INTEGRATION, objective="land t-1 on work", base_sha=BASE))
    merge = kernel.assign("t-1-integration", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(merge.attempt_id, token=1, base_sha=BASE)
    kernel.record_evidence(merge.attempt_id, token=1, name="pytest", payload=b"ok")
    kernel.record_candidate(merge.attempt_id, token=1, sha=MERGED, evidence_satisfied=("pytest",), clean_worktree=True)
    kernel.dispatch_review(merge.attempt_id, reviewer_principal_id="gpt", packet=b"packet", current_head=MERGED)
    kernel.admit_verdict(merge.attempt_id, reviewer=party("gpt", "s-m", "/w/m", MERGED, read_only=True), verdict=ReviewVerdict.READY,
                         payload=b"READY at M", observed_candidate_sha=MERGED, current_head=MERGED)
    assert len(kernel.store.read_acceptances("t-1-integration")) == 1
    # withdrawn: a defect is found in the merge and its revision is blocked
    kernel.block("t-1-integration", 1, blocker_class=BlockerClass.DETERMINISTIC, reason="defect found in the merge result")
    with pytest.raises(LifecycleError, match="is blocked, not accepted or done"):
        kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests")
    # superseded: revision 2 replaces it; the r1 acceptance stays on disk, and is history
    kernel.create_task(task(task_id="t-1-integration", revision=2, kind=TaskKind.INTEGRATION, objective="land t-1 on work, again", base_sha=BASE))
    assert kernel.store.read_task_state("t-1-integration", 1).status is TaskStatus.OBSOLETE
    assert len(kernel.store.read_acceptances("t-1-integration")) == 1
    with pytest.raises(LifecycleError, match="superseded by revision 2; its acceptance is history"):
        kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests")
    assert state(kernel) is TaskStatus.ACCEPTED and kernel.store.read_integrations() == ()


# ---------------------------------------------------- one writer, whole records


def test_two_competing_assignments_cannot_both_write(tmp_path, clock, git):
    """K-03. Kernel B runs its assign while kernel A holds the writer lock mid-verb (after A's
    checks, before A's first write): B is refused by the lock and has written nothing. When B
    tries again after A, the task is no longer READY. One attempt, one opened event, one token."""
    root = tmp_path / "engineering"
    a = Kernel(LifecycleStore(root), REGISTRY, git, clock=clock, journal=False)
    b = Kernel(LifecycleStore(root), REGISTRY, git, clock=clock, journal=False, lock_timeout_s=0)
    a.create_task(task())
    refusals: list[str] = []

    def while_a_holds_the_lock(verb: str) -> None:
        if verb == "assign":
            with pytest.raises(StoreBusyError) as refused:
                b.assign("t-1", 1, worker_id="w2", worker=party("claude", "s2", "/w2", BASE))
            refusals.append(str(refused.value))
            assert b.store.read_attempts() == () and b.store.read_task_state("t-1", 1).status is TaskStatus.READY

    a.on_validated = while_a_holds_the_lock
    first = a.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    assert len(refusals) == 1 and "writer lock" in refusals[0]
    with pytest.raises(LifecycleError, match="only a READY or REJECTED"):
        b.assign("t-1", 1, worker_id="w2", worker=party("claude", "s2", "/w2", BASE))
    attempts = a.store.read_attempts()
    assert [x.attempt_id for x in attempts] == [first.attempt_id] and [x.fencing_token for x in attempts] == [1]
    assert [e.kind for e in a.store.read_events("t-1", first.attempt_id)] == [EventKind.OPENED]
    assert a.store.read_task_state("t-1", 1).attempt_id == first.attempt_id
    # the lock is released with the verb: B can write once A is done and the task allows it
    a.cancel_attempt(first.attempt_id, reason="handing over")
    second = b.assign("t-1", 1, worker_id="w2", worker=party("claude", "s2", "/w2", BASE))
    assert second.fencing_token == 2


def test_a_refusal_after_the_first_write_leaves_no_partial_record(kernel, clock, git):
    """K-03, the race without the lock: the state file changes under the verb between its checks
    and its compare-and-swap. The swap refuses; the attempt and the opened event written before
    it are rolled back, so the refusal left nothing behind."""
    kernel.create_task(task())
    state_path = kernel.store.task_states_dir / "t-1.r1.json"

    def another_writer_got_in(verb: str) -> None:
        if verb == "assign":
            current = kernel.store.read_task_state("t-1", 1)
            moved = current.model_copy(update={"transition_seq": current.transition_seq + 1})
            JsonRecordStore._atomic_write(state_path, JsonRecordStore._canonical_bytes(moved))

    kernel.on_validated = another_writer_got_in
    with pytest.raises(StateConflictError, match="stale task state"):
        kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    assert kernel.store.read_attempts() == ()
    assert kernel.store.read_events("t-1", "t-1-a1") == ()
    assert not (kernel.store.attempts_dir / "t-1" / "t-1-a1.json").exists()
    runtime = kernel.store.read_task_state("t-1", 1)
    assert runtime.status is TaskStatus.READY and runtime.attempt_id is None
    kernel.on_validated = None
    # the foreign write left seq 1 behind; the next verb reads it fresh under the lock and moves on from it
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    assert attempt.fencing_token == 1 and kernel.store.read_task_state("t-1", 1).transition_seq == 2


# ------------------------------------------------------------ backfill


def test_backfill_needs_the_marker_and_an_evidence_reference(kernel, clock):
    kernel.create_task(task())
    earlier = T0 - timedelta(hours=2)
    with pytest.raises(LifecycleError, match="must be marked backfilled"):
        kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, at=earlier)
    with pytest.raises(LifecycleError, match="name the evidence"):
        kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, at=earlier, backfilled=True)
    with pytest.raises(LifecycleError, match="future"):
        kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, at=T0 + timedelta(hours=1))
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, at=earlier, backfilled=True,
                            evidence_ref="commit 1ec236a; CI run 35771824941")
    assert attempt.backfilled and attempt.opened_at == earlier and attempt.recorded_at == T0
    event = kernel.store.read_events("t-1", attempt.attempt_id)[0]
    assert event.backfilled and event.at == earlier and event.evidence_ref.startswith("commit")
    assert lifecycle_view(kernel.store, now=clock())["tasks"][0]["backfilled"] is True


# ------------------------------------------------------------- journal


def test_the_journal_commits_every_write_when_the_store_is_a_checkout(tmp_path, clock, git):
    repo = tmp_path / "state"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    kernel = Kernel(LifecycleStore(repo / "engineering"), REGISTRY, git, operator="tests", clock=clock, journal=True)
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    log = subprocess.run(["git", "log", "--format=%an|%s"], cwd=repo, capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(log) == 4  # init + three verbs
    assert log[0].startswith("CLIVE kernel|kernel: t-1 t-1-a1 acknowledged")
    assert "operator: tests" in log[0]
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert dirty == ""
    assert len(kernel.journal_shas) == 3


def test_a_journal_failure_rolls_the_store_back_to_the_last_commit(tmp_path, clock, git, monkeypatch):
    repo = tmp_path / "state"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
    kernel = Kernel(LifecycleStore(repo / "engineering"), REGISTRY, git, operator="tests", clock=clock, journal=True)
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    events_before = kernel.store.read_events("t-1", attempt.attempt_id)

    def git_is_down(root, message):
        raise RuntimeError("git down")

    monkeypatch.setattr(lifecycle_module, "git_journal", git_is_down)
    with pytest.raises(RuntimeError, match="git down"):
        kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    assert kernel.store.read_events("t-1", attempt.attempt_id) == events_before
    assert kernel.store.read_task_state("t-1", 1).status is TaskStatus.ASSIGNED
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert dirty == ""


def test_the_view_is_json_serialisable_and_names_its_store(kernel, clock, git):
    to_review(kernel, clock, git)
    projected = lifecycle_view(kernel.store, now=clock())
    assert json.loads(json.dumps(projected))["tasks"][0]["stage"] == "REVIEWING"
    assert projected["store_root"] == str(kernel.store.root)
    assert projected["reviewing_by_principal"]["gpt"]["candidate_sha"] == CAND


# ------------------------------------------------ the projection reads records


def roster(store_root: Path, worktree: Path) -> dict:
    return {
        "fresh_window_s": 900,
        "stale_window_s": 3600,
        "engineering_store": str(store_root),
        "workers": [
            {"worker_id": "w1", "display_name": "W One", "role": "builder", "principal_id": "claude",
             "probe": {"kind": "worktree_process", "worktree": str(worktree)}},
            {"worker_id": "gpt-reviewer", "display_name": "GPT", "role": "reviewer", "principal_id": "gpt",
             "probe": {"kind": "records_only"}},
        ],
    }


def by_id(built: dict, worker_id: str) -> dict:
    return next(w for w in built["workers"] if w["worker_id"] == worker_id)


def test_records_place_a_worker_and_the_probe_only_reconciles(kernel, clock, git, tmp_path, monkeypatch):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "f.py").write_text("x = 1")
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: [])  # nothing runs here
    r = roster(kernel.store.root, worktree)

    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, lease_duration_s=300)
    built = view.build_view(r)
    w1 = by_id(built, "w1")
    assert w1["status"] == view.ASSIGNED and w1["status_source"] == "records+probe"
    assert w1["task_id"] == "t-1" and w1["attempt_id"] == "t-1-a1"
    assert w1["reconciliation"]["consistent"] is False
    assert "found no agent process" in w1["status_reason"]
    assert built["totals"]["assigned"] == 1 and built["totals"]["online"] == 0
    assert by_id(built, "gpt-reviewer")["status"] == view.UNKNOWN

    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: [
        {"pid": 7, "cmdline": "claude", "cpu_seconds": 1.0, "started_at": "2026-09-22T22:00:00Z", "is_agent": True}])
    monkeypatch.setattr(view.time, "time", lambda: clock().timestamp())
    built = view.build_view(r)
    w1 = by_id(built, "w1")
    assert w1["status"] == view.BUILDING and w1["status_source"] == "records"
    assert w1["reconciliation"]["consistent"] is True
    assert w1["last_heartbeat"] is None  # no heartbeat event yet: nothing is invented
    clock.advance(100)
    kernel.heartbeat(attempt.attempt_id, token=1)
    built = view.build_view(r)
    assert by_id(built, "w1")["last_heartbeat"] == "2026-09-22T22:01:40Z"

    clock.advance(400)  # past the 300s lease with no heartbeat
    built = view.build_view(r)
    w1 = by_id(built, "w1")
    assert w1["status"] == view.STALE
    assert "lease expired" in w1["status_reason"]
    assert built["totals"]["stale"] == 1 and built["totals"]["working"] == 0


def test_a_review_dispatch_places_the_reviewer_principal_and_completion_reads_complete(kernel, clock, git, tmp_path, monkeypatch):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: [])
    monkeypatch.setattr(view.time, "time", lambda: clock().timestamp())
    r = roster(kernel.store.root, worktree)
    attempt = to_review(kernel, clock, git)
    built = view.build_view(r)
    gpt = by_id(built, "gpt-reviewer")
    assert gpt["status"] == view.REVIEWING and gpt["candidate_sha"] == CAND
    assert gpt["review_state"] == "reviewing" and gpt["reconciliation"]["consistent"] is True
    assert by_id(built, "w1")["status"] == view.IDLE
    assert by_id(built, "w1")["review_state"] == "under review by gpt"
    assert built["tasks"][0]["stage"] == "REVIEWING"

    kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                         observed_candidate_sha=CAND, current_head=CAND)
    kernel.integrate("t-1", 1, integration_sha=CAND, target_base_sha=BASE, method=IntegrationMethod.FAST_FORWARD, integrated_by="tests")
    built = view.build_view(r)
    w1 = by_id(built, "w1")
    assert w1["status"] == view.COMPLETE and w1["review_state"] == "accepted and integrated"
    assert built["tasks"][0]["stage"] == "COMPLETE" and built["totals"]["complete"] == 1
    assert by_id(built, "gpt-reviewer")["status"] == view.UNKNOWN  # nothing open for it any more

    clock.advance(3601)  # the completion window closes; the probe speaks again
    built = view.build_view(r)
    assert by_id(built, "w1")["status"] == view.OFFLINE


def test_a_missing_or_broken_store_is_a_named_problem_not_an_empty_campus(tmp_path, monkeypatch):
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: [])
    r = roster(tmp_path / "nowhere", tmp_path)
    built = view.build_view(r)
    assert built["engineering"]["problem"].startswith("declared engineering store")
    assert built["tasks"] == []
    assert by_id(built, "w1")["status_source"] == "probe"
    broken = tmp_path / "broken"
    (broken / "tasks").mkdir(parents=True)
    (broken / "tasks" / "t.r1.json").write_text("{not json")
    built = view.build_view(roster(broken, tmp_path))
    assert built["engineering"]["problem"].startswith("engineering store unreadable")


def test_attempt_ids_are_unique_across_tasks_not_just_within_one(kernel):
    kernel.create_task(task())
    kernel.create_task(task(task_id="t-2"))
    first = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    second = kernel.assign("t-2", 1, worker_id="w2", worker=party("claude", "s2", "/w2", BASE))
    assert first.attempt_id == "t-1-a1" and second.attempt_id == "t-2-a1"
    kernel.acknowledge(second.attempt_id, token=1, base_sha=BASE)  # names the attempt by id alone
    assert kernel.store.read_task_state("t-2", 1).status is TaskStatus.RUNNING
    assert kernel.store.read_task_state("t-1", 1).status is TaskStatus.ASSIGNED
    with pytest.raises(LifecycleError, match="already exists in this store"):
        kernel.cancel_attempt(first.attempt_id, reason="x") and kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, attempt_id="t-2-a1")


def test_a_worker_holding_two_live_assignments_is_placed_by_the_more_active_one(kernel, clock, git):
    attempt = to_review(kernel, clock, git)  # t-1 under review: the author waits
    kernel.create_task(task(task_id="t-2", stream_id="other"))
    second = kernel.assign("t-2", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(second.attempt_id, token=1, base_sha=BASE)
    projected = lifecycle_view(kernel.store, now=clock())
    placed = projected["assignments_by_worker"]["w1"]
    assert placed["task_id"] == "t-2" and placed["stage"] == "RUNNING"
    assert placed["also_assigned"] == ["t-1 r1 (REVIEWING)"]
    assert projected["reviewing_by_principal"]["gpt"]["attempt_id"] == attempt.attempt_id
