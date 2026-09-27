"""The owner's screens, from the conversation: put something on one, and read what was done.

Two tools. `screen_show` puts an order's fulfilment slip or an objective (each one the
conversation was shown: its id is an issued one, app/tools/gate.py), or a titled list, on a
screen the owner named when he opened `/display` on it ("office screen", "bedroom screen").
The screen is named in full — a slip carries a customer's name and address, so it never goes to
the nearest match — and a list is bounded before anything is done with it (the 2026-09-27
deploy review, B-05). `screen_list`
says which screens there are, whether each is on and what it shows, and what was last marked
done on them — "has 2048 been packed?" is `screen_list` with the order's id.

Both act on CLIVE's own record of screens (app/displays/store.py) and nothing else: no store,
inbox or message is changed. A screen is only ever one of the owner's own devices
(app/routes/displays.py).
"""

from __future__ import annotations

from typing import Any

from app.capabilities.families import CapabilityFamily, register
from app.displays import views
from app.displays.store import DisplayError, store
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

LIST_TOOL = "screen_list"
SHOW_TOOL = "screen_show"

register(CapabilityFamily(
    key="screens", label="Screens", area="system",
    what="put an order's packing slip, an objective or a list on one of your own screens, and say what was marked done there",
    tools=(LIST_TOOL, SHOW_TOOL),
    state="READY", detail="ready",
))


@tool(
    name=LIST_TOOL,
    description=(
        "The owner's screens: which are on, what each shows, and what was marked done on them "
        "(order_id: whether that order was marked packed)."
    ),
    input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}},
    tier=Tier.GREEN,
)
async def screen_list(order_id: str | None = None) -> dict[str, Any]:
    s = store()
    out: dict[str, Any] = {"screens": s.screens(), "done": s.done(ref=order_id or None)}
    if not out["screens"]:
        out["note"] = "No screens yet: open CLIVE's address with /display on a screen and give it a name."
    return out


@tool(
    name=SHOW_TOOL,
    description=(
        "Put an order's packing slip (order_id), objective (objective_id) or list (title, lines) "
        "on the screen named in full; clear empties it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "screen": {"type": "string"},
            "order_id": {"type": "string"},
            "objective_id": {"type": "string"},
            "title": {"type": "string", "maxLength": views.MAX_TITLE},
            "lines": {"type": "array", "maxItems": views.MAX_LINES, "items": {"type": "string", "maxLength": views.MAX_LINE}},
            "clear": {"type": "boolean"},
        },
        "required": ["screen"],
    },
    tier=Tier.AMBER,
    issued_id_args=("order_id", "objective_id"),
)
async def screen_show(screen: str, order_id: str | None = None, objective_id: str | None = None,
                      title: str | None = None, lines: list[str] | None = None, clear: bool = False) -> dict[str, Any]:
    # Bounds first, before a screen is looked for or a line is looked at.
    if not isinstance(screen, str) or not screen.strip() or len(screen) > 200:
        raise ToolError("Name the screen.")
    if title is not None and (not isinstance(title, str) or len(title) > views.MAX_TITLE):
        raise ToolError(f"A title is one line of at most {views.MAX_TITLE} characters.")
    if lines is not None:
        if not isinstance(lines, list) or len(lines) > views.MAX_LINES:
            raise ToolError(f"A list on a screen is at most {views.MAX_LINES} lines.")
        if any(not isinstance(line, str) or len(line) > views.MAX_LINE for line in lines):
            raise ToolError(f"Each line on a screen is short text, at most {views.MAX_LINE} characters.")
    s = store()
    try:
        target = s.find(screen, exact=True)
    except DisplayError as exc:
        raise ToolError(str(exc)) from None
    chosen = [bool(order_id), bool(objective_id), bool(lines) or bool(title), bool(clear)]
    if sum(chosen) != 1:
        raise ToolError("Say one thing to show: an order_id, an objective_id, a title with lines, or clear.")
    if clear:
        view = None
    elif order_id:
        from app.tools.shopify_tools import hydrator

        order = await hydrator().order(str(order_id), budget_s=0.25)
        if not order.get("order_number"):
            raise ToolError("That order could not be read.")
        view = views.order_view(order)
    elif objective_id:
        from app.objectives.store import ObjectiveError
        from app.objectives.store import store as objectives

        try:
            obj = objectives().get(str(objective_id))
        except ObjectiveError as exc:
            raise ToolError(str(exc)) from None
        view = views.objective_view(obj.summary(), obj.items)
    else:
        view = views.list_view(title or "", list(lines or []))
    try:
        shown = s.show(target["id"], view)
    except DisplayError as exc:
        raise ToolError(str(exc)) from None
    on = s.online(target["id"])
    result: dict[str, Any] = {"screen": shown["name"], "showing": (view or {}).get("title") or "nothing", "on": on}
    if not on:
        result["note"] = f"{shown['name']} has not asked for anything in a while: it shows this when it is next on."
    return result
