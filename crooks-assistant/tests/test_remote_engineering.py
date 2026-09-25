"""The bounded GitHub inbox and controller adapter: same or less authority than CLI intake, idempotent, no second store."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.orchestrator.contracts import BlockerClass, TaskStatus
from app.orchestrator.lifecycle import (
    GitFacts,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
    sha256_of,
)
from app.orchestrator.objectives import ObjectiveStore
from app.remote_engineering import (
    ADAPTER_ROOT_NOT_IGNORED,
    DEFAULT_INBOX_BRANCH,
    DEFAULT_INBOX_DIRECTORY,
    DEFAULT_STATUS_BRANCH,
    INTAKE_UNAVAILABLE,
    MAX_HEARTBEAT_S,
    PUBLISH_UNAVAILABLE,
    REQUEST_ID_MAX_LENGTH,
    REQUEST_SCHEMA,
    Claim,
    ClaimLog,
    InboxError,
    Receipt,
    ReceiptLog,
    RemoteController,
    RemoteControllerConfig,
    RemoteEngineeringLoop,
    RequestSchemaError,
    adapter_root_preconditions,
    build_status,
    fetch_inbox,
    parse_request,
    publish_status,
)
from scripts import remote_engineering as cli

REGISTRY = Path(__file__).resolve().parent.parent / "config" / "review_principals.json"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def env(tmp_path: Path) -> SimpleNamespace:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "a.txt").write_text("a\n")
    _git(origin, "add", "-A")
    _git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    base = _git(origin, "rev-parse", "HEAD")

    checkout = tmp_path / "checkout"
    _git(tmp_path, "clone", "-q", str(origin), str(checkout))

    return SimpleNamespace(origin=origin, checkout=checkout, base=base)


def commit_request(origin: Path, request_id: str, payload: dict, *,
                    branch: str = DEFAULT_INBOX_BRANCH, filename: str | None = None) -> None:
    filename = filename or f"{request_id}.json"
    exists = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", branch], cwd=origin, capture_output=True
    ).returncode == 0
    if exists:
        _git(origin, "checkout", "-q", branch)
    else:
        _git(origin, "checkout", "-q", "-b", branch)
    directory = origin / DEFAULT_INBOX_DIRECTORY
    directory.mkdir(exist_ok=True)
    (directory / filename).parent.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(json.dumps(payload, indent=2))
    _git(origin, "add", "-A")
    _git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"request {request_id}")
    _git(origin, "checkout", "-q", "main")


def valid_request(env: SimpleNamespace, **overrides) -> dict:
    request_id = overrides.get("request_id", "remote-support-queue")
    fields = dict(
        schema_version=REQUEST_SCHEMA,
        request_id=request_id,
        title="Support queue",
        requested_outcome="Show unanswered Crooks order enquiries, newest first.",
        base_ref="main",
        base_sha=env.base,
        allowed_paths=["crooks-assistant/app/support"],
        acceptance_criteria=["every unanswered thread is listed"],
        checks=[{"name": "tests", "argv": ["true"], "cwd": "."}],
        target_branch=f"clive/objective/{request_id}",
        max_repair_rounds=2,
    )
    fields.update(overrides)
    return fields


def make_controller(env: SimpleNamespace, tmp_path: Path):
    store = LifecycleStore(tmp_path / "engineering")
    kernel = Kernel(store=store, registry=PrincipalRegistry.load(REGISTRY), git=GitFacts(env.checkout),
                    operator="remote-test", journal=False, clock=lambda: NOW)
    objectives = ObjectiveStore(store, journal=False)
    receipts = ReceiptLog(store.root / "remote_engineering")
    config = RemoteControllerConfig(repo=env.checkout, repository="crooksldn-pixel/clive", product_memory_ref="main")
    controller = RemoteController(kernel=kernel, objectives=objectives, config=config, receipts=receipts,
                                  clock=lambda: NOW)
    return kernel, objectives, receipts, controller


def test_valid_request_becomes_exactly_one_objective_and_task(env, tmp_path):
    commit_request(env.origin, "remote-support-queue", valid_request(env))
    kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert len(outcomes) == 1 and outcomes[0]["outcome"] == "accepted"
    assert objectives.read("remote-support-queue").requested_outcome.startswith("Show unanswered")
    task = kernel.store.read_task("remote-support-queue", 1)
    assert task is not None and task.allowed_paths == ("crooks-assistant/app/support",)
    assert kernel.store.read_task_state("remote-support-queue", 1).status is TaskStatus.READY


def test_replay_is_idempotent(env, tmp_path):
    commit_request(env.origin, "r-one-a", valid_request(env, request_id="r-one-a"))
    kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    first = controller.poll_once()
    second = controller.poll_once()
    assert first == second
    assert len(kernel.store.read_tasks()) == 1


def test_same_id_different_content_is_refused(env, tmp_path):
    commit_request(env.origin, "r-two-a", valid_request(env, request_id="r-two-a"))
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    commit_request(env.origin, "r-two-a", valid_request(env, request_id="r-two-a", requested_outcome="Something else."))
    with pytest.raises(InboxError):
        controller.poll_once()
    assert objectives.read("r-two-a").requested_outcome.startswith("Show unanswered")


def test_protected_scope_is_refused_by_canonical_validation(env, tmp_path):
    commit_request(env.origin, "r-three-a", valid_request(
        env, request_id="r-three-a", allowed_paths=["crooks-assistant/app/orchestrator/lifecycle.py"]
    ))
    kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert "no objective may put in scope" in outcomes[0]["reason"]
    assert objectives.read("r-three-a") is None
    assert kernel.store.read_task("r-three-a", 1) is None


def test_malformed_schema_fails_closed(env, tmp_path):
    commit_request(env.origin, "bad-record", {"not": "a request"}, filename="bad-record.json")
    _kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert receipts.read_all() == ()


def test_unknown_field_is_refused_not_executed(env, tmp_path):
    payload = valid_request(env, request_id="r-four-a")
    payload["shell"] = "rm -rf /"
    commit_request(env.origin, "r-four-a", payload)
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert objectives.read("r-four-a") is None


def test_check_argv_is_never_shell_parsed(env, tmp_path):
    payload = valid_request(env, request_id="r-twelve", checks=[{"name": "x", "argv": ["true; rm -rf /"], "cwd": "."}])
    commit_request(env.origin, "r-twelve", payload)
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    assert objectives.read("r-twelve").checks[0].argv == ("true; rm -rf /",)


def test_owner_gate_cannot_be_lifted_by_replay(env, tmp_path):
    commit_request(env.origin, "r-five-a", valid_request(env, request_id="r-five-a"))
    kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    kernel.block("r-five-a", 1, blocker_class=BlockerClass.OWNER_ONLY, reason="needs owner", owner_gate=True)
    controller.poll_once()
    assert kernel.store.read_task_state("r-five-a", 1).status is TaskStatus.OWNER_GATE


def test_owner_gate_cannot_be_lifted_even_if_the_receipt_is_lost(env, tmp_path):
    commit_request(env.origin, "r-five-b", valid_request(env, request_id="r-five-b"))
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    kernel.block("r-five-b", 1, blocker_class=BlockerClass.OWNER_ONLY, reason="needs owner", owner_gate=True)
    receipts._path("r-five-b").unlink()
    controller.poll_once()
    assert kernel.store.read_task_state("r-five-b", 1).status is TaskStatus.OWNER_GATE


def test_controller_exposes_no_verb_that_could_advance_or_resolve_lifecycle(env):
    for verb in ("resume", "block", "assign", "dispatch_review", "admit_verdict", "integrate"):
        assert not hasattr(RemoteController, verb)


def test_restart_and_repoll_do_not_duplicate(env, tmp_path):
    commit_request(env.origin, "r-six-a", valid_request(env, request_id="r-six-a"))
    _kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    kernel2, _objectives2, _receipts2, controller2 = make_controller(env, tmp_path)
    controller2.poll_once()
    assert len(kernel2.store.read_tasks()) == 1
    assert kernel2.store.read_attempts() == ()


def test_status_is_a_projection_of_existing_records(env, tmp_path):
    commit_request(env.origin, "r-seven-a", valid_request(env, request_id="r-seven-a"))
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    status = build_status(store=kernel.store, receipts=receipts, now=NOW)
    item = status["requests"][0]
    assert item["objective_id"] == "r-seven-a" and item["task_id"] == "r-seven-a"
    assert item["stage"] == "READY"
    assert item["owner_gate"] is False


def test_credential_like_extra_field_never_enters_output(env, tmp_path):
    secret = "sk-supersecrettoken1234567890"
    payload = valid_request(env, request_id="r-eight-a")
    payload["api_key"] = secret
    commit_request(env.origin, "r-eight-a", payload)
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert secret not in json.dumps(outcomes)
    status = build_status(store=kernel.store, receipts=receipts, now=NOW)
    assert secret not in json.dumps(status)


def test_receipts_carry_pointers_only_never_a_second_lifecycle_store():
    assert set(Receipt.model_fields) == {
        "schema_version", "request_id", "request_sha256", "outcome", "reason",
        "objective_id", "task_id", "source", "recorded_at",
    }


def test_base_ref_must_resolve_to_the_declared_sha(env, tmp_path):
    commit_request(env.origin, "r-eleven", valid_request(env, request_id="r-eleven", base_sha="f" * 40))
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert objectives.read("r-eleven") is None


def test_parse_request_rejects_invalid_json():
    with pytest.raises(RequestSchemaError):
        parse_request(b"{not json")


def test_parse_request_rejects_unknown_schema_version():
    with pytest.raises(RequestSchemaError):
        parse_request(json.dumps({"schema_version": "nope"}).encode())


def test_remote_name_cannot_be_a_url(env):
    with pytest.raises(InboxError):
        fetch_inbox(env.checkout, remote="https://evil.example/repo.git", branch=DEFAULT_INBOX_BRANCH)


def test_branch_name_cannot_escape(env):
    with pytest.raises(InboxError):
        fetch_inbox(env.checkout, remote="origin", branch="../../etc/passwd")


def test_cli_rejects_unknown_verb():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--store", "x", "--repo", "y", "deploy"])


def test_cli_poll_and_status(env, tmp_path, capsys):
    commit_request(env.origin, "r-ten", valid_request(env, request_id="r-ten"))
    store_dir = tmp_path / "engineering"
    rc = cli.run([
        "--store", str(store_dir), "--repo", str(env.checkout), "--no-journal",
        "poll", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"outcome": "accepted"' in out

    rc2 = cli.run(["--store", str(store_dir), "--repo", str(env.checkout), "--no-journal", "status", "--json"])
    assert rc2 == 0
    status_out = capsys.readouterr().out
    assert '"r-ten"' in status_out


def test_status_projection_publishes_to_bounded_git_ref_without_touching_worktree(env):
    before = _git(env.checkout, "status", "--porcelain")
    status = {
        "schema_version": "clive.remote_engineering_status.v1",
        "generated_at": NOW.isoformat(),
        "requests": [],
    }
    first = publish_status(env.checkout, status)
    second = publish_status(env.checkout, status)
    assert first == second
    assert _git(env.checkout, "status", "--porcelain") == before
    _git(env.checkout, "fetch", "-q", "origin", DEFAULT_STATUS_BRANCH)
    published = _git(env.checkout, "show", f"origin/{DEFAULT_STATUS_BRANCH}:status.json")
    assert json.loads(published) == status


def test_status_projection_refuses_remote_url(env):
    with pytest.raises(InboxError):
        publish_status(env.checkout, {"requests": []}, remote="https://evil.example/repo.git")


def test_remote_loop_uses_existing_dispatcher_then_publishes_projection(tmp_path):
    calls = []

    class Controller:
        def poll_once(self):
            calls.append("poll")
            return [{"outcome": "accepted"}]

    class Dispatcher:
        def tick(self):
            calls.append("tick")
            return iter(["advanced"])

    store = LifecycleStore(tmp_path / "engineering")
    receipts = ReceiptLog(store.root / "remote_engineering")
    published = []

    loop = RemoteEngineeringLoop(
        controller=Controller(),
        dispatcher=Dispatcher(),
        store=store,
        receipts=receipts,
        publish=lambda status: published.append(status) or "a" * 40,
        clock=lambda: NOW,
    )
    result = loop.cycle()
    assert calls == ["poll", "tick"]
    assert result["dispatcher_events"] == ["advanced"]
    assert result["projection_commit"] == "a" * 40
    assert published[0]["schema_version"] == "clive.remote_engineering_status.v1"


def test_cli_exposes_long_lived_run_without_any_deploy_verb():
    parser = cli.build_parser()
    parsed = parser.parse_args([
        "--store", "x", "--repo", "y", "run",
        "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main",
        "--max-cycles", "1",
    ])
    assert parsed.verb == "run"
    with pytest.raises(SystemExit):
        parser.parse_args(["--store", "x", "--repo", "y", "deploy"])


def test_run_refuses_to_publish_status_over_owner_inbox(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_kernel_parts", lambda args: (
        LifecycleStore(Path(args.store)),
        SimpleNamespace(),
        SimpleNamespace(),
        ReceiptLog(Path(args.store) / "remote_engineering"),
    ))
    rc = cli.run([
        "--store", "/tmp/remote-engineering-test-store",
        "--repo", "/tmp/remote-engineering-test-repo",
        "run",
        "--repository", "crooksldn-pixel/clive",
        "--product-memory-ref", "main",
        "--branch", DEFAULT_INBOX_BRANCH,
        "--status-branch", DEFAULT_INBOX_BRANCH,
        "--max-cycles", "1",
    ])
    assert rc == 2
    assert "status branch must be separate" in capsys.readouterr().err


# ---------------------------------------------------------------- activation successor: projection and loop bounds


def _status_at(stamp: datetime, requests: list | None = None) -> dict:
    return {
        "schema_version": "clive.remote_engineering_status.v1",
        "generated_at": stamp.isoformat(),
        "requests": requests or [],
    }


def _status_log(env) -> list[str]:
    _git(env.checkout, "fetch", "-q", "origin", f"+refs/heads/{DEFAULT_STATUS_BRANCH}:refs/remotes/origin/{DEFAULT_STATUS_BRANCH}")
    return _git(env.checkout, "rev-list", f"origin/{DEFAULT_STATUS_BRANCH}").splitlines()


def test_status_projection_is_not_republished_when_only_generated_at_changes(env):
    first = publish_status(env.checkout, _status_at(NOW))
    second = publish_status(env.checkout, _status_at(NOW + timedelta(seconds=15)))
    third = publish_status(env.checkout, _status_at(NOW + timedelta(seconds=599)))
    assert first == second == third
    assert _status_log(env) == [first]


def test_status_projection_heartbeat_and_real_changes_republish_as_fast_forwards(env):
    first = publish_status(env.checkout, _status_at(NOW))
    beat = publish_status(env.checkout, _status_at(NOW + timedelta(seconds=600)))
    changed = publish_status(env.checkout, _status_at(NOW + timedelta(seconds=601), [{"request_id": "r-x"}]))
    assert len({first, beat, changed}) == 3
    assert _status_log(env) == [changed, beat, first]
    assert json.loads(_git(env.checkout, "show", f"{changed}:status.json"))["requests"] == [{"request_id": "r-x"}]


def test_status_projection_reads_a_fresh_head_from_another_publisher(env, tmp_path):
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(env.origin), str(other))
    first = publish_status(other, _status_at(NOW))
    second = publish_status(env.checkout, _status_at(NOW + timedelta(seconds=5), [{"request_id": "r-y"}]))
    assert _status_log(env) == [second, first]


@pytest.mark.parametrize("branch", ["main", DEFAULT_INBOX_BRANCH, "clive/objective/demo", "clive/controlx"])
def test_status_projection_refuses_branches_outside_the_dedicated_namespace(env, branch):
    heads_before = _git(env.origin, "for-each-ref", "refs/heads")
    with pytest.raises(InboxError):
        publish_status(env.checkout, _status_at(NOW), branch=branch)
    assert _git(env.origin, "for-each-ref", "refs/heads") == heads_before


def test_status_projection_refuses_to_overwrite_a_branch_that_is_not_a_pure_projection(env):
    _git(env.origin, "branch", "clive/control/status-real-work", "main")
    before = _git(env.origin, "rev-parse", "clive/control/status-real-work")
    with pytest.raises(InboxError, match="not a pure status projection"):
        publish_status(env.checkout, _status_at(NOW), branch="clive/control/status-real-work")
    assert _git(env.origin, "rev-parse", "clive/control/status-real-work") == before


def test_status_projection_distinguishes_an_unreachable_remote_from_a_missing_branch(env):
    _git(env.checkout, "remote", "add", "gone", str(env.origin.parent / "does-not-exist"))
    with pytest.raises(InboxError, match="cannot read status branch"):
        publish_status(env.checkout, _status_at(NOW), remote="gone")


def test_status_projection_follows_the_repair_revision_not_revision_one(tmp_path):
    from tests.test_engineering_dispatcher import FINDING, OBJ, World, review

    w = World(tmp_path)
    w.scenarios({"edits": [["pkg/hello.txt", "bye\n"]]}, {"edits": [["pkg/hello.txt", "hello\n"]]})
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[FINDING])
                              if ctx.task_revision == 1 else review(ctx, "READY"))
    w.run_until(lambda: w.stage() == "COMPLETE")
    receipts = ReceiptLog(w.store.root / "remote_engineering")
    receipts.put(Receipt(request_id="r-repair", request_sha256="0" * 64, outcome="accepted",
                         objective_id=OBJ, task_id=OBJ, source="requests/r-repair.json", recorded_at=NOW))
    _a1, a2 = w.store.read_attempts(OBJ)
    repaired = next(r for r in w.store.read_results() if r.attempt_id == a2.attempt_id).result_sha

    item = build_status(store=w.store, receipts=receipts, now=w.clock())["requests"][0]
    assert item["revision"] == 2
    assert item["stage"] == "COMPLETE"
    assert item["candidate_sha"] == repaired
    assert w.store.read_task_state(OBJ, 1).status is TaskStatus.OBSOLETE


class _Ticker:
    def __init__(self, events=("advanced",), error: Exception | None = None):
        self.calls = 0
        self.events = list(events)
        self.error = error

    def tick(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.events)


def _loop(controller, dispatcher, store, publish):
    return RemoteEngineeringLoop(controller=controller, dispatcher=dispatcher, store=store,
                                 receipts=ReceiptLog(store.root / "remote_engineering"), publish=publish,
                                 clock=lambda: NOW)


def test_a_changed_request_is_reported_but_the_dispatcher_keeps_supervising(env, tmp_path):
    commit_request(env.origin, "r-mut", valid_request(env, request_id="r-mut"))
    kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    commit_request(env.origin, "r-mut", valid_request(env, request_id="r-mut", requested_outcome="Changed."))
    ticker = _Ticker()
    loop = _loop(controller, ticker, kernel.store, lambda status: publish_status(env.checkout, status))

    result = loop.cycle()

    assert ticker.calls == 1 and result["dispatcher_events"] == ["advanced"]
    assert result["outcomes"] == [] and result["publish_error"] is None
    published = json.loads(_git(env.checkout, "show", f"{result['projection_commit']}:status.json"))
    assert "r-mut is already recorded with different content" in published["adapter"]["intake_error"]
    assert "Changed." not in json.dumps(published)
    assert [r["request_id"] for r in published["requests"]] == ["r-mut"]


def test_an_intake_transport_failure_never_projects_raw_git_output(tmp_path):
    secretish = "fatal: unable to access 'https://x-access-token:SYNTHETIC-NOT-A-TOKEN@example.invalid/r.git'"

    class Broken:
        def poll_once(self):
            raise InboxError(secretish)

    store = LifecycleStore(tmp_path / "engineering")
    published: list[dict] = []
    ticker = _Ticker()
    result = _loop(Broken(), ticker, store, lambda status: published.append(status) or "b" * 40).cycle()

    assert ticker.calls == 1
    # The host log is this same dict: `run` prints intake_error/publish_error verbatim, so
    # the raw transport text must be absent from the whole result, not only the projection.
    assert "SYNTHETIC-NOT-A-TOKEN" not in json.dumps(published)
    assert "SYNTHETIC-NOT-A-TOKEN" not in json.dumps(result, default=str)
    assert published[0]["adapter"]["intake_error"] == INTAKE_UNAVAILABLE
    assert result["intake_error"] == INTAKE_UNAVAILABLE


def test_a_publish_failure_is_reported_and_the_cycle_completes(tmp_path):
    class Quiet:
        def poll_once(self):
            return []

    def refuse(_status):
        raise InboxError("push rejected")

    store = LifecycleStore(tmp_path / "engineering")
    ticker = _Ticker()
    result = _loop(Quiet(), ticker, store, refuse).cycle()
    assert ticker.calls == 1
    assert result["projection_commit"] is None
    assert result["publish_error"] == PUBLISH_UNAVAILABLE
    assert "push rejected" not in json.dumps(result, default=str)


def test_kernel_failures_inside_the_dispatcher_still_stop_the_loop(tmp_path):
    from app.orchestrator.lifecycle import LifecycleError

    class Quiet:
        def poll_once(self):
            return []

    store = LifecycleStore(tmp_path / "engineering")
    published: list[dict] = []
    loop = _loop(Quiet(), _Ticker(error=LifecycleError("store refused")), store,
                 lambda status: published.append(status) or "c" * 40)
    with pytest.raises(LifecycleError):
        loop.cycle()
    assert published == []


def test_run_records_dispatcher_transitions_under_the_dispatcher_operator(tmp_path):
    args = cli.build_parser().parse_args([
        "--store", str(tmp_path / "engineering"), "--repo", str(tmp_path),
        "--runtime-root", str(tmp_path / "runtime"), "--workspace-root", str(tmp_path / "workers"),
        "--dispatcher-operator", "clive-dispatcher@test-host",
        "run", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main",
    ])
    _store, kernel, objectives, _receipts = cli._kernel_parts(args)
    dispatcher = cli._dispatcher(args, kernel, objectives)
    assert kernel.operator == "remote-engineering-inbox"
    assert dispatcher.kernel.operator == "clive-dispatcher@test-host"
    assert dispatcher.kernel.store is kernel.store and dispatcher.kernel.registry is kernel.registry
    assert dispatcher.kernel.journal_shas is not kernel.journal_shas
    assert args.status_heartbeat_s == 600.0


# ------------------------------------------------- activation successor 2: atomic intake and bounded reporting


def test_a_changed_request_admits_nothing_else_in_the_same_snapshot(env, tmp_path):
    """F-01: a valid request must not slip in ahead of a changed one it merely sorts before."""
    commit_request(env.origin, "b-changed", valid_request(env, request_id="b-changed"))
    kernel, objectives, receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()

    # "a-new" sorts before "b-changed", so the old sequential pass would have admitted it first.
    commit_request(env.origin, "a-new", valid_request(env, request_id="a-new"))
    commit_request(env.origin, "b-changed",
                   valid_request(env, request_id="b-changed", requested_outcome="Changed."))

    with pytest.raises(InboxError):
        controller.poll_once()

    assert objectives.read("a-new") is None
    assert kernel.store.read_task("a-new", 1) is None
    assert receipts.get("a-new") is None
    assert [r.request_id for r in receipts.read_all()] == ["b-changed"]
    assert objectives.read("b-changed").requested_outcome.startswith("Show unanswered")


def test_one_id_twice_in_a_snapshot_with_different_bytes_admits_nothing(env, tmp_path):
    """F-01: the conflict may also be inside a single snapshot, before anything is recorded."""
    commit_request(env.origin, "dup-record", valid_request(env, request_id="dup-record"), filename="dup-a.json")
    commit_request(env.origin, "dup-record", valid_request(env, request_id="dup-record", requested_outcome="Other."),
                   filename="dup-b.json")
    kernel, objectives, receipts, controller = make_controller(env, tmp_path)

    with pytest.raises(InboxError):
        controller.poll_once()

    assert objectives.read("dup-record") is None
    assert kernel.store.read_tasks() == ()
    assert receipts.read_all() == ()


def test_the_same_id_twice_with_identical_bytes_is_not_a_conflict(env, tmp_path):
    """The immutability rule is about changed bytes; a duplicated file is still one decision."""
    payload = valid_request(env, request_id="same-record")
    commit_request(env.origin, "same-record", payload, filename="same-a.json")
    commit_request(env.origin, "same-record", payload, filename="same-b.json")
    _kernel, objectives, receipts, controller = make_controller(env, tmp_path)

    outcomes = controller.poll_once()

    assert [o["outcome"] for o in outcomes] == ["accepted", "accepted"]
    assert objectives.read("same-record") is not None
    assert len(receipts.read_all()) == 1


def test_a_transport_failure_carries_no_git_output_into_its_message(env, monkeypatch):
    """F-02: git names the remote it failed to reach, and a remote URL can carry a credential."""
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    monkeypatch.setenv("GIT_ASKPASS", "true")
    url = "https://x-access-token:SYNTHETIC-NOT-A-TOKEN@example.invalid/r.git"
    _git(env.checkout, "remote", "add", "leaky", url)

    with pytest.raises(InboxError) as fetch_failure:
        fetch_inbox(env.checkout, remote="leaky", branch=DEFAULT_INBOX_BRANCH)
    assert "SYNTHETIC-NOT-A-TOKEN" not in str(fetch_failure.value)

    with pytest.raises(InboxError) as publish_failure:
        publish_status(env.checkout, _status_at(NOW), remote="leaky")
    assert "SYNTHETIC-NOT-A-TOKEN" not in str(publish_failure.value)
    assert "cannot read status branch" in str(publish_failure.value)


def test_a_rejected_schema_version_value_is_never_echoed():
    """F-02/F-03: the supplied value is rejected content and could itself be a credential."""
    secret = "sk-supersecrettoken1234567890"
    with pytest.raises(RequestSchemaError) as refusal:
        parse_request(json.dumps({"schema_version": secret}).encode())
    assert secret not in str(refusal.value)
    assert REQUEST_SCHEMA in str(refusal.value)


def test_a_malformed_record_is_visible_in_the_projection_and_survives_a_restart(env, tmp_path):
    """F-03: a record that never became a request id still has to be visible on GitHub."""
    secret = "sk-supersecrettoken1234567890"
    commit_request(env.origin, "bad-record-two", {"schema_version": REQUEST_SCHEMA, "api_key": secret},
                   filename="bad-record-two.json")
    kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    ticker = _Ticker()
    published: list[dict] = []
    loop = _loop(controller, ticker, kernel.store, lambda status: published.append(status) or "d" * 40)

    first = loop.cycle()

    assert first["status"]["requests"] == []
    refused = first["status"]["refused_records"]
    assert refused[0]["outcome"] == "refused"
    # A record with no trusted id is located by its digest, never by the name it chose.
    assert [r["source"] for r in refused] == [f"{DEFAULT_INBOX_DIRECTORY}/#{refused[0]['request_sha256']}"]
    assert refused[0]["refusal_id"] == f"{refused[0]['source']}@{refused[0]['request_sha256']}"
    assert secret not in json.dumps(published, default=str)
    assert secret not in json.dumps(first, default=str)

    # Restart: a new controller over the same store re-derives the identical refusal.
    kernel2, _objectives2, _receipts2, controller2 = make_controller(env, tmp_path)
    second = _loop(controller2, _Ticker(), kernel2.store,
                   lambda status: published.append(status) or "e" * 40).cycle()
    assert second["status"]["refused_records"] == refused


def test_an_accepted_request_leaves_the_refusal_projection_empty(env, tmp_path):
    commit_request(env.origin, "clean-record", valid_request(env, request_id="clean-record"))
    kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    result = _loop(controller, _Ticker(), kernel.store, lambda status: "f" * 40).cycle()
    assert result["status"]["refused_records"] == []
    assert [r["request_id"] for r in result["status"]["requests"]] == ["clean-record"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -1.0, MAX_HEARTBEAT_S + 1])
def test_publish_status_refuses_an_unbounded_heartbeat(env, bad):
    """F-04: a non-finite or out-of-range heartbeat disables generated_at suppression."""
    heads_before = _git(env.origin, "for-each-ref", "refs/heads")
    with pytest.raises(InboxError):
        publish_status(env.checkout, _status_at(NOW), heartbeat_s=bad)
    assert _git(env.origin, "for-each-ref", "refs/heads") == heads_before


@pytest.mark.parametrize("flag,value", [
    ("--interval", "nan"),
    ("--interval", "inf"),
    ("--interval", "0"),
    ("--interval", "-5"),
    ("--interval", "100000"),
    ("--status-heartbeat-s", "nan"),
    ("--status-heartbeat-s", "0"),
    ("--status-heartbeat-s", "-1"),
    ("--status-heartbeat-s", "999999999"),
])
def test_run_refuses_an_unbounded_timing_argument_before_any_cycle(monkeypatch, capsys, tmp_path, flag, value):
    """F-04: refused before the loop starts, so no poll, no tick and no publication happen."""
    started: list[str] = []
    monkeypatch.setattr(cli, "_kernel_parts", lambda args: (
        LifecycleStore(Path(args.store)),
        SimpleNamespace(),
        SimpleNamespace(),
        ReceiptLog(Path(args.store) / "remote_engineering"),
    ))
    monkeypatch.setattr(cli, "_controller", lambda *a, **k: started.append("controller"))
    monkeypatch.setattr(cli, "_dispatcher", lambda *a, **k: started.append("dispatcher"))

    rc = cli.run([
        "--store", str(tmp_path / "engineering"), "--repo", str(tmp_path),
        "run", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main",
        flag, value, "--max-cycles", "1",
    ])

    assert rc == 2
    assert flag in capsys.readouterr().err
    assert started == []


def test_run_accepts_the_documented_timing_defaults():
    args = cli.build_parser().parse_args([
        "--store", "x", "--repo", "y",
        "run", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main",
    ])
    assert args.interval == 15.0 and args.status_heartbeat_s == 600.0
    assert cli.validate_seconds(args.interval, what="--interval",
                                minimum=cli.MIN_INTERVAL_S, maximum=cli.MAX_INTERVAL_S) == 15.0


# --------------------------------------------- activation successor 3: nothing untrusted is echoed

SECRET_URL = "https://x-access-token:SYNTHETIC-NOT-A-TOKEN@example.invalid/r.git"


def _spy_git(controller):
    """Record every ref this controller hands to git, so a refusal can be proven pre-git."""
    seen: list[str] = []
    original = controller.kernel.git.rev_parse
    controller.kernel.git.rev_parse = lambda ref: seen.append(ref) or original(ref)
    return seen


@pytest.mark.parametrize("base_ref", [
    SECRET_URL,
    "--upload-pack=touch /tmp/pwned",
    "-oProxyCommand=touch /tmp/pwned",
    "main^{commit}",
    "main..other",
    "refs/heads/x.lock",
    "a" * 300,
])
def test_an_unbounded_base_ref_is_refused_before_git_and_never_echoed(env, tmp_path, base_ref):
    """F-01: base_ref reaches `git rev-parse`, and its refusal reason is published."""
    commit_request(env.origin, "r-ref", valid_request(env, request_id="r-ref", base_ref=base_ref))
    kernel, objectives, receipts, controller = make_controller(env, tmp_path)
    seen = _spy_git(controller)

    outcomes = controller.poll_once()

    assert outcomes[0]["outcome"] == "refused"
    assert seen == []  # refused by the schema, before git was asked anything
    assert objectives.read("r-ref") is None
    assert receipts.read_all() == ()
    status = build_status(store=kernel.store, receipts=receipts, now=NOW,
                          refusals=tuple(o for o in outcomes if "refusal_id" in o))
    for rendered in (json.dumps(outcomes), json.dumps(status)):
        assert base_ref not in rendered
        assert "SYNTHETIC-NOT-A-TOKEN" not in rendered
        assert "pwned" not in rendered


def test_a_resolvable_ref_that_disagrees_with_the_declared_sha_is_refused_without_echoing_it(env, tmp_path):
    commit_request(env.origin, "r-mismatch",
                   valid_request(env, request_id="r-mismatch", base_ref="main", base_sha="f" * 40))
    _kernel, objectives, receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert "base ref does not resolve" in outcomes[0]["reason"]
    assert "'main'" not in outcomes[0]["reason"]
    assert objectives.read("r-mismatch") is None
    assert receipts.get("r-mismatch") is not None  # the id was decided, so it earns a receipt


def test_a_credential_in_an_unknown_key_name_never_enters_any_output(env, tmp_path):
    """F-02: pydantic's loc segment for a forbidden extra field IS the requester's key name."""
    secret = "sk-supersecrettoken1234567890"
    payload = valid_request(env, request_id="r-key")
    payload[secret] = "anything"
    commit_request(env.origin, "r-key", payload)
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    ticker = _Ticker()
    published: list[dict] = []
    result = _loop(controller, ticker, kernel.store,
                   lambda status: published.append(status) or "a" * 40).cycle()

    assert secret not in json.dumps(result, default=str)
    assert secret not in json.dumps(published, default=str)
    assert secret not in json.dumps(build_status(store=kernel.store, receipts=receipts, now=NOW), default=str)
    assert "<redacted>" in json.dumps(result, default=str)


@pytest.mark.parametrize("filename", [
    "sk-supersecrettoken1234567890.json",
    "a b\tc.json",
    ("n" * 120) + ".json",
])
def test_an_untrusted_request_filename_is_replaced_by_an_opaque_locator(env, tmp_path, filename):
    """F-03: a requester chooses the filename, and `source` is published on a public branch."""
    commit_request(env.origin, "ignored-record", {"not": "a request"}, filename=filename)
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    published: list[dict] = []
    result = _loop(controller, _Ticker(), kernel.store,
                   lambda status: published.append(status) or "b" * 40).cycle()

    stem = filename[:-len(".json")]
    for rendered in (json.dumps(result, default=str), json.dumps(published, default=str)):
        assert stem not in rendered
    refused = result["status"]["refused_records"]
    assert len(refused) == 1
    assert refused[0]["source"] == f"{DEFAULT_INBOX_DIRECTORY}/#{refused[0]['request_sha256']}"
    assert receipts.read_all() == ()


def test_a_nested_request_path_is_replaced_by_an_opaque_locator(env, tmp_path):
    payload = valid_request(env, request_id="r-nested")
    commit_request(env.origin, "r-nested", payload, filename="sk-secretdir/r-nested.json")
    _kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert "sk-secretdir" not in json.dumps(outcomes)
    assert receipts.get("r-nested").source.startswith(f"{DEFAULT_INBOX_DIRECTORY}/#")


def test_a_plain_request_filename_is_still_reported_as_itself(env, tmp_path):
    commit_request(env.origin, "r-plain", valid_request(env, request_id="r-plain"))
    _kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    assert receipts.get("r-plain").source == f"{DEFAULT_INBOX_DIRECTORY}/r-plain.json"


def test_one_shot_poll_never_prints_a_credential_bearing_remote(env, tmp_path, capsys):
    """F-04: an operator who mistypes an authenticated URL into --remote must not print it."""
    rc = cli.run([
        "--store", str(tmp_path / "engineering"), "--repo", str(env.checkout), "--no-journal",
        "poll", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main",
        "--remote", SECRET_URL,
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert "SYNTHETIC-NOT-A-TOKEN" not in captured.out + captured.err
    assert SECRET_URL not in captured.out + captured.err
    assert "is not a bounded git identifier" in captured.err


def test_one_shot_poll_never_prints_an_escaping_branch_name(env, tmp_path, capsys):
    rc = cli.run([
        "--store", str(tmp_path / "engineering"), "--repo", str(env.checkout), "--no-journal",
        "poll", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main",
        "--branch", "../../SYNTHETIC-NOT-A-TOKEN",
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert "SYNTHETIC-NOT-A-TOKEN" not in captured.out + captured.err


# ------------------------------------------- activation successor 3: work bounds and fixed transport text

from app.remote_engineering import inbox as inbox_module  # noqa: E402
from app.remote_engineering.errors import InboxBoundExceeded  # noqa: E402
from app.remote_engineering.runner import INTAKE_OVER_BOUND  # noqa: E402

TOKEN_SHAPED = "ghp_SYNTHETICNOTATOKEN0123456789abcd"


def _commit_raw(origin: Path, files: dict[str, bytes], *, branch: str = DEFAULT_INBOX_BRANCH) -> None:
    exists = subprocess.run(["git", "rev-parse", "--verify", "--quiet", branch], cwd=origin,
                            capture_output=True).returncode == 0
    _git(origin, "checkout", "-q", branch) if exists else _git(origin, "checkout", "-q", "-b", branch)
    for name, body in files.items():
        target = origin / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    _git(origin, "add", "-A")
    _git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "raw inbox files")
    _git(origin, "checkout", "-q", "main")


def _admitted_nothing(kernel) -> bool:
    return kernel.store.read_tasks() == ()


def test_an_oversized_record_admits_nothing_and_the_dispatcher_still_ticks(env, tmp_path):
    commit_request(env.origin, "r-small", valid_request(env, request_id="r-small"))
    _commit_raw(env.origin, {"requests/r-huge.json": b"{" + b" " * (inbox_module.MAX_RECORD_BYTES + 1) + b"}"})
    kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    with pytest.raises(InboxBoundExceeded):
        controller.poll_once()
    ticker = _Ticker()
    result = _loop(controller, ticker, kernel.store, lambda status: "e" * 40).cycle()
    assert ticker.calls == 1
    assert result["intake_error"] == INTAKE_OVER_BOUND
    assert _admitted_nothing(kernel)


@pytest.mark.parametrize("bound, value", [
    ("MAX_INBOX_RECORDS", 2),
    ("MAX_SNAPSHOT_BYTES", 600),
    ("MAX_LISTING_BYTES", 120),
    ("MAX_DISCOVERY_S", 0.0),
])
def test_every_snapshot_bound_refuses_the_whole_snapshot(env, tmp_path, monkeypatch, bound, value):
    for request_id in ("r-b1", "r-b2", "r-b3"):
        commit_request(env.origin, request_id, valid_request(env, request_id=request_id))
    monkeypatch.setattr(inbox_module, bound, value)
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    with pytest.raises(InboxBoundExceeded) as refusal:
        controller.poll_once()
    assert "nothing was admitted" in str(refusal.value)
    assert _admitted_nothing(kernel) and receipts.read_all() == ()


def test_record_sizes_are_checked_before_any_record_is_read(env, tmp_path, monkeypatch):
    _commit_raw(env.origin, {"requests/r-huge.json": b"x" * (inbox_module.MAX_RECORD_BYTES + 1)})
    reads: list[list[str]] = []
    real = inbox_module._bounded_git

    def spy(repo, args, **kwargs):
        reads.append(list(args))
        return real(repo, args, **kwargs)

    monkeypatch.setattr(inbox_module, "_bounded_git", spy)
    _kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    with pytest.raises(InboxBoundExceeded):
        controller.poll_once()
    assert all(args[0] != "cat-file" for args in reads)


@pytest.mark.parametrize("name", [
    "clive/" + "a" * 201,
    "clive/control/inbox.lock",
    "clive/./inbox",
    "clive/.hidden",
    "clive//inbox",
    "clive/inbox.",
    "-clive",
])
def test_non_canonical_or_oversized_ref_names_are_refused_before_git(env, monkeypatch, name):
    def no_git(*_args, **_kwargs):
        raise AssertionError("git must not be called for a refused name")

    monkeypatch.setattr(inbox_module.subprocess, "run", no_git)
    with pytest.raises(InboxError) as refusal:
        fetch_inbox(env.checkout, branch=name)
    assert name not in str(refusal.value)


@pytest.mark.parametrize("remote", ["o" * 65, "origin/other", "origin.lock", ".origin", SECRET_URL])
def test_oversized_or_non_canonical_remote_names_are_refused_before_git(env, monkeypatch, remote):
    def no_git(*_args, **_kwargs):
        raise AssertionError("git must not be called for a refused remote")

    monkeypatch.setattr(inbox_module.subprocess, "run", no_git)
    with pytest.raises(InboxError) as refusal:
        fetch_inbox(env.checkout, remote=remote)
    assert remote not in str(refusal.value)


def test_an_accepted_token_shaped_remote_or_branch_is_never_printed(env, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    for extra in (["--remote", TOKEN_SHAPED], ["--branch", f"clive/control/{TOKEN_SHAPED}"]):
        rc = cli.run([
            "--store", str(tmp_path / "engineering"), "--repo", str(env.checkout), "--no-journal",
            "poll", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main", *extra,
        ])
        captured = capsys.readouterr()
        assert rc == 2
        assert TOKEN_SHAPED not in captured.out + captured.err
        assert "inbox fetch failed" in captured.err
    with pytest.raises(InboxError) as publish_failure:
        publish_status(env.checkout, _status_at(NOW), remote=TOKEN_SHAPED)
    assert TOKEN_SHAPED not in str(publish_failure.value)


def test_the_inbox_fetch_never_follows_tags_or_touches_other_refs(env, tmp_path):
    commit_request(env.origin, "r-tag", valid_request(env, request_id="r-tag"))
    _git(env.origin, "tag", "sneaky", DEFAULT_INBOX_BRANCH)
    _git(env.origin, "-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "sneaky-annotated", "-m", "x",
         DEFAULT_INBOX_BRANCH)
    before = set(_git(env.checkout, "for-each-ref", "--format=%(refname) %(objectname)").splitlines())
    sha = fetch_inbox(env.checkout)
    after = set(_git(env.checkout, "for-each-ref", "--format=%(refname) %(objectname)").splitlines())
    assert after - before == {f"refs/remotes/origin/{DEFAULT_INBOX_BRANCH} {sha}"}
    assert _git(env.checkout, "tag", "-l") == ""


@pytest.mark.parametrize("path", [
    "a\tb.json", "status.json\n100644 blob 0000000000000000000000000000000000000000\tx.json",
    "st\0atus.json", "status.JSON", ".status.json", "sub/status.json", "st.atus.json",
    "s" * 64 + ".json", "status json",
])
def test_status_paths_outside_the_allowlist_publish_nothing(env, path):
    heads_before = _git(env.origin, "for-each-ref", "refs/heads")
    with pytest.raises(InboxError) as refusal:
        publish_status(env.checkout, _status_at(NOW), path=path)
    assert path not in str(refusal.value)
    assert _git(env.origin, "for-each-ref", "refs/heads") == heads_before


def test_the_published_tree_is_built_nul_delimited_and_holds_one_file(env):
    commit = publish_status(env.checkout, _status_at(NOW), path="status.json")
    _git(env.checkout, "fetch", "-q", "origin", f"+refs/heads/{DEFAULT_STATUS_BRANCH}:refs/remotes/origin/{DEFAULT_STATUS_BRANCH}")
    assert _git(env.checkout, "ls-tree", "-r", "--name-only", commit).splitlines() == ["status.json"]


# ------------------------------------ activation successor 4: decoder containment and nothing supplied echoed

import dataclasses  # noqa: E402

from app.orchestrator.lifecycle import JournalError  # noqa: E402
from app.remote_engineering.errors import REDACTED  # noqa: E402

DEEP = b'{"schema_version": "clive.remote_engineering_request.v1", "x": ' + b"[" * 20000 + b"]" * 20000 + b"}"
HUGE_INT = b'{"schema_version": "clive.remote_engineering_request.v1", "x": 1' + b"1" * 5000 + b"}"


@pytest.mark.parametrize("raw", [DEEP, HUGE_INT, b"[" * 30000 + b"]" * 30000], ids=["deep-object", "huge-int", "deep-array"])
def test_decoder_failures_are_refusals_never_crashes(raw):
    assert len(raw) < inbox_module.MAX_RECORD_BYTES * 2
    with pytest.raises(RequestSchemaError) as refusal:
        parse_request(raw)
    assert "1111" not in str(refusal.value) and "[[[" not in str(refusal.value)


def test_a_deeply_nested_inbox_record_is_refused_and_the_dispatcher_still_ticks(env, tmp_path):
    assert len(DEEP) < inbox_module.MAX_RECORD_BYTES
    _commit_raw(env.origin, {"requests/r-deep.json": DEEP})
    kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    ticker = _Ticker()
    result = _loop(controller, ticker, kernel.store, lambda status: "f" * 40).cycle()
    assert ticker.calls == 1 and result["intake_error"] is None
    assert [o["outcome"] for o in result["outcomes"]] == ["refused"]
    assert _admitted_nothing(kernel)


def test_an_unexpected_intake_failure_is_contained_but_journal_failures_still_stop(tmp_path):
    store = LifecycleStore(tmp_path / "engineering")

    class Explodes:
        def __init__(self, exc):
            self.exc = exc

        def poll_once(self):
            raise self.exc

    ticker = _Ticker()
    result = _loop(Explodes(RecursionError("deep")), ticker, store, lambda status: "a" * 40).cycle()
    assert ticker.calls == 1 and result["intake_error"] == INTAKE_UNAVAILABLE
    assert "deep" not in json.dumps(result, default=str)
    with pytest.raises(JournalError):
        _loop(Explodes(JournalError("store")), _Ticker(), store, lambda status: "a" * 40).cycle()


@pytest.mark.parametrize(
    "directory", ["", "../requests", "a/b", "req uests", ".requests", "r" * 65, SECRET_URL],
    ids=["empty", "parent", "nested", "space", "dot", "long", "url"],
)
def test_an_inbox_directory_must_be_one_plain_component_and_is_never_echoed(env, directory):
    with pytest.raises(InboxError) as refusal:
        RemoteControllerConfig(repo=env.checkout, repository="crooksldn-pixel/clive",
                               product_memory_ref="main", inbox_directory=directory)
    assert directory not in str(refusal.value) or directory == ""


def test_a_configured_inbox_directory_never_reaches_receipts_outcomes_or_the_projection(env, tmp_path):
    good = valid_request(env, request_id="r-dir1")
    _commit_raw(env.origin, {
        f"{TOKEN_SHAPED}/r-dir1.json": json.dumps(good).encode(),
        f"{TOKEN_SHAPED}/odd-name.json": b"not json",
    })
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    controller.config = dataclasses.replace(controller.config, inbox_directory=TOKEN_SHAPED)
    outcomes = controller.poll_once()
    refusals = tuple(item for item in outcomes if "refusal_id" in item)
    status = build_status(store=kernel.store, receipts=receipts, now=NOW, refusals=refusals)
    everything = json.dumps({"outcomes": outcomes, "status": status}, default=str)
    assert TOKEN_SHAPED not in everything
    assert {o.get("source") for o in outcomes} == {"requests/r-dir1.json", f"requests/#{refusals[0]['request_sha256']}"}


def test_the_cli_no_longer_accepts_an_inbox_directory(tmp_path):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([
            "--store", "x", "--repo", "y", "poll", "--repository", "crooksldn-pixel/clive",
            "--product-memory-ref", "main", "--directory", "requests",
        ])


@pytest.mark.parametrize("paths", [
    [f"crooks-assistant/app/orchestrator/workers/{TOKEN_SHAPED}"],
    [f"../{TOKEN_SHAPED}"],
    [f"/{TOKEN_SHAPED}/x/"],
])
def test_an_intake_refusal_never_records_or_publishes_a_supplied_value(env, tmp_path, capsys, paths):
    request = valid_request(env, request_id="r-leak1", allowed_paths=paths)
    commit_request(env.origin, "r-leak1", request)
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert [o["outcome"] for o in outcomes] == ["refused"]
    reason = outcomes[0]["reason"]
    assert "cannot become an objective" in reason and REDACTED in reason
    status = build_status(store=kernel.store, receipts=receipts, now=NOW)
    stored = [r.model_dump(mode="json") for r in receipts.read_all()]
    assert TOKEN_SHAPED not in json.dumps({"o": outcomes, "s": status, "r": stored}, default=str)


# ------------------------------------------- activation successor 5: crash-safe intake provenance


class _CrashOnAccept(ReceiptLog):
    """A receipt log that dies exactly in the window the claim exists to close."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.crashed = 0

    def put(self, receipt: Receipt) -> Receipt:
        if receipt.outcome == "accepted":
            self.crashed += 1
            raise RuntimeError("process died after intake, before the receipt")
        return super().put(receipt)


