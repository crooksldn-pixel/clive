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
import time
from collections.abc import Callable
from importlib import resources
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from shipping import lifecycle, views
from shipping.auth import BadToken, verify_session_token
from shipping.commodity import spaced
from shipping.models import Address
from shipping.money import Money
from shipping.operations import Operations
from shipping.physical_printing import PhysicalPrinting, intent_state
from shipping.print_provider import PrintNodeProvider
from shipping.printing import PrintError, Printing
from shipping.providers.base import ProviderError
from shipping.purchase import ActionError, Stale
from shipping.service import ShippingService
from shipping.settings import Settings
from shipping.shopify import ShopifyError
from shipping.store import Conflict

log = logging.getLogger("shipping.admin")

# What a stored document may be served as; anything else downloads as bytes.
DOCUMENT_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})


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
    value: dict[str, Any] = Field(default_factory=dict, max_length=8)


class SuggestBody(BaseModel):
    text: str = Field(default="", max_length=200)
    sid: str | None = Field(default=None, max_length=80)
    subject: str | None = Field(default=None, max_length=200)
    answers: dict[str, str] = Field(default_factory=dict, max_length=8)


class PackageBody(BaseModel):
    preset_id: str = Field(max_length=60)


class ServiceBody(BaseModel):
    service_code: str = Field(max_length=120)


class BuyBody(BaseModel):
    basis: str = Field(min_length=4, max_length=80)
    # Made once per click intent by the page; the same key replays, never re-buys.
    idempotency_key: str = Field(min_length=8, max_length=120)


class PrintBody(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)


class PrintViewBody(BaseModel):
    shipment_ids: list[str] = Field(min_length=1, max_length=100)


class BatchBody(BaseModel):
    kind: str
    shipment_ids: list[str] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=120)


class CustomsBody(BaseModel):
    subject: str = Field(max_length=200)
    hs_code: str = Field(max_length=10)
    description: str = Field(max_length=100)
    origin: str = Field(max_length=2)
    # How the code was found (a suggestion confirmed, or typed): kept beside it as evidence.
    classification: dict[str, Any] | None = None


class CancelBody(BaseModel):
    confirm: bool = False


class PresetBody(BaseModel):
    name: str = Field(max_length=60)
    length_cm: float
    width_cm: float
    height_cm: float
    empty_weight_g: int
    make_default: bool = False


class OriginBody(BaseModel):
    name: str = Field(default="", max_length=100)
    company: str = Field(default="", max_length=100)
    line1: str = Field(default="", max_length=120)
    line2: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=80)
    region: str = Field(default="", max_length=80)
    postcode: str = Field(default="", max_length=20)
    country: str = Field(default="", max_length=2)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=120)


