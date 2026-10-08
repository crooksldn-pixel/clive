"""What a routine's step that is not a lookup changes, in plain words (DEC-074; the review's N1).

Most of a routine's steps are reads, and every change to the shop or a message is staged as its own
card for his gesture. A few of the tools the gate runs at once are not lookups: they change CLIVE's
own records (the work list, an objective), what is on one of his screens (a slip on the office TV, a
video), what is on his own app (a draft being written), or start something at a service (the first
look-up of a tracking number starts a Ship24 tracker, one shipment of the plan). As a step each runs
at once, as it does when he asks for it singly, and the routine card says what it changed in plain
words, never "read" or "Done" as if it were a lookup.

`will` is a saved step's line ("Puts it on the Office TV each run"), from the step's own arguments;
`did` is a run's line ("Put on the Office TV"), from what its call returned. Both are bounded and
drawn as text (web/routines.js). Nothing here reads, writes or decides anything.
"""

from __future__ import annotations

from typing import Any

# The step-able tools that act at once (app/tools/gate.py's read allow-list, each one's comment there).
# The drafts are app/presentation.py WORKSPACE_TOOLS and the composer's two (app/families/compose.py).
ACTS = frozenset({
    "work_note", "objective_open", "objective_note",
    "screen_show", "screen_play", "screen_off", "screen_video", "screen_remote", "close_screen",
    "track_parcel",
    "shopify_order_open", "shopify_order_build", "shopify_discount_open", "shopify_store_credit",
    "gmail_compose_open", "gmail_compose_fill",
})
MAX = 120

_WORK = {  # work_note's action: (each run, what it did)
    "assign": ("Hands out a job", "Handed out"), "routine": ("Sets up a repeating job", "Set up to repeat"),
    "cancel": ("Cancels a job", "Cancelled"), "claim": ("Claims a job", "Claimed"),
    "release": ("Lets go of a job", "Let go of"), "packed": ("Marks a job packed", "Marked packed"),
    "counts": ("Records a stock count", "Recorded the count for"), "done": ("Marks a job done", "Marked done"),
    "flag": ("Flags a job for you", "Flagged for you"),
}
_VIDEO = {  # screen_video's action: (each run, what it did)
    "play": ("Plays", "Played"), "pause": ("Pauses", "Paused"), "mute": ("Mutes", "Muted"),
    "unmute": ("Unmutes", "Unmuted"), "volume": ("Sets the volume of", "Set the volume of"),
    "louder": ("Turns up", "Turned up"), "quieter": ("Turns down", "Turned down"),
    "skip": ("Skips through", "Skipped through"), "restart": ("Restarts", "Restarted"), "jump": ("Moves", "Moved"),
}
_DRAFTS = {  # each run, what it did
    "shopify_order_open": ("Opens an order being built on your screen", "Opened an order being built on your screen"),
    "shopify_order_build": ("Changes the order being built on your screen", "Changed the order being built on your screen"),
    "shopify_discount_open": ("Opens a discount being written on your screen", "Opened a discount being written on your screen"),
    "shopify_store_credit": ("Opens a store credit on your screen", "Opened a store credit on your screen"),
    "gmail_compose_open": ("Opens an email draft on your screen", "Opened an email draft on your screen"),
    "gmail_compose_fill": ("Changes the email draft on your screen", "Changed the email draft on your screen"),
}


def _text(value: Any, limit: int = 60) -> str:
    return " ".join(str(value or "").split())[:limit]


def _screen(found: Any) -> str:
    """"the Office TV": the screen a step names or its call reported, or "a screen" when neither does."""
    name = _text(found.get("screen") if isinstance(found, dict) else "", 40)
    return f"the {name}" if name else "a screen"


def will(tool: str, args: dict[str, Any] | None) -> str:
    """What a saved step will change each time the routine runs, from its own arguments."""
    args = args if isinstance(args, dict) else {}
    if tool == "work_note":
        return _WORK.get(str(args.get("action") or ""), ("Changes the work list", ""))[0] + " each run"
    if tool == "objective_open":
        return "Opens a new objective each run"
    if tool == "objective_note":
        return "Changes an objective each run"
    if tool == "screen_show":
        return f"Clears {_screen(args)} each run" if args.get("clear") is True else f"Puts it on {_screen(args)} each run"
    if tool == "screen_play":
        return f"Plays a video on {_screen(args)} each run"
    if tool == "screen_off":
        return f"Takes everything off {_screen(args)} each run"
    if tool == "screen_video":
        return _VIDEO.get(str(args.get("action") or ""), ("Works", ""))[0] + f" the video on {_screen(args)} each run"
    if tool == "screen_remote":
        return f"Opens the remote for {_screen(args)} each run"
    if tool == "close_screen":
        return "Clears your screen each run"
    if tool == "track_parcel":
        return "May start a Ship24 tracker, one shipment of the plan"
    if tool in _DRAFTS:
        return _DRAFTS[tool][0] + " each run"
    return ""


def did(tool: str, args: dict[str, Any] | None, result: Any) -> str:
    """What a step's call changed, from what it returned: the screen it named, the job's own title."""
    args = args if isinstance(args, dict) else {}
    result = result if isinstance(result, dict) else {}
    if tool == "work_note":
        record = result.get("job") if isinstance(result.get("job"), dict) else result.get("routine")
        title = _text(record.get("title") if isinstance(record, dict) else "")
        verb = _WORK.get(str(args.get("action") or ""), ("", "Changed"))[1]
        return f"{verb} on the work list: {title}" if title else f"{verb} on the work list"
    if tool in ("objective_open", "objective_note"):
        record = result.get("objective") if isinstance(result.get("objective"), dict) else result
        title = _text(record.get("title") if isinstance(record, dict) else "")
        verb = "Opened the objective" if tool == "objective_open" else "Noted on the objective"
        return f"{verb}: {title}" if title else verb
    if tool == "screen_show":
        return f"Cleared {_screen(result)}" if result.get("showing") == "nothing" else f"Put on {_screen(result)}"
    if tool == "screen_play":
        return f"Put a video on {_screen(result)}"
    if tool == "screen_off":
        return f"Took it off {_screen(result)}" if result.get("taken_off") else f"{_screen(result)[:1].upper()}{_screen(result)[1:]} was showing nothing already"
    if tool == "screen_video":
        return _VIDEO.get(str(args.get("action") or ""), ("", "Worked"))[1] + f" the video on {_screen(result)}"
    if tool == "screen_remote":
        return f"Opened the remote for {_screen(result)}"
    if tool == "close_screen":
        return "Cleared your screen"
    if tool == "track_parcel":
        return ("Started a Ship24 tracker: one shipment of the plan" if result.get("new_tracker")
                else "Started no new Ship24 tracker")
    if tool in _DRAFTS:
        return _DRAFTS[tool][1]
    return ""
