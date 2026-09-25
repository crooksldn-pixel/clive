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

Why a task is stuck travels too, so the Director need not read the host: the open findings
of the latest independent verdict (read from the verdict payload the kernel stores beside
its admission), the failing checks of a refused result (read from the check evidence file
whose path and sha256 the kernel recorded; a file that no longer matches its digest is not
published) and the text of a worker-reported block (the worker's structured report in the
attempt's runtime stream log, which the kernel's blocker record holds only the first 990
characters of). Each is redacted with ``redact_published`` before it is truncated, and
bounded by the constants below, so the projection stays deterministic and bounded in size.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.orchestrator.dispatcher import RESULT_REFUSED
from app.orchestrator.lifecycle import (
    EventKind,
    LifecycleStore,
    VerdictOutcome,
    lifecycle_view,
    sha256_of,
)

from .errors import redact_published
from .receipts import ReceiptLog

STATUS_SCHEMA = "clive.remote_engineering_status.v1"

MAX_FINDINGS = 10
MAX_FINDING_CHARS = 600
MAX_FAILED_CHECKS = 5
MAX_CHECK_TAIL_LINES = 40
MAX_CHECK_TAIL_CHARS = 4000
MAX_WORKER_REPORT_CHARS = 4000
_MAX_LABEL_CHARS = 40
_MAX_EVIDENCE_BYTES = 256 * 1024
_MAX_STREAM_TAIL_BYTES = 1024 * 1024

# How the dispatcher words a block whose reason is the worker's own report, by report status.
_WORKER_REPORT_PREFIXES = {
    "blocked": "worker reported blocked: ",
    "owner_decision_required": "worker reports an owner decision is required: ",
}
_BLOCKED_STAGES = ("BLOCKED", "OWNER_GATE")

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
    runtime_root: Path | None = None,
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
            # The blocker is the worker's own report for a worker-reported block, so it is
            # redacted like ``worker_report`` rather than published beside it unredacted.
            for field_name in ("stage_reason", "blocker"):
                if isinstance(item[field_name], str):
                    item[field_name] = redact_published(item[field_name])
            item["open_findings"] = _open_findings(store, task["task_id"])
            item["failed_checks"] = _failed_checks(task)
            item["worker_report"] = _worker_report(task, runtime_root)
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


def _bounded(text: object, limit: int) -> str:
    """Redacted first, then cut: a cut must never leave part of a secret its shape would have matched."""
    return redact_published(str(text))[:limit]


def _open_findings(store: LifecycleStore, task_id: str) -> list[dict]:
    """The material findings of the task's latest admitted verdict, across its revisions.

    A refused verdict decided nothing and is skipped; a READY verdict leaves nothing open.
    Fencing tokens rise across a task's revisions, so (token, admission) orders them all.
    """
    latest = None
    for attempt in store.read_attempts(task_id):
        for admission in store.read_admissions(task_id, attempt.attempt_id):
            if admission.outcome is VerdictOutcome.REFUSED:
                continue
            key = (attempt.fencing_token, admission.admission_seq)
            if latest is None or key > latest[0]:
                latest = (key, admission)
    if latest is None or latest[1].outcome is not VerdictOutcome.REJECTED_BY_VERDICT:
        return []
    try:
        payload = json.loads((store.root / latest[1].payload_path).read_bytes())
    except (OSError, ValueError):
        return []
    findings = payload.get("findings") if isinstance(payload, dict) else None
    out: list[dict] = []
    for finding in findings if isinstance(findings, list) else ():
        if not isinstance(finding, dict) or finding.get("material") is not True:
            continue
        item = {
            "finding_id": _bounded(finding.get("finding_id", ""), _MAX_LABEL_CHARS),
            "finding": _bounded(finding.get("finding", ""), MAX_FINDING_CHARS),
        }
        if isinstance(finding.get("severity"), str):
            item["severity"] = _bounded(finding["severity"], _MAX_LABEL_CHARS)
        out.append(item)
        if len(out) == MAX_FINDINGS:
            break
    return out


