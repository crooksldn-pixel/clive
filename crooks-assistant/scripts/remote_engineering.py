#!/usr/bin/env python3
"""Bounded GitHub ingress for CLIVE engineering.

poll
    Fetch the dedicated inbox once and intake immutable repository-only requests.
status
    Print a read-only projection of authoritative lifecycle records.
run
    Long-lived control loop: poll inbox, advance the existing Dispatcher once,
    publish a disposable GitHub status projection, sleep, repeat.

GitHub is transport/projection only. Objective/task/review/integration authority
remains in the existing engineering store and frozen lifecycle kernel. The one thing
read back from GitHub is the ``acceptance`` check on a candidate's exact SHA, which the
Dispatcher's GitHub acceptance gate requires green before review, acceptance and
integration (app/orchestrator/github_acceptance.py), asked with the credential git
already holds for the publish remote.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import socket
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.orchestrator.checks import NamespaceSandbox  # noqa: E402
from app.orchestrator.dispatcher import (  # noqa: E402
    Dispatcher,
    DispatcherBusy,
    DispatcherConfig,
    recorded_acceptance_gates,
)
from app.orchestrator.github_acceptance import GitHubAcceptance, git_remote_token  # noqa: E402
from app.orchestrator.lifecycle import (  # noqa: E402
    GitFacts,
    JournalError,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
)
from app.orchestrator.objectives import ObjectiveStore  # noqa: E402
from app.orchestrator.reviewers import (  # noqa: E402
    GPT_DEFAULT_EFFORT,
    GPT_DEFAULT_MODEL,
    GptResponsesReviewer,
    GptUnavailable,
)
from app.orchestrator.store import RecordConflictError, StateConflictError  # noqa: E402
from app.orchestrator.workers import ClaudeCodeWorker  # noqa: E402
from app.remote_engineering import (  # noqa: E402
    DEFAULT_INBOX_BRANCH,
    DEFAULT_STATUS_BRANCH,
    DEFAULT_STATUS_HEARTBEAT_S,
    DEFAULT_STATUS_PATH,
    MAX_HEARTBEAT_S,
    MIN_HEARTBEAT_S,
    InboxError,
    ReceiptLog,
    RemoteController,
    RemoteControllerConfig,
    RemoteEngineeringLoop,
    adapter_root_preconditions,
    build_status,
    publish_status,
    validate_seconds,
)

DEFAULT_REGISTRY = ROOT / "config" / "review_principals.json"
PRODUCT_MEMORY_REF = "origin/clive/trunk"

# Host-configured loop bounds. A long-lived mode is only "bounded" if these are.
MIN_INTERVAL_S = 1.0
MAX_INTERVAL_S = 3_600.0


def _add_transport_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", required=True, help="OWNER/REPO objectives are recorded against")
    parser.add_argument("--product-memory-ref", default=PRODUCT_MEMORY_REF,
                        help=f"product-memory truth ref bound by the host (default {PRODUCT_MEMORY_REF}, "
                             "where canonical product memory lives since the 2026-09-25 consolidation)")
    parser.add_argument("--remote", default="origin", help="configured remote name, never a URL")
    parser.add_argument("--branch", default=DEFAULT_INBOX_BRANCH)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True, help="the kernel engineering store root")
    parser.add_argument("--adapter-root", default=None,
                        help="where inbox claims and receipts live (default <store>/remote_engineering); "
                             "with a journalled store it must be outside the store's git work tree or "
                             "ignored there, or poll and run refuse to start")
    parser.add_argument("--repo", required=True, help="engineering checkout, never production checkout")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--operator", default="remote-engineering-inbox")
    parser.add_argument("--dispatcher-operator", default=f"clive-dispatcher@{socket.gethostname()}",
                        help="journal operator for Dispatcher transitions (run only); intake keeps --operator")
    parser.add_argument("--no-journal", action="store_true")

    # Host-only dispatcher configuration. None of these values can come from inbox JSON.
    parser.add_argument("--runtime-root", default="/opt/crooks-workers/runtime")
    parser.add_argument("--workspace-root", default="/opt/crooks-workers")
    parser.add_argument("--publish-remote", default=None)
    parser.add_argument("--gpt-api-key-file", default=None)
    parser.add_argument("--gpt-model", default=GPT_DEFAULT_MODEL)
    parser.add_argument("--gpt-effort", default=GPT_DEFAULT_EFFORT)
    parser.add_argument("--worker-cli", default="claude")
    parser.add_argument("--worker-model", default=None)
    parser.add_argument("--worker-effort", default=None)
    parser.add_argument("--worker-max-turns", type=int, default=200)
    parser.add_argument("--worker-token-file", default=None)
    parser.add_argument("--check-ro-path", action="append", default=[])
    parser.add_argument("--max-concurrent", type=int, default=1)

    sub = parser.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("poll", help="intake the bounded inbox once")
    _add_transport_args(p)
    p.add_argument("--json", action="store_true")

    s = sub.add_parser("status", help="print the read-only lifecycle projection")
    s.add_argument("--json", action="store_true")

    r = sub.add_parser("run", help="poll, advance existing Dispatcher, publish status, repeat")
    _add_transport_args(r)
    r.add_argument("--status-branch", default=DEFAULT_STATUS_BRANCH)
    r.add_argument("--status-path", default=DEFAULT_STATUS_PATH)
    r.add_argument("--status-heartbeat-s", type=float, default=DEFAULT_STATUS_HEARTBEAT_S,
                   help=f"republish an unchanged projection at most this often (liveness signal); "
                        f"{MIN_HEARTBEAT_S}-{MAX_HEARTBEAT_S}s")
    r.add_argument("--interval", type=float, default=15.0,
                   help=f"seconds between cycles; {MIN_INTERVAL_S}-{MAX_INTERVAL_S}s")
    r.add_argument("--max-cycles", type=int, default=0, help="0 means run until stopped")
    return parser


def _kernel_parts(args):
    store = LifecycleStore(Path(args.store))
    kernel = Kernel(
        store=store,
        registry=PrincipalRegistry.load(Path(args.registry)),
        git=GitFacts(Path(args.repo)),
        operator=args.operator,
        journal=not args.no_journal,
    )
    objectives = ObjectiveStore(store, journal=not args.no_journal)
    adapter_root = Path(args.adapter_root) if args.adapter_root else store.root / "remote_engineering"
    receipts = ReceiptLog(adapter_root)
    return store, kernel, objectives, receipts


def _refuse_an_unsafe_adapter_root(args, store: LifecycleStore, receipts: ReceiptLog) -> None:
    """Before anything is claimed: a journalled store refuses every verb while claims or receipts
    sit in its work tree unignored, so every request would be refused with its id already burned."""
    if not args.no_journal:
        adapter_root_preconditions(store.root, receipts.dir.parent)


def _controller(args, kernel: Kernel, objectives: ObjectiveStore, receipts: ReceiptLog) -> RemoteController:
    config = RemoteControllerConfig(
        repo=Path(args.repo),
        repository=args.repository,
        product_memory_ref=args.product_memory_ref,
        remote=args.remote,
        inbox_branch=args.branch,
    )
    return RemoteController(kernel=kernel, objectives=objectives, config=config, receipts=receipts)


def _dispatcher(args, kernel: Kernel, objectives: ObjectiveStore) -> Dispatcher:
    runtime = Path(args.runtime_root)
    if args.gpt_api_key_file:
        reviewers = [
            GptResponsesReviewer(
                runtime / "gpt",
                repo=Path(args.repo),
                key_file=Path(args.gpt_api_key_file),
                model=args.gpt_model,
                effort=args.gpt_effort,
            )
        ]
    else:
        reviewers = [GptUnavailable()]
    worker = ClaudeCodeWorker(
        cli=args.worker_cli,
        model=args.worker_model,
        effort=args.worker_effort,
        max_turns=args.worker_max_turns,
        oauth_token_file=Path(args.worker_token_file) if args.worker_token_file else None,
    )
    config = DispatcherConfig(
        runtime_root=runtime,
        workspace_root=Path(args.workspace_root),
        repo=Path(args.repo),
        publish_remote=args.publish_remote,
        max_concurrent=args.max_concurrent,
    )
    sandbox = NamespaceSandbox(ro_paths=tuple(args.check_ro_path))
    # The GitHub acceptance gate asks with the credential git already holds for the remote the
    # candidates are published to (else the inbox remote): no credential of its own.
    acceptance = GitHubAcceptance(git_remote_token(Path(args.repo), args.publish_remote or args.remote))
    # Same store, registry and git facts; only the journal attribution differs, so every
    # Dispatcher transition is recorded as the dispatcher's, not as the inbox adapter's.
    dispatch_kernel = dataclasses.replace(kernel, operator=args.dispatcher_operator, journal_shas=[])
    return Dispatcher(dispatch_kernel, objectives, worker, reviewers, config, checks=sandbox, acceptance=acceptance)


def _recorded_gates(store: LifecycleStore, runtime_root: Path) -> dict[str, dict]:
    """The dispatcher's recorded GitHub acceptance answers; a read-only view publishes none it cannot read."""
    try:
        return recorded_acceptance_gates(store, runtime_root)
    except (OSError, ValueError):
        return {}


