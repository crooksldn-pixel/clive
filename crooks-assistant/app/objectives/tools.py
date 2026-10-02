"""The model's hands on objectives. Four tools, every one of them local to CLIVE.

They read and change only CLIVE's own objective records (app/objectives/store.py): no Shopify,
no Gmail, no booking, no payment, no message leaves this machine through them. That is why they
sit on the gate's read allow-list beside the composer's tools, which likewise change only the
Mac's own copy of something (app/tools/gate.py). What they cannot do is the owner's: authorise a
work item, or set an objective done or dropped as the owner. The store refuses both unless the
owner's own screen asks.

What they can do, when the owner says so, is close an objective out (objective_note `complete`
or `remove`, with his words): it leaves objective_list's live list and nothing on it is deleted.
objective_show still reads it whole by its id, and objective_list with `closed` lists the closed
ones, `search` finding one by anything in its record. They were paid for in the tool block's
budget (tests/test_registry.py) by offering nothing the store always refuses — status `dropped`
(`remove` drops one now) and state `proposed` (no item advances to it) — and saying "he" for
"the owner" where the sentence already names him.

Round 12 gave an objective a shape (the store's docstring): objective_open takes the kind and
its design, and objective_note's `set`, `stage`, `task` and `drop` change it, so everything the
owner said when he opened it stays editable by voice. The new actions ride on the existing tool
rather than a fifth one, which would need its own place on the gate's allow-list; the rules for
choosing a kind are in the system prompt once (app/kb/loader.py). Each call that opens, shows or
changes one objective returns its card for the tablet under `_surfaces` (app/objectives/cards.py),
which the model never reads (app/tools/dispatch.py `_render`).

A number to reach (objectives by touch, part C) rides the same way: `number` on objective_open, and
on objective_note's `set`, where only the parts passed change and `{}` takes it off. These tools
record what he said and read nothing from the shop; what has sold is counted on the owner's screen
(app/objectives/count.py through app/routes/objectives.py), and the model asks the sales tools.
"""

from __future__ import annotations

from typing import Any

from app.objectives import cards
from app.objectives.store import (
    BLOCKER_KINDS,
    KINDS,
    LADDER,
    MAX_PEOPLE,
    MAX_STAGES,
    MAX_TASKS,
    ObjectiveError,
    store,
)
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

_ACTIONS = ("fact", "unknown", "blocker", "ask_owner", "propose", "advance", "progress", "resolve", "status",
            "set", "stage", "task", "drop", "complete", "remove")
# Closing an objective out, action by action, as the store names how it ended.
_CLOSING = {"complete": "complete", "remove": "removed"}
# The kinds the model chooses from, in the order the prompt explains them.
_KIND_CHOICE = ["project", "tasks", "business", "build"]
assert set(_KIND_CHOICE) == set(KINDS)
_DATE = {"type": "string", "description": "YYYY-MM-DD"}
_NAMES = {"type": "array", "items": {"type": "string"}}
# The store's own limits, said to the model. They are not where the limits are kept: these tools
# are reads to the gate, so nothing checks a schema bound on them, and the store refuses a list
# past its limit whole rather than cut it (round 13, S6-02).
_PEOPLE = {**_NAMES, "maxItems": MAX_PEOPLE}
_STAGES = {**_NAMES, "maxItems": MAX_STAGES}
# A number to reach: what is counted, in his words, its target, since when if he said, the unit.
# Its meaning is said once, in the system prompt (app/kb/loader.py), not here.
_NUMBER = {"type": "object", "properties": {"of": {"type": "string"}, "target": {"type": "integer"}, "since": _DATE,
                                            "unit": {"type": "string"}}}


def _short(obj) -> dict[str, Any]:
    return obj.summary()


def _full(obj) -> dict[str, Any]:
    data = obj.to_dict()
    data["events"] = data["events"][-15:]  # the recent history is what a turn needs; the store keeps it all
    data["summary"] = obj.summary()
    data["_surfaces"] = [cards.surface(obj)]
    return data


