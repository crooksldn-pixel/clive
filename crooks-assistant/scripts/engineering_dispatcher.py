#!/usr/bin/env python3
"""The owner's door for engineering objectives, and the dispatcher that carries them.

    engineering_dispatcher.py --store <engineering/> --repo <dispatcher clone> VERB ...

    objective      record one owner objective and its task revision 1 (the only intake)
    tick           one deterministic pass: every objective advances by what its records allow
    run            tick until every objective is COMPLETE, BLOCKED or at OWNER_GATE
    status         task / revision / attempt, worker process, progress, candidate, review, blocker, next action
    submit-review  (relay reviewer only) hand the dispatcher a typed clive.review_result.v1 a person carried back

Example:

    engineering_dispatcher.py --store /srv/clive-state/engineering --repo /opt/crooks-dispatcher \\
        objective --title "Support queue" \\
        --objective "Show unanswered Crooks order enquiries ..." \\
        --base-ref origin/claude/support-investigator-v1-2026-09-23 \\
        --allowed-path crooks-assistant/app/support --allowed-path crooks-assistant/tests/test_support_queue.py \\
        --acceptance "lists every thread with no reply from us, newest first" \\
        --check 'tests=.venv/bin/python -m pytest -q tests/test_support_queue.py' --check-cwd tests=crooks-assistant

    engineering_dispatcher.py --store ... --repo ... run

Nothing here deploys, restarts a service, changes runtime, grants a permission or
lifts an owner gate. Every stage is a kernel record (app/orchestrator/lifecycle.py,
unchanged); the dispatcher's own files under --runtime-root are execution notes.
Exit status: 0 done, 2 refused, 4 another dispatcher is running.
"""

from __future__ import annotations

import argparse
import json
import shlex
import socket
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.orchestrator.checks import NamespaceSandbox  # noqa: E402
from app.orchestrator.contracts import TaskStatus  # noqa: E402
from app.orchestrator.dispatcher import Dispatcher, DispatcherBusy, DispatcherConfig  # noqa: E402
from app.orchestrator.lifecycle import (  # noqa: E402
    GitFacts,
    JournalError,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
)
from app.orchestrator.objectives import (  # noqa: E402
    DEFAULT_PROHIBITED_ACTIONS,
    Check,
    Objective,
    ObjectiveStore,
    accepted_candidates,
    intake,
    integration_scope,
    owner_entry_from_host,
    slug,
)
from app.orchestrator.reviewers import (  # noqa: E402
    GPT_DEFAULT_MODEL,
    GptResponsesReviewer,
    GptUnavailable,
    RelayReviewer,
    ReviewContext,
    ReviewResult,
)
from app.orchestrator.store import RecordConflictError, StateConflictError  # noqa: E402
from app.orchestrator.workers import ClaudeCodeWorker  # noqa: E402

