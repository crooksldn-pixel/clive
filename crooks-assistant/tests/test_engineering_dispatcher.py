"""The dispatcher end to end, against the real kernel, real git and a real worker process.

The worker is the Claude Code driver (``ClaudeCodeWorker``) pointed at a fake
``claude`` executable written per test. The fake speaks the same stream-json the
real CLI writes (an init event with the roster, tool events, a result with
``structured_output``), edits files in its cwd and can die, stall or misreport its
roster. Only the model is replaced: the launch, the sanitised environment, the
attempt marker, the process checks, the parser and every kernel verb are real.

By default the fake reports the roster the real CLI reports for the launch it was given,
MCP included: every server its ``--mcp-config`` names is listed ``connected`` and that
server's tools named in ``--allowedTools`` are in ``tools``, as Claude Code 2.1.285 did
for the ``clive_checks`` launch on 2026-09-30 (``{"name": "clive_checks", "status":
"connected"}`` and ``mcp__clive_checks__run_checks``). That default changed with the
2026-09-30 re-pin review (second run, F-01): a launch with declared checks now requires
the tool and the connected server, and the old default (no MCP at all) would have made
every builder launched with checks a refused launch. A scenario's ``tools`` and ``mcp``
keys still replace the roster exactly, which is how a missing tool or server is tested.
``ignore_sigterm`` makes the worker ignore SIGTERM, so only SIGKILL stops it;
``sleep_after_result`` keeps it alive after its result.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.orchestrator import objectives as objectives_module
from app.orchestrator.checks import NamespaceSandbox
from app.orchestrator.contracts import BlockerClass, TaskKind, TaskStatus
from app.orchestrator.dispatcher import Dispatcher, DispatcherBusy, DispatcherConfig
from app.orchestrator.github_acceptance import GateResult, GateState, RunFact
from app.orchestrator.lifecycle import (
    EventKind,
    GitFacts,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
    VerdictOutcome,
    lifecycle_view,
    sha256_of,
)
from app.orchestrator.objectives import (
    RECORDED,
    Check,
    Objective,
    ObjectiveStore,
    OwnerEntry,
    intake,
)
from app.orchestrator.reviewers import GPT_GAP, GptUnavailable, RelayReviewer, ReviewContext
from app.orchestrator.workers import ClaudeCodeWorker
from app.orchestrator.workers.base import Finished, LaunchSpec, processes_with_marker, worker_marker
from app.orchestrator.workers.claude import CHECK_TOOL, MARKER

REGISTRY = Path(__file__).resolve().parent.parent / "config" / "review_principals.json"
OBJ = "demo-objective"
ALLOWED = ("pkg",)

FAKE_CLAUDE = r'''#!{python}
import json, os, signal, sys, time
from pathlib import Path
state = Path({state!r})
count_file = state / "invocations"
n = int(count_file.read_text()) if count_file.exists() else 0
count_file.write_text(str(n + 1))
scenarios = json.loads((state / "scenarios.json").read_text())
sc = scenarios[min(n, len(scenarios) - 1)]
if sc.get("ignore_sigterm"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)   # only SIGKILL stops it; installed before argv.<n>.json exists
argv = sys.argv[1:]
def arg(flag):
    return argv[argv.index(flag) + 1] if flag in argv else None
(state / f"argv.{{n}}.json").write_text(json.dumps(argv))
(state / f"env.{{n}}.json").write_text(json.dumps(sorted(os.environ)))
prompt = arg("-p")
(state / f"prompt.{{n}}.txt").write_text(prompt or "")
def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
# The roster the real CLI reports for this launch: its --mcp-config servers connected, their allowed tools listed.
servers = list(json.loads(arg("--mcp-config") or "{{}}").get("mcpServers", {{}}))
granted = argv[argv.index("--allowedTools") + 1:] if "--allowedTools" in argv else []
granted = granted[:next((i for i, a in enumerate(granted) if a.startswith("--")), len(granted))]
mcp_tools = [t for t in granted if any(t.startswith(f"mcp__{{s}}__") for s in servers)]
tools = sc.get("tools") or (arg("--tools").split(",") + ["StructuredOutput"] + mcp_tools)
# A skills launch (--plugin-dir): the folder's skills as the real CLI names them, the folder as an inline plugin,
# and two of the CLI's own commands beside the skills, as 2.1.293 lists them with bundled skills off.
plugin_dir = arg("--plugin-dir")
folder_skills = sorted(p.name for p in (Path(plugin_dir) / "skills").iterdir()) if plugin_dir else []
skills = sc.get("skills", [f"clive-skills:{{n}}" for n in folder_skills])
plugins = [{{"name": "telemetry", "path": "builtin", "source": "telemetry@builtin"}}] + sc.get("plugins", (
    [{{"name": "clive-skills", "path": plugin_dir, "source": "clive-skills@inline", "version": "1.0.0"}}]
    if plugin_dir else []))
slash = sc.get("slash_commands", skills + (["compact", "model"] if plugin_dir else []))
if sc.get("die_before_init"):
    sys.stderr.write(sc.get("stderr", "boom\n")); sys.exit(1)
time.sleep(sc.get("sleep_before_init", 0))
emit({{"type": "system", "subtype": "init", "session_id": sc.get("session") or arg("--session-id"),
      "cwd": os.getcwd(), "tools": tools,
      "mcp_servers": sc.get("mcp", [{{"name": s, "status": "connected"}} for s in servers]),
      "plugins": plugins,
      "skills": skills, "slash_commands": slash, "permissionMode": arg("--permission-mode"),
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
time.sleep(sc.get("sleep_after_result", 0))
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


class FakeAcceptance:
    """The GitHub acceptance gate double: every SHA is green unless a test says otherwise.

    Like the real gate it reads a red run's failed job (``failure_log``): ``logs`` holds what it answers per SHA,
    as keyword arguments of a ``FailureLog``; a SHA without one answers that no log could be read."""

    def __init__(self, state: GateState = GateState.GREEN) -> None:
        self.state = state
        self.by_sha: dict[str, GateState] = {}
        self.asked: list[tuple[str, str]] = []
        self.logs: dict[str, dict] = {}
        self.logs_asked: list[tuple[str, str, tuple[int, ...]]] = []
        self.red_conclusion: dict[str, str] = {}      # a red run's conclusion per SHA; "failure" unless set

    def failure_log(self, repository: str, sha: str, run_ids: tuple[int, ...]):
        from app.orchestrator.github_acceptance import FailureLog

        self.logs_asked.append((repository, sha, tuple(run_ids)))
        return FailureLog(sha=sha, **self.logs.get(sha, {"problem": "the fake gate holds no log for this commit"}))

    def check(self, repository: str, sha: str) -> GateResult:
        self.asked.append((repository, sha))
        state = self.by_sha.get(sha, self.state)
        done = state in (GateState.GREEN, GateState.RED)
        runs = () if state in (GateState.MISSING, GateState.UNAVAILABLE) else (
            RunFact(id=4242, status="completed" if done else "in_progress",
                    conclusion={GateState.GREEN: "success",
                                GateState.RED: self.red_conclusion.get(sha, "failure")}.get(state)),)
        return GateResult(sha=sha, state=state, detail=f"fake gate says {state.value}", runs=runs)


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
                 worker_options: dict | None = None, **config) -> None:
        self.runner = runner or TreeRunnerForTests()
        self.worker_options = dict(worker_options or {})
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
        self.acceptance = FakeAcceptance()
        defaults = dict(runtime_root=tmp / "runtime", workspace_root=tmp / "workers", repo=self.repo,
                        heartbeat_interval_s=0, progress_interval_s=0, backoff_base_s=0, acceptance_poll_s=0)
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
        return Dispatcher(self.kernel, self.objectives, self.worker(), self.reviewers,
                          self.config, checks=self.runner, acceptance=self.acceptance)

    def worker(self) -> ClaudeCodeWorker:
        return ClaudeCodeWorker(cli=str(self.cli), **self.worker_options)

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

    @staticmethod
    def marker(attempt) -> str:
        return worker_marker(attempt.attempt_id, attempt.worker.session.session_id)

    def wait_started(self, n: int, timeout: float = 10.0) -> None:
        """Wait until the fake's invocation ``n`` runs its scenario, its SIGTERM handling already in place."""
        deadline = time.monotonic() + timeout
        while not (self.state / f"argv.{n}.json").exists():
            assert time.monotonic() < deadline, f"fake invocation {n} never started"
            time.sleep(0.02)

    def wait_logged(self, attempt, event_type: str, timeout: float = 10.0) -> None:
        """Wait until the attempt's stream log holds an event of ``event_type`` (``system``, ``result``...)."""
        log = self.config.runtime_root / "logs" / f"{attempt.attempt_id}.stream.jsonl"
        deadline = time.monotonic() + timeout
        while not (log.exists() and any(json.loads(line).get("type") == event_type
                                         for line in log.read_text().splitlines() if line.strip())):
            assert time.monotonic() < deadline, f"no {event_type} event in {log}"
            time.sleep(0.02)

    def kill_leftovers(self) -> None:
        """SIGKILL any fake worker of this world still alive, found on the host by its marker."""
        for attempt in self.store.read_attempts(OBJ):
            for pid in processes_with_marker(MARKER, self.marker(attempt)):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


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
    assert set(env) <= {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_ATTEMPT_ID", "DISABLE_AUTOUPDATER", "PWD", "SHLVL", "_", "LC_CTYPE"}
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
    # One builder, one attempt: the candidate's. Said outright rather than assumed by reading [0], so a wasted
    # attempt (a loaded root host lost one to the read-before-liveness race in ``_supervise``, now fixed) fails
    # here with its reason instead of as a missing evidence file of the wrong attempt.
    attempts = w.store.read_attempts(OBJ)
    cancelled = [e.note for a in attempts for e in w.store.read_events(OBJ, a.attempt_id)
                 if e.kind is EventKind.CANCELLED]
    assert len(attempts) == 1 and not cancelled, cancelled
    attempt = attempts[0]
    assert w.store.read_results()[0].attempt_id == attempt.attempt_id
    ws = tmp_path / "workers" / OBJ / attempt.attempt_id
    assert (ws / "pkg" / "hello.txt").read_text() == "hello\n" and not (ws / "uid.txt").exists()
    evidence = json.loads((tmp_path / "runtime" / "evidence" / attempt.attempt_id / "check-probe.json").read_text())
    assert evidence["runner"] == "linux-namespaces" and "canary held" in evidence["sandbox"]
    expected = "65534" if os.geteuid() == 0 else "0"
    assert evidence["stdout_tail"].strip() == expected
    assert w.store.read_results()[0].clean_worktree


class RacingWorker(ClaudeCodeWorker):
    """A worker that writes its result and exits in the instant between two of the dispatcher's looks.

    Until ``live_pids`` has been asked once after the result is in the log, ``read`` does not show the result
    (it was not there yet when the log was read); from that question on the worker counts as gone. A dispatcher
    that reads the log before asking whether the worker lives therefore sees it alive without a result, then
    dead without one; one that asks first sees it dead and then reads everything it wrote."""

    exited = False
    log_root: Path | None = None

    def _result_written(self, marker: str) -> bool:
        attempt = marker.split("/", 1)[0]
        logs = [p for p in Path(self.log_root).glob(f"{attempt}.stream.jsonl")] if self.log_root else []
        return any('"type": "result"' in p.read_text() for p in logs)

    def live_pids(self, marker: str) -> list[int]:
        if self.exited or self._result_written(marker):
            self.exited = True
            return []
        return super().live_pids(marker)

    def read(self, log_path: Path, offset: int = 0):
        observations, end = super().read(log_path, offset)
        if not self.exited:
            observations = [o for o in observations if not isinstance(o, Finished)]
        return observations, end


def test_a_worker_that_reports_and_exits_between_two_looks_is_ingested_not_cancelled(tmp_path):
    """PR #63's ``_supervise`` race: the log was read before the liveness check, so a builder that wrote its result
    and exited in between lost its attempt as a transient death and was built again."""
    w = World(tmp_path)
    # The result comes a second after the init, so it lands while the attempt is RUNNING, between two ticks.
    w.scenarios({**EDIT_HELLO, "sleep_before_result": 1, "sleep_after_result": 60}, EDIT_HELLO)
    racing = RacingWorker(cli=str(w.cli))
    racing.log_root = tmp_path / "runtime" / "logs"
    w.worker = lambda: racing
    w.objective()
    try:
        w.run_until(w.status_is(TaskStatus.REVIEWING, TaskStatus.BLOCKED))
        attempts = w.store.read_attempts(OBJ)
        cancelled = [e.note for e in w.store.read_events(OBJ, attempts[0].attempt_id) if e.kind is EventKind.CANCELLED]
        assert racing.exited and not cancelled, cancelled
        assert len(attempts) == 1 and w.state_of().status is TaskStatus.REVIEWING
        assert w.store.read_results()[0].attempt_id == attempts[0].attempt_id and w.invocations() == 1
    finally:
        w.kill_leftovers()


class SandboxShapedTreeRunner(NamespaceSandbox):
    """The dispatcher's runner type (so the builder gets run_checks) with the test double's behaviour."""

    def availability(self):
        return True, "test double: no isolation"

    def run(self, argv, *, tree, cwd, timeout_s):
        return TreeRunnerForTests().run(argv, tree=tree, cwd=cwd, timeout_s=timeout_s)


RUN_CHECKS_LINE = "run_checks runs your objective's listed checks in your workspace; use it before you report."


def test_a_builder_with_declared_checks_gets_run_checks_bound_to_exactly_those_checks(tmp_path):
    check = Check(name="hello", argv=("grep", "-qx", "hello", "pkg/hello.txt"), timeout_s=45)
    w = World(tmp_path, checks=(check,), runner=SandboxShapedTreeRunner(ro_paths=(str(tmp_path),)))
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    attempt = w.store.read_attempts(OBJ)[0]
    argv = json.loads((w.state / "argv.0.json").read_text())
    servers = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
    assert list(servers) == ["clive_checks"]
    config_path = Path(servers["clive_checks"]["args"][-1])
    assert config_path == tmp_path / "runtime" / "checks" / attempt.attempt_id / "_builder" / "config.json"
    assert oct(config_path.stat().st_mode & 0o777) == "0o600"
    config = json.loads(config_path.read_text())
    assert config["checks"] == [{"name": "hello", "argv": ["grep", "-qx", "hello", "pkg/hello.txt"], "cwd": ".",
                                 "timeout_s": 45}]
    assert config["workspace"] == str(tmp_path / "workers" / OBJ / attempt.attempt_id)
    assert config["sandbox"]["ro_paths"] == [str(tmp_path)]
    assert "mcp__clive_checks__run_checks" in argv
    assert RUN_CHECKS_LINE in (w.state / "prompt.0.txt").read_text()
    # the builder's tool is advisory: the dispatcher ran the check itself, and that run is the evidence
    evidence = json.loads((tmp_path / "runtime" / "evidence" / attempt.attempt_id / "check-hello.json").read_text())
    assert evidence["exit_code"] == 0 and evidence["head"] == w.store.read_results()[0].result_sha


def test_a_builder_reporting_success_is_still_refused_when_the_dispatchers_own_check_fails(tmp_path):
    check = Check(name="hello", argv=("grep", "-qx", "hello", "pkg/hello.txt"))
    w = World(tmp_path, checks=(check,), runner=SandboxShapedTreeRunner())
    w.scenarios({"edits": [["pkg/hello.txt", "not hello\n"]],
                 "report": {"status": "completed", "summary": "run_checks passed, all green"}}, EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    first, second = w.store.read_attempts(OBJ)
    first_events = w.store.read_events(OBJ, first.attempt_id)
    assert "checks failed" in [e.note for e in first_events if e.kind is EventKind.CANCELLED][0]
    assert w.store.read_results()[0].attempt_id == second.attempt_id


def test_without_the_namespace_sandbox_or_declared_checks_there_is_no_run_checks(tmp_path):
    w = World(tmp_path, checks=(Check(name="c", argv=("true",)),))  # the test double is not the sandbox
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(lambda: w.invocations() >= 1 and (w.state / "argv.0.json").exists())
    argv = json.loads((w.state / "argv.0.json").read_text())
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert RUN_CHECKS_LINE not in (w.state / "prompt.0.txt").read_text()


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
    d = Dispatcher(w.kernel, w.objectives, ClaudeCodeWorker(cli=str(w.cli)), w.reviewers, w.config, checks=runner,
                   acceptance=w.acceptance)
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


# ---------------------------------------------------------------- the GitHub acceptance gate (owner's loop update)

def _candidate(w: World):
    [result] = [r for r in w.store.read_results() if r.task_id == OBJ]
    return result


def latest_attempt(w: World):
    """The attempt that carries the candidate: on a loaded host the harness may have retried one first."""
    return max(w.store.read_attempts(OBJ), key=lambda a: a.fencing_token)


def test_review_is_dispatched_only_once_github_acceptance_is_green_on_the_exact_candidate(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.acceptance.state = GateState.PENDING
    w.run_until(w.status_is(TaskStatus.EVIDENCE_READY))
    sha = _candidate(w).result_sha
    lines = w.dispatcher().tick()
    attempt = latest_attempt(w)
    assert w.state_of().status is TaskStatus.EVIDENCE_READY
    assert not w.store.read_dispatches(OBJ, attempt.attempt_id)
    assert any(f"review dispatch waits for a green GitHub acceptance run on {sha} (pending" in line for line in lines)
    assert set(w.acceptance.asked) == {("crooksldn-pixel/clive", sha)}   # the objective's repository, the exact SHA
    # the answer and the SHA it is about are recorded, as execution notes and as an evidence file
    notes = json.loads((tmp_path / "runtime" / "attempts" / f"{attempt.attempt_id}.json").read_text())
    evidence = json.loads((tmp_path / "runtime" / "evidence" / attempt.attempt_id / "github-acceptance.json").read_text())
    assert notes["github_acceptance"] == evidence
    assert evidence["sha"] == sha and evidence["state"] == "pending" and evidence["green"] is False
    assert w.dispatcher().status()[0]["github_acceptance"]["state"] == "pending"

    w.acceptance.state = GateState.GREEN
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    packet = (w.store.root / w.store.read_dispatches(OBJ, attempt.attempt_id)[-1].packet_path).read_text()
    assert "## GitHub acceptance on this exact SHA" in packet and f'"sha": "{sha}"' in packet
    assert '"state": "green"' in packet
    w.reviewer.answers.append(lambda ctx: review(ctx))
    w.run_until(lambda: w.stage() == "COMPLETE")


def test_a_review_is_dispatched_only_on_a_green_answer_asked_at_that_moment(tmp_path):
    """The 2026-09-30 re-pin review, F-01: a green answer remembered from a tick whose dispatch the kernel
    refused (the target ref no longer matched) must not start a review once the run has gone red inside the
    poll interval.

    Since the owner's "go" of 30 September (OWNER_DECISIONS_2026-09-30: a red GitHub run is a repair round, not
    a block), red at review dispatch routes a repair revision while repair rounds remain; with none left
    (``max_repair_rounds=0`` here) it blocks as it always did, which is what this test pins."""
    w = World(tmp_path, acceptance_poll_s=60, max_repair_rounds=0)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.acceptance.state = GateState.PENDING
    w.run_until(w.status_is(TaskStatus.EVIDENCE_READY))
    attempt = latest_attempt(w)
    d = w.dispatcher()
    real = w.kernel.dispatch_review

    def target_moved(*args, **kwargs):
        raise LifecycleError("the target ref no longer matches the candidate")

    w.acceptance.state = GateState.GREEN
    w.clock.offset = timedelta(seconds=61)              # past the interval: GitHub is asked, and says green
    w.kernel.dispatch_review = target_moved
    lines = d.tick()
    assert any("kernel refused (evidence_ready)" in line for line in lines)
    assert w.state_of().status is TaskStatus.EVIDENCE_READY and not w.store.read_dispatches(OBJ, attempt.attempt_id)
    notes = json.loads((tmp_path / "runtime" / "attempts" / f"{attempt.attempt_id}.json").read_text())
    assert notes["github_acceptance"]["green"] is True   # the green answer is remembered...

    w.kernel.dispatch_review = real                      # ...the ref is put right...
    w.acceptance.state = GateState.RED                   # ...and a re-run goes red, all inside the interval
    w.clock.offset = timedelta(seconds=70)
    asked = len(w.acceptance.asked)
    d.tick()
    assert len(w.acceptance.asked) == asked + 1          # asked again, not the remembered green
    assert not w.store.read_dispatches(OBJ, attempt.attempt_id)
    state = w.state_of()
    assert state.status is TaskStatus.BLOCKED and "review dispatch refused" in state.blocker_reason


def test_a_red_candidate_blocks_before_review_and_is_resumable_once_green(tmp_path):
    """Red at review dispatch blocks once the objective has no repair round left. Before the owner's "go" of 30
    September it blocked at once whatever the rounds; since then (OWNER_DECISIONS_2026-09-30: a red GitHub run is a
    repair round) a red run with rounds left routes a repair (``test_red_github_becomes_a_repair_revision...``), so
    this test pins the block with ``max_repair_rounds=0``, and everything it asserted still holds."""
    w = World(tmp_path, max_repair_rounds=0)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.acceptance.state = GateState.RED
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    sha = _candidate(w).result_sha
    attempt = latest_attempt(w)
    reason = w.state_of().blocker_reason
    assert f"GitHub acceptance is red on {sha}" in reason and "review dispatch refused" in reason
    assert not w.store.read_dispatches(OBJ, attempt.attempt_id) and not w.store.read_acceptances(OBJ)
    for _ in range(2):                      # the dispatcher never lifts its own blocker
        w.dispatcher().tick()
    assert w.state_of().status is TaskStatus.BLOCKED
    # a green re-run of the same SHA, then the Director's resume: the same candidate goes on to review
    w.acceptance.state = GateState.GREEN
    w.kernel.resume(OBJ, 1, note="acceptance re-run is green")
    w.reviewer.answers.append(lambda ctx: review(ctx))
    w.run_until(lambda: w.stage() == "COMPLETE")
    assert w.store.read_acceptances(OBJ)[0].accepted_sha == sha


# ---------------------------------------------- a red run is a repair round (OWNER_DECISIONS_2026-09-30, "go")

def _red_log(token: str, secret: str) -> str:
    """A failed acceptance job's log as GitHub serves it: timestamps, colours, pytest's failures and summary."""
    stamp = "2026-09-30T12:00:00.1234567Z "
    lines = [f"{stamp}##[group]Run the acceptance tests", f"{stamp}collected 912 items"]
    lines += [f"{stamp}tests/test_filler_{n}.py ........................................ [ {n}%]" for n in range(150)]
    lines += [
        f"{stamp}\x1b[31m___ test_the_checked_in_document_is_the_generated_one ___\x1b[0m",
        f"{stamp}    def test_the_checked_in_document_is_the_generated_one():",
        f"{stamp}>       assert DOC.read_text() == tool_matrix.markdown()",
        f"{stamp}E       AssertionError: docs/phase4/TOOL_MATRIX.md is out of date; run make tool-matrix",
        f"{stamp}E       assert 'old' == 'new'",
        f"{stamp}GH_TOKEN={token} leaked by a test that printed its environment",
        f"{stamp}fatal: unable to access 'https://bot:{secret}@github.com/o/r.git/'",
        f"{stamp}=========================== short test summary info ============================",
        f"{stamp}FAILED tests/test_tool_matrix.py::test_the_checked_in_document_is_the_generated_one - AssertionError",
        f"{stamp}ERROR tests/test_broken_import.py - ModuleNotFoundError: No module named 'nothing'",
        f"{stamp}1 failed, 910 passed, 1 error in 61.02s",
        f"{stamp}##[error]Process completed with exit code 1.",
    ]
    return "\n".join(lines) + "\n"


def _red_then_green(w: World) -> str:
    """The first candidate is red on GitHub (with a log); every later SHA is green. Returns the red SHA."""
    w.acceptance.state = GateState.PENDING
    w.run_until(w.status_is(TaskStatus.EVIDENCE_READY))
    sha = _candidate(w).result_sha
    w.acceptance.by_sha[sha] = GateState.RED
    w.acceptance.state = GateState.GREEN
    return sha


def test_red_github_becomes_a_repair_revision_whose_prompt_carries_the_failure_redacted(tmp_path):
    from tests.fake_credentials import github_token, password

    token, secret = github_token("red-run-log"), password("red-run-log")
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO, {"edits": [["pkg/hello.txt", "hello, again\n"]]})
    w.objective()
    red = _red_then_green(w)
    w.acceptance.logs[red] = {"run_id": 4242, "job_id": 77, "job_name": "acceptance",
                              "failed_steps": ("Run the acceptance tests",), "text": _red_log(token, secret)}
    w.run_until(lambda: w.state_of().task_revision == 2 and w.invocations() >= 2)
    r1, r2 = sorted((t for t in w.store.read_tasks() if t.task_id == OBJ), key=lambda t: t.revision)
    assert r2.kind is TaskKind.REPAIR and r2.base_sha == r1.base_sha and red in r2.objective
    assert r2.authorising_reference.startswith(f"GitHub acceptance red on {red}")
    assert w.store.read_task_state(OBJ, 1).status is TaskStatus.OBSOLETE
    a1 = w.store.read_attempts(OBJ)[0]
    assert not w.store.read_dispatches(OBJ, a1.attempt_id)             # nothing red was ever reviewed
    assert w.acceptance.logs_asked == [("crooksldn-pixel/clive", red, (4242,))]

    prompt = (w.state / "prompt.1.txt").read_text()
    assert "REPAIR OF A RED GITHUB ACCEPTANCE RUN" in prompt and red in prompt
    assert "- FAILED tests/test_tool_matrix.py::test_the_checked_in_document_is_the_generated_one" in prompt
    assert "- ERROR tests/test_broken_import.py - ModuleNotFoundError" in prompt
    assert "E       AssertionError: docs/phase4/TOOL_MATRIX.md is out of date" in prompt
    assert "Run: https://github.com/crooksldn-pixel/clive/actions/runs/4242" in prompt
    assert "Failed job: acceptance (https://github.com/crooksldn-pixel/clive/actions/runs/4242/job/77)" in prompt
    assert "Failed step(s): Run the acceptance tests" in prompt
    assert "do not report owner_decision_required" in prompt and "nobody re-runs the red one" in prompt
    assert token not in prompt and secret not in prompt and "[redacted]" in prompt
    assert "\x1b[" not in prompt and "2026-09-30T12:00:00" not in prompt
    tail = prompt.split("LAST OUTPUT OF THE FAILED JOB")[1].split("```")[1]
    assert len(tail.strip()) <= 4000 and "Process completed with exit code 1." in tail
    assert "test_filler_0.py" not in tail                              # the tail, not the whole log
    # the repair starts at the red SHA and is a new SHA of its own
    evidence = json.loads((tmp_path / "runtime" / "evidence" / a1.attempt_id / "github-failure.json").read_text())
    assert evidence["sha"] == red and evidence["failing_tests"][0].startswith("tests/test_tool_matrix.py::")
    assert token not in json.dumps(evidence) and secret not in json.dumps(evidence)
    w.reviewer.answers.append(lambda ctx: review(ctx))
    w.run_until(lambda: w.stage() == "COMPLETE")
    repaired = next(r for r in w.store.read_results() if r.task_revision == 2).result_sha
    assert repaired != red and _git(w.repo, "merge-base", "--is-ancestor", red, repaired) == ""
    item = w.dispatcher().status()[0]
    assert item["repairs"] == {"review": 0, "ci": 1, "max": 2}
    assert [(a["revision"], a["outcome"]) for a in item["attempts"]] == [(1, "blocked"), (2, "candidate")]
    assert item["attempts"][0]["reason"].startswith("red GitHub acceptance, repair routed:")
    a2 = next(a for a in w.store.read_attempts(OBJ) if a.task_revision == 2)
    packet = (w.store.root / w.store.read_dispatches(OBJ, a2.attempt_id)[-1].packet_path).read_text()
    assert "## Red GitHub acceptance runs of earlier revisions" in packet and red in packet
    assert token not in json.dumps(item, default=str)


def test_red_repairs_stop_at_max_repair_rounds_then_block_with_the_last_failure(tmp_path):
    w = World(tmp_path, max_repair_rounds=1)
    w.scenarios(EDIT_HELLO, {"edits": [["pkg/hello.txt", "hello, again\n"]]})
    w.acceptance.state = GateState.RED
    w.objective()
    log = {"run_id": 4242, "job_id": 77, "job_name": "acceptance", "text": _red_log("t", "s")}
    real = w.acceptance.failure_log
    w.acceptance.failure_log = lambda repository, sha, run_ids: (w.acceptance.logs.setdefault(sha, log),
                                                                real(repository, sha, run_ids))[1]
    w.run_until(lambda: w.state_of().status is TaskStatus.BLOCKED and w.state_of().task_revision == 2, timeout=30)
    state = w.state_of()
    second = next(r for r in w.store.read_results() if r.task_revision == 2).result_sha
    assert f"GitHub acceptance is red on {second}" in state.blocker_reason
    assert "1 of 1 repair round(s) are used, so no repair is routed" in state.blocker_reason
    assert "last failure: failing: tests/test_tool_matrix.py::test_the_checked_in_document_is_the_generated_one" \
        in state.blocker_reason
    assert state.blocker_class is BlockerClass.DETERMINISTIC and not state.owner_gate    # never an owner decision
    assert w.invocations() == 2 and len([t for t in w.store.read_tasks() if t.task_id == OBJ]) == 2
    for _ in range(2):
        w.dispatcher().tick()
    assert w.state_of() == state                                         # the dispatcher never lifts it
    assert w.dispatcher().status()[0]["repairs"] == {"review": 0, "ci": 1, "max": 1}


def test_review_and_red_repairs_share_the_rounds(tmp_path):
    w = World(tmp_path, max_repair_rounds=1)
    w.scenarios({"edits": [["pkg/hello.txt", "bye\n"]]}, EDIT_HELLO)
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[FINDING]))
    w.acceptance.state = GateState.PENDING
    w.run_until(w.status_is(TaskStatus.EVIDENCE_READY))
    w.acceptance.by_sha[_candidate(w).result_sha] = GateState.GREEN     # the first candidate is reviewed...
    w.acceptance.state = GateState.RED                                  # ...and its review repair is red on GitHub
    w.run_until(lambda: w.state_of().status is TaskStatus.BLOCKED and w.state_of().task_revision == 2)
    assert "1 of 1 repair round(s) are used" in w.state_of().blocker_reason
    assert w.dispatcher().status()[0]["repairs"] == {"review": 1, "ci": 0, "max": 1}


