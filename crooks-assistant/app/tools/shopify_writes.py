"""The changes that move money or end an order: cancel (here), and the refund, the address
and the fulfilment that follow. Each one PREPARES from a fresh read — the exact arguments the
mutation will be sent with, the facts the card prints, the fingerprint the engine checks —
and sends nothing. The engine sends the one reviewed mutation later, by name, after the
owner's gesture, waits for Shopify to finish where Shopify finishes later, and proves the
change by reading again. Policy (refund on cancel, restock, notify) is configuration, printed
on the card; it is never an argument the model supplies.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any

from app.actions.models import Observed, Prepared
from app.clients.shopify import (
    MAX_CUSTOM_LINE_PRICE,
    MAX_CUSTOM_TITLE_CHARS,
    ShopifyClient,
    ShopifyError,
)
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool
from app.tools.shopify_tools import _c, append_note, hydrator

log = logging.getLogger("crooks.shopify_writes")

_policy = None


def bind_policy(getter) -> None:
    """Where the write policy comes from: the runtime's settings. Tests bind their own."""
    global _policy
    _policy = getter


def policy():
    if _policy is not None:
        return _policy()
    from config.settings import get_settings

    return get_settings()


def _amount(node: Any) -> float | None:
    try:
        shop = (node or {}).get("shopMoney") or node
        return round(float(shop["amount"]), 2)
    except (TypeError, KeyError, ValueError, AttributeError):
        return None


def _currency(node: Any) -> str:
    try:
        return str(((node or {}).get("shopMoney") or node).get("currencyCode") or "GBP")
    except AttributeError:
        return "GBP"


def _display(amount: float | None, currency: str) -> str:
    if amount is None:
        return "—"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency.upper())
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency}"


def _spoken_money(amount: float | None, currency: str) -> str:
    """The amount as the voice says it: the speakable layer already turns "£60.00" into
    "sixty pounds"; the model is handed the words so it reads them back the same way."""
    if amount is None:
        return "an unknown amount"
    from app.speech.speakable import to_speakable

    return to_speakable(_display(amount, currency))


# ------------------------------------------------------------------------- cancel

CANCEL_REASONS = {
    "customer": "CUSTOMER", "inventory": "INVENTORY", "fraud": "FRAUD", "declined": "DECLINED", "staff": "STAFF", "other": "OTHER",
}
REASON_WORDS = {
    "CUSTOMER": "customer request", "INVENTORY": "out of stock", "FRAUD": "suspected fraud", "DECLINED": "payment declined",
    "STAFF": "staff error", "OTHER": "other",
}
MAX_STAFF_NOTE_CHARS = 200
# The job Shopify runs to cancel is waited for this long, looking a little less often each time.
JOB_WAIT_S = 12.0
JOB_POLL_FIRST_S = 0.3
JOB_POLL_GROWTH = 1.5
JOB_POLL_MAX_S = 2.0

CANCEL_STATE_QUERY = """
query CrooksOrderCancelState($id: ID!) {
  order(id: $id) {
    id
    name
    cancelledAt
    cancelReason
    displayFinancialStatus
    displayFulfillmentStatus
    fullyPaid
    currentTotalPriceSet { shopMoney { amount currencyCode } }
    totalRefundedSet { shopMoney { amount currencyCode } }
    totalOutstandingSet { shopMoney { amount currencyCode } }
    customer { displayName }
    fullRefund: suggestedRefund(suggestFullRefund: true) {
      amountSet { shopMoney { amount currencyCode } }
      maximumRefundableSet { shopMoney { amount currencyCode } }
    }
    lineItems(first: 50) { edges { node { id quantity unfulfilledQuantity refundableQuantity } } }
  }
}
"""


async def _read_cancel_state(client: ShopifyClient, order_id: str) -> dict[str, Any]:
    payload = await client.graphql(CANCEL_STATE_QUERY, {"id": order_id})
    node = (payload.get("data") or {}).get("order")
    if not isinstance(node, dict) or node.get("id") != order_id:
        raise ToolError(f"No order with id {order_id}.")
    return node


def cancel_fingerprint(node: dict[str, Any]) -> dict[str, Any]:
    """What a cancellation turns on and what it must change: cancelled, the statuses, and the
    money refunded so far. Numbers and words; nothing personal."""
    refunded = _amount(node.get("totalRefundedSet"))
    return {
        "cancelled": bool(node.get("cancelledAt")),
        "fulfillment": str(node.get("displayFulfillmentStatus") or ""),
        "financial": str(node.get("displayFinancialStatus") or ""),
        "refunded": f"{refunded:.2f}" if refunded is not None else "",
    }


async def _observe_cancel(execution: dict) -> Observed:
    node = await _read_cancel_state(_c(), str(execution["order_id"]))
    return Observed(fingerprint=cancel_fingerprint(node), entity=None)


async def _entity_after(execution: dict) -> dict:
    return await hydrator().order(str(execution["order_id"]), budget_s=0.0, fresh=True)


async def _execute_cancel(execution: dict) -> dict:
    client = _c()
    order_id = str(execution["order_id"])
    payload = await client.mutate("order_cancel", {
        "orderId": order_id,
        "reason": str(execution["reason"]),
        "refundMethod": {"originalPaymentMethodsRefund": bool(execution["refund"])},
        "restock": bool(execution["restock"]),
        "notifyCustomer": bool(execution["notify"]),
        "staffNote": str(execution.get("staff_note") or ""),
    })
    hydrator().forget(order_id)
    job = ((payload.get("data") or {}).get("orderCancel") or {}).get("job")
    if not isinstance(job, dict) or not job.get("id"):
        # No job and no user error: Shopify did not take it. The engine looks, not guesses.
        raise ShopifyError("Shopify did not start the cancellation.")
    return {"job_id": str(job["id"]), "done": bool(job.get("done"))}


async def _settle_cancel(execution: dict, sent: dict) -> None:
    """Wait for the job Shopify started, bounded, looking a little less often each time. A job
    Shopify has forgotten, or one that is still running at the bound, is left to the proving
    read: the engine says what it sees, never what it hopes."""
    job_id = str((sent or {}).get("job_id") or "")
    if not job_id or (sent or {}).get("done"):
        return
    client = _c()
    deadline = time.monotonic() + JOB_WAIT_S
    wait = JOB_POLL_FIRST_S
    while time.monotonic() < deadline:
        await asyncio.sleep(min(wait, max(0.0, deadline - time.monotonic())))
        try:
            done = await client.job_done(job_id)
        except ShopifyError as exc:
            log.warning("job %s could not be checked: %s", job_id, exc)
            return
        if done is None or done:
            return
        wait = min(wait * JOB_POLL_GROWTH, JOB_POLL_MAX_S)
    log.warning("job %s still running after %.0fs; the re-read decides", job_id, JOB_WAIT_S)


def _verify_cancel(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    if not observed.get("cancelled"):
        return False, ""
    expected = float(execution.get("expected_refund") or 0)
    if execution.get("refund") and expected > 0:
        try:
            landed = float(observed.get("refunded") or 0) - float(before.get("refunded") or 0)
        except ValueError:
            landed = 0.0
        if landed + 0.005 < expected:
            return True, "The refund isn't showing yet; check the order."
    return True, ""


def _present_cancel(proposal) -> dict:
    s = proposal.summary
    currency = str(s.get("currency") or "GBP")
    amount = s.get("refund_amount")
    refund_words = (
        _display(float(amount), currency) + " to the original payment" if s.get("refund") and amount
        else ("nothing captured to refund" if s.get("refund") else "not refunded (policy)")
    )
    facts = [
        {"label": "Customer", "value": str(s.get("customer") or "—")},
        {"label": "Items", "value": f"{s.get('items', 0)} · {_display(float(s['total']), currency) if s.get('total') else '—'}, {str(s.get('financial') or '').lower().replace('_', ' ') or 'unknown'}"},
        {"label": "Refund", "value": refund_words, "tone": "bad" if s.get("refund") and amount else ""},
        {"label": "Restock", "value": f"{s.get('restock_count', 0)} item{'s' if s.get('restock_count', 0) != 1 else ''}" if s.get("restock") else "no"},
        {"label": "Customer emailed", "value": "yes" if s.get("notify") else "no"},
        {"label": "Reason", "value": REASON_WORDS.get(str(s.get("reason")), "other")},
    ]
    target = f"Drop to cancel and refund {_display(float(amount), currency)}" if s.get("refund") and amount else "Drop to cancel"
    return {
        "title": "Cancel order", "summary": "", "detail": "Cancelling cannot be undone.",
        "facts": facts, "target": target, "done_title": "Cancelled",
    }


@tool(
    name="shopify_order_cancel",
    description=(
        "Prepare the cancellation of one order that has not shipped. Whether it refunds, restocks "
        "and emails the customer is fixed policy, shown on the card — not yours to choose."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order_id from a search."},
            "reason": {"type": "string", "maxLength": 12, "description": "One of: customer, inventory, fraud, declined, staff, other. Default customer."},
            "staff_note": {"type": "string", "maxLength": MAX_STAFF_NOTE_CHARS, "description": "Internal note on the cancellation, one sentence."},
        },
        "required": ["order_id"],
    },
    tier=Tier.RED,
    issued_id_args=("order_id",),
    write=WriteSpec(
        operation="order_cancel",
        entity_kind="order",
        entity_arg="order_id",
        mutation="order_cancel",
        observe=_observe_cancel,
        execute=_execute_cancel,
        present=_present_cancel,
        entity=_entity_after,
        settle=_settle_cancel,
        verify=_verify_cancel,
        op_class="money",
        reversible=False,
        spoken_success="Order {label} cancelled.",
        spoken_failure="I couldn't confirm the cancellation. Check the order before asking again.",
        spoken_stale="The order changed since this was prepared. Nothing was sent.",
    ),
)
async def shopify_order_cancel(order_id: str, reason: str = "customer", staff_note: str = "") -> Prepared:
    """Prepare, never send: read the order as it is now, decide every argument, and hand the
    engine the fingerprint it must see again before it sends."""
    code = CANCEL_REASONS.get(str(reason or "customer").strip().lower())
    if code is None:
        raise ToolError("The reason must be one of: customer, inventory, fraud, declined, staff, other.")
    note = " ".join(str(staff_note or "").split())
    if len(note) > MAX_STAFF_NOTE_CHARS or "<" in note:
        raise ToolError("The staff note must be one plain sentence.")
    node = await _read_cancel_state(_c(), str(order_id))
    if node.get("cancelledAt"):
        raise ToolError(f"Order {node.get('name')} is already cancelled.")
    status = str(node.get("displayFulfillmentStatus") or "").upper()
    if status in ("FULFILLED", "PARTIALLY_FULFILLED"):
        raise ToolError(f"Order {node.get('name')} has shipped; it cannot be cancelled from here.")
    if str(node.get("displayFinancialStatus") or "").upper() == "VOIDED":
        raise ToolError(f"Order {node.get('name')} is voided; there is nothing to cancel.")
    settings = policy()
    full = node.get("fullRefund") or {}
    currency = _currency(node.get("currentTotalPriceSet"))
    refundable = _amount(full.get("amountSet")) if full else None
    maximum = _amount(full.get("maximumRefundableSet")) if full else None
    amount = min(x for x in (refundable, maximum) if x is not None) if refundable is not None or maximum is not None else None
    refund = bool(settings.cancel_refund) and (amount or 0) > 0
    restock_count = sum(int((e.get("node") or {}).get("unfulfilledQuantity") or 0) for e in ((node.get("lineItems") or {}).get("edges") or []))
    restock = bool(settings.cancel_restock) and restock_count > 0
    # A customer who asked to cancel expects the email; suspected fraud or a declined card gets none.
    notify = bool(settings.cancel_notify) and code not in ("FRAUD", "DECLINED")
    items = len((node.get("lineItems") or {}).get("edges") or [])
    total = _amount(node.get("currentTotalPriceSet"))
    execution = {
        "order_id": str(order_id), "reason": code, "staff_note": note, "refund": refund, "restock": restock,
        "notify": notify, "expected_refund": f"{amount:.2f}" if refund and amount else "0.00", "currency": currency,
    }
    read_back = "cancel order " + str(node.get("name") or "").rsplit("-", 1)[-1].lstrip("#")
    if refund and amount:
        read_back += f", refunding {_spoken_money(amount, currency)} to the original payment"
    read_back += (", restocking" if restock else ", no restock") + (", emailing the customer" if notify else ", without emailing the customer")
    return Prepared(
        execution=execution,
        before=cancel_fingerprint(node),
        expected_after={"cancelled": True},
        entity_ref=str(order_id),
        entity_label=str(node.get("name") or ""),
        summary={
            "customer": str((node.get("customer") or {}).get("displayName") or ""), "items": items, "total": total,
            "financial": str(node.get("displayFinancialStatus") or ""), "refund": refund, "refund_amount": amount if refund else None,
            "restock": restock, "restock_count": restock_count, "notify": notify, "reason": code, "currency": currency,
            "read_back": read_back,
            "ledger": {"refund": refund, "amount": f"{amount:.2f}" if refund and amount else "0.00", "currency": currency, "restock": restock_count if restock else 0, "notify": notify, "reason": code},
        },
    )


# ------------------------------------------------------------------------- refund
#
# Three shapes a clothing label actually issues, all priced by Shopify itself
# (suggestedRefund) and never by the model: the returned items (with restock), the postage,
# or a goodwill amount. The amount is capped at what the store can still refund; the
# transactions are Shopify's suggested ones, each capped at its own maximum; a gift-card
# tender is refused. Verified by the refunded total moving by exactly the amount.

MAX_REFUND_NOTE_CHARS = 120
RESTOCK_KINDS = {"return": "RETURN", "cancel": "CANCEL", "none": "NO_RESTOCK"}

REFUND_STATE_QUERY = """
query CrooksRefundState($id: ID!) {
  order(id: $id) {
    id
    name
    cancelledAt
    displayFinancialStatus
    refundable
    currentTotalPriceSet { shopMoney { amount currencyCode } }
    totalRefundedSet { shopMoney { amount currencyCode } }
  }
}
"""

