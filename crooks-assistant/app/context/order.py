"""The order as the tablet shows it: one nested read, then the customer's history and the
inbox around it, fetched beside each other under a budget rather than one after the other.

The read model is a plain dict shaped here, key by key, from what Shopify returned — the
same discipline as app/presentation.py, one layer down. The model reads the same dict the
card is built from, so the spoken answer and the screen cannot disagree.

Enrichment that misses the budget is not lost: it carries on in the background, and the
tablet collects it from GET /context/order/{id} once the card is up. Nothing is hydrated
serially in front of the first paint.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.clients.shopify import ShopifyClient, ShopifyError
from app.context.attention import attention_for
from app.tools.registry import ToolError

log = logging.getLogger("crooks.context")

# Bounds. The card is eight inches wide; the model's context is not free either.
MAX_ITEMS = 12
RECENT_ORDERS = 5
EMAIL_THREADS = 3
MAX_EVENTS = 5
MAX_REFUNDS = 6
MAX_TEXT = 200
# A customer's own inbox read: a year back, enough threads for a timeline, and their address
# with up to four of their order numbers (two spellings each) as the terms.
CUSTOMER_EMAIL_DAYS = 365
CUSTOMER_EMAIL_LIMIT = 10
CUSTOMER_EMAIL_TERMS = 9
# How long the tool waits for the customer's history and the inbox before answering with
# what it has. The order itself is never waited on twice.
ENRICH_BUDGET_S = 1.5
# A finished enrichment is reused for the same order this long: a second look at the order
# a moment later re-reads the order (its state matters) but not the customer's history.
ENRICH_REUSE_S = 60.0
JOB_RETENTION_S = 600.0

# How long a freshly read order is reused for: the search the Mac runs ahead of the model
# already holds the whole order, and the model's own detail call a moment later must not
# read it again. Short, because an order's state is what every change turns on.
CORE_REUSE_S = 5.0
# What a detail call made BY THE MODEL waits for the history and the inbox: the card
# collects the rest, and the model is told what is still on its way.
MODEL_BUDGET_S = 0.25

# One selection, validated against the Admin API schema (2025-07), used by both documents
# below. Items, fulfilments, refunds and events are capped well under the 1,000-point cost.
# The image is asked for at the width the card draws, so the CDN's own rendition is served.
_ORDER_SELECTION = """
    id
    name
    email
    createdAt
    processedAt
    cancelledAt
    cancelReason
    closedAt
    displayFulfillmentStatus
    displayFinancialStatus
    returnStatus
    fullyPaid
    tags
    note
    refundable
    currentTotalPriceSet { shopMoney { amount currencyCode } }
    subtotalPriceSet { shopMoney { amount currencyCode } }
    totalShippingPriceSet { shopMoney { amount currencyCode } }
    totalTaxSet { shopMoney { amount currencyCode } }
    totalDiscountsSet { shopMoney { amount currencyCode } }
    totalRefundedSet { shopMoney { amount currencyCode } }
    totalOutstandingSet { shopMoney { amount currencyCode } }
    shippingLine { title }
    shippingAddress {
      firstName lastName company address1 address2 city province provinceCode zip country countryCodeV2
    }
    customer {
      id
      displayName
      numberOfOrders
      createdAt
      amountSpent { amount currencyCode }
      defaultEmailAddress { emailAddress }
    }
    lineItems(first: $n) {
      edges { node {
        id
        title
        quantity
        currentQuantity
        refundableQuantity
        unfulfilledQuantity
        variantTitle
        sku
        originalTotalSet { shopMoney { amount currencyCode } }
        discountedTotalSet { shopMoney { amount currencyCode } }
        image { url(transform: {maxWidth: 320}) width height }
        variant {
          id
          inventoryQuantity
          inventoryItem { id tracked }
          selectedOptions { name value }
        }
        product { id title }
      } }
    }
    fulfillments(first: 10) {
      id
      status
      displayStatus
      createdAt
      trackingInfo { company number url }
    }
    refunds(first: 10) {
      id
      createdAt
      note
      totalRefundedSet { shopMoney { amount currencyCode } }
      transactions(first: 3) {
        edges { node {
          kind status gateway formattedGateway processedAt errorCode
          amountSet { shopMoney { amount currencyCode } }
          paymentDetails { ... on CardPaymentDetails { company number } }
        } }
      }
    }
    events(first: 5, sortKey: CREATED_AT, reverse: true) {
      edges { node { id message createdAt } }
    }
