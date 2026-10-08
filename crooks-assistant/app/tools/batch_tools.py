"""Bulk changes: the same reviewed write tools, applied to every member of a working set.

A batch tool takes a set id (never a list of ids: the Mac holds the membership) and says
which write tool to prepare for each member, with what arguments. The batch engine
(app/actions/batch.py) does the rest: a fresh read per member, an exclusion with its reason
where the change does not apply, one card, one gesture, one proposal committed and proven
per member, and a count. Nothing here sends anything.

The first four: tags on and off orders, threads out of the inbox (archived, or junked since
ruling 27 of DEC-071), drafts to customers. A
refund, a cancel, a fulfilment, a stock change stay single until this pattern has proved
itself on the tablet; the shape below is ready for them.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.actions.batch import MAX_BATCH
from app.analytics import sets as working_sets
from app.tools.context import current_session
from app.tools.gate import Tier
from app.tools.registry import BatchPlan, BatchSpec, ToolError, tool

# --------------------------------------------------------------------------- the set


def _set(set_id: str, *, kinds: tuple[str, ...]) -> Any:
    session = current_session()
    ws = working_sets.get(session, str(set_id or "")) if session is not None else None
    if ws is None:
        raise ToolError(f"There is no working set {set_id} in this conversation; list the items first (commerce_query, gmail_search or email_query) and use the set id it returns.")
    if ws.kind not in kinds:
        raise ToolError(f"Set {ws.set_id} holds {ws.kind}; this change applies to {' or '.join(kinds)}. Narrow to a set of {kinds[0]} first.")
    if ws.count > MAX_BATCH:
        raise ToolError(f"Set {ws.set_id} holds {ws.count} {ws.kind}; a batch takes at most {MAX_BATCH}. Narrow it first (a period, a filter) and try again.")
    if ws.count == 0:
        raise ToolError(f"Set {ws.set_id} is empty.")
    return ws


# --------------------------------------------------------------------------- tags


def _present_tags(batch) -> dict[str, Any]:
    tags = [str(t) for t in batch.summary.get("tags") or []]
    remove = batch.operation.startswith("batch_order_tags_remove")
    if batch.undo_of:
        return {"title": "Put the tags back on" if remove else "Take the tags back off", "detail": "Reverses exactly what the batch did, order by order.", "confirm_label": "Undo all", "undone_title": "Tags put back" if remove else "Tags taken back off"}
    return {
        "title": ("Remove tags from" if remove else "Add tags to") + f" {len(batch.eligible)} orders",
        "summary": ", ".join(tags),
        "detail": ("Taken off each order's tags; nothing else changes." if remove else "Added to each order's tags; nothing is removed.") + " Each order is checked first and read back afterwards.",
        "done_title": "Tags removed" if remove else "Tags added",
        "target": "Apply to all",
    }


@tool(
    name="batch_order_tags_add",
    description="Add tags to every order in a working set (≤50): one card, each order checked and proven on its own.",
    input_schema={
        "type": "object",
        "properties": {
            "set_id": {"type": "string", "description": "A set of orders."},
            "tags": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string", "maxLength": 40}},
        },
        "required": ["set_id", "tags"],
    },
    tier=Tier.AMBER,
    issued_id_args=("set_id",),
    timeout_s=30.0,
    batch=BatchSpec(operation="batch_order_tags_add", child_tool="shopify_order_tags_add", set_kinds=("orders",), present=_present_tags, verb="Tagged", noun="orders"),
)
async def batch_order_tags_add(set_id: str, tags: list) -> BatchPlan:
    from app.tools.shopify_tools import _clean_tags

    wanted = _clean_tags(tags)
    ws = _set(set_id, kinds=("orders",))
    return BatchPlan(set_id=ws.set_id, child_tool="shopify_order_tags_add", child_args=lambda ref: {"order_id": ref, "tags": list(wanted)}, label=f"add tags {', '.join(wanted)}", summary={"tags": wanted, "read_back": f"tag all {ws.count} orders {', '.join(wanted)}"})


@tool(
    name="batch_order_tags_remove",
    description="Take tags off every order in a working set (≤50) that has them.",
    input_schema={
        "type": "object",
        "properties": {
            "set_id": {"type": "string", "description": "A set of orders."},
            "tags": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string", "maxLength": 40}},
        },
        "required": ["set_id", "tags"],
    },
    tier=Tier.AMBER,
    issued_id_args=("set_id",),
    timeout_s=30.0,
    batch=BatchSpec(operation="batch_order_tags_remove", child_tool="shopify_order_tags_remove", set_kinds=("orders",), present=_present_tags, verb="Took the tags off", noun="orders"),
)
async def batch_order_tags_remove(set_id: str, tags: list) -> BatchPlan:
    from app.tools.shopify_tools import _clean_tags

    wanted = _clean_tags(tags)
    ws = _set(set_id, kinds=("orders",))
    return BatchPlan(set_id=ws.set_id, child_tool="shopify_order_tags_remove", child_args=lambda ref: {"order_id": ref, "tags": list(wanted)}, label=f"remove tags {', '.join(wanted)}", summary={"tags": wanted, "read_back": f"take {', '.join(wanted)} off all {ws.count} orders"})


# --------------------------------------------------------------------------- the inbox


def _threads(n: int) -> str:
    return f"{n} thread" if n == 1 else f"{n} threads"


def _present_archive(batch) -> dict[str, Any]:
    if batch.undo_of:
        return {"title": "Put them all back in the inbox", "detail": "Each thread goes back where it was.", "confirm_label": "Undo all", "undone_title": "Back in the inbox"}
    return {
        "title": f"Archive {_threads(len(batch.eligible))}",
        "detail": "Each leaves the inbox and stays in All Mail and in search. Undo puts them all back.",
        "done_title": "Archived",
        "target": "Archive all",
    }


@tool(
    name="batch_email_archive",
    description="Archive every thread in a working set of emails (≤50) still in the inbox.",
    input_schema={"type": "object", "properties": {"set_id": {"type": "string", "description": "A set of emails."}}, "required": ["set_id"]},
    tier=Tier.AMBER,
    issued_id_args=("set_id",),
    timeout_s=30.0,
    batch=BatchSpec(operation="batch_email_archive", child_tool="gmail_thread_archive", set_kinds=("emails",), present=_present_archive, verb="Archived", noun="threads"),
)
async def batch_email_archive(set_id: str) -> BatchPlan:
    ws = _set(set_id, kinds=("emails",))
    return BatchPlan(set_id=ws.set_id, child_tool="gmail_thread_archive", child_args=lambda ref: {"thread_id": ref}, label="archive", summary={"read_back": f"archive all {ws.count} threads"})


# Ruling 27 (DEC-071): junk a set of threads on one card and one hold. Each thread is checked on its
# own by gmail_thread_junk — still in the inbox, not already in Spam, and not from a customer of the
# shop (nor from anyone the shop could not be asked about) — and a thread that fails a check is left
# out with its reason before the card is shown. The tool is RED, so the batch is a hold however few.


def _present_junk(batch) -> dict[str, Any]:
    if batch.undo_of:
        return {"title": "Not junk: put them all back in the inbox", "detail": "Each thread comes out of Spam and back to the inbox.", "confirm_label": "Undo all", "undone_title": "Back in the inbox"}
    return {
        "title": f"Junk {_threads(len(batch.eligible))}",
        "detail": "Each moves to Spam. Gmail learns from it, so their next email may go to Spam too; Gmail empties Spam after 30 days. Undo puts them all back.",
        "done_title": "Junked",
        "target": "Junk all",
    }


@tool(
    name="batch_email_junk",
    description="Junk every thread in a working set of emails (≤50) still in the inbox; never a customer's.",
    input_schema={"type": "object", "properties": {"set_id": {"type": "string", "description": "A set of emails."}}, "required": ["set_id"]},
    tier=Tier.RED,
    issued_id_args=("set_id",),
    timeout_s=30.0,
    batch=BatchSpec(operation="batch_email_junk", child_tool="gmail_thread_junk", set_kinds=("emails",), present=_present_junk, verb="Junked", noun="threads"),
)
async def batch_email_junk(set_id: str) -> BatchPlan:
    ws = _set(set_id, kinds=("emails",))
    return BatchPlan(set_id=ws.set_id, child_tool="gmail_thread_junk", child_args=lambda ref: {"thread_id": ref}, label="junk", summary={"read_back": f"junk all {ws.count} threads"})


# --------------------------------------------------------------------------- drafts

# The words the Mac fills in per customer, from the order it reads: nothing else is
# substituted, and a placeholder that is not one of these is refused before any read.
PLACEHOLDERS = ("first_name", "order_number", "order_age_days")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
MAX_CAMPAIGN = 50


def _check_template(text: str, *, allowed: tuple[str, ...]) -> None:
    for name in _PLACEHOLDER.findall(str(text or "")):
        if name not in allowed:
            raise ToolError(f"{{{name}}} is not a placeholder I can fill; use {', '.join('{' + p + '}' for p in allowed)}.")


def fill(template: str, values: dict[str, str]) -> str:
    """Deterministic substitution: only the named placeholders, only from what the Mac read."""
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), str(template or ""))


def _age_days(placed_at: str, *, tz: str = "Europe/London") -> int | None:
    try:
        placed = datetime.fromisoformat(str(placed_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    now = datetime.now(ZoneInfo(tz))
    return max(0, (now.date() - placed.astimezone(ZoneInfo(tz)).date()).days)


async def _draft_args(ref: str, subject: str, body: str, kind: str) -> dict[str, Any]:
    """The child's arguments for one member: the template filled from the order (or the
    customer) as the Mac reads it now. The recipient is the child's to decide, from Shopify."""
    values: dict[str, str] = {}
    if kind == "orders":
        from app.context.order import order_digits
        from app.tools.gmail_writes import _first_name, _order_customer
        from app.tools.shopify_tools import hydrator

        order = await hydrator().order(ref, budget_s=0.0)
        customer = await _order_customer(order_id=ref)
        values["first_name"] = _first_name(str(customer.get("name") or ""), str(customer.get("email") or ""))
        # The number as the owner says it: "1938" from "#1938" or "CROOKS-1938".
        number = str(order.get("order_number") or "")
        values["order_number"] = order_digits(number) or number.lstrip("#")
        age = _age_days(str(order.get("placed_at") or ""))
        values["order_age_days"] = str(age) if age is not None else ""
        return {"order_id": ref, "subject": fill(subject, values), "body": fill(body, values)}
    from app.tools.gmail_writes import _first_name, _order_customer

    customer = await _order_customer(customer_id=ref)
    values["first_name"] = _first_name(str(customer.get("name") or ""), str(customer.get("email") or ""))
    return {"customer_id": ref, "subject": fill(subject, values), "body": fill(body, values)}


