"""A stand-in CROOKS Returns for CLIVE's own tests: its /api/v1 and /health, answered from returns
held here, in the shapes the service's `returns/api.py` and `ReturnsService.staff` give them.

Not a test module. The unit tests (tests/test_crooks_returns.py) and the browser check build on
it; the true contract is tested against the service's own code (tests/test_crooks_returns_contract.py).
Every request is recorded (method, path, query, headers, body), so a test can say exactly what
CLIVE sent, and that no request went anywhere else. Every name, order and number here is invented.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote

import httpx

from tests.fake_credentials import bearer_token

READ = bearer_token("returns-read", length=32)
WRITE = bearer_token("returns-write", length=32)
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
STATUS_AFTER = {
    ("approve", "label_now"): "awaiting_shipment", ("approve", "self_ship"): "awaiting_shipment",
    ("approve", "label_later"): "awaiting_label", ("approve", "no_return"): "completed",
    ("decline", None): "declined", ("label", None): "awaiting_shipment", ("tracking", None): "in_transit",
    ("receive", "ok"): "completed", ("receive", "damaged"): "received", ("receive", "worn"): "received",
    ("receive", "missing"): "received", ("complete", None): "completed", ("cancel", None): "cancelled",
    ("note", None): None,
}
ALLOWED = {
    "approve": ("requested",), "decline": ("requested",), "label": ("awaiting_label",),
    "tracking": ("awaiting_shipment", "awaiting_label"), "receive": ("awaiting_label", "awaiting_shipment", "in_transit"),
    "complete": ("received",), "cancel": ("requested", "awaiting_label", "awaiting_shipment"), "note": None,
}


def iso(moment: datetime) -> str:
    return moment.isoformat()


def ret(rid: str, number: int, *, status: str = "requested", resolution: str = "refund", customer: str = "Sam Taylor",
        order_id: str = "", days_ago: float = 1.0, lines: list[dict[str, Any]] | None = None,
        money: dict[str, int] | None = None, postage: dict[str, Any] | None = None, attention: list[str] | None = None,
        timeline: list[dict[str, Any]] | None = None, last_error: str | None = None) -> dict[str, Any]:
    """A return as the service's staff view gives it."""
    at = NOW - timedelta(days=days_ago)
    lines = lines or [{"title": "Docket Tee", "variant_title": "M", "sku": "TEE-M", "quantity": 1, "reason": "too_small",
                       "unit_paid_pence": 2500, "exchange_direction": None, "exchange_variant_title": None}]
    money = {"items_pence": 2500, "fee_pence": 0, "bonus_pence": 0, "shipping_refund_pence": 0, "refund_pence": 2500,
             "credit_pence": 0, **(money or {})}
    postage = {"chosen": "free_label", "mode": None, "carrier": None, "tracking": None, "tracking_url": None,
               "service_name": None, "label_price_pence": None, "label_ref": None, "label_file_id": None,
               "courier_stage": None, "shops": [], **(postage or {})}
    timeline = timeline if timeline is not None else [
        {"at": iso(at), "type": "requested", "actor": "customer", "detail": {"resolution": resolution}, "verified": False}]
    attention = attention if attention is not None else (["needs_approval"] if status == "requested" else [])
    return {
        "id": rid, "order_id": order_id or f"gid://shopify/Order/{number}", "order_name": f"CROOKS-{number}",
        "customer_id": "gid://shopify/Customer/77", "customer_name": customer, "customer_email": "sam@example.com",
        "status": status, "resolution": resolution, "created_at": iso(at), "updated_at": iso(at), "lines": lines,
        "money": money, "postage": postage, "shopify": {"return_id": None}, "inspection": None, "decline_reason": None,
        "last_error": last_error, "timeline": timeline,
        "summary": f"CROOKS-{number}: 1x Docket Tee (M) [Too small]; refund £{money['refund_pence'] // 100}.{money['refund_pence'] % 100:02d}",
        "attention": attention, "label_url": None,
    }


