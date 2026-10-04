"""What a label provider must do, and the three ways a call can go wrong.

The error classes are the heart of money safety. Every adapter must map each failure to exactly
one of them, and the purchase protocol treats them very differently:

  ProviderRefused      the provider answered and said no. Definitely not done (not charged).
  ProviderUnavailable  the request was not delivered (DNS, connect refused, 503 before
                       processing). Definitely not done.
  ProviderUncertain    the request may have been processed: timeout after sending, connection
                       lost mid-reply, a 5xx after the provider received it. For a payment this
                       means "you may have been charged": never retry it, reconcile instead.

An adapter that cannot tell Unavailable from Uncertain must say Uncertain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from shipping.models import Quote, Shipment


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class ProviderRefused(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class ProviderUncertain(ProviderError):
    pass


@dataclass
class ProviderOrder:
    ref: str  # opaque to everyone but the adapter; enough to read, pay and fetch documents
    amount_minor: int
    currency: str


@dataclass
class OrderReadback:
    paid: bool
    amount_minor: int | None = None


@dataclass
class Documents:
    label_4x6: bytes | None = None
    label_a4: bytes | None = None
    customs: bytes | None = None  # commercial invoices, when separate from the label PDF
    tracking_number: str | None = None
    tracking_url: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


class ShippingProvider(Protocol):
    name: str

    def quotes(self, shipment: Shipment) -> list[Quote]:
        """Non-binding prices for this shipment. Never spends money."""
        ...

    def verify(self, shipment: Shipment, quote: Quote) -> int:
        """The exact price, in minor units, for buying this quote now. Never spends money."""
        ...

    def create_order(self, shipment: Shipment, quote: Quote, reference: str) -> ProviderOrder:
        """An unpaid order. Must not spend money. `reference` is the ledger operation id."""
        ...

    def pay(self, ref: str) -> None:
        """Spend money. Called at most once per order, ever, by the purchase protocol."""
        ...

    def read_order(self, ref: str) -> OrderReadback:
        """Whether the order was paid, from the provider's own records."""
        ...

    def documents(self, ref: str) -> Documents:
        """The label and customs documents of a paid order. Never spends money."""
        ...
