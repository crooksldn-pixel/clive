"""A record put on one of the owner's screens by his own hand (round 12).

George, 29 September: "i also suggest we add physical ways of displaying to devices, whether that
be dragging an order, email, order card or objective by holding and a 'displays screen appearing'
which you can drag and drop the item to display too." So he presses and holds an order or an
objective on his app, a Displays tray rises with his screens in it, and he drops it on one — or
taps one, or picks one with the keyboard (web/lift.js). This is what the drop asks of the server
(`POST /displays/{screen_id}/show`, app/routes/displays.py).

It is the screen_show tool, run for his tap: the same call his spoken "put order 1938 on the office
TV" makes, through the one gated path every tool call takes (app/tools/dispatch.py). The gate
refuses a record this conversation was not issued (app/tools/gate.py, screen_show's issued-id
arguments); the tool refuses anyone but the owner, a screen not named exactly and a screen not yet
approved, reads the order or the objective from CLIVE's own records and builds from it only the
fields a screen may carry (app/displays/views.py); the store keeps it as it keeps everything a
screen shows. Nothing here builds a view, reads a record or writes the record of screens itself,
so a drop can put on a screen nothing a sentence could not.

The tap names the screen by its id — the tray drew it from the owner's own list (GET /displays) —
and the record by its kind and id, as the card it was held on carries them. The id is turned into
the screen's exact name here, which is what screen_show takes: that screen and no other, never the
nearest match. Before the tool is asked, the things a drop can meet that the page must put in its
own words are answered here, each with its own code: the conversation has gone or is another
login's, the screen has gone or is waiting for approval, the record was never shown to this
conversation. What the tool refuses after that is said in the tool's own words.

Objectives are issued as the home lists them (`issue_listed`, GET /objectives with the page's
conversation): the home showing an objective is this conversation being shown it, the rule a card
keeps for the rows on it (app/workspace.py _open). So an objective is held to the same rule as an
order here, with no exception for either.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import Request

from app.displays.store import store
from app.routes.actions import session_matches
from app.tools.display_tools import SHOW_TOOL
from app.tools.gate import Disposition, classify

# The kinds a screen shows that the owner can hold, and the screen_show argument each goes in.
# An email or a customer has no view a screen draws (app/displays/views.py), so neither is here:
# the page does not lift one, and this refuses one (422) before anything is looked at.
ARGUMENT = {"order": "order_id", "objective": "objective_id"}

MAX_REF = 200


class Refused(Exception):
    """A drop that put nothing on the screen: the answer's status, a code the page acts on, and
    the words it shows."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def _conversation(request: Request, session_id: str) -> Any:
    """The conversation the record was held in, and only if it is this caller's."""
    try:
        session = request.app.state.runtime.sessions.get(str(session_id)[:MAX_REF])
    except KeyError:
        raise Refused(409, "no_session", "CLIVE has let go of that conversation. Ask for it again, then hold it.") from None
    if not session_matches(session, request):
        raise Refused(403, "wrong_session", "That conversation belongs to another login.")
    return session


def _screen(screen_id: str) -> dict[str, Any]:
    """The screen the tray showed, while it is still there and approved."""
    screen = store().get(screen_id)
    if screen is None:
        raise Refused(404, "not_found", "That screen isn't there any more.")
    if screen.get("paired", True) is not True:
        raise Refused(409, "not_approved", f"The {screen['name']} hasn't been approved yet. Tell CLIVE the code it "
                                           "shows, then try again.")
    return screen


def _not_issued(kind: str) -> Refused:
    what = "That order wasn't" if kind == "order" else "That objective wasn't"
    return Refused(403, "not_issued", f"{what} shown in this conversation, so it can't go on a screen from here. "
                                      "Ask CLIVE for it, then hold it again.")


# How app/tools/dispatch.py and app/tools/registry.py say that a tool raised something that is not
# a sentence, or ran out of time. Their words are for the model; these two are put in the owner's.
_UNEXPECTED = "failed unexpectedly"
_TOO_LONG = "did not respond within"


def _words(said: str, call: Any, name: str) -> str:
    """Why nothing went up, as the owner reads it: the tool's own sentence where it wrote one."""
    if call is None or _UNEXPECTED in said:
        return f"That couldn't be put on the {name}."
    error = str(getattr(call, "error", "") or "")
    if _TOO_LONG in error:
        return f"That took too long to read, so nothing went on the {name}. Try again."
    return error[:300] or f"That couldn't be put on the {name}."


async def put_held(request: Request, screen_id: str, kind: str, ref: str, *, session_id: str) -> dict[str, Any]:
    """Put the record the owner held on the screen he dropped it on, or say exactly why not.
    Returns what the screen now shows and whether it is on; raises Refused otherwise."""
    from app.tools.dispatch import dispatch

    argument = ARGUMENT.get(kind)
    if argument is None:
        raise Refused(422, "not_screenable", "A screen shows orders and objectives.")
    session = _conversation(request, session_id)
    screen = _screen(screen_id)
    args = {"screen": screen["name"], argument: str(ref)[:MAX_REF]}
    # The gate's own decision, asked first so its refusal can be said in the owner's words and
    # before anything is read; dispatch asks it again, and nothing runs that it refuses.
    if classify(SHOW_TOOL, args, session.issued_ids).disposition is Disposition.DENY:
        raise _not_issued(kind)
    runtime = request.app.state.runtime
    calls: list[Any] = []
    said = await dispatch(SHOW_TOOL, args, session=session, timeout_s=float(runtime.settings.tool_timeout_s), calls=calls)
    call = calls[-1] if calls else None
    result = call.result if call is not None and call.ok and isinstance(call.result, dict) else None
    if result is None:
        raise Refused(409, "not_shown", _words(said, call, screen["name"]))
    return {"ok": True, "screen": str(result.get("screen") or screen["name"]), "screen_id": screen["id"],
            "showing": str(result.get("showing") or ""), "on": bool(result.get("on"))}


def issue_listed(request: Request, session_id: str, refs: Iterable[str]) -> None:
    """The owner's home lists these objectives to the conversation its page is in (web/alpha.js),
    so they are issued to it: an objective he can see on his home is one this conversation has
    been shown, and one he may hold and put on a screen. The conversation is made if it is not
    there yet, as GET /branches makes it when the page opens (app/routes/branches.py); it is read
    without being kept alive otherwise, so the home asking every few seconds does not keep a
    conversation open that would have closed. One that is another login's is left untouched."""
    sid = str(session_id or "").strip()[:MAX_REF]
    ids = [str(r) for r in refs if r]
    if not sid or not ids:
        return
    sessions = request.app.state.runtime.sessions
    try:
        session = sessions.peek(sid)
    except KeyError:
        session = sessions.get_or_create(sid)
    if session_matches(session, request):
        session.issue(*ids)