class GateWithoutLogs(FakeAcceptance):
    """A gate that answers ``check`` and cannot read job logs at all."""

    failure_log = None


@pytest.mark.parametrize("gate", ["no-log", "no-reader"])
def test_a_red_run_whose_log_cannot_be_fetched_still_repairs_and_says_so(tmp_path, gate):
    w = World(tmp_path)
    if gate == "no-reader":
        w.acceptance = GateWithoutLogs()
    w.scenarios(EDIT_HELLO, {"edits": [["pkg/hello.txt", "hello, again\n"]]})
    w.objective()
    red = _red_then_green(w)
    if gate == "no-log":
        w.acceptance.logs[red] = {"run_id": 4242, "job_id": 77, "job_name": "acceptance",
                                  "failed_steps": ("Run the acceptance tests",),
                                  "problem": "GitHub could not give the job log (HTTP 404)"}
    w.run_until(lambda: w.state_of().task_revision == 2 and w.invocations() >= 2)
    prompt = (w.state / "prompt.1.txt").read_text()
    assert "REPAIR OF A RED GITHUB ACCEPTANCE RUN" in prompt and "The failed job's log could not be fetched" in prompt
    assert "Run: https://github.com/crooksldn-pixel/clive/actions/runs/4242" in prompt
    if gate == "no-log":
        assert "(GitHub could not give the job log (HTTP 404))" in prompt
        assert "Failed job: acceptance" in prompt and "Failed step(s): Run the acceptance tests" in prompt
    else:
        assert "this acceptance gate cannot read job logs" in prompt
    r2 = w.store.read_task(OBJ, 2)
    assert r2.kind is TaskKind.REPAIR and "its log could not be fetched" in r2.objective


