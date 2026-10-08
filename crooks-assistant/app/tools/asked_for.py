"""What he asked to see, said by the model: `asked_for` (DEC-073, the owner's ruling 25 of 8 October).

George, 8 October: "asking to see todays orders and to show a specific order s different to asking
to see a specific order and seeing the specific order + todays orders. in one instance it was asked,
in the other, the ai inferred it was needed when it wasnt specified."

The Mac cannot tell those apart from the cards: both turns read today's orders and order 1940. Only
the model knows which reads answer what he asked and which were how it found its way, and the Mac
must not find out by matching his words (MAP rule 7). So the model says it, here, in the same turn
as its reads: the records he asked for by their id or order number, and the lists he asked for by
the read that drew them: the tool's name and the words the model gave it ("gmail_search cap"), so
that naming today's emails never brings in the search that found a customer's thread (the review of
DEC-073, note 2). The call is recorded with the turn like any other, and `app/focus.py` reads it back from the
turn's calls to choose the cards: what he asked for always shows; what was not asked shows only when
it is about the same customer, order or thread; nothing else does.

What it promises: it reads nothing and changes nothing — no store, inbox, screen or record. It only
hands back, cleaned, what it was given: ids without spaces (a name is not an id, and is dropped), and
lists named by a read tool this registry offers, with at most MAX_WORDS characters of its words. A turn that never calls it is chosen by DEC-069's rules, as before.
"""

from __future__ import annotations

import re
from typing import Any

from app.capabilities.families import CapabilityFamily, register
from app.tools.gate import Tier
from app.tools.registry import get, normalise_tool_name, tool

ASKED_TOOL = "asked_for"
MAX_RECORDS = 8
MAX_LISTS = 8
# The words a read was given, as far as naming it needs: a query, a name, a number of days.
MAX_WORDS = 80
# An id or an order number as a tool returned it: a gid, a Gmail thread id, "#1940", "obj_…", a
# conversation's chat_id. No spaces: anything with one is words, not an id, and is not kept.
_ID = re.compile(r"^[A-Za-z0-9#][A-Za-z0-9_:#./@+=-]{0,79}$")

# Named in the family table like every tool the model is offered (tests/test_families.py).
register(CapabilityFamily(
    key="asked_for", label="What you asked to see", area="system",
    what="the screen shows what you asked for, and only what is about the same customer, order or thread",
    tools=(ASKED_TOOL,),
    state="READY", detail="ready",
))


def records_of(value: Any) -> list[str]:
    """The ids and order numbers given, in order, each once; anything that is not one is left out."""
    out: list[str] = []
    for item in value if isinstance(value, (list, tuple)) else []:
        text = str(item or "").strip()
        if _ID.fullmatch(text) and text not in out:
            out.append(text)
    return out[:MAX_RECORDS]


def lists_of(value: Any) -> list[str]:
    """The lists given, each named by the read that drew it ("<tool> <the words it was given>"),
    in order, each once; a name that is not a read tool this registry offers is left out."""
    out: list[str] = []
    for item in value if isinstance(value, (list, tuple)) else []:
        text = _named_read(item)
        if text and text not in out:
            out.append(text)
    return out[:MAX_LISTS]


def _named_read(item: Any) -> str:
    """One list as "<tool> <words>", cleaned; "" when it does not start with a read tool's name."""
    name, _, words = " ".join(str(item or "").split()).partition(" ")
    name = normalise_tool_name(name)
    return f"{name} {words[:MAX_WORDS]}".strip() if _a_read(name) else ""


def _a_read(name: str) -> bool:
    """Whether this is a tool that reads: registered, and neither a write nor a batch."""
    if not name or name == ASKED_TOOL:
        return False
    try:
        spec = get(name)
    except KeyError:
        return False
    return spec.write is None and spec.batch is None


@tool(
    name=ASKED_TOOL,
    description=(
        "Name what he asked to see, with your reads: records by id or order number; lists by the read that "
        "drew them, its tool name then the words you gave it ('gmail_search cap'). He sees those, then only "
        "what you read about the same customer, order or thread."
    ),
    input_schema={"type": "object", "properties": {
        "records": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_RECORDS},
        "lists": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_LISTS},
    }},
    tier=Tier.GREEN,
    timeout_s=2.0,
)
async def asked_for(records: list[str] | None = None, lists: list[str] | None = None) -> dict[str, Any]:
    kept, kinds = records_of(records), lists_of(lists)
    out: dict[str, Any] = {"records": kept, "lists": kinds}
    given = records if isinstance(records, (list, tuple)) else []
    notes = []
    if any(not _ID.fullmatch(str(item or "").strip()) for item in given):
        notes.append("Only ids and order numbers are kept; a name is not one.")
    if any(not _named_read(item) for item in (lists if isinstance(lists, (list, tuple)) else [])):
        notes.append("A list is named by the read that drew it: its tool name, then the words you gave it.")
    if notes:
        out["note"] = " ".join(notes)
    return out
