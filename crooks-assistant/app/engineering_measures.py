"""The two measures the owner judges the build system by, from records that already exist.

NEXT_PHASE_2026-09-25.md section 3.7: hours from asking to seeing the change on the phone,
and minutes of the owner's attention per change. Per objective this reports the time from
submission to completion, to landing in the trunk and, where a deploy covers it, to
production; the number of review rounds; and the owner minutes attributed to it. Per day it
reports totals and medians of the same.

Everything here takes parsed data, never a live system:

- status projections: the ``clive.remote_engineering_status.v1`` documents the loops
  publish (``app.remote_engineering.status``). A request's submission time is its
  ``submitted_at`` when present, else the receipt's ``recorded_at``; it is complete when
  its stage is ``COMPLETE``, at its integration's ``at``.
- the trunk history: ``git log --first-parent`` of the trunk, newest first, as
  ``TrunkCommit`` records, plus optionally the parents of every commit reachable from it.
  A commit reaches the trunk with the first first-parent commit that brings it in, at that
  commit's committer date.
- a deploy log: ``{sha, deployed_at}`` records. A deploy covers a candidate when it deployed
  the candidate itself, or a trunk commit at or after the one that landed the candidate.
- an owner-attention log: ``{at, minutes, about}`` records, where ``about`` names a request,
  objective or task id, or a pull request (matched through the merge that landed it).

Nothing is guessed. An input that was not supplied leaves its columns empty (``None``) on
every row; an input that was supplied but holds no fact about a row leaves that row's cell
empty. Owner minutes that cannot be tied to exactly one objective are reported as
unattributed, never split. Days are UTC calendar days.

A second source is the loop's own records (``read_loop_records`` then ``measure_loop``):
the kernel's store (objectives, task revisions, attempts, verdict admissions, candidates,
acceptances, integrations, and each objective's stage as ``lifecycle_view`` reports it) and
the dispatcher's ``<runtime>/landings/<objective>.json`` records. They are read with the
store's read methods only: no lock, no layout, no write. Only fixed words, ids, SHAs,
counts, times and the objective's title reach that report; no finding, reason or note text.
Deploys and owner attention are recorded nowhere in them, so those measures stay empty.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "clive.engineering_measures.v1"
COMPLETE = "COMPLETE"

# ``git log`` formats the script uses; the parsers below read exactly these.
FIELD_SEP = "\x1f"
TRUNK_LOG_FORMAT = "%H%x1f%P%x1f%cI%x1f%s"
GRAPH_LOG_FORMAT = "%H%x1f%P"

_MERGE_PR = re.compile(r"^Merge pull request #(\d+)\b")
_SQUASH_PR = re.compile(r"\(#(\d+)\)\s*$")
_ABOUT_PR = re.compile(r"(?:^#|/pull/|\bpull request\s*#?|\bPR\s*#?)(\d+)\b", re.IGNORECASE)


class MeasuresError(ValueError):
    """An input record is malformed; measuring it anyway would be guessing."""


@dataclass(frozen=True)
class TrunkCommit:
    sha: str
    parents: tuple[str, ...]
    committed_at: datetime
    subject: str = ""


@dataclass(frozen=True)
class Landing:
    trunk_sha: str
    position: int  # 0 is the oldest commit of the supplied first-parent history
    at: datetime
    pull_request: str | None


@dataclass(frozen=True)
class Deploy:
    sha: str
    deployed_at: datetime


@dataclass(frozen=True)
class Attention:
    at: datetime
    minutes: float
    about: str


# ------------------------------------------------------------------ parsing


def parse_time(value: object, *, what: str) -> datetime | None:
    """An aware timestamp, ``None`` when absent. A naive or malformed one is refused."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise MeasuresError(f"{what}: expected an ISO-8601 timestamp, got {value!r}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MeasuresError(f"{what}: not an ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MeasuresError(f"{what}: timestamp has no timezone: {value!r}")
    return parsed


def _required_time(value: object, *, what: str) -> datetime:
    parsed = parse_time(value, what=what)
    if parsed is None:
        raise MeasuresError(f"{what}: timestamp is missing")
    return parsed


def read_json_lines(text: str, *, what: str) -> list[dict]:
    records = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MeasuresError(f"{what} line {number}: not JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise MeasuresError(f"{what} line {number}: expected a JSON object")
        records.append(record)
    return records


def parse_trunk_log(text: str) -> list[TrunkCommit]:
    """``git log --first-parent --format=TRUNK_LOG_FORMAT`` output, in the order git printed it."""
    commits = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split(FIELD_SEP, 3)
        if len(fields) != 4:
            raise MeasuresError(f"trunk log line {number}: expected 4 fields, got {len(fields)}")
        sha, parents, committed_at, subject = fields
        commits.append(
            TrunkCommit(
                sha=sha.strip().lower(),
                parents=tuple(parent.lower() for parent in parents.split()),
                committed_at=_required_time(committed_at.strip(), what=f"trunk log line {number}"),
                subject=subject,
            )
        )
    return commits


def parse_graph_log(text: str) -> dict[str, tuple[str, ...]]:
    """``git log --format=GRAPH_LOG_FORMAT`` output: every reachable commit's parents."""
    graph: dict[str, tuple[str, ...]] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split(FIELD_SEP)
        if len(fields) != 2:
            raise MeasuresError(f"commit graph line {number}: expected 2 fields, got {len(fields)}")
        graph[fields[0].strip().lower()] = tuple(parent.lower() for parent in fields[1].split())
    return graph


def _deploys(records: Iterable[Mapping]) -> list[Deploy]:
    deploys = []
    for number, record in enumerate(records, 1):
        sha = record.get("sha")
        if not isinstance(sha, str) or not sha.strip():
            raise MeasuresError(f"deploy log record {number}: sha is missing")
        at = _required_time(record.get("deployed_at"), what=f"deploy log record {number}")
        deploys.append(Deploy(sha=sha.strip().lower(), deployed_at=at))
    return deploys


def _attention(records: Iterable[Mapping]) -> list[Attention]:
    entries = []
    for number, record in enumerate(records, 1):
        minutes = record.get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int | float) or minutes < 0:
            raise MeasuresError(f"attention log record {number}: minutes must be a number >= 0")
        about = record.get("about")
        if not isinstance(about, str) or not about.strip():
            raise MeasuresError(f"attention log record {number}: about is missing")
        at = _required_time(record.get("at"), what=f"attention log record {number}")
        entries.append(Attention(at=at, minutes=float(minutes), about=about.strip()))
    return entries


# ------------------------------------------------------------------ the trunk


def pull_request_of(subject: str) -> str | None:
    """The pull request a trunk commit's subject says it merged, as ``#N``."""
    match = _MERGE_PR.search(subject) or _SQUASH_PR.search(subject)
    return f"#{match.group(1)}" if match else None


def pull_request_about(about: str) -> str | None:
    match = _ABOUT_PR.search(about)
    return f"#{match.group(1)}" if match else None


def trunk_landings(
    trunk: Sequence[TrunkCommit], graph: Mapping[str, Sequence[str]] | None = None
) -> dict[str, Landing]:
    """When each commit reached the trunk: the first-parent commit that first brought it in.

    ``trunk`` is ``git log --first-parent`` order, newest first. Walking it oldest first,
    each trunk commit lands itself and its merged-in parents. With ``graph`` the walk
    continues through those parents' ancestry, so a candidate that reached the trunk only
    inside a later branch's merge lands with that merge; without it, only a merge's direct
    parents are known. The oldest commit's own ancestry predates the history and stays
    unknown.
    """
    landed: dict[str, Landing] = {}
    for position, commit in enumerate(reversed(trunk)):
        landing = Landing(commit.sha, position, commit.committed_at, pull_request_of(commit.subject))
        landed.setdefault(commit.sha, landing)
        pending = list(commit.parents[1:])
        while pending:
            sha = pending.pop()
            if sha in landed:
                continue
            landed[sha] = landing
            if graph is not None:
                pending.extend(graph.get(sha, ()))
    return landed


def _production(
    candidate: str, landing: Landing | None, deploys: Sequence[Deploy], positions: Mapping[str, int]
) -> Deploy | None:
    covering = []
    for deploy in deploys:
        if deploy.sha == candidate:
            covering.append(deploy)
        elif landing is not None:
            position = positions.get(deploy.sha)
            if position is not None and position >= landing.position:
                covering.append(deploy)
    return min(covering, key=lambda deploy: deploy.deployed_at, default=None)


# ------------------------------------------------------------------ measuring


def _hours(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 3600, 3)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _day(value: datetime) -> str:
    return value.astimezone(UTC).date().isoformat()


def _requests(projections: Sequence[Mapping]) -> list[Mapping]:
    """Every request once. One seen in several projections is read from the latest generated."""
    chosen: dict[str, tuple[tuple, Mapping]] = {}
    for index, projection in enumerate(projections):
        if not isinstance(projection, Mapping):
            raise MeasuresError(f"status projection {index + 1}: expected a JSON object")
        generated =parse_time(projection.get("generated_at"), what=f"status projection {index + 1}")
        key = (generated is not None, generated or datetime.min.replace(tzinfo=UTC), index)
        for request in projection.get("requests") or ():
            request_id = request.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                raise MeasuresError(f"status projection {index + 1}: a request has no request_id")
            current = chosen.get(request_id)
            if current is None or key > current[0]:
                chosen[request_id] = (key, request)
    return [request for _, request in chosen.values()]


def _review_rounds(request: Mapping) -> int | None:
    """Admitted verdicts on the current revision, plus one per earlier revision.

    Every revision after the first is a repair the dispatcher routes only from an admitted
    CHANGES_REQUIRED verdict on the one before it. A refused verdict (a fence failed) was
    never a review round.
    """
    revision = request.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        return None
    review = request.get("review") or {}
    verdicts = review.get("verdicts") or ()
    return revision - 1 + sum(1 for verdict in verdicts if verdict.get("outcome") != "refused")


def _row(
    request: Mapping,
    *,
    landings: Mapping[str, Landing] | None,
    positions: Mapping[str, int],
    deploys: Sequence[Deploy] | None,
) -> dict:
    request_id = request["request_id"]
    what = f"request {request_id}"
    submitted = parse_time(request.get("submitted_at") or request.get("recorded_at"), what=what)
    integration = request.get("integration")
    completed = None
    if request.get("stage") == COMPLETE and isinstance(integration, Mapping):
        completed = parse_time(integration.get("at"), what=f"{what} integration")
    candidate = request.get("candidate_sha")
    candidate = candidate.lower() if isinstance(candidate, str) and candidate else None
    landing = landings.get(candidate) if landings is not None and candidate else None
    deploy = (
        _production(candidate, landing, deploys, positions)
        if deploys is not None and candidate
        else None
    )
    return {
        "request_id": request_id,
        "objective_id": request.get("objective_id"),
        "task_id": request.get("task_id"),
        "outcome": request.get("outcome"),
        "stage": request.get("stage"),
        "candidate_sha": candidate,
        "day": _day(submitted) if submitted else None,
        "submitted_at": _iso(submitted),
        "completed_at": _iso(completed),
        "hours_to_complete": _hours(submitted, completed),
        "landed_at": _iso(landing.at) if landing else None,
        "landed_via": landing.trunk_sha if landing else None,
        "pull_request": landing.pull_request if landing else None,
        "hours_to_trunk": _hours(submitted, landing.at if landing else None),
        "deployed_at": _iso(deploy.deployed_at) if deploy else None,
        "deployed_sha": deploy.sha if deploy else None,
        "hours_to_production": _hours(submitted, deploy.deployed_at if deploy else None),
        "review_rounds": _review_rounds(request),
        "owner_minutes": None,
    }


def _attribute(entries: Sequence[Attention], rows: Sequence[dict], *, have_trunk: bool) -> list[dict]:
    """Add each entry's minutes to the one objective it names; return those naming none or several."""
    by_id: dict[str, set[str]] = {}
    by_pr: dict[str, set[str]] = {}
    by_request = {row["request_id"]: row for row in rows}
    for row in rows:
        row["owner_minutes"] = 0.0
        for key in ("request_id", "objective_id", "task_id"):
            if row[key]:
                by_id.setdefault(row[key], set()).add(row["request_id"])
        if row["pull_request"]:
            by_pr.setdefault(row["pull_request"], set()).add(row["request_id"])
    unattributed = []
    for entry in entries:
        reason = None
        targets = by_id.get(entry.about)
        if targets is None:
            pull_request = pull_request_about(entry.about)
            if pull_request is None:
                reason = "names no known request, objective, task or pull request"
            elif not have_trunk:
                reason = f"pull request {pull_request} cannot be matched without the trunk history"
            else:
                targets = by_pr.get(pull_request)
                if targets is None:
                    reason = f"no objective landed through pull request {pull_request}"
        if targets is not None and len(targets) > 1:
            reason = f"names {len(targets)} objectives; minutes are not split"
        if reason is not None:
            unattributed.append(
                {"at": entry.at.isoformat(), "minutes": entry.minutes, "about": entry.about, "reason": reason}
            )
            continue
        (request_id,) = targets
        by_request[request_id]["owner_minutes"] += entry.minutes
    return unattributed


def _median(values: Iterable[float | int | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(statistics.median(present), 3) if present else None


def _total(values: Iterable[float | int | None]) -> float | int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _total_hours(values: Iterable[float | None]) -> float | None:
    total = _total(values)
    return round(total, 3) if total is not None else None


def _aggregate(
    rows: Sequence[dict],
    deploys: Sequence[Deploy] | None,
    attention: Sequence[Attention] | None,
    *,
    have_trunk: bool,
) -> dict:
    def column(name: str) -> list:
        return [row[name] for row in rows]

    return {
        "objectives": len(rows),
        "completed": sum(1 for row in rows if row["completed_at"]),
        "landed": sum(1 for row in rows if row["landed_at"]) if have_trunk else None,
        "deployed": sum(1 for row in rows if row["deployed_at"]) if deploys is not None else None,
        "deploys": len(deploys) if deploys is not None else None,
        "total_hours_to_complete": _total_hours(column("hours_to_complete")),
        "median_hours_to_complete": _median(column("hours_to_complete")),
        "total_hours_to_trunk": _total_hours(column("hours_to_trunk")),
        "median_hours_to_trunk": _median(column("hours_to_trunk")),
        "total_hours_to_production": _total_hours(column("hours_to_production")),
        "median_hours_to_production": _median(column("hours_to_production")),
        "review_rounds": _total(column("review_rounds")),
        "median_review_rounds": _median(column("review_rounds")),
        "owner_minutes_attributed": (
            sum(row["owner_minutes"] for row in rows) if attention is not None else None
        ),
        "median_owner_minutes": _median(column("owner_minutes")),
        "owner_minutes_logged": (
            sum(entry.minutes for entry in attention) if attention is not None else None
        ),
    }


def measure(
    *,
    status_projections: Sequence[Mapping],
    trunk: Sequence[TrunkCommit] | None = None,
    graph: Mapping[str, Sequence[str]] | None = None,
    deploy_log: Iterable[Mapping] | None = None,
    attention_log: Iterable[Mapping] | None = None,
) -> dict:
    """The measures, per objective, per day and in total. ``None`` means the input was not supplied."""
    landings = trunk_landings(trunk, graph) if trunk is not None else None
    positions = {commit.sha: position for position, commit in enumerate(reversed(trunk or ()))}
    deploys = _deploys(deploy_log) if deploy_log is not None else None
    attention = _attention(attention_log) if attention_log is not None else None

    rows = [
        _row(request, landings=landings, positions=positions, deploys=deploys)
        for request in _requests(status_projections)
    ]
    rows.sort(
        key=lambda row: (
            row["submitted_at"] is None,
            datetime.fromisoformat(row["submitted_at"]) if row["submitted_at"] else datetime.min.replace(tzinfo=UTC),
            row["request_id"],
        )
    )
    unattributed = (
        _attribute(attention, rows, have_trunk=landings is not None) if attention is not None else []
    )

    days = sorted(
        {row["day"] for row in rows if row["day"]}
        | {_day(deploy.deployed_at) for deploy in deploys or ()}
        | {_day(entry.at) for entry in attention or ()}
    )
    per_day = [
        {
            "day": day,
            **_aggregate(
                [row for row in rows if row["day"] == day],
                [deploy for deploy in deploys if _day(deploy.deployed_at) == day]
                if deploys is not None
                else None,
                [entry for entry in attention if _day(entry.at) == day] if attention is not None else None,
                have_trunk=landings is not None,
            ),
        }
        for day in days
    ]
    return {
        "schema": SCHEMA,
        "inputs": {
            "status_projections": len(status_projections),
            "trunk_history": trunk is not None,
            "commit_graph": graph is not None,
            "deploy_log": deploys is not None,
            "attention_log": attention is not None,
        },
        "objectives": rows,
        "days": per_day,
        "totals": _aggregate(rows, deploys, attention, have_trunk=landings is not None),
        "unattributed_attention": unattributed,
    }


# ------------------------------------------------------------------ markdown


_OBJECTIVE_COLUMNS = (
    ("Request", "request_id"),
    ("Objective", "objective_id"),
    ("Outcome", "outcome"),
    ("Stage", "stage"),
    ("Submitted", "submitted_at"),
    ("Hours to complete", "hours_to_complete"),
    ("Hours to trunk", "hours_to_trunk"),
    ("Pull request", "pull_request"),
    ("Hours to production", "hours_to_production"),
    ("Review rounds", "review_rounds"),
    ("Owner minutes", "owner_minutes"),
)

_AGGREGATE_COLUMNS = (
    ("Objectives", "objectives"),
    ("Completed", "completed"),
    ("Landed", "landed"),
    ("Deployed", "deployed"),
    ("Deploys", "deploys"),
    ("Total h to complete", "total_hours_to_complete"),
    ("Median h to complete", "median_hours_to_complete"),
    ("Total h to trunk", "total_hours_to_trunk"),
    ("Median h to trunk", "median_hours_to_trunk"),
    ("Total h to production", "total_hours_to_production"),
    ("Median h to production", "median_hours_to_production"),
    ("Review rounds", "review_rounds"),
    ("Median review rounds", "median_review_rounds"),
    ("Owner min attributed", "owner_minutes_attributed"),
    ("Median owner min", "median_owner_minutes"),
    ("Owner min logged", "owner_minutes_logged"),
)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).replace("|", "\\|")


def _table(columns: Sequence[tuple[str, str]], rows: Sequence[Mapping]) -> list[str]:
    lines = [
        "| " + " | ".join(title for title, _ in columns) + " |",
        "|" + "---|" * len(columns),
    ]
    lines += ["| " + " | ".join(_cell(row.get(key)) for _, key in columns) + " |" for row in rows]
    return lines


def render_markdown(report: Mapping) -> str:
    inputs = report["inputs"]
    supplied = ", ".join(
        f"{name.replace('_', ' ')}: {'yes' if inputs[name] else 'not supplied'}"
        for name in ("trunk_history", "commit_graph", "deploy_log", "attention_log")
    )
    lines = [
        "# Engineering measures",
        "",
        f"Status projections: {inputs['status_projections']}; {supplied}.",
        "Hours are from submission. Days are UTC. An empty cell means the record it needs was not "
        "supplied or holds nothing about that row; nothing is estimated.",
        "",
        "## Per objective",
        "",
        *_table(_OBJECTIVE_COLUMNS, report["objectives"]),
        "",
        "## Per day",
        "",
        *_table((("Day", "day"), *_AGGREGATE_COLUMNS), report["days"]),
        "",
        "## Totals",
        "",
        *_table(_AGGREGATE_COLUMNS, [report["totals"]]),
    ]
    if report["unattributed_attention"]:
        lines += ["", "## Unattributed owner attention", ""]
        lines += [
            f"- {entry['at']}: {entry['minutes']:g} min about {entry['about']!r} ({entry['reason']})"
            for entry in report["unattributed_attention"]
        ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ the loop's own records


LOOP_SCHEMA = "clive.engineering_loop_measures.v1"
LANDING_SCHEMA = "clive.landing.v1"
NOT_RECORDED = "not recorded anywhere; left empty, never estimated"
_LANDING_STATES = frozenset({"waiting", "refreshing", "landed", "refused"})
_LANDED_BY = frozenset({"loop", "unconfirmed", "other"})
_EXACT_SHA = re.compile(r"^[0-9a-f]{40}$")
_BLOCKED_STAGES = frozenset({"BLOCKED", "OWNER_GATE"})


def _earliest(values: Iterable[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _landing(path: Path, objective_id: str) -> dict | None:
    """The objective's ``clive.landing.v1`` record as fixed words, a SHA and a time; ``None`` when it is not one.

    A landed record whose ``landed_at`` is not an aware ISO-8601 time is not one either: it is
    ignored and counted like any other, rather than ending the report. A landed record with no
    ``by`` predates the loop recording who landed a SHA (1 October 2026): who landed it is not
    recorded, and ``by_recorded`` says so. Its reason, evidence path and review details are never
    read into the report."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if (
        not isinstance(record, dict)
        or record.get("schema") != LANDING_SCHEMA
        or record.get("objective_id") != objective_id
    ):
        return None
    state = record.get("state")
    state = state if isinstance(state, str) and state in _LANDING_STATES else "unrecognised"
    landed = state == "landed"
    sha = record.get("sha")
    sha = sha.lower() if isinstance(sha, str) and _EXACT_SHA.match(sha.lower()) else None
    landed_at = None
    if landed:
        try:
            landed_at = parse_time(record.get("landed_at"), what=f"landing record of {objective_id}")
        except MeasuresError:
            return None
    by = record.get("by")
    by_recorded = landed and by is not None
    if not by_recorded:
        by = None
    elif not (isinstance(by, str) and by in _LANDED_BY):
        by = "unrecognised"
    return {
        "state": state,
        "sha": sha if landed else None,
        "by": by,
        "by_recorded": by_recorded,
        "landed_at": landed_at,
    }


def read_loop_records(store_root: Path, runtime_root: Path, *, now: datetime | None = None) -> dict:
    """The facts ``measure_loop`` takes, from the kernel's store and the dispatcher's landing records.

    Read-only: the store's read methods and ``lifecycle_view``, never a verb, ``ensure_layout``
    or the writer lock, and nothing is created under either root. A store that is missing or
    cannot be read is a ``MeasuresError``; a readable store with no objectives has none. An
    objective's tasks are the revisions of the task with its id. A landing file that is not a
    ``clive.landing.v1`` record of that objective is ignored and counted.
    """
    from app.orchestrator.contracts import TaskKind
    from app.orchestrator.lifecycle import LifecycleStore, VerdictOutcome, lifecycle_view
    from app.orchestrator.objectives import ObjectiveStore

    root = Path(store_root)
    if not root.is_dir():
        raise MeasuresError(f"engineering store {root} does not exist or is not a directory")
    store = LifecycleStore(root)
    try:
        os.listdir(root)
        objectives = ObjectiveStore(store, journal=False).read_all()
        view = lifecycle_view(store, now=now or datetime.now(UTC))
        tasks = store.read_tasks()
        attempts = store.read_attempts()
        admissions = {
            (attempt.task_id, attempt.attempt_id): store.read_admissions(attempt.task_id, attempt.attempt_id)
            for attempt in attempts
        }
        results = store.read_results()
        acceptances = store.read_acceptances()
        integrations = store.read_integrations()
    except (OSError, ValueError) as exc:
        raise MeasuresError(f"engineering store {root} cannot be read: {exc}") from exc

    landings_dir = Path(runtime_root) / "landings"
    landings_read = landings_dir.is_dir()
    ignored = 0
    facts = []
    for objective in objectives:
        objective_id = objective.objective_id
        revisions = [task for task in tasks if task.task_id == objective_id]
        its_attempts = [attempt for attempt in attempts if attempt.task_id == objective_id]
        latest = max(
            (task for task in view["tasks"] if task["task_id"] == objective_id),
            key=lambda task: task["revision"],
            default=None,
        )
        stage = latest["stage"] if latest else None
        landing = None
        path = landings_dir / f"{objective_id}.json"
        try:
            if landings_read and path.is_file():
                landing = _landing(path, objective_id)
                ignored += landing is None
        except OSError as exc:
            raise MeasuresError(f"landing record {path} cannot be read: {exc}") from exc
        facts.append(
            {
                "objective_id": objective_id,
                "title": objective.title,
                "recorded_at": objective.created_at,
                "base_sha": str(objective.base_sha).lower(),
                "revisions": len(revisions),
                "repairs_created": sorted(task.created_at for task in revisions if task.kind is TaskKind.REPAIR),
                "refreshes": sum(1 for task in revisions if task.kind is TaskKind.INTEGRATION),
                "attempts": len(its_attempts),
                "review_rounds": sum(
                    1
                    for attempt in its_attempts
                    for admission in admissions[(attempt.task_id, attempt.attempt_id)]
                    if admission.outcome is not VerdictOutcome.REFUSED
                ),
                "stage": stage,
                "blocker_class": latest["blocker_class"] if stage in _BLOCKED_STAGES else None,
                "first_candidate_at": _earliest(
                    result.completed_at for result in results if result.task_id == objective_id and result.result_sha
                ),
                "accepted_at": _earliest(a.accepted_at for a in acceptances if a.task_id == objective_id),
                "integrated_at": _earliest(i.integrated_at for i in integrations if i.task_id == objective_id),
                "landing": landing,
            }
        )
    return {
        "store": str(root),
        "runtime_root": str(runtime_root),
        "landings_read": landings_read,
        "landings_source": str(landings_dir) if landings_read else f"not read: {landings_dir} does not exist",
        "landing_records_ignored": ignored,
        "objectives": facts,
    }


def _loop_row(fact: Mapping) -> dict:
    """One objective. Accepted and integrated are its first acceptance and integration, of any revision."""
    landing = fact["landing"] or {}
    recorded = fact["recorded_at"]
    return {
        "objective_id": fact["objective_id"],
        "title": fact["title"],
        "day": _day(recorded),
        "recorded_at": _iso(recorded),
        "revisions": fact["revisions"],
        "repairs": len(fact["repairs_created"]),
        "refreshes": fact["refreshes"],
        "attempts": fact["attempts"],
        "review_rounds": fact["review_rounds"],
        "stage": fact["stage"],
        "blocker_class": fact["blocker_class"],
        "first_candidate_at": _iso(fact["first_candidate_at"]),
        "accepted_at": _iso(fact["accepted_at"]),
        "integrated_at": _iso(fact["integrated_at"]),
        "landing_state": landing.get("state"),
        "landed_sha": landing.get("sha"),
        "landed_by": landing.get("by"),
        "landed_at": _iso(landing.get("landed_at")),
        "hours_to_first_candidate": _hours(recorded, fact["first_candidate_at"]),
        "hours_to_integrate": _hours(recorded, fact["integrated_at"]),
        "hours_to_land": _hours(recorded, landing.get("landed_at")),
        "deployed_at": None,
        "hours_to_production": None,
        "owner_minutes": None,
    }


# This repository titles a merged pull request "… (PR #N)". The loop report reads that as well as
# GitHub's own titles; ``pull_request_of``, which the --status report uses, is left as it is.
_OWN_PR = re.compile(r"\(PR #(\d+)\)\s*$")

# What the per-day trunk columns mean, said in the report as it is said here.
TRUNK_OTHER_IS = (
    "a first-parent commit of the trunk that is not a loop landing, did not come onto the trunk "
    "with one, and is not a pull request's merge"
)
TRUNK_WITH_LANDING_IS = (
    "a first-parent commit below a loop landing and above its objective's base: the builder's own "
    "commits and the loop's merges of the trunk into the objective's branch, which the landing "
    "fast-forwarded onto the trunk"
)
TRUNK_UNSEEN = (
    "a commit that came onto the trunk while an objective was being built (a pull request's merge, "
    "or another objective's landing) is merged into that objective's branch by the loop; once the "
    "objective lands by fast-forward, that commit is off the first-parent history and is not counted "
    "in the trunk columns (Loop landings, read from the landing records, still counts every loop "
    "landing)"
)
MEDIAN_IS = "over every landed objective, whoever landed it; loop landings count only the loop's"
PREDATES_ATTRIBUTION = (
    "a landed record with no `by` predates the loop recording who landed a SHA (1 October 2026); "
    "who landed it is not recorded"
)


def _loop_pull_request(subject: str) -> bool:
    return bool(pull_request_of(subject) or _OWN_PR.search(subject))


def _landing_runs(
    trunk: Sequence[TrunkCommit], landings: Sequence[tuple[str, str, str | None]]
) -> tuple[dict[str, str], list[str]]:
    """Which first-parent commits came onto the trunk with a loop landing, and which landings
    could not be traced.

    ``landings`` is (objective id, the landed SHA, the objective's base SHA). The loop lands an
    objective by fast-forwarding the trunk to its branch, whose first-parent line runs from the
    landed SHA through the builder's commits and the loop's merges of the trunk back to the base
    the objective was built on. That run is the landing's. A run that reaches the end of the
    history, another loop landing or a pull request's merge before its base is not traced: its
    commits stay where they were, and the objective is named as untraced."""
    on_trunk = {commit.sha: commit for commit in trunk}
    landed = {sha for _, sha, _ in landings}
    runs: dict[str, str] = {}
    untraced: list[str] = []
    for objective_id, sha, base in landings:
        if sha not in on_trunk:
            continue  # not on this first-parent history: nothing of it is counted
        run: list[str] = []
        at = on_trunk[sha].parents[0] if on_trunk[sha].parents else None
        traced = False
        while at is not None and at in on_trunk and base:
            if at == base:
                traced = True
                break
            commit = on_trunk[at]
            if at in landed or _loop_pull_request(commit.subject):
                break
            run.append(at)
            at = commit.parents[0] if commit.parents else None
        if traced:
            runs.update((member, objective_id) for member in run)
        else:
            untraced.append(objective_id)
    return runs, sorted(untraced)


def _trunk_kind(commit: TrunkCommit, loop_shas: set[str], with_landing: Mapping[str, str]) -> str:
    if commit.sha in loop_shas:
        return "loop"
    if commit.sha in with_landing:
        return "with_landing"
    return "pull_request" if _loop_pull_request(commit.subject) else "other"


def _loop_aggregate(events: Mapping, day: str | None, *, landings_read: bool, have_trunk: bool) -> dict:
    """One day's figures, or the totals when ``day`` is ``None``.

    Without the landings, loop landings are unknown, and so is which trunk commits were the
    loop's: those counts are ``None`` and every trunk commit not merging a pull request is
    left uncounted rather than called other."""

    def on(event_day: str) -> bool:
        return day is None or event_day == day

    trunk = [kind for event_day, kind in events["trunk"] if on(event_day)]
    return {
        "objectives_recorded": sum(1 for event_day in events["recorded"] if on(event_day)),
        "first_candidates": sum(1 for event_day in events["first_candidate"] if on(event_day)),
        "repair_revisions": sum(1 for event_day in events["repair"] if on(event_day)),
        "loop_landings": sum(1 for event_day in events["loop_landing"] if on(event_day)) if landings_read else None,
        "median_hours_to_land": _median(hours for event_day, hours in events["land_hours"] if on(event_day)),
        "trunk_commits": len(trunk) if have_trunk else None,
        "trunk_loop_landings": trunk.count("loop") if have_trunk and landings_read else None,
        "trunk_with_loop_landings": trunk.count("with_landing") if have_trunk and landings_read else None,
        "trunk_pull_request_merges": trunk.count("pull_request") if have_trunk else None,
        "trunk_other": trunk.count("other") if have_trunk and landings_read else None,
        "deploys": None,
        "owner_minutes": None,
    }


def measure_loop(records: Mapping, *, trunk: Sequence[TrunkCommit] | None = None) -> dict:
    """The loop's measures per objective, per UTC day and in total, from ``read_loop_records``.

    ``trunk`` is the trunk's ``git log --first-parent`` history; a commit is a loop landing
    when a landing record by ``loop`` names its SHA, and came with one when it lies between
    that SHA and its objective's base (``_landing_runs``). A pull request's merge is titled as
    GitHub titles it or "… (PR #N)". Without the history the trunk counts are ``None``, not 0.
    Hours are from the objective's ``recorded_at``. A day's median hours to land is over every
    objective that landed that day, whoever landed it. Deploys and owner attention are not
    recorded.
    """
    landings_read = bool(records["landings_read"])
    facts = sorted(records["objectives"], key=lambda fact: (fact["recorded_at"], fact["objective_id"]))
    rows = [_loop_row(fact) for fact in facts]
    landed = [(fact["landing"]["landed_at"], row) for fact, row in zip(facts, rows, strict=True) if row["landed_at"]]
    loop_shas = {row["landed_sha"] for _, row in landed if row["landed_by"] == "loop" and row["landed_sha"]}
    traceable = trunk is not None and landings_read
    with_landing, untraced = (
        _landing_runs(
            trunk,
            [
                (fact["objective_id"], row["landed_sha"], fact.get("base_sha"))
                for fact, row in zip(facts, rows, strict=True)
                if row["landed_by"] == "loop" and row["landed_sha"] in loop_shas
            ],
        )
        if traceable
        else ({}, [])
    )
    predating = sorted(
        fact["objective_id"]
        for fact in facts
        if fact["landing"] and fact["landing"]["state"] == "landed" and not fact["landing"].get("by_recorded")
    )
    events = {
        "recorded": [row["day"] for row in rows],
        "first_candidate": [_day(fact["first_candidate_at"]) for fact in facts if fact["first_candidate_at"]],
        "repair": [_day(at) for fact in facts for at in fact["repairs_created"]],
        "loop_landing": [_day(at) for at, row in landed if row["landed_by"] == "loop"],
        "land_hours": [(_day(at), row["hours_to_land"]) for at, row in landed],
        "trunk": [(_day(commit.committed_at), _trunk_kind(commit, loop_shas, with_landing)) for commit in trunk or ()],
    }
    days = sorted(
        set(events["recorded"])
        | set(events["first_candidate"])
        | set(events["repair"])
        | {event_day for event_day, _ in events["land_hours"]}
        | {event_day for event_day, _ in events["trunk"]}
    )
    flags = {"landings_read": landings_read, "have_trunk": trunk is not None}
    return {
        "schema": LOOP_SCHEMA,
        "inputs": {
            "store": records["store"],
            "runtime_root": records["runtime_root"],
            "landings": records["landings_source"],
            "landings_read": landings_read,
            "landing_records_ignored": records["landing_records_ignored"],
            "trunk_history": trunk is not None,
            "trunk_landings_untraced": untraced if traceable else None,
            "trunk_other_is": TRUNK_OTHER_IS,
            "trunk_with_loop_landings_is": TRUNK_WITH_LANDING_IS,
            "trunk_not_counted": TRUNK_UNSEEN,
            "landings_predating_attribution": predating,
            "landed_by_null_when_landed": PREDATES_ATTRIBUTION,
            "median_hours_to_land_is": MEDIAN_IS,
            "deploys": NOT_RECORDED,
            "owner_attention": NOT_RECORDED,
        },
        "objectives": rows,
        "days": [{"day": day, **_loop_aggregate(events, day, **flags)} for day in days],
        "totals": _loop_aggregate(events, None, **flags),
    }


_LOOP_OBJECTIVE_COLUMNS = (
    ("Objective", "objective_id"),
    ("Title", "title"),
    ("Recorded", "recorded_at"),
    ("Revisions", "revisions"),
    ("Repairs", "repairs"),
    ("Refreshes", "refreshes"),
    ("Attempts", "attempts"),
    ("Review rounds", "review_rounds"),
    ("Stage", "stage"),
    ("Blocker", "blocker_class"),
    ("First candidate", "first_candidate_at"),
    ("Accepted", "accepted_at"),
    ("Integrated", "integrated_at"),
    ("Landing", "landing_state"),
    ("Landed SHA", "landed_sha"),
    ("Landed by", "landed_by"),
    ("Landed at", "landed_at"),
    ("H to first candidate", "hours_to_first_candidate"),
    ("H to integrate", "hours_to_integrate"),
    ("H to land", "hours_to_land"),
)

_LOOP_AGGREGATE_COLUMNS = (
    ("Recorded", "objectives_recorded"),
    ("First candidates", "first_candidates"),
    ("Repair revisions", "repair_revisions"),
    ("Loop landings", "loop_landings"),
    ("Median h to land (all landings)", "median_hours_to_land"),
    ("Trunk commits", "trunk_commits"),
    ("Trunk: loop", "trunk_loop_landings"),
    ("Trunk: with a loop landing", "trunk_with_loop_landings"),
    ("Trunk: PR merges", "trunk_pull_request_merges"),
    ("Trunk: other", "trunk_other"),
    ("Deploys", "deploys"),
    ("Owner min", "owner_minutes"),
)


def render_loop_markdown(report: Mapping) -> str:
    inputs = report["inputs"]
    landings = "read" if inputs["landings_read"] else "not read (no landings directory)"
    # A landed objective whose record has no `by` is said so in its cell, not left blank.
    objectives = [
        {**row, "landed_by": "predates attribution"}
        if row["landing_state"] == "landed" and row["landed_by"] is None
        else row
        for row in report["objectives"]
    ]
    untraced = inputs.get("trunk_landings_untraced") or []
    predating = inputs.get("landings_predating_attribution") or []
    lines = [
        "# Engineering measures from the loop's records",
        "",
        f"Objectives: {len(report['objectives'])}; landings: {landings}; "
        f"trunk history: {'yes' if inputs['trunk_history'] else 'not read'}.",
        "Deploys and owner attention are not recorded anywhere; their columns are empty, never estimated.",
        "Hours are from when the objective was recorded. Days are UTC. An empty cell means no record "
        "holds that fact; nothing is estimated.",
        f"Median hours to land is {MEDIAN_IS}.",
        f"Trunk: with a loop landing is {TRUNK_WITH_LANDING_IS}. Trunk: other is {TRUNK_OTHER_IS}. "
        f"Not counted at all: {TRUNK_UNSEEN}.",
    ]
    if untraced:
        lines.append(
            f"{len(untraced)} loop landing(s) could not be traced down to their objective's base "
            f"({', '.join(untraced)}); the commits they brought are counted in Trunk: other."
        )
    if predating:
        lines.append(f"Landed by is not recorded for {', '.join(predating)}: {PREDATES_ATTRIBUTION}.")
    lines += [
        "",
        "## Per objective",
        "",
        *_table(_LOOP_OBJECTIVE_COLUMNS, objectives),
        "",
        "## Per day",
        "",
        *_table((("Day", "day"), *_LOOP_AGGREGATE_COLUMNS), report["days"]),
        "",
        "## Totals",
        "",
        *_table(_LOOP_AGGREGATE_COLUMNS, [report["totals"]]),
    ]
    return "\n".join(lines) + "\n"