SUGGESTED_REFUND_QUERY = """
query CrooksSuggestedRefund($id: ID!, $shippingAmount: Money, $shippingFull: Boolean, $refundLineItems: [RefundLineItemInput!], $full: Boolean) {
  order(id: $id) {
    id
    name
    suggestedRefund(shippingAmount: $shippingAmount, refundShipping: $shippingFull, refundLineItems: $refundLineItems, suggestFullRefund: $full) {
      amountSet { shopMoney { amount currencyCode } }
      subtotalSet { shopMoney { amount currencyCode } }
      totalTaxSet { shopMoney { amount currencyCode } }
      maximumRefundableSet { shopMoney { amount currencyCode } }
      shipping { amountSet { shopMoney { amount currencyCode } } maximumRefundableSet { shopMoney { amount currencyCode } } }
      suggestedTransactions { amountSet { shopMoney { amount currencyCode } } maximumRefundableSet { shopMoney { amount currencyCode } } gateway kind parentTransaction { id } }
      refundLineItems { quantity lineItem { id title } priceSet { shopMoney { amount currencyCode } } }
    }
  }
}
"""

LOCATIONS_QUERY = """
query CrooksLocations { locations(first: 10, includeInactive: false) { edges { node { id name isActive fulfillsOnlineOrders } } } }
"""


async def _read_refund_state(client: ShopifyClient, order_id: str) -> dict[str, Any]:
    payload = await client.graphql(REFUND_STATE_QUERY, {"id": order_id})
    node = (payload.get("data") or {}).get("order")
    if not isinstance(node, dict) or node.get("id") != order_id:
        raise ToolError(f"No order with id {order_id}.")
    return node


def refund_fingerprint(node: dict[str, Any]) -> dict[str, Any]:
    refunded = _amount(node.get("totalRefundedSet"))
    return {"refunded": f"{refunded:.2f}" if refunded is not None else "", "financial": str(node.get("displayFinancialStatus") or "")}


async def _observe_refund(execution: dict) -> Observed:
    node = await _read_refund_state(_c(), str(execution["order_id"]))
    return Observed(fingerprint=refund_fingerprint(node), entity=None)


async def _restock_location(client: ShopifyClient) -> tuple[str, str] | None:
    """The one location stock goes back to. None when there is not exactly one candidate:
    a guess between warehouses is not a restock."""
    payload = await client.graphql(LOCATIONS_QUERY)
    nodes = [e.get("node") or {} for e in ((payload.get("data") or {}).get("locations") or {}).get("edges") or []]
    candidates = [n for n in nodes if n.get("isActive") and n.get("fulfillsOnlineOrders")] or [n for n in nodes if n.get("isActive")]
    if len(candidates) != 1 or not candidates[0].get("id"):
        return None
    return str(candidates[0]["id"]), str(candidates[0].get("name") or "")


def _allocate(amount: float, suggested: list[dict[str, Any]], order_id: str) -> list[dict[str, Any]]:
    """The amount across Shopify's suggested transactions, in order, each capped at what it
    can refund. Not a gift card: money goes back the way it came, and only that way."""
    remaining = round(amount, 2)
    out: list[dict[str, Any]] = []
    for t in suggested:
        if remaining <= 0.004:
            break
        gateway = str(t.get("gateway") or "")
        if not gateway or "gift" in gateway.lower():
            continue
        parent = (t.get("parentTransaction") or {}).get("id")
        cap = _amount(t.get("maximumRefundableSet")) or _amount(t.get("amountSet")) or 0.0
        if not parent or cap <= 0:
            continue
        take = round(min(cap, remaining), 2)
        out.append({"orderId": order_id, "gateway": gateway, "kind": "REFUND", "amount": f"{take:.2f}", "parentId": str(parent)})
        remaining = round(remaining - take, 2)
    if remaining > 0.004:
        raise ToolError("That amount cannot go back the way it was paid; the store can refund less than that to the original payment.")
    return out


async def _entity_after_refund(execution: dict) -> dict:
    return await hydrator().order(str(execution["order_id"]), budget_s=0.0, fresh=True)


async def _execute_refund(execution: dict) -> dict:
    client = _c()
    order_id = str(execution["order_id"])
    payload = await client.mutate("refund_create", {"input": dict(execution["input"])})
    hydrator().forget(order_id)
    refund = ((payload.get("data") or {}).get("refundCreate") or {}).get("refund") or {}
    _forget_customer(str(execution.get("customer_id") or ""))
    if not refund.get("id"):
        raise ShopifyError("Shopify did not confirm the refund.")
    return {"refund_id": str(refund["id"])}


def _forget_customer(customer_id: str) -> None:
    """customers: a refund on their order changes the customer's story (app/customers/history.py)
    — a refund row, CLIVE's change — so whatever is held of it (for Back, a tap, a read asked
    twice) is dropped the moment the refund has been sent, and the next look reads it again."""
    if not customer_id:
        return
    try:
        from app.memory.store import invalidate_for_write

        invalidate_for_write("customer", customer_id)
    except Exception:  # noqa: BLE001 — a refund is sent whether or not a cache can be told
        log.debug("could not drop the customer's held story", exc_info=True)


def _verify_refund(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    try:
        moved = round(float(observed.get("refunded") or 0) - float(before.get("refunded") or 0), 2)
        expected = round(float(execution.get("amount") or 0), 2)
    except ValueError:
        return False, ""
    return abs(moved - expected) < 0.005, ""


def _present_refund(proposal) -> dict:
    s = proposal.summary
    currency = str(s.get("currency") or "GBP")
    amount = float(s.get("amount") or 0)
    facts = [
        {"label": "Customer", "value": str(s.get("customer") or "")},
        {"label": "Amount", "value": f"{_display(amount, currency)} to the original payment", "tone": "bad"},
        {"label": "Of", "value": f"{_display(float(s.get('paid') or 0), currency)} paid · {_display(float(s.get('remaining_after') or 0), currency)} remains refundable after"},
        {"label": "Items", "value": str(s.get("items_words") or "none · goodwill")},
        {"label": "Shipping", "value": str(s.get("shipping_words") or "no")},
        {"label": "Restock", "value": str(s.get("restock_words") or "no")},
        {"label": "Customer emailed", "value": "yes" if s.get("notify") else "no"},
    ]
    if s.get("reason"):
        facts.append({"label": "Reason", "value": str(s.get("reason"))})
    return {
        "title": "Refund", "summary": "", "detail": "A refund cannot be undone.", "facts": facts,
        "target": f"Drop to refund {_display(amount, currency)}", "done_title": "Refunded",
    }


@tool(
    name="shopify_refund_create",
    description=(
        "Prepare a refund on one order, priced by Shopify: a plain amount, the returned items (with "
        "restock), or the postage. Item ids come from shopify_order_detail."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order_id from a search."},
            "amount": {"type": "string", "maxLength": 12, "description": "A plain amount, e.g. \"20.00\"; leave out when refunding items."},
            "items": {
                "type": "array", "maxItems": 12,
                "items": {"type": "object", "properties": {"line_item_id": {"type": "string"}, "quantity": {"type": "integer"}}, "required": ["line_item_id", "quantity"]},
                "description": "Items refunded, by line_item_id, with quantities.",
            },
            "restock": {"type": "string", "maxLength": 8, "description": "For items: return, cancel (never shipped) or none. Default none."},
            "shipping": {"type": "string", "maxLength": 12, "description": "Refund the postage too: \"full\" or an amount like \"3.95\"."},
            "reason": {"type": "string", "maxLength": MAX_REFUND_NOTE_CHARS, "description": "Short reason, kept on the refund."},
        },
        "required": ["order_id"],
    },
    tier=Tier.RED,
    issued_id_args=("order_id",),
    write=WriteSpec(
        operation="refund_create",
        entity_kind="order",
        entity_arg="order_id",
        mutation="refund_create",
        observe=_observe_refund,
        execute=_execute_refund,
        present=_present_refund,
        entity=_entity_after_refund,
        verify=_verify_refund,
        op_class="money",
        reversible=False,
        spoken_success="Refunded {amount} on order {label}.",
        spoken_failure="I couldn't confirm the refund. Check the order before asking again.",
        spoken_stale="The order's payments changed since this was prepared. Nothing was sent.",
    ),
)
async def shopify_refund_create(
    order_id: str, amount: str = "", items: list | None = None, restock: str = "none", shipping: str = "", reason: str = "",
) -> Prepared:
    """Prepare, never send. Shopify prices the refund; the Mac decides every argument."""
    client = _c()
    reason = " ".join(str(reason or "").split())[:MAX_REFUND_NOTE_CHARS]
    if "<" in reason:
        raise ToolError("The reason must be plain text.")
    restock_kind = RESTOCK_KINDS.get(str(restock or "none").strip().lower())
    if restock_kind is None:
        raise ToolError("restock must be return, cancel or none.")
    items = items or []
    if not isinstance(items, list) or len(items) > 12:
        raise ToolError("Give up to twelve items.")
    shipping_word = str(shipping or "").strip().lower()
    plain = _decimal(amount) if str(amount or "").strip() else None
    if str(amount or "").strip() and plain is None:
        raise ToolError("The amount must be a number of pounds, like 20.00.")
    if plain is not None and (items or shipping_word):
        raise ToolError("Give either a plain amount, or items and/or shipping — not both.")
    if plain is None and not items and not shipping_word:
        raise ToolError("Say what to refund: an amount, the items, or the shipping.")

    state = await _read_refund_state(client, str(order_id))
    if str(state.get("displayFinancialStatus") or "").upper() in ("VOIDED", "REFUNDED") or state.get("refundable") is False:
        raise ToolError(f"Order {state.get('name')} has nothing left to refund.")
    currency = _currency(state.get("currentTotalPriceSet"))
    paid = _amount(state.get("currentTotalPriceSet")) or 0.0
    refunded_so_far = _amount(state.get("totalRefundedSet")) or 0.0

    # The items, checked against the order as it is now — not against what the model said.
    order = await hydrator().order(str(order_id), budget_s=0.0, fresh=True)
    by_id = {str(i.get("line_item_id")): i for i in order.get("items") or [] if i.get("line_item_id")}
    refund_lines: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ToolError("Each item needs a line_item_id and a quantity.")
        line_id = str(item.get("line_item_id") or "")
        try:
            quantity = int(item.get("quantity"))
        except (TypeError, ValueError):
            raise ToolError("Each item needs a whole-number quantity.") from None
        known = by_id.get(line_id)
        if known is None:
            raise ToolError(f"{line_id or 'that item'} is not on order {state.get('name')}.")
        limit = known.get("refundable_quantity")
        if quantity < 1 or (isinstance(limit, int) and quantity > limit):
            raise ToolError(f"Only {limit} of {known.get('title')} can be refunded.")
        refund_lines.append({"lineItemId": line_id, "quantity": quantity, "restockType": restock_kind, "title": str(known.get("title") or ""), "variant": str(known.get("variant") or "")})

    location: tuple[str, str] | None = None
    if refund_lines and restock_kind != "NO_RESTOCK":
        location = await _restock_location(client)
        if location is None:
            raise ToolError("Stock cannot be put back: the store has no single location to restock at. Say restock none, or restock in Admin.")

    # Shopify prices it. A plain amount is priced against the full refund and then capped.
    shipping_amount = None
    shipping_full = None
    if shipping_word == "full":
        shipping_full = True
    elif shipping_word:
        shipping_amount = _decimal(shipping_word)
        if shipping_amount is None:
            raise ToolError("The shipping amount must be a number of pounds, like 3.95.")
    variables: dict[str, Any] = {"id": str(order_id), "shippingAmount": None, "shippingFull": None, "refundLineItems": None, "full": None}
    if plain is not None:
        variables["full"] = True
    else:
        variables["refundLineItems"] = [{"lineItemId": line["lineItemId"], "quantity": line["quantity"], "restockType": line["restockType"]} for line in refund_lines] or None
        variables["shippingAmount"] = f"{shipping_amount:.2f}" if shipping_amount is not None else None
        variables["shippingFull"] = shipping_full
    payload = await client.graphql(SUGGESTED_REFUND_QUERY, variables)
    node = (payload.get("data") or {}).get("order") or {}
    suggested = node.get("suggestedRefund") or {}
    maximum = _amount(suggested.get("maximumRefundableSet"))
    priced = _amount(suggested.get("amountSet"))
    if plain is not None:
        total = plain
    else:
        total = priced
    if total is None or total <= 0:
        raise ToolError("There is nothing to refund for that.")
    if maximum is not None and total > maximum + 0.004:
        raise ToolError(f"Only {_display(maximum, currency)} can still be refunded on order {state.get('name')}.")
    transactions = _allocate(total, list(suggested.get("suggestedTransactions") or []), str(order_id))
    shipping_priced = _amount((suggested.get("shipping") or {}).get("amountSet")) if plain is None else None

    settings = policy()
    notify = bool(getattr(settings, "refund_notify", True))
    refund_input: dict[str, Any] = {"orderId": str(order_id), "notify": notify, "currency": currency, "transactions": transactions}
    if reason:
        refund_input["note"] = reason
    if refund_lines:
        refund_input["refundLineItems"] = [
            {"lineItemId": line["lineItemId"], "quantity": line["quantity"], "restockType": line["restockType"], **({"locationId": location[0]} if location else {})}
            for line in refund_lines
        ]
    if shipping_full:
        refund_input["shipping"] = {"fullRefund": True}
    elif shipping_amount is not None:
        refund_input["shipping"] = {"amount": f"{shipping_amount:.2f}"}

    items_words = ", ".join(f"{line['title']}{' ' + line['variant'] if line['variant'] else ''}{' ×' + str(line['quantity']) if line['quantity'] > 1 else ''}" for line in refund_lines) or ("none · goodwill" if plain is not None else "none")
    shipping_words = "in full" if shipping_full else (_display(shipping_amount, currency) if shipping_amount is not None else "no")
    restock_words = f"{'returned to' if restock_kind == 'RETURN' else 'back into'} stock at {location[1]}" if location else "no"
    label = str(node.get("name") or state.get("name") or "")
    digits = label.rsplit("-", 1)[-1].lstrip("#")
    customer = str(order.get("customer_name") or "")
    read_back = f"refund {_spoken_money(total, currency)} to {customer or 'the customer'} on order {digits}"
    if refund_lines:
        read_back += f" for {items_words}"
    if shipping_full or shipping_amount is not None:
        read_back += f", shipping {shipping_words}"
    read_back += (", restocking" if location else "") + (", emailing the customer" if notify else ", without emailing the customer")
    return Prepared(
        execution={"order_id": str(order_id), "input": refund_input, "amount": f"{total:.2f}", "currency": currency,
                   # Whose story the refund changes (`_execute_refund` drops what is held of it).
                   "customer_id": str(order.get("customer_id") or "")},
        before=refund_fingerprint(state),
        expected_after={"refunded": f"{refunded_so_far + total:.2f}"},
        entity_ref=str(order_id),
        entity_label=label,
        summary={
            "customer": customer,
            "amount": f"{total:.2f}", "currency": currency, "paid": f"{paid:.2f}", "remaining_after": f"{max(0.0, (maximum if maximum is not None else paid - refunded_so_far) - total):.2f}",
            "items_words": items_words, "shipping_words": shipping_words, "restock_words": restock_words, "notify": notify, "reason": reason,
            "shipping_priced": f"{shipping_priced:.2f}" if shipping_priced is not None else "", "read_back": read_back,
            "ledger": {"amount": f"{total:.2f}", "currency": currency, "lines": len(refund_lines), "restock": restock_kind if refund_lines else "NO_RESTOCK", "shipping": bool(shipping_full or shipping_amount), "notify": notify, "tenders": len(transactions)},
        },
    )


