"""Whether a refund has landed, in Shopify's own words and nobody else's.

George, 2 October: "Clive cannot confirm a refund has landed (but I do confirm refunds through
Clive's work)." A refund in Shopify is a record, and the money moving is a TRANSACTION under it,
which the payment provider answers: succeeded, pending, failed. This reads those transactions —
status, gateway, the card they went back to, the amount, when Shopify processed them — and says
them plainly:

    "Refund of £45.00 to Visa ending 4242 succeeded on Tue 1 Oct at 14:02."
    "Refund of £45.00 to Visa ending 4242 is pending at the payment provider."
    "Refund of £45.00 to Visa ending 4242 failed: the card was declined."

Nothing is inferred past what Shopify reports. What it means for the customer is the provider's
answer, and — only for a refund that succeeded — the line the shop itself publishes about how
long a refund takes to land (kb/returns-policy.md), quoted as it is and named as the shop's
policy, never as a promise about this one.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger("crooks.customers.payments")

SHOP_TZ = ZoneInfo("Europe/London")

# Shopify's OrderTransactionStatus, as one of four words.
STATES = {
    "SUCCESS": "succeeded", "PENDING": "pending", "AWAITING_RESPONSE": "pending",
    "FAILURE": "failed", "ERROR": "failed", "UNKNOWN": "unknown",
}
# Shopify's OrderTransactionErrorCode, as a reason a person reads. Anything not here is said
# in Shopify's own words, its code with the underscores taken out.
REASONS = {
    "CARD_DECLINED": "the card was declined", "EXPIRED_CARD": "the card has expired",
    "CALL_ISSUER": "the card's bank asked to be called", "PICK_UP_CARD": "the card's bank refused it",
    "PROCESSING_ERROR": "the payment provider had a processing error", "GENERIC_ERROR": "the payment provider refused it",
    "INVALID_AMOUNT": "the amount was refused", "PAYMENT_METHOD_UNAVAILABLE": "the payment method is not available any more",
    "UNSUPPORTED_FEATURE": "the payment provider does not support it", "CONFIG_ERROR": "the payment provider is not set up for it",
}
_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}
# The shop's own line about when an approved refund lands (kb/returns-policy.md).
POLICY_FILE = "returns-policy.md"
POLICY_PHRASE = "An approved refund lands"


def money(amount: float | None, currency: str) -> str:
    if amount is None:
        return "an amount Shopify did not give"
    symbol = _SYMBOLS.get(str(currency or "").upper())
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency}"


def when_words(stamp: Any, tz: ZoneInfo = SHOP_TZ) -> str:
    """"Tue 1 Oct at 14:02", in the shop's own time."""
    try:
        moment = datetime.fromisoformat(str(stamp or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    local = moment.astimezone(tz)
    return f"{local.strftime('%a')} {local.day} {local.strftime('%b')} at {local.strftime('%H:%M')}"


def _amount(node: Any) -> tuple[float | None, str]:
    shop = ((node or {}).get("shopMoney") or node or {}) if isinstance(node, dict) else {}
    try:
        return round(float(shop.get("amount")), 2), str(shop.get("currencyCode") or "GBP")
    except (TypeError, ValueError):
        return None, str(shop.get("currencyCode") or "GBP")


def _transactions(refund: dict[str, Any]) -> list[dict[str, Any]]:
    raw = refund.get("transactions")
    if isinstance(raw, dict):
        raw = [(e or {}).get("node") for e in raw.get("edges") or []]
    return [t for t in raw or [] if isinstance(t, dict)]


def paid_to(transaction: dict[str, Any]) -> str:
    """Where the money went back: "Visa ending 4242", or the gateway's own name."""
    details = transaction.get("paymentDetails") or {}
    company = str(details.get("company") or "").strip()
    digits = re.sub(r"\D", "", str(details.get("number") or ""))[-4:]
    if company and digits:
        return f"{company} ending {digits}"
    if company:
        return company
    gateway = str(transaction.get("formattedGateway") or transaction.get("gateway") or "").strip()
    return gateway.replace("_", " ") if gateway else ""


def refund_state(refund: dict[str, Any], *, tz: ZoneInfo = SHOP_TZ, policy: str = "") -> dict[str, Any]:
    """One refund, as the payment provider has answered it so far."""
    total, currency = _amount(refund.get("totalRefundedSet"))
    moves = [t for t in _transactions(refund) if str(t.get("kind") or "REFUND").upper() in ("REFUND", "VOID")]
    if not moves:
        stamp = refund.get("createdAt")
        return {
            "state": "recorded", "amount": money(total, currency), "to": "", "processed_at": stamp, "error": "",
            "landed": (f"Refund of {money(total, currency)} recorded on {when_words(stamp, tz)}; Shopify shows no payment "
                       "sent back for it."),
            "means": "Shopify shows no money moving for this refund, so nothing is on its way back to the customer from it.",
        }
    words = [STATES.get(str(t.get("status") or "").upper(), "unknown") for t in moves]
    state = "failed" if "failed" in words else "pending" if "pending" in words else "unknown" if "unknown" in words else "succeeded"
    amounts = [_amount(t.get("amountSet")) for t in moves]
    summed = [a for a, _c in amounts if a is not None]
    amount = round(sum(summed), 2) if summed else total
    currency = next((c for a, c in amounts if a is not None), currency)
    to = ", ".join(dict.fromkeys(p for p in (paid_to(t) for t in moves) if p))
    latest = max((str(t.get("processedAt") or t.get("createdAt") or "") for t in moves), default="")
    failed = next((t for t in moves if STATES.get(str(t.get("status") or "").upper()) == "failed"), None)
    code = str((failed or {}).get("errorCode") or "").upper()
    reason = REASONS.get(code) or (code.replace("_", " ").lower() if code else "Shopify gives no reason")
    head = f"Refund of {money(amount, currency)}" + (f" to {to}" if to else "")
    at = when_words(latest, tz)
    landed = {
        "succeeded": f"{head} succeeded" + (f" on {at}" if at else "") + ".",
        "pending": f"{head} is pending at the payment provider" + (f" (since {at})" if at else "") + ".",
        "failed": f"{head} failed: {reason}.",
        "unknown": f"{head}: Shopify reports its state as unknown.",
    }[state]
    means = {
        "succeeded": (f"Shopify shows the payment provider accepted it back to {to or 'the original payment'}"
                      + (f" on {at}" if at else "") + "." + (f" The shop's policy: {policy}" if policy else "")),
        "pending": "Shopify is still waiting on the payment provider; it has not confirmed the money went back yet.",
        "failed": f"The money has not gone back: the provider refused it ({reason}).",
        "unknown": "Shopify does not know yet whether the money went back.",
    }[state]
    return {"state": state, "amount": money(amount, currency), "to": to, "processed_at": latest or None,
            "error": reason if state == "failed" else "", "landed": landed, "means": means}


_policy_cache: dict[str, tuple[float, str]] = {}


def policy_line(kb_dir: Path | str | None = None) -> str:
    """The shop's own sentence about when a refund lands, as it is in the knowledge base."""
    if kb_dir is None:
        try:
            from config.settings import get_settings

            kb_dir = get_settings().kb_dir
        except Exception:  # noqa: BLE001 — no settings, no policy line; the refund state stands
            return ""
    path = Path(kb_dir) / POLICY_FILE
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    held = _policy_cache.get(str(path))
    if held and held[0] == stamp:
        return held[1]
    line = ""
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            text = raw.strip().lstrip("-").strip()
            if text.startswith(POLICY_PHRASE):
                line = text[:300]
                break
    except OSError:
        return ""
    _policy_cache[str(path)] = (stamp, line)
    return line
