"""HTTP surface of CLIVE Preorders (served at https://<host>/preorders/* by Caddy).

/admin, /admin/api/*   the embedded screens, Shopify admin session tokens
/api/v1/*              CLIVE and other systems: bearer keys (read / write)
/proxy/preorders/*     the storefront, through the app proxy (crooksldn.com/apps/returns/
                       preorders/*), checked by Shopify's signature
/webhooks/shopify      Shopify webhooks, HMAC-checked, recorded and answered at once
/health                liveness
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import asynccontextmanager
from importlib import resources
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from preorders.auth import BadToken, verify_session_token
from preorders.comms import Communications, RecordingMailer, build_mailer
from preorders.fake import FakeShopify
from preorders.reconcile import last_report, reconcile
from preorders.selling_plans import OFF, ShopifyPlans, UnavailablePlans
from preorders.service import ActionError, PreordersService
from preorders.settings import Settings, get_settings
from preorders.shopify import GraphQLShopify, ShopifyError
from preorders.store import Store
from preorders.waitlist import Waitlist

log = logging.getLogger("preorders.app")


def build_service(settings: Settings, shopify: Any = None, mailer: Any = None) -> PreordersService:
    if shopify is None:
        shopify = (
            FakeShopify()
            if settings.shopify_backend == "fake"
            else GraphQLShopify(
                settings.shop_domain, settings.shopify_client_id, settings.shopify_client_secret
            )
        )
    plans = ShopifyPlans(shopify) if settings.selling_plans == "shopify" else UnavailablePlans(OFF)
    svc = PreordersService(settings, Store(settings.db_path), shopify, plans)
    svc.comms = Communications(
        svc,
        mailer
        or (RecordingMailer() if settings.shopify_backend == "fake" else build_mailer(settings)),
    )
    svc.waitlist = Waitlist(svc)
    return svc


def gid(kind: str, n: str) -> str:
    n = str(n)
    return n if n.startswith("gid://") else f"gid://shopify/{kind}/{n}"


def webhook_ok(body: bytes, header: str, secret: str) -> bool:
    want = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return bool(secret) and hmac.compare_digest(want.encode(), (header or "").encode())


def proxy_signature_ok(query: list[tuple[str, str]], secret: str) -> bool:
    """Shopify app proxy signature: every parameter except `signature`, key=value with repeated
    keys joined by commas, sorted, concatenated, HMAC-SHA256 hex with the app secret."""
    given = next((v for k, v in query if k == "signature"), "")
    grouped: dict[str, list[str]] = {}
    for k, v in query:
        if k != "signature":
            grouped.setdefault(k, []).append(v)
    message = "".join(sorted(f"{k}={','.join(v)}" for k, v in grouped.items()))
    want = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return bool(given and secret) and hmac.compare_digest(want.encode(), given.encode())


PROXY_MAX_AGE_S = 300


class RateLimiter:
    def __init__(self, limit: int, window_s: int) -> None:
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        q, t = self.hits[key], time.monotonic()
        while q and t - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(t)
        return True


def problem(exc: ActionError) -> HTTPException:
    return HTTPException(exc.status, {"message": str(exc), "code": exc.code})


# ------------------------------------------------------------------ bodies


class BatchLineBody(BaseModel):
    variant_id: str = Field(max_length=80)
    expected_quantity: int = Field(ge=1, le=100000)
    preorder_allocation: int | None = Field(default=None, ge=0, le=100000)


class BatchBody(BaseModel):
    reference: str = Field(max_length=80)
    expected_arrival_at: str | None = Field(default=None, max_length=10)
    expected_dispatch_at: str | None = Field(default=None, max_length=10)
    supplier_reference: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=2000)
    status: str = Field(default="ORDERED", max_length=20)
    lines: list[BatchLineBody] = Field(default_factory=list, max_length=200)


class LineChangeBody(BaseModel):
    expected_quantity: int | None = Field(default=None, ge=0, le=100000)
    preorder_allocation: int | None = Field(default=None, ge=0, le=100000)


class StatusBody(BaseModel):
    status: str = Field(max_length=20)


class DispatchBody(BaseModel):
    expected_dispatch_at: str = Field(max_length=10)
    expected_arrival_at: str | None = Field(default=None, max_length=10)
    delayed: bool = False
    notify: bool = False


class ReceiveBody(BaseModel):
    quantity: int = Field(ge=1, le=100000)
    key: str = Field(min_length=8, max_length=80)


class OfferBody(BaseModel):
    product_id: str = Field(max_length=80)
    batch_id: str = Field(max_length=40)
    discount_type: str = Field(default="NONE", max_length=12)
    discount_value: float = Field(default=0, ge=0, lt=100)
    dispatch_at: str | None = Field(default=None, max_length=10)
    variants: list[str] | None = Field(default=None, max_length=100)
    mode: str = Field(default="AUTO", max_length=20)


class SignupBody(BaseModel):
    variant_id: str = Field(max_length=80)
    email: str = Field(max_length=254)
    customer_id: str | None = Field(default=None, max_length=40)


# ------------------------------------------------------------------ routers


def admin_router(
    svc: PreordersService, settings: Settings, reconcile_now: Callable[[str], dict[str, Any]]
) -> APIRouter:
    router = APIRouter(prefix="/admin")
    shop = settings.shop_domain

    def staff(authorization: str | None = Header(default=None)) -> str:
        token = (authorization or "")[7:].strip() if authorization else ""
        if not token and settings.dev_skip_admin_auth:
            return "Staff (dev)"
        try:
            claims = verify_session_token(
                token,
                client_id=settings.shopify_client_id,
                secret=settings.shopify_client_secret,
                shop_domain=shop,
            )
        except BadToken as exc:
            raise HTTPException(401, "Open this from the Apps menu in Shopify admin.") from exc
        return f"Staff {claims.get('sub', '')}".strip()

    def act(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except ActionError as exc:
            raise problem(exc) from exc

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    def page() -> HTMLResponse:
        html = resources.files("preorders").joinpath("static/admin.html").read_text("utf-8")
        return HTMLResponse(
            html.replace("{{CLIENT_ID}}", settings.shopify_client_id),
            headers={
                "Content-Security-Policy": "frame-ancestors "
                f"https://{shop} https://admin.shopify.com;"
            },
        )

    @router.get("/api/overview")
    def overview(_: str = Depends(staff)) -> dict[str, Any]:
        return {**svc.overview(), "email_enabled": svc.comms.enabled}

    @router.get("/api/products")
    def products(view: str = "all", q: str = "", _: str = Depends(staff)) -> dict[str, Any]:
        return {"rows": svc.products(view, q[:80])}

    @router.post("/api/catalog/refresh")
    def refresh(who: str = Depends(staff)) -> dict[str, Any]:
        n = svc.refresh_catalog()
        svc.sync_all()
        return {"variants": n}

    @router.get("/api/variants/{n}")
    def variant(n: str, _: str = Depends(staff)) -> dict[str, Any]:
        vid = gid("ProductVariant", n)
        cat = act(lambda: svc.variant(vid))
        ov = svc._live_offer_variant(vid)
        lines = svc.store.all(
            "SELECT bl.*, b.reference, b.status, b.expected_dispatch_at FROM batch_lines bl JOIN "
            "batches b ON b.id = bl.batch_id WHERE bl.variant_id = ? ORDER BY b.created_at DESC",
            (vid,),
        )
        return {
            "variant": cat,
            "state": svc.state_of(vid).value,
            "offer": svc.offer_view(ov["offer_id"]) if ov else None,
            "batch_lines": lines,
            "waitlist": svc.waitlist.notify_preview(vid),
        }

    @router.get("/api/batches")
    def batches(_: str = Depends(staff)) -> dict[str, Any]:
        return {"batches": svc.batches()}

    @router.post("/api/batches")
    def create_batch(body: BatchBody, who: str = Depends(staff)) -> dict[str, Any]:
        lines = [
            {**x.model_dump(), "variant_id": gid("ProductVariant", x.variant_id)}
            for x in body.lines
        ]
        return act(
            lambda: svc.create_batch(
                reference=body.reference,
                expected_arrival_at=body.expected_arrival_at,
                expected_dispatch_at=body.expected_dispatch_at,
                supplier_reference=body.supplier_reference,
                notes=body.notes,
                status=body.status,
                lines=lines,
                actor=who,
            )
        )

    @router.get("/api/batches/{bid}")
    def batch(bid: str, _: str = Depends(staff)) -> dict[str, Any]:
        b = act(lambda: svc.batch(bid))
        return {**b, "audience": svc.comms.audience(bid), "release": svc.release_preview(bid)}

    @router.post("/api/batches/{bid}/lines")
    def add_line(bid: str, body: BatchLineBody, who: str = Depends(staff)) -> dict[str, Any]:
        line = {**body.model_dump(), "variant_id": gid("ProductVariant", body.variant_id)}
        return act(lambda: svc.add_batch_line(bid, line, who))

    @router.patch("/api/batch-lines/{lid}")
    def change_line(lid: str, body: LineChangeBody, who: str = Depends(staff)) -> dict[str, Any]:
        return act(
            lambda: svc.update_batch_line(
                lid,
                expected_quantity=body.expected_quantity,
                preorder_allocation=body.preorder_allocation,
                actor=who,
            )
        )

    @router.post("/api/batches/{bid}/status")
    def status(bid: str, body: StatusBody, who: str = Depends(staff)) -> dict[str, Any]:
        return act(lambda: svc.set_batch_status(bid, body.status, who))

    @router.post("/api/batches/{bid}/dispatch")
    def dispatch(bid: str, body: DispatchBody, who: str = Depends(staff)) -> dict[str, Any]:
        out = act(
            lambda: svc.change_dispatch(
                bid,
                expected_dispatch_at=body.expected_dispatch_at,
                expected_arrival_at=body.expected_arrival_at,
                delayed=body.delayed,
                actor=who,
            )
        )
        if body.notify:
            out["notified"] = act(lambda: _notify(lambda: svc.comms.notify_delay(bid, who)))
        return out

    @router.post("/api/batches/{bid}/notify-update")
    def notify_update(bid: str, who: str = Depends(staff)) -> dict[str, Any]:
        return {"notified": act(lambda: _notify(lambda: svc.comms.notify_update(bid, who)))}

    @router.post("/api/batch-lines/{lid}/receive")
    def receive(lid: str, body: ReceiveBody, who: str = Depends(staff)) -> dict[str, Any]:
        return act(lambda: svc.receive(lid, body.quantity, body.key, who))

    @router.post("/api/batches/{bid}/release")
    def release(bid: str, who: str = Depends(staff)) -> dict[str, Any]:
        return act(lambda: svc.release_ready(bid, who))

    @router.post("/api/offers")
    def save_offer(body: OfferBody, who: str = Depends(staff)) -> dict[str, Any]:
        variants = (
            [gid("ProductVariant", v) for v in body.variants] if body.variants is not None else None
        )
        return act(
            lambda: svc.configure_offer(
                product_id=gid("Product", body.product_id),
                batch_id=body.batch_id,
                discount_type=body.discount_type,
                discount_value=body.discount_value,
                dispatch_at=body.dispatch_at,
                variants=variants,
                mode=body.mode,
                actor=who,
            )
        )

    @router.get("/api/offers/{oid}")
    def offer(oid: str, _: str = Depends(staff)) -> dict[str, Any]:
        return act(lambda: svc.offer_view(oid))

    @router.post("/api/offers/{oid}/activate")
    def activate(oid: str, who: str = Depends(staff)) -> dict[str, Any]:
        return act(lambda: svc.activate_offer(oid, who))

    @router.post("/api/offers/{oid}/close")
    def close(oid: str, who: str = Depends(staff)) -> dict[str, Any]:
        return act(lambda: svc.close_offer(oid, who))

    @router.get("/api/preorders")
    def preorders(view: str = "all", q: str = "", _: str = Depends(staff)) -> dict[str, Any]:
        return {"rows": svc.preorder_lines(view, q[:80])}

    @router.get("/api/waitlist")
    def demand(view: str = "most_wanted", _: str = Depends(staff)) -> dict[str, Any]:
        return {"rows": svc.waitlist.demand(view), "email_enabled": svc.comms.enabled}

    @router.get("/api/waitlist/{n}")
    def waiting(n: str, _: str = Depends(staff)) -> dict[str, Any]:
        vid = gid("ProductVariant", n)
        return {
            "variant": act(lambda: svc.variant(vid)),
            "subscribers": svc.waitlist.subscribers(vid),
            "preview": svc.waitlist.notify_preview(vid),
        }

    @router.post("/api/waitlist/{n}/notify")
    def notify(n: str, who: str = Depends(staff)) -> dict[str, Any]:
        return {"notified": act(lambda: svc.waitlist.notify(gid("ProductVariant", n), who))}

    @router.delete("/api/waitlist/subscriptions/{sid}")
    def delete_signup(sid: str, who: str = Depends(staff)) -> dict[str, Any]:
        svc.waitlist.delete(sid, who)
        return {"ok": True}

    @router.get("/api/communications")
    def communications(_: str = Depends(staff)) -> dict[str, Any]:
        return {"rows": svc.comms.log(), "email_enabled": svc.comms.enabled}

    @router.post("/api/reconcile")
    def run_reconcile(who: str = Depends(staff)) -> dict[str, Any]:
        return reconcile_now(who)

    @router.get("/api/health")
    def health_view(_: str = Depends(staff)) -> dict[str, Any]:
        report = last_report(svc)
        return {
            "last_reconcile": {**report, "detail": json.loads(report["detail"])}
            if report
            else None,
            "inbox_waiting": svc.store.value(
                "SELECT COUNT(*) FROM webhook_inbox WHERE processed_at IS NULL"
            ),
            "plans_available": svc.plans.available,
            "plans_reason": svc.plans.reason,
            "email_enabled": svc.comms.enabled,
        }

    def _notify(send: Callable[[], dict[str, int]]) -> dict[str, int]:
        if not svc.comms.enabled:
            raise ActionError(
                "Email isn't set up on the server (PREORDERS_EMAIL_PROVIDER): nothing was sent.",
                503,
                "email_off",
            )
        return send()

    return router


def api_router(svc: PreordersService, settings: Settings) -> APIRouter:
    """CLIVE's view. Reads only for now: dispatch decisions belong to CLIVE Shipping."""
    router = APIRouter(prefix="/api/v1")

    def reader(authorization: str | None = Header(default=None)) -> None:
        key = (
            (authorization or "")[7:].strip()
            if (authorization or "").lower().startswith("bearer ")
            else ""
        )
        if not key:
            raise HTTPException(401, "A bearer key is required.")
        if not any(hmac.compare_digest(key.encode(), k.encode()) for k in settings.keys("read")):
            raise HTTPException(403, "This key cannot read preorders.")

    @router.get("/capabilities", dependencies=[Depends(reader)])
    def capabilities() -> dict[str, Any]:
        return {
            "service": "CLIVE Preorders",
            "operations": [
                {
                    "method": "GET",
                    "path": "/api/v1/lines/{line_item_id}/classification",
                    "does": "Can this order line be dispatched now: IN_STOCK, PREORDER_WAITING, "
                    "PREORDER_READY or CANCELLED, with the dates and batch.",
                },
                {
                    "method": "GET",
                    "path": "/api/v1/orders/{order_id}/classification",
                    "does": "The same for every line of an order (mixed orders).",
                },
                {
                    "method": "GET",
                    "path": "/api/v1/variants/{variant_id}/state",
                    "does": "IN_STOCK, PREORDER or NOTIFY_ME for a variant.",
                },
                {"method": "GET", "path": "/api/v1/preorders?view=", "does": "Preorder lines."},
                {"method": "GET", "path": "/api/v1/batches", "does": "Inbound batches."},
            ],
        }

    @router.get("/lines/{n}/classification", dependencies=[Depends(reader)])
    def line(n: str) -> dict[str, Any]:
        return svc.classify_line(gid("LineItem", n))

    @router.get("/orders/{n}/classification", dependencies=[Depends(reader)])
    def order(n: str) -> dict[str, Any]:
        try:
            return svc.classify_order(gid("Order", n))
        except ActionError as exc:
            raise problem(exc) from exc

    @router.get("/variants/{n}/state", dependencies=[Depends(reader)])
    def state(n: str) -> dict[str, Any]:
        return {
            "variant_id": gid("ProductVariant", n),
            "state": svc.state_of(gid("ProductVariant", n)).value,
        }

    @router.get("/preorders", dependencies=[Depends(reader)])
    def lines(view: str = "all") -> dict[str, Any]:
        rows = svc.preorder_lines(view)
        return {
            "rows": [
                {
                    k: r[k]
                    for k in (
                        "order_id",
                        "order_name",
                        "line_item_id",
                        "variant_id",
                        "sku",
                        "title",
                        "current_quantity",
                        "fulfilled_quantity",
                        "ready_quantity",
                        "state",
                        "promised_dispatch_at",
                        "current_dispatch_at",
                        "batch_id",
                        "selling_plan_id",
                    )
                }
                for r in rows
            ]
        }

    @router.get("/batches", dependencies=[Depends(reader)])
    def batches() -> dict[str, Any]:
        return {
            "batches": [
                {
                    k: b[k]
                    for k in (
                        "id",
                        "reference",
                        "status",
                        "expected_arrival_at",
                        "expected_dispatch_at",
                        "totals",
                    )
                }
                for b in svc.batches()
            ]
        }

    return router


