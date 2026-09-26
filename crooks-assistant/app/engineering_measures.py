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
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

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