def _advancing_clock(start: datetime = NOW, step: timedelta = timedelta(minutes=5)):
    """A clock that moves, as a real host's does between a crash and its restart."""
    state = {"now": start}

    def tick() -> datetime:
        value = state["now"]
        state["now"] = value + step
        return value

    return tick


def _crash_controller(env: SimpleNamespace, tmp_path: Path):
    store = LifecycleStore(tmp_path / "engineering")
    kernel = Kernel(store=store, registry=PrincipalRegistry.load(REGISTRY), git=GitFacts(env.checkout),
                    operator="remote-test", journal=False, clock=lambda: NOW)
    objectives = ObjectiveStore(store, journal=False)
    receipts = _CrashOnAccept(store.root / "remote_engineering")
    config = RemoteControllerConfig(repo=env.checkout, repository="crooksldn-pixel/clive",
                                    product_memory_ref="main")
    controller = RemoteController(kernel=kernel, objectives=objectives, config=config, receipts=receipts,
                                  clock=_advancing_clock())
    return kernel, objectives, receipts, controller


def _live_controller(env: SimpleNamespace, tmp_path: Path):
    """A fresh process over the same store, with its own later clock."""
    store = LifecycleStore(tmp_path / "engineering")
    kernel = Kernel(store=store, registry=PrincipalRegistry.load(REGISTRY), git=GitFacts(env.checkout),
                    operator="remote-test", journal=False, clock=lambda: NOW)
    objectives = ObjectiveStore(store, journal=False)
    receipts = ReceiptLog(store.root / "remote_engineering")
    config = RemoteControllerConfig(repo=env.checkout, repository="crooksldn-pixel/clive",
                                    product_memory_ref="main")
    controller = RemoteController(kernel=kernel, objectives=objectives, config=config, receipts=receipts,
                                  clock=_advancing_clock(NOW + timedelta(hours=1)))
    return kernel, objectives, receipts, controller


