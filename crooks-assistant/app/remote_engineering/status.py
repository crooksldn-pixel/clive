"""A read-only projection of existing kernel records, for a GPT Director polling GitHub.

Every field is either read straight from the kernel's own records (``lifecycle_view``,
unchanged) or from a receipt this adapter itself earned when it processed a request.
Nothing here is inferred and nothing here is authority: a task's real stage is always
whatever the kernel's records say, never this projection.
"""

from __future__ import annotations

from datetime import datetime

from app.orchestrator.lifecycle import LifecycleStore, lifecycle_view

from .receipts import ReceiptLog

STATUS_SCHEMA = "clive.remote_engineering_status.v1"

_TASK_FIELDS = (
    "stage",
    "stage_reason",
    "blocker",
    "blocker_class",
    "owner_gate",
    "candidate_sha",
    "review",
    "acceptance",
    "integration",
)


def build_status(*, store: LifecycleStore, receipts: ReceiptLog, now: datetime) -> dict:
    # A repair is a new task revision (r+1); the earlier revision becomes OBSOLETE. The
    # task's current stage, candidate, review, acceptance and integration are therefore
    # those of its highest recorded revision, exactly as the Dispatcher itself reads them.
    latest: dict[str, dict] = {}
    for task in lifecycle_view(store, now=now)["tasks"]:
        current = latest.get(task["task_id"])
        if current is None or task["revision"] > current["revision"]:
            latest[task["task_id"]] = task
    requests = []
    for receipt in receipts.read_all():
        item = {
            "request_id": receipt.request_id,
            "source": receipt.source,
            "request_sha256": receipt.request_sha256,
            "outcome": receipt.outcome,
            "reason": receipt.reason,
            "objective_id": receipt.objective_id,
            "task_id": receipt.task_id,
            "recorded_at": receipt.recorded_at.isoformat(),
        }
        task = latest.get(receipt.task_id) if receipt.task_id else None
        if task is not None:
            item["revision"] = task["revision"]
            item.update({field_name: task.get(field_name) for field_name in _TASK_FIELDS})
        requests.append(item)
    return {"schema_version": STATUS_SCHEMA, "generated_at": now.isoformat(), "requests": requests}
