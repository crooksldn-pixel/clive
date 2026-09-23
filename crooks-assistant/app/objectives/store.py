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
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass, field
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
_ID = re.compile(r"^obj_[0-9a-f]{8}$")
MAX_TEXT = 2000


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


@dataclass
class Objective:
    id: str
    title: str
    request: str
    created_at: str
    updated_at: str
    status: str = "active"
    deadline: str | None = None
    facts: list[dict] = field(default_factory=list)
    unknowns: list[dict] = field(default_factory=list)
    blockers: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    attention: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    # ---- views ------------------------------------------------------------
    def open_(self, key: str) -> list[dict]:
        return [x for x in getattr(self, key) if not x.get("resolved_at")]

    def summary(self) -> dict[str, Any]:
        """What the home screen and the model's list need: short, current, no history."""
        items = [i for i in self.items if i["state"] not in ("completed", "verified")]
        now_doing = next((i["text"] for i in items if i["state"] == "started"), None)
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "deadline": self.deadline,
            "days_left": _days_left(self.deadline),
            "doing": now_doing,
            "next": [i["text"] for i in items if i["state"] in ("proposed", "authorised")][:3],
            "blocked_by": [b["text"] for b in self.open_("blockers")][:3],
            "needs_you": [a["text"] for a in self.open_("attention")],
            "unknowns": len(self.open_("unknowns")),
            "facts": len(self.facts),
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        return Objective(**json.loads(path.read_text(encoding="utf-8")))

    def all(self) -> list[Objective]:
        if not self.root.exists():
            return []
        out = []
        for path in sorted(self.root.glob("obj_*.json")):
            try:
                out.append(Objective(**json.loads(path.read_text(encoding="utf-8"))))
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
    def create(self, *, title: str, request: str, deadline: str | None = None, by: str = "clive") -> Objective:
        if deadline:
            try:
                deadline = date.fromisoformat(str(deadline)).isoformat()
            except ValueError as exc:
                raise ObjectiveError(f"The deadline {deadline!r} is not a date (YYYY-MM-DD).") from exc
        now = _now()
        obj = Objective(id=_new_id("obj"), title=_clean(title, limit=120, what="title"),
                        request=_clean(request, limit=4000, what="request"), created_at=now, updated_at=now,
                        deadline=deadline or None)
        self._event(obj, "created", "Objective recorded from the owner's request.", by)
        with self._lock:
            self._write(obj)
        return obj

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

    def add_blocker(self, objective_id: str, text: str, *, kind: str, by: str = "clive") -> Objective:
        if kind not in BLOCKER_KINDS:
            raise ObjectiveError(f"A blocker is one of {', '.join(BLOCKER_KINDS)}.")
        def fn(o):
            o.blockers.append({"id": _new_id("b"), "text": _clean(text), "kind": kind, "at": _now(), "resolved_at": None})
            if o.status == "active":
                o.status = "blocked" if kind != "needs_owner" else "waiting"
            self._event(o, "blocker", f"{kind}: {text}", by)
        return self._change(objective_id, fn, by=by)

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
        if status == "done" and by != "owner":
            # CLIVE can say everything is complete; closing the owner's objective is the owner's call.
            raise ObjectiveError("Only the owner closes an objective; ask them whether it is done.")
        def fn(o):
            o.status = status
            self._event(o, "status", f"{status}{' — ' + note if note else ''}", by)
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