def test_the_claim_is_written_before_any_lifecycle_write(env, tmp_path, monkeypatch):
    """The binding must already be on disk when the first authoritative write is attempted."""
    commit_request(env.origin, "r-order", valid_request(env, request_id="r-order"))
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    seen: list[str | None] = []

    def spy(objective, *, kernel, objectives):
        seen.append(controller.claims.get("r-order").request_sha256 if controller.claims.get("r-order") else None)
        raise LifecycleError("refused at the canonical door")

    monkeypatch.setattr("app.remote_engineering.controller.intake", spy)
    outcomes = controller.poll_once()

    assert outcomes[0]["outcome"] == "refused"
    assert seen and seen[0] is not None          # claimed before intake was ever called
    assert objectives.read("r-order") is None
    assert controller.claims.get("r-order").request_sha256 == outcomes[0]["request_sha256"]


def test_a_crash_between_intake_and_the_receipt_recovers_idempotently(env, tmp_path):
    """The window the reviewer named: lifecycle written, receipt not, process gone."""
    commit_request(env.origin, "r-crash", valid_request(env, request_id="r-crash"))
    kernel, objectives, receipts, controller = _crash_controller(env, tmp_path)

    with pytest.raises(RuntimeError):
        controller.poll_once()

    # The objective is admitted, the receipt never landed, the claim did.
    assert receipts.crashed == 1
    assert objectives.read("r-crash") is not None
    assert kernel.store.read_task("r-crash", 1) is not None
    assert receipts.get("r-crash") is None
    claimed = controller.claims.get("r-crash")
    assert claimed is not None and claimed.claimed_at == NOW

    # Restart: the same bytes, a clock an hour later. Recovery must be byte-identical,
    # not merely equivalent, or the objective store refuses its own record.
    kernel2, objectives2, receipts2, controller2 = _live_controller(env, tmp_path)
    outcomes = controller2.poll_once()

    assert outcomes[0]["outcome"] == "accepted"
    assert outcomes[0]["request_sha256"] == claimed.request_sha256
    assert receipts2.get("r-crash").objective_id == "r-crash"
    assert objectives2.read("r-crash").created_at == NOW      # the claimed instant, not the new one
    assert len(kernel2.store.read_tasks()) == 1
    assert kernel2.store.read_attempts() == ()


