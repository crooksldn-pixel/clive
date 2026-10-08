"""What a screen shows, built from CLIVE's own records: an order as a fulfilment slip, an
objective, an email thread (ruling 29 of DEC-071: when George puts it there), or a titled list; or
a YouTube video the owner asked for, by its id. Plain data; the screen draws it (web/display.js).

Every field is bounded here, before it is kept (the 2026-09-27 deploy review, round 6, B-03):
each string is cut before it is cleaned, so a very long value is never walked whole; every list
is cut before it is looked through; and one whole view is at most MAX_VIEW_BYTES once written
down (app/displays/store.py refuses anything larger). An order with more items than a screen
takes is marked partial, and a partial slip can never be marked packed (B-04)."""

from __future__ import annotations

import re
from typing import Any

MAX_ITEMS = 60
MAX_LINES = 40
MAX_LINE = 200
MAX_TITLE = 120
MAX_ADDRESS_LINES = 6
MAX_URL = 500
MAX_ID = 200
MAX_VIEW_BYTES = 64_000
# A YouTube video's id (app/clients/youtube.py VIDEO_ID), and how far in one may start.
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_START_S = 12 * 3600


def _text(value: Any, limit: int = MAX_LINE) -> str:
    # Cut first: only what could survive is ever split and joined.
    return " ".join(str(value or "")[: limit * 4].split())[:limit]


def _count(value: Any) -> int | None:
    return max(0, min(int(value), 100_000)) if isinstance(value, int) and not isinstance(value, bool) else None


def _days(value: Any) -> int | None:
    """Days left, which can be below nought for an objective past its date."""
    return max(-100_000, min(int(value), 100_000)) if isinstance(value, int) and not isinstance(value, bool) else None


def _when(value: Any) -> str | None:
    return _text(value, 40) or None


def order_view(order: dict[str, Any]) -> dict[str, Any]:
    """The fulfilment slip: who it goes to, where, and what goes in the box — the items still to
    send first, each with its size and colour, quantity and SKU."""
    address = order.get("shipping_address") if isinstance(order.get("shipping_address"), dict) else {}
    street = address.get("lines") if isinstance(address.get("lines"), list) else []
    lines = [
        *[_text(x, 120) for x in street[:MAX_ADDRESS_LINES]],
        _text(address.get("city"), 80), _text(address.get("province"), 80), _text(address.get("zip"), 20),
        _text(address.get("country"), 60),
    ]
    raw_items = order.get("items") if isinstance(order.get("items"), list) else []
    every = [item for item in raw_items if isinstance(item, dict)]
    items = []
    for item in every[:MAX_ITEMS]:
        image = str(item.get("image_url") or "")
        items.append({
            "title": _text(item.get("product_title") or item.get("title"), 120),
            "variant": _text(item.get("variant"), 80),
            "sku": _text(item.get("sku"), 60),
            "quantity": _count(item.get("current_quantity", item.get("quantity"))),
            "to_send": _count(item.get("unfulfilled_quantity")),
            "image": image if image.startswith("https://") and len(image) <= MAX_URL else None,
        })
    items.sort(key=lambda i: 0 if (i["to_send"] or 0) > 0 else 1)
    number = _text(order.get("order_number"), 40)
    tags = order.get("tags") if isinstance(order.get("tags"), list) else []
    slip = {
        "number": number,
        "placed_at": _when(order.get("placed_at")),
        "customer": _text(address.get("name") or order.get("customer_name"), 80),
        "company": _text(address.get("company"), 80) or None,
        "address": [line for line in lines if line],
        "phone": _text(address.get("phone"), 40) or None,
        "items": items,
        "note": _text(order.get("note"), 600) or None,
        "tags": [_text(t, 40) for t in tags[:10]],
        "fulfillment": _text(order.get("fulfillment"), 40) or None,
        "payment": _text(order.get("payment"), 40) or None,
        "shipping_method": _text(order.get("shipping_method"), 80) or None,
    }
    if len(every) > MAX_ITEMS:
        # More than a screen takes: shown as far as it goes, and never marked packed from here.
        slip["partial"] = True
        slip["total_items"] = len(every)
    return {
        "kind": "order",
        "ref": _text(order.get("order_id"), MAX_ID),
        "title": f"Order {number}" if number else "Order",
        "order": slip,
    }


