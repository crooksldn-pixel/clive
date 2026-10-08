"""Royal Mail Click & Drop return labels.

Built to the published Click & Drop REST schema (create order, label in the response). Two
things can only be confirmed against the CROOKS account itself, and the first live label is
the test: label generation through the API needs a Royal Mail Online Business Account
(pay-as-you-go accounts are answered 403), and the Tracked Returns service code is set per
account in RETURNS_CLICKDROP_SERVICE_CODE. Until both hold, approvals fall back to "label
later" and say why, rather than pretending a label exists.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from returns.models import Return, declared_value_pence, to_amount
from returns.settings import Settings


class LabelError(RuntimeError):
    """No label was made. The message says why, for staff and CLIVE. `ref` is set once an
    order exists with the provider, so a retry settles that one instead of buying another.
    `paid` is True when the provider confirmed the label is paid for (only collecting it
    failed), False when it confirmed it isn't, None when nobody knows yet. `status` is the
    provider's HTTP status when it answered with an error (a 4xx means it said no).

    After a payment that got no answer, the order reading unpaid is not believed at once:
    `unpaid_at` is when it first read unpaid (to be kept for the next check), and `dropped`
    means it read unpaid again at least two minutes later, so that order is never paid and a
    new one is needed (the rule Shipping follows, docs/shipping/DESIGN.md section G.5)."""

    def __init__(
        self,
        message: str,
        ref: str | None = None,
        paid: bool | None = None,
        status: int | None = None,
        unpaid_at: datetime | None = None,
        dropped: bool = False,
    ) -> None:
        super().__init__(message)
        self.ref = ref
        self.paid = paid
        self.status = status
        self.unpaid_at = unpaid_at
        self.dropped = dropped


# Called with the provider's order reference just before money can move, so the caller writes
# it down first: a lost answer or a restart then settles that order and never buys another.
Keep = Callable[[str], None]


@dataclass
class Label:
    tracking: str | None
    pdf: bytes | None
    ref: str
    carrier: str = "Royal Mail"
    # A code the customer shows at the drop-off shop instead of printing anything.
    qr_png: bytes | None = None
    tracking_url: str | None = None
    price_pence: int | None = None
    service: str | None = None
    service_name: str | None = None
    # The text of the in-store code, if the courier gave one (shown under the QR).
    drop_off_code: str | None = None


def tracking_url(number: str) -> str:
    return f"https://www.royalmail.com/track-your-item#/tracking-results/{number}"


class LabelPort(Protocol):
    def available(self) -> tuple[bool, str]: ...
    def create(self, ret: Return, address: dict[str, Any], keep: Keep | None = None) -> Label: ...


class ClickAndDrop:
    name = "Click & Drop"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._http = httpx.Client(timeout=30, base_url=settings.clickdrop_base_url)

    def available(self) -> tuple[bool, str]:
        if not self.s.clickdrop_api_key:
            return False, "Click & Drop is not connected (no API key)."
        if not self.s.clickdrop_service_code:
            return False, "No Tracked Returns service code is set for Click & Drop."
        return True, ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.s.clickdrop_api_key}", "Accept": "application/json"}

    def order_body(self, ret: Return, address: dict[str, Any]) -> dict[str, Any]:
        """The customer is the recipient: a Tracked Returns label carries their address and
        comes back to the return address held on the Click & Drop account."""
        name = " ".join(x for x in (address.get("firstName"), address.get("lastName")) if x)
        value = declared_value_pence(ret.lines)
        return {
            "items": [
                {
                    "orderReference": f"{ret.order_name} {ret.id}"[:40],
                    "recipient": {
                        "address": {
                            "fullName": name or ret.customer_name or "Customer",
                            "addressLine1": address.get("address1") or "",
                            "addressLine2": address.get("address2") or "",
                            "city": address.get("city") or "",
                            "county": address.get("province") or "",
                            "postcode": address.get("zip") or "",
                            "countryCode": address.get("countryCodeV2") or "GB",
                        },
                        "emailAddress": ret.customer_email or "",
                    },
                    "packages": [
                        {
                            "weightInGrams": self.s.clickdrop_weight_grams,
                            "packageFormatIdentifier": self.s.clickdrop_package_format,
                        }
                    ],
                    "orderDate": datetime.now(UTC).isoformat(),
                    "subtotal": float(to_amount(value)),
                    "shippingCostCharged": 0,
                    "total": float(to_amount(value)),
                    "currencyCode": ret.currency,
                    "postageDetails": {"serviceCode": self.s.clickdrop_service_code},
                    "label": {"includeLabelInResponse": True},
                }
            ]
        }

    def create(self, ret: Return, address: dict[str, Any], keep: Keep | None = None) -> Label:
        # One call makes and pays the order, so there is no moment to write a reference down.
        ok, why = self.available()
        if not ok:
            raise LabelError(why)
        r = self._http.post("/orders", json=self.order_body(ret, address), headers=self._headers())
        if r.status_code == 403:
            raise LabelError(
                "Click & Drop refused label generation (403). Labels through the "
                "API need a Royal Mail Online Business Account."
            )
        if r.status_code >= 400:
            raise LabelError(f"Click & Drop answered {r.status_code}: {r.text[:300]}")
        body = r.json()
        if body.get("failedOrders"):
            errors = body["failedOrders"][0].get("errors") or []
            raise LabelError(
                "Click & Drop rejected the label: "
                + "; ".join(str(e.get("errorMessage") or e) for e in errors)
            )
        created = (body.get("createdOrders") or [None])[0]
        if not created:
            raise LabelError("Click & Drop created no order.")
        ref = str(created["orderIdentifier"])
        pdf = base64.b64decode(created["label"]) if created.get("label") else None
        if pdf is None:
            lr = self._http.get(
                f"/orders/{ref}/label",
                params={"documentType": "postageLabel", "includeReturnsLabel": "false"},
                headers={**self._headers(), "Accept": "application/pdf"},
            )
            if lr.status_code == 200:
                pdf = lr.content
        if pdf is None:
            raise LabelError(f"Click & Drop order {ref} was created but returned no label.")
        return Label(tracking=created.get("trackingNumber"), pdf=pdf, ref=ref)


class NoLabels:
    """Labels switched off: every approval that needs one waits on staff or CLIVE."""

    name = "No labels"

    def available(self) -> tuple[bool, str]:
        return False, "Automatic labels are not set up."

    def create(self, ret: Return, address: dict[str, Any], keep: Keep | None = None) -> Label:
        raise LabelError(self.available()[1])