def test_a_crash_before_the_receipt_still_refuses_changed_bytes_for_that_id(env, tmp_path):
    """Provenance may not be replaced by bytes that merely parse to the same request."""
    commit_request(env.origin, "r-swap", valid_request(env, request_id="r-swap"))
    _kernel, objectives, _receipts, controller = _crash_controller(env, tmp_path)
    with pytest.raises(RuntimeError):
        controller.poll_once()
    claimed = controller.claims.get("r-swap")

    # Same id, same parsed request, different bytes (whitespace only).
    payload = valid_request(env, request_id="r-swap")
    directory = env.origin / DEFAULT_INBOX_DIRECTORY
    _git(env.origin, "checkout", "-q", DEFAULT_INBOX_BRANCH)
    (directory / "r-swap.json").write_text(json.dumps(payload, indent=4))
    _git(env.origin, "add", "-A")
    _git(env.origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "reformat")
    _git(env.origin, "checkout", "-q", "main")

    _kernel2, objectives2, receipts2, controller2 = _live_controller(env, tmp_path)
    with pytest.raises(InboxError):
        controller2.poll_once()

    assert controller2.claims.get("r-swap").request_sha256 == claimed.request_sha256
    assert receipts2.get("r-swap") is None
    assert objectives2.read("r-swap").requested_outcome == objectives.read("r-swap").requested_outcome


