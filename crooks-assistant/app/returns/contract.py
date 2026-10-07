"""Returns, exchanges, replacements and resends: the contract, and why none of them runs yet.

§21 asks for the reviewed capability FOUNDATION for four changes the shop will want, and asks
plainly that unsafe live mutations are not rushed to tick a box. So this file is the part that
can be got right without a store to try it on:

* the REQUEST shapes, validated — an order, its lines, quantities that exist, a reason from
  Shopify's own list, whether to restock, whether to notify;
* what each change WOULD be, named: the Shopify mutation, the scopes it needs, the
  preconditions to re-read immediately before it, and the authoritative re-read that would
  prove it;
* one refusal, in the owner's words, naming the exact scope that is missing.

What it deliberately does NOT contain is a mutation. `returnCreate` on a fulfilled order is
indeed the straightforward candidate — and it is straightforward only when the app holds
`write_returns`, which this one has never been granted, and when there is a store to verify
against, which this environment does not have. A write staged against neither would be a
second mutation path proven by nothing. So `plan()` builds exactly what would be staged and
`stage()` refuses, by name, until the scope and the verification exist.

When they do, the work is: a `WriteSpec` in a new app/tools module with these preconditions and
this verification, and `available=True` here. Nothing in the application layer needs to change,
because nothing in the application layer knows about this file — it goes through the one action
engine.

Nothing registers the four as capability families any more: since DEC-066 returns and exchanges
go through CROOKS Returns, whose own families say what CLIVE can do, and the rows
app/families/returns.py registered from this file were retired. The contract is kept until it is
deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Shopify's own return reasons (ReturnReason enum). Named here so a request can be validated
# before it is ever sent, and so the tablet's picker and the model's vocabulary are the same.
REASONS = (
    "COLOR", "DEFECTIVE", "NOT_AS_DESCRIBED", "OTHER", "SIZE_TOO_LARGE",
    "SIZE_TOO_SMALL", "STYLE", "UNKNOWN", "UNWANTED", "WRONG_ITEM",
)

# The scopes each change needs, by name. This is the "exact scope required" §21 asks to be
# named, and it is what the owner is shown when he asks why a return is not offered.
SCOPE_RETURNS = "write_returns"
SCOPE_RETURNS_READ = "read_returns"
SCOPE_ORDER_EDITS = "write_order_edits"
SCOPE_DRAFT_ORDERS = "write_draft_orders"
SCOPE_FULFILMENT = "write_merchant_managed_fulfillment_orders"


class NotAvailable(RuntimeError):
    """Asked to stage a change whose backend support does not exist. Names what is missing."""

    def __init__(self, capability: str, missing: tuple[str, ...]) -> None:
        super().__init__(f"{capability} is not available yet: {', '.join(missing)}")
        self.capability = capability
        self.missing = tuple(missing)


class InvalidRequest(ValueError):
    """The request itself does not make sense — before any scope or store is involved."""


@dataclass(frozen=True)
class ReturnLine:
    """One line coming back. `fulfillment_line_item_id` is what Shopify's returnCreate takes,
    which is not the order's line id: a return is against what SHIPPED."""

    fulfillment_line_item_id: str
    quantity: int
    reason: str = "UNKNOWN"
    note: str = ""

    def validate(self, *, shipped: dict[str, int] | None = None) -> None:
        if not self.fulfillment_line_item_id:
            raise InvalidRequest("a return line needs the id of the line that shipped")
        if self.quantity <= 0:
            raise InvalidRequest("a return line needs a quantity of at least one")
        if self.reason not in REASONS:
            raise InvalidRequest(f"{self.reason!r} is not one of Shopify's return reasons")
        if shipped is not None:
            available = int(shipped.get(self.fulfillment_line_item_id, 0))
            if available <= 0:
                raise InvalidRequest("that line did not ship on this order")
            if self.quantity > available:
                raise InvalidRequest(f"only {available} of that line shipped; {self.quantity} cannot come back")


