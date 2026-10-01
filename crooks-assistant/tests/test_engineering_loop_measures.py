"""Engineering measures from the loop's own records: the kernel's store, the landings, the trunk.

Every store here is written by the real kernel (a fake git, a fixed clock, no journal) into a
temporary directory; the landing records and the trunk's git history are fake data as well.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.engineering_measures import (
    LOOP_SCHEMA,
    NOT_RECORDED,
    MeasuresError,
    read_loop_records,
    render_loop_markdown,
)
from app.orchestrator.contracts import BlockerClass, EngineeringTask, TaskKind
from app.orchestrator.lifecycle import (
    IntegrationMethod,
    Kernel,
    LifecycleStore,
    PrincipalRegistry,
    lifecycle_view,
)
from app.orchestrator.objectives import Objective, ObjectiveStore, OwnerEntry, intake
from app.orchestrator.review_acceptance import ReviewVerdict
from app.orchestrator.routing import Party, Principal, PrincipalKind, SessionContext, Workspace
from app.orchestrator.store import JsonRecordStore
from scripts import engineering_measures as cli

BASE = "a" * 40
CAND = "b" * 40
CAND2 = "d" * 40
MEMORY = "e" * 40
T0 = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)  # alpha recorded
T1 = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)  # beta
T2 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)  # gamma
T3 = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)  # delta
EVIDENCE = ("worker_report", "worker_transcript")

# Text that lives in the records and must never reach the report.
SECRETS = (
    "SECRET-OUTCOME", "SECRET-FINDING", "SECRET-NOTE", "SECRET-BLOCKER", "SECRET-LANDING",
    "superseded by revision", "verdict_not_ready", "review_observed_sha_drift",
)


@dataclass
class FakeGit:
    heads: dict[str, str] = field(default_factory=lambda: {"work": BASE})

    def commit_exists(self, sha: str) -> bool:
        return sha in {BASE, CAND, CAND2, MEMORY}

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return ancestor == descendant or (ancestor, descendant) in {(BASE, CAND), (BASE, CAND2)}

    def rev_parse(self, ref: str) -> str | None:
        return self.heads.get(ref.removeprefix("refs/remotes/origin/"))

    def remote_head(self, remote: str, branch: str) -> str | None:
        return None

    def changed_paths(self, base: str, head: str) -> tuple[str, ...] | None:
        return ("f.py",)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


REGISTRY = PrincipalRegistry(
    {
        "claude": {"principal_id": "claude", "may_review": False},
        "gpt": {"principal_id": "gpt", "may_review": True},
    }
)


def party(principal: str, workspace: str, head: str, *, read_only: bool = False) -> Party:
    return Party(
        principal=Principal(principal_id=principal, kind=PrincipalKind.MODEL),
        session=SessionContext(session_id=f"session-{workspace}", context_is_fresh=True, started_at=T0),
        workspace=Workspace(workspace_id=workspace, branch="work", head_sha=head, read_only=read_only, clean=True),
    )


AUTHOR = party("claude", "/w/author", BASE)


def objective(objective_id: str, title: str, at: datetime) -> Objective:
    return Objective(
        objective_id=objective_id, title=title, requested_outcome=f"SECRET-OUTCOME of {objective_id}",
        repository="o/r", base_ref="main", base_sha=BASE, target_branch="work", product_memory_sha=MEMORY,
        allowed_paths=("f.py",), owner=OwnerEntry(os_user="tester", host="test-host"), created_at=at,
    )


def revision(task_id: str, number: int, kind: TaskKind, at: datetime) -> EngineeringTask:
    return EngineeringTask(
        task_id=task_id, revision=number, stream_id=f"objective:{task_id}", kind=kind,
        objective=f"SECRET-FINDING revision {number}", repository="o/r", base_sha=BASE, target_branch="work",
        product_memory_sha=MEMORY, allowed_paths=("f.py",), required_evidence=EVIDENCE,
        authorising_reference="SECRET-FINDING: the verdict that routed it", created_at=at,
    )


def to_review(kernel: Kernel, clock: Clock, git: FakeGit, task_id: str, number: int, sha: str, at: datetime):
    """Assign, acknowledge, build and record the candidate ``sha`` at ``at``, then dispatch its review."""
    git.heads["work"] = BASE
    attempt = kernel.assign(task_id, number, worker_id="w1", worker=AUTHOR, lease_duration_s=86400)
    token = attempt.fencing_token
    kernel.acknowledge(attempt.attempt_id, token=token, base_sha=BASE)
    kernel.heartbeat(attempt.attempt_id, token=token, note="SECRET-NOTE: still building", progress=True)
    for name in EVIDENCE:
        kernel.record_evidence(attempt.attempt_id, token=token, name=name, payload=b"ok")
    clock.now = at
    kernel.record_candidate(attempt.attempt_id, token=token, sha=sha, evidence_satisfied=EVIDENCE, clean_worktree=True)
    git.heads["work"] = sha
    kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id="gpt", packet=b"SECRET-FINDING packet",
                           current_head=sha)
    return attempt


def build_store(root: Path) -> None:
    """Four objectives, each a different story, written by the kernel's own verbs.

    alpha: built, one verdict refused, one REPAIR_REQUIRED, repaired in r2, accepted, integrated,
           then a trunk refresh r3 (READY); landed by the loop.
    beta:  built until blocked (deterministic); its landing record is waiting.
    gamma: recorded, no task yet, no landing record.
    delta: recorded, no task; a landing record by someone other than the loop.
    """
    clock = Clock(T0)
    git = FakeGit()
    kernel = Kernel(LifecycleStore(root), REGISTRY, git, operator="tests", clock=clock, journal=False)
    objectives = ObjectiveStore(kernel.store, journal=False)

    intake(objective("alpha", "Alpha | the first change", T0), kernel=kernel, objectives=objectives)
    clock.now = T0 + timedelta(hours=1)
    first = to_review(kernel, clock, git, "alpha", 1, CAND, T0 + timedelta(hours=2))
    kernel.admit_verdict(first.attempt_id, reviewer=party("gpt", "/w/r1", CAND, read_only=True),
                         verdict=ReviewVerdict.READY, payload=b"SECRET-FINDING refused",
                         observed_candidate_sha=BASE, current_head=CAND)  # refused: not a review round
    kernel.admit_verdict(first.attempt_id, reviewer=party("gpt", "/w/r1", CAND, read_only=True),
                         verdict=ReviewVerdict.REPAIR_REQUIRED, payload=b"SECRET-FINDING J-01",
                         observed_candidate_sha=CAND, current_head=CAND)
    clock.now = T0 + timedelta(hours=3)
    kernel.create_task(revision("alpha", 2, TaskKind.REPAIR, clock.now))
    clock.now = T0 + timedelta(hours=4)
    second = to_review(kernel, clock, git, "alpha", 2, CAND2, T0 + timedelta(hours=4, minutes=30))
    clock.now = T0 + timedelta(hours=5)
    kernel.admit_verdict(second.attempt_id, reviewer=party("gpt", "/w/r2", CAND2, read_only=True),
                         verdict=ReviewVerdict.READY, payload=b"SECRET-FINDING none",
                         observed_candidate_sha=CAND2, current_head=CAND2)
    clock.now = T0 + timedelta(hours=6)
    kernel.integrate("alpha", 2, integration_sha=CAND2, target_base_sha=BASE,
                     method=IntegrationMethod.FAST_FORWARD, integrated_by="tests")
    clock.now = T0 + timedelta(hours=7)
    kernel.create_task(revision("alpha", 3, TaskKind.INTEGRATION, clock.now))

    clock.now = T1
    intake(objective("beta", "Beta", T1), kernel=kernel, objectives=objectives)
    clock.now = T1 + timedelta(hours=1)
    git.heads["work"] = BASE
    attempt = kernel.assign("beta", 1, worker_id="w2", worker=AUTHOR, lease_duration_s=86400)
    kernel.acknowledge(attempt.attempt_id, token=attempt.fencing_token, base_sha=BASE)
    kernel.block("beta", 1, blocker_class=BlockerClass.DETERMINISTIC, reason="SECRET-BLOCKER: the base is broken")

    clock.now = T3
    objectives.put(objective("gamma", "Gamma", T2), operator="tests")
    objectives.put(objective("delta", "Delta", T3), operator="tests")


def git_in(repo: Path, *args: str, at: str | None = None) -> str:
    env = {**os.environ, "HOME": str(repo.parent), "GIT_CONFIG_NOSYSTEM": "1"}
    if at:
        env.update(GIT_AUTHOR_DATE=at, GIT_COMMITTER_DATE=at)
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo, env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()


def commit(repo: Path, subject: str, at: str) -> str:
    (repo / "f.txt").write_text(subject, encoding="utf-8")
    git_in(repo, "add", "f.txt")
    git_in(repo, "commit", "-q", "-m", subject, at=at)
    return git_in(repo, "rev-parse", "HEAD")


def build_trunk(repo: Path) -> dict[str, str]:
    """clive/trunk, first-parent: other (09-26), the loop's landing (09-27), PR #12 merge (09-28), other (09-29)."""
    repo.mkdir()
    git_in(repo, "init", "-q")
    git_in(repo, "symbolic-ref", "HEAD", "refs/heads/clive/trunk")
    commit(repo, "initial", "2026-09-26T10:00:00Z")
    loop = commit(repo, "alpha: the first change", "2026-09-27T17:59:00Z")
    git_in(repo, "checkout", "-q", "-b", "feature")
    commit(repo, "feature work", "2026-09-28T08:00:00Z")
    git_in(repo, "checkout", "-q", "clive/trunk")
    git_in(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #12 from owner/feature", "feature",
           at="2026-09-28T10:00:00Z")
    other = commit(repo, "a fix by hand", "2026-09-29T10:00:00Z")
    return {"loop": loop, "other": other}