def test_an_interrupted_id_refuses_its_whole_snapshot_before_any_write(env, tmp_path):
    """The claim participates in preflight, so admission stays atomic per cycle."""
    commit_request(env.origin, "b-claimed", valid_request(env, request_id="b-claimed"))
    _kernel, _objectives, _receipts, controller = _crash_controller(env, tmp_path)
    with pytest.raises(RuntimeError):
        controller.poll_once()

    commit_request(env.origin, "a-fresh", valid_request(env, request_id="a-fresh"))
    commit_request(env.origin, "b-claimed",
                   valid_request(env, request_id="b-claimed", requested_outcome="Changed."))

    kernel2, objectives2, receipts2, controller2 = _live_controller(env, tmp_path)
    with pytest.raises(InboxError):
        controller2.poll_once()

    assert objectives2.read("a-fresh") is None
    assert kernel2.store.read_task("a-fresh", 1) is None
    assert receipts2.get("a-fresh") is None
    assert controller2.claims.get("a-fresh") is None


def test_a_claim_is_write_once_and_refuses_divergent_bytes(tmp_path):
    claims = ClaimLog(tmp_path / "remote_engineering")
    first = Claim(request_id="r", request_sha256="a" * 64, claimed_at=NOW)
    assert claims.put(first) == first
    assert claims.put(first) == first                     # identical bytes are idempotent
    assert claims.get("r").request_sha256 == "a" * 64
    with pytest.raises(InboxError):
        claims.put(Claim(request_id="r", request_sha256="b" * 64, claimed_at=NOW))
    assert claims.get("r").request_sha256 == "a" * 64


