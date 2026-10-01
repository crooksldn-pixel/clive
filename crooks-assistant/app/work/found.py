"""Work CLIVE finds by itself, read live: orders to pack, emails and Instagram messages waiting.

Nobody writes these down. Each is read from where it lives (Shopify, Gmail, Instagram), with a
short note of what CLIVE already knows, and keyed by what it is about ("order:<id>"), so the list
can show who has claimed it. Every source is asked with a time limit and on its own: a slow inbox
never hides the orders. Each answer is kept a while (a minute for orders, longer for the inboxes),
so a team of phones asking does not ask the services over and over.

Read-only: nothing here changes the shop or the inbox, and a message's text is what the service
holds, untrusted, never an instruction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("crooks.work")

SOURCE_TIMEOUT_S = 12.0
# How long each source's answer is kept: the shop changes fastest, and Instagram's API allows the
# fewest calls an hour (a listing can cost a call for each conversation's latest message).
KEEP_S = {"orders": 60.0, "emails": 120.0, "instagram": 300.0}
# Even a fresh read (a page opened) reuses an answer this young: phones opening together ask once.
MIN_FRESH_S = 10.0
ORDERS_MAX = 25
EMAILS_SCANNED = 20
EMAILS_MAX = 12
INSTAGRAM_MAX = 12

# Each source's last answer, by name. Two phones asking in the same moment may both read a service
# once; that is cheaper than a lock shared across event loops, which a lock made at import would be.
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_ORDERS_QUERY = """
query WorkOrders($q: String!, $n: Int!) {
  orders(first: $n, query: $q, sortKey: PROCESSED_AT, reverse: false) {
    edges { node {
      id name processedAt createdAt note displayFulfillmentStatus displayFinancialStatus
      customer { displayName }
      shippingLine { title }
      lineItems(first: 25) { edges { node { name sku quantity unfulfilledQuantity variantTitle } } }
    } }
  }
}
"""


def reset(source: str = "") -> None:
    """Forget one source's kept answer (by its name in SOURCES), or every source's."""
    if source:
        _CACHE.pop(source, None)
    else:
        _CACHE.clear()


def when(stamp: str | int | float | None) -> datetime | None:
    """A source's time as a moment: Gmail's epoch milliseconds, or an ISO time (Shopify's, and
    Instagram's "+0000" form). None when there is none or it cannot be read."""
    if stamp in (None, "") or isinstance(stamp, bool):
        return None
    try:
        if isinstance(stamp, int | float):
            then = datetime.fromtimestamp(float(stamp) / 1000, UTC)
        else:
            then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, OSError, OverflowError):
        return None
    return then if then.tzinfo else then.replace(tzinfo=UTC)


def _ago(stamp: str | int | None, now: datetime | None = None) -> str:
    then = when(stamp)
    if then is None:
        return ""
    seconds = max(0, int(((now or datetime.now(UTC)) - then).total_seconds()))
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'' if n == 1 else 's'}"
    return "just now"


async def _orders(runtime: Any) -> dict[str, Any]:
    shop = getattr(runtime, "shopify", None)
    graphql = getattr(shop, "graphql", None)
    if not callable(graphql):
        return {"available": False, "reason": "Shopify is not connected", "items": []}
    payload = await graphql(_ORDERS_QUERY, {
        "q": "status:open AND (fulfillment_status:unfulfilled OR fulfillment_status:partial) AND NOT financial_status:voided",
        "n": ORDERS_MAX,
    })
    edges = ((((payload or {}).get("data") or {}).get("orders") or {}).get("edges")) or []
    items = []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        if not node.get("id"):
            continue
        lines = [(e or {}).get("node") or {} for e in ((node.get("lineItems") or {}).get("edges") or [])]
        to_pack = [li for li in lines if int(li.get("unfulfilledQuantity", li.get("quantity", 0)) or 0) > 0]
        count = sum(int(li.get("unfulfilledQuantity", li.get("quantity", 0)) or 0) for li in to_pack)
        who = ((node.get("customer") or {}).get("displayName")) or "a customer"
        placed = node.get("processedAt") or node.get("createdAt") or ""
        note = " ".join(str(node.get("note") or "").split())[:200]
        items.append({
            "ref": f"order:{node['id']}",
            "kind": "pack_order",
            "title": f"Pack {node.get('name')}: {count} item{'s' if count != 1 else ''} for {who}",
            "details": "; ".join(filter(None, [
                f"placed {_ago(placed)} ago" if _ago(placed) else "",
                ((node.get("shippingLine") or {}).get("title") or ""),
                f"note: {note}" if note else "",
            ])),
            "order_number": node.get("name"),
            "lines": [{"item": f"{li.get('name')}" + (f" ({li.get('variantTitle')})" if li.get("variantTitle") else ""),
                       "sku": li.get("sku") or "",
                       "quantity": int(li.get("unfulfilledQuantity", li.get("quantity", 0)) or 0)} for li in to_pack],
            "since": placed,
            "partly": node.get("displayFulfillmentStatus") == "PARTIALLY_FULFILLED",
        })
    return {"available": True, "items": items}