def objective_view(summary: dict[str, Any], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An objective as the owner reads it across a room: what is being done now, what needs him,
    and what comes next — the work not yet started, in the order it was proposed."""
    listed = items if isinstance(items, list) else []
    open_items = [i for i in listed[:500] if isinstance(i, dict) and i.get("state") not in ("completed", "verified")]
    waiting = [_text(i.get("text")) for i in open_items if i.get("state") in ("proposed", "authorised")][:8]

    def few(key: str, n: int) -> list[str]:
        value = summary.get(key)
        return [_text(x) for x in (value[:n] if isinstance(value, list) else [])]

    return {
        "kind": "objective",
        "ref": _text(summary.get("id"), MAX_ID),
        "title": _text(summary.get("title"), MAX_TITLE) or "Objective",
        "objective": {
            "deadline": _when(summary.get("deadline")),
            "days_left": _days(summary.get("days_left")),
            "doing": _text(summary.get("doing")) or None,
            "next": waiting or few("next", 8),
            "needs_you": few("needs_you", 6),
            "blocked_by": few("blocked_by", 6),
            "items": [{"text": _text(i.get("text")), "state": _text(i.get("state"), 20)} for i in open_items[:MAX_LINES]],
        },
    }


# An email on a screen (ruling 29): the newest messages of the thread, as CLIVE read it from Gmail,
# each bounded. Never a draft (nobody sent it), never an address where a name is known, and never
# more of the thread than a room can read.
MAX_EMAIL_MESSAGES = 4
MAX_EMAIL_BODY = 1500


def email_view(thread: dict[str, Any]) -> dict[str, Any]:
    """An email thread as the room reads it: the subject, who it is with, and the newest messages,
    each with who wrote it, when, whether it was ours, and its words — from gmail_read_thread's own
    read of Gmail, never from the page or the model."""
    raw = thread.get("messages") if isinstance(thread.get("messages"), list) else []
    sent = [m for m in raw[-50:] if isinstance(m, dict) and not m.get("draft")]
    theirs = [m for m in sent if not m.get("outbound")]
    latest = sent[-1] if sent else {}
    subject = _text((theirs[-1] if theirs else latest).get("subject"), MAX_TITLE)
    messages = [{
        "from": _text(m.get("from") or m.get("from_email"), 80),
        "when": _text(m.get("date"), 60) or None,
        "ours": m.get("outbound") is True,
        # Line breaks are kept (a screen shows the email as it was written); each line is cut first.
        "body": "\n".join(" ".join(line.split())[:MAX_LINE] for line in str(m.get("body") or "")[: MAX_EMAIL_BODY * 2].splitlines())[:MAX_EMAIL_BODY].strip(),
    } for m in sent[-MAX_EMAIL_MESSAGES:]]
    return {
        "kind": "email",
        "ref": _text(thread.get("thread_id"), MAX_ID),
        "title": subject or "Email",
        "email": {
            "with": _text(theirs[-1].get("from") or theirs[-1].get("from_email"), 80) if theirs else None,
            "count": _count(thread.get("message_count")),
            "waiting": thread.get("awaiting_reply") is True,
            "messages": messages,
            "earlier": max(0, len(sent) - MAX_EMAIL_MESSAGES) or None,
        },
    }


def video_view(video: str, *, title: str, channel: str = "", duration_s: int | None = None, live: bool = False,
               start: int = 0) -> dict[str, Any]:
    """A YouTube video, played on the screen in YouTube's own embedded player (web/display.js).
    Only the video's id, its title and channel, how long it is and where to start are kept: the
    screen builds the player's address from the id itself, so nothing here is ever an address."""
    ident = str(video or "")
    if not VIDEO_ID.fullmatch(ident):
        raise ValueError("not a YouTube video id")
    return {
        "kind": "video",
        "ref": ident,
        "title": _text(title, MAX_TITLE) or "YouTube video",
        "video": {
            "id": ident,
            "channel": _text(channel, 80) or None,
            "duration_s": None if live else _count(duration_s),
            "live": bool(live) or None,
            "start": max(0, min(int(start), MAX_START_S)) if isinstance(start, int) and not isinstance(start, bool) else 0,
        },
    }


def list_view(title: str, lines: list[str]) -> dict[str, Any]:
    """A titled list. At most MAX_LINES lines are ever looked at: the tool refuses more before
    this is reached (app/tools/display_tools.py), and this does not rely on it."""
    kept: list[str] = []
    for line in (lines if isinstance(lines, list) else [])[: MAX_LINES * 2]:
        text = _text(line)
        if text:
            kept.append(text)
            if len(kept) == MAX_LINES:
                break
    return {
        "kind": "list",
        "ref": "",
        "title": _text(title, MAX_TITLE) or "List",
        "list": {"lines": kept},
    }