def landing(objective_id: str, **fields) -> str:
    record = {
        "schema": "clive.landing.v1", "objective_id": objective_id, "task_id": objective_id, "revision": 1,
        "reason": "SECRET-LANDING: why it is where it is", "evidence": "/runtime/SECRET-LANDING/landing.json",
        "at": "2026-09-29T12:00:00+00:00", **fields,
    }
    return json.dumps(record, sort_keys=True)


@dataclass
class World:
    tmp: Path
    store: Path
    runtime: Path
    repo: Path
    trunk: dict[str, str]


@pytest.fixture
def world(tmp_path) -> World:
    store = tmp_path / "engineering"
    build_store(store)
    repo = tmp_path / "repo"
    trunk = build_trunk(repo)
    landings = tmp_path / "runtime" / "landings"
    landings.mkdir(parents=True)
    (landings / "alpha.json").write_text(
        landing("alpha", state="landed", sha=trunk["loop"], by="loop", landed_at="2026-09-27T18:00:00+00:00"))
    (landings / "beta.json").write_text(landing("beta", state="waiting", sha=CAND))
    (landings / "delta.json").write_text(
        landing("delta", state="landed", sha=trunk["other"], by="other", landed_at="2026-09-29T10:00:00+00:00"))
    return World(tmp_path, store, tmp_path / "runtime", repo, trunk)


