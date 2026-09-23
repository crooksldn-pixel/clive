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
remains in the existing engineering store and frozen lifecycle kernel.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.orchestrator.checks import NamespaceSandbox  # noqa: E402
from app.orchestrator.dispatcher import Dispatcher, DispatcherBusy, DispatcherConfig  # noqa: E402
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
    GPT_DEFAULT_MODEL,
    GptResponsesReviewer,
    GptUnavailable,
)
from app.orchestrator.store import RecordConflictError, StateConflictError  # noqa: E402
from app.orchestrator.workers import ClaudeCodeWorker  # noqa: E402
from app.remote_engineering import (  # noqa: E402
    DEFAULT_INBOX_BRANCH,
    DEFAULT_INBOX_DIRECTORY,
    DEFAULT_STATUS_BRANCH,
    DEFAULT_STATUS_PATH,
    InboxError,
    ReceiptLog,
    RemoteController,
    RemoteControllerConfig,
    RemoteEngineeringLoop,
    build_status,
    publish_status,
)

DEFAULT_REGISTRY = ROOT / "config" / "review_principals.json"


def _add_transport_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", required=True, help="OWNER/REPO objectives are recorded against")
    parser.add_argument("--product-memory-ref", required=True, help="product-memory truth ref bound by the host")
    parser.add_argument("--remote", default="origin", help="configured remote name, never a URL")
    parser.add_argument("--branch", default=DEFAULT_INBOX_BRANCH)
    parser.add_argument("--directory", default=DEFAULT_INBOX_DIRECTORY)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True, help="the kernel engineering store root")
    parser.add_argument("--repo", required=True, help="engineering checkout, never production checkout")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--operator", default="remote-engineering-inbox")
    parser.add_argument("--no-journal", action="store_true")

    # Host-only dispatcher configuration. None of these values can come from inbox JSON.
    parser.add_argument("--runtime-root", default="/opt/crooks-workers/runtime")
    parser.add_argument("--workspace-root", default="/opt/crooks-workers")
    parser.add_argument("--publish-remote", default=None)
    parser.add_argument("--gpt-api-key-file", default=None)
    parser.add_argument("--gpt-model", default=GPT_DEFAULT_MODEL)
    parser.add_argument("--gpt-effort", default="high")
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
    r.add_argument("--interval", type=float, default=15.0)
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
    receipts = ReceiptLog(store.root / "remote_engineering")
    return store, kernel, objectives, receipts


def _controller(args, kernel: Kernel, objectives: ObjectiveStore, receipts: ReceiptLog) -> RemoteController:
    config = RemoteControllerConfig(
        repo=Path(args.repo),
        repository=args.repository,
        product_memory_ref=args.product_memory_ref,
        remote=args.remote,
        inbox_branch=args.branch,
        inbox_directory=args.directory,
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
    return Dispatcher(kernel, objectives, worker, reviewers, config, checks=sandbox)


def _print_status(status: dict) -> None:
    for item in status["requests"]:
        print(f"{item['request_id']}  {item['outcome']}  {item.get('objective_id') or '-'}  {item.get('stage') or '-'}")
        if item.get("reason"):
            print(f"    {item['reason']}")


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store, kernel, objectives, receipts = _kernel_parts(args)
    try:
        if args.verb == "poll":
            outcomes = _controller(args, kernel, objectives, receipts).poll_once()
            print(json.dumps(outcomes, indent=2, sort_keys=True, default=str))
        elif args.verb == "status":
            status = build_status(store=store, receipts=receipts, now=datetime.now(UTC))
            if args.json:
                print(json.dumps(status, indent=2, sort_keys=True, default=str))
            else:
                _print_status(status)
        elif args.verb == "run":
            if args.status_branch == args.branch:
                raise InboxError("status branch must be separate from the owner inbox branch")
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
                ),
            )
            cycles = 0
            while True:
                result = loop.cycle()
                print(json.dumps({
                    "outcomes": result["outcomes"],
                    "dispatcher_events": result["dispatcher_events"],
                    "projection_commit": result["projection_commit"],
                }, sort_keys=True, default=str), flush=True)
                cycles += 1
                if args.max_cycles and cycles >= args.max_cycles:
                    break
                time.sleep(max(args.interval, 1.0))
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