@tool(
    name="objective_open",
    description=(
        "Open a real-world objective he wants kept alive, in his words, shaped by its kind. "
        "Only when objective_list has nothing covering it. Then ask exactly what `ask` says."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "request": {"type": "string"},
            "kind": {"type": "string", "enum": _KIND_CHOICE},
            "deadline": _DATE,
            "purpose": {"type": "string"},
            "done_when": {"type": "string"},
            "people": {**_PEOPLE, "description": "Name (role)"},
            "check_every_days": {"type": "integer"},
            "stages": {**_STAGES, "description": "project: in order"},
            "stage": {"type": "string", "description": "where it is now"},
            "waiting_on": {"type": "string", "description": "who that stage waits on"},
            "tasks": {"type": "array", "maxItems": MAX_TASKS, "items": {"type": "object", "properties": {
                "who": {"type": "string"}, "text": {"type": "string"}, "due": _DATE}, "required": ["who", "text"]}},
            "number": _NUMBER,
        },
        "required": ["title", "request", "kind"],
    },
    tier=Tier.GREEN,
)
async def objective_open(title: str, request: str, kind: str = "business", deadline: str | None = None,
                         purpose: str = "", done_when: str = "", people: list | None = None,
                         check_every_days: int | None = None, stages: list | None = None, stage: str = "",
                         waiting_on: str = "", tasks: list | None = None, number: dict | None = None) -> dict:
    try:
        obj = store().create(title=title, request=request, deadline=deadline, kind=kind, purpose=purpose,
                             done_when=done_when, people=people, check_every_days=check_every_days,
                             stages=stages, stage=stage, waiting_on=waiting_on, tasks=tasks, number=number)
    except ObjectiveError as exc:
        raise ToolError(str(exc)) from exc
    return {**_full(obj), "missing": obj.missing(), "ask": obj.ask()}


@tool(
    name="objective_list",
    description=(
        "The owner's live objectives: doing, next, blocked by, needs the owner. Call it when he "
        "refers to something ongoing, and before opening one."
    ),
    input_schema={"type": "object", "properties": {
        "closed": {"type": "boolean"},
        "search": {"type": "string"},
    }},
    tier=Tier.GREEN,
)
async def objective_list(closed: bool = False, search: str = "") -> dict:
    s = store()
    if closed:
        return {"closed": True, "objectives": [_short(o) for o in s.closed(search)]}
    return {"objectives": [_short(o) for o in s.live() if o.mentions(search)]}


