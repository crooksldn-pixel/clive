"""Putting the screen away: "close that", "clear the screen", "put it away".

Round 12. The owner's own close clears his screen, and so does a new subject; a question
answered in words now leaves the screen he is working on where it is (app/screen.py). That made
one thing he says impossible: asking CLIVE to take it away. Every sentence is the model's, so
the model needs the hands for it, and this is them.

`close_screen` clears this half's screen — the Mac's copy of it (`Branch.last_ui`), which the
turn then reports as `screen: "cleared"` so the tablet goes back to the orb. Nothing is read and
nothing is written anywhere else: no store, no inbox, no TV (his TVs are `screen_off`'s). The
cursor and the trail stay, and what the screen showed stays on `Branch.shown_before`, so "pull
that back up" (app/tools/show_again.py) brings it straight back.
"""

from __future__ import annotations

from typing import Any

from app import screen
from app.capabilities.families import CapabilityFamily, register
from app.tools.context import acting_branch, current_session
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

CLOSE_TOOL = "close_screen"

# Named in the family table like every tool the model is offered (tests/test_families.py).
register(CapabilityFamily(
    key="put_away", label="Put it away", area="system",
    what="close what is on your screen and go back to the orb; nothing in the shop changes",
    tools=(CLOSE_TOOL,),
    state="READY", detail="ready",
))


def _label(card: dict[str, Any]) -> str:
    data = card.get("data") if isinstance(card.get("data"), dict) else {}
    for key in ("order_number", "title", "name", "subject"):
        if data.get(key):
            return str(data[key])[:60]
    return screen.kind(card).replace("_", " ")


@tool(
    name=CLOSE_TOOL,
    description=(
        "Close what is on the owner's own screen and go back to the orb: for 'close that', 'clear the "
        "screen', 'put it away'. Not his TVs (screen_off). Changes nothing else."
    ),
    input_schema={"type": "object", "properties": {}},
    tier=Tier.GREEN,
    timeout_s=2.0,
)
async def close_screen() -> dict[str, Any]:
    session = current_session()
    if session is None:
        raise ToolError("There is no conversation to close anything in.")
    branch = session.branch(acting_branch(session))
    was = [_label(card) for card in screen.showing(branch) if screen.is_subject(card)]
    branch.cleared(branch.last_answer, branch.last_question)
    return {"closed": True, "was": was[:4] or "nothing was up"}
