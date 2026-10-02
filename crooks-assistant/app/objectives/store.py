"""Objectives: the owner's real-world goals, kept alive across turns, sessions and restarts.

One objective is one JSON file under ``settings.objectives_dir``, written atomically. It holds
the owner's own words, what CLIVE knows (each fact with where it came from), what it does not
know, what blocks it, the work items with their state, what needs the owner, and a history.

The work-item ladder is the product invariant, enforced here rather than asked of the model:

    proposed -> authorised -> started -> completed -> verified

* CLIVE may propose anything.
* A work item that needs the owner (spending money, booking, submitting an official application,
  sending an external message, making a commitment) can only be ``authorised`` by the owner,
  through ``authorise`` below, which only the owner's own screen calls. No model tool can reach it.
* Work that needs no approval (research, preparation, drafting for review) may go straight from
  proposed to started.
* ``completed`` is what CLIVE did; ``verified`` needs the evidence that shows it happened.

Nothing here performs an action in the world. A "booking" work item is a record that a booking
is needed; making it is a separate capability that does not exist yet, and saying so is a blocker.

An objective also has a shape that fits what it is for (round 12, the owner on 29 September:
"telling clive that samples have started xyz shows the same as saying give [two of the team]
these tasks to do later"). Its kind says which:

* ``project`` moves through stages to a finish: a drop's sampling, approval, production and
  delivery. It holds its stages in order, the one it is at now, and for each a date and who or
  what it is waiting on. Moving a stage records where the project is; it books, orders and pays
  for nothing.
* ``tasks`` is jobs handed to named people ("give Rosa and Kit these to do later"): each task
  has who, what, an optional date, and done or not. It is the owner's list. Nothing is sent to
  the people on it.
* ``build`` is a change to CLIVE itself, filed with the engineering loop.
* ``business`` is any other goal CLIVE works through in steps (a trip, an application).

Any of them can carry its purpose (why), what finished looks like, the people involved, a
deadline and a check-in cadence. The cadence is not a scheduler: nothing runs between
conversations. It is a promise the record keeps by itself: when an objective has gone quiet for
longer than the owner asked, its headline says a check-in is due (``attention_``).

Where the design lives, and why (rollback safety). A deploy that fails rolls back to the
previous build, and the owner can roll back by hand; the store before round 12 reads a record with
``Objective(**data)``, which refuses any key it does not know. So ``obj_x.json`` keeps exactly the
keys that store knows (``RECORD_FIELDS``), and the design is written beside it, atomically and
first, to ``design/obj_x.json``: a folder the old store never lists, since it reads only
``obj_*.json`` at the top. After a rollback every objective still lists and opens, as a plain one;
rolled forward again, its design is where it was. A record with no design file (written before
round 12, or by an older build after a rollback) is whole without one (``_from_record``).

Two files must never split an objective, so a design is used only when it agrees with its record
(same id, same kind, this format, and the record has the very event the design was written after)
and a write goes down in three atomic steps: the new design as a pending file, the record, then
the pending design becomes the design (``ObjectiveStore._write`` says why that order is safe). A
design that cannot be read or does not agree never hides or breaks the objective: it reads as its
plain kind from its record, and the file is logged (never its content) and kept aside, renamed
``.damaged``, never overwritten.

The owner's touch, and six seconds to take it back (objectives by touch, part A). On his own screen
he can make a stage now, tick a task, hand a task to someone else and drag the date it must land
by. Each of those is one ordinary change (``move_stage``, ``task``, ``design``: one locked write,
one event, the design file and record in their order) wrapped by ``_touch``, which, under the same
lock, keeps what the change could alter (the stages with their states and dates, the tasks, the
deadline, the number) as it was just before, and hands back a one-use token. ``undo`` with that token puts those
fields back exactly, from what was kept rather than by working out an inverse, as one more change
with its own "Undone: ..." event, and only while nothing else has touched the objective since (the
record's history ends where that change left it) and within a short window. Tokens live in this
process's memory alone, a bounded few, never on the disk and never in a log: a restart forgets
them, which is the honest answer six seconds after a restart anyway.

A number to reach (objectives by touch, part C: "shift the last 200 hoodies by the 18th"). Any kind
can carry one: what is counted (a product as the owner names it, matched the way the sales figures
match his words), the target, the day counting starts and the words for what a unit is. It is one
more design field, so it lives in the design file and nothing already stored changes: the store
before round 12 never sees it, and a round-12 build that does not know it keeps it untouched and
writes it back (``_design_extra``). The record holds only what he said; how many have sold is never
stored here. It is read from the shop's orders when the objective is drawn (app/objectives/count.py),
so a stored figure can never go stale or be mistaken for a count. The owner can drag the target on
his screen, with the same six seconds to take it back as every other touch (``touch_target``).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.analytics.periods import MAX_DAYS as COUNT_BACK_DAYS
from app.objectives.gaps import _fsync_dir

log = logging.getLogger("crooks.objectives")

__all__ = [
    "LADDER",
    "Objective",
    "ObjectiveError",
    "ObjectiveStore",
    "install",
    "store",
]

LADDER = ("proposed", "authorised", "started", "completed", "verified")
STATUSES = ("active", "waiting", "blocked", "done", "dropped")
# Closed out, in the owner's words, and the status each is kept under. Neither deletes anything:
# a closed objective leaves the live list and stays whole, read by its id (`get`) or found again
# among the closed (`closed`).
CLOSINGS = {"complete": "done", "removed": "dropped"}
CLOSED = ("done", "dropped")
BLOCKER_KINDS = ("missing_info", "missing_capability", "needs_owner", "external")
# What an objective is for, which decides its shape (the module docstring says each). "build":
# the owner wants CLIVE itself changed, and the work goes to the engineering loop. "business" is
# the kind every record had before kinds were designed, and stays the kind of any other goal.
KINDS = ("business", "build", "project", "tasks")
STAGE_STATES = ("done", "current", "upcoming")
_ID = re.compile(r"^obj_[0-9a-f]{8}$")
MAX_TEXT = 2000
# The design file's own format. 3: the design fields, with the record they were written with (its
# id, kind and last event), so a design is only ever read with that record or one grown from it
# (``_verdict``). 2 was round 12's first sidecar, never deployed: it named no record, and is set
# aside when met. 1 is a record without a design.
VERSION = 3
# A design file whose record is gone (a creation cut short) is tidied once it is this old.
ORPHAN_AGE_S = 24 * 3600
TIDY_EVERY_S = 3600
# The keys of obj_x.json: exactly what the store before round 12 reads (547f652f), in that order.
RECORD_FIELDS = ("id", "title", "request", "created_at", "updated_at", "status", "status_set_by", "deadline",
                 "facts", "unknowns", "blockers", "items", "attention", "events", "kind", "engineering")
# The keys of design/obj_x.json, beside ``version``. `number` came after round 12 (part C) within
# the same format: a build that does not know it keeps it as it found it, so it needs no new version
# (a new version would set every design aside on a rollback, ``_verdict``).
DESIGN_FIELDS = ("purpose", "done_when", "people", "stages", "tasks", "check_every_days", "number")
DESIGN_DIR = "design"
# Bounds that keep a record a thing a person reads, not a spreadsheet.
MAX_STAGES = 10
MAX_TASKS = 60
MAX_PEOPLE = 12
MAX_NAME = 60
MAX_CHECK_EVERY = 90
# What each field `missing` can name means, in the words the model asks in.
_MEANS = {"deadline": "the date it has to be done by", "tasks": "who is to do what"}
# A touch can be taken back for this long on the screen; the server allows a little more, for the
# time the tap on Undo spends on its way. At most this many offers are kept at once.
UNDO_OFFER_S = 6
UNDO_GRACE_S = 10
UNDO_KEPT = 32
# What an owner's touch can change, and so what its undo puts back.
_RESTORABLE = ("stages", "tasks", "deadline", "number")
# A number's bounds: a target a person counts towards, and a unit said in a few words. Counting
# can start at most as far back as the order cache reads (a year), and its day, when he gives none,
# is the day it was set in the shop's own time zone (London, as app/families/compose.py has it).
MAX_TARGET = 100_000
MAX_UNIT = 30
_NUMBER_KEYS = ("of", "target", "since", "unit")
SHOP_TZ = ZoneInfo("Europe/London")
_ROLE = re.compile(r"^(?P<name>[^()]+?)\s*\((?P<role>[^()]*)\)\s*$")


class ObjectiveError(ValueError):
    """A change was refused; the record is unchanged. The message is safe to show the owner."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(text: Any, *, limit: int = MAX_TEXT, what: str = "text") -> str:
    value = " ".join(str(text or "").split())
    if not value:
        raise ObjectiveError(f"The {what} is empty.")
    return value[:limit]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def _date(value: Any, *, what: str = "date") -> str | None:
    """An ISO date, or None for nothing. Anything else is refused, never guessed at."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ObjectiveError(f"The {what} {raw!r} is not a date (YYYY-MM-DD).") from exc


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _on(iso: str | None) -> str:
    """A date as the owner reads it in the history: "14 Nov 2026", never "2026-11-14"."""
    try:
        day = date.fromisoformat(str(iso))
    except ValueError:
        return str(iso or "")
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _day(iso: str | None) -> str:
    """A date as the screen says it: "Fri 30 Oct", with the year only when it is not this one."""
    try:
        day = date.fromisoformat(str(iso))
    except ValueError:
        return str(iso or "")
    said = f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"
    return said if day.year == datetime.now(UTC).date().year else f"{said} {day.year}"


def _listed(names: list[str]) -> str:
    """"A", "A and B", "A, B and C": a list the way a person says it."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _clock() -> float:
    """The time an undo's window is measured by: monotonic, so a clock change neither opens nor
    shuts it."""
    return time.monotonic()


