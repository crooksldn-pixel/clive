"""One customer's history as one story, newest first.

George, 2 October: "Clive should understand the history of this customer, through emails where
they are related, to orders and the whole broader Clive ecosystem."

The customer card already had three tabs that each told a third of it — the orders, the inbox, a
count — and nothing at all of what CLIVE itself knew: that an order was packed on the studio TV,
that a refund went through CLIVE yesterday and whether it landed, that one of the owner's
objectives is about them. This folds every one of those into one list of rows, each with when it
happened, what it was, and where it came from:

    Shopify     their orders (the newest five), each one's shipping, refunds (and whether the
                money went back), cancellation, return and staff note
    Gmail       threads from them, to them, and naming one of their orders — one inbox read,
                the one the customer card already made, over a year (app/context/order.py)
    work list   who claimed, packed and finished each of their orders (app/work/store.py)
    screens     orders of theirs marked packed on a screen (app/displays/store.py)
    CLIVE       the changes CLIVE made to their orders, and whether each was proven
                (the action ledger, which holds ids and outcomes, never content)
    objectives  the owner's objectives that name them or one of their orders — the owner's
                own records, so only when the owner is the one asking

It reads only: CLIVE's own records on this machine and what the customer read already holds. No
Shopify or Gmail call is made here, so the timeline costs the customer card nothing it did not
already spend. A source that is not there says so in `sources`, rather than looking empty.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from app.customers import when as when_words

log = logging.getLogger("crooks.customers.history")

MAX_ROWS = 24
MAX_TEXT = 160
# The tail of the action ledger read for a customer's changes: the last few months of a busy shop.
LEDGER_TAIL_BYTES = 768_000
WORK_RECORD_LINES = 600
# What the ledger's terminal states say happened. A change that never ran is not history.
_LEDGER_SAID = {"VERIFIED": "proven", "UNVERIFIED": "sent, not proven"}
_OPERATION_WORDS = {
    "refund_create": "refunded", "order_cancel": "cancelled", "order_note_append": "added a note to",
    "order_tags_add": "tagged", "order_tags_remove": "took tags off", "order_shipping_address_set": "changed the address on",
    "fulfillment_create": "fulfilled", "fulfillment_tracking_set": "set the tracking on", "order_add_item": "added an item to",
    "order_add_custom_item": "added a custom item to", "gmail_send_new": "emailed them about", "gmail_send_reply": "replied about",
    "gmail_draft_new": "drafted an email about", "gmail_draft_reply": "drafted a reply about",
    "checkout_link_send": "sent them a checkout link", "draft_order_complete": "created an order for",
    "store_credit_credit": "put store credit on",
}
_WORK_SAID = {"packed": "Packed", "claimed": "Claimed", "done": "Finished", "flagged": "Flagged", "released": "Gave back",
              "cancelled": "Job cancelled for"}


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def _moment(value: Any) -> datetime | None:
    """Any stamp the sources use — Shopify's ISO, an email's Date header, a ledger epoch — in UTC."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), UTC)
    text = str(value)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    if moment is None:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC)


def _number(text: Any) -> str:
    digits = str(text or "").rsplit("-", 1)[-1].lstrip("#")
    return f"#{digits}" if digits else ""


def _row(at: Any, kind: str, what: str, detail: str = "", *, ref: str = "", ref_kind: str = "", source: str) -> dict[str, Any]:
    moment = _moment(at)
    return {"at": moment.isoformat().replace("+00:00", "Z") if moment else "", "_t": moment, "kind": kind,
            "what": _clip(what, 120), "detail": _clip(detail), "ref": ref, "ref_kind": ref_kind, "source": source}


# --------------------------------------------------------------------------- Shopify


