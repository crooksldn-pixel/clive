"""The "routine" card, and what a turn that ran a routine puts on the screen (DEC-074).

Three views, all drawn by web/routines.js from what the routine tools returned (app/work/
routine_tools.py), and never from the model's prose:

  list   the asker's routines: each name, how many steps, how many of them are changes.
  one    one routine as it is saved now (after a save or an edit, as the store read it back):
         its steps in order, each a read or a change, in the words it was saved with.
  run    one routine as this turn carried it out: each step done (a read that ran), waiting (a
         change staged as a card for his gesture), failed, skipped with why, or not done. Read
         from the calls the model made after routine_run in this turn, matched to the steps in
         order by tool: a step is "done" only when its own tool came back, and "waiting" only
         when the gate staged it. A step nobody called says so.

A turn that ran a routine shows everything the routine was asked to do: the steps' own cards stay,
whatever app/focus.py would set aside, because naming the routine asked for each of them (ruling
25: what he asked for always shows). A change waiting for his gesture still comes first (DEC-069),
then this card, then the steps' cards. The lookups the model made on the way to a change (the
order found so a tag could go on it) are not steps, and are not drawn: as DEC-069 has it, what was
read to find something is not what was asked for. Errors are drawn as always, by present().

Every string is bounded here, and the page writes it with textContent.
"""

from __future__ import annotations

import re
from typing import Any

TOOLS = frozenset({"routine_list", "routine_note", "routine_run"})
RUN_TOOL = "routine_run"
STATES = ("done", "waiting", "failed", "skipped", "not_done", "pending")
MAX_ROWS = 30
MAX_TEXT = 160
# The routine's own id (app/work/routines.py), the card's identity on the glass: never its name.
_ID = re.compile(r"^nr_[0-9a-f]{8}$")
_CHANGE_CARDS = frozenset({"confirmation", "batch_action", "variant_picker", "email_compose", "workspace"})


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value or "").split())[:limit]


def _routine(result: dict[str, Any]) -> dict[str, Any]:
    routine = result.get("routine")
    return routine if isinstance(routine, dict) else {}


def _steps(routine: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (routine.get("steps") or []) if isinstance(s, dict)][:MAX_ROWS]


def card(name: str, result: dict[str, Any], later: list[Any] | None) -> dict[str, Any]:
    """The card's data for one routine tool's result. `later` is the calls the turn made after it,
    or None when they are not known yet (the early drawing of one read, app/progressive.py)."""
    view = str(result.get("view") or "")
    said = _text(result.get("said"), 80)
    if view == "list":
        rows = []
        for routine in [r for r in (result.get("routines") or []) if isinstance(r, dict)][:MAX_ROWS]:
            steps = _steps(routine)
            rows.append({"name": _text(routine.get("name"), 60), "count": len(steps),
                         "changes": sum(1 for s in steps if s.get("kind") == "change"),
                         "says": [_text(s.get("say"), 80) for s in steps[:3]], "more": max(0, len(steps) - 3)})
        return {"view": "list", "key": "list", "title": "Routines", "said": said, "routines": rows}
    routine = _routine(result)
    title = _text(routine.get("name"), 60)
    ident = str(routine.get("routine_id") or "")
    ident = ident if _ID.fullmatch(ident) else ""
    if view == "run" and name == RUN_TOOL:
        rows = progress(result.get("run"), _until_next_run(later) if later is not None else None)
        counts = {state: sum(1 for r in rows if r["state"] == state) for state in STATES}
        return {"view": "run", "key": f"run {ident}".strip(), "title": title, "steps": rows, "counts": counts}
    steps = [{"n": n, "say": _text(s.get("say")), "kind": "change" if s.get("kind") == "change" else "read"}
             for n, s in enumerate(_steps(routine), start=1)]
    out: dict[str, Any] = {"view": "one", "key": f"one {ident}".strip(), "title": title, "said": said, "steps": steps}
    if result.get("ids_not_kept"):
        out["looked_up"] = True       # an id he gave is looked up again each run, never kept
    return out