"""

ORDER_CONTEXT_QUERY = f"""
query CrooksOrderContext($id: ID!, $n: Int!) {{
  order(id: $id) {{ {_ORDER_SELECTION} }}
}}
"""

# The search by order number, carrying the whole order: one round trip yields the summary
# the model is handed AND the order the card is built from.
ORDER_BY_NAME_QUERY = f"""
query CrooksOrderByName($q: String!, $n: Int!) {{
  orders(first: 2, query: $q, sortKey: CREATED_AT, reverse: true) {{
    edges {{ node {{ {_ORDER_SELECTION} }} }}
  }}
}}
"""

CUSTOMER_ORDERS_QUERY = """
query CrooksCustomerOrders($id: ID!, $n: Int!) {
  customer(id: $id) {
    id
    displayName
    numberOfOrders
    createdAt
    tags
    amountSpent { amount currencyCode }
    defaultEmailAddress { emailAddress }
    lastOrder { id name }
    firstOrder: orders(first: 1, sortKey: CREATED_AT) {
      edges { node { id name processedAt createdAt } }
    }
    openOrders: orders(first: 5, query: "fulfillment_status:unfulfilled", sortKey: CREATED_AT, reverse: true) {
      edges { node { id name cancelledAt displayFulfillmentStatus } }
    }
    orders(first: $n, sortKey: CREATED_AT, reverse: true) {
      edges { node {
        id
        name
        createdAt
        processedAt
        cancelledAt
        displayFulfillmentStatus
        displayFinancialStatus
        returnStatus
        note
        currentTotalPriceSet { shopMoney { amount currencyCode } }
        totalPriceSet { shopMoney { amount currencyCode } }
        lineItems(first: 5) { edges { node { title quantity variantTitle } } }
        fulfillments(first: 3) { createdAt displayStatus trackingInfo(first: 1) { company } }
        refunds(first: 3) {
          createdAt
          totalRefundedSet { shopMoney { amount currencyCode } }
          transactions(first: 2) { edges { node { kind status gateway formattedGateway processedAt errorCode amountSet { shopMoney { amount currencyCode } } } } }
        }
      } }
    }
  }
}
"""

ThreadsFor = Callable[..., Awaitable[dict[str, Any]]]


def money(node: Any) -> str | None:
    """"430.50 GBP" — the same text form every tool returns, so the card formats it once."""
    if not isinstance(node, dict):
        return None
    shop = node.get("shopMoney") or node
    amount = shop.get("amount") if isinstance(shop, dict) else None
    if amount is None:
        return None
    return f"{amount} {shop.get('currencyCode', '')}".strip()


def money_amount(node: Any) -> float | None:
    if not isinstance(node, dict):
        return None
    shop = node.get("shopMoney") or node
    try:
        return float(shop.get("amount"))
    except (TypeError, ValueError, AttributeError):
        return None


def order_digits(name: Any) -> str:
    """"CROOKS-1938" and "#1036" are order 1938 and order 1036 to the office."""
    text = str(name or "").strip()
    digits = text.rsplit("-", 1)[-1].lstrip("#").strip()
    return digits if digits.isdigit() else ""


# ------------------------------------------------------------------ the order itself


def shape_order(node: dict[str, Any]) -> dict[str, Any]:
    """The order read model from one CrooksOrderContext node. Every key is chosen here; a
    field Shopify adds does not reach the model or the card until a line here carries it."""
    customer = node.get("customer") or {}
    email = (customer.get("defaultEmailAddress") or {}).get("emailAddress")
    items = []
    for edge in ((node.get("lineItems") or {}).get("edges") or [])[:MAX_ITEMS]:
        it = edge.get("node") or {}
        variant = it.get("variant") or {}
        inventory_item = variant.get("inventoryItem") or {}
        image = it.get("image") or {}
        quantity = it.get("quantity")
        items.append({
            "line_item_id": it.get("id"),
            "title": it.get("title"),
            "variant": it.get("variantTitle"),
            "sku": it.get("sku"),
            "quantity": quantity,
            "current_quantity": it.get("currentQuantity", quantity),
            "refundable_quantity": it.get("refundableQuantity"),
            "unfulfilled_quantity": it.get("unfulfilledQuantity"),
            "total": money(it.get("originalTotalSet")),
            "discounted_total": money(it.get("discountedTotalSet")),
            "image_url": image.get("url"),
            "variant_id": variant.get("id"),
            "product_id": (it.get("product") or {}).get("id"),
            "product_title": (it.get("product") or {}).get("title"),
            "options": [
                {"name": str(o.get("name", ""))[:40], "value": str(o.get("value", ""))[:40]}
                for o in (variant.get("selectedOptions") or [])[:4] if isinstance(o, dict)
            ],
            "stock": {
                "tracked": bool(inventory_item.get("tracked", True)),
                "available": variant.get("inventoryQuantity"),
                "inventory_item_id": inventory_item.get("id"),
            } if variant else None,
        })
    fulfillments = []
    for f in (node.get("fulfillments") or [])[:10]:
        tracking = (f.get("trackingInfo") or [{}])[0] or {}
        fulfillments.append({
            "fulfillment_id": f.get("id"),
            "status": f.get("status"),
            "display_status": f.get("displayStatus"),
            "shipped_at": f.get("createdAt"),
            "carrier": tracking.get("company"),
            "number": tracking.get("number"),
            "url": tracking.get("url"),
        })
    refunds = [_refund(r) for r in (node.get("refunds") or [])[:MAX_REFUNDS] if isinstance(r, dict)]
    events = [
        {"at": (e.get("node") or {}).get("createdAt"), "message": _short((e.get("node") or {}).get("message"), 120)}
        for e in ((node.get("events") or {}).get("edges") or [])[:MAX_EVENTS]
    ]
    address = node.get("shippingAddress") or {}
    total = node.get("currentTotalPriceSet")
    return {
        "order_id": node.get("id"),
        "order_number": node.get("name"),
        "placed_at": node.get("processedAt") or node.get("createdAt"),
        "fulfillment": node.get("displayFulfillmentStatus"),
        "payment": node.get("displayFinancialStatus"),
        "total": money(total),
        "customer_name": customer.get("displayName"),
        "customer_id": customer.get("id"),
        # The address on the order first: a customer who changed their account email after
        # ordering wrote in from the one on the order, and is answered there.
        "customer_email": (str(node.get("email") or "").strip().lower() or email),
        "customer": {
            "customer_id": customer.get("id"),
            "name": customer.get("displayName"),
            "email": email,
            "orders": _int(customer.get("numberOfOrders")),
            "spent": money(customer.get("amountSpent")),
            "since": customer.get("createdAt"),
        } if customer else None,
        "items": items,
        "items_truncated": len(items) >= MAX_ITEMS,
        "fulfillments": fulfillments,
        "cancelled_at": node.get("cancelledAt"),
        "cancel_reason": node.get("cancelReason"),
        "closed_at": node.get("closedAt"),
        "return_status": node.get("returnStatus"),
        "fully_paid": node.get("fullyPaid"),
        "note": _short(node.get("note"), 1200),
        "tags": [str(t)[:40] for t in (node.get("tags") or [])[:10]],
        "money": {
            "subtotal": money(node.get("subtotalPriceSet")),
            "shipping": money(node.get("totalShippingPriceSet")),
            "tax": money(node.get("totalTaxSet")),
            "discounts": money(node.get("totalDiscountsSet")),
            "refunded": money(node.get("totalRefundedSet")),
            "outstanding": money(node.get("totalOutstandingSet")),
            "total": money(total),
            "currency": ((total or {}).get("shopMoney") or {}).get("currencyCode"),
        },
        "refundable": node.get("refundable"),
        "refunds": refunds,
        "shipping_method": ((node.get("shippingLine") or {}).get("title")),
        # City and country for a spoken answer; the address itself is for the card and for
        # the change-of-address diff, and is redacted by key wherever a log might carry it.
        "ships_to": ", ".join(p for p in (address.get("city"), address.get("country")) if p) or None,
        "shipping_address": shape_address(address) if address else None,
        "events": events,
    }


def _refund(r: dict[str, Any]) -> dict[str, Any]:
    """One refund, and — when Shopify read its transactions — whether the money has gone back,
    in the payment provider's own answer (app/customers/payments.py). Without the transactions
    it is the record alone, as it always was."""
    out = {"refund_id": r.get("id"), "created_at": r.get("createdAt"),
           "amount": money(r.get("totalRefundedSet")), "note": _short(r.get("note"))}
    if r.get("transactions") is not None:
        from app.customers import payments

        state = payments.refund_state(r, policy=payments.policy_line())
        out.update({"state": state["state"], "landed": state["landed"], "paid_to": state["to"] or None,
                    "processed_at": state["processed_at"], "means": state["means"],
                    # For the order card alone (payments.CARD_ONLY): `model_view` drops them.
                    "landed_card": state["landed_card"], "paid_to_card": state["paid_to_card"] or None})
    return out


def summary(order: dict[str, Any]) -> dict[str, Any]:
    """The thin shape a search returns: the same keys shopify_find_order always had."""
    return {k: order.get(k) for k in ("order_id", "order_number", "placed_at", "fulfillment", "payment", "total", "customer_name", "customer_id", "customer_email")}


def shape_address(address: dict[str, Any]) -> dict[str, Any]:
    name = " ".join(p for p in (address.get("firstName"), address.get("lastName")) if p)
    lines = [address.get("address1"), address.get("address2")]
    return {
        "name": name or None,
        "company": address.get("company") or None,
        "lines": [str(line)[:120] for line in lines if line],
        "city": address.get("city") or None,
        "province": address.get("province") or None,
        "province_code": address.get("provinceCode") or None,
        "zip": address.get("zip") or None,
        "country": address.get("country") or None,
        "country_code": address.get("countryCodeV2") or None,
    }


# --------------------------------------------------------------- the customer's history


def shape_customer_history(node: dict[str, Any], *, current_order_id: str | None = None) -> dict[str, Any]:
    """What the owner asks about a person: first order? bought before? spent? last order?
    anything else waiting to ship?"""
    recent = []
    other_unfulfilled = []
    for edge in ((node.get("orders") or {}).get("edges") or [])[:RECENT_ORDERS]:
        o = edge.get("node") or {}
        brief = ", ".join(
            f"{(e.get('node') or {}).get('title', '')}" + (f" ×{(e.get('node') or {}).get('quantity')}" if (e.get('node') or {}).get('quantity', 1) not in (1, None) else "")
            for e in ((o.get("lineItems") or {}).get("edges") or [])[:5]
        )
        row = {
            "order_id": o.get("id"),
            "order_number": o.get("name"),
            "placed_at": o.get("processedAt") or o.get("createdAt"),
            "fulfillment": o.get("displayFulfillmentStatus"),
            "payment": o.get("displayFinancialStatus"),
            "cancelled_at": o.get("cancelledAt"),
            "total": money(o.get("currentTotalPriceSet")),
            "items_brief": brief[:MAX_TEXT] or None,
            "current": bool(current_order_id) and o.get("id") == current_order_id,
        }
        row.update(_story(o))
        recent.append(row)
        if (
            not row["current"] and not row["cancelled_at"]
            and str(row["fulfillment"] or "").upper() in {"UNFULFILLED", "PARTIALLY_FULFILLED", "ON_HOLD", "SCHEDULED"}
        ):
            other_unfulfilled.append(row["order_number"])
    count = _int(node.get("numberOfOrders"))
    email = (node.get("defaultEmailAddress") or {}).get("emailAddress")
    last = node.get("lastOrder") or {}
    # The first order and the open orders come from their own small connections, so a regular
    # with twelve orders is answered from all twelve, not from the five shown.
    first_edges = ((node.get("firstOrder") or {}).get("edges") or [])
    first = (first_edges[0].get("node") or {}) if first_edges else {}
    first_at = first.get("processedAt") or first.get("createdAt")
    if not first_at and recent and count is not None and count <= len(recent):
        first_at = recent[-1]["placed_at"]
    open_edges = (node.get("openOrders") or {}).get("edges")
    if open_edges is not None:
        other_unfulfilled = [
            (e.get("node") or {}).get("name") for e in open_edges
            if isinstance(e.get("node"), dict) and (e["node"].get("id") != current_order_id) and not e["node"].get("cancelledAt")
            and e["node"].get("name")
        ]
    return {
        "customer_id": node.get("id"),
        "name": node.get("displayName"),
        "email": email,
        "orders": count,
        "spent": money(node.get("amountSpent")),
        "since": node.get("createdAt"),
        "tags": [str(t)[:40] for t in (node.get("tags") or [])[:10]],
        "standing": standing(count),
        "first_order_at": first_at,
        "last_order": {"order_id": last.get("id"), "order_number": last.get("name")} if last else None,
        "recent": recent,
        "recent_truncated": bool(count is not None and count > len(recent)),
        "other_unfulfilled": other_unfulfilled,
        "provenance": "SHOPIFY",
    }


def _story(o: dict[str, Any]) -> dict[str, Any]:
    """What happened to one of a customer's orders after it was placed — shipped, refunded,
    returned, noted — for the customer's timeline (app/customers/history.py). Only the keys
    Shopify answered: a read from before these were asked for adds nothing."""
    out: dict[str, Any] = {}
    if o.get("totalPriceSet"):
        # What was paid, before any refund — what "Ordered" says in the story.
        out["paid"] = money(o.get("totalPriceSet"))
    if "fulfillments" in o:
        out["shipped"] = [
            {"at": f.get("createdAt"), "status": f.get("displayStatus"),
             "carrier": ((f.get("trackingInfo") or [{}])[0] or {}).get("company")}
            for f in (o.get("fulfillments") or [])[:3] if isinstance(f, dict)
        ]
    if "refunds" in o:
        from app.customers import payments

        out["refunds"] = []
        for r in (o.get("refunds") or [])[:3]:
            if not isinstance(r, dict):
                continue
            state = payments.refund_state(r) if r.get("transactions") is not None else {}
            out["refunds"].append({"at": r.get("createdAt"), "amount": money(r.get("totalRefundedSet")),
                                   "state": state.get("state"), "landed": state.get("landed")})
    if o.get("returnStatus") and str(o.get("returnStatus")).upper() != "NO_RETURN":
        out["return_status"] = o.get("returnStatus")
    if o.get("note"):
        out["note"] = _short(o.get("note"), 160)
    return out


def standing(count: int | None) -> str:
    if count is None:
        return "unknown"
    if count <= 1:
        return "first order"
    if count >= 4:
        return "regular"
    return "returning"


# ---------------------------------------------------------------- the inbox around it


def correlate_threads(threads: list[dict[str, Any]], *, customer_email: str | None, digits: str) -> list[dict[str, Any]]:
    """Which threads are about this order, and how sure that is. A From header that equals
    the order's customer is a match; it is VERIFIED only when the receiving server's own
    Authentication-Results say the mail passed DKIM or SPF for that sender — a From header
    is a claim anyone can write. The order number alone is a mention. A name match is
    nothing at all: anyone can be called Sam."""
    email = (customer_email or "").strip().lower()
    out = []
    for t in threads:
        sender = str(t.get("from_email") or "").strip().lower()
        text = f"{t.get('subject', '')} {t.get('snippet', '')}"
        mentions = bool(digits) and re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", text) is not None
        matches = bool(email) and sender == email
        if not matches and not mentions:
            continue
        verified = matches and bool(t.get("authenticated"))
        out.append({
            **t,
            "sender_match": matches,
            "verified_sender": verified,
            "match": "both" if matches and mentions else ("sender" if matches else "order_number"),
            "provenance": "CUSTOMER_EMAIL" if matches else "UNKNOWN",
        })
    return out[:EMAIL_THREADS]


# ------------------------------------------------------------- what the model reads

# What the model is told while a part of the order is still on its way: never "none".
_PENDING_WORDS = {
    "history": "still being read — do not say the customer has no history",
    "email": "still being read — do not say there is no email",
}


def model_view(order: dict[str, Any]) -> dict[str, Any]:
    """The order as the model reads it. The card gets the street address, the image paths
    and the ids of things that are never spoken; the voice gets the town, the postcode's
    outward part, and every fact it may need to answer with or act on."""
    out = dict(order)
    address = order.get("shipping_address") if isinstance(order.get("shipping_address"), dict) else None
    out.pop("shipping_address", None)
    if address:
        zip_code = str(address.get("zip") or "").strip().upper()
        out["ships_to"] = ", ".join(p for p in (address.get("city"), zip_code.split(" ")[0] if zip_code else None, address.get("country")) if p) or out.get("ships_to")
    out["items"] = [
        {k: v for k, v in item.items() if k not in ("image_url",)} for item in order.get("items") or [] if isinstance(item, dict)
    ]
    for item in out["items"]:
        stock = item.get("stock")
        if isinstance(stock, dict):
            item["stock"] = {k: v for k, v in stock.items() if k != "inventory_item_id"}
    out["fulfillments"] = [
        {k: v for k, v in f.items() if k not in ("fulfillment_id", "url")} for f in order.get("fulfillments") or [] if isinstance(f, dict)
    ]
    # A refund's id is never spoken, and the card it went back to is the order card's alone
    # (app/customers/payments.py CARD_ONLY): the model reads "the card it was paid with".
    from app.customers.payments import CARD_ONLY

    out["refunds"] = [{k: v for k, v in r.items() if k != "refund_id" and k not in CARD_ONLY}
                      for r in order.get("refunds") or [] if isinstance(r, dict)]
    for part, words in _PENDING_WORDS.items():
        if part in (order.get("pending") or []):
            out[part] = words
    email = out.get("email")
    if isinstance(email, dict):
        out["email"] = {
            **email,
            "threads": [{k: v for k, v in t.items() if k not in ("likely_bulk", "authenticated")} for t in email.get("threads") or [] if isinstance(t, dict)],
        }
    out.pop("events", None) if not order.get("events") else None
    return out


# ------------------------------------------------------------------------ the hydrator


class _Job:
    """One order's enrichment in flight: the parts land one by one, so a caller who cannot
    wait for all of them takes what is there and says what is still to come."""

    __slots__ = ("order_id", "parts", "task", "started", "finished", "core")

    def __init__(self, order_id: str, started: float) -> None:
        self.order_id = order_id
        self.parts: dict[str, Any] = {}
        self.core: dict[str, Any] | None = None   # the order the parts belong to, for a later reading
        self.task: asyncio.Task | None = None
        self.started = started
        self.finished: float | None = None

    @property
    def pending(self) -> list[str]:
        return [name for name in ("history", "email") if name not in self.parts]


class Hydrator:
    """Builds the read models. One per process; the tools and the /context route share it so
    an order looked up ahead of the model is not looked up again a second later."""

    def __init__(self, shopify: Callable[[], ShopifyClient], *, threads_for: ThreadsFor | None = None, clock=time.time) -> None:
        self._shopify = shopify
        self._threads_for = threads_for
        self.clock = clock
        self._jobs: dict[str, _Job] = {}
        # An order read in flight, or just read: two callers share it, and the model's detail
        # call a moment after the search finds the order already in hand.
        self._cores: dict[str, tuple[asyncio.Future, float]] = {}
        self.core_reads = 0
        self.on_forget: list[Callable[[str], None]] = []

    # -------------------------------------------------------------- order

    async def order(self, order_id: str, *, budget_s: float = ENRICH_BUDGET_S, fresh: bool = False, request_id: str = "") -> dict[str, Any]:
        """The order, with as much of its history and inbox as arrives within the budget.
        `pending` names what is still on its way. An order read a moment ago is reused;
        `fresh` reads it again regardless — what a change is checked against, and proved
        by, is never a copy."""
        started = time.perf_counter()
        if fresh:
            self._cores.pop(order_id, None)
        reused = order_id in self._cores
        try:
            core = await self._core(order_id)
        except Exception as exc:
            self._trace("order", order_id, request_id, started, error=exc, budget_s=budget_s, reused_core=reused)
            raise
        job = self._enrich(order_id, core)
        if budget_s > 0 and job.task is not None and not job.task.done():
            await asyncio.wait({job.task}, timeout=budget_s)
        self._trace("order", order_id, request_id, started, job=job, budget_s=budget_s, reused_core=reused, fresh=fresh)
        return self._merge(core, job)

    async def extension(self, order_id: str, *, wait_s: float, request_id: str = "") -> dict[str, Any]:
        """What the tablet collects after the card is up: the parts of the enrichment that
        missed the turn's budget. Starts the work if nothing is in flight (a restart, a card
        the owner came back to)."""
        started = time.perf_counter()
        job = self._jobs.get(order_id)
        reused = job is not None
        if job is None or (job.finished is not None and self.clock() - job.finished > ENRICH_REUSE_S):
            try:
                core = await self._core(order_id)
            except Exception as exc:
                self._trace("extension", order_id, request_id, started, error=exc, budget_s=wait_s, reused_core=False)
                raise
            job = self._enrich(order_id, core)
        if job.task is not None and not job.task.done() and wait_s > 0:
            await asyncio.wait({job.task}, timeout=wait_s)
        out = {"order_id": order_id, "pending": job.pending, **{k: v for k, v in job.parts.items()}}
        if job.core is not None:
            # Read again with what has landed: the card's attention lines follow the parts.
            out["attention"] = self._merge(job.core, job)["attention"]
        self._trace("extension", order_id, request_id, started, job=job, budget_s=wait_s, reused_core=reused)
        return out

    def _trace(self, kind: str, order_id: str, request_id: str, started: float, *, job: _Job | None = None, error: BaseException | None = None, **fields: Any) -> None:
        """One `context_hydration` event per read, for the test-session timeline: what was
        asked for, how long it took, which parts landed and which are still on their way."""
        from app.observability import timeline

        if timeline.current().active is None:
            return
        landed = [k for k, v in (job.parts.items() if job is not None else ()) if v is not None]
        missing = [k for k, v in (job.parts.items() if job is not None else ()) if v is None]
        timeline.emit(
            "context_hydration", context_request_id=request_id or timeline.new_id("ctx"), hydration=kind, order_id=order_id,
            ms=round((time.perf_counter() - started) * 1000, 1), landed=landed, unavailable=missing,
            pending=(job.pending if job is not None else None), error=(f"{type(error).__name__}: {error}"[:200] if error is not None else None), **fields,
        )

    async def customer(self, customer_id: str) -> dict[str, Any]:
        """A customer's history on its own, with the inbox around them."""
        started = time.perf_counter()
        history = await self._history(customer_id, current_order_id=None)
        self._trace("customer", customer_id, "", started, landed_history=history is not None)
        if history is None:
            raise ToolError(f"No customer with id {customer_id}.")
        # Two inbox reads side by side. `email_threads` is what it always was — the search for
        # threads FROM them — so their own email is never crowded out of the card and the model by
        # others about their orders; `_threads` is the wide one the customer's story is made from
        # (app/customers/history.py), and only that.
        email, threads = await asyncio.gather(self._email(history.get("email"), digits=""), self._customer_threads(history))
        return {**history, "email_threads": email, "_threads": threads}

    async def _customer_threads(self, history: dict[str, Any]) -> list[dict[str, Any]]:
        """For the customer's story: anything from them, anything naming their address, and
        anything naming one of their recent orders as an order is written ("#2201", "CROOKS-2201")
        — over a year rather than an order's sixty days. Empty when the inbox cannot say."""
        if self._threads_for is None:
            return []
        address = str(history.get("email") or "").strip().lower()
        numbers = [order_digits(r.get("order_number")) for r in history.get("recent") or [] if isinstance(r, dict)]
        terms = ([address] if address else []) + [t for d in numbers if d for t in (f"CROOKS-{d}", f"#{d}")]
        try:
            found = await self._threads_for(sender=address, terms=terms[:CUSTOMER_EMAIL_TERMS],
                                            days=CUSTOMER_EMAIL_DAYS, limit=CUSTOMER_EMAIL_LIMIT)
        except Exception as exc:  # noqa: BLE001 — the story stands without the inbox
            log.warning("customer story email unavailable: %s", type(exc).__name__)
            return []
        if not found.get("available"):
            return []
        return [t for t in found.get("threads") or [] if isinstance(t, dict)]

    def forget(self, order_id: str) -> None:
        """The order has just been changed: whatever was held of it is no longer it — here,
        and in whatever else holds a copy (the read layer's cache)."""
        self._cores.pop(order_id, None)
        for listener in list(self.on_forget):
            try:
                listener(order_id)
            except Exception:  # noqa: BLE001 — a listener never stops the forgetting
                log.debug("forget listener failed", exc_info=True)

    # --------------------------------------------------------- internals

    async def find_by_number(self, digits: str, *, limit: int = 2) -> list[dict[str, Any]]:
        """The orders named by a number, whole. Each is kept as read for a few seconds, so
        the detail call that follows a search costs nothing; a single match starts its
        history and inbox at once, beside whatever happens next."""
        payload = await self._shopify().graphql(ORDER_BY_NAME_QUERY, {"q": f"name:{digits}", "n": MAX_ITEMS})
        edges = ((payload.get("data") or {}).get("orders") or {}).get("edges") or []
        orders: list[dict[str, Any]] = []
        now = self.clock()
        for edge in edges[:limit]:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict) or not node.get("id"):
                continue
            shaped = shape_order(node)
            if payload.get("_partial_errors"):
                shaped["partial"] = str(payload["_partial_errors"])[:200]
            done: asyncio.Future = asyncio.get_running_loop().create_future()
            done.set_result(shaped)
            self._cores[str(node["id"])] = (done, now)
            orders.append(shaped)
        if len(orders) == 1:
            self._enrich(orders[0]["order_id"], orders[0])
        return orders

    async def _core(self, order_id: str) -> dict[str, Any]:
        held = self._cores.get(order_id)
        now = self.clock()
        if held is not None and (not held[0].done() or now - held[1] < CORE_REUSE_S) and not (held[0].done() and held[0].exception() is not None):
            return await held[0]
        task = asyncio.ensure_future(self._read_order(order_id))
        self._cores[order_id] = (task, now)
        try:
            return await task
        except Exception:
            self._cores.pop(order_id, None)
            raise

    async def _read_order(self, order_id: str) -> dict[str, Any]:
        self.core_reads += 1
        payload = await self._shopify().graphql(ORDER_CONTEXT_QUERY, {"id": order_id, "n": MAX_ITEMS})
        node = (payload.get("data") or {}).get("order")
        if not isinstance(node, dict) or node.get("id") != order_id:
            raise ToolError(f"No order with id {order_id}.")
        shaped = shape_order(node)
        if payload.get("_partial_errors"):
            shaped["partial"] = str(payload["_partial_errors"])[:200]
        return shaped

    def _enrich(self, order_id: str, core: dict[str, Any]) -> _Job:
        self._prune()
        job = self._jobs.get(order_id)
        now = self.clock()
        if job is not None and (job.finished is None or now - job.finished < ENRICH_REUSE_S):
            return job
        job = _Job(order_id, now)
        job.core = core
        self._jobs[order_id] = job
        job.task = asyncio.ensure_future(self._run(job, core))
        return job

    async def _run(self, job: _Job, core: dict[str, Any]) -> None:
        customer = core.get("customer") or {}
        customer_id = customer.get("customer_id")
        digits = order_digits(core.get("order_number"))

        async def history() -> None:
            # Three different truths, kept apart: the order has no customer (None); the customer
            # was read (a dict); the read FAILED (a dict that says so). The Phase 2 live test
            # found a failed read printed as "No customer on this order." under a header naming
            # the customer — infrastructure turned into business fact.
            if not customer_id:
                job.parts["history"] = None
                return
            try:
                job.parts["history"] = await self._history(customer_id, current_order_id=core.get("order_id"))
            except Exception as exc:  # noqa: BLE001 — the order stands without its history
                log.warning("customer history unavailable for %s: %s", job.order_id, type(exc).__name__)
                job.parts["history"] = {"available": False, "reason": "read_failed", "detail": type(exc).__name__, "customer_id": customer_id}

        async def email() -> None:
            try:
                job.parts["email"] = await self._email(customer.get("email"), digits=digits)
            except Exception as exc:  # noqa: BLE001
                log.warning("email correlation unavailable for %s: %s", job.order_id, type(exc).__name__)
                job.parts["email"] = {"available": False, "reason": "unavailable", "threads": []}

        try:
            await asyncio.gather(history(), email())
        finally:
            job.finished = self.clock()

    async def _history(self, customer_id: str | None, *, current_order_id: str | None) -> dict[str, Any] | None:
        if not customer_id:
            return None
        try:
            payload = await self._shopify().graphql(CUSTOMER_ORDERS_QUERY, {"id": customer_id, "n": RECENT_ORDERS})
        except ShopifyError as exc:
            log.warning("customer history read failed: %s", exc)
            return None
        node = (payload.get("data") or {}).get("customer")
        if not isinstance(node, dict):
            return None
        return shape_customer_history(node, current_order_id=current_order_id)

    async def _email(self, customer_email: str | None, *, digits: str) -> dict[str, Any]:
        if self._threads_for is None:
            return {"available": False, "reason": "Gmail is not configured on this backend.", "threads": []}
        terms = [f"CROOKS-{digits}", f"#{digits}"] if digits else []
        found = await self._threads_for(sender=customer_email or "", terms=terms)
        if not found.get("available"):
            return {"available": False, "reason": str(found.get("reason") or "")[:160], "threads": []}
        threads = correlate_threads(list(found.get("threads") or []), customer_email=customer_email, digits=digits)
        return {"available": True, "threads": threads}

    def _merge(self, core: dict[str, Any], job: _Job) -> dict[str, Any]:
        out = dict(core)
        out["history"] = job.parts.get("history")
        out["email"] = job.parts.get("email")
        out["pending"] = job.pending
        # What the order needs, from whatever has landed; recomputed as the rest arrives.
        out["attention"] = attention_for(out, now=self.clock())
        return out

    def _prune(self) -> None:
        now = self.clock()
        for order_id, job in list(self._jobs.items()):
            if now - job.started > JOB_RETENTION_S:
                if job.task is not None and not job.task.done():
                    job.task.cancel()
                del self._jobs[order_id]
        for order_id, (future, started) in list(self._cores.items()):
            if future.done() and now - started > CORE_REUSE_S:
                del self._cores[order_id]


def _short(value: Any, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