@pytest.mark.parametrize("conclusion", ["cancelled", "startup_failure", "stale"])
def test_a_red_run_that_failed_no_test_blocks_without_spending_a_repair_round(tmp_path, conclusion):
    """A run GitHub cancelled, never started or let go stale is red, but nothing in the candidate failed: no
    builder is sent to fix it and no repair round is spent. It blocks as a red run always did (the #70
    pre-review)."""
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO, {"edits": [["pkg/hello.txt", "hello, again\n"]]})
    w.objective()
    red = _red_then_green(w)
    w.acceptance.red_conclusion[red] = conclusion
    w.run_until(lambda: w.state_of().status is TaskStatus.BLOCKED)
    state = w.state_of()
    assert state.task_revision == 1 and f"GitHub acceptance is red on {red}" in state.blocker_reason
    assert "No repair is routed: no run failed its tests" in state.blocker_reason
    assert not state.blocker_reason.startswith("red GitHub acceptance, repair routed:")
    assert [t.revision for t in w.store.read_tasks() if t.task_id == OBJ] == [1] and w.invocations() == 1
    assert w.acceptance.logs_asked == []                                  # no failure to read, no builder to brief
    assert w.dispatcher().status()[0]["repairs"] == {"review": 0, "ci": 0, "max": 2}