def proxy_router(svc: PreordersService, settings: Settings) -> APIRouter:
    """The storefront, through Shopify's signed app proxy. No customer account needed."""
    router = APIRouter(prefix="/proxy/preorders")
    per_ip = RateLimiter(settings.signup_ip_limit, 3600)

    def signed(request: Request) -> None:
        if settings.dev_skip_admin_auth and "signature" not in request.query_params:
            return
        if not proxy_signature_ok(
            list(request.query_params.multi_items()), settings.shopify_client_secret
        ):
            raise HTTPException(401, "Not signed by Shopify.")
        # Shopify signs each request as it forwards it: an old signed URL is a replay.
        try:
            age = abs(time.time() - int(request.query_params.get("timestamp", "")))
        except ValueError:
            raise HTTPException(401, "Not signed by Shopify.") from None
        if age > PROXY_MAX_AGE_S:
            raise HTTPException(401, "This request has expired.")
        if settings.shop_domain and request.query_params.get("shop") != settings.shop_domain:
            raise HTTPException(401, "Not this store.")

    @router.post("/waitlist", dependencies=[Depends(signed)])
    def signup(body: SignupBody, request: Request) -> JSONResponse:
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "")
        if not per_ip.allow(ip.split(",")[0].strip()):
            return JSONResponse({"message": "Too many tries. Try again later."}, status_code=429)
        customer = request.query_params.get("logged_in_customer_id") or None
        try:
            out = svc.waitlist.signup(
                variant_id=gid("ProductVariant", body.variant_id),
                email=body.email,
                source="storefront",
                customer_id=customer,
            )
        except ActionError as exc:
            return JSONResponse({"message": str(exc)}, status_code=exc.status)
        return JSONResponse(out)

    @router.get(
        "/waitlist/unsubscribe", response_class=HTMLResponse, dependencies=[Depends(signed)]
    )
    def unsubscribe(id: str = "", t: str = "") -> HTMLResponse:
        ok = svc.waitlist.unsubscribe(id[:40], t[:64])
        words = (
            "You won't get any more alerts for this size."
            if ok
            else "That link isn't valid any more."
        )
        # Liquid page through the app proxy: rendered inside the store's theme.
        return HTMLResponse(
            f'<div style="max-width:520px;margin:48px auto;padding:0 16px">'
            f"<h1>Notify me</h1><p>{words}</p></div>",
            headers={"Content-Type": "application/liquid"},
        )

    @router.get("/state", dependencies=[Depends(signed)])
    def state(variant: str = "") -> dict[str, Any]:
        vid = gid("ProductVariant", variant[:40])
        return {"variant_id": vid, "state": svc.state_of(vid).value}

    return router