def _optional(text: Any, *, limit: int = 400) -> str | None:
    """Free text that may be cleared: empty means none."""
    value = " ".join(str(text or "").split())
    return value[:limit] or None


def _key(name: Any) -> str:
    return " ".join(str(name or "").split()).casefold()


def _proper(name: str) -> str:
    """A name as a person writes it. A transcript hands names over in lower case ("rosa"); a
    name the speaker capitalised is kept exactly as given."""
    return name.title() if name == name.lower() else name


def _person(entry: Any) -> dict[str, str | None]:
    """"Northfield (factory)" -> a name and a role; a plain name has no role."""
    if isinstance(entry, dict):
        name, role = entry.get("name"), entry.get("role")
    else:
        found = _ROLE.match(" ".join(str(entry or "").split()))
        name, role = (found.group("name"), found.group("role")) if found else (entry, None)
    clean = _clean(name, limit=MAX_NAME, what="person's name")
    return {"name": _proper(clean), "role": _optional(role, limit=MAX_NAME)}


def _check_every(value: Any) -> int | None:
    """Days between check-ins, 1 to 90; nought or nothing means no cadence."""
    if value in (None, ""):
        return None
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise ObjectiveError("A check-in cadence is a number of days.") from exc
    if days <= 0:
        return None
    if days > MAX_CHECK_EVERY:
        raise ObjectiveError(f"A check-in cadence is at most {MAX_CHECK_EVERY} days.")
    return days


def _target(value: Any) -> int:
    """A target: a whole number from 1 to MAX_TARGET, never a guess at what was meant."""
    if isinstance(value, bool):
        raise ObjectiveError("A target is a number.")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ObjectiveError("A target is a number.") from exc
    if number != value and str(number) != str(value).strip():
        raise ObjectiveError("A target is a whole number.")
    if not 1 <= number <= MAX_TARGET:
        raise ObjectiveError(f"A target is between 1 and {MAX_TARGET:,}.")
    return number


def _shop_today() -> date:
    return datetime.now(SHOP_TZ).date()


def _number(value: Any, existing: dict | None) -> dict | None:
    """A number as the owner set or changed it: what is counted, the target, the day counting
    starts and the unit's words. Only what is passed changes; `{}` takes the number off. A new one
    needs what is counted and the target; counting starts the day it is set unless he said when."""
    if not isinstance(value, dict):
        raise ObjectiveError("A number is what is counted (of), the target, and since when if he said.")
    unknown = sorted(set(value) - set(_NUMBER_KEYS))
    if unknown:
        raise ObjectiveError(f"A number has {', '.join(_NUMBER_KEYS)}; not {', '.join(unknown)}.")
    if not value:
        if existing is None:
            raise ObjectiveError("It has no number to take off.")
        return None
    merged = {**(existing or {}), **value}
    if merged.get("of") in (None, "") or merged.get("target") in (None, ""):
        raise ObjectiveError("A number needs what is counted (of) and its target.")
    since = _date(merged.get("since"), what="day counting starts") or _shop_today().isoformat()
    earliest = _shop_today() - timedelta(days=COUNT_BACK_DAYS)
    if date.fromisoformat(since) < earliest:
        raise ObjectiveError(f"Orders are read back a year at most, so counting can start on {_on(earliest.isoformat())} "
                             "at the earliest; nothing was changed.")
    return {"of": _clean(merged["of"], limit=MAX_NAME, what="thing it counts"), "target": _target(merged["target"]),
            "since": since, "unit": _optional(merged.get("unit"), limit=MAX_UNIT)}


def _number_said(before: dict | None, after: dict | None) -> str:
    """What a change to the number was, for the history, in the owner's words."""
    if after is None:
        return "No number"
    unit = f" {after['unit']}" if after.get("unit") else ""
    if before is None or before.get("of") != after["of"]:
        return f"Counting {after['of']}: {after['target']:,}{unit} from {_on(after['since'])}"
    said = []
    if before.get("target") != after["target"]:
        said.append(f"Target {after['target']:,}")
    if before.get("since") != after["since"]:
        said.append(f"counted from {_on(after['since'])}")
    if before.get("unit") != after.get("unit"):
        said.append(f"counted as {after['unit']}" if after.get("unit") else "no unit")
    return ", ".join(said) or f"Counting {after['of']}, as it was"


