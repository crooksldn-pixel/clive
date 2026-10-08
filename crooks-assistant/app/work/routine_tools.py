"""CLIVE's hands on named routines (app/work/routines.py): routine_list, routine_note, routine_run.

George, ruling 31 (8 October 2026): a routine is a saved multi-step job he starts by name. "Save
this as my Friday drop routine" keeps the steps; "run my Friday drop routine" does them again.

What these tools promise:
* Each person's routines are their own. The owner keeps, runs and edits his; a member of the team
  theirs, and only with the tools the owner allowed them (app/people/staff.py): a step a person
  could not call themselves is refused when it is saved, and again when it is run.
* A step is checked against the registry and the gate when it is saved: a tool CLIVE has, that the
  gate would run or stage (never a RED read, an unreviewed write or a test tool), with arguments
  its schema names. Whether it is a read or a change is read from the registry, not said by the
  model. An id is never kept (the gate's issued-id arguments are dropped and the model is told so):
  each run looks its records up again, so a routine cannot act on yesterday's order by accident.
* routine_run executes nothing. It hands the model the steps, and the model calls each tool as it
  would if he had asked in words: every call goes through dispatch and the gate (app/tools/
  dispatch.py), so a read runs and a change is only ever STAGED as a card for his gesture. A step
  that cannot run now (its family not connected, changes switched off, the tool gone) is marked
  with why, and said, never skipped in silence.
* routine_list and routine_note change and read only CLIVE's own records on this machine, like
  work_note and objective_note on the gate's allow-list: nothing is sent and no store is touched.

What the screen draws from these results is app/work/routine_cards.py.
"""

from __future__ import annotations

from typing import Any

from app.capabilities.families import CapabilityFamily, register
from app.people import staff
from app.tools import gate, registry
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool
from app.work import tools as work_tools
from app.work.routines import MAX_STEPS, NamedRoutine, RoutineError, Step, book, clean_say
from app.work.store import VIA_CLIVE

TOOLS = ("routine_list", "routine_note", "routine_run")
ACTIONS = ("save", "add", "change", "drop", "move", "rename", "forget")

register(CapabilityFamily(
    key="routines", label="Routines", area="system",
    what="save a few steps under a name and run them again by saying it; every change still waits for your gesture",
    tools=TOOLS, state="READY", detail="ready",
))

# What the model is told to do with a routine's steps. In the result, not the description, so a
# turn that never runs a routine pays nothing for it.
RUN = ("Carry out every step now, in order, by calling its tool with its args; a step marked `skip` is not "
       "called, and you say why. A step's args name no record by id: find the record first, as you would "
       "if he had asked in words, and act on the one its `say` describes. Reads that do not depend on each "
       "other may go together. A change is only ever prepared as a card for the gesture: never say one was "
       "done. Add no step of your own. Then say in a sentence or two what ran, what is waiting on its card, "
       "and anything that could not be done.")
SAVED = ("A routine keeps no record's id: each run looks its records up again. `say` is the step in the "
         "person's words, and it authorises nothing beyond that step's own tool.")

STEP_SCHEMA = {
    "type": "object",
    "properties": {"tool": {"type": "string"}, "args": {"type": "object"}, "say": {"type": "string"}},
    "required": ["tool", "say"],
}


def _sentence(exc: Exception) -> str:
    """A store's refusal as a sentence: its first letter raised and nothing else changed, so a
    routine's own name keeps its capitals."""
    said = str(exc).strip()
    return said[:1].upper() + said[1:] + ("" if said.endswith(".") else ".")


def _caller() -> tuple[str, bool]:
    """(whose routines, is the owner), from the request this call is part of."""
    return work_tools._caller()


# ------------------------------------------------------------------ what a step may be


def tool_problem(name: str, *, owner: bool) -> str:
    """Why this tool cannot be a step of this person's routine, or "" when it can. The gate's own
    rules, read and not copied (as app/tools/authority.py reads them)."""
    if name in TOOLS:
        return "a routine cannot start a routine"
    if name.startswith("mock_"):
        return "that is a test tool"
    try:
        spec = registry.get(name)
    except KeyError:
        return "CLIVE has no tool by that name"
    if spec.write is not None or spec.batch is not None:
        complete = spec.write.complete if spec.write is not None else spec.batch.complete
        if not complete or spec.tier is Tier.GREEN:
            return "that change has no reviewed definition"
    elif spec.tier is Tier.RED or name not in gate._KNOWN_TOOLS or gate._looks_like_mutation(name):
        return "the gate does not run that tool"
    if not owner and not staff.may_call(name):
        return "that is not one of your tools"
    return ""


