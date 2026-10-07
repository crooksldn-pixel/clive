"""CROOKS Returns' answers, put the way the owner reads them: a row per return, one return in full,
"where is my return?", the labels paid for and never posted, a period's numbers, and the home's count.

Every value here comes from what the returns service sent (app/clients/crooks_returns.py) and is
only rearranged and bounded: nothing is estimated, and a field the service did not send is left
out rather than filled in. Money stays integer pence until it is shown, and is shown as £ by
`crooks_returns.pounds` alone. What the customer is called is kept (the owner's card names them);
their email, phone and address are never copied out of a return.

Pure functions, no I/O: the tools (app/tools/returns_tools.py), the order card and the customer's
story (app/tools/shopify_tools.py), and the home's row (app/routes/returns.py) all shape from here.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from app.clients.crooks_returns import pence, pounds, scrub

MAX_ROWS = 25
MAX_EVENTS = 12
MAX_LINES = 8
TEXT = 160
UNUSED_LABEL_DAYS = 14
# A product with this many too-small returns in the period is a size-chart (or fit) finding.
SIZE_FINDING_AT = 2

STATUS_WORDS = {
    "requested": "waiting for your approval",
    "awaiting_label": "approved, waiting for a label",
    "awaiting_shipment": "approved, waiting for the customer to post it",
    "in_transit": "on its way back",
    "received": "back with us",
    "completed": "complete",
    "declined": "declined",
    "cancelled": "cancelled",
}
ATTENTION_WORDS = {
    "needs_approval": "to approve",
    "awaiting_label_overdue": "label overdue",
    "delivered_unchecked": "delivered, not checked",
    "needs_decision": "needs a decision",
    "error": "has an error",
}
# The order the home and the list put them in: what is broken, then what only he can decide.
ATTENTION_ORDER = ("error", "needs_decision", "delivered_unchecked", "awaiting_label_overdue", "needs_approval")
RESOLUTION_WORDS = {"exchange": "exchange", "store_credit": "store credit", "refund": "refund"}
REASON_WORDS = {
    "too_small": "too small", "too_big": "too big", "changed_mind": "changed their mind",
    "not_as_described": "not as described", "faulty": "faulty or damaged", "wrong_item": "wrong item sent",
}
MODE_WORDS = {"label_now": "label bought now", "self_ship": "customer posts it", "label_later": "label later",
              "no_return": "nothing comes back"}
DIRECTION_WORDS = {"size_up": "a size up", "size_down": "a size down", "same": "the same size", "other": "another variant"}
EVENT_WORDS = {
    "requested": "Customer asked to return it", "approved": "Approved", "approve_failed": "Approval failed",
    "declined": "Declined", "awaiting_label": "Waiting for a label", "label_bought": "Label bought",
    "label_overdue": "Label overdue", "shipping_attached": "Tracking added to the Shopify return",
    "shipping_attach_failed": "Shopify didn't take the tracking", "in_transit": "On its way back",
    "delivered_to_us": "Delivered to us", "received": "Received", "processed": "Money moved in Shopify",
    "process_failed": "Shopify didn't process it", "bonus_credited": "Bonus credited", "bonus_failed": "Bonus failed",
    "completed": "Completed", "cancelled": "Cancelled", "cancel_failed": "Cancel failed", "note": "Note",
    "no_return": "Customer keeps the item",
}
MONEY_WORDS = (
    ("items_pence", "Items"), ("refund_pence", "Refund"), ("credit_pence", "Store credit"),
    ("bonus_pence", "of which bonus"), ("shipping_refund_pence", "Delivery refunded"), ("fee_pence", "Label fee kept"),
)


def _text(value: Any, limit: int = TEXT) -> str:
    words = " ".join(str(value or "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def _when(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def order_number(ret: dict[str, Any]) -> str:
    """"#2131" from "CROOKS-2131" or "#2131": how the office says an order."""
    digits = "".join(ch for ch in str(ret.get("order_name") or "") if ch.isdigit())
    return f"#{digits}" if digits else ""


def money(ret: dict[str, Any]) -> list[dict[str, Any]]:
    """The return's money as the service holds it: each non-zero amount, in pence and in pounds."""
    held = _dict(ret.get("money"))
    out = []
    for key, label in MONEY_WORDS:
        amount = pence(held.get(key))
        if amount:
            out.append({"key": key, "label": label, "pence": amount, "shown": pounds(amount)})
    return out


