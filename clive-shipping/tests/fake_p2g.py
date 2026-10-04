"""A stand-in Parcel2Go shaped like the sandbox's real answers (2026-10-04/05), and its
fixtures. Like the real one it charges again when a paid order is paid again."""

import base64
import json

import httpx

from shipping.models import Address, ShopConfig
from shipping.providers.parcel2go import Parcel2Go

from .conftest import SHOP
from .pdfs import A4, LABEL_4X6, pdf

# Paperwork per service, as the sandbox returned it (2026-10-05): copies of the commercial
# invoice to print, or 0 when customs is handled electronically.
PAPER_COPIES = {"dpd": 0, "landmark": 0, "upsc-via-ocs": 0, "myhermes": 3, "ups-access": 4}

# Shaped like the sandbox's list: regions come as extra rows of the same country, some before
# the main row, each recognised by postcode.
COUNTRIES = [
    {
        "Name": "UK - Mainland",
        "Iso3Code": "GBR",
        "Iso2Code": "GB",
        "RequiresCustoms": False,
        "Subdivision": None,
    },
    {
        "Name": "Northern Ireland",
        "Iso3Code": "GBR",
        "Iso2Code": "GB",
        "RequiresCustoms": False,
        "Subdivision": "NIR",
        "PostcodeRegex": "^.*$",  # a format check, not a region test
    },
    {
        "Name": "Germany",
        "Iso3Code": "DEU",
        "Iso2Code": "DE",
        "RequiresCustoms": True,
        "Subdivision": None,
    },
    {
        "Name": "Portugal",
        "Iso3Code": "PRT",
        "Iso2Code": "PT",
        "RequiresCustoms": True,
        "Subdivision": None,
    },
    {
        "Name": "Madeira",
        "Iso3Code": "PRT",
        "Iso2Code": "PT",
        "RequiresCustoms": True,
        "Subdivision": "PT-30",
        "PostcodeRegex": "^.*$",
    },
    {
        "Name": "Tenerife",
        "Iso3Code": "ESP",
        "Iso2Code": "ES",
        "RequiresCustoms": True,
        "Subdivision": "ES-TEN",
        "PostcodeRegex": "^[0-9]{5}$",
    },
    {
        "Name": "Canary Islands",
        "Iso3Code": "ESP",
        "Iso2Code": "ES",
        "RequiresCustoms": True,
        "Subdivision": "ES-GC",
        "PostcodeRegex": "^[0-9]{5}$",
    },
    {
        "Name": "Spain (Mainland Only)",
        "Iso3Code": "ESP",
        "Iso2Code": "ES",
        "RequiresCustoms": True,
        "Subdivision": None,
    },
    {
        "Name": "USA",
        "Iso3Code": "USA",
        "Iso2Code": "US",
        "RequiresCustoms": True,
        "Subdivision": None,
    },
]


def quote(
    slug, courier, price, delivery="Door", max_w=None, collection="2026-10-06", est="2026-10-08"
):
    return {
        "Service": {
            "Slug": slug,
            "Name": slug.title(),
            "CourierSlug": courier,
            "CourierName": courier.title(),
            "CollectionType": "Shop",
            "DeliveryType": delivery,
            "IsPrinterRequired": True,
            "MaxWeight": max_w,
            "MaxLength": 1.2,
        },
        "TotalPrice": price,
        # True on every international quote in the sandbox, paperless services included: CLIVE
        # must not key paperless on it.
        "RequiresCommercialInvoice": True,
        "RequiresCustoms": True,
        "Collection": f"{collection}T00:00:00",
        "EstimatedDeliveryDate": f"{est}T00:00:00",
    }


