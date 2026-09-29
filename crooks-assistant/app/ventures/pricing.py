"""How a price is shown, when shipping becomes free, and whether a "was" price may be claimed.

Presentation follows the evidence the research found rather than habit: a price ending in .99
helps mainly when it changes the left digit, and round prices suit gifts and premium goods. The
presented price is never below the floor it was built from.

Reference prices are where pricing law bites. In the EU, an announced reduction must be
measured against the lowest price of the previous 30 days (Omnibus Directive; CJEU, Aldi Süd,
26 September 2024). In the UK and the US the tests are "genuine" and "reasonably substantial
period" rather than a fixed count of days, so the engine applies a conservative default of its
own for those regions (``UK_US_RULE``). It is the engine's rule, not a statement of the law, and
the owner may tighten it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.ventures.economics import as_amount

STYLES = ("charm", "round")
EU_LOOKBACK_DAYS = 30


def present_price(floor: object, style: str = "charm") -> Decimal:
    """The price to show for a floor.

    ``charm``: the smallest price ending in .99 that is at or above the floor.
    ``round``: the floor rounded up to a whole unit.
    """
    value = as_amount("floor", floor, positive=True)
    if style == "charm":
        candidate = value.to_integral_value(rounding=ROUND_FLOOR) + Decimal("0.99")
        return candidate if candidate >= value else candidate + 1
    if style == "round":
        return value.to_integral_value(rounding=ROUND_CEILING)
    raise ValueError(f"style must be one of {', '.join(STYLES)}, not {style!r}")


def changes_left_digit(price: Decimal) -> bool:
    """Whether the price sits one cent under a new leading digit (19.99 against 20.00), the case
    where the research found nine-endings actually move buyers."""
    below, above = str(int(price)), str(int(price + Decimal("0.01")))
    return below[0] != above[0] or len(below) != len(above)


def free_shipping_threshold(median_order: object, factor: object = "1.4") -> Decimal:
    """Free shipping from about 1.3 to 1.5 times the median order, rounded up to a multiple of 5 so
    it reads as a threshold rather than a computation."""
    median = as_amount("median_order", median_order, positive=True)
    multiple = as_amount("factor", factor, positive=True)
    if not Decimal("1") <= multiple <= Decimal("2"):
        raise ValueError("factor must be between 1 and 2 times the median order")
    return (median * multiple / 5).to_integral_value(rounding=ROUND_CEILING) * 5


@dataclass(frozen=True, slots=True)
class PricePoint:
    """A price in force from ``effective_from`` until the next point."""

    effective_from: date
    price: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "price", as_amount("price", self.price, positive=True))


@dataclass(frozen=True, slots=True)
class UkUsRule:
    """The engine's conservative default for "was" prices in the UK and the US: the reference price
    must have been the price on every one of the ``consecutive_days`` before the sale, and on at
    least ``share_of_lookback`` of the ``lookback_days`` before it."""

    consecutive_days: int = 28
    lookback_days: int = 90
    share_of_lookback: Decimal = Decimal("0.5")


UK_US_RULE = UkUsRule()


@dataclass(frozen=True, slots=True)
class ReferenceCheck:
    """Whether a reduction from ``reference`` to ``sale`` may be announced, and why."""

    allowed: bool
    region: str
    reference: Decimal
    sale: Decimal
    discount_basis: Decimal | None
    reasons: tuple[str, ...]

    @property
    def discount_percent(self) -> Decimal | None:
        """The reduction as a percentage of the price it must be measured from, when allowed."""
        if not self.allowed or self.discount_basis is None:
            return None
        return ((self.discount_basis - self.sale) / self.discount_basis * 100).quantize(Decimal("0.1"))


def price_on(history: Sequence[PricePoint], day: date) -> Decimal | None:
    """The price in force on ``day``, or None before the first recorded price."""
    in_force = None
    for point in _ordered(history):
        if point.effective_from > day:
            break
        in_force = point.price
    return in_force


def check_reference_price(
    history: Sequence[PricePoint],
    *,
    reference: object,
    sale: object,
    sale_starts: date,
    region: str,
    rule: UkUsRule = UK_US_RULE,
) -> ReferenceCheck:
    """Whether announcing a reduction from ``reference`` to ``sale`` from ``sale_starts`` is allowed
    by the engine's rules for ``region``, judged against the price history the engine itself kept.

    The history must be the engine's own ledger of prices actually charged in that market,
    including any price shown to a test group. Shopify sends no notification when a price list
    changes, so a history reconstructed afterwards is not evidence.
    """
    ref = as_amount("reference", reference, positive=True)
    now = as_amount("sale", sale, positive=True)
    points = _ordered(history)
    reasons: list[str] = []
    if now >= ref:
        reasons.append("the sale price is not below the reference price, so there is no reduction")
    if region == "EU":
        window = [sale_starts - timedelta(days=offset) for offset in range(1, EU_LOOKBACK_DAYS + 1)]
        prices = [price_on(points, day) for day in window]
        if any(price is None for price in prices):
            reasons.append(
                "the product has not been on sale for the 30 days before the reduction, so no prior "
                "price can be shown"
            )
            return ReferenceCheck(False, region, ref, now, None, tuple(reasons))
        lowest = min(p for p in prices if p is not None)
        if ref != lowest:
            reasons.append(
                f"the reference {ref} is not the lowest price of the previous 30 days, {lowest}; "
                "the prior price shown must be that lowest price"
            )
        return ReferenceCheck(not reasons, region, ref, now, lowest, tuple(reasons))
    if region in ("UK", "US"):
        streak = [price_on(points, sale_starts - timedelta(days=offset)) for offset in range(1, rule.consecutive_days + 1)]
        if any(price != ref for price in streak):
            reasons.append(
                f"the reference {ref} was not the price on every one of the {rule.consecutive_days} "
                "days before the sale"
            )
        lookback = [price_on(points, sale_starts - timedelta(days=offset)) for offset in range(1, rule.lookback_days + 1)]
        at_reference = sum(1 for price in lookback if price == ref)
        if Decimal(at_reference) < rule.share_of_lookback * rule.lookback_days:
            reasons.append(
                f"the reference {ref} was the price on {at_reference} of the {rule.lookback_days} days "
                f"before the sale, fewer than {rule.share_of_lookback:%} of them"
            )
        return ReferenceCheck(not reasons, region, ref, now, ref if not reasons else None, tuple(reasons))
    raise ValueError(f"region must be UK, US or EU, not {region!r}")


def _ordered(history: Sequence[PricePoint]) -> list[PricePoint]:
    points = sorted(history, key=lambda point: point.effective_from)
    days = [point.effective_from for point in points]
    if len(set(days)) != len(days):
        raise ValueError("price history has two prices on the same day")
    return points