def _preview_draft(prepared) -> dict[str, Any]:
    s = prepared.summary
    return {"to": str(s.get("to_line") or ""), "subject": str(s.get("subject") or ""), "body": str(s.get("body") or "")}


def _present_drafts(batch) -> dict[str, Any]:
    if batch.undo_of:
        return {"title": f"Delete the {len(batch.eligible)} drafts", "detail": "Each draft this saved is deleted from Gmail.", "confirm_label": "Undo all", "undone_title": "Drafts deleted"}
    s = batch.summary
    per = "order" if batch.set_kind == "orders" else "customer"
    return {
        "title": f"Save {len(batch.eligible)} drafts",
        # The template, filled in for each member by the Mac; the card shows one filled
        # (the preview) and keeps the template behind a fold.
        "body": str(s.get("body") or ""),
        "detail": f"One draft per {per}, saved in Gmail drafts. Nothing is sent; sending is a separate step, one at a time.",
        "done_title": "Drafts saved",
        "target": "Save all",
    }


# One schema for both email batches: the same set, the same template, the same bounds. The
# difference between them is whether the messages go, and that is the tool's name and tier.
_CAMPAIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "set_id": {"type": "string", "description": "A set of orders or customers."},
        "subject": {"type": "string", "maxLength": 120, "description": "One plain line; placeholders allowed."},
        "body": {"type": "string", "maxLength": 2000, "description": "Plain text with placeholders; the sign-off is added."},
    },
    "required": ["set_id", "subject", "body"],
}


