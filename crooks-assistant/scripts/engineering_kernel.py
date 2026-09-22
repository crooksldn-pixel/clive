#!/usr/bin/env python3
"""The kernel's verbs, from a shell. CLIVE authors its engineering lifecycle here.

    engineering_kernel.py --store <root> --repo <checkout> [--registry F] [--operator NAME] VERB ...

Verbs, in lifecycle order: task, assign, ack, heartbeat, evidence, candidate, dispatch,
verdict, integrate; and cancel, block, resume, view. Each validates everything before it
writes anything, writes immutable records plus one compare-and-swap state transition,
regenerates ACTIVE_STATE.json, and journals the change as a git commit when the store
lives in a checkout. A refusal prints the reason and exits 2; nothing is written.

Nothing here runs a worker, a watcher, a service or a deployment. The store is the
authoritative record of the lifecycle; processes and branches are what the projection
reconciles against it.
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
)
from app.orchestrator.lifecycle import (  # noqa: E402
    GitFacts,
    IntegrationMethod,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
    lifecycle_view,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True, help="store root (the engineering/ directory)")
    parser.add_argument("--repo", default=str(ROOT.parent), help="git checkout answering commit questions")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--operator", default="unnamed operator")
    parser.add_argument("--no-journal", action="store_true", help="do not git-commit the store")
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
    c.add_argument("--changed-path", action="append", default=[])
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
    i.add_argument("--verify-remote", default=None)
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

    r = sub.add_parser("resume", help="lift a block; the stage is recomputed from the records")
    r.add_argument("--task-id", required=True)
    r.add_argument("--revision", type=int, required=True)
    r.add_argument("--note", required=True)

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
    )
    when = dict(at=_iso(getattr(args, "at", None)), backfilled=getattr(args, "backfilled", False),
                evidence_ref=getattr(args, "evidence_ref", None))
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
                args.attempt_id, token=args.token, sha=args.sha, changed_paths=tuple(args.changed_path),
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
            out = kernel.admit_verdict(
                args.attempt_id, reviewer=_party(args, "reviewer"), verdict=ReviewVerdict(args.verdict),
                payload=Path(args.evidence).read_bytes(), observed_candidate_sha=args.observed_sha,
                current_head=_current_head(kernel, args, task.target_branch), **when,
            ).model_dump(mode="json")
        elif args.verb == "integrate":
            out = kernel.integrate(
                args.task_id, args.revision, integration_sha=args.integration_sha,
                target_base_sha=args.target_base_sha, method=IntegrationMethod(args.method),
                integrated_by=args.integrated_by, remote=args.verify_remote,
                gates_evidence=Path(args.gates_evidence).read_bytes() if args.gates_evidence else None,
            ).model_dump(mode="json")
        elif args.verb == "cancel":
            out = kernel.cancel_attempt(args.attempt_id, reason=args.reason).model_dump(mode="json")
        elif args.verb == "block":
            out = kernel.block(args.task_id, args.revision, blocker_class=BlockerClass(args.blocker_class),
                               reason=args.reason, owner_gate=args.owner_gate).model_dump(mode="json")
        elif args.verb == "resume":
            out = kernel.resume(args.task_id, args.revision, note=args.note).model_dump(mode="json")
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
            return 0
        else:  # pragma: no cover
            raise SystemExit(f"unknown verb {args.verb}")
    except (LifecycleError, RecordConflictError, StateConflictError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    summary = {"verb": args.verb, "record": out}
    if kernel.journal_shas:
        summary["journal_commit"] = kernel.journal_shas[-1]
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(run())
