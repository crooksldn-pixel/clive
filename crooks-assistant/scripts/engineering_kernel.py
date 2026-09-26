#!/usr/bin/env python3
"""The kernel's verbs, from a shell. CLIVE authors its engineering lifecycle here.

    engineering_kernel.py --store <root> --repo <checkout> [--registry F] [--operator NAME] VERB ...

Verbs, in lifecycle order: task, assign, ack, heartbeat, evidence, candidate, dispatch,
verdict, integrate; and cancel, block, resume, gate, verify-judgment, view. Each holds the
store's writer lock
for its whole duration, validates everything before it writes anything, writes immutable
records plus one compare-and-swap state transition, regenerates ACTIVE_STATE.json, and
journals the change as a git commit when the store lives in a checkout. A refusal prints
the reason and exits 2; nothing is written, and anything written before a late refusal is
rolled back.

Nothing here runs a worker, a watcher, a service or a deployment. The store is the
authoritative record of the lifecycle; processes and branches are what the projection
reconciles against it.

The GitHub acceptance gate (owner's loop update, OWNER_DECISIONS_2026-09-25.md) holds here
exactly as in the dispatcher: a ``ready`` verdict, which records an acceptance, is submitted
only while GitHub's ``acceptance`` run is green on the attempt's exact candidate SHA, and
``integrate`` only while it is green on the integrated SHA and on the accepted SHA. Anything
else (red, pending, missing, or GitHub unavailable) refuses the verb before it writes to the
store, exit 2, naming the SHA, the gate's answer and what to do. There is no bypass. Each
answer is recorded where the dispatcher records its own (``--runtime-root``: the attempt's
runtime notes and ``evidence/<attempt>/github-acceptance.json``, which the status projection
reads), under the dispatcher's runtime lock; exit 4 means a dispatcher tick held that lock
for longer than ``--lock-timeout``. An integration's gates evidence is the green answers it
rests on (``evidence/<attempt>/integration-gates.json``), binding ``--gates-evidence`` by
digest when given. GitHub is asked with the credential git already holds for
``--github-remote``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.orchestrator.contracts import (  # noqa: E402
    BlockerClass,
    EngineeringTask,
    TaskKind,
    validate_exact_sha,
)
from app.orchestrator.dispatcher import (  # noqa: E402
    DispatcherBusy,
    record_gate_answer,
    runtime_lock,
    write_integration_gates,
)
from app.orchestrator.github_acceptance import (  # noqa: E402
    AcceptanceChecks,
    GateState,
    GitHubAcceptance,
    ask,
    git_remote_token,
)
from app.orchestrator.lifecycle import (  # noqa: E402
    Attempt,
    GitFacts,
    IntegrationMethod,
    JournalError,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
    lifecycle_view,
    sha256_of,
)
from app.orchestrator.review_acceptance import ReviewVerdict  # noqa: E402
from app.orchestrator.routing import (  # noqa: E402
    Party,
    Principal,
    PrincipalKind,
    SessionContext,
    Workspace,
)
from app.orchestrator.store import RecordConflictError, StateConflictError  # noqa: E402

DEFAULT_REGISTRY = ROOT / "config" / "review_principals.json"


def _iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SystemExit("timestamps must carry a timezone, e.g. 2026-09-22T21:00:00Z")
    return parsed


def _party(args, prefix: str) -> Party:
    get = lambda name: getattr(args, f"{prefix}_{name}")  # noqa: E731
    return Party(
        principal=Principal(principal_id=get("principal"), kind=PrincipalKind(get("principal_kind"))),
        session=SessionContext(
            session_id=get("session"),
            context_is_fresh=not getattr(args, f"{prefix}_context_inherited", False),
            started_at=_iso(get("session_started")) or datetime.now(UTC),
        ),
        workspace=Workspace(
            workspace_id=get("workspace_id"),
            branch=get("workspace_branch"),
            head_sha=get("workspace_head"),
            read_only=bool(getattr(args, f"{prefix}_read_only", False)),
            clean=not bool(getattr(args, f"{prefix}_dirty", False)),
        ),
    )


def _party_flags(parser: argparse.ArgumentParser, prefix: str, *, reviewer: bool) -> None:
    p = parser.add_argument
    p(f"--{prefix}-principal", dest=f"{prefix}_principal", required=True)
    p(f"--{prefix}-principal-kind", dest=f"{prefix}_principal_kind", default="model",
      choices=[k.value for k in PrincipalKind])
    p(f"--{prefix}-session", dest=f"{prefix}_session", required=True)
    p(f"--{prefix}-session-started", dest=f"{prefix}_session_started", default=None)
    p(f"--{prefix}-context-inherited", dest=f"{prefix}_context_inherited", action="store_true")
    p(f"--{prefix}-workspace-id", dest=f"{prefix}_workspace_id", required=True)
    p(f"--{prefix}-workspace-branch", dest=f"{prefix}_workspace_branch", required=True)
    p(f"--{prefix}-workspace-head", dest=f"{prefix}_workspace_head", required=True)
    if reviewer:
        p(f"--{prefix}-read-only", dest=f"{prefix}_read_only", action="store_true")
        p(f"--{prefix}-dirty", dest=f"{prefix}_dirty", action="store_true")


def _when_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--at", default=None, help="record time; the past needs --backfilled")
    parser.add_argument("--backfilled", action="store_true")
    parser.add_argument("--evidence-ref", default=None, help="what a backfilled record was taken from")


def _current_head(kernel: Kernel, args, task_branch: str) -> str:
    if getattr(args, "current_head", None):
        return args.current_head
    head = kernel.git.rev_parse(f"refs/remotes/origin/{task_branch}") or kernel.git.rev_parse(task_branch)
    if head is None:
        raise SystemExit(f"cannot resolve the current head of {task_branch}; pass --current-head")
    return head


# What the operator can do about each answer that is not green.
_NEXT_STEP = {
    GateState.RED: "a completed acceptance run on it is not successful: re-run the workflow on that exact SHA "
                   "until it is green, or record a new candidate",
    GateState.PENDING: "its acceptance run has not finished: run this verb again once it is green",
    GateState.MISSING: "no acceptance run exists for it: push that SHA to a branch so the workflow runs on it, "
                       "then run this verb again once it is green",
    GateState.UNAVAILABLE: "GitHub could not be asked or gave an answer the gate will not decide on: check the "
                           "credential git holds for --github-remote, then run this verb again",
}


def acceptance_gate(args) -> AcceptanceChecks:
    """The GitHub acceptance gate, asking with the credential git holds for ``--github-remote``."""
    return GitHubAcceptance(git_remote_token(Path(args.repo), args.github_remote))


def _require_green(kernel: Kernel, args, attempt: Attempt, shas: tuple[str, ...], step: str) -> list[dict]:
    """Ask the gate about each exact SHA and record every answer; refuse, before any store write, unless
    all are green. The caller holds the runtime lock."""
    task = kernel._task(attempt.task_id, attempt.task_revision)
    gate = acceptance_gate(args)
    records = []
    for sha in dict.fromkeys(shas):
        result = ask(gate, task.repository, sha)
        record = result.record(checked_at=datetime.now(UTC))
        where = record_gate_answer(Path(args.runtime_root), attempt.attempt_id, record)
        records.append(record)
        if not result.green:
            raise LifecycleError(
                f"GitHub acceptance is not green on {sha} ({result.state.value}: {result.detail}); {step} only after "
                f"a green GitHub acceptance run on that exact SHA (owner's loop update, OWNER_DECISIONS_2026-09-25). "
                f"Nothing was written to the store; the gate's answer is recorded in {where}. Next: "
                f"{_NEXT_STEP[result.state]}"
            )
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True, help="store root (the engineering/ directory)")
    parser.add_argument("--repo", default=str(ROOT.parent), help="git checkout answering commit questions")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--operator", default="unnamed operator")
    parser.add_argument("--no-journal", action="store_true", help="do not git-commit the store")
    parser.add_argument("--lock-timeout", type=float, default=10.0,
                        help="seconds to wait for the store's writer lock (and, for verdict and integrate, the "
                             "dispatcher's runtime lock) before refusing")
    parser.add_argument("--runtime-root", default="/opt/crooks-workers/runtime",
                        help="the dispatcher's runtime root, where verdict and integrate record the GitHub "
                             "acceptance gate's answers")
    parser.add_argument("--github-remote", default="origin",
                        help="configured remote (never a URL) whose git credential the GitHub acceptance gate reuses")
    sub = parser.add_subparsers(dest="verb", required=True)

    t = sub.add_parser("task", help="record an authorised task revision")
    t.add_argument("--task-id", required=True)
    t.add_argument("--revision", type=int, required=True)
    t.add_argument("--stream", required=True)
    t.add_argument("--kind", required=True, choices=[k.value for k in TaskKind])
    t.add_argument("--objective", required=True)
    t.add_argument("--repository", required=True)
    t.add_argument("--base-sha", required=True)
    t.add_argument("--target-branch", required=True)
    t.add_argument("--product-memory-sha", required=True)
    t.add_argument("--authorising-reference", required=True)
    t.add_argument("--allowed-path", action="append", default=[])
    t.add_argument("--prohibited-action", action="append", default=[])
    t.add_argument("--required-evidence", action="append", default=[])
    t.add_argument("--predecessor", action="append", default=[])
    t.add_argument("--priority", type=int, default=0)
    t.add_argument("--not-independent", action="store_true", help="review need not be independent (rare)")
    t.add_argument("--created-at", default=None)

    a = sub.add_parser("assign", help="assignment, fenced attempt, lease and dispatch identity")
    a.add_argument("--task-id", required=True)
    a.add_argument("--revision", type=int, required=True)
    a.add_argument("--worker-id", required=True, help="the roster worker id")
    _party_flags(a, "worker", reviewer=False)
    a.add_argument("--lease-s", type=int, default=900)
    a.add_argument("--attempt-id", default=None)
    _when_flags(a)

    k = sub.add_parser("ack", help="the worker acknowledges revision, base and token")
    k.add_argument("--attempt-id", required=True)
    k.add_argument("--token", type=int, required=True)
    k.add_argument("--base-sha", required=True)
    _when_flags(k)

    h = sub.add_parser("heartbeat", help="liveness; --progress when something moved")
    h.add_argument("--attempt-id", required=True)
    h.add_argument("--token", type=int, required=True)
    h.add_argument("--note", default=None)
    h.add_argument("--progress", action="store_true")
    _when_flags(h)

    e = sub.add_parser("evidence", help="record an artifact by name and digest")
    e.add_argument("--attempt-id", required=True)
    e.add_argument("--token", type=int, required=True)
    e.add_argument("--name", required=True)
    e.add_argument("--file", required=True)
    _when_flags(e)

    c = sub.add_parser("candidate", help="record the immutable candidate SHA")
    c.add_argument("--attempt-id", required=True)
    c.add_argument("--token", type=int, required=True)
    c.add_argument("--sha", required=True)
    c.add_argument("--changed-path", action="append", default=[],
                   help="optional declaration; must equal the git diff exactly (the record uses git)")
    c.add_argument("--evidence-satisfied", action="append", default=[])
    c.add_argument("--dirty", action="store_true", help="the worktree was not clean (refused later by policy)")
    c.add_argument("--verify-remote", default=None, help="remote whose target branch must equal the SHA")
    _when_flags(c)

    d = sub.add_parser("dispatch", help="hand the exact candidate to an independent reviewer")
    d.add_argument("--attempt-id", required=True)
    d.add_argument("--reviewer", required=True, help="reviewer principal id")
    d.add_argument("--packet", required=True, help="the review packet file, kept in the store")
    d.add_argument("--current-head", default=None)
    _when_flags(d)

    v = sub.add_parser("verdict", help="admit or refuse a reviewer's exact-SHA verdict")
    v.add_argument("--attempt-id", required=True)
    _party_flags(v, "reviewer", reviewer=True)
    v.add_argument("--verdict", required=True, choices=[x.value for x in ReviewVerdict])
    v.add_argument("--observed-sha", required=True, help="the SHA the reviewer says it reviewed")
    v.add_argument("--evidence", required=True, help="the verdict text, kept in the store")
    v.add_argument("--current-head", default=None)
    _when_flags(v)

    i = sub.add_parser("integrate", help="record a verified integration of the accepted SHA")
    i.add_argument("--task-id", required=True)
    i.add_argument("--revision", type=int, required=True)
    i.add_argument("--integration-sha", required=True)
    i.add_argument("--target-base-sha", required=True)
    i.add_argument("--method", required=True, choices=[m.value for m in IntegrationMethod])
    i.add_argument("--integrated-by", required=True)
    i.add_argument("--verify-remote", default=None,
                   help="remote whose target branch must resolve to the SHA; without it the local ref must")
    i.add_argument("--gates-evidence", default=None)

    x = sub.add_parser("cancel", help="fence an attempt for good")
    x.add_argument("--attempt-id", required=True)
    x.add_argument("--reason", required=True)

    b = sub.add_parser("block", help="record a blocker or owner gate")
    b.add_argument("--task-id", required=True)
    b.add_argument("--revision", type=int, required=True)
    b.add_argument("--class", dest="blocker_class", required=True, choices=[c.value for c in BlockerClass if c is not BlockerClass.NONE])
    b.add_argument("--reason", required=True)
    b.add_argument("--owner-gate", action="store_true")

    r = sub.add_parser("resume", help="lift a blocker (never an owner gate); the stage is recomputed from the records")
    r.add_argument("--task-id", required=True)
    r.add_argument("--revision", type=int, required=True)
    r.add_argument("--note", required=True)

    g = sub.add_parser("gate", help="print the owner gate as the proposal an owner judgment must be about")
    g.add_argument("--task-id", required=True)
    g.add_argument("--revision", type=int, required=True)

    j = sub.add_parser("verify-judgment", help="check whether an owner judgment binds to a gate; lifts nothing")
    j.add_argument("--task-id", required=True)
    j.add_argument("--revision", type=int, required=True)
    j.add_argument("--owner-judgment", required=True, help="a judgment id from the owner's ledger")
    j.add_argument("--owner-ledger", required=True, help="the owner's ledger (JSON lines of judgments); read only")

    w = sub.add_parser("view", help="print what the records say")
    w.add_argument("--json", action="store_true")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = LifecycleStore(Path(args.store))
    kernel = Kernel(
        store=store,
        registry=PrincipalRegistry.load(Path(args.registry)),
        git=GitFacts(Path(args.repo)),
        operator=args.operator,
        journal=not args.no_journal,
        lock_timeout_s=args.lock_timeout,
    )
    when = dict(at=_iso(getattr(args, "at", None)), backfilled=getattr(args, "backfilled", False),
                evidence_ref=getattr(args, "evidence_ref", None))
    gated: list[dict] = []
    try:
        if args.verb == "task":
            task = EngineeringTask(
                task_id=args.task_id, revision=args.revision, stream_id=args.stream,
                kind=TaskKind(args.kind), objective=args.objective, repository=args.repository,
                base_sha=args.base_sha, target_branch=args.target_branch,
                product_memory_sha=args.product_memory_sha,
                allowed_paths=tuple(args.allowed_path), prohibited_actions=tuple(args.prohibited_action),
                predecessor_task_ids=tuple(args.predecessor), required_evidence=tuple(args.required_evidence),
                reviewer_must_be_independent=not args.not_independent,
                authorising_reference=args.authorising_reference, priority=args.priority,
                created_at=_iso(args.created_at) or datetime.now(UTC),
            )
            out = kernel.create_task(task).model_dump(mode="json")
        elif args.verb == "assign":
            out = kernel.assign(
                args.task_id, args.revision, worker_id=args.worker_id, worker=_party(args, "worker"),
                lease_duration_s=args.lease_s, attempt_id=args.attempt_id, **when,
            ).model_dump(mode="json")
        elif args.verb == "ack":
            out = kernel.acknowledge(args.attempt_id, token=args.token, base_sha=args.base_sha, **when).model_dump(mode="json")
        elif args.verb == "heartbeat":
            out = kernel.heartbeat(args.attempt_id, token=args.token, note=args.note, progress=args.progress, **when).model_dump(mode="json")
        elif args.verb == "evidence":
            out = kernel.record_evidence(args.attempt_id, token=args.token, name=args.name,
                                         payload=Path(args.file).read_bytes(), path=args.file, **when).model_dump(mode="json")
        elif args.verb == "candidate":
            out = kernel.record_candidate(
                args.attempt_id, token=args.token, sha=args.sha,
                changed_paths=tuple(args.changed_path) or None,
                evidence_satisfied=tuple(args.evidence_satisfied), clean_worktree=not args.dirty,
                remote=args.verify_remote, **when,
            ).model_dump(mode="json")
        elif args.verb == "dispatch":
            attempt = kernel._find_attempt(args.attempt_id)
            task = kernel._task(attempt.task_id, attempt.task_revision)
            out = kernel.dispatch_review(
                args.attempt_id, reviewer_principal_id=args.reviewer, packet=Path(args.packet).read_bytes(),
                current_head=_current_head(kernel, args, task.target_branch), **when,
            ).model_dump(mode="json")
        elif args.verb == "verdict":
            attempt = kernel._find_attempt(args.attempt_id)
            task = kernel._task(attempt.task_id, attempt.task_revision)
            verdict = ReviewVerdict(args.verdict)
            payload = Path(args.evidence).read_bytes()
            current_head = _current_head(kernel, args, task.target_branch)
            with runtime_lock(Path(args.runtime_root), args.lock_timeout):
                if verdict is ReviewVerdict.READY:
                    # A READY that the kernel admits records the acceptance: the exact candidate must be green.
                    result = kernel._result(attempt)
                    if result is None or result.result_sha is None:
                        raise LifecycleError(f"no candidate is recorded for attempt {attempt.attempt_id}")
                    gated = _require_green(kernel, args, attempt, (result.result_sha,), "a READY verdict is admitted")
                out = kernel.admit_verdict(
                    args.attempt_id, reviewer=_party(args, "reviewer"), verdict=verdict, payload=payload,
                    observed_candidate_sha=args.observed_sha, current_head=current_head, **when,
                ).model_dump(mode="json")
        elif args.verb == "integrate":
            integration_sha = validate_exact_sha(args.integration_sha)
            state = kernel._state(args.task_id, args.revision)
            if state.attempt_id is None:
                raise LifecycleError(f"task {args.task_id} r{args.revision} is {state.status.value}, not ACCEPTED")
            attempt = kernel._attempt(args.task_id, state.attempt_id)
            accepted = [a.accepted_sha for a in store.read_acceptances(args.task_id) if a.attempt_id == attempt.attempt_id]
            operator = Path(args.gates_evidence).read_bytes() if args.gates_evidence else None
            with runtime_lock(Path(args.runtime_root), args.lock_timeout):
                # What lands (the integration SHA) and what was accepted must both be green.
                gated = _require_green(kernel, args, attempt, (integration_sha, *accepted[-1:]), "an integration lands")
                gates = write_integration_gates(Path(args.runtime_root), attempt.attempt_id, gated,
                                                sha256_of(operator) if operator is not None else None)
                out = kernel.integrate(
                    args.task_id, args.revision, integration_sha=integration_sha,
                    target_base_sha=args.target_base_sha, method=IntegrationMethod(args.method),
                    integrated_by=args.integrated_by, remote=args.verify_remote, gates_evidence=gates,
                ).model_dump(mode="json")
        elif args.verb == "cancel":
            out = kernel.cancel_attempt(args.attempt_id, reason=args.reason).model_dump(mode="json")
        elif args.verb == "block":
            out = kernel.block(args.task_id, args.revision, blocker_class=BlockerClass(args.blocker_class),
                               reason=args.reason, owner_gate=args.owner_gate).model_dump(mode="json")
        elif args.verb == "resume":
            out = kernel.resume(args.task_id, args.revision, note=args.note).model_dump(mode="json")
        elif args.verb == "gate":
            print(json.dumps(kernel.gate_proposal(args.task_id, args.revision), indent=2, sort_keys=True))
            return 0
        elif args.verb == "verify-judgment":
            binding = kernel.verify_owner_judgment_binding(
                args.task_id, args.revision, args.owner_judgment, args.owner_ledger
            )
            print(json.dumps(binding, indent=2, sort_keys=True))
            return 0
        elif args.verb == "view":
            view = lifecycle_view(store, now=datetime.now(UTC))
            if args.json:
                print(json.dumps(view, indent=2, sort_keys=True))
            else:
                for task in view["tasks"]:
                    print(f"{task['task_id']} r{task['revision']}  {task['stage']:<14} {task['stage_reason']}")
                    if task["candidate_sha"]:
                        print(f"    candidate {task['candidate_sha']}")
                    if task["acceptance"]:
                        print(f"    accepted  {task['acceptance']['sha']} by {task['acceptance']['by']} at {task['acceptance']['at']}")
                    if task["integration"]:
                        print(f"    integrated {task['integration']['sha']} into {task['integration']['target_branch']} at {task['integration']['at']}")
                    for r in task.get("owner_resolutions", []):
                        print(f"    owner gate lifted by judgment {r['judgment_id']} of {r['by']} at {r['at']}: {r['resolution']}")
            return 0
        else:  # pragma: no cover
            raise SystemExit(f"unknown verb {args.verb}")
    except DispatcherBusy as exc:
        print(f"BUSY: {exc}; nothing was written; try again, or pass a longer --lock-timeout", file=sys.stderr)
        return 4
    except (LifecycleError, RecordConflictError, StateConflictError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # A file this verb reads, or the runtime root the gate records into, is not usable.
        print(f"REFUSED: {exc}; nothing was written to the store", file=sys.stderr)
        return 2
    except JournalError as exc:
        print(f"JOURNAL FAILED: {exc}; the verb's writes were rolled back, files and index", file=sys.stderr)
        return 3
    summary = {"verb": args.verb, "record": out}
    if gated:
        summary["github_acceptance"] = gated
    if kernel.journal_shas:
        summary["journal_commit"] = kernel.journal_shas[-1]
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(run())
