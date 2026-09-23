#!/usr/bin/env python3
"""The GitHub inbox adapter, from a shell. GPT submits requests via git; this reads them.

    remote_engineering.py --store <engineering/> --repo <checkout> poll \\
        --repository OWNER/REPO --product-memory-ref REF [--remote NAME] [--branch NAME]

    remote_engineering.py --store <engineering/> --repo <checkout> status [--json]

``poll`` fetches exactly one configured remote's one dedicated inbox branch, discovers
every request file committed under it, and intakes each one through the existing
Objective intake (``app.orchestrator.objectives.intake``) exactly once. ``status``
prints a read-only projection of the kernel's own records plus this adapter's receipts.

Nothing here deploys, restarts a service, changes runtime, grants a permission, lifts
an owner gate, or runs a shell string built from request content. It is not a second
lifecycle engine: every objective, task, attempt, review and integration still lives
only in the kernel's own records (``app/orchestrator/lifecycle.py``, unchanged).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.orchestrator.lifecycle import (  # noqa: E402
    GitFacts,
    JournalError,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
)
from app.orchestrator.objectives import ObjectiveStore  # noqa: E402
from app.orchestrator.store import RecordConflictError, StateConflictError  # noqa: E402
from app.remote_engineering import (  # noqa: E402
    DEFAULT_INBOX_BRANCH,
    DEFAULT_INBOX_DIRECTORY,
    InboxError,
    ReceiptLog,
    RemoteController,
    RemoteControllerConfig,
    build_status,
)

DEFAULT_REGISTRY = ROOT / "config" / "review_principals.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True, help="the kernel's store root (engineering/)")
    parser.add_argument("--repo", required=True, help="a checkout of the repository the inbox targets")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--operator", default="remote-engineering-inbox")
    parser.add_argument("--no-journal", action="store_true")
    sub = parser.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("poll", help="fetch the bounded inbox ref once and intake every request found")
    p.add_argument("--repository", required=True, help="OWNER/REPO the objectives are recorded against")
    p.add_argument("--product-memory-ref", required=True, help="the product-memory truth ref to bind objectives to")
    p.add_argument("--remote", default="origin", help="a configured remote name, never a URL")
    p.add_argument("--branch", default=DEFAULT_INBOX_BRANCH)
    p.add_argument("--directory", default=DEFAULT_INBOX_DIRECTORY)
    p.add_argument("--json", action="store_true")

    s = sub.add_parser("status", help="print the read-only projection of the kernel's own records")
    s.add_argument("--json", action="store_true")
    return parser


def _print_status(status: dict) -> None:
    for item in status["requests"]:
        print(f"{item['request_id']}  {item['outcome']}  {item.get('objective_id') or '-'}  {item.get('stage') or '-'}")
        if item.get("reason"):
            print(f"    {item['reason']}")


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
    objectives = ObjectiveStore(store, journal=not args.no_journal)
    receipts = ReceiptLog(store.root / "remote_engineering")
    try:
        if args.verb == "poll":
            config = RemoteControllerConfig(
                repo=Path(args.repo),
                repository=args.repository,
                product_memory_ref=args.product_memory_ref,
                remote=args.remote,
                inbox_branch=args.branch,
                inbox_directory=args.directory,
            )
            controller = RemoteController(kernel=kernel, objectives=objectives, config=config, receipts=receipts)
            outcomes = controller.poll_once()
            print(json.dumps(outcomes, indent=2, sort_keys=True, default=str))
        elif args.verb == "status":
            status = build_status(store=store, receipts=receipts, now=datetime.now(UTC))
            if args.json:
                print(json.dumps(status, indent=2, sort_keys=True, default=str))
            else:
                _print_status(status)
        else:  # pragma: no cover
            raise SystemExit(f"unknown verb {args.verb}")
    except (LifecycleError, InboxError, RecordConflictError, StateConflictError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except JournalError as exc:
        print(f"JOURNAL FAILED: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(run())