def test_a_claim_carries_pointers_only_never_a_second_lifecycle_store():
    assert set(Claim.model_fields) == {"schema_version", "request_id", "request_sha256", "claimed_at"}
    assert not hasattr(ClaimLog, "advance") and not hasattr(ClaimLog, "resolve")


# ------------------------------------- activation successor 6: constrained ids, durable atomic claims

# Schema-valid under the previous id pattern, and credential-shaped: one long run and a
# dotted form. Neither is a slug, so neither is admitted now.
#
# Assembled at runtime from a bare prefix and a repeating body. The secret scanner reads
# this file, so a credential-shaped fixture written as a literal would be a finding in its
# own right -- which is exactly what it was, and it failed the secret_scan gate and, with
# it, the control assertion in test_acceptance_provenance that needs a clean tree.
TOKEN_ID = "sk-" + "proj-" + "abc123" * 6
DOTTED_TOKEN_ID = "ghp" + "." + "abcdef" * 6


@pytest.mark.parametrize("request_id", [TOKEN_ID, DOTTED_TOKEN_ID, "sk", "a-", "-a", "a--b",
                                        "a-" + "b" * 17, "-".join("abc" for _ in range(9)),
                                        "Mixed-Case", "has_underscore-x"])
def test_a_request_id_that_is_not_a_slug_is_refused(env, tmp_path, request_id):
    """F-01: the id reaches a claim, a receipt, a task id and the public projection."""
    payload = valid_request(env, request_id=request_id,
                            target_branch=f"clive/objective/{request_id}")
    commit_request(env.origin, request_id, payload, filename="candidate.json")
    _kernel, objectives, receipts, controller = make_controller(env, tmp_path)

    outcomes = controller.poll_once()

    assert outcomes[0]["outcome"] == "refused"
    assert objectives.read(request_id) is None
    assert receipts.read_all() == ()
    assert controller.claims.get(request_id) is None


@pytest.mark.parametrize("request_id", [TOKEN_ID, DOTTED_TOKEN_ID])
def test_a_credential_shaped_request_id_is_never_echoed(env, tmp_path, request_id):
    """The refusal itself must not republish the very value that was refused.

    Only ids long enough to carry a secret are checked: the refusal quotes this host's own
    id pattern, and a two-character id is a substring of that fixed text rather than an echo.
    """
    payload = valid_request(env, request_id=request_id,
                            target_branch=f"clive/objective/{request_id}")
    commit_request(env.origin, request_id, payload, filename="candidate.json")
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)

    outcomes = controller.poll_once()
    status = build_status(store=kernel.store, receipts=receipts, now=NOW,
                          refusals=tuple(o for o in outcomes if "refusal_id" in o))

    for rendered in (json.dumps(outcomes), json.dumps(status)):
        assert request_id not in rendered


def test_every_id_this_system_actually_uses_is_still_admitted(env, tmp_path):
    """The constraint must not refuse the ids the Director and the runbooks already use."""
    for request_id in ("operational-alpha-acceptance-repair",
                       "remote-engineering-control-v1-activation-readiness",
                       "remote-loop-dispatcher-timing-parity"):
        assert parse_request(json.dumps(valid_request(env, request_id=request_id,
                                                      target_branch=f"clive/objective/{request_id}")
                                        ).encode()).request_id == request_id


@pytest.mark.parametrize("target_branch", [
    "clive/objective/something-else",
    "clive/objective/r-branch/../../secret",
    "refs/heads/r-branch",
    "clive/objective/r-branch-extra",
])
def test_a_target_branch_that_is_not_the_request_id_is_refused_without_echo(env, tmp_path, target_branch):
    """F-01: the dispatcher publishes this branch, so it carries the slug and nothing else."""
    payload = valid_request(env, request_id="r-branch", target_branch=target_branch)
    commit_request(env.origin, "r-branch", payload)
    _kernel, objectives, receipts, controller = make_controller(env, tmp_path)

    outcomes = controller.poll_once()

    assert outcomes[0]["outcome"] == "refused"
    assert objectives.read("r-branch") is None
    assert receipts.read_all() == ()
    assert target_branch not in json.dumps(outcomes)


def _fsync_spy(monkeypatch):
    """Record the path behind every fsynced descriptor, then do the real fsync."""
    seen: list[str] = []
    real = os.fsync

    def spy(fd: int) -> None:
        try:
            seen.append(os.readlink(f"/proc/self/fd/{fd}"))
        except OSError:  # pragma: no cover - only on a platform without /proc
            pass
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    return seen


def test_the_first_ever_claim_makes_each_new_directory_durable(tmp_path, monkeypatch):
    """F-02: on first intake both remote_engineering/ and claims/ are new."""
    root = tmp_path / "engineering" / "remote_engineering"
    seen = _fsync_spy(monkeypatch)
    ClaimLog(root).put(Claim(request_id="r-first", request_sha256="a" * 64, claimed_at=NOW))

    # Each newly created directory's own parent is flushed, so the entry that makes it
    # reachable survives, not merely the entry inside it.
    assert str(root.parent) in seen           # the entry that made remote_engineering/ reachable
    assert str(root) in seen                  # the entry that made claims/ reachable
    assert str(root / "claims") in seen       # the entry that made the claim file reachable


def test_an_existing_claims_directory_still_flushes_the_claim_itself(tmp_path, monkeypatch):
    root = tmp_path / "engineering" / "remote_engineering"
    claims = ClaimLog(root)
    claims.put(Claim(request_id="r-warm", request_sha256="a" * 64, claimed_at=NOW))
    seen = _fsync_spy(monkeypatch)
    claims.put(Claim(request_id="r-second", request_sha256="b" * 64, claimed_at=NOW))
    assert str(root / "claims") in seen


