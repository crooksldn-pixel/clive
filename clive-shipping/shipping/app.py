"""The application. `uvicorn shipping.app:app --port 8120`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from shipping.admin import build_admin_router
from shipping.providers.base import ProviderError, ShippingProvider
from shipping.purchase import Purchases
from shipping.service import ShippingService
from shipping.settings import Settings, get_settings
from shipping.shopify import ShopifyError
from shipping.store import Store

log = logging.getLogger("shipping.app")


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


def build_provider(settings: Settings, store: Store) -> ShippingProvider:
    """Every provider with credentials on the server. Two or more are asked together."""
    if settings.provider == "fake":
        from shipping.providers.fake import FakeProvider

        return FakeProvider()
    from shipping.providers.parcel2go import Parcel2Go

    found: list[ShippingProvider] = []
    if settings.p2g_client_id and settings.p2g_client_secret:
        found.append(
            Parcel2Go(
                settings.p2g_base_url,
                settings.p2g_client_id,
                settings.p2g_client_secret,
                config=store.config,
                cache=store,
            )
        )
    if settings.easyship_access_token.strip():
        from shipping.providers.easyship import Easyship

        found.append(Easyship(settings.easyship_access_token, config=store.config))
    if not found:  # nothing configured: Parcel2Go, so Setup says what's missing
        found.append(Parcel2Go(settings.p2g_base_url, "", "", config=store.config, cache=store))
    if len(found) == 1:
        return found[0]
    from shipping.providers.multi import Providers

    return Providers(found)


def build_service(settings: Settings) -> ShippingService:
    store = Store(settings.db_path)
    if settings.shopify_backend == "fake":
        from shipping.fake_shopify import FakeShopify

        shopify: Any = FakeShopify()
    else:
        from shipping.shopify import GraphQLShopify

        shopify = GraphQLShopify(
            settings.shop_domain, settings.shopify_client_id, settings.shopify_client_secret
        )
    provider = build_provider(settings, store)
    allowed = settings.authorised()
    return ShippingService(
        store,
        shopify,
        provider,
        Purchases(store, provider),
        may_buy=lambda s: settings.buying_enabled or _order_number(s.order_name) in allowed,
    )


def _order_number(name: str) -> str:
    found = re.findall(r"\d+", name or "")
    return found[-1] if found else ""


def connection_status(settings: Settings, svc: ShippingService) -> dict[str, Any]:
    """Each provider's connection, checked with a read that spends nothing (a balance)."""
    if settings.provider == "fake":
        one = {
            "provider": svc.provider.name,
            "environment": "test",
            "connected": True,
            "detail": "Test provider: nothing is booked.",
        }
        return {**one, "providers": [one]}
    providers = getattr(svc.provider, "providers", None) or [svc.provider]
    rows = [_check(settings, p) for p in providers]
    if not (settings.p2g_client_id and settings.p2g_client_secret):
        rows = [r for r in rows if r["provider"] != "Parcel2Go"] + [
            {
                "provider": "Parcel2Go",
                "environment": settings.p2g_environment,
                "connected": False,
                "detail": "No Parcel2Go credentials on the server.",
            }
        ]
    first = rows[0]
    return {**first, "connected": all(r["connected"] for r in rows), "providers": rows}


def _check(settings: Settings, p: Any) -> dict[str, Any]:
    from shipping.money import Money, to_minor
    from shipping.providers.easyship import Easyship
    from shipping.providers.parcel2go import Parcel2Go

    if isinstance(p, Easyship):
        out: dict[str, Any] = {"provider": p.name, "environment": settings.easyship_environment}
        try:
            acct = p.account()
            bal = acct.get("balance")
            cur = acct.get("currency")
            cur = cur if isinstance(cur, str) else "GBP"
            detail = (
                f"Credit balance {Money(minor=to_minor(bal), currency=cur)} (labels can also "
                "be paid by a payment method saved in Easyship)"
                if bal is not None
                else "Connected; no credit balance reported (labels may be charged to a card)."
            )
        except ProviderError as exc:
            log.warning("Easyship connection check failed: %s", exc)
            why = "the access token was refused" if exc.code == "auth" else "it didn't answer"
            return {**out, "connected": False, "detail": f"Easyship: {why}."}
        except (ArithmeticError, ValueError, TypeError):
            detail = "Connected; the balance couldn't be read."
        return {**out, "connected": True, "detail": detail}
    out = {"provider": getattr(p, "name", "Provider"), "environment": settings.p2g_environment}
    if not isinstance(p, Parcel2Go):
        return {**out, "connected": True, "detail": ""}
    try:
        raw = p._call("GET", "/prepay")
        found = Money(minor=to_minor(raw))
    except ProviderError as exc:
        log.warning("Parcel2Go connection check failed: %s", exc)
        why = (
            "the credentials were refused"
            if exc.code in ("auth", "unauthorized", "forbidden")
            or "401" in str(exc)
            or "403" in str(exc)
            else "it didn't answer"
        )
        return {**out, "connected": False, "detail": f"Parcel2Go: {why}."}
    except (ArithmeticError, ValueError, TypeError):
        return {**out, "connected": True, "detail": "Connected; the balance couldn't be read."}
    return {**out, "connected": True, "detail": f"PrePay balance {found}"}


def create_app(settings: Settings | None = None, service: ShippingService | None = None) -> FastAPI:
    settings = settings or get_settings()
    svc = service or build_service(settings)
    shop = settings.shop_domain

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Reconcile purchases, retry Shopify and refresh orders on a timer: correctness never
        # depends on someone having the page open.
        async def ticker() -> None:
            while True:
                await asyncio.sleep(settings.tick_interval_s)
                try:
                    await run_in_threadpool(svc.tick, shop)
                except Exception:  # noqa: BLE001 - one failed sweep must not stop the next
                    log.exception("tick failed")

        task = asyncio.create_task(ticker()) if settings.tick_interval_s > 0 else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,
        title="CLIVE Shipping",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(ShopifyError)
    async def shopify_down(request: Request, exc: ShopifyError) -> UTF8JSONResponse:
        log.error("%s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        return UTF8JSONResponse(
            {
                "detail": {
                    "message": "Shopify didn't answer just now. Try again in a minute; "
                    "anything already saved is kept.",
                    "code": "shopify_unavailable",
                }
            },
            status_code=503,
        )

    @app.exception_handler(ProviderError)
    async def provider_down(request: Request, exc: ProviderError) -> UTF8JSONResponse:
        log.error("%s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        return UTF8JSONResponse(
            {
                "detail": {
                    "message": f"{svc.provider.name} didn't answer just now. Try again in a "
                    "minute.",
                    "code": "provider_unavailable",
                }
            },
            status_code=503,
        )

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, Any]:
        return {"ok": True}

    app.include_router(build_admin_router(svc, settings, lambda: connection_status(settings, svc)))
    app.state.service = svc
    return app


def __getattr__(name: str):
    # `shipping.app:app` builds on first use, so importing this module never reads .env.
    if name == "app":
        return create_app()
    raise AttributeError(name)
