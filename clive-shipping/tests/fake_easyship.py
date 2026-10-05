"""A stand-in Easyship (public API 2024-09), shaped by the documented contract (2026-10-05).

Dangerous on purpose: buying a label twice charges twice, a reply can be lost after the
charge, and documents can lag behind the label."""

from __future__ import annotations

import base64
import copy
import itertools
import json
from pathlib import Path
from typing import Any

import httpx
import jsonschema

from shipping.models import ShopConfig
from shipping.providers.easyship import Easyship

from .pdfs import A4, LABEL_4X6, pdf

TOKEN = "prod_test-token"

# Easyship's own request schemas (OpenAPI 3.0, fetched 2026-10-05), so a body the real API
# would reject with 400 is rejected here too. The live API refused `"sku": null` this way.
_SPEC = json.loads((Path(__file__).parent / "easyship_requests_2024-09.json").read_text())


def _jsonschema(o: Any) -> Any:
    """OpenAPI 3.0 -> JSON Schema 2020-12: `nullable` becomes a null branch, refs to $defs."""
    if isinstance(o, list):
        return [_jsonschema(x) for x in o]
    if not isinstance(o, dict):
        return o
    out = {k: _jsonschema(v) for k, v in o.items() if k != "nullable"}
    if "$ref" in out:
        out["$ref"] = out["$ref"].replace("#/components/schemas/", "#/$defs/")
    if o.get("nullable") is True:
        if "enum" in out:
            out["enum"] = [*out["enum"], None]
        if isinstance(out.get("type"), str):
            out["type"] = [out["type"], "null"]
        elif "type" not in out:
            out = {"anyOf": [out, {"type": "null"}]}
    return out


_DEFS = {k: _jsonschema(v) for k, v in _SPEC["schemas"].items()}
VALIDATORS = {
    endpoint: jsonschema.Draft202012Validator({"$ref": f"#/$defs/{root}", "$defs": _DEFS})
    for endpoint, root in _SPEC["roots"].items()
}


def spec_errors(endpoint: str, body: Any) -> list[str]:
    """Why Easyship's schema refuses this request body (empty: it complies)."""
    v = VALIDATORS.get(endpoint)
    if v is None:
        return []
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in v.iter_errors(body)]


def service(
    sid: str,
    umbrella: str,
    name: str,
    price: float,
    days: tuple[int, int] = (2, 4),
    tracking_rating: int = 2,
    handover: tuple[str, ...] = ("dropoff",),
    payment_recipient: str = "Easyship",
    currency: str = "GBP",
    invoice: bool = False,
) -> dict[str, Any]:
    return {
        "id": sid,
        "umbrella": umbrella,
        "name": name,
        "price": price,
        "days": days,
        "tracking_rating": tracking_rating,
        "handover": list(handover),
        "payment_recipient": payment_recipient,
        "currency": currency,
        "invoice": invoice,
    }


# Channel Islands, as the owner sees it in Easyship's dashboard (prices illustrative).
GUERNSEY = [
    service("svc-rm-ci", "Royal Mail", "Royal Mail International Tracked", 3.24, (2, 4)),
    service(
        "svc-rm-std",
        "Royal Mail",
        "Royal Mail International Standard",
        2.95,
        (3, 6),
        tracking_rating=-1,
    ),
    service(
        "svc-ups", "UPS", "UPS Express Saver", 41.02, (1, 2), handover=("dropoff", "free_pickup")
    ),
]