def _decimal(value: object) -> float | None:
    text = str(value or "").strip().replace("£", "").replace(",", "")
    try:
        amount = round(float(text), 2)
    except ValueError:
        return None
    if amount <= 0 or amount > 9_999_999:
        return None
    return amount


# ------------------------------------------------------------------------ address
#
# The shipping address, changed to what the customer asked for and nothing else. RED
# always: a redirected parcel is the oldest fraud there is, and a DKIM pass proves the
# mailbox sent the mail, not that the account holder did — provenance is printed on the
# card, never a reason to soften the gesture. The evidence is one message, read here on
# the Mac: its sender must be the order's customer, and the postcode and street the model
# gives must appear in its text. The changed fields are merged into the address as it is
# now, every field is diffed, a reprint note goes on the order in the same write, and the
# change is proven by re-reading the address. There is no undo card: "change it back" is
# a fresh instruction with a fresh diff.

ADDRESS_STATE_QUERY = """
query CrooksAddressState($id: ID!) {
  order(id: $id) {
    id
    name
    note
    email
    cancelledAt
    displayFulfillmentStatus
    customer { displayName defaultEmailAddress { emailAddress } }
    shippingAddress { firstName lastName company address1 address2 city province provinceCode zip country countryCodeV2 phone }
    fulfillments(first: 5) { id status }
  }
}
"""

# Where the open fulfilment orders will ship. Needs a fulfilment-order scope the store may
# not have granted; read best-effort and printed after the change, never a reason to stop it.
DESTINATION_QUERY = """
query CrooksFulfillmentDestination($id: ID!) {
  order(id: $id) {
    id
    fulfillmentOrders(first: 5) {
      edges { node { id status destination { address1 address2 city zip countryCode } } }
    }
  }
}
"""

REPRINT_NOTE = "ADDRESS CHANGED — reprint label"
# How long the address change waits for the order's email reading, to notice an uncited email about the address.
ADDRESS_EMAIL_BUDGET_S = 1.0
MAX_ADDRESS_CHARS = 100
# Shopify's MailingAddressInput, in its own names. The read side answers with countryCodeV2.
_ADDRESS_INPUT_KEYS = ("firstName", "lastName", "company", "address1", "address2", "city", "provinceCode", "zip", "countryCode", "phone")
# The fields that say where a parcel goes, as a fulfilment-order destination has them.
_PLACE_KEYS = ("address1", "address2", "city", "zip", "countryCode")
_CHANGE_WORDS = {
    "address1": "street", "address2": "second line", "city": "town", "zip": "postcode", "countryCode": "country",
    "provinceCode": "region", "firstName": "name", "lastName": "name", "company": "company", "phone": "phone",
}
_OPEN_FULFILLMENT_ORDERS = frozenset({"OPEN", "IN_PROGRESS", "SCHEDULED", "ON_HOLD"})
_COUNTRY_CODE = re.compile(r"^[A-Za-z]{2}$")
_PROVINCE_CODE = re.compile(r"^[A-Za-z0-9]{1,5}$")
_PHONE = re.compile(r"^\+?[0-9 ()\-]{6,20}$")
_WORD = re.compile(r"[a-z0-9]+")

_evidence_reader = None        # async (message_id) -> the message; the Gmail read, injectable
_destination_reads = True      # False once the store has said the fulfilment-order scope is missing


def bind_evidence(reader) -> None:
    """The read that turns a message id into the message. Tests hand in a fake inbox."""
    global _evidence_reader
    _evidence_reader = reader


async def _evidence(message_id: str) -> dict[str, Any]:
    reader = _evidence_reader
    if reader is None:
        from app.tools.gmail_tools import message_evidence

        reader = message_evidence
    return await reader(message_id)