def _present_sends(batch) -> dict[str, Any]:
    if batch.undo_of:
        # There is no undo for a sent email, and there must never look like one.
        return {"title": "Nothing to undo", "detail": "An email that has gone cannot be recalled.", "confirm_label": "", "undone_title": ""}
    s = batch.summary
    per = "order" if batch.set_kind == "orders" else "customer"
    return {
        "title": f"SEND {len(batch.eligible)} emails",
        "body": str(s.get("body") or ""),
        "detail": (
            f"One email per {per}, going out from team@crooksldn.com. Each is the exact message "
            "prepared below and shown on this card — it is not written again when it goes. "
            "There is no undo: an email that has gone has gone."
        ),
        "done_title": "Emails sent",
        "target": "Send all",
    }


@tool(
    name="batch_email_send",
    description=(
        "As batch_email_drafts, but the emails GO. Prepared and shown first; each goes exactly "
        "as shown; no undo. Only when the owner asked for them to be sent."
    ),
    input_schema=_CAMPAIGN_SCHEMA,
    # RED because it is irreversible and it leaves the building. The batch engine takes the
    # tool's tier as a floor (app/actions/batch.py batch_risk), so this is always the
    # hold-and-drag gesture however few members the set has.
    tier=Tier.RED,
    issued_id_args=("set_id",),
    timeout_s=30.0,
    batch=BatchSpec(operation="batch_email_send", child_tool="gmail_send_new", set_kinds=("orders", "customers"), present=_present_sends, verb="Sent to", noun="", preview=_preview_draft),
)
async def batch_email_send(set_id: str, subject: str, body: str) -> BatchPlan:
    """Prepare one email per member. Nothing is sent here, and nothing is written twice.

    Each member's message is built ONCE, at preparation, by the same child write tool a
    single email goes through — which reads the customer from Shopify, builds the MIME, and
    freezes it in the proposal's execution arguments. The card prints one of those exact
    messages. When the owner's gesture commits the batch, the engine sends the frozen
    arguments: the template is not filled again, the customer is not read again, and what
    goes is what was on the card. See app/actions/batch.py.
    """
    from app.tools.gmail_writes import clean_body, clean_subject

    ws = _set(set_id, kinds=("orders", "customers"))
    allowed = PLACEHOLDERS if ws.kind == "orders" else ("first_name",)
    _check_template(subject, allowed=allowed)
    _check_template(body, allowed=allowed)
    clean_subject(subject)
    clean_body(body)

    def child_args(ref: str):
        return _draft_args(ref, subject, body, ws.kind)

    return BatchPlan(
        set_id=ws.set_id, child_tool="gmail_send_new", child_args=child_args, label="send campaign",
        summary={"subject": " ".join(str(subject).split())[:120], "body": str(body)[:2000],
                 "read_back": f"send an email to each of the {ws.count} {ws.kind}"},
    )


