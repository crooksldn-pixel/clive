"""Whether a refund has landed, in Shopify's own words and nobody else's.

George, 2 October: "Clive cannot confirm a refund has landed (but I do confirm refunds through
Clive's work)." A refund in Shopify is a record, and the money moving is a TRANSACTION under it,
which the payment provider answers: succeeded, pending, failed. This reads those transactions —
status, gateway, the card they went back to, the amount, when Shopify processed them — and says
them plainly:

    "Refund of £45.00 to Visa ending 4242 succeeded on Tue 1 Oct at 14:02."
    "Refund of £45.00 to Visa ending 4242 is pending at the payment provider."
    "Refund of £45.00 to Visa ending 4242 failed: the card was declined."

The card's brand and its last four digits are for the order card on the glass and nowhere else:
`landed_card` carries them, and the order card is the one thing that reads it. Everything else —
`landed`, `means`, `to`, which the model reads and which can therefore reach a log — says "the
card it was paid with" instead (app/context/order.py `model_view` and app/support/redact.py
drop `CARD_ONLY`).

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

# Shopify's OrderTransactionStatus, as one of four words. A refund with transactions in more than
# one of them, one of which succeeded, is "partly": each part is said for what it is (`_partly`).
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
# A card, said without its brand or its digits.
CARD_SAID = "the card it was paid with"
# The keys that carry a card's brand and last four: the order card's alone.
CARD_ONLY = ("landed_card", "paid_to_card")
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


def card_of(transaction: dict[str, Any]) -> str:
    """The card the money went back to, for the order card only: "Visa ending 4242"; "" when
    Shopify gave no card."""
    details = transaction.get("paymentDetails") or {}
    company = str(details.get("company") or "").strip()
    digits = re.sub(r"\D", "", str(details.get("number") or ""))[-4:]
    if company and digits:
        return f"{company} ending {digits}"
    return company


def paid_to(transaction: dict[str, Any], *, card: bool = False) -> str:
    """Where the money went back: the gateway's own name, or a card — "the card it was paid
    with", or with `card` (the order card's own words) "Visa ending 4242"."""
    held = card_of(transaction)
    if held:
        return held if card else CARD_SAID
    gateway = str(transaction.get("formattedGateway") or transaction.get("gateway") or "").strip()
    return gateway.replace("_", " ") if gateway else ""


def refund_state(refund: dict[str, Any], *, tz: ZoneInfo = SHOP_TZ, policy: str = "") -> dict[str, Any]:
    """One refund, as the payment provider has answered it so far."""
    total, currency = _amount(refund.get("totalRefundedSet"))
    moves = [t for t in _transactions(refund) if str(t.get("kind") or "REFUND").upper() in ("REFUND", "VOID")]
    if not moves:
        stamp = refund.get("createdAt")
        landed = (f"Refund of {money(total, currency)} recorded on {when_words(stamp, tz)}; Shopify shows no payment "
                  "sent back for it.")
        return {
            "state": "recorded", "amount": money(total, currency), "to": "", "processed_at": stamp, "error": "",
            "landed": landed, "landed_card": landed, "paid_to_card": "",
            "means": "Shopify shows no money moving for this refund, so nothing is on its way back to the customer from it.",
        }
    words = [STATES.get(str(t.get("status") or "").upper(), "unknown") for t in moves]
    if "succeeded" in words and len(set(words)) > 1:
        return _partly(moves, words, total, currency, tz, policy)
    state = "failed" if "failed" in words else "pending" if "pending" in words else "unknown" if "unknown" in words else "succeeded"
    amounts = [_amount(t.get("amountSet")) for t in moves]
    summed = [a for a, _c in amounts if a is not None]
    amount = round(sum(summed), 2) if summed else total
    currency = next((c for a, c in amounts if a is not None), currency)
    to = ", ".join(dict.fromkeys(p for p in (paid_to(t) for t in moves) if p))
    to_card = ", ".join(dict.fromkeys(p for p in (paid_to(t, card=True) for t in moves) if p))
    latest = max((str(t.get("processedAt") or t.get("createdAt") or "") for t in moves), default="")
    reason = _reason(moves)
    at = when_words(latest, tz)

    def said(where: str) -> str:
        head = f"Refund of {money(amount, currency)}" + (f" to {where}" if where else "")
        return {
            "succeeded": f"{head} succeeded" + (f" on {at}" if at else "") + ".",
            "pending": f"{head} is pending at the payment provider" + (f" (since {at})" if at else "") + ".",
            "failed": f"{head} failed: {reason}.",
            "unknown": f"{head}: Shopify reports its state as unknown.",
        }[state]

    landed = said(to)
    means = {
        "succeeded": (f"Shopify shows the payment provider accepted it back to {to or 'the original payment'}"
                      + (f" on {at}" if at else "") + "." + (f" The shop's policy: {policy}" if policy else "")),
        "pending": "Shopify is still waiting on the payment provider; it has not confirmed the money went back yet.",
        "failed": f"The money has not gone back: the provider refused it ({reason}).",
        "unknown": "Shopify does not know yet whether the money went back.",
    }[state]
    return {"state": state, "amount": money(amount, currency), "to": to, "processed_at": latest or None,
            "error": reason if state == "failed" else "", "landed": landed, "means": means,
            # The order card's own: the same sentence with the card's brand and last four.
            "landed_card": said(to_card), "paid_to_card": to_card}


