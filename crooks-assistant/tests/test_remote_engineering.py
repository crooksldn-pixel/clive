"""The bounded GitHub inbox and controller adapter: same or less authority than CLI intake, idempotent, no second store."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.orchestrator.contracts import BlockerClass, TaskStatus
from app.orchestrator.lifecycle import (
    GitFacts,
    Kernel,
    LifecycleStore,
    PrincipalRegistry,
)
from app.orchestrator.objectives import ObjectiveStore
from app.remote_engineering import (
    DEFAULT_INBOX_BRANCH,
    DEFAULT_INBOX_DIRECTORY,
    DEFAULT_STATUS_BRANCH,
    REQUEST_SCHEMA,
    InboxError,
    Receipt,
    ReceiptLog,
    RemoteController,
    RemoteControllerConfig,
    RemoteEngineeringLoop,
    RequestSchemaError,
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
    commit_request(env.origin, "r1a", valid_request(env, request_id="r1a"))
    kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    first = controller.poll_once()
    second = controller.poll_once()
    assert first == second
    assert len(kernel.store.read_tasks()) == 1


def test_same_id_different_content_is_refused(env, tmp_path):
    commit_request(env.origin, "r2a", valid_request(env, request_id="r2a"))
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    commit_request(env.origin, "r2a", valid_request(env, request_id="r2a", requested_outcome="Something else."))
    with pytest.raises(InboxError):
        controller.poll_once()
    assert objectives.read("r2a").requested_outcome.startswith("Show unanswered")


def test_protected_scope_is_refused_by_canonical_validation(env, tmp_path):
    commit_request(env.origin, "r3a", valid_request(
        env, request_id="r3a", allowed_paths=["crooks-assistant/app/orchestrator/lifecycle.py"]
    ))
    kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert "no objective may put in scope" in outcomes[0]["reason"]
    assert objectives.read("r3a") is None
    assert kernel.store.read_task("r3a", 1) is None


def test_malformed_schema_fails_closed(env, tmp_path):
    commit_request(env.origin, "bad", {"not": "a request"}, filename="bad.json")
    _kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert receipts.read_all() == ()


def test_unknown_field_is_refused_not_executed(env, tmp_path):
    payload = valid_request(env, request_id="r4a")
    payload["shell"] = "rm -rf /"
    commit_request(env.origin, "r4a", payload)
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert objectives.read("r4a") is None


def test_check_argv_is_never_shell_parsed(env, tmp_path):
    payload = valid_request(env, request_id="r12", checks=[{"name": "x", "argv": ["true; rm -rf /"], "cwd": "."}])
    commit_request(env.origin, "r12", payload)
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    assert objectives.read("r12").checks[0].argv == ("true; rm -rf /",)


def test_owner_gate_cannot_be_lifted_by_replay(env, tmp_path):
    commit_request(env.origin, "r5a", valid_request(env, request_id="r5a"))
    kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    kernel.block("r5a", 1, blocker_class=BlockerClass.OWNER_ONLY, reason="needs owner", owner_gate=True)
    controller.poll_once()
    assert kernel.store.read_task_state("r5a", 1).status is TaskStatus.OWNER_GATE


def test_owner_gate_cannot_be_lifted_even_if_the_receipt_is_lost(env, tmp_path):
    commit_request(env.origin, "r5b", valid_request(env, request_id="r5b"))
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    kernel.block("r5b", 1, blocker_class=BlockerClass.OWNER_ONLY, reason="needs owner", owner_gate=True)
    receipts._path("r5b").unlink()
    controller.poll_once()
    assert kernel.store.read_task_state("r5b", 1).status is TaskStatus.OWNER_GATE


def test_controller_exposes_no_verb_that_could_advance_or_resolve_lifecycle(env):
    for verb in ("resume", "block", "assign", "dispatch_review", "admit_verdict", "integrate"):
        assert not hasattr(RemoteController, verb)


def test_restart_and_repoll_do_not_duplicate(env, tmp_path):
    commit_request(env.origin, "r6a", valid_request(env, request_id="r6a"))
    _kernel, _objectives, _receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    kernel2, _objectives2, _receipts2, controller2 = make_controller(env, tmp_path)
    controller2.poll_once()
    assert len(kernel2.store.read_tasks()) == 1
    assert kernel2.store.read_attempts() == ()


def test_status_is_a_projection_of_existing_records(env, tmp_path):
    commit_request(env.origin, "r7a", valid_request(env, request_id="r7a"))
    kernel, _objectives, receipts, controller = make_controller(env, tmp_path)
    controller.poll_once()
    status = build_status(store=kernel.store, receipts=receipts, now=NOW)
    item = status["requests"][0]
    assert item["objective_id"] == "r7a" and item["task_id"] == "r7a"
    assert item["stage"] == "READY"
    assert item["owner_gate"] is False


def test_credential_like_extra_field_never_enters_output(env, tmp_path):
    secret = "sk-supersecrettoken1234567890"
    payload = valid_request(env, request_id="r8a")
    payload["api_key"] = secret
    commit_request(env.origin, "r8a", payload)
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
    commit_request(env.origin, "r11", valid_request(env, request_id="r11", base_sha="f" * 40))
    _kernel, objectives, _receipts, controller = make_controller(env, tmp_path)
    outcomes = controller.poll_once()
    assert outcomes[0]["outcome"] == "refused"
    assert objectives.read("r11") is None


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
    commit_request(env.origin, "r10", valid_request(env, request_id="r10"))
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
    assert '"r10"' in status_out


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
