"""The application. `uvicorn returns.app:app --port 8100`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from returns.admin import build_admin_router
from returns.api import build_routers
from returns.labels import ClickAndDrop, NoLabels
from returns.service import ReturnsService
from returns.settings import Settings, get_settings
from returns.shopify import GraphQLShopify, ShopifyError
from returns.store import Store


class UTF8JSONResponse(JSONResponse):
    # Say UTF-8 outright, so a browser opening /health shows £ rather than Â£.
    media_type = "application/json; charset=utf-8"


def label_provider(settings: Settings):
    if settings.label_provider == "parcel2go":
        from returns.parcel2go import Parcel2Go

        return Parcel2Go(settings)
    if settings.label_provider == "none":
        return NoLabels()
    return ClickAndDrop(settings)


def build_service(settings: Settings) -> ReturnsService:
    if settings.shopify_backend == "fake":
        from returns.fake import FakeLabels, FakeShopify

        shopify = FakeShopify()
        # Fake store, real Parcel2Go sandbox: lets the whole flow run without Shopify.
        labels = (
            label_provider(settings) if settings.label_provider == "parcel2go" else FakeLabels()
        )
    else:
        shopify, labels = GraphQLShopify(settings), label_provider(settings)
    return ReturnsService(settings, Store(settings.db_path), shopify, labels)


def create_app(settings: Settings | None = None, service: ReturnsService | None = None) -> FastAPI:
    settings = settings or get_settings()
    service = service or build_service(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Flag overdue labels on a timer, so no outside scheduler is needed.
        async def ticker() -> None:
            while True:
                await asyncio.sleep(settings.tick_interval_s)
                try:
                    await run_in_threadpool(service.tick)
                except Exception:  # noqa: BLE001 - one failed check must not stop the next
                    logging.getLogger("returns.tick").exception("overdue check failed")

        task = asyncio.create_task(ticker()) if settings.tick_interval_s > 0 else None
        # Each recorded event to CLIVE's door, on its own thread (off without
        # RETURNS_CLIVE_WEBHOOK_URL): returns/doorbell.py.
        service.doorbell.start()
        yield
        service.doorbell.stop()
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,
        title="CROOKS Returns",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.exception_handler(ShopifyError)
    async def shopify_down(request: Request, exc: ShopifyError) -> UTF8JSONResponse:
        # The customer gets a plain message; the reason goes to the log for staff.
        logging.getLogger("returns.shopify").error(
            "%s %s: %s", request.method, request.url.path, exc
        )
        return UTF8JSONResponse(
            {"detail": "Our store system didn't answer just now. Please try again in a minute."},
            status_code=503,
        )

    for router in build_routers(service):
        app.include_router(router)
    app.include_router(build_admin_router(service))
    app.state.service = service
    return app


def __getattr__(name: str):
    # `returns.app:app` builds on first use, so importing this module never reads .env.
    if name == "app":
        return create_app()
    raise AttributeError(name)
