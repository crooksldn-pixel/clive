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
what was last marked done on them — "has 2048 been packed?" is `screen_list` with the order's id
or its number.

Round 9 adds two more, and a way to show two things at once. `screen_show` with `beside` puts
the new thing next to what is up (two at most; a third is refused with both named, and
`replace` says which one to swap). `screen_off` takes everything off a screen, back to its clock,
or one of the two — "turn the screen off", "clear the TV", "take that off", "go home".
`screen_remote` turns the owner's app into the remote for a screen — "become the remote",
"control the TV" — through the same cards every other answer draws: its result is a
`screen_remote` card (app/presentation.py), and the app opens the remote when it draws one
(web/remote.js). It is understood by CLIVE from the owner's words, never by matching a phrase.

And a screen plays YouTube. `screen_play` puts a video on a screen — found on YouTube from what
the owner asked for ("the Heat trailer", "lofi girl"), or the link he gave — and its answer is
the same `screen_remote` card, so the app becomes the video's remote. `screen_video` plays,
pauses, mutes, sets the volume of, skips through or restarts what is playing ("pause the TV",
"turn it up", "back thirty seconds"). A video carries nobody's details, so the screen may be
named in part, or not at all when there is only one it could be.

All of them act on CLIVE's own record of screens (app/displays/store.py) and nothing else: no
store, inbox or message is changed. A screen is only ever one of the owner's own devices
(app/routes/displays.py). And all of them answer only the owner's own request (round 8, B-01):
each handler checks the authority the call holds itself, so no service work — a speculative read
the owner's request started (app/memory/prefetch.py) — reaches a screen, whatever the
dispatcher lets through.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any

from app.capabilities.families import CapabilityFamily, register
from app.clients import youtube
from app.displays import views
from app.displays.store import (
    MAX_JUMP_S,
    MAX_SKIP_S,
    DisplayError,
    how_marked,
    no_packed_record,
    store,
)
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
# YouTube on a screen. Neither name holds a verb the gate reads as a store write: both change
# only CLIVE's own record of screens, and read YouTube.
PLAY_TOOL = "screen_play"
VIDEO_TOOL = "screen_video"

register(CapabilityFamily(
    key="screens", label="Screens", area="system",
    what=("put an order's packing slip, an objective or a list on one of your own screens (two at once), play a "
          "YouTube video on one and pause it, turn it up or skip, approve a new screen by the code it shows, turn "
          "a screen off, work it from a remote, and say what was marked done there"),
    tools=(LIST_TOOL, SHOW_TOOL, PAIR_TOOL, OFF_TOOL, REMOTE_TOOL, PLAY_TOOL, VIDEO_TOOL),
    state="READY", detail="ready",
))

# The two panes of a screen as the owner and CLIVE name them (app/displays/store.py PANES).
_PANE = {"first": 0, "second": 1}

# The screen a drop was checked for, by its id (round 13, S3-01). Set by the drop's own route
# (app/displays/put.py) around its one call to screen_show, and by nothing else: it is in no tool's
# schema or signature, so the model can neither pass it nor see it. While it is set, screen_show
# puts the record on that screen and no other. The name the route passes is looked up as always,
# and a name that no longer leads to that id (the screen forgotten and another device named and
# approved in its place meanwhile) is refused before anything is read.
DROP_SCREEN: ContextVar[str] = ContextVar("crooks_drop_screen", default="")


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
    # Each done row says how it was marked, in words to say as they are. The owner ruled on
    # 1 October (ruling 12, closing B-04) that a row marked by a screen's own button, his remote
    # or the remote's controls on a screen counts as packed, so each is said as packed. An order
    # is found by its Shopify id or by its number as he says it ("1047", "#1047").
    done = [{**row, "marked": how_marked(row)} for row in s.done(order=order_id or None)]
    out: dict[str, Any] = {"screens": s.screens(), "done": done}
    if order_id and not done:
        out["packed_record"] = no_packed_record(order_id)
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
    bound = DROP_SCREEN.get()
    if bound and target.get("id") != bound:
        raise ToolError(f"The {target['name']} is not the screen the record was dropped on any more (it was "
                        "forgotten and named again), so nothing was put on it.")
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
    """The owner's own "turn the screen off", asked now: whatever is up on the screen he means
    when this runs comes off, and the answer names each thing that did, so he hears exactly
    what went (round 9, B-REMOTE-OFF). The remote's off is different: it is a tap on a view that
    may be old by the time it arrives, so it names the screen's version and a changed screen is
    left as it is (app/routes/displays.py remote_off)."""
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
    if out.get("removed"):
        result["took_off"] = [title or "something" for title in out["removed"]]
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


