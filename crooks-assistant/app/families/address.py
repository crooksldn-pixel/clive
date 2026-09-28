"""Correcting a delivery address with a thumb (brief §20).

    "How do I type a separate hall for you?"

is what the owner asked in the live session, garbled, on the eighth turn. He was asking how
to TYPE. The answer at the time was: on one card, the composer, which nothing led to and
which nothing said could be typed into. Everything else exact — a postcode, a house number,
a tracking number, a SKU — was a sentence into a microphone that had already produced four
recordings under 150 ms and two transcripts the normaliser had to repair.

A postcode is the worst possible thing to dictate. "Sefton" and "Seften" are both plausible;
"BS7 9AL" and "BS7 8AL" are both valid postcodes and one of them is somebody else's house.
The fixture world has the case in it verbatim — an order whose street has no number, and a
customer who emailed the number in — and until this file there was no way to put it right
with a finger: `order.change_address` armed the microphone and nothing else.

So: the address chip on an order OPENS a workspace. The parts of the current address are
already in the fields, because correcting a house number is not re-entering an address, and
the owner types over the part that is wrong. Everything else is the shape every other
workspace has (app/families/_workspace.py):

* Opening reads nothing — the order is already on the Mac — and stages nothing.
* A keystroke posts the FIELD'S NAME and the characters. The Mac validates them into its own
  copy and answers with the card again. The tablet has posted a value, not an argument.
* The gesture stages `shopify_order_shipping_address_set` with the arguments built HERE, from
  the Mac's copy, and `from_owner=True` — which is what that argument is for: the owner gave
  this address, not an email, so there is no message for the tool to check it against.
* Nothing here can apply anything. The write tool re-reads the order, merges, prints the
  difference, and the owner's hold on the card that comes back is what sends it.

The way in is a finger on the chip the Mac put on the order card. A sentence asking to
change an address is a model turn like every other, and the model stages the same write tool
itself.
"""

from __future__ import annotations

import re
from typing import Any

from app.commands import Command, Outcome, may_open
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command
from app.families import _workspace as ws

KIND = "address"
WRITE_TOOL = "shopify_order_shipping_address_set"