def run(world: World, *extra: str, runtime: Path | None = None) -> dict:
    out = world.tmp / "out" / "loop.json"
    arguments = ["--store", str(world.store), "--runtime-root", str(runtime or world.runtime),
                 "--repo", str(world.repo), "--format", "json", "--json", str(out), *extra]
    assert cli.main(arguments) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def rows(report: dict) -> dict[str, dict]:
    return {row["objective_id"]: row for row in report["objectives"]}


def days(report: dict) -> dict[str, dict]:
    return {day["day"]: day for day in report["days"]}


def at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def snapshot(root: Path) -> dict[str, bytes | None]:
    """Every path under ``root``: a file's bytes, ``None`` for a directory."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


# ------------------------------------------------------------------ per objective


def test_each_objective_is_one_row_from_its_records(world):
    report = run(world)
    assert report["schema"] == LOOP_SCHEMA
    assert [row["objective_id"] for row in report["objectives"]] == ["alpha", "beta", "gamma", "delta"]
    alpha, beta, gamma, delta = (rows(report)[name] for name in ("alpha", "beta", "gamma", "delta"))

    assert alpha["title"] == "Alpha | the first change"
    assert at(alpha["recorded_at"]) == T0
    assert (alpha["revisions"], alpha["repairs"], alpha["refreshes"]) == (3, 1, 1)
    assert alpha["attempts"] == 2
    assert alpha["review_rounds"] == 2  # REPAIR_REQUIRED and READY; the refused verdict is not a round
    assert (alpha["stage"], alpha["blocker_class"]) == ("READY", None)
    assert at(alpha["first_candidate_at"]) == T0 + timedelta(hours=2)
    assert at(alpha["accepted_at"]) == T0 + timedelta(hours=5)
    assert at(alpha["integrated_at"]) == T0 + timedelta(hours=6)
    assert (alpha["landing_state"], alpha["landed_sha"], alpha["landed_by"]) == ("landed", world.trunk["loop"], "loop")
    assert at(alpha["landed_at"]) == datetime(2026, 9, 27, 18, 0, tzinfo=UTC)
    assert (alpha["hours_to_first_candidate"], alpha["hours_to_integrate"], alpha["hours_to_land"]) == (2.0, 6.0, 10.0)

    assert (beta["revisions"], beta["repairs"], beta["refreshes"], beta["attempts"], beta["review_rounds"]) == (1, 0, 0, 1, 0)
    assert (beta["stage"], beta["blocker_class"]) == ("BLOCKED", "deterministic")
    assert beta["first_candidate_at"] is None and beta["hours_to_first_candidate"] is None
    assert (beta["landing_state"], beta["landed_sha"], beta["landed_by"], beta["landed_at"]) == ("waiting", None, None, None)
    assert beta["hours_to_land"] is None

    assert (gamma["revisions"], gamma["attempts"], gamma["stage"], gamma["landing_state"]) == (0, 0, None, None)
    assert (delta["landing_state"], delta["landed_by"], delta["hours_to_land"]) == ("landed", "other", 21.0)


def test_stage_is_what_lifecycle_view_reports_for_the_latest_revision(world):
    view = lifecycle_view(LifecycleStore(world.store), now=T3)["tasks"]
    for objective_id, row in rows(run(world)).items():
        revisions = [task for task in view if task["task_id"] == objective_id]
        latest = max(revisions, key=lambda task: task["revision"]) if revisions else None
        assert row["stage"] == (latest["stage"] if latest else None)


def test_the_markdown_objective_table_carries_every_event_timestamp(world):
    markdown = world.tmp / "loop.md"
    report = run(world, "--markdown", str(markdown))
    lines = markdown.read_text(encoding="utf-8").splitlines()
    table = lines[lines.index("## Per objective") + 2:]
    header = [cell.strip() for cell in table[0].strip("|").split("|")]
    for title in ("First candidate", "Accepted", "Integrated", "Landed at"):
        assert title in header
    alpha = rows(report)["alpha"]
    alpha_line = next(line for line in table if line.startswith("| alpha |"))
    for key in ("first_candidate_at", "accepted_at", "integrated_at", "landed_at"):
        assert alpha[key] and alpha[key] in alpha_line


# ------------------------------------------------------------------ per day and in total


def test_per_day_and_totals_with_the_trunk_history(world):
    report = run(world)
    assert report["inputs"]["trunk_history"] is True
    assert report["inputs"]["trunk_source"].startswith("clive/trunk (4 first-parent commits)")
    by_day = days(report)
    assert sorted(by_day) == ["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29"]

    def figures(day: dict) -> tuple:
        return (day["objectives_recorded"], day["first_candidates"], day["repair_revisions"], day["loop_landings"],
                day["median_hours_to_land"], day["trunk_commits"], day["trunk_loop_landings"],
                day["trunk_pull_request_merges"], day["trunk_other"])

    assert figures(by_day["2026-09-26"]) == (0, 0, 0, 0, None, 1, 0, 0, 1)
    assert figures(by_day["2026-09-27"]) == (1, 1, 1, 1, 10.0, 1, 1, 0, 0)
    assert figures(by_day["2026-09-28"]) == (3, 0, 0, 0, None, 1, 0, 1, 0)
    assert figures(by_day["2026-09-29"]) == (0, 0, 0, 0, 21.0, 1, 0, 0, 1)
    assert figures(report["totals"]) == (4, 1, 1, 1, 15.5, 4, 1, 1, 2)


def test_without_the_trunk_history_the_trunk_counts_are_null_not_zero(world):
    report = run(world, "--no-trunk")
    assert report["inputs"]["trunk_history"] is False
    for figures in (*report["days"], report["totals"]):
        for name in ("trunk_commits", "trunk_loop_landings", "trunk_pull_request_merges", "trunk_other"):
            assert figures[name] is None
    assert report["totals"]["loop_landings"] == 1  # the landing records still count


def test_an_unreadable_trunk_leaves_the_trunk_counts_null(world, capsys):
    report = run(world, "--trunk-ref", "no-such-ref")
    assert report["totals"]["trunk_commits"] is None
    assert report["inputs"]["trunk_source"].startswith("unavailable")
    assert "unavailable" in capsys.readouterr().err


# ------------------------------------------------------------------ landings


def test_without_a_landings_directory_landings_are_not_read_rather_than_none_landed(world):
    runtime = world.tmp / "no-runtime"
    report = run(world, runtime=runtime)
    assert not runtime.exists()
    assert report["inputs"]["landings_read"] is False
    assert report["inputs"]["landings"].startswith("not read")
    assert all(row["landing_state"] is None and row["landed_at"] is None for row in report["objectives"])
    totals = report["totals"]
    assert totals["loop_landings"] is None and totals["median_hours_to_land"] is None
    assert totals["trunk_commits"] == 4 and totals["trunk_pull_request_merges"] == 1
    assert totals["trunk_loop_landings"] is None and totals["trunk_other"] is None
    assert all(day["loop_landings"] is None for day in report["days"])
    markdown = (world.tmp / "loop.md")
    run(world, "--markdown", str(markdown), runtime=runtime)
    assert "landings: not read" in markdown.read_text(encoding="utf-8")


def test_only_clive_landing_v1_records_of_the_objective_count(world):
    landings = world.runtime / "landings"
    (landings / "delta.json").write_text(landing("delta", schema="clive.landing.v0", state="landed",
                                                 sha=world.trunk["other"], by="other",
                                                 landed_at="2026-09-29T10:00:00+00:00"))
    (landings / "beta.json").write_text("{not json")
    (landings / "gamma.json").write_text(landing("alpha", state="landed", sha=world.trunk["other"], by="loop",
                                                 landed_at="2026-09-29T10:00:00+00:00"))
    report = run(world)
    assert report["inputs"]["landing_records_ignored"] == 3
    by_id = rows(report)
    assert [by_id[name]["landing_state"] for name in ("beta", "gamma", "delta")] == [None, None, None]
    assert by_id["alpha"]["landing_state"] == "landed"
    assert report["totals"]["loop_landings"] == 1 and report["totals"]["trunk_loop_landings"] == 1


def test_a_landing_by_someone_else_is_not_a_loop_landing(world):
    report = run(world)
    other = days(report)["2026-09-29"]
    assert other["loop_landings"] == 0 and other["trunk_loop_landings"] == 0 and other["trunk_other"] == 1


# ------------------------------------------------------------------ what is not recorded


def test_deploys_and_owner_attention_are_reported_as_not_recorded(world):
    report = run(world)
    assert report["inputs"]["deploys"] == NOT_RECORDED
    assert report["inputs"]["owner_attention"] == NOT_RECORDED
    for row in report["objectives"]:
        assert (row["deployed_at"], row["hours_to_production"], row["owner_minutes"]) == (None, None, None)
    for figures in (*report["days"], report["totals"]):
        assert (figures["deploys"], figures["owner_minutes"]) == (None, None)
    markdown = world.tmp / "loop.md"
    run(world, "--markdown", str(markdown))
    assert "Deploys and owner attention are not recorded anywhere" in markdown.read_text(encoding="utf-8")


def test_deploy_and_attention_logs_are_refused_without_status(world, capsys):
    log = world.tmp / "deploys.jsonl"
    log.write_text("")
    with pytest.raises(SystemExit) as exited:
        cli.main(["--store", str(world.store), "--deploy-log", str(log), "--no-trunk"])
    assert exited.value.code == 2
    assert "--deploy-log" in capsys.readouterr().err


# ------------------------------------------------------------------ the store


def test_a_missing_store_exits_2_with_the_reason(tmp_path, capsys):
    assert cli.main(["--store", str(tmp_path / "absent"), "--runtime-root", str(tmp_path), "--no-trunk"]) == 2
    assert "does not exist" in capsys.readouterr().err
    (tmp_path / "a-file").write_text("x")
    assert cli.main(["--store", str(tmp_path / "a-file"), "--runtime-root", str(tmp_path), "--no-trunk"]) == 2
    assert "not a directory" in capsys.readouterr().err
    assert not (tmp_path / "absent").exists()


def test_an_unreadable_store_exits_2_with_the_reason(world, capsys):
    (world.store / "objectives" / "alpha.json").write_text("{broken", encoding="utf-8")
    assert cli.main(["--store", str(world.store), "--runtime-root", str(world.runtime), "--no-trunk"]) == 2
    assert "cannot be read" in capsys.readouterr().err
    with pytest.raises(MeasuresError, match="cannot be read"):
        read_loop_records(world.store, world.runtime)


def test_a_readable_store_with_no_objectives_has_zero_rows_and_zero_counts(tmp_path):
    store = tmp_path / "engineering"
    store.mkdir()
    (tmp_path / "runtime" / "landings").mkdir(parents=True)
    out = tmp_path / "loop.json"
    assert cli.main(["--store", str(store), "--runtime-root", str(tmp_path / "runtime"), "--no-trunk",
                     "--json", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["objectives"] == [] and report["days"] == []
    totals = report["totals"]
    assert (totals["objectives_recorded"], totals["first_candidates"], totals["repair_revisions"],
            totals["loop_landings"]) == (0, 0, 0, 0)
    assert totals["median_hours_to_land"] is None
    assert sorted(path.name for path in store.iterdir()) == []


def test_reading_never_writes_creates_or_locks_the_store_or_the_runtime(world, monkeypatch):
    (world.store / ".kernel.lock").unlink()  # the layout made one while the kernel wrote; the reader must not
    bare_runtime = world.tmp / "bare-runtime"
    bare_runtime.mkdir()
    before = (snapshot(world.store), snapshot(world.runtime), snapshot(bare_runtime))

    def refuse(*args, **kwargs):
        raise AssertionError("the reader wrote, laid out or locked")

    monkeypatch.setattr(fcntl, "flock", refuse)
    monkeypatch.setattr(LifecycleStore, "ensure_layout", refuse)
    monkeypatch.setattr(LifecycleStore, "exclusive_writer", refuse)
    monkeypatch.setattr(JsonRecordStore, "_atomic_write", staticmethod(refuse))
    monkeypatch.setattr(LifecycleStore, "_atomic_write", refuse)
    monkeypatch.setattr(LifecycleStore, "append_event", refuse)
    run(world, "--markdown", str(world.tmp / "out" / "loop.md"))
    run(world, runtime=bare_runtime)
    run(world, "--no-trunk", runtime=world.tmp / "no-runtime")

    assert (snapshot(world.store), snapshot(world.runtime), snapshot(bare_runtime)) == before
    assert not (world.store / ".kernel.lock").exists()
    assert not (bare_runtime / "landings").exists() and not (world.tmp / "no-runtime").exists()


@pytest.mark.parametrize("root", ["store", "runtime"])
@pytest.mark.parametrize("option", ["--json", "--markdown"])
def test_an_output_inside_the_store_or_the_runtime_is_refused(world, capsys, root, option):
    tree = getattr(world, root)
    before = (snapshot(world.store), snapshot(world.runtime))
    targets = (
        tree / "objectives" / "alpha.json" if root == "store" else tree / "landings" / "alpha.json",
        tree / "new-dir" / "deeper" / "out.json",
        world.tmp / "elsewhere" / ".." / tree.name / "report.md",
    )
    for target in targets:
        assert cli.main(["--store", str(world.store), "--runtime-root", str(world.runtime), "--no-trunk",
                         option, str(target)]) == 2
        assert f"inside the {root}" in capsys.readouterr().err
    assert (snapshot(world.store), snapshot(world.runtime)) == before
    assert not (tree / "new-dir").exists() and not (world.tmp / "elsewhere").exists()


def test_no_finding_reason_or_note_text_reaches_the_report(world):
    # The records do hold every one of them, so their absence below is the reader's doing.
    held = b"".join(path.read_bytes() for path in world.store.rglob("*") if path.is_file())
    held += b"".join(path.read_bytes() for path in world.runtime.rglob("*") if path.is_file())
    assert all(secret.encode() in held for secret in SECRETS)

    markdown = world.tmp / "loop.md"
    report = run(world, "--markdown", str(markdown))
    rendered = json.dumps(report) + markdown.read_text(encoding="utf-8")
    assert [secret for secret in SECRETS if secret in rendered] == []
    assert "Alpha \\| the first change" in markdown.read_text(encoding="utf-8")


# ------------------------------------------------------------------ the arguments


def test_status_or_store_is_required(capsys):
    with pytest.raises(SystemExit) as exited:
        cli.main(["--no-trunk"])
    assert exited.value.code == 2
    assert "--status or --store" in capsys.readouterr().err


def test_status_and_store_together_give_both_reports(world):
    status = world.tmp / "status.json"
    status.write_text(json.dumps({"generated_at": "2026-09-29T00:00:00+00:00", "requests": []}))
    out = world.tmp / "both.json"
    assert cli.main(["--status", str(status), "--store", str(world.store), "--runtime-root", str(world.runtime),
                     "--no-trunk", "--json", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["schema"] == "clive.engineering_measures.v1" and report["objectives"] == []
    assert report["loop_records"]["schema"] == LOOP_SCHEMA
    assert len(report["loop_records"]["objectives"]) == 4


# ------------------------------------------------------------------ the landing review's fixes (1 October 2026)


def _fact(objective_id: str, base_sha: str, landing: dict | None) -> dict:
    """One objective's facts as ``read_loop_records`` gives them, for ``measure_loop`` alone."""
    return {
        "objective_id": objective_id, "title": objective_id, "recorded_at": T0, "base_sha": base_sha,
        "revisions": 1, "repairs_created": [], "refreshes": 0, "attempts": 1, "review_rounds": 1,
        "stage": "COMPLETE", "blocker_class": None, "first_candidate_at": None, "accepted_at": None,
        "integrated_at": None, "landing": landing,
    }