# ---- YouTube on a screen ------------------------------------------------------------------


def _clip(view: dict[str, Any] | None) -> str:
    return str((view or {}).get("title") or "")


@tool(
    name=PLAY_TOOL,
    description=(
        "Play a YouTube video on a screen: query (the owner's words) or video (a link). choices are the other "
        "matches. beside/replace as screen_show."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "screen": {"type": "string", "maxLength": 80},
            "query": {"type": "string", "maxLength": youtube.MAX_QUERY},
            "video": {"type": "string", "maxLength": 500},
            "beside": {"type": "boolean"},
            "replace": {"type": "string", "enum": ["first", "second"]},
        },
    },
    tier=Tier.GREEN,
)
async def screen_play(screen: str | None = None, query: str | None = None, video: str | None = None,
                      beside: bool = False, replace: str | None = None) -> dict[str, Any]:
    _owners_own()
    if bool((query or "").strip()) == bool((video or "").strip()):
        raise ToolError("Say what to find on YouTube (query) or give the link (video), one of the two.")
    if replace is not None and replace not in _PANE:
        raise ToolError("replace is first or second.")
    # Which screen, before YouTube is asked anything.
    target = _screen_meant(screen, doing="play it")
    if target.get("paired", True) is not True:
        raise ToolError(f"The {target['name']} hasn't been approved yet. It shows a six-digit code: it is approved "
                        "only with the code the owner reads from it.")
    choices: list[youtube.Video] = []
    try:
        if video and video.strip():
            linked = youtube.parse(video)
            if linked is None:
                raise ToolError("That is not a YouTube link. Ask for the link from YouTube's Share button, or say what "
                                "to search for.")
            chosen = await youtube.video(linked[0], start=linked[1])
        else:
            found = await youtube.search(str(query))
            if not found:
                raise ToolError("YouTube found nothing it lets play on a screen for that. Try other words.")
            chosen, choices = found[0], found[1:]
    except youtube.YouTubeUnavailable as exc:
        raise ToolError(str(exc)) from None
    view = views.video_view(chosen.id, title=chosen.title, channel=chosen.channel, duration_s=chosen.duration_s,
                            live=chosen.live, start=chosen.start)
    s = store()
    try:
        shown = s.show(target["id"], view, beside=beside is True, replace=_PANE.get(replace or ""))
    except DisplayError as exc:
        raise ToolError(str(exc)) from None
    on = s.online(target["id"])
    showing = [_clip(shown.get(key)) for key in ("showing", "beside") if isinstance(shown.get(key), dict)]
    result: dict[str, Any] = {"screen": shown["name"], "screen_id": shown["id"], "playing": chosen.said(),
                              "showing": showing, "on": on, "remote": "open"}
    if choices:
        result["choices"] = [c.said() for c in choices]
    if not on:
        result["note"] = f"{shown['name']} has not asked for anything in a while: it plays this when it is next on."
    return result


_VIDEO_ACTIONS = ("play", "pause", "mute", "unmute", "volume", "louder", "quieter", "skip", "restart", "jump")


