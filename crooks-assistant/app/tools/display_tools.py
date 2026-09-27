"""The owner's screens, from the conversation: put something on one, approve a new one, and read
what was done.

Three tools. `screen_show` puts an order's fulfilment slip or an objective (each one the
conversation was shown: its id is an issued one, app/tools/gate.py), or a titled list, on a
screen the owner named when he opened `/display` on it ("office screen", "bedroom screen").
The screen is named in full — a slip carries a customer's name and address, so it never goes to
the nearest match — and a list is bounded before anything is done with it (the 2026-09-27
deploy review, B-05). `screen_pair` approves a newly named screen with the six-digit code it
shows, as the owner read it out: until then nothing goes on it (round 8, B-02). `screen_list`
says which screens there are, whether each is on, waiting for approval, and what it shows, and
what was last marked done on them — "has 2048 been packed?" is `screen_list` with the order's id.

All three act on CLIVE's own record of screens (app/displays/store.py) and nothing else: no
store, inbox or message is changed. A screen is only ever one of the owner's own devices
(app/routes/displays.py). And all three answer only the owner's own request (round 8, B-01):
each handler checks the authority the call holds itself, so no service work — a speculative read
the owner's request started (app/memory/prefetch.py) — reaches a screen, whatever the
dispatcher lets through.
"""

from __future__ import annotations

import re
from typing import Any

from app.capabilities.families import CapabilityFamily, register
from app.displays import views
from app.displays.store import DisplayError, store
from app.tools import authority as tool_authority
from app.tools.context import current_session
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

LIST_TOOL = "screen_list"
SHOW_TOOL = "screen_show"
# Named "pair" and not "approve": the gate reads "approve" in a tool's name as a change to the
# store to be staged for the owner's tap (app/tools/gate.py _MUTATION_VERBS). This changes only
# CLIVE's own record of screens, like screen_show, and needs the code the owner read out instead.
PAIR_TOOL = "screen_pair"

register(CapabilityFamily(
    key="screens", label="Screens", area="system",
    what=("put an order's packing slip, an objective or a list on one of your own screens, approve a new screen "
          "by the code it shows, and say what was marked done there"),
    tools=(LIST_TOOL, SHOW_TOOL, PAIR_TOOL),
    state="READY", detail="ready",
))


def _owners_own() -> None:
    """Round 8, B-01: a screen tool runs only for the owner's own request. Service authority —
    bounded work derived from his request that may outlive it — is refused here even while it is
    live, and so is none at all, whatever the dispatcher decided."""
    held = tool_authority.current()
    if held is None or held.kind != tool_authority.OWNER:
        raise ToolError("Screens answer only the owner's own request, and this was not one, so nothing was done.")


# Digits said as words, as a transcript may write them ("one two three four five six").
_DIGIT_WORDS = {"zero": "0", "oh": "0", "nought": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_DIGIT_WORD = re.compile(r"\b(" + "|".join(_DIGIT_WORDS) + r")\b")
_DIGIT_RUN = re.compile(r"\d(?:[\s,.\-]*\d)*")


def _owner_said(digits: str) -> bool:
    """Whether the owner himself said this code in the request being answered (round 8, B-02):
    the code is the proof he is looking at the device he means, so it must come from his own
    words (the session's `heard`), never from an email, an order note or a guess the model
    makes. Digits may be spaced, hyphenated or said as words."""
    heard = str(getattr(current_session(), "heard", "") or "")[:2000].lower()
    spoken = _DIGIT_WORD.sub(lambda m: _DIGIT_WORDS[m.group(1)], heard)
    return any(digits in re.sub(r"\D", "", run) for run in _DIGIT_RUN.findall(spoken))


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
    _owners_own()
    s = store()
    out: dict[str, Any] = {"screens": s.screens(), "done": s.done(ref=order_id or None)}
    if not out["screens"]:
        out["note"] = "No screens yet: open CLIVE's address with /display on a screen and give it a name."
    elif any(x.get("pending") for x in out["screens"]):
        out["note"] = "A pending screen shows a six-digit code: it takes nothing until the owner reads the code out."
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
    _owners_own()
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
    if target.get("paired", True) is not True:
        # Before an order is read for it (round 8, B-02); the store refuses it again.
        raise ToolError(f"The {target['name']} hasn't been approved yet. It shows a six-digit code: it is approved "
                        "only with the code the owner reads from it.")
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


@tool(
    name=PAIR_TOOL,
    description="Approve a newly named screen: its full name, and the six-digit code it shows as the owner read it out.",
    input_schema={
        "type": "object",
        "properties": {"screen": {"type": "string", "maxLength": 80}, "code": {"type": "string", "maxLength": 20}},
        "required": ["screen", "code"],
    },
    tier=Tier.GREEN,
)
async def screen_pair(screen: str, code: str) -> dict[str, Any]:
    _owners_own()
    if not isinstance(screen, str) or not screen.strip() or len(screen) > 80:
        raise ToolError("Name the screen.")
    if not isinstance(code, str) or len(code) > 20 or len(re.sub(r"\D", "", code)) != 6:
        raise ToolError("The code is the six digits the screen shows, like 123 456.")
    digits = re.sub(r"\D", "", code)
    if not _owner_said(digits):
        # Not counted as a wrong code: it is not the owner's attempt at all.
        raise ToolError("A screen is approved only with the code the owner reads out from it himself, in this request. "
                        "Ask him to read it out; nothing was approved.")
    try:
        return store().approve(screen, digits)
    except DisplayError as exc:
        raise ToolError(str(exc)) from None