MAX_LINE = 120
# Loose on purpose. A postcode is not one format — GB, IE, US and CA all differ, and a
# validator that knows one of them refuses the other three. What this rejects is what cannot
# be a postcode anywhere: punctuation that belongs to a sentence, and lengths the write tool
# itself will not take (`shopify_order_shipping_address_set` caps it at 12).
_POSTCODE = re.compile(r"^[A-Z0-9][A-Z0-9 -]{1,11}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_PROVINCE = re.compile(r"^[A-Z0-9]{2,5}$")


def _line(limit: int):
    def clean(raw: str) -> tuple[str, str, str]:
        return " ".join(str(raw or "").split())[:limit], "ok", ""
    return clean


# TOO LONG IS INVALID, NEVER TRUNCATED. This is the one rule in this file worth stating
# twice: a value cut to fit is a different value, and for a code it is a plausible one
# belonging to somewhere else. "britain" truncated to two letters is BR, which is Brazil, and
# the card would have shown it as `ok`. Every cleaner here bounds the value it SHOWS — the
# card must not grow — and refuses what would not fit rather than shortening it into
# something that validates.
def _bounded(raw: str, *, limit: int, squash: bool) -> tuple[str, bool]:
    value = ("".join if squash else " ".join)(str(raw or "").split()).upper()
    return value[:limit], len(value) > limit


def _postcode(raw: str) -> tuple[str, str, str]:
    value, over = _bounded(raw, limit=12, squash=False)
    if not value:
        return "", "invalid", "a delivery needs a postcode"
    if over or not _POSTCODE.match(value):
        return value, "invalid", "that is not a postcode I can send"
    return value, "ok", ""


def _country(raw: str) -> tuple[str, str, str]:
    value, over = _bounded(raw, limit=2, squash=True)
    if not value:
        return "", "invalid", "two letters, like GB"
    if over or not _COUNTRY.match(value):
        return value, "invalid", "two letters, like GB — not the country's name"
    return value, "ok", ""


def _province(raw: str) -> tuple[str, str, str]:
    value, over = _bounded(raw, limit=5, squash=True)
    if not value:
        return "", "ok", ""            # most addresses need none
    if over or not _PROVINCE.match(value):
        return value, "invalid", "a short code, like ENG or CA"
    return value, "ok", ""


def _city(raw: str) -> tuple[str, str, str]:
    value = " ".join(str(raw or "").split())[:MAX_LINE]
    if not value:
        return "", "invalid", "a delivery needs a town"
    return value, "ok", ""


def _street(raw: str) -> tuple[str, str, str]:
    value = " ".join(str(raw or "").split())[:MAX_LINE]
    if not value:
        return "", "invalid", "a delivery needs a number and a street"
    return value, "ok", ""


# The fields, in the order a label is written. Every one of them carries a `kind` the
# renderer knows (web/ui.js FIELD_KINDS), which is what gives the postcode a keyboard with
# no autocorrect on it and the street one with capitals.
FIELDS: tuple[ws.Field, ...] = (
    ws.Field("name", "Recipient", kind="text", maxlength=80, rows=1, clean=_line(80)),
    ws.Field("address1", "Number and street", kind="address", maxlength=MAX_LINE, rows=2, clean=_street),
    ws.Field("address2", "Second line", kind="address", maxlength=MAX_LINE, rows=2, clean=_line(MAX_LINE)),
    ws.Field("city", "Town", kind="text", maxlength=MAX_LINE, rows=1, clean=_city),
    ws.Field("postcode", "Postcode", kind="code", maxlength=12, clean=_postcode),
    ws.Field("province_code", "Region code", kind="code", maxlength=5, clean=_province),
    ws.Field("country_code", "Country", kind="code", maxlength=2, clean=_country),
)

ACTIONS: tuple[ws.Action, ...] = (
    ws.Action(id="prepare", label="Prepare the change", command="address.stage", risk="red"),
    ws.Action(id="discard", label="Cancel", command="address.discard"),
)

# What the owner is told about typing, on the card, because he asked and nothing answered.
HOW = "Tap any line to type it. The parts already there are the address as it stands."


def _no_workspace() -> Outcome:
    return Outcome.refused("no_workspace", "There is no address open on this half to change.")


def _order_of(workspace: dict[str, Any]) -> str:
    return str(ws.fact(workspace, "order_id", "") or "")


def _held_order(ctx: CommandCtx, order_id: str) -> tuple[dict[str, Any] | None, Outcome | None]:
    """The order this conversation was shown and the Mac still holds.

    Two checks and two refusals, as everywhere else: permission is not the same question as
    whether the cache is warm, and the owner can do something about only one of them.
    """
    from app.memory import ENTITY
    from app.memory import current as memory

    if not order_id:
        return None, Outcome.refused("no_order", "There is no order open to change the address on.")
    if not may_open(ctx, "order", order_id):
        return None, Outcome.refused("not_this_conversation", "That is not an order this conversation has been shown.")
    held = memory().get(ENTITY, f"order:{order_id}", allow_stale=True)
    value = getattr(held, "value", None) if held is not None else None
    if not isinstance(value, dict):
        return None, Outcome.refused("order_not_held", "I am not holding that order any more — open it again.")
    return value, None


def _why_not(order: dict[str, Any]) -> str:
    """Why this order's address cannot be changed, in the owner's words. Empty when it can.

    Said BEFORE the fields are drawn rather than after the gesture: the write tool refuses a
    shipped order too, and being told by a card you have just filled in is the worst place to
    find out.
    """
    if order.get("cancelled_at"):
        return "That order is cancelled, so its address does not matter now."
    status = str(order.get("fulfillment") or "").upper()
    shipped = status in ("FULFILLED", "PARTIALLY_FULFILLED") or any(
        str(f.get("status") or "").upper() == "SUCCESS"
        for f in (order.get("fulfillments") or []) if isinstance(f, dict)
    )
    if shipped:
        return "That order has shipped. The address cannot be changed from here — contact the carrier."
    if not isinstance(order.get("shipping_address"), dict):
        return "That order has no delivery address to change."
    return ""


def _from_order(order: dict[str, Any]) -> dict[str, str]:
    """The address as it stands, as the fields' starting values.

    This is the whole reason the workspace is worth having. The live session's own case is an
    order with a street and no house number: with the current address in the boxes the owner
    types four characters, and with empty boxes he retypes a stranger's address from memory.
    """
    address = order.get("shipping_address") if isinstance(order.get("shipping_address"), dict) else {}
    lines = [str(line) for line in (address.get("lines") or []) if str(line or "").strip()]
    return {
        "name": str(address.get("name") or "")[:80],
        "address1": (lines[0] if lines else "")[:MAX_LINE],
        "address2": (lines[1] if len(lines) > 1 else "")[:MAX_LINE],
        "city": str(address.get("city") or "")[:MAX_LINE],
        "postcode": str(address.get("zip") or "").upper()[:12],
        "province_code": str(address.get("province_code") or "").upper()[:5],
        "country_code": str(address.get("country_code") or "").upper()[:2],
    }


def _blocked(workspace: dict[str, Any]) -> str:
    """Why this cannot be prepared yet. The order's own state first, then the fields."""
    standing = str(ws.fact(workspace, "why_not", "") or "")
    if standing:
        return standing
    for spec in FIELDS:
        if ws.status(workspace, spec.name) == "invalid":
            hint = str((workspace.get("hints") or {}).get(spec.name) or "")
            return f"{spec.label}: {hint or 'that is not something I can send to'}."
    if not ws.value(workspace, "address1").strip():
        return "Number and street: a delivery needs a number and a street."
    if not ws.value(workspace, "city").strip():
        return "Town: a delivery needs a town."
    if not ws.value(workspace, "postcode").strip():
        return "Postcode: a delivery needs a postcode."
    if not ws.value(workspace, "country_code").strip():
        return "Country: two letters, like GB."
    if _written(workspace) == str(ws.fact(workspace, "written", "") or ""):
        return "Nothing has changed yet. Type over the part that is wrong."
    return ""


def _written(workspace: dict[str, Any]) -> str:
    """The address on one line, as it would go on a label."""
    parts = [ws.value(workspace, name) for name in
             ("name", "address1", "address2", "city", "province_code", "postcode", "country_code")]
    return ", ".join(p for p in parts if p.strip())


def _surface(workspace: dict[str, Any]):
    blocked = _blocked(workspace)
    number = str(ws.fact(workspace, "order_number", "") or "")
    return ws.surface(
        workspace,
        fields=FIELDS,
        kicker="Delivery address · not changed",
        title=f"Where {number} is going".strip() if number else "Where this is going",
        subtitle=_written(workspace)[:120],
        facts=[
            {"label": "As it stands", "value": str(ws.fact(workspace, "written", "") or "—")},
            {"label": "As it would be", "value": _written(workspace) or "—",
             "tone": "" if blocked else "ok"},
        ],
        notes=[HOW],
        actions=ACTIONS,
        field_command="address.field",
        blocked=blocked,
        spoken="Nothing is changed until you hold the card that follows.",
    )


def _open(ctx: CommandCtx) -> Outcome:
    """The address chip on an order, tapped. Opens the workspace; reads nothing; stages
    nothing. The tablet posts an ORDER and nothing else."""
    order_id = ctx.arg("order_id") or ctx.arg("ref")
    order, refused = _held_order(ctx, order_id)
    if refused is not None:
        return refused
    assert order is not None
    why_not = _why_not(order)
    values = _from_order(order)
    number = str(order.get("order_number") or "")
    workspace = ws.open_workspace(
        ctx.branch, kind=KIND, workspace_id=ws.new_id("adr"), values=values,
        facts={"order_id": order_id, "order_number": number, "why_not": why_not,
               "written": ", ".join(v for v in values.values() if v.strip())},
    )
    ctx.session.issue(str(workspace["workspace_id"]))
    remember = getattr(ctx.session, "remember_pii", None)
    if callable(remember):
        remember(*[v for v in (values["name"], values["address1"], values["postcode"]) if v])
    # Still standing on the order: the composer and this are contexts on the branch, not
    # stops on the trail, so Back from either returns to the record it is about.
    ctx.branch.visit("order", order_id, f"#{number.lstrip('#')}" if number else "", tab="shipping")
    return Outcome(
        answer=why_not or "The address as it stands. Type over the part that is wrong.",
        surfaces=[_surface(workspace)],
        changed={"workspace_id": str(workspace["workspace_id"]), "order_id": order_id, "kind": KIND},
    )


def _field(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    name = ctx.arg("field")
    accepted, why = ws.type_into(workspace, FIELDS, name, str(ctx.args.get("value") or ""))
    if not accepted:
        return Outcome.refused("unknown_field", why)
    remember = getattr(ctx.session, "remember_pii", None)
    if callable(remember):
        remember(*[v for v in (ws.value(workspace, "name"), ws.value(workspace, "address1"),
                               ws.value(workspace, "postcode")) if v])
    return Outcome(answer="", surfaces=[_surface(workspace)],
                   changed={"workspace_id": str(workspace["workspace_id"]), "field": name,
                            "status": ws.status(workspace, name)})


def _stage(ctx: CommandCtx) -> Outcome:
    """Prepare the change. Every argument is built here, from the Mac's own copy.

    The tablet posted a workspace id. It did not post an address, and it could not: the write
    tool takes named parts, and the parts come from this dictionary — which only got them
    through each field's own `clean` on this side of the wire.
    """
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    ident = str(workspace["workspace_id"])
    if ident not in (getattr(ctx.session, "issued_ids", None) or frozenset()):
        return Outcome.refused("not_held", "That is not an address this conversation opened.")
    blocked = _blocked(workspace)
    if blocked:
        return Outcome.refused("not_ready", blocked)
    order_id = _order_of(workspace)
    if not may_open(ctx, "order", order_id):
        return Outcome.refused("not_held", "I do not have that order to hand; look it up again.")
    args: dict[str, Any] = {
        "order_id": order_id,
        "address1": ws.value(workspace, "address1"),
        "address2": ws.value(workspace, "address2"),
        "city": ws.value(workspace, "city"),
        "postcode": ws.value(workspace, "postcode"),
        "country_code": ws.value(workspace, "country_code"),
        "province_code": ws.value(workspace, "province_code"),
        "name": ws.value(workspace, "name"),
        # What this argument is for: the owner typed this, so there is no email for the tool
        # to check it against, and the card must say as much before the hold.
        "from_owner": True,
    }
    return Outcome(answer="", changed={
        "workspace_id": ident,
        "stage": {"tool": WRITE_TOOL, "args": args, "what": "change the delivery address"},
    })


def _discard(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    ws.discard(ctx.branch)
    return Outcome(answer="Gone. The address is as it was.",
                   changed={"workspace": None, "discarded": str(workspace["workspace_id"])})


# Touch only, all four: controls the owner can see on the card.
register_command(Command("address.open", "Open the delivery address to correct it", _open, voice=False))
register_command(Command("address.field", "Type into the delivery address", _field, voice=False))
register_command(Command("address.stage", "Prepare the address change for authorising", _stage, voice=False))
register_command(Command("address.discard", "Throw away the address being corrected", _discard, voice=False))