def _records(*facts: dict) -> dict:
    return {"store": "store", "runtime_root": "runtime", "landings_read": True, "landings_source": "runtime/landings",
            "landing_records_ignored": 0, "objectives": list(facts)}


def _landed(sha: str, by: str | None = "loop") -> dict:
    return {"state": "landed", "sha": sha, "by": by, "by_recorded": by is not None,
            "landed_at": datetime(2026, 9, 30, 15, 0, tzinfo=UTC)}


def commit_own(repo: Path, name: str, subject: str, at: str) -> str:
    """A commit that touches a file of its own, so that the branches below merge cleanly."""
    (repo / f"{name}.txt").write_text(subject, encoding="utf-8")
    git_in(repo, "add", f"{name}.txt")
    git_in(repo, "commit", "-q", "-m", subject, at=at)
    return git_in(repo, "rev-parse", "HEAD")


def build_loop_shaped_trunk(repo: Path) -> dict[str, str]:
    """The trunk as the loop leaves it, all on 2026-09-30. An objective is built on ``base``; a
    pull request titled as this repository titles them merges onto the trunk meanwhile; the loop
    merges the trunk into the objective's branch and lands by fast-forwarding the trunk to that
    merge; then a pull request merges on the first-parent line, and someone commits by hand."""
    repo.mkdir()
    git_in(repo, "init", "-q")
    git_in(repo, "symbolic-ref", "HEAD", "refs/heads/clive/trunk")
    base = commit_own(repo, "base", "initial", "2026-09-30T08:00:00Z")
    git_in(repo, "checkout", "-q", "-b", "clive/objective/omega")
    built = commit_own(repo, "omega", "omega r2 omega-a1: the change", "2026-09-30T09:00:00Z")
    git_in(repo, "checkout", "-q", "-b", "feature-a", base)
    commit_own(repo, "a", "feature a", "2026-09-30T09:30:00Z")
    git_in(repo, "checkout", "-q", "clive/trunk")
    git_in(repo, "merge", "-q", "--no-ff", "-m", "Feature A on the trunk (PR #41)", "feature-a", at="2026-09-30T10:00:00Z")
    unseen = git_in(repo, "rev-parse", "HEAD")
    git_in(repo, "checkout", "-q", "clive/objective/omega")
    git_in(repo, "merge", "-q", "--no-ff", "-m",
           f"Merge clive/trunk {unseen} into clive/objective/omega at {built} (loop)", "clive/trunk",
           at="2026-09-30T11:00:00Z")
    landed = git_in(repo, "rev-parse", "HEAD")
    git_in(repo, "checkout", "-q", "clive/trunk")
    git_in(repo, "merge", "-q", "--ff-only", "clive/objective/omega")
    git_in(repo, "checkout", "-q", "-b", "feature-b")
    commit_own(repo, "b", "feature b", "2026-09-30T12:00:00Z")
    git_in(repo, "checkout", "-q", "clive/trunk")
    git_in(repo, "merge", "-q", "--no-ff", "-m", "Feature B on the trunk (PR #42)", "feature-b", at="2026-09-30T13:00:00Z")
    commit_own(repo, "hand", "a fix by hand", "2026-09-30T14:00:00Z")
    return {"base": base, "built": built, "landed": landed, "unseen": unseen}


