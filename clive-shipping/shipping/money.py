"""Money is an integer count of minor units (pence) and an ISO currency. Never a float.

Providers answer in JSON numbers (Parcel2Go: 10.69). Those are converted through their decimal
string, so 10.69 is 1069 and not 1068.9999.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel


class Money(BaseModel, frozen=True):
    minor: int
    currency: str = "GBP"

    def __add__(self, other: Money) -> Money:
        if other.currency != self.currency:
            raise ValueError(f"Can't add {other.currency} to {self.currency}.")
        return Money(minor=self.minor + other.minor, currency=self.currency)

    def __str__(self) -> str:
        symbol = {"GBP": "£", "EUR": "€", "USD": "$"}.get(self.currency)
        amount = f"{Decimal(self.minor) / 100:.2f}"
        return f"{symbol}{amount}" if symbol else f"{amount} {self.currency}"


def to_minor(amount: str | int | float | Decimal | None) -> int:
    """A provider's amount (10.69, "10.69", Decimal) in minor units, rounding half up."""
    if amount in (None, ""):
        return 0
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(amount: str | int | float | Decimal | None, currency: str = "GBP") -> Money:
    return Money(minor=to_minor(amount), currency=currency)