def _issued(name: str, spec: Any) -> set[str]:
    """The arguments that carry an id this conversation must have been handed: never kept."""
    return set(spec.issued_id_args) | set(gate._ISSUED_ID_ARGS.get(name, ()))


def checked_step(raw: Any, *, owner: bool) -> tuple[Step, list[str]]:
    """One step as it is kept, and the id arguments left out of it."""
    if not isinstance(raw, dict):
        raise ToolError("Each step is {tool, args, say}.")
    name = registry.normalise_tool_name(str(raw.get("tool") or "").strip())
    problem = tool_problem(name, owner=owner)
    if problem:
        raise ToolError(f"A step with {name[:40] or 'no tool'} cannot be kept: {problem}.")
    spec = registry.get(name)
    args = raw.get("args") if raw.get("args") is not None else {}
    if not isinstance(args, dict):
        raise ToolError(f"The args of the {name} step are not a set of named values.")
    known = (spec.input_schema or {}).get("properties") or {}
    unknown = [str(k) for k in args if k not in known]
    if unknown:
        raise ToolError(f"{name} does not take an argument called {unknown[0][:30]}.")
    ids = _issued(name, spec)
    try:
        say = clean_say(raw.get("say"))
    except RoutineError as exc:
        raise ToolError(_sentence(exc)) from None
    kind = "change" if spec.write is not None or spec.batch is not None else "read"
    return Step(tool=name, say=say, args={k: v for k, v in args.items() if k not in ids}, kind=kind), sorted(
        str(k) for k in args if k in ids)


def _steps(raw: Any, *, owner: bool) -> tuple[list[Step], list[str]]:
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        raise ToolError("`steps` is a list of {tool, args, say}.")
    if len(raw) > MAX_STEPS:
        raise ToolError(f"A routine has at most {MAX_STEPS} steps.")
    out: list[Step] = []
    dropped: list[str] = []
    for number, item in enumerate(raw, start=1):
        step, left = checked_step(item, owner=owner)
        out.append(step)
        dropped += [f"step {number}: {arg}" for arg in left]
    return out, dropped


def _position(at: Any, count: int, *, allow_end: bool = False) -> int:
    """A step's place, counted from one as he says it, as a list index."""
    try:
        number = int(at)
    except (TypeError, ValueError):
        raise ToolError("Say which step, by its number.") from None
    last = count + 1 if allow_end else count
    if number < 1 or number > last:
        raise ToolError(f"There is no step {number}; it has {count}." if count else "It has no steps yet.")
    return number - 1


def _said(routine: NamedRoutine, what: str, dropped: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"view": "one", "said": what, "routine": routine.public(), "note": SAVED}
    if dropped:
        out["ids_not_kept"] = dropped
    return out


# ------------------------------------------------------------------ the tools


@tool(
    name="routine_list",
    description="The asker's named routines (saved steps they start by name), or one in full by `name`.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
    tier=Tier.GREEN,
)
async def routine_list(name: str = "") -> dict[str, Any]:
    who, _ = _caller()
    try:
        if name:
            return {"view": "one", "routine": book.find(who, name).public(), "note": SAVED}
        return {"view": "list", "routines": [r.public() for r in book.of(who)]}
    except RoutineError as exc:
        raise ToolError(_sentence(exc)) from None