def _check_outcome(path: str, digest: str | None) -> dict | None:
    """A check evidence file, only while its bytes are still the ones the kernel recorded."""
    try:
        file = Path(path)
        if file.stat().st_size > _MAX_EVIDENCE_BYTES:
            return None
        raw = file.read_bytes()
        if sha256_of(raw) != digest:
            return None
        data = json.loads(raw)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _output_tail(data: dict) -> str:
    text = "\n".join(
        part.rstrip("\n") for part in (data.get("stdout_tail"), data.get("stderr_tail"))
        if isinstance(part, str) and part
    )
    tail = "\n".join(redact_published(text).splitlines()[-MAX_CHECK_TAIL_LINES:])
    return tail[-MAX_CHECK_TAIL_CHARS:]


def _failed_checks(task: dict) -> list[dict]:
    """The failing checks of the task's current attempt, when the dispatcher refused its result."""
    refused = any(
        event["kind"] == EventKind.CANCELLED.value and (event["note"] or "").startswith(RESULT_REFUSED)
        for event in task.get("history") or ()
    )
    if not refused:
        return []
    out: list[dict] = []
    for evidence in task.get("evidence") or ():
        name = evidence.get("name") or ""
        if not name.startswith("check-") or not evidence.get("path"):
            continue
        data = _check_outcome(evidence["path"], evidence.get("sha256"))
        if data is None or data.get("exit_code") == 0:
            continue
        code = data.get("exit_code")
        out.append({
            "name": _bounded(name.removeprefix("check-"), _MAX_LABEL_CHARS),
            "exit_code": code if isinstance(code, int) and not isinstance(code, bool) else None,
            "output_tail": _output_tail(data),
        })
        if len(out) == MAX_FAILED_CHECKS:
            break
    return out


def _reported_text(runtime_root: Path | None, attempt_id: object, status: str) -> str | None:
    """``reason or summary`` of the attempt's structured report, as the worker wrote it.

    The authoritative record is the dispatcher's stream log of the attempt,
    ``<runtime_root>/logs/<attempt_id>.stream.jsonl`` (``Dispatcher._paths``), whose ``result``
    event carries the report as ``structured_output``. It is the worker's last event, so only a
    bounded tail of the log is read.
    """
    if runtime_root is None or not isinstance(attempt_id, str) or Path(attempt_id).name != attempt_id:
        return None
    try:
        with (Path(runtime_root) / "logs" / f"{attempt_id}.stream.jsonl").open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - _MAX_STREAM_TAIL_BYTES))
            tail = handle.read(_MAX_STREAM_TAIL_BYTES)
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(event, dict) or event.get("type") != "result":
            continue
        report = event.get("structured_output")
        if not isinstance(report, dict) or report.get("status") != status:
            return None
        text = report.get("reason") or report.get("summary")
        return text if isinstance(text, str) else None
    return None


def _worker_report(task: dict, runtime_root: Path | None) -> str | None:
    """The worker's own report of why it stopped, whole, cut only to ``MAX_WORKER_REPORT_CHARS``.

    Read from the attempt's stream log; the kernel's blocker record is the dispatcher's prefix
    and the same text cut to 990 characters, so a log report is published only when the blocker
    is its start. Without the log, the blocker's text is all there is.
    """
    blocker = task.get("blocker")
    if task.get("stage") not in _BLOCKED_STAGES or not isinstance(blocker, str):
        return None
    for status, prefix in _WORKER_REPORT_PREFIXES.items():
        if blocker.startswith(prefix):
            text = _reported_text(runtime_root, task.get("attempt_id"), status)
            if text is None or not (prefix + text).startswith(blocker):
                text = blocker.removeprefix(prefix)
            return _bounded(text, MAX_WORKER_REPORT_CHARS)
    return None
