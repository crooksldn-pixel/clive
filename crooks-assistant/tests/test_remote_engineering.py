"""The bounded GitHub inbox and controller adapter: same or less authority than CLI intake, idempotent, no second store."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
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
from tests.fake_credentials import LOWER_ALNUM, credential_url, github_token, openai_key

REGISTRY = Path(__file__).resolve().parent.parent / "config" / "review_principals.json"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
# A credential a requester might paste into a request, and the installation token a git remote URL
# carries. Both come from the shared helper (owner rule B): no credential is written as a literal here.
LEAKED_KEY = openai_key("remote-engineering", kind="")
URL_TOKEN = github_token("remote-engineering-url", kind="s")
SECRET_URL = credential_url(URL_TOKEN)


def fake_free_id(value: object) -> str | None:
    """A parametrized case's id with no fake credential in it: pytest would otherwise use the value
    itself, and print it in every report and CI log. None keeps pytest's own id."""
    for name, fake in (("leaked-key", LEAKED_KEY), ("url-token", URL_TOKEN), ("token-shaped", TOKEN_SHAPED),
                       ("token-id", TOKEN_ID), ("dotted-token-id", DOTTED_TOKEN_ID)):
        if fake in str(value):
            return name
    return None


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
    secret = LEAKED_KEY
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


def _other_commit(env: SimpleNamespace) -> str:
    """A commit the engineering repo has, which is not the one `main` resolves to.

    A declared sha the repo does not have at all is no longer a mismatch: the loop waits for it
    (the 2026-09-30 base wait, below). A mismatch is a ref naming a different commit that exists."""
    return _git(env.checkout, "-c", "user.name=t", "-c", "user.email=t@t",
                "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "elsewhere")


def test_base_ref_must_resolve_to_the_declared_sha(env, tmp_path):
    commit_request(env.origin, "r-eleven", valid_request(env, request_id="r-eleven", base_sha=_other_commit(env)))
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
    secretish = f"fatal: unable to access '{SECRET_URL}'"

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
    assert URL_TOKEN not in json.dumps(published)
    assert URL_TOKEN not in json.dumps(result, default=str)
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
        "--dispatcher-operator", "clive-dispatcher@test-host", "--publish-remote", "origin",
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
    url = SECRET_URL
    _git(env.checkout, "remote", "add", "leaky", url)

    with pytest.raises(InboxError) as fetch_failure:
        fetch_inbox(env.checkout, remote="leaky", branch=DEFAULT_INBOX_BRANCH)
    assert URL_TOKEN not in str(fetch_failure.value)

    with pytest.raises(InboxError) as publish_failure:
        publish_status(env.checkout, _status_at(NOW), remote="leaky")
    assert URL_TOKEN not in str(publish_failure.value)
    assert "cannot read status branch" in str(publish_failure.value)


def test_a_rejected_schema_version_value_is_never_echoed():
    """F-02/F-03: the supplied value is rejected content and could itself be a credential."""
    secret = LEAKED_KEY
    with pytest.raises(RequestSchemaError) as refusal:
        parse_request(json.dumps({"schema_version": secret}).encode())
    assert secret not in str(refusal.value)
    assert REQUEST_SCHEMA in str(refusal.value)


def test_a_malformed_record_is_visible_in_the_projection_and_survives_a_restart(env, tmp_path):
    """F-03: a record that never became a request id still has to be visible on GitHub."""
    secret = LEAKED_KEY
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
], ids=fake_free_id)
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
        assert URL_TOKEN not in rendered
        assert "pwned" not in rendered


def test_a_resolvable_ref_that_disagrees_with_the_declared_sha_is_refused_without_echoing_it(env, tmp_path):
    commit_request(env.origin, "r-mismatch",
                   valid_request(env, request_id="r-mismatch", base_ref="main", base_sha=_other_commit(env)))
    _kernel, objectives, receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert "base ref does not resolve" in outcomes[0]["reason"]
    assert "'main'" not in outcomes[0]["reason"]
    assert objectives.read("r-mismatch") is None
    assert receipts.get("r-mismatch") is not None  # the id was decided, so it earns a receipt


def test_a_credential_in_an_unknown_key_name_never_enters_any_output(env, tmp_path):
    """F-02: pydantic's loc segment for a forbidden extra field IS the requester's key name."""
    secret = LEAKED_KEY
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
    f"{LEAKED_KEY}.json",
    "a b\tc.json",
    ("n" * 120) + ".json",
], ids=fake_free_id)
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
    directory = openai_key("remote-engineering-dir", kind="", length=16)
    commit_request(env.origin, "r-nested", payload, filename=f"{directory}/r-nested.json")
    _kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert directory not in json.dumps(outcomes)
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
    assert URL_TOKEN not in captured.out + captured.err
    assert SECRET_URL not in captured.out + captured.err
    assert "is not a bounded git identifier" in captured.err


