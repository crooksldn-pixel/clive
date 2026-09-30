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

What each build went through, so the owner's assistant can answer "did it retry?", "why is it
blocked?" and "did it land?" (``engineering_status``, app/tools/engineering_tools.py). Two sources:

- ``build_history``, read here from the kernel's own records whatever the Dispatcher's version:
  every builder attempt of the task (``read_attempts``), grouped by task revision -- its kind (build,
  repair, integration) and how many attempts it took, and of those how many were cancelled for a
  transient failure or had their result refused by CLIVE's checks (the Dispatcher's own cancellation
  prefixes, ``read_events``) -- how many times an admitted review verdict asked for changes, and the
  objective's ``max_repair_rounds``. Counts and fixed words only: no note text is copied.
- ``attempts``, ``repairs``, ``generated`` and ``landing``, published when ``Dispatcher.status()``
  reports them (one entry per objective): each attempt's id, revision, outcome (launched, cancelled,
  refused, candidate, blocked), reason and time, oldest first; repair rounds used after a review and
  after a red GitHub run, and their limit; the paths the loop regenerated itself; and where the build
  stands with the trunk (off, waiting, landed, refused, refreshing). A key the Dispatcher does not
  report is absent, meaning unknown, never "none"; one it reports as null stays null.

Every value is rebuilt field by field, never copied: words from a fixed set, SHAs as 40 hex, times as
ISO-8601, counts as bounded non-negative integers, paths as plain repository paths, and all text one
line, redacted with the Dispatcher's own secret rules (URL userinfo, token shapes, credential
assignments, long mixed-case runs) and the app's customer-shape rules (e-mail, card, postcode, phone;
``app/logging/turnlog.py``) before it is cut to a bound. Lists are bounded too.

``waiting_requests`` carries the requests intake deferred because their base commit had not reached
the engineering repo yet (waits.py): id, locator, digest, fixed words, since when, and when it is
refused if still missing. A request with a receipt is never listed there.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime

from app.logging.turnlog import redact_text as _redact_customer_shapes
from app.orchestrator.dispatcher import RESULT_REFUSED, TRANSIENT
from app.orchestrator.lifecycle import EventKind, LifecycleStore, VerdictOutcome, lifecycle_view
from app.orchestrator.objectives import ObjectiveStore
from app.orchestrator.workers.check_server import redact as _redact_secrets

from .receipts import ReceiptLog
from .waits import WaitLog

STATUS_SCHEMA = "clive.remote_engineering_status.v1"

# ``Dispatcher.status()``'s per-build keys, each published only when the entry carries it.
LOOP_FIELDS = ("attempts", "repairs", "generated", "landing")
ATTEMPT_OUTCOMES = frozenset({"launched", "cancelled", "refused", "candidate", "blocked"})
LANDING_STATES = frozenset({"off", "waiting", "landed", "refused", "refreshing"})
TASK_KINDS = frozenset({"build", "repair", "review", "evidence", "integration"})
MAX_ATTEMPTS = 20
MAX_REVISIONS = 20
MAX_GENERATED = 20
MAX_LOOP_TEXT = 500
MAX_PATH_CHARS = 200
MAX_COUNT = 10_000
_MAX_INPUT_CHARS = 8 * MAX_LOOP_TEXT
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ATTEMPT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_REPO_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/-]{0,199}$")
# A URL's user part: git names the remote it failed to reach, and that name can carry a credential.
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]*@")

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
    progress: Mapping[str, Mapping] | None = None,
    waits: WaitLog | None = None,
) -> dict:
    """``progress`` is ``Dispatcher.status()`` keyed by objective id; ``waits`` defaults to the
    wait log beside ``receipts``, under the same adapter root."""
    # A repair is a new task revision (r+1); the earlier revision becomes OBSOLETE. The
    # task's current stage, candidate, review, acceptance and integration are therefore
    # those of its highest recorded revision, exactly as the Dispatcher itself reads them.
    latest: dict[str, dict] = {}
    for task in lifecycle_view(store, now=now)["tasks"]:
        current = latest.get(task["task_id"])
        if current is None or task["revision"] > current["revision"]:
            latest[task["task_id"]] = task
    tasks = store.read_tasks()   # read once for every request's history; lifecycle_view just read them too
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
            history = build_history(store, receipt.task_id, objective_id=receipt.objective_id, tasks=tasks)
            if history is not None:
                item["build_history"] = history
        entry = (progress or {}).get(receipt.objective_id) if receipt.objective_id else None
        if isinstance(entry, Mapping):
            item.update(loop_fields(entry))
        requests.append(item)
    decided = {receipt["request_id"] for receipt in requests}
    waits = waits if waits is not None else WaitLog(receipts.dir.parent)
    waiting = [wait.outcome() for wait in waits.read_all() if wait.request_id not in decided]
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
        "waiting_requests": waiting,
    }


