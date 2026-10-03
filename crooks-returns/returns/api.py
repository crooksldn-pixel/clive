"""HTTP surface.

/proxy/api/*    the customer portal, reached only through the Shopify app proxy
                (crooksldn.com/apps/returns/api/* -> here), checked by Shopify's signature
/api/v1/*       CLIVE and staff: bearer keys, read or write
/files/*        label PDFs behind signed links (Shopify and the customer both fetch these)
/webhooks/*     Shopify webhooks, checked by HMAC
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from collections import Counter
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from returns import verify
from returns.models import Postage, Resolution, Selection, gbp
from returns.service import ActionError, ReturnsService


def proxy_signature_ok(query: list[tuple[str, str]], secret: str) -> bool:
    """Shopify app proxy signature: every query parameter except `signature`, as key=value
    with repeated keys joined by commas, sorted, concatenated with no separator, HMAC-SHA256
    in hex with the app's secret."""
    given = next((v for k, v in query if k == "signature"), "")
    grouped: dict[str, list[str]] = {}
    for k, v in query:
        if k != "signature":
            grouped.setdefault(k, []).append(v)
    message = "".join(sorted(f"{k}={','.join(v)}" for k, v in grouped.items()))
    want = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return bool(given) and hmac.compare_digest(want, given)


def webhook_ok(body: bytes, header: str, secret: str) -> bool:
    want = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return bool(header) and hmac.compare_digest(want, header)