DEFAULT_REGISTRY = ROOT / "config" / "review_principals.json"
TERMINAL = {"COMPLETE", "BLOCKED", "OWNER_GATE", "UNKNOWN", "NO_TASK"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", required=True, help="the kernel's store root (engineering/)")
    p.add_argument("--repo", required=True, help="the dispatcher's own clone; never a production checkout")
    p.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    p.add_argument("--runtime-root", default="/opt/crooks-workers/runtime")
    p.add_argument("--workspace-root", default="/opt/crooks-workers")
    p.add_argument("--operator", default=f"clive-dispatcher@{socket.gethostname()}")
    p.add_argument("--no-journal", action="store_true")
    p.add_argument("--publish-remote", default=None, help="push candidates to this remote's target branch")
    p.add_argument("--reviewer", choices=["gpt", "relay"], default="gpt",
                   help="gpt: the programmatic GPT reviewer (needs --gpt-api-key-file, else the task blocks with the gap); "
                        "relay: a person carries packet and typed result (courier)")
    p.add_argument("--gpt-api-key-file", default=None,
                   help="host-side file (mode 600, outside git and every workspace) holding the OpenAI API key "
                        "for the programmatic GPT reviewer; read only by the reviewer process")
    p.add_argument("--gpt-model", default=GPT_DEFAULT_MODEL)
    p.add_argument("--gpt-effort", default="high")
    p.add_argument("--worker-cli", default="claude")
    p.add_argument("--worker-model", default=None)
    p.add_argument("--worker-effort", default=None)
    p.add_argument("--worker-max-turns", type=int, default=200)
    p.add_argument("--worker-token-file", default=None, help="host-side file holding CLAUDE_CODE_OAUTH_TOKEN")
    p.add_argument("--worker-bash-prefix", action="append", default=[],
                   help="allow Bash commands with this prefix (off by default; a prefix is not a sandbox)")
    p.add_argument("--check-ro-path", action="append", default=[],
                   help="a host directory the check sandbox binds read-only (e.g. the interpreter's virtualenv); "
                        "nothing else of the host is visible to a check")
    p.add_argument("--lease-s", type=int, default=1800)
    p.add_argument("--stall-s", type=int, default=1200)
    p.add_argument("--init-timeout-s", type=int, default=180)
    p.add_argument("--max-concurrent", type=int, default=1)
    sub = p.add_subparsers(dest="verb", required=True)

    o = sub.add_parser("objective", help="record one owner objective (and its task r1)")
    o.add_argument("--title", required=True)
    o.add_argument("--objective", required=True, help="the requested outcome, in the owner's words")
    o.add_argument("--id", default=None, help="objective id (default: from the title)")
    o.add_argument("--base-ref", required=True, help="branch, tag or SHA the work starts from")
    o.add_argument("--target-branch", default=None, help="default clive/objective/<id>")
    o.add_argument("--allowed-path", action="append", required=True)
    o.add_argument("--acceptance", action="append", default=[])
    o.add_argument("--check", action="append", default=[], help="NAME=COMMAND (no shell)")
    o.add_argument("--check-cwd", action="append", default=[], help="NAME=DIR inside the workspace")
    o.add_argument("--prohibited", action="append", default=[], help="an extra prohibited action")
    o.add_argument("--max-repair-rounds", type=int, default=2)
    o.add_argument("--repository", default="crooksldn-pixel/clive")
    o.add_argument("--product-memory-ref", default="origin/claude/product-memory-truth-2026-09-23")

    g = sub.add_parser("integrate", help="an integration objective: CLIVE merges the accepted candidates of "
                                         "several objectives, runs whole-product checks, and GPT reviews the result")
    g.add_argument("--title", required=True)
    g.add_argument("--id", default=None)
    g.add_argument("--from", dest="sources", action="append", required=True,
                   help="an objective id whose verified, accepted candidate is integrated (repeat)")
    g.add_argument("--base-ref", required=True, help="the line the candidates are integrated onto")
    g.add_argument("--target-branch", default=None)
    g.add_argument("--acceptance", action="append", default=[])
    g.add_argument("--check", action="append", default=[], help="NAME=COMMAND (no shell): whole-product checks")
    g.add_argument("--check-cwd", action="append", default=[])
    g.add_argument("--repository", default="crooksldn-pixel/clive")
    g.add_argument("--product-memory-ref", default="origin/claude/product-memory-truth-2026-09-23")

    sub.add_parser("tick", help="one deterministic pass")
    r = sub.add_parser("run", help="tick until every objective is terminal")
    r.add_argument("--interval", type=float, default=15.0)
    r.add_argument("--max-ticks", type=int, default=0, help="0: no limit")
    s = sub.add_parser("status", help="what the records and the host say")
    s.add_argument("--json", action="store_true")
    v = sub.add_parser("submit-review", help="relay only: a typed review result carried back by a person")
    v.add_argument("--file", required=True)
    return p


def _parts(args):
    store = LifecycleStore(Path(args.store))
    kernel = Kernel(store=store, registry=PrincipalRegistry.load(Path(args.registry)), git=GitFacts(Path(args.repo)),
                    operator=args.operator, journal=not args.no_journal)
    objectives = ObjectiveStore(store, journal=not args.no_journal)
    runtime = Path(args.runtime_root)
    if args.reviewer == "relay":
        reviewers = [RelayReviewer(runtime / "relay")]
    elif args.gpt_api_key_file:
        reviewers = [GptResponsesReviewer(runtime / "gpt", repo=Path(args.repo), key_file=Path(args.gpt_api_key_file),
                                          model=args.gpt_model, effort=args.gpt_effort)]
    else:
        reviewers = [GptUnavailable()]
    worker = ClaudeCodeWorker(cli=args.worker_cli, model=args.worker_model, effort=args.worker_effort,
                              max_turns=args.worker_max_turns, bash_prefixes=tuple(args.worker_bash_prefix),
                              oauth_token_file=Path(args.worker_token_file) if args.worker_token_file else None)
    config = DispatcherConfig(runtime_root=runtime, workspace_root=Path(args.workspace_root), repo=Path(args.repo),
                              publish_remote=args.publish_remote, lease_s=args.lease_s, stall_s=args.stall_s,
                              init_timeout_s=args.init_timeout_s, max_concurrent=args.max_concurrent)
    sandbox = NamespaceSandbox(ro_paths=tuple(args.check_ro_path))
    return kernel, objectives, Dispatcher(kernel, objectives, worker, reviewers, config, checks=sandbox)


def _objective(args, kernel: Kernel) -> Objective:
    base = kernel.git.rev_parse(args.base_ref)
    if base is None:
        raise LifecycleError(f"base ref {args.base_ref!r} does not resolve to a commit in {args.repo}")
    memory = kernel.git.rev_parse(args.product_memory_ref)
    if memory is None:
        raise LifecycleError(f"product-memory ref {args.product_memory_ref!r} does not resolve")
    objective_id = args.id or slug(args.title)
    cwds = dict(item.split("=", 1) for item in args.check_cwd)
    checks = []
    for item in args.check:
        if "=" not in item:
            raise SystemExit(f"--check {item!r}: expected NAME=COMMAND")
        name, command = item.split("=", 1)
        checks.append(Check(name=name, argv=tuple(shlex.split(command)), cwd=cwds.get(name, ".")))
    return Objective(
        objective_id=objective_id, title=args.title, requested_outcome=args.objective,
        acceptance_criteria=tuple(args.acceptance), checks=tuple(checks), repository=args.repository,
        base_ref=args.base_ref, base_sha=base, target_branch=args.target_branch or f"clive/objective/{objective_id}",
        product_memory_sha=memory, allowed_paths=tuple(args.allowed_path),
        prohibited_actions=(*DEFAULT_PROHIBITED_ACTIONS, *args.prohibited), max_repair_rounds=args.max_repair_rounds,
        owner=owner_entry_from_host(), created_at=datetime.now(UTC),
    )


def _integration(args, kernel: Kernel) -> Objective:
    sources = tuple(args.sources)
    shas = accepted_candidates(kernel, sources)
    base = kernel.git.rev_parse(args.base_ref)
    if base is None:
        raise LifecycleError(f"base ref {args.base_ref!r} does not resolve to a commit in {args.repo}")
    args.allowed_path = list(integration_scope(kernel, base, shas))
    args.objective = (f"Integrate the accepted candidates of {', '.join(sources)} "
                      f"({', '.join(shas)}) onto {args.base_ref} ({base}); the integrated SHA must pass the "
                      "whole-product checks and an independent review.")
    args.prohibited, args.max_repair_rounds = [], 0
    args.acceptance = [*args.acceptance, "every integrated candidate's change is present, unaltered, at the integrated SHA",
                       "the whole-product checks pass at the integrated SHA"]
    fields = _objective(args, kernel).model_dump()
    fields.update(builder="integrator", integrates=shas)
    return Objective.model_validate(fields)


def _print_status(items: list[dict]) -> None:
    for s in items:
        print(f"{s['objective_id']}  {s.get('stage')}  r{s.get('revision')} {s.get('attempt_id') or '-'}")
        print(f"    {s.get('stage_reason') or ''}")
        proc = s.get("process") or {}
        if proc:
            print(f"    process alive: {proc.get('alive')} {proc.get('pids') or ''}; last observed event "
                  f"{proc.get('last_observed_event_at')}; last heartbeat {s.get('last_heartbeat')}; "
                  f"last progress {s.get('last_progress')}")
        if s.get("candidate_sha"):
            print(f"    candidate {s['candidate_sha']}")
        review = s.get("review_mechanism") or {}
        if review:
            print(f"    review: {review.get('principal_id')} via {review.get('mechanism')}"
                  f"{' (COURIER)' if review.get('courier') else ''}")
        if s.get("blocker"):
            print(f"    blocker ({s.get('blocker_class')}): {s['blocker']}")
        print(f"    next: {s.get('next_action')}")


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    kernel, objectives, dispatcher = _parts(args)
    try:
        if args.verb == "objective":
            print(json.dumps(intake(_objective(args, kernel), kernel=kernel, objectives=objectives), indent=2))
        elif args.verb == "integrate":
            print(json.dumps(intake(_integration(args, kernel), kernel=kernel, objectives=objectives), indent=2))
        elif args.verb == "tick":
            for line in dispatcher.tick():
                print(line)
        elif args.verb == "run":
            ticks = 0
            while True:
                for line in dispatcher.tick():
                    print(line, flush=True)
                ticks += 1
                stages = {s["objective_id"]: s.get("stage") for s in dispatcher.status()}
                if all(stage in TERMINAL for stage in stages.values()):
                    print(json.dumps(stages, indent=2))
                    break
                if args.max_ticks and ticks >= args.max_ticks:
                    print(json.dumps(stages, indent=2))
                    break
                time.sleep(args.interval)
        elif args.verb == "status":
            items = dispatcher.status()
            if args.json:
                print(json.dumps(items, indent=2, default=str))
            else:
                _print_status(items)
        elif args.verb == "submit-review":
            if args.reviewer != "relay":
                raise SystemExit("submit-review exists only for --reviewer relay")
            payload = Path(args.file).read_bytes()
            typed = ReviewResult.model_validate_json(payload)  # refuse malformed input at the door
            state = kernel.store.read_task_state(typed.task_id, typed.task_revision)
            dispatches = kernel.store.read_dispatches(typed.task_id, typed.attempt_id)
            if state is None or state.status is not TaskStatus.REVIEWING or not dispatches:
                raise LifecycleError(f"{typed.task_id} r{typed.task_revision} {typed.attempt_id} is not under review")
            last = dispatches[-1]
            ctx = ReviewContext(typed.task_id, typed.task_revision, typed.attempt_id, last.dispatch_seq,
                                last.candidate_sha, kernel.store.root / last.packet_path)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            print(RelayReviewer(Path(args.runtime_root) / "relay").submit(ctx, payload, stamp=stamp))
    except DispatcherBusy as exc:
        print(f"BUSY: {exc}", file=sys.stderr)
        return 4
    except (LifecycleError, RecordConflictError, StateConflictError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except JournalError as exc:
        print(f"JOURNAL FAILED: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(run())