@dataclass
class Objective:
    id: str
    title: str
    request: str
    created_at: str
    updated_at: str
    status: str = "active"
    status_set_by: str | None = None
    deadline: str | None = None
    facts: list[dict] = field(default_factory=list)
    unknowns: list[dict] = field(default_factory=list)
    blockers: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    attention: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    kind: str = "business"
    # The engineering requests filed for a build objective, newest last: request id, the host
    # whose loop builds it, the branch its work lands on, when it was filed.
    engineering: list[dict] = field(default_factory=list)
    # ---- the design (version 2). Every one of them optional, so a version-1 record is whole.
    purpose: str | None = None                  # why, in the owner's words
    done_when: str | None = None                # what finished looks like
    people: list[dict] = field(default_factory=list)   # {name, role}: who is involved
    # A project's stages, in order: {id, name, state (done/current/upcoming), due, waiting_on,
    # started_at, done_at}. At most one is current; none current and none done is "not started".
    stages: list[dict] = field(default_factory=list)
    # Jobs for named people: {id, who, text, due, done, done_at, at}.
    tasks: list[dict] = field(default_factory=list)
    check_every_days: int | None = None
    # A number to reach, or None: {of, target, since, unit} (`_number`). What has sold is counted
    # when it is drawn, never kept here.
    number: dict | None = None

    def __post_init__(self) -> None:
        # Legacy JSON written before status_set_by existed has no such field, so the dataclass
        # default (None) is supplied even when the objective's own status event proves who set
        # the current terminal status. Infer it from that event so old owner-closed objectives
        # do not lose their terminal attention; a missing or non-owner event leaves it unproven.
        if self.status_set_by is None and self.status in ("done", "dropped"):
            for event in reversed(self.events):
                if event.get("kind") == "status" and str(event.get("text", "")).startswith(self.status):
                    self.status_set_by = event.get("by")
                    break

    # ---- views ------------------------------------------------------------
    def open_(self, key: str) -> list[dict]:
        return [x for x in getattr(self, key) if not x.get("resolved_at")]

    def current_stage(self) -> tuple[int, dict] | None:
        """The stage the project is at now, with its place in the order."""
        return next(((i, s) for i, s in enumerate(self.stages) if s.get("state") == "current"), None)

    def stage_line(self) -> str | None:
        """"Sampling · waiting on Northfield": where a project is, in a line. None when it is
        not a project or has not started; "Every stage done" when it has finished them all."""
        if self.kind != "project" or not self.stages:
            return None
        here = self.current_stage()
        if here is None:
            return "Every stage done" if all(s.get("state") == "done" for s in self.stages) else None
        stage = here[1]
        waiting = stage.get("waiting_on")
        return f"{stage['name']} · waiting on {waiting}" if waiting else stage["name"]

    def task_groups(self) -> list[dict[str, Any]]:
        """The tasks by person, in the order each person first appears, open tasks first."""
        groups: dict[str, dict[str, Any]] = {}
        for task in self.tasks:
            group = groups.setdefault(_key(task.get("who")), {"who": task.get("who"), "tasks": []})
            group["tasks"].append(task)
        for group in groups.values():
            group["tasks"].sort(key=lambda t: bool(t.get("done")))
            group["open"] = sum(1 for t in group["tasks"] if not t.get("done"))
            group["done"] = len(group["tasks"]) - group["open"]
        return list(groups.values())

    def check_in(self, today: date | None = None) -> dict[str, Any] | None:
        """The cadence the owner asked for, and whether it has lapsed: due once the record has
        been quiet (no change of any kind) for as many days as he said."""
        if not self.check_every_days:
            return None
        today = today or datetime.now(UTC).date()
        try:
            last = date.fromisoformat(str(self.updated_at)[:10])
        except ValueError:
            return {"every_days": self.check_every_days, "quiet_days": None, "due": False}
        quiet = (today - last).days
        return {"every_days": self.check_every_days, "quiet_days": quiet, "due": quiet >= self.check_every_days}

    def attention_(self) -> tuple[str, str]:
        """The one rule for the headline everywhere, derived from open records, not the stored
        status: needs_you (an open question, or a proposed item needing the owner) beats blocked
        (an open blocker) beats check_in (the cadence he asked for has lapsed) beats doing (an
        item started, a project at a stage, a task still open) beats idle. Only owner-set
        done/dropped (status_set_by == "owner") stand; any other or unproven done/dropped status
        is ignored."""
        if self.status in ("done", "dropped") and self.status_set_by == "owner":
            return self.status, f"the owner set this objective to {self.status}"
        question = next(iter(self.open_("attention")), None)
        if question:
            return "needs_you", f"open question: {question['text']}"
        awaiting = next((i for i in self.items if i["state"] == "proposed" and i.get("needs_owner")), None)
        if awaiting:
            return "needs_you", f"awaiting your approval: {awaiting['text']}"
        blocker = next(iter(self.open_("blockers")), None)
        if blocker:
            return "blocked", f"blocked by: {blocker['text']}"
        cadence = self.check_in()
        if cadence and cadence["due"]:
            return "check_in", (f"no update for {cadence['quiet_days']} days; "
                                f"you check in every {cadence['every_days']}")
        doing = next((i for i in self.items if i["state"] == "started"), None)
        if doing:
            return "doing", f"in progress: {doing['text']}"
        if self.kind == "project" and self.current_stage() is not None:
            return "doing", f"at {self.stage_line()}"
        open_tasks = sum(1 for t in self.tasks if not t.get("done"))
        if open_tasks:
            return "doing", f"{open_tasks} task{'s' if open_tasks != 1 else ''} open"
        if self.kind == "project" and self.stages and all(s.get("state") == "done" for s in self.stages):
            return "idle", "every stage is done"
        if self.tasks:
            return "idle", "every task is done"
        return "idle", "nothing open"

    def missing(self) -> list[str]:
        """What this kind cannot do without and the owner has not said: the only things CLIVE may
        ask when it opens the objective, and nothing else. A drop, a sample round or a shoot has a
        date, so a project without a deadline asks for one. Where a project is now is not asked:
        one he has not said has started is simply not started. Tasks "for later" need no date,
        and a business or build objective asks what it needs as questions on the record."""
        if self.kind == "project" and not self.deadline:
            return ["deadline"]
        if self.kind == "tasks" and not self.tasks:
            return ["tasks"]
        return []

    def ask(self) -> str:
        """The one line the model is handed with `missing`, so that it asks exactly that."""
        wanted = self.missing()
        if not wanted:
            return "Nothing essential is missing: ask no question about it."
        return f"Ask only for {' and '.join(_MEANS[f] for f in wanted)}, in one short question; nothing else."

    def mentions(self, search: str) -> bool:
        """Whether every word of `search` is somewhere in the record: its title, request, why,
        facts and their sources, notes, blockers, questions, items, tasks, stages, people, history."""
        parts = [self.id, self.title, self.request, self.purpose or "", self.done_when or ""]
        for key in ("facts", "unknowns", "blockers", "items", "attention", "events", "tasks"):
            for entry in getattr(self, key):
                parts.extend(str(entry.get(k) or "") for k in ("text", "source", "resolution", "who"))
        parts.extend(str(s.get("name") or "") for s in self.stages)
        parts.extend(str(p.get("name") or "") for p in self.people)
        if self.number:
            parts.append(str(self.number.get("of") or ""))
        found = _key(" ".join(parts))
        return all(word in found for word in _key(search).split())

    def summary(self) -> dict[str, Any]:
        """What the home screen and the model's list need: short, current, no history."""
        items = [i for i in self.items if i["state"] not in ("completed", "verified")]
        now_doing = next((i["text"] for i in items if i["state"] == "started"), None)
        attention, attention_reason = self.attention_()
        waiting = [i["text"] for i in items if i["state"] in ("proposed", "authorised")]
        kind = self.kind if self.kind in KINDS else "business"
        here = self.current_stage()
        # "Doing" and "next" in the shape's own terms, which is what the screens read: a
        # project is doing its stage and next are the stages after it; delegated tasks are next.
        if kind == "project":
            now_doing = now_doing or (self.stage_line() if here is not None else None)
            after = [s["name"] for s in self.stages[(here[0] + 1 if here else 0):] if s.get("state") == "upcoming"]
            waiting = waiting + after
        elif kind == "tasks":
            waiting = waiting + [f"{t['who']}: {t['text']}" for g in self.task_groups() for t in g["tasks"] if not t.get("done")]
        cadence = self.check_in()
        out = {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "attention": attention,
            "attention_reason": attention_reason,
            "deadline": self.deadline,
            "days_left": _days_left(self.deadline),
            "doing": now_doing,
            "next": waiting[:3],
            "blocked_by": [b["text"] for b in self.open_("blockers")][:3],
            "needs_you": [a["text"] for a in self.open_("attention")],
            "unknowns": len(self.open_("unknowns")),
            "facts": len(self.facts),
            "updated_at": self.updated_at,
            "kind": kind,
            "engineering": [{"request_id": e.get("request_id"), "host": e.get("host")} for e in self.engineering][-3:],
            # The shape, as short as a home row needs it.
            "stage": ({"name": here[1]["name"], "index": here[0], "count": len(self.stages),
                       "waiting_on": here[1].get("waiting_on"), "due": here[1].get("due")} if here else None),
            # Each stage's date too, for the next six weeks on the home (web/horizon.js): one dot a
            # day, each stage's day marked. None for a stage nobody gave a date.
            "stages": [{"name": s["name"], "state": s["state"], "due": s.get("due")} for s in self.stages],
            "people_tasks": [{"who": g["who"], "open": g["open"], "done": g["done"]} for g in self.task_groups()],
            "check_in": cadence,
        }
        # The number as he set it, only on an objective that has one, so every other summary reads
        # exactly as before. How many have sold is added by the owner's routes, which count it
        # (app/objectives/count.py); the model reads the figures with the sales tools.
        if self.number:
            out["number"] = dict(self.number)
        return out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FIELDS = frozenset(f.name for f in fields(Objective))
assert _FIELDS == set(RECORD_FIELDS) | set(DESIGN_FIELDS)


def _from_record(raw: Any, design: Any = None) -> Objective:
    """An objective from its record and its design file, as any build of the store wrote them.

    The record (obj_x.json) is read as it always was: one written before kinds existed has no
    kind, engineering or status_set_by, and gets "business", none and None. The design
    (design/obj_x.json) may be absent — a record from before round 12, or one an older build made
    after a rollback — and every design field then means "none", so the objective reads exactly
    as it did. A record that carries the design inline (round 12's first cut, never deployed) is
    read too, and split on its next write. A key in the record that no build of this store writes
    is refused, as a damaged file is, rather than dropped on the next write; a design key this
    build does not know is kept and written back as it was, under the version that wrote it
    (``Objective._design_extra``, ``_design_version``).
    """
    if not isinstance(raw, dict):
        raise ValueError("an objective record is a JSON object")
    if design is not None and not isinstance(design, dict):
        raise ValueError("an objective's design is a JSON object")
    data = dict(raw)
    inline = {k: data.pop(k) for k in (*DESIGN_FIELDS, "version") if k in data}
    unknown = set(data) - set(RECORD_FIELDS)
    if unknown:
        raise ValueError(f"unknown fields {sorted(unknown)}")
    data.setdefault("kind", "business")
    data.setdefault("engineering", [])
    shape = {**inline, **(design or {})}
    for stamp in _STAMP:
        shape.pop(stamp, None)
    try:
        written_as = int(shape.pop("version", None) or VERSION)
    except (TypeError, ValueError) as exc:
        raise ValueError("an objective's design has no readable version") from exc
    extra = {k: v for k, v in shape.items() if k not in DESIGN_FIELDS}
    for name in ("people", "stages", "tasks"):
        data[name] = list(shape.get(name) or [])
    for name in ("purpose", "done_when", "check_every_days", "number"):
        data[name] = shape.get(name)
    obj = Objective(**data)
    obj._design_extra = extra
    obj._design_version = max(VERSION, written_as)
    return obj


def _split(obj: Objective) -> tuple[dict[str, Any], dict[str, Any]]:
    """The two files an objective is written as: the record the store before round 12 can read,
    key for key, and its design, stamped with that record."""
    data = obj.to_dict()
    record = {k: data[k] for k in RECORD_FIELDS}
    design = {"version": getattr(obj, "_design_version", VERSION), **_stamp_of(record),
              **getattr(obj, "_design_extra", {}), **{k: data[k] for k in DESIGN_FIELDS}}
    return record, design


# The keys that tie a design to its record.
_STAMP = ("id", "kind", "events", "after")
# Verdicts that mean the file itself is wrong, not merely out of step with its record.
_DAMAGE = frozenset({"unreadable", "foreign", "version"})


def _mark(event: Any) -> str:
    """One event, as a short fingerprint: the record's history never rewrites an event, so the
    same event at the same place means the same history up to there."""
    return hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _stamp_of(record: dict[str, Any]) -> dict[str, Any]:
    events = record.get("events") or []
    return {"id": record.get("id"), "kind": record.get("kind") or "business", "events": len(events),
            "after": _mark(events[-1]) if events else None}


def _well_formed(design: Any) -> bool:
    """Whether a design has the shape the rest of this file reads without checking again."""
    if not isinstance(design, dict):
        return False
    def text_or_none(value: Any) -> bool:
        return value is None or isinstance(value, str)

    try:
        return all((
            isinstance(design.get("version"), int), isinstance(design.get("id"), str),
            isinstance(design.get("kind"), str), isinstance(design.get("events"), int) and design["events"] >= 0,
            text_or_none(design.get("after")),
            text_or_none(design.get("purpose")), text_or_none(design.get("done_when")),
            design.get("check_every_days") is None or isinstance(design.get("check_every_days"), int),
            isinstance(design.get("people", []), list) and all(
                isinstance(p, dict) and isinstance(p.get("name"), str) and text_or_none(p.get("role"))
                for p in design.get("people", [])),
            isinstance(design.get("stages", []), list) and all(
                isinstance(st, dict) and isinstance(st.get("name"), str) and st.get("state") in STAGE_STATES
                and text_or_none(st.get("due")) and text_or_none(st.get("waiting_on"))
                for st in design.get("stages", [])),
            isinstance(design.get("tasks", []), list) and all(
                isinstance(t, dict) and isinstance(t.get("id"), str) and isinstance(t.get("who"), str)
                and isinstance(t.get("text"), str) and isinstance(t.get("done", False), bool) and text_or_none(t.get("due"))
                for t in design.get("tasks", [])),
            design.get("number") is None or (
                isinstance(design["number"], dict) and isinstance(design["number"].get("of"), str)
                and isinstance(design["number"].get("target"), int) and not isinstance(design["number"]["target"], bool)
                and isinstance(design["number"].get("since"), str) and text_or_none(design["number"].get("unit"))),
        ))
    except (TypeError, AttributeError):
        return False