def test_a_remembered_red_is_asked_again_before_it_routes_a_repair(tmp_path):
    """A red answer authorises a repair round only when asked at that moment: after a restart inside the poll
    interval, a run re-run green since is seen and the candidate goes to review instead (the #70 pre-review)."""
    from dataclasses import replace

    w = World(tmp_path)
    w.scenarios(EDIT_HELLO, {"edits": [["pkg/hello.txt", "hello, again\n"]]})
    w.objective()
    red = _red_then_green(w)
    d = w.dispatcher()

    def crash(*args, **kwargs):
        raise RuntimeError("the host lost power while reading the red run")

    d._github_failure = crash
    with pytest.raises(RuntimeError, match="red run"):
        w.run_until(lambda: False, dispatcher=d)
    assert GateResult.from_record(json.loads(
        (w.config.runtime_root / "attempts" / f"{_candidate(w).attempt_id}.json").read_text())["github_acceptance"]
    ).state is GateState.RED                                                 # the red answer is remembered...
    w.config = replace(w.config, acceptance_poll_s=3600)                     # ...and would be kept an hour
    w.acceptance.by_sha[red] = GateState.GREEN                               # someone re-ran it: green now
    asked = len(w.acceptance.asked)
    w.reviewer.answers.append(lambda ctx: review(ctx))
    w.run_until(lambda: w.stage() == "COMPLETE")
    assert len(w.acceptance.asked) > asked
    assert [t.revision for t in w.store.read_tasks() if t.task_id == OBJ] == [1]     # no repair was routed
    assert w.dispatcher().status()[0]["repairs"]["ci"] == 0


def test_a_restart_between_the_red_block_and_the_repair_revision_completes_the_repair(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO, {"edits": [["pkg/hello.txt", "hello, again\n"]]})
    w.objective()
    _red_then_green(w)
    d = w.dispatcher()

    def crash(*args, **kwargs):
        raise RuntimeError("the host lost power between the block and the repair")

    d._route_red_repair = crash
    with pytest.raises(RuntimeError):
        d.tick()
    assert w.state_of().status is TaskStatus.BLOCKED and w.state_of().task_revision == 1
    w.run_until(lambda: w.state_of().task_revision == 2)                # a fresh dispatcher completes it
    assert w.store.read_task(OBJ, 2).kind is TaskKind.REPAIR
    assert len([t for t in w.store.read_tasks() if t.task_id == OBJ]) == 2


def test_red_at_integration_and_at_a_ready_verdict_still_refuses_with_repair_rounds_left(tmp_path):
    """Only review dispatch turns red into a repair (OWNER_DECISIONS_2026-09-30); a READY verdict and an integration
    still ask afresh and refuse red, exactly as before, whatever rounds remain."""
    w = World(tmp_path, max_repair_rounds=2)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    w.reviewer.answers.append(lambda ctx: review(ctx))
    d = w.dispatcher()
    original = d._integrate

    def red_before_integration(obj, task, state_):
        w.acceptance.state = GateState.RED
        d._integrate = original
        return original(obj, task, state_)

    d._integrate = red_before_integration
    w.run_until(w.status_is(TaskStatus.BLOCKED), dispatcher=d)
    assert "integration refused" in w.state_of().blocker_reason and not w.store.read_integrations()
    assert len([t for t in w.store.read_tasks() if t.task_id == OBJ]) == 1          # no repair was routed
    assert w.dispatcher().status()[0]["repairs"] == {"review": 0, "ci": 0, "max": 2}

    (tmp_path / "ready").mkdir()
    v = World(tmp_path / "ready", max_repair_rounds=2)
    v.scenarios(EDIT_HELLO)
    v.objective()
    v.run_until(v.status_is(TaskStatus.REVIEWING))
    v.acceptance.state = GateState.RED
    v.reviewer.answers.append(lambda ctx: review(ctx, "READY"))
    v.run_until(v.status_is(TaskStatus.BLOCKED))
    assert "accepting a READY verdict refused" in v.state_of().blocker_reason
    assert len([t for t in v.store.read_tasks() if t.task_id == OBJ]) == 1


def test_the_failure_summary_is_redacted_and_bounded():
    from app.orchestrator.dispatcher import summarise_failure_log
    from tests.fake_credentials import github_token

    token = github_token("summary")
    text = "\n".join([f"line {n}" for n in range(5000)] + [f"FAILED tests/test_x.py::test_{n} - {token}"
                                                             for n in range(50)] + ["E       " + "y" * 1000])
    parts = summarise_failure_log(text)
    assert len(parts["tail"]) <= 4000 and not parts["tail"].startswith("ine")
    assert len(parts["short_summary"]) <= 30 and len(parts["failing_tests"]) == 30
    assert all(len(line) <= 300 for line in parts["short_summary"] + parts["assertions"])
    assert token not in json.dumps(parts)


@pytest.mark.parametrize("state", [GateState.MISSING, GateState.PENDING, GateState.UNAVAILABLE])
def test_waiting_for_github_is_bounded_then_blocks_and_a_resume_waits_again(tmp_path, state):
    w = World(tmp_path, acceptance_timeout_s=600)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.acceptance.state = state
    w.run_until(w.status_is(TaskStatus.EVIDENCE_READY))
    sha = _candidate(w).result_sha
    w.clock.offset += timedelta(seconds=590)
    w.dispatcher().tick()
    assert w.state_of().status is TaskStatus.EVIDENCE_READY          # still inside the bound
    w.clock.offset += timedelta(seconds=20)
    w.dispatcher().tick()
    reason = w.state_of().blocker_reason
    assert w.state_of().status is TaskStatus.BLOCKED
    assert f"GitHub acceptance on {sha} was not green within 600s ({state.value}:" in reason
    w.kernel.resume(OBJ, 1, note="wait again")
    w.dispatcher().tick()
    assert w.state_of().status is TaskStatus.EVIDENCE_READY          # the bound restarts at the resume
    w.acceptance.state = GateState.GREEN
    w.run_until(w.status_is(TaskStatus.REVIEWING))


def test_each_gate_waits_its_own_bound_so_a_slow_review_does_not_use_it_up(tmp_path):
    w = World(tmp_path, acceptance_timeout_s=600)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))                  # green when review was dispatched
    w.clock.offset += timedelta(hours=2)                            # a slow reviewer
    w.acceptance.state = GateState.UNAVAILABLE                      # and GitHub blips as its READY arrives
    w.reviewer.answers.append(lambda ctx: review(ctx))
    w.dispatcher().tick()
    assert w.state_of().status is TaskStatus.REVIEWING              # waiting, not timed out by the review
    w.clock.offset += timedelta(seconds=601)
    w.dispatcher().tick()
    assert w.state_of().status is TaskStatus.BLOCKED
    assert "accepting a READY verdict refused" in w.state_of().blocker_reason
    assert not w.store.read_acceptances(OBJ)


def test_github_is_asked_about_a_sha_at_most_once_per_poll_interval(tmp_path):
    w = World(tmp_path, acceptance_poll_s=300, acceptance_timeout_s=7200)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.acceptance.state = GateState.PENDING
    w.run_until(w.status_is(TaskStatus.EVIDENCE_READY))
    for _ in range(3):
        w.dispatcher().tick()                                      # fresh dispatchers: the bound is on disk
    assert len(w.acceptance.asked) == 1
    w.clock.offset += timedelta(seconds=301)
    w.dispatcher().tick()
    assert len(w.acceptance.asked) == 2
    # a remembered answer never outlives a resume: the resumed task asks again at once
    w.kernel.block(OBJ, 1, blocker_class=BlockerClass.DETERMINISTIC, reason="held by a test")
    w.kernel.resume(OBJ, 1, note="resumed by a test")
    w.acceptance.state = GateState.GREEN
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    assert len(w.acceptance.asked) == 3


def test_a_ready_verdict_waits_unconsumed_until_the_candidate_is_green(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))                  # green when review was dispatched
    sha = _candidate(w).result_sha
    attempt = latest_attempt(w)
    w.acceptance.state = GateState.PENDING                          # e.g. a re-run started on the same SHA
    w.reviewer.answers.append(lambda ctx: review(ctx, "READY"))
    lines = w.dispatcher().tick()
    assert any(f"accepting a READY verdict waits for a green GitHub acceptance run on {sha}" in line for line in lines)
    assert w.state_of().status is TaskStatus.REVIEWING
    assert not w.store.read_admissions(OBJ, attempt.attempt_id) and not w.store.read_acceptances(OBJ)
    w.acceptance.state = GateState.GREEN
    w.run_until(lambda: w.stage() == "COMPLETE")
    assert [a.outcome for a in w.store.read_admissions(OBJ, attempt.attempt_id)] == [VerdictOutcome.ACCEPTED]


