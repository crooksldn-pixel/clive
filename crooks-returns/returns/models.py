"""The shapes everything else agrees on. Money is always integer pence."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def to_pence(amount: str | float | int | Decimal | None) -> int:
    if amount in (None, ""):
        return 0
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_amount(pence: int) -> str:
    return f"{Decimal(pence) / 100:.2f}"


def gbp(pence: int) -> str:
    sign = "-" if pence < 0 else ""
    return f"{sign}£{Decimal(abs(pence)) / 100:.2f}"


class Reason(StrEnum):
    too_small = "too_small"
    too_big = "too_big"
    changed_mind = "changed_mind"
    not_as_described = "not_as_described"
    faulty = "faulty"
    wrong_item = "wrong_item"


REASON_LABELS = {
    Reason.too_small: "Too small",
    Reason.too_big: "Too big",
    Reason.changed_mind: "Changed my mind",
    Reason.not_as_described: "Not as described or pictured",
    Reason.faulty: "Faulty or damaged",
    Reason.wrong_item: "Wrong item sent",
}

# Our fault: free postage, a full refund, the 30-day Consumer Rights Act window.
SELLER_FAULT = {Reason.faulty, Reason.wrong_item, Reason.not_as_described}
FIT = {Reason.too_small, Reason.too_big}


class Resolution(StrEnum):
    exchange = "exchange"
    store_credit = "store_credit"
    refund = "refund"


class Postage(StrEnum):
    # What the customer chose in the portal.
    free_label = "free_label"  # we pay for the Royal Mail label
    paid_label = "paid_label"  # Royal Mail label at cost, taken off the refund
    self_ship = "self_ship"  # customer sends it their own way


class PostageMode(StrEnum):
    # What staff or CLIVE decided at approval. Approving and labelling are separate decisions.
    label_now = "label_now"
    self_ship = "self_ship"
    no_return = "no_return"
    label_later = "label_later"


class Status(StrEnum):
    requested = "requested"
    awaiting_label = "awaiting_label"
    awaiting_shipment = "awaiting_shipment"
    in_transit = "in_transit"
    received = "received"
    completed = "completed"
    declined = "declined"
    cancelled = "cancelled"


OPEN_STATUSES = {
    Status.requested,
    Status.awaiting_label,
    Status.awaiting_shipment,
    Status.in_transit,
    Status.received,
}


# --------------------------------------------------------------- the order, as the portal sees it


class Variant(BaseModel):
    id: str
    title: str
    sku: str | None = None
    price_pence: int
    available: bool


class OrderLine(BaseModel):
    fulfillment_line_item_id: str
    line_item_id: str
    title: str
    variant_title: str | None = None
    sku: str | None = None
    image_url: str | None = None
    variant_id: str | None = None
    variant_price_pence: int | None = None
    product_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    ordered_qty: int
    returnable_qty: int
    unit_paid_pence: int
    siblings: list[Variant] = Field(default_factory=list)


class Order(BaseModel):
    id: str
    name: str
    created_at: datetime
    email: str | None = None
    phone: str | None = None
    currency: str = "GBP"
    customer_id: str | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    shipping_zip: str | None = None
    billing_zip: str | None = None
    shipping_phone: str | None = None
    billing_phone: str | None = None
    shipping_address: dict[str, Any] = Field(default_factory=dict)
    # Delivery charged on the order, refunded when everything comes back for a refund.
    shipping_pence: int = 0
    fulfilled_at: datetime | None = None
    delivered_at: datetime | None = None
    lines: list[OrderLine] = Field(default_factory=list)


class Transaction(BaseModel):
    id: str
    kind: str
    status: str
    gateway: str | None = None
    amount_pence: int


class OrderMoney(BaseModel):
    transactions: list[Transaction]
    shipping_pence: int


# --------------------------------------------------------------------------------- the return


class Selection(BaseModel):
    fulfillment_line_item_id: str
    quantity: int = Field(ge=1)
    reason: Reason
    note: str = Field(default="", max_length=300)


class ReturnLine(BaseModel):
    fulfillment_line_item_id: str
    line_item_id: str
    title: str
    variant_title: str | None = None
    sku: str | None = None
    variant_id: str | None = None
    quantity: int
    reason: Reason
    note: str = ""
    unit_paid_pence: int
    # Exchange only: what this line becomes.
    exchange_variant_id: str | None = None
    exchange_variant_title: str | None = None
    exchange_sku: str | None = None
    exchange_direction: str | None = None  # size_up, size_down, same, other


class Money(BaseModel):
    items_pence: int = 0
    fee_pence: int = 0
    bonus_pence: int = 0
    shipping_refund_pence: int = 0
    refund_pence: int = 0
    credit_pence: int = 0


class PostageState(BaseModel):
    chosen: Postage
    mode: PostageMode | None = None
    paid_by: str = "crooks"  # crooks | customer
    carrier: str | None = None
    tracking: str | None = None
    tracking_url: str | None = None
    label_file_id: str | None = None
    label_ref: str | None = None
    label_due_at: datetime | None = None


class ShopifyRefs(BaseModel):
    return_id: str | None = None
    return_name: str | None = None
    reverse_fulfillment_order_ids: list[str] = Field(default_factory=list)
    # fulfillment line item id -> return line item id
    return_line_item_ids: dict[str, str] = Field(default_factory=dict)
    # fulfillment line item id -> reverse fulfillment order line item id
    rfo_line_item_ids: dict[str, str] = Field(default_factory=dict)
    exchange_line_item_ids: list[str] = Field(default_factory=list)
    reverse_delivery_id: str | None = None
    # returnProcess has run: money moved and any exchange released to ship.
    processed: bool = False
    refund_ids: list[str] = Field(default_factory=list)
    store_credit_transaction_id: str | None = None


class Event(BaseModel):
    at: datetime
    type: str
    actor: str
    detail: dict[str, Any] = Field(default_factory=dict)
    # True once the outcome has been read back from Shopify (or the carrier) and matched.
    verified: bool = False


class Return(BaseModel):
    id: str
    order_id: str
    order_name: str
    customer_id: str | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    currency: str = "GBP"
    created_at: datetime
    updated_at: datetime
    status: Status
    resolution: Resolution
    lines: list[ReturnLine]
    postage: PostageState
    money: Money
    offers_shown: list[str] = Field(default_factory=list)
    inspection: dict[str, Any] | None = None
    decline_reason: str | None = None
    last_error: str | None = None
    shopify: ShopifyRefs = Field(default_factory=ShopifyRefs)
    timeline: list[Event] = Field(default_factory=list)

    @property
    def seller_fault(self) -> bool:
        return any(line.reason in SELLER_FAULT for line in self.lines)
