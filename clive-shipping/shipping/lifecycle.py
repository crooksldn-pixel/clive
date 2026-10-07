"""Where an order is in its journey, for the Shipping tabs and for CLIVE. The one place that says.

Derived every time from the shipment's own facts, never stored, so it can't disagree with them:

  1. Not bought, and anything stops it (payment, a missing detail, no service...) → attention
  2. Not bought, and ready: payment allows it, a service is chosen               → ready
  3. Bought, and Shopify's carrier tracking says delivered                        → delivered
  4. Bought, and the carrier has it (moving, or a carrier problem)                → in_transit
  5. Bought, and the label has printed (PhysicalPrinting.summary)                 → printed
  6. Otherwise bought                                                             → bought

A person must act (a purchase to reconcile, a Shopify update to retry, a cancellation) →
attention. Cancelled orders and cancelled labels are "closed", shown only under All.

"Printed" means PrintNode reported the job done, or the label was opened in the print view (as
Shopify counts a printed label). A job still printing, failed, uncertain or never confirmed
stays under Labels bought with its own badge: a page that may not exist is never called
printed.
"""

from __future__ import annotations

from typing import Any

from shipping.models import Shipment
from shipping.models import ShipmentStatus as S
from shipping.payment import payment
from shipping.tracking import MOVING

STAGES = ("attention", "ready", "bought", "printed", "in_transit", "delivered")
TITLES = {
    "attention": "Needs attention",
    "ready": "Ready to ship",
    "bought": "Labels bought",
    "printed": "Printed",
    "in_transit": "In transit",
    "delivered": "Delivered",
    "closed": "Closed",
}

NOT_BOUGHT = (S.discovered, S.needs_attention, S.ready)
NEEDS_A_PERSON = (
    S.purchasing,
    S.reconciliation_required,
    S.fulfillment_failed,
    S.void_requested,
    S.void_rejected,
)
CLOSED = (S.cancelled, S.voided)


def stage(s: Shipment, print_summary: dict[str, Any] | None) -> str:
    if s.status in CLOSED:
        return "closed"
    if s.status in NOT_BOUGHT:
        ready = (
            s.status == S.ready
            and s.quote is not None
            and not s.questions
            and payment(s.payment_status).allows_purchase
        )
        return "ready" if ready else "attention"
    if s.status in NEEDS_A_PERSON or s.label is None:
        return "attention"
    carrier = s.tracking.stage if s.tracking else "unknown"
    if carrier == "delivered":
        return "delivered"
    if carrier == "cancelled":
        return "attention"  # the Shopify fulfilment was cancelled: a person decides
    if carrier in MOVING:
        return "in_transit"
    if print_summary and print_summary.get("state") == "printed":
        return "printed"
    return "bought"


def may_bulk_buy(stage_name: str) -> bool:
    return stage_name == "ready"


def may_bulk_first_print(stage_name: str, print_summary: dict[str, Any] | None) -> bool:
    """Only labels not printed (or whose prints all failed), and not already with the carrier."""
    return stage_name == "bought" and bool(print_summary and print_summary["first_print_available"])