class StubReturns:
    """The service, answered by an httpx MockTransport. `fail` names a path suffix to answer with a
    status; `error_on` makes an execute record its step and report an error, as the service does
    when Shopify or Parcel2Go refuses part of an action."""

    def __init__(self, returns: list[dict[str, Any]] | None = None) -> None:
        self.returns: dict[str, dict[str, Any]] = {r["id"]: r for r in (returns or [])}
        self.calls: list[dict[str, Any]] = []
        self.done: dict[str, dict[str, Any]] = {}
        self.fail: dict[str, int] = {}
        self.error_on: str = ""
        self.read_keys = {READ, WRITE}
        self.write_keys = {WRITE}
        self.health_keys = True
        self.clock = NOW

    # -------------------------------------------------------------- plumbing

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def requests(self, method: str = "", path: str = "") -> list[dict[str, Any]]:
        return [c for c in self.calls if (not method or c["method"] == method) and (not path or c["path"].endswith(path))]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        call = {"method": request.method, "path": request.url.path, "query": dict(request.url.params),
                "headers": dict(request.headers), "body": body, "url": str(request.url)}
        self.calls.append(call)
        for suffix, status in self.fail.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(status, json={"detail": "Refused by the stub."})
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True, "shopify": "graphql", "clive": {"read_keys": self.health_keys}})
        key = (request.headers.get("authorization") or "")[7:]
        if not request.url.path.startswith("/api/v1/"):
            return httpx.Response(404, json={"detail": "Not Found"})
        path = request.url.path[len("/api/v1"):]
        writing = request.method == "POST" and not path.endswith("/preview")
        if not key:
            return httpx.Response(401, json={"detail": "Bearer key required."})
        if writing and key not in self.write_keys:
            return httpx.Response(403, json={"detail": "This key cannot act on returns."})
        if not writing and key not in self.read_keys:
            return httpx.Response(403, json={"detail": "This key cannot read returns."})
        return self._route(request.method, path, call)

    def _route(self, method: str, path: str, call: dict[str, Any]) -> httpx.Response:
        parts = path.strip("/").split("/")
        if method == "GET" and parts == ["returns"]:
            return httpx.Response(200, json={"returns": self._search(call["query"])})
        if method == "GET" and len(parts) == 2 and parts[0] == "returns":
            found = self.returns.get(parts[1])
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"detail": "Return not found."})
        if method == "GET" and len(parts) == 3 and parts[0] == "orders":
            digits = "".join(ch for ch in unquote(parts[1]) if ch.isdigit())
            rows = [r for r in self.returns.values() if "".join(ch for ch in r["order_name"] if ch.isdigit()) == digits]
            return httpx.Response(200, json={"returns": rows})
        if method == "GET" and parts == ["stats"]:
            return httpx.Response(200, json=self._stats())
        if method == "POST" and len(parts) >= 4 and parts[0] == "returns" and parts[2] == "actions":
            return self._action(parts[1], parts[3], preview=len(parts) == 5, body=call["body"] or {})
        return httpx.Response(404, json={"detail": "Not Found"})

    # -------------------------------------------------------------- reads

    def _search(self, query: dict[str, str]) -> list[dict[str, Any]]:
        rows = list(self.returns.values())
        if query.get("open") == "true":
            rows = [r for r in rows if r["status"] in ("requested", "awaiting_label", "awaiting_shipment", "in_transit", "received")]
        if query.get("since"):
            since = datetime.fromisoformat(query["since"].replace("Z", "+00:00"))
            rows = [r for r in rows if datetime.fromisoformat(r["updated_at"]) >= since]
        rows.sort(key=lambda r: r["updated_at"], reverse=True)
        return copy.deepcopy(rows[: int(query.get("limit") or 100)])

    def _stats(self) -> dict[str, Any]:
        live = [r for r in self.returns.values() if r["status"] not in ("declined", "cancelled")]
        value = sum(r["money"]["items_pence"] for r in live)
        kept = sum(r["money"]["items_pence"] for r in live if r["resolution"] != "refund")
        reasons: dict[str, int] = {}
        for r in live:
            for ln in r["lines"]:
                reasons[ln["reason"]] = reasons.get(ln["reason"], 0) + ln["quantity"]
        return {"returns": len(self.returns), "by_status": {}, "by_resolution": {"refund": len(live)},
                "by_reason": reasons, "by_sku": [["TEE-M", 2]], "size_swaps": {"size_up": 1},
                "value_returned": f"£{value / 100:.2f}", "value_kept": f"£{kept / 100:.2f}",
                "kept_share": round(kept / value, 3) if value else None, "bonus_given": "£0.00", "label_fees_recovered": "£0.00"}

    # -------------------------------------------------------------- actions

    def _action(self, rid: str, action: str, *, preview: bool, body: dict[str, Any]) -> httpx.Response:
        doc = self.returns.get(rid)
        if doc is None:
            return httpx.Response(404, json={"detail": "Return not found."})
        if action not in ALLOWED:
            return httpx.Response(404, json={"detail": f"Unknown action {action}."})
        params = body.get("params") or {}
        allowed = ALLOWED[action]
        if allowed and doc["status"] not in allowed:
            return httpx.Response(409, json={"detail": f"This return is {doc['status']}; that needs {', '.join(allowed)}."})
        if preview:
            return httpx.Response(200, json={"return_id": rid, "action": action, "status": doc["status"],
                                             "will": self._will(doc, action, params), "shopify_calls": [], "money": doc["money"]})
        key = body.get("idempotency_key") or ""
        if not key:
            return httpx.Response(422, json={"detail": "An idempotency key is required."})
        scoped = f"{rid}:{action}:{key}"
        if scoped in self.done:
            return httpx.Response(200, json={**self.done[scoped], "replayed": True, "return": doc})
        if action == "tracking" and len(params.get("number") or "") < 6:
            return httpx.Response(422, json={"detail": "That tracking number doesn't look right."})
        before = doc["status"]
        choice = params.get("postage_mode") if action == "approve" else params.get("condition") if action == "receive" else None
        after = STATUS_AFTER.get((action, choice), before) or before
        self.clock += timedelta(minutes=1)
        verified = action in ("approve", "complete", "cancel") or (action == "receive" and after == "completed")
        error = ""
        if self.error_on == action:
            error = "Shopify did not process the return: refused (test)"
            verified = False
        doc["status"] = after
        doc["last_error"] = error or None
        doc["updated_at"] = iso(self.clock)
        doc["timeline"].append({"at": iso(self.clock), "type": {"approve": "approved", "note": "note"}.get(action, action),
                                "actor": body.get("actor") or "clive", "detail": params, "verified": verified})
        doc["attention"] = (["error"] if error else []) + (["needs_approval"] if after == "requested" else [])
        out = {"return_id": rid, "action": action, "from": before, "status": after, "verified": verified,
               "error": error or None, "evidence": {}}
        self.done[scoped] = out
        return httpx.Response(200, json={**out, "return": doc})

    def _will(self, doc: dict[str, Any], action: str, params: dict[str, Any]) -> list[str]:
        if action == "approve":
            lines = [f"Create Shopify return on {doc['order_name']} for: {doc['summary']}."]
            mode = params.get("postage_mode")
            if mode == "label_now":
                lines.append("Book Evri (Evri ParcelShop) for £2.98 from Parcel2Go PrePay, balance £50.00. The customer "
                             "gets the label by email and a QR code on the returns page.")
            elif mode == "no_return":
                lines.append("Nothing comes back. Refund £25.00 to the original payment method.")
            elif mode == "self_ship":
                lines.append("Ask the customer to send it back themselves and add tracking.")
            else:
                lines.append("Hold it as awaiting_label; overdue after 24h.")
            return lines
        if action == "receive":
            condition = params.get("condition") or "ok"
            lines = [f"Mark received in condition '{condition}'."]
            return lines + (["Refund £25.00 to the original payment method."] if condition == "ok"
                            else ["Stop there for a decision, because the items are not as expected."])
        return {"decline": [f"Decline: {params.get('reason') or 'no reason given'}. Nothing in Shopify changes."],
                "note": ["Add a note to the timeline."], "complete": ["Refund £25.00 to the original payment method."],
                "cancel": ["Cancel the return."], "tracking": [f"Record tracking {params.get('number')} and mark it in transit."],
                "label": ["Book Evri (Evri ParcelShop) for £2.98 from Parcel2Go PrePay, balance £50.00."]}[action]