def _clean_field(value: object, limit: int = MAX_ADDRESS_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit or "<" in text or any(ord(ch) < 32 for ch in text):
        raise ToolError("Address fields must be plain text, each under a hundred characters.")
    return text


def address_input(address: dict[str, Any] | None) -> dict[str, str]:
    """A MailingAddressInput from an address as Shopify answers with it: the same ten fields,
    whitespace collapsed, empty ones left out."""
    address = address if isinstance(address, dict) else {}
    out: dict[str, str] = {}
    for key in _ADDRESS_INPUT_KEYS:
        value = address.get("countryCodeV2") if key == "countryCode" and address.get("countryCodeV2") else address.get(key)
        text = " ".join(str(value or "").split())
        if text:
            out[key] = text
    return out


def _canon(value: object, key: str) -> str:
    text = " ".join(str(value or "").split()).casefold()
    if key == "zip":
        return text.replace(" ", "")
    if key == "phone":
        return re.sub(r"\D", "", text)
    return text


def address_hash(address: dict[str, Any]) -> str:
    """Sixteen hex characters standing for an address, case and spacing aside: what the
    fingerprint and the ledger carry instead of the street."""
    canon = {k: _canon(address.get(k), k) for k in _ADDRESS_INPUT_KEYS}
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def place_hash(address: dict[str, Any]) -> str:
    """The same, for the five fields a fulfilment-order destination has."""
    canon = {k: _canon(address.get(k), k) for k in _PLACE_KEYS}
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _note_hash(note: object) -> str:
    text = (note if isinstance(note, str) else "").replace("\r\n", "\n").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def address_line(address: dict[str, Any]) -> str:
    """One line for the card: the street lines, the town, the postcode, the country when
    it is not the store's own."""
    parts = [address.get("address1"), address.get("address2"), address.get("city"), address.get("zip")]
    line = ", ".join(p for p in (str(x or "").strip() for x in parts) if p)
    country = str(address.get("countryCode") or "").upper()
    return f"{line}, {country}" if country and country != "GB" else line


async def _read_address_state(client: ShopifyClient, order_id: str) -> dict[str, Any]:
    payload = await client.graphql(ADDRESS_STATE_QUERY, {"id": order_id})
    node = (payload.get("data") or {}).get("order")
    if not isinstance(node, dict) or node.get("id") != order_id:
        raise ToolError(f"No order with id {order_id}.")
    return node


async def _read_destination(client: ShopifyClient, order_id: str) -> str:
    """The place hashes of the open fulfilment orders, joined; "none" when there are none;
    "unknown" when the store would not say."""
    global _destination_reads
    if not _destination_reads:
        return "unknown"
    try:
        payload = await client.graphql(DESTINATION_QUERY, {"id": order_id})
    except Exception as exc:  # noqa: BLE001 — a courtesy read; the address itself is the proof
        text = str(exc)
        if "ACCESS_DENIED" in text.upper() or "access denied" in text.lower():
            _destination_reads = False
        log.info("fulfilment destination not readable for %s: %s", order_id, text[:120])
        return "unknown"
    order = (payload.get("data") or {}).get("order") or {}
    if order.get("fulfillmentOrders") is None:
        # A read the store's scopes do not cover comes back as a null field, not an error.
        _destination_reads = False
        return "unknown"
    edges = (order.get("fulfillmentOrders") or {}).get("edges") or []
    places = []
    for edge in edges:
        node = edge.get("node") or {}
        destination = node.get("destination")
        if str(node.get("status") or "").upper() in _OPEN_FULFILLMENT_ORDERS and isinstance(destination, dict):
            places.append(place_hash(destination))
    return "|".join(sorted(set(places))) or "none"


def address_fingerprint(node: dict[str, Any], destination: str) -> dict[str, Any]:
    return {
        "address": address_hash(address_input(node.get("shippingAddress"))),
        "note": _note_hash(node.get("note")),
        "fulfillment": str(node.get("displayFulfillmentStatus") or ""),
        "cancelled": bool(node.get("cancelledAt")),
        "destination": destination,
    }


async def _observe_address(execution: dict) -> Observed:
    client = _c()
    order_id = str(execution["order_id"])
    node, destination = await asyncio.gather(_read_address_state(client, order_id), _read_destination(client, order_id))
    return Observed(fingerprint=address_fingerprint(node, destination), entity=None)


async def _execute_address(execution: dict) -> dict:
    client = _c()
    order_id = str(execution["order_id"])
    payload = await client.mutate(
        "order_shipping_address_set", {"id": order_id, "address": dict(execution["address"]), "note": str(execution["note"])},
    )
    hydrator().forget(order_id)
    order = ((payload.get("data") or {}).get("orderUpdate") or {}).get("order") or {}
    if order.get("id") != order_id:
        raise ShopifyError("Shopify did not confirm which order it updated.")
    return {"order_id": order_id}


def _verify_address(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """The address on the order is the staged one: proven. The note and the fulfilment
    destination are courtesies, said out loud when they did not follow."""
    if observed.get("address") != execution.get("address_hash"):
        return False, ""
    notes = []
    if observed.get("note") != execution.get("note_hash"):
        notes.append("The reprint note didn't stick; add it by hand.")
    destination = str(observed.get("destination") or "")
    if destination not in ("", "none", "unknown") and any(part != execution.get("place_hash") for part in destination.split("|")):
        notes.append("The fulfilment destination still shows the old address; check it before printing the label.")
    return True, " ".join(notes)


def _present_address(proposal) -> dict:
    s = proposal.summary
    facts = [
        {"label": "Customer", "value": str(s.get("customer") or "")},
        {"label": "From", "value": str(s.get("from_line") or "")},
        {"label": "To", "value": str(s.get("to_line") or ""), "tone": "warn"},
        {"label": "Changes", "value": ", ".join(str(c) for c in s.get("changes") or [])},
        {"label": "Cited", "value": str(s.get("cited") or ""), "tone": str(s.get("cited_tone") or ("" if s.get("evidence") else "warn"))},
        {"label": "Note", "value": REPRINT_NOTE},
    ]
    return {
        "title": "Change the address", "summary": "",
        "detail": "Not shipped yet. If a label is already printed, reprint it.",
        "facts": facts, "done_title": "Address changed",
    }


def _when(date_header: str) -> str:
    try:
        return parsedate_to_datetime(date_header).strftime("%-d %b %H:%M")
    except (TypeError, ValueError, IndexError):
        return str(date_header or "")[:16]


_UNIT_WORDS = frozenset({"flat", "apartment", "apt", "unit", "floor", "fl", "suite", "room", "house", "building", "block", "level", "the"})
_SUFFIXES = {
    "street": "st", "road": "rd", "avenue": "ave", "lane": "ln", "row": "rw", "close": "cl", "drive": "dr", "place": "pl", "square": "sq",
    "court": "ct", "terrace": "ter", "gardens": "gdns", "crescent": "cres", "grove": "gr", "way": "way", "hill": "hill", "park": "park",
    "walk": "walk", "mews": "mews", "yard": "yd", "estate": "est",
}
_SUFFIX_WORDS = frozenset(_SUFFIXES) | frozenset(_SUFFIXES.values())


def _street_parts(line: object) -> tuple[str, list[str]]:
    """A street line as its number and its name: "Flat 3, 12 Baker Street" → ("3"? no: the
    first token with a digit that is not a unit's, and the words that are neither unit
    words nor street suffixes — "baker"). The suffix is never required: "St" and "Street"
    are the same street."""
    tokens = _WORD.findall(str(line or "").casefold())
    number = ""
    for i, t in enumerate(tokens):
        if any(ch.isdigit() for ch in t) and not (i > 0 and tokens[i - 1] in _UNIT_WORDS):
            number = t
            break
    if not number:
        number = next((t for t in tokens if any(ch.isdigit() for ch in t)), "")
    name = [t for t in tokens if t != number and t not in _UNIT_WORDS and t not in _SUFFIX_WORDS and not t.isdigit() and len(t) >= 3]
    return number, name


def _list_words(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1] if words else ""


def _in_text(token: str, text: str) -> bool:
    return bool(token) and re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


def _mentions(body: str, new: dict[str, str], changed: set[str]) -> tuple[list[str], list[str], list[str]]:
    """Which of the changed parts the message's own text contains (found), which it does not
    (missing), and which cannot be checked against text at all (unchecked). The postcode
    with its spaces removed; a street by its number and every word of its name, never its
    suffix, so "12 Baker St" in the mail matches "12 Baker Street" on the card and "12 Oak
    Street" does not; the second line, the town, the name, the phone and the company each
    by what they contain."""
    text = " ".join(str(body or "").split()).casefold()
    squashed = text.replace(" ", "")
    digits_only = re.sub(r"\D", "", text)
    found: list[str] = []
    missing: list[str] = []
    unchecked: list[str] = []

    def judge(word: str, ok: bool) -> None:
        (found if ok else missing).append(word)

    if "zip" in changed:
        code = _canon(new.get("zip"), "zip")
        judge("postcode", bool(code) and code in squashed)
    if "address1" in changed:
        number, name = _street_parts(new.get("address1"))
        if not number and not name:
            unchecked.append("street")
        else:
            judge("street", (not number or _in_text(number, text)) and bool(name or number) and all(_in_text(t, text) or t in squashed for t in name))
    if "address2" in changed and new.get("address2"):
        number, name = _street_parts(new.get("address2"))
        if not number and not name:
            unchecked.append("second line")
        else:
            judge("second line", (not number or _in_text(number, text)) and all(_in_text(t, text) for t in name))
    if "city" in changed:
        city = _canon(new.get("city"), "city")
        judge("town", bool(city) and city in text)
    if {"firstName", "lastName"} & changed:
        words = [t for t in _WORD.findall(f"{new.get('firstName', '')} {new.get('lastName', '')}".casefold()) if len(t) >= 2]
        judge("name", bool(words) and all(_in_text(t, text) for t in words))
    if "phone" in changed:
        digits = re.sub(r"\D", "", str(new.get("phone") or ""))
        judge("phone", len(digits) >= 6 and digits[-6:] in digits_only)
    if "company" in changed and new.get("company"):
        words = [t for t in _WORD.findall(str(new.get("company")).casefold()) if len(t) >= 3]
        judge("company", bool(words) and any(_in_text(t, text) for t in words))
    for key, word in (("countryCode", "country"), ("provinceCode", "region")):
        if key in changed:
            unchecked.append(word)
    return found, missing, unchecked


async def _address_threads(order_id: str) -> list[dict[str, Any]]:
    """The emails about this order that mention an address, from the order's own reading."""
    from app.context.attention import _ADDRESS

    try:
        order = await hydrator().order(order_id, budget_s=ADDRESS_EMAIL_BUDGET_S)
    except Exception:  # noqa: BLE001 — the check is a courtesy; the refusal below never depends on a failed read
        return []
    email = order.get("email") if isinstance(order.get("email"), dict) else {}
    return [t for t in (email.get("threads") or []) if isinstance(t, dict) and _ADDRESS.search(f"{t.get('subject') or ''} {t.get('snippet') or ''}")]


@tool(
    name="shopify_order_shipping_address_set",
    description=(
        "Prepare a change to an order's shipping address before it ships: give only the parts that "
        "change; they are merged into the current address and the difference printed. If the "
        "address came from an email, pass its message_id: CLIVE reads that message and refuses "
        "unless the postcode and street are in it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order_id from a search."},
            "evidence_message_id": {"type": "string", "maxLength": 40, "description": "message_id of the email giving the address."},
            "address1": {"type": "string", "maxLength": MAX_ADDRESS_CHARS, "description": "Number and street."},
            "address2": {"type": "string", "maxLength": MAX_ADDRESS_CHARS},
            "city": {"type": "string", "maxLength": MAX_ADDRESS_CHARS, "description": "Town."},
            "postcode": {"type": "string", "maxLength": 12},
            "country_code": {"type": "string", "maxLength": 2, "description": "Two letters."},
            "province_code": {"type": "string", "maxLength": 5, "description": "Region code, where needed."},
            "name": {"type": "string", "maxLength": 80, "description": "Recipient."},
            "company": {"type": "string", "maxLength": MAX_ADDRESS_CHARS},
            "phone": {"type": "string", "maxLength": 20},
            "from_owner": {"type": "boolean", "description": "True when the owner gave the address, not an email."},
        },
        "required": ["order_id"],
    },
    tier=Tier.RED,
    issued_id_args=("order_id", "evidence_message_id"),
    write=WriteSpec(
        operation="order_shipping_address_set",
        precondition_keys=("address", "note", "fulfillment", "cancelled"),
        entity_kind="order",
        entity_arg="order_id",
        mutation="order_shipping_address_set",
        observe=_observe_address,
        execute=_execute_address,
        present=_present_address,
        entity=_entity_after,
        verify=_verify_address,
        op_class="irreversible",
        reversible=False,
        spoken_success="Changed the address on order {label}. Reprint the label if one is printed.",
        spoken_failure="I couldn't confirm the address change. Check the order before asking again.",
        spoken_stale="The order changed since this was prepared. Nothing was sent.",
    ),
)
async def shopify_order_shipping_address_set(
    order_id: str, evidence_message_id: str = "", address1: str = "", address2: str = "", city: str = "", postcode: str = "",
    country_code: str = "", province_code: str = "", name: str = "", company: str = "", phone: str = "", from_owner: bool = False,
) -> Prepared:
    """Prepare, never send: the address as it is now, the parts that change merged in, the
    evidence read and checked, the diff printed, and the fingerprint the engine must see
    again before it sends."""
    client = _c()
    given = {k: _clean_field(v) for k, v in {
        "address1": address1, "address2": address2, "city": city, "zip": postcode, "countryCode": country_code,
        "provinceCode": province_code, "name": name, "company": company, "phone": phone,
    }.items()}
    given["zip"] = given["zip"].upper()
    if len(given["zip"]) > 12:
        raise ToolError("That postcode is too long.")
    if given["countryCode"] and not _COUNTRY_CODE.match(given["countryCode"]):
        raise ToolError("country_code must be two letters, like GB.")
    if given["provinceCode"] and not _PROVINCE_CODE.match(given["provinceCode"]):
        raise ToolError("province_code must be a short code, like ENG or CA.")
    if given["phone"] and not _PHONE.match(given["phone"]):
        raise ToolError("The phone number must be digits, with an optional leading +.")

    node = await _read_address_state(client, str(order_id))
    label = str(node.get("name") or "")
    if node.get("cancelledAt"):
        raise ToolError(f"Order {label} is cancelled; its address does not matter now.")
    status = str(node.get("displayFulfillmentStatus") or "").upper()
    shipped = status in ("FULFILLED", "PARTIALLY_FULFILLED") or any(
        str(f.get("status") or "").upper() == "SUCCESS" for f in node.get("fulfillments") or [] if isinstance(f, dict)
    )
    if shipped:
        raise ToolError(f"Order {label} has shipped; the address cannot be changed from here. Contact the carrier.")
    current = address_input(node.get("shippingAddress"))
    if not current.get("address1"):
        raise ToolError(f"Order {label} has no shipping address to change.")

    # The merge: a new street brings its own second line (an old flat number on a new street
    # is a wrong address); a new country drops a region code that belonged to the old one.
    new = dict(current)
    if given["address1"]:
        new["address1"] = given["address1"]
        new.pop("address2", None)
        if given["address2"]:
            new["address2"] = given["address2"]
    elif given["address2"]:
        new["address2"] = given["address2"]
    if given["city"]:
        new["city"] = given["city"]
    if given["zip"]:
        new["zip"] = given["zip"]
    if given["countryCode"] and given["countryCode"].upper() != current.get("countryCode"):
        new["countryCode"] = given["countryCode"].upper()
        new.pop("provinceCode", None)
    if given["provinceCode"]:
        new["provinceCode"] = given["provinceCode"].upper()
    if given["name"]:
        first, _, last = given["name"].partition(" ")
        new["firstName"] = first
        new.pop("lastName", None)
        if last:
            new["lastName"] = last
    if given["company"]:
        new["company"] = given["company"]
    if given["phone"]:
        new["phone"] = given["phone"]
    if not new.get("countryCode"):
        raise ToolError(f"Order {label}'s address has no country; set it in Admin first.")

    changed = {k for k in _ADDRESS_INPUT_KEYS if _canon(new.get(k), k) != _canon(current.get(k), k)}
    if not changed:
        raise ToolError(f"That is the address already on order {label}; nothing to change.")
    changes = []
    for key in _ADDRESS_INPUT_KEYS:
        if key in changed:
            word = _CHANGE_WORDS[key] + (" cleared" if not new.get(key) else "")
            if word not in changes:
                changes.append(word)

    # The evidence: read here, never trusted from the model's summary of it.
    customer_email = str(node.get("email") or ((node.get("customer") or {}).get("defaultEmailAddress") or {}).get("emailAddress") or "").strip().lower()
    evidence = None
    cited_tone = ""
    message_id = str(evidence_message_id or "").strip()
    if message_id:
        evidence = await _evidence(message_id)
        sender = str(evidence.get("from_email") or "").strip().lower()
        if not customer_email or sender != customer_email:
            raise ToolError(
                f"That email is from {sender or 'an unknown sender'}, not the customer on order {label}. "
                "The address was not changed; do it in Admin if you are sure."
            )
        body = str(evidence.get("body") or "")
        found, missing, unchecked = _mentions(body, new, changed)
        if missing:
            raise ToolError(
                f"The email does not contain the new {' or '.join(missing)}. Read it again, or change the address in Admin."
            )
        if not found:
            raise ToolError(
                f"Nothing in that email can be checked against this change ({', '.join(unchecked) or 'nothing checkable changed'}). "
                "Change it in Admin, or say the owner gave the address."
            )
        if "address1" in changed and "zip" not in changed:
            # A new street keeps the old postcode only if the email says so: a street
            # without its postcode is a parcel to the wrong town.
            squashed = " ".join(body.split()).casefold().replace(" ", "")
            if not _canon(current.get("zip"), "zip") or _canon(current.get("zip"), "zip") not in squashed:
                raise ToolError("A new street needs its postcode: the email does not repeat the order's. Say the postcode, or read it from the email.")
        cited = (
            f"Email from {sender}, {_when(str(evidence.get('date') or ''))} · "
            f"{'verified sender' if evidence.get('authenticated') else 'sender not verified'}"
            f" · {_list_words(found)} found in the message" + (f" · not checked: {_list_words(unchecked)}" if unchecked else "")
        )
        cited_tone = "" if evidence.get("authenticated") else "warn"
    else:
        about = await _address_threads(str(order_id))
        if about and not from_owner:
            t = about[0]
            raise ToolError(
                f"An email about this order's address is in the inbox (from {t.get('from_email') or 'an unknown sender'}, "
                f"{_when(str(t.get('date') or ''))}). Cite its message_id so CLIVE can check it, or say from_owner if the owner gave the address."
            )
        cited = "none — given by the owner"
        cited_tone = "warn"
        if about:
            t = about[0]
            cited += f"; an email about the address from {t.get('from_email') or 'an unknown sender'} was NOT checked"
            cited_tone = "bad"

    note = append_note(str(node.get("note") or ""), REPRINT_NOTE) if REPRINT_NOTE not in str(node.get("note") or "") else str(node.get("note") or "")
    destination = await _read_destination(client, str(order_id))
    from_line = address_line(current)
    to_line = address_line(new)
    digits = label.rsplit("-", 1)[-1].lstrip("#")
    read_back = f"change the address on order {digits} to {to_line}"
    execution = {
        "order_id": str(order_id), "address": new, "note": note,
        "address_hash": address_hash(new), "place_hash": place_hash(new), "note_hash": _note_hash(note),
    }
    pii = [v for v in (current.get("address1"), current.get("address2"), current.get("zip"), new.get("address1"), new.get("address2"), new.get("zip"),
                       new.get("phone"), given["name"]) if v]
    return Prepared(
        execution=execution,
        before=address_fingerprint(node, destination),
        expected_after={"address": execution["address_hash"]},
        entity_ref=str(order_id),
        entity_label=label,
        summary={
            "customer": str((node.get("customer") or {}).get("displayName") or ""),
            "from_line": from_line, "to_line": to_line, "changes": changes, "cited": cited, "cited_tone": cited_tone,
            "evidence": bool(evidence), "verified_sender": bool(evidence and evidence.get("authenticated")),
            "read_back": read_back, "pii": pii,
            "ledger": {
                "line1": "address1" in changed, "post": "zip" in changed, "town": "city" in changed, "country": new.get("countryCode", ""),
                "evidence": bool(evidence), "verified_sender": bool(evidence and evidence.get("authenticated")),
                "destination_known": destination != "unknown",
            },
        },
    )


# ---------------------------------------------------------------------- fulfilment
#
# Marking an order shipped: the Mac reads the order's own fulfilment orders and their
# remaining lines, fulfils exactly those (or the items named, no more than remain), names
# the carrier as Shopify names it so the number becomes a link, and says on the card whether
# the customer hears. Not idempotent — never sent twice — and proven by the remaining
# quantities dropping to exactly what was expected. RED with a hold: a shipping email is
# irrevocable, and the labels in Click & Drop are a second system nobody here can see.

FULFILLMENT_ORDERS_QUERY = """
query CrooksFulfillmentOrders($id: ID!) {
  order(id: $id) {
    id
    name
    cancelledAt
    displayFulfillmentStatus
    displayFinancialStatus
    customer { displayName }
    fulfillmentOrders(first: 10) {
      edges { node {
        id
        status
        requestStatus
        assignedLocation { name location { id } }
        lineItems(first: 50) {
          edges { node { id remainingQuantity totalQuantity lineItem { id title variantTitle } } }
        }
      } }
    }
  }
}
"""

# Carriers a London label ships with, spelled exactly as Shopify's supported-tracking-company
# list spells them (capitalisation matters to Shopify): a name from here gets a tracking link
# built by Shopify; any other name would be stored as dead text.
CARRIERS = (
    "Royal Mail", "Parcelforce", "Evri", "DPD UK", "DPD Local", "DPD", "Yodel", "DHL Parcel", "DHL Express",
    "UPS", "FedEx", "TNT", "Amazon Logistics UK", "An Post", "Whistl", "Tuffnells", "APC", "DX", "GLS",
)
_CARRIER_BY_KEY = {re.sub(r"[^a-z0-9]", "", c.casefold()): c for c in CARRIERS}
_ROYAL_MAIL_S10 = re.compile(r"^[A-Z]{2}\d{9}GB$")
_TRACKING_NUMBER = re.compile(r"^[A-Za-z0-9\-]{8,34}$")
_FULFILLABLE = frozenset({"OPEN", "IN_PROGRESS"})
_PAID_FOR_SHIPPING = frozenset({"PAID", "PARTIALLY_REFUNDED"})


async def _read_fulfillment_state(client: ShopifyClient, order_id: str) -> dict[str, Any]:
    payload = await client.graphql(FULFILLMENT_ORDERS_QUERY, {"id": order_id})
    node = (payload.get("data") or {}).get("order")
    if not isinstance(node, dict) or node.get("id") != order_id:
        raise ToolError(f"No order with id {order_id}.")
    return node


