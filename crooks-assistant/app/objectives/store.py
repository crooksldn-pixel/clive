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

A record written before round 12 (version 1) has none of the design fields; ``_from_record``
reads it as it always read, and the fields are written the next time it changes.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

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
BLOCKER_KINDS = ("missing_info", "missing_capability", "needs_owner", "external")
# What an objective is for, which decides its shape (the module docstring says each). "build":
# the owner wants CLIVE itself changed, and the work goes to the engineering loop. "business" is
# the kind every record had before kinds were designed, and stays the kind of any other goal.
KINDS = ("business", "build", "project", "tasks")
STAGE_STATES = ("done", "current", "upcoming")
_ID = re.compile(r"^obj_[0-9a-f]{8}$")
MAX_TEXT = 2000
# The record's own format. 1: Objective V0 and the build kind; 2: the design fields (round 12).
VERSION = 2
# Bounds that keep a record a thing a person reads, not a spreadsheet.
MAX_STAGES = 10
MAX_TASKS = 60
MAX_PEOPLE = 12
MAX_NAME = 60
MAX_CHECK_EVERY = 90
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
    version: int = VERSION

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

    def missing(self) -> list[dict[str, str]]:
        """What the shape of this kind still lacks and only the owner can say, for the one short
        question CLIVE asks when it opens the objective. Business and build objectives ask what
        they need as questions on the record (ask_owner), as they always have."""
        out: list[dict[str, str]] = []
        if self.kind == "project":
            if not any(s.get("state") in ("current", "done") for s in self.stages):
                out.append({"field": "stage", "means": "which stage it is at now"})
            if not self.deadline:
                out.append({"field": "deadline", "means": "the date it has to be finished by"})
        elif self.kind == "tasks" and not self.tasks:
            out.append({"field": "tasks", "means": "who is to do what"})
        return out

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
        return {
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
            "stages": [{"name": s["name"], "state": s["state"]} for s in self.stages],
            "people_tasks": [{"who": g["who"], "open": g["open"], "done": g["done"]} for g in self.task_groups()],
            "check_in": cadence,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FIELDS = frozenset(f.name for f in fields(Objective))


def _from_record(raw: Any) -> Objective:
    """A record as any version of the store wrote it, as an Objective of this version.

    Version 1 (no ``version`` key) was written by Objective V0 and by the build kind: it has no
    purpose, done_when, people, stages, tasks or cadence, and records older still have no kind,
    engineering or status_set_by. Each missing field is given the value that means "none", the
    kind a record without one always had ("business") is written in, and nothing already there
    is touched, so an old objective reads exactly as it did. A key this store does not know
    (a record from a newer build) is refused as the whole record is, like a damaged file,
    rather than dropped on the next write.
    """
    if not isinstance(raw, dict):
        raise ValueError("an objective record is a JSON object")
    data = dict(raw)
    if int(data.get("version") or 1) < 2:
        data.setdefault("kind", "business")
        data.setdefault("engineering", [])
        for name in ("people", "stages", "tasks"):
            data[name] = list(data.get(name) or [])
        for name in ("purpose", "done_when", "check_every_days"):
            data.setdefault(name, None)
        data["version"] = VERSION
    unknown = set(data) - _FIELDS
    if unknown:
        raise ValueError(f"unknown fields {sorted(unknown)}")
    return Objective(**data)


def _days_left(deadline: str | None) -> int | None:
    if not deadline:
        return None
    try:
        return (date.fromisoformat(deadline) - datetime.now(UTC).date()).days
    except ValueError:
        return None


class ObjectiveStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()

    # ---- persistence ----------------------------------------------------------
    def _path(self, objective_id: str) -> Path:
        if not _ID.fullmatch(str(objective_id)):
            raise ObjectiveError(f"There is no objective {objective_id!r}.")
        return self.root / f"{objective_id}.json"

    def _write(self, obj: Objective) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(obj.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(obj.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def get(self, objective_id: str) -> Objective:
        path = self._path(objective_id)
        if not path.exists():
            raise ObjectiveError(f"There is no objective {objective_id!r}.")
        return _from_record(json.loads(path.read_text(encoding="utf-8")))

    def all(self) -> list[Objective]:
        if not self.root.exists():
            return []
        out = []
        for path in sorted(self.root.glob("obj_*.json")):
            try:
                out.append(_from_record(json.loads(path.read_text(encoding="utf-8"))))
            except (ValueError, TypeError):
                continue  # a damaged file is skipped, never silently rewritten
        return sorted(out, key=lambda o: o.updated_at, reverse=True)

    def live(self) -> list[Objective]:
        return [o for o in self.all() if o.status not in ("done", "dropped")]

    def _event(self, obj: Objective, kind: str, text: str, by: str) -> None:
        obj.events.append({"at": _now(), "kind": kind, "text": text[:MAX_TEXT], "by": by})
        obj.updated_at = _now()

    def _change(self, objective_id: str, fn, *, by: str) -> Objective:
        with self._lock:
            obj = self.get(objective_id)
            fn(obj)
            self._write(obj)
            return obj

    # ---- creation ---------------------------------------------------------------
    def create(self, *, title: str, request: str, deadline: str | None = None, by: str = "clive",
               kind: str = "business", purpose: str = "", done_when: str = "", people: list | None = None,
               check_every_days: int | None = None, stages: list | None = None, stage: str = "",
               waiting_on: str = "", tasks: list | None = None) -> Objective:
        """A new objective, shaped by its kind. A project is opened with its stages (and the one
        it is at, when that is known); a tasks objective with its tasks, each with who does it.
        Everything else in the design is optional and can be added later (`design`)."""
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
                        people=self._people(people or []), check_every_days=_check_every(check_every_days))
        if stages:
            obj.stages = self._stages([], stages)
            if stage:
                self._move(obj, self._stage_index(obj, stage))
            if waiting_on:
                here = obj.current_stage()
                if here is None:
                    raise ObjectiveError("waiting_on belongs to the stage it is at now; say which stage that is.")
                here[1]["waiting_on"] = _optional(waiting_on, limit=MAX_NAME * 2)
        for task in (tasks or [])[:MAX_TASKS]:
            if not isinstance(task, dict):
                raise ObjectiveError("Each task has who and text.")
            self._add_task(obj, who=task.get("who"), text=task.get("text"), due=task.get("due"))
        self._event(obj, "created", "Objective recorded from the owner's request.", by)
        with self._lock:
            self._write(obj)
        return obj

    # ---- the design: stages, tasks, people, dates -------------------------------------
    @staticmethod
    def _people(entries: list) -> list[dict]:
        out: list[dict] = []
        for entry in list(entries)[:MAX_PEOPLE]:
            person = _person(entry)
            if all(_key(p["name"]) != _key(person["name"]) for p in out):
                out.append(person)
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
        return out

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

    def _add_task(self, obj: Objective, *, who: Any, text: Any, due: Any) -> dict:
        person, words = self._who(obj, who), _clean(text, limit=300, what="task")
        same = next((t for t in obj.tasks if not t.get("done") and _key(t["who"]) == _key(person)
                     and _key(t["text"]) == _key(words)), None)
        if same is not None:
            return same  # said twice is one task, not two
        if len(obj.tasks) >= MAX_TASKS:
            raise ObjectiveError(f"An objective holds at most {MAX_TASKS} tasks.")
        task = {"id": _new_id("t"), "who": person, "text": words, "due": _date(due, what="task's date"),
                "done": False, "done_at": None, "at": _now()}
        obj.tasks.append(task)
        return task

    def design(self, objective_id: str, *, by: str = "clive", title: str | None = None, kind: str | None = None,
               deadline: str | None = None, purpose: str | None = None, done_when: str | None = None,
               people: list | None = None, check_every_days: int | None = None, stages: list | None = None,
               stage: str | None = None, waiting_on: str | None = None, due: str | None = None) -> Objective:
        """Change what the objective is: only what is passed changes, and an empty string clears
        a text or a date. `stages` is the whole list in its new order. With `stage`, `due` and
        `waiting_on` are that stage's and nothing moves (moving is `move_stage`)."""
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
            added = self._add_task(o, who=who, text=text, due=due)
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
            o.items.append({"id": _new_id("w"), "text": _clean(text), "state": "proposed", "needs_owner": bool(needs_owner),
                            "evidence": None, "history": [{"state": "proposed", "at": _now(), "by": by}]})
            self._event(o, "proposed", f"{text}{' (needs your approval)' if needs_owner else ''}", by)
        return self._change(objective_id, fn, by=by)

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
