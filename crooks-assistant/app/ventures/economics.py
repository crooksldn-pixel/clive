"""What one order leaves after its costs, what advertising it can pay for, and the lowest price
that still pays for it.

Money is Decimal throughout and a float is refused: a binary fraction is how a margin quietly
gains or loses a cent. Every cost is the caller's own figure and none has a default, because a
silent zero is how a loss-making product looks profitable. Figures are per order, in the
market's currency, and net of consumer tax.

Break-even ROAS is revenue over contribution: at that return an order's advertising exactly
uses up what the order leaves. ROAS is measured on the shown price, which is what the ad
platforms report as the purchase value."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from app.ventures.markets import CENT, Market

ZERO = Decimal(0)
ONE = Decimal(1)


def as_amount(name: str, value: object, *, positive: bool = False) -> Decimal:
    """A money amount from a Decimal, int or string; a float or a negative amount is refused."""
    decimal = _as_decimal(name, value)
    if decimal < 0 or (positive and decimal == 0):
        raise ValueError(f"{name} must be {'above' if positive else 'at least'} 0, not {decimal}")
    return decimal


def as_rate(name: str, value: object) -> Decimal:
    """A rate such as 0.029 for 2.9%: at least 0 and below 1."""
    decimal = _as_decimal(name, value)
    if not ZERO <= decimal < ONE:
        raise ValueError(f"{name} must be at least 0 and below 1, not {decimal}")
    return decimal


def _as_decimal(name: str, value: object) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{name} must be a Decimal, an int or a string, not {type(value).__name__}")
    if isinstance(value, Decimal):
        decimal = value
    elif isinstance(value, int | str):
        try:
            decimal = Decimal(value)
        except ArithmeticError:
            raise ValueError(f"{name} is not a number: {value!r}") from None
    else:
        raise TypeError(f"{name} must be a Decimal, an int or a string, not {type(value).__name__}")
    if not decimal.is_finite():
        raise ValueError(f"{name} must be finite, not {decimal}")
    return decimal


@dataclass(frozen=True, slots=True)
class UnitCosts:
    """What fulfilling one order costs the seller before advertising.

    ``product``, ``shipping`` and ``duty`` make the landed cost. ``per_order_fixed`` is
    packaging, pick fees and per-order app charges. ``payment_rate`` and ``payment_fixed`` are
    the card fee, charged on what the customer pays. ``commission_rate`` is a marketplace
    referral fee or an affiliate's commission, also on what the customer pays. ``returns_rate``
    is the share of net revenue set aside for refunds and returns.
    """

    product: Decimal
    shipping: Decimal
    duty: Decimal
    per_order_fixed: Decimal
    payment_rate: Decimal
    payment_fixed: Decimal
    returns_rate: Decimal
    commission_rate: Decimal

    def __post_init__(self) -> None:
        for name in ("product", "shipping", "duty", "per_order_fixed", "payment_fixed"):
            object.__setattr__(self, name, as_amount(name, getattr(self, name)))
        for name in ("payment_rate", "returns_rate", "commission_rate"):
            object.__setattr__(self, name, as_rate(name, getattr(self, name)))

    @property
    def landed(self) -> Decimal:
        """Product, shipping and duty: what the item costs to put in the customer's hands."""
        return self.product + self.shipping + self.duty

    @property
    def fixed_per_order(self) -> Decimal:
        """Every cost of an order that does not scale with its price."""
        return self.landed + self.per_order_fixed + self.payment_fixed

    @property
    def price_rates(self) -> Decimal:
        """The rates charged on the shown price: card fee and commission."""
        return self.payment_rate + self.commission_rate


@dataclass(frozen=True, slots=True)
class Contribution:
    """One order at one price, taken apart."""

    price: Decimal
    net_revenue: Decimal
    fixed_costs: Decimal
    rate_costs: Decimal
    returns_allowance: Decimal
    contribution: Decimal

    @property
    def margin_on_price(self) -> Decimal:
        """Contribution as a share of the shown price."""
        return self.contribution / self.price

    @property
    def break_even_cpa(self) -> Decimal | None:
        """The most one purchase may cost in advertising before the order loses money; None when
        the order loses money before any advertising."""
        return self.contribution if self.contribution > 0 else None

    @property
    def break_even_roas(self) -> Decimal | None:
        """Shown price over contribution; None when no return on ad spend can break even."""
        return self.price / self.contribution if self.contribution > 0 else None

    def margin_after(self, cpa: Decimal) -> Decimal:
        """What an order keeps after paying ``cpa`` for its purchase, as a share of net revenue."""
        return (self.contribution - as_amount("cpa", cpa)) / self.net_revenue


def contribution(price: object, costs: UnitCosts, market: Market) -> Contribution:
    """Take one order at the shown ``price`` apart into what it pays and what it leaves."""
    shown = as_amount("price", price, positive=True)
    net = market.net_of_tax(shown)
    rate_costs = costs.price_rates * shown
    returns_allowance = costs.returns_rate * net
    left = net - costs.fixed_per_order - rate_costs - returns_allowance
    return Contribution(
        price=shown,
        net_revenue=net,
        fixed_costs=costs.fixed_per_order,
        rate_costs=rate_costs,
        returns_allowance=returns_allowance,
        contribution=left,
    )


@dataclass(frozen=True, slots=True)
class PriceFloor:
    """The lowest price that pays the target cost per purchase and keeps the target margin."""

    net_minimum: Decimal
    shown_minimum: Decimal
    target_cpa: Decimal
    target_margin: Decimal
    landed: Decimal

    @property
    def landed_multiple(self) -> Decimal:
        """The floor as a multiple of landed cost, the figure operators quote as "markup"."""
        return self.shown_minimum / self.landed if self.landed > 0 else ZERO


def price_floor(
    costs: UnitCosts, market: Market, *, target_cpa: object, target_margin: object
) -> PriceFloor:
    """The lowest shown price at which an order pays ``target_cpa`` for its purchase in
    advertising and still keeps ``target_margin`` of its net revenue.

    With ``t`` the tax included in the shown price, ``P`` the shown price and ``N = P / (1 + t)``
    the net, the order must satisfy::

        N - F - (p + c) * P - r * N - A >= m * N

    where ``F`` is the fixed cost of an order, ``p`` and ``c`` the card fee and commission
    rates (charged on ``P``), ``r`` the returns allowance, ``A`` the target cost per purchase and
    ``m`` the target margin. Solving for ``N``::

        N >= (F + A) / (1 - (p + c) * (1 + t) - r - m)

    With no tax in the price this is the research formula: price floor equals landed cost plus
    fixed per-order costs plus target cost per purchase, over one minus fees, returns allowance
    and target margin. The shown floor is rounded up to the cent, never down, so the order at
    the floor always meets the target.
    """
    cpa = as_amount("target_cpa", target_cpa)
    margin = as_rate("target_margin", target_margin)
    denominator = ONE - costs.price_rates * (ONE + market.tax_rate) - costs.returns_rate - margin
    if denominator <= 0:
        raise ValueError(
            "no price can pay these rates: card fee, commission, returns allowance and target "
            "margin take the whole of every sale"
        )
    net_minimum = (costs.fixed_per_order + cpa) / denominator
    shown_minimum = (net_minimum * (ONE + market.tax_rate)).quantize(CENT, rounding=ROUND_CEILING)
    return PriceFloor(
        net_minimum=net_minimum,
        shown_minimum=shown_minimum,
        target_cpa=cpa,
        target_margin=margin,
        landed=costs.landed,
    )
