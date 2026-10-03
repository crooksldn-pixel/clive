"""The application. `uvicorn returns.app:app --port 8100`."""

from __future__ import annotations

from fastapi import FastAPI

from returns.api import build_routers
from returns.labels import ClickAndDrop
from returns.service import ReturnsService
from returns.settings import Settings, get_settings
from returns.shopify import GraphQLShopify
from returns.store import Store


def create_app(settings: Settings | None = None, service: ReturnsService | None = None) -> FastAPI:
    settings = settings or get_settings()
    if service is None:
        if settings.shopify_backend == "fake":
            from returns.fake import FakeLabels, FakeShopify

            shopify, labels = FakeShopify(), FakeLabels()
        else:
            shopify, labels = GraphQLShopify(settings), ClickAndDrop(settings)
        service = ReturnsService(settings, Store(settings.db_path), shopify, labels)
    app = FastAPI(
        title="CROOKS Returns",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    for router in build_routers(service):
        app.include_router(router)
    app.state.service = service
    return app


def __getattr__(name: str):
    # `returns.app:app` builds on first use, so importing this module never reads .env.
    if name == "app":
        return create_app()
    raise AttributeError(name)