def fail(exc: ActionError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


# --------------------------------------------------------------------------- bodies


class LookupBody(BaseModel):
    order: str = Field(max_length=40)
    proof: str = Field(max_length=200)


class SessionBody(BaseModel):
    session: str


class QuoteBody(SessionBody):
    items: list[Selection]


class SubmitBody(QuoteBody):
    resolution: Resolution
    postage: Postage
    exchange: dict[str, str] = Field(default_factory=dict)


class TrackingBody(SessionBody):
    return_id: str
    number: str = Field(max_length=40)


class ActionBody(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default="clive", max_length=80)
    idempotency_key: str = Field(default="", max_length=120)


# --------------------------------------------------------------------------- routers


def build_routers(svc: ReturnsService) -> list[APIRouter]:
    settings = svc.s

    # ------------------------------------------------------------------ portal

    def proxied(request: Request) -> None:
        if settings.dev_skip_proxy_signature:
            return
        if not proxy_signature_ok(
            list(request.query_params.multi_items()), settings.shopify_client_secret
        ):
            raise HTTPException(401, "Not signed by Shopify.")

    portal = APIRouter(prefix="/proxy/api", dependencies=[Depends(proxied)])

    @portal.post("/lookup")
    def lookup(body: LookupBody, request: Request) -> dict[str, Any]:
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "")
        try:
            session, order = svc.lookup(body.order, body.proof, ip.split(",")[0].strip())
        except ActionError as exc:
            raise fail(exc) from exc
        return {"session": session, **svc.portal_order(svc.available(order))}

    @portal.post("/order")
    def order(body: SessionBody) -> dict[str, Any]:
        try:
            return svc.portal_order(svc.order_for_session(body.session))
        except ActionError as exc:
            raise fail(exc) from exc

    @portal.post("/quote")
    def quote(body: QuoteBody) -> dict[str, Any]:
        try:
            q = svc.quote(svc.order_for_session(body.session), body.items)
        except ActionError as exc:
            raise fail(exc) from exc
        return {
            "items_total": gbp(q.items_pence),
            "options": [
                {
                    "resolution": o.resolution.value,
                    "headline": o.headline,
                    "detail": o.detail,
                    "postage": [
                        {"choice": p.choice.value, "label": p.label, "total": gbp(p.total_pence)}
                        for p in o.postage
                    ],
                    "exchange_choices": {
                        fli: [{"id": v.id, "title": v.title} for v in vs]
                        for fli, vs in o.exchange_choices.items()
                    },
                }
                for o in q.options
            ],
        }

    @portal.post("/submit")
    def submit(body: SubmitBody) -> dict[str, Any]:
        try:
            order = svc.order_for_session(body.session)
            ret = svc.submit(order, body.items, body.resolution, body.postage, body.exchange)
        except ActionError as exc:
            raise fail(exc) from exc
        return {"return": svc.public(ret)}

    @portal.post("/tracking")
    def tracking(body: TrackingBody) -> dict[str, Any]:
        try:
            order = svc.order_for_session(body.session)
            ret = svc.customer_tracking(order, body.return_id, body.number)
        except ActionError as exc:
            raise fail(exc) from exc
        return {"return": svc.public(ret)}

    # ------------------------------------------------------------------ CLIVE / staff

    def bearer(authorization: str | None) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Bearer key required.")
        return authorization[7:].strip()

    def can(kind: str, key: str) -> bool:
        return any(hmac.compare_digest(key, k) for k in settings.keys(kind))

    def reader(authorization: str | None = Header(default=None)) -> None:
        if not can("read", bearer(authorization)):
            raise HTTPException(403, "This key cannot read returns.")

    def writer(authorization: str | None = Header(default=None)) -> None:
        if not can("write", bearer(authorization)):
            raise HTTPException(403, "This key cannot act on returns.")

    api = APIRouter(prefix="/api/v1")

    @api.get("/returns", dependencies=[Depends(reader)])
    def list_returns(
        status: str | None = None,
        since: datetime | None = None,
        open: bool = False,
        limit: int = Query(100, le=500),
    ) -> dict[str, Any]:  # noqa: A002
        rows = svc.store.search(
            status=status.split(",") if status else None, since=since, open_only=open, limit=limit
        )
        return {"returns": [svc.staff(r) for r in rows]}

    @api.get("/returns/{return_id}", dependencies=[Depends(reader)])
    def get_return(return_id: str) -> dict[str, Any]:
        ret = svc.store.get(return_id)
        if ret is None:
            raise HTTPException(404, "Return not found.")
        return svc.staff(ret)

    @api.get("/orders/{order_name}/returns", dependencies=[Depends(reader)])
    def order_returns(order_name: str) -> dict[str, Any]:
        digits = re.sub(r"\D", "", order_name)
        rows = svc.store.for_order_name(order_name) or svc.store.for_order_name(f"#{digits}")
        return {"returns": [svc.staff(r) for r in rows]}

    @api.get("/stats", dependencies=[Depends(reader)])
    def stats(since: datetime | None = None) -> dict[str, Any]:
        rows = svc.store.search(since=since, limit=100_000)
        live = [r for r in rows if r.status.value not in ("declined", "cancelled")]
        value = sum(r.money.items_pence for r in live)
        kept = sum(r.money.items_pence for r in live if r.resolution != Resolution.refund)
        return {
            "returns": len(rows),
            "by_status": Counter(r.status.value for r in rows),
            "by_resolution": Counter(r.resolution.value for r in live),
            "by_reason": Counter(ln.reason.value for r in live for ln in r.lines),
            "by_sku": Counter(ln.sku or ln.title for r in live for ln in r.lines).most_common(20),
            "size_swaps": Counter(
                ln.exchange_direction for r in live for ln in r.lines if ln.exchange_direction
            ),
            "value_returned": gbp(value),
            "value_kept": gbp(kept),
            "kept_share": round(kept / value, 3) if value else None,
            "bonus_given": gbp(sum(r.money.bonus_pence for r in live)),
            "label_fees_recovered": gbp(sum(r.money.fee_pence for r in live)),
        }

    @api.post("/returns/{return_id}/actions/{action}/preview", dependencies=[Depends(reader)])
    def preview(return_id: str, action: str, body: ActionBody) -> dict[str, Any]:
        try:
            return svc.preview(return_id, action, body.params)
        except ActionError as exc:
            raise fail(exc) from exc

    @api.post("/returns/{return_id}/actions/{action}", dependencies=[Depends(writer)])
    def act(return_id: str, action: str, body: ActionBody) -> dict[str, Any]:
        try:
            out = svc.execute(return_id, action, body.params, body.actor, body.idempotency_key)
        except ActionError as exc:
            raise fail(exc) from exc
        ret = out.pop("return_doc")
        return {**out, "return": svc.staff(ret)}

    @api.post("/tick", dependencies=[Depends(writer)])
    def tick() -> dict[str, Any]:
        return {"overdue_flagged": svc.tick()}

    # ------------------------------------------------------------------ files, hooks, health

    misc = APIRouter()

    @misc.get("/files/{file_id}")
    def file(file_id: str, t: str = "") -> Response:
        payload = verify.unsign(t, settings.session_secret)
        if not payload or payload.get("kind") != "file" or payload.get("id") != file_id:
            raise HTTPException(404, "Not found.")
        found = svc.store.get_file(file_id)
        if not found:
            raise HTTPException(404, "Not found.")
        content_type, body = found
        return Response(
            body,
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="crooks-return-label-{file_id}.pdf"'
            },
        )

    @misc.post("/webhooks/shopify")
    async def shopify_webhook(request: Request) -> dict[str, Any]:
        body = await request.body()
        if not webhook_ok(
            body, request.headers.get("x-shopify-hmac-sha256", ""), settings.shopify_client_secret
        ):
            raise HTTPException(401, "Bad signature.")
        topic = request.headers.get("x-shopify-topic", "")
        data = await request.json()
        rid = data.get("admin_graphql_api_id") or ""
        if topic.startswith("returns/") and rid:
            ret = svc.shopify_changed(rid, topic)
            return {"ok": True, "return": ret.id if ret else None}
        return {"ok": True}

    @misc.get("/health")
    def health() -> dict[str, Any]:
        labels_ok, labels_why = svc.labels.available()
        return {
            "ok": True,
            "shopify": settings.shopify_backend,
            "labels": {"automatic": labels_ok, "why_not": labels_why or None},
            "policy": {
                "window_days": settings.window_days,
                "fault_window_days": settings.fault_window_days,
                "credit_bonus_bands": [
                    {"from": gbp(f), "bonus": gbp(b)} for f, b in settings.bonus_bands()
                ],
                "return_label_cost": (
                    gbp(settings.return_label_cost_pence)
                    if settings.return_label_cost_pence is not None
                    else None
                ),
                "exchange_ships": "when the return arrives back",
            },
            "clive": {
                "read_keys": bool(settings.keys("read")),
                "webhook": bool(settings.clive_webhook_url),
            },
        }

    return [portal, api, misc]
