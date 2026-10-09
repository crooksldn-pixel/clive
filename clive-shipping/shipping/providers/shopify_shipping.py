"""Shopify Shipping: UK labels bought from the merchant's own Shopify Shipping account.

`shippingLabelPurchase` (Admin API 2026-07+) buys one label for one fulfillment order,
asynchronously: the mutation answers with a result id at PENDING_PURCHASE, which ends PURCHASED
or PURCHASE_FAILED. What it doesn't have, and how this adapter copes (every limit is the
purchase protocol's to enforce; nothing here relies on Shopify for safety):

- **No price before buying** (no rates query for apps): quotes carry `price_known=False` and a
  zero amount; the merchant is told the price is Shopify Shipping's, set when bought. The owner
  accepted this for UK labels.
- **No idempotency** (the mutation isn't documented as @idempotent): one mutation per purchase
  operation, ever. The request is recorded (the `label_purchases` row) before it is sent, the
  row says it was sent, and `pay` refuses to send for a row already sent.
- **Rates by code only, and no list of codes**: the service is always the owner's mapped
  Tracked 24 / Tracked 48 with its server-set carrier and service code; Shopify's default rate
  selection is never used.
- **A lost reply** (no result id) is UNKNOWN. The result can't be searched for, so the order is
  read back: a fulfilment carrying a tracking number on this fulfillment order means a label was
  bought (adopted; its file can't be fetched without the result id, and staff are told where to
  print it). Nothing found is believed only after the settle window, by the protocol.

The protocol's steps map onto it like this: `create_order` records the request (no network, no
money); `pay` sends the mutation once and polls the result to an end within `poll_for`;
`read_order` reads the result (or the order) back; `documents` fetches the label (and any
customs form) files from Shopify's links.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from shipping import domestic
from shipping.domestic import DomesticPolicy
from shipping.label_selection import measure
from shipping.models import CustomsMode, DocumentKind, PageSize, Quote, Shipment, ShopConfig
from shipping.money import Money
from shipping.providers.base import (
    Documents,
    OrderReadback,
    ProviderDocument,
    ProviderOrder,
    ProviderRefused,
    ProviderUnavailable,
    ProviderUncertain,
)
from shipping.shopify import LabelApi, ShopifyError, ShopifyNotSent, ShopifyPort, ShopifyRefused
from shipping.store import Store, now

log = logging.getLogger("shipping.providers.shopify_shipping")

PURCHASED, FAILED, PENDING = "PURCHASED", "PURCHASE_FAILED", "PENDING_PURCHASE"

# Shopify's userErrors and purchase errors, in words a merchant acts on. Anything else is shown
# as Shopify wrote it (it carries no secrets).
REASONS = {
    "TERMS_OF_SERVICE_NOT_ACCEPTED": "Shopify Shipping's terms haven't been accepted for this "
    "store. Buy one label in Shopify admin first, which asks for them.",
    "RATES_NOT_FOUND": "Shopify Shipping has no rate for this service and parcel. Check the "
    "service code set on the server, the package and the weight.",
    "MISSING_SHIPPING_RATE": "Shopify Shipping needs a rate for this parcel and found none.",
    "FULFILLMENT_ORDER_INVALID": "Shopify won't buy a label for this order as it stands (it "
    "may be fulfilled, on hold or moved).",
    "TOTAL_WEIGHT_ZERO": "The parcel's weight is zero.",
    "INVALID_PACKAGE_DIMENSIONS": "The package's size isn't valid.",
    "SHIPPING_DATE_IN_THE_PAST": "The shipping date was in the past.",
    "PHONE_NUMBER_NOT_FULLY_QUALIFIED_DESTINATION": "The customer's phone number needs its "
    "country code (e.g. +44).",
    "PHONE_NUMBER_NOT_FULLY_QUALIFIED_ORIGIN": "The ship-from phone number needs its country "
    "code (e.g. +44).",
    "KILL_SWITCH": "Shopify has paused label buying for now. Try again later.",
    "CARRIER_NOT_SUPPORTED": "This carrier can't be bought through Shopify's API.",
    "CARRIER_NOT_AVAILABLE": "Royal Mail isn't available for this label right now.",
    "CONNECTION_ERROR": "Shopify couldn't reach Royal Mail. Try again in a few minutes.",
    "DISABLED_SHIPPING_ACCOUNT": "The store's Shopify Shipping account is disabled; contact "
    "Shopify Support.",
    "JOB_NOT_ENQUEUED": "Another label is being bought for this order in Shopify.",
    "PURCHASE_LABEL_VALIDATION_ERROR": "Shopify Shipping found the address, weight or package "
    "invalid.",
}


def reason(errors: list[dict[str, Any]]) -> tuple[str, str]:
    """(code, words) for Shopify's errors."""
    code = str((errors[0] or {}).get("code") or "") if errors else ""
    words = [REASONS.get(str(e.get("code") or ""), str(e.get("message") or "")) for e in errors]
    said = " ".join(dict.fromkeys(w for w in words if w)) or "Shopify gave no reason."
    return code, said


