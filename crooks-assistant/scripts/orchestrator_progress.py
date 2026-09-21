"""Render current engineering progress from a repository-only record store."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.orchestrator.progress import project_progress, render_progress_table
from app.orchestrator.store import JsonRecordStore


def build_snapshots(
    store: JsonRecordStore,
    *,
    include_history: bool = False,
):
    tasks = {(task.task_id, task.revision): task for task in store.read_tasks()}
    runtime = {
        (state.task_id, state.task_revision): state
        for state in store.read_task_states()
    }
    grouped = defaultdict(list)
    for event in store.read_all_progress_events():
        grouped[(event.task_id, event.task_revision, event.attempt_id)].append(event)

    projected = {}
    for (task_id, revision, attempt_id), events in sorted(grouped.items()):
        task = tasks.get((task_id, revision))
        if task is None:
            raise ValueError(
                f"progress exists without immutable task contract: {task_id} r{revision}"
            )
        projected[(task_id, revision, attempt_id)] = project_progress(
            task=task,
            events=events,
        )

    if include_history:
        return tuple(projected[key] for key in sorted(projected))

    current = []
    task_keys = sorted({(task_id, revision) for task_id, revision, _ in projected})
    for task_key in task_keys:
        task_state = runtime.get(task_key)
        if task_state and task_state.attempt_id:
            selected = projected.get((*task_key, task_state.attempt_id))
            if selected is not None:
                current.append(selected)
                continue

        candidates = [
            snapshot
            for (task_id, revision, _), snapshot in projected.items()
            if (task_id, revision) == task_key
        ]
        current.append(max(candidates, key=lambda item: item.last_event_at))

    return tuple(current)


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
    parser.add_argument(
        "--all-attempts",
        action="store_true",
        help="include historical attempts instead of only the current/latest attempt",
    )
    parser.add_argument("--now", help="override current time with timezone-aware ISO timestamp")
    args = parser.parse_args()

    store = JsonRecordStore(args.root)
    snapshots = build_snapshots(store, include_history=args.all_attempts)

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
