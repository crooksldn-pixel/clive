"""An objective as the tablet draws it: one bounded, whitelisted payload for every kind.

The same payload is the conversation's `objective` card (app/presentation.py, drawn by
web/objective-cards.js through web/ui.js) and the body of the objective's sheet on the home
(GET /objectives/{id} carries it as `card`), so what the owner sees right after he speaks is
what he sees when he opens it later. Values are copied key by key and every string is cut to a
length the screen can hold, as in app/presentation.py: a new field of the record reaches the
screen only when a line here carries it.

The shape is the kind's: a project's stages in order with the one it is at, delegated tasks
grouped by person, and for the other kinds what CLIVE is doing and what comes next. Any kind may
also carry a number to reach (objectives by touch, part C): `number` is what the owner set, and
`count` what has sold of it, day by day, with the pace and where it lands, as the owner's routes
read it from the shop (app/objectives/count.py). The model's own tools never read the shop, so
their card carries the number without a count, and the tablet asks its own route for one.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.objectives.store import KINDS, Objective

MAX_TITLE = 120
MAX_LINE = 200
MAX_NAME = 60
MAX_STAGES = 10
MAX_PEOPLE = 8
MAX_GROUPS = 8
MAX_TASKS_EACH = 12
MAX_LINES = 3
MAX_DAYS = 366


def _text(value: Any, limit: int = MAX_LINE) -> str:
    return " ".join(str(value or "").split())[:limit]


def _maybe(value: Any, limit: int = MAX_LINE) -> str | None:
    return _text(value, limit) or None


def data(obj: Objective, tally: dict[str, Any] | None = None) -> dict[str, Any]:
    """The card's payload for one objective; `tally` is its number's count, when one was read."""
    summary = obj.summary()
    kind = obj.kind if obj.kind in KINDS else "business"
    out: dict[str, Any] = {
        "objective_id": obj.id,
        "kind": kind,
        "title": _text(obj.title, MAX_TITLE),
        "attention": _text(summary["attention"], 20),
        "attention_reason": _text(summary["attention_reason"]),
        "purpose": _maybe(obj.purpose),
        "done_when": _maybe(obj.done_when),
        "deadline": _maybe(obj.deadline, 10),
        "days_left": summary["days_left"] if isinstance(summary["days_left"], int) else None,
        "check_in": _check_in(summary.get("check_in")),
        "people": [{"name": _text(p.get("name"), MAX_NAME), "role": _maybe(p.get("role"), MAX_NAME)}
                   for p in obj.people[:MAX_PEOPLE] if isinstance(p, dict) and p.get("name")],
        "needs_you": [_text(t) for t in summary["needs_you"][:MAX_LINES]],
        "blocked_by": [_text(t) for t in summary["blocked_by"][:MAX_LINES]],
        "doing": _maybe(summary["doing"]),
        # CLIVE's own work items not yet started, as the sheet has always listed them.
        "next": [_text(i["text"]) for i in obj.items if i.get("state") in ("proposed", "authorised")][:MAX_LINES],
        "updated_at": _text(obj.updated_at, 20),
    }
    if kind == "project":
        out["stages"] = [_stage(s) for s in obj.stages[:MAX_STAGES]]
    if obj.tasks:
        out["groups"] = [_group(g) for g in obj.task_groups()[:MAX_GROUPS]]
    if isinstance(obj.number, dict) and obj.number.get("of"):
        out["number"] = _number(obj.number)
        if isinstance(tally, dict):
            out["count"] = _count(tally)
    return out


def surface(obj: Objective) -> dict[str, Any]:
    """The conversation's card: one `ui` item of the `objective` type."""
    return {"type": "objective", "data": data(obj)}


def _check_in(cadence: Any) -> dict[str, Any] | None:
    if not isinstance(cadence, dict) or not cadence.get("every_days"):
        return None
    quiet = cadence.get("quiet_days")
    return {"every_days": int(cadence["every_days"]), "quiet_days": quiet if isinstance(quiet, int) else None,
            "due": bool(cadence.get("due"))}


def _stage(stage: dict[str, Any]) -> dict[str, Any]:
    state = stage.get("state")
    return {
        "id": _text(stage.get("id"), 20),
        "name": _text(stage.get("name"), MAX_NAME),
        "state": state if state in ("done", "current", "upcoming") else "upcoming",
        "due": _maybe(stage.get("due"), 10),
        "waiting_on": _maybe(stage.get("waiting_on"), MAX_NAME * 2),
        "started_at": _maybe(stage.get("started_at"), 20),
        "done_at": _maybe(stage.get("done_at"), 20),
    }


def _group(group: dict[str, Any]) -> dict[str, Any]:
    tasks = group.get("tasks") or []
    return {
        "who": _text(group.get("who"), MAX_NAME),
        "open": int(group.get("open") or 0),
        "done": int(group.get("done") or 0),
        "tasks": [{"id": _text(t.get("id"), 20), "text": _text(t.get("text")), "due": _maybe(t.get("due"), 10),
                   "done": bool(t.get("done"))} for t in tasks[:MAX_TASKS_EACH]],
        "more": max(0, len(tasks) - MAX_TASKS_EACH),
    }


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _number(number: dict[str, Any]) -> dict[str, Any]:
    return {"of": _text(number.get("of"), MAX_NAME), "target": _int(number.get("target")),
            "since": _maybe(number.get("since"), 10), "unit": _maybe(number.get("unit"), 30)}


def _count(tally: dict[str, Any]) -> dict[str, Any]:
    """The count, key by key: figures as numbers, days as dates, and the one sentence it may say
    when it could not count (app/objectives/count.py's own words).

    At most a year and a day of days is sent. A number counted for longer sends its latest days, and
    with them the day the series sent starts on (`first`) and what sold before it (`carried`), so the
    tablet indexes its days, totals and dates from that day, never from when counting began."""
    if not tally.get("counted"):
        return {"counted": False, "why": _text(tally.get("why"))}
    pace = tally.get("pace")
    days = [max(0, n) if (n := _int(v)) is not None else 0 for v in (tally.get("per_day") or [])]
    sent = days[-MAX_DAYS:]
    try:
        first = (date.fromisoformat(str(tally.get("today"))) - timedelta(days=len(sent) - 1)).isoformat() if sent else None
    except ValueError:
        first = None
    return {
        "counted": True,
        "per_day": sent,
        "first": first,
        "carried": sum(days[: len(days) - len(sent)]),
        "total": _int(tally.get("total")) or 0,
        "pace": round(float(pace), 2) if isinstance(pace, int | float) and not isinstance(pace, bool) else None,
        "pace_days": _int(tally.get("pace_days")) or 0,
        "today": _maybe(tally.get("today"), 10),
        "lands": _maybe(tally.get("lands"), 10),
        "reached_on": _maybe(tally.get("reached_on"), 10),
        "far": bool(tally.get("far")),
        "days_early": _int(tally.get("days_early")),
        "by_deadline": _int(tally.get("by_deadline")),
        "short": _int(tally.get("short")),
        "at_deadline": _int(tally.get("at_deadline")),
        # What was counted, by name: the products his words matched, the most sold first.
        "matched": [_text(t, MAX_NAME * 2) for t in (tally.get("matched") or [])[:3] if _text(t)],
        "matched_more": _int(tally.get("matched_more")) or 0,
        "counted_at": _maybe(tally.get("counted_at"), 20),
        "age_s": _int(tally.get("age_s")),
    }