class ShopifyShipping:
    name = "Shopify Shipping"
    ref_prefix = "ss:"
    # Asked only for UK parcels (service.prepare), never in the international quote round.
    domestic_only = True
    can_cancel = False
    # How long a lost reply waits, with nothing found on the order, before it counts as not
    # bought. Shopify says most purchases finish in seconds; this leaves a wide margin.
    settle_after = timedelta(minutes=10)
    # After PURCHASED, how long Shopify gets to put the label's tracking on the order itself
    # before CLIVE adds the fulfilment (read first, as always).
    fulfil_grace = timedelta(minutes=2)
    # What staff are told when a lost reply is settled by finding nothing (never "confirmed").
    not_found = (
        "Shopify showed no label on this order for 10 minutes after the request whose answer "
        "was lost, so CLIVE treats it as not bought. Check the order in Shopify admin for a "
        "label before buying again."
    )

    def __init__(
        self,
        api: LabelApi,
        shopify: ShopifyPort,
        store: Store,
        shop: str,
        policy: DomesticPolicy,
        config: Callable[[str], ShopConfig],
        clock: Callable[[], datetime] = now,
        poll_for: float = 60.0,
        poll_every: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.api, self.shopify, self.store, self.shop = api, shopify, store, shop
        self.policy, self.config, self.clock = policy, config, clock
        # Shopify recommends an overall timeout (e.g. 60 s) rather than polling for ever.
        self.poll_for, self.poll_every = poll_for, poll_every
        self.sleep, self.monotonic = sleep, monotonic

    # ------------------------------------------------------------------ quotes

    def quotes(self, shipment: Shipment) -> list[Quote]:
        """The one service this order gets (the owner's mapping, or a person's choice), with no
        price: Shopify Shipping sets it when the label is bought."""
        service = shipment.domestic_service
        if not shipment.domestic or service is None or self.policy.rate(service) is None:
            return []
        days = domestic.DAYS.get(service, (None, None))
        return [
            Quote(
                provider=self.name,
                carrier=domestic.CARRIER,
                service_code=service,
                service_name=domestic.title(service),
                amount=Money(minor=0, currency=shipment.currency),
                price_known=False,
                est_days_min=days[0],
                est_days_max=days[1],
                tracked=True,
                billed_by="provider",
                generated_at=self.clock(),
            )
        ]

    def verify(self, shipment: Shipment, quote: Quote) -> int:
        """No price can be read before buying; checks the service can still be bought here."""
        if self.policy.rate(quote.service_code) is None:
            raise ProviderRefused(
                f"Shopify Shipping's code for Royal Mail {domestic.title(quote.service_code)} "
                "isn't set on the server.",
                code="service_code",
            )
        return 0

    # ------------------------------------------------------------------ the purchase

    def create_order(self, shipment: Shipment, quote: Quote, reference: str) -> ProviderOrder:
        """Writes down exactly what will be sent, from the authorised shipment and service. No
        network and no money: Shopify has no unpaid order to make."""
        rate = self.policy.rate(quote.service_code)
        p = shipment.package
        if rate is None:
            raise ProviderRefused("The service has no Shopify Shipping code set.", code="service")
        if p is None or p.total_weight_g <= 0:
            raise ProviderRefused("The parcel needs a package and a weight.", code="package")
        cfg = self.config(shipment.shop)
        purchase = {
            "fulfillmentOrderId": shipment.fulfillment_order_id,
            # Must not be in the past when Shopify reads it: a little ahead of now, today.
            "shippingDatetime": (self.clock() + timedelta(minutes=10)).isoformat(),
            "packageInfo": {
                "customPackage": {
                    "dimensions": {
                        "length": p.length_mm / 10,
                        "width": p.width_mm / 10,
                        "height": p.height_mm / 10,
                        "unit": "CENTIMETERS",
                    },
                    "weight": {"value": float(p.empty_weight_g), "unit": "GRAMS"},
                }
            },
            "totalWeight": {"value": float(p.total_weight_g), "unit": "GRAMS"},
            "preferredRateSelection": {
                "carrierCode": rate.carrier_code,
                "serviceCode": rate.service_code,
            },
            "notifyCustomer": cfg.notify_customer,
        }
        ref = f"{self.ref_prefix}{reference}"
        self.store.add_label_purchase(
            shipment.shop,
            ref,
            {
                "ref": ref,
                "shipment_id": shipment.id,
                "order_id": shipment.order_id,
                "fulfillment_order_id": shipment.fulfillment_order_id,
                "service": quote.service_code,
                "purchase": purchase,
                "state": "prepared",
                "prepared_at": self.clock().isoformat(),
                "sent_at": None,
                "result_id": None,
            },
        )
        return ProviderOrder(ref=ref, amount_minor=0, currency=shipment.currency)

    def _row(self, ref: str) -> dict[str, Any]:
        row = self.store.label_purchase(self.shop, ref)
        if row is None:
            raise ProviderUnavailable("CLIVE has no record of this Shopify Shipping purchase.")
        return row

    def _save(self, ref: str, row: dict[str, Any], **changes: Any) -> None:
        row.update(changes)
        self.store.save_label_purchase(self.shop, ref, row)

    def pay(self, ref: str) -> None:
        """The one call that spends: shippingLabelPurchase, sent once and never again for this
        operation, then its result polled to an end within `poll_for`."""
        row = self._row(ref)
        if row.get("sent_at") or row.get("state") != "prepared":
            # Defence in depth: the protocol never pays twice, and neither does this.
            raise ProviderUncertain(
                "This label purchase was already sent once; CLIVE reads it back, never resends."
            )
        self._save(ref, row, state="sending", sent_at=self.clock().isoformat())
        try:
            payload = self.api.purchase_label(row["purchase"])
        except ShopifyNotSent as exc:
            self._save(ref, row, state="not_sent", error=str(exc))
            raise ProviderUnavailable(str(exc)) from exc
        except ShopifyRefused as exc:
            self._save(ref, row, state="refused", error=str(exc))
            raise ProviderRefused(f"Shopify refused the purchase ({exc})") from exc
        except ShopifyError as exc:
            self._save(ref, row, state="unknown", error=str(exc))
            raise ProviderUncertain(str(exc)) from exc
        errors = payload.get("userErrors") or []
        if errors:
            code, said = reason(errors)
            self._save(ref, row, state="refused", error=said, codes=[e.get("code") for e in errors])
            raise ProviderRefused(said, code=code)
        result = payload.get("shippingLabelPurchaseResult") or {}
        rid = result.get("id") if isinstance(result, dict) else None
        if not rid:
            self._save(ref, row, state="unknown", error="no result id in Shopify's answer")
            raise ProviderUncertain("Shopify answered without saying whether it started buying.")
        self._save(ref, row, state="pending", result_id=rid)  # kept before anything else
        status = result.get("status")
        deadline = self.monotonic() + self.poll_for
        while True:
            if status == PURCHASED:
                self._save(ref, row, state="purchased")
                return
            if status == FAILED:
                code, said = reason(result.get("errors") or [])
                self._save(ref, row, state="failed", error=said)
                raise ProviderRefused(said, code=code or "purchase_failed")
            if self.monotonic() >= deadline:
                raise ProviderUncertain("Shopify is still buying the label.")
            self.sleep(self.poll_every)
            try:
                result = self.api.label_purchase(rid) or {}
            except ShopifyError as exc:  # a read; the next poll (or reconcile) asks again
                log.warning("polling %s: %s", rid, exc)
                result = {}
            status = result.get("status")

    # ------------------------------------------------------------------ read back

    def read_order(self, ref: str) -> OrderReadback:
        """Whether this purchase bought a label, from Shopify's own records."""
        row = self._row(ref)
        rid = row.get("result_id")
        if rid:
            try:
                result = self.api.label_purchase(rid)
            except ShopifyError as exc:
                raise ProviderUnavailable(f"Shopify didn't answer the read-back: {exc}") from exc
            status = (result or {}).get("status")
            if status == PURCHASED:
                return OrderReadback(paid=True)
            if status == FAILED:
                self._save(ref, row, state="failed")
                return OrderReadback(paid=False, failed=True)
            return OrderReadback(paid=False, pending=True)  # pending, or not visible yet
        # The reply was lost: Shopify's result can't be found. A label shows on the order as a
        # fulfilment with a tracking number on this fulfillment order.
        try:
            snap = self.shopify.fulfillment_order(row["fulfillment_order_id"])
        except ShopifyError as exc:
            raise ProviderUnavailable(f"Shopify didn't answer the read-back: {exc}") from exc
        numbers = snap.tracking_numbers if snap is not None else []
        if numbers:
            self._save(ref, row, state="adopted", adopted_tracking=numbers[0])
            return OrderReadback(paid=True)
        return OrderReadback(paid=False)

    def documents(self, ref: str) -> Documents:
        """The bought label's files, fetched from Shopify's links and measured as they are."""
        row = self._row(ref)
        rid = row.get("result_id")
        if not rid:
            if row.get("adopted_tracking"):
                return Documents(
                    customs=CustomsMode.not_required,
                    tracking_number=row["adopted_tracking"],
                    file_unavailable=(
                        "Shopify bought this label (found on the order after the reply was "
                        "lost), but CLIVE can't fetch its file without Shopify's purchase "
                        "reference. Print it from the order in Shopify admin; don't buy again."
                    ),
                )
            raise ProviderUnavailable("No Shopify Shipping label recorded yet.")
        try:
            result = self.api.label_purchase(rid) or {}
        except ShopifyError as exc:
            raise ProviderUnavailable(f"Shopify didn't answer: {exc}") from exc
        if result.get("status") == FAILED:
            raise ProviderRefused("Shopify says this purchase failed.", code="unpaid")
        labels = result.get("shippingLabels") or []
        if result.get("status") != PURCHASED or not labels:
            raise ProviderUnavailable("Shopify hasn't finished the label yet.")
        label = labels[0]
        tracking = label.get("trackingInfo") or {}
        docs: list[ProviderDocument] = []
        for d in label.get("shippingDocuments") or []:
            docs.append(self._document(d))
        if not any(d.kind == DocumentKind.shipping_label for d in docs):
            raise ProviderUnavailable("Shopify's label has no label document yet.")
        customs = (
            CustomsMode.paper
            if any(d.kind == DocumentKind.customs_declaration for d in docs)
            else CustomsMode.not_required
        )
        label_id = str(label.get("id") or "")
        return Documents(
            documents=docs,
            customs=customs,
            tracking_number=tracking.get("number") or None,
            tracking_url=tracking.get("url")
            if str(tracking.get("url") or "").startswith("https://")
            else None,
            provider_ids={"label": label_id.rsplit("/", 1)[-1]} if label_id else {},
        )

    def _document(self, d: dict[str, Any]) -> ProviderDocument:
        kind = (
            DocumentKind.customs_declaration
            if d.get("documentType") == "CUSTOMS_FORM"
            else DocumentKind.shipping_label
        )
        url = str(d.get("url") or "")
        if not url:
            raise ProviderUnavailable("Shopify's document has no link yet.")
        try:
            _, body = self.api.download(url)
        except ShopifyError as exc:
            raise ProviderUnavailable(f"The label file couldn't be fetched: {exc}") from exc
        what = "label" if kind == DocumentKind.shipping_label else "customs form"
        if d.get("format") != "PDF" or not body.startswith(b"%PDF"):
            # Kept for the record; it can't be printed from here (the print paths need a PDF).
            return ProviderDocument(
                kind=kind,
                body=body,
                media_type="application/octet-stream",
                must_print=True,
                attach_to_parcel=True,
                note=f"Shopify gave the {what} as {d.get('format') or 'an unknown format'}, "
                "not PDF, so it can't be printed from here. Set Shopify's label format to PDF, "
                "or print it from the order in Shopify admin.",
            )
        try:
            size, pages, words = measure(body)
        except ValueError:
            size, pages, words = PageSize.other, 0, "unreadable"
        note = (
            ""
            if size == PageSize.label_4x6
            else f"Shopify's {what} file is {words}, not 4×6. It isn't scaled to fit: print it "
            "from Open PDF on a printer that takes that size, or change the label size in "
            "Shopify's shipping label settings."
        )
        return ProviderDocument(
            kind=kind,
            body=body,
            page_size=size,
            pages=pages,
            copies_required=1,
            must_print=True,
            attach_to_parcel=True,
            note=note,
        )
