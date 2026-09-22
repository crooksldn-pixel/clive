"""The kernel writes the lifecycle; these tests are mostly about what it refuses to write.

Every verb is exercised against a fake git (four answers, no shell) and a fixed
clock, so the only things under test are the records, the fences and the order.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.orchestrator.contracts import (
    BlockerClass,
    EngineeringTask,
    TaskKind,
    TaskStatus,
)
from app.orchestrator.lifecycle import (
    Attempt,
    EventKind,
    IntegrationMethod,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
    VerdictOutcome,
    lifecycle_view,
)
from app.orchestrator.review_acceptance import ReviewVerdict
from app.orchestrator.routing import Party, Principal, PrincipalKind, SessionContext, Workspace
from app.orchestrator.store import RecordConflictError
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

    def commit_exists(self, sha: str) -> bool:
        return sha in self.commits

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
        "owner": {"principal_id": "owner", "may_review": True},
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


def to_candidate(kernel: Kernel, clock: Clock, git: FakeGit, *, sha: str = CAND) -> Attempt:
    """The happy path up to a recorded candidate, shared by the later tests."""
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, lease_duration_s=300)
    kernel.acknowledge(attempt.attempt_id, token=attempt.fencing_token, base_sha=BASE)
    clock.advance(10)
    kernel.record_evidence(attempt.attempt_id, token=attempt.fencing_token, name="pytest", payload=b"3000 passed")
    kernel.record_candidate(attempt.attempt_id, token=attempt.fencing_token, sha=sha, changed_paths=("f.py",),
                            evidence_satisfied=("pytest",), clean_worktree=True)
    git.heads["work"] = sha
    return attempt


def to_review(kernel, clock, git):
    attempt = to_candidate(kernel, clock, git)
    kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"packet", current_head=CAND)
    return attempt


def state(kernel: Kernel) -> TaskStatus:
    return kernel.store.read_task_state("t-1", 1).status


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


# ----------------------------------------------------------- assignment


def test_assign_records_attempt_lease_token_and_dispatch_identity(kernel):
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR, lease_duration_s=300)
    assert attempt.fencing_token == 1 and attempt.attempt_id == "attempt-1"
    assert attempt.worker == AUTHOR and attempt.worker_id == "w1"
    assert state(kernel) is TaskStatus.ASSIGNED
    runtime = kernel.store.read_task_state("t-1", 1)
    assert (runtime.attempt_id, runtime.worker_id) == ("attempt-1", "w1")
    events = kernel.store.read_events("t-1", "attempt-1")
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
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, changed_paths=(), evidence_satisfied=(), clean_worktree=True)


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
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, changed_paths=(), evidence_satisfied=("pytest",), clean_worktree=True)
    kernel.record_evidence(attempt.attempt_id, token=1, name="pytest", payload=b"ok")
    with pytest.raises(LifecycleError, match="required evidence not satisfied"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, changed_paths=(), evidence_satisfied=(), clean_worktree=True)
    with pytest.raises(LifecycleError, match="not a commit"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha="9" * 40, changed_paths=(), evidence_satisfied=("pytest",), clean_worktree=True)
    with pytest.raises(LifecycleError, match="does not descend"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=MEMORY, changed_paths=(), evidence_satisfied=("pytest",), clean_worktree=True)
    assert state(kernel) is TaskStatus.RUNNING


def test_one_candidate_per_attempt(kernel, clock, git):
    attempt = to_candidate(kernel, clock, git)
    with pytest.raises(LifecycleError, match="already recorded a candidate"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND2, changed_paths=(), evidence_satisfied=("pytest",), clean_worktree=True)
    assert state(kernel) is TaskStatus.EVIDENCE_READY


def test_candidate_publication_is_verified_against_the_remote(kernel, git):
    kernel.create_task(task())
    attempt = kernel.assign("t-1", 1, worker_id="w1", worker=AUTHOR)
    kernel.acknowledge(attempt.attempt_id, token=1, base_sha=BASE)
    kernel.record_evidence(attempt.attempt_id, token=1, name="pytest", payload=b"ok")
    with pytest.raises(LifecycleError, match="publish first"):
        kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, changed_paths=(), evidence_satisfied=("pytest",), clean_worktree=True, remote="origin")
    git.remote[("origin", "work")] = CAND
    result = kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, changed_paths=(), evidence_satisfied=("pytest",), clean_worktree=True, remote="origin")
    assert result.result_sha == CAND
    assert kernel.store.read_events("t-1", "attempt-1")[-1].note == "published at origin"


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
    kernel.record_candidate(attempt.attempt_id, token=1, sha=CAND, changed_paths=(), evidence_satisfied=("pytest",), clean_worktree=True)
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
    assert repair.fencing_token == 2 and repair.attempt_id == "attempt-2"
    with pytest.raises(LifecycleError, match="not the current attempt"):
        kernel.heartbeat(attempt.attempt_id, token=1)
    kernel.acknowledge(repair.attempt_id, token=2, base_sha=BASE)
    kernel.record_evidence(repair.attempt_id, token=2, name="pytest", payload=b"ok")
    kernel.record_candidate(repair.attempt_id, token=2, sha=CAND2, changed_paths=(), evidence_satisfied=("pytest",), clean_worktree=True)
    git.heads["work"] = CAND2
    kernel.dispatch_review(repair.attempt_id, reviewer_principal_id="gpt", packet=b"packet 2", current_head=CAND2)
    admission = kernel.admit_verdict(repair.attempt_id, reviewer=party("gpt", "s2", "/w/r2", CAND2, read_only=True),
                                     verdict=ReviewVerdict.READY, payload=b"READY", observed_candidate_sha=CAND2, current_head=CAND2)
    assert admission.outcome is VerdictOutcome.ACCEPTED
    projected = lifecycle_view(kernel.store, now=clock())["tasks"][0]
    assert projected["attempt_id"] == "attempt-2" and projected["fencing_token"] == 2
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
    assert state(kernel) is TaskStatus.ACCEPTED
    git.remote[("origin", "work")] = MERGED
    integration = kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE,
                                   integrated_by="tests", remote="origin", gates_evidence=b"all green")
    assert integration.ancestry_verified and integration.remote_head_sha == MERGED
    assert state(kernel) is TaskStatus.DONE


def test_complete_needs_every_record_and_a_bare_done_state_is_unknown(kernel, clock, git):
    attempt = to_review(kernel, clock, git)
    kernel.admit_verdict(attempt.attempt_id, reviewer=REVIEWER, verdict=ReviewVerdict.READY, payload=b"READY",
                         observed_candidate_sha=CAND, current_head=CAND)
    kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests")
    projected = lifecycle_view(kernel.store, now=clock())["tasks"][0]
    assert projected["stage"] == "COMPLETE"
    assert projected["integration"]["sha"] == MERGED and projected["acceptance"]["sha"] == CAND
    (kernel.store.integrations_dir / "t-1.r1.json").unlink()  # the state says done; the evidence is gone
    projected = lifecycle_view(kernel.store, now=clock())["tasks"][0]
    assert projected["stage"] == "UNKNOWN"
    assert "record is missing" in projected["stage_reason"]


# ------------------------------------------------------- block/resume


def test_block_and_resume_recompute_the_stage_from_the_records(kernel, clock, git):
    attempt = to_candidate(kernel, clock, git)
    kernel.block("t-1", 1, blocker_class=BlockerClass.OWNER_ONLY, reason="needs the owner", owner_gate=True)
    runtime = kernel.store.read_task_state("t-1", 1)
    assert runtime.status is TaskStatus.OWNER_GATE and runtime.owner_gate and runtime.attempt_id == attempt.attempt_id
    with pytest.raises(LifecycleError, match="needs one of"):
        kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"p", current_head=CAND)
    kernel.resume("t-1", 1, note="owner answered")
    assert state(kernel) is TaskStatus.EVIDENCE_READY  # a candidate exists, no dispatch yet
    with pytest.raises(LifecycleError, match="needs a blocker class"):
        kernel.block("t-1", 1, blocker_class=BlockerClass.NONE, reason="x")


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
    assert log[0].startswith("CLIVE kernel|kernel: t-1 attempt-1 acknowledged")
    assert "operator: tests" in log[0]
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout
    assert dirty == ""
    assert len(kernel.journal_shas) == 3


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
    assert w1["task_id"] == "t-1" and w1["attempt_id"] == "attempt-1"
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
    kernel.integrate("t-1", 1, integration_sha=MERGED, target_base_sha=BASE, method=IntegrationMethod.MERGE, integrated_by="tests")
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
