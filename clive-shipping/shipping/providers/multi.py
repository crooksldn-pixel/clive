"""Several label providers behind the one ShippingProvider port.

Quotes come from every provider at once (concurrently) and are merged into one list; a provider
that fails has a safe structured failure in `quote_all`'s second result; other rates still stand.
Every step after that belongs to exactly one provider: verify and create_order go to the provider
named on the quote, and pay / read_order / documents / cancel go to the provider whose
reference prefix the order carries ("p2g:", "es:"). The purchase protocol (purchase.py) is
unchanged: it still sees one provider that pays at most once per order.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from shipping.models import ProviderFailure, Quote, Shipment
from shipping.providers.base import (
    Documents,
    OrderReadback,
    ProviderError,
    ProviderOrder,
    ProviderRefused,
    ProviderUnavailable,
    ShippingProvider,
)
from shipping.providers.reporting import quote_failure

log = logging.getLogger("shipping.providers")


class Providers:
    def __init__(self, providers: list[ShippingProvider]) -> None:
        if not providers:
            raise ValueError("At least one provider is needed.")
        self.providers = providers
        # Asked for international quotes: everyone but the UK-only provider (Shopify Shipping
        # is asked by the service for UK parcels only).
        self.quoting = [p for p in providers if not getattr(p, "domestic_only", False)]
        self.name = " + ".join(p.name for p in self.quoting or providers)

    # ------------------------------------------------------------------ routing

    def by_name(self, name: str) -> ShippingProvider:
        found = next((p for p in self.providers if p.name == name), None)
        if found is None:
            raise ProviderRefused(f"{name} isn't connected.", code="provider")
        return found

    def for_ref(self, ref: str) -> ShippingProvider:
        for p in self.providers:
            prefix = getattr(p, "ref_prefix", "")
            if prefix and ref.startswith(prefix):
                return p
        if len(self.providers) == 1:
            return self.providers[0]
        raise ProviderRefused("No connected provider owns this order.", code="provider")

    def can_cancel(self, ref: str) -> bool:
        try:
            return bool(getattr(self.for_ref(ref), "can_cancel", False))
        except ProviderRefused:
            return False

    # ------------------------------------------------------------------ quotes

    def quote_all(self, shipment: Shipment) -> tuple[list[Quote], list[ProviderFailure]]:
        """Fresh merged quotes and safe failures for this attempt only."""

        def ask(p: ShippingProvider) -> tuple[str, list[Quote] | Exception]:
            try:
                return p.name, p.quotes(shipment)
            except ProviderError as exc:
                return p.name, exc
            except Exception as exc:  # noqa: BLE001 - one adapter's bug must not hide the rest
                log.exception("%s quotes failed unexpectedly", p.name)
                return p.name, exc

        if not self.quoting:
            return [], []
        with ThreadPoolExecutor(max_workers=len(self.quoting)) as pool:
            answers = list(pool.map(ask, self.quoting))
        quotes: list[Quote] = []
        failures: list[ProviderFailure] = []
        for name, got in answers:
            if isinstance(got, Exception):
                log.warning(
                    "%s quotes unavailable for %s (%s): %s",
                    name,
                    shipment.id,
                    shipment.order_name,
                    got,
                )
                failures.append(quote_failure(name, got))
            else:
                quotes.extend(got)
        if len(failures) == len(self.quoting):
            raise ProviderUnavailable(
                "; ".join(f.safe_message for f in failures), failures=failures
            )
        return quotes, failures

    def quotes(self, shipment: Shipment) -> list[Quote]:
        return self.quote_all(shipment)[0]

    # ------------------------------------------------------------------ one provider each

    def verify(self, shipment: Shipment, quote: Quote) -> int:
        return self.by_name(quote.provider).verify(shipment, quote)

    def create_order(self, shipment: Shipment, quote: Quote, reference: str) -> ProviderOrder:
        return self.by_name(quote.provider).create_order(shipment, quote, reference)

    def pay(self, ref: str) -> None:
        self.for_ref(ref).pay(ref)

    def read_order(self, ref: str) -> OrderReadback:
        return self.for_ref(ref).read_order(ref)

    def documents(self, ref: str) -> Documents:
        return self.for_ref(ref).documents(ref)

    def tracking(self, ref: str) -> tuple[str | None, str | None]:
        p: Any = self.for_ref(ref)
        if not hasattr(p, "tracking"):
            return None, None
        return p.tracking(ref)

    def cancel(self, ref: str) -> None:
        p: Any = self.for_ref(ref)
        if not getattr(p, "can_cancel", False):
            raise ProviderRefused(f"{p.name} labels can't be cancelled through CLIVE.")
        p.cancel(ref)

    def cancelled(self, ref: str) -> bool:
        p: Any = self.for_ref(ref)
        return bool(p.cancelled(ref))
