"""The dispatcher end to end, against the real kernel, real git and a real worker process.

The worker is the Claude Code driver (``ClaudeCodeWorker``) pointed at a fake
``claude`` executable written per test. The fake speaks the same stream-json the
real CLI writes (an init event with the roster, tool events, a result with
``structured_output``), edits files in its cwd and can die, stall or misreport its
roster. Only the model is replaced: the launch, the sanitised environment, the
attempt marker, the process checks, the parser and every kernel verb are real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.orchestrator.checks import NamespaceSandbox
from app.orchestrator.contracts import BlockerClass, TaskKind, TaskStatus
from app.orchestrator.dispatcher import Dispatcher, DispatcherBusy, DispatcherConfig
from app.orchestrator.lifecycle import (
    EventKind,
    GitFacts,
    Kernel,
    LifecycleStore,
    PrincipalRegistry,
    VerdictOutcome,
    lifecycle_view,
)
from app.orchestrator.objectives import Check, Objective, ObjectiveStore, OwnerEntry, intake
from app.orchestrator.reviewers import GPT_GAP, GptUnavailable, RelayReviewer, ReviewContext
from app.orchestrator.workers import ClaudeCodeWorker
from app.orchestrator.workers.base import worker_marker

REGISTRY = Path(__file__).resolve().parent.parent / "config" / "review_principals.json"
OBJ = "demo-objective"
ALLOWED = ("pkg",)

FAKE_CLAUDE = r'''#!{python}
import json, os, sys, time
from pathlib import Path
state = Path({state!r})
count_file = state / "invocations"
n = int(count_file.read_text()) if count_file.exists() else 0
count_file.write_text(str(n + 1))
scenarios = json.loads((state / "scenarios.json").read_text())
sc = scenarios[min(n, len(scenarios) - 1)]
argv = sys.argv[1:]
def arg(flag):
    return argv[argv.index(flag) + 1] if flag in argv else None
(state / f"argv.{{n}}.json").write_text(json.dumps(argv))
(state / f"env.{{n}}.json").write_text(json.dumps(sorted(os.environ)))
prompt = arg("-p")
(state / f"prompt.{{n}}.txt").write_text(prompt or "")
def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
tools = sc.get("tools") or (arg("--tools").split(",") + ["StructuredOutput"])
if sc.get("die_before_init"):
    sys.stderr.write(sc.get("stderr", "boom\n")); sys.exit(1)
emit({{"type": "system", "subtype": "init", "session_id": sc.get("session") or arg("--session-id"),
      "cwd": os.getcwd(), "tools": tools, "mcp_servers": sc.get("mcp", []),
      "plugins": [{{"name": "telemetry", "path": "builtin", "source": "telemetry@builtin"}}],
      "skills": [], "slash_commands": [], "permissionMode": arg("--permission-mode"),
      "model": "fake", "apiKeySource": "none"}})
time.sleep(sc.get("sleep_after_init", 0))
for i, (path, content) in enumerate(sc.get("edits", [])):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content)
    emit({{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": f"t{{i}}", "name": "Write",
          "input": {{"file_path": os.path.join(os.getcwd(), path)}}}}]}}}})
    emit({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": f"t{{i}}"}}]}}}})
for path in sc.get("exec", []):
    os.chmod(path, 0o755)
if sc.get("hang"):
    time.sleep(3600)
if sc.get("die"):
    sys.stderr.write(sc.get("stderr", "killed\n")); sys.exit(1)
time.sleep(sc.get("sleep_before_result", 0))
if "error" in sc:
    emit(dict({{"type": "result", "subtype": "error_during_execution", "is_error": True}}, **sc["error"]))
else:
    report = sc.get("report", {{"status": "completed", "summary": "made the change"}})
    emit({{"type": "result", "subtype": "success", "is_error": False, "structured_output": report,
          "num_turns": 3, "session_id": arg("--session-id")}})
'''


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Clock:
    def __init__(self) -> None:
        self.offset = timedelta(0)

    def __call__(self) -> datetime:
        return datetime.now(UTC) + self.offset


class TreeRunnerForTests:
    """A test double for the check runner: runs the check in the exported tree, with no isolation.

    Only for tests of the dispatcher's own logic (evidence, refusal, retry). What isolation a real check
    gets is ``NamespaceSandbox``'s, tested in test_check_sandbox.py and in the sandbox test below.
    """

    kind = "tree-runner-for-tests"

    def availability(self):
        return True, "test double: no isolation"

    def run(self, argv, *, tree, cwd, timeout_s):
        proc = subprocess.run(list(argv), cwd=str(Path(tree) / cwd), capture_output=True, text=True,
                              timeout=timeout_s)
        return {"exit_code": proc.returncode, "stdout_tail": proc.stdout[-6000:], "stderr_tail": proc.stderr[-3000:],
                "runner": self.kind, "sandbox": "none (test double)"}


class FakeReviewer:
    """A programmatic reviewer double: an independent principal answering from a queue."""

    mechanism = "fake-programmatic"
    courier = False

    def __init__(self, principal_id: str = "gpt", available: bool = True) -> None:
        self.principal_id = principal_id
        self.available = available
        self.answers: list = []
        self.started: list[ReviewContext] = []

    def availability(self):
        return self.available, "fake"

    def start(self, ctx):
        if ctx not in self.started:
            self.started.append(ctx)

    def poll(self, ctx):
        out = []
        for answer in self.answers:
            out.append(answer(ctx) if callable(answer) else answer)
        return out


def review(ctx: ReviewContext, verdict: str = "READY", *, findings=(), sha: str | None = None,
           attempt: str | None = None, principal: str = "gpt", revision: int | None = None) -> bytes:
    return json.dumps({
        "schema_version": "clive.review_result.v1",
        "task_id": ctx.task_id, "task_revision": revision or ctx.task_revision,
        "attempt_id": attempt or ctx.attempt_id, "candidate_sha": sha or ctx.candidate_sha,
        "verdict": verdict, "findings": list(findings),
        "reviewer": {"principal_id": principal, "session_id": f"{principal}-review-{ctx.attempt_id}",
                     "session_started_at": "2026-09-23T12:00:00Z", "context_fresh": True,
                     "workspace_id": f"{principal}-ro-checkout", "workspace_branch": "review",
                     "workspace_head": sha or ctx.candidate_sha, "read_only": True, "clean": True},
        "summary": "human-readable explanation; decides nothing",
    }).encode()


FINDING = {"finding_id": "F-01", "material": True, "finding": "the greeting is wrong",
           "evidence_ref": "pkg/hello.txt line 1", "required_repair": "say hello, not goodbye"}


class World:
    def __init__(self, tmp: Path, *, reviewers=None, checks=(), max_repair_rounds: int = 2, runner=None,
                 **config) -> None:
        self.runner = runner or TreeRunnerForTests()
        self.tmp = tmp
        self.repo = tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "pkg").mkdir()
        (self.repo / "pkg" / "hello.txt").write_text("goodbye\n")
        (self.repo / "README").write_text("outside the scope\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
        self.base = _git(self.repo, "rev-parse", "HEAD")
        self.state = tmp / "fake-state"
        self.state.mkdir()
        self.cli = tmp / "claude"
        self.cli.write_text(FAKE_CLAUDE.format(python=sys.executable, state=str(self.state)))
        self.cli.chmod(0o755)
        self.clock = Clock()
        self.store = LifecycleStore(tmp / "engineering")
        self.kernel = Kernel(store=self.store, registry=PrincipalRegistry.load(REGISTRY), git=GitFacts(self.repo),
                             operator="test", journal=False, clock=self.clock)
        self.objectives = ObjectiveStore(self.store, journal=False)
        self.reviewer = FakeReviewer()
        self.reviewers = [self.reviewer] if reviewers is None else reviewers
        defaults = dict(runtime_root=tmp / "runtime", workspace_root=tmp / "workers", repo=self.repo,
                        heartbeat_interval_s=0, progress_interval_s=0, backoff_base_s=0)
        defaults.update(config)
        self.config = DispatcherConfig(**defaults)
        self.checks = checks
        self.max_repair_rounds = max_repair_rounds

    def scenarios(self, *items: dict) -> None:
        (self.state / "scenarios.json").write_text(json.dumps(list(items)))

    def invocations(self) -> int:
        f = self.state / "invocations"
        return int(f.read_text()) if f.exists() else 0

    def dispatcher(self) -> Dispatcher:
        """A fresh dispatcher each call: nothing survives in memory, as after a restart."""
        return Dispatcher(self.kernel, self.objectives, ClaudeCodeWorker(cli=str(self.cli)), self.reviewers,
                          self.config, checks=self.runner)

    def objective(self, **overrides) -> dict:
        fields = dict(
            objective_id=OBJ, title="Demo", requested_outcome="Make pkg/hello.txt say hello.",
            acceptance_criteria=("pkg/hello.txt reads 'hello'",), checks=self.checks,
            repository="crooksldn-pixel/clive", base_ref="main", base_sha=self.base,
            target_branch="clive/objective/demo", product_memory_sha=self.base, allowed_paths=ALLOWED,
            max_repair_rounds=self.max_repair_rounds,
            owner=OwnerEntry(os_user="george", host="host"), created_at=self.clock(),
        )
        fields.update(overrides)
        return intake(Objective(**fields), kernel=self.kernel, objectives=self.objectives)

    def state_of(self, revision: int | None = None):
        tasks = [t for t in self.store.read_tasks() if t.task_id == OBJ]
        rev = revision or max(t.revision for t in tasks)
        return self.store.read_task_state(OBJ, rev)

    def run_until(self, predicate, *, timeout: float = 20.0, dispatcher: Dispatcher | None = None) -> list[str]:
        d = dispatcher or self.dispatcher()
        lines: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            lines += d.tick()
            if predicate():
                return lines
            time.sleep(0.05)
        raise AssertionError(f"timed out; state {self.state_of()}; log:\n" + "\n".join(lines))

    def stage(self) -> str:
        view = lifecycle_view(self.store, now=self.clock())
        task = [t for t in view["tasks"] if t["task_id"] == OBJ]
        return max(task, key=lambda t: t["revision"])["stage"]

    def status_is(self, *statuses: TaskStatus):
        return lambda: self.state_of().status in statuses


EDIT_HELLO = {"edits": [["pkg/hello.txt", "hello\n"]]}


# ---------------------------------------------------------------- happy path

def test_one_objective_reaches_complete_through_the_real_records(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    out = w.objective()
    assert out["stage"] == "ready" and out["required_evidence"] == ["worker_report", "worker_transcript"]
    w.reviewer.answers.append(lambda ctx: review(ctx, "READY"))
    w.run_until(lambda: w.stage() == "COMPLETE")

    attempt = w.store.read_attempts(OBJ)[0]
    result = w.store.read_results()[0]
    # candidate identity is git's: the target branch, the ingested ref and the result agree
    assert _git(w.repo, "rev-parse", "clive/objective/demo") == result.result_sha
    assert _git(w.repo, "show", f"{result.result_sha}:pkg/hello.txt") == "hello"
    assert result.changed_paths == ("pkg/hello.txt",)
    # one workspace per attempt, under the root: a plain tree, its git metadata beside it with no remote
    ws = tmp_path / "workers" / OBJ / attempt.attempt_id
    assert attempt.worker.workspace.workspace_id == str(ws)
    assert not (ws / ".git").exists() and (ws.parent / f"{attempt.attempt_id}.git" / "HEAD").is_file()
    assert _git(ws.parent / f"{attempt.attempt_id}.git", "remote") == ""
    # the kernel session is the session the worker ran as
    argv = json.loads((w.state / "argv.0.json").read_text())
    assert argv[argv.index("--session-id") + 1] == attempt.worker.session.session_id
    # lifecycle: every verb in order, from real observations
    kinds = [e.kind for e in w.store.read_events(OBJ, attempt.attempt_id)]
    assert kinds[:2] == [EventKind.OPENED, EventKind.ACKNOWLEDGED]
    assert EventKind.PROGRESS in kinds and kinds.index(EventKind.PROGRESS) < kinds.index(EventKind.CANDIDATE)
    assert kinds[-4:] == [EventKind.REVIEW_DISPATCHED, EventKind.VERDICT_ADMITTED, EventKind.ACCEPTED,
                          EventKind.INTEGRATED]
    progress = [e for e in w.store.read_events(OBJ, attempt.attempt_id) if e.kind is EventKind.PROGRESS]
    assert "pkg/hello.txt" in progress[0].note
    evidence = {e.evidence_name for e in w.store.read_events(OBJ, attempt.attempt_id) if e.kind is EventKind.EVIDENCE}
    assert evidence == {"worker_report", "worker_transcript"}
    integration = w.store.read_integrations()[0]
    assert integration.method.value == "fast_forward" and integration.integration_sha == result.result_sha
    assert w.invocations() == 1


def test_the_worker_process_gets_a_sanitised_environment_and_a_fresh_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "must-not-leak")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "must-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    env = json.loads((w.state / "env.0.json").read_text())
    assert set(env) <= {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_ATTEMPT_ID", "PWD", "SHLVL", "_", "LC_CTYPE"}
    attempt = w.store.read_attempts(OBJ)[0]
    runtime = json.loads((tmp_path / "runtime" / "attempts" / f"{attempt.attempt_id}.json").read_text())
    assert runtime["roster"]["mcp_servers"] == [] and runtime["roster"]["problems"] == []
    assert "Bash" not in runtime["roster"]["tools"]


# ---------------------------------------------------------------- restart and liveness

def test_a_restarted_dispatcher_reattaches_and_never_launches_a_second_worker(tmp_path):
    w = World(tmp_path)
    w.scenarios({**EDIT_HELLO, "sleep_before_result": 1.5})
    w.objective()
    first = w.dispatcher()
    first.tick()
    deadline = time.monotonic() + 10
    while w.invocations() < 1 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert w.invocations() == 1
    for _ in range(5):  # several brand-new dispatchers while the worker is still running
        w.dispatcher().tick()
    assert w.invocations() == 1
    w.reviewer.answers.append(lambda ctx: review(ctx))
    w.run_until(lambda: w.stage() == "COMPLETE")
    assert w.invocations() == 1


def test_a_candidate_finished_while_the_dispatcher_was_down_is_not_lost(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.dispatcher().tick()  # assign + launch, then the dispatcher "dies"
    attempt = w.store.read_attempts(OBJ)[0]
    worker = ClaudeCodeWorker(cli=str(w.cli))
    deadline = time.monotonic() + 10
    while worker.live_pids(worker_marker(attempt.attempt_id, attempt.worker.session.session_id)) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not worker.live_pids(worker_marker(attempt.attempt_id, attempt.worker.session.session_id))
    w.dispatcher().tick()  # a new dispatcher: ack from the log, then the candidate from the workspace
    assert w.state_of().status in (TaskStatus.REVIEWING, TaskStatus.EVIDENCE_READY)
    assert w.store.read_results()[0].result_sha == _git(w.repo, "rev-parse", "clive/objective/demo")


def test_a_dispatcher_that_dies_while_ingesting_a_result_recovers_the_candidate(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    d = w.dispatcher()

    def crash(task, sha):
        raise RuntimeError("dispatcher killed mid-ingest")

    d._publish = crash
    with pytest.raises(RuntimeError):
        w.run_until(lambda: False, dispatcher=d, timeout=10)
    assert w.state_of().status is TaskStatus.RUNNING and not w.store.read_results()
    w.run_until(w.status_is(TaskStatus.REVIEWING))  # a fresh dispatcher finds the same result
    assert len(w.store.read_attempts(OBJ)) == 1 and w.invocations() == 1
    assert w.store.read_results()[0].result_sha == _git(w.repo, "rev-parse", "clive/objective/demo")


def test_a_worker_of_another_store_with_the_same_attempt_id_is_never_taken_for_ours(tmp_path):
    (tmp_path / "other").mkdir()
    (tmp_path / "ours").mkdir()
    other = World(tmp_path / "other")
    other.scenarios({**EDIT_HELLO, "hang": True})
    other.objective()
    other.run_until(other.status_is(TaskStatus.RUNNING))  # a live worker named demo-objective-a1 elsewhere
    theirs = other.store.read_attempts(OBJ)[0]
    w = World(tmp_path / "ours")
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx))
    w.run_until(lambda: w.stage() == "COMPLETE")  # launched its own worker despite the same attempt id
    assert w.invocations() == 1
    worker = ClaudeCodeWorker(cli=str(other.cli))
    assert worker.live_pids(worker_marker(theirs.attempt_id, theirs.worker.session.session_id))  # and never killed it
    worker.kill(worker_marker(theirs.attempt_id, theirs.worker.session.session_id))


def test_two_dispatchers_cannot_tick_at_once(tmp_path):
    w = World(tmp_path)
    w.objective()
    d = w.dispatcher()
    with d.exclusive(), pytest.raises(DispatcherBusy):
        w.dispatcher().tick()


def test_a_process_that_dies_is_a_transient_failure_retried_with_a_higher_token(tmp_path):
    w = World(tmp_path)
    w.scenarios({"die": True}, EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    attempts = w.store.read_attempts(OBJ)
    assert [a.fencing_token for a in attempts] == [1, 2]
    cancelled = [e for e in w.store.read_events(OBJ, attempts[0].attempt_id) if e.kind is EventKind.CANCELLED]
    assert cancelled[0].note.startswith("transient:")
    assert w.store.read_results()[0].attempt_id == attempts[1].attempt_id


def test_transient_failures_are_bounded_then_block(tmp_path):
    w = World(tmp_path, max_transient_retries=2)
    w.scenarios({"die": True})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    state = w.state_of()
    assert state.blocker_class is BlockerClass.DETERMINISTIC and "exhausted" in state.blocker_reason
    assert w.invocations() == 2


def test_backoff_is_honoured_between_transient_retries(tmp_path):
    w = World(tmp_path, backoff_base_s=600)
    w.scenarios({"die": True}, EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.READY))
    lines = w.dispatcher().tick()
    assert any("backing off" in line for line in lines) and w.invocations() == 1
    w.clock.offset = timedelta(seconds=601)
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    assert w.invocations() == 2


def test_an_authentication_failure_is_deterministic_not_retried(tmp_path):
    w = World(tmp_path)
    w.scenarios({"die_before_init": True, "stderr": "Invalid API key · Please run /login\n"})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert "authentication" in w.state_of().blocker_reason and w.invocations() == 1


def test_a_stalled_worker_is_killed_and_cancelled(tmp_path):
    w = World(tmp_path, stall_s=30)
    w.scenarios({"hang": True, **EDIT_HELLO}, EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.RUNNING))
    w.dispatcher().tick()
    w.clock.offset = timedelta(seconds=31)
    w.run_until(lambda: len(w.store.read_attempts(OBJ)) == 2)
    first = w.store.read_attempts(OBJ)[0]
    assert not ClaudeCodeWorker(cli=str(w.cli)).live_pids(worker_marker(first.attempt_id, first.worker.session.session_id))
    notes = [e.note for e in w.store.read_events(OBJ, first.attempt_id) if e.kind is EventKind.CANCELLED]
    assert "stalled" in notes[0]


def test_liveness_is_not_progress_and_no_heartbeat_comes_from_the_launch_alone(tmp_path):
    w = World(tmp_path, heartbeat_interval_s=0)
    w.scenarios({"sleep_after_init": 1.0, **EDIT_HELLO})
    w.objective()
    w.run_until(w.status_is(TaskStatus.RUNNING))
    attempt = w.store.read_attempts(OBJ)[0]
    w.dispatcher().tick()
    kinds = [e.kind for e in w.store.read_events(OBJ, attempt.attempt_id)]
    assert EventKind.HEARTBEAT not in kinds and EventKind.PROGRESS not in kinds  # init only: no event yet
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    kinds = [e.kind for e in w.store.read_events(OBJ, attempt.attempt_id)]
    assert EventKind.PROGRESS in kinds


# ---------------------------------------------------------------- launch surface and scope

def test_a_worker_reporting_an_mcp_server_is_killed_and_blocked_before_acknowledgement(tmp_path):
    w = World(tmp_path)
    w.scenarios({"mcp": [{"name": "claude.ai Shopify", "status": "connected"}], "sleep_after_init": 30})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    state = w.state_of()
    assert "MCP servers present" in state.blocker_reason and "Shopify" in state.blocker_reason
    attempt = w.store.read_attempts(OBJ)[0]
    assert EventKind.ACKNOWLEDGED not in {e.kind for e in w.store.read_events(OBJ, attempt.attempt_id)}
    assert not ClaudeCodeWorker(cli=str(w.cli)).live_pids(worker_marker(attempt.attempt_id, attempt.worker.session.session_id))


def test_a_worker_reporting_extra_tools_or_another_session_is_refused(tmp_path):
    w = World(tmp_path)
    w.scenarios({"tools": ["Read", "Edit", "Bash", "WebFetch"], "session": "someone-else"})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    reason = w.state_of().blocker_reason
    assert "Bash" in reason and "WebFetch" in reason and "not the assigned session" in reason


def test_an_out_of_scope_change_is_refused_and_retried_then_blocked(tmp_path):
    w = World(tmp_path)
    w.scenarios({"edits": [["pkg/hello.txt", "hello\n"], ["README", "edited\n"]]})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert not w.store.read_results()  # no candidate was recorded for an out-of-scope tree
    assert "refused 2 times" in w.state_of().blocker_reason
    prompt = (w.state / "prompt.1.txt").read_text()
    assert "outside the objective's scope" in prompt and "README" in prompt


def test_a_worker_that_changes_nothing_has_no_candidate(tmp_path):
    w = World(tmp_path, max_result_refusals=1)
    w.scenarios({"edits": []})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert not w.store.read_results() and "changed nothing" in w.state_of().blocker_reason


def test_nothing_the_worker_writes_in_its_tree_can_steer_clives_git(tmp_path):
    sentinel = tmp_path / "git-was-steered"
    hostile = {"edits": [
        ["pkg/hello.txt", "hello\n"],
        [".git/config", f"[core]\n\tfsmonitor = touch {sentinel}\n\thooksPath = .git/hooks\n"
                        f"[filter \"evil\"]\n\tclean = touch {sentinel}\n"],
        [".git/hooks/post-commit", f"#!/bin/sh\ntouch {sentinel}\n"],
        [".git/hooks/pre-commit", f"#!/bin/sh\ntouch {sentinel}\n"],
        ["pkg/.gitattributes", "* filter=evil\n"],
        ["pkg/.git", "gitdir: /tmp/elsewhere\n"],
    ], "exec": [".git/hooks/post-commit", ".git/hooks/pre-commit"]}
    w = World(tmp_path)
    w.scenarios(hostile)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    result = w.store.read_results()[0]
    ws = tmp_path / "workers" / OBJ / result.attempt_id
    assert os.access(ws / ".git" / "hooks" / "post-commit", os.X_OK)  # the planted hooks were armed
    assert not sentinel.exists()  # no fsmonitor, hook or filter the worker planted ran
    tree = _git(w.repo, "ls-tree", "-r", "--name-only", result.result_sha).splitlines()
    assert not any(p == ".git" or p.startswith(".git/") or p.endswith("/.git") for p in tree)
    assert set(result.changed_paths) == {"pkg/hello.txt", "pkg/.gitattributes"}
    # the trusted metadata is the one CLIVE created, beside the tree, untouched
    gd = tmp_path / "workers" / OBJ / f"{result.attempt_id}.git"
    assert "evil" not in (gd / "config").read_text() and "fsmonitor" not in (gd / "config").read_text()


def test_checks_run_in_the_sandbox_on_a_copy_and_cannot_touch_the_candidate_tree(tmp_path):
    from tests.test_check_sandbox import require_sandbox

    probe = Check(name="probe", argv=("/bin/sh", "-c", "id -u > uid.txt; echo tampered > pkg/hello.txt; cat uid.txt"))
    w = World(tmp_path, checks=(probe,), runner=require_sandbox(NamespaceSandbox()))
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    attempt = w.store.read_attempts(OBJ)[0]
    ws = tmp_path / "workers" / OBJ / attempt.attempt_id
    assert (ws / "pkg" / "hello.txt").read_text() == "hello\n" and not (ws / "uid.txt").exists()
    evidence = json.loads((tmp_path / "runtime" / "evidence" / attempt.attempt_id / "check-probe.json").read_text())
    assert evidence["runner"] == "linux-namespaces" and "canary held" in evidence["sandbox"]
    expected = "65534" if os.geteuid() == 0 else "0"
    assert evidence["stdout_tail"].strip() == expected
    assert w.store.read_results()[0].clean_worktree


class NoSandbox:
    kind = "unavailable-for-test"

    def __init__(self):
        self.ran = []

    def availability(self):
        return False, "unshare is not permitted on this host"

    def run(self, argv, **kw):  # pragma: no cover - must never be reached
        self.ran.append(argv)
        raise AssertionError("a check ran without a sandbox")


def test_without_a_sandbox_checks_never_run_and_the_task_blocks(tmp_path):
    w = World(tmp_path, checks=(Check(name="says-hello", argv=("grep", "-q", "hello", "pkg/hello.txt")),))
    w.scenarios(EDIT_HELLO)
    w.objective()
    runner = NoSandbox()
    d = Dispatcher(w.kernel, w.objectives, ClaudeCodeWorker(cli=str(w.cli)), w.reviewers, w.config, checks=runner)
    w.run_until(w.status_is(TaskStatus.BLOCKED), dispatcher=d)
    reason = w.state_of().blocker_reason
    assert "check sandbox unavailable" in reason and "never run unsandboxed" in reason
    assert runner.ran == [] and not w.store.read_results()


def test_failed_checks_are_evidence_and_never_a_candidate(tmp_path):
    check = Check(name="says-hello", argv=("grep", "-q", "^hello$", "pkg/hello.txt"))
    w = World(tmp_path, checks=(check,))
    w.scenarios({"edits": [["pkg/hello.txt", "helo\n"]]}, EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    first, second = w.store.read_attempts(OBJ)
    first_events = w.store.read_events(OBJ, first.attempt_id)
    assert any(e.kind is EventKind.EVIDENCE and e.evidence_name == "check-says-hello" for e in first_events)
    assert "checks failed" in [e.note for e in first_events if e.kind is EventKind.CANCELLED][0]
    result = w.store.read_results()[0]
    assert result.attempt_id == second.attempt_id and "check-says-hello" in result.evidence_satisfied
    # the retry is told what failed, not only that something did
    retry_prompt = (w.state / "prompt.1.txt").read_text()
    assert f"FAILED CHECK `says-hello` on {first.attempt_id} (exit 1)" in retry_prompt


# ---------------------------------------------------------------- review

def test_without_an_available_independent_reviewer_the_task_blocks_with_the_exact_gap(tmp_path):
    w = World(tmp_path, reviewers=[GptUnavailable()])
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    attempt = w.store.read_attempts(OBJ)[0]
    assert not w.store.read_dispatches(OBJ, attempt.attempt_id)  # nothing dispatched to nobody
    assert GPT_GAP.split(":")[0] in w.state_of().blocker_reason
    assert w.store.read_results()  # the candidate itself is kept


def test_the_author_principal_is_never_chosen_as_reviewer(tmp_path):
    w = World(tmp_path, reviewers=[FakeReviewer(principal_id="claude")])
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert "claude: is the author principal" in w.state_of().blocker_reason


def test_changes_required_routes_a_repair_revision_and_the_old_verdict_does_not_transfer(tmp_path):
    w = World(tmp_path)
    w.scenarios({"edits": [["pkg/hello.txt", "bye\n"]]}, {"edits": [["pkg/hello.txt", "hello\n"]]})
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[FINDING])
                              if ctx.task_revision == 1 else review(ctx, "READY"))
    w.run_until(lambda: w.stage() == "COMPLETE")
    r1, r2 = sorted((t for t in w.store.read_tasks() if t.task_id == OBJ), key=lambda t: t.revision)
    assert r2.kind is TaskKind.REPAIR and r2.base_sha == r1.base_sha and "F-01" in r2.objective
    assert w.store.read_task_state(OBJ, 1).status is TaskStatus.OBSOLETE
    a1, a2 = w.store.read_attempts(OBJ)
    rejected = next(r for r in w.store.read_results() if r.attempt_id == a1.attempt_id).result_sha
    repaired = next(r for r in w.store.read_results() if r.attempt_id == a2.attempt_id).result_sha
    assert _git(w.repo, "merge-base", "--is-ancestor", rejected, repaired) == ""  # repair builds on it
    assert [a.attempt_id for a in w.store.read_acceptances(OBJ)] == [a2.attempt_id]  # r1 never accepted
    prompt = (w.state / "prompt.1.txt").read_text()
    assert "[F-01]" in prompt and rejected in prompt and "say hello, not goodbye" in prompt
    packet = (w.store.root / w.store.read_dispatches(OBJ, a2.attempt_id)[-1].packet_path).read_text()
    assert repaired in packet and "F-01" in packet


def test_the_convergence_limit_blocks_instead_of_repairing_forever(tmp_path):
    w = World(tmp_path, max_repair_rounds=0)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[FINDING]))
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert "convergence limit" in w.state_of().blocker_reason
    assert len([t for t in w.store.read_tasks() if t.task_id == OBJ]) == 1


def test_stale_and_drifted_verdicts_are_refused(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    other_sha = w.base
    w.reviewer.answers += [
        lambda ctx: review(ctx, "READY", attempt="demo-objective-a9"),  # another attempt: refused at the door
        lambda ctx: review(ctx, "READY", sha=other_sha),  # this attempt, another SHA: the kernel refuses
        b"READY. Looks good to me!",  # prose: never parsed
    ]
    lines = w.dispatcher().tick()
    assert any("stale review result refused" in line for line in lines)
    assert w.state_of().status is TaskStatus.REVIEWING
    attempt = w.store.read_attempts(OBJ)[0]
    admissions = w.store.read_admissions(OBJ, attempt.attempt_id)
    assert [a.outcome for a in admissions] == [VerdictOutcome.REFUSED]
    w.dispatcher().tick()
    assert w.state_of().status is TaskStatus.REVIEWING and not w.store.read_acceptances(OBJ)
    w.reviewer.answers.append(lambda ctx: review(ctx, "READY"))
    w.run_until(lambda: w.stage() == "COMPLETE")


def test_a_relay_review_is_marked_courier_and_admitted_from_a_typed_file(tmp_path):
    relay = RelayReviewer(tmp_path / "runtime" / "relay")
    w = World(tmp_path, reviewers=[relay])
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    attempt = w.store.read_attempts(OBJ)[0]
    dispatch = w.store.read_dispatches(OBJ, attempt.attempt_id)[-1]
    ctx = ReviewContext(OBJ, 1, attempt.attempt_id, dispatch.dispatch_seq, dispatch.candidate_sha,
                        w.store.root / dispatch.packet_path)
    assert relay.outbox(ctx).read_bytes() == (w.store.root / dispatch.packet_path).read_bytes()
    status = w.dispatcher().status()[0]
    assert status["review_mechanism"]["courier"] is True
    relay.submit(ctx, review(ctx), stamp="1")
    w.run_until(lambda: w.stage() == "COMPLETE")


# ---------------------------------------------------------------- authority and integration

def test_owner_decision_from_the_worker_is_an_owner_gate_the_dispatcher_never_lifts(tmp_path):
    w = World(tmp_path)
    w.scenarios({"report": {"status": "owner_decision_required", "summary": "needs a Shopify token",
                            "reason": "the objective needs a new credential"}})
    w.objective()
    w.run_until(w.status_is(TaskStatus.OWNER_GATE))
    before = w.state_of()
    assert before.owner_gate and before.blocker_class is BlockerClass.OWNER_ONLY
    for _ in range(3):
        w.dispatcher().tick()
    assert w.state_of() == before and w.invocations() == 1


def test_a_worker_that_reports_blocked_blocks_the_task(tmp_path):
    w = World(tmp_path)
    w.scenarios({"report": {"status": "blocked", "summary": "cannot", "reason": "the file does not exist"}})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert "the file does not exist" in w.state_of().blocker_reason


def test_complete_only_after_verified_integration_of_the_exact_accepted_sha(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    # someone moves the target branch after review dispatch: the acceptance cannot integrate
    w.reviewer.answers.append(lambda ctx: review(ctx))
    d = w.dispatcher()
    original = d._integrate

    def moved_then_integrate(obj, task, state):
        _git(w.repo, "update-ref", "refs/heads/clive/objective/demo", w.base)
        return original(obj, task, state)

    d._integrate = moved_then_integrate
    w.run_until(w.status_is(TaskStatus.BLOCKED), dispatcher=d)
    assert w.stage() == "BLOCKED" and not w.store.read_integrations()
    assert "integration refused" in w.state_of().blocker_reason


def test_status_reports_what_a_person_needs_without_inventing_progress(tmp_path):
    w = World(tmp_path)
    w.scenarios({**EDIT_HELLO, "sleep_before_result": 1.0})
    w.objective()
    w.run_until(w.status_is(TaskStatus.RUNNING))
    item = w.dispatcher().status()[0]
    assert item["stage"] == "RUNNING" and item["process"]["alive"] is True
    assert item["candidate_sha"] is None and item["next_action"].startswith("observe the worker")
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    item = w.dispatcher().status()[0]
    assert item["candidate_sha"] and item["process"]["alive"] is False and item["last_progress"]


def test_the_cli_door_records_an_objective_and_its_task(tmp_path):
    w = World(tmp_path)
    script = Path(__file__).resolve().parent.parent / "scripts" / "engineering_dispatcher.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--store", str(w.store.root), "--repo", str(w.repo), "--no-journal",
         "--runtime-root", str(tmp_path / "rt"), "--workspace-root", str(tmp_path / "ws"),
         "objective", "--title", "Say hello", "--objective", "Make pkg/hello.txt say hello.",
         "--base-ref", "main", "--product-memory-ref", "main", "--allowed-path", "pkg",
         "--check", "hello=grep -q hello pkg/hello.txt"],
        capture_output=True, text=True, cwd=tmp_path, env={**os.environ},
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["objective_id"] == "say-hello" and out["stage"] == "ready"
    objective = w.objectives.read("say-hello")
    assert objective.target_branch == "clive/objective/say-hello" and objective.checks[0].argv[0] == "grep"
    assert w.store.read_task("say-hello", 1).required_evidence == ("worker_report", "worker_transcript", "check-hello")
