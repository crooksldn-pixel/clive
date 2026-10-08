"""CLIVE Shipping's answers, put the way the owner reads them: a row per international order, one order
in full (payment, label, print and the carrier apart), what changed, and the "shipping" card.

Every value here comes from what the shipping service sent (app/clients/crooks_shipping.py) and is
only rearranged and bounded: nothing is estimated, and a field the service did not send is left out
rather than filled in. Prices are the service's own words ("£11.79"); CLIVE never does sums with them.
The service's rows name no customer; a sentence it wrote (an alert, an error, a carrier's update) is
scrubbed of anything shaped like an email address, a phone number or a postcode before it is kept.

Pure functions, no I/O: the tools (app/tools/shipping_tools.py), the cards (app/presentation.py,
drawn by web/shipping.js) and the proposal card after a buy or a print all shape from here.
"""

from __future__ import annotations

import re
from typing import Any

from app.clients.crooks_shipping import SHIPMENT_ID, STAGES, scrub

MAX_ROWS = 25
MAX_EVENTS = 30
TEXT = 120
ORDER_REF = re.compile(r"^gid://shopify/Order/\d+$")

# The service's own tab names (clive-shipping/shipping/lifecycle.py TITLES), one order at a time.
STAGE_WORDS = {
    "attention": "Needs attention",
    "ready": "Ready to ship",
    "bought": "Label bought",
    "printed": "Printed",
    "in_transit": "In transit",
    "delivered": "Delivered",
    "closed": "Closed",
}
# The stages a list shows when none is named: every order still on its way out.
OPEN_STAGES = ("attention", "ready", "bought", "printed", "in_transit")
# A print that did not happen, or may not have: the owner's to look at.
PRINT_PROBLEMS = ("Print failed", "Print uncertain", "Not confirmed by printer")
# What an event's detail may say, by the service's own keys. Anything else stays with the service.
EVENT_DETAIL_KEYS = ("amount", "service", "message", "country", "why", "was", "now")