@tool(
    name="batch_email_drafts",
    description="One Gmail draft per order (or per customer, for a set of customers) in a working set (≤50), from a template CLIVE fills: {first_name}, {order_number}, {order_age_days}. Nothing is sent.",
    input_schema=_CAMPAIGN_SCHEMA,
    tier=Tier.AMBER,
    issued_id_args=("set_id",),
    timeout_s=30.0,
    batch=BatchSpec(operation="batch_email_drafts", child_tool="gmail_draft_new", set_kinds=("orders", "customers"), present=_present_drafts, verb="Saved drafts for", noun="", preview=_preview_draft),
)
async def batch_email_drafts(set_id: str, subject: str, body: str) -> BatchPlan:
    from app.tools.gmail_writes import clean_body, clean_subject

    ws = _set(set_id, kinds=("orders", "customers"))
    allowed = PLACEHOLDERS if ws.kind == "orders" else ("first_name",)
    _check_template(subject, allowed=allowed)
    _check_template(body, allowed=allowed)
    # The template is held to the same rules as a single email (plain, bounded, links only
    # where the store links), before any customer is read.
    clean_subject(subject)
    clean_body(body)

    def child_args(ref: str):
        return _draft_args(ref, subject, body, ws.kind)

    return BatchPlan(set_id=ws.set_id, child_tool="gmail_draft_new", child_args=child_args, label="draft campaign", summary={"subject": " ".join(str(subject).split())[:120], "body": str(body)[:2000], "read_back": f"save a draft for each of the {ws.count} {ws.kind}"})