def _until_next_run(later: list[Any]) -> list[Any]:
    """The calls that belong to this run: up to the next routine started in the same turn."""
    out = []
    for call in later or []:
        if getattr(call, "name", "") == RUN_TOOL:
            break
        out.append(call)
    return out


def _match(steps: list[dict[str, Any]], calls: list[Any]) -> dict[int, Any]:
    """Each step's call, by tool and in order: the first not already taken. A call the gate refused
    as a wrong turning and the model then made properly counts as the one that came back."""
    taken: set[int] = set()
    found: dict[int, Any] = {}
    for number, step in enumerate(steps):
        if step.get("skip"):
            continue
        tool = str(step.get("tool") or "")
        index = next((i for i, c in enumerate(calls) if i not in taken and getattr(c, "name", "") == tool), None)
        if index is None:
            continue
        taken.add(index)
        if not getattr(calls[index], "ok", False):
            again = next((i for i in range(index + 1, len(calls))
                          if i not in taken and getattr(calls[i], "name", "") == tool and getattr(calls[i], "ok", False)), None)
            if again is not None:
                taken.add(again)
                index = again
        found[number] = (index, calls[index])
    return found


def progress(run: Any, later: list[Any] | None) -> list[dict[str, Any]]:
    """Each step of a run as this turn left it."""
    steps = [s for s in (run or []) if isinstance(s, dict)][:MAX_ROWS]
    matched = _match(steps, later or [])
    rows = []
    for number, step in enumerate(steps):
        row = {"n": number + 1, "say": _text(step.get("say")), "kind": "change" if step.get("change") else "read"}
        if step.get("skip"):
            row.update(state="skipped", why=_text(step.get("skip"), 80))
        elif later is None:
            row["state"] = "pending"
        elif number not in matched:
            row["state"] = "not_done"
        else:
            call = matched[number][1]
            row["state"] = ("waiting" if getattr(call, "proposal_id", None) else "done") if getattr(call, "ok", False) else "failed"
        rows.append(row)
    return rows


def ran(calls: list[Any] | None) -> bool:
    """Whether this turn started a routine."""
    return any(getattr(c, "name", "") == RUN_TOOL and getattr(c, "ok", False) for c in calls or [])


def lookups_on_the_way(calls: list[Any] | None) -> frozenset[int]:
    """The reads a turn made after starting a routine that are none of its steps: how a change's
    record was found. Their cards are not drawn (see the module's note); a failure still is."""
    calls = list(calls or [])
    out: set[int] = set()
    for start, call in enumerate(calls):
        if getattr(call, "name", "") != RUN_TOOL or not getattr(call, "ok", False):
            continue
        result = getattr(call, "result", None)
        run = result.get("run") if isinstance(result, dict) else None
        steps = [s for s in (run or []) if isinstance(s, dict)]
        span = _until_next_run(calls[start + 1:])
        used = {index for index, _ in _match(steps, span).values()}
        for offset, later in enumerate(span):
            if offset not in used and getattr(later, "ok", False) and not getattr(later, "proposal_id", None) \
                    and getattr(later, "name", "") not in TOOLS:
                out.add(start + 1 + offset)
    return frozenset(out)


def answer_cards(items: list[dict[str, Any]], why: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """A routine turn's screen: every card it drew, a change first, then the routine, then the rest."""
    cards = [item for item in items or [] if isinstance(item, dict)]
    changes = [c for c in cards if c.get("type") in _CHANGE_CARDS]
    routine = [c for c in cards if c.get("type") == "routine"]
    rest = [c for c in cards if c.get("type") not in _CHANGE_CARDS and c.get("type") != "routine"]
    if why is not None:
        why.update({"rule": "routine", "set_aside": []})
    return changes + routine + rest