def create_app(
    settings: Settings | None = None, service: PreordersService | None = None
) -> FastAPI:
    settings = settings or get_settings()
    svc = service or build_service(settings)
    timers = {"reconcile": time.monotonic(), "catalog": 0.0, "purge": 0.0}

    def reconcile_now(actor: str) -> dict[str, Any]:
        timers["reconcile"] = time.monotonic()
        return reconcile(svc, actor)

    def tick() -> None:
        svc.process_inbox()
        if time.monotonic() - timers["catalog"] > 600:
            timers["catalog"] = time.monotonic()
            try:
                svc.refresh_catalog()
                svc.sync_all()
            except ShopifyError as exc:
                log.warning("catalogue refresh failed: %s", exc)
        if (
            settings.reconcile_every_min
            and time.monotonic() - timers["reconcile"] > settings.reconcile_every_min * 60
        ):
            reconcile_now("system")
        if time.monotonic() - timers["purge"] > 86400:
            timers["purge"] = time.monotonic()
            svc.waitlist.purge_old()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def ticker() -> None:
            while True:
                await asyncio.sleep(settings.tick_interval_s)
                try:
                    await run_in_threadpool(tick)
                except Exception:  # noqa: BLE001 - one failed sweep must not stop the next
                    log.exception("tick failed")

        task = asyncio.create_task(ticker()) if settings.tick_interval_s > 0 else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        lifespan=lifespan, title="CLIVE Preorders", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.svc = svc
    app.state.tick = tick

    @app.exception_handler(ShopifyError)
    async def shopify_down(request: Request, exc: ShopifyError) -> JSONResponse:
        log.error("%s %s: Shopify: %s", request.method, request.url.path, exc)
        return JSONResponse(
            {
                "detail": {
                    "message": "Shopify didn't answer just now. Try again in "
                    "a minute; anything already saved is kept.",
                    "code": "shopify_unavailable",
                }
            },
            status_code=503,
        )

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, Any]:
        return {"ok": True}

    @app.post("/webhooks/shopify", include_in_schema=False)
    async def webhook(request: Request) -> dict[str, Any]:
        body = await request.body()
        if not webhook_ok(
            body, request.headers.get("x-shopify-hmac-sha256", ""), settings.shopify_client_secret
        ):
            raise HTTPException(401, "Bad signature.")
        topic = request.headers.get("x-shopify-topic", "")
        event_id = (
            request.headers.get("x-shopify-event-id")
            or request.headers.get("x-shopify-webhook-id")
            or ""
        )
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise HTTPException(400, "Not JSON.") from exc
        if topic.startswith("orders/"):
            resource = str(data.get("admin_graphql_api_id") or "")
        elif topic == "inventory_levels/update":
            resource = gid("InventoryItem", str(data.get("inventory_item_id") or ""))
        elif topic == "customers/redact":
            email = (data.get("customer") or {}).get("email") or ""
            await run_in_threadpool(svc.waitlist.redact_email, email)
            return {"ok": True}
        else:
            return {"ok": True, "ignored": topic}
        if resource and event_id:
            await run_in_threadpool(svc.record_webhook, event_id, topic, resource)
        return {"ok": True}

    app.include_router(admin_router(svc, settings, reconcile_now))
    app.include_router(api_router(svc, settings))
    app.include_router(proxy_router(svc, settings))
    return app


def __getattr__(name: str) -> Any:
    # `uvicorn preorders.app:app` builds the app from the environment on first use.
    if name == "app":
        return create_app()
    raise AttributeError(name)