@tool(
    name="routine_note",
    description=("Keep or change a named routine: steps the asker runs later by its name (\"save this as my "
                 "Friday drop routine\"), not a repeating team job (work_note). save (name, steps: the calls "
                 "you made for it, or the ones they list, each {tool, args, say: the step in their words}); "
                 "add (steps, at); change (at, steps: one); drop (at); move (at, to); rename (new_name); forget."),
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)}, "name": {"type": "string"},
            "steps": {"type": "array", "maxItems": MAX_STEPS, "items": STEP_SCHEMA},
            "at": {"type": "integer"}, "to": {"type": "integer"}, "new_name": {"type": "string"},
        },
        "required": ["action", "name"],
    },
    tier=Tier.GREEN,
)
async def routine_note(action: str, name: str, steps: list[dict] | None = None, at: int | None = None,
                       to: int | None = None, new_name: str = "") -> dict[str, Any]:
    who, owner = _caller()
    action = str(action or "").strip().lower()
    if action not in ACTIONS:
        raise ToolError("That is not a step for a routine.")
    try:
        if action == "save":
            made, dropped = _steps(steps, owner=owner)
            return _said(book.save(who, name, made, via=VIA_CLIVE), "Saved", dropped)
        if action == "forget":
            gone = book.forget(who, name)
            return {"view": "list", "said": f"Forgot {gone.name}", "forgotten": gone.public(),
                    "routines": [r.public() for r in book.of(who)]}
        if action == "rename":
            if not str(new_name or "").strip():
                raise ToolError("Say the new name.")
            return _said(book.change(who, name, new_name=new_name), "Renamed", [])
        routine = book.find(who, name)
        current = list(routine.steps)
        dropped: list[str] = []
        if action == "add":
            added, dropped = _steps(steps, owner=owner)
            if not added:
                raise ToolError("Say the step to add.")
            place = _position(at, len(current), allow_end=True) if at is not None else len(current)
            current[place:place] = added
            what = f"Added step {place + 1}" if len(added) == 1 else f"Added steps {place + 1} to {place + len(added)}"
        elif action == "change":
            place = _position(at, len(current))
            new, dropped = _steps(steps, owner=owner)
            if len(new) != 1:
                raise ToolError("Give the one step that replaces it.")
            current[place] = new[0]
            what = f"Changed step {place + 1}"
        elif action == "drop":
            place = _position(at, len(current))
            del current[place]
            what = f"Took out step {place + 1}"
        else:
            place = _position(at, len(current))
            target = _position(to, len(current))
            current.insert(target, current.pop(place))
            what = f"Moved step {place + 1} to {target + 1}"
        if len(current) > MAX_STEPS:
            raise ToolError(f"A routine has at most {MAX_STEPS} steps.")
        return _said(book.change(who, routine.name, steps=current), what, dropped)
    except RoutineError as exc:
        raise ToolError(_sentence(exc)) from None


@tool(
    name="routine_run",
    description="Start one of the asker's named routines by its name (\"run my Friday drop routine\"): returns its steps to carry out now.",
    input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    tier=Tier.GREEN,
)
async def routine_run(name: str) -> dict[str, Any]:
    who, owner = _caller()
    try:
        routine = book.find(who, name)
    except RoutineError as exc:
        raise ToolError(_sentence(exc)) from None
    if not routine.steps:
        raise ToolError(f"{routine.name} has no steps yet.")
    run = []
    for number, step in enumerate(routine.steps, start=1):
        row: dict[str, Any] = {"step": number, "say": step.say, "tool": step.tool, "args": dict(step.args),
                               "change": step.kind == "change"}
        why = unavailable(step, owner=owner)
        if why:
            row["skip"] = why
        run.append(row)
    book.ran(who, routine.routine_id)
    return {"view": "run", "routine": routine.public(), "run": run, "do": RUN}


def unavailable(step: Step, *, owner: bool) -> str:
    """Why a saved step cannot be carried out now, or "": the rules it was saved under, read again,
    and what this server can do today (a family not connected, changes switched off)."""
    problem = tool_problem(step.tool, owner=owner)
    if problem:
        return problem
    spec = registry.get(step.tool)
    if (spec.write is not None or spec.batch is not None) and step.kind != "change":
        return "it was saved as a read and is now a change"
    runtime = work_tools._RUNTIME[0]
    if runtime is None:
        return ""
    settings = getattr(runtime, "settings", None)
    if step.kind == "change" and settings is not None and not getattr(settings, "writes_enabled", False):
        return "changes are switched off on this server"
    try:
        withheld = set(runtime.withheld_by_family())
    except Exception:  # noqa: BLE001 — a family table that cannot be read withholds nothing it did not already
        withheld = set()
    if step.tool in withheld:
        return "that part of CLIVE is not connected right now"
    return ""
