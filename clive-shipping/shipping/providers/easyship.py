"""Easyship (public API 2024-09): rates, shipments, labels, documents, tracking, cancel.

Verified against Easyship's developer reference on 2026-10-05 (developers.easyship.com,
version 2024.09; the OpenAPI definitions embedded in each reference page):

  POST /2024-09/rates                              quotes and the exact price (a read)
  POST /2024-09/shipments                          an unrated-to-labelled shipment, no label
  POST /2024-09/shipments/{id}/label               buys the label: the only call that spends
  GET  /2024-09/shipments/{id}                     the record: label_paid_at, label_state,
                                                   trackings, shipping_documents (base64)
  POST /2024-09/shipments/{id}/cancel              cancels the shipment (refund per Easyship)
  GET  /2024-09/account/credit                     balance / available_balance (Setup)

Hosts: production https://public-api.easyship.com, sandbox
https://public-api-sandbox.easyship.com; tokens say which ("prod_" / "sand_"). Bearer auth.
Rate limit 60 requests a minute, 10 a second. Easyship documents no idempotency key: the
purchase ledger (purchase.py) is the only protection against paying twice, as for Parcel2Go.

A rate has no id of its own: a service is identified by courier_service.id, and the price is
total_charge in the rate's currency (output_currency is set to the shipment's). Shipping rules
are never applied, so the service and price can't change between preview and purchase.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from shipping import contacts
from shipping.documents import is_pdf, page_size, pdf_pages
from shipping.label_selection import CN23_NOTE, easyship_cn23
from shipping.models import (
    Address,
    CustomsLine,
    CustomsMode,
    DocumentKind,
    PageSize,
    Quote,
    Shipment,
    ShopConfig,
)
from shipping.money import Money, to_minor
from shipping.providers.base import (
    Documents,
    OrderReadback,
    ProviderDocument,
    ProviderError,
    ProviderOrder,
    ProviderRefused,
    ProviderUnavailable,
    ProviderUncertain,
)
from shipping.store import now

log = logging.getLogger("shipping.easyship")

API = "/2024-09"
PRODUCTION = "https://public-api.easyship.com"
SANDBOX = "https://public-api-sandbox.easyship.com"
REF_PREFIX = "es:"
# Words in Easyship's refusal of a label that mean "couldn't charge you".
PAYMENT_WORDS = re.compile(r"credit|balance|payment|card|fund", re.IGNORECASE)
SERVICE_PREFIX = "es-"

# Label states that mean the label exists or is being made, i.e. it was bought.
BOUGHT_STATES = frozenset({"pending", "generating", "generated", "printed", "reported"})
READY_STATES = frozenset({"generated", "printed", "reported"})


def base_url(token: str) -> str:
    """Which Easyship the token belongs to. A token that names neither is refused."""
    if token.startswith("prod_"):
        return PRODUCTION
    if token.startswith("sand_"):
        return SANDBOX
    raise ProviderRefused("The Easyship token isn't a production or sandbox token.", code="auth")


def _errors(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return (r.text or f"HTTP {r.status_code}")[:200]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        details = [str(d) for d in (err.get("details") or []) if d][:3]
        text = str(err.get("message") or err.get("code") or f"HTTP {r.status_code}")
        return (text + (": " + "; ".join(details) if details else ""))[:400]
    return str(body)[:300]


def _money(value: Any, what: str, error: type[ProviderError]) -> int:
    """A price in minor units. Missing, malformed or not positive is an error, never 0."""
    try:
        minor = to_minor(value) if value not in (None, "") and not isinstance(value, bool) else None
    except (ArithmeticError, ValueError, TypeError):
        minor = None
    if minor is None or minor <= 0:
        raise error(f"Easyship's {what} answer had no usable price ({value!r}).")
    return minor


def _obj(value: Any) -> dict[str, Any]:
    """A JSON object, or an empty one: Easyship's answers are never trusted to be shaped."""
    return value if isinstance(value, dict) else {}


