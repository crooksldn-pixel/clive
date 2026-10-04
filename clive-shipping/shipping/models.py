"""The shapes CLIVE Shipping agrees on. Every record carries its shop: tenancy from day one.

A Shipment is one Shopify fulfillment order going abroad. Its status says where it is in the
journey; the money-moving work itself lives in ProviderOp rows (the purchase ledger), so a
shipment can always say whether money may have moved, even mid-flight.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from shipping.money import Money


class ShipmentStatus(StrEnum):
    discovered = "discovered"  # found in Shopify, not yet checked
    needs_attention = "needs_attention"  # one or more questions only a person can answer
    ready = "ready"  # everything known: a label can be bought
    purchasing = "purchasing"  # a buy is in flight (see its ProviderOp)
    reconciliation_required = "reconciliation_required"  # payment outcome unknown: checking
    label_purchased = "label_purchased"  # paid and the label exists; Shopify not yet updated
    fulfillment_failed = "fulfillment_failed"  # label bought, Shopify refused the fulfilment
    fulfilled = "fulfilled"  # Shopify shows the fulfilment with our tracking (read back)
    in_transit = "in_transit"
    delivered = "delivered"
    void_requested = "void_requested"  # merchant asked to cancel the label at the provider
    voided = "voided"
    void_rejected = "void_rejected"
    cancelled = "cancelled"  # order cancelled or fulfilled elsewhere before a label was bought


# Where money may have moved for this shipment.
PAID_STATUSES = frozenset(
    {
        ShipmentStatus.label_purchased,
        ShipmentStatus.fulfillment_failed,
        ShipmentStatus.fulfilled,
        ShipmentStatus.in_transit,
        ShipmentStatus.delivered,
        ShipmentStatus.void_requested,
        ShipmentStatus.voided,
        ShipmentStatus.void_rejected,
    }
)


class OpState(StrEnum):
    """One attempt to buy a label: the money boundary, step by step."""

    authorised = "authorised"  # the person (or CLIVE with authority) said buy; nothing sent
    order_created = "order_created"  # provider order exists, unpaid: no money has moved
    pay_sent = "pay_sent"  # the pay request is being sent: money may move from here
    pay_unknown = "pay_unknown"  # we don't know if it was charged: reconcile, never re-pay
    paid = "paid"  # the provider confirmed the charge (reply or read-back)
    done = "done"  # label and documents stored
    failed = "failed"  # definitely not charged
    abandoned = "abandoned"  # outcome was unknown; confirmed unpaid twice; never paid


OPEN_OP_STATES = frozenset(
    {OpState.authorised, OpState.order_created, OpState.pay_sent, OpState.pay_unknown, OpState.paid}
)


class Address(BaseModel):
    name: str = ""
    company: str = ""
    line1: str = ""
    line2: str = ""
    city: str = ""
    region: str = ""
    postcode: str = ""
    country: str = ""  # ISO 3166-1 alpha-2
    phone: str = ""
    email: str = ""


class CustomsLine(BaseModel):
    fulfillment_order_line_item_id: str
    variant_id: str | None = None
    inventory_item_id: str | None = None
    product_id: str | None = None
    product_type: str = ""
    variant_title: str = ""
    sku: str | None = None
    title: str
    customs_description: str = ""
    quantity: int
    unit_value: Money
    unit_weight_g: int | None = None
    hs_code: str | None = None
    origin_country: str | None = None
    # Where the facts came from: "shopify", "knowledge" or "merchant". Suggestions are never
    # stored here until a person confirms them.
    facts_source: str = "shopify"


class PackagePlan(BaseModel):
    preset_id: str | None = None
    name: str = ""
    length_mm: int
    width_mm: int
    height_mm: int
    empty_weight_g: int
    items_weight_g: int
    source: str = "default"  # default | learned | merchant

    @property
    def total_weight_g(self) -> int:
        return self.empty_weight_g + self.items_weight_g


class PackagePreset(BaseModel):
    """A real package the merchant entered once (never invented)."""

    id: str
    name: str
    length_mm: int
    width_mm: int
    height_mm: int
    empty_weight_g: int
    created_by: str = ""


class DutiesPolicy(BaseModel):
    """Who pays import charges. A merchant setting, not a constant: DAP today, IOSS/DDP later
    without changing the shipment model."""

    mode: str = "DAP"  # DAP: the recipient pays any import VAT/duty/fees on arrival. DDP: prepaid.
    ioss_number: str | None = None  # EU Import One-Stop Shop number, when the merchant has one


class DutiesTerms(BaseModel):
    """What applies to this shipment, in words a merchant (and customer) can rely on."""

    incoterm: str  # DAP | DDP
    ioss_number: str | None = None  # sent to the carrier only when it applies
    recipient_may_pay: bool
    summary: str  # one honest sentence for the preview


class ShopConfig(BaseModel):
    shop: str
    origin: Address | None = None  # from the Shopify location; confirmed in Setup
    origin_location_id: str | None = None
    label_format: str = "4x6"  # 100x150 mm thermal by default; "a4" for desk printers
    notify_customer: bool = True  # Shopify's shipping email with tracking
    duties: DutiesPolicy = Field(default_factory=DutiesPolicy)
    packages: list[PackagePreset] = Field(default_factory=list)
    default_package_id: str | None = None


class Quote(BaseModel):
    provider: str
    carrier: str
    service_code: str
    service_name: str
    amount: Money
    est_days_min: int | None = None
    est_days_max: int | None = None
    printer_required: bool = True
    generated_at: datetime


class Label(BaseModel):
    provider: str
    provider_ref: str  # the provider's order reference (Parcel2Go: p2g:order:line:hash)
    carrier: str
    service_name: str
    amount: Money
    tracking_number: str | None = None
    tracking_url: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)  # kind -> artifact id
    purchased_at: datetime


class Event(BaseModel):
    at: datetime
    type: str
    actor: str
    detail: dict[str, Any] = Field(default_factory=dict)
    verified: bool = False


class Question(BaseModel):
    """One thing only a person can answer, asked once and remembered."""

    kind: str  # customs | origin | weight | package | no_rates | address
    subject: str  # e.g. the inventory item id or "address"
    text: str
    suggestion: str | None = None
    choices: list[str] = Field(default_factory=list)


class Shipment(BaseModel):
    id: str
    shop: str
    order_id: str
    order_name: str
    fulfillment_order_id: str
    destination: Address
    status: ShipmentStatus
    currency: str = "GBP"
    lines: list[CustomsLine] = Field(default_factory=list)
    package: PackagePlan | None = None
    quote: Quote | None = None
    label: Label | None = None
    questions: list[Question] = Field(default_factory=list)
    duties: DutiesTerms | None = None
    # Things a person should know that don't block anything (e.g. "order edited after the
    # label was bought").
    alerts: list[str] = Field(default_factory=list)
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
    timeline: list[Event] = Field(default_factory=list)

    @property
    def money_may_have_moved(self) -> bool:
        return self.status in PAID_STATUSES or self.status in (
            ShipmentStatus.purchasing,
            ShipmentStatus.reconciliation_required,
        )


class ProviderOp(BaseModel):
    id: str
    shop: str
    shipment_id: str
    kind: str = "buy_label"
    idempotency_key: str
    basis: str
    actor: str
    amount: Money
    state: OpState
    provider_ref: str | None = None
    unpaid_reads: list[datetime] = Field(default_factory=list)
    pay_sent_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