def _fulfillment_orders(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Every fulfilment order on the order, each with its lines and what remains of them."""
    out = []
    for edge in ((node.get("fulfillmentOrders") or {}).get("edges") or []):
        fo = edge.get("node") or {}
        if not fo.get("id"):
            continue
        location = fo.get("assignedLocation") or {}
        lines = []
        for line_edge in ((fo.get("lineItems") or {}).get("edges") or []):
            line = line_edge.get("node") or {}
            item = line.get("lineItem") or {}
            if line.get("id"):
                lines.append({
                    "id": str(line["id"]), "line_item_id": str(item.get("id") or ""), "remaining": int(line.get("remainingQuantity") or 0),
                    "total": int(line.get("totalQuantity") or 0), "title": str(item.get("title") or ""), "variant": str(item.get("variantTitle") or ""),
                })
        out.append({
            "id": str(fo["id"]), "status": str(fo.get("status") or "").upper(), "request": str(fo.get("requestStatus") or "").upper(),
            "location_id": str((location.get("location") or {}).get("id") or ""), "location": str(location.get("name") or ""), "lines": lines,
        })
    return out


def _remaining_hash(remaining: dict[str, int]) -> str:
    """Sixteen hex characters for "which fulfilment-order lines have how many left": the
    state a fulfilment changes, and the state that proves it."""
    return hashlib.sha256(json.dumps(sorted(remaining.items())).encode("utf-8")).hexdigest()[:16]


def fulfil_fingerprint(node: dict[str, Any]) -> dict[str, Any]:
    orders = _fulfillment_orders(node)
    remaining = {line["id"]: line["remaining"] for fo in orders for line in fo["lines"]}
    return {
        "fulfillment": str(node.get("displayFulfillmentStatus") or ""), "cancelled": bool(node.get("cancelledAt")),
        "remaining": _remaining_hash(remaining), "lines": len(remaining),
    }


async def _observe_fulfil(execution: dict) -> Observed:
    node = await _read_fulfillment_state(_c(), str(execution["order_id"]))
    return Observed(fingerprint=fulfil_fingerprint(node), entity=None)


async def _execute_fulfil(execution: dict) -> dict:
    client = _c()
    order_id = str(execution["order_id"])
    payload = await client.mutate("fulfillment_create", {"fulfillment": dict(execution["input"])})
    hydrator().forget(order_id)
    fulfillment = ((payload.get("data") or {}).get("fulfillmentCreate") or {}).get("fulfillment") or {}
    if not fulfillment.get("id"):
        raise ShopifyError("Shopify did not confirm the fulfilment.")
    return {"fulfillment_id": str(fulfillment["id"]), "status": str(fulfillment.get("status") or "")}


def _verify_fulfil(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """What remained to ship dropped by exactly what was sent: proven from the state, not
    from the answer. A shipment that then reads oddly in Shopify is said out loud."""
    if observed.get("remaining") != execution.get("expected_remaining"):
        return False, ""
    status = str(observed.get("fulfillment") or "").upper()
    if execution.get("complete") and status != "FULFILLED":
        return True, "Shopify still shows the order as not fully shipped; check it."
    return True, ""


def _present_fulfil(proposal) -> dict:
    s = proposal.summary
    tracking = str(s.get("tracking") or "")
    facts = [
        {"label": "Customer", "value": str(s.get("customer") or "")},
        {"label": "Items", "value": str(s.get("items_words") or "")},
        {"label": "From", "value": str(s.get("location") or "")},
        {"label": "Carrier", "value": str(s.get("carrier") or "")},
        {"label": "Tracking", "value": (tracking + (f" · {s['tracking_warning']}" if s.get("tracking_warning") else "")) if tracking else "none", "tone": "warn" if (s.get("tracking_warning") or not tracking) else ""},
        {"label": "Customer emailed", "value": "yes — with the tracking link" if s.get("notify") and tracking else ("yes" if s.get("notify") else "no")},
    ]
    return {
        "title": "Mark as shipped", "summary": "",
        "detail": "Marks every item shipped." if s.get("complete") else "Marks these items shipped; the rest stay open.",
        "facts": facts, "done_title": "Shipped",
    }


@tool(
    name="shopify_order_fulfil",
    description=(
        "Prepare to mark an order shipped: everything still to ship, or only the items named (by "
        "line_item_id), with the carrier and tracking number. Store policy decides whether the "
        "customer is emailed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order_id from a search."},
            "tracking_number": {"type": "string", "maxLength": 40, "description": "The tracking number, if any."},
            "carrier": {"type": "string", "maxLength": 40, "description": "Royal Mail, Evri, DPD…; default the store's usual."},
            "items": {
                "type": "array", "maxItems": 12,
                "items": {"type": "object", "properties": {"line_item_id": {"type": "string"}, "quantity": {"type": "integer"}}, "required": ["line_item_id", "quantity"]},
                "description": "Only these items; leave out to ship everything still open.",
            },
        },
        "required": ["order_id"],
    },
    tier=Tier.RED,
    issued_id_args=("order_id",),
    write=WriteSpec(
        operation="fulfillment_create",
        entity_kind="order",
        entity_arg="order_id",
        mutation="fulfillment_create",
        observe=_observe_fulfil,
        execute=_execute_fulfil,
        present=_present_fulfil,
        entity=_entity_after,
        verify=_verify_fulfil,
        op_class="irreversible",
        reversible=False,
        spoken_success="Order {label} marked as shipped.",
        spoken_failure="I couldn't confirm the fulfilment. Check the order before asking again.",
        spoken_stale="The order's items changed since this was prepared. Nothing was sent.",
    ),
)
async def shopify_order_fulfil(order_id: str, tracking_number: str = "", carrier: str = "", items: list | None = None) -> Prepared:
    """Prepare, never send: the fulfilment orders as they are now, the lines to ship decided
    here, the carrier named as Shopify names it, and the fingerprint the engine must see
    again before it sends."""
    settings = policy()
    carrier_key = re.sub(r"[^a-z0-9]", "", str(carrier or getattr(settings, "carrier", "Royal Mail") or "").casefold())
    carrier_name = _CARRIER_BY_KEY.get(carrier_key)
    if carrier_name is None:
        raise ToolError("The carrier must be one Shopify knows: " + ", ".join(CARRIERS[:8]) + ", …")
    tracking = re.sub(r"\s+", "", str(tracking_number or "")).upper()
    if tracking and not _TRACKING_NUMBER.match(tracking):
        raise ToolError("The tracking number must be letters, digits and dashes, 8 to 34 characters.")
    tracking_warning = ""
    if tracking and carrier_name == "Royal Mail" and not _ROYAL_MAIL_S10.match(tracking):
        tracking_warning = "not the usual Royal Mail form (two letters, nine digits, GB)"
    items = items or []
    if not isinstance(items, list) or len(items) > 12:
        raise ToolError("Give up to twelve items.")

    node = await _read_fulfillment_state(_c(), str(order_id))
    label = str(node.get("name") or "")
    if node.get("cancelledAt"):
        raise ToolError(f"Order {label} is cancelled; it cannot be shipped.")
    financial = str(node.get("displayFinancialStatus") or "").upper()
    if financial == "PARTIALLY_PAID":
        raise ToolError(f"Order {label} is partly paid; take the balance first.")
    if financial not in _PAID_FOR_SHIPPING:
        raise ToolError(f"Order {label} is {financial.lower().replace('_', ' ') or 'not paid'}; it should not ship yet.")
    open_orders = [fo for fo in _fulfillment_orders(node) if fo["status"] in _FULFILLABLE and any(line["remaining"] > 0 for line in fo["lines"])]
    if not open_orders:
        raise ToolError(f"Order {label} has nothing left to ship.")
    locations = {fo["location_id"] for fo in open_orders}
    if len(locations) > 1:
        raise ToolError(f"Order {label} is split across locations; fulfil it in Admin.")

    # Which lines, how many: everything that remains, or exactly the items named.
    by_line_item = {line["line_item_id"]: (fo, line) for fo in open_orders for line in fo["lines"] if line["remaining"] > 0}
    chosen: dict[str, tuple[dict, dict, int]] = {}
    if items:
        for item in items:
            if not isinstance(item, dict):
                raise ToolError("Each item needs a line_item_id and a quantity.")
            line_id = str(item.get("line_item_id") or "")
            try:
                quantity = int(item.get("quantity"))
            except (TypeError, ValueError):
                raise ToolError("Each item needs a whole-number quantity.") from None
            found = by_line_item.get(line_id)
            if found is None:
                raise ToolError(f"{line_id or 'that item'} is not still to ship on order {label}.")
            fo, line = found
            if quantity < 1 or quantity > line["remaining"]:
                raise ToolError(f"Only {line['remaining']} of {line['title']} remain to ship.")
            chosen[line["id"]] = (fo, line, quantity)
    else:
        for fo in open_orders:
            for line in fo["lines"]:
                if line["remaining"] > 0:
                    chosen[line["id"]] = (fo, line, line["remaining"])

    by_order: dict[str, list[dict[str, Any]]] = {}
    for fo, line, quantity in chosen.values():
        by_order.setdefault(fo["id"], []).append({"id": line["id"], "quantity": quantity})
    fulfillment_input: dict[str, Any] = {
        "notifyCustomer": bool(getattr(settings, "fulfil_notify", False)),
        "lineItemsByFulfillmentOrder": [{"fulfillmentOrderId": fo_id, "fulfillmentOrderLineItems": lines} for fo_id, lines in by_order.items()],
    }
    if tracking:
        fulfillment_input["trackingInfo"] = {"company": carrier_name, "number": tracking}

    # What remains once this ships, for the proof; complete when nothing remains anywhere.
    remaining = {line["id"]: line["remaining"] for fo in _fulfillment_orders(node) for line in fo["lines"]}
    for line_id, (_, _, quantity) in chosen.items():
        remaining[line_id] = max(0, remaining.get(line_id, 0) - quantity)
    complete = all(count == 0 for count in remaining.values())
    units = sum(quantity for _, _, quantity in chosen.values())
    items_words = ", ".join(
        f"{line['title']}{' ' + line['variant'] if line['variant'] else ''}{' ×' + str(quantity) if quantity > 1 else ''}" for _, line, quantity in chosen.values()
    )
    notify = fulfillment_input["notifyCustomer"]
    digits = label.rsplit("-", 1)[-1].lstrip("#")
    customer = str((node.get("customer") or {}).get("displayName") or "")
    read_back = f"mark order {digits}{f' for {customer}' if customer else ''} as shipped{'' if complete else ' in part'} with {carrier_name}"
    read_back += f", tracking {tracking}" if tracking else ", no tracking number"
    read_back += ", emailing the customer" if notify else ", without emailing the customer"
    return Prepared(
        execution={
            "order_id": str(order_id), "input": fulfillment_input, "expected_remaining": _remaining_hash(remaining), "complete": complete,
        },
        before=fulfil_fingerprint(node),
        expected_after={"remaining": _remaining_hash(remaining)},
        entity_ref=str(order_id),
        entity_label=label,
        summary={
            "customer": str((node.get("customer") or {}).get("displayName") or ""), "items_words": items_words, "units": units,
            "location": open_orders[0]["location"], "carrier": carrier_name, "tracking": tracking, "tracking_warning": tracking_warning,
            "notify": notify, "complete": complete, "read_back": read_back,
            "ledger": {
                "lines": len(chosen), "units": units, "carrier": carrier_name[:24], "tracked": bool(tracking), "notify": notify, "complete": complete,
            },
        },
    )


# ------------------------------------------------------------------------- stock
#
# One variant's available quantity at the one location the store keeps stock at, moved by a
# small number for a reason Shopify records. The Mac reads the quantity now and asks Shopify
# to set the new one only if the old one still stands (compareQuantity): a sale between the
# read and the hold makes the change stale, never wrong. Bounded: a hundred units at a time,
# never below zero, never at a store with more than one stock location (a guess between
# warehouses is not a stock count). Reversible: the undo moves it back the same guarded way.

VARIANT_STOCK_QUERY = """
query CrooksVariantStock($id: ID!) {
  productVariant(id: $id) {
    id
    title
    sku
    inventoryQuantity
    product { id title }
    inventoryItem {
      id
      tracked
      inventoryLevels(first: 5) {
        edges { node { id location { id name isActive } quantities(names: ["available", "on_hand"]) { name quantity } } }
      }
    }
  }
}
"""
MAX_STOCK_DELTA = 100
STOCK_REASONS = {
    "correction": "correction", "count": "correction", "recount": "correction", "received": "received", "delivery": "received",
    "damaged": "damaged", "restock": "restock", "returned": "restock", "return": "restock", "shrinkage": "shrinkage",
    "lost": "shrinkage", "stolen": "shrinkage", "other": "other",
}
REASON_SPOKEN = {"correction": "a recount", "received": "a delivery", "damaged": "damage", "restock": "a return to stock", "shrinkage": "shrinkage", "other": "no stated reason"}


async def _read_stock(client: ShopifyClient, variant_id: str) -> dict[str, Any]:
    payload = await client.graphql(VARIANT_STOCK_QUERY, {"id": variant_id})
    node = (payload.get("data") or {}).get("productVariant")
    if not isinstance(node, dict) or node.get("id") != variant_id:
        raise ToolError(f"No variant with id {variant_id}.")
    return node


def _stock_levels(node: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for edge in (((node.get("inventoryItem") or {}).get("inventoryLevels") or {}).get("edges") or []):
        level = edge.get("node") or {}
        location = level.get("location") or {}
        quantities = {str(q.get("name")): q.get("quantity") for q in level.get("quantities") or [] if isinstance(q, dict)}
        if location.get("id"):
            out.append({
                "location_id": str(location["id"]), "location": str(location.get("name") or ""), "active": bool(location.get("isActive", True)),
                "available": quantities.get("available"), "on_hand": quantities.get("on_hand"),
            })
    return out


def stock_fingerprint(node: dict[str, Any], location_id: str) -> dict[str, Any]:
    level = next((lv for lv in _stock_levels(node) if lv["location_id"] == location_id), None)
    return {
        "available": int(level["available"]) if level and level.get("available") is not None else None,
        "tracked": bool((node.get("inventoryItem") or {}).get("tracked")), "levels": len(_stock_levels(node)),
    }


async def _observe_stock(execution: dict) -> Observed:
    node = await _read_stock(_c(), str(execution["variant_id"]))
    return Observed(fingerprint=stock_fingerprint(node, str(execution["location_id"])), entity=None)


async def _execute_stock(execution: dict) -> dict:
    client = _c()
    payload = await client.mutate("inventory_set_quantities", {"input": dict(execution["input"])})
    group = ((payload.get("data") or {}).get("inventorySetQuantities") or {}).get("inventoryAdjustmentGroup") or {}
    if not group.get("id"):
        raise ShopifyError("Shopify did not confirm the stock change.")
    return {"adjustment_id": str(group["id"])}


def _verify_stock(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return observed.get("available") == int(execution.get("to")), ""


def _undo_stock(execution: dict) -> dict:
    reverse = dict(execution)
    reverse["from"], reverse["to"], reverse["delta"] = execution["to"], execution["from"], -int(execution["delta"])
    reverse["input"] = {
        **execution["input"], "referenceDocumentUri": f"gid://crooks-assistant/StockAdjustment/{uuid.uuid4().hex[:12]}",
        "quantities": [{**execution["input"]["quantities"][0], "quantity": int(execution["from"]), "compareQuantity": int(execution["to"])}],
    }
    return reverse


def _present_stock(proposal) -> dict:
    s = proposal.summary
    ex = dict(proposal.execution)
    if proposal.undo_of:
        return {"title": "Put the stock back", "summary": "", "detail": f"{ex.get('from')} → {ex.get('to')} at {ex.get('location') or 'the store'}.", "confirm_label": "Hold to undo", "undone_title": "Stock put back"}
    facts = [
        {"label": "Item", "value": str(s.get("item") or "")},
        {"label": "Location", "value": str(s.get("location") or "")},
        {"label": "Available", "value": f"{ex.get('from')} → {ex.get('to')}", "tone": "warn"},
        {"label": "Reason", "value": str(s.get("reason_words") or "")},
    ]
    if s.get("oversold"):
        facts.append({"label": "Note", "value": "This variant is oversold: more sold than were in stock.", "tone": "bad"})
    return {"title": "Adjust stock", "summary": "", "detail": "Changes what the shop can sell now. The undo puts it back.", "facts": facts, "done_title": "Stock adjusted"}


@tool(
    name="shopify_inventory_adjust",
    description=(
        "Prepare a change to one variant's available stock by a small number, up or down, for a "
        'reason (correction, received, damaged, restock, shrinkage). Needs a variant_id from a stock '
        'check or an order.'
    ),
    input_schema={
        "type": "object",
        "properties": {
            "variant_id": {"type": "string", "description": "The variant_id from a stock check or an order."},
            "delta": {"type": "integer", "minimum": -MAX_STOCK_DELTA, "maximum": MAX_STOCK_DELTA, "description": "How many to add (positive) or remove (negative)."},
            "reason": {"type": "string", "maxLength": 12, "description": "correction, received, damaged, restock, shrinkage or other."},
        },
        "required": ["variant_id", "delta"],
    },
    tier=Tier.RED,
    issued_id_args=("variant_id",),
    write=WriteSpec(
        operation="inventory_set",
        entity_kind="variant",
        entity_arg="variant_id",
        mutation="inventory_set_quantities",
        observe=_observe_stock,
        execute=_execute_stock,
        present=_present_stock,
        verify=_verify_stock,
        reversible=True,
        undo=_undo_stock,
        op_class="reversible",
        spoken_success="Stock for {label} is now {to}.",
        spoken_undo_success="Stock for {label} is back to {to}.",
        spoken_failure="I couldn't confirm the stock change. Check the variant before asking again.",
        spoken_stale="The stock moved since this was prepared — a sale, or a change in Admin. Nothing was sent.",
    ),
)
async def shopify_inventory_adjust(variant_id: str, delta: int, reason: str = "correction") -> Prepared:
    """Prepare, never send: the quantity as it is now at the one location, the new number
    decided here, and the compare quantity Shopify will hold it to."""
    try:
        change = int(delta)
    except (TypeError, ValueError):
        raise ToolError("delta must be a whole number.") from None
    if change == 0 or abs(change) > MAX_STOCK_DELTA:
        raise ToolError(f"Move stock by 1 to {MAX_STOCK_DELTA} units at a time.")
    reason_code = STOCK_REASONS.get(str(reason or "correction").strip().lower())
    if reason_code is None:
        raise ToolError("The reason must be one of: correction, received, damaged, restock, shrinkage, other.")
    node = await _read_stock(_c(), str(variant_id))
    item = (node.get("inventoryItem") or {})
    title = " ".join(p for p in (str((node.get("product") or {}).get("title") or ""), str(node.get("title") or "")) if p and p.lower() != "default title")
    if not item.get("tracked"):
        raise ToolError(f"Stock is not tracked for {title}; turn tracking on in Admin first.")
    levels = [lv for lv in _stock_levels(node) if lv["active"]]
    if len(levels) != 1:
        raise ToolError(f"{title} is stocked at {len(levels)} locations; adjust it in Admin." if levels else f"{title} is not stocked at any location.")
    level = levels[0]
    current = level.get("available")
    if current is None:
        raise ToolError(f"Shopify did not say how many {title} are available.")
    current = int(current)
    new = current + change
    if new < 0:
        raise ToolError(f"Only {max(current, 0)} {title} are available; the stock cannot go below zero.")
    reference = f"gid://crooks-assistant/StockAdjustment/{uuid.uuid4().hex[:12]}"
    stock_input = {
        "name": "available", "reason": reason_code, "referenceDocumentUri": reference, "ignoreCompareQuantity": False,
        "quantities": [{"inventoryItemId": str(item["id"]), "locationId": level["location_id"], "quantity": new, "compareQuantity": current}],
    }
    words = f"{'add' if change > 0 else 'remove'} {abs(change)}"
    read_back = f"{words} {title} at {level['location']}: {current} to {new}, {REASON_SPOKEN[reason_code]}"
    return Prepared(
        execution={"variant_id": str(variant_id), "location_id": level["location_id"], "location": level["location"], "from": current, "to": new, "delta": change, "input": stock_input},
        before=stock_fingerprint(node, level["location_id"]),
        expected_after={"available": new},
        entity_ref=str(variant_id),
        entity_label=title or str(node.get("sku") or "the variant"),
        summary={
            "item": title, "sku": str(node.get("sku") or ""), "location": level["location"], "reason_words": REASON_SPOKEN[reason_code],
            "oversold": current < 0, "spoken_to": str(new), "read_back": read_back,
            "ledger": {"delta": change, "was": current, "now": new, "reason": reason_code},
        },
    )


# ------------------------------------------------------------------- tracking
#
# A shipment already marked shipped without its number — Click & Drop prints the label, the
# number arrives afterwards — gets the number here. The Mac reads the order's shipments,
# takes the one shipment without a number, names the carrier as Shopify names it, and proves
# the change by re-reading that shipment's tracking. Setting a value, so never harmful to
# repeat; RED with a hold because the shipping email, when policy sends it, cannot be unsent.

TRACKING_STATE_QUERY = """
query CrooksFulfillmentsForTracking($id: ID!) {
  order(id: $id) {
    id
    name
    cancelledAt
    displayFulfillmentStatus
    customer { displayName }
    fulfillments(first: 10) { id status displayStatus trackingInfo { company number url } }
  }
}
"""


async def _read_tracking_state(client: ShopifyClient, order_id: str) -> dict[str, Any]:
    payload = await client.graphql(TRACKING_STATE_QUERY, {"id": order_id})
    node = (payload.get("data") or {}).get("order")
    if not isinstance(node, dict) or node.get("id") != order_id:
        raise ToolError(f"No order with id {order_id}.")
    return node


def _shipments(node: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in node.get("fulfillments") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        tracking = (f.get("trackingInfo") or [{}])[0] or {}
        out.append({
            "id": str(f["id"]), "status": str(f.get("status") or "").upper(),
            "number": str(tracking.get("number") or "").replace(" ", "").upper(), "company": str(tracking.get("company") or ""),
        })
    return out


def tracking_fingerprint(node: dict[str, Any], fulfillment_id: str) -> dict[str, Any]:
    shipment = next((s for s in _shipments(node) if s["id"] == fulfillment_id), None)
    return {
        "number": shipment["number"] if shipment else "", "company": shipment["company"][:24] if shipment else "",
        "status": shipment["status"] if shipment else "", "cancelled": bool(node.get("cancelledAt")),
    }


async def _observe_tracking(execution: dict) -> Observed:
    node = await _read_tracking_state(_c(), str(execution["order_id"]))
    return Observed(fingerprint=tracking_fingerprint(node, str(execution["fulfillment_id"])), entity=None)


async def _execute_tracking(execution: dict) -> dict:
    client = _c()
    payload = await client.mutate(
        "fulfillment_tracking_set",
        {"fulfillmentId": str(execution["fulfillment_id"]), "trackingInfoInput": dict(execution["input"]), "notifyCustomer": bool(execution["notify"])},
    )
    hydrator().forget(str(execution["order_id"]))
    fulfillment = ((payload.get("data") or {}).get("fulfillmentTrackingInfoUpdate") or {}).get("fulfillment") or {}
    if fulfillment.get("id") != str(execution["fulfillment_id"]):
        raise ShopifyError("Shopify did not confirm which shipment it updated.")
    return {"fulfillment_id": str(fulfillment["id"])}


def _verify_tracking(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return str(observed.get("number") or "") == str(execution.get("number") or ""), ""


def _present_tracking(proposal) -> dict:
    s = proposal.summary
    tracking = str(s.get("tracking") or "")
    facts = [
        {"label": "Customer", "value": str(s.get("customer") or "")},
        {"label": "Shipment", "value": str(s.get("shipment") or "")},
        {"label": "Carrier", "value": str(s.get("carrier") or "")},
        {"label": "Tracking", "value": tracking + (f" · {s['tracking_warning']}" if s.get("tracking_warning") else ""), "tone": "warn" if s.get("tracking_warning") else ""},
        {"label": "Customer emailed", "value": "yes — with the tracking link" if s.get("notify") else "no"},
    ]
    return {"title": "Add tracking", "summary": "", "detail": "Puts the number on the shipment already marked shipped.", "facts": facts, "done_title": "Tracking added"}


@tool(
    name="shopify_fulfillment_tracking_set",
    description=(
        "Prepare to add a tracking number to an order already marked shipped without one, with the "
        "carrier. Store policy decides whether the customer is emailed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order_id from a search."},
            "tracking_number": {"type": "string", "maxLength": 40, "description": "The tracking number."},
            "carrier": {"type": "string", "maxLength": 40, "description": "Royal Mail, Evri, DPD…; default the store's usual."},
        },
        "required": ["order_id", "tracking_number"],
    },
    tier=Tier.RED,
    issued_id_args=("order_id",),
    write=WriteSpec(
        operation="fulfillment_tracking_set",
        entity_kind="order",
        entity_arg="order_id",
        mutation="fulfillment_tracking_set",
        observe=_observe_tracking,
        execute=_execute_tracking,
        present=_present_tracking,
        entity=_entity_after,
        verify=_verify_tracking,
        op_class="irreversible",
        reversible=False,
        spoken_success="Tracking added to order {label}.",
        spoken_failure="I couldn't confirm the tracking was added. Check the order before asking again.",
        spoken_stale="The shipment changed since this was prepared. Nothing was sent.",
    ),
)
async def shopify_fulfillment_tracking_set(order_id: str, tracking_number: str, carrier: str = "") -> Prepared:
    """Prepare, never send: the one shipment without a number, the carrier as Shopify names
    it, and the number as it will be stored."""
    settings = policy()
    carrier_key = re.sub(r"[^a-z0-9]", "", str(carrier or getattr(settings, "carrier", "Royal Mail") or "").casefold())
    carrier_name = _CARRIER_BY_KEY.get(carrier_key)
    if carrier_name is None:
        raise ToolError("The carrier must be one Shopify knows: " + ", ".join(CARRIERS[:8]) + ", …")
    tracking = re.sub(r"\s+", "", str(tracking_number or "")).upper()
    if not _TRACKING_NUMBER.match(tracking):
        raise ToolError("The tracking number must be letters, digits and dashes, 8 to 34 characters.")
    tracking_warning = "not the usual Royal Mail form (two letters, nine digits, GB)" if carrier_name == "Royal Mail" and not _ROYAL_MAIL_S10.match(tracking) else ""
    node = await _read_tracking_state(_c(), str(order_id))
    label = str(node.get("name") or "")
    if node.get("cancelledAt"):
        raise ToolError(f"Order {label} is cancelled.")
    shipments = [s for s in _shipments(node) if s["status"] == "SUCCESS"]
    if not shipments:
        raise ToolError(f"Order {label} has no shipment marked shipped; fulfil it first, with the number.")
    without = [s for s in shipments if not s["number"]]
    if not without:
        raise ToolError(f"Order {label} already has tracking {shipments[-1]['number']} on its shipment.")
    if len(without) > 1:
        raise ToolError(f"Order {label} has {len(without)} shipments without tracking; add it in Admin.")
    shipment = without[0]
    notify = bool(getattr(settings, "fulfil_notify", False))
    digits = label.rsplit("-", 1)[-1].lstrip("#")
    customer = str((node.get("customer") or {}).get("displayName") or "")
    read_back = f"add tracking {tracking} with {carrier_name} to order {digits}{f' for {customer}' if customer else ''}" + (", emailing the customer" if notify else ", without emailing the customer")
    return Prepared(
        execution={"order_id": str(order_id), "fulfillment_id": shipment["id"], "input": {"company": carrier_name, "number": tracking}, "notify": notify, "number": tracking},
        before=tracking_fingerprint(node, shipment["id"]),
        expected_after={"number": tracking},
        entity_ref=str(order_id),
        entity_label=label,
        summary={
            "customer": customer, "shipment": f"{len(shipments)} of {len(shipments)}" if len(shipments) == 1 else f"the one of {len(shipments)} without a number",
            "carrier": carrier_name, "tracking": tracking, "tracking_warning": tracking_warning, "notify": notify, "read_back": read_back,
            "ledger": {"carrier": carrier_name[:24], "notify": notify},
        },
    )


# --------------------------------------------------------------- adding a line to an order
#
# "Add a black hoodie to this order" was refused all through Phase 2 because line-item
# changes were unsupported. They are supported here, and the reason this is safe to offer at
# all is the shape of Shopify's own API for it: an order edit is a THREE-step mutation and
# only the last step touches the order.
#
#   orderEditBegin        opens a CalculatedOrder — a scratch copy Shopify prices for us
#   orderEditAddVariant   puts the variant on THAT, and answers with the new arithmetic
#   orderEditCommit       applies it to the real order
#
# So PREPARE runs the first two. Nothing the customer or the shop can see has moved when the
# card goes up, and every number on it — the line's unit price, the new total, what the
# customer will owe — is Shopify's own calculation of the edit, not ours and never the
# model's. The commit is the one mutation the gesture authorises.
#
# RED and irreversible: there is no orderEditRemoveVariant undo that puts a paid order back
# as it was, and the money owed follows the customer. The gesture is a hold.

MAX_ADD_QUANTITY = 20
MAX_EDIT_STAFF_NOTE = 200

ORDER_EDIT_STATE_QUERY = """
query CrooksOrderEditState($id: ID!) {
  order(id: $id) {
    id
    name
    cancelledAt
    closedAt
    currencyCode
    presentmentCurrencyCode
    displayFinancialStatus
    displayFulfillmentStatus
    currentTotalPriceSet { shopMoney { amount currencyCode } }
    totalOutstandingSet { shopMoney { amount currencyCode } }
    customer { displayName }
    lineItems(first: 50) { pageInfo { hasNextPage } edges { node { id title quantity currentQuantity variant { id } } } }
  }
}
"""

VARIANT_FOR_EDIT_QUERY = """
query CrooksVariantForOrderEdit($id: ID!) {
  productVariant(id: $id) {
    id
    title
    sku
    price
    availableForSale
    inventoryQuantity
    selectedOptions { name value }
    product { id title status }
  }
}
"""


async def _read_order_edit_state(client: ShopifyClient, order_id: str) -> dict[str, Any]:
    payload = await client.graphql(ORDER_EDIT_STATE_QUERY, {"id": order_id})
    node = (payload.get("data") or {}).get("order")
    if not isinstance(node, dict) or node.get("id") != order_id:
        raise ToolError(f"No order with id {order_id}.")
    return node


def _order_lines(node: dict[str, Any]) -> list[dict[str, Any]]:
    """The order's live lines: id, how many of them there still are, which variant, and the
    title. `currentQuantity` is what is on the order NOW — a refunded or removed line reads 0 —
    and that is what a line count on this card has to mean. A custom line has no variant
    (Shopify's LineItem has no field that marks one, so "no variant" is the mark)."""
    out = []
    for edge in ((node.get("lineItems") or {}).get("edges") or []):
        line = (edge or {}).get("node") or {}
        if not line.get("id"):
            continue
        quantity = line.get("currentQuantity")
        if quantity is None:
            quantity = line.get("quantity")
        out.append({
            "id": str(line["id"]),
            "quantity": int(quantity or 0),
            "variant_id": str(((line.get("variant") or {}).get("id")) or ""),
            "title": str(line.get("title") or ""),
        })
    return [line for line in out if line["quantity"] > 0]


def order_edit_fingerprint(node: dict[str, Any], variant_id: str) -> dict[str, Any]:
    """What the order must still look like for this addition to be the one that was prepared.

    The line count and the total, as the brief asks — plus how many of THIS variant the order
    already carries, and whether it is cancelled or archived. The extra three are not padding:
    `allowDuplicates: false` means Shopify may fold the addition into an existing line, so the
    line count alone cannot prove the change landed; and an order cancelled between the card
    and the tap need not have moved its total at all, so without the flag a cancelled order
    would pass the precondition and be edited.
    """
    lines = _order_lines(node)
    total = _amount(node.get("currentTotalPriceSet"))
    return {
        "lines": len(lines),
        "total": f"{total:.2f}" if total is not None else "",
        "variant_qty": sum(line["quantity"] for line in lines if line["variant_id"] == str(variant_id)),
        "cancelled": bool(node.get("cancelledAt")),
        "closed": bool(node.get("closedAt")),
    }


async def _observe_order_add_item(execution: dict) -> Observed:
    node = await _read_order_edit_state(_c(), str(execution["order_id"]))
    return Observed(fingerprint=order_edit_fingerprint(node, str(execution["variant_id"])), entity=None)


async def _entity_after_order_add_item(execution: dict) -> dict:
    return await hydrator().order(str(execution["order_id"]), budget_s=0.0, fresh=True)


async def _execute_order_add_item(execution: dict) -> dict:
    """The commit, and only the commit. The CalculatedOrder was built and priced at staging
    time; this applies it. `notifyCustomer` is false always — an email about money now owed
    is the owner's to write, not a side effect of a tap — and the staff note is built here
    from what was stored, so nothing new is decided at execution time."""
    client = _c()
    order_id = str(execution["order_id"])
    note = f"Added {int(execution['quantity'])} x {execution['line_item_title']} (CROOKS assistant)"
    payload = await client.mutate(
        "order_edit_commit",
        {"id": str(execution["calculated_order_id"]), "notifyCustomer": False, "staffNote": note[:MAX_EDIT_STAFF_NOTE]},
    )
    hydrator().forget(order_id)
    order = ((payload.get("data") or {}).get("orderEditCommit") or {}).get("order") or {}
    if order.get("id") != order_id:
        raise ShopifyError("Shopify did not confirm which order it edited.")
    return {"order_id": str(order["id"])}


def _verify_order_add_item(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """Proof, by re-reading the order: it carries at least this many more of the variant, and
    the total is the one Shopify calculated for the edit.

    "A line for that variant with a quantity of at least what was asked for" would pass on an
    order that ALREADY had one and to which nothing was added — which is the commonest case
    here. So the test is against the quantity the order carried when the change was prepared.
    """
    try:
        added = int(execution.get("quantity") or 0)
        moved = int(observed.get("variant_qty") or 0) - int(before.get("variant_qty") or 0)
    except (TypeError, ValueError):
        return False, ""
    if moved < added:
        return False, ""
    total = str(observed.get("total") or "")
    if total != str(execution.get("new_total") or ""):
        # The line is on the order; the total is not the one that was priced (another edit
        # landed, a discount recalculated). Proven applied, and the card says to look.
        return True, "the order's total is not the figure on the card; check the order."
    return True, ""


def _present_order_add_item(proposal) -> dict:
    s = proposal.summary
    currency = str(s.get("currency") or "GBP")
    facts = [
        {"label": "Customer", "value": str(s.get("customer") or "")},
        {"label": "Adding", "value": str(s.get("line") or "")},
        {"label": "Unit price", "value": str(s.get("unit_price_display") or "")},
        {"label": "Adds", "value": f"{_display(float(s.get('subtotal_delta') or 0), currency)} to the order", "tone": "warn"},
        {"label": "New total", "value": _display(float(s.get("amount") or 0), currency)},
        {"label": "Customer owes", "value": f"{_display(float(s.get('amount_outstanding') or 0), currency)} after this", "tone": "bad" if float(s.get("amount_outstanding") or 0) > 0 else ""},
        {"label": "Customer emailed", "value": "no — tell them yourself"},
    ]
    if s.get("stock_note"):
        facts.append({"label": "Stock", "value": str(s.get("stock_note")), "tone": "warn"})
    return {
        "title": "Add to the order",
        "summary": "",
        "detail": "Applies the edit Shopify has already priced. It cannot be undone from here.",
        "facts": facts,
        "done_title": "Item added",
    }


@tool(
    name="shopify_order_add_item",
    description=(
        "Prepare to add one product variant to an existing order, priced by Shopify. The "
        "customer is not emailed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "From a search."},
            "variant_id": {"type": "string", "description": "From shopify_variant_search."},
            "quantity": {"type": "integer", "minimum": 1, "maximum": MAX_ADD_QUANTITY},
        },
        "required": ["order_id", "variant_id"],
    },
    tier=Tier.RED,
    issued_id_args=("order_id", "variant_id"),
    write=WriteSpec(
        operation="order_edit_add_line",
        entity_kind="order",
        entity_arg="order_id",
        mutation="order_edit_commit",
        observe=_observe_order_add_item,
        execute=_execute_order_add_item,
        present=_present_order_add_item,
        entity=_entity_after_order_add_item,
        verify=_verify_order_add_item,
        op_class="irreversible",
        reversible=False,
        spoken_success="Added to order {label}. The total is now {amount}.",
        spoken_failure="I couldn't confirm the item was added. Check the order before asking again.",
        spoken_stale="The order changed since this was prepared. Nothing was added.",
    ),
)
async def shopify_order_add_item(order_id: str, variant_id: str, quantity: int = 1) -> Prepared:
    """Prepare, never commit: read the order and the variant, open a CalculatedOrder, put the
    variant on it, and keep Shopify's arithmetic for the card.

    The two mutations this sends — `order_edit_begin` and `order_edit_add_variant` — change
    NOTHING on the order. They build and price the scratch copy that `order_edit_commit`
    later applies, which is how the financial consequence is known before the owner's
    gesture rather than after it.
    """
    client = _c()
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ToolError("The quantity must be a whole number.") from None
    if not 1 <= quantity <= MAX_ADD_QUANTITY:
        raise ToolError(f"The quantity must be between 1 and {MAX_ADD_QUANTITY}.")

    node = await _read_order_edit_state(client, str(order_id))
    label = str(node.get("name") or "")
    if node.get("cancelledAt"):
        raise ToolError(f"Order {label} is cancelled; nothing can be added to it.")
    if node.get("closedAt"):
        raise ToolError(f"Order {label} is archived; reopen it in Admin before adding to it.")

    variant = ((await client.graphql(VARIANT_FOR_EDIT_QUERY, {"id": str(variant_id)})).get("data") or {}).get("productVariant")
    if not isinstance(variant, dict) or variant.get("id") != str(variant_id):
        raise ToolError(f"No product variant with id {variant_id}.")
    product = variant.get("product") or {}
    if str(product.get("status") or "ACTIVE").upper() != "ACTIVE" or not variant.get("availableForSale"):
        raise ToolError(
            f"{str(product.get('title') or 'That item')} {str(variant.get('title') or '')}".strip()
            + " is not for sale, so it cannot be added to an order."
        )
    options = [str((o or {}).get("value") or "") for o in (variant.get("selectedOptions") or []) if (o or {}).get("value")]
    variant_words = " / ".join(options) or str(variant.get("title") or "")
    line_title = str(product.get("title") or variant.get("title") or "item")
    available = variant.get("inventoryQuantity")
    stock_note = ""
    if isinstance(available, int) and not isinstance(available, bool) and available < quantity:
        # Not a refusal: Shopify's own oversell policy decides whether the sale may happen,
        # and a shop that makes its own garments often adds a line it is about to cut.
        stock_note = f"{available} in stock, {quantity} being added"

    # From here on nothing is arithmetic of ours. Shopify opens the scratch order and prices
    # the addition on it; both mutations leave the real order exactly as it is.
    begun = await client.mutate("order_edit_begin", {"id": str(order_id)})
    calculated = ((begun.get("data") or {}).get("orderEditBegin") or {}).get("calculatedOrder") or {}
    calculated_order_id = str(calculated.get("id") or "")
    if not calculated_order_id:
        raise ShopifyError("Shopify did not open an order edit for that order.")
    added = await client.mutate(
        "order_edit_add_variant",
        {"id": calculated_order_id, "variantId": str(variant_id), "quantity": quantity, "allowDuplicates": False},
    )
    body = ((added.get("data") or {}).get("orderEditAddVariant") or {})
    calculated_line = body.get("calculatedLineItem") or {}
    edited = body.get("calculatedOrder") or {}
    unit_price = _amount(calculated_line.get("originalUnitPriceSet"))
    currency = _currency(calculated_line.get("originalUnitPriceSet") or node.get("currentTotalPriceSet"))
    new_total = _amount(edited.get("totalPriceSet"))
    outstanding = _amount(edited.get("totalOutstandingSet"))
    if new_total is None or unit_price is None:
        raise ShopifyError("Shopify did not price the edit; nothing was changed.")
    # The line count the edited order will show, from Shopify's own calculated lines rather
    # than from "one more than before": with `allowDuplicates: false` an addition of
    # something the order already has folds into that line and the count does not move.
    calculated_lines = [
        e for e in ((edited.get("lineItems") or {}).get("edges") or [])
        if isinstance(e, dict) and int(((e.get("node") or {}).get("quantity")) or 0) > 0
    ]
    before = order_edit_fingerprint(node, str(variant_id))
    subtotal_delta = round(unit_price * quantity, 2)
    customer = str((node.get("customer") or {}).get("displayName") or "")
    digits = label.rsplit("-", 1)[-1].lstrip("#")
    line = f"{quantity} x {line_title}{f' ({variant_words})' if variant_words else ''}"
    read_back = (
        f"add {line} to order {digits}{f' for {customer}' if customer else ''}, "
        f"{_display(subtotal_delta, currency)} more, taking the order to {_display(new_total, currency)}"
    )
    return Prepared(
        execution={
            "calculated_order_id": calculated_order_id,
            "order_id": str(order_id),
            "variant_id": str(variant_id),
            "quantity": quantity,
            "line_item_title": line_title,
            "unit_price": f"{unit_price:.2f}",
            "subtotal_delta": f"{subtotal_delta:.2f}",
            "new_total": f"{new_total:.2f}",
            "amount_outstanding": f"{outstanding:.2f}" if outstanding is not None else "",
        },
        before=before,
        # The fingerprint the order must show once the edit is applied: Shopify's line count
        # and total, and this variant's quantity moved by what is being added. `verify` is
        # what actually proves it (the count cannot, see above); this is what the ledger and
        # the default equality path read.
        expected_after={
            "lines": len(calculated_lines) or before["lines"] + 1,
            "total": f"{new_total:.2f}",
            "variant_qty": before["variant_qty"] + quantity,
            "cancelled": False,
            "closed": False,
        },
        entity_ref=str(order_id),
        entity_label=label,
        summary={
            "customer": customer,
            "line": line,
            "variant": variant_words,
            "product": line_title,
            "quantity": quantity,
            "unit_price": f"{unit_price:.2f}",
            "unit_price_display": _display(unit_price, currency),
            "subtotal_delta": f"{subtotal_delta:.2f}",
            # `amount` is what the spoken success line reads out (engine._spoken_amount).
            "amount": f"{new_total:.2f}",
            "amount_outstanding": f"{outstanding:.2f}" if outstanding is not None else "0.00",
            "currency": currency,
            "stock_note": stock_note,
            "read_back": read_back,
            "spoken_to": _display(new_total, currency),
            "ledger": {"quantity": quantity, "adds": f"{subtotal_delta:.2f}", "currency": currency[:24]},
        },
    )


# --------------------------------------------------------------- a custom line on an order
#
# The sibling of the addition above, for what the catalogue does not list: "add a £15 rush
# alteration to order 1930" (the owner's decision 8 of 1 October 2026: "custom item on an
# existing order: yes"). The same three steps and the same boundary: PREPARE opens the
# CalculatedOrder and puts the custom line on it with `orderEditAddCustomItem`, which changes
# nothing on the order; the card carries Shopify's arithmetic for the edit; the hold sends
# `orderEditCommit` and nothing else.
#
# What differs is where the numbers come from. A variant's price is the catalogue's; a custom
# line's is the owner's, so it is held here to a positive amount in pence and no more than
# MAX_CUSTOM_LINE_PRICE a unit ("fifteen" heard as "fifteen hundred" is refused, not priced),
# and the currency is the ORDER's, read from the order and never an argument. An order the
# customer paid in a currency other than the shop's is refused: which of the two a custom
# price is in is not something to settle by guessing on a paid order.
#
# Proof is the line itself: the re-read order carries at least `quantity` more of a live line
# with no variant and exactly this title than it did when the change was prepared.

_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")


def _custom_title(value: Any) -> str:
    """The title as it will be sent: trimmed, plain text, bounded — or a refusal in words."""
    title = value.strip() if isinstance(value, str) else ""
    if not title:
        raise ToolError("The custom item needs a title: what it is, in a few words.")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in title):
        raise ToolError("The title has a control character in it; say it in plain words.")
    if "<" in title:
        raise ToolError("The title cannot contain '<'; say it in plain words.")
    if len(title) > MAX_CUSTOM_TITLE_CHARS:
        raise ToolError(f"The title must be at most {MAX_CUSTOM_TITLE_CHARS} characters; it is {len(title)}.")
    return title


def _custom_price(value: Any) -> Decimal:
    """The unit price as an exact amount of money — or a refusal in words. Never rounded: a
    price with a third decimal place is a misunderstanding, not a figure to tidy up."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ToolError("The price must be an amount of money, like 15 or 15.50.")
    try:
        price = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ToolError("The price must be an amount of money, like 15 or 15.50.") from None
    if not price.is_finite():
        raise ToolError("The price must be an amount of money, like 15 or 15.50.")
    if price <= 0:
        raise ToolError("The price must be more than zero.")
    if price > Decimal(str(MAX_CUSTOM_LINE_PRICE)):
        raise ToolError(f"The price must be at most {MAX_CUSTOM_LINE_PRICE:,.2f} a unit; a bigger addition is one to make in Admin.")
    if price != price.quantize(Decimal("0.01")):
        raise ToolError("The price can have at most two decimal places.")
    return price.quantize(Decimal("0.01"))


def _order_currency(node: dict[str, Any], label: str) -> str:
    """The currency a custom price on this order is in: the order's own, as Shopify states it.
    Refused when Shopify does not say, and when the customer paid in another currency than
    the shop's — never defaulted, and never the model's."""
    shop = str(node.get("currencyCode") or "").upper()
    paid = str(node.get("presentmentCurrencyCode") or "").upper()
    if not _CURRENCY_CODE.match(shop) or not _CURRENCY_CODE.match(paid):
        raise ToolError(f"Shopify did not say what currency order {label} is in; nothing was prepared.")
    if paid != shop:
        raise ToolError(f"Order {label} was paid in {paid}, not the shop's {shop}; add a custom item to it in Admin.")
    return shop


def order_custom_item_fingerprint(node: dict[str, Any], title: str) -> dict[str, Any]:
    """What the order must still look like for this custom line to be the one that was
    prepared: the line count, the total, how many of a custom line with THIS title it already
    carries, and whether it is cancelled or archived (see `order_edit_fingerprint` for why the
    last two are there)."""
    lines = _order_lines(node)
    total = _amount(node.get("currentTotalPriceSet"))
    return {
        "lines": len(lines),
        "total": f"{total:.2f}" if total is not None else "",
        "custom_qty": sum(line["quantity"] for line in lines if not line["variant_id"] and line["title"] == str(title)),
        "cancelled": bool(node.get("cancelledAt")),
        "closed": bool(node.get("closedAt")),
    }


async def _observe_order_add_custom_item(execution: dict) -> Observed:
    node = await _read_order_edit_state(_c(), str(execution["order_id"]))
    return Observed(fingerprint=order_custom_item_fingerprint(node, str(execution["title"])), entity=None)


async def _execute_order_add_custom_item(execution: dict) -> dict:
    """The commit, and only the commit, as for a variant: `notifyCustomer` false always, and
    the staff note built here from what was stored."""
    client = _c()
    order_id = str(execution["order_id"])
    note = f"Added {int(execution['quantity'])} x {execution['title']} (custom item, CROOKS assistant)"
    payload = await client.mutate(
        "order_edit_commit",
        {"id": str(execution["calculated_order_id"]), "notifyCustomer": False, "staffNote": note[:MAX_EDIT_STAFF_NOTE]},
    )
    hydrator().forget(order_id)
    order = ((payload.get("data") or {}).get("orderEditCommit") or {}).get("order") or {}
    if order.get("id") != order_id:
        raise ShopifyError("Shopify did not confirm which order it edited.")
    return {"order_id": str(order["id"])}


def _verify_order_add_custom_item(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """Proof, by re-reading the order: it carries at least this many more of a custom line
    with this title than it did when the change was prepared (an order that already had one
    must not pass on the one it had), and the total is the one Shopify calculated."""
    try:
        added = int(execution.get("quantity") or 0)
        moved = int(observed.get("custom_qty") or 0) - int(before.get("custom_qty") or 0)
    except (TypeError, ValueError):
        return False, ""
    if added < 1 or moved < added:
        return False, ""
    if str(observed.get("total") or "") != str(execution.get("new_total") or ""):
        return True, "the order's total is not the figure on the card; check the order."
    return True, ""


def _present_order_add_custom_item(proposal) -> dict:
    s = proposal.summary
    currency = str(s.get("currency") or "")
    treated = ("taxable" if s.get("taxable") else "not taxable") + " · " + ("needs shipping" if s.get("requires_shipping") else "needs no shipping")
    facts = [
        {"label": "Customer", "value": str(s.get("customer") or "")},
        {"label": "Adding", "value": str(s.get("line") or "")},
        {"label": "Unit price", "value": str(s.get("unit_price_display") or "")},
        {"label": "Adds", "value": f"{_display(float(s.get('adds') or 0), currency)} to the order", "tone": "warn"},
        {"label": "Treated as", "value": treated},
        {"label": "New total", "value": _display(float(s.get("amount") or 0), currency)},
        {"label": "Customer owes", "value": f"{_display(float(s.get('amount_outstanding') or 0), currency)} after this", "tone": "bad" if float(s.get("amount_outstanding") or 0) > 0 else ""},
        {"label": "Customer emailed", "value": "no — tell them yourself"},
    ]
    return {
        "title": "Add a custom item to the order",
        "summary": "",
        "detail": "Applies the edit Shopify has already priced. It cannot be undone from here.",
        "facts": facts,
        "done_title": "Custom item added",
    }


@tool(
    name="shopify_order_add_custom_item",
    description="Prepare to add a custom line (not a catalogue product) to an existing order, priced by Shopify. The customer is not emailed.",
    input_schema={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "From a search."},
            "title": {"type": "string", "minLength": 1, "maxLength": MAX_CUSTOM_TITLE_CHARS},
            "price": {"type": "number", "minimum": 0.01, "maximum": MAX_CUSTOM_LINE_PRICE, "description": "Unit price, order's currency."},
            "quantity": {"type": "integer", "minimum": 1, "maximum": MAX_ADD_QUANTITY},
            "taxable": {"type": "boolean"},
            "requires_shipping": {"type": "boolean"},
        },
        "required": ["order_id", "title", "price"],
    },
    tier=Tier.RED,
    issued_id_args=("order_id",),
    write=WriteSpec(
        operation="order_edit_add_custom_line",
        entity_kind="order",
        entity_arg="order_id",
        mutation="order_edit_commit",
        observe=_observe_order_add_custom_item,
        execute=_execute_order_add_custom_item,
        present=_present_order_add_custom_item,
        entity=_entity_after_order_add_item,
        verify=_verify_order_add_custom_item,
        op_class="irreversible",
        reversible=False,
        spoken_success="Added to order {label}. The total is now {amount}.",
        spoken_failure="I couldn't confirm the custom item was added. Check the order before asking again.",
        spoken_stale="The order changed since this was prepared. Nothing was added.",
    ),
)
async def shopify_order_add_custom_item(
    order_id: str, title: str, price: Any, quantity: int = 1, taxable: bool = True, requires_shipping: bool = False,
) -> Prepared:
    """Prepare, never commit: check what the owner said, read the order, open a CalculatedOrder,
    put the custom line on it in the order's own currency, and keep Shopify's arithmetic for
    the card.

    `taxable` and `requires_shipping` default to Shopify's own defaults for a custom item
    (taxable; no shipping) and are sent explicitly either way, so the card states what Shopify
    was told. The two mutations this sends — `order_edit_begin` and
    `order_edit_add_custom_item` — change NOTHING on the order.
    """
    client = _c()
    line_title = _custom_title(title)
    unit = _custom_price(price)
    # A whole number, or a refusal: 1.5 is not "one", and truncating it would add a line nobody
    # asked for to a paid order.
    if isinstance(quantity, bool) or (isinstance(quantity, float) and not quantity.is_integer()):
        raise ToolError("The quantity must be a whole number.")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ToolError("The quantity must be a whole number.") from None
    if not 1 <= quantity <= MAX_ADD_QUANTITY:
        raise ToolError(f"The quantity must be between 1 and {MAX_ADD_QUANTITY}.")
    if not isinstance(taxable, bool) or not isinstance(requires_shipping, bool):
        raise ToolError("Whether it is taxable and whether it needs shipping are each yes or no.")

    node = await _read_order_edit_state(client, str(order_id))
    label = str(node.get("name") or "")
    if node.get("cancelledAt"):
        raise ToolError(f"Order {label} is cancelled; nothing can be added to it.")
    if node.get("closedAt"):
        raise ToolError(f"Order {label} is archived; reopen it in Admin before adding to it.")
    currency = _order_currency(node, label)
    if (((node.get("lineItems") or {}).get("pageInfo")) or {}).get("hasNextPage"):
        # The proof counts this order's lines; one it cannot read whole could never prove the
        # line landed, and the owner would be told to check an order that had in fact changed.
        raise ToolError(f"Order {label} has more lines than CLIVE reads at once; add a custom item to it in Admin.")
    current_total = _amount(node.get("currentTotalPriceSet"))

    # From here on nothing is arithmetic of ours. Shopify opens the scratch order and prices
    # the custom line on it; both mutations leave the real order exactly as it is.
    begun = await client.mutate("order_edit_begin", {"id": str(order_id)})
    calculated = ((begun.get("data") or {}).get("orderEditBegin") or {}).get("calculatedOrder") or {}
    calculated_order_id = str(calculated.get("id") or "")
    if not calculated_order_id:
        raise ShopifyError("Shopify did not open an order edit for that order.")
    added = await client.mutate(
        "order_edit_add_custom_item",
        {
            "id": calculated_order_id,
            "title": line_title,
            "price": {"amount": f"{unit:.2f}", "currencyCode": currency},
            "quantity": quantity,
            "taxable": taxable,
            "requiresShipping": requires_shipping,
        },
    )
    body = ((added.get("data") or {}).get("orderEditAddCustomItem") or {})
    calculated_line = body.get("calculatedLineItem") or {}
    edited = body.get("calculatedOrder") or {}
    unit_price = _amount(calculated_line.get("originalUnitPriceSet"))
    new_total = _amount(edited.get("totalPriceSet"))
    outstanding = _amount(edited.get("totalOutstandingSet"))
    if new_total is None or unit_price is None:
        raise ShopifyError("Shopify did not price the edit; nothing was changed.")
    line_money = (calculated_line.get("originalUnitPriceSet") or {}).get("shopMoney") or {}
    if f"{unit_price:.2f}" != f"{unit:.2f}" or str(line_money.get("currencyCode") or "") != currency:
        # The line is ours to price, so Shopify answering with another figure means the edit is
        # not the one the owner asked for. Nothing was applied; nothing is offered.
        raise ShopifyError(
            f"Shopify priced the custom item at {_display(unit_price, str(line_money.get('currencyCode') or '?'))}, "
            f"not {_display(float(unit), currency)}; nothing was changed."
        )
    # The title the order will carry is the one Shopify gave the calculated line; the proof
    # and the card both use it, so what is checked is what was priced.
    stored_title = str(calculated_line.get("title") or "").strip() or line_title
    calculated_lines = [
        e for e in ((edited.get("lineItems") or {}).get("edges") or [])
        if isinstance(e, dict) and int(((e.get("node") or {}).get("quantity")) or 0) > 0
    ]
    before = order_custom_item_fingerprint(node, stored_title)
    subtotal_delta = unit * quantity
    # What the order moves by is Shopify's: its new total less the order's total now, which
    # includes any tax Shopify adds on a taxable line. The line price alone would understate it.
    adds = (Decimal(f"{new_total:.2f}") - Decimal(f"{current_total:.2f}")) if current_total is not None else subtotal_delta
    customer = str((node.get("customer") or {}).get("displayName") or "")
    digits = label.rsplit("-", 1)[-1].lstrip("#")
    line = f"{quantity} x {stored_title}"
    read_back = (
        f"add {line} (a custom item) to order {digits}{f' for {customer}' if customer else ''}, "
        f"{_display(float(adds), currency)} more, taking the order to {_display(new_total, currency)}"
    )
    return Prepared(
        execution={
            "calculated_order_id": calculated_order_id,
            "order_id": str(order_id),
            "title": stored_title,
            "quantity": quantity,
            "unit_price": f"{unit:.2f}",
            "currency": currency,
            "taxable": taxable,
            "requires_shipping": requires_shipping,
            "subtotal_delta": f"{subtotal_delta:.2f}",
            "new_total": f"{new_total:.2f}",
            "amount_outstanding": f"{outstanding:.2f}" if outstanding is not None else "",
        },
        before=before,
        # A custom line is always a line of its own (there is no catalogue variant to fold it
        # into), so the count moves by one; Shopify's own calculated lines say so first.
        expected_after={
            "lines": len(calculated_lines) or before["lines"] + 1,
            "total": f"{new_total:.2f}",
            "custom_qty": before["custom_qty"] + quantity,
            "cancelled": False,
            "closed": False,
        },
        entity_ref=str(order_id),
        entity_label=label,
        summary={
            "customer": customer,
            "line": line,
            "title": stored_title,
            "quantity": quantity,
            "unit_price": f"{unit:.2f}",
            "unit_price_display": _display(float(unit), currency),
            "subtotal_delta": f"{subtotal_delta:.2f}",
            "adds": f"{adds:.2f}",
            "taxable": taxable,
            "requires_shipping": requires_shipping,
            # `amount` is what the spoken success line reads out (engine._spoken_amount).
            "amount": f"{new_total:.2f}",
            "amount_outstanding": f"{outstanding:.2f}" if outstanding is not None else "0.00",
            "currency": currency,
            "read_back": read_back,
            "spoken_to": _display(new_total, currency),
            "ledger": {"quantity": quantity, "adds": f"{adds:.2f}", "currency": currency[:24]},
        },
    )
