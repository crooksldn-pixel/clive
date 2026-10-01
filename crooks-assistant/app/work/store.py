"""Jobs, their claims and their record, kept on this machine.

One JSON file per job (work/items/<id>.json), routines in work/routines.json, and every step in
work/record.jsonl (append-only). All 0600, written atomically. The ladder:

    open -> claimed -> done          (or cancelled, by the owner)

* Anyone on the team may claim an open job meant for them or for anyone; the owner may claim any.
* Only who claimed a job (or the owner) may release it, mark it packed or finish it.
* A finished job keeps what proves it: packed, the counts, a note, the change that closed it.
* The owner hands jobs out and sets routines; the team takes and finishes them, and anyone may flag
  a job for the owner.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

KINDS = ("job", "pack_order", "reply_email", "reply_instagram", "stock_count")
SOURCES = ("assigned", "routine", "found")
STATUSES = ("open", "claimed", "done", "cancelled")
CADENCES = ("daily", "weekdays", "mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_TEXT = 500
MAX_COUNTS = 200
MAX_ROUTINES = 40
# A finished or cancelled job leaves the live folder this long after it ended (for items/archive/
# <yyyy-mm>/), so what every phone reads each minute stays the size of the work in hand.
ARCHIVE_AFTER_DAYS = 14
# The screen reads the record's latest lines only; a question about further back reads it all.
TAIL_BYTES = 1_000_000
REF = re.compile(r"^(order|email|instagram|comment):[A-Za-z0-9_:/.=-]{1,200}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A job or routine the owner's assistant made, rather than the owner with his own taps: text it read
# in an email or a DM may have steered it, so the team can tell the two apart.
VIA_CLIVE = "clive"


class WorkError(ValueError):
    """A step that cannot be taken, with a reason fit to show the person."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def as_day(text: str) -> str:
    """A day as YYYY-MM-DD, or refused in words."""
    day = str(text or "").strip()
    try:
        if DAY.fullmatch(day):
            return date.fromisoformat(day).isoformat()
    except ValueError:
        pass
    raise WorkError("say the day as a date, like 2026-10-01")


