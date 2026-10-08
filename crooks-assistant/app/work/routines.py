"""Named routines: saved steps a person starts by name (George's ruling 31, 8 October 2026; DEC-074).

"Save this as my Friday drop routine" keeps the steps CLIVE just took, or the steps he gives it one
by one, under a name he chose; "run my Friday drop routine" carries them out again. Not the work
list's repeating jobs (store.py `Routine`: "tidy the desks" every day, made into a job each day):
those come back on a calendar for the team, these come back only when somebody names them.

What a routine is, and what it promises:
* a name, and up to MAX_STEPS steps. A step is one tool CLIVE has, the arguments it is called
  with, and what it does in the person's own words (`say`). A step is a read or a change; which,
  is read from the registry when the step is saved, never taken from what the model said.
* a routine is its maker's: the owner's are his, a member of the team's are theirs. Nobody lists,
  runs or edits anyone else's (`who` is the authority's, app/work/routine_tools.py).
* no record's id is kept. A step's arguments are what to look for and how ("orders from the last
  seven days", "tag friday-drop"); the record a change is made to is looked up again each run, as
  it would be if he asked for it in words (routine_tools.py drops issued-id arguments on saving).
* running one changes nothing by itself: every step goes through the gate as the model's own call,
  and a change is only ever staged as a card waiting for his gesture (app/tools/gate.py has no path
  from a tool call to a mutation).

Kept beside the work list (the same folder, the same private atomic write and the same lock as
store.py): work/named-routines.json, 0600, written whole and read back after every change so a
change is proved, never assumed. Nothing here sends, stages or reads anything outside this file.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from typing import Any

from app.work.store import WorkError, WorkStore, now, work

FILE = "named-routines.json"
MAX_STEPS = 8            # a routine runs in one turn, inside the model's own turn limit and the read budget
MAX_EACH = 30            # routines one person keeps
MAX_ALL = 300            # routines this machine keeps, everyone's together
MAX_NAME = 60
MAX_SAY = 160
MAX_ARGS_CHARS = 1_000   # a step's arguments, as JSON
KINDS = ("read", "change")
_ID = re.compile(r"^nr_[0-9a-f]{8}$")
_WHO = re.compile(r"^[A-Za-z0-9_.@:-]{1,80}$")
# Words around a name that are not the name: "my Friday drop routine" is "Friday drop".
_AROUND = re.compile(r"^(?:(?:my|our|the|a)\s+)+|(?:^|\s+)routine$", re.I)


class RoutineError(WorkError):
    """A routine that cannot be saved, found or changed, with a reason fit to say to the person."""


@dataclass
class Step:
    tool: str
    say: str
    args: dict[str, Any] = field(default_factory=dict)
    kind: str = "read"

    def public(self) -> dict[str, Any]:
        return {"tool": self.tool, "say": self.say, "args": dict(self.args), "kind": self.kind}


@dataclass
class NamedRoutine:
    routine_id: str
    name: str
    who: str
    steps: list[Step] = field(default_factory=list)
    created_at: str = field(default_factory=now)
    created_via: str = ""
    changed_at: str = ""
    last_ran_at: str = ""
    runs: int = 0

    @property
    def key(self) -> str:
        return key_of(self.name)

    def public(self) -> dict[str, Any]:
        return {"routine_id": self.routine_id, "name": self.name, "steps": [s.public() for s in self.steps],
                "changes": sum(1 for s in self.steps if s.kind == "change"), "created_at": self.created_at,
                "changed_at": self.changed_at, "last_ran_at": self.last_ran_at, "runs": self.runs}


def clean_name(text: Any) -> str:
    """The name as it is kept: one line, without "my" in front or "routine" after it."""
    name = " ".join(str(text or "").split())
    for _ in range(3):
        stripped = _AROUND.sub("", name).strip()
        if stripped == name:
            break
        name = stripped
    if not name:
        raise RoutineError("say what the routine is called")
    if len(name) > MAX_NAME:
        raise RoutineError(f"a routine's name is at most {MAX_NAME} characters")
    return name


def key_of(text: Any) -> str:
    """How a name is matched: its letters and digits, lower case, so "Friday-drop" is "friday drop"."""
    try:
        name = clean_name(text)
    except RoutineError:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def clean_say(text: Any) -> str:
    said = " ".join(str(text or "").split())
    if not said:
        raise RoutineError("say what each step does, in a few words")
    if len(said) > MAX_SAY:
        raise RoutineError(f"a step's words are at most {MAX_SAY} characters")
    return said


def _step_from(data: Any) -> Step | None:
    if not isinstance(data, dict):
        return None
    args = data.get("args") if isinstance(data.get("args"), dict) else {}
    kind = str(data.get("kind") or "read")
    tool = str(data.get("tool") or "")
    if not tool or kind not in KINDS:
        return None
    return Step(tool=tool, say=str(data.get("say") or ""), args=args, kind=kind)


def _routine_from(data: Any) -> NamedRoutine | None:
    if not isinstance(data, dict) or not _ID.fullmatch(str(data.get("routine_id") or "")):
        return None
    steps = [s for s in (_step_from(d) for d in data.get("steps") or []) if s is not None]
    known = {k: v for k, v in data.items() if k in NamedRoutine.__dataclass_fields__ and k != "steps"}
    try:
        return NamedRoutine(**known, steps=steps)
    except TypeError:
        return None


class RoutineBook:
    """Everyone's named routines, in one private file beside the work list."""

    def __init__(self, store: WorkStore) -> None:
        self._store = store

    # ------------------------------------------------------------------ the file

    def _path(self):
        return self._store._root() / FILE

    def _all(self) -> list[NamedRoutine]:
        try:
            data = json.loads(self._path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            # Unknown is RED: a file that cannot be read is said, never read as "no routines",
            # which the next save would then write over.
            raise RoutineError("the saved routines could not be read on this server") from exc
        items = data.get("routines") if isinstance(data, dict) else None
        return [r for r in (_routine_from(d) for d in items or []) if r is not None]

    def _keep(self, routines: list[NamedRoutine]) -> None:
        body = {"routines": [asdict(r) for r in routines]}
        self._store._write(self._path(), json.dumps(body, ensure_ascii=False, indent=1))

    # ------------------------------------------------------------------ reads

    def of(self, who: str) -> list[NamedRoutine]:
        """This person's routines, in the order they were made."""
        who = _who(who)
        with self._store._lock:
            return [r for r in self._all() if r.who == who]

    def find(self, who: str, name: str) -> NamedRoutine:
        """This person's routine by its name: the same name, or the one name that holds every word
        asked for ("friday" for "Friday drop"). Two that could be meant are named, never chosen."""
        wanted = key_of(name)
        mine = self.of(who)
        if not wanted:
            raise RoutineError("say which routine")
        exact = [r for r in mine if r.key == wanted]
        if exact:
            return exact[0]
        words = set(wanted.split())
        near = [r for r in mine if words <= set(r.key.split()) or set(r.key.split()) <= words]
        if len(near) == 1:
            return near[0]
        if near:
            raise RoutineError("that could be " + _either(near) + "; say which")
        if not mine:
            raise RoutineError("there are no routines saved yet")
        raise RoutineError(f"there is no routine called {clean_name(name)[:40]}; the saved ones are " + _either(mine, "and"))

    # ------------------------------------------------------------------ changes, each read back

    def save(self, who: str, name: str, steps: list[Step], *, via: str = "") -> NamedRoutine:
        who, name = _who(who), clean_name(name)
        _check_steps(steps)
        with self._store._lock:
            everyone = self._all()
            mine = [r for r in everyone if r.who == who]
            if any(r.key == key_of(name) for r in mine):
                raise RoutineError(f"there is already a routine called {name}; change its steps, or forget it first")
            if len(mine) >= MAX_EACH:
                raise RoutineError(f"there are already {MAX_EACH} routines saved; forget one first")
            if len(everyone) >= MAX_ALL:
                raise RoutineError("this server keeps no more routines; forget one first")
            made = NamedRoutine(routine_id="nr_" + secrets.token_hex(4), name=name, who=who, steps=list(steps),
                                created_via=via)
            self._keep(everyone + [made])
            return self._proved(who, made)

    def change(self, who: str, name: str, *, steps: list[Step] | None = None, new_name: str = "") -> NamedRoutine:
        """New steps (all of them, in order), a new name, or both, for one of this person's routines."""
        who = _who(who)
        with self._store._lock:
            target = self.find(who, name)
            everyone = self._all()
            routine = next(r for r in everyone if r.routine_id == target.routine_id)
            if new_name:
                renamed = clean_name(new_name)
                clash = next((r for r in everyone if r.who == who and r.key == key_of(renamed)
                              and r.routine_id != routine.routine_id), None)
                if clash is not None:
                    raise RoutineError(f"there is already a routine called {clash.name}")
                routine.name = renamed
            if steps is not None:
                _check_steps(steps)
                routine.steps = list(steps)
            routine.changed_at = now()
            self._keep(everyone)
            return self._proved(who, routine)

    def forget(self, who: str, name: str) -> NamedRoutine:
        """Delete one of this person's routines. Returns it as it was, so it can be saved again."""
        who = _who(who)
        with self._store._lock:
            target = self.find(who, name)
            everyone = self._all()
            self._keep([r for r in everyone if r.routine_id != target.routine_id])
            if any(r.routine_id == target.routine_id for r in self._all()):
                raise RoutineError(f"{target.name} could not be forgotten on this server")
            return target

    def ran(self, who: str, routine_id: str) -> None:
        """Note that a routine was started: when, and how many times. Never raises: a run is not
        undone because its count could not be kept."""
        try:
            with self._store._lock:
                everyone = self._all()
                for routine in everyone:
                    if routine.routine_id == routine_id and routine.who == _who(who):
                        routine.last_ran_at = now()
                        routine.runs += 1
                        self._keep(everyone)
                        return
        except (OSError, WorkError):
            return

    def _proved(self, who: str, routine: NamedRoutine) -> NamedRoutine:
        """The routine as the file now holds it, or an error: a change is proved by reading it back."""
        kept = next((r for r in self._all() if r.routine_id == routine.routine_id and r.who == who), None)
        if kept is None or asdict(kept) != asdict(routine):
            raise RoutineError(f"{routine.name} could not be saved on this server")
        return kept


def _who(who: str) -> str:
    who = str(who or "")
    if not _WHO.fullmatch(who):
        raise RoutineError("nobody is asking")
    return who


def _check_steps(steps: list[Step]) -> None:
    if len(steps) > MAX_STEPS:
        raise RoutineError(f"a routine has at most {MAX_STEPS} steps")
    for step in steps:
        if step.kind not in KINDS or not step.tool:
            raise RoutineError("a step is one of CLIVE's tools and what it does")
        clean_say(step.say)
        if len(json.dumps(step.args, ensure_ascii=False, default=str)) > MAX_ARGS_CHARS:
            raise RoutineError(f"a step's details are at most {MAX_ARGS_CHARS} characters")


def _either(routines: list[NamedRoutine], word: str = "or") -> str:
    names = [r.name for r in routines[:6]]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" {word} " + names[-1]


book = RoutineBook(work)
