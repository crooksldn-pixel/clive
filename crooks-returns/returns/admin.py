"""The staff screen inside Shopify admin (Apps -> CROOKS Returns).

Shopify loads /admin in an iframe. The page asks App Bridge for a session token (a short JWT
signed with the app's secret, naming the shop and the staff member) and sends it with every
call, so only people Shopify has let into the app can read or act. Actions are the same preview
and execute that CLIVE and returns-ctl use, signed on the timeline with the staff member's name.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from importlib import resources
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from returns.models import (
    OPEN_STATUSES,
    REASON_LABELS,
    PostageMode,
    Reason,
    Resolution,
    Return,
    Selection,
    Status,
    gbp,
)
from returns import policy
from returns.service import ActionError, ReturnsService

LEEWAY_S = 10
NAME_RETRY_S = 600  # a failed staff-name lookup is tried again after 10 minutes


class BadToken(Exception):
    pass


def _b64(part: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    except (binascii.Error, ValueError) as exc:
        raise BadToken("not base64") from exc


def verify_session_token(
    token: str, *, client_id: str, secret: str, shop_domain: str, now: float | None = None
) -> dict[str, Any]:
    """Check a Shopify admin session token: HS256 with the app secret, for this app, for this
    shop, inside its validity window. Returns its claims."""
    parts = token.split(".")
    if len(parts) != 3 or not secret:
        raise BadToken("malformed")
    try:
        header = json.loads(_b64(parts[0]))
        claims = json.loads(_b64(parts[1]))
    except ValueError as exc:
        raise BadToken("malformed") from exc
    if header.get("alg") != "HS256":
        raise BadToken("wrong algorithm")
    want = hmac.new(secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(want, _b64(parts[2])):
        raise BadToken("bad signature")
    now = time.time() if now is None else now
    if float(claims.get("exp", 0)) < now - LEEWAY_S:
        raise BadToken("expired")
    if float(claims.get("nbf", 0)) > now + LEEWAY_S:
        raise BadToken("not yet valid")
    aud = claims.get("aud")
    if client_id not in (aud if isinstance(aud, list) else [aud]):
        raise BadToken("for another app")
    if urlparse(str(claims.get("dest", ""))).hostname != shop_domain:
        raise BadToken("for another shop")
    return claims


# --------------------------------------------------------------------------- shaping


def numeric_id(gid: str | None) -> str | None:
    found = re.search(r"/(\d+)$", gid or "")
    return found.group(1) if found else None


def actions_for(ret: Return) -> list[str]:
    """What staff can do next, in the order the buttons appear."""
    by_status = {
        Status.requested: ["approve", "decline"],
        Status.awaiting_label: ["label", "receive", "cancel"],
        Status.awaiting_shipment: ["receive", "tracking", "cancel"],
        Status.in_transit: ["receive"],
        Status.received: ["complete"],
    }
    out = [*by_status.get(ret.status, [])]
    if (
        ret.origin == "staff"
        and ret.email is not None
        and ret.status
        in (
            Status.awaiting_shipment,
            Status.in_transit,
        )
    ):
        out.append("resend_email")
    return [*out, "note"]


EMAIL_WORDS = {
    "pending": "Waiting to send",
    "sending": "Sending",
    "sent": "Sent",
    "unknown": "Not confirmed yet: checking",
    "unconfirmed": "Not confirmed",
    "failed": "Not sent",
    "off": "Not sent: email isn't set up",
    "no_address": "Not sent: no email address",
}


def email_view(ret: Return) -> dict[str, Any] | None:
    e = ret.email
    if e is None:
        return None
    return {
        "status": e.status,
        "words": EMAIL_WORDS.get(e.status, e.status),
        "to": e.to,
        "sent_at": e.sent_at.isoformat() if e.sent_at else None,
        "error": e.error,
        "ok": e.status == "sent",
    }


def outcome(ret: Return) -> str:
    if ret.resolution == Resolution.exchange:
        swaps = [ln.exchange_variant_title for ln in ret.lines if ln.exchange_variant_title]
        return "Swap to " + ", ".join(swaps) if swaps else "Exchange"
    if ret.resolution == Resolution.store_credit:
        return f"{gbp(ret.money.credit_pence)} credit"
    return f"{gbp(ret.money.refund_pence)} refund"


def row(svc: ReturnsService, ret: Return) -> dict[str, Any]:
    staff = svc.staff(ret)
    return {
        "id": ret.id,
        "order_name": ret.order_name,
        "customer": ret.customer_name or ret.customer_email or "Guest",
        "items": ", ".join(
            f"{ln.quantity}× {ln.title}" + (f" / {ln.variant_title}" if ln.variant_title else "")
            for ln in ret.lines
        ),
        "reasons": sorted({REASON_LABELS[ln.reason] for ln in ret.lines}),
        "resolution": ret.resolution.value,
        "origin": ret.origin,
        "outcome": outcome(ret),
        "status": ret.status.value,
        "attention": staff["attention"],
        "created_at": ret.created_at.isoformat(),
        "updated_at": ret.updated_at.isoformat(),
    }


def detail(svc: ReturnsService, ret: Return) -> dict[str, Any]:
    doc = svc.staff(ret)
    for line, out in zip(ret.lines, doc["lines"], strict=True):
        out["reason_label"] = REASON_LABELS[line.reason]
    labels_ok, labels_why = svc.labels.available()
    p = ret.postage
    doc["label"] = {
        "service": p.service_name,
        "courier": p.carrier,
        "cost": gbp(p.label_price_pence) if p.label_price_pence is not None else None,
        "qr_url": svc.label_link(p.qr_file_id) if p.qr_file_id else None,
        "ref": p.label_ref.split(":")[1] if (p.label_ref or "").startswith("p2g:") else p.label_ref,
        "courier_stage": p.courier_stage,
        "shops": p.shops,
    }
    return {
        **doc,
        "row": row(svc, ret),
        "origin": ret.origin,
        "email": email_view(ret),
        "actions": actions_for(ret),
        "customer_message": svc.public(ret)["message"],
        "links": {
            "order": f"shopify://admin/orders/{numeric_id(ret.order_id)}",
            "customer": f"shopify://admin/customers/{numeric_id(ret.customer_id)}"
            if numeric_id(ret.customer_id)
            else None,
        },
        "labels": {
            "automatic": labels_ok,
            "why_not": labels_why or None,
            "name": getattr(svc.labels, "name", "Labels"),
        },
        "default_postage_mode": (
            svc._mode(ret, {}).value
            if labels_ok or svc._mode(ret, {}) != PostageMode.label_now
            else PostageMode.self_ship.value
        ),
    }


# Returns staff left out (tests) are only in their own view (and in a search).
VIEWS = {
    "todo": lambda r, a: bool(a) and r.left_out is None,
    "open": lambda r, a: r.status in OPEN_STATUSES and r.left_out is None,
    "done": lambda r, a: r.status not in OPEN_STATUSES and r.left_out is None,
    "all": lambda r, a: r.left_out is None,
    "left_out": lambda r, a: r.left_out is not None,
}


def matches(ret: Return, q: str) -> bool:
    q = q.strip().casefold()
    if not q:
        return True
    digits = re.sub(r"\D", "", q)
    hay = " ".join(
        x or "" for x in (ret.order_name, ret.customer_name, ret.customer_email, ret.id)
    ).casefold()
    return q in hay or bool(digits and digits == re.sub(r"\D", "", ret.order_name))


# --------------------------------------------------------------------------- bodies


class AdminAction(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(default="", max_length=120)


class LeaveOutBody(BaseModel):
    reason: str = Field(default="Test return", max_length=200)


class StaffLine(BaseModel):
    id: str = Field(max_length=200)
    quantity: int = Field(ge=1, le=100)
    reason: Reason
    note: str = Field(default="", max_length=500)


class NewReturnQuote(BaseModel):
    order_id: str = Field(max_length=200)
    lines: list[StaffLine] = Field(min_length=1, max_length=50)

    def selections(self) -> list[Selection]:
        return [
            Selection(
                fulfillment_line_item_id=x.id, quantity=x.quantity, reason=x.reason, note=x.note
            )
            for x in self.lines
        ]


class NewReturnBody(NewReturnQuote):
    refund_pence: int = Field(ge=0, le=10_000_000)
    courier: str | None = Field(default=None, max_length=60)
    idempotency_key: str = Field(min_length=8, max_length=120)


class PilotBody(BaseModel):
    orders: str = Field(default="", max_length=2000)


# --------------------------------------------------------------------------- router


def page_html(client_id: str) -> str:
    html = resources.files("returns").joinpath("static/admin.html").read_text("utf-8")
    return html.replace("{{CLIENT_ID}}", client_id)


def build_admin_router(svc: ReturnsService) -> APIRouter:
    s = svc.s
    names: dict[str, str] = {}
    # A failed name lookup is not repeated for a while: it sits in front of every admin call,
    # and a slow or refused token exchange made each tap (Approve's preview too) wait.
    missed: dict[str, float] = {}

    def staff(authorization: str | None = Header(default=None)) -> str:
        """The signed-in staff member's name, for the timeline."""
        token = (authorization or "")[7:].strip() if authorization else ""
        if not token and s.dev_skip_admin_auth:
            return "Staff (dev)"
        try:
            claims = verify_session_token(
                token,
                client_id=s.shopify_client_id,
                secret=s.shopify_client_secret,
                shop_domain=s.shop_domain,
            )
        except BadToken as exc:
            raise HTTPException(401, "Open this from the Apps menu in Shopify admin.") from exc
        sub = str(claims.get("sub", ""))
        if sub not in names and time.monotonic() - missed.get(sub, -1e9) > NAME_RETRY_S:
            found = svc.shopify.staff_member(token)
            if found:
                names[sub] = found
            else:
                missed[sub] = time.monotonic()
        return names.get(sub) or f"Staff {sub}".strip()

    router = APIRouter(prefix="/admin")

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    def page() -> HTMLResponse:
        return HTMLResponse(
            page_html(s.shopify_client_id),
            headers={
                # Only Shopify admin may frame this page.
                "Content-Security-Policy": (
                    f"frame-ancestors https://{s.shop_domain} https://admin.shopify.com;"
                ),
                "Cache-Control": "no-store",
            },
        )

    @router.get("/api/overview")
    def overview(who: str = Depends(staff)) -> dict[str, Any]:
        rows = svc.store.search(limit=5000)
        attention = {r.id: svc.staff(r)["attention"] for r in rows}
        labels_ok, labels_why = svc.labels.available()
        return {
            "me": who,
            "counts": {v: sum(f(r, attention[r.id]) for r in rows) for v, f in VIEWS.items()},
            "stats": svc.stats(),
            "pilot": sorted(svc.pilot_orders(), key=int),
            "labels": {
                "automatic": labels_ok,
                "why_not": labels_why or None,
                "name": getattr(svc.labels, "name", "Labels"),
            },
            "shop": s.shop_domain,
        }

    @router.get("/api/checks")
    def checks(who: str = Depends(staff)) -> dict[str, Any]:
        return {"checks": svc.checks()}

    @router.get("/api/returns")
    def list_returns(view: str = "todo", q: str = "", who: str = Depends(staff)) -> dict[str, Any]:
        keep = VIEWS.get(view, VIEWS["all"])
        out = []
        for ret in svc.store.search(limit=5000):
            r = row(svc, ret)
            if (q or keep(ret, r["attention"])) and matches(ret, q):
                out.append(r)
        return {"returns": out[:300]}

    @router.get("/api/returns/{return_id}")
    def get_return(return_id: str, who: str = Depends(staff)) -> dict[str, Any]:
        ret = svc.store.get(return_id)
        if ret is None:
            raise HTTPException(404, "Return not found.")
        return detail(svc, ret)

    # ------------------------------------------------ a return staff issue for a customer

    @router.get("/api/new-return/order")
    def new_return_order(ref: str, who: str = Depends(staff)) -> dict[str, Any]:
        """The order to issue a return on: its items still returnable, the customer, and the
        drop-off options for their address (with the nearest shops)."""
        try:
            order = svc.staff_order(ref)
        except ActionError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        labels_ok, labels_why = svc.labels.available()
        address = order.shipping_address or {}
        return {
            "order_id": order.id,
            "order_name": order.name,
            "customer": order.customer_name or "Guest",
            "email": order.email or order.customer_email,
            "postcode": address.get("zip") or order.shipping_zip,
            "lines": [
                {
                    "id": ln.fulfillment_line_item_id,
                    "title": ln.title,
                    "variant": ln.variant_title,
                    "image": ln.image_url,
                    "price": gbp(ln.unit_paid_pence),
                    "returnable_qty": ln.returnable_qty,
                }
                for ln in order.lines
            ],
            "reasons": policy.reason_list(),
            "drop_offs": [
                {**o, "price": gbp(o["price_pence"])} for o in svc.drop_off_options(order)
            ],
            "labels": {
                "automatic": labels_ok,
                "why_not": labels_why or None,
                "name": getattr(svc.labels, "name", "Labels"),
            },
            "email_on": svc.mailer.enabled,
        }

    @router.post("/api/new-return/quote")
    def new_return_quote(body: NewReturnQuote, who: str = Depends(staff)) -> dict[str, Any]:
        try:
            q = svc.staff_quote(body.order_id, body.selections())
        except ActionError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return {
            **q,
            "default_refund": gbp(q["default_refund_pence"]),
            "max_refund": gbp(q["max_refund_pence"]),
        }

    @router.post("/api/new-return")
    def new_return(body: NewReturnBody, who: str = Depends(staff)) -> dict[str, Any]:
        """Create the return, approve it with a label (bought once, as any approval), and email
        the customer its QR code and drop-off points."""
        try:
            ret = svc.create_for_customer(
                body.order_id,
                body.selections(),
                body.refund_pence,
                body.courier,
                who,
                body.idempotency_key,
            )
        except ActionError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return detail(svc, ret)

    @router.post("/api/returns/{return_id}/resend-email")
    def resend_email(return_id: str, who: str = Depends(staff)) -> dict[str, Any]:
        try:
            return detail(svc, svc.resend_label_email(return_id, who))
        except ActionError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    # Before the general action routes, which would otherwise take these paths.
    @router.post("/api/returns/{return_id}/leave-out")
    def leave_out(return_id: str, body: LeaveOutBody, who: str = Depends(staff)) -> dict[str, Any]:
        try:
            return detail(svc, svc.leave_out(return_id, who, body.reason))
        except ActionError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @router.post("/api/returns/{return_id}/put-back")
    def put_back(return_id: str, who: str = Depends(staff)) -> dict[str, Any]:
        try:
            return detail(svc, svc.put_back(return_id, who))
        except ActionError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @router.post("/api/returns/{return_id}/{action}/preview")
    def preview(
        return_id: str, action: str, body: AdminAction, who: str = Depends(staff)
    ) -> dict[str, Any]:
        try:
            return svc.preview(return_id, action, body.params)
        except ActionError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @router.post("/api/returns/{return_id}/{action}")
    def act(
        return_id: str, action: str, body: AdminAction, who: str = Depends(staff)
    ) -> dict[str, Any]:
        try:
            out = svc.execute(
                return_id, action, body.params, who, body.idempotency_key, source="ui"
            )
        except ActionError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        ret = out.pop("return_doc")
        return {**out, "return": detail(svc, ret)}

    @router.post("/api/pilot")
    def set_pilot(body: PilotBody, who: str = Depends(staff)) -> dict[str, Any]:
        return {"pilot": sorted(svc.set_pilot_orders(body.orders, who), key=int)}

    return router