def attention(ret: dict[str, Any]) -> list[str]:
    said = [str(a) for a in _list(ret.get("attention")) if str(a) in ATTENTION_WORDS]
    return sorted(said, key=ATTENTION_ORDER.index)


def _postage(ret: dict[str, Any]) -> dict[str, Any]:
    p = _dict(ret.get("postage"))
    url = str(p.get("tracking_url") or "")
    return {
        "chosen": _text(p.get("chosen"), 20), "mode": _text(p.get("mode"), 20), "carrier": _text(p.get("carrier"), 40),
        "service": _text(p.get("service_name"), 60), "tracking": _text(p.get("tracking"), 40),
        "tracking_url": url if url.startswith("https://") and len(url) <= 300 else "",
        "courier_stage": _text(p.get("courier_stage"), 30),
        "label_price": pounds(p.get("label_price_pence")),
    }


def row(ret: dict[str, Any]) -> dict[str, Any]:
    """One return as a list shows it."""
    status = str(ret.get("status") or "")
    needs = attention(ret)
    return {
        "return_id": _text(ret.get("id"), 48),
        "order_id": _text(ret.get("order_id"), 80),
        "order_number": order_number(ret),
        "customer_name": _text(ret.get("customer_name"), 60),
        "status": _text(status, 20),
        "status_words": STATUS_WORDS.get(status, status.replace("_", " ")),
        "resolution": RESOLUTION_WORDS.get(str(ret.get("resolution") or ""), _text(ret.get("resolution"), 20)),
        "summary": _text(ret.get("summary"), 240),
        "attention": needs,
        "attention_words": [ATTENTION_WORDS[a] for a in needs],
        "money": money(ret),
        "postage": _postage(ret),
        "error": scrub(ret.get("last_error")) if ret.get("last_error") else "",
        "created_at": _text(ret.get("created_at"), 40),
        "updated_at": _text(ret.get("updated_at"), 40),
    }


def _event(e: dict[str, Any]) -> dict[str, Any]:
    kind = str(e.get("type") or "")
    detail = _dict(e.get("detail"))
    bits = []
    for key in ("postage_mode", "service", "cost", "ref", "tracking", "stage", "condition", "reason", "outcome", "amount"):
        value = detail.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "postage_mode":
            bits.append(MODE_WORDS.get(str(value), str(value).replace("_", " ")))
        else:
            bits.append(f"{key} {value}" if key in ("ref", "stage", "condition") else str(value))
    if kind == "note" and detail.get("text"):
        bits = [str(detail["text"])]
    if detail.get("error"):
        bits.append(str(detail["error"]))
    actor = str(e.get("actor") or "")
    return {
        "at": _text(e.get("at"), 40),
        "what": EVENT_WORDS.get(kind, kind.replace("_", " ").capitalize()),
        "kind": _text(kind, 40),
        "by": _text(actor, 60),
        "detail": scrub("; ".join(bits)) if bits else "",
        "verified": bool(e.get("verified")),
    }


def where(ret: dict[str, Any]) -> str:
    """"Where is my return?", answered from its status, its tracking and its timeline."""
    status = str(ret.get("status") or "")
    p = _postage(ret)
    said = [f"{order_number(ret) or 'The return'} is {STATUS_WORDS.get(status, status.replace('_', ' '))}"]
    events = [e for e in _list(ret.get("timeline")) if isinstance(e, dict)]
    last = events[-1] if events else None
    if last is not None:
        moment = _when(last.get("at"))
        day = f"{moment.day} {moment.strftime('%b')}" if moment else ""
        said.append(f"last: {EVENT_WORDS.get(str(last.get('type') or ''), str(last.get('type') or '').replace('_', ' ')).lower()}"
                    + (f" on {day}" if day else ""))
    if p["tracking"]:
        said.append(f"tracking {p['tracking']}" + (f" with {p['carrier']}" if p["carrier"] else ""))
    elif status in ("awaiting_shipment",) and p["mode"] == "self_ship":
        said.append("no tracking from the customer yet")
    if p["courier_stage"]:
        said.append(f"the courier last said {p['courier_stage']}")
    return _text("; ".join(said) + ".", 300)