def _video_meant(screen: str | None, pane: str | None) -> tuple[dict[str, Any], int, dict[str, Any]]:
    """The screen and pane whose video the owner means: the screen he named, or the one screen
    playing anything; and on it the pane he named, or the one video on it."""
    s = store()
    if screen is not None:
        target = _screen_meant(screen, doing="play")
        videos = s.playing(target["id"])
    else:
        playing = [(x, s.playing(x["id"])) for x in s.screens() if not x.get("pending")]
        playing = [(x, v) for x, v in playing if v]
        if not playing:
            raise ToolError("Nothing is playing on a screen.")
        if len(playing) > 1:
            names = ", ".join(sorted(x["name"] for x, _ in playing))
            raise ToolError(f"Which screen? Videos are playing on {names}.")
        target, videos = s.find(playing[0][0]["name"], exact=True), playing[0][1]
    if not videos:
        raise ToolError(f"Nothing is playing on the {target['name']}.")
    if pane is not None:
        wanted = [v for v in videos if v["pane"] == _PANE[pane]]
        if not wanted:
            raise ToolError(f"The {pane} thing on the {target['name']} is not a video.")
        return target, _PANE[pane], wanted[0]
    if len(videos) > 1:
        raise ToolError(f"Two videos are on the {target['name']}: say the first or the second.")
    return target, int(videos[0]["pane"]), videos[0]


@tool(
    name=VIDEO_TOOL,
    description=(
        "Control a screen's video. level: the volume, or how much louder/quieter. seconds: how far to skip "
        "(back is negative) or where to jump to."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_VIDEO_ACTIONS)},
            "screen": {"type": "string", "maxLength": 80},
            "pane": {"type": "string", "enum": ["first", "second"]},
            "level": {"type": "integer", "minimum": 0, "maximum": 100},
            "seconds": {"type": "integer", "minimum": -MAX_JUMP_S, "maximum": MAX_JUMP_S},
        },
        "required": ["action"],
    },
    tier=Tier.GREEN,
)
async def screen_video(action: str, screen: str | None = None, pane: str | None = None, level: int | None = None,
                       seconds: int | None = None) -> dict[str, Any]:
    _owners_own()
    if action not in _VIDEO_ACTIONS:
        raise ToolError("action is one of " + ", ".join(_VIDEO_ACTIONS) + ".")
    if pane is not None and pane not in _PANE:
        raise ToolError("pane is first or second.")
    for name, value in (("level", level), ("seconds", seconds)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ToolError(f"{name} is a whole number.")
    value: int | None = None
    if action == "volume":
        if level is None:
            raise ToolError("Say the volume, 0 to 100.")
        value = level
    elif action in ("louder", "quieter"):
        value = level if level else None
    elif action == "skip":
        if not seconds or abs(seconds) > MAX_SKIP_S:
            raise ToolError(f"Say how far to skip: 1 to {MAX_SKIP_S} seconds, negative to go back.")
        value = seconds
    elif action == "jump":
        if seconds is None or seconds < 0:
            raise ToolError("Say where to jump to, in seconds from the start.")
        value = seconds
    elif action == "restart":
        action, value = "jump", 0
    target, n, clip = _video_meant(screen, pane)
    try:
        state = store().player(target["id"], n, int(clip["v"]), action, value)
    except DisplayError as exc:
        raise ToolError(str(exc)) from None
    player, heard = state["player"], state.get("playing") or {}
    result: dict[str, Any] = {"screen": target["name"], "video": clip["title"], "done": action,
                              "paused": player["paused"], "muted": player["muted"]}
    if player["volume"] is not None:
        result["volume"] = player["volume"]
    if heard.get("state"):
        result["was"] = heard["state"]
        if heard.get("at") is not None:
            result["at"] = youtube.clock(int(heard["at"]))
        if heard.get("blocked"):
            result["note"] = "The screen can only play it muted until someone there presses a button on it."
    if not store().online(target["id"]):
        result["note"] = f"{target['name']} has not asked for anything in a while: it does this when it is next on."
    return result