def _days(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _handover(options: Any) -> str:
    opts = set(options) if isinstance(options, list) else set()
    drop, pick = "dropoff" in opts, bool(opts & {"free_pickup", "paid_pickup"})
    return "either" if drop and pick else "dropoff" if drop else "collection" if pick else ""


BILLED_BY = {"Easyship": "provider", "EasyshipPayOnScan": "on_scan", "Courier": "courier_account"}


def _variant_ref(variant_id: str | None) -> str | None:
    """A stable item reference for a line without a SKU: its Shopify variant number."""
    num = (variant_id or "").rsplit("/", 1)[-1]
    return f"shopify-variant-{num}" if num.isdigit() else None


class Easyship:
    name = "Easyship"
    ref_prefix = REF_PREFIX
    can_cancel = True

    def __init__(
        self,
        token: str,
        config: Callable[[str], ShopConfig],
        http: httpx.Client | None = None,
        clock: Callable[[], datetime] = now,
        timeout: float = 30.0,
    ) -> None:
        self.token = token.strip()
        self.config = config
        self.clock = clock
        self._http = http or httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0))

    # ------------------------------------------------------------------ transport

    def _call(
        self,
        method: str,
        path: str,
        *,
        writes: bool,
        json: Any = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """One request. `writes` says whether the call may change something at Easyship
        (create a shipment, buy a label, cancel); a lost reply to such a call is UNKNOWN."""
        url = f"{base_url(self.token)}{API}{path}"
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            r = self._http.request(method, url, headers=headers, json=json, params=params)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise ProviderUnavailable(
                f"Easyship could not be reached ({exc})", code="timeout"
            ) from exc
        except httpx.HTTPError as exc:
            if writes:
                raise ProviderUncertain(f"Easyship's answer was lost ({exc})") from exc
            raise ProviderUnavailable(f"Easyship didn't answer ({exc})", code="timeout") from exc
        if r.status_code in (401, 403):
            raise ProviderRefused(
                f"Easyship refused the access token ({r.status_code}).", code="auth"
            )
        if r.status_code == 429:
            # Rejected before processing: definitely not done.
            raise ProviderUnavailable(
                "Easyship's rate limit was reached; try again shortly.", code="rate_limit"
            )
        if r.status_code >= 500:
            if writes:
                raise ProviderUncertain(f"Easyship failed while handling it ({r.status_code})")
            raise ProviderUnavailable(
                f"Easyship is having problems ({r.status_code})", code="server_error"
            )
        if r.status_code >= 400:
            raise ProviderRefused(_errors(r), code=str(r.status_code))
        try:
            body = r.json()
        except ValueError as exc:
            if writes:
                raise ProviderUncertain(f"Easyship's answer to {path} was unreadable.") from exc
            raise ProviderUnavailable(f"Easyship's answer to {path} was unreadable.") from exc
        if not isinstance(body, dict):
            if writes:
                raise ProviderUncertain(f"Easyship's answer to {path} was unexpected.")
            raise ProviderUnavailable(f"Easyship's answer to {path} was unexpected.")
        body["_status"] = r.status_code
        return body

    # ------------------------------------------------------------------ request shapes

    @staticmethod
    def _address(a: Address, *, origin: bool = False) -> dict[str, Any]:
        out = {
            "line_1": a.line1,
            "line_2": a.line2 or None,
            "city": a.city,
            "postal_code": a.postcode or None,
            "country_alpha2": a.country,
            "contact_name": a.name or a.company,
            "company_name": a.company or None,
            "contact_phone": a.phone or None,
            "contact_email": a.email or None,
        }
        out = {k: v for k, v in out.items() if v not in (None, "")}
        # Rates require the key even where there are no states (GB, GG): the origin's must be
        # a string, the destination's may be null.
        out["state"] = a.region or ("" if origin else None)
        return out

    def _origin(self, s: Shipment) -> dict[str, Any]:
        cfg = self.config(s.shop)
        if cfg.origin is None:
            raise ProviderRefused("The ship-from address isn't set up yet.", code="origin")
        return self._address(cfg.origin, origin=True)

    @staticmethod
    def _parcel(s: Shipment) -> dict[str, Any]:
        p = s.package
        if p is None:
            raise ProviderRefused("No package chosen for this order.", code="package")
        return {
            "total_actual_weight": round(p.total_weight_g / 1000, 3),
            "box": {
                "length": round(p.length_mm / 10, 1),
                "width": round(p.width_mm / 10, 1),
                "height": round(p.height_mm / 10, 1),
            },
            "items": [Easyship._item(ln) for ln in s.lines],
        }

    @staticmethod
    def _item(ln: CustomsLine) -> dict[str, Any]:
        out = {
            "description": ln.customs_description or ln.title,
            "hs_code": ln.hs_code,
            "origin_country_alpha2": ln.origin_country,
            # Easyship refuses a null SKU; without one, the Shopify variant stands in.
            "sku": ln.sku or _variant_ref(ln.variant_id),
            "quantity": ln.quantity,
            "declared_currency": ln.unit_value.currency,
            "declared_customs_value": float(ln.unit_value.minor) / 100,
        }
        return {k: v for k, v in out.items() if v not in (None, "")}

    def _rates_body(self, s: Shipment, service_ids: list[str] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "origin_address": self._origin(s),
            "destination_address": self._address(self._recipient(s)),
            "incoterms": "DDP" if s.duties and s.duties.incoterm == "DDP" else "DDU",
            "insurance": {"is_insured": False},
            "courier_settings": {"show_courier_logo_url": False, "apply_shipping_rules": False},
            "shipping_settings": {
                "units": {"weight": "kg", "dimensions": "cm"},
                "output_currency": s.currency,
            },
            "parcels": [self._parcel(s)],
            "calculate_tax_and_duties": False,
        }
        if service_ids:
            body["filter_options"] = {"courier_service_ids": service_ids}
        return body

    # ------------------------------------------------------------------ quotes (no money)

    def quotes(self, shipment: Shipment) -> list[Quote]:
        body = self._call("POST", "/rates", writes=False, json=self._rates_body(shipment))
        rows = body.get("rates")
        if not isinstance(rows, list):
            raise ProviderUnavailable("Easyship's rates answer had no rates list.")
        best: dict[str, Quote] = {}
        for row in rows:
            q = self._quote(shipment, row)
            if q is None:
                continue
            seen = best.get(q.service_code)  # the same service twice: keep the cheaper
            if seen is None or q.amount.minor < seen.amount.minor:
                best[q.service_code] = q
        return sorted(best.values(), key=lambda q: q.amount.minor)

    def _quote(self, s: Shipment, row: Any) -> Quote | None:
        if not isinstance(row, dict) or not isinstance(row.get("courier_service"), dict):
            log.warning("Easyship rate without a courier service skipped")
            return None
        cs = row["courier_service"]
        sid = str(cs.get("id") or "").strip()
        if not sid:
            return None
        if str(row.get("currency") or "") != s.currency:
            # Never compare prices across currencies; output_currency asks for ours.
            log.warning(
                "Easyship rate %s in %s skipped (shop: %s)", sid, row.get("currency"), s.currency
            )
            return None
        try:
            amount = _money(row.get("total_charge"), "rate", ProviderUnavailable)
        except ProviderUnavailable:
            log.warning("Easyship rate %s has no usable total_charge", sid)
            return None
        rating = row.get("tracking_rating")
        return Quote(
            provider=self.name,
            carrier=str(cs.get("umbrella_name") or cs.get("name") or "Courier"),
            service_code=SERVICE_PREFIX + sid,
            service_name=str(cs.get("name") or cs.get("umbrella_name") or "Service"),
            amount=Money(minor=amount, currency=s.currency),
            est_days_min=_days(row.get("min_delivery_time")),
            est_days_max=_days(row.get("max_delivery_time")),
            generated_at=self.clock(),
            tracked=None if not isinstance(rating, int | float) else rating >= 0,
            handover=_handover(row.get("available_handover_options")),
            billed_by=BILLED_BY.get(str(row.get("payment_recipient") or ""), ""),
        )

    @staticmethod
    def _service_id(quote: Quote) -> str:
        if not quote.service_code.startswith(SERVICE_PREFIX):
            raise ProviderRefused("That service isn't an Easyship service.", code="service")
        return quote.service_code[len(SERVICE_PREFIX) :]

    def _recipient(self, s: Shipment) -> Address:
        # The customer's phone and email, else the shop's (booking data, not saved anywhere).
        return contacts.recipient(s.destination, self.config(s.shop).origin)[0]

    def missing_contacts(self, s: Shipment) -> list[str]:
        """What Easyship needs to create a shipment and nothing can stand in for (after the
        store phone/email fallback). Quoting needs none of it."""
        o, d = self.config(s.shop).origin or Address(), self._recipient(s)
        missing = []
        for name, v in (("name", o.name or o.company), ("phone", o.phone), ("email", o.email)):
            if not v.strip():
                missing.append(f"Setup → Ship from {name}")
        if not (d.name or d.company).strip():
            missing.append("the customer's name")
        return missing

    def _require_contacts(self, s: Shipment) -> None:
        if missing := self.missing_contacts(s):
            raise ProviderRefused(
                f"Easyship needs {', '.join(missing)} to book a label", code="contacts"
            )

    def verify(self, shipment: Shipment, quote: Quote) -> int:
        """The exact price now: the same rates request, for this one service."""
        sid = self._service_id(quote)
        self._require_contacts(shipment)  # before the preview, so it can't fail at the purchase
        body = self._call("POST", "/rates", writes=False, json=self._rates_body(shipment, [sid]))
        for row in body.get("rates") or []:
            q = self._quote(shipment, row)
            if q is not None and q.service_code == quote.service_code:
                return q.amount.minor
        raise ProviderRefused(f"Easyship no longer offers {quote.title} for this parcel.")

    # ------------------------------------------------------------------ the purchase

    def create_order(self, shipment: Shipment, quote: Quote, reference: str) -> ProviderOrder:
        """A shipment for exactly this service, without a label: no money moves."""
        sid = self._service_id(quote)
        self._require_contacts(shipment)
        cfg = self.config(shipment.shop)
        body = self._rates_body(shipment)
        body.pop("calculate_tax_and_duties", None)
        if cfg.origin is not None:  # a shipment's sender must name a company
            body["origin_address"]["company_name"] = cfg.origin.company or cfg.origin.name
        body["courier_settings"] = {
            "courier_service_id": sid,
            "allow_fallback": False,
            "apply_shipping_rules": False,
        }
        body["shipping_settings"] = {
            "units": {"weight": "kg", "dimensions": "cm"},
            "output_currency": shipment.currency,
            "buy_label": False,
        }
        body["metadata"] = {"clive_operation": reference}
        body["order_data"] = {
            "platform_name": "CROOKS Shipping",
            "platform_order_number": shipment.order_name,
        }
        ids = {
            "eori": cfg.eori_number,
            "vat_number": cfg.vat_number,
            "ioss": shipment.duties.ioss_number if shipment.duties else None,
        }
        if any(ids.values()):
            body["regulatory_identifiers"] = {k: v for k, v in ids.items() if v}
        made = self._call("POST", "/shipments", writes=True, json=body)
        sh = _obj(made.get("shipment"))
        es_id = str(sh.get("easyship_shipment_id") or "")
        if not es_id:
            # Created or not, without an id it can never be paid.
            raise ProviderUncertain("Easyship's shipment answer had no shipment id.")
        if made.get("_status") == 202:
            raise ProviderRefused(f"Easyship created {es_id} but couldn't rate it.")
        chosen = sh.get("courier_service")
        if not isinstance(chosen, dict) or str(chosen.get("id")) != sid:
            raise ProviderRefused(f"Easyship didn't keep {quote.title} for {es_id}.")
        amount = self._shipment_price(sh, sid, shipment.currency)
        return ProviderOrder(
            ref=REF_PREFIX + es_id, amount_minor=amount, currency=shipment.currency
        )

    @staticmethod
    def _shipment_price(sh: dict[str, Any], sid: str, currency: str) -> int:
        for row in sh.get("rates") or []:
            cs = row.get("courier_service") if isinstance(row, dict) else None
            if isinstance(cs, dict) and str(cs.get("id")) == sid:
                if str(row.get("currency") or currency) != currency:
                    return 0  # never comparable; the protocol refuses a 0 price
                try:
                    return _money(row.get("total_charge"), "shipment", ProviderRefused)
                except ProviderRefused:
                    return 0
        return 0

    @staticmethod
    def _id(ref: str) -> str:
        if not ref.startswith(REF_PREFIX):
            raise ProviderRefused("Not an Easyship reference.", code="ref")
        return ref[len(REF_PREFIX) :]

    def pay(self, ref: str) -> None:
        """Buy the label. Called at most once per shipment, by the purchase protocol only."""
        try:
            body = self._call(
                "POST",
                f"/shipments/{self._id(ref)}/label",
                writes=True,
                json={
                    "printing_options": {
                        "format": "pdf",
                        "label": "4x6",
                        "commercial_invoice": "A4",
                        "packing_slip": "none",
                    }
                },
            )
        except ProviderRefused as exc:
            # The credit balance shown in Setup is only information (a saved card may pay);
            # Easyship's own refusal is what counts, and it says what to do.
            if exc.code == "402" or PAYMENT_WORDS.search(str(exc)):
                raise ProviderRefused(
                    f"{exc}. Add credit or a payment method in your Easyship account, then "
                    "buy again",
                    code="payment",
                ) from exc
            raise
        sh = _obj(body.get("shipment"))
        state = str(sh.get("label_state") or "")
        if not sh.get("label_paid_at") and state not in BOUGHT_STATES:
            # A 2xx that doesn't show a bought label: the read-back decides, never a retry.
            raise ProviderUncertain(f"Easyship answered but the label is '{state or 'unknown'}'.")

    def discard(self, ref: str) -> None:
        """Delete a shipment that has no label (the dry run's booking probe). Easyship refuses
        to delete one with a label, so this can never undo or lose a purchase."""
        self._call("DELETE", f"/shipments/{self._id(ref)}", writes=True)

    def _shipment(self, ref: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        body = self._call("GET", f"/shipments/{self._id(ref)}", writes=False, params=params)
        sh = body.get("shipment")
        if not isinstance(sh, dict):
            raise ProviderUnavailable("Easyship's shipment answer had no shipment.")
        return sh

    def read_order(self, ref: str) -> OrderReadback:
        sh = self._shipment(ref)
        sid = str((sh.get("courier_service") or {}).get("id") or "")
        paid = bool(sh.get("label_paid_at")) or str(sh.get("label_state") or "") in BOUGHT_STATES
        amount = self._shipment_price(sh, sid, str(sh.get("currency") or "GBP")) or None
        return OrderReadback(paid=paid, amount_minor=amount)

    # ------------------------------------------------------------------ after the purchase

    def documents(self, ref: str) -> Documents:
        sh = self._shipment(
            ref,
            {"format": "PDF", "label": "4x6", "commercial_invoice": "A4", "packing_slip": "none"},
        )
        state = str(sh.get("label_state") or "")
        if not sh.get("label_paid_at") and state not in BOUGHT_STATES:
            raise ProviderRefused("Easyship says the label isn't bought.", code="unpaid")
        if state not in READY_STATES:
            raise ProviderUnavailable(f"Easyship is still making the label ({state}).")
        docs: list[ProviderDocument] = []
        invoice = False
        cn23 = False
        for d in sh.get("shipping_documents") or []:
            if not isinstance(d, dict):
                continue
            category = str(d.get("category") or "")
            body = self._decode(d.get("base64_encoded_strings"))
            if category == "label":
                if not is_pdf(body):
                    raise ProviderUnavailable("Easyship's label file wasn't a PDF yet.")
                assert body is not None
                includes_cn23 = easyship_cn23(body)
                cn23 = cn23 or includes_cn23
                docs.append(
                    ProviderDocument(
                        kind=DocumentKind.shipping_label,
                        body=body,
                        page_size=page_size(body),
                        pages=pdf_pages(body),
                        copies_required=1,
                        note=CN23_NOTE if includes_cn23 else "",
                        must_print=True,
                        attach_to_parcel=True,
                    )
                )
            elif category == "commercial_invoice" and (d.get("required") is not False):
                invoice = True
                docs.append(
                    ProviderDocument(
                        kind=DocumentKind.commercial_invoice,
                        body=body,
                        page_size=page_size(body) if body else PageSize.a4,
                        pages=pdf_pages(body) if body else 0,
                        copies_required=1,
                        must_print=True,
                        attach_to_parcel=True,
                        note="Easyship doesn't say how many copies; print one and attach it "
                        "in a document pouch unless the courier asks for more.",
                    )
                )
        if not any(d.kind == DocumentKind.shipping_label for d in docs):
            raise ProviderUnavailable("Easyship hasn't attached the label file yet.")
        # A separate invoice or a positively identified bundled CN23 is paper customs.
        # Otherwise retain Easyship's existing electronic-customs assumption.
        customs = CustomsMode.paper if invoice or cn23 else CustomsMode.electronic
        number, _ = self._tracking(sh)
        from shipping.providers.parcel2go import safe_link

        return Documents(
            documents=docs,
            customs=customs,
            tracking_number=number,
            tracking_url=safe_link(sh.get("tracking_page_url")),
            provider_ids={"shipment": str(sh.get("easyship_shipment_id") or self._id(ref))},
        )

    @staticmethod
    def _decode(parts: Any) -> bytes | None:
        if not isinstance(parts, list) or not parts:
            return None
        try:
            return base64.b64decode(str(parts[0]), validate=False)
        except (binascii.Error, ValueError):
            return None

    @staticmethod
    def _tracking(sh: dict[str, Any]) -> tuple[str | None, str | None]:
        legs = [t for t in sh.get("trackings") or [] if isinstance(t, dict)]
        legs.sort(key=lambda t: t.get("leg_number") or 0)
        for leg in legs:
            number = str(leg.get("tracking_number") or "").strip()
            if number:
                return number, str(leg.get("handler") or "") or None
        return None, None

    def tracking(self, ref: str) -> tuple[str | None, str | None]:
        """The carrier's tracking number and Easyship's tracking page, when they exist. A
        read: used to fill in a number that arrives after the label."""
        from shipping.providers.parcel2go import safe_link

        sh = self._shipment(ref)
        number, _ = self._tracking(sh)
        return number, safe_link(sh.get("tracking_page_url"))

    def cancel(self, ref: str) -> None:
        """Cancel the shipment (and its label) at Easyship. Consequential: the caller asks the
        merchant first. A lost reply is UNKNOWN; `cancelled()` reads the outcome."""
        self._call("POST", f"/shipments/{self._id(ref)}/cancel", writes=True)

    def cancelled(self, ref: str) -> bool:
        sh = self._shipment(ref)
        return (
            str(sh.get("shipment_state") or "") in ("cancelled", "cancelling")
            or str(sh.get("label_state") or "") == "voided"
        )

    def account(self) -> dict[str, Any]:
        """The credit balance, for Setup. A read."""
        body = self._call("GET", "/account/credit", writes=False)
        credit = _obj(body.get("credit"))
        return {
            "balance": credit.get("available_balance", credit.get("balance")),
            "currency": credit.get("currency"),
        }