def _reason(moves: list[dict[str, Any]]) -> str:
    failed = next((t for t in moves if STATES.get(str(t.get("status") or "").upper()) == "failed"), None)
    code = str((failed or {}).get("errorCode") or "").upper()
    return REASONS.get(code) or (code.replace("_", " ").lower() if code else "Shopify gives no reason")


def _partly(moves: list[dict[str, Any]], words: list[str], total: float | None, currency: str, tz: ZoneInfo,
            policy: str) -> dict[str, Any]:
    """A refund part of which went back and part of which did not: each part said for what it is,
    what succeeded first — never the whole called failed, nor the whole called landed."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for move, word in zip(moves, words, strict=True):
        groups.setdefault(word, []).append(move)
    reason = _reason(moves)

    def summed(group: list[dict[str, Any]]) -> tuple[float | None, str]:
        amounts = [_amount(t.get("amountSet")) for t in group]
        values = [a for a, _c in amounts if a is not None]
        return (round(sum(values), 2) if values else None), next((c for a, c in amounts if a is not None), currency)

    def part(word: str, group: list[dict[str, Any]], card: bool) -> str:
        amount, cur = summed(group)
        where = ", ".join(dict.fromkeys(p for p in (paid_to(t, card=card) for t in group) if p))
        head = money(amount, cur) + (f" to {where}" if where else "")
        at = when_words(max((str(t.get("processedAt") or t.get("createdAt") or "") for t in group), default=""), tz)
        return {"succeeded": f"{head} succeeded" + (f" on {at}" if at else ""),
                "pending": f"{head} is pending at the payment provider",
                "failed": f"{head} failed: {reason}",
                "unknown": f"{head}: Shopify reports its state as unknown"}[word]

    order = [w for w in ("succeeded", "pending", "failed", "unknown") if w in groups]
    landed = "Refund: " + "; ".join(part(w, groups[w], False) for w in order) + "."
    landed_card = "Refund: " + "; ".join(part(w, groups[w], True) for w in order) + "."
    went, cur = summed(groups["succeeded"])
    means = [f"Part of it has gone back: {money(went, cur)} succeeded."]
    if "failed" in groups:
        means.append(f"{money(*summed(groups['failed']))} has not gone back: the provider refused it ({reason}).")
    if "pending" in groups:
        means.append(f"{money(*summed(groups['pending']))} is still with the payment provider.")
    if "unknown" in groups:
        means.append(f"Shopify does not know yet whether {money(*summed(groups['unknown']))} went back.")
    if policy:
        means.append(f"The shop's policy: {policy}")
    latest = max((str(t.get("processedAt") or t.get("createdAt") or "") for t in moves), default="")
    return {"state": "partly", "amount": money(total, currency), "succeeded": money(went, cur),
            "to": ", ".join(dict.fromkeys(p for p in (paid_to(t) for t in moves) if p)), "processed_at": latest or None,
            "error": reason if "failed" in groups else "", "landed": landed, "means": " ".join(means),
            "landed_card": landed_card, "paid_to_card": ", ".join(dict.fromkeys(p for p in (paid_to(t, card=True) for t in moves) if p))}


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
