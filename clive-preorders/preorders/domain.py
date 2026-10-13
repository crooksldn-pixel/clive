"""The rules, with no Shopify and no database: what state a variant is in, how much can still be
preordered, which preorders the stock that arrived covers, and what a line means to the rest of
CLIVE. Everything else asks these functions; nothing re-implements them.

The unit is the Shopify variant: sizes of one product differ.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class CommerceState(StrEnum):
    IN_STOCK = "IN_STOCK"  # normal Shopify behaviour
    PREORDER = "PREORDER"  # an open offer with capacity left, and nothing on the shelf
    NOTIFY_ME = "NOTIFY_ME"  # can't be bought now: collect demand


class Mode(StrEnum):
    AUTO = "AUTO"  # shelf stock first, then preorder while capacity lasts, then Notify me
    PREORDER_ONLY = "PREORDER_ONLY"  # preorder even while some stock is on the shelf
    NOTIFY_ONLY = "NOTIFY_ONLY"  # never preorder; Notify me when the shelf is empty


class BatchStatus(StrEnum):
    PLANNED = "PLANNED"
    ORDERED = "ORDERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELAYED = "DELAYED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


OPEN_BATCH = frozenset(
    {
        BatchStatus.PLANNED,
        BatchStatus.ORDERED,
        BatchStatus.IN_TRANSIT,
        BatchStatus.DELAYED,
        BatchStatus.PARTIALLY_RECEIVED,
    }
)


class OfferStatus(StrEnum):
    DRAFT = "DRAFT"  # configured, not on sale
    ACTIVE = "ACTIVE"  # on sale while capacity lasts
    CLOSED = "CLOSED"  # stopped by staff, or the batch arrived or was cancelled


class LineState(StrEnum):
    AWAITING_STOCK = "AWAITING_STOCK"
    READY = "READY"  # the stock that arrived covers it
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class Classification(StrEnum):
    """What CLIVE Shipping (or anyone) needs to know about one order line."""

    IN_STOCK = "IN_STOCK"  # an ordinary line: dispatch as normal
    PREORDER_WAITING = "PREORDER_WAITING"  # a preorder whose stock hasn't arrived
    PREORDER_READY = "PREORDER_READY"  # a preorder the received stock now covers
    CANCELLED = "CANCELLED"


class WaitlistStatus(StrEnum):
    ACTIVE = "ACTIVE"
    NOTIFIED = "NOTIFIED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    CONVERTED = "CONVERTED"


# ------------------------------------------------------------------ capacity and state


def remaining(allocation: int, sold: int) -> int:
    """Preorder units still on offer. Never negative: an oversell shows as `oversold`."""
    return max(allocation - sold, 0)


def oversold(allocation: int, sold: int) -> int:
    return max(sold - allocation, 0)


def derive_state(
    *,
    available: int,
    offer_active: bool,
    allocation: int,
    sold: int,
    mode: Mode = Mode.AUTO,
    override: CommerceState | None = None,
) -> CommerceState:
    """The state the storefront shows for one variant.

    `available` is Shopify's own figure; with preorders committed against it (the selling plan
    reserves on sale) it can be below zero, which means "nothing on the shelf".
    """
    if override is not None:
        return override
    shelf = available > 0
    open_ = offer_active and remaining(allocation, sold) > 0
    if mode == Mode.NOTIFY_ONLY:
        return CommerceState.IN_STOCK if shelf else CommerceState.NOTIFY_ME
    if mode == Mode.PREORDER_ONLY and open_:
        return CommerceState.PREORDER
    if shelf:
        return CommerceState.IN_STOCK
    return CommerceState.PREORDER if open_ else CommerceState.NOTIFY_ME


def badge(
    state: CommerceState, *, had_offer: bool, capacity_left: int, delayed: bool
) -> tuple[str, str]:
    """(label, Polaris tone) for the admin: IN STOCK, PRE-ORDER, DELAYED, SOLD OUT, WAITLIST."""
    if state == CommerceState.IN_STOCK:
        return "In stock", "success"
    if state == CommerceState.PREORDER:
        return ("Delayed", "warning") if delayed else ("Pre-order", "info")
    if had_offer and capacity_left <= 0:
        return "Sold out", "critical"
    return "Waitlist", "neutral"


# ------------------------------------------------------------------ readiness


@dataclass(frozen=True)
class OpenLine:
    """A preorder line still owed to a customer, for readiness."""

    id: str
    ordered_at: datetime
    units: int  # still to be dispatched (current quantity less fulfilled)


def ready_units(lines: Iterable[OpenLine], received: int) -> dict[str, int]:
    """How many units of each line the received stock covers, oldest order first.

    Received stock is committed to preorders first (the selling plan reserves on sale), so every
    unit received for a batch line backs a preorder until they are all covered.
    """
    left = max(received, 0)
    out: dict[str, int] = {}
    for line in sorted(lines, key=lambda x: (x.ordered_at, x.id)):
        take = min(left, max(line.units, 0))
        out[line.id] = take
        left -= take
    return out


def line_state(*, cancelled: bool, units_open: int, fulfilled: int, ready: int) -> LineState:
    if cancelled or (units_open <= 0 and fulfilled <= 0):
        return LineState.CANCELLED
    if units_open <= 0:
        return LineState.FULFILLED
    if ready >= units_open:
        return LineState.READY
    return LineState.AWAITING_STOCK


def classify(state: LineState | None) -> Classification:
    """No preorder record means an ordinary line."""
    if state is None:
        return Classification.IN_STOCK
    if state == LineState.CANCELLED:
        return Classification.CANCELLED
    if state in (LineState.READY, LineState.FULFILLED):
        return Classification.PREORDER_READY
    return Classification.PREORDER_WAITING


# ------------------------------------------------------------------ dates and words


def dispatch_words(day: date | None) -> str:
    """ "Expected to dispatch by 7 November", as the customer sees it."""
    if day is None:
        return "Expected dispatch date to be confirmed"
    return f"Expected to dispatch by {day.day} {day:%B}"


def plan_name(day: date | None) -> str:
    """The selling plan's name: Shopify shows it in the cart, checkout, order and emails."""
    if day is None:
        return "Pre-order"
    return f"Pre-order: expected to dispatch by {day.day} {day:%B}"


def discount_ok(kind: str, value: float) -> bool:
    if kind == "NONE":
        return value == 0
    return kind == "PERCENTAGE" and 0 < value < 100
