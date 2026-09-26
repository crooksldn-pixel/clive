"""A read-only projection of existing kernel records, for a GPT Director polling GitHub.

Every field is either read straight from the kernel's own records (``lifecycle_view``,
unchanged) or from a receipt this adapter itself earned when it processed a request.
Nothing here is inferred and nothing here is authority: a task's real stage is always
whatever the kernel's records say, never this projection.

``refused_records`` carries the one thing receipts cannot: an inbox record that never
became a request id at all, because it failed schema validation. Such a record earns no
receipt -- nothing was decided about an id -- so it is regenerated deterministically from
the same inbox snapshot on every poll, and keyed by the bounded inbox path it came from
plus the digest of its exact bytes rather than by an id this adapter never trusted. It
carries a redacted schema diagnostic only, never the rejected content.

``github_acceptance`` is the dispatcher's last recorded answer from the GitHub acceptance gate for
the task's current attempt (``Dispatcher.acceptance_gates``): the exact SHA it was asked about, its
state (green, pending, missing, red, unavailable), a sentence the gate built itself, the acceptance
run ids with GitHub's status and conclusion words, and when it was asked. Like everything here it is
a projection, and it is the Director's view of why a candidate waits before review or integration.

What is never published: review findings text. A verdict appears only as its outcome, its verdict
word, the reviewer principal and the kernel's reason codes (``lifecycle_view``); the findings, their
evidence references, required repairs and the reviewer's summary stay in the engineering store.
"""

from __future__ import annotations

from collections.abc import Mapping
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


def build_status(
    *,
    store: LifecycleStore,
    receipts: ReceiptLog,
    now: datetime,
    refusals: tuple[dict, ...] = (),
    gates: Mapping[str, dict] | None = None,
) -> dict:
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
            item["github_acceptance"] = (gates or {}).get(receipt.task_id)
        requests.append(item)
    refused = sorted(
        (
            {
                "refusal_id": item["refusal_id"],
                "source": item["source"],
                "request_sha256": item["request_sha256"],
                "outcome": "refused",
                "reason": item["reason"],
            }
            for item in refusals
        ),
        key=lambda item: item["refusal_id"],
    )
    return {
        "schema_version": STATUS_SCHEMA,
        "generated_at": now.isoformat(),
        "requests": requests,
        "refused_records": refused,
    }