class FakeEasyship:
    def __init__(self, services: list[dict[str, Any]] | None = None) -> None:
        self.services = copy.deepcopy(services or GUERNSEY)  # tests change prices freely
        self.shipments: dict[str, dict[str, Any]] = {}
        self.charges: list[str] = []
        self.requests: list[tuple[str, str]] = []
        self.bodies: list[tuple[str, Any]] = []
        self.balance = 50.0
        self._ids = itertools.count(1001)
        # endpoint -> fault, used once: an httpx.Response, "garbage", "timeout" (the request
        # never answered), or "timeout_after" (done, then the reply is lost).
        # Endpoints: rates create label read cancel credit delete
        self.faults: dict[str, Any] = {}
        self.label_state_after_buy = "generated"
        self.tracking_after_buy = True

    # ------------------------------------------------------------------ plumbing

    @staticmethod
    def endpoint(path: str, method: str) -> str:
        if path == "/2024-09/rates" and method == "POST":
            return "rates"
        if path == "/2024-09/shipments" and method == "POST":
            return "create"
        if path.endswith("/label") and method == "POST":
            return "label"
        if path.endswith("/cancel") and method == "POST":
            return "cancel"
        if path == "/2024-09/account/credit":
            return "credit"
        if path.startswith("/2024-09/shipments/") and method == "GET":
            return "read"
        if path.startswith("/2024-09/shipments/") and method == "DELETE":
            return "delete"
        return ""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        name = self.endpoint(path, method)
        self.requests.append((method, path))
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(
                401, json={"error": {"code": "unauthorized", "message": "Bad token"}}
            )
        body = None
        if request.content:
            body = json.loads(request.content)
            self.bodies.append((name, body))
            if errors := spec_errors(name, body):
                return httpx.Response(
                    400,
                    json={
                        "error": {
                            "code": "invalid_content",
                            "message": "The request body content is not valid.",
                            "details": errors,
                            "type": "invalid_request_error",
                        }
                    },
                )
        fault = self.faults.pop(name, None)
        if isinstance(fault, httpx.Response):
            return fault
        if fault == "garbage":
            return httpx.Response(200, content=b"<html>Bad gateway</html>")
        if fault == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        answer = self.handle(name, path, body, request)
        if fault == "timeout_after":
            raise httpx.ReadTimeout("timed out after it was done", request=request)
        return answer

    # ------------------------------------------------------------------ endpoints

    def rate_row(self, svc: dict[str, Any]) -> dict[str, Any]:
        return {
            "courier_service": {
                "id": svc["id"],
                "name": svc["name"],
                "umbrella_name": svc["umbrella"],
                "courier_id": "c-" + svc["id"],
                "easyship_courier_service": True,
            },
            "min_delivery_time": svc["days"][0],
            "max_delivery_time": svc["days"][1],
            "currency": svc["currency"],
            "total_charge": svc["price"],
            "shipment_charge_total": svc["price"],
            "tracking_rating": svc["tracking_rating"],
            "available_handover_options": svc["handover"],
            "payment_recipient": svc["payment_recipient"],
            "incoterms": "DDU",
        }

    def handle(self, name: str, path: str, body: Any, request: httpx.Request) -> httpx.Response:
        if name == "rates":
            wanted = ((body or {}).get("filter_options") or {}).get("courier_service_ids")
            rows = [self.rate_row(s) for s in self.services if not wanted or s["id"] in wanted]
            return httpx.Response(200, json={"rates": rows, "meta": {"request_id": "r1"}})
        if name == "create":
            sid = body["courier_settings"]["courier_service_id"]
            svc = next((s for s in self.services if s["id"] == sid), None)
            es_id = f"ESGG{next(self._ids)}"
            sh = {
                "easyship_shipment_id": es_id,
                "shipment_state": "created",
                "label_state": "not_created",
                "label_paid_at": None,
                "currency": "GBP",
                "courier_service": None,
                "rates": [],
                "trackings": [],
                "shipping_documents": [],
                "metadata": body.get("metadata"),
            }
            if svc is None:
                self.shipments[es_id] = sh
                return httpx.Response(202, json={"shipment": sh, "meta": {}})
            sh["courier_service"] = self.rate_row(svc)["courier_service"]
            sh["rates"] = [self.rate_row(svc)]
            sh["_svc"] = svc
            self.shipments[es_id] = sh
            return httpx.Response(201, json={"shipment": self.public(sh)})
        es_id = path.split("/")[3] if path.count("/") >= 3 else ""
        sh: dict[str, Any] = self.shipments.get(es_id) or {}
        if name in ("label", "read", "cancel", "delete") and not sh:
            return httpx.Response(
                404, json={"error": {"code": "not_found", "message": "record not found"}}
            )
        if name == "label":
            if self.balance < sh["_svc"]["price"]:
                return httpx.Response(
                    422,
                    json={
                        "error": {"code": "insufficient_credit", "message": "Insufficient balance"}
                    },
                )
            # Like a careless provider: buying again charges again.
            self.charges.append(es_id)
            self.balance -= sh["_svc"]["price"]
            sh["label_paid_at"] = "2026-10-05T12:00:00Z"
            sh["label_state"] = self.label_state_after_buy
            if self.tracking_after_buy:
                sh["trackings"] = [
                    {"tracking_number": "RM123456789GB", "leg_number": 1, "handler": "Royal Mail"}
                ]
            sh["tracking_page_url"] = f"https://www.trackmyshipment.co/shipment-tracking/{es_id}"
            return httpx.Response(201, json={"shipment": self.public(sh)})
        if name == "read":
            out = self.public(sh)
            if sh["label_state"] in ("generated", "printed"):
                docs = [
                    {
                        "category": "label",
                        "required": True,
                        "format": "pdf",
                        "page_size": "4x6",
                        "base64_encoded_strings": [base64.b64encode(pdf(LABEL_4X6)).decode()],
                    }
                ]
                if sh["_svc"].get("invoice"):
                    docs.append(
                        {
                            "category": "commercial_invoice",
                            "required": True,
                            "format": "pdf",
                            "page_size": "A4",
                            "base64_encoded_strings": [base64.b64encode(pdf(A4)).decode()],
                        }
                    )
                out["shipping_documents"] = docs
            return httpx.Response(200, json={"shipment": out})
        if name == "delete":
            if sh["label_paid_at"]:
                return httpx.Response(
                    404,
                    json={"error": {"code": "not_found", "message": "not in a deletable state"}},
                )
            del self.shipments[es_id]
            return httpx.Response(200, json={"success": {"message": "deleted"}, "meta": {}})
        if name == "cancel":
            if sh["shipment_state"] == "cancelled":
                return httpx.Response(
                    422, json={"error": {"code": "invalid_state", "message": "Already cancelled"}}
                )
            sh["shipment_state"] = "cancelled"
            if sh["label_paid_at"]:
                sh["label_state"] = "voided"
                self.balance += sh["_svc"]["price"]
            return httpx.Response(200, json={"success": {"message": "cancelled"}, "meta": {}})
        if name == "credit":
            return httpx.Response(
                200,
                json={
                    "credit": {
                        "balance": self.balance,
                        "available_balance": self.balance,
                        "currency": "GBP",
                    }
                },
            )
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})

    @staticmethod
    def public(sh: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in sh.items() if not k.startswith("_")}


def adapter(server: FakeEasyship, cfg: ShopConfig, clock, token: str = TOKEN) -> Easyship:
    return Easyship(
        token,
        config=lambda shop: cfg,
        http=httpx.Client(transport=httpx.MockTransport(server)),
        clock=clock,
    )