class SetupBody(BaseModel):
    origin: OriginBody | None = None
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
    operations_ready: Callable[[Operations], None] | None = None,
) -> APIRouter:
    shop = settings.shop_domain
    printing = Printing(svc.store, clock=svc.clock)
    key = settings.printnode_api_key.get_secret_value()
    provider = (
        PrintNodeProvider(key, settings.printnode_printer_id)
        if settings.printnode_enabled and key
        else None
    )
    physical = PhysicalPrinting(svc.store, provider, settings.printnode_printer_id)
    physical_enabled = provider is not None

    names: dict[str, str] = {}  # Shopify user id -> name, from the token exchange
    # A failed lookup isn't repeated for ten minutes: it sits in front of every admin call.
    missed: dict[str, float] = {}

    def who_is(token: str, sub: str) -> str:
        if sub and sub not in names and time.monotonic() - missed.get(sub, -1e9) > 600:
            found = svc.shopify.staff_member(token)
            if found:
                names[sub] = found
            else:
                missed[sub] = time.monotonic()
        return names.get(sub) or f"Staff {sub}".strip()

    zone: dict[str, Any] = {"tz": None, "tried": -1e9}

    def store_timezone() -> str:
        """The store's time zone for order times; London until Shopify says (asked again after
        ten minutes if it couldn't be read)."""
        if zone["tz"] is None and time.monotonic() - zone["tried"] > 600:
            zone["tried"] = time.monotonic()
            try:
                zone["tz"] = svc.shopify.shop_timezone()
            except ShopifyError:
                log.warning("store time zone not read; showing London time")
        return zone["tz"] or "Europe/London"

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
        return who_is(token, str(claims.get("sub", "")))

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

    operations = Operations(svc, physical)
    if operations_ready:
        operations_ready(operations)

    def detail_of(sid: str) -> dict[str, Any]:
        s = shipment(sid)
        result = views.detail(
            s,
            svc.recommendation(s),
            presets(),
            may_buy=svc.may_buy(s),
            may_cancel=svc.can_cancel(s),
            origin=svc.store.config(s.shop).origin,
        )
        result["print_status"] = physical.summary(shop, sid)
        result["print_method"] = "printnode" if physical_enabled else "print_view"
        result["print_connection"] = physical.connection() if s.label else None
        result["stage"] = lifecycle.stage(s, result["print_status"])
        result["stage_title"] = lifecycle.TITLES[result["stage"]]
        result["payment"] = views.payment_view(s)
        result["fulfilment"] = views.fulfilment_view(s)
        result["carrier"] = views.carrier_view(s)
        result["journey"] = views.journey_view(s, result["print_status"]) if s.label else None
        # History written before a name was known ("Staff 1268…") shows the name once known.
        for e in result["timeline"]:
            sub = e["who"][6:] if e["who"].startswith("Staff ") else ""
            e["who"] = names.get(sub, e["who"])
        return result

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
    def inbox(q: str = "", stage: str = "attention", who: str = Depends(staff)) -> dict[str, Any]:
        """One lifecycle stage's orders (search applies within it), and how many each holds."""
        if stage not in (*lifecycle.STAGES, "all"):
            stage = "attention"
        counts = dict.fromkeys(lifecycle.STAGES, 0)
        rows: list[dict[str, Any]] = []
        for s in sorted(svc.store.shipments(shop), key=views.placed_at, reverse=True):
            if not svc.visible(s) or not views.matches(s, q):
                continue
            printed = physical.summary(shop, s.id)
            where = lifecycle.stage(s, printed)
            if where in counts:
                counts[where] += 1
            if stage not in (where, "all"):
                continue
            r = views.row(s)
            r["stage"] = where
            r["print_status"] = printed
            r["can_buy"] = lifecycle.may_bulk_buy(where) and svc.may_buy(s)
            r["can_first_print"] = lifecycle.may_bulk_first_print(where, printed)
            r["can_select"] = r["can_buy"] or r["can_first_print"]
            rows.append(r)
        if not q and stage in ("delivered", "all"):
            rows = rows[:100]  # the newest; search finds older ones
        cfg = svc.store.config(shop)
        return {
            "me": who,
            "stage": stage,
            "rows": rows,
            "counts": counts,
            "printing": physical_enabled,
            "print_method": "printnode" if physical_enabled else "print_view",
            "timezone": store_timezone(),
            "ready_to_print": len(printing.ready(shop)),
            "batches": [
                {
                    "id": b["id"],
                    "kind": b["kind"],
                    "state": b["state"],
                    "created_at": b["created_at"],
                }
                for b in svc.store.batches(shop)[:10]
            ],
            "setup": {
                "origin": cfg.origin is not None,
                "package": bool(cfg.packages),
            },
        }

    @router.post("/api/batches/preview")
    def batch_preview(body: BatchBody, who: str = Depends(staff)):
        return act(
            lambda: operations.preview(
                shop, body.kind, body.shipment_ids, who, body.idempotency_key
            )
        )

    @router.get("/api/batches/{bid}")
    def batch_get(bid: str, who: str = Depends(staff)):
        return act(lambda: operations.get(shop, bid))

    @router.post("/api/batches/{bid}/confirm")
    def batch_confirm(
        bid: str, body: CancelBody, tasks: BackgroundTasks, who: str = Depends(staff)
    ):
        if not body.confirm:
            raise HTTPException(422, "Review and confirm this batch first.")
        result = act(lambda: operations.confirm(shop, bid, who))
        tasks.add_task(operations.run, shop, bid)
        return result

    @router.post("/api/shipments/{sid}/customs")
    def customs_edit(sid: str, body: CustomsBody, who: str = Depends(staff)):
        act(
            lambda: svc.edit_customs(
                shop,
                sid,
                body.subject,
                body.hs_code,
                body.description,
                body.origin,
                who,
                classification=body.classification,
            )
        )
        return detail_of(sid)

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

    @router.post("/api/shipments/{sid}/tracking")
    def check_tracking(sid: str, who: str = Depends(staff)) -> dict[str, Any]:
        """Read the carrier's view from Shopify now. Only reads: never buys or prints."""
        shipment(sid)
        try:
            act(lambda: svc.refresh_tracking(shop, sid))
        except ShopifyError as exc:
            log.warning("tracking read for %s failed: %s", sid, exc)
            raise HTTPException(
                503,
                {"message": "Shopify didn't answer just now; try again in a minute.",
                 "code": "unavailable"},
            ) from exc  # fmt: skip
        return detail_of(sid)

    @router.post("/api/shipments/{sid}/refresh")
    def refresh(sid: str, who: str = Depends(staff)) -> dict[str, Any]:
        shipment(sid)
        try:
            act(lambda: svc.prepare(shop, sid))
        except (ShopifyError, ProviderError) as exc:
            log.warning("refresh of %s failed: %s", sid, exc)
            raise HTTPException(
                503,
                {
                    "message": "Shopify or Parcel2Go didn't answer just now. Nothing changed; "
                    "try again in a minute.",
                    "code": "unavailable",
                },
            ) from exc
        return detail_of(sid)

    @router.post("/api/commodity/suggest")
    def commodity_suggest(body: SuggestBody, who: str = Depends(staff)) -> dict[str, Any]:
        """Plain words (and what Shopify already says about the product) to a commodity code
        the UK Trade Tariff confirms, or the one question that decides it. Saves nothing."""
        if svc.commodity is None:
            return {"state": "manual", "message": "Finding codes is switched off here."}
        known: list[str] = []
        if body.sid and body.subject:
            s = svc.store.get(shop, body.sid)
            line = next(
                (
                    ln
                    for ln in (s.lines if s else [])
                    if (ln.product_id or ln.title) == body.subject
                ),
                None,
            )
            if line is not None:
                known = [
                    line.title,
                    line.variant_title,
                    line.product_type,
                    line.customs_description,
                ]
        context = " ".join(x for x in known if x)[:400]
        out = svc.commodity.suggest(body.text[:400], body.answers, context)
        result: dict[str, Any] = {"state": out.state, "message": out.message}
        if out.question is not None:
            result["question"] = {
                "fact": out.question.fact,
                "text": out.question.text,
                "options": out.question.options,
            }
        if out.entry is not None:
            result["candidate"] = {
                "code": out.entry.code,
                "spaced": spaced(out.entry.code),
                "description": out.entry.description,
                "path": out.entry.path,
                "source": out.entry.source,
                "checked_at": out.entry.checked_at,
                "reasons": out.reasons,
                "inputs": out.inputs,
            }
        return result

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
            "charged": out.get("charged", ""),
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

    @router.post("/api/shipments/{sid}/cancel-label")
    def cancel_label(sid: str, body: CancelBody, who: str = Depends(staff)) -> dict[str, Any]:
        """Cancel a bought label at a provider that supports it. Needs the merchant's explicit
        confirmation (the page asks; the body must say so)."""
        if not body.confirm:
            raise HTTPException(
                422, {"message": "Confirm the cancellation first.", "code": "confirm"}
            )
        act(lambda: svc.cancel_label(shop, sid, who))
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
        jobs, skipped = act(lambda: printing.print_ready(shop, who))
        return {
            "jobs": [j.as_dict() for j in jobs],
            "labels": len({j.shipment_id for j in jobs}),
            "skipped": skipped,
        }

    @router.get("/api/documents/{artifact_id}")
    def document(artifact_id: str, who: str = Depends(staff)) -> Response:
        if not re.fullmatch(r"art_[A-Za-z0-9]{6,40}", artifact_id):
            raise HTTPException(404, {"message": "Document not found.", "code": "not_found"})
        content_type, body = act(lambda: printing.document(shop, artifact_id))
        if content_type not in DOCUMENT_TYPES:
            content_type = "application/octet-stream"  # never rendered in the app's origin
        return Response(
            body,
            media_type=content_type,
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox",
            },
        )

    def pdf(body: bytes, note: str = "", **headers: str) -> Response:
        return Response(
            body,
            media_type="application/pdf",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Print-Note": quote(note),  # headers are latin-1: words go URL-encoded
                **headers,
            },
        )

    @router.post("/api/shipments/{sid}/print-view")
    def print_view(sid: str, who: str = Depends(staff)) -> Response:
        """Print without PrintNode: the label as a 4x6 PDF for the browser's print dialog."""
        body, note = act(lambda: physical.print_view(shop, sid, who))
        return pdf(body, note)

    @router.post("/api/print-view")
    def print_view_many(body: PrintViewBody, who: str = Depends(staff)) -> Response:
        """Several labels as one PDF, as Shopify prints labels in bulk."""
        out, done, skipped = act(lambda: physical.print_view_many(shop, body.shipment_ids, who))
        left = "; ".join(f"{x['order']}: {x['reason']}" for x in skipped)
        return pdf(out, f"Left out: {left}" if left else "", **{"X-Print-Count": str(len(done))})

    @router.get("/api/print/connection")
    def print_connection(who: str = Depends(staff)) -> dict[str, Any]:
        return physical.connection()

    def sent_result(intent):
        outcome = intent_state(intent)
        message = {
            "printed": "Printed",
            "printing": f"Printing on {intent.get('printer_name') or 'the printer'}…",
            "sending": "Sending to the printer…",
        }.get(outcome) or (
            intent.get("error") or "Print request recorded; check its status before reprinting"
        )
        return {"print_intent": intent, "outcome": outcome, "message": message}

    @router.post("/api/shipments/{sid}/print-label")
    def physical_label(sid: str, body: PrintBody, who: str = Depends(staff)):
        return sent_result(act(lambda: physical.print_label(shop, sid, who, body.idempotency_key)))

    @router.post("/api/shipments/{sid}/reprint-label")
    def physical_reprint(sid: str, body: PrintBody, who: str = Depends(staff)):
        return sent_result(
            act(lambda: physical.print_label(shop, sid, who, body.idempotency_key, reprint=True))
        )

    @router.post("/api/print/order/{ref}/label")
    def physical_order(ref: str, body: PrintBody, who: str = Depends(staff)):
        s = act(lambda: printing.find_order(shop, ref))
        return sent_result(act(lambda: physical.print_label(shop, s.id, who, body.idempotency_key)))

    @router.get("/api/print/intents/{intent_id}")
    def physical_status(intent_id: str, who: str = Depends(staff)):
        return sent_result(act(lambda: physical.status(shop, intent_id)))

    @router.get("/api/print/health")
    def physical_health(who: str = Depends(staff)):
        return physical.health()

    @router.post("/api/print/test")
    def physical_test(body: PrintBody, who: str = Depends(staff)):
        return sent_result(act(lambda: physical.test_print(shop, who, body.idempotency_key)))

    # ------------------------------------------------------------------ setup

    def setup_view() -> dict[str, Any]:
        cfg = svc.store.config(shop)
        return {
            "origin": cfg.origin.model_dump() if cfg.origin else None,
            "presets": presets(),
            "default_package_id": cfg.default_package_id,
            "label_format": "4x6",
            "label_printer": physical.health(),
            "print_connection": physical.connection(),
            "printer": {
                "label": "Open PDF remains available for manual 4×6 printing",
                "document": "Customs copies open in your browser to print on A4",
                "direct": "Direct labels use the server-side PrintNode connection",
            },
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
            cfg.origin = Address(**o.model_dump())
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
        svc.reprepare_waiting(shop, lambda q: q.kind == "package")
        return setup_view()

    return router