async def _customer_note(runtime: Any, email: str) -> str:
    """What CLIVE already knows about who wrote: how many orders, and the latest's state."""
    shop = getattr(runtime, "shopify", None)
    graphql = getattr(shop, "graphql", None)
    if not callable(graphql) or "@" not in str(email or ""):
        return ""
    try:
        payload = await asyncio.wait_for(graphql(
            "query WorkCustomer($q: String!) { customers(first: 1, query: $q) { edges { node { "
            "numberOfOrders orders(first: 1, sortKey: PROCESSED_AT, reverse: true) { edges { node { "
            "name displayFulfillmentStatus } } } } } } }",
            {"q": f"email:{email}"}), 6.0)
    except Exception:  # noqa: BLE001 - a note is a nicety; its absence is not a fault
        return ""
    edges = ((((payload or {}).get("data") or {}).get("customers") or {}).get("edges")) or []
    if not edges:
        return "Not a customer in the shop yet."
    node = edges[0].get("node") or {}
    orders = int(node.get("numberOfOrders") or 0)
    latest = [((e or {}).get("node") or {}) for e in ((node.get("orders") or {}).get("edges") or [])]
    if not orders:
        return "A customer with no orders yet."
    tail = ""
    if latest:
        state = str(latest[0].get("displayFulfillmentStatus") or "").replace("_", " ").lower()
        tail = f"; the latest, {latest[0].get('name')}, is {state}" if state else f"; the latest is {latest[0].get('name')}"
    return f"{orders} order{'s' if orders != 1 else ''}{tail}."


async def _emails(runtime: Any) -> dict[str, Any]:
    from app.tools import gmail_tools

    listing = await gmail_tools.inbox_threads(days=14, limit=EMAILS_SCANNED)
    if not listing.get("available"):
        return {"available": False, "reason": listing.get("reason") or "Gmail is not connected", "items": []}
    threads = listing.get("threads") or []
    gate = asyncio.Semaphore(5)

    async def state(thread: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        async with gate:
            return thread, await gmail_tools.reply_state(thread.get("thread_id") or "")

    waiting = []
    for thread, reply in await asyncio.gather(*(state(t) for t in threads)):
        if reply and reply.get("waiting_since") and not reply.get("has_reply_after_latest_inbound"):
            waiting.append((thread, reply))
    waiting.sort(key=lambda pair: pair[1].get("waiting_since") or 0)
    waiting = waiting[:EMAILS_MAX]
    notes = await asyncio.gather(*(_customer_note(runtime, t.get("from_email") or "") for t, _ in waiting))
    items = []
    for (thread, reply), note in zip(waiting, notes, strict=True):
        who = thread.get("from") or thread.get("from_email") or "someone"
        items.append({
            "ref": f"email:{thread['thread_id']}",
            "kind": "reply_email",
            "title": f"Reply to {who}: {thread.get('subject') or '(no subject)'}"[:160],
            "details": "; ".join(filter(None, [f"waiting {_ago(reply.get('waiting_since'))}", note])),
            "snippet": thread.get("snippet") or "",
            "from_email": thread.get("from_email") or "",
            "since": reply.get("waiting_since"),
        })
    return {"available": True, "items": items}


async def _instagram(runtime: Any) -> dict[str, Any]:
    from app.clients import instagram

    if not instagram.token():
        return {"available": False, "reason": "Instagram is not connected", "items": []}
    account = await instagram.account()
    found = await instagram.conversations(limit=INSTAGRAM_MAX)
    items = []
    for conversation in found:
        latest = conversation.get("latest") or {}
        if not latest or instagram.is_ours(latest.get("from"), account):
            continue
        who = conversation.get("username") or "someone"
        items.append({
            "ref": f"instagram:{conversation['conversation_id']}",
            "kind": "reply_instagram",
            "title": f"Instagram: @{who} is waiting",
            "details": f"waiting {_ago(latest.get('created_time'))}" if latest.get("created_time") else "",
            "snippet": (latest.get("text") or ("(an attachment)" if latest.get("attachments") else ""))[:300],
            "since": latest.get("created_time") or "",
        })
    items.sort(key=lambda item: item["since"] or "")
    return {"available": True, "items": items}


SOURCES = {"orders": _orders, "emails": _emails, "instagram": _instagram}


async def found(runtime: Any, *, fresh: bool = False) -> dict[str, dict[str, Any]]:
    """Every source's live work: {"orders": {...}, "emails": {...}, "instagram": {...}}, each read
    again once its own keeping time has passed, or now when `fresh`."""

    async def ask(name: str, source) -> tuple[str, dict[str, Any]]:
        held = _CACHE.get(name)
        if held and time.monotonic() - held[0] < (MIN_FRESH_S if fresh else KEEP_S.get(name, 60.0)):
            return name, held[1]
        try:
            answer = await asyncio.wait_for(source(runtime), SOURCE_TIMEOUT_S)
        except TimeoutError:
            answer = {"available": False, "reason": "did not answer in time", "items": []}
        except Exception as exc:  # noqa: BLE001 - one source failing never hides the rest
            log.warning("work: %s unavailable (%s)", name, type(exc).__name__)
            answer = {"available": False, "reason": "could not be read just now", "items": []}
        _CACHE[name] = (time.monotonic(), answer)
        return name, answer

    return dict(await asyncio.gather(*(ask(n, s) for n, s in SOURCES.items())))
