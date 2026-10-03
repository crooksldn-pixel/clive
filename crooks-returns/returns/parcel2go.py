"""Return labels through Parcel2Go, paid from the CROOKS PrePay balance.

A return is booked as a drop-off parcel FROM the customer's address TO the CROOKS returns
address, on a service the customer can use without a printer: they show a QR code at an
InPost or Evri shop (or a Post Office). Built to the published Parcel2Go API (Swagger v1):

    POST /auth/connect/token            client credentials, scope "public-api payment"
    POST /api/quotes                    services and prices for this parcel and route
    GET  /api/dropshops/{code}/location nearest drop-off shops to a postcode
    POST /api/orders                    an unpaid order
    POST /api/orders/{id}/paywithprepay pay it; the answer links the label and the QR code
    POST /api/orders/{id}/parcelnumbers the courier's tracking number

There is no cancel in the API: an unused label is refunded by asking Parcel2Go, so a label is
only bought when staff approve the return.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from returns.labels import Label, LabelError
from returns.models import Return, to_amount, to_pence
from returns.settings import Settings

log = logging.getLogger("returns.parcel2go")

ISO3 = {"GB": "GBR", "IE": "IRL", "JE": "JEY", "GG": "GGY", "IM": "IMN"}
# Our courier names -> Parcel2Go courier slugs (Evri still trades as "myhermes" there).
COURIERS = {
    "evri": ("evri", "myhermes"),
    "inpost": ("inpost",),
    "royal-mail": ("royal-mail", "royalmail"),
    "collectplus": ("collectplus",),
}
NAMES = {"evri": "Evri", "inpost": "InPost", "royal-mail": "Royal Mail", "collectplus": "Collect+"}
# Shop and locker services, which the customer walks to. Collection services need them in.
DROP_OFF = {"Shop", "Locker"}


@dataclass
class DropShop:
    name: str
    address: str
    postcode: str
    distance_m: int | None
    hours: str = ""


@dataclass
class DropOption:
    """One way the customer can send their return, for them to choose from."""

    courier: str  # Parcel2Go courier slug, e.g. "inpost"
    courier_name: str
    service: str  # service slug, what gets booked
    service_name: str
    price_pence: int  # what CROOKS pays, inc VAT
    price_ex_vat_pence: int
    printer: bool  # the customer has to print a label
    locker: bool
    drop_off_code: str | None
    print_in_store: bool = False  # book with Parcel2Go's in-store QR code
    shops: list[DropShop] = field(default_factory=list)


def split_property(line1: str) -> tuple[str, str]:
    """ "12 Brick Lane" -> ("12", "Brick Lane"); "Flat 3, Rose House" stays whole."""
    found = re.match(r"^\s*(\d+[a-zA-Z]?)[\s,]+(.+)$", line1 or "")
    return (found.group(1), found.group(2).strip()) if found else (line1 or "", "")


class Parcel2Go:
    name = "Parcel2Go"

    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self.s = settings
        self.base = settings.p2g_base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=30)
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ plumbing

    def available(self) -> tuple[bool, str]:
        if not (self.s.p2g_client_id and self.s.p2g_client_secret):
            return False, "Parcel2Go is not connected (no API credentials)."
        if not (self.s.returns_address_line1 and self.s.returns_address_postcode):
            return False, "No returns address is set for the labels to come back to."
        return True, ""

    @property
    def sandbox(self) -> bool:
        return "sandbox" in self.base

    def token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token[1] - 120:
                return self._token[0]
            try:
                r = self._http.post(
                    f"{self.base}/auth/connect/token",
                    data={
                        "grant_type": "client_credentials",
                        "scope": "public-api payment",
                        "client_id": self.s.p2g_client_id,
                        "client_secret": self.s.p2g_client_secret,
                    },
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise LabelError(f"Parcel2Go could not be reached: {exc}") from exc
            if r.status_code != 200:
                raise LabelError(
                    f"Parcel2Go refused the API credentials ({r.status_code}). Check the client "
                    f"id and secret are for {'the sandbox' if self.sandbox else 'the live site'}."
                )
            body = r.json()
            self._token = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
            return self._token[0]

    def _call(self, method: str, path: str, **kw: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token()}", "Accept": "application/json"}
        try:
            r = self._http.request(method, f"{self.base}/api{path}", headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise LabelError(f"Parcel2Go could not be reached: {exc}") from exc
        if r.status_code >= 400:
            raise LabelError(f"Parcel2Go answered {r.status_code} to {path}: {_errors(r)}")
        return r.json() if r.content else None

    # ------------------------------------------------------------------ addresses

    def our_address(self) -> dict[str, Any]:
        s = self.s
        town, _, county = (s.returns_address_city or "").partition(",")
        return {
            "ContactName": s.returns_address_name,
            "Organisation": "CROOKS LDN",
            "Email": s.returns_contact_email or None,
            "Phone": s.returns_contact_phone or None,
            "Property": s.returns_address_line1,
            "Street": s.returns_address_line2 or s.returns_address_line1,
            "Town": town.strip(),
            "County": county.strip() or None,
            "Postcode": s.returns_address_postcode,
            "CountryIsoCode": ISO3.get(s.returns_address_country.upper(), "GBR"),
        }

    def customer_address(self, ret: Return, address: dict[str, Any]) -> dict[str, Any]:
        country = (address.get("countryCodeV2") or "GB").upper()
        if country != "GB":
            raise LabelError("Return labels are UK only. Ask the customer to post it themselves.")
        prop, street = split_property(address.get("address1") or "")
        if not street:
            prop, street = address.get("address1") or "", address.get("address2") or ""
        elif address.get("address2"):
            street = f"{street}, {address['address2']}"
        name = " ".join(x for x in (address.get("firstName"), address.get("lastName")) if x)
        return {
            "ContactName": name or ret.customer_name or "Customer",
            "Email": ret.customer_email or None,
            # Parcel2Go insists on a sender phone; ours if the customer gave none.
            "Phone": address.get("phone") or self.s.returns_contact_phone or None,
            "Property": prop,
            "Street": street or prop,
            "Town": address.get("city") or "",
            "County": address.get("province") or None,
            "Postcode": address.get("zip") or "",
            "CountryIsoCode": "GBR",
        }

    def _parcel(self, value_pence: int) -> dict[str, Any]:
        length, width, height = self.s.parcel_size()
        return {
            "Weight": round(self.s.parcel_weight_grams / 1000, 2),
            "Length": length,
            "Width": width,
            "Height": height,
            "Value": float(to_amount(value_pence)),
        }

    # ------------------------------------------------------------------ choosing

    def quotes(self, postcode: str, value_pence: int = 2500) -> list[dict[str, Any]]:
        our = self.our_address()
        body = {
            "CollectionAddress": {"Country": "GBR", "Postcode": postcode},
            "DeliveryAddress": {"Country": "GBR", "Postcode": our["Postcode"]},
            "Parcels": [self._parcel(value_pence)],
        }
        return (self._call("POST", "/quotes", json=body) or {}).get("Quotes") or []

    def options(
        self, postcode: str, value_pence: int = 2500, with_shops: bool = True
    ) -> list[DropOption]:
        """The cheapest no-printer drop-off service per preferred courier, best first."""
        found: dict[str, DropOption] = {}
        for q in self.quotes(postcode, value_pence):
            svc = q.get("Service") or {}
            courier = (svc.get("CourierSlug") or "").lower()
            want = next(
                (c for c in self.s.p2g_courier_list() if courier in COURIERS.get(c, (c,))), None
            )
            if (
                not want
                or svc.get("CollectionType") not in DROP_OFF
                or svc.get("DeliveryType") not in (None, "Door")
                or not self._fits(svc)
            ):
                continue
            extras = {e.get("Type"): e for e in q.get("AvailableExtras") or []}
            in_store = "PrintInStore" in extras
            printer = bool(svc.get("IsPrinterRequired")) and not in_store
            extra = to_pence(extras["PrintInStore"].get("Total") or 0) if in_store else 0
            option = DropOption(
                courier=want,
                courier_name=NAMES.get(want) or svc.get("CourierName") or want.title(),
                service=svc["Slug"],
                service_name=svc.get("Name") or svc["Slug"],
                price_pence=to_pence(q.get("TotalPrice") or 0) + extra,
                price_ex_vat_pence=to_pence(q.get("TotalPriceExVat") or 0)
                + (to_pence(extras["PrintInStore"].get("Price") or 0) if in_store else 0),
                printer=printer,
                print_in_store=in_store,
                locker=svc.get("CollectionType") == "Locker",
                drop_off_code=svc.get("DropOffProviderCode"),
            )
            best = found.get(want)
            # Shops before lockers (anyone can use a shop), then the cheaper one.
            if best is None or (option.locker, option.price_pence) < (
                best.locker,
                best.price_pence,
            ):
                found[want] = option
        prefs = self.s.p2g_courier_list()
        # No printer first; otherwise in the order CROOKS prefers.
        ordered = sorted(found.values(), key=lambda o: (o.printer, prefs.index(o.courier)))
        if with_shops:
            for option in ordered:
                option.shops = self.drop_shops(option.drop_off_code, postcode)[:3]
        return ordered

    def _fits(self, svc: dict[str, Any]) -> bool:
        """Our parcel inside the service's limits (Parcel2Go gives sizes in metres)."""
        weight = self.s.parcel_weight_grams / 1000
        if svc.get("MaxWeight") and weight > float(svc["MaxWeight"]):
            return False
        limits = sorted(
            float(svc[k]) * 100 for k in ("MaxLength", "MaxWidth", "MaxHeight") if svc.get(k)
        )
        if len(limits) < 3:
            return True
        return all(a <= b for a, b in zip(sorted(self.s.parcel_size()), limits, strict=True))

    def drop_shops(self, code: str | None, postcode: str) -> list[DropShop]:
        if not code or not postcode:
            return []
        try:
            body = self._call(
                "GET",
                f"/dropshops/{code}/location",
                params={"location": postcode, "iso3CountryCode": "GBR"},
            )
        except LabelError as exc:
            log.warning("drop shops for %s near %s: %s", code, postcode, exc)
            return []
        shops, seen = [], set()
        for s in (body or {}).get("Results") or []:
            distance = s.get("Distance")
            key = ((s.get("Name") or "").strip().lower(), (s.get("Postcode") or "").upper())
            if key in seen:
                continue
            seen.add(key)
            hours = re.sub(r"<br\s*/?>", "; ", s.get("ConcatenatedTimes") or "")
            shops.append(
                DropShop(
                    name=s.get("Name") or "",
                    address=", ".join(x for x in (s.get("Address1"), s.get("Address2")) if x),
                    postcode=s.get("Postcode") or "",
                    distance_m=int(distance) if distance is not None else None,
                    hours="" if not hours.strip(" :;") else hours.strip(),
                )
            )
        return sorted(shops, key=lambda x: x.distance_m if x.distance_m is not None else 1e9)

    def balance_pence(self) -> int | None:
        try:
            return to_pence(self._call("GET", "/prepay") or 0)
        except LabelError:
            return None

    # ------------------------------------------------------------------ booking

    def create(self, ret: Return, address: dict[str, Any]) -> Label:
        ok, why = self.available()
        if not ok:
            raise LabelError(why)
        if ret.postage.label_ref and ret.postage.label_ref.startswith("p2g:"):
            # Already paid for on an earlier try: fetch that label, never buy a second.
            return self._documents(ret.postage.label_ref, ret.postage.service)
        collection = self.customer_address(ret, address)
        if not collection["Phone"]:
            raise LabelError(
                "The courier needs a phone number for the customer and the order has none. "
                "Set RETURNS_RETURNS_CONTACT_PHONE so ours is used, or add tracking by hand."
            )
        value = sum(line.unit_paid_pence * line.quantity for line in ret.lines)
        option = self._pick(ret.postage.service, collection["Postcode"], value)
        parcel = {k: v for k, v in self._parcel(value).items() if k != "Value"}
        order = {
            "Items": [
                {
                    "Id": str(uuid.uuid4()),
                    "CollectionDate": datetime.now(UTC).isoformat(),
                    "OriginCountry": "GBR",
                    "Service": option.service,
                    "Reference": f"{ret.order_name} {ret.id}"[:50],
                    "Upsells": [{"Type": "PrintInStore"}] if option.print_in_store else [],
                    "CollectionAddress": collection,
                    "Parcels": [
                        {
                            "Id": str(uuid.uuid4()),
                            **parcel,
                            "EstimatedValue": float(to_amount(value)),
                            "DeliveryAddress": self.our_address(),
                            "ContentsSummary": "Clothing return",
                        }
                    ],
                }
            ],
            "CustomerDetails": {
                "Email": self.s.returns_contact_email or ret.customer_email or "",
                "Forename": "CROOKS",
                "Surname": "LDN",
                "Reference": ret.id,
            },
        }
        made = self._call("POST", "/orders", json=order) or {}
        order_id, order_hash = str(made.get("OrderId") or ""), made.get("Hash") or ""
        if not order_id:
            raise LabelError(f"Parcel2Go created no order: {made}")
        lines = made.get("OrderlineIdMap") or [{}]
        line_id = str(lines[0].get("OrderLineId") or "")
        ref = f"p2g:{order_id}:{line_id}:{order_hash}"
        try:
            paid = self._call(
                "POST", f"/orders/{order_id}/paywithprepay", params={"hash": order_hash}
            )
        except LabelError as exc:
            raise LabelError(
                f"Parcel2Go order {order_id} was created but not paid: {exc}. Top up PrePay "
                "and try the label again."
            ) from exc
        if isinstance(paid, dict) and paid.get("Errors"):
            raise LabelError(
                f"Parcel2Go order {order_id} was not paid: "
                + "; ".join(e.get("Description") or e.get("Name") or "" for e in paid["Errors"])
            )
        label = self._documents(ref, option.service, paid)
        label.price_pence = to_pence(made.get("TotalPrice") or 0)
        label.service_name = option.service_name
        label.carrier = option.courier_name
        return label

    def _pick(self, wanted: str | None, postcode: str, value: int) -> DropOption:
        options = self.options(postcode, value, with_shops=False)
        if not options:
            raise LabelError(
                f"Parcel2Go has no printer-free drop-off service for {postcode} "
                f"({', '.join(self.s.p2g_courier_list())}). Ask the customer to post it."
            )
        chosen = next((o for o in options if o.service == wanted or o.courier == wanted), None)
        return chosen or options[0]

    def _documents(self, ref: str, service: str | None, paid: Any = None) -> Label:
        """The paid order's label PDF, QR code and tracking. A failure here keeps `ref`, so
        trying again fetches the same label."""
        _, order_id, line_id, order_hash = ref.split(":", 3)
        links = _links(paid)
        # The order itself carries the in-store code, per parcel.
        code, code_format = None, None
        try:
            got = self._call("GET", "/orders", params={"orderId": order_id, "hash": order_hash})
        except LabelError:
            got = None
        if isinstance(got, dict):
            links = {**_links(got), **links}
            for item in got.get("Items") or []:
                for parcel in item.get("Parcels") or []:
                    links = {**_links(parcel), **links}
                    code = code or parcel.get("PrintInStoreBarcode")
                    code_format = code_format or parcel.get("PrintInStoreBarcodeFormat")
        pdf = self._fetch(links.get("labels-a4") or links.get("labels-4x6"))
        qr = self._fetch(links.get("barcode-printinstore")) or qr_png(code, code_format)
        if pdf is None:
            try:
                got = self._call(
                    "GET",
                    f"/labels/{order_id}",
                    params={
                        "referenceType": "OrderId",
                        "detailLevel": "Labels",
                        "labelMedia": "A4",
                        "labelFormat": "PDF",
                        "hash": order_hash,
                    },
                )
                encoded = (got or {}).get("Base64EncodedLabels") or []
                if encoded:
                    import base64

                    pdf = base64.b64decode(encoded[0])
            except LabelError as exc:
                log.warning("label for %s: %s", ref, exc)
        if pdf is None and qr is None:
            raise LabelError(
                f"Parcel2Go order {order_id} is paid but its label isn't ready yet. Try the "
                "label again in a minute.",
                ref=ref,
            )
        tracking = None
        try:
            numbers = self._call("POST", f"/orders/{order_id}/parcelnumbers") or {}
            tracking = next(
                (t.get("TrackingNumber") for t in numbers.get("TrackingNumbers") or []), None
            )
        except LabelError as exc:
            log.info("tracking for %s not ready: %s", ref, exc)
        return Label(
            tracking=tracking or (f"P2G{line_id}" if line_id else None),
            pdf=pdf,
            ref=ref,
            carrier="Parcel2Go",
            qr_png=qr,
            tracking_url=links.get("tracking-page")
            or (f"{self.base}/tracking/{line_id}" if line_id else None),
            service=service,
            drop_off_code=code,
        )

    def _fetch(self, url: str | None) -> bytes | None:
        if not url:
            return None
        try:
            r = self._http.get(url)
        except httpx.HTTPError:
            return None
        return r.content if r.status_code == 200 and r.content else None


def qr_png(code: str | None, code_format: str | None = None) -> bytes | None:
    """Draw the in-store code as a QR image when Parcel2Go gives the code but no picture.
    A linear barcode format is left to the PDF label, which carries it."""
    if not code or (code_format and "qr" not in code_format.lower()):
        return None
    import io

    import segno

    out = io.BytesIO()
    segno.make(code, error="m").save(out, kind="png", scale=10, border=3)
    return out.getvalue()


def _links(body: Any) -> dict[str, str]:
    """Parcel2Go returns links as a list of {Name, Link} or as an object; take either."""
    raw = body.get("Links") if isinstance(body, dict) else body
    if isinstance(raw, dict):
        return {str(k).lower(): str(v) for k, v in raw.items() if v}
    if isinstance(raw, list):
        return {
            str(x.get("Name") or "").lower(): str(x.get("Link") or "")
            for x in raw
            if isinstance(x, dict) and x.get("Link")
        }
    return {}


def _errors(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return r.text[:300]
    errors = body.get("Errors") if isinstance(body, dict) else None
    if errors:
        return "; ".join(str(e.get("Error") or e.get("Description") or e) for e in errors)[:400]
    return str(body)[:300]