def build_history(
    store: LifecycleStore, task_id: str, *, objective_id: str | None = None, tasks: Sequence | None = None
) -> dict | None:
    """What the kernel's records say this task's builds went through, in counts and fixed words.

    ``attempts`` is every builder attempt of every revision. Each revision says its kind and how many
    attempts it took; an attempt past the first in a revision is a retry, and ``transient`` and
    ``refused`` count the attempts the Dispatcher cancelled for a transient failure or for a result
    CLIVE's checks refused. ``review_changes_requested`` counts admitted verdicts that asked for
    changes. None when the records cannot be read: this is a projection, never a reason to stop.
    ``tasks`` is ``store.read_tasks()`` when the caller has already read it.
    """
    try:
        tasks = store.read_tasks() if tasks is None else tasks
        kinds = {task.revision: task.kind.value for task in tasks if task.task_id == task_id}
        revisions = {
            revision: {"revision": revision, "kind": _word(kind, TASK_KINDS), "attempts": 0,
                       "transient": 0, "refused": 0}
            for revision, kind in sorted(kinds.items())
        }
        attempts = 0
        changes_requested = 0
        for attempt in store.read_attempts(task_id):
            attempts += 1
            row = revisions.setdefault(attempt.task_revision, {
                "revision": attempt.task_revision, "kind": None, "attempts": 0, "transient": 0, "refused": 0,
            })
            row["attempts"] += 1
            for event in store.read_events(task_id, attempt.attempt_id):
                if event.kind is EventKind.CANCELLED:
                    note = event.note or ""
                    if note.startswith(TRANSIENT):
                        row["transient"] += 1
                    elif note.startswith(RESULT_REFUSED):
                        row["refused"] += 1
                    break
            changes_requested += sum(
                1 for admission in store.read_admissions(task_id, attempt.attempt_id)
                if admission.outcome is VerdictOutcome.REJECTED_BY_VERDICT
            )
        objective = ObjectiveStore(store, journal=False).read(objective_id) if objective_id else None
    except (OSError, ValueError):
        return None
    listed = [revisions[r] for r in sorted(revisions)][-MAX_REVISIONS:]
    return {
        "attempts": _count(attempts),
        "revisions": [{key: (_count(value) if isinstance(value, int) else value) for key, value in row.items()}
                      for row in listed],
        "review_changes_requested": _count(changes_requested),
        "max_repair_rounds": _count(objective.max_repair_rounds) if objective is not None else None,
    }


def loop_fields(entry: Mapping) -> dict:
    """The Dispatcher's per-build keys that ``entry`` carries, rebuilt bounded and redacted.

    A key the entry does not carry is left out (unknown); one it carries as null stays null, and so
    does one of the wrong shape."""
    out: dict = {}
    if "attempts" in entry:
        attempts = entry["attempts"]
        out["attempts"] = (
            [_attempt(a) for a in [a for a in attempts if isinstance(a, Mapping)][-MAX_ATTEMPTS:]]
            if isinstance(attempts, (list, tuple)) else None
        )
    if "repairs" in entry:
        repairs = entry["repairs"]
        out["repairs"] = (
            {"review": _count(repairs.get("review")), "ci": _count(repairs.get("ci")), "max": _count(repairs.get("max"))}
            if isinstance(repairs, Mapping) else None
        )
    if "generated" in entry:
        generated = entry["generated"]
        out["generated"] = (
            [path for path in (_path(p) for p in list(generated)[:MAX_GENERATED]) if path]
            if isinstance(generated, (list, tuple)) else None
        )
    if "landing" in entry:
        landing = entry["landing"]
        out["landing"] = (
            {
                "state": _word(landing.get("state"), LANDING_STATES),
                "sha": _sha(landing.get("sha")),
                "at": _time(landing.get("at")),
                "reason": _text(landing.get("reason")),
            }
            if isinstance(landing, Mapping) else None
        )
    return out


def _attempt(attempt: Mapping) -> dict:
    attempt_id = attempt.get("attempt_id")
    revision = attempt.get("revision")
    return {
        "attempt_id": attempt_id if isinstance(attempt_id, str) and _ATTEMPT_ID.fullmatch(attempt_id) else None,
        "revision": revision if _count(revision) else None,
        "outcome": _word(attempt.get("outcome"), ATTEMPT_OUTCOMES),
        "reason": _text(attempt.get("reason")),
        "at": _time(attempt.get("at")),
    }


def _word(value: object, allowed: frozenset[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_COUNT:
        return None
    return value


def _sha(value: object) -> str | None:
    return value if isinstance(value, str) and _SHA40.fullmatch(value) else None


def _time(value: object) -> str | None:
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str) and len(value) <= 64:
        try:
            stamp = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return stamp.isoformat() if stamp.tzinfo is not None and stamp.utcoffset() is not None else None


def _path(value: object) -> str | None:
    """A plain repository path, or nothing: never text, and never anything a redaction would change."""
    if not isinstance(value, str) or not _REPO_PATH.fullmatch(value) or ".." in value.split("/"):
        return None
    return value if _clean(value) == value else None


def _text(value: object, limit: int = MAX_LOOP_TEXT) -> str | None:
    """One line of the loop's own words, redacted before the cut (a cut made first could leave a
    secret's head that no longer looks like one), at most ``limit`` characters."""
    if not isinstance(value, str):
        return None
    if len(value) > _MAX_INPUT_CHARS:
        # Bound the work, and drop the word the bound cut through: a cut secret no longer looks like one.
        head = value[:_MAX_INPUT_CHARS]
        cut = max(head.rfind(" "), head.rfind("\n"), head.rfind("\t"))
        value = head[:cut] if cut > 0 else ""
    text = " ".join(_clean(value).split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _clean(text: str) -> str:
    """Secrets (the Dispatcher's rules, and a URL's userinfo) and customer shapes (the app's log rules)."""
    return _redact_customer_shapes(_redact_secrets(_URL_USERINFO.sub(r"\1[redacted]@", text)))