def _print_status(status: dict) -> None:
    for item in status["requests"]:
        print(f"{item['request_id']}  {item['outcome']}  {item.get('objective_id') or '-'}  {item.get('stage') or '-'}")
        if item.get("reason"):
            print(f"    {item['reason']}")
        gate = item.get("github_acceptance") or {}
        if gate:
            print(f"    GitHub acceptance on {gate.get('sha')}: {gate.get('state')} ({gate.get('detail')})")


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store, kernel, objectives, receipts = _kernel_parts(args)
    try:
        if args.verb == "poll":
            _refuse_an_unsafe_adapter_root(args, store, receipts)
            outcomes = _controller(args, kernel, objectives, receipts).poll_once()
            print(json.dumps(outcomes, indent=2, sort_keys=True, default=str))
        elif args.verb == "status":
            status = build_status(store=store, receipts=receipts, now=datetime.now(UTC),
                                  gates=_recorded_gates(store, Path(args.runtime_root)))
            if args.json:
                print(json.dumps(status, indent=2, sort_keys=True, default=str))
            else:
                _print_status(status)
        elif args.verb == "run":
            if args.status_branch == args.branch:
                raise InboxError("status branch must be separate from the owner inbox branch")
            # Refused before anything starts: argparse accepts nan and inf for a float, and
            # neither a NaN sleep (which raises) nor an infinite one is a bounded loop.
            interval = validate_seconds(
                args.interval, what="--interval", minimum=MIN_INTERVAL_S, maximum=MAX_INTERVAL_S
            )
            heartbeat_s = validate_seconds(
                args.status_heartbeat_s, what="--status-heartbeat-s",
                minimum=MIN_HEARTBEAT_S, maximum=MAX_HEARTBEAT_S,
            )
            _refuse_an_unsafe_adapter_root(args, store, receipts)
            controller = _controller(args, kernel, objectives, receipts)
            dispatcher = _dispatcher(args, kernel, objectives)
            loop = RemoteEngineeringLoop(
                controller=controller,
                dispatcher=dispatcher,
                store=store,
                receipts=receipts,
                publish=lambda status: publish_status(
                    Path(args.repo),
                    status,
                    remote=args.remote,
                    branch=args.status_branch,
                    path=args.status_path,
                    heartbeat_s=heartbeat_s,
                ),
            )
            cycles = 0
            while True:
                result = loop.cycle()
                print(json.dumps({
                    "outcomes": result["outcomes"],
                    "dispatcher_events": result["dispatcher_events"],
                    "projection_commit": result["projection_commit"],
                    "intake_error": result["intake_error"],
                    "publish_error": result["publish_error"],
                }, sort_keys=True, default=str), flush=True)
                cycles += 1
                if args.max_cycles and cycles >= args.max_cycles:
                    break
                time.sleep(interval)
        else:  # pragma: no cover
            raise SystemExit(f"unknown verb {args.verb}")
    except DispatcherBusy as exc:
        print(f"BUSY: {exc}", file=sys.stderr)
        return 4
    except (LifecycleError, InboxError, RecordConflictError, StateConflictError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except JournalError as exc:
        print(f"JOURNAL FAILED: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(run())
