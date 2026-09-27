"""What a screen shows, built from CLIVE's own records: an order as a fulfilment slip, an
objective, or a titled list. Plain data; the screen draws it (web/display.js)."""

from __future__ import annotations

from typing import Any

MAX_ITEMS = 60
MAX_LINES = 40
MAX_LINE = 200


def _text(value: Any, limit: int = MAX_LINE) -> str:
    return " ".join(str(value or "").split())[:limit]


def order_view(order: dict[str, Any]) -> dict[str, Any]:
    """The fulfilment slip: who it goes to, where, and what goes in the box — the items still to
    send first, each with its size and colour, quantity and SKU."""
    address = order.get("shipping_address") if isinstance(order.get("shipping_address"), dict) else {}
    lines = [
        *[_text(x) for x in (address.get("lines") or [])],
        _text(address.get("city")), _text(address.get("province")), _text(address.get("zip")), _text(address.get("country")),
    ]
    items = []
    for item in (order.get("items") or [])[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        to_send = item.get("unfulfilled_quantity")
        quantity = item.get("current_quantity", item.get("quantity"))
        items.append({
            "title": _text(item.get("product_title") or item.get("title"), 120),
            "variant": _text(item.get("variant"), 80),
            "sku": _text(item.get("sku"), 60),
            "quantity": int(quantity) if isinstance(quantity, int) else None,
            "to_send": int(to_send) if isinstance(to_send, int) else None,
            "image": item.get("image_url") if str(item.get("image_url") or "").startswith("https://") else None,
        })
    items.sort(key=lambda i: 0 if (i["to_send"] or 0) > 0 else 1)
    number = _text(order.get("order_number"), 40)
    return {
        "kind": "order",
        "ref": str(order.get("order_id") or ""),
        "title": f"Order {number}" if number else "Order",
        "order": {
            "number": number,
            "placed_at": order.get("placed_at"),
            "customer": _text(address.get("name") or order.get("customer_name"), 80),
            "company": _text(address.get("company"), 80) or None,
            "address": [line for line in lines if line],
            "phone": _text(address.get("phone"), 40) or None,
            "items": items,
            "note": _text(order.get("note"), 600) or None,
            "tags": [_text(t, 40) for t in (order.get("tags") or [])][:10],
            "fulfillment": _text(order.get("fulfillment"), 40) or None,
            "payment": _text(order.get("payment"), 40) or None,
            "shipping_method": _text(order.get("shipping_method"), 80) or None,
        },
    }


def objective_view(summary: dict[str, Any], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An objective as the owner reads it across a room: what is being done now, what needs him,
    and what comes next — the work not yet started, in the order it was proposed."""
    open_items = [i for i in (items or []) if isinstance(i, dict) and i.get("state") not in ("completed", "verified")]
    waiting = [_text(i.get("text")) for i in open_items if i.get("state") in ("proposed", "authorised")]
    days_left = summary.get("days_left")
    return {
        "kind": "objective",
        "ref": str(summary.get("id") or ""),
        "title": _text(summary.get("title"), 120) or "Objective",
        "objective": {
            "deadline": summary.get("deadline"),
            "days_left": days_left if isinstance(days_left, int) else None,
            "doing": _text(summary.get("doing")) or None,
            "next": (waiting or [_text(x) for x in (summary.get("next") or [])])[:8],
            "needs_you": [_text(x) for x in (summary.get("needs_you") or [])][:6],
            "blocked_by": [_text(x) for x in (summary.get("blocked_by") or [])][:6],
            "items": [{"text": _text(i.get("text")), "state": _text(i.get("state"), 20)} for i in open_items][:MAX_LINES],
        },
    }


def list_view(title: str, lines: list[str]) -> dict[str, Any]:
    return {
        "kind": "list",
        "ref": "",
        "title": _text(title, 120) or "List",
        "list": {"lines": [_text(line) for line in (lines or []) if _text(line)][:MAX_LINES]},
    }