@dataclass(frozen=True)
class ReturnRequest:
    """What the owner means by "take these back"."""

    order_id: str
    lines: tuple[ReturnLine, ...] = ()
    notify_customer: bool = False
    restock: bool = True
    # An exchange is a return plus what goes out instead, by variant. Kept on the same request
    # because Shopify models it that way (returnCreate carries exchangeLineItems), and because
    # two request shapes for one gesture is how two implementations start.
    exchange_variants: tuple[tuple[str, int], ...] = ()

    def validate(self, *, order: dict[str, Any] | None = None) -> None:
        if not self.order_id:
            raise InvalidRequest("a return needs an order")
        if not self.lines:
            raise InvalidRequest("a return needs at least one line")
        shipped = _shipped_lines(order) if order is not None else None
        if order is not None and str(order.get("fulfillment") or "").upper() not in ("FULFILLED", "PARTIALLY_FULFILLED"):
            # The precondition that makes returnCreate the straightforward candidate: there is
            # nothing to return until something has shipped.
            raise InvalidRequest("nothing has shipped on that order, so there is nothing to return")
        seen: set[str] = set()
        for line in self.lines:
            line.validate(shipped=shipped)
            if line.fulfillment_line_item_id in seen:
                raise InvalidRequest("the same line is listed twice")
            seen.add(line.fulfillment_line_item_id)
        for variant, quantity in self.exchange_variants:
            if not variant or int(quantity) <= 0:
                raise InvalidRequest("an exchange line needs a variant and a quantity")

    @property
    def is_exchange(self) -> bool:
        return bool(self.exchange_variants)


@dataclass(frozen=True)
class ReviewedCapability:
    """One future change, described completely enough to be built and refused honestly."""

    key: str
    label: str
    what: str
    mutation: str                                  # the Shopify mutation that would do it
    scopes: tuple[str, ...]
    preconditions: tuple[str, ...]                 # re-read immediately before the write
    verification: str                              # the authoritative re-read that proves it
    # False until the scope is granted AND the write is written AND it is verified against a
    # store. Flipping this alone does nothing: `stage` refuses on `missing`.
    available: bool = False
    missing: tuple[str, ...] = ()
    risk: str = "AMBER"
    extra: dict[str, Any] = field(default_factory=dict)

    def refusal(self) -> str:
        """What the owner is told, naming the scope. One sentence, no apology, no guessing."""
        return (
            f"I cannot {self.what} yet: {', '.join(self.missing) or 'the change is not built'}. "
            f"It needs the {' and '.join(self.scopes)} scope on the app."
        )

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "what": self.what, "mutation": self.mutation,
            "scopes": list(self.scopes), "preconditions": list(self.preconditions),
            "verification": self.verification, "available": self.available,
            "missing": list(self.missing), "risk": self.risk,
        }


# The four. Each says what it would do, what it needs, and what would prove it — and each is
# unavailable, for the reason given.
_NOT_GRANTED = "the app has not been granted the scope"
_NOT_WRITTEN = "the reviewed mutation is not written"
_NOT_VERIFIED = "no store to verify the change against in this build"
# The read a return needs and the order read does not make yet. Named because it is the one
# item on these lists that is neither a scope nor a store: it is work in this repository, and
# a precondition ("the lines named actually shipped") cannot be checked without it.
MISSING_FULFILMENT_LINES = (
    "the order read does not include fulfilment line items yet "
    "(fulfillments { fulfillmentLineItems { id quantity } } in app/context/order.py)"
)

RETURN = ReviewedCapability(
    key="return_create", label="Taking an item back", what="start a return on an order",
    mutation="returnCreate",
    scopes=(SCOPE_RETURNS, SCOPE_RETURNS_READ),
    preconditions=(
        "the order still exists and is not cancelled",
        "the lines named actually shipped, in at least the quantity asked for",
        "no open return already covers those lines",
    ),
    verification="read the order's returns back and find one with the lines and quantities asked for",
    missing=(_NOT_GRANTED, _NOT_WRITTEN, _NOT_VERIFIED, MISSING_FULFILMENT_LINES),
)
EXCHANGE = ReviewedCapability(
    key="return_exchange", label="Swapping an item", what="take an item back and send another instead",
    mutation="returnCreate (with exchangeLineItems)",
    scopes=(SCOPE_RETURNS, SCOPE_ORDER_EDITS),
    preconditions=(
        "everything a return needs",
        "the variant going out exists and is in stock at the shop's location",
        "the price difference is calculated and shown before the gesture",
    ),
    verification="read the order back: a return for the lines, and the exchange line on the order",
    missing=(_NOT_GRANTED, _NOT_WRITTEN, _NOT_VERIFIED, MISSING_FULFILMENT_LINES),
    risk="RED",
)
REPLACEMENT = ReviewedCapability(
    key="replacement_item", label="Sending a replacement", what="send a replacement item at no charge",
    mutation="draftOrderCreate then draftOrderComplete (no payment)",
    scopes=(SCOPE_DRAFT_ORDERS,),
    preconditions=(
        "the original order exists and names the customer",
        "the variant exists and is in stock",
        "the replacement is linked to the original order by note and tag",
    ),
    verification="read the new order back and find the line, the customer and the link to the original",
    missing=(_NOT_GRANTED, _NOT_WRITTEN, _NOT_VERIFIED),
    risk="RED",
)
RESEND = ReviewedCapability(
    key="resend_shipment", label="Sending it again", what="ship an order again after a lost parcel",
    mutation="fulfillmentCreate on the remaining fulfilment order",
    scopes=(SCOPE_FULFILMENT,),
    preconditions=(
        "the order exists and its first shipment is recorded as lost or returned to sender",
        "there is a fulfilment order left to fulfil, or a replacement was created for it",
        "stock is there to send",
    ),
    verification="read the order's fulfillments back and find the second one, with its tracking",
    missing=(_NOT_GRANTED, _NOT_WRITTEN, _NOT_VERIFIED),
    risk="RED",
)

