"""Where a venture sells: its currency, how consumer tax sits in the shown price, and the
region whose rules the rest of the engine applies.

Tax is the one market fact the arithmetic needs. In the UK and the EU a VAT-registered seller
shows prices with VAT included and keeps the net; in the US sales tax is added at checkout, so
the shown price is the seller's own. The rates below are the standard rates in force in
September 2026. A seller that is not VAT-registered, or a product on a reduced rate, uses a
Market of its own (``UK-NOVAT`` is provided for the first case)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
REGIONS = ("UK", "US", "EU")
_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}


@dataclass(frozen=True, slots=True)
class Market:
    """A place a venture sells, and the rule set that applies there."""

    code: str
    region: str
    currency: str
    tax_rate: Decimal
    label: str

    def __post_init__(self) -> None:
        if self.region not in REGIONS:
            raise ValueError(f"region must be one of {', '.join(REGIONS)}, not {self.region!r}")
        if not isinstance(self.tax_rate, Decimal):
            raise TypeError("tax_rate must be a Decimal")
        if not Decimal(0) <= self.tax_rate < Decimal(1):
            raise ValueError("tax_rate must be at least 0 and below 1")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError(f"currency must be an ISO 4217 code, not {self.currency!r}")

    def net_of_tax(self, shown: Decimal) -> Decimal:
        """What the seller keeps of a shown price once consumer tax is taken out."""
        return shown / (Decimal(1) + self.tax_rate)


def _market(code: str, region: str, currency: str, rate: str, label: str) -> Market:
    return Market(code, region, currency, Decimal(rate), label)


MARKETS: dict[str, Market] = {
    m.code: m
    for m in (
        _market("UK", "UK", "GBP", "0.20", "United Kingdom, VAT-registered seller (20% VAT in the price)"),
        _market("UK-NOVAT", "UK", "GBP", "0", "United Kingdom, seller not registered for VAT"),
        _market("US", "US", "USD", "0", "United States (sales tax added at checkout)"),
        _market("EU-DE", "EU", "EUR", "0.19", "Germany (19% VAT in the price)"),
        _market("EU-FR", "EU", "EUR", "0.20", "France (20% VAT in the price)"),
        _market("EU-ES", "EU", "EUR", "0.21", "Spain (21% VAT in the price)"),
        _market("EU-IT", "EU", "EUR", "0.22", "Italy (22% VAT in the price)"),
        _market("EU-NL", "EU", "EUR", "0.21", "Netherlands (21% VAT in the price)"),
        _market("EU-IE", "EU", "EUR", "0.23", "Ireland (23% VAT in the price)"),
    )
}


def market(code: str) -> Market:
    """The named market, or a ValueError that lists the codes there are."""
    try:
        return MARKETS[code]
    except KeyError:
        raise ValueError(f"unknown market {code!r}; known: {', '.join(sorted(MARKETS))}") from None


def format_money(amount: Decimal, currency: str) -> str:
    """``£26.99``, ``-$4.10``, ``1,250.00 CHF``: rounded half-up to the cent for display only."""
    value = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    sign = "-" if value < 0 else ""
    body = f"{abs(value):,.2f}"
    symbol = _SYMBOLS.get(currency)
    return f"{sign}{symbol}{body}" if symbol else f"{sign}{body} {currency}"