def _text(value: Any, limit: int = TEXT) -> str:
    """A field the service filled in (a stage, a price, a date, a tracking number): one line, bounded."""
    words = " ".join(str(value if value is not None else "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def _said(value: Any, limit: int = TEXT) -> str:
    """A sentence the service wrote (an alert, an error, a carrier's update): bounded and scrubbed."""
    return scrub(value, limit) if value is not None else ""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def order_number(s: dict[str, Any]) -> str:
    """ "CROOKS-2142" -> "#2142": the order as the owner says it."""
    digits = re.sub(r"\D", "", str(s.get("order") or ""))
    return f"#{digits}" if 1 <= len(digits) <= 10 else ""


def _id(value: Any) -> str:
    text = str(value or "")
    return text if SHIPMENT_ID.fullmatch(text) else ""


def tone(row: dict[str, Any], *, error: str = "") -> str:
    """The row's dot. bad: a print that failed or may not have, or an error the service recorded;
    warn: something stops the order; ask: something for him to do (buy a ready label, print a bought
    one); quiet: on its way, or done."""
    if error or row.get("print") in PRINT_PROBLEMS:
        return "bad"
    stage = row.get("stage")
    if stage == "attention":
        return "warn"
    if stage == "ready" or (stage == "bought" and row.get("print") in ("", "Not printed")):
        return "ask"
    return "quiet"


def _label(value: Any) -> Any:
    """The words of a field that is a sentence in a list's row and {label, tone, ...} in an order's
    detail (payment, carrier): the same words either way."""
    return value.get("label") if isinstance(value, dict) else value


def row(s: dict[str, Any]) -> dict[str, Any]:
    """One order as the service sums it up (its `summary`, or the summary inside its detail), bounded."""
    stage = _text(s.get("stage"), 20)
    out = {
        "shipment_id": _id(s.get("id")),
        "order_number": order_number(s),
        "order_id": str(s.get("order_id") or "") if ORDER_REF.fullmatch(str(s.get("order_id") or "")) else "",
        "country": _text(s.get("country"), 4),
        "stage": stage,
        "stage_words": STAGE_WORDS.get(stage, stage.replace("_", " ")),
        "status": _text(s.get("status"), 60),
        "reasons": [_text(r, 40) for r in _list(s.get("reasons"))[:6] if r],
        "payment": _text(_label(s.get("payment")), 40),
        "service": _text(s.get("service"), 80),
        "price": _text(s.get("price"), 20),
        "tracking_number": _text(s.get("tracking_number"), 40),
        "print": _text(s.get("print"), 40),
        "carrier": _text(_label(s.get("carrier")), 60),
        "updated_at": _text(s.get("updated_at"), 40),
    }
    out["tone"] = tone(out)
    return out


def detail(d: dict[str, Any]) -> dict[str, Any]:
    """One order in full: its row, then payment, the label, the print and the carrier, each as the
    service said it, and what it says needs a person."""
    out = row(d)
    payment, printing, carrier, label = (_dict(d.get(k)) for k in ("payment", "print_status", "carrier", "label"))
    url = str(label.get("tracking_url") or "")
    out.update({
        "payment_note": _said(payment.get("note"), 80),
        "label": {
            "provider": _text(label.get("provider"), 40), "service": _text(label.get("service"), 80),
            "tracking_number": _text(label.get("tracking_number"), 40),
            "tracking_url": url[:300] if url.startswith("https://") else "",
            "purchased_at": _text(label.get("purchased_at"), 40),
        } if label else None,
        "printing": {
            "state": _text(printing.get("state"), 20), "label": _text(printing.get("label"), 40),
            "via": _text(printing.get("via"), 60), "printed_at": _text(printing.get("printed_at"), 40),
            "last_sent": _text(printing.get("last_sent"), 40), "error": _said(printing.get("error"), 160),
            "reprints": printing.get("reprint_count") if isinstance(printing.get("reprint_count"), int) else 0,
            "attempts": len(_list(printing.get("history"))),
            "first_print_available": printing.get("first_print_available") is True,
        } if printing else None,
        "carrier_view": {
            "label": _text(carrier.get("label"), 60), "note": _said(carrier.get("note"), 160),
            "estimated_delivery_at": _text(carrier.get("estimated_delivery_at"), 40),
            "delivered_at": _text(carrier.get("delivered_at"), 40), "checked_at": _text(carrier.get("checked_at"), 40),
        } if carrier else None,
        "alerts": [_said(a, 200) for a in _list(d.get("alerts"))[:4] if a],
        "can_buy": d.get("can_buy") is True,
        "error": _said(d.get("last_error"), 200),
    })
    out["tone"] = tone(out, error=out["error"])
    return out


def open_view(rows: list[dict[str, Any]], *, stage: str = "", checked_at: str = "") -> dict[str, Any]:
    """The orders in one stage, or, with none named, every order still on its way out, in the order
    of the service's tabs, with how many are in each stage."""
    shaped = [row(s) for s in rows if isinstance(s, dict)]
    if stage:
        shown = [r for r in shaped if r["stage"] == stage]
        counts = [{"stage": stage, "words": STAGE_WORDS[stage], "count": len(shown)}]
    else:
        counts = [{"stage": s, "words": STAGE_WORDS[s], "count": n} for s in STAGES
                  if (n := sum(1 for r in shaped if r["stage"] == s))]
        shown = sorted((r for r in shaped if r["stage"] in OPEN_STAGES), key=lambda r: OPEN_STAGES.index(r["stage"]))
    return {
        "stage": stage, "counts": counts, "shipments": shown[:MAX_ROWS], "total": len(shown),
        "truncated": len(shown) > MAX_ROWS, "needs_you": sum(1 for r in shown if r["tone"] in ("ask", "warn", "bad")),
        "checked_at": checked_at,
    }


def _event_detail(detail_value: Any) -> str:
    held = _dict(detail_value)
    said = [str(held[k]) for k in EVENT_DETAIL_KEYS if isinstance(held.get(k), (str, int, float)) and str(held[k]).strip()]
    return _said(" · ".join(said), 120)


def events_view(found: list[dict[str, Any]], *, hours: int, since: str, more: bool = False) -> dict[str, Any]:
    """What changed since `since`, newest first: on which order, what, who, and whether the service
    checked it against Shopify, the courier or the printer."""
    rows = []
    for e in reversed([e for e in found if isinstance(e, dict)]):
        rows.append({
            "at": _text(e.get("at"), 40), "order_number": order_number(e), "shipment_id": _id(e.get("shipment_id")),
            "type": _text(e.get("type"), 40), "what": _text(e.get("what") or e.get("type"), 80),
            "by": _said(e.get("actor"), 60), "verified": e.get("verified") is True, "detail": _event_detail(e.get("detail")),
        })
    return {"hours": hours, "since": since, "events": rows[:MAX_EVENTS], "total": len(rows),
            "truncated": len(rows) > MAX_EVENTS or more}


# ------------------------------------------------------------------ the "shipping" card


def _card_row(r: dict[str, Any]) -> dict[str, Any]:
    keys = ("shipment_id", "order_number", "order_id", "country", "stage", "stage_words", "status", "payment",
            "service", "price", "tracking_number", "print", "carrier", "tone")
    out = {k: _text(r.get(k), 80) for k in keys}
    out["reasons"] = [_text(x, 40) for x in _list(r.get("reasons"))[:6] if x]
    return out


def _card_one(d: dict[str, Any]) -> dict[str, Any]:
    out = _card_row(d)
    label, printing, carrier = (_dict(d.get(k)) for k in ("label", "printing", "carrier_view"))
    url = str(label.get("tracking_url") or "")
    out.update({
        "payment_note": _text(d.get("payment_note"), 80),
        "label": {k: _text(label.get(k), 80) for k in ("provider", "service", "tracking_number", "purchased_at")}
        | {"tracking_url": url[:300] if url.startswith("https://") else ""} if label else None,
        "printing": {k: _text(printing.get(k), 160) for k in ("state", "label", "via", "printed_at", "error")}
        | {"reprints": printing.get("reprints") if isinstance(printing.get("reprints"), int) else 0} if printing else None,
        "carrier_view": {k: _text(carrier.get(k), 160) for k in ("label", "note", "estimated_delivery_at", "delivered_at",
                                                                 "checked_at")} if carrier else None,
        "alerts": [_text(a, 200) for a in _list(d.get("alerts"))[:4] if a],
        "error": _text(d.get("error"), 200),
    })
    return out


def card(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    """The "shipping" card (drawn by web/shipping.js) from one of the reads' results: built from
    those results and nothing else, every string bounded again here."""
    if tool == "shipments_open":
        stage = _text(result.get("stage"), 20)
        return {
            "view": "open", "key": f"open {stage or 'all'}", "stage": stage,
            "counts": [{"stage": _text(c.get("stage"), 20), "words": _text(c.get("words"), 30),
                        "count": c.get("count") if isinstance(c.get("count"), int) else 0}
                       for c in _list(result.get("counts"))[:7] if isinstance(c, dict)],
            "shipments": [_card_row(r) for r in _list(result.get("shipments"))[:MAX_ROWS] if isinstance(r, dict)],
            "total": result.get("total") if isinstance(result.get("total"), int) else 0,
            "needs_you": result.get("needs_you") if isinstance(result.get("needs_you"), int) else 0,
            "truncated": bool(result.get("truncated")), "checked_at": _text(result.get("checked_at"), 40),
        }
    if tool in ("shipment_find", "shipment_tracking"):
        found = [_card_one(d) for d in _list(result.get("shipments"))[:4] if isinstance(d, dict)]
        number = _text(result.get("order_number"), 16) or (found[0]["order_number"] if found else "")
        return {"view": "one", "key": f"one {number or (found[0]['shipment_id'] if found else '')}".strip(),
                "shipments": found, "order_number": number, "note": _text(result.get("note"), 160),
                "tracking": tool == "shipment_tracking"}
    if tool == "shipping_events":
        hours = result.get("hours") if isinstance(result.get("hours"), int) else 0
        return {
            "view": "events", "key": f"events {hours}", "hours": hours,
            "events": [{k: _text(e.get(k), 120) for k in ("at", "order_number", "what", "by", "detail")}
                       | {"verified": e.get("verified") is True}
                       for e in _list(result.get("events"))[:MAX_EVENTS] if isinstance(e, dict)],
            "total": result.get("total") if isinstance(result.get("total"), int) else 0,
            "truncated": bool(result.get("truncated")),
        }
    return {"view": "none", "key": "none"}