def _clip(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


@dataclass
class WorkItem:
    item_id: str
    title: str
    kind: str = "job"
    source: str = "assigned"
    ref: str = ""                  # what a found job is about: "order:<id>", "email:<thread>", "instagram:<conversation>"
    details: str = ""
    assignee: str = ""             # a person's id, or "" for whoever is free
    due: str = ""                  # YYYY-MM-DD, or "" for whenever
    status: str = "open"
    claimed_by: str = ""
    claimed_at: str = ""
    done_by: str = ""
    done_at: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    routine_id: str = ""
    created_by: str = ""
    created_via: str = ""          # VIA_CLIVE when the owner's assistant made it
    created_at: str = field(default_factory=now)
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> dict[str, Any]:
        out = {k: v for k, v in self.to_dict().items() if k != "events"}
        out["last"] = self.events[-1] if self.events else None
        return out


@dataclass
class Routine:
    routine_id: str
    title: str
    cadence: str = "daily"
    details: str = ""
    assignee: str = ""
    kind: str = "job"
    active: bool = True
    created_by: str = ""
    created_via: str = ""
    created_at: str = field(default_factory=now)

    def due_on(self, day: date) -> bool:
        if not self.active:
            return False
        if self.cadence == "daily":
            return True
        if self.cadence == "weekdays":
            return day.weekday() < 5
        return WEEKDAYS[day.weekday()] == self.cadence


class WorkStore:
    def __init__(self, folder: Path | None = None) -> None:
        self._folder = Path(folder) if folder else None
        self._lock = threading.RLock()
        self._archived_on = ""

    def configure(self, folder: Path | None) -> None:
        with self._lock:
            self._folder = Path(folder) if folder else None
            self._archived_on = ""

    # ------------------------------------------------------------------ files

    def _root(self) -> Path:
        if self._folder is None:
            raise WorkError("the work list is not set up on this server")
        (self._folder / "items").mkdir(parents=True, exist_ok=True)
        return self._folder

    def _write(self, path: Path, text: str) -> None:
        handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        temporary_path = Path(temporary)
        try:
            os.fchmod(handle, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    def _item_path(self, item_id: str) -> Path:
        if not re.fullmatch(r"w_[0-9a-z_]{4,40}", str(item_id or "")):
            raise WorkError("there is no such job")
        return self._root() / "items" / f"{item_id}.json"

    def _save(self, item: WorkItem) -> None:
        self._write(self._item_path(item.item_id), json.dumps(item.to_dict(), ensure_ascii=False, indent=1))

    def _load(self, path: Path) -> WorkItem | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        known = {k: v for k, v in data.items() if k in WorkItem.__dataclass_fields__} if isinstance(data, dict) else {}
        try:
            return WorkItem(**known)
        except TypeError:
            return None

    def record(self, entry: dict[str, Any]) -> None:
        """One line in the record: who did what to which job, never a message or a key."""
        path = self._root() / "record.jsonl"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": now(), **entry}, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ reads

    def get(self, item_id: str) -> WorkItem | None:
        with self._lock:
            path = self._item_path(item_id)
            return self._load(path) if path.exists() else None

    def items(self) -> list[WorkItem]:
        with self._lock:
            folder = self._root() / "items"
            found = [self._load(p) for p in sorted(folder.glob("w_*.json"))]
        return [i for i in found if i is not None]

    def archived(self, since: str = "") -> list[WorkItem]:
        """The jobs put away under items/archive/<yyyy-mm>/, from the month of `since` (YYYY-MM-DD)
        on: a job ends no earlier than the day it is asked about. Read only; nothing is moved."""
        with self._lock:
            folder = self._root() / "items" / "archive"
            months = sorted(p for p in folder.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]") if p.is_dir()
                            and p.name >= since[:7]) if folder.is_dir() else []
            found = [self._load(p) for month in months for p in sorted(month.glob("w_*.json"))]
        return [i for i in found if i is not None]

    def by_ref(self, ref: str) -> list[WorkItem]:
        return [i for i in self.items() if i.ref == ref]

    def history(self, *, who: str = "", ref: str = "", day: str = "", limit: int = 50,
                everything: bool = False) -> list[dict[str, Any]]:
        """The record, newest first: by person, by what it was about, by day. From its latest lines
        (the last TAIL_BYTES), or from the start when `everything`."""
        with self._lock:
            path = self._root() / "record.jsonl"
            try:
                lines = _read_lines(path, everything=everything)
            except FileNotFoundError:
                return []
        out: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            if who and entry.get("who") != who:
                continue
            if ref and not _about(entry, ref):
                continue
            if day and not str(entry.get("at") or "").startswith(day):
                continue
            out.append(entry)
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------ routines

    def routines(self) -> list[Routine]:
        with self._lock:
            path = self._root() / "routines.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                return []
        out = []
        for item in (data.get("routines") if isinstance(data, dict) else None) or []:
            known = {k: v for k, v in item.items() if k in Routine.__dataclass_fields__} if isinstance(item, dict) else {}
            try:
                out.append(Routine(**known))
            except TypeError:
                continue
        return out

    def add_routine(self, *, title: str, cadence: str, details: str = "", assignee: str = "", kind: str = "job",
                    by: str = "", via: str = "") -> Routine:
        cadence = str(cadence or "").strip().lower()
        if cadence[:3] in WEEKDAYS:          # "monday", "Mondays" -> "mon"
            cadence = cadence[:3]
        if cadence not in CADENCES:
            raise WorkError("a routine is daily, weekdays, or one day of the week (mon to sun)")
        if not _clip(title, 120):
            raise WorkError("say what the routine is")
        with self._lock:
            routines = self.routines()
            if len([r for r in routines if r.active]) >= MAX_ROUTINES:
                raise WorkError(f"there are already {MAX_ROUTINES} routines; stop one first")
            routine = Routine(routine_id="r_" + secrets.token_hex(4), title=_clip(title, 120), cadence=cadence,
                              details=_clip(details), assignee=assignee, kind=kind if kind in KINDS else "job", created_by=by,
                              created_via=via)
            routines.append(routine)
            self._write(self._root() / "routines.json",
                        json.dumps({"routines": [asdict(r) for r in routines]}, ensure_ascii=False, indent=1))
        self.record({"who": by, "what": "routine_set", "item_id": routine.routine_id, "detail": f"{routine.title} ({cadence})",
                     **({"via": via} if via else {})})
        return routine

    def stop_routine(self, routine_id: str, *, by: str = "") -> bool:
        with self._lock:
            routines = self.routines()
            hit = next((r for r in routines if r.routine_id == routine_id and r.active), None)
            if hit is None:
                return False
            hit.active = False
            self._write(self._root() / "routines.json",
                        json.dumps({"routines": [asdict(r) for r in routines]}, ensure_ascii=False, indent=1))
        self.record({"who": by, "what": "routine_stopped", "item_id": routine_id, "detail": hit.title})
        return True

    def materialise(self, day: str | None = None) -> list[WorkItem]:
        """Make the day's copy of every routine due that day, once. Idempotent. The first time on a
        new day, finished jobs from more than ARCHIVE_AFTER_DAYS ago are put away first. Only ever
        asked for today (view.py): a question about another day reads and writes nothing."""
        day = day or today()
        when = date.fromisoformat(day)
        made = []
        with self._lock:
            if self._archived_on != day:
                self.archive(day)
                self._archived_on = day
            existing = {(i.routine_id, i.due) for i in self.items() if i.routine_id}
            for routine in self.routines():
                if routine.due_on(when) and (routine.routine_id, day) not in existing:
                    item = self._new(title=routine.title, kind=routine.kind, source="routine", details=routine.details,
                                     assignee=routine.assignee, due=day, by=routine.created_by or "routine",
                                     routine_id=routine.routine_id, via=routine.created_via)
                    made.append(item)
        return made

    def archive(self, day: str | None = None) -> int:
        """Move finished and cancelled jobs that ended more than ARCHIVE_AFTER_DAYS before `day` to
        items/archive/<yyyy-mm>/. Their lines in the record stay where they are."""
        cutoff = (date.fromisoformat(day or today()) - timedelta(days=ARCHIVE_AFTER_DAYS)).isoformat()
        moved = 0
        with self._lock:
            folder = self._root() / "items"
            for item in self.items():
                if item.status not in ("done", "cancelled"):
                    continue
                ended = (item.done_at or (item.events[-1].get("at") if item.events else "") or item.created_at)[:10]
                if not ended or ended >= cutoff:
                    continue
                target = folder / "archive" / ended[:7]
                target.mkdir(parents=True, exist_ok=True)
                (folder / f"{item.item_id}.json").replace(target / f"{item.item_id}.json")
                moved += 1
        return moved

    # ------------------------------------------------------------------ the ladder

    def _new(self, *, title: str, kind: str = "job", source: str = "assigned", ref: str = "", details: str = "",
             assignee: str = "", due: str = "", by: str = "", routine_id: str = "", via: str = "",
             what: str = "created") -> WorkItem:
        if kind not in KINDS:
            raise WorkError("that is not a kind of job CLIVE keeps")
        if ref and not REF.fullmatch(ref):
            raise WorkError("that job's reference is malformed")
        if due:
            try:
                date.fromisoformat(due)
            except ValueError:
                raise WorkError("a date is YYYY-MM-DD") from None
        item = WorkItem(item_id=f"w_{datetime.now(UTC):%y%m%d}_{secrets.token_hex(4)}", title=_clip(title, 160) or "A job",
                        kind=kind, source=source, ref=ref, details=_clip(details), assignee=assignee, due=due,
                        created_by=by, created_via=via, routine_id=routine_id)
        item.events.append({"at": item.created_at, "who": by, "what": what})
        self._save(item)
        self.record({"who": by, "what": what, "item_id": item.item_id, "ref": ref, "detail": item.title,
                     "assignee": assignee, **({"via": via} if via else {})})
        return item

    def assign(self, *, title: str, details: str = "", assignee: str = "", due: str = "", kind: str = "job",
               by: str = "", via: str = "") -> WorkItem:
        with self._lock:
            return self._new(title=title, kind=kind, source="assigned", details=details, assignee=assignee, due=due, by=by,
                             via=via)

    def flag(self, *, title: str, details: str = "", ref: str = "", by: str, via: str = "") -> WorkItem:
        """Something for the owner to do, noted by anyone: an open job assigned to him."""
        if not _clip(title, 160):
            raise WorkError("say what the owner needs to do")
        with self._lock:
            return self._new(title=title, source="assigned", ref=ref, details=details, assignee="owner", by=by, via=via,
                             what="flagged")

    def claim(self, item_id: str, *, who: str, owner: bool = False) -> WorkItem:
        with self._lock:
            item = self._must(item_id)
            if item.status == "claimed" and item.claimed_by == who:
                return item
            if item.status != "open":
                raise WorkError(f"that job is {item.status}" + (f" by {item.claimed_by}" if item.claimed_by else ""))
            if item.assignee and item.assignee != who and not owner:
                raise WorkError("that job is someone else's")
            return self._step(item, who, "claimed", status="claimed", claimed_by=who, claimed_at=now())

    def claim_found(self, *, ref: str, kind: str, title: str, details: str, who: str) -> WorkItem:
        """Claim something CLIVE found: kept from now on, with this person's name on it. Two people
        tapping at once: the second is told who has it."""
        with self._lock:
            kept = self.by_ref(ref)
            for item in kept:
                if item.status == "claimed":
                    if item.claimed_by == who:
                        return item
                    raise WorkError(f"{item.claimed_by} has already claimed that")
            # Given back earlier: the same job is taken again, so its story stays in one place.
            item = next((i for i in kept if i.status == "open"), None)
            if item is None:
                item = self._new(title=title, kind=kind, source="found", ref=ref, details=details, by=who)
            return self._step(item, who, "claimed", status="claimed", claimed_by=who, claimed_at=now())

    def release(self, item_id: str, *, who: str, owner: bool = False) -> WorkItem:
        with self._lock:
            item = self._held(item_id, who, owner)
            return self._step(item, who, "released", status="open", claimed_by="", claimed_at="")

    def packed(self, item_id: str, *, who: str, owner: bool = False) -> WorkItem:
        with self._lock:
            item = self._held(item_id, who, owner)
            if item.kind != "pack_order":
                raise WorkError("only an order is packed")
            item.evidence = {**item.evidence, "packed": True, "packed_by": who, "packed_at": now()}
            return self._step(item, who, "packed")

    def counted(self, item_id: str, counts: list[dict[str, Any]], *, who: str, owner: bool = False) -> WorkItem:
        with self._lock:
            item = self._held(item_id, who, owner)
            if item.kind != "stock_count":
                raise WorkError("counts belong to a stock count")
            clean = []
            for row in counts or []:
                if not isinstance(row, dict):
                    continue
                label = _clip(row.get("item") or row.get("sku") or row.get("label"), 120)
                try:
                    number = int(row.get("counted"))
                except (TypeError, ValueError):
                    raise WorkError(f"{label or 'a line'}: a count is a whole number") from None
                if number < 0 or number > 100_000:
                    raise WorkError(f"{label or 'a line'}: that count is out of range")
                clean.append({"item": label, "sku": _clip(row.get("sku"), 64), "variant_id": _clip(row.get("variant_id"), 120),
                              "counted": number})
            if not clean:
                raise WorkError("enter at least one count")
            if len(clean) > MAX_COUNTS:
                raise WorkError(f"a count holds at most {MAX_COUNTS} lines")
            item.evidence = {**item.evidence, "counts": clean, "counted_by": who, "counted_at": now()}
            return self._step(item, who, "counted", detail=f"{len(clean)} line{'s' if len(clean) != 1 else ''}")

    def done(self, item_id: str, *, who: str, note: str = "", owner: bool = False, evidence: dict | None = None) -> WorkItem:
        with self._lock:
            item = self._held(item_id, who, owner, allow_open=owner)
            if item.kind == "stock_count" and not item.evidence.get("counts") and not owner:
                raise WorkError("enter the counts first")
            merged = {**item.evidence, **(evidence or {})}
            if note:
                merged["note"] = _clip(note)
            item.evidence = merged
            return self._step(item, who, "done", status="done", done_by=who, done_at=now(), detail=_clip(note, 120))

    def cancel(self, item_id: str, *, by: str) -> WorkItem:
        with self._lock:
            item = self._must(item_id)
            if item.status in ("done", "cancelled"):
                raise WorkError(f"that job is already {item.status}")
            return self._step(item, by, "cancelled", status="cancelled")

    # ------------------------------------------------------------------ helpers

    def _must(self, item_id: str) -> WorkItem:
        item = self.get(item_id)
        if item is None:
            raise WorkError("there is no such job")
        return item

    def _held(self, item_id: str, who: str, owner: bool, *, allow_open: bool = False) -> WorkItem:
        item = self._must(item_id)
        if item.status in ("done", "cancelled"):
            raise WorkError(f"that job is already {item.status}")
        if item.status == "open" and not allow_open:
            raise WorkError("claim it first")
        if item.status == "claimed" and item.claimed_by != who and not owner:
            raise WorkError(f"{item.claimed_by} has that job")
        return item

    def _step(self, item: WorkItem, who: str, what: str, *, detail: str = "", **changes: Any) -> WorkItem:
        for key, value in changes.items():
            setattr(item, key, value)
        event = {"at": now(), "who": who, "what": what}
        if detail:
            event["detail"] = detail
        item.events.append(event)
        item.events = item.events[-60:]
        self._save(item)
        self.record({"who": who, "what": what, "item_id": item.item_id, "ref": item.ref, "detail": item.title,
                     **({"note": detail} if detail else {})})
        return item


def _read_lines(path: Path, *, everything: bool) -> list[str]:
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        if everything or size <= TAIL_BYTES:
            stream.seek(0)
        else:
            stream.seek(size - TAIL_BYTES)
            stream.readline()                       # the first line read is only part of one
        return stream.read().decode("utf-8", "replace").splitlines()


def _about(entry: dict[str, Any], ref: str) -> bool:
    """Whether a record line is about this: its reference or job id exactly, or an order by its
    number ("#1930", "1930"), which the line names in its words rather than its reference."""
    if ref in (entry.get("ref") or "", entry.get("item_id") or ""):
        return True
    number = re.fullmatch(r"#?(\d{3,10})", ref.strip())
    return bool(number) and re.search(rf"(?<!\d){number.group(1)}(?!\d)", str(entry.get("detail") or "")) is not None


def due_on_or_before(item: WorkItem, day: str) -> bool:
    return not item.due or item.due <= day


def day_after(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


work = WorkStore()
