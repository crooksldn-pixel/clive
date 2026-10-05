"""The application. `uvicorn shipping.app:app --port 8120`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
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
    if settings.provider == "fake":
        from shipping.providers.fake import FakeProvider

        return FakeProvider()
    from shipping.providers.parcel2go import Parcel2Go

    return Parcel2Go(
        settings.p2g_base_url,
        settings.p2g_client_id,
        settings.p2g_client_secret,
        config=store.config,
        cache=store,
    )


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
    return ShippingService(store, shopify, provider, Purchases(store, provider))


def connection_status(settings: Settings, svc: ShippingService) -> dict[str, Any]:
    """Is Parcel2Go reachable with these credentials? Reads the PrePay balance only."""
    env = settings.p2g_environment
    out: dict[str, Any] = {"provider": svc.provider.name, "environment": env}
    if settings.provider == "fake":
        return {**out, "connected": True, "detail": "Test provider: nothing is booked."}
    if not (settings.p2g_client_id and settings.p2g_client_secret):
        return {**out, "connected": False, "detail": "No Parcel2Go credentials on the server."}
    from shipping.providers.parcel2go import Parcel2Go, balance

    found = balance(svc.provider) if isinstance(svc.provider, Parcel2Go) else None
    if found is None:
        return {**out, "connected": False, "detail": "Parcel2Go didn't answer with a balance."}
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
        log.error("%s %s: %s", request.method, request.url.path, exc)
        return UTF8JSONResponse(
            {
                "detail": {
                    "message": "Shopify didn't answer just now. Nothing was bought; try "
                    "again in a minute.",
                    "code": "shopify_unavailable",
                }
            },
            status_code=503,
        )

    @app.exception_handler(ProviderError)
    async def provider_down(request: Request, exc: ProviderError) -> UTF8JSONResponse:
        log.error("%s %s: %s", request.method, request.url.path, exc)
        return UTF8JSONResponse(
            {
                "detail": {
                    "message": f"{svc.provider.name} didn't answer just now. Try again in "
                    "a minute.",
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
