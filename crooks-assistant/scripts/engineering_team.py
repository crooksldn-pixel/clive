#!/usr/bin/env python3
"""A read-only view of every objective the engineering dispatcher is carrying at once.

    engineering_team.py --store <engineering/> --repo <dispatcher clone> [--json]

One line per objective: its stage, current attempt id, builder kind, any live
builder pids, its reviewer (principal and mechanism) while under review, and its
blocker while blocked. Then totals (building, reviewing, blocked, complete,
other) and how many of --max-concurrent builder slots are free.

This never ticks, launches a worker, writes a record or changes a file: it reads
``Dispatcher.status()`` and the objective store, nothing else. It takes the same
``--store``/``--repo``/``--registry``/``--runtime-root``/``--workspace-root``/
``--max-concurrent`` arguments as ``engineering_dispatcher.py``, and builds the
Dispatcher the same way.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.orchestrator import checks, dispatcher, lifecycle, objectives, reviewers, workers  # noqa: E402

DEFAULT_REGISTRY = ROOT / "config" / "review_principals.json"

BUILDING = {"ASSIGNED", "RUNNING"}
REVIEWING = {"EVIDENCE_READY", "REVIEWING"}
BLOCKED = {"BLOCKED", "OWNER_GATE"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", required=True, help="the kernel's store root (engineering/)")
    p.add_argument("--repo", required=True, help="the dispatcher's own clone; never a production checkout")
    p.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    p.add_argument("--runtime-root", default="/opt/crooks-workers/runtime")
    p.add_argument("--workspace-root", default="/opt/crooks-workers")
    p.add_argument("--max-concurrent", type=int, default=1)
    p.add_argument("--json", action="store_true")
    return p


def build_dispatcher(args) -> dispatcher.Dispatcher:
    """The same Dispatcher engineering_dispatcher.py builds for its defaults (``--reviewer gpt`` with no
    ``--gpt-api-key-file``, ``--worker-cli claude`` and no other worker/check-sandbox overrides): the same
    app.orchestrator imports, the same reviewer-driver (``GptUnavailable``, since this script takes no key
    file) and the same worker and sandbox wiring. Only ``status()`` is ever called on it, so nothing here
    dispatches or collects a review, launches a worker or writes a record."""
    store = lifecycle.LifecycleStore(Path(args.store))
    kernel = lifecycle.Kernel(store=store, registry=lifecycle.PrincipalRegistry.load(Path(args.registry)),
                              git=lifecycle.GitFacts(Path(args.repo)), operator="engineering-team (read-only)",
                              journal=False)
    objective_store = objectives.ObjectiveStore(store, journal=False)
    review_drivers = [reviewers.GptUnavailable()]
    worker = workers.ClaudeCodeWorker(cli="claude", model=None, effort=None, max_turns=200, bash_prefixes=(),
                                      oauth_token_file=None)
    config = dispatcher.DispatcherConfig(runtime_root=Path(args.runtime_root), workspace_root=Path(args.workspace_root),
                                         repo=Path(args.repo), max_concurrent=args.max_concurrent)
    return dispatcher.Dispatcher(kernel, objective_store, worker, review_drivers, config, checks=checks.NamespaceSandbox())


def _category(stage: str | None) -> str:
    if stage in BUILDING:
        return "building"
    if stage in REVIEWING:
        return "reviewing"
    if stage in BLOCKED:
        return "blocked"
    if stage == "COMPLETE":
        return "complete"
    return "other"


def gather(team: dispatcher.Dispatcher) -> dict:
    """Everything to report, read straight from Dispatcher.status() and the objective store."""
    builder_kind = {obj.objective_id: (team.integrator.kind if obj.builder == "integrator" else team.worker.kind)
                    for obj in team.objectives.read_all()}
    rows = []
    totals = {"building": 0, "reviewing": 0, "blocked": 0, "complete": 0, "other": 0}
    for item in team.status():
        stage = item.get("stage")
        category = _category(stage)
        totals[category] += 1
        process = item.get("process") or {}
        review_mechanism = item.get("review_mechanism") or {}
        row = {
            "objective_id": item["objective_id"],
            "stage": stage,
            "attempt_id": item.get("attempt_id"),
            "builder": builder_kind.get(item["objective_id"]),
            "pids": list(process.get("pids") or []),
            "reviewer_principal": review_mechanism.get("principal_id") if stage == "REVIEWING" else None,
            "reviewer_mechanism": review_mechanism.get("mechanism") if stage == "REVIEWING" else None,
            "blocker": item.get("blocker") if category == "blocked" else None,
        }
        rows.append(row)
    free_slots = max(0, team.config.max_concurrent - totals["building"])
    return {"objectives": rows, "totals": totals, "max_concurrent": team.config.max_concurrent,
            "free_slots": free_slots}


def _line(row: dict) -> str:
    parts = [row["objective_id"], f"stage={row['stage']}", f"attempt={row['attempt_id'] or '-'}",
             f"builder={row['builder'] or '-'}", f"pids={row['pids'] or '-'}"]
    if row["reviewer_principal"]:
        parts.append(f"reviewer={row['reviewer_principal']} via {row['reviewer_mechanism']}")
    if row["blocker"]:
        parts.append(f"blocker={row['blocker']}")
    return "  ".join(parts)


def render(report: dict) -> str:
    lines = [_line(row) for row in report["objectives"]]
    t = report["totals"]
    lines.append(f"totals: building={t['building']} reviewing={t['reviewing']} blocked={t['blocked']} "
                 f"complete={t['complete']} other={t['other']}")
    lines.append(f"max-concurrent={report['max_concurrent']} free={report['free_slots']}")
    return "\n".join(lines)


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    team = build_dispatcher(args)
    report = gather(team)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(run())