def test_a_ready_verdict_on_a_red_candidate_blocks_and_records_no_acceptance(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    w.acceptance.state = GateState.RED
    w.reviewer.answers.append(lambda ctx: review(ctx, "READY"))
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert "accepting a READY verdict refused" in w.state_of().blocker_reason
    assert not w.store.read_acceptances(OBJ) and not w.store.read_integrations()



# ---------------------------------------------- the 2026-09-26 re-pin review: F-01 and F-03

def _script(w: World, *answers: GateState, then: GateState) -> None:
    """GitHub answers ``answers`` in order, one per question, then ``then`` for every later question."""
    queue = list(answers)
    real = w.acceptance.check

    def check(repository: str, sha: str) -> GateResult:
        w.acceptance.state = queue.pop(0) if queue else then
        return real(repository, sha)

    w.acceptance.check = check


@pytest.mark.parametrize("change", [GateState.RED, GateState.PENDING, GateState.UNAVAILABLE])
def test_a_green_answer_inside_the_poll_interval_never_admits_a_ready_verdict(tmp_path, change):
    """F-01: the green answer that let review be dispatched is not reused when the READY arrives; GitHub is
    asked again at that moment, and a re-run or an outage inside the interval holds the acceptance."""
    w = World(tmp_path, acceptance_poll_s=300, acceptance_timeout_s=7200)
    _script(w, GateState.GREEN, then=change)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))                  # green when review was dispatched
    asked = len(w.acceptance.asked)
    w.reviewer.answers.append(lambda ctx: review(ctx, "READY"))
    w.dispatcher().tick()                                           # well inside the 300 s interval
    assert len(w.acceptance.asked) == asked + 1                     # asked afresh, not the remembered green
    assert not w.store.read_acceptances(OBJ)
    if change is GateState.RED:
        assert w.state_of().status is TaskStatus.BLOCKED
        assert "accepting a READY verdict refused" in w.state_of().blocker_reason
    else:
        assert w.state_of().status is TaskStatus.REVIEWING
        w.dispatcher().tick()                                       # a remembered non-green answer is reused
        assert len(w.acceptance.asked) == asked + 1 and not w.store.read_acceptances(OBJ)


@pytest.mark.parametrize("change", [GateState.RED, GateState.PENDING, GateState.UNAVAILABLE])
def test_a_green_answer_inside_the_poll_interval_never_lands_an_integration(tmp_path, change):
    """F-01: the green answer the acceptance rested on is not reused to integrate; GitHub is asked again."""
    w = World(tmp_path, acceptance_poll_s=300, acceptance_timeout_s=7200)
    _script(w, GateState.GREEN, GateState.GREEN, then=change)       # review dispatch, READY, then integration
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    w.reviewer.answers.append(lambda ctx: review(ctx))
    w.run_until(lambda: bool(w.store.read_acceptances(OBJ)) and len(w.acceptance.asked) >= 3)
    for _ in range(3):
        w.dispatcher().tick()
    assert not w.store.read_integrations()
    assert w.stage() != "COMPLETE"
    if change is GateState.RED:
        assert "integration refused" in w.state_of().blocker_reason
    else:
        w.acceptance.check = FakeAcceptance(GateState.GREEN).check  # GitHub is green again
        w.clock.offset += timedelta(seconds=301)
        w.run_until(lambda: w.stage() == "COMPLETE")
        assert len(w.store.read_integrations()) == 1


def test_git_error_text_is_redacted_before_it_becomes_a_reason():
    from app.orchestrator.dispatcher import MAX_GIT_ERROR, safe_git_error
    from tests.fake_credentials import github_token, password

    token, secret = github_token("push-error"), password("push-error")
    text = safe_git_error(
        f"fatal: unable to access 'https://x-access-token:{token}@github.com/o/r.git/': 403\n"
        f"fatal: could not read from https://bot:{secret}@example.com/r.git\nremote: token {token}\n"
        + "x" * 1000)
    assert token not in text and secret not in text and secret[:6] not in text
    assert "https://[redacted]@github.com/o/r.git/" in text and "\n" not in text
    assert len(text) == MAX_GIT_ERROR
    # redaction happens before the cut, so a cut can never leave a secret's head behind
    head = safe_git_error("x" * (MAX_GIT_ERROR - 10) + f" https://u:{secret}@h/r")
    assert secret[:4] not in head
    assert safe_git_error("") == "git gave no error text"


def test_a_failed_candidate_push_blocks_without_git_error_credentials_in_the_store_or_status(tmp_path, monkeypatch):
    """F-03: a failed push's stderr can name an authenticated remote URL; the blocker reason, which the store
    keeps and the status projection publishes, carries it redacted."""
    from app.orchestrator import dispatcher as dispatcher_module
    from tests.fake_credentials import github_token

    token = github_token("failed-push")
    real_run = dispatcher_module.subprocess.run

    def run(argv, *args, **kwargs):
        if list(argv[:2]) == ["git", "push"]:
            return subprocess.CompletedProcess(argv, 128, "", f"fatal: unable to access 'https://x-access-token:"
                                                            f"{token}@github.com/o/r.git/': 403 {token}\n")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(dispatcher_module.subprocess, "run", run)
    w = World(tmp_path, publish_remote="origin")
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    reason = w.state_of().blocker_reason
    assert reason.startswith("publishing ") and "failed:" in reason and "[redacted]" in reason
    assert token not in reason
    assert token not in json.dumps(w.dispatcher().status(), default=str)
    assert not any(token in path.read_text(errors="replace") for path in w.store.root.rglob("*") if path.is_file())

def test_a_rejection_is_admitted_without_waiting_for_github(tmp_path):
    w = World(tmp_path)
    w.scenarios({"edits": [["pkg/hello.txt", "bye\n"]]}, EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    w.acceptance.state = GateState.PENDING
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[FINDING]))
    # the repair revision is routed at once; only its own candidate then waits for GitHub
    w.run_until(lambda: w.state_of().task_revision == 2 and w.state_of().status is TaskStatus.EVIDENCE_READY)
    assert w.store.read_task_state(OBJ, 1).status is TaskStatus.OBSOLETE and not w.store.read_acceptances(OBJ)


@pytest.mark.parametrize("state", [GateState.PENDING, GateState.RED])
def test_integration_lands_only_a_green_accepted_sha_and_keeps_the_answer_as_gates_evidence(tmp_path, state):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    w.reviewer.answers.append(lambda ctx: review(ctx))
    d = w.dispatcher()
    original = d._integrate

    def turns_before_integration(obj, task, state_):
        # An acceptance recorded before this gate existed, or a re-run gone red: integration is held.
        w.acceptance.state = state
        d._integrate = original
        return original(obj, task, state_)

    d._integrate = turns_before_integration
    d.tick()
    assert not w.store.read_integrations() and w.store.read_acceptances(OBJ)
    expected = TaskStatus.ACCEPTED if state is GateState.PENDING else TaskStatus.BLOCKED
    assert w.state_of().status is expected
    w.acceptance.state = GateState.GREEN
    if state is GateState.RED:
        assert "integration refused" in w.state_of().blocker_reason
        w.kernel.resume(OBJ, 1, note="re-run is green")
    w.run_until(lambda: w.stage() == "COMPLETE", dispatcher=d)
    integration = w.store.read_integrations()[0]
    attempt = latest_attempt(w)
    evidence = tmp_path / "runtime" / "evidence" / attempt.attempt_id
    record = json.loads((evidence / "github-acceptance.json").read_text())
    assert record["green"] is True and record["sha"] == integration.integration_sha == integration.accepted_sha
    assert integration.method.value == "fast_forward"
    kept = (evidence / "integration-gates.json").read_bytes()      # the gates evidence, byte for byte
    assert integration.gates_evidence_sha256 == sha256_of(kept)
    document = json.loads(kept)
    assert document["schema"] == "clive.integration_gates.v1" and document["github_acceptance"] == [record]
    assert document["operator_gates_evidence_sha256"] is None


def test_without_a_configured_gate_nothing_is_reviewed_or_accepted(tmp_path):
    w = World(tmp_path)
    w.acceptance = None
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    attempt = latest_attempt(w)
    assert "no GitHub acceptance gate is configured" in w.state_of().blocker_reason
    assert not w.store.read_dispatches(OBJ, attempt.attempt_id) and w.store.read_results()


class _BrokenGate:
    def check(self, repository, sha):
        raise RuntimeError("boom")


class _ElsewhereGate:
    def check(self, repository, sha):
        return GateResult(sha="f" * 40, state=GateState.GREEN, detail="green, but for another commit")


@pytest.mark.parametrize("gate", [_BrokenGate(), _ElsewhereGate()], ids=["raises", "another-sha"])
def test_a_gate_that_fails_or_answers_about_another_sha_is_not_green(tmp_path, gate):
    w = World(tmp_path)
    w.acceptance = gate
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.EVIDENCE_READY))
    w.dispatcher().tick()
    assert w.state_of().status is TaskStatus.EVIDENCE_READY
    attempt = latest_attempt(w)
    assert not w.store.read_dispatches(OBJ, attempt.attempt_id)
    assert w.dispatcher().status()[0]["github_acceptance"]["state"] == "unavailable"