CAPABILITIES: dict[str, ReviewedCapability] = {c.key: c for c in (RETURN, EXCHANGE, REPLACEMENT, RESEND)}


def get(key: str) -> ReviewedCapability | None:
    return CAPABILITIES.get(key)


def plan(capability: str, request: ReturnRequest, *, order: dict[str, Any] | None = None) -> dict[str, Any]:
    """What WOULD be staged: the exact server-side arguments, validated, with nothing sent.

    This is the useful half of a foundation — it is testable now, it is what the future
    `WriteSpec` will build, and building it here proves the request shapes hold together
    without any mutation existing. It does not stage anything: staging is `stage()`, and
    `stage()` refuses.
    """
    spec = CAPABILITIES.get(capability)
    if spec is None:
        raise InvalidRequest(f"there is no reviewed capability called {capability!r}")
    request.validate(order=order)
    args: dict[str, Any] = {
        "orderId": request.order_id,
        "returnLineItems": [
            {"fulfillmentLineItemId": line.fulfillment_line_item_id, "quantity": int(line.quantity),
             "returnReason": line.reason, **({"returnReasonNote": line.note[:300]} if line.note else {})}
            for line in request.lines
        ],
        "notifyCustomer": bool(request.notify_customer),
    }
    if request.is_exchange:
        args["exchangeLineItems"] = [{"variantId": variant, "quantity": int(quantity)}
                                     for variant, quantity in request.exchange_variants]
    return {
        "capability": spec.key, "mutation": spec.mutation, "arguments": args,
        "scopes": list(spec.scopes), "preconditions": list(spec.preconditions),
        "verification": spec.verification, "available": spec.available,
    }


def stage(capability: str, request: ReturnRequest, *, order: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refuse, by name. The one function a caller would reach for to make a change happen.

    It is here so that the refusal is in the same place the future implementation will be, and
    so that "returns are not available" is a fact about one function rather than an absence
    somebody could accidentally fill in from the tablet. When it does become possible it will
    not execute anything either: it will PROPOSE, through app/actions/engine.py, and the
    gesture and the verification will be the engine's as they are for every other change.
    """
    spec = CAPABILITIES.get(capability)
    if spec is None:
        raise InvalidRequest(f"there is no reviewed capability called {capability!r}")
    plan(capability, request, order=order)          # validate first: a bad request is a bad request
    if not spec.available or spec.missing:
        raise NotAvailable(spec.label, spec.missing or ("the change is not built",))
    raise NotAvailable(spec.label, ("no reviewed mutation is registered for it",))


def words() -> list[str]:
    """The four, as lines the owner or the model can read. Each names its scope."""
    return [f"- {c.label}: not available — {c.refusal()}" for c in CAPABILITIES.values()]


def _shipped_lines(order: dict[str, Any]) -> dict[str, int] | None:
    """What actually shipped, by fulfilment line id — or None when this build cannot know.

    The order read (`app/context/order.py`) asks for a fulfilment's id, status, date and
    tracking; it does NOT ask for its LINE ITEMS, which is what a return is against. So for an
    order as the Mac reads it today the answer is unknown, and unknown must not be reported as
    "nothing shipped": that would refuse every honest return for the wrong reason. It comes
    back None, the quantity check is skipped, and the missing read is named in
    `MISSING_FULFILMENT_LINES` — one of the things `stage` refuses on.
    """
    out: dict[str, int] = {}
    seen_lines = False
    for fulfillment in order.get("fulfillments") or []:
        if not isinstance(fulfillment, dict):
            continue
        lines = fulfillment.get("line_items") or fulfillment.get("lines") or []
        for line in lines:
            if not isinstance(line, dict):
                continue
            seen_lines = True
            ref = str(line.get("fulfillment_line_item_id") or line.get("id") or "")
            if ref:
                out[ref] = out.get(ref, 0) + int(line.get("quantity") or 0)
    return out if seen_lines else None
