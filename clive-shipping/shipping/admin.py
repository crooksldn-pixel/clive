"""The embedded admin (Apps → CLIVE Shipping): inbox, shipment detail, Setup.

Shopify loads /admin in an iframe; the page asks App Bridge for a session token with every
call, so only staff Shopify let into the app can read or act. Buying uses the same preview →
basis → buy protocol as everything else: the page shows the preview's price and sends its
basis back with an idempotency key made once per click intent, so a double click, a retry or
a lost reply can never buy twice. Print and reprint go through printing.py, which can't buy.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from importlib import resources
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from shipping import views
from shipping.auth import BadToken, verify_session_token
from shipping.models import Address, ShipmentStatus
from shipping.money import Money
from shipping.printing import PrintError, Printing
from shipping.providers.base import ProviderError
from shipping.purchase import ActionError, Stale
from shipping.service import ShippingService
from shipping.settings import Settings
from shipping.shopify import ShopifyError
from shipping.store import Conflict

log = logging.getLogger("shipping.admin")


def page_html(client_id: str) -> str:
    html = resources.files("shipping").joinpath("static/admin.html").read_text("utf-8")
    return html.replace("{{CLIENT_ID}}", client_id)


def problem(exc: ActionError | PrintError) -> HTTPException:
    code = exc.code if isinstance(exc, ActionError) else "print"
    detail = {"message": str(exc), "code": code}
    if isinstance(exc, Stale):
        detail["title"] = views.STALE
    return HTTPException(exc.status, detail)


# --------------------------------------------------------------------------- bodies


class AnswerBody(BaseModel):
    kind: str = Field(max_length=40)
    subject: str = Field(max_length=200)
    value: dict[str, Any] = Field(default_factory=dict)


class PackageBody(BaseModel):
    preset_id: str = Field(max_length=60)


class ServiceBody(BaseModel):
    service_code: str = Field(max_length=120)


class BuyBody(BaseModel):
    basis: str = Field(min_length=4, max_length=80)
    # Made once per click intent by the page; the same key replays, never re-buys.
    idempotency_key: str = Field(min_length=8, max_length=120)


class PresetBody(BaseModel):
    name: str = Field(max_length=60)
    length_cm: float
    width_cm: float
    height_cm: float
    empty_weight_g: int
    make_default: bool = False


class SetupBody(BaseModel):
    origin: Address | None = None
    default_package_id: str | None = Field(default=None, max_length=60)
    eori_number: str | None = Field(default=None, max_length=20)
    vat_number: str | None = Field(default=None, max_length=20)
    ioss_number: str | None = Field(default=None, max_length=20)
    notify_customer: bool | None = None


# --------------------------------------------------------------------------- router


def build_admin_router(
    svc: ShippingService,
    settings: Settings,
    connection: Callable[[], dict[str, Any]],
) -> APIRouter:
    shop = settings.shop_domain
    printing = Printing(svc.store, clock=svc.clock)

    def staff(authorization: str | None = Header(default=None)) -> str:
        """The signed-in staff member, for the timeline."""
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

    def shipment(sid: str):
        s = svc.store.get(shop, sid)
        if s is None:
            raise HTTPException(404, {"message": "Shipment not found.", "code": "not_found"})
        return s

    def presets() -> list[dict[str, Any]]:
        cfg = svc.store.config(shop)
        return [
            {
                "id": p.id,
                "name": p.name,
                "size": f"{p.length_mm / 10:g} × {p.width_mm / 10:g} × {p.height_mm / 10:g} cm",
                "empty_weight": f"{p.empty_weight_g} g",
                "default": p.id == cfg.default_package_id,
            }
            for p in cfg.packages
        ]

    def detail_of(sid: str) -> dict[str, Any]:
        s = shipment(sid)
        return views.detail(s, svc.recommendation(s), presets())

    def act(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except (ActionError, PrintError) as exc:
            raise problem(exc) from exc
        except Conflict as exc:
            raise HTTPException(
                409,
                {"message": "This order was updated meanwhile. Look at it again.", "code": "busy"},
            ) from exc

    router = APIRouter(prefix="/admin")

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    def page() -> HTMLResponse:
        return HTMLResponse(
            page_html(settings.shopify_client_id),
            headers={
                # Only Shopify admin may frame this page.
                "Content-Security-Policy": (
                    f"frame-ancestors https://{shop} https://admin.shopify.com;"
                ),
                "Cache-Control": "no-store",
            },
        )

    # ------------------------------------------------------------------ inbox

    @router.get("/api/inbox")
    def inbox(q: str = "", who: str = Depends(staff)) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {
            views.GROUP_READY: [],
            views.GROUP_ATTENTION: [],
            views.GROUP_BOUGHT: [],
            views.GROUP_DONE: [],
        }
        for s in sorted(svc.store.shipments(shop), key=lambda x: x.created_at, reverse=True):
            if not views.matches(s, q):
                continue
            r = views.row(s)
            groups[r["status"]["group"]].append(r)
        if not q:
            groups[views.GROUP_DONE] = groups[views.GROUP_DONE][:20]
            groups[views.GROUP_BOUGHT] = groups[views.GROUP_BOUGHT][:50]
        cfg = svc.store.config(shop)
        return {
            "me": who,
            "groups": groups,
            "counts": {k: len(v) for k, v in groups.items()},
            "ready_to_print": len(printing.ready(shop)),
            "setup": {
                "origin": cfg.origin is not None,
                "package": bool(cfg.packages),
            },
        }

    @router.post("/api/sync")
    def sync(who: str = Depends(staff)) -> dict[str, Any]:
        try:
            return svc.sync(shop)
        except ShopifyError as exc:
            log.error("sync: %s", exc)
            raise HTTPException(
                503,
                {
                    "message": "Shopify didn't answer just now. Try again in a minute.",
                    "code": "shopify_unavailable",
                },
            ) from exc

    # ------------------------------------------------------------------ one shipment

    @router.get("/api/shipments/{sid}")
    def get_shipment(sid: str, who: str = Depends(staff)) -> dict[str, Any]:
        return detail_of(sid)

    @router.post("/api/shipments/{sid}/refresh")
    def refresh(sid: str, who: str = Depends(staff)) -> dict[str, Any]:
        shipment(sid)
        try:
            act(lambda: svc.prepare(shop, sid))
        except (ShopifyError, ProviderError) as exc:
            raise HTTPException(
                503,
                {
                    "message": f"Couldn't refresh just now ({exc}). Try again in a minute.",
                    "code": "unavailable",
                },
            ) from exc
        return detail_of(sid)

    @router.post("/api/shipments/{sid}/answer")
    def answer(sid: str, body: AnswerBody, who: str = Depends(staff)) -> dict[str, Any]:
        act(lambda: svc.answer(shop, sid, body.kind, body.subject, body.value, who))
        return detail_of(sid)

    @router.post("/api/shipments/{sid}/package")
    def package(sid: str, body: PackageBody, who: str = Depends(staff)) -> dict[str, Any]:
        act(lambda: svc.choose_package(shop, sid, body.preset_id, who))
        return detail_of(sid)

    @router.post("/api/shipments/{sid}/service")
    def service(sid: str, body: ServiceBody, who: str = Depends(staff)) -> dict[str, Any]:
        act(lambda: svc.choose_service(shop, sid, body.service_code, who))
        return detail_of(sid)

    @router.post("/api/shipments/{sid}/preview")
    def preview(sid: str, who: str = Depends(staff)) -> dict[str, Any]:
        out = act(lambda: svc.preview(shop, sid))
        price = out["money"]
        return {
            "basis": out["basis"],
            "will": out["will"],
            "price": str(Money(minor=price["shipping_minor"], currency=price["currency"])),
            "service": out["service"],
            "shipment": detail_of(sid),
        }

    @router.post("/api/shipments/{sid}/buy")
    def buy(sid: str, body: BuyBody, who: str = Depends(staff)) -> dict[str, Any]:
        out = act(lambda: svc.buy(shop, sid, body.basis, who, body.idempotency_key))
        return {
            "charged": out["charged"],
            "may_have_been_charged": out["may_have_been_charged"],
            "replayed": out["replayed"],
            "status": out["status"],
            "error": out["error"],
            "shipment": detail_of(sid),
        }

    @router.post("/api/shipments/{sid}/retry-shopify")
    def retry_shopify(sid: str, who: str = Depends(staff)) -> dict[str, Any]:
        """Retry the Shopify side only. Never reaches the provider."""
        act(lambda: svc.fulfil(shop, sid, who))
        return detail_of(sid)

    # ------------------------------------------------------------------ printing (read-only)

    @router.post("/api/shipments/{sid}/print")
    def print_one(sid: str, who: str = Depends(staff)) -> dict[str, Any]:
        jobs = act(lambda: printing.print_shipment(shop, sid, who))
        return {"jobs": [j.as_dict() for j in jobs], "shipment": detail_of(sid)}

    @router.post("/api/print/order/{ref}")
    def print_order(ref: str, who: str = Depends(staff)) -> dict[str, Any]:
        """ "Reprint order 2145"."""
        found = act(lambda: printing.find_order(shop, ref))
        jobs = act(lambda: printing.print_shipment(shop, found.id, who))
        return {"jobs": [j.as_dict() for j in jobs], "order": found.order_name}

    @router.post("/api/print/ready")
    def print_ready(who: str = Depends(staff)) -> dict[str, Any]:
        """ "Print all ready labels": every bought label not printed yet."""
        jobs = act(lambda: printing.print_ready(shop, who))
        return {
            "jobs": [j.as_dict() for j in jobs],
            "labels": len({j.shipment_id for j in jobs}),
        }

    @router.get("/api/documents/{artifact_id}")
    def document(artifact_id: str, who: str = Depends(staff)) -> Response:
        if not re.fullmatch(r"art_[A-Za-z0-9]{6,40}", artifact_id):
            raise HTTPException(404, {"message": "Document not found.", "code": "not_found"})
        content_type, body = act(lambda: printing.document(shop, artifact_id))
        return Response(
            body,
            media_type=content_type,
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    # ------------------------------------------------------------------ setup

    def setup_view() -> dict[str, Any]:
        cfg = svc.store.config(shop)
        return {
            "origin": cfg.origin.model_dump() if cfg.origin else None,
            "presets": presets(),
            "default_package_id": cfg.default_package_id,
            "label_format": "4x6",
            "printer": {"label": "Browser print (PrintNode later)", "document": "Browser print"},
            "customs": {
                "duties": cfg.duties.mode,
                "ioss_number": cfg.duties.ioss_number,
                "eori_number": cfg.eori_number,
                "vat_number": cfg.vat_number,
                "notify_customer": cfg.notify_customer,
                "explain": "Delivered at place (DAP): the customer may pay import charges on "
                "delivery. Nothing is prepaid unless you add an IOSS number for EU parcels.",
            },
            "connection": connection(),
        }

    @router.get("/api/setup")
    def get_setup(who: str = Depends(staff)) -> dict[str, Any]:
        return setup_view()

    @router.post("/api/setup")
    def save_setup(body: SetupBody, who: str = Depends(staff)) -> dict[str, Any]:
        cfg = svc.store.config(shop)
        if body.origin is not None:
            o = body.origin
            missing = [
                n
                for n, v in (
                    ("name", o.name),
                    ("street", o.line1),
                    ("town", o.city),
                    ("postcode", o.postcode),
                )
                if not v.strip()
            ]
            if missing or not re.fullmatch(r"[A-Z]{2}", o.country):
                raise HTTPException(
                    422,
                    {
                        "message": "The ship-from address needs a name, street, town, postcode "
                        "and country.",
                        "code": "invalid",
                    },
                )
            cfg.origin = o
        if body.default_package_id is not None:
            if not any(p.id == body.default_package_id for p in cfg.packages):
                raise HTTPException(
                    422, {"message": "That package doesn't exist.", "code": "invalid"}
                )
            cfg.default_package_id = body.default_package_id
        for field in ("eori_number", "vat_number"):
            value = getattr(body, field)
            if value is not None:
                setattr(cfg, field, value.strip().upper() or None)
        if body.ioss_number is not None:
            ioss = body.ioss_number.strip().upper()
            if ioss and not re.fullmatch(r"IM\d{10}", ioss):
                raise HTTPException(
                    422, {"message": "An IOSS number looks like IM1234567890.", "code": "invalid"}
                )
            cfg.duties.ioss_number = ioss or None
        if body.notify_customer is not None:
            cfg.notify_customer = body.notify_customer
        svc.store.save_config(cfg)
        return setup_view()

    @router.post("/api/setup/packages")
    def add_preset(body: PresetBody, who: str = Depends(staff)) -> dict[str, Any]:
        from shipping import packages

        cfg = svc.store.config(shop)
        try:
            p = packages.add(
                cfg,
                name=body.name,
                length_cm=body.length_cm,
                width_cm=body.width_cm,
                height_cm=body.height_cm,
                empty_weight_g=body.empty_weight_g,
                actor=who,
            )
        except ValueError as exc:
            raise HTTPException(422, {"message": str(exc), "code": "invalid"}) from exc
        if body.make_default:
            cfg.default_package_id = p.id
        svc.store.save_config(cfg)
        # Orders waiting only for a package can go ahead now.
        for s in svc.store.shipments(shop, [ShipmentStatus.needs_attention.value]):
            if any(q.kind == "package" for q in s.questions):
                try:
                    svc.prepare(shop, s.id)
                except (Conflict, ShopifyError, ProviderError):
                    continue  # the next sync picks it up
        return setup_view()

    return router