def test_the_loop_never_publishes_a_candidate_onto_the_trunk(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective(target_branch="clive/trunk")
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert "never publishes a candidate onto" in w.state_of().blocker_reason and w.invocations() == 0
    trunk = ["git", "rev-parse", "--verify", "--quiet", "refs/heads/clive/trunk"]
    assert subprocess.run(trunk, cwd=w.repo, capture_output=True).returncode != 0
    # a worker already running on such a task when this took effect is refused at publication too
    reason = w.dispatcher()._publish(w.store.read_task(OBJ, 1), w.base)
    assert reason is not None and "clive/trunk" in reason
    assert subprocess.run(trunk, cwd=w.repo, capture_output=True).returncode != 0


# ---------------------------------------------------------------- protected paths (owner's loop update)

def test_an_objective_recorded_before_its_scope_was_protected_loads_but_never_advances(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    fields = dict(
        objective_id=OBJ, title="Legacy", requested_outcome="Change the loop's own inbox adapter.",
        repository="crooksldn-pixel/clive", base_ref="main", base_sha=w.base, target_branch="clive/objective/demo",
        product_memory_sha=w.base, allowed_paths=("crooks-assistant/app/remote_engineering", "pkg"),
        owner=OwnerEntry(os_user="george", host="host"), created_at=w.clock(),
    )
    with pytest.raises(ValidationError, match="no objective may put in scope"):
        Objective(**fields)                                    # the door refuses it today
    intake(Objective.model_validate(fields, context=RECORDED), kernel=w.kernel, objectives=w.objectives)
    assert [o.objective_id for o in w.objectives.read_all()] == [OBJ]   # an old record still loads
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    reason = w.state_of().blocker_reason
    assert "covers protected path(s) crooks-assistant/app/remote_engineering" in reason
    assert w.invocations() == 0 and not w.store.read_attempts(OBJ)


@pytest.mark.parametrize("stage", [TaskStatus.ASSIGNED, TaskStatus.RUNNING], ids=["assigned", "running"])
def test_a_worker_whose_scope_becomes_protected_is_stopped_and_its_task_blocked_after_a_restart(
        tmp_path, monkeypatch, stage):
    """The 2026-09-30 re-pin review, F-02: a task launched before its scope was protected is not left to work
    on until its candidate is refused; the next dispatcher, after a restart, stops the worker and blocks it."""
    w = World(tmp_path)
    if stage is TaskStatus.ASSIGNED:
        w.scenarios({"sleep_before_init": 30, **EDIT_HELLO})
        w.objective()
        w.dispatcher().tick()                            # launched; its init event has not come yet
    else:
        w.scenarios({"hang": True, **EDIT_HELLO})
        w.objective()
        w.run_until(w.status_is(TaskStatus.RUNNING))
    assert w.state_of().status is stage
    attempt = latest_attempt(w)
    marker = worker_marker(attempt.attempt_id, attempt.worker.session.session_id)
    worker = ClaudeCodeWorker(cli=str(w.cli))
    deadline = time.monotonic() + 10
    while not worker.live_pids(marker) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert worker.live_pids(marker)

    monkeypatch.setattr(objectives_module, "PROTECTED_PATHS", objectives_module.PROTECTED_PATHS + ("pkg",))
    w.dispatcher().tick()                                # a fresh dispatcher: nothing survives in memory
    state = w.state_of()
    assert state.status is TaskStatus.BLOCKED
    assert "covers protected path(s) pkg" in state.blocker_reason
    deadline = time.monotonic() + 10
    while worker.live_pids(marker) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not worker.live_pids(marker)
    assert not w.store.read_results()
    for _ in range(2):                                   # it stays blocked: nothing is launched again
        w.dispatcher().tick()
    assert w.state_of().status is TaskStatus.BLOCKED and len(w.store.read_attempts(OBJ)) == 1


@pytest.mark.parametrize("protected", [".gitleaks.toml", "crooks-assistant/tests/test_gate.py"])
def test_a_candidate_that_changes_a_protected_path_is_refused_whatever_the_scope(tmp_path, protected):
    w = World(tmp_path, max_result_refusals=1)
    w.scenarios({"edits": [["pkg/hello.txt", "hello\n"], [protected, "# weakened\n"]]})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert not w.store.read_results()
    attempt = latest_attempt(w)
    [note] = [e.note for e in w.store.read_events(OBJ, attempt.attempt_id) if e.kind is EventKind.CANCELLED]
    assert "changes protected paths" in note and protected in note


# ------------------------- the 2026-09-30 re-pin review, waived and done by hand: a stopped worker is confirmed gone

FAST_KILL = {"kill_grace_s": 0.5, "kill_confirm_s": 5.0}
FOREIGN_MCP = [{"name": "claude.ai Shopify", "status": "connected"}]
HANGS = {"hang": True, **EDIT_HELLO}


def _running(w: World) -> None:
    """The worker is acknowledged and running, its edits observed; it never reports."""
    w.run_until(w.status_is(TaskStatus.RUNNING))
    w.dispatcher().tick()


def _launched(w: World) -> None:
    """The worker is launched and running its scenario; its init event has not come yet."""
    w.dispatcher().tick()
    assert w.state_of().status is TaskStatus.ASSIGNED
    w.wait_started(0)


def _acknowledged(w: World) -> None:
    w.run_until(w.status_is(TaskStatus.RUNNING))


def _later(seconds: int) -> Callable[[World, pytest.MonkeyPatch], None]:
    def trigger(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
        w.clock.offset += timedelta(seconds=seconds)
    return trigger


def _init_logged(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    w.wait_logged(latest_attempt(w), "system")


def _result_logged(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    w.wait_logged(latest_attempt(w), "result")


def _scope_protected(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(objectives_module, "PROTECTED_PATHS", objectives_module.PROTECTED_PATHS + ("pkg",))


@dataclass(frozen=True)
class StopSite:
    """One place the dispatcher stops a worker: how the test gets there, what makes the next tick stop it, and
    what the dispatcher records once the worker is gone (``cancel``, ``block`` or ``candidate``)."""

    scenario: dict
    reach: Callable[[World], None]
    trigger: Callable[[World, pytest.MonkeyPatch], None]
    outcome: str
    says: str                                   # in the cancellation note, the blocker reason or why it was stopped
    config: dict = field(default_factory=dict)


STOP_SITES = {
    "stall": StopSite(HANGS, _running, _later(31), "cancel", "worker stalled: no event for 30s", {"stall_s": 30}),
    "init-timeout": StopSite({"sleep_before_init": 60}, _launched, _later(61), "cancel", "no init event within 60s",
                             {"init_timeout_s": 60}),
    "lease-expired": StopSite(HANGS, _running, _later(601), "cancel", "the attempt's lease expired",
                              {"lease_s": 600, "stall_s": 7200}),
    "time-limit": StopSite(HANGS, _running, _later(61), "block", "exceeded the attempt time limit of 60s",
                           {"attempt_timeout_s": 60}),
    "launch-surface": StopSite({"mcp": FOREIGN_MCP, "sleep_before_init": 0.5, "sleep_after_init": 60}, _launched,
                               _init_logged, "block",
                               "worker launch surface refused: MCP servers present: claude.ai Shopify"),
    "protected-scope": StopSite(HANGS, _running, _scope_protected, "block", "covers protected path(s) pkg"),
    "after-result": StopSite({**EDIT_HELLO, "sleep_before_result": 2, "sleep_after_result": 60}, _acknowledged,
                             _result_logged, "candidate", "its result (completed) was read"),
}


def _launch_spec(tmp_path: Path) -> LaunchSpec:
    (tmp_path / "ws").mkdir(exist_ok=True)
    return LaunchSpec(task_id="t", task_revision=1, attempt_id="t-a1", fencing_token=1, session_id=str(uuid.uuid4()),
                      workspace=tmp_path / "ws", home=tmp_path / "home", log_path=tmp_path / "log",
                      stderr_path=tmp_path / "err", prompt="p")


def test_the_driver_sigkills_a_worker_that_ignores_sigterm_and_confirms_it_gone(tmp_path):
    """F-01: SIGTERM alone never stopped this worker; the driver waits out the grace, SIGKILLs, and confirms."""
    w = World(tmp_path, worker_options=FAST_KILL)
    w.scenarios({"ignore_sigterm": True, "hang": True})
    worker = w.worker()
    spec = _launch_spec(tmp_path)
    record = worker.launch(spec)
    proc = worker._children[record.pid]
    try:
        w.wait_started(0)
        os.killpg(record.pid, signal.SIGTERM)                  # what stopping used to be, and all it was
        time.sleep(0.3)
        assert worker.live_pids(spec.marker) == [record.pid]
        began = time.monotonic()
        assert worker.kill(spec.marker) == []                  # confirmed gone
        assert time.monotonic() - began >= FAST_KILL["kill_grace_s"]  # SIGTERM had its grace first
        assert proc.wait(timeout=10) == -signal.SIGKILL        # then SIGKILL
        assert worker.live_pids(spec.marker) == [] and worker.kill(spec.marker) == []
    finally:
        w.kill_leftovers()
        if proc.poll() is None:
            proc.kill()


def test_the_driver_stops_a_worker_that_honours_sigterm_without_waiting_out_the_grace(tmp_path):
    w = World(tmp_path, worker_options={"kill_grace_s": 30, "kill_confirm_s": 30})
    w.scenarios({"hang": True})
    worker = w.worker()
    spec = _launch_spec(tmp_path)
    record = worker.launch(spec)
    proc = worker._children[record.pid]
    try:
        w.wait_started(0)
        began = time.monotonic()
        assert worker.kill(spec.marker) == []
        assert time.monotonic() - began < 10 and proc.wait(timeout=10) == -signal.SIGTERM   # SIGTERM was enough
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.parametrize("site", STOP_SITES.values(), ids=STOP_SITES.keys())
def test_a_worker_that_ignores_sigterm_is_gone_before_the_dispatcher_records_its_stop(tmp_path, monkeypatch, site):
    """F-01, at every place the dispatcher stops a worker: the worker ignores SIGTERM, is SIGKILLed after the grace,
    and is gone before the tick that records the cancel, the block or the candidate returns. What is recorded is
    exactly what was recorded before: a transient cancel that is retried, a block with its own reason, a candidate."""
    w = World(tmp_path, worker_options=FAST_KILL, **site.config)
    w.scenarios({**site.scenario, "ignore_sigterm": True}, EDIT_HELLO)
    w.objective()
    try:
        site.reach(w)
        attempt = latest_attempt(w)
        assert w.worker().live_pids(w.marker(attempt))
        site.trigger(w, monkeypatch)
        w.dispatcher().tick()
        assert not w.worker().live_pids(w.marker(attempt))     # gone when the tick returns; the test does not wait
        events = w.store.read_events(OBJ, attempt.attempt_id)
        if site.outcome == "cancel":
            [note] = [e.note for e in events if e.kind is EventKind.CANCELLED]
            assert note.startswith("transient:") and site.says in note
            w.run_until(w.status_is(TaskStatus.REVIEWING))     # retried, as before
            assert latest_attempt(w).fencing_token > attempt.fencing_token
            assert [r.attempt_id for r in w.store.read_results()] == [latest_attempt(w).attempt_id]
        elif site.outcome == "block":
            state = w.state_of()
            assert state.status is TaskStatus.BLOCKED and site.says in state.blocker_reason
            assert "could not be stopped" not in state.blocker_reason
            assert not any(e.kind is EventKind.CANCELLED for e in events)
        else:
            assert [r.attempt_id for r in w.store.read_results()] == [attempt.attempt_id]
    finally:
        w.kill_leftovers()


@pytest.mark.parametrize("site", STOP_SITES.values(), ids=STOP_SITES.keys())
def test_a_worker_that_cannot_be_confirmed_gone_blocks_its_task_and_is_never_recorded_as_stopped(
        tmp_path, monkeypatch, site):
    """F-01: when the host still reports the worker after SIGTERM, SIGKILL and both waits, nothing is recorded as
    if it had stopped: no cancel, no retry, no candidate. The task blocks, naming the attempt, the pids and why it
    was being stopped. (The host's answer is simulated: ``live_pids`` keeps reporting a process it once saw.)"""
    w = World(tmp_path, worker_options={"kill_grace_s": 0.3, "kill_confirm_s": 0.3}, **site.config)
    w.scenarios({**site.scenario, "ignore_sigterm": True}, EDIT_HELLO)
    w.objective()
    real = ClaudeCodeWorker.live_pids
    seen: dict[str, list[int]] = {}

    def never_confirmed_gone(self, marker):
        pids = real(self, marker)
        if pids:
            seen[marker] = pids
        return pids or seen.get(marker, [])

    monkeypatch.setattr(ClaudeCodeWorker, "live_pids", never_confirmed_gone)
    try:
        site.reach(w)
        attempt = latest_attempt(w)
        site.trigger(w, monkeypatch)
        w.dispatcher().tick()
        state = w.state_of()
        pids = ", ".join(str(pid) for pid in seen[w.marker(attempt)])
        assert state.status is TaskStatus.BLOCKED and state.blocker_class is BlockerClass.DETERMINISTIC
        assert state.blocker_reason.startswith(f"the worker of {attempt.attempt_id} could not be stopped: "
                                               f"pid(s) {pids} still alive after SIGTERM, SIGKILL")
        assert site.says in state.blocker_reason                # and why it was being stopped
        events = w.store.read_events(OBJ, attempt.attempt_id)
        assert not any(e.kind is EventKind.CANCELLED for e in events)   # never a normal cancel
        assert not w.store.read_results()                                 # nor a candidate
        for _ in range(2):                                                # nothing is launched in its place
            w.dispatcher().tick()
        assert w.state_of().status is TaskStatus.BLOCKED and len(w.store.read_attempts(OBJ)) == 1
        assert w.invocations() == 1
        assert not real(w.worker(), w.marker(attempt))    # it did die: only the confirmation was withheld
    finally:
        w.kill_leftovers()


# ------------------------- the 2026-09-30 re-pin review, second run, waived and done by hand: declared checks are required

@pytest.mark.parametrize("roster, missing", [
    ({"tools": ["Read", "Edit", "Write", "Glob", "Grep", "StructuredOutput"]},
     f"the declared checks' tool {CHECK_TOOL} is missing from the init roster"),
    ({"mcp": []}, "the declared checks' MCP server clive_checks is not in the init roster"),
    ({"mcp": [{"name": "clive_checks", "status": "failed"}]},
     "the declared checks' MCP server clive_checks is not connected (status failed)"),
], ids=["no-run-checks-tool", "no-checks-server", "checks-server-failed"])
def test_a_builder_launched_with_declared_checks_is_refused_and_stopped_without_run_checks(tmp_path, roster, missing):
    """F-01 (second run): the launch asked for the run_checks tool and its server, and the prompt tells the builder
    it has them; an init roster without either is a refused launch surface, stopped and blocked before any ack."""
    check = Check(name="hello", argv=("grep", "-qx", "hello", "pkg/hello.txt"))
    w = World(tmp_path, checks=(check,), runner=SandboxShapedTreeRunner())
    w.scenarios({**roster, "sleep_after_init": 60, **EDIT_HELLO})
    w.objective()
    try:
        w.run_until(w.status_is(TaskStatus.BLOCKED))
        reason = w.state_of().blocker_reason
        assert reason.startswith("worker launch surface refused: ") and missing in reason
        attempt = latest_attempt(w)
        assert EventKind.ACKNOWLEDGED not in {e.kind for e in w.store.read_events(OBJ, attempt.attempt_id)}
        assert not w.worker().live_pids(w.marker(attempt))
        assert not w.store.read_results()
        argv = json.loads((w.state / "argv.0.json").read_text())     # the launch did ask for both
        assert CHECK_TOOL in argv and list(json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]) == \
            ["clive_checks"]
        assert RUN_CHECKS_LINE in (w.state / "prompt.0.txt").read_text()
    finally:
        w.kill_leftovers()


# ---------------------------------------------------------------- the owner's skills for builders

DEMO_SKILL = "---\nname: demo\ndescription: A demo skill.\n---\n\nSay hello properly.\n"
ROGUE_SKILL = "---\nname: rogue\ndescription: Not on the owner's list.\n---\n\nDo something else.\n"


def _skills_world(tmp_path: Path, listed: dict[str, str], **config) -> World:
    """A world whose base commit vendors three skills in .claude/skills, with an allow-list pinning ``listed``
    (name -> the content its SKILL.md hash is taken from)."""
    import hashlib

    w = World(tmp_path, **config)
    for name, text in {"demo": DEMO_SKILL, "other": DEMO_SKILL, "rogue": ROGUE_SKILL}.items():
        (w.repo / ".claude" / "skills" / name).mkdir(parents=True)
        (w.repo / ".claude" / "skills" / name / "SKILL.md").write_text(text)
    _git(w.repo, "add", "-A")
    _git(w.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "skills")
    w.base = _git(w.repo, "rev-parse", "HEAD")
    allow = tmp_path / "builder_skills.json"
    allow.write_text(json.dumps({"schema": "clive.builder_skills.v1", "cli_skills_off": ["doctor"], "skills": [
        {"name": name, "source": "repo", "path": f".claude/skills/{name}",
         "files": {"SKILL.md": hashlib.sha256(text.encode()).hexdigest()}} for name, text in listed.items()]}))
    w.config.builder_skills_file = allow
    return w


def test_a_builder_gets_exactly_the_owners_skills_each_verified_by_hash(tmp_path):
    w = _skills_world(tmp_path, {"demo": DEMO_SKILL, "other": DEMO_SKILL + "pinned before an edit\n",
                                 "missing": DEMO_SKILL})
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    attempt = w.store.read_attempts(OBJ)[0]
    folder = tmp_path / "runtime" / "homes" / attempt.attempt_id / "clive-skills"
    argv = json.loads((w.state / "argv.0.json").read_text())
    assert argv[argv.index("--plugin-dir") + 1] == str(folder) and "--disable-slash-commands" not in argv
    assert argv[argv.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep,Skill"
    flags = argv[argv.index("-p") + 2:]          # everything but the prompt
    assert "Skill(clive-skills:demo)" in flags and not any("other" in a or "rogue" in a for a in flags)
    assert json.loads(argv[argv.index("--settings") + 1]) == {"disableBundledSkills": True,
                                                              "skillOverrides": {"doctor": "off"}}
    assert "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS" in json.loads((w.state / "env.0.json").read_text())
    # the folder holds exactly the one skill that verified, byte for byte, outside the workspace
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert files == [".claude-plugin/plugin.json", "skills/demo/SKILL.md"]
    assert (folder / "skills" / "demo" / "SKILL.md").read_text() == DEMO_SKILL
    workspace = tmp_path / "workers" / OBJ / attempt.attempt_id
    assert workspace not in folder.parents
    notes = json.loads((tmp_path / "runtime" / "attempts" / f"{attempt.attempt_id}.json").read_text())
    assert notes["skills"]["provided"] == ["demo"]
    withheld = dict(map(tuple, notes["skills"]["withheld"]))
    assert set(withheld) == {"other", "missing"}
    assert "differs from the hash" in withheld["other"] and "not readable" in withheld["missing"]
    assert notes["roster"]["skill_names"] == ["clive-skills:demo"] and notes["roster"]["problems"] == []
    prompt = (w.state / "prompt.0.txt").read_text()
    assert "SKILLS" in prompt and "- clive-skills:demo" in prompt and "clive-skills:other" not in prompt


@pytest.mark.parametrize("roster, says", [
    ({"skills": ["clive-skills:demo", "deploy"]}, "skills beyond the owner's list: deploy"),
    ({"skills": []}, "missing from the init roster: clive-skills:demo"),
    ({"slash_commands": ["clive-skills:demo", "ecc:ship"]}, "plugin commands beyond the owner's skills: ecc:ship"),
    ({"plugins": [{"name": "clive-skills", "path": "/elsewhere", "source": "clive-skills@inline"}]},
     "plugins beyond the builtin allowance: clive-skills@inline"),
], ids=["foreign-skill", "skills-missing", "plugin-command", "other-folder"])
def test_a_builder_whose_roster_is_not_exactly_the_owners_skills_is_stopped_and_blocked(tmp_path, roster, says):
    w = _skills_world(tmp_path, {"demo": DEMO_SKILL})
    w.scenarios({**EDIT_HELLO, **roster, "sleep_after_init": 30})
    w.objective()
    try:
        w.run_until(w.status_is(TaskStatus.BLOCKED))
        reason = w.state_of().blocker_reason
        assert reason.startswith("worker launch surface refused") and says in reason, reason
        assert not w.store.read_results()
        assert processes_with_marker(MARKER, w.marker(w.store.read_attempts(OBJ)[0])) == []
    finally:
        w.kill_leftovers()


def test_with_builder_skills_off_the_launch_is_exactly_the_launch_without_skills(tmp_path):
    w = _skills_world(tmp_path, {"demo": DEMO_SKILL}, builder_skills=False)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    argv = json.loads((w.state / "argv.0.json").read_text())
    assert "--disable-slash-commands" in argv and "--plugin-dir" not in argv and "--settings" not in argv
    assert argv[argv.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep"
    assert "SKILLS" not in (w.state / "prompt.0.txt").read_text()


# ---------------------------------------------------------------- why a build stopped, kept privately (owner, 7 Oct)

def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_a_build_stopped_at_its_repair_limit_keeps_the_reviewers_findings_whole_on_the_host_only(tmp_path):
    """Item 1 of the owner's loop upgrade: whoever repairs a stopped build gets the reviewer's words. They are kept
    on the loop host (``<runtime>/stops``, 0600), redacted for credentials, and never reach the public status."""
    from app.remote_engineering import Receipt, ReceiptLog, build_status
    from tests.fake_credentials import github_token

    token = github_token("stop-report")
    finding = {**FINDING, "finding": f"the greeting is wrong; the builder pasted {token} into pkg/hello.txt",
               "evidence_ref": "pkg/hello.txt line 1, see MARKER-EVIDENCE"}
    minor = {"finding_id": "F-02", "material": False, "finding": "MARKER-MINOR wording could be warmer",
             "evidence_ref": "pkg/hello.txt", "required_repair": "optional"}
    w = World(tmp_path, max_repair_rounds=0)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[finding, minor]))
    w.run_until(w.status_is(TaskStatus.BLOCKED))

    reports = w.dispatcher().stop_reports()
    assert len(reports) == 1
    report = reports[0]
    attempt = w.store.read_attempts(OBJ)[0]
    candidate = w.store.read_results()[0].result_sha
    assert (report["objective_id"], report["stage"], report["cause"]) == (OBJ, "BLOCKED", "review_limit")
    assert report["attempt_id"] == attempt.attempt_id and report["candidate_sha"] == candidate
    assert report["max_repair_rounds"] == 0 and report["blocker"].startswith("convergence limit")
    [round_] = report["review_rounds"]
    assert round_["candidate_sha"] == candidate and round_["reviewer"] == "gpt"
    assert round_["summary"] == "human-readable explanation; decides nothing"
    first, second = round_["findings"]
    assert first["finding"] == "the greeting is wrong; the builder pasted [redacted] into pkg/hello.txt"
    assert first["evidence_ref"] == "pkg/hello.txt line 1, see MARKER-EVIDENCE"
    assert first["required_repair"] == "say hello, not goodbye" and first["material"] is True
    assert second["finding"].startswith("MARKER-MINOR") and second["material"] is False
    assert token not in json.dumps(report)

    # kept on the host, readable by the loop's own user only, and rebuilt only when the stop itself changes
    path = tmp_path / "runtime" / "stops" / f"{OBJ}.json"
    assert json.loads(path.read_text())["review_rounds"] == report["review_rounds"]
    assert _mode(path) == 0o600 and _mode(path.parent) == 0o700
    before = path.stat().st_mtime_ns
    assert w.dispatcher().stop_reports() == reports and path.stat().st_mtime_ns == before

    # the public projection still carries counts and words only
    receipts = ReceiptLog(w.store.root / "remote_engineering")
    receipts.put(Receipt(request_id="r-stop", request_sha256="0" * 64, outcome="accepted", objective_id=OBJ,
                         task_id=OBJ, source="requests/r-stop.json", recorded_at=w.clock()))
    published = json.dumps(build_status(store=w.store, receipts=receipts, now=w.clock()))
    assert "the greeting is wrong" not in published and "MARKER" not in published
    assert "say hello, not goodbye" not in published


def test_failed_checks_keep_their_output_with_the_stop(tmp_path):
    check = Check(name="says-hello", argv=("sh", "-c", "echo MARKER-CHECK-OUTPUT; grep -q '^hello$' pkg/hello.txt"))
    w = World(tmp_path, checks=(check,))
    w.scenarios({"edits": [["pkg/hello.txt", "helo\n"]]})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    [report] = w.dispatcher().stop_reports()
    assert report["cause"] == "checks_failed" and report["blocker"].startswith("worker results refused")
    attempts = {a.attempt_id for a in w.store.read_attempts(OBJ)}
    assert report["failed_checks"] and {c["attempt_id"] for c in report["failed_checks"]} <= attempts
    newest = report["failed_checks"][0]
    assert (newest["what"], newest["name"], newest["exit_code"]) == ("check", "says-hello", 1)
    assert "MARKER-CHECK-OUTPUT" in newest["tail"]
    assert newest["attempt_id"] == max(attempts, key=lambda a: int(a.rsplit("-a", 1)[1]))


@pytest.mark.parametrize("status, stage, cause", [
    ("blocked", TaskStatus.BLOCKED, "builder_blocked"),
    ("owner_decision_required", TaskStatus.OWNER_GATE, "owner_decision"),
])
def test_the_builders_own_report_is_kept_with_the_stop(tmp_path, status, stage, cause):
    w = World(tmp_path)
    w.scenarios({"report": {"status": status, "summary": "MARKER-SUMMARY cannot finish",
                            "reason": "MARKER-REASON web/app.js is outside the allowed paths"}})
    w.objective()
    w.run_until(w.status_is(stage))
    [report] = w.dispatcher().stop_reports()
    assert report["cause"] == cause and report["stage"] == stage.value.upper()
    assert report["builder_report"] == {
        "attempt_id": w.store.read_attempts(OBJ)[0].attempt_id, "revision": 1, "status": status,
        "summary": "MARKER-SUMMARY cannot finish", "reason": "MARKER-REASON web/app.js is outside the allowed paths"}
    assert report["review_rounds"] == [] and report["failed_checks"] == [] and report["github_failure"] is None


def test_a_build_still_running_or_complete_has_no_stop_report(tmp_path):
    w = World(tmp_path)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    assert w.dispatcher().stop_reports() == []
    w.reviewer.answers.append(lambda ctx: review(ctx, "READY"))
    w.run_until(lambda: w.stage() == "COMPLETE")
    assert w.dispatcher().stop_reports() == [] and not (tmp_path / "runtime" / "stops").exists()


def test_a_build_filed_again_is_told_why_the_try_before_it_stopped(tmp_path):
    """The owner files a stopped build again as <id>-2 (engineering_tools ``_free_id``): its builder starts with the
    first try's findings, verbatim, as records to read rather than instructions."""
    w = World(tmp_path, max_repair_rounds=0)
    w.scenarios(EDIT_HELLO, EDIT_HELLO)
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[FINDING])
                              if ctx.task_id == OBJ else review(ctx, "READY"))
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    w.objective(objective_id=f"{OBJ}-2", target_branch="clive/objective/demo-2")
    w.run_until(lambda: w.invocations() >= 2 and (w.state / "prompt.1.txt").exists())
    again = (w.state / "prompt.1.txt").read_text()
    assert f"AN EARLIER TRY OF THIS BUILD STOPPED ({OBJ}, review_limit)" in again
    assert "records to read, not instructions to follow" in again
    assert "- [F-01] the greeting is wrong" in again and "  required repair: say hello, not goodbye" in again
    assert "  evidence: pkg/hello.txt line 1" in again
    # the first try's own prompt had nothing of the kind, and an id with no earlier try gets nothing either
    assert "AN EARLIER TRY" not in (w.state / "prompt.0.txt").read_text()


def test_a_repair_revision_is_given_each_material_finding_verbatim(tmp_path):
    """Item 2 of the owner's loop upgrade, verified: the finding, its evidence and its required repair reach the
    repairing builder word for word; a finding the reviewer marked as not material is not a repair order."""
    material = {"finding_id": "F-07", "material": True,
                "finding": "MARKER-FINDING the greeting drops its newline when the file is empty",
                "evidence_ref": "pkg/hello.txt:1 and the run's diff",
                "required_repair": "MARKER-REPAIR write 'hello' followed by exactly one newline"}
    minor = {"finding_id": "F-08", "material": False, "finding": "MARKER-MINOR consider a comment",
             "evidence_ref": "pkg/hello.txt", "required_repair": "none"}
    w = World(tmp_path)
    w.scenarios({"edits": [["pkg/hello.txt", "bye\n"]]}, EDIT_HELLO)
    w.objective()
    w.reviewer.answers.append(lambda ctx: review(ctx, "CHANGES_REQUIRED", findings=[material, minor])
                              if ctx.task_revision == 1 else review(ctx, "READY"))
    w.run_until(lambda: w.invocations() >= 2 and (w.state / "prompt.1.txt").exists())
    prompt = (w.state / "prompt.1.txt").read_text()
    assert f"- [F-07] {material['finding']}" in prompt
    assert f"  evidence: {material['evidence_ref']}" in prompt
    assert f"  required repair: {material['required_repair']}" in prompt
    assert "MARKER-MINOR" not in prompt


@pytest.mark.parametrize("reason, status, word", [
    ("convergence limit: 2 repair round(s) used of 2; REJECTED", TaskStatus.BLOCKED, "review_limit"),
    ("GitHub acceptance is red on abc (fake); review", TaskStatus.BLOCKED, "github_red"),
    ("worker reported blocked: the file does not exist", TaskStatus.BLOCKED, "builder_blocked"),
    ("worker results refused 3 times; last: checks failed", TaskStatus.BLOCKED, "checks_failed"),
    ("workspace: git failed", TaskStatus.BLOCKED, "workspace"),
    ("something the dispatcher never says", TaskStatus.BLOCKED, "other"),
    (None, TaskStatus.OWNER_GATE, "owner_gate"),
])
def test_each_stop_is_named_by_one_fixed_word(reason, status, word):
    from app.orchestrator.dispatcher import STOP_CAUSE_WORDS, stop_cause

    assert stop_cause(reason, status) == word and word in STOP_CAUSE_WORDS


def test_probe_launch_says_whether_this_cli_passes_the_launch_check_and_leaves_nothing_running(tmp_path):
    """For the operator before a re-pin or after a deliberate CLI update: a builder launched exactly as an attempt
    would be, stopped at its init event, and the launch check's verdict on it."""
    w = World(tmp_path)
    script = Path(__file__).resolve().parent.parent / "scripts" / "engineering_dispatcher.py"

    def probe() -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), "--store", str(w.store.root), "--repo", str(w.repo), "--no-journal",
             "--runtime-root", str(tmp_path / "rt"), "--workspace-root", str(tmp_path / "ws"),
             "--worker-cli", str(w.cli), "probe-launch", "--base-ref", "main", "--timeout-s", "20"],
            capture_output=True, text=True, cwd=tmp_path, env={**os.environ}, timeout=120)

    w.scenarios({"hang": True})
    passed = probe()
    assert passed.returncode == 0, passed.stderr
    out = json.loads(passed.stdout)
    assert out["verdict"] == "PASS" and out["problems"] == []
    assert CHECK_TOOL in out["roster"]["tools"] and out["roster"]["mcp_servers"] == [["clive_checks", "connected"]]
    # this base vendors none of the owner's skills, so each is withheld, said why, and nothing loads in its place
    assert out["skills"]["given"] == [] and len(out["skills"]["withheld"]) == 4 and out["roster"]["skills"] == []
    w.scenarios({"hang": True, "plugins": [{"name": "ecc", "path": "/opt/ecc", "source": "ecc@market"}]})
    refused = probe()
    assert refused.returncode == 2
    assert json.loads(refused.stdout)["problems"] == ["plugins beyond the builtin allowance: ecc@market"]
    assert w.invocations() == 2
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _probes_running():
        time.sleep(0.1)
    assert not _probes_running(), "the probed builder was stopped"


def _probes_running() -> list[int]:
    found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            environ = (proc / "environ").read_bytes()
        except OSError:
            continue
        if f"{MARKER}=probe-".encode() in environ:
            found.append(int(proc.name))
    return found
