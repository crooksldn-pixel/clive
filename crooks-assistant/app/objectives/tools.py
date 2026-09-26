"""The model's hands on objectives. Four tools, every one of them local to CLIVE.

They read and change only CLIVE's own objective records (app/objectives/store.py): no Shopify,
no Gmail, no booking, no payment, no message leaves this machine through them. That is why they
sit on the gate's read allow-list beside the composer's tools, which likewise change only the
Mac's own copy of something (app/tools/gate.py). What they cannot do is the owner's: authorise a
work item or close an objective. The store refuses both unless the owner's own screen asks.
"""

from __future__ import annotations

from typing import Any

from app.objectives.store import BLOCKER_KINDS, LADDER, ObjectiveError, store
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

_ACTIONS = ("fact", "unknown", "blocker", "ask_owner", "propose", "advance", "progress", "resolve", "status")


def _short(obj) -> dict[str, Any]:
    return obj.summary()


def _full(obj) -> dict[str, Any]:
    data = obj.to_dict()
    data["events"] = data["events"][-15:]  # the recent history is what a turn needs; the store keeps it all
    data["summary"] = obj.summary()
    return data


@tool(
    name="objective_open",
    description=(
        "Open a real-world objective the owner wants kept alive (steps, dependencies or a "
        "deadline), in the owner's words. Only when objective_list has nothing covering it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "request": {"type": "string"},
            "deadline": {"type": "string", "description": "YYYY-MM-DD"},
            "kind": {"type": "string", "enum": ["business", "build"], "description": "build: a change to CLIVE itself."},
        },
        "required": ["title", "request"],
    },
    tier=Tier.GREEN,
)
async def objective_open(title: str, request: str, deadline: str | None = None, kind: str = "business") -> dict:
    try:
        return _full(store().create(title=title, request=request, deadline=deadline, kind=kind))
    except ObjectiveError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    name="objective_list",
    description=(
        "The owner's live objectives: doing, next, blocked by, needs the owner. Call it when the "
        "owner refers to something ongoing, and before opening one."
    ),
    input_schema={"type": "object", "properties": {}},
    tier=Tier.GREEN,
)
async def objective_list() -> dict:
    return {"objectives": [_short(o) for o in store().live()]}


@tool(
    name="objective_show",
    description="One objective in full: facts and sources, unknowns, blockers, items, questions, history.",
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
        "it); ask_owner (only the owner can answer); propose (needs_owner true for spending, "
        "booking, official applications, external messages); advance (item_id to started, "
        "completed, or verified with evidence; owner-needing items wait for the owner's "
        "approval); progress; resolve (entry_id now settled); status. Never record a guess as a fact."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "objective_id": {"type": "string"},
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "text": {"type": "string"},
            "source": {"type": "string"},
            "kind": {"type": "string", "enum": list(BLOCKER_KINDS)},
            "capability": {"type": "string", "description": "What is missing, in a few words."},
            "needs_owner": {"type": "boolean"},
            "item_id": {"type": "string"},
            "state": {"type": "string", "enum": [s for s in LADDER if s != "authorised"]},
            "evidence": {"type": "string"},
            "entry_id": {"type": "string"},
            "status": {"type": "string", "enum": ["active", "waiting", "blocked", "dropped"]},
        },
        "required": ["objective_id", "action"],
    },
    tier=Tier.GREEN,
)
async def objective_note(objective_id: str, action: str, text: str = "", source: str = "", kind: str = "",
                         needs_owner: bool = False, item_id: str = "", state: str = "", evidence: str = "",
                         entry_id: str = "", status: str = "", capability: str = "") -> dict:
    s = store()
    try:
        if action == "fact":
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
        else:
            raise ObjectiveError(f"Unknown action {action!r}.")
    except ObjectiveError as exc:
        raise ToolError(str(exc)) from exc
    return {"recorded": action, "objective": _short(obj),
            "ids": {"items": [(i["id"], i["text"][:60], i["state"]) for i in obj.items[-5:]],
                    "open": [(e["id"], e["text"][:60]) for k in ("unknowns", "blockers", "attention") for e in obj.open_(k)][-8:]}}