@tool(
    name="objective_show",
    description="One objective in full, live or closed.",
    input_schema={"type": "object", "properties": {"objective_id": {"type": "string"}}, "required": ["objective_id"]},
    tier=Tier.GREEN,
)
async def objective_show(objective_id: str) -> dict:
    try:
        return _full(store().get(objective_id))
    except ObjectiveError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    name="objective_note",
    description=(
        "Record on an objective. action: fact (source: 'owner', a URL, 'general knowledge, not "
        "verified live'…); unknown; blocker (kind; missing_capability when CLIVE has no tool for "
        "it); ask_owner (only he can answer); propose (needs_owner true for spending, "
        "booking, official applications, external messages); advance (item_id to started, "
        "completed, or verified with evidence; owner-needing items wait for his "
        "approval); progress; resolve (entry_id now settled); status; complete, remove (on his "
        "word, in text); and its design (see action). Never record a guess as a fact."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "objective_id": {"type": "string"},
            "action": {"type": "string", "enum": list(_ACTIONS), "description": (
                "set: change the design, only what you pass (stages: the whole list; with stage, its "
                "due or waiting_on). stage: the project is now at stage (a name or next). task: add "
                "(who, text, due), or change item_id (done true/false); only who and done: all theirs. "
                "drop: remove task item_id.")},
            "text": {"type": "string"},
            "source": {"type": "string"},
            "kind": {"type": "string", "enum": list(BLOCKER_KINDS) + _KIND_CHOICE,
                     "description": "a blocker's; with set, the objective's"},
            "capability": {"type": "string", "description": "What is missing, in a few words."},
            "needs_owner": {"type": "boolean"},
            "item_id": {"type": "string"},
            "state": {"type": "string", "enum": [s for s in LADDER if s not in ("proposed", "authorised")]},
            "evidence": {"type": "string"},
            "entry_id": {"type": "string"},
            "status": {"type": "string", "enum": ["active", "waiting", "blocked"]},
            "title": {"type": "string"},
            "deadline": {"type": "string"},
            "purpose": {"type": "string"},
            "done_when": {"type": "string"},
            "people": _PEOPLE,
            "check_every_days": {"type": "integer"},
            "stages": _STAGES,
            "stage": {"type": "string"},
            "waiting_on": {"type": "string"},
            "who": {"type": "string"},
            "due": {"type": "string"},
            "done": {"type": "boolean"},
            "number": _NUMBER,
        },
        "required": ["objective_id", "action"],
    },
    tier=Tier.GREEN,
)
async def objective_note(objective_id: str, action: str, text: str = "", source: str = "", kind: str = "",
                         needs_owner: bool = False, item_id: str = "", state: str = "", evidence: str = "",
                         entry_id: str = "", status: str = "", capability: str = "", title: str | None = None,
                         deadline: str | None = None, purpose: str | None = None, done_when: str | None = None,
                         people: list | None = None, check_every_days: int | None = None,
                         stages: list | None = None, stage: str | None = None, waiting_on: str | None = None,
                         who: str | None = None, due: str | None = None, done: bool | None = None,
                         number: dict | None = None) -> dict:
    s = store()
    try:
        if action == "set":
            obj = s.design(objective_id, title=title, kind=kind or None, deadline=deadline, purpose=purpose,
                           done_when=done_when, people=people, check_every_days=check_every_days,
                           stages=stages, stage=stage, waiting_on=waiting_on, due=due, number=number)
        elif action == "stage":
            obj = s.move_stage(objective_id, stage or text, waiting_on=waiting_on, due=due)
        elif action == "task":
            obj = s.task(objective_id, item_id=item_id, who=who, text=text or None, due=due, done=done)
        elif action == "drop":
            obj = s.drop_task(objective_id, item_id)
        elif action == "fact":
            obj = s.add_fact(objective_id, text, source=source or "unstated")
        elif action == "unknown":
            obj = s.add_unknown(objective_id, text)
        elif action == "blocker":
            obj = s.add_blocker(objective_id, text, kind=kind or "missing_info", capability=capability)
        elif action == "ask_owner":
            obj = s.ask_owner(objective_id, text)
        elif action == "propose":
            obj = s.propose(objective_id, text, needs_owner=needs_owner)
        elif action == "advance":
            obj = s.advance(objective_id, item_id, state, evidence=evidence)
        elif action == "progress":
            obj = s.progress(objective_id, text)
        elif action == "resolve":
            obj = s.resolve(objective_id, entry_id, note=text)
        elif action == "status":
            obj = s.set_status(objective_id, status, note=text)
        elif action in _CLOSING:
            obj = s.close(objective_id, _CLOSING[action], note=text)
        else:
            raise ObjectiveError(f"Unknown action {action!r}.")
    except ObjectiveError as exc:
        raise ToolError(str(exc)) from exc
    ids: dict[str, Any] = {"items": [(i["id"], i["text"][:60], i["state"]) for i in obj.items[-5:]],
                           "open": [(e["id"], e["text"][:60]) for k in ("unknowns", "blockers", "attention") for e in obj.open_(k)][-8:]}
    if obj.tasks:
        ids["tasks"] = [(t["id"], t["who"], t["text"][:60], "done" if t.get("done") else "open") for t in obj.tasks[-20:]]
    return {"recorded": action, "objective": _short(obj), "ids": ids, "_surfaces": [cards.surface(obj)]}