class FakeP2G:
    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.charges: list[str] = []
        self.bodies: list[dict] = []
        self.pay_fault: str | None = None  # connect | timeout_after_charge | 500 | refuse
        # detailLevel -> override answer: an httpx.Response, or "garbage" for a non-PDF body
        self.labels_override: dict[str, object] = {}
        self.all_extra_pages = 0  # extra pages the "All" view reports beyond the truth
        self.copies: dict[str, int] = dict(PAPER_COPIES)  # per-service, changeable mid-test
        self.invoice_pages = 1  # pages in one commercial invoice
        # endpoint -> fault, used once: an httpx.Response, "garbage" (200 with an HTML body),
        # or a function(request) -> Response. Endpoints: countries quotes verify create read.
        self.faults: dict[str, object] = {}

    @staticmethod
    def endpoint(path: str, method: str) -> str:
        return {
            ("/api/countries", "GET"): "countries",
            ("/api/quotes", "POST"): "quotes",
            ("/api/orders/verify", "POST"): "verify",
            ("/api/orders", "POST"): "create",
            ("/api/orders", "GET"): "read",
            ("/api/prepay", "GET"): "prepay",
        }.get(
            (path, method),
            "pay"
            if path.endswith("/paywithprepay")
            else "parcelnumbers"
            if path.endswith("/parcelnumbers")
            else "",
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == "/auth/connect/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        fault = self.faults.pop(self.endpoint(path, method), None)
        if isinstance(fault, httpx.Response):
            return fault
        if fault == "garbage":
            return httpx.Response(200, content=b"<html>Service Unavailable</html>")
        if callable(fault):
            answer = fault(request)
            assert isinstance(answer, httpx.Response)
            return answer
        if path == "/api/countries":
            return httpx.Response(200, json=COUNTRIES)
        if path == "/api/quotes":
            self.bodies.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "Quotes": [
                        quote("dpd-classic", "dpd", 10.69),
                        quote(
                            "myhermes-international-parcelshop", "myhermes", 6.6, est="2026-10-14"
                        ),
                        quote(
                            "ups-shop-to-shop", "ups", 5.0, delivery="Shop"
                        ),  # recipient collects
                        quote("tiny", "dpd", 3.0, max_w=0.2),  # too light a limit for our parcel
                    ]
                },
            )
        if path == "/api/orders/verify":
            self.bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"Errors": [], "Cost": 10.69})
        if path == "/api/orders" and method == "POST":
            body = json.loads(request.content)
            self.bodies.append(body)
            oid = str(26700 + len(self.orders))
            item = body["Items"][0]
            self.orders[oid] = {
                "paid": False,
                "service": item["Service"],
                "to": item["Parcels"][0]["DeliveryAddress"]["CountryIsoCode"],
            }
            return httpx.Response(
                200,
                json={
                    "OrderId": oid,
                    "Hash": "h/+=",
                    "TotalPrice": 10.69,
                    "OrderlineIdMap": [{"OrderLineId": "45800"}],
                },
            )
        if path.endswith("/paywithprepay"):
            oid = path.split("/")[3]
            fault, self.pay_fault = self.pay_fault, None
            if fault == "connect":
                raise httpx.ConnectError("refused", request=request)
            if fault == "refuse":
                return httpx.Response(
                    400, json={"Errors": [{"Name": "Balance", "Description": "Not enough"}]}
                )
            self.orders[oid]["paid"] = True
            self.charges.append(oid)  # charges every time, like the real one
            if fault == "timeout_after_charge":
                raise httpx.ReadTimeout("lost", request=request)
            if fault == "500":
                return httpx.Response(502)
            if fault == "garbage_after_charge":
                return httpx.Response(200, content=b"<html>Gateway</html>")
            return httpx.Response(200, json={"Links": []})
        if path == "/api/orders" and method == "GET":
            oid = request.url.params["orderId"]
            paid = self.orders[oid]["paid"]
            return httpx.Response(
                200,
                json={
                    "PaidDate": "2026-10-05T10:00:00" if paid else None,
                    "TotalPrice": 10.69,
                    "Items": [
                        {
                            "Id": 45800,
                            "Parcels": [
                                {"DeliveryAddress": {"CountryIsoCode": self.orders[oid]["to"]}}
                            ],
                        }
                    ],
                    "Links": {
                        "labels-4x6": "https://p2g.test/label/x?m=1",
                        "labels-a4": "https://p2g.test/label/x?m=0",
                        "tracking-page": "https://p2g.test/track/45800",
                    },
                },
            )
        if path.startswith("/api/labels/"):
            return self.labels(path.split("/")[3], request.url.params)
        if path.startswith("/label/"):
            return httpx.Response(200, content=b"%PDF-1.4 label " + request.url.query)
        if path.endswith("/parcelnumbers"):
            return httpx.Response(200, json={"TrackingNumbers": [{"TrackingNumber": None}]})
        if path == "/api/prepay":
            return httpx.Response(200, json=50.0)
        return httpx.Response(404)

    def labels(self, oid: str, params) -> httpx.Response:
        detail, media = params["detailLevel"], params["labelMedia"]
        override = self.labels_override.get(detail)
        if isinstance(override, httpx.Response):
            return override
        order = self.orders[oid]
        copies = next(v for k, v in self.copies.items() if order["service"].startswith(k))
        label = LABEL_4X6 if media == "Label4X6" else A4
        invoice = [A4] * self.invoice_pages
        pages = {
            "Labels": [label],
            "CommercialInvoice": invoice,
            "AdditionalDocuments": invoice * copies,
            "All": [label] + invoice + invoice * copies + [A4] * self.all_extra_pages,
        }.get(detail)
        if not pages and override not in ("garbage", "empty", "objstm", "two_files"):
            return httpx.Response(404, json={"Message": "No documents"})
        files = [pdf(*(pages or [A4]))]
        if override == "garbage":
            files = [b"<html>oops</html>"]
        elif override == "empty":
            files = []
        elif override == "objstm":  # a real PDF whose pages can't be counted without a library
            files = [b"%PDF-1.5\n1 0 obj << /Type /ObjStm /N 3 >> stream x endstream endobj"]
        elif override == "two_files":
            files = files * 2
        return httpx.Response(
            200,
            json={
                "SuccessfulLabels": len(files),
                "FailedLabels": 0,
                "Base64EncodedLabels": [base64.b64encode(f).decode() for f in files],
            },
        )


def shop_config() -> ShopConfig:
    return ShopConfig(
        shop=SHOP,
        origin=Address(
            name="CROOKS LDN",
            line1="Unit M",
            line2="Bourne End Business Park",
            city="Bourne End",
            postcode="SL8 5AS",
            country="GB",
            phone="07700900000",
            email="team@crooksldn.com",
        ),
    )


def adapter(server: FakeP2G, cfg: ShopConfig, clock, cache=None) -> Parcel2Go:
    return Parcel2Go(
        "https://p2g.test",
        "id",
        "secret",
        config=lambda shop: cfg,
        http=httpx.Client(transport=httpx.MockTransport(server)),
        clock=clock,
        cache=cache,
    )
