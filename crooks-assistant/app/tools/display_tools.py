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

Round 9 adds two more, and a way to show two things at once. `screen_show` with `beside` puts
the new thing next to what is up (two at most; a third is refused with both named, and
`replace` says which one to swap). `screen_off` takes everything off a screen, back to its clock,
or one of the two — "turn the screen off", "clear the TV", "take that off", "go home".
`screen_remote` turns the owner's app into the remote for a screen — "become the remote",
"control the TV" — through the same cards every other answer draws: its result is a
`screen_remote` card (app/presentation.py), and the app opens the remote when it draws one
(web/remote.js). It is understood by CLIVE from the owner's words, never by matching a phrase.

All of them act on CLIVE's own record of screens (app/displays/store.py) and nothing else: no
store, inbox or message is changed. A screen is only ever one of the owner's own devices
(app/routes/displays.py). And all of them answer only the owner's own request (round 8, B-01):
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
# Round 9. Neither name holds a verb the gate reads as a store write (app/tools/gate.py
# _MUTATION_VERBS): both change only CLIVE's own record of screens, or nothing at all.
OFF_TOOL = "screen_off"
REMOTE_TOOL = "screen_remote"

register(CapabilityFamily(
    key="screens", label="Screens", area="system",
    what=("put an order's packing slip, an objective or a list on one of your own screens (two at once), approve "
          "a new screen by the code it shows, turn a screen off, work it from a remote, and say what was marked "
          "done there"),
    tools=(LIST_TOOL, SHOW_TOOL, PAIR_TOOL, OFF_TOOL, REMOTE_TOOL),
    state="READY", detail="ready",
))

# The two panes of a screen as the owner and CLIVE name them (app/displays/store.py PANES).
_PANE = {"first": 0, "second": 1}


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
        "on the screen named in full; clear empties it. beside: next to what is up (two at most); "
        "replace: which of the two to swap."
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
            "beside": {"type": "boolean"},
            "replace": {"type": "string", "enum": ["first", "second"]},
        },
        "required": ["screen"],
    },
    tier=Tier.AMBER,
    issued_id_args=("order_id", "objective_id"),
)
async def screen_show(screen: str, order_id: str | None = None, objective_id: str | None = None,
                      title: str | None = None, lines: list[str] | None = None, clear: bool = False,
                      beside: bool = False, replace: str | None = None) -> dict[str, Any]:
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
    # Round 9: next to what is up, or in place of one of the two (never with clear: screen_off
    # takes one of them off).
    if replace is not None and replace not in _PANE:
        raise ToolError("replace is first or second.")
    if (beside is True or replace is not None) and clear:
        raise ToolError("clear takes everything off; to take one of two off, use screen_off.")
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
        shown = s.show(target["id"], view, beside=beside is True, replace=_PANE.get(replace or ""))
    except DisplayError as exc:
        raise ToolError(str(exc)) from None
    on = s.online(target["id"])
    result: dict[str, Any] = {"screen": shown["name"], "showing": (view or {}).get("title") or "nothing", "on": on}
    if shown.get("beside"):
        result["panes"] = [str((shown.get(key) or {}).get("title") or "") for key in ("showing", "beside")]
    if not on:
        result["note"] = f"{shown['name']} has not asked for anything in a while: it shows this when it is next on."
    return result


def _screen_meant(screen: str | None, *, doing: str) -> dict[str, Any]:
    """The screen the owner means (round 9): the one he named — a unique part of a name will do,
    since nothing is put on it — or, when he named none, the one screen showing anything (or
    the only screen there is); otherwise he is asked which."""
    s = store()
    if screen is not None:
        if not isinstance(screen, str) or not screen.strip() or len(screen) > 80:
            raise ToolError("Name the screen.")
        try:
            return s.find(screen)
        except DisplayError as exc:
            raise ToolError(str(exc)) from None
    listed = [x for x in s.screens() if not x.get("pending")]
    showing = [x for x in listed if x.get("showing")]
    for group in (showing, listed if not showing else []):
        if len(group) == 1:
            return s.find(group[0]["name"], exact=True)
    if not listed:
        raise ToolError("No screens yet: open CLIVE's address with /display on a screen and give it a name.")
    names = ", ".join(sorted(x["name"] for x in (showing or listed)))
    raise ToolError(f"Which screen should {doing}? {names}.")


@tool(
    name=OFF_TOOL,
    description="Take everything off a screen, back to its clock, or only the pane named (first or second).",
    input_schema={
        "type": "object",
        "properties": {"screen": {"type": "string", "maxLength": 80}, "pane": {"type": "string", "enum": ["first", "second"]}},
    },
    tier=Tier.GREEN,
)
async def screen_off(screen: str | None = None, pane: str | None = None) -> dict[str, Any]:
    _owners_own()
    if pane is not None and pane not in _PANE:
        raise ToolError("pane is first or second.")
    target = _screen_meant(screen, doing="be turned off")
    try:
        out = store().take_off(target["id"], _PANE.get(pane or ""))
    except DisplayError as exc:
        raise ToolError(str(exc)) from None
    left = str((out.get("showing") or {}).get("title") or "")
    result: dict[str, Any] = {"screen": out["name"], "taken_off": out["taken_off"], "showing": left or "nothing"}
    if not out["taken_off"]:
        result["note"] = "It was showing nothing already."
    return result


@tool(
    name=REMOTE_TOOL,
    description="Open the remote for a screen, on the device the owner is asking from.",
    input_schema={"type": "object", "properties": {"screen": {"type": "string", "maxLength": 80}}},
    tier=Tier.GREEN,
)
async def screen_remote(screen: str | None = None) -> dict[str, Any]:
    """Nothing on the screen changes: the answer carries the screen, and the app opens its remote
    when it draws the card this becomes (app/presentation.py)."""
    _owners_own()
    target = _screen_meant(screen, doing="this app control")
    if target.get("paired", True) is not True:
        raise ToolError(f"The {target['name']} hasn't been approved yet: it shows only its code until the owner "
                        "reads that out.")
    s = store()
    showing = [str(v.get("title") or "") for v in (target.get("showing"), target.get("beside")) if isinstance(v, dict)]
    return {"screen": target["name"], "screen_id": target["id"], "remote": "open", "showing": showing,
            "on": s.online(target["id"])}


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