def test_two_claims_for_the_same_bytes_converge_on_one_record(tmp_path):
    """F-03: both processes found the id unclaimed; the create decides, not the check."""
    root = tmp_path / "remote_engineering"
    winner = ClaimLog(root).put(Claim(request_id="r-race", request_sha256="a" * 64, claimed_at=NOW))
    loser = ClaimLog(root).put(
        Claim(request_id="r-race", request_sha256="a" * 64, claimed_at=NOW + timedelta(minutes=3))
    )

    assert loser == winner                       # the loser adopts the winning record
    assert loser.claimed_at == NOW               # ...including its instant, not its own
    assert len(list((root / "claims").glob("*.json"))) == 1


def test_a_losing_claim_with_different_bytes_is_refused_before_any_lifecycle_write(env, tmp_path):
    """F-03: the loser must refuse a divergent digest, not intake under it."""
    payload = valid_request(env, request_id="r-lose")
    commit_request(env.origin, "r-lose", payload)
    _kernel, objectives, receipts, controller = make_controller(env, tmp_path)

    # Another process claimed this id first, for different bytes.
    controller.claims.put(Claim(request_id="r-lose", request_sha256="c" * 64, claimed_at=NOW))

    with pytest.raises(InboxError):
        controller.poll_once()

    assert objectives.read("r-lose") is None
    assert receipts.read_all() == ()
    assert controller.claims.get("r-lose").request_sha256 == "c" * 64


def test_a_concurrent_claim_makes_the_admission_use_the_winning_instant(env, tmp_path):
    """The loser's objective must be the winner's byte-identical one."""
    payload = valid_request(env, request_id="r-adopt")
    commit_request(env.origin, "r-adopt", payload)
    raw = json.dumps(payload, indent=2).encode()
    earlier = NOW - timedelta(minutes=11)
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.claims.put(Claim(request_id="r-adopt", request_sha256=sha256_of(raw), claimed_at=earlier))

    outcomes = controller.poll_once()

    assert outcomes[0]["outcome"] == "accepted"
    assert objectives.read("r-adopt").created_at == earlier


# ------------------------------------- journal-safe adapter records, every admitted id length

# Exactly REQUEST_ID_MAX_LENGTH characters: the longest id the request schema admits.
LONGEST_ID = "-".join(["longest" + "a" * 9, "b" * 16, "c" * 16, "d" * 16, "e" * 12])


@pytest.fixture
def no_host_git_config(monkeypatch):
    """No global excludes file or any other host-level git setting may be relied on."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _journalled_state(tmp_path: Path) -> Path:
    """A real git work tree to hold the store, carrying no ignore rule of any kind."""
    state = tmp_path / "state"
    state.mkdir()
    _git(state, "init", "-q", "-b", "clive/engineering-state")
    _git(state, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "root")
    exclude = state / ".git" / "info" / "exclude"
    rules = exclude.read_text().splitlines() if exclude.exists() else []
    assert [line for line in rules if line.strip() and not line.startswith("#")] == []
    assert not (state / ".gitignore").exists()
    return state


def _journalled_cli(env: SimpleNamespace, tmp_path: Path, verb: str, *extra: str) -> int:
    """The real CLI over a journalled store, with the adapter root outside its work tree."""
    return cli.run([
        "--store", str(tmp_path / "state" / "engineering"), "--adapter-root", str(tmp_path / "adapter"),
        "--repo", str(env.checkout),
        verb, "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main", *extra,
    ])


def test_a_request_is_admitted_through_a_journalled_store_to_an_accepted_receipt(env, tmp_path,
                                                                                 no_host_git_config):
    state = _journalled_state(tmp_path)
    store = LifecycleStore(state / "engineering")
    kernel = Kernel(store=store, registry=PrincipalRegistry.load(REGISTRY), git=GitFacts(env.checkout),
                    operator="remote-test", journal=True, clock=lambda: NOW)
    objectives = ObjectiveStore(store, journal=True)
    adapter_root = tmp_path / "adapter"                 # outside the store's git work tree
    adapter_root_preconditions(store.root, adapter_root)  # so the loop would start
    receipts = ReceiptLog(adapter_root)
    config = RemoteControllerConfig(repo=env.checkout, repository="crooksldn-pixel/clive", product_memory_ref="main")
    controller = RemoteController(kernel=kernel, objectives=objectives, config=config, receipts=receipts,
                                  clock=lambda: NOW)
    commit_request(env.origin, "r-journal", valid_request(env, request_id="r-journal"))

    outcomes = controller.poll_once()

    assert [o["outcome"] for o in outcomes] == ["accepted"]
    assert receipts.get("r-journal").outcome == "accepted"
    assert controller.claims.get("r-journal").request_sha256 == outcomes[0]["request_sha256"]
    assert kernel.store.read_task_state("r-journal", 1).status is TaskStatus.READY
    subjects = _git(state, "log", "--format=%s").splitlines()
    assert any(s.startswith("objective r-journal entered") for s in subjects)
    assert any(s.startswith("kernel: task r-journal r1 created") for s in subjects)
    assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""
    assert controller.poll_once() == outcomes             # a replay through the journal is still clean


def test_poll_and_run_refuse_to_start_while_adapter_records_would_be_unignored_store_state(
        env, tmp_path, capsys, monkeypatch, no_host_git_config):
    """The default adapter root lies inside the store: without an ignore rule nothing starts."""
    state = _journalled_state(tmp_path)
    store_dir = state / "engineering"
    commit_request(env.origin, "r-unsafe", valid_request(env, request_id="r-unsafe"))
    started: list[str] = []
    monkeypatch.setattr(cli, "_dispatcher", lambda *a, **k: started.append("dispatcher"))

    for verb, extra in (("poll", []), ("run", ["--max-cycles", "1"])):
        rc = cli.run([
            "--store", str(store_dir), "--repo", str(env.checkout),
            verb, "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main", *extra,
        ])
        captured = capsys.readouterr()
        assert rc == 2
        assert ADAPTER_ROOT_NOT_IGNORED in captured.err
        assert str(state) not in captured.out + captured.err

    assert started == []
    assert not (store_dir / "remote_engineering").exists()   # nothing claimed, so no id was burned
    assert not (store_dir / "objectives").exists()
    assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""


def test_the_adapter_root_guard_admits_only_records_the_journal_cannot_see(tmp_path, no_host_git_config):
    state = _journalled_state(tmp_path)
    store_root = state / "engineering"
    inside = store_root / "remote_engineering"

    with pytest.raises(InboxError) as refusal:
        adapter_root_preconditions(store_root, inside)
    assert str(refusal.value) == ADAPTER_ROOT_NOT_IGNORED
    adapter_root_preconditions(store_root, tmp_path / "adapter")

    # A committed rule is carried by every clone, unlike a host's .git/info/exclude.
    (state / ".gitignore").write_text("/engineering/remote_engineering/\n")
    _git(state, "add", ".gitignore")
    _git(state, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ignore adapter records")
    adapter_root_preconditions(store_root, inside)


@pytest.mark.parametrize("rules", [
    "/engineering/remote_engineering/claims/request.json\n/engineering/remote_engineering/receipts/request.json\n",
    "/engineering/remote_engineering/claims/*.json\n/engineering/remote_engineering/receipts/*.json\n",
], ids=["only-the-old-probe-files", "record-names-but-not-temporary-files"])
def test_poll_and_run_refuse_when_only_some_record_files_are_ignored(env, tmp_path, capsys, monkeypatch,
                                                                     no_host_git_config, rules):
    """F-01: rules that cover sample file names, not the record directories, are not safety."""
    state = _journalled_state(tmp_path)
    store_dir = state / "engineering"
    (state / ".gitignore").write_text(rules)
    _git(state, "add", ".gitignore")
    _git(state, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ignore some records")
    commit_request(env.origin, "r-narrow", valid_request(env, request_id="r-narrow"))
    started: list[str] = []
    monkeypatch.setattr(cli, "_dispatcher", lambda *a, **k: started.append("dispatcher"))

    with pytest.raises(InboxError) as refusal:
        adapter_root_preconditions(store_dir, store_dir / "remote_engineering")
    assert str(refusal.value) == ADAPTER_ROOT_NOT_IGNORED

    for verb, extra in (("poll", []), ("run", ["--max-cycles", "1"])):
        rc = cli.run([
            "--store", str(store_dir), "--repo", str(env.checkout),
            verb, "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main", *extra,
        ])
        captured = capsys.readouterr()
        assert rc == 2
        assert ADAPTER_ROOT_NOT_IGNORED in captured.err
        assert "r-narrow" not in captured.out + captured.err

    assert started == []
    assert ClaimLog(store_dir / "remote_engineering").get("r-narrow") is None
    assert not (store_dir / "remote_engineering").exists()   # nothing claimed, so no id was burned
    assert not (store_dir / "objectives").exists()
    assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""


def test_the_longest_admitted_id_reaches_an_accepted_receipt_in_one_shot_poll(env, tmp_path, capsys,
                                                                              no_host_git_config):
    assert len(LONGEST_ID) == REQUEST_ID_MAX_LENGTH
    parse_request(json.dumps(valid_request(env, request_id=LONGEST_ID)).encode())
    state = _journalled_state(tmp_path)
    commit_request(env.origin, LONGEST_ID, valid_request(env, request_id=LONGEST_ID))

    rc = _journalled_cli(env, tmp_path, "poll")

    captured = capsys.readouterr()
    assert rc == 0 and captured.err == ""
    assert [o["outcome"] for o in json.loads(captured.out)] == ["accepted"]
    receipt = ReceiptLog(tmp_path / "adapter").get(LONGEST_ID)
    assert receipt is not None and receipt.outcome == "accepted" and receipt.task_id == LONGEST_ID
    assert ClaimLog(tmp_path / "adapter").get(LONGEST_ID) is not None
    assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""


def test_the_longest_admitted_id_reaches_an_accepted_receipt_in_run(env, tmp_path, capsys, monkeypatch,
                                                                    no_host_git_config):
    state = _journalled_state(tmp_path)
    commit_request(env.origin, LONGEST_ID, valid_request(env, request_id=LONGEST_ID))
    ticker = _Ticker()
    monkeypatch.setattr(cli, "_dispatcher", lambda *a, **k: ticker)

    rc = _journalled_cli(env, tmp_path, "run", "--max-cycles", "1")

    captured = capsys.readouterr()
    assert rc == 0 and captured.err == ""
    cycle = json.loads(captured.out)
    assert cycle["intake_error"] is None and ticker.calls == 1
    assert [o["outcome"] for o in cycle["outcomes"]] == ["accepted"]
    assert ReceiptLog(tmp_path / "adapter").get(LONGEST_ID).outcome == "accepted"
    assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""


@pytest.mark.parametrize("request_id", [LONGEST_ID + "e", "-".join(["a" * 16] + ["b" * 16] * 7)],
                         ids=["one-past-the-boundary", "previous-pattern-maximum"])
def test_an_id_past_the_admitted_length_is_refused_before_any_claim_and_never_echoed(env, tmp_path, capsys,
                                                                                     request_id):
    assert len(request_id) > REQUEST_ID_MAX_LENGTH
    commit_request(env.origin, request_id, valid_request(env, request_id=request_id), filename="candidate.json")
    store_dir = tmp_path / "engineering"

    rc = cli.run([
        "--store", str(store_dir), "--repo", str(env.checkout), "--no-journal",
        "poll", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main",
    ])

    captured = capsys.readouterr()
    assert rc == 0
    assert [o["outcome"] for o in json.loads(captured.out)] == ["refused"]
    assert request_id not in captured.out + captured.err
    adapter = store_dir / "remote_engineering"
    assert ClaimLog(adapter).get(request_id) is None
    assert ReceiptLog(adapter).read_all() == ()


# ------------------------------------ why a task is stuck: findings, failing checks, worker report

import sys  # noqa: E402

from app.orchestrator.objectives import Check  # noqa: E402
from app.remote_engineering import status as status_module  # noqa: E402
from app.remote_engineering.errors import redact_published  # noqa: E402


def _blocked_item(w) -> tuple[dict, str]:
    """The projected request for the World's objective, and the whole published document."""
    from tests.test_engineering_dispatcher import OBJ

    receipts = ReceiptLog(w.store.root / "remote_engineering")
    receipts.put(Receipt(request_id="r-blocked", request_sha256="0" * 64, outcome="accepted",
                         objective_id=OBJ, task_id=OBJ, source="requests/r-blocked.json", recorded_at=NOW))
    status = build_status(store=w.store, receipts=receipts, now=w.clock())
    return status["requests"][0], json.dumps(status, sort_keys=True)