def detail(ret: dict[str, Any]) -> dict[str, Any]:
    """One return in full: its lines, the timeline newest first, and the answer to where it is."""
    out = row(ret)
    out["lines"] = [
        {
            "title": _text(ln.get("title"), 80), "variant": _text(ln.get("variant_title"), 60), "sku": _text(ln.get("sku"), 40),
            "quantity": ln.get("quantity") if isinstance(ln.get("quantity"), int) else None,
            "reason": REASON_WORDS.get(str(ln.get("reason") or ""), _text(ln.get("reason"), 30)),
            "paid": pounds(ln.get("unit_paid_pence")),
            "exchange_for": _text(ln.get("exchange_variant_title"), 60),
            "direction": DIRECTION_WORDS.get(str(ln.get("exchange_direction") or ""), ""),
        }
        for ln in _list(ret.get("lines"))[:MAX_LINES] if isinstance(ln, dict)
    ]
    events = [e for e in _list(ret.get("timeline")) if isinstance(e, dict)]
    out["timeline"] = [_event(e) for e in reversed(events[-MAX_EVENTS:])]
    out["timeline_total"] = len(events)
    inspection = _dict(ret.get("inspection"))
    if inspection:
        out["inspection"] = {"condition": _text(inspection.get("condition"), 20), "restock": bool(inspection.get("restock", True)),
                             "note": scrub(inspection.get("note"))}
    if ret.get("decline_reason"):
        out["decline_reason"] = scrub(ret.get("decline_reason"))
    out["where"] = where(ret)
    return out


def _label_bought_at(ret: dict[str, Any]) -> datetime | None:
    for e in reversed(_list(ret.get("timeline"))):
        if isinstance(e, dict) and e.get("type") == "label_bought":
            return _when(e.get("at"))
    return None


def _label_order(ret: dict[str, Any]) -> str:
    """The Parcel2Go order number of the label, as the timeline records it (never the access hash
    the service keeps beside it)."""
    for e in reversed(_list(ret.get("timeline"))):
        if isinstance(e, dict) and e.get("type") == "label_bought":
            return _text(_dict(e.get("detail")).get("ref"), 20)
    return ""