def _trunk_figures(report: dict) -> tuple:
    totals = report["totals"]
    return (totals["trunk_commits"], totals["trunk_loop_landings"], totals["trunk_with_loop_landings"],
            totals["trunk_pull_request_merges"], totals["trunk_other"])


def test_this_repositorys_pull_request_titles_count_in_the_loop_report_and_the_status_reading_is_unchanged(tmp_path):
    from app.engineering_measures import measure_loop, pull_request_of

    repo = tmp_path / "repo"
    shas = build_loop_shaped_trunk(repo)
    trunk, _graph = cli.read_trunk(repo, "clive/trunk")
    report = measure_loop(_records(_fact("omega", shas["base"], _landed(shas["landed"]))), trunk=trunk)
    # First-parent: the hand fix, PR #42's merge, the landing, the builder's commit, the base.
    assert _trunk_figures(report) == (5, 1, 1, 1, 2)
    # The --status report's reading of a title is the one it always was.
    assert pull_request_of("Feature B on the trunk (PR #42)") is None
    assert pull_request_of("Merge pull request #42 from owner/feature-b") == "#42"


def test_the_commits_a_loop_landing_fast_forwarded_count_with_it_down_to_its_base(tmp_path):
    from app.engineering_measures import measure_loop

    repo = tmp_path / "repo"
    shas = build_loop_shaped_trunk(repo)
    trunk, _graph = cli.read_trunk(repo, "clive/trunk")
    report = measure_loop(_records(_fact("omega", shas["base"], _landed(shas["landed"]))), trunk=trunk)
    assert report["inputs"]["trunk_landings_untraced"] == []
    # The builder's commit is the landing's, not other; the base and the hand fix are other.
    assert report["totals"]["trunk_with_loop_landings"] == 1 and report["totals"]["trunk_other"] == 2
    # PR #41 merged while omega was built: off the first-parent line once omega landed, and the
    # report says such merges are not counted.
    assert shas["unseen"] not in {commit.sha for commit in trunk}
    assert "is not counted" in report["inputs"]["trunk_not_counted"]
    markdown = render_loop_markdown(report)
    assert "Trunk: with a loop landing" in markdown and "Not counted at all:" in markdown


