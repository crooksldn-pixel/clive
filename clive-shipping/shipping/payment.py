"""Whether the order's own money allows a NEW label to be bought. The one place that decides.

Shopify's `Order.displayFinancialStatus` (Admin API 2026-10, enum OrderDisplayFinancialStatus,
checked against the schema 2026-10-07): AUTHORIZED, EXPIRED, PAID, PARTIALLY_PAID,
PARTIALLY_REFUNDED, PENDING, REFUNDED, VOIDED. Anything else, or nothing at all, is unknown and
blocks: postage is never bought on a guess about the customer's payment.

Only NEW purchases are gated. A label already bought stays (it is history, and evidence); if the
order's payment changes afterwards, a person is told, nothing is cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentState:
    status: str  # Shopify's value, or "" when Shopify gave none
    label: str  # what the merchant sees: "Paid", "Payment pending"
    allows_purchase: bool
    reason: str  # why a label can't be bought; "" when it can
    tone: str


# status: (label, allows a new label, why not)
POLICY: dict[str, tuple[str, bool, str]] = {
    "PAID": ("Paid", True, ""),
    # Some money went back, the rest is paid: not unpaid. What still ships was paid for.
    "PARTIALLY_REFUNDED": ("Partially refunded", True, ""),
    # Validated, not captured: a business decision CLIVE doesn't take on its own.
    "AUTHORIZED": (
        "Authorized — not captured",
        False,
        "The payment is authorized but not captured. Capture it in Shopify, then buy the label.",
    ),
    "PENDING": (
        "Payment pending",
        False,
        "The payment is still pending in Shopify. The label can be bought once it's paid.",
    ),
    "PARTIALLY_PAID": (
        "Partially paid",
        False,
        "Only part of the order is paid. Take the rest of the payment in Shopify first.",
    ),
    "REFUNDED": (
        "Refunded",
        False,
        "The order was refunded in full, so no label is bought for it.",
    ),
    "VOIDED": (
        "Payment voided",
        False,
        "The payment was voided, so no label is bought for it.",
    ),
    "EXPIRED": (
        "Payment expired",
        False,
        "The payment authorization expired before it was captured. Take payment again first.",
    ),
}

UNKNOWN = (
    "Payment status unknown",
    False,
    "Shopify didn't say whether this order is paid, so no label is bought until it does.",
)


def payment(status: str | None) -> PaymentState:
    """Shopify's financial status, read once, the same way everywhere."""
    raw = (status or "").strip().upper()
    label, allows, reason = POLICY.get(raw, UNKNOWN)
    tone = "success" if raw == "PAID" else "info" if allows else "critical"
    return PaymentState(status=raw, label=label, allows_purchase=allows, reason=reason, tone=tone)
