"""Render current engineering progress from a repository-only record store."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.orchestrator.progress import project_progress, render_progress_table
from app.orchestrator.store import JsonRecordStore


def build_snapshots(store: JsonRecordStore):
    tasks = {(task.task_id, task.revision): task for task in store.read_tasks()}
    grouped = defaultdict(list)
    for event in store.read_all_progress_events():
        grouped[(event.task_id, event.task_revision, event.attempt_id)].append(event)

    snapshots = []
    for (task_id, revision, _attempt_id), events in sorted(grouped.items()):
        task = tasks.get((task_id, revision))
        if task is None:
            raise ValueError(
                f"progress exists without immutable task contract: {task_id} r{revision}"
            )
        snapshots.append(project_progress(task=task, events=events))
    return tuple(snapshots)


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include a timezone offset")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Show CLIVE engineering worker progress")
    parser.add_argument("--root", type=Path, required=True, help="control-plane record-store root")
    parser.add_argument("--json", action="store_true", help="emit snapshots as JSON")
    parser.add_argument("--now", help="override current time with timezone-aware ISO timestamp")
    args = parser.parse_args()

    store = JsonRecordStore(args.root)
    snapshots = build_snapshots(store)

    if args.json:
        print(
            json.dumps(
                [snapshot.model_dump(mode="json") for snapshot in snapshots],
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_progress_table(snapshots, now=_parse_now(args.now)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
