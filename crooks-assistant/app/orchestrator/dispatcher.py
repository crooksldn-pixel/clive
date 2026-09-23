"""Engineering Dispatcher V1: a deterministic controller around the frozen kernel.

It coordinates; it does not reason. Each ``tick`` reads the authoritative records,
finds the one transition each objective is eligible for, performs or reconciles
the execution behind it, and submits what actually happened to the kernel:

    READY            -> fresh workspace at the base, ``assign``, launch the builder
    ASSIGNED         -> the worker's own init event, checked against the launch
                        policy, is the acknowledgement (``ack``); a bad roster blocks
    RUNNING          -> stream events renew the lease (``heartbeat``); a successful
                        file edit is ``progress``; the worker's result is committed by
                        CLIVE, scoped, checked in the sandbox (``checks.py``), recorded as
                        ``evidence`` and the exact
                        git SHA as the ``candidate``
    EVIDENCE_READY   -> an independent, available reviewer gets the exact-SHA packet
                        (``dispatch``); if none is available, the task is BLOCKED with
                        the exact gap, and nothing is dispatched to nobody
    REVIEWING        -> a typed ``clive.review_result.v1`` is submitted (``verdict``);
                        the kernel admits, rejects or refuses it
    REJECTED         -> a repair revision carrying the material findings (``task``
                        r+1, kind repair); after ``max_repair_rounds`` it blocks
    ACCEPTED         -> the target ref is verified at the accepted SHA (``integrate``)
    DONE             -> COMPLETE when the projection says every record agrees
    BLOCKED / OWNER_GATE -> nothing; the dispatcher never lifts either

What it never does: manufacture a state (a launch is not an acknowledgement, a
live process is not progress, a worker's "done" is not a candidate, a candidate is
not accepted, an acceptance is not an integration, an integration is not a
deployment), lift an owner gate, deploy, or touch anything outside the task's
workspace, its candidate refs and its target branch.

Restart: every stage is re-derived from the kernel's records on each tick; the
dispatcher's own runtime notes (``<runtime>/attempts/*.json``) hold only execution
facts (pid, launch time, how many worker events were already mapped). Worker
processes are found on the host by their attempt marker, so a restarted
dispatcher re-attaches instead of launching a second worker, and a worker that
finished while the dispatcher was down is ingested from its log and workspace.

Failure classes: a transient failure (a provider error, a process that died, a
stall) cancels the attempt and retries with exponential backoff, at most
``max_transient_retries`` times, counted from the kernel's cancellation records; a
deterministic failure (a refused launch surface, missing capability, a worker that
reports it is blocked, a candidate that cannot be published) blocks the task once.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .checks import CheckRunner, NamespaceSandbox
from .contracts import BlockerClass, EngineeringTask, TaskKind, TaskStatus
from .lifecycle import (
    Attempt,
    EventKind,
    IntegrationMethod,
    Kernel,
    LifecycleError,
    VerdictOutcome,
    lifecycle_view,
    sha256_of,
)
from .objectives import Objective, ObjectiveStore
from .reviewers.base import ReviewContext, ReviewerDriver, ReviewResult
from .routing import Party, Principal, PrincipalKind, SessionContext, Workspace
from .workers.base import (
    Activity,
    Finished,
    LaunchSpec,
    Started,
    WorkerDriver,
    WorkerLaunchError,
    worker_marker,
)
from .workspaces import WorkspaceError, WorkspaceManager, git

__all__ = ["Dispatcher", "DispatcherBusy", "DispatcherConfig", "NEXT_ACTION"]

TRANSIENT = "transient:"
RESULT_REFUSED = "result_refused:"

NEXT_ACTION = {
    TaskStatus.READY: "launch a builder attempt in a fresh workspace",
    TaskStatus.ASSIGNED: "wait for the worker's init event, check its launch surface, acknowledge",
    TaskStatus.RUNNING: "observe the worker; on its result: commit, scope, checks, evidence, candidate",
    TaskStatus.EVIDENCE_READY: "dispatch the exact candidate to an available independent reviewer",
    TaskStatus.REVIEWING: "wait for the typed review result and submit it to the kernel",
    TaskStatus.REJECTED: "route a repair revision carrying the material findings",
    TaskStatus.ACCEPTED: "verify the target ref at the accepted SHA and record the integration",
    TaskStatus.DONE: "none",
    TaskStatus.BLOCKED: "none: the blocker must be resolved and the task resumed (kernel resume)",
    TaskStatus.OWNER_GATE: "none: owner decision; the dispatcher never lifts an owner gate",
    TaskStatus.OBSOLETE: "none: superseded",
    TaskStatus.CANCELLED: "none",
}


class DispatcherBusy(RuntimeError):
    """Another dispatcher holds the runtime lock. Nothing was done."""


@dataclass
class DispatcherConfig:
    runtime_root: Path
    workspace_root: Path
    repo: Path
    publish_remote: str | None = None
    worker_id: str = "clive-dispatcher-builder"
    lease_s: int = 1800
    heartbeat_interval_s: int = 300
    progress_interval_s: int = 120
    init_timeout_s: int = 180
    stall_s: int = 1200
    attempt_timeout_s: int = 4 * 3600
    max_transient_retries: int = 3
    backoff_base_s: int = 60
    max_result_refusals: int = 2
    max_concurrent: int = 1
    packet_diff_limit: int = 200_000


@dataclass
class Dispatcher:
    kernel: Kernel
    objectives: ObjectiveStore
    worker: WorkerDriver
    reviewers: Sequence[ReviewerDriver]
    config: DispatcherConfig
    checks: CheckRunner = field(default_factory=NamespaceSandbox)
    integrator: WorkerDriver | None = None
    log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workspaces = WorkspaceManager(self.config.workspace_root)
        self.store = self.kernel.store
        if self.integrator is None:
            from .workers.integrator import IntegratorWorker
            self.integrator = IntegratorWorker(self.config.repo)

    def _worker_for(self, obj: Objective) -> WorkerDriver:
        return self.integrator if obj.builder == "integrator" else self.worker

    # ------------------------------------------------------------ plumbing
    def now(self) -> datetime:
        return self.kernel.clock()

    def _note(self, objective_id: str, text: str) -> str:
        line = f"{objective_id}: {text}"
        self.log.append(line)
        return line

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        self.config.runtime_root.mkdir(parents=True, exist_ok=True)
        handle = open(self.config.runtime_root / "dispatcher.lock", "a+b")  # noqa: SIM115
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DispatcherBusy(f"another dispatcher holds {self.config.runtime_root}/dispatcher.lock") from None
            yield
        finally:
            handle.close()

    def _runtime_path(self, attempt_id: str) -> Path:
        return self.config.runtime_root / "attempts" / f"{attempt_id}.json"

    def _runtime(self, attempt_id: str) -> dict:
        path = self._runtime_path(attempt_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _save_runtime(self, attempt_id: str, data: dict) -> None:
        path = self._runtime_path(attempt_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def _paths(self, attempt: Attempt) -> dict[str, Path]:
        base = self.config.runtime_root
        return {
            "workspace": self.workspaces.path_for(attempt.task_id, attempt.attempt_id),
            "home": base / "homes" / attempt.attempt_id,
            "log": base / "logs" / f"{attempt.attempt_id}.stream.jsonl",
            "stderr": base / "logs" / f"{attempt.attempt_id}.stderr.txt",
            "evidence": base / "evidence" / attempt.attempt_id,
            "checks": base / "checks" / attempt.attempt_id,
        }

    def _latest(self, task_id: str) -> tuple[EngineeringTask | None, object]:
        tasks = [t for t in self.store.read_tasks() if t.task_id == task_id]
        if not tasks:
            return None, None
        task = max(tasks, key=lambda t: t.revision)
        return task, self.store.read_task_state(task_id, task.revision)

    def _current_attempt(self, task: EngineeringTask, state) -> Attempt:
        for attempt in self.store.read_attempts(task.task_id):
            if attempt.attempt_id == state.attempt_id:
                return attempt
        raise LifecycleError(f"attempt {state.attempt_id} of {task.task_id} is not recorded")

    def _target_head(self, task: EngineeringTask) -> str | None:
        if self.config.publish_remote:
            return self.kernel.git.remote_head(self.config.publish_remote, task.target_branch)
        return self.kernel.git.rev_parse(f"refs/heads/{task.target_branch}")

    # ------------------------------------------------------------ the loop
    def tick(self) -> list[str]:
        """One pass over every objective. Returns what was done, one line per action."""
        with self.exclusive():
            start = len(self.log)
            for objective in self.objectives.read_all():
                for _ in range(12):  # several transitions per tick when each is immediate
                    _, advanced = self._step(objective)
                    if not advanced:
                        break
            return self.log[start:]

    def _step(self, obj: Objective) -> tuple[str | None, bool]:
        task, state = self._latest(obj.objective_id)
        if task is None or state is None:
            return self._note(obj.objective_id, "objective recorded with no task; re-run intake"), False
        status = state.status
        try:
            if status is TaskStatus.READY:
                return self._start_attempt(obj, task, state)
            if status in (TaskStatus.ASSIGNED, TaskStatus.RUNNING):
                return self._supervise(obj, task, state)
            if status is TaskStatus.EVIDENCE_READY:
                return self._dispatch_review(obj, task, state)
            if status is TaskStatus.REVIEWING:
                return self._collect_review(obj, task, state)
            if status is TaskStatus.REJECTED:
                return self._route_repair(obj, task, state)
            if status is TaskStatus.ACCEPTED:
                return self._integrate(obj, task, state)
        except WorkspaceError as exc:
            return self._block(obj, task, f"workspace: {exc}"), True
        except LifecycleError as exc:
            # The kernel refused a verb: nothing was written. Report it; the next tick re-reads the records.
            return self._note(obj.objective_id, f"kernel refused ({status.value}): {exc}"), False
        return None, False

    # ------------------------------------------------------------ READY
    def _failed_check_output(self, attempt: Attempt, limit: int = 3000) -> list[str]:
        """What the failing checks of a refused attempt printed, so the next builder need not guess.

        Output of CLIVE's own sandboxed run of the objective's checks: the builder cannot run them."""
        out: list[str] = []
        for path in sorted(self._paths(attempt)["evidence"].glob("check-*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("exit_code") == 0:
                continue
            tail = ((data.get("stdout_tail") or "") + (data.get("stderr_tail") or ""))[-limit:]
            out += [f"FAILED CHECK `{data.get('name')}` on {attempt.attempt_id} (exit {data.get('exit_code')}), "
                    "last output:", "```", tail, "```", ""]
        return out

    def _revision_history(self, task: EngineeringTask) -> list[tuple[Attempt, str, datetime]]:
        """Every cancellation of this revision's attempts: (attempt, reason, when)."""
        out = []
        for attempt in self.store.read_attempts(task.task_id):
            if attempt.task_revision != task.revision:
                continue
            for event in self.store.read_events(task.task_id, attempt.attempt_id):
                if event.kind is EventKind.CANCELLED:
                    out.append((attempt, event.note or "", event.at))
        return sorted(out, key=lambda item: item[0].fencing_token)

    def _live_count(self) -> int:
        live = 0
        for obj in self.objectives.read_all():
            _, state = self._latest(obj.objective_id)
            if state is not None and state.status in (TaskStatus.ASSIGNED, TaskStatus.RUNNING):
                live += 1
        return live

    def _start_attempt(self, obj: Objective, task: EngineeringTask, state) -> tuple[str | None, bool]:
        history = self._revision_history(task)
        transient = [h for h in history if h[1].startswith(TRANSIENT)]
        refused = [h for h in history if h[1].startswith(RESULT_REFUSED)]
        if len(transient) >= self.config.max_transient_retries:
            return self._block(obj, task, f"transient worker failures exhausted after {len(transient)} attempts; "
                                          f"last: {transient[-1][1]}"), True
        if len(refused) >= self.config.max_result_refusals:
            return self._block(obj, task, f"worker results refused {len(refused)} times; last: {refused[-1][1]}"), True
        if history and history[-1][1].startswith(TRANSIENT):
            wait = self.config.backoff_base_s * 2 ** (len(transient) - 1)
            ready_at = history[-1][2] + timedelta(seconds=wait)
            if self.now() < ready_at:
                return self._note(obj.objective_id, f"backing off until {ready_at.isoformat()} after a transient failure"), False
        if self._live_count() >= self.config.max_concurrent:
            return self._note(obj.objective_id, "waiting: the concurrent-worker limit is reached"), False

        token = max((a.fencing_token for a in self.store.read_attempts(task.task_id)), default=0) + 1
        attempt_id = f"{task.task_id}-a{token}"
        info = self.workspaces.create(self.config.repo, task_id=task.task_id, attempt_id=attempt_id,
                                      base_sha=task.base_sha)
        session_id = str(uuid.uuid4())
        now = self.now()
        worker = Party(
            principal=Principal(principal_id=self._worker_for(obj).principal_id,
                                kind=PrincipalKind.AUTOMATION if obj.builder == "integrator" else PrincipalKind.MODEL),
            session=SessionContext(session_id=session_id, context_is_fresh=True, started_at=now),
            workspace=Workspace(workspace_id=str(info.path), branch=info.branch, head_sha=task.base_sha,
                                read_only=False, clean=True),
        )
        attempt = self.kernel.assign(task.task_id, task.revision, worker_id=self.config.worker_id, worker=worker,
                                     lease_duration_s=self.config.lease_s, attempt_id=attempt_id)
        start_sha = task.base_sha
        if task.kind is TaskKind.REPAIR:
            start_sha = self._rejected_candidate(task)
            self.workspaces.fast_forward_to(info.path, start_sha)
        self._save_runtime(attempt_id, {"attempt_id": attempt_id, "session_id": session_id,
                                        "start_sha": start_sha, "consumed": 0, "phase": "assigned"})
        self._note(obj.objective_id, f"assigned {attempt_id} (token {attempt.fencing_token}) in {info.path}")
        return self._launch(obj, task, attempt), True

    def _rejected_candidate(self, task: EngineeringTask) -> str:
        previous = self.store.read_task(task.task_id, task.revision - 1)
        results = [r for r in self.store.read_results()
                   if r.task_id == task.task_id and r.task_revision == task.revision - 1 and r.result_sha]
        if previous is None or not results:
            raise LifecycleError(f"repair revision {task.revision} has no rejected candidate to start from")
        return max(results, key=lambda r: r.completed_at).result_sha

    def _launch(self, obj: Objective, task: EngineeringTask, attempt: Attempt) -> str:
        rt = self._runtime(attempt.attempt_id)
        paths = self._paths(attempt)
        spec = LaunchSpec(
            task_id=task.task_id, task_revision=task.revision, attempt_id=attempt.attempt_id,
            fencing_token=attempt.fencing_token, session_id=attempt.worker.session.session_id,
            workspace=paths["workspace"], home=paths["home"], log_path=paths["log"],
            stderr_path=paths["stderr"], prompt=self.worker_prompt(obj, task, attempt, rt.get("start_sha")),
        )
        try:
            record = self._worker_for(obj).launch(spec)
        except WorkerLaunchError as exc:
            if exc.transient:
                return self._cancel(obj, attempt, f"{TRANSIENT} launch failed: {exc}")
            return self._block(obj, task, f"worker launch refused: {exc}")
        rt.update(phase="launched", pid=record.pid, pid_start_ticks=record.pid_start_ticks,
                  argv=list(record.argv), env_names=list(record.env_names),
                  launched_at=self.now().isoformat(), last_activity_at=self.now().isoformat())
        self._save_runtime(attempt.attempt_id, rt)
        return self._note(obj.objective_id, f"launched {self._worker_for(obj).kind} pid {record.pid} for {attempt.attempt_id} "
                                            f"(session {spec.session_id}); env: {', '.join(record.env_names)}")

    # ------------------------------------------------------------ ASSIGNED / RUNNING
    def _supervise(self, obj: Objective, task: EngineeringTask, state) -> tuple[str | None, bool]:
        attempt = self._current_attempt(task, state)
        rt = self._runtime(attempt.attempt_id)
        paths = self._paths(attempt)
        observations, _ = self._worker_for(obj).read(paths["log"], 0)
        live = self._worker_for(obj).live_pids(_marker(attempt))
        now = self.now()
        launched_at = _parse(rt.get("launched_at"))

        if state.status is TaskStatus.ASSIGNED:
            started = next((o for o in observations if isinstance(o, Started)), None)
            if started is None:
                if live:
                    if launched_at and now - launched_at > timedelta(seconds=self.config.init_timeout_s):
                        self._worker_for(obj).kill(_marker(attempt))
                        return self._cancel(obj, attempt, f"{TRANSIENT} no init event within "
                                                          f"{self.config.init_timeout_s}s"), True
                    return self._note(obj.objective_id, f"{attempt.attempt_id}: process alive, no init event yet"), False
                if rt.get("phase") != "launched":
                    return self._launch(obj, task, attempt), True  # assigned, never launched: launch once
                reason, transient = self._worker_for(obj).diagnose_exit(paths["stderr"])
                if transient:
                    return self._cancel(obj, attempt, f"{TRANSIENT} {reason}"), True
                return self._block(obj, task, reason), True
            spec_like = LaunchSpec(task.task_id, task.revision, attempt.attempt_id, attempt.fencing_token,
                                   attempt.worker.session.session_id, paths["workspace"], paths["home"],
                                   paths["log"], paths["stderr"], "")
            problems = self._worker_for(obj).verify_started(started, spec_like)
            rt["roster"] = {"session_id": started.session_id, "cwd": started.cwd, "model": started.model,
                            "tools": list(started.tools), "mcp_servers": list(started.mcp_servers),
                            "plugins": list(started.plugins), "skills": started.skills,
                            "slash_commands": started.slash_commands, "permission_mode": started.permission_mode,
                            "api_key_source": started.api_key_source, "problems": problems}
            self._save_runtime(attempt.attempt_id, rt)
            if problems:
                self._worker_for(obj).kill(_marker(attempt))
                return self._block(obj, task, "worker launch surface refused: " + "; ".join(problems)), True
            self.kernel.acknowledge(attempt.attempt_id, token=attempt.fencing_token, base_sha=attempt.base_sha)
            return self._note(obj.objective_id, f"{attempt.attempt_id} acknowledged from the worker's init event "
                                                f"(tools {', '.join(started.tools)}; no MCP servers)"), True

        # RUNNING
        if now > self.kernel.lease(attempt)["expires_at"]:
            # Nothing renewed the lease in time (the dispatcher was not observing): the kernel would fence
            # every submission of this attempt, so it is cancelled rather than left to fail late.
            self._worker_for(obj).kill(_marker(attempt))
            return self._cancel(obj, attempt, f"{TRANSIENT} the attempt's lease expired before its result "
                                              "was ingested"), True
        consumed = int(rt.get("consumed", 0))
        fresh = observations[consumed:]
        activities = [o for o in fresh if isinstance(o, Activity)]
        # The result is read from the whole log, not only the unmapped tail: it is terminal and unique, and a
        # dispatcher that died while ingesting it must find it again after a restart.
        finished = next((o for o in observations if isinstance(o, Finished)), None)
        if activities:
            rt["last_activity_at"] = now.isoformat()
            edited = sorted({a.edited for a in activities if a.edited})
            rt["pending_edits"] = sorted(set(rt.get("pending_edits", [])) | set(edited))
            rt["pending_events"] = int(rt.get("pending_events", 0)) + len(activities)
            if any(a.denied for a in activities):
                rt["denials"] = int(rt.get("denials", 0)) + sum(a.denied for a in activities)
        rt["consumed"] = len(observations)
        self._save_runtime(attempt.attempt_id, rt)
        # Edits observed before a result are recorded as progress before the candidate, whatever the interval.
        self._renew(obj, attempt, rt, now, flush_edits=finished is not None)

        if finished is not None:
            return self._finished(obj, task, attempt, finished), True
        if not live:
            reason, transient = self._worker_for(obj).diagnose_exit(paths["stderr"])
            if transient:
                return self._cancel(obj, attempt, f"{TRANSIENT} {reason}"), True
            return self._block(obj, task, reason), True
        last_activity = _parse(rt.get("last_activity_at")) or launched_at or now
        if now - last_activity > timedelta(seconds=self.config.stall_s):
            self._worker_for(obj).kill(_marker(attempt))
            return self._cancel(obj, attempt, f"{TRANSIENT} worker stalled: no event for {self.config.stall_s}s"), True
        if launched_at and now - launched_at > timedelta(seconds=self.config.attempt_timeout_s):
            self._worker_for(obj).kill(_marker(attempt))
            return self._block(obj, task, f"worker exceeded the attempt time limit of {self.config.attempt_timeout_s}s"), True
        return None, False

    def _renew(self, obj: Objective, attempt: Attempt, rt: dict, now: datetime, *, flush_edits: bool = False) -> None:
        """Map observed worker activity onto the kernel: edits are progress, other events liveness."""
        if not rt.get("pending_events"):
            return
        lease = self.kernel.lease(attempt)
        since = (now - lease["last_liveness_at"]).total_seconds()
        workspace = str(self._paths(attempt)["workspace"]) + "/"
        edits = [e.removeprefix(workspace) for e in rt.get("pending_edits", [])]
        if edits and (flush_edits or since >= self.config.progress_interval_s):
            shown = ", ".join(edits[:8]) + (f" and {len(edits) - 8} more" if len(edits) > 8 else "")
            self.kernel.heartbeat(attempt.attempt_id, token=attempt.fencing_token, progress=True,
                                  note=f"worker edited {shown}")
        elif since >= self.config.heartbeat_interval_s:
            self.kernel.heartbeat(attempt.attempt_id, token=attempt.fencing_token,
                                  note=f"{rt['pending_events']} worker stream events observed")
        else:
            return
        rt["pending_edits"], rt["pending_events"] = [], 0
        self._save_runtime(attempt.attempt_id, rt)

    def _finished(self, obj: Objective, task: EngineeringTask, attempt: Attempt, fin: Finished) -> str:
        self._worker_for(obj).kill(_marker(attempt))  # a result is final; nothing of this attempt keeps running
        if fin.status == "blocked":
            return self._block(obj, task, f"worker reported blocked: {fin.reason or fin.summary}")
        if fin.status == "owner_decision_required":
            return self._block(obj, task, f"worker reports an owner decision is required: {fin.reason or fin.summary}",
                               owner=True)
        if fin.status == "error":
            if fin.error_class == "transient":
                return self._cancel(obj, attempt, f"{TRANSIENT} {fin.reason}")
            return self._block(obj, task, fin.reason)
        return self._ingest_candidate(obj, task, attempt, fin)

    def _ingest_candidate(self, obj: Objective, task: EngineeringTask, attempt: Attempt, fin: Finished) -> str:
        rt = self._runtime(attempt.attempt_id)
        paths = self._paths(attempt)
        ws = paths["workspace"]
        info = self.workspaces.recognise(ws)
        first_line = (fin.summary.strip().splitlines() or ["worker result"])[0][:120]
        self.workspaces.commit_all(ws, message=f"{task.task_id} r{task.revision} {attempt.attempt_id}: {first_line}\n\n"
                                               f"Committed by CLIVE from the worker's tree; worker principal "
                                               f"{attempt.worker.principal.principal_id}, session "
                                               f"{attempt.worker.session.session_id}.",
                                   author=f"CLIVE worker {attempt.worker.principal.principal_id} ({attempt.attempt_id})")
        head = self.workspaces.head(ws)
        if head == rt.get("start_sha", task.base_sha):
            return self._cancel(obj, attempt, f"{RESULT_REFUSED} the worker reported completion but changed nothing: "
                                              f"{first_line}")
        self.workspaces.ingest(self.config.repo, ws, branch=info.branch, sha=head)
        changed = self.kernel.git.changed_paths(task.base_sha, head) or ()
        escaped = [p for p in changed if not any(p == a or p.startswith(a + "/") for a in task.allowed_paths)]
        if escaped:
            return self._cancel(obj, attempt, f"{RESULT_REFUSED} candidate {head} changes paths outside the objective's "
                                              f"scope: {', '.join(sorted(escaped)[:10])}")
        evidence_dir = paths["evidence"]
        evidence_dir.mkdir(parents=True, exist_ok=True)
        if obj.checks:
            ok, why = self.checks.availability()
            if not ok:
                return self._block(obj, task, f"check sandbox unavailable ({self.checks.kind}): {why}; the "
                                              f"objective's checks run worker-authored code and are never run "
                                              f"unsandboxed; candidate {head} is kept as history")
        failed = []
        for check in obj.checks:
            outcome = self._run_check(check, ws=ws, head=head, attempt=attempt)
            payload = json.dumps(outcome, indent=2, sort_keys=True).encode()
            file = evidence_dir / f"check-{check.name}.json"
            file.write_bytes(payload)
            self.kernel.record_evidence(attempt.attempt_id, token=attempt.fencing_token, name=f"check-{check.name}",
                                        payload=payload, path=str(file))
            if outcome["exit_code"] != 0:
                failed.append(f"{check.name} (exit {outcome['exit_code']})")
        if failed:
            return self._cancel(obj, attempt, f"{RESULT_REFUSED} checks failed on {head}: {', '.join(failed)}")
        transcript = paths["log"].read_bytes()
        self.kernel.record_evidence(attempt.attempt_id, token=attempt.fencing_token, name="worker_transcript",
                                    payload=transcript, path=str(paths["log"]))
        report = json.dumps({"status": fin.status, "summary": fin.summary, "reason": fin.reason,
                             "result": fin.detail, "launch": {k: rt.get(k) for k in ("argv", "env_names", "roster")},
                             "committed_head": head}, indent=2, sort_keys=True, default=str).encode()
        (evidence_dir / "worker_report.json").write_bytes(report)
        self.kernel.record_evidence(attempt.attempt_id, token=attempt.fencing_token, name="worker_report",
                                    payload=report, path=str(evidence_dir / "worker_report.json"))
        published = self._publish(task, head)
        if published is not None:
            return self._block(obj, task, published)
        dirty = self.workspaces.dirty_paths(ws)
        self.kernel.record_candidate(attempt.attempt_id, token=attempt.fencing_token, sha=head,
                                     evidence_satisfied=task.required_evidence, clean_worktree=not dirty,
                                     remote=self.config.publish_remote)
        return self._note(obj.objective_id, f"candidate {head} recorded for {attempt.attempt_id} "
                                            f"({len(changed)} paths; checks passed: {len(obj.checks)})")

    def _run_check(self, check, *, ws: Path, head: str, attempt: Attempt) -> dict:
        """One check, on a fresh export of exactly the candidate, inside the sandbox. Never on the host."""
        tree = self.workspaces.export(ws, head, self._paths(attempt)["checks"] / check.name)
        started = self.now()
        outcome = self.checks.run(tuple(check.argv), tree=tree, cwd=check.cwd, timeout_s=check.timeout_s)
        return {"name": check.name, "argv": list(check.argv), "cwd": check.cwd, "head": head,
                "started_at": started.isoformat(), **outcome}

    def _publish(self, task: EngineeringTask, sha: str) -> str | None:
        """Move the target branch forward to the candidate. Returns a blocker reason, or None."""
        repo = self.config.repo
        current = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if current == task.target_branch:
            return (f"the dispatcher's repository has the target branch {task.target_branch} checked out; "
                    "use a dedicated dispatcher clone")
        old = self.kernel.git.rev_parse(f"refs/heads/{task.target_branch}")
        if old is not None and old != sha and not self.kernel.git.is_ancestor(old, sha):
            return f"target branch {task.target_branch} is at {old}, which the candidate {sha} does not descend from"
        git(repo, "update-ref", f"refs/heads/{task.target_branch}", sha, *( [old] if old else ["0" * 40]))
        if self.config.publish_remote:
            proc = subprocess.run(["git", "push", "--quiet", self.config.publish_remote,
                                   f"{sha}:refs/heads/{task.target_branch}"],
                                  cwd=str(repo), capture_output=True, text=True, timeout=180)
            if proc.returncode != 0:
                return f"publishing {sha} to {self.config.publish_remote}/{task.target_branch} failed: {proc.stderr.strip()[:300]}"
            if self.kernel.git.remote_head(self.config.publish_remote, task.target_branch) != sha:
                return f"{self.config.publish_remote}/{task.target_branch} does not resolve to {sha} after the push"
        return None

    # ------------------------------------------------------------ EVIDENCE_READY / REVIEWING
    def _dispatch_review(self, obj: Objective, task: EngineeringTask, state) -> tuple[str | None, bool]:
        attempt = self._current_attempt(task, state)
        result = next(r for r in self.store.read_results()
                      if r.task_id == task.task_id and r.attempt_id == attempt.attempt_id)
        author = attempt.worker.principal.principal_id.strip().casefold()
        gaps: list[str] = []
        chosen: ReviewerDriver | None = None
        for reviewer in self.reviewers:
            who = reviewer.principal_id
            if who.strip().casefold() == author:
                gaps.append(f"{who}: is the author principal")
                continue
            if not self.kernel.registry.may_review(who):
                gaps.append(f"{who}: not registered to review")
                continue
            ok, why = reviewer.availability()
            if not ok:
                gaps.append(f"{who}: {why}")
                continue
            chosen = reviewer
            break
        if chosen is None:
            reason = f"no eligible independent reviewer is available for candidate {result.result_sha}: " + (
                "; ".join(gaps) or "no reviewer driver is configured")
            return self._block(obj, task, reason), True
        packet = self.review_packet(obj, task, attempt, result, chosen)
        head = self._target_head(task) or ""
        dispatch = self.kernel.dispatch_review(attempt.attempt_id, reviewer_principal_id=chosen.principal_id,
                                               packet=packet, current_head=head)
        ctx = self._review_ctx(task, attempt, dispatch.dispatch_seq, dispatch.candidate_sha, dispatch.packet_path)
        chosen.start(ctx)
        rt = self._runtime(attempt.attempt_id)
        rt["review"] = {"dispatch_seq": dispatch.dispatch_seq, "principal_id": chosen.principal_id,
                        "mechanism": chosen.mechanism, "courier": chosen.courier, "consumed": []}
        self._save_runtime(attempt.attempt_id, rt)
        courier = " (COURIER: a person must carry the packet and the result)" if chosen.courier else ""
        return self._note(obj.objective_id, f"review of {dispatch.candidate_sha} dispatched to {chosen.principal_id} "
                                            f"via {chosen.mechanism}{courier}"), True

    def _review_ctx(self, task, attempt, seq: int, sha: str, packet_path: str) -> ReviewContext:
        return ReviewContext(task_id=task.task_id, task_revision=task.revision, attempt_id=attempt.attempt_id,
                             dispatch_seq=seq, candidate_sha=sha, packet_path=self.store.root / packet_path)

    def _review_problem(self, task: EngineeringTask, state) -> str | None:
        attempt = self._current_attempt(task, state)
        dispatches = self.store.read_dispatches(task.task_id, attempt.attempt_id)
        if not dispatches:
            return None
        dispatch = dispatches[-1]
        driver = next((r for r in self.reviewers if r.principal_id == dispatch.reviewer_principal_id), None)
        ctx = self._review_ctx(task, attempt, dispatch.dispatch_seq, dispatch.candidate_sha, dispatch.packet_path)
        return _review_problem_of(driver, ctx)

    def _collect_review(self, obj: Objective, task: EngineeringTask, state) -> tuple[str | None, bool]:
        attempt = self._current_attempt(task, state)
        dispatch = self.store.read_dispatches(task.task_id, attempt.attempt_id)[-1]
        driver = next((r for r in self.reviewers if r.principal_id == dispatch.reviewer_principal_id), None)
        if driver is None:
            return self._note(obj.objective_id, f"awaiting review from {dispatch.reviewer_principal_id}; no driver "
                                                "for it is configured in this dispatcher"), False
        ctx = self._review_ctx(task, attempt, dispatch.dispatch_seq, dispatch.candidate_sha, dispatch.packet_path)
        driver.start(ctx)  # idempotent: a restart between dispatch and start loses nothing
        rt = self._runtime(attempt.attempt_id)
        review = rt.setdefault("review", {"dispatch_seq": dispatch.dispatch_seq, "consumed": []})
        consumed = set(review.get("consumed", []))
        payload = next((p for p in driver.poll(ctx) if sha256_of(p) not in consumed), None)
        if payload is None:
            problem = driver.problem(ctx) if hasattr(driver, "problem") else None
            if problem and hasattr(driver, "exhausted") and driver.exhausted(ctx):
                return self._block(obj, task, f"review of {dispatch.candidate_sha} could not be obtained: {problem}"), True
            last = f" (last run: {problem})" if problem else ""
            return self._note(obj.objective_id, f"awaiting the typed review of {dispatch.candidate_sha} from "
                                                f"{dispatch.reviewer_principal_id} via {driver.mechanism}{last}"), False
        review.setdefault("consumed", []).append(sha256_of(payload))
        self._save_runtime(attempt.attempt_id, rt)
        try:
            typed = ReviewResult.model_validate_json(payload)
        except ValueError as exc:
            return self._note(obj.objective_id, f"review result refused before the kernel: not a valid "
                                                f"clive.review_result.v1 ({str(exc).splitlines()[0][:200]})"), True
        if (typed.task_id, typed.task_revision, typed.attempt_id) != (task.task_id, task.revision, attempt.attempt_id):
            return self._note(obj.objective_id, f"stale review result refused: it judges {typed.task_id} "
                                                f"r{typed.task_revision} {typed.attempt_id}, not the current "
                                                f"{attempt.attempt_id}"), True
        admission = self.kernel.admit_verdict(attempt.attempt_id, reviewer=typed.reviewer.party(),
                                              verdict=typed.kernel_verdict, payload=payload,
                                              observed_candidate_sha=typed.candidate_sha,
                                              current_head=self._target_head(task) or "")
        refused = admission.outcome is VerdictOutcome.REFUSED
        detail = ": " + ", ".join(admission.reasons) if refused else ""
        # True either way: a refused verdict changed no stage, but it consumed a submission, and the
        # next one (if any) is read in the same tick.
        return self._note(obj.objective_id, f"verdict {typed.verdict} on {typed.candidate_sha} from "
                                            f"{typed.reviewer.principal_id}: {admission.outcome.value}{detail}"), True

    # ------------------------------------------------------------ REJECTED
    def _route_repair(self, obj: Objective, task: EngineeringTask, state) -> tuple[str | None, bool]:
        attempt = self._current_attempt(task, state)
        admissions = [a for a in self.store.read_admissions(task.task_id, attempt.attempt_id)
                      if a.outcome is VerdictOutcome.REJECTED_BY_VERDICT]
        if not admissions:
            return self._block(obj, task, "REJECTED without an admitted CHANGES_REQUIRED verdict on record"), True
        admission = admissions[-1]
        rounds = sum(1 for t in self.store.read_tasks() if t.task_id == task.task_id and t.kind is TaskKind.REPAIR)
        findings = ReviewResult.model_validate_json((self.store.root / admission.payload_path).read_bytes()).material_findings
        ids = ", ".join(f.finding_id for f in findings)
        if rounds >= obj.max_repair_rounds:
            return self._block(obj, task, f"convergence limit: {rounds} repair round(s) used of {obj.max_repair_rounds}; "
                                          f"findings {ids} on {admission.evidence.candidate_sha} remain; the owner "
                                          "decides how to proceed"), True
        repair = EngineeringTask(
            task_id=task.task_id, revision=task.revision + 1, stream_id=task.stream_id, kind=TaskKind.REPAIR,
            objective=(f"Repair of rejected candidate {admission.evidence.candidate_sha} ({task.task_id} r{task.revision} "
                       f"{attempt.attempt_id}) for material findings {ids} only; objective {obj.objective_id} "
                       "unchanged"),
            repository=task.repository, base_sha=task.base_sha, target_branch=task.target_branch,
            product_memory_sha=task.product_memory_sha, allowed_paths=task.allowed_paths,
            prohibited_actions=task.prohibited_actions, required_evidence=task.required_evidence,
            reviewer_must_be_independent=True,
            authorising_reference=(
                f"CHANGES_REQUIRED from {admission.evidence.reviewer.principal.principal_id} admitted at "
                f"reviews/{task.task_id}/{attempt.attempt_id}/verdict.{admission.admission_seq}.json (payload sha256 "
                f"{admission.evidence.evidence_sha256}) on {admission.evidence.candidate_sha}; repair routed by the "
                f"dispatcher within objective {obj.objective_id} (round {rounds + 1} of {obj.max_repair_rounds})"),
            created_at=self.now(),
        )
        self.kernel.create_task(repair)
        return self._note(obj.objective_id, f"repair revision r{repair.revision} routed for findings {ids} on "
                                            f"{admission.evidence.candidate_sha}"), True

    # ------------------------------------------------------------ ACCEPTED
    def _integrate(self, obj: Objective, task: EngineeringTask, state) -> tuple[str | None, bool]:
        acceptance = [a for a in self.store.read_acceptances(task.task_id) if a.attempt_id == state.attempt_id][-1]
        head = self._target_head(task)
        if head != acceptance.accepted_sha:
            return self._block(obj, task, f"target branch {task.target_branch} is at {head}, not the accepted "
                                          f"{acceptance.accepted_sha}; integration refused"), True
        self.kernel.integrate(task.task_id, task.revision, integration_sha=acceptance.accepted_sha,
                              target_base_sha=task.base_sha, method=IntegrationMethod.FAST_FORWARD,
                              integrated_by=f"clive-dispatcher ({self.kernel.operator})",
                              remote=self.config.publish_remote)
        return self._note(obj.objective_id, f"accepted {acceptance.accepted_sha} integrated on {task.target_branch} "
                                            "(fast-forward, target ref verified); not deployed"), True

    # ------------------------------------------------------------ kernel shorthands
    def _block(self, obj: Objective, task: EngineeringTask, reason: str, *, owner: bool = False) -> str:
        self.kernel.block(task.task_id, task.revision, reason=reason[:990],
                          blocker_class=BlockerClass.OWNER_ONLY if owner else BlockerClass.DETERMINISTIC,
                          owner_gate=owner)
        return self._note(obj.objective_id, f"{'OWNER_GATE' if owner else 'BLOCKED'}: {reason}")

    def _cancel(self, obj: Objective, attempt: Attempt, reason: str) -> str:
        self._worker_for(obj).kill(_marker(attempt))
        self.kernel.cancel_attempt(attempt.attempt_id, reason=reason[:990])
        return self._note(obj.objective_id, f"{attempt.attempt_id} cancelled: {reason}")

    # ------------------------------------------------------------ texts
    def worker_prompt(self, obj: Objective, task: EngineeringTask, attempt: Attempt, start_sha: str | None) -> str:
        if obj.builder == "integrator":
            return json.dumps({"base": start_sha or task.base_sha, "integrate": list(obj.integrates)})
        lines = [
            "You are an isolated CLIVE engineering builder. CLIVE owns the task, its lifecycle, its evidence and its",
            "acceptance; you produce a change in this workspace and a structured report, nothing else.",
            "",
            f"TASK {task.task_id} revision {task.revision} ({task.kind.value}), attempt {attempt.attempt_id}, "
            f"fencing token {attempt.fencing_token}",
            f"BASE {task.base_sha}; your workspace (the current directory) is a private checkout at "
            f"{start_sha or task.base_sha} with no remote.",
            "",
            f"OBJECTIVE — {obj.title} (the owner's words, verbatim):",
            obj.requested_outcome,
            "",
        ]
        if obj.acceptance_criteria:
            lines += ["ACCEPTANCE CRITERIA:", *(f"- {c}" for c in obj.acceptance_criteria), ""]
        if obj.checks:
            lines += ["CHECKS CLIVE WILL RUN on your result (they must pass):",
                      *(f"- {c.name}: {' '.join(c.argv)} (in {c.cwd})" for c in obj.checks), ""]
        lines += ["ALLOWED PATHS — change files only inside these:", *(f"- {p}" for p in task.allowed_paths), "",
                  "PROHIBITED:", *(f"- {p}" for p in task.prohibited_actions), ""]
        if task.kind is TaskKind.REPAIR:
            lines += self._repair_brief(task)
        refusals = [h for h in self._revision_history(task) if h[1].startswith(RESULT_REFUSED)]
        if refusals:
            lines += ["AN EARLIER ATTEMPT OF THIS REVISION WAS REFUSED BY CLIVE:", *(f"- {h[1]}" for h in refusals), ""]
            lines += self._failed_check_output(refusals[-1][0])
        lines += [
            "RULES:",
            "- Use only the file tools, only inside the allowed paths. Do not commit: CLIVE commits your tree and",
            "  takes the candidate identity from git.",
            "- You have no network, no credentials and no business systems. Never try to deploy, send, or change",
            "  runtime, secrets, permissions or anything outside this repository.",
            "- Make the smallest change that meets the objective. No speculative cleanup.",
            "- Finish with the structured report: status 'completed' when the change is made; 'blocked' when you",
            "  cannot make it (say exactly why in reason); 'owner_decision_required' when it needs something only",
            "  the owner can authorise (credentials, deployment, spend, permissions, a product decision).",
            "- Your report is not evidence of success: CLIVE runs the checks and an independent reviewer judges",
            "  the exact commit.",
        ]
        return "\n".join(lines)

    def _repair_brief(self, task: EngineeringTask) -> list[str]:
        rejected = self._rejected_candidate(task)
        lines = [f"REPAIR: the workspace starts at the rejected candidate {rejected}. Fix exactly these material",
                 "findings and nothing else:"]
        for finding in self._findings_for(task.task_id, task.revision - 1):
            lines += [f"- [{finding.finding_id}] {finding.finding}", f"  evidence: {finding.evidence_ref}",
                      f"  required repair: {finding.required_repair}"]
        return [*lines, ""]

    def _findings_for(self, task_id: str, revision: int):
        out = []
        for attempt in self.store.read_attempts(task_id):
            if attempt.task_revision != revision:
                continue
            for admission in self.store.read_admissions(task_id, attempt.attempt_id):
                if admission.outcome is VerdictOutcome.REJECTED_BY_VERDICT:
                    typed = ReviewResult.model_validate_json((self.store.root / admission.payload_path).read_bytes())
                    out.extend(typed.material_findings)
        return out

    def review_packet(self, obj: Objective, task: EngineeringTask, attempt: Attempt, result, reviewer) -> bytes:
        diff = git(self.config.repo, "diff", "--no-renames", "--stat", "--patch", task.base_sha, result.result_sha,
                   check=False)
        truncated = len(diff) > self.config.packet_diff_limit
        events = self.store.read_events(task.task_id, attempt.attempt_id)
        evidence = [e for e in events if e.kind is EventKind.EVIDENCE]
        checks_dir = self._paths(attempt)["evidence"]
        header = {
            "task_id": task.task_id, "task_revision": task.revision, "attempt_id": attempt.attempt_id,
            "candidate_sha": result.result_sha, "base_sha": task.base_sha, "target_branch": task.target_branch,
            "repository": task.repository, "author_principal": attempt.worker.principal.principal_id,
            "author_session": attempt.worker.session.session_id, "reviewer_principal": reviewer.principal_id,
            "review_mechanism": reviewer.mechanism, "courier": reviewer.courier,
        }
        prior = []
        for revision in range(1, task.revision):
            prior.extend(self._findings_for(task.task_id, revision))
        lines = [
            f"# CLIVE review packet — {task.task_id} r{task.revision} {attempt.attempt_id}",
            "",
            "```json", json.dumps(header, indent=2, sort_keys=True), "```",
            "",
            f"Your verdict applies to exactly `{result.result_sha}` and to nothing else.",
            "",
            f"## Objective — {obj.title} (the owner's words)", "", obj.requested_outcome, "",
            "## Acceptance criteria", *(f"- {c}" for c in obj.acceptance_criteria or ("(none stated)",)), "",
            "## Scope", *(f"- allowed: `{p}`" for p in task.allowed_paths),
            *(f"- prohibited: {p}" for p in task.prohibited_actions), "",
            "## Evidence recorded by CLIVE (name, sha256)", *(f"- `{e.evidence_name}` {e.evidence_sha256}" for e in evidence), "",
        ]
        for check in obj.checks:
            file = checks_dir / f"check-{check.name}.json"
            if file.exists():
                data = json.loads(file.read_text())
                lines += [f"### check `{check.name}`: exit {data['exit_code']}", "```",
                          (data.get("stdout_tail") or "")[-1500:], "```"]
        lines += ["", "## Changed paths (git diff --no-renames, base..candidate)", *(f"- `{p}`" for p in result.changed_paths), ""]
        if prior:
            lines += ["## Findings of earlier revisions (this candidate is their repair)",
                      *(f"- [{f.finding_id}] {f.finding} — required: {f.required_repair}" for f in prior), ""]
        lines += [f"## Diff{' (truncated; fetch the SHA for the rest)' if truncated else ''}", "```diff",
                  diff[: self.config.packet_diff_limit], "```", "",
                  "## How to answer",
                  "Return exactly one JSON object of schema `clive.review_result.v1`: `verdict` is `READY` or",
                  "`CHANGES_REQUIRED`; every material finding has `finding_id`, `material: true`, `finding`,",
                  "`evidence_ref` and a bounded `required_repair`; `reviewer` states your principal, session and a",
                  "read-only, clean workspace at the candidate SHA. Prose in `summary` is for people and decides",
                  "nothing. The JSON schema:", "```json",
                  json.dumps(ReviewResult.model_json_schema(), indent=1, sort_keys=True), "```", ""]
        return "\n".join(lines).encode("utf-8")

    # ------------------------------------------------------------ observability
    def status(self) -> list[dict]:
        """What a person needs to know per objective. Read-only; nothing is inferred beyond the records."""
        now = self.now()
        view = {(t["task_id"], t["revision"]): t for t in lifecycle_view(self.store, now=now)["tasks"]}
        out = []
        for obj in self.objectives.read_all():
            task, state = self._latest(obj.objective_id)
            if task is None or state is None:
                out.append({"objective_id": obj.objective_id, "title": obj.title, "stage": "NO_TASK",
                            "next_action": "re-run intake"})
                continue
            record = view.get((task.task_id, task.revision), {})
            item = {
                "objective_id": obj.objective_id, "title": obj.title, "task_id": task.task_id,
                "revision": task.revision, "kind": task.kind.value, "stage": record.get("stage"),
                "stage_reason": record.get("stage_reason"), "attempt_id": state.attempt_id,
                "worker": record.get("dispatch_identity"), "last_heartbeat": record.get("last_heartbeat"),
                "last_progress": next((h["at"] for h in reversed(record.get("history", [])) if h["kind"] == "progress"), None),
                "lease": record.get("lease"), "candidate_sha": record.get("candidate_sha"),
                "review": record.get("review"), "acceptance": record.get("acceptance"),
                "integration": record.get("integration"), "blocker": state.blocker_reason,
                "blocker_class": state.blocker_class.value, "next_action": NEXT_ACTION.get(state.status, state.status.value),
            }
            if state.attempt_id:
                rt = self._runtime(state.attempt_id)
                pids = self._worker_for(obj).live_pids(_marker(self._current_attempt(task, state)))
                item["process"] = {"alive": bool(pids), "pids": pids, "launched_at": rt.get("launched_at"),
                                   "last_observed_event_at": rt.get("last_activity_at"),
                                   "observed_roster": rt.get("roster"), "permission_denials": rt.get("denials", 0)}
                item["review_mechanism"] = rt.get("review")
                if state.status is TaskStatus.REVIEWING:
                    item["review_problem"] = self._review_problem(task, state)
            out.append(item)
        return out


def _review_problem_of(driver, ctx) -> str | None:
    return driver.problem(ctx) if driver is not None and hasattr(driver, "problem") else None


def _marker(attempt: Attempt) -> str:
    return worker_marker(attempt.attempt_id, attempt.worker.session.session_id)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