def _verdict(design: Any, record: dict[str, Any]) -> str:
    """Whether this design belongs with this record: "agrees", or why not.

    unreadable  not a design of the shape this file reads
    foreign     another objective's
    version     a format this build does not know
    ahead       written with a record that has more history than this one: a write that stopped
                before its record went down
    history     written after an event this record does not have at that place
    kind        written for another kind than the record now is (the store production rolls back
                to can make any objective a build)
    """
    if not _well_formed(design):
        return "unreadable"
    if design["id"] != record.get("id"):
        return "foreign"
    if design["version"] != VERSION:
        return "version"
    events = record.get("events") or []
    count = design["events"]
    if count > len(events):
        return "ahead"
    if (_mark(events[count - 1]) if count else None) != design.get("after"):
        return "history"
    if design["kind"] != (record.get("kind") or "business"):
        return "kind"
    return "agrees"


def _restorable(obj: Objective) -> dict[str, Any]:
    """What an owner's touch can change, as it is now, kept apart from the objective."""
    return {name: copy.deepcopy(getattr(obj, name)) for name in _RESTORABLE}


def _ends(obj: Objective) -> tuple[int, str | None]:
    """Where the record's history ends: every write adds an event (`_change`), so the same end
    means nothing has been written since."""
    return len(obj.events), (_mark(obj.events[-1]) if obj.events else None)


def _days_left(deadline: str | None) -> int | None:
    if not deadline:
        return None
    try:
        return (date.fromisoformat(deadline) - datetime.now(UTC).date()).days
    except ValueError:
        return None


# What an owner's touch answers: the objective, the undo offer when it changed something, and the
# line that says so when it changed nothing (`ObjectiveStore._touch`).
Touched = tuple[Objective, dict[str, Any] | None, str | None]


class ObjectiveStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()
        # The undo offers made for the owner's touches, by token, oldest first (`_touch`).
        self._undos: OrderedDict[str, dict[str, Any]] = OrderedDict()

    # ---- persistence ----------------------------------------------------------
    def _path(self, objective_id: str) -> Path:
        if not _ID.fullmatch(str(objective_id)):
            raise ObjectiveError(f"There is no objective {objective_id!r}.")
        return self.root / f"{objective_id}.json"

    def _design_path(self, objective_id: str) -> Path:
        return self._path(objective_id).parent / DESIGN_DIR / f"{objective_id}.json"

    def _pending_path(self, objective_id: str) -> Path:
        return self._path(objective_id).parent / DESIGN_DIR / f"{objective_id}.next.json"

    @staticmethod
    def _folder(folder: Path) -> None:
        """A folder, made where it is not, each one it makes named durably in its parent: a file
        renamed into a folder whose own name did not reach the disk is lost with it."""
        if folder.is_dir():
            return
        ObjectiveStore._folder(folder.parent)
        folder.mkdir(exist_ok=True)
        _fsync_dir(folder.parent)

    @staticmethod
    def _atomic(path: Path, data: dict[str, Any]) -> None:
        """`data` at `path`, whole or not at all, and on the disk before this returns (round 13,
        S6-01): the content is flushed and fsynced before the rename, and the folder after it.
        Without both, a power cut could keep a later step of `_write` and lose this one, and the
        order the three steps are written in is what keeps an objective whole."""
        ObjectiveStore._folder(path.parent)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)

    def _promote(self, objective_id: str) -> None:
        """Step 3: the pending design becomes the design, and that is on the disk too."""
        design = self._design_path(objective_id)
        os.replace(self._pending_path(objective_id), design)
        _fsync_dir(design.parent)

    def _write(self, obj: Objective) -> None:
        """Three atomic steps, in an order that leaves the whole old objective or the whole new
        one wherever it stops:

        1. the new design, as design/obj_x.next.json, stamped with the new record;
        2. the record, obj_x.json;
        3. the pending design becomes design/obj_x.json.

        Stopped before 2 finishes, the record is the old one: the pending design is ahead of it
        (written for a record with an event this one does not have) and is not read, and the
        design is the old one, which agrees — the old objective. Stopped after 2, the record is
        the new one and both designs agree with it (its history holds the old design's event
        too); the one written after more of that history is read — the pending one, the new
        objective. After 3 there is one design and it is the new one. Every write adds an event
        (a change that changes nothing is not written, ``_change``), which is what makes "more
        history" certain. The store before round 12 reads only obj_x.json, and at every point
        that is a whole record, old or new.

        "Wherever it stops" includes a power cut, because each step is on the disk, content and
        folder, before the next begins (`_atomic`, `_promote`). A pending design that is damaged
        all the same beside a record that has moved on is said to the owner (`_read`).
        """
        record, design = _split(obj)
        self._settle(obj.id)
        self._atomic(self._pending_path(obj.id), design)
        self._atomic(self._path(obj.id), record)
        self._promote(obj.id)

    def _settle(self, objective_id: str) -> None:
        """Before a write: finish or discard what the last one left. A pending design the record
        has (step 3 did not happen) becomes the design; one it does not have (the write stopped
        before its record) is discarded, since the change it carried was never made."""
        path = self._path(objective_id)
        if not path.exists():
            return
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(record, dict):
            return
        chosen = self._design_for(objective_id, record)
        pending = self._pending_path(objective_id)
        if chosen is not None and chosen[0] == "pending":
            self._promote(objective_id)
        elif pending.exists():
            pending.unlink()
            log.info("objective %s: a change that stopped before its record was written was not applied", objective_id)

    def _design_for(self, objective_id: str, record: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        return self._judge(objective_id, record)[0]

    def _judge(self, objective_id: str, record: dict[str, Any]) -> tuple[tuple[str, dict[str, Any]] | None, bool]:
        """The design that belongs with this record — ("design" or "pending", the design) — or
        None, and what to do with the files that do not; and whether a file was set aside as
        damage (unreadable, another objective's, a format this build does not know).

        A pending design that agrees is the newer of the two (step 3 of a write did not happen),
        and the design it supersedes is left for ``_settle`` to replace, whatever its verdict,
        unless it is damage of its own (unreadable, another objective's, an unknown format). A
        pending design that is only ahead of its record is an unfinished write, also left for
        ``_settle``. Anything else that cannot be used is set aside."""
        slots = {"design": self._design_path(objective_id), "pending": self._pending_path(objective_id)}
        judged: dict[str, tuple[str, Any]] = {}
        for slot, path in slots.items():
            if not path.exists():
                continue
            try:
                design = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                design = None
            judged[slot] = (_verdict(design, record), design)
        agreeing = {slot: design for slot, (verdict, design) in judged.items() if verdict == "agrees"}
        chosen = None
        if agreeing:
            slot = max(agreeing, key=lambda k: (agreeing[k]["events"], k == "pending"))
            chosen = (slot, agreeing[slot])
        damaged = False
        for slot, (verdict, _design) in judged.items():
            if verdict == "agrees":
                continue
            if slot == "pending" and verdict in ("ahead", "kind"):
                continue                                   # an unfinished write: _settle discards it
            if slot == "design" and chosen and chosen[0] == "pending" and verdict not in _DAMAGE:
                continue                                   # superseded: _settle replaces it
            damaged = damaged or verdict in _DAMAGE
            self._set_aside(objective_id, slots[slot], verdict, record)
        return chosen, damaged

    def _set_aside(self, objective_id: str, path: Path, verdict: str, record: dict[str, Any]) -> None:
        """Keep a design that cannot be used, renamed where no read or write will touch it again,
        and say so without a word of what is in it."""
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        kept = path.with_name(f"{objective_id}.{stamp}.{verdict}.damaged")
        try:
            os.replace(path, kept)
        except OSError:
            log.warning("objective %s: its design file (%s) could not be used or set aside; it reads as a plain %s",
                        objective_id, verdict, record.get("kind") or "business")
            return
        log.warning("objective %s: its design file could not be used (%s) and is kept aside as %s; the objective "
                    "reads as a plain %s from its record", objective_id, verdict, kept.name, record.get("kind") or "business")

    def _read(self, path: Path) -> Objective:
        with self._lock:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("an objective record is a JSON object")
            if not _ID.fullmatch(path.stem):
                return _from_record(raw, None)
            chosen, damaged = self._judge(path.stem, raw)
            obj = _from_record(raw, chosen[1] if chosen else None)
            if damaged and (chosen is None or chosen[1]["events"] < len(raw.get("events") or [])):
                self._say_lost(obj, chosen is not None)
            return obj

    def _say_lost(self, obj: Objective, kept: bool) -> None:
        """A design file was damaged, and the record has moved past the design being read: the
        record's latest change to the stages, tasks or people did not come back from the disk
        (round 13, T6-01). The design read is the one before it, or none. That is not passed
        over: it is put to the owner as an open question on the objective, with the change the
        record says was made, and written, so the next read and the next restart still say it.
        A record the store production rolls back to moved on, with no damaged file beside it,
        asks nothing (`_verdict`)."""
        last = str((obj.events[-1] if obj.events else {}).get("text") or "").strip()
        what = f" The last change recorded was: {last}" if last else ""
        if kept:
            text = ("The last change to its stages, tasks or people could not be read back from the disk, "
                    f"so they are shown as they were before it.{what} Say it again to put it back.")
        else:
            text = (f"Its stages, tasks and people could not be read back from the disk, so it shows as a plain "
                    f"{obj.kind} objective.{what} Say them again to put them back.")
        text = _clean(text)
        obj.attention.append({"id": _new_id("a"), "text": text, "at": _now(), "resolved_at": None})
        self._event(obj, "needs_owner", text, "clive")
        try:
            self._write(obj)
        except OSError:
            log.warning("objective %s: a lost design change could not be written down as a question; "
                        "it is shown on this read only", obj.id)

    def get(self, objective_id: str) -> Objective:
        path = self._path(objective_id)
        if not path.exists():
            raise ObjectiveError(f"There is no objective {objective_id!r}.")
        try:
            return self._read(path)
        except (OSError, ValueError, TypeError) as exc:
            # The record itself is damaged: skipped on the home (all), and said, not a 500, here.
            raise ObjectiveError(f"The record of objective {objective_id!r} cannot be read; it is kept as it is.") from exc

    def all(self) -> list[Objective]:
        if not self.root.exists():
            return []
        with self._lock:
            self._tidy()
            out = []
            for path in sorted(self.root.glob("obj_*.json")):
                try:
                    out.append(self._read(path))
                except (OSError, ValueError, TypeError):
                    continue  # a damaged file is skipped, never silently rewritten
        return sorted(out, key=lambda o: o.updated_at, reverse=True)

    def _tidy(self) -> None:
        """At most hourly: a design file (or its pending one, or a half-written one) whose record
        does not exist is a creation that stopped before its record was written; once it is a day
        old it is removed. Files kept aside as .damaged are evidence and stay. Objectives are never
        deleted, so a design with a record is never removed."""
        now = time.time()
        if now - getattr(self, "_tidied", 0.0) < TIDY_EVERY_S:
            return
        self._tidied = now
        folder = self.root / DESIGN_DIR
        if not folder.is_dir():
            return
        for path in folder.iterdir():
            name = path.name
            if not (name.endswith(".json") or name.endswith(".json.tmp")):
                continue
            objective_id = name.split(".", 1)[0]
            if not _ID.fullmatch(objective_id) or (self.root / f"{objective_id}.json").exists():
                continue
            try:
                if now - path.stat().st_mtime < ORPHAN_AGE_S:
                    continue
                path.unlink()
            except OSError:
                continue
            log.info("objective %s: a design file with no record, a day old, was removed", objective_id)

    def live(self) -> list[Objective]:
        return [o for o in self.all() if o.status not in CLOSED]

    def closed(self, search: str = "") -> list[Objective]:
        """The objectives closed out (done or dropped), each kept whole, the latest change first;
        with `search`, only those whose record mentions every word of it."""
        return [o for o in self.all() if o.status in CLOSED and o.mentions(search)]

    def _event(self, obj: Objective, kind: str, text: str, by: str) -> None:
        obj.events.append({"at": _now(), "kind": kind, "text": text[:MAX_TEXT], "by": by})
        obj.updated_at = _now()

    def _change(self, objective_id: str, fn, *, by: str) -> Objective:
        """One change, under the lock. A change that changes nothing is not written: every write
        then adds an event, which is what ties a design to its record without doubt (_write)."""
        with self._lock:
            obj = self.get(objective_id)
            before = _split(obj)
            fn(obj)
            if _split(obj) != before:
                self._write(obj)
            return obj

    # ---- creation ---------------------------------------------------------------
    def create(self, *, title: str, request: str, deadline: str | None = None, by: str = "clive",
               kind: str = "business", purpose: str = "", done_when: str = "", people: list | None = None,
               check_every_days: int | None = None, stages: list | None = None, stage: str = "",
               waiting_on: str = "", tasks: list | None = None, number: dict | None = None) -> Objective:
        """A new objective, shaped by its kind. A project is opened with its stages (and the one
        it is at, when that is known); a tasks objective with its tasks, each with who does it.
        Any kind may carry a number to reach. Everything else in the design is optional and can be
        added later (`design`)."""
        if kind not in KINDS:
            raise ObjectiveError(f"An objective is one of {', '.join(KINDS)}.")
        if kind == "project" and not stages:
            raise ObjectiveError("A project needs its stages, in order (for a drop: sampling, approval, "
                                 "production, delivery, or the stages he named).")
        if stages and kind != "project":
            raise ObjectiveError("Only a project has stages; open it as kind project.")
        if kind == "tasks" and not tasks:
            raise ObjectiveError("A tasks objective needs its tasks, each with who is to do it.")
        now = _now()
        obj = Objective(id=_new_id("obj"), title=_clean(title, limit=120, what="title"),
                        request=_clean(request, limit=4000, what="request"), created_at=now, updated_at=now,
                        deadline=_date(deadline, what="deadline"), kind=kind,
                        purpose=_optional(purpose), done_when=_optional(done_when),
                        people=self._people(people or []), check_every_days=_check_every(check_every_days),
                        number=_number(number, None) if number else None)
        if stages:
            obj.stages = self._stages([], stages)
            if stage:
                self._move(obj, self._stage_index(obj, stage))
            if waiting_on:
                here = obj.current_stage()
                if here is None:
                    raise ObjectiveError("waiting_on belongs to the stage it is at now; say which stage that is.")
                here[1]["waiting_on"] = _optional(waiting_on, limit=MAX_NAME * 2)
        # Every task he listed, or none (round 13, S6-02): past the limit `_add_task` refuses the
        # whole objective rather than keep the first sixty.
        for task in tasks or []:
            if not isinstance(task, dict):
                raise ObjectiveError("Each task has who and text.")
            found, added = self._add_task(obj, who=task.get("who"), text=task.get("text"), due=task.get("due"))
            when = _date(task.get("due"), what="task's date")
            if not added and when and when != found.get("due"):
                if found.get("due"):
                    raise ObjectiveError(f"{found['who']}'s task {found['text']!r} is listed twice with two dates, "
                                         f"{_on(found['due'])} and {_on(when)}; say which, and nothing was recorded.")
                found["due"] = when
        self._event(obj, "created", "Objective recorded from the owner's request.", by)
        with self._lock:
            self._write(obj)
        return obj

    # ---- the design: stages, tasks, people, dates -------------------------------------
    @staticmethod
    def _people(entries: list) -> list[dict]:
        """The people named, each once. Past the limit, refused whole rather than cut (round 13,
        S6-02): the thirteenth person named is not quietly left off."""
        out: list[dict] = []
        for entry in list(entries):
            person = _person(entry)
            if all(_key(p["name"]) != _key(person["name"]) for p in out):
                out.append(person)
            if len(out) > MAX_PEOPLE:
                raise ObjectiveError(f"An objective names at most {MAX_PEOPLE} people; nothing was recorded.")
        return out

    @staticmethod
    def _stages(existing: list[dict], names: list) -> list[dict]:
        """The stages in the order given. A stage that already exists (by name, in any case)
        keeps its state, dates and who it waits on; a new one is upcoming. If the stage the
        project was at is gone, it is at none until it is told."""
        if not isinstance(names, list) or not names:
            raise ObjectiveError("Stages are a list of names, in order.")
        if len(names) > MAX_STAGES:
            raise ObjectiveError(f"A project has at most {MAX_STAGES} stages.")
        by_name = {_key(s["name"]): s for s in existing}
        out: list[dict] = []
        for raw in names:
            name = _clean(raw.get("name") if isinstance(raw, dict) else raw, limit=MAX_NAME, what="stage name")
            if any(_key(s["name"]) == _key(name) for s in out):
                raise ObjectiveError(f"The stage {name!r} is named twice.")
            kept = by_name.get(_key(name))
            out.append({**kept, "name": name} if kept else {
                "id": _new_id("s"), "name": name, "state": "upcoming", "due": None, "waiting_on": None,
                "started_at": None, "done_at": None,
            })
        ObjectiveStore._in_order(out)
        return out

    @staticmethod
    def _in_order(stages: list[dict]) -> None:
        """Every done stage before the one the project is at, and every stage not yet reached
        after it (round 13, S6-04). A stage keeps its state by name when the list is reordered,
        and moving on (`_move`) goes by place: a done stage placed after the current one was made
        upcoming again by the next "next", and when it was done was wiped. So an order that would
        put a stage where its state does not belong is refused, in words that say which."""
        rank = {"done": 0, "current": 1, "upcoming": 2}
        for before, after in zip(stages, stages[1:], strict=False):
            if rank[before["state"]] <= rank[after["state"]]:
                continue
            if after["state"] == "done":
                raise ObjectiveError(f"{after['name']} is done, so it cannot come after {before['name']}, which is "
                                     f"not; nothing was changed.")
            raise ObjectiveError(f"{before['name']} has not been reached, so it cannot come before {after['name']}, "
                                 f"where the project is now; put it after, or move the project back first. "
                                 f"Nothing was changed.")

    @staticmethod
    def _stage_index(obj: Objective, stage: str) -> int:
        """Which stage `stage` names: its name in any case, or "next" (the one after the stage it
        is at, or the first when it has not started). len(stages) means past the last one."""
        wanted = _key(stage)
        if not obj.stages:
            raise ObjectiveError("This objective has no stages; only a project does.")
        if wanted == "next":
            here = obj.current_stage()
            if here is not None:
                return here[0] + 1
            if all(s.get("state") == "done" for s in obj.stages):
                raise ObjectiveError("Every stage is already done.")
            return next(i for i, s in enumerate(obj.stages) if s.get("state") != "done")
        for index, candidate in enumerate(obj.stages):
            if _key(candidate["name"]) == wanted:
                return index
        names = ", ".join(s["name"] for s in obj.stages)
        raise ObjectiveError(f"There is no stage {stage!r}; the stages are {names}.")

    @staticmethod
    def _move(obj: Objective, index: int) -> None:
        """The project is now at stage `index`: every stage before it done, it current, every
        stage after it upcoming. Past the last stage, every stage is done. A stage keeps the
        time it was first done; moving back makes the stages after it upcoming again."""
        now = _now()
        for i, stage in enumerate(obj.stages):
            if i < index:
                if stage["state"] != "done":
                    stage["state"], stage["done_at"] = "done", now
                    stage["started_at"] = stage.get("started_at") or now
            elif i == index:
                if stage["state"] != "current":
                    stage["state"], stage["started_at"], stage["done_at"] = "current", now, None
            elif stage["state"] != "upcoming":
                stage["state"], stage["started_at"], stage["done_at"] = "upcoming", None, None

    def _who(self, obj: Objective, who: Any) -> str:
        """A person as this objective already spells them, or as given."""
        name = _clean(who, limit=MAX_NAME, what="name of who is to do it")
        for known in [t.get("who") for t in obj.tasks] + [p["name"] for p in obj.people]:
            if known and _key(known) == _key(name):
                return known
        return _proper(name)

    def _add_task(self, obj: Objective, *, who: Any, text: Any, due: Any) -> tuple[dict, bool]:
        """The task, and whether it is new. Said twice is one task, not two: the one already
        there comes back, and what to do with a date said with it is the caller's (a new date
        is applied, never passed over: round 13, S6-03)."""
        person, words = self._who(obj, who), _clean(text, limit=300, what="task")
        same = next((t for t in obj.tasks if not t.get("done") and _key(t["who"]) == _key(person)
                     and _key(t["text"]) == _key(words)), None)
        if same is not None:
            return same, False
        if len(obj.tasks) >= MAX_TASKS:
            raise ObjectiveError(f"An objective holds at most {MAX_TASKS} tasks; nothing was recorded.")
        task = {"id": _new_id("t"), "who": person, "text": words, "due": _date(due, what="task's date"),
                "done": False, "done_at": None, "at": _now()}
        obj.tasks.append(task)
        return task, True

    def design(self, objective_id: str, *, by: str = "clive", title: str | None = None, kind: str | None = None,
               deadline: str | None = None, purpose: str | None = None, done_when: str | None = None,
               people: list | None = None, check_every_days: int | None = None, stages: list | None = None,
               stage: str | None = None, waiting_on: str | None = None, due: str | None = None,
               number: dict | None = None) -> Objective:
        """Change what the objective is: only what is passed changes, and an empty string clears
        a text or a date. `stages` is the whole list in its new order. With `stage`, `due` and
        `waiting_on` are that stage's and nothing moves (moving is `move_stage`). `number` changes
        only the parts of the number passed, and `{}` takes it off."""
        def fn(o: Objective) -> None:
            said: list[str] = []
            if title is not None:
                o.title = _clean(title, limit=120, what="title")
                said.append(f"Called {o.title}")
            if kind is not None and kind != o.kind:
                if kind not in KINDS:
                    raise ObjectiveError(f"An objective is one of {', '.join(KINDS)}.")
                if o.engineering and kind != "build":
                    raise ObjectiveError("A build objective with an engineering request filed stays a build.")
                if kind == "project" and not (stages or o.stages):
                    raise ObjectiveError("A project needs its stages, in order.")
                if o.kind == "project" and kind != "project":
                    o.stages = []
                o.kind = kind
                said.append(f"Now a {kind} objective")
            if stages is not None:
                if o.kind != "project":
                    raise ObjectiveError("Only a project has stages; make it kind project first.")
                o.stages = self._stages(o.stages, stages)
                said.append("Stages: " + ", ".join(s["name"] for s in o.stages))
            if deadline is not None:
                o.deadline = _date(deadline, what="deadline")
                said.append(f"Deadline {_on(o.deadline)}" if o.deadline else "No deadline")
            if purpose is not None:
                o.purpose = _optional(purpose)
                said.append(f"Why: {o.purpose}" if o.purpose else "No purpose")
            if done_when is not None:
                o.done_when = _optional(done_when)
                said.append(f"Done when: {o.done_when}" if o.done_when else "No finish line")
            if people is not None:
                o.people = self._people(people)
                said.append("People: " + (", ".join(p["name"] for p in o.people) or "none"))
            if check_every_days is not None:
                o.check_every_days = _check_every(check_every_days)
                said.append(f"Check in every {o.check_every_days} days" if o.check_every_days else "No check-ins")
            if number is not None:
                before = o.number
                o.number = _number(number, before)
                said.append(_number_said(before, o.number))
            if stage is not None:
                target = o.stages[self._stage_index(o, stage)] if _key(stage) != "next" else None
                if target is None:
                    raise ObjectiveError("Name the stage to change; to move on, use the stage action.")
                said.extend(self._stage_details(target, waiting_on=waiting_on, due=due))
            elif waiting_on is not None or due is not None:
                raise ObjectiveError("waiting_on and due belong to a stage here; name it with stage.")
            if not said:
                raise ObjectiveError("Nothing to change was given.")
            self._event(o, "design", "; ".join(said) + ".", by)
        return self._change(objective_id, fn, by=by)

    @staticmethod
    def _stage_details(stage: dict, *, waiting_on: str | None, due: str | None) -> list[str]:
        said = []
        if waiting_on is not None:
            stage["waiting_on"] = _optional(waiting_on, limit=MAX_NAME * 2)
            said.append(f"{stage['name']} waiting on {stage['waiting_on']}" if stage["waiting_on"]
                        else f"{stage['name']} waiting on nobody")
        if due is not None:
            stage["due"] = _date(due, what="stage's date")
            said.append(f"{stage['name']} by {_on(stage['due'])}" if stage["due"] else f"{stage['name']} has no date")
        return said

    def move_stage(self, objective_id: str, stage: str, *, waiting_on: str | None = None, due: str | None = None,
                   by: str = "clive") -> Objective:
        """The project is now at `stage` (its name, or "next"). What that stage waits on and its
        date may be said in the same breath. A record of where the project is: nothing is
        ordered, booked or sent by moving it."""
        def fn(o: Objective) -> None:
            if o.kind != "project":
                raise ObjectiveError("Only a project has stages.")
            index = self._stage_index(o, stage)
            before = o.current_stage()
            self._move(o, index)
            if index >= len(o.stages):
                if waiting_on is not None or due is not None:
                    raise ObjectiveError("Every stage is done, so no stage is waiting on anything.")
                last = f"; {before[1]['name']} was the last" if before else ""
                self._event(o, "stage", f"Every stage done{last}.", by)
                return
            here = o.stages[index]
            extra = self._stage_details(here, waiting_on=waiting_on, due=due)
            left = f"; {before[1]['name']} done" if before and before[0] < index else ""
            self._event(o, "stage", f"Now at {here['name']}{left}{'; ' + '; '.join(extra) if extra else ''}.", by)
        return self._change(objective_id, fn, by=by)

    def task(self, objective_id: str, *, item_id: str = "", who: str | None = None, text: str | None = None,
             due: str | None = None, done: bool | None = None, by: str = "clive") -> Objective:
        """One task added (who and text, and a date if one was said), or, with item_id, that
        task changed: who, what, when, done or not. With only who and done, every one of that
        person's tasks: "mark Rosa's done". Nothing is sent to anybody."""
        def fn(o: Objective) -> None:
            if item_id:
                found = next((t for t in o.tasks if t["id"] == item_id), None)
                if found is None:
                    raise ObjectiveError(f"There is no task {item_id!r} on this objective.")
                if who is None and text is None and due is None and done is None:
                    raise ObjectiveError("Nothing to change on that task was given.")
                self._edit_task(o, found, who=who, text=text, due=due, done=done, by=by)
                return
            if text is None and who is not None and done is not None:
                theirs = [t for t in o.tasks if _key(t["who"]) == _key(who) and bool(t.get("done")) != done]
                if not theirs:
                    state = "done" if done else "open"
                    raise ObjectiveError(f"{_proper(str(who))} has no task that is not already {state}.")
                for found in theirs:
                    self._edit_task(o, found, who=None, text=None, due=None, done=done, by=by)
                return
            if who is None or text is None:
                raise ObjectiveError("A new task needs who is to do it and what it is.")
            added, new = self._add_task(o, who=who, text=text, due=due)
            when = _date(due, what="task's date")
            if not new and when and when != added.get("due"):
                # Said again with another date: the date he gives now is the task's date.
                self._edit_task(o, added, who=None, text=None, due=when, done=done or None, by=by)
                return
            if done:
                self._edit_task(o, added, who=None, text=None, due=None, done=True, by=by)
            self._event(o, "task", f"For {added['who']}: {added['text']}"
                                   f"{' by ' + _on(added['due']) if added.get('due') else ''}.", by)
        return self._change(objective_id, fn, by=by)

    def _edit_task(self, o: Objective, task: dict, *, who: Any, text: Any, due: Any, done: bool | None,
                   by: str) -> None:
        said = []
        if who is not None:
            task["who"] = self._who(o, who)
            said.append(f"now {task['who']}'s")
        if text is not None:
            task["text"] = _clean(text, limit=300, what="task")
            said.append("reworded")
        if due is not None:
            task["due"] = _date(due, what="task's date")
            said.append(f"by {_on(task['due'])}" if task["due"] else "no date")
        if done is not None and bool(task.get("done")) != bool(done):
            task["done"], task["done_at"] = bool(done), (_now() if done else None)
            said.append("done" if done else "not done after all")
        if said:
            self._event(o, "task", f"{task['who']}: {task['text']} — {', '.join(said)}.", by)

    def drop_task(self, objective_id: str, item_id: str, *, by: str = "clive") -> Objective:
        def fn(o: Objective) -> None:
            found = next((t for t in o.tasks if t["id"] == item_id), None)
            if found is None:
                raise ObjectiveError(f"There is no task {item_id!r} on this objective.")
            o.tasks.remove(found)
            self._event(o, "task", f"Taken off {found['who']}'s list: {found['text']}.", by)
        return self._change(objective_id, fn, by=by)

    # ---- the owner's touch, and six seconds to take it back ----------------------------
    # Each returns the objective, the undo offer ({token, ttl_s, says}) when it changed something,
    # and, when it changed nothing, the line that says so (`Touched`). Only the owner's screen
    # calls these.
    def touch_stage(self, objective_id: str, stage: str) -> Touched:
        """The owner made `stage` (a name, or "next") the stage the project is at now."""
        def plan(o: Objective):
            if o.kind != "project":
                raise ObjectiveError("Only a project has stages.")
            index = self._stage_index(o, stage)
            here = o.current_stage()
            if here is not None and here[0] == index:
                return f"{here[1]['name']} is already where it is now."
            act = lambda: self.move_stage(objective_id, stage, by="owner")  # noqa: E731
            return act, self._stage_says(o, index, here), self._stage_was(o, here)
        return self._touch(objective_id, plan)

    @staticmethod
    def _stage_says(o: Objective, index: int, here: tuple[int, dict] | None) -> str:
        if index >= len(o.stages):
            return "Every stage done"
        name = o.stages[index]["name"]
        if here is None and not any(s.get("state") == "done" for s in o.stages):
            return f"Started: {name} is now"
        return f"{name} is now" if here is not None and index > here[0] else f"Back to {name}"

    @staticmethod
    def _stage_was(o: Objective, here: tuple[int, dict] | None) -> str:
        if here is not None:
            return f"Back at {here[1]['name']}, as it was"
        if o.stages and all(s.get("state") == "done" for s in o.stages):
            return "Every stage done, as it was"
        return "Not started, as it was"

    def touch_task(self, objective_id: str, task_id: str, *, done: bool | None = None,
                   who: str | None = None) -> Touched:
        """The owner ticked a task done or open, or handed it to someone else, or both."""
        def plan(o: Objective):
            found = next((t for t in o.tasks if t["id"] == task_id), None)
            if found is None:
                raise ObjectiveError(f"There is no task {task_id!r} on this objective.")
            if done is None and who is None:
                raise ObjectiveError("Say whether it is done, or who it is for.")
            to = self._who(o, who) if who is not None else None
            to = to if to is not None and _key(to) != _key(found["who"]) else None
            tick = done if done is not None and bool(done) != bool(found.get("done")) else None
            if to is None and tick is None:
                if who is not None:
                    return f"That is already {found['who']}'s."
                return f"Already {'done' if found.get('done') else 'open'}: {found['text']}"
            act = lambda: self.task(objective_id, item_id=task_id, who=to, done=tick, by="owner")  # noqa: E731
            return act, self._task_says(found, to, tick), self._task_was(found, to, tick)
        return self._touch(objective_id, plan)

    @staticmethod
    def _task_says(found: dict, to: str | None, tick: bool | None) -> str:
        if to is not None:
            return f"Moved to {to}" + ("" if tick is None else f", {'done' if tick else 'open'}")
        return f"{'Done' if tick else 'Open again'}: {found['text']}"

    @staticmethod
    def _task_was(found: dict, to: str | None, tick: bool | None) -> str:
        again = []
        if to is not None:
            again.append(f"{found['who']}'s")
        if tick is not None:
            again.append("done" if found.get("done") else "open")
        return f"“{found['text']}” is {' and '.join(again)} again"

    def touch_deadline(self, objective_id: str, deadline: str) -> Touched:
        """The owner moved the date it must land by ("" takes it off)."""
        def plan(o: Objective):
            new = _date(deadline, what="deadline")
            if new == o.deadline:
                return f"It is already due {_day(new)}." if new else "It has no deadline to take off."
            act = lambda: self.design(objective_id, deadline=new or "", by="owner")  # noqa: E731
            says = f"Due {_day(new)}{self._lands(o, new)}" if new else "No deadline now"
            return act, says, (f"Due {_day(o.deadline)} again" if o.deadline else "No deadline again")
        return self._touch(objective_id, plan)

    def touch_target(self, objective_id: str, target: Any) -> Touched:
        """The owner dragged the number's target up or down. What that means for the pace is the
        count's to say (the route adds it); here it is the target, as one ordinary change."""
        def plan(o: Objective):
            if not o.number:
                raise ObjectiveError("This objective has no number, so it has no target to move.")
            new, was = _target(target), o.number["target"]
            if new == was:
                return f"The target is already {new:,}."
            act = lambda: self.design(objective_id, number={"target": new}, by="owner")  # noqa: E731
            return act, f"Target {new:,}", f"Target {was:,} again"
        return self._touch(objective_id, plan)

    @staticmethod
    def _lands(o: Objective, deadline: str) -> str:
        """What a new deadline means for a project's dated stages still to finish."""
        dated = [s for s in o.stages if s.get("state") != "done" and s.get("due")] if o.kind == "project" else []
        late = [s["name"] for s in dated if s["due"] > deadline]
        if late:
            return f"; {_listed(late)} would land after it"
        return "; everything still lands in time" if dated else ""

    def _touch(self, objective_id: str, plan: Callable[[Objective], Any]) -> Touched:
        """One touch, under the lock: what it can change is kept as it was, the change is made the
        ordinary way, and an undo offer is made for it. `plan` says what the change is (the act,
        what it did in words, what an undo puts back), or, as a string, that it changes nothing."""
        with self._lock:
            before = self.get(objective_id)
            planned = plan(before)
            if isinstance(planned, str):
                return before, None, planned
            act, says, put_back = planned
            kept = _restorable(before)
            after = act()
            if _restorable(after) == kept:
                return after, None, None
            token = secrets.token_urlsafe(18)
            self._offer(token, {"objective_id": after.id, "kept": kept, "ends": _ends(after), "at": _clock(),
                                "says": says, "put_back": put_back})
            return after, {"token": token, "ttl_s": UNDO_OFFER_S, "says": says}, None

    def _offer(self, token: str, offer: dict[str, Any]) -> None:
        """Keep an undo offer: the lapsed ones go first, then the oldest past the bound."""
        for old in [t for t, o in self._undos.items() if offer["at"] - o["at"] > UNDO_GRACE_S]:
            del self._undos[old]
        self._undos[token] = offer
        while len(self._undos) > UNDO_KEPT:
            self._undos.popitem(last=False)

    def undo(self, objective_id: str, token: str) -> tuple[Objective, str]:
        """Take back the touch `token` was offered for: its stages, tasks, deadline and number exactly as
        they were before it, if the objective has not changed since and the window is still open.
        Once used, or refused for being late or overtaken, the token is gone."""
        with self._lock:
            offer = self._undos.get(str(token or ""))
            if offer is None:
                raise ObjectiveError("That can no longer be undone, so nothing was changed.")
            if offer["objective_id"] != objective_id:
                raise ObjectiveError("That undo belongs to another objective, so nothing was undone.")
            del self._undos[str(token)]
            if _clock() - offer["at"] > UNDO_GRACE_S:
                raise ObjectiveError("It is too late to undo that, so nothing was undone.")

            def fn(o: Objective) -> None:
                if _ends(o) != offer["ends"]:
                    raise ObjectiveError("It has changed since, so nothing was undone.")
                for name, value in offer["kept"].items():
                    setattr(o, name, copy.deepcopy(value))
                self._event(o, "undo", f"Undone: {offer['says']}.", "owner")
            return self._change(objective_id, fn, by="owner"), offer["put_back"]

    # ---- what CLIVE records as it works --------------------------------------------
    def add_fact(self, objective_id: str, text: str, *, source: str, by: str = "clive") -> Objective:
        source = _clean(source, limit=300, what="source")
        def fn(o):
            o.facts.append({"id": _new_id("f"), "text": _clean(text), "source": source, "at": _now()})
            self._event(o, "fact", f"{text} (source: {source})", by)
        return self._change(objective_id, fn, by=by)

    def add_unknown(self, objective_id: str, text: str, *, by: str = "clive") -> Objective:
        def fn(o):
            o.unknowns.append({"id": _new_id("u"), "text": _clean(text), "at": _now(), "resolved_at": None})
            self._event(o, "unknown", text, by)
        return self._change(objective_id, fn, by=by)

    def add_blocker(self, objective_id: str, text: str, *, kind: str, by: str = "clive",
                    capability: str = "") -> Objective:
        """A blocker. A missing_capability one is also a capability gap (app/objectives/gaps.py),
        counted under `capability` (a few words naming what CLIVE lacks) or, without it, under
        the blocker's own words."""
        if kind not in BLOCKER_KINDS:
            raise ObjectiveError(f"A blocker is one of {', '.join(BLOCKER_KINDS)}.")
        capability = " ".join(str(capability or "").split())[:60]

        def fn(o):
            entry = {"id": _new_id("b"), "text": _clean(text), "kind": kind, "at": _now(), "resolved_at": None}
            if kind == "missing_capability" and capability:
                entry["capability"] = capability
            o.blockers.append(entry)
            if o.status == "active":
                o.status = "blocked" if kind != "needs_owner" else "waiting"
            self._event(o, "blocker", f"{kind}: {text}", by)
        obj = self._change(objective_id, fn, by=by)
        if kind == "missing_capability":
            from app.objectives import gaps

            record = gaps.ledger()
            if record is not None:
                record.note_blocker(obj.id, obj.blockers[-1]["text"], capability, at=obj.blockers[-1]["at"])
        return obj

    def gap_keys(self, objective_id: str) -> list[str]:
        """The capability gaps an objective's open missing_capability blockers name."""
        from app.objectives.gaps import key_for

        obj = self.get(objective_id)
        return sorted({key_for(b.get("capability", ""), b.get("text", "")) for b in obj.open_("blockers")
                       if b.get("kind") == "missing_capability"})

    def ask_owner(self, objective_id: str, text: str, *, by: str = "clive") -> Objective:
        def fn(o):
            o.attention.append({"id": _new_id("a"), "text": _clean(text), "at": _now(), "resolved_at": None})
            self._event(o, "needs_owner", text, by)
        return self._change(objective_id, fn, by=by)

    def resolve(self, objective_id: str, entry_id: str, *, note: str = "", by: str = "clive") -> Objective:
        def fn(o):
            for key in ("unknowns", "blockers", "attention"):
                for entry in getattr(o, key):
                    if entry["id"] == entry_id and not entry.get("resolved_at"):
                        entry["resolved_at"] = _now()
                        if note:
                            entry["resolution"] = note[:MAX_TEXT]
                        self._event(o, "resolved", f"{entry['text']}{' — ' + note if note else ''}", by)
                        if key == "blockers" and not o.open_("blockers") and o.status in ("blocked", "waiting"):
                            o.status = "active"
                        return
            raise ObjectiveError(f"There is no open unknown, blocker or question {entry_id!r} on this objective.")
        return self._change(objective_id, fn, by=by)

    def propose(self, objective_id: str, text: str, *, needs_owner: bool, by: str = "clive") -> Objective:
        def fn(o):
            self._not_the_plan_again(o, text)
            o.items.append({"id": _new_id("w"), "text": _clean(text), "state": "proposed", "needs_owner": bool(needs_owner),
                            "evidence": None, "history": [{"state": "proposed", "at": _now(), "by": by}]})
            self._event(o, "proposed", f"{text}{' (needs your approval)' if needs_owner else ''}", by)
        return self._change(objective_id, fn, by=by)

    @staticmethod
    def _not_the_plan_again(o: Objective, text: str) -> None:
        """A work item that repeats one of the people's tasks or a stage is the design written out
        a second time as a to-do list, which is exactly the complaint round 12 answers: refused,
        with what to do instead. "Rosa: steam the samples" and "Steam the samples" both repeat
        Rosa's task."""
        said = _key(text)
        for task in o.tasks:
            if said in (_key(task["text"]), _key(f"{task['who']}: {task['text']}")):
                raise ObjectiveError(f"That is already {task['who']}'s task; tasks are not work items. "
                                     "Use action task to change it.")
        for stage in o.stages:
            if said == _key(stage["name"]):
                raise ObjectiveError(f"{stage['name']} is already a stage of this project; move it with action stage.")

    def advance(self, objective_id: str, item_id: str, to: str, *, evidence: str = "", by: str = "clive") -> Objective:
        """Move a work item up the ladder. The owner's approval is never taken from here."""
        if to not in LADDER:
            raise ObjectiveError(f"A work item's state is one of {', '.join(LADDER)}.")
        if to == "authorised" and by != "owner":
            raise ObjectiveError("Only the owner can authorise a work item; ask them instead.")
        def fn(o):
            item = next((i for i in o.items if i["id"] == item_id), None)
            if item is None:
                raise ObjectiveError(f"There is no work item {item_id!r} on this objective.")
            here, there = LADDER.index(item["state"]), LADDER.index(to)
            if there <= here:
                raise ObjectiveError(f"That item is already {item['state']}.")
            if item["needs_owner"] and there >= LADDER.index("started") and item["state"] == "proposed":
                raise ObjectiveError("This item needs the owner's approval before it can start.")
            if to == "verified" and not evidence.strip():
                raise ObjectiveError("Verified needs the evidence that shows it happened.")
            item["state"] = to
            if evidence:
                item["evidence"] = evidence[:MAX_TEXT]
            item["history"].append({"state": to, "at": _now(), "by": by, **({"evidence": evidence[:MAX_TEXT]} if evidence else {})})
            self._event(o, to, item["text"] + (f" — {evidence}" if evidence else ""), by)
        return self._change(objective_id, fn, by=by)

    def authorise(self, objective_id: str, item_id: str) -> Objective:
        """The owner's approval of one work item. Called only from the owner's own screen."""
        return self.advance(objective_id, item_id, "authorised", by="owner")

    def progress(self, objective_id: str, text: str, *, by: str = "clive") -> Objective:
        def fn(o):
            self._event(o, "progress", _clean(text), by)
        return self._change(objective_id, fn, by=by)

    def set_status(self, objective_id: str, status: str, *, note: str = "", by: str = "clive") -> Objective:
        if status not in STATUSES:
            raise ObjectiveError(f"An objective's status is one of {', '.join(STATUSES)}.")
        if status in ("done", "dropped") and by != "owner":
            # CLIVE can say everything is complete or dead; closing the owner's objective is the owner's call.
            raise ObjectiveError("Only the owner closes or drops an objective; ask them first.")
        def fn(o):
            o.status = status
            o.status_set_by = by
            self._event(o, "status", f"{status}{' — ' + note if note else ''}", by)
        return self._change(objective_id, fn, by=by)

    def close(self, objective_id: str, outcome: str, *, note: str, by: str = "clive") -> Objective:
        """Close an objective out, complete or removed, when the owner says so: it leaves the live
        list and nothing on it is deleted — facts, notes, blockers, items, tasks and history stay
        as they were, read by its id or found among the closed. The owner's words asking for it
        are required and kept in the history with who closed it. Closed by CLIVE on those words,
        it is not an owner-set status (`attention_`), which stays the owner's screen's to set
        (`set_status`). Reopening it is status active."""
        status = CLOSINGS.get(outcome)
        if status is None:
            raise ObjectiveError(f"An objective is closed as {' or '.join(CLOSINGS)}.")
        said = _clean(note, what="owner's request to close it")

        def fn(o):
            if o.status in CLOSED:
                raise ObjectiveError(f"That objective is already closed ({o.status}).")
            o.status = status
            o.status_set_by = by
            self._event(o, "status", f"{status} — closed as {outcome}: {said}", by)
        return self._change(objective_id, fn, by=by)

    def link_engineering(self, objective_id: str, *, request_id: str, host: str, target_branch: str,
                         by: str = "clive") -> Objective:
        """An engineering request was filed for this objective (app/tools/engineering_tools.py):
        remember it, make it a build objective, and put the building on the ladder as started —
        the loop is working on it from now, and the owner authorised the filing on his card."""
        def fn(o):
            o.kind = "build"
            o.engineering.append({"request_id": str(request_id)[:80], "host": str(host)[:40],
                                  "target_branch": str(target_branch)[:120], "filed_at": _now()})
            text = _clean(f"Build it with the engineering loop (request {request_id})")
            o.items.append({"id": _new_id("w"), "text": text, "state": "started", "needs_owner": False,
                            "evidence": None, "engineering": str(request_id)[:80],
                            "history": [{"state": "started", "at": _now(), "by": by}]})
            self._event(o, "engineering", f"Filed engineering request {request_id} with the {host} loop; "
                                          f"its work lands on {target_branch}.", by)
        return self._change(objective_id, fn, by=by)

    def owner_note(self, objective_id: str, text: str) -> Objective:
        """Something the owner said about the objective, kept as a fact from the owner."""
        return self.add_fact(objective_id, text, source="owner", by="owner")


_STORE: ObjectiveStore | None = None


def install(root: Path) -> ObjectiveStore:
    global _STORE
    _STORE = ObjectiveStore(root)
    return _STORE


def store() -> ObjectiveStore:
    if _STORE is None:
        from config.settings import get_settings

        return install(get_settings().objectives_dir)
    return _STORE