def _order_rows(history: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for order in history.get("recent") or []:
        if not isinstance(order, dict):
            continue
        number, ref = _number(order.get("order_number")), str(order.get("order_id") or "")
        bits = [order.get("total"), order.get("items_brief")]
        if order.get("return_status"):
            bits.append(f"return {str(order['return_status']).replace('_', ' ').lower()}")
        out.append(_row(order.get("placed_at"), "ordered", f"Ordered {number}", " · ".join(_money(b) for b in bits if b),
                        ref=ref, ref_kind="order", source="Shopify"))
        if order.get("cancelled_at"):
            out.append(_row(order["cancelled_at"], "cancelled", f"Cancelled {number}", ref=ref, ref_kind="order", source="Shopify"))
        for shipment in order.get("shipped") or []:
            carrier = shipment.get("carrier") or ""
            status = str(shipment.get("status") or "").replace("_", " ").lower()
            out.append(_row(shipment.get("at"), "shipped", f"Shipped {number}", " · ".join(p for p in (carrier, status) if p),
                            ref=ref, ref_kind="order", source="Shopify"))
        for refund in order.get("refunds") or []:
            out.append(_row(refund.get("at"), "refund", f"Refunded {_money(refund.get('amount'))} on {number}",
                            str(refund.get("landed") or ""), ref=ref, ref_kind="order", source="Shopify"))
        if order.get("note"):
            # A staff note has no date of its own: it sits with the order it is on.
            out.append(_row(order.get("placed_at"), "note", f"Note on {number}", str(order["note"]), ref=ref, ref_kind="order",
                            source="Shopify"))
    return out


def _money(value: Any) -> str:
    """"60.00 GBP" as "£60.00"; anything else as it is."""
    text = str(value or "")
    found = re.fullmatch(r"(-?\d+(?:\.\d+)?) GBP", text)
    return f"£{float(found.group(1)):,.2f}" if found else text


# --------------------------------------------------------------------------- the inbox


def _email_rows(threads: list[dict[str, Any]], *, email: str, numbers: list[str], ours: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for thread in threads:
        sender = str(thread.get("from_email") or "").strip().lower()
        subject = _clip(thread.get("subject") or "(no subject)", 80)
        text = f"{thread.get('subject', '')} {thread.get('snippet', '')}"
        named = [n for n in numbers if n and re.search(rf"(?<!\d){re.escape(n)}(?!\d)", text)]
        if email and sender == email:
            what, kind = f"Emailed us: {subject}", "email_in"
        elif ours and sender == ours:
            what, kind = f"We emailed them: {subject}", "email_out"
        elif named:
            what, kind = f"{_clip(thread.get('from') or sender, 40)} wrote about #{named[0]}: {subject}", "email_about"
        elif email:
            what, kind = f"Email naming them: {subject}", "email_about"
        else:
            continue
        out.append(_row(thread.get("date"), kind, what, _clip(thread.get("snippet"), 140), ref=str(thread.get("thread_id") or ""),
                        ref_kind="email_thread", source="Gmail"))
    return out


# --------------------------------------------------------------------------- CLIVE's records


def _work_rows(order_ids: set[str], labels: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
    from app.work.store import work

    if getattr(work, "_folder", None) is None:
        return [], "not set up"
    try:
        record = work.history(limit=WORK_RECORD_LINES)
    except Exception as exc:  # noqa: BLE001 — the work list is one source of several
        log.info("work record unavailable: %s", type(exc).__name__)
        return [], "unavailable"
    out = []
    for entry in record:
        ref = str(entry.get("ref") or "")
        order_id = ref[len("order:"):] if ref.startswith("order:") else ""
        what = str(entry.get("what") or "")
        if order_id not in order_ids or what not in _WORK_SAID:
            continue
        who = _person(entry.get("who"))
        out.append(_row(entry.get("at"), f"work_{what}", f"{_WORK_SAID[what]} {labels.get(order_id, 'their order')}",
                        f"work list · {who}" if who else "work list", ref=order_id, ref_kind="order", source="CLIVE"))
    return out, f"{len(out)} step{'s' if len(out) != 1 else ''}"


def _person(who: Any) -> str:
    who = str(who or "")
    if not who:
        return ""
    if who == "owner":
        return "you"
    try:
        from app.people.store import people

        person = people.get(who)
        return person.name if person is not None else "the team"
    except Exception:  # noqa: BLE001
        return "the team"


def _screen_rows(numbers: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
    from app.displays import store as displays

    held = displays._STORE
    if held is None:
        return [], "not set up"
    out = []
    for order_id, digits in numbers.items():
        try:
            rows = held.done(order=digits, limit=3)
        except Exception:  # noqa: BLE001
            continue
        for row in rows:
            if row.get("kind") != "order":
                continue
            out.append(_row(row.get("done_at"), "packed_screen", f"Packed #{digits}", displays.how_marked(row),
                            ref=order_id, ref_kind="order", source="CLIVE"))
    return out, f"{len(out)} packed"


def _ledger_entries() -> list[dict[str, Any]]:
    from app.actions import engine

    held = engine._engine
    ledger = getattr(held, "ledger", None)
    if ledger is None:
        return []
    path = getattr(ledger, "path", None)
    if not isinstance(path, Path) or str(path) == "/dev/null":
        try:
            return list(ledger.read())
        except Exception:  # noqa: BLE001
            return []
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - LEDGER_TAIL_BYTES))
            text = stream.read().decode("utf-8", "replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines()[1 if size > LEDGER_TAIL_BYTES else 0:]:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def _clive_rows(order_ids: set[str], customer_id: str, labels: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
    refs = set(order_ids) | ({customer_id} if customer_id else set())
    out = []
    for entry in _ledger_entries():
        said = _LEDGER_SAID.get(str(entry.get("event") or ""))
        ref = str(entry.get("entity_ref") or "")
        if said is None or ref not in refs:
            continue
        verb = _OPERATION_WORDS.get(str(entry.get("operation") or ""), str(entry.get("operation") or "changed").replace("_", " "))
        target = labels.get(ref, "")
        what = f"CLIVE {verb} {target}".strip() if target and not verb.endswith("link") else f"CLIVE {verb}"
        out.append(_row(entry.get("ts"), "clive", what, said, ref=ref if ref in order_ids else "", ref_kind="order" if ref in order_ids else "",
                        source="CLIVE"))
    return out, f"{len(out)} change{'s' if len(out) != 1 else ''}"


def _objective_rows(name: str, email: str, numbers: dict[str, str], *, owner: bool) -> tuple[list[dict[str, Any]], str]:
    if not owner:
        return [], "the owner's own"
    from app.objectives import store as objectives

    held = objectives._STORE
    if held is None:
        return [], "not set up"
    try:
        everything = held.all()
    except Exception:  # noqa: BLE001
        return [], "unavailable"
    searches = [s for s in (name, email, *(f"#{d}" for d in numbers.values()), *numbers.values()) if s and len(s) >= 3]
    out = []
    for objective in everything:
        if not any(objective.mentions(s) for s in searches):
            continue
        summary = objective.summary()
        out.append(_row(summary.get("updated_at"), "objective", f"Objective: {objective.title}",
                        str(summary.get("doing") or summary.get("status") or ""), ref=objective.id, ref_kind="objective", source="CLIVE"))
    return out, f"{len(out)} objective{'s' if len(out) != 1 else ''}"


# --------------------------------------------------------------------------- the whole


def timeline(history: dict[str, Any], threads: list[dict[str, Any]] | None, *, owner: bool, ours: str = "",
             today: date | None = None) -> dict[str, Any]:
    """The customer's story, newest first, and what each source contributed."""
    today = today or datetime.now(when_words.SHOP_TZ).date()
    recent = [o for o in history.get("recent") or [] if isinstance(o, dict)]
    order_ids = {str(o.get("order_id")) for o in recent if o.get("order_id")}
    labels = {str(o.get("order_id")): _number(o.get("order_number")) for o in recent if o.get("order_id")}
    numbers = {oid: label.lstrip("#") for oid, label in labels.items()}
    email = str(history.get("email") or "").strip().lower()
    rows = _order_rows(history)
    count = history.get("orders")
    sources: dict[str, str] = {
        "Shopify": f"the newest {len(recent)} of {count} orders" if isinstance(count, int) and count > len(recent) else f"{len(recent)} order{'s' if len(recent) != 1 else ''}",
    }
    if threads is None:
        sources["Gmail"] = "not read"
    else:
        found = _email_rows(threads, email=email, numbers=list(numbers.values()), ours=ours)
        rows += found
        sources["Gmail"] = f"{len(found)} thread{'s' if len(found) != 1 else ''}"
    for key, (more, said) in (
        ("work list", _work_rows(order_ids, labels)),
        ("screens", _screen_rows(numbers)),
        ("CLIVE's changes", _clive_rows(order_ids, str(history.get("customer_id") or ""), labels)),
        ("objectives", _objective_rows(str(history.get("name") or ""), email, numbers, owner=owner)),
    ):
        rows += more
        sources[key] = said
    floor = datetime.min.replace(tzinfo=UTC)
    rows.sort(key=lambda r: r["_t"] or floor, reverse=True)
    shown = rows[:MAX_ROWS]
    for row in shown:
        moment = row.pop("_t")
        row["when"] = when_words.day_words(moment.astimezone(when_words.SHOP_TZ).date(), today) if moment else ""
    return {"rows": shown, "count": len(rows), "truncated": len(rows) > MAX_ROWS, "sources": sources}