def test_one_shot_poll_never_prints_an_escaping_branch_name(env, tmp_path, capsys):
    rc = cli.run([
        "--store", str(tmp_path / "engineering"), "--repo", str(env.checkout), "--no-journal",
        "poll", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main",
        "--branch", f"../../{URL_TOKEN}",
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert URL_TOKEN not in captured.out + captured.err


# ------------------------------------------- activation successor 3: work bounds and fixed transport text

from app.remote_engineering import inbox as inbox_module  # noqa: E402
from app.remote_engineering.errors import InboxBoundExceeded  # noqa: E402
from app.remote_engineering.runner import INTAKE_OVER_BOUND  # noqa: E402

TOKEN_SHAPED = github_token("remote-engineering-shaped")


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


@pytest.mark.parametrize("remote", ["o" * 65, "origin/other", "origin.lock", ".origin", SECRET_URL],
                         ids=fake_free_id)
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
# Assembled at runtime by the shared helper, in lower case as the previous pattern required.
# The secret scanner reads this file, so a credential-shaped fixture written as a literal would
# be a finding in its own right -- which is exactly what it once was, and it failed the
# secret_scan gate and, with it, the control assertion in test_acceptance_provenance that needs
# a clean tree.
TOKEN_ID = openai_key("request-id", alphabet=LOWER_ALNUM, length=36)
DOTTED_TOKEN_ID = github_token("request-id", alphabet=LOWER_ALNUM).replace("_", ".")


@pytest.mark.parametrize("request_id", [TOKEN_ID, DOTTED_TOKEN_ID, "sk", "a-", "-a", "a--b",
                                        "a-" + "b" * 17, "-".join("abc" for _ in range(9)),
                                        "Mixed-Case", "has_underscore-x"], ids=fake_free_id)
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


@pytest.mark.parametrize("request_id", [TOKEN_ID, DOTTED_TOKEN_ID], ids=fake_free_id)
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


def test_the_hosts_own_exclude_rule_starts_the_loop_on_its_default_layout_and_a_restart_replays_it(
        env, tmp_path, capsys, no_host_git_config):
    """The re-pin review of a599a447, F-02: restart with the host's unchanged flags. clive-worker-01's unit
    passes no --adapter-root, so its claims and receipts live at the default <store>/remote_engineering,
    where the base loop (4c32bb3d, before this guard) wrote them in the same v1 records; and the host
    ignores that directory in the store's own .git/info/exclude (line 7 there reads exactly
    /engineering/remote_engineering/). With that rule, and only it, the default flags start; a restart
    with the same flags finds what was recorded and neither claims nor admits it again."""
    state = _journalled_state(tmp_path)
    store_dir = state / "engineering"
    exclude = state / ".git" / "info" / "exclude"
    exclude.write_text((exclude.read_text() if exclude.exists() else "") + "/engineering/remote_engineering/\n")
    adapter_root_preconditions(store_dir, store_dir / "remote_engineering")   # the guard admits the default
    commit_request(env.origin, "r-host", valid_request(env, request_id="r-host"))
    flags = ["--store", str(store_dir), "--repo", str(env.checkout),
             "poll", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main"]

    assert cli.run(flags) == 0
    first = capsys.readouterr()
    assert first.err == "" and [o["outcome"] for o in json.loads(first.out)] == ["accepted"]
    adapter = store_dir / "remote_engineering"
    written = sorted(path.relative_to(adapter).as_posix() for path in adapter.rglob("*.json"))
    assert written == ["claims/r-host.json", "receipts/r-host.json"]
    assert json.loads((adapter / "claims" / "r-host.json").read_text())["schema_version"] == \
        "clive.remote_engineering_claim.v1"
    assert json.loads((adapter / "receipts" / "r-host.json").read_text())["schema_version"] == \
        "clive.remote_engineering_receipt.v1"
    claim, receipt = ClaimLog(adapter).get("r-host"), ReceiptLog(adapter).get("r-host")
    assert receipt.outcome == "accepted" and claim is not None
    assert _git(state, "status", "--porcelain", "--untracked-files=all") == "", "the records are ignored state"

    # The restart: the same flags, the same store, the records already there.
    assert cli.run(flags) == 0
    again = capsys.readouterr()
    assert again.err == "" and json.loads(again.out) == json.loads(first.out)
    assert ClaimLog(adapter).get("r-host") == claim and ReceiptLog(adapter).get("r-host") == receipt
    subjects = _git(state, "log", "--format=%s").splitlines()
    assert sum(subject.startswith("objective r-host entered") for subject in subjects) == 1
    assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""


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


# --------------------------- loop update: the GitHub gate in the projection; findings text only through IDEA-066

FINDING_MARKERS = {
    "finding": "MARKER-FINDING-TEXT the greeting reads goodbye",
    "evidence_ref": "MARKER-EVIDENCE-REF pkg/hello.txt:1",
    "required_repair": "MARKER-REQUIRED-REPAIR write hello",
    "summary": "MARKER-REVIEW-SUMMARY prose for people only",
    "note": "MARKER-NON-MATERIAL-NOTE a style remark",
}


def _review_with_text(ctx, verdict: str) -> bytes:
    from tests.test_engineering_dispatcher import review

    body = json.loads(review(ctx, verdict))
    material = verdict == "CHANGES_REQUIRED"
    body["findings"] = [{"finding_id": "F-TEXT-1", "material": material, "finding": FINDING_MARKERS["finding"],
                         "evidence_ref": FINDING_MARKERS["evidence_ref"],
                         "required_repair": FINDING_MARKERS["required_repair"]}]
    if not material:
        body["findings"][0]["finding"] = FINDING_MARKERS["note"]
    body["summary"] = FINDING_MARKERS["summary"]
    return json.dumps(body).encode()


def test_the_published_status_never_carries_review_findings_text(tmp_path):
    """Findings, their evidence refs, required repairs and the reviewer's summary stay in the store.

    Interim, not the direction: IDEA-066 (the status publishes why an objective is stuck, so the
    owner is not the courier) will publish findings bounded and credential-redacted. Until that is
    built this pins that nothing unbounded or unredacted reaches the published status; building
    IDEA-066 replaces this test."""
    from tests.test_engineering_dispatcher import OBJ, World

    w = World(tmp_path)
    # Every builder run writes something new, so the repair always changes the rejected candidate, even if a
    # loaded host makes the harness retry an attempt.
    w.scenarios(*({"edits": [["pkg/hello.txt", f"hello {n}\n"]]} for n in range(8)))
    w.objective()
    w.reviewer.answers.append(lambda ctx: _review_with_text(ctx, "CHANGES_REQUIRED" if ctx.task_revision == 1
                                                             else "READY"))
    w.run_until(lambda: w.stage() == "COMPLETE", timeout=60)   # two revisions: generous on a loaded host
    receipts = ReceiptLog(w.store.root / "remote_engineering")
    receipts.put(Receipt(request_id="r-findings", request_sha256="0" * 64, outcome="accepted", objective_id=OBJ,
                         task_id=OBJ, source="requests/r-findings.json", recorded_at=NOW))

    class Quiet:
        def poll_once(self):
            return []

    published: list[dict] = []
    loop = RemoteEngineeringLoop(controller=Quiet(), dispatcher=w.dispatcher(), store=w.store, receipts=receipts,
                                 publish=lambda status: published.append(status) or "d" * 40, clock=w.clock)
    result = loop.cycle()
    text = json.dumps(published, default=str) + json.dumps(result["status"], default=str)
    # the texts are really in the store, so their absence from the projection is a property, not luck
    stored = "".join(p.read_text() for p in (w.store.root / "reviews").rglob("verdict.*"))
    assert all(marker in stored for marker in FINDING_MARKERS.values())
    for marker in FINDING_MARKERS.values():
        assert marker not in text
    assert "MARKER" not in text
    [item] = published[0]["requests"]
    assert item["stage"] == "COMPLETE" and item["revision"] == 2
    assert [(v["outcome"], v["verdict"]) for v in item["review"]["verdicts"]] == [("accepted", "ready")]
    assert item["github_acceptance"]["sha"] == item["candidate_sha"] and item["github_acceptance"]["green"] is True


def test_the_projection_carries_the_gate_answer_and_the_sha_it_checked(tmp_path, capsys):
    from app.orchestrator.github_acceptance import GateState
    from tests.test_engineering_dispatcher import OBJ, World

    w = World(tmp_path)
    w.scenarios({"edits": [["pkg/hello.txt", "hello\n"]]})
    w.objective()
    w.acceptance.state = GateState.PENDING
    w.run_until(lambda: w.state_of().status is TaskStatus.EVIDENCE_READY)
    receipts = ReceiptLog(w.store.root / "remote_engineering")
    receipts.put(Receipt(request_id="r-gate", request_sha256="0" * 64, outcome="accepted", objective_id=OBJ,
                         task_id=OBJ, source="requests/r-gate.json", recorded_at=NOW))

    status = build_status(store=w.store, receipts=receipts, now=w.clock(), gates=w.dispatcher().acceptance_gates())
    [item] = status["requests"]
    gate = item["github_acceptance"]
    assert item["stage"] == "EVIDENCE_READY" and gate["sha"] == item["candidate_sha"]
    assert gate["state"] == "pending" and gate["green"] is False and gate["check"] == "acceptance"
    assert [run["id"] for run in gate["runs"]] == [4242] and gate["checked_at"]
    assert set(gate) == {"schema", "check", "sha", "state", "green", "detail", "runs", "checked_at"}

    # the read-only CLI shows the same answer, read from the dispatcher's runtime root
    rc = cli.run(["--store", str(w.store.root), "--repo", str(w.repo), "--adapter-root",
                  str(w.store.root / "remote_engineering"), "--runtime-root", str(tmp_path / "runtime"),
                  "--no-journal", "status", "--json"])
    assert rc == 0
    [shown] = json.loads(capsys.readouterr().out)["requests"]
    assert shown["github_acceptance"] == gate
    cli.run(["--store", str(w.store.root), "--repo", str(w.repo), "--adapter-root",
             str(w.store.root / "remote_engineering"), "--runtime-root", str(tmp_path / "runtime"), "--no-journal",
             "status"])
    assert f"GitHub acceptance on {gate['sha']}: pending" in capsys.readouterr().out


def test_a_projection_without_recorded_gate_answers_still_publishes(tmp_path):
    store = LifecycleStore(tmp_path / "engineering")

    class Quiet:
        def poll_once(self):
            return []

    class NotesUnreadable:
        def tick(self):
            return []

        def acceptance_gates(self):
            raise ValueError("a runtime note is not JSON")

    published: list[dict] = []
    result = _loop(Quiet(), NotesUnreadable(), store, lambda status: published.append(status) or "e" * 40).cycle()
    assert result["projection_commit"] == "e" * 40 and published[0]["requests"] == []


def test_both_doors_build_the_github_gate_and_read_product_memory_from_the_trunk(tmp_path):
    from app.orchestrator.github_acceptance import GitHubAcceptance
    from scripts import engineering_dispatcher as dispatcher_cli

    common = ["--store", str(tmp_path / "engineering"), "--repo", str(tmp_path),
              "--runtime-root", str(tmp_path / "runtime"), "--workspace-root", str(tmp_path / "workers")]
    args = cli.build_parser().parse_args([*common, "--publish-remote", "origin",
                                          "run", "--repository", "crooksldn-pixel/clive"])
    assert args.product_memory_ref == "origin/clive/trunk"
    _store, kernel, objectives, _receipts = cli._kernel_parts(args)
    assert isinstance(cli._dispatcher(args, kernel, objectives).acceptance, GitHubAcceptance)

    parser = dispatcher_cli.build_parser()
    objective = parser.parse_args([*common, "objective", "--title", "t", "--objective", "o", "--base-ref", "main",
                                   "--allowed-path", "pkg"])
    integrate = parser.parse_args([*common, "integrate", "--title", "t", "--from", "a-b", "--base-ref", "main"])
    assert objective.product_memory_ref == integrate.product_memory_ref == "origin/clive/trunk"
    _kernel, _objectives, dispatcher = dispatcher_cli._parts(objective)
    assert isinstance(dispatcher.acceptance, GitHubAcceptance)



# ------------------------------------------------ the 2026-09-26 re-pin review: F-02

def test_a_github_gated_loop_does_not_start_without_a_publication_remote(tmp_path, capsys):
    """F-02: without --publish-remote a candidate only moves a local branch, GitHub never runs acceptance on
    it, and every one would wait and then block. The loop refuses to start instead; with it, it starts."""
    from scripts import engineering_dispatcher as dispatcher_cli

    common = ["--store", str(tmp_path / "engineering"), "--repo", str(tmp_path),
              "--runtime-root", str(tmp_path / "runtime"), "--workspace-root", str(tmp_path / "workers")]
    tail = ["run", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main"]
    args = cli.build_parser().parse_args([*common, *tail])
    assert args.publish_remote is None
    _store, kernel, objectives, _receipts = cli._kernel_parts(args)
    with pytest.raises(InboxError, match="--publish-remote"):
        cli._dispatcher(args, kernel, objectives)
    assert cli.run([*common, *tail, "--max-cycles", "1"]) == 2
    assert cli.NO_PUBLISH_REMOTE in capsys.readouterr().err
    with_remote = cli.build_parser().parse_args([*common, "--publish-remote", "origin", *tail])
    assert cli._dispatcher(with_remote, kernel, objectives).config.publish_remote == "origin"

    for verb in ("tick", "run"):
        assert dispatcher_cli.run([*common, verb]) == 2
        assert dispatcher_cli.NO_PUBLISH_REMOTE in capsys.readouterr().err


# ------------------------------- the 2026-09-30 re-pin review of 40e6a73f, F-02 (waived, done by hand): `run` restarted

def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _kill_builders(store: LifecycleStore) -> None:
    """SIGKILL every builder this store launched that is still alive, found on the host by its attempt marker."""
    from app.orchestrator.workers.base import processes_with_marker, worker_marker
    from app.orchestrator.workers.claude import MARKER

    for task in store.read_tasks():
        for attempt in store.read_attempts(task.task_id):
            for pid in processes_with_marker(MARKER, worker_marker(attempt.attempt_id, attempt.worker.session.session_id)):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_run_restarted_on_an_existing_store_replays_it_admits_nothing_twice_and_blocks_a_newly_protected_objective(
        env, tmp_path, capsys, monkeypatch, no_host_git_config):
    """The re-pin review of 40e6a73f, F-02: the long-running mode, restarted against what a host's store holds.

    The flags are clive-worker-01's (OWNER_DECISIONS_2026-09-30): ``run`` with ``--publish-remote origin`` and
    ``--product-memory-ref origin/clive/trunk``, a journalled store and no ``--adapter-root``, so claims and receipts
    live at the default <store>/remote_engineering under the host's own exclude rule; only the paths (store, repo,
    runtime, workspaces) and the builder CLI (the dispatcher tests' fake claude) are the test's. Its first life
    leaves what a restart finds: v1 claims and receipts (one of them a refusal), objectives, tasks, an attempt
    whose builder is alive, the dispatcher's runtime notes, and one objective waiting for the worker slot. Then a
    path is newly protected, a new request arrives, and ``run`` starts again with the same flags. Replay keeps
    every record, admits and launches nothing twice, stops the builder of the objective whose scope is now
    protected and blocks it with its reason, launches the waiting one once, and admits the new request once."""
    from app.orchestrator import objectives as objectives_module
    from app.orchestrator.workers import ClaudeCodeWorker
    from app.orchestrator.workers.base import worker_marker
    from app.remote_engineering import DEFAULT_STATUS_PATH
    from tests.test_engineering_dispatcher import FAKE_CLAUDE

    state = _journalled_state(tmp_path)
    store_dir = state / "engineering"
    exclude = state / ".git" / "info" / "exclude"
    exclude.write_text((exclude.read_text() if exclude.exists() else "") + "/engineering/remote_engineering/\n")
    _git(env.origin, "branch", "clive/trunk", "main")            # product memory lives on the trunk
    _git(env.checkout, "fetch", "-q", "origin")
    fake_state = tmp_path / "fake-state"
    fake_state.mkdir()
    (fake_state / "scenarios.json").write_text(json.dumps([{"hang": True}]))   # every builder starts and works on
    fake = tmp_path / "claude"
    fake.write_text(FAKE_CLAUDE.format(python=sys.executable, state=str(fake_state)))
    fake.chmod(0o755)
    runtime, workers = tmp_path / "runtime", tmp_path / "workers"
    host = ["--store", str(store_dir), "--repo", str(env.checkout), "--runtime-root", str(runtime),
            "--workspace-root", str(workers), "--worker-cli", str(fake), "--publish-remote", "origin",
            "run", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "origin/clive/trunk",
            "--max-cycles", "1"]
    commit_request(env.origin, "r-guarded", valid_request(env, request_id="r-guarded",
                                                         allowed_paths=["crooks-assistant/app/guarded"]))
    commit_request(env.origin, "r-kept", valid_request(env, request_id="r-kept"))
    commit_request(env.origin, "r-refused", valid_request(env, request_id="r-refused",
                                                         allowed_paths=["crooks-assistant/app/remote_engineering"]))
    store = LifecycleStore(store_dir)
    worker = ClaudeCodeWorker(cli=str(fake))
    try:
        # ---- the loop's first life
        assert cli.run(host) == 0
        first = capsys.readouterr()
        assert first.err == ""
        before = json.loads(first.out)
        assert before["intake_error"] is None and before["publish_error"] is None
        assert {o["request_id"]: o["outcome"] for o in before["outcomes"]} == \
            {"r-guarded": "accepted", "r-kept": "accepted", "r-refused": "refused"}
        [guarded] = store.read_attempts("r-guarded")
        marker = worker_marker(guarded.attempt_id, guarded.worker.session.session_id)
        deadline = time.monotonic() + 10
        while not worker.live_pids(marker) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert worker.live_pids(marker)                           # its builder is alive when the loop restarts
        assert store.read_task_state("r-guarded", 1).status in (TaskStatus.ASSIGNED, TaskStatus.RUNNING)
        assert store.read_task_state("r-kept", 1).status is TaskStatus.READY and not store.read_attempts("r-kept")
        assert any("r-kept: waiting: the concurrent-worker limit" in line for line in before["dispatcher_events"])

        adapter = store_dir / "remote_engineering"
        records = _files(adapter)
        assert sorted(records) == [f"{kind}/{rid}.json" for kind in ("claims", "receipts")
                                   for rid in ("r-guarded", "r-kept", "r-refused")]
        assert {json.loads(data)["schema_version"] for name, data in records.items() if name.startswith("claims/")} \
            == {"clive.remote_engineering_claim.v1"}
        assert {json.loads(data)["schema_version"] for name, data in records.items() if name.startswith("receipts/")} \
            == {"clive.remote_engineering_receipt.v1"}
        lifecycle = {name: data for name, data in _files(store_dir).items() if not name.startswith("remote_engineering/")}
        assert any(name.startswith("objectives/") for name in lifecycle) and any(name.startswith("attempts/")
                                                                                 for name in lifecycle)
        notes = _files(runtime / "attempts")
        assert list(notes) == [f"{guarded.attempt_id}.json"]
        assert json.loads(notes[f"{guarded.attempt_id}.json"])["phase"] == "launched"
        assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""

        # ---- a path is newly protected, a new request arrives, and the loop restarts with the same flags
        monkeypatch.setattr(objectives_module, "PROTECTED_PATHS",
                            objectives_module.PROTECTED_PATHS + ("crooks-assistant/app/guarded",))
        commit_request(env.origin, "r-new", valid_request(env, request_id="r-new"))
        assert cli.run(host) == 0
        second = capsys.readouterr()
        assert second.err == ""
        after = json.loads(second.out)
        assert after["intake_error"] is None and after["publish_error"] is None

        # replay: every earlier decision is repeated from its record, byte for byte; only r-new is new
        old = {o["request_id"]: o for o in before["outcomes"]}
        new = {o["request_id"]: o for o in after["outcomes"]}
        assert {rid: new[rid] for rid in old} == old
        assert new["r-new"]["outcome"] == "accepted"
        assert _files(adapter) == {**records, **{f"{kind}/r-new.json": _files(adapter)[f"{kind}/r-new.json"]
                                                 for kind in ("claims", "receipts")}}
        # nothing admitted twice: one objective entry and one task per admitted id, none for the refusal
        subjects = _git(state, "log", "--format=%s").splitlines()
        for rid in ("r-guarded", "r-kept", "r-new"):
            assert sum(s.startswith(f"objective {rid} entered") for s in subjects) == 1, rid
            assert sum(s.startswith(f"kernel: task {rid} r1 created") for s in subjects) == 1, rid
        assert not any("r-refused" in s for s in subjects)
        # the lifecycle records are kept: write-once records unchanged, event logs only appended to
        now = {name: data for name, data in _files(store_dir).items() if not name.startswith("remote_engineering/")}
        states = store.task_states_dir.relative_to(store_dir).as_posix() + "/"
        for name, data in lifecycle.items():
            if name.startswith(states) or name.endswith(".lock"):
                continue                                          # the kernel's current-state projection moves on
            if name.endswith(".jsonl"):
                assert now[name].startswith(data), name
            else:
                assert now[name] == data, name
        # the runtime notes of the attempt the loop found are kept as they were
        assert _files(runtime / "attempts")[f"{guarded.attempt_id}.json"] == notes[f"{guarded.attempt_id}.json"]

        # the newly protected objective: its builder stopped and confirmed gone, its task blocked with the reason
        blocked = store.read_task_state("r-guarded", 1)
        assert blocked.status is TaskStatus.BLOCKED and blocked.blocker_class is BlockerClass.DETERMINISTIC
        assert "covers protected path(s) crooks-assistant/app/guarded" in blocked.blocker_reason
        assert "could not be stopped" not in blocked.blocker_reason
        assert not worker.live_pids(marker)
        assert [a.attempt_id for a in store.read_attempts("r-guarded")] == [guarded.attempt_id]
        # the one waiting for the slot is launched once; the new one waits for it; one builder per launch
        [kept] = store.read_attempts("r-kept")
        assert store.read_task_state("r-kept", 1).status in (TaskStatus.ASSIGNED, TaskStatus.RUNNING)
        assert store.read_task_state("r-new", 1).status is TaskStatus.READY and not store.read_attempts("r-new")
        assert int((fake_state / "invocations").read_text()) == 2
        events = after["dispatcher_events"]
        assert any(line.startswith("r-guarded: BLOCKED: the task's scope covers protected path(s) "
                                   "crooks-assistant/app/guarded") for line in events), events
        assert any(line.startswith(f"r-kept: assigned {kept.attempt_id}") for line in events), events
        assert any(line.startswith("r-new: waiting: the concurrent-worker limit") for line in events), events
        # and the published projection says so
        published = json.loads(_git(env.origin, "show", f"{after['projection_commit']}:{DEFAULT_STATUS_PATH}"))
        item = next(i for i in published["requests"] if i["request_id"] == "r-guarded")
        assert item["stage"] == "BLOCKED" and "covers protected path(s) crooks-assistant/app/guarded" in item["blocker"]
        assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""
    finally:
        _kill_builders(store)


# ------------------------ the 2026-09-30 base wait: a base the engineering repo has not fetched yet waits, not refuses
#
# On 30 Sep a request named a trunk commit merged minutes earlier; the engineering repo had not fetched
# it, and the request was refused with its id burned. The filing tool names the trunk head it reads at
# filing time, so any filing right after a merge is at risk. The loop now fetches the trunk once, and
# while the commit is still absent defers the request -- no claim, no receipt -- for a bound recorded
# at first sight under the adapter root. A ref that names a different commit is refused as before.
# The new names are imported inside the tests, after each one's first behavioural assertion, so on
# code without the wait every test here fails on what the loop did, not on an import.

class _Clock:
    """A host clock the test moves by hand."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _origin_commit(env: SimpleNamespace, branch: str, text: str) -> str:
    """A commit on origin's ``branch`` (made from main when new), made after the engineering repo was
    cloned: that repo does not have it until it fetches something that contains it."""
    exists = subprocess.run(["git", "rev-parse", "--verify", "--quiet", branch], cwd=env.origin,
                            capture_output=True).returncode == 0
    _git(env.origin, "checkout", "-q", branch) if exists else _git(env.origin, "checkout", "-q", "-b", branch, "main")
    (env.origin / "b.txt").write_text(text)
    _git(env.origin, "add", "-A")
    _git(env.origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", text)
    sha = _git(env.origin, "rev-parse", "HEAD")
    _git(env.origin, "checkout", "-q", "main")
    return sha


def _has(env: SimpleNamespace, sha: str) -> bool:
    return GitFacts(env.checkout).commit_exists(sha)


def _waiting_controller(env: SimpleNamespace, tmp_path: Path, clock: _Clock):
    """make_controller's controller over the same store, with a clock the test moves (a fresh one is a restart)."""
    store = LifecycleStore(tmp_path / "engineering")
    kernel = Kernel(store=store, registry=PrincipalRegistry.load(REGISTRY), git=GitFacts(env.checkout),
                    operator="remote-test", journal=False, clock=lambda: NOW)
    objectives = ObjectiveStore(store, journal=False)
    receipts = ReceiptLog(store.root / "remote_engineering")
    config = RemoteControllerConfig(repo=env.checkout, repository="crooksldn-pixel/clive", product_memory_ref="main")
    return kernel, objectives, receipts, RemoteController(kernel=kernel, objectives=objectives, config=config,
                                                          receipts=receipts, clock=clock)


def _as_filed(env: SimpleNamespace, request_id: str, base: str) -> dict:
    """A request as CLIVE's filing tool writes it: the base named by its SHA, as the ref and the sha."""
    return valid_request(env, request_id=request_id, base_ref=base, base_sha=base)


def test_an_unfetched_trunk_base_is_fetched_once_and_admitted(env, tmp_path):
    """The 30 Sep case: the base is the trunk head, merged after the engineering repo last fetched."""
    _git(env.origin, "branch", "clive/trunk", "main")
    merged = _origin_commit(env, "clive/trunk", "merged minutes ago")
    assert not _has(env, merged)
    commit_request(env.origin, "r-fresh-base", _as_filed(env, "r-fresh-base", merged))
    kernel, objectives, receipts, controller = _waiting_controller(env, tmp_path, _Clock())

    outcomes = controller.poll_once()

    assert [o["outcome"] for o in outcomes] == ["accepted"]
    assert objectives.read("r-fresh-base").base_sha == merged
    assert kernel.store.read_task_state("r-fresh-base", 1).status is TaskStatus.READY
    assert _git(env.checkout, "rev-parse", "refs/remotes/origin/clive/trunk") == merged   # the trunk, fetched
    assert receipts.get("r-fresh-base").outcome == "accepted"
    assert not (receipts.dir.parent / "waits").exists() or not any((receipts.dir.parent / "waits").iterdir())


def test_a_base_still_missing_defers_with_nothing_burned_and_is_admitted_once_it_arrives(env, tmp_path):
    _git(env.origin, "branch", "clive/trunk", "main")
    pending = _origin_commit(env, "feature/elsewhere", "not on the trunk yet")
    commit_request(env.origin, "r-wait-base", _as_filed(env, "r-wait-base", pending))
    clock = _Clock()
    kernel, objectives, receipts, controller = _waiting_controller(env, tmp_path, clock)

    [first] = controller.poll_once()

    assert first["outcome"] == "waiting"
    from app.remote_engineering import BASE_WAIT_REASON, WaitLog

    assert first["reason"] == BASE_WAIT_REASON and first["durable"] is False
    assert first["waiting_since"] == NOW.isoformat()
    assert first["refuse_after"] == (NOW + timedelta(hours=1)).isoformat()
    assert pending not in json.dumps(first)                     # the declared sha is never echoed
    # nothing burned: no claim, no receipt, no objective, no task; only the wait
    assert controller.claims.get("r-wait-base") is None and receipts.get("r-wait-base") is None
    assert objectives.read("r-wait-base") is None and kernel.store.read_tasks() == ()
    assert [w.request_id for w in WaitLog(receipts.dir.parent).read_all()] == ["r-wait-base"]
    status = build_status(store=kernel.store, receipts=receipts, now=NOW)
    assert status["requests"] == []
    [shown] = status["waiting_requests"]
    assert shown["request_id"] == "r-wait-base" and shown["outcome"] == "waiting"
    assert shown["reason"] == BASE_WAIT_REASON and pending not in json.dumps(status)

    clock.now = NOW + timedelta(minutes=10)
    [again] = controller.poll_once()
    assert again["outcome"] == "waiting" and again["waiting_since"] == NOW.isoformat()   # still counted from first sight

    _git(env.origin, "branch", "-f", "clive/trunk", pending)    # it is merged
    clock.now = NOW + timedelta(minutes=20)
    [admitted] = controller.poll_once()

    assert admitted["outcome"] == "accepted"
    assert objectives.read("r-wait-base").base_sha == pending
    assert controller.claims.get("r-wait-base").claimed_at == NOW + timedelta(minutes=20)
    assert WaitLog(receipts.dir.parent).read_all() == ()
    status = build_status(store=kernel.store, receipts=receipts, now=clock.now)
    assert status["waiting_requests"] == [] and [r["request_id"] for r in status["requests"]] == ["r-wait-base"]
    assert controller.poll_once() == [admitted]                 # and a replay repeats the receipt


def test_a_ref_naming_another_commit_is_refused_at_once_while_a_missing_base_waits(env, tmp_path):
    """Only a missing base waits. A ref that resolves to a different commit is refused in the same poll,
    exactly as before: same wording, its id decided, and it never waits."""
    _git(env.origin, "branch", "clive/trunk", "main")
    pending = _origin_commit(env, "feature/elsewhere", "not on the trunk yet")
    commit_request(env.origin, "r-missing", _as_filed(env, "r-missing", pending))
    commit_request(env.origin, "r-other", valid_request(env, request_id="r-other", base_ref="main",
                                                        base_sha=_other_commit(env)))
    _kernel, objectives, receipts, controller = _waiting_controller(env, tmp_path, _Clock())

    outcomes = {o["request_id"]: o for o in controller.poll_once()}

    assert outcomes["r-missing"]["outcome"] == "waiting"
    refused = outcomes["r-other"]
    assert refused["outcome"] == "refused"
    assert refused["reason"] == "request r-other: base ref does not resolve to the declared base sha <redacted>"
    assert "'main'" not in refused["reason"]
    assert receipts.get("r-other").outcome == "refused" and controller.claims.get("r-other") is not None
    assert objectives.read("r-other") is None
    from app.remote_engineering import WaitLog

    assert [w.request_id for w in WaitLog(receipts.dir.parent).read_all()] == ["r-missing"]


def test_a_base_still_missing_past_its_bound_is_refused_and_the_id_is_decided(env, tmp_path):
    _git(env.origin, "branch", "clive/trunk", "main")
    never = _origin_commit(env, "feature/abandoned", "never merged")
    commit_request(env.origin, "r-too-late", _as_filed(env, "r-too-late", never))
    clock = _Clock()
    _kernel, objectives, receipts, controller = _waiting_controller(env, tmp_path, clock)

    assert [o["outcome"] for o in controller.poll_once()] == ["waiting"]
    clock.now = NOW + timedelta(minutes=59, seconds=59)
    assert [o["outcome"] for o in controller.poll_once()] == ["waiting"]
    clock.now = NOW + timedelta(hours=1)
    [refused] = controller.poll_once()

    assert refused["outcome"] == "refused"
    assert refused["reason"] == (
        "request r-too-late: base ref does not resolve to the declared base sha <redacted>; the engineering "
        "repo still did not have that commit 1 hour after the loop first saw the request"
    )
    assert never not in json.dumps(refused)
    assert receipts.get("r-too-late").outcome == "refused"
    assert controller.claims.get("r-too-late") is not None and objectives.read("r-too-late") is None
    from app.remote_engineering import WaitLog

    assert WaitLog(receipts.dir.parent).read_all() == ()
    # decided means decided: the base arriving afterwards changes nothing
    _git(env.origin, "branch", "-f", "clive/trunk", never)
    clock.now = NOW + timedelta(hours=2)
    assert controller.poll_once() == [refused]
    assert objectives.read("r-too-late") is None


def test_a_restart_mid_wait_keeps_counting_from_first_sight(env, tmp_path):
    _git(env.origin, "branch", "clive/trunk", "main")
    pending = _origin_commit(env, "feature/slow", "merged later")
    commit_request(env.origin, "r-restart-wait", _as_filed(env, "r-restart-wait", pending))

    _k1, _o1, _r1, first = _waiting_controller(env, tmp_path, _Clock(NOW))
    assert [o["outcome"] for o in first.poll_once()] == ["waiting"]

    # a new process, the same adapter root, half an hour on: still waiting, still counted from NOW
    _k2, _o2, receipts, second = _waiting_controller(env, tmp_path, _Clock(NOW + timedelta(minutes=30)))
    [waiting] = second.poll_once()
    assert waiting["outcome"] == "waiting"
    assert waiting["waiting_since"] == NOW.isoformat()
    assert waiting["refuse_after"] == (NOW + timedelta(hours=1)).isoformat()
    assert second.claims.get("r-restart-wait") is None and receipts.get("r-restart-wait") is None

    # restarted again once the bound from first sight has passed: refused, not given a fresh hour
    _k3, objectives, receipts, third = _waiting_controller(env, tmp_path, _Clock(NOW + timedelta(hours=1)))
    [refused] = third.poll_once()
    assert refused["outcome"] == "refused" and "1 hour after the loop first saw the request" in refused["reason"]
    assert objectives.read("r-restart-wait") is None


def test_a_restart_mid_wait_admits_the_request_once_its_base_arrives(env, tmp_path):
    _git(env.origin, "branch", "clive/trunk", "main")
    pending = _origin_commit(env, "feature/slow", "merged later")
    commit_request(env.origin, "r-restart-admit", _as_filed(env, "r-restart-admit", pending))
    _k1, _o1, _r1, first = _waiting_controller(env, tmp_path, _Clock(NOW))
    assert [o["outcome"] for o in first.poll_once()] == ["waiting"]

    _git(env.origin, "branch", "-f", "clive/trunk", pending)
    kernel, objectives, receipts, second = _waiting_controller(env, tmp_path, _Clock(NOW + timedelta(minutes=45)))
    [admitted] = second.poll_once()

    assert admitted["outcome"] == "accepted"
    assert objectives.read("r-restart-admit").base_sha == pending
    assert len(kernel.store.read_tasks()) == 1
    from app.remote_engineering import WaitLog

    assert WaitLog(receipts.dir.parent).read_all() == ()


def test_the_trunk_is_fetched_once_per_poll_however_many_requests_wait(env, tmp_path, monkeypatch):
    from app.remote_engineering import controller as controller_module

    _git(env.origin, "branch", "clive/trunk", "main")
    one = _origin_commit(env, "feature/one", "one")
    two = _origin_commit(env, "feature/two", "two")
    commit_request(env.origin, "r-wait-one", _as_filed(env, "r-wait-one", one))
    commit_request(env.origin, "r-wait-two", _as_filed(env, "r-wait-two", two))
    fetched: list[str] = []
    real = controller_module.fetch_trunk
    monkeypatch.setattr(controller_module, "fetch_trunk",
                        lambda repo, **kw: fetched.append(kw["branch"]) or real(repo, **kw))
    _kernel, _objectives, _receipts, controller = _waiting_controller(env, tmp_path, _Clock())

    assert [o["outcome"] for o in controller.poll_once()] == ["waiting", "waiting"]
    assert fetched == ["clive/trunk"]                            # once, for both
    controller.poll_once()
    assert fetched == ["clive/trunk", "clive/trunk"]             # and again next poll


def test_a_base_present_needs_no_fetch_and_a_trunk_that_cannot_be_fetched_only_keeps_it_waiting(env, tmp_path,
                                                                                                  monkeypatch):
    from app.remote_engineering import TRUNK_UNAVAILABLE
    from app.remote_engineering import controller as controller_module

    fetched: list[str] = []
    real = controller_module.fetch_trunk
    monkeypatch.setattr(controller_module, "fetch_trunk",
                        lambda repo, **kw: fetched.append(kw["branch"]) or real(repo, **kw))
    commit_request(env.origin, "r-present", valid_request(env, request_id="r-present"))
    _kernel, _objectives, _receipts, controller = _waiting_controller(env, tmp_path, _Clock())
    assert [o["outcome"] for o in controller.poll_once()] == ["accepted"]
    assert fetched == [] and controller.trunk_fetch_error is None

    # origin has no clive/trunk at all: the fetch fails, and the request waits rather than being refused
    pending = _origin_commit(env, "feature/elsewhere", "somewhere")
    commit_request(env.origin, "r-no-trunk", _as_filed(env, "r-no-trunk", pending))
    outcomes = {o["request_id"]: o for o in controller.poll_once()}
    assert outcomes["r-no-trunk"]["outcome"] == "waiting"
    assert controller.trunk_fetch_error == TRUNK_UNAVAILABLE
    assert str(env.origin) not in json.dumps(outcomes)


def test_the_published_status_shows_a_waiting_request_and_why_the_trunk_could_not_be_fetched(env, tmp_path):
    pending = _origin_commit(env, "feature/elsewhere", "somewhere")
    commit_request(env.origin, "r-shown-waiting", _as_filed(env, "r-shown-waiting", pending))
    kernel, _objectives, _receipts, controller = _waiting_controller(env, tmp_path, _Clock())
    published: list[dict] = []

    result = _loop(controller, _Ticker(), kernel.store, lambda status: published.append(status) or "a" * 40).cycle()

    assert [o["outcome"] for o in result["outcomes"]] == ["waiting"]
    from app.remote_engineering import BASE_WAIT_REASON, TRUNK_UNAVAILABLE

    [status] = published
    assert status["requests"] == [] and status["refused_records"] == []
    [waiting] = status["waiting_requests"]
    assert waiting == {
        "request_id": "r-shown-waiting", "source": "requests/r-shown-waiting.json",
        "request_sha256": result["outcomes"][0]["request_sha256"], "outcome": "waiting",
        "reason": BASE_WAIT_REASON, "waiting_since": NOW.isoformat(),
        "refuse_after": (NOW + timedelta(hours=1)).isoformat(),
    }
    assert status["adapter"] == {"intake_error": None, "trunk_fetch_error": TRUNK_UNAVAILABLE}
    for text in (json.dumps(published), json.dumps(result, default=str)):
        assert pending not in text and str(env.origin) not in text


def test_a_request_that_leaves_the_inbox_while_waiting_stops_being_shown(env, tmp_path):
    _git(env.origin, "branch", "clive/trunk", "main")
    pending = _origin_commit(env, "feature/elsewhere", "somewhere")
    commit_request(env.origin, "r-withdrawn", _as_filed(env, "r-withdrawn", pending))
    kernel, _objectives, receipts, controller = _waiting_controller(env, tmp_path, _Clock())
    assert [o["outcome"] for o in controller.poll_once()] == ["waiting"]

    _git(env.origin, "checkout", "-q", DEFAULT_INBOX_BRANCH)
    _git(env.origin, "rm", "-q", f"{DEFAULT_INBOX_DIRECTORY}/r-withdrawn.json")
    _git(env.origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "withdrawn")
    _git(env.origin, "checkout", "-q", "main")

    assert controller.poll_once() == []
    assert build_status(store=kernel.store, receipts=receipts, now=NOW)["waiting_requests"] == []


def test_the_base_wait_is_host_configuration_bounded_and_never_a_request_field(env):
    from app.remote_engineering import DEFAULT_BASE_WAIT_S, DEFAULT_TRUNK_BRANCH

    config = RemoteControllerConfig(repo=env.checkout, repository="crooksldn-pixel/clive", product_memory_ref="main")
    assert config.base_wait_s == DEFAULT_BASE_WAIT_S == 3600.0 and config.trunk_branch == DEFAULT_TRUNK_BRANCH
    for bad in (float("nan"), float("inf"), 0, -1, 59, 86_401):
        with pytest.raises(InboxError):
            RemoteControllerConfig(repo=env.checkout, repository="o/r", product_memory_ref="main", base_wait_s=bad)
    for bad in ("../trunk", "-x", "a..b", "https://evil.example/x"):
        with pytest.raises(InboxError):
            RemoteControllerConfig(repo=env.checkout, repository="o/r", product_memory_ref="main", trunk_branch=bad)
    with pytest.raises(RequestSchemaError):
        parse_request(json.dumps(valid_request(env, request_id="r-wait-own", base_wait_s=1)).encode())


def test_poll_refuses_to_start_while_the_waits_directory_would_be_unignored_store_state(
        env, tmp_path, capsys, no_host_git_config):
    """A deferred request writes its wait beside the claims and receipts; the journal must not see it either.
    These rules do ignore the claims and receipts directories (without a trailing slash, so git matches them
    before they exist), which alone used to be enough to start."""
    state = _journalled_state(tmp_path)
    store_dir = state / "engineering"
    (state / ".gitignore").write_text("/engineering/remote_engineering/claims\n/engineering/remote_engineering/receipts\n")
    _git(state, "add", ".gitignore")
    _git(state, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ignore two record dirs")
    for directory in ("claims", "receipts"):
        assert subprocess.run(["git", "check-ignore", "-q", "--", f"engineering/remote_engineering/{directory}"],
                              cwd=state).returncode == 0, directory

    with pytest.raises(InboxError) as refusal:
        adapter_root_preconditions(store_dir, store_dir / "remote_engineering")
    assert str(refusal.value) == ADAPTER_ROOT_NOT_IGNORED
    rc = cli.run(["--store", str(store_dir), "--repo", str(env.checkout),
                  "poll", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main"])
    assert rc == 2 and ADAPTER_ROOT_NOT_IGNORED in capsys.readouterr().err
    assert not (store_dir / "remote_engineering").exists()


def test_under_the_hosts_exclude_rule_a_wait_leaves_the_journalled_store_clean(env, tmp_path, capsys,
                                                                              no_host_git_config):
    """clive-worker-01's layout: the default adapter root, ignored whole by the store's own exclude rule."""
    state = _journalled_state(tmp_path)
    store_dir = state / "engineering"
    exclude = state / ".git" / "info" / "exclude"
    exclude.write_text((exclude.read_text() if exclude.exists() else "") + "/engineering/remote_engineering/\n")
    _git(env.origin, "branch", "clive/trunk", "main")
    pending = _origin_commit(env, "feature/elsewhere", "somewhere")
    commit_request(env.origin, "r-host-wait", _as_filed(env, "r-host-wait", pending))
    flags = ["--store", str(store_dir), "--repo", str(env.checkout),
             "poll", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main"]

    assert cli.run(flags) == 0
    first = capsys.readouterr()
    assert first.err == "" and [o["outcome"] for o in json.loads(first.out)] == ["waiting"]
    adapter = store_dir / "remote_engineering"
    assert sorted(p.relative_to(adapter).as_posix() for p in adapter.rglob("*.json")) == ["waits/r-host-wait.json"]
    assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""

    _git(env.origin, "branch", "-f", "clive/trunk", pending)
    assert cli.run(flags) == 0
    second = capsys.readouterr()
    assert [o["outcome"] for o in json.loads(second.out)] == ["accepted"]
    assert sorted(p.relative_to(adapter).as_posix() for p in adapter.rglob("*.json")) == \
        ["claims/r-host-wait.json", "receipts/r-host-wait.json"]
    assert _git(state, "status", "--porcelain", "--untracked-files=all") == ""


# ------------------------ the 2026-09-30 build truth: what each build went through, published per request
#
# The owner asked CLIVE whether the loop retries a failed build, and CLIVE could not see that it does:
# the status carried a stage and a reason only. The projection now carries, per request, what the
# kernel's own records say (``build_history``: attempts per revision, the retries among them and why,
# the review's requests for changes, the repair limit), and the Dispatcher's per-build keys when it
# reports them (``attempts``, ``repairs``, ``generated``, ``landing``), rebuilt bounded and redacted.
# As above, new names are imported after each test's first behavioural assertion.

CUSTOMER_EMAIL = "mia.kowalski@example.com"
CUSTOMER_PHONE = "07700 900123"
PROJECTION_TOKEN = github_token("remote-engineering-projection", kind="p")
PROJECTION_KEY = openai_key("remote-engineering-projection", kind="")
PROJECTION_URL = credential_url(github_token("remote-engineering-projection-url", kind="s"))
LANDED = "abc1234" + "0" * 33
DISPATCHER_KEYS = {
    "attempts": [
        {"attempt_id": "r-built-a1", "revision": 1, "outcome": "cancelled", "reason": "transient: the provider timed out",
         "at": "2026-09-30T10:00:00+00:00"},
        {"attempt_id": "r-built-a2", "revision": 1, "outcome": "candidate", "reason": None,
         "at": "2026-09-30T10:20:00+00:00"},
        {"attempt_id": "r-built-a3", "revision": 2, "outcome": "blocked",
         "reason": "GitHub's tests failed — tests/test_x.py::test_y", "at": "2026-09-30T11:00:00+00:00"},
    ],
    "repairs": {"review": 1, "ci": 1, "max": 2},
    "generated": ["crooks-assistant/docs/phase4/TOOL_MATRIX.md"],
    "landing": {"state": "landed", "sha": LANDED, "at": "2026-09-30T11:30:00+00:00", "reason": None},
}
PROJECTED_BASE_KEYS = {"request_id", "source", "request_sha256", "outcome", "reason", "objective_id", "task_id",
                       "recorded_at"}


class _QuietIntake:
    def poll_once(self):
        return []


class _Reporting:
    """A Dispatcher whose ``status()`` says what it is given, as the one on the teammate's branch is to."""

    def __init__(self, entries=None, *, error: Exception | None = None):
        self.entries, self.error = entries, error

    def tick(self):
        return []

    def status(self):
        if self.error is not None:
            raise self.error
        return self.entries


def _decided(tmp_path: Path, *ids: str) -> tuple[LifecycleStore, ReceiptLog]:
    store = LifecycleStore(tmp_path / "engineering")
    receipts = ReceiptLog(store.root / "remote_engineering")
    for rid in ids:
        receipts.put(Receipt(request_id=rid, request_sha256="0" * 64, outcome="accepted", objective_id=rid,
                             task_id=rid, source=f"requests/{rid}.json", recorded_at=NOW))
    return store, receipts


def _published(tmp_path: Path, dispatcher, *ids: str) -> dict:
    store, receipts = _decided(tmp_path, *ids)
    published: list[dict] = []
    RemoteEngineeringLoop(controller=_QuietIntake(), dispatcher=dispatcher, store=store, receipts=receipts,
                          publish=lambda status: published.append(status) or "a" * 40, clock=lambda: NOW).cycle()
    [status] = published
    json.dumps(status)   # plain JSON, as it is pushed
    return status


def _built_world(tmp_path: Path):
    """A real Dispatcher's run to COMPLETE: revision 1's first builder dies (a transient failure, retried),
    its second is sent back by the review; the repair's first builder changes nothing (a result CLIVE
    refuses, retried) and its second passes review."""
    from tests.test_engineering_dispatcher import FINDING, OBJ, World, review

    w = World(tmp_path)
    w.scenarios({"die": True}, {"edits": [["pkg/hello.txt", "bye\n"]]}, {"edits": []},
                {"edits": [["pkg/hello.txt", "hello\n"]]})
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[FINDING])
                              if ctx.task_revision == 1 else review(ctx, "READY"))
    w.run_until(lambda: w.stage() == "COMPLETE")
    receipts = ReceiptLog(w.store.root / "remote_engineering")
    receipts.put(Receipt(request_id="r-built", request_sha256="0" * 64, outcome="accepted", objective_id=OBJ,
                         task_id=OBJ, source="requests/r-built.json", recorded_at=NOW))
    return w, receipts


def test_the_projection_counts_each_revisions_attempts_and_retries_from_the_kernels_records(tmp_path):
    """Before the Dispatcher reports anything new, the records alone show the owner that the loop retried
    and repaired by itself: four builds, two of them retries, one review asking for changes."""
    w, receipts = _built_world(tmp_path)
    notes = [e.note or "" for a in w.store.read_attempts("demo-objective")
             for e in w.store.read_events("demo-objective", a.attempt_id) if e.kind.value == "cancelled"]
    assert [n.split(":", 1)[0] for n in notes] == ["transient", "result_refused"]   # what the world did

    [item] = build_status(store=w.store, receipts=receipts, now=w.clock())["requests"]

    assert item["revision"] == 2 and item["stage"] == "COMPLETE"
    assert item["build_history"] == {
        "attempts": 4,
        "revisions": [
            {"revision": 1, "kind": "build", "attempts": 2, "transient": 1, "refused": 0},
            {"revision": 2, "kind": "repair", "attempts": 2, "transient": 0, "refused": 1},
        ],
        "review_changes_requested": 1,
        "max_repair_rounds": 2,
    }
    # counts and fixed words only: no note the Dispatcher wrote is copied
    assert all(note[:40] not in json.dumps(item["build_history"]) for note in notes)
    from app.remote_engineering import build_history

    assert build_history(w.store, "no-such-task") == {"attempts": 0, "revisions": [], "review_changes_requested": 0,
                                                      "max_repair_rounds": None}


def test_the_records_projection_says_plainly_that_the_loop_retried_by_itself(tmp_path):
    """End to end, from the kernel's records to the words CLIVE is handed for "did the loop retry?"."""
    from app.tools import engineering_tools

    w, receipts = _built_world(tmp_path)
    [item] = build_status(store=w.store, receipts=receipts, now=w.clock())["requests"]

    row = engineering_tools.progress(item)

    assert row["progress"] == "done"
    assert row["history"] == ("Built 4 times; the loop retried it by itself twice (1 transient failure, 1 result "
                              "refused by CLIVE's checks); the review asked for changes once.")


def test_an_unreadable_record_leaves_the_history_out_and_never_stops_the_projection(tmp_path):
    w, receipts = _built_world(tmp_path)
    [item] = build_status(store=w.store, receipts=receipts, now=w.clock())["requests"]
    assert item["build_history"]["attempts"] == 4
    [attempt, *_] = w.store.read_attempts("demo-objective")
    events = w.store.events_dir / "demo-objective" / f"{attempt.attempt_id}.jsonl"
    events.write_text(events.read_text() + "{not json\n")

    [item] = build_status(store=w.store, receipts=receipts, now=w.clock())["requests"]

    assert item["stage"] == "COMPLETE" and "build_history" not in item


def test_the_dispatchers_per_build_keys_are_published_when_it_reports_them(tmp_path):
    status = _published(tmp_path, _Reporting([{"objective_id": "r-built", "stage": "BLOCKED", **DISPATCHER_KEYS},
                                              {"objective_id": "r-plain", "stage": "RUNNING"}]), "r-built", "r-plain")

    built, plain = status["requests"]
    assert built["attempts"] == DISPATCHER_KEYS["attempts"]
    assert built["repairs"] == {"review": 1, "ci": 1, "max": 2}
    assert built["generated"] == ["crooks-assistant/docs/phase4/TOOL_MATRIX.md"]
    assert built["landing"] == DISPATCHER_KEYS["landing"]
    # an entry that reports none of them publishes none of them: absent means unknown, never "none"
    assert set(plain) == PROJECTED_BASE_KEYS
    assert status["schema_version"] == "clive.remote_engineering_status.v1"


def test_a_key_the_dispatcher_reports_as_null_or_misshapen_is_null_and_one_it_omits_is_absent(tmp_path):
    entries = [{"objective_id": "r-null", "landing": None, "repairs": None},
               {"objective_id": "r-odd", "attempts": "three", "repairs": [1, 2], "generated": "TOOL_MATRIX.md",
                "landing": "landed"}]
    null, odd = _published(tmp_path, _Reporting(entries), "r-null", "r-odd")["requests"]

    assert null["landing"] is None and null["repairs"] is None
    assert not {"attempts", "generated"} & set(null)
    assert odd["attempts"] is None and odd["repairs"] is None and odd["generated"] is None and odd["landing"] is None


def test_every_dispatcher_value_is_rebuilt_bounded_and_carries_no_secret_or_customer_data(tmp_path):
    long_reason = "the check failed: " + "one more step passed; " * 400
    entry = {
        "objective_id": "r-built",
        "attempts": [{"attempt_id": f"r-built-a{n}", "revision": 1, "outcome": "cancelled", "reason": f"retry {n}",
                      "at": "2026-09-30T10:00:00+00:00"} for n in range(30)]
        + [{"attempt_id": "bad id with spaces", "revision": True, "outcome": "exploded",
            "reason": f"push failed for {PROJECTION_URL}\nand {PROJECTION_TOKEN}, api_key={PROJECTION_KEY}; "
                      f"the fixture mailed {CUSTOMER_EMAIL} on {CUSTOMER_PHONE}", "at": "yesterday"},
           {"attempt_id": "r-built-naive", "revision": 0, "outcome": ["refused"], "reason": long_reason,
            "at": "2026-09-30T10:00:00"}],
        "repairs": {"review": -1, "ci": True, "max": "2"},
        "generated": [f"docs/generated_{n}.md" for n in range(25)] + [PROJECTION_KEY, "../escape.md", CUSTOMER_EMAIL],
        "landing": {"state": "merged-by-magic", "sha": "ABCDEF0123" * 4, "at": 12,
                    "reason": f"{long_reason} {PROJECTION_TOKEN}"},
    }
    [item] = _published(tmp_path, _Reporting([entry]), "r-built")["requests"]

    assert len(item["attempts"]) == 20 and item["attempts"][0]["attempt_id"] == "r-built-a12"   # the latest 20
    odd, naive = item["attempts"][-2:]
    assert odd["attempt_id"] is None and odd["revision"] is None and odd["outcome"] is None and odd["at"] is None
    assert "\n" not in odd["reason"] and "[redacted]@" in odd["reason"] and "[email]" in odd["reason"]
    assert "[phone]" in odd["reason"]
    assert naive["revision"] is None and naive["outcome"] is None and naive["at"] is None   # a naive time: unknown
    assert len(naive["reason"]) <= 500 and naive["reason"].endswith("...")
    assert item["repairs"] == {"review": None, "ci": None, "max": None}
    assert item["generated"] == [f"docs/generated_{n}.md" for n in range(20)]
    assert item["landing"]["state"] is None and item["landing"]["sha"] is None and item["landing"]["at"] is None
    assert len(item["landing"]["reason"]) <= 500
    text = json.dumps(item)
    for leaked in (PROJECTION_TOKEN, PROJECTION_KEY, PROJECTION_URL, CUSTOMER_EMAIL, CUSTOMER_PHONE, "../escape"):
        assert leaked not in text, leaked


def test_a_dispatcher_without_the_view_or_that_cannot_answer_publishes_none_of_it_and_the_cycle_goes_on(tmp_path):
    for n, dispatcher in enumerate((_Ticker(), _Reporting(error=RuntimeError("notes unreadable")),
                                    _Reporting("nonsense"), _Reporting([None, "x", {"objective_id": 5, **DISPATCHER_KEYS}]))):
        [item] = _published(tmp_path / str(n), dispatcher, "r-built")["requests"]
        assert set(item) == PROJECTED_BASE_KEYS, type(dispatcher).__name__
    # and one that answers is published, beside the ones that do not
    [item] = _published(tmp_path / "answers", _Reporting([{"objective_id": "r-built", **DISPATCHER_KEYS}]),
                        "r-built")["requests"]
    assert item["repairs"] == {"review": 1, "ci": 1, "max": 2}


def test_a_kernel_failure_raised_by_the_dispatchers_status_view_still_stops_the_loop(tmp_path):
    """Fail closed, as from the tick: the projection read swallows ordinary failures, never the store's."""
    store, receipts = _decided(tmp_path, "r-built")
    published: list[dict] = []
    loop = RemoteEngineeringLoop(controller=_QuietIntake(), dispatcher=_Reporting(error=LifecycleError("torn")),
                                 store=store, receipts=receipts,
                                 publish=lambda status: published.append(status) or "a" * 40, clock=lambda: NOW)
    with pytest.raises(LifecycleError):
        loop.cycle()
    assert published == []


def test_the_dispatcher_on_the_trunk_today_publishes_its_records_history_and_none_of_the_new_keys(tmp_path):
    """The real Dispatcher as this lands against it: its status view is read after the tick, the keys it does
    not report yet are absent, the records' history is there regardless, and the keys appear once reported."""
    from app.orchestrator.github_acceptance import GateState
    from tests.test_engineering_dispatcher import OBJ, World

    w = World(tmp_path)
    w.scenarios({"edits": [["pkg/hello.txt", "hello\n"]]})
    w.objective()
    w.acceptance.state = GateState.PENDING
    w.run_until(lambda: w.state_of().status is TaskStatus.EVIDENCE_READY)
    receipts = ReceiptLog(w.store.root / "remote_engineering")
    receipts.put(Receipt(request_id=OBJ, request_sha256="0" * 64, outcome="accepted", objective_id=OBJ,
                         task_id=OBJ, source=f"requests/{OBJ}.json", recorded_at=NOW))
    dispatcher = w.dispatcher()

    def publish_once(d) -> dict:
        published: list[dict] = []
        RemoteEngineeringLoop(controller=_QuietIntake(), dispatcher=d, store=w.store, receipts=receipts,
                              publish=lambda status: published.append(status) or "d" * 40, clock=w.clock).cycle()
        [item] = published[0]["requests"]
        return item

    item = publish_once(dispatcher)
    assert item["stage"] == "EVIDENCE_READY"
    assert item["build_history"]["attempts"] == 1
    reported = {entry["objective_id"]: entry for entry in dispatcher.status()}[OBJ]
    for name in ("attempts", "repairs", "generated", "landing"):
        assert (name in item) == (name in reported), name

    class WithKeys:
        """The same dispatcher, reporting the four keys as the teammate's Dispatcher.status() is to."""

        def tick(self):
            return dispatcher.tick()

        def acceptance_gates(self):
            return dispatcher.acceptance_gates()

        def status(self):
            return [{**entry, **DISPATCHER_KEYS} for entry in dispatcher.status()]

    item = publish_once(WithKeys())
    assert item["stage"] == "EVIDENCE_READY" and item["repairs"] == {"review": 1, "ci": 1, "max": 2}
    assert item["landing"]["state"] == "landed" and len(item["attempts"]) == 3


def test_a_waiting_request_is_listed_until_it_is_decided(tmp_path):
    store, receipts = _decided(tmp_path, "r-decided")
    waits_dir = receipts.dir.parent / "waits"

    status = build_status(store=store, receipts=receipts, now=NOW)
    assert status.get("waiting_requests") == []

    from app.remote_engineering import BASE_WAIT_REASON, WaitLog

    waits = WaitLog(receipts.dir.parent)
    for rid in ("r-decided", "r-waiting"):
        waits.note(request_id=rid, request_sha256="1" * 64, source=f"requests/{rid}.json", now=NOW, bound_s=3600)
    status = build_status(store=store, receipts=receipts, now=NOW)
    assert [r["request_id"] for r in status["requests"]] == ["r-decided"]
    assert status["waiting_requests"] == [{
        "request_id": "r-waiting", "source": "requests/r-waiting.json", "request_sha256": "1" * 64,
        "outcome": "waiting", "reason": BASE_WAIT_REASON, "waiting_since": NOW.isoformat(),
        "refuse_after": (NOW + timedelta(hours=1)).isoformat(),
    }]
    # an unreadable wait record is not published and does not stop the projection
    (waits_dir / "r-garbled.json").write_text("{not json")
    assert [w["request_id"] for w in build_status(store=store, receipts=receipts, now=NOW)["waiting_requests"]] == \
        ["r-waiting"]
