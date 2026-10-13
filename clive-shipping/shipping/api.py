"""CLIVE's way into Shipping: /api/v1, the same contract shape CROOKS Returns already serves.

    GET  /api/v1/capabilities                         read   what CLIVE can do here
    GET  /api/v1/shipments?stage=&q=&limit=           read   orders in a lifecycle stage
    GET  /api/v1/shipments/{id}                       read   one order: payment, print, carrier
    POST /api/v1/shipments/{id}/preview               read   the exact price now; buys nothing
    POST /api/v1/shipments/{id}/buy                   write  buy the previewed label, once
    POST /api/v1/shipments/{id}/print                 write  first print (PrintNode), once
    POST /api/v1/shipments/{id}/reprint               write  an extra copy, explicitly confirmed
    POST /api/v1/shipments/{id}/tracking              read   read Shopify's carrier tracking now
    GET  /api/v1/events?since=&limit=                 read   what changed, newest last

Every action calls the same service method as the Shipping screen: buying goes through the
same authorisation, Shopify re-read (payment, address, items), price check, idempotency and
reconciliation; printing through the same print intents. Nothing here can buy postage except
`buy`, and `buy` needs the basis a preview returned plus an idempotency key. Keys: bearer,
read or write (SHIPPING_CLIVE_READ_KEYS / SHIPPING_CLIVE_WRITE_KEYS); none set, nothing answers.
Failures are {"detail": {"message", "code"}} with an HTTP status, as everywhere in Shipping.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from shipping import domestic, lifecycle, views
from shipping.models import Shipment
from shipping.printing import PrintError
from shipping.purchase import ActionError
from shipping.service import ShippingService
from shipping.settings import Settings
from shipping.store import Conflict

CAPABILITIES = [
    ("GET", "/api/v1/shipments", "read", "List orders in a stage: attention, ready, bought, "
     "printed, in_transit, delivered, all. Optional q (order number, name, city)."),
    ("GET", "/api/v1/shipments/{id}", "read", "One order: stage, payment, blockers, service, "
     "label, print state and carrier tracking."),
    ("POST", "/api/v1/shipments/{id}/preview", "read", "Re-read the order in Shopify and get "
     "the exact price now (UK labels: no price, money.price_known false). Buys nothing. "
     "Returns the basis that buy needs."),
    ("POST", "/api/v1/shipments/{id}/buy", "write", "Buy the label previewed: {basis, "
     "idempotency_key, actor}. Refused if anything changed since the preview."),
    ("POST", "/api/v1/shipments/{id}/print", "write", "Send the label to the printer the "
     "first time: {idempotency_key, actor}. Never buys."),
    ("POST", "/api/v1/shipments/{id}/reprint", "write", "Print an extra copy: {confirm: true, "
     "idempotency_key, actor}. Never buys."),
    ("POST", "/api/v1/shipments/{id}/tracking", "read", "Read the carrier's view from Shopify "
     "now. Never buys or prints."),
    ("GET", "/api/v1/events", "read", "What changed since a time: each event names the "
     "order, what happened, who did it and whether it was checked."),
]  # fmt: skip


class Actor(BaseModel):
    # Who CLIVE acts for, recorded on the order's history with "(CLIVE)".
    actor: str = Field(default="CLIVE", max_length=80)


class BuyBody(Actor):
    basis: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=120)


class PrintBody(Actor):
    idempotency_key: str = Field(min_length=8, max_length=120)


class ReprintBody(PrintBody):
    confirm: bool = False


def fail(status: int, code: str, message: str) -> HTTPException:
    # The same shape as every other Shipping error: {"detail": {"message", "code"}}.
    return HTTPException(status, {"message": message, "code": code})


def page(found: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """The oldest events first, at most `limit`. With has_more, ask again with since= the last
    `at`: a page never ends part-way through one moment, so nothing is skipped."""
    found.sort(key=lambda x: x["at"])
    n = max(1, min(limit, 1000))
    if len(found) <= n:
        return {"events": found, "has_more": False}
    cut = found[n]["at"]
    head = [e for e in found[:n] if e["at"] != cut]
    if not head:  # one moment fills the page: give all of that moment, never part of it
        head = [e for e in found if e["at"] == cut]
    return {"events": head, "has_more": len(found) > len(head)}


def source_of(e: Any) -> str:
    """Where a change came from, as Returns says it: api (CLIVE), system (the timer, PrintNode,
    the carrier) or ui (staff on the Shipping screen)."""
    if e.actor.endswith("(CLIVE)"):
        return "api"
    if e.actor in ("system", "PrintNode") or e.type.startswith("carrier_"):
        return "system"
    return "ui"


def summary(s: Shipment, printed: dict[str, Any] | None) -> dict[str, Any]:
    st = views.status_of(s)
    q = s.quote
    return {
        "id": s.id,
        "order": s.order_name,
        "order_id": s.order_id,
        "country": s.destination.country,
        "stage": lifecycle.stage(s, printed),
        "status": st["label"],
        "reasons": st["reasons"],
        "payment": views.payment_view(s)["label"],
        "service": f"{q.provider} · {q.title}" if q else None,
        "provider": (s.label.provider if s.label else q.provider if q else None),
        "domestic": s.domestic,
        # None with price_known false: the provider sets it when buying (Shopify Shipping).
        "price": str(q.amount) if q and q.price_known else None,
        "price_known": q.price_known if q else None,
        "tracking_number": s.label.tracking_number if s.label else None,
        "print": printed["label"] if printed else None,
        "carrier": (views.carrier_view(s) or {}).get("label"),
        "updated_at": s.updated_at.isoformat(),
    }


def build_api_router(
    svc: ShippingService, settings: Settings, physical: Callable[[Request], Any]
) -> APIRouter:
    """`physical` gives the app's one PhysicalPrinting (built with the admin)."""
    shop = settings.shop_domain

    def bearer(authorization: str | None) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise fail(401, "unauthenticated", "A bearer key is required.")
        return authorization[7:].strip()

    def can(kind: str, key: str) -> bool:
        given = key.encode()  # bytes: any key compares, none raises
        return any(hmac.compare_digest(given, k.encode()) for k in settings.keys(kind))

    def reader(authorization: str | None = Header(default=None)) -> None:
        if not can("read", bearer(authorization)):
            raise fail(403, "forbidden", "This key cannot read shipping.")

    def writer(authorization: str | None = Header(default=None)) -> None:
        if not can("write", bearer(authorization)):
            raise fail(403, "forbidden", "This key cannot act on shipping.")

    def get(sid: str) -> Shipment:
        s = svc.store.get(shop, sid)
        if s is None:
            raise fail(404, "not_found", "No such shipment.")
        return s

    def run(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except ActionError as exc:
            raise fail(exc.status, exc.code or "refused", str(exc)) from exc
        except PrintError as exc:
            raise fail(409, "print_refused", str(exc)) from exc
        except Conflict as exc:
            raise fail(409, "busy", "This order was updated meanwhile. Read it again.") from exc

    def detail(request: Request, s: Shipment) -> dict[str, Any]:
        printed = physical(request).summary(shop, s.id)
        out = summary(s, printed)
        out.update(
            payment=views.payment_view(s),
            fulfilment=views.fulfilment_view(s),
            print_status=printed,
            carrier=views.carrier_view(s),
            questions=[{"kind": q.kind, "text": q.text} for q in s.questions],
            label=None
            if s.label is None
            else {
                "provider": s.label.provider,
                "service": s.label.service_name,
                "price": str(s.label.amount) if s.label.price_known else None,
                "price_known": s.label.price_known,
                # Bought, but its file can't be fetched here: what to do instead.
                "file_note": s.label.file_note or None,
                "tracking_number": s.label.tracking_number,
                "tracking_url": s.label.tracking_url,
                "purchased_at": s.label.purchased_at.isoformat(),
            },
            domestic=views.domestic_view(s),
            alerts=list(s.alerts),
            can_buy=lifecycle.may_bulk_buy(out["stage"]) and svc.may_buy(s),
            last_error=s.last_error,
        )
        return out

    api = APIRouter(prefix="/api/v1")

    @api.get("/capabilities", dependencies=[Depends(reader)])
    def capabilities() -> dict[str, Any]:
        uk = svc.domestic
        return {
            "service": "CLIVE Shipping",
            "stages": list(lifecycle.STAGES),
            "operations": [
                {"method": m, "path": p, "key": k, "does": d} for m, p, k, d in CAPABILITIES
            ],
            "providers": [
                {
                    "name": getattr(p, "name", "Provider"),
                    "orders": "international",
                    "price_before_buying": True,
                }
                for p in getattr(svc.provider, "quoting", None) or [svc.provider]
            ]
            + (
                [
                    {
                        "name": "Shopify Shipping",
                        "orders": "uk",
                        "services": [
                            {
                                "service": domestic.title(k),
                                "code": k,
                                "buyable": v is not None,
                            }
                            for k, v in uk.rates.items()
                        ],
                        # Shopify has no rates query and the purchase isn't idempotent: the
                        # price is on the Shopify bill, and CLIVE sends each purchase once.
                        "price_before_buying": False,
                        "idempotent_at_provider": False,
                    }
                ]
                if uk.enabled
                else []
            ),
            "uk_orders": {
                "enabled": uk.enabled,
                "service_by_checkout_line": {
                    title: domestic.title(service) for title, service in uk.lines.items()
                },
                "unmapped": "attention: a person picks Tracked 24 or Tracked 48 in the admin",
            },
        }

    @api.get("/shipments", dependencies=[Depends(reader)])
    def shipments(
        request: Request, stage: str = "attention", q: str = "", limit: int = 100
    ) -> dict[str, Any]:
        if stage not in (*lifecycle.STAGES, "all"):
            raise fail(422, "invalid", f"stage is one of {', '.join((*lifecycle.STAGES, 'all'))}.")
        rows = []
        for s in sorted(svc.store.shipments(shop), key=views.placed_at, reverse=True):
            if not svc.visible(s) or not views.matches(s, q):
                continue
            r = summary(s, physical(request).summary(shop, s.id))
            if stage in (r["stage"], "all"):
                rows.append(r)
        return {"stage": stage, "shipments": rows[: max(1, min(limit, 500))]}

    @api.get("/shipments/{sid}", dependencies=[Depends(reader)])
    def one(request: Request, sid: str) -> dict[str, Any]:
        return detail(request, get(sid))

    @api.post("/shipments/{sid}/preview", dependencies=[Depends(reader)])
    def preview(sid: str) -> dict[str, Any]:
        get(sid)
        out = run(lambda: svc.preview(shop, sid))
        return {"shipment_id": sid, **out}

    @api.post("/shipments/{sid}/buy", dependencies=[Depends(writer)])
    def buy(request: Request, sid: str, body: BuyBody) -> dict[str, Any]:
        get(sid)
        who = f"{body.actor} (CLIVE)"
        out = run(lambda: svc.buy(shop, sid, body.basis, who, body.idempotency_key))
        out.pop("shipment", None)
        return {**out, "shipment": detail(request, get(sid))}

    def print_once(request: Request, sid: str, body: PrintBody, reprint: bool) -> dict[str, Any]:
        get(sid)
        printer = physical(request)
        if printer.provider is None:
            raise fail(409, "printing_disabled", "Label printing (PrintNode) is not switched on.")
        who = f"{body.actor} (CLIVE)"
        intent = run(
            lambda: printer.print_label(shop, sid, who, body.idempotency_key, reprint=reprint)
        )
        return {
            "print_intent": intent,
            # Accepted by PrintNode is not paper in the tray: never claimed as printed.
            "sent_to_printer": intent["state"] == "accepted" and bool(intent["provider_job_id"]),
            "shipment": detail(request, get(sid)),
        }

    @api.post("/shipments/{sid}/print", dependencies=[Depends(writer)])
    def print_label(request: Request, sid: str, body: PrintBody) -> dict[str, Any]:
        return print_once(request, sid, body, reprint=False)

    @api.post("/shipments/{sid}/reprint", dependencies=[Depends(writer)])
    def reprint(request: Request, sid: str, body: ReprintBody) -> dict[str, Any]:
        if not body.confirm:
            raise fail(422, "confirm_required", "A reprint is an extra copy: send confirm: true.")
        return print_once(request, sid, body, reprint=True)

    @api.post("/shipments/{sid}/tracking", dependencies=[Depends(reader)])
    def tracking(request: Request, sid: str) -> dict[str, Any]:
        get(sid)
        run(lambda: svc.refresh_tracking(shop, sid))
        return detail(request, get(sid))

    @api.get("/events", dependencies=[Depends(reader)])
    def events(since: datetime | None = None, limit: int = 200) -> dict[str, Any]:
        """Every order's history after `since`, oldest first: what changed, on which order,
        who did it, and whether it was checked against Shopify or the provider."""
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=UTC)  # a time without a zone is read as UTC
        found = []
        for s in svc.store.shipments(shop):
            if since is not None and s.updated_at <= since:
                continue
            for e in s.timeline:
                if since is None or e.at > since:
                    found.append(
                        {
                            "at": e.at.isoformat(),
                            "shipment_id": s.id,
                            "order": s.order_name,
                            "type": e.type,
                            "what": views.TIMELINE.get(e.type, e.type),
                            "actor": e.actor,
                            "source": source_of(e),
                            "verified": e.verified,
                            "detail": e.detail,
                        }
                    )
        return page(found, limit)

    return api
