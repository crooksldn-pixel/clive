"""What he asked to see, said by the model: `asked_for` (DEC-073, the owner's ruling 25 of 8 October).

George, 8 October: "asking to see todays orders and to show a specific order s different to asking
to see a specific order and seeing the specific order + todays orders. in one instance it was asked,
in the other, the ai inferred it was needed when it wasnt specified."

The Mac cannot tell those apart from the cards: both turns read today's orders and order 1940. Only
the model knows which reads answer what he asked and which were how it found its way, and the Mac
must not find out by matching his words (MAP rule 7). So the model says it, here, in the same turn
as its reads: the records he asked for by their id or order number, and the lists he asked for by
kind. The call is recorded with the turn like any other, and `app/focus.py` reads it back from the
turn's calls to choose the cards: what he asked for always shows; what was not asked shows only when
it is about the same customer, order or thread; nothing else does.

What it promises: it reads nothing and changes nothing — no store, inbox, screen or record. It only
hands back, cleaned, what it was given: ids without spaces (a name is not an id, and is dropped), and
list kinds from a closed set. A turn that never calls it is chosen by DEC-069's rules, as before.
"""

from __future__ import annotations

import re
from typing import Any

from app.capabilities.families import CapabilityFamily, register
from app.tools.gate import Tier
from app.tools.registry import tool

ASKED_TOOL = "asked_for"
# The kinds of list he can ask to see, each the cards app/focus.py `list_kind` says it is.
LISTS = ("orders", "emails", "customers", "messages", "shipments", "returns", "numbers", "products")
MAX_RECORDS = 8
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
    """The list kinds given that are one of LISTS, in order, each once."""
    out: list[str] = []
    for item in value if isinstance(value, (list, tuple)) else []:
        text = str(item or "").strip().lower()
        if text in LISTS and text not in out:
            out.append(text)
    return out


@tool(
    name=ASKED_TOOL,
    description=(
        "Name what he asked to see, with your reads: records by id or order number, lists by kind. He sees "
        "those, then only what you read about the same customer, order or thread."
    ),
    input_schema={"type": "object", "properties": {
        "records": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_RECORDS},
        "lists": {"type": "array", "items": {"type": "string", "enum": list(LISTS)}, "maxItems": len(LISTS)},
    }},
    tier=Tier.GREEN,
    timeout_s=2.0,
)
async def asked_for(records: list[str] | None = None, lists: list[str] | None = None) -> dict[str, Any]:
    kept, kinds = records_of(records), lists_of(lists)
    out: dict[str, Any] = {"records": kept, "lists": kinds}
    given = records if isinstance(records, (list, tuple)) else []
    if any(not _ID.fullmatch(str(item or "").strip()) for item in given):
        out["note"] = "Only ids and order numbers are kept; a name is not one."
    return out