def test_a_loop_landing_that_cannot_be_traced_to_its_base_is_named_and_its_commits_stay_other(tmp_path):
    from app.engineering_measures import measure_loop

    repo = tmp_path / "repo"
    shas = build_loop_shaped_trunk(repo)
    trunk, _graph = cli.read_trunk(repo, "clive/trunk")
    report = measure_loop(_records(_fact("omega", "f" * 40, _landed(shas["landed"]))), trunk=trunk)
    assert report["inputs"]["trunk_landings_untraced"] == ["omega"]
    assert _trunk_figures(report) == (5, 1, 0, 1, 3)
    markdown = render_loop_markdown(report)
    assert "could not be traced down to their objective's base (omega)" in markdown
    assert "counted in Trunk: other" in markdown


def test_a_landed_record_with_a_malformed_time_is_ignored_and_counted_not_fatal(world):
    (world.runtime / "landings" / "delta.json").write_text(
        landing("delta", state="landed", sha=world.trunk["other"], by="other", landed_at="yesterday"))
    report = run(world)
    assert report["inputs"]["landing_records_ignored"] == 1
    assert rows(report)["delta"]["landing_state"] is None
    assert rows(report)["alpha"]["landing_state"] == "landed"


def test_a_landed_record_with_no_by_is_said_to_predate_attribution(world):
    (world.runtime / "landings" / "alpha.json").write_text(
        landing("alpha", state="landed", sha=world.trunk["loop"], landed_at="2026-09-27T18:00:00+00:00"))
    markdown = world.tmp / "loop.md"
    report = run(world, "--markdown", str(markdown))
    alpha = rows(report)["alpha"]
    assert (alpha["landing_state"], alpha["landed_by"]) == ("landed", None)
    assert report["inputs"]["landings_predating_attribution"] == ["alpha"]
    assert "predates the loop recording who landed a SHA" in report["inputs"]["landed_by_null_when_landed"]
    assert report["totals"]["loop_landings"] == 0, "who landed it is not recorded, so it is not the loop's"
    text = markdown.read_text(encoding="utf-8")
    alpha_line = next(line for line in text.splitlines() if line.startswith("| alpha |"))
    assert "predates attribution" in alpha_line
    assert "Landed by is not recorded for alpha" in text


def test_a_by_that_is_not_one_of_the_recorded_words_is_unrecognised(world):
    (world.runtime / "landings" / "alpha.json").write_text(
        landing("alpha", state="landed", sha=world.trunk["loop"], by=["loop"], landed_at="2026-09-27T18:00:00+00:00"))
    assert rows(run(world))["alpha"]["landed_by"] == "unrecognised"


def test_the_median_hours_to_land_is_labelled_as_covering_every_landing(world):
    markdown = world.tmp / "loop.md"
    report = run(world, "--markdown", str(markdown))
    assert report["inputs"]["median_hours_to_land_is"].startswith("over every landed objective, whoever landed it")
    text = markdown.read_text(encoding="utf-8")
    assert "Median h to land (all landings)" in text
    assert "Median hours to land is over every landed objective, whoever landed it" in text
    # 2026-09-29: delta, landed by someone other than the loop, is in the median and not a loop landing.
    assert (days(report)["2026-09-29"]["loop_landings"], days(report)["2026-09-29"]["median_hours_to_land"]) == (0, 21.0)