def unused_labels(returns: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Labels CROOKS paid for that the customer never posted: waiting for shipment, a label bought
    more than fourteen days ago, and no courier stage since. Parcel2Go's API has no cancel, so these
    are for the owner to cancel on parcel2go.com, which refunds them."""
    now = now or datetime.now(UTC)
    out = []
    for ret in returns:
        p = _dict(ret.get("postage"))
        if str(ret.get("status") or "") != "awaiting_shipment" or p.get("courier_stage"):
            continue
        if not (p.get("label_ref") or p.get("label_file_id") or pence(p.get("label_price_pence")) is not None):
            continue
        bought = _label_bought_at(ret) or _when(ret.get("updated_at"))
        if bought is None:
            continue
        days = (now - bought).days
        if days < UNUSED_LABEL_DAYS:
            continue
        out.append({
            "return_id": _text(ret.get("id"), 48), "order_number": order_number(ret),
            "customer_name": _text(ret.get("customer_name"), 60), "carrier": _text(p.get("carrier"), 40),
            "service": _text(p.get("service_name"), 60), "paid": pounds(p.get("label_price_pence")),
            "parcel2go_order": _label_order(ret), "bought_at": bought.isoformat().replace("+00:00", "Z"), "days": days,
        })
    return sorted(out, key=lambda x: -x["days"])


def counts(returns: list[dict[str, Any]]) -> dict[str, int]:
    """How many open returns need the owner, in each way (a return may need him in two)."""
    found: Counter[str] = Counter()
    for ret in returns:
        for a in attention(ret):
            found[a] += 1
    return {a: found[a] for a in ATTENTION_ORDER if found[a]}


def brief(returns: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    """The home's row: how many returns need him, and the words for why."""
    needing = [r for r in returns if attention(r)]
    unused = unused_labels(returns, now=now)
    parts = [f"{n} {ATTENTION_WORDS[a]}" for a, n in counts(returns).items()]
    if unused:
        parts.append(f"{len(unused)} unused label{'s' if len(unused) != 1 else ''} to cancel")
    return {"open": len(returns), "needs": len(needing), "unused_labels": len(unused), "words": " · ".join(parts)}


def open_view(returns: list[dict[str, Any]], *, now: datetime | None = None, checked_at: str = "") -> dict[str, Any]:
    """Every open return, those that need the owner first, and the labels to cancel."""
    ordered = sorted(returns, key=lambda r: (0 if attention(r) else 1, min((ATTENTION_ORDER.index(a) for a in attention(r)), default=9)))
    rows = [row(r) for r in ordered[:MAX_ROWS]]
    return {
        "open": len(returns), "needs_you": sum(1 for r in returns if attention(r)), "counts": counts(returns),
        "returns": rows, "truncated": len(returns) > MAX_ROWS,
        "unused_labels": unused_labels(returns, now=now), "checked_at": checked_at,
    }


def products(returns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per product, from each return's lines: why it came back, and which way a size was swapped.
    A product returned too small again and again is a size-chart (or fit) finding, and says so."""
    table: dict[str, dict[str, Any]] = {}
    for ret in returns:
        if str(ret.get("status") or "") in ("declined", "cancelled"):
            continue
        for ln in _list(ret.get("lines")):
            if not isinstance(ln, dict):
                continue
            title = _text(ln.get("title"), 80) or _text(ln.get("sku"), 40)
            if not title:
                continue
            quantity = ln.get("quantity") if isinstance(ln.get("quantity"), int) and ln.get("quantity") > 0 else 1
            entry = table.setdefault(title, {"title": title, "returned": 0, "reasons": Counter(), "size_up": 0, "size_down": 0})
            entry["returned"] += quantity
            entry["reasons"][str(ln.get("reason") or "")] += quantity
            if ln.get("exchange_direction") == "size_up":
                entry["size_up"] += quantity
            elif ln.get("exchange_direction") == "size_down":
                entry["size_down"] += quantity
    out = []
    for entry in sorted(table.values(), key=lambda e: -e["returned"]):
        small, big = entry["reasons"]["too_small"], entry["reasons"]["too_big"]
        finding = ""
        if small >= SIZE_FINDING_AT and small > big:
            finding = (f"{small} came back too small ({entry['size_up']} swapped a size up): check its size chart, "
                       "or say it runs small.")
        elif big >= SIZE_FINDING_AT and big > small:
            finding = (f"{big} came back too big ({entry['size_down']} swapped a size down): check its size chart, "
                       "or say it runs big.")
        out.append({
            "title": entry["title"], "returned": entry["returned"], "size_up": entry["size_up"], "size_down": entry["size_down"],
            "reasons": [{"reason": REASON_WORDS.get(k, k), "count": n} for k, n in entry["reasons"].most_common(3) if k],
            "finding": finding,
        })
    return out[:12]


def stats_view(stats: dict[str, Any], returns: list[dict[str, Any]], *, days: int, since: str) -> dict[str, Any]:
    """A period's numbers as the service counted them, with the per-product swaps beside them."""
    by_reason = _dict(stats.get("by_reason"))
    kept = stats.get("kept_share")
    per_product = products(returns)
    return {
        "days": days, "since": since,
        "returns": stats.get("returns") if isinstance(stats.get("returns"), int) else None,
        "by_status": {str(k): v for k, v in _dict(stats.get("by_status")).items() if isinstance(v, int)},
        "by_resolution": {RESOLUTION_WORDS.get(str(k), str(k)): v for k, v in _dict(stats.get("by_resolution")).items() if isinstance(v, int)},
        "reasons": [{"reason": REASON_WORDS.get(str(k), str(k)), "count": v}
                    for k, v in sorted(by_reason.items(), key=lambda kv: -kv[1] if isinstance(kv[1], int) else 0) if isinstance(v, int)][:6],
        "top_skus": [{"sku": _text(pair[0], 60), "count": pair[1]} for pair in _list(stats.get("by_sku"))[:8]
                     if isinstance(pair, list) and len(pair) == 2 and isinstance(pair[1], int)],
        "size_swaps": {DIRECTION_WORDS.get(str(k), str(k)): v for k, v in _dict(stats.get("size_swaps")).items() if isinstance(v, int)},
        "value_returned": _text(stats.get("value_returned"), 20), "value_kept": _text(stats.get("value_kept"), 20),
        "kept_share": f"{round(kept * 100)}%" if isinstance(kept, (int, float)) and not isinstance(kept, bool) else "",
        "bonus_given": _text(stats.get("bonus_given"), 20), "label_fees_recovered": _text(stats.get("label_fees_recovered"), 20),
        "products": per_product,
        "findings": [f"{p['title']}: {p['finding']}" for p in per_product if p["finding"]],
        "products_from": len(returns),
    }


def timeline_rows(returns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A customer's returns as rows of their story (app/customers/history.py): when each was asked
    for, and where it stands now."""
    out = []
    for ret in returns:
        number = order_number(ret)
        out.append({"at": ret.get("created_at"), "kind": "return",
                    "what": f"Asked to return {number}".strip(), "detail": _text(ret.get("summary"), 160),
                    "ref": str(ret.get("order_id") or ""), "ref_kind": "order", "source": "Returns"})
        status = str(ret.get("status") or "")
        events = [e for e in _list(ret.get("timeline")) if isinstance(e, dict)]
        if status != "requested":
            # Dated by the return's latest timeline entry: the last thing that happened to it.
            out.append({"at": (events[-1].get("at") if events else None) or ret.get("updated_at"), "kind": "return",
                        "what": f"Return on {number}: {STATUS_WORDS.get(status, status.replace('_', ' '))}",
                        "detail": " · ".join(ATTENTION_WORDS[a] for a in attention(ret)),
                        "ref": str(ret.get("order_id") or ""), "ref_kind": "order", "source": "Returns"})
    return out


def on_order(returns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The returns on one order, for its card: each with where it stands and what it needs."""
    out = []
    for ret in returns[:4]:
        shown = row(ret)
        out.append({k: shown[k] for k in ("return_id", "status", "status_words", "resolution", "summary", "attention_words",
                                          "money", "postage", "error", "updated_at")} | {"where": where(ret)})
    return out


# ------------------------------------------------------------------ the card


def _rows_for_card(rows: list[Any]) -> list[dict[str, Any]]:
    out = []
    for r in rows[:MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        postage = _dict(r.get("postage"))
        out.append({
            "return_id": _text(r.get("return_id"), 48), "order_id": _text(r.get("order_id"), 80),
            "order_number": _text(r.get("order_number"), 16), "customer_name": _text(r.get("customer_name"), 60),
            "status": _text(r.get("status"), 20), "status_words": _text(r.get("status_words"), 60),
            "resolution": _text(r.get("resolution"), 20), "summary": _text(r.get("summary"), 240),
            "attention": [_text(a, 30) for a in _list(r.get("attention"))[:5]],
            "attention_words": [_text(a, 30) for a in _list(r.get("attention_words"))[:5]],
            "money": [{"label": _text(m.get("label"), 30), "shown": _text(m.get("shown"), 20)}
                      for m in _list(r.get("money"))[:6] if isinstance(m, dict)],
            "tracking": _text(postage.get("tracking"), 40), "tracking_url": _text(postage.get("tracking_url"), 300),
            "carrier": _text(postage.get("carrier"), 40), "error": _text(r.get("error"), MAX_DETAIL_CARD),
            "updated_at": _text(r.get("updated_at"), 40),
        })
    return out


MAX_DETAIL_CARD = 200


def card(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    """The "returns" card (drawn by web/returns.js) from one of the three reads' results: built
    from those results and nothing else, every string bounded again here."""
    if tool == "returns_open":
        counted = _dict(result.get("counts"))
        return {
            "view": "open", "key": "open", "open": result.get("open") if isinstance(result.get("open"), int) else 0,
            "needs_you": result.get("needs_you") if isinstance(result.get("needs_you"), int) else 0,
            "counts": [{"key": k, "words": ATTENTION_WORDS[k], "count": v} for k, v in counted.items()
                       if k in ATTENTION_WORDS and isinstance(v, int)],
            "rows": _rows_for_card(_list(result.get("returns"))), "truncated": bool(result.get("truncated")),
            "unused_labels": [{k: _text(u.get(k), 60) for k in ("return_id", "order_number", "customer_name", "carrier", "service",
                                                               "paid", "parcel2go_order", "bought_at")}
                              | {"days": u.get("days") if isinstance(u.get("days"), int) else None}
                              for u in _list(result.get("unused_labels"))[:10] if isinstance(u, dict)],
            "checked_at": _text(result.get("checked_at"), 40),
        }
    if tool == "return_find":
        found = []
        for d in _list(result.get("returns"))[:4]:
            if not isinstance(d, dict):
                continue
            base = _rows_for_card([d])[0]
            base.update({
                "where": _text(d.get("where"), 300),
                "lines": [{k: _text(ln.get(k), 80) for k in ("title", "variant", "reason", "paid", "exchange_for", "direction")}
                          | {"quantity": ln.get("quantity") if isinstance(ln.get("quantity"), int) else None}
                          for ln in _list(d.get("lines"))[:MAX_LINES] if isinstance(ln, dict)],
                "timeline": [{k: _text(e.get(k), 160) for k in ("at", "what", "by", "detail")} | {"verified": bool(e.get("verified"))}
                             for e in _list(d.get("timeline"))[:MAX_EVENTS] if isinstance(e, dict)],
                "timeline_total": d.get("timeline_total") if isinstance(d.get("timeline_total"), int) else 0,
            })
            found.append(base)
        number = _text(result.get("order_number"), 16) or (found[0]["order_number"] if found else "")
        return {"view": "one", "key": f"one {number or (found[0]['return_id'] if found else '')}".strip(), "returns": found,
                "order_number": _text(result.get("order_number"), 16), "note": _text(result.get("note"), 160)}
    if tool == "returns_stats":
        days = result.get("days") if isinstance(result.get("days"), int) else None
        return {
            "view": "stats", "key": f"stats {days}", "days": days,
            "returns": result.get("returns") if isinstance(result.get("returns"), int) else None,
            "kept_share": _text(result.get("kept_share"), 8), "value_returned": _text(result.get("value_returned"), 20),
            "value_kept": _text(result.get("value_kept"), 20), "bonus_given": _text(result.get("bonus_given"), 20),
            "label_fees_recovered": _text(result.get("label_fees_recovered"), 20),
            "by_resolution": [{"label": _text(k, 20), "count": v} for k, v in _dict(result.get("by_resolution")).items()
                              if isinstance(v, int)][:4],
            "reasons": [{"label": _text(r.get("reason"), 30), "count": r.get("count")} for r in _list(result.get("reasons"))[:6]
                        if isinstance(r, dict) and isinstance(r.get("count"), int)],
            "top_skus": [{"label": _text(r.get("sku"), 60), "count": r.get("count")} for r in _list(result.get("top_skus"))[:6]
                         if isinstance(r, dict) and isinstance(r.get("count"), int)],
            "products": [{"title": _text(p.get("title"), 80), "returned": p.get("returned"), "size_up": p.get("size_up"),
                          "size_down": p.get("size_down"), "finding": _text(p.get("finding"), 200)}
                         for p in _list(result.get("products"))[:8] if isinstance(p, dict)],
            "findings": [_text(f, 240) for f in _list(result.get("findings"))[:4]],
        }
    return {"view": "none"}
