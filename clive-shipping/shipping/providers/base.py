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

from shipping.models import CustomsMode, DocumentKind, PageSize, ProviderFailure, Quote, Shipment


class ProviderError(RuntimeError):
    def __init__(
        self, message: str, *, code: str = "", failures: list[ProviderFailure] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.failures = failures or []


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
    # The provider is still working on it: neither paid nor unpaid (never counted as unpaid).
    pending: bool = False
    # The provider's own record of this very attempt says it failed: nothing was bought, so
    # there is nothing to wait for (Shopify's PURCHASE_FAILED). Only with paid False.
    failed: bool = False
    # With `failed`: the provider's reason leaves a person to look before buying again (e.g.
    # another purchase was already running for the order). The words to show them.
    check: str = ""
    # With `failed`: how the provider knows, in words for staff (default: it confirmed it).
    note: str = ""


@dataclass
class ProviderDocument:
    """A document as the provider returned it, already classified by the adapter."""

    kind: DocumentKind
    body: bytes | None  # None: nothing to print (e.g. customs filed electronically)
    media_type: str = "application/pdf"
    page_size: PageSize = PageSize.other
    pages: int = 0
    copies_required: int = 0
    must_print: bool = False
    attach_to_parcel: bool = False
    electronic: bool = False
    note: str = ""
    print_note: str = ""  # why it can't go to the label printer as it is


@dataclass
class Documents:
    """Everything that comes with a paid label. `customs` is UNKNOWN until the adapter has
    positive evidence either way; it is never guessed as electronic."""

    documents: list[ProviderDocument] = field(default_factory=list)
    customs: CustomsMode = CustomsMode.unknown
    tracking_number: str | None = None
    tracking_url: str | None = None
    provider_ids: dict[str, str] = field(default_factory=dict)
    # The label is bought but its file can't be fetched by CLIVE (e.g. found by reading the
    # order back after a lost reply): what staff should do instead. Nothing more will come.
    file_unavailable: str = ""

    def find(self, kind: DocumentKind) -> ProviderDocument | None:
        return next((d for d in self.documents if d.kind == kind), None)


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