def test_a_convergence_limited_objective_publishes_its_open_findings_bounded_and_redacted(tmp_path):
    from tests.test_engineering_dispatcher import EDIT_HELLO, FINDING, World, review

    secret = "sk-ant-" + "q" * 40
    findings = [
        FINDING,
        {**FINDING, "finding_id": "F-02", "finding": f"the log prints {secret} in full"},
        {**FINDING, "finding_id": "N-01", "material": False, "finding": "a nit, not open"},
        *({**FINDING, "finding_id": f"F-{n:02d}", "finding": "x" * 4000} for n in range(3, 15)),
    ]
    w = World(tmp_path, max_repair_rounds=0)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=findings))
    w.run_until(w.status_is(TaskStatus.BLOCKED))

    item, published = _blocked_item(w)
    assert "convergence limit" in item["blocker"]
    found = item["open_findings"]
    assert found[0] == {"finding_id": "F-01", "finding": "the greeting is wrong"}
    assert found[1] == {"finding_id": "F-02", "finding": f"the log prints {REDACTED} in full"}
    assert [f["finding_id"] for f in found] == ["F-01", "F-02", *(f"F-{n:02d}" for n in range(3, 11))]
    assert len(found) == status_module.MAX_FINDINGS == 10
    assert found[2]["finding"] == "x" * status_module.MAX_FINDING_CHARS
    assert all(len(f["finding"]) <= status_module.MAX_FINDING_CHARS == 600 for f in found)
    assert item["failed_checks"] == [] and item["worker_report"] is None
    assert secret not in published


def test_a_refused_result_publishes_the_failing_checks_tail_redacted_and_bounded(tmp_path):
    from tests.test_engineering_dispatcher import EDIT_HELLO, World

    token, key_body = "ghp_" + "Z" * 36, "b3BlbnNzaC1rZXktdjEAAAAABG5vbmU"
    credential_path, password = "/etc/crooks-os/secrets/gmail_token", "hunter2" * 2
    says_hello = "\n".join([
        "import sys",
        "for n in range(80): print(f'line {n}')",
        f"print('pushing with {token}')",
        "print('-----BEGIN OPENSSH PRIVATE KEY-----')",
        f"print('{key_body}')",
        "print('-----END OPENSSH PRIVATE KEY-----')",
        f"print('reading {credential_path}')",
        f"print('password={password}')",
        "sys.stderr.write('AssertionError: the greeting is wrong\\n')",
        "sys.exit(1)",
    ])
    wide = "for n in range(60): print(str(n).rjust(3) + ' ' + 'w' * 200)\nraise SystemExit(2)"
    checks = (Check(name="says-hello", argv=(sys.executable, "-c", says_hello)),
              Check(name="wide", argv=(sys.executable, "-c", wide)))
    w = World(tmp_path, checks=checks, max_result_refusals=1)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))

    item, published = _blocked_item(w)
    assert "checks failed" in item["blocker"]
    hello, wide_check = item["failed_checks"]
    assert (hello["name"], hello["exit_code"]) == ("says-hello", 1)
    lines = hello["output_tail"].splitlines()
    assert len(lines) == status_module.MAX_CHECK_TAIL_LINES == 40
    assert lines[-5:] == [f"pushing with {REDACTED}", REDACTED, f"reading {REDACTED}",
                          f"password={REDACTED}", "AssertionError: the greeting is wrong"]
    assert "line 79" in hello["output_tail"] and "line 0" not in hello["output_tail"]
    assert (wide_check["name"], wide_check["exit_code"]) == ("wide", 2)
    assert len(wide_check["output_tail"]) == status_module.MAX_CHECK_TAIL_CHARS == 4000
    assert wide_check["output_tail"].endswith(" 59 " + "w" * 200)
    assert len(wide_check["output_tail"].splitlines()) <= status_module.MAX_CHECK_TAIL_LINES
    for planted in (token, key_body, credential_path, password):
        assert planted not in published
    assert item["open_findings"] == [] and item["worker_report"] is None


def test_a_check_evidence_file_changed_after_it_was_recorded_is_not_published(tmp_path):
    from tests.test_engineering_dispatcher import EDIT_HELLO, OBJ, World

    w = World(tmp_path, checks=(Check(name="fails", argv=(sys.executable, "-c", "raise SystemExit(1)")),),
              max_result_refusals=1)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    attempt = w.store.read_attempts(OBJ)[0]
    evidence = next(e for e in w.store.read_events(OBJ, attempt.attempt_id) if e.evidence_name == "check-fails")
    assert [c["name"] for c in _blocked_item(w)[0]["failed_checks"]] == ["fails"]

    Path(evidence.evidence_path).write_text('{"name": "fails", "exit_code": 1, "stdout_tail": "not recorded"}')
    item, published = _blocked_item(w)
    assert item["failed_checks"] == [] and "not recorded" not in published


def test_a_worker_reported_block_publishes_the_report_redacted(tmp_path):
    from tests.test_engineering_dispatcher import World

    token = "ghp_" + "W" * 36
    w = World(tmp_path)
    w.scenarios({"report": {"status": "blocked", "summary": "cannot",
                            "reason": f"the fixture needs {token} from ~/.ssh/id_ed25519 to run"}})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))

    item, published = _blocked_item(w)
    assert item["worker_report"] == f"the fixture needs {REDACTED} from {REDACTED} to run"
    assert token not in published and "id_ed25519" not in published
    assert item["blocker"] == f"worker reported blocked: {item['worker_report']}"
    assert item["open_findings"] == [] and item["failed_checks"] == []


def test_a_request_that_is_not_stuck_publishes_nothing_extra(env, tmp_path):
    commit_request(env.origin, "r-idle", valid_request(env, request_id="r-idle"))
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    item = build_status(store=kernel.store, receipts=receipts, now=NOW)["requests"][0]
    assert (item["open_findings"], item["failed_checks"], item["worker_report"]) == ([], [], None)


@pytest.mark.parametrize("text, expected", [
    ("key: -----BEGIN RSA PRIVATE KEY-----\nMIIEpAIB\n-----END RSA PRIVATE KEY-----\nok", f"key: {REDACTED}\nok"),
    ("MIIEpAIB\nAAAAB3Nz\n-----END PRIVATE KEY-----\nok", f"{REDACTED}\nok"),
    ("ok\n-----BEGIN ENCRYPTED PRIVATE KEY-----\nMIIEpAIB", f"ok\n{REDACTED}"),
    ("fetch https://bot:" + "p" * 20 + "@github.com/x.git", f"fetch https://{REDACTED}@github.com/x.git"),
    ("curl -H Bearer " + "a1" * 20, f"curl -H Bearer {REDACTED}"),
    ("Authorization: Basic " + "a1" * 20, f"Authorization: {REDACTED} {REDACTED}"),
    ('{"api_key": "abc123abc123"}', f'{{"api_key": "{REDACTED}"}}'),
    ("key file /home/u/.config/clive/gpt.key: mode 644", f"key file {REDACTED} mode 644"),
    ("AKIA" + "B" * 16 + " and sk-" + "c" * 30, f"{REDACTED} and {REDACTED}"),
], ids=["key-block", "key-block-cut-at-begin", "key-block-cut-at-end", "url-userinfo", "bearer",
        "authorization", "assigned", "credential-path", "token-shapes"])
def test_published_text_is_redacted_by_shape(text, expected):
    assert redact_published(text) == expected


def test_published_redaction_leaves_ordinary_check_output_readable():
    text = ("FAILED tests/test_remote_engineering.py::test_a_secret_is_redacted - assert 'hello' == 'bye'\n"
            "task-status-publishes-findings r2: max_tokens 5, app/remote_engineering/status.py:88")
    assert redact_published(text) == text
