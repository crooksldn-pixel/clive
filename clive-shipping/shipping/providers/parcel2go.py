"""Parcel2Go, the v1 label provider (PrePay). Built to the published Swagger v1 and checked
against the sandbox (2026-10-04/05): quotes, exact-price verify, unpaid orders with customs
contents, pay, PaidDate read-back, label PDFs that include the commercial invoices.

Every failure is sorted into exactly one of the purchase protocol's three kinds:

  refused      Parcel2Go answered and said no (4xx, or Errors in a 200).
  unavailable  the request never got there (DNS, connection refused, connect timeout), or a
               read (GET) failed: reads never move money.
  uncertain    a POST was sent and the answer was lost (read timeout, dropped connection, 5xx).
               For pay this means "may have been charged": the protocol reconciles, never
               re-pays. Paying a paid order charges again (seen in the sandbox).
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Protocol

import httpx

from shipping.documents import (
    ENVELOPE,
    CustomsEvidence,
    customs_mode,
    is_pdf,
    page_size,
    pdf_pages,
)
from shipping.models import (
    Address,
    Country,
    CustomsMode,
    DocumentKind,
    PackagePlan,
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

log = logging.getLogger("shipping.parcel2go")


class ReferenceCache(Protocol):
    def reference(self, provider: str, kind: str) -> tuple[Any, datetime] | None: ...
    def put_reference(self, provider: str, kind: str, data: Any, at: datetime) -> None: ...


CARRIERS = {
    "myhermes": "Evri",
    "hermes": "Evri",
    "dpd": "DPD",
    "ups": "UPS",
    "parcelforce": "Parcelforce",
    "royal-mail": "Royal Mail",
    "dhl": "DHL",
    "fedex": "FedEx",
    "inpost": "InPost",
}


# Parcel2Go's names for the countries we print on customs invoices, where its list differs.
NAMES = {"UK - Mainland": "United Kingdom", "USA": "United States"}


def split_address(line1: str, line2: str = "") -> tuple[str, str]:
    """Parcel2Go needs a property (house name/number) AND a street. Shopify has two free-text
    lines. When there's only one, split the number off it the way it was written: "12 Brick
    Lane", "Torstrasse 12", "Via Roma 5, 2B". Only a line with no number at all
    ("Rose Cottage") goes into both."""
    line1, line2 = (line1 or "").strip(), (line2 or "").strip()
    if line1 and line2:
        return line1, line2
    line1 = line1 or line2
    m = re.match(r"^\s*(\d+[\w/-]*)[\s,]+(.+)$", line1)  # 12 Brick Lane
    if m:
        return m.group(1), m.group(2).strip()
    m = re.match(
        r"^(.*?\D)[\s,]+(\d+[\w/-]*(?:[\s,]+[\w.ºª°-]{1,4}){0,2})$", line1
    )  # Torstrasse 12, 2B
    if m:
        return m.group(2).strip(), m.group(1).strip(" ,")
    if "," in line1:
        first, rest = line1.split(",", 1)
        return first.strip(), rest.strip()
    return line1, line1


# Regions Parcel2Go prices separately. Its country list has a row for each, but its
# PostcodeRegex there is only a format check ("^.*$" for Madeira and Northern Ireland), so the
# region has to be worked out here: sent without it, the sandbox quotes Tenerife and Palermo as
# mainland Spain and Italy (2026-10-05). Longest prefix wins; the codes after the first are
# fallbacks. Corsica and the Balearics have no code: Parcel2Go prices them as the mainland.
REGIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "ES": {
        "35": ("ES-GRC", "ES-GC"),  # Las Palmas province: Gran Canaria unless below
        "355": ("ES-LZ", "ES-GC"),  # Lanzarote, La Graciosa
        "356": ("ES-FU", "ES-GC"),  # Fuerteventura
        "38": ("ES-TEN", "ES-GC"),  # Santa Cruz de Tenerife province: Tenerife unless below
        "387": ("ES-LP", "ES-GC"),  # La Palma
        "388": ("ES-LG", "ES-GC"),  # La Gomera
        "389": ("ES-EH", "ES-GC"),  # El Hierro
        "51": ("ES-CE",),
        "52": ("ES-ML",),
    },
    "PT": {
        **{p: ("PT-30",) for p in ("90", "91", "92", "93", "94")},  # Madeira, Porto Santo
        **{p: ("PT-20",) for p in ("95", "96", "97", "98", "99")},  # Azores
    },
    "IT": {
        **{p: ("IT-SI",) for p in ("90", "91", "92", "93", "94", "95", "96", "97", "98")},
        **{p: ("IT-SA",) for p in ("07", "08", "09")},
    },
}
# UK regions by postcode area and district (only the merchant's origin can be in the UK).
UK_REGIONS: dict[str, tuple[str, list[tuple[int, int]] | None]] = {
    "BT": ("NIR", None),
    "IM": ("IOM", None),
    "HS": ("HIGH", None),
    "IV": ("HIGH", None),
    "KW": ("HIGH", None),
    "ZE": ("HIGH", None),
    "PA": ("HIGH", [(20, 49), (60, 78)]),
    "PH": ("HIGH", [(17, 26), (30, 44), (49, 50)]),
    "KA": ("HIGH", [(27, 28)]),
}


def region(iso2: str, postcode: str) -> tuple[str, ...]:
    """Parcel2Go region codes for this postcode, best first; () for the mainland."""
    iso2, pc = (iso2 or "").upper(), (postcode or "").strip().upper()
    if iso2 == "GB":
        m = re.match(r"^([A-Z]{1,2})(\d{1,2})", pc)
        if not m or m.group(1) not in UK_REGIONS:
            return ()
        code, districts = UK_REGIONS[m.group(1)]
        n = int(m.group(2))
        if districts is None or any(lo <= n <= hi for lo, hi in districts):
            return (code,)
        return ()
    digits = re.sub(r"\D", "", pc)
    rules = REGIONS.get(iso2, {})
    best = max((p for p in rules if digits.startswith(p)), key=len, default=None)
    return rules[best] if best else ()


def _errors(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return r.text[:300] or f"HTTP {r.status_code}"
    if isinstance(body, dict):
        errs = body.get("Errors") or body.get("errors")
        if errs:
            return "; ".join(
                str(e.get("Error") or e.get("Description") or e.get("Name") or e) for e in errs
            )[:400]
        if body.get("Message"):
            return str(body["Message"])[:300]
    return str(body)[:300]


def _price(value: Any, what: str, error: type[ProviderError]) -> int:
    """A price in pence. Missing, malformed or not positive is an error, never 0."""
    try:
        minor = to_minor(value) if value not in (None, "") else None
    except ArithmeticError:
        minor = None
    if minor is None or minor <= 0:
        raise error(f"Parcel2Go's {what} answer had no usable price ({value!r}).")
    return minor


def next_working_day(today: date) -> date:
    d = today + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


class Parcel2Go:
    name = "Parcel2Go"

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        config: Callable[[str], ShopConfig],
        http: httpx.Client | None = None,
        clock: Callable[[], datetime] = now,
        cache: ReferenceCache | None = None,
        countries_ttl: timedelta = timedelta(days=7),
    ) -> None:
        self.base = base_url.rstrip("/")
        self.cache, self.countries_ttl = cache, countries_ttl
        self.client_id, self.client_secret = client_id, client_secret
        self.config = config
        self.clock = clock
        self._http = http or httpx.Client(timeout=httpx.Timeout(30, connect=10))
        self._token: tuple[str, float] | None = None
        self._countries: list[dict[str, Any]] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ plumbing

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token[1] - 120:
                return self._token[0]
            try:
                r = self._http.post(
                    f"{self.base}/auth/connect/token",
                    data={
                        "grant_type": "client_credentials",
                        "scope": "public-api payment",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(f"Parcel2Go could not be reached ({exc})") from exc
            if r.status_code != 200:
                raise ProviderUnavailable(
                    f"Parcel2Go refused the API credentials ({r.status_code})", code="auth"
                )
            try:
                body = r.json()
                self._token = (
                    str(body["access_token"]),
                    time.time() + int(body.get("expires_in", 3600)),
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise ProviderUnavailable("Parcel2Go sent an unreadable token answer.") from exc
            return self._token[0]

    def _call(self, method: str, path: str, **kw: Any) -> Any:
        writes = method != "GET"
        headers = {"Authorization": f"Bearer {self._access_token()}", "Accept": "application/json"}
        try:
            r = self._http.request(method, f"{self.base}/api{path}", headers=headers, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise ProviderUnavailable(f"Parcel2Go could not be reached ({exc})") from exc
        except httpx.HTTPError as exc:
            if writes:
                raise ProviderUncertain(f"Parcel2Go's answer was lost ({exc})") from exc
            raise ProviderUnavailable(f"Parcel2Go didn't answer ({exc})") from exc
        if r.status_code >= 500:
            if writes:
                raise ProviderUncertain(f"Parcel2Go failed while handling it ({r.status_code})")
            raise ProviderUnavailable(f"Parcel2Go is having problems ({r.status_code})")
        if r.status_code >= 400:
            raise ProviderRefused(_errors(r), code=str(r.status_code))
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError as exc:
            # The provider did something and answered with garbage. For a write that may
            # have taken effect, that is "unknown"; for a read it is just "not available".
            if writes:
                raise ProviderUncertain(f"Parcel2Go's answer to {path} was unreadable.") from exc
            raise ProviderUnavailable(f"Parcel2Go's answer to {path} was unreadable.") from exc

    @staticmethod
    def _split(ref: str) -> tuple[str, str, str]:
        _, order_id, line_id, order_hash = ref.split(":", 3)
        return order_id, line_id, order_hash

    def countries(self) -> list[dict[str, Any]]:
        """Parcel2Go's own country list. One country can have several rows: the main one (no
        Subdivision) and separately priced regions (Madeira, Canaries, Northern Ireland...).
        Which region a postcode is in comes from REGIONS, not from these rows.

        Cached (in memory, and in the store when one is given) for `countries_ttl`; when
        Parcel2Go can't be reached, a stale copy is used rather than nothing."""
        if self._countries is not None:
            return self._countries
        cached = self.cache.reference(self.name, "countries") if self.cache else None
        if cached and self.clock() - cached[1] < self.countries_ttl:
            self._countries = cached[0]
            return cached[0]
        try:
            rows = self._call("GET", "/countries")
            if not isinstance(rows, list):
                raise ProviderUnavailable("Parcel2Go sent an unexpected country list.")
            fresh = [c for c in rows if isinstance(c, dict) and c.get("Iso2Code")]
            if not fresh:
                raise ProviderUnavailable("Parcel2Go sent an empty country list.")
        except ProviderError:
            if cached:
                log.warning("Parcel2Go countries unavailable; using the copy from %s", cached[1])
                self._countries = cached[0]
                return cached[0]
            raise
        if self.cache:
            self.cache.put_reference(self.name, "countries", fresh, self.clock())
        self._countries = fresh
        return fresh

    def place(self, iso2: str, postcode: str = "") -> Country:
        """A country as CLIVE models it, with Parcel2Go's region code for this postcode."""
        found = self._main(iso2)
        if not found:
            raise ProviderRefused(f"Parcel2Go doesn't deliver to {iso2}.", code="country")
        return Country(
            iso2=iso2.upper(),
            iso3=found["Iso3Code"],
            name=self._country_name(iso2),
            subdivision=self._subdivision(iso2, postcode) if postcode else None,
        )

    def _main(self, iso2: str) -> dict[str, Any] | None:
        rows = [c for c in self.countries() if c["Iso2Code"].upper() == (iso2 or "").upper()]
        return next((c for c in rows if not c.get("Subdivision")), rows[0] if rows else None)

    def _iso3(self, iso2: str) -> str:
        found = self._main(iso2)
        if not found:
            raise ProviderRefused(f"Parcel2Go doesn't deliver to {iso2}.", code="country")
        return found["Iso3Code"]

    def _subdivision(self, iso2: str, postcode: str) -> str | None:
        """The separately priced region this postcode is in (e.g. PT-30 for Madeira), as one of
        Parcel2Go's own codes, or None for the mainland."""
        wanted = region(iso2, postcode)
        if not wanted:
            return None
        listed = {c.get("Subdivision") for c in self.countries() if c.get("Subdivision")}
        found = next((code for code in wanted if code in listed), None)
        if not found:
            # Quoting it as the mainland would buy the wrong service at the wrong price.
            raise ProviderRefused(
                f"Postcode {postcode} is in a region Parcel2Go no longer lists ({wanted[0]}).",
                code="region",
            )
        return found

    def _region(self, iso2: str, postcode: str) -> dict[str, str]:
        code = self._subdivision(iso2, postcode)
        return {"Subdivision": code} if code else {}

    def _country_name(self, iso2: str) -> str:
        found = self._main(iso2)
        if not found:
            return iso2
        name = found["Name"]
        return NAMES.get(name) or re.sub(r"\s*\(.*\)\s*$", "", name)

    # ------------------------------------------------------------------ addresses

    def _origin(self, cfg: ShopConfig) -> dict[str, Any]:
        o = cfg.origin or Address()
        return {
            "ContactName": "CROOKS LDN" if not o.name else o.name,
            "Organisation": o.company or o.name,
            "Email": o.email or None,
            "Phone": o.phone or None,
            "Property": split_address(o.line1, o.line2)[0],
            "Street": split_address(o.line1, o.line2)[1],
            "Town": o.city,
            "County": o.region or None,
            "Postcode": o.postcode,
            "CountryIsoCode": self._iso3(o.country or "GB"),
            **self._region(o.country or "GB", o.postcode),
        }

    def _destination(self, d: Address) -> dict[str, Any]:
        return {
            "ContactName": d.name or d.company,
            "Organisation": d.company or None,
            "Email": d.email or None,
            "Phone": d.phone or None,
            "Property": split_address(d.line1, d.line2)[0],
            "Street": split_address(d.line1, d.line2)[1],
            "Town": d.city,
            "County": d.region or None,
            "Postcode": d.postcode,
            "CountryIsoCode": self._iso3(d.country),
            **self._region(d.country, d.postcode),
        }

    @staticmethod
    def _package(s: Shipment) -> PackagePlan:
        if s.package is None:
            raise ProviderRefused("No package is chosen for this shipment yet.", code="package")
        return s.package

    @classmethod
    def _parcel(cls, s: Shipment) -> dict[str, Any]:
        p = cls._package(s)
        return {
            "Weight": round(p.total_weight_g / 1000, 2),
            "Length": p.length_mm / 10,
            "Width": p.width_mm / 10,
            "Height": p.height_mm / 10,
        }

    @staticmethod
    def _value(s: Shipment) -> float:
        return sum(ln.unit_value.minor * ln.quantity for ln in s.lines) / 100

    # ------------------------------------------------------------------ quotes

    def quotes(self, shipment: Shipment) -> list[Quote]:
        cfg = self.config(shipment.shop)
        origin = cfg.origin or Address(country="GB")
        body = {
            "CollectionAddress": {
                "Country": self._iso3(origin.country or "GB"),
                "Postcode": origin.postcode,
                **self._region(origin.country or "GB", origin.postcode),
            },
            "DeliveryAddress": {
                "Country": self._iso3(shipment.destination.country),
                "Postcode": shipment.destination.postcode,
                **self._region(shipment.destination.country, shipment.destination.postcode),
            },
            "Parcels": [{**self._parcel(shipment), "Value": self._value(shipment)}],
        }
        try:
            answer = self._call("POST", "/quotes", json=body)
        except ProviderUncertain as exc:  # quoting never spends: a lost answer is just missing
            raise ProviderUnavailable(str(exc)) from exc
        if not isinstance(answer, dict):
            raise ProviderUnavailable("Parcel2Go sent an unexpected quotes answer.")
        out = []
        for q in answer.get("Quotes") or []:
            try:
                quote = self._quote(shipment, q)
            except (
                KeyError,
                TypeError,
                ValueError,
                ArithmeticError,
                AttributeError,
                ProviderError,
            ) as exc:
                log.warning("skipping an unreadable Parcel2Go quote: %s", exc)
                continue
            if quote is not None:
                out.append(quote)
        return out

    def _quote(self, shipment: Shipment, q: dict[str, Any]) -> Quote | None:
        svc = q.get("Service") or {}
        if svc.get("DeliveryType") not in (None, "Door") or not self._fits(shipment, svc):
            return None
        slug = (svc.get("CourierSlug") or "").lower()
        carrier = next(
            (v for k, v in CARRIERS.items() if k in slug), svc.get("CourierName") or slug
        )
        days = None
        if q.get("EstimatedDeliveryDate") and q.get("Collection"):
            days = max(
                1,
                (
                    date.fromisoformat(q["EstimatedDeliveryDate"][:10])
                    - date.fromisoformat(q["Collection"][:10])
                ).days,
            )
        return Quote(
            provider=self.name,
            carrier=carrier,
            service_code=svc["Slug"],
            service_name=(svc.get("Name") or svc["Slug"]).replace("myHermes", "Evri"),
            amount=Money(minor=_price(q.get("TotalPrice"), "quote", ProviderUnavailable)),
            est_days_max=days,
            printer_required=bool(svc.get("IsPrinterRequired", True)),
            ship_date=(q.get("Collection") or "")[:10] or None,
            generated_at=self.clock(),
        )

    @classmethod
    def _fits(cls, s: Shipment, svc: dict[str, Any]) -> bool:
        p = cls._package(s)
        weight = p.total_weight_g / 1000
        if svc.get("MaxWeight") and weight > float(svc["MaxWeight"]):
            return False
        limits = sorted(
            float(svc[k]) * 100 for k in ("MaxLength", "MaxWidth", "MaxHeight") if svc.get(k)
        )
        if len(limits) < 3:
            return True
        dims = sorted([p.length_mm / 10, p.width_mm / 10, p.height_mm / 10])
        return all(a <= b for a, b in zip(dims, limits, strict=True))

    # ------------------------------------------------------------------ the order

    def _order(self, s: Shipment, quote: Quote, reference: str) -> dict[str, Any]:
        cfg = self.config(s.shop)
        ship = quote.ship_date or next_working_day(self.clock().date()).isoformat()
        item: dict[str, Any] = {
            "Id": str(uuid.uuid4()),
            "CollectionDate": f"{ship}T09:00:00+00:00",
            "OriginCountry": self._iso3((cfg.origin.country if cfg.origin else "") or "GB"),
            "Service": quote.service_code,
            "Reference": f"{s.order_name} {reference}"[:50],
            "ExportReason": "Sale",
            "CollectionAddress": self._origin(cfg),
            "Parcels": [
                {
                    "Id": str(uuid.uuid4()),
                    **self._parcel(s),
                    "EstimatedValue": self._value(s),
                    "DeliveryAddress": self._destination(s.destination),
                    "ContentsSummary": ", ".join(
                        sorted({ln.customs_description for ln in s.lines})
                    )[:100],
                    "Contents": [
                        {
                            "Description": ln.customs_description[:100],
                            "Quantity": ln.quantity,
                            "EstimatedValue": float(ln.unit_value.minor * ln.quantity) / 100,
                            "TariffCode": ln.hs_code,
                            # Parcel2Go wants the country's name here, not its code.
                            "OriginCountry": self._country_name(ln.origin_country or ""),
                        }
                        for ln in s.lines
                    ],
                }
            ],
        }
        if s.duties and s.duties.ioss_number:
            item["IOSSCode"] = s.duties.ioss_number
        if cfg.eori_number:
            item["EoriNumber"] = cfg.eori_number
        if cfg.vat_number:
            item["VatNumber"], item["VatStatus"] = cfg.vat_number, "Registered"
        origin = cfg.origin or Address()
        return {
            "Items": [item],
            "CustomerDetails": {
                "Email": origin.email or "",
                "Forename": "CROOKS",
                "Surname": "LDN",
                "Reference": reference,
            },
        }

    def verify(self, shipment: Shipment, quote: Quote) -> int:
        try:
            body = self._call("POST", "/orders/verify", json=self._order(shipment, quote, "verify"))
        except ProviderUncertain as exc:  # verify never spends: a lost answer is just missing
            raise ProviderUnavailable(str(exc)) from exc
        if not isinstance(body, dict):
            raise ProviderUnavailable("Parcel2Go sent an unexpected price check answer.")
        errors = body.get("Errors") or []
        if errors:
            raise ProviderRefused(
                "; ".join(str(e.get("Error") if isinstance(e, dict) else e) for e in errors)[:400]
            )
        return _price(body.get("Cost"), "price check", ProviderUnavailable)

    def create_order(self, shipment: Shipment, quote: Quote, reference: str) -> ProviderOrder:
        made = self._call("POST", "/orders", json=self._order(shipment, quote, reference))
        if not isinstance(made, dict):
            raise ProviderUncertain("Parcel2Go's order answer was unreadable; nothing was paid.")
        order_id, order_hash = str(made.get("OrderId") or ""), str(made.get("Hash") or "")
        if not order_id or not order_hash:
            raise ProviderRefused(f"Parcel2Go created no usable order: {str(made)[:200]}")
        try:
            line = str(((made.get("OrderlineIdMap") or [{}])[0]).get("OrderLineId") or "")
        except (AttributeError, IndexError, TypeError):
            line = ""
        # An order whose price we can't read is never paid: the price is the authorisation.
        amount = _price(made.get("TotalPrice"), "order", ProviderUncertain)
        return ProviderOrder(
            ref=f"p2g:{order_id}:{line}:{order_hash}", amount_minor=amount, currency="GBP"
        )

    def pay(self, ref: str) -> None:
        order_id, _, order_hash = self._split(ref)
        paid = self._call("POST", f"/orders/{order_id}/paywithprepay", params={"hash": order_hash})
        if isinstance(paid, dict) and paid.get("Errors"):
            raise ProviderRefused(
                "; ".join(e.get("Description") or e.get("Name") or "" for e in paid["Errors"])
            )

    def read_order(self, ref: str) -> OrderReadback:
        order_id, _, order_hash = self._split(ref)
        got = self._call("GET", "/orders", params={"orderId": order_id, "hash": order_hash})
        if not isinstance(got, dict) or "PaidDate" not in got:
            # Without the field we can't tell paid from unpaid: say nothing rather than "no".
            raise ProviderUnavailable("Parcel2Go's order answer didn't say whether it was paid.")
        try:
            amount = to_minor(got.get("TotalPrice"))
        except ArithmeticError:
            amount = None
        return OrderReadback(paid=bool(got.get("PaidDate")), amount_minor=amount)

    def documents(self, ref: str) -> Documents:
        """The paid order's genuine 4x6 label and its customs paperwork, classified.

        Endpoints (sandbox-verified 2026-10-05): GET /labels/{orderId} with detailLevel
        Labels + labelMedia Label4X6 is a single 100x150 mm page (the order's "labels-4x6" link
        is not: it mixes A4 pages in). AdditionalDocuments is 404 when nothing must be printed,
        else the invoice copies to attach; CommercialInvoice is one A4 page; All is label +
        invoice + additional. Paperless needs AdditionalDocuments and All to agree."""
        order_id, line_id, order_hash = self._split(ref)
        got = self._call("GET", "/orders", params={"orderId": order_id, "hash": order_hash}) or {}
        if not isinstance(got, dict) or not got.get("PaidDate"):
            raise ProviderRefused("The order isn't paid, so it has no label.")
        labels = self._labels(order_id, order_hash, "Labels", "Label4X6")
        label = next((b for b in labels if is_pdf(b)), None)
        if label is None:
            raise ProviderUnavailable("The label isn't ready yet.")
        docs = [
            ProviderDocument(
                kind=DocumentKind.shipping_label,
                body=label,
                page_size=page_size(label),
                pages=pdf_pages(label),
                copies_required=1,
                must_print=True,
                attach_to_parcel=True,
            )
        ]

        def pages(detail: str) -> tuple[int | None, bytes | None]:
            try:
                found = self._labels(order_id, order_hash, detail, "A4")
            except ProviderError as exc:
                log.info("%s for order %s: %s", detail, order_id, exc)
                return None, None
            pdfs = [b for b in found if is_pdf(b)]
            if len(pdfs) != len(found):
                return None, None  # something that isn't a PDF: can't count it
            return sum(pdf_pages(b) for b in pdfs), (pdfs[0] if pdfs else None)

        additional, extra_pdf = pages("AdditionalDocuments")
        invoice_pages, invoice_pdf = pages("CommercialInvoice")
        all_pages, _ = pages("All")
        evidence = CustomsEvidence(
            route_requires_customs=self._requires_customs(got),
            additional_pages=additional,
            invoice_pages=invoice_pages,
            label_pages=pdf_pages(label) or None,
            all_pages=all_pages,
        )
        mode, copies = customs_mode(evidence)
        if mode == CustomsMode.paper and extra_pdf is not None:
            per_copy = invoice_pages or 1
            invoices = copies % per_copy == 0
            docs.append(
                ProviderDocument(
                    kind=DocumentKind.commercial_invoice
                    if invoices
                    else DocumentKind.other_documents,
                    body=extra_pdf,
                    page_size=page_size(extra_pdf),
                    pages=copies,
                    copies_required=copies // per_copy if invoices else 1,
                    must_print=True,
                    attach_to_parcel=True,
                    note=ENVELOPE,
                )
            )
        elif invoice_pdf is not None and mode != CustomsMode.unknown:
            docs.append(  # kept for the record; the courier has the data
                ProviderDocument(
                    kind=DocumentKind.commercial_invoice,
                    body=invoice_pdf,
                    page_size=page_size(invoice_pdf),
                    pages=invoice_pages or 0,
                    electronic=mode == CustomsMode.electronic,
                )
            )
        links = {str(k).lower(): v for k, v in (got.get("Links") or {}).items() if v}
        courier = self._courier_tracking(order_id)
        return Documents(
            documents=docs,
            customs=mode,
            # Until the courier's number exists (none in the sandbox), Parcel2Go's own.
            tracking_number=courier or (f"P2G{line_id}" if line_id else None),
            tracking_url=links.get("tracking-page")
            or (f"https://www.parcel2go.com/tracking/{line_id}" if line_id else None),
            provider_ids={"order": order_id, "order_line": line_id}
            | ({"courier_tracking": courier} if courier else {}),
        )

    def _labels(self, order_id: str, order_hash: str, detail: str, media: str) -> list[bytes]:
        """Documents at one detail level, decoded. [] when Parcel2Go has none (404)."""
        try:
            body = self._call(
                "GET",
                f"/labels/{order_id}",
                params={
                    "referenceType": "OrderId",
                    "detailLevel": detail,
                    "labelMedia": media,
                    "labelFormat": "PDF",
                    "hash": order_hash,
                },
            )
        except ProviderRefused as exc:
            if exc.code == "404":
                return []
            raise
        if not isinstance(body, dict):
            raise ProviderUnavailable(f"Parcel2Go sent an unexpected {detail} answer.")
        out = []
        for encoded in body.get("Base64EncodedLabels") or []:
            try:
                out.append(base64.b64decode(encoded, validate=True))
            except (binascii.Error, ValueError, TypeError) as exc:
                raise ProviderUnavailable(f"Parcel2Go sent an unreadable {detail}.") from exc
        return out

    def _requires_customs(self, order: dict[str, Any]) -> bool:
        """From the order's delivery country and Parcel2Go's own country list. When in doubt,
        yes: the cost of that answer is checking paperwork, not a parcel stuck at customs."""
        try:
            iso3 = order["Items"][0]["Parcels"][0]["DeliveryAddress"]["CountryIsoCode"]
        except (KeyError, IndexError, TypeError):
            return True
        rows = [c for c in self.countries() if c.get("Iso3Code") == iso3]
        return any(c.get("RequiresCustoms", True) is not False for c in rows) or not rows

    def _courier_tracking(self, order_id: str) -> str | None:
        try:
            numbers = self._call("POST", f"/orders/{order_id}/parcelnumbers") or {}
            return next(
                (
                    t.get("TrackingNumber")
                    for t in (numbers.get("TrackingNumbers") or [])
                    if isinstance(t, dict) and t.get("TrackingNumber")
                ),
                None,
            )
        except (ProviderError, AttributeError) as exc:
            log.info("tracking for %s not ready: %s", order_id, exc)
            return None


def balance(provider: Parcel2Go) -> Money | None:
    try:
        return Money(minor=to_minor(provider._call("GET", "/prepay")))
    except (ProviderRefused, ProviderUnavailable):
        return None
