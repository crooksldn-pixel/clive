"""Configuration, from SHIPPING_* environment variables (or .env). Live secrets are set on the
server only, never in the repo."""

from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str | None:
    # SHIPPING_ENV_FILE set to nothing reads no file: the tests and dev server run that way.
    return os.environ.get("SHIPPING_ENV_FILE", ".env") or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHIPPING_", env_file=_env_file(), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Shopify ---
    shop_domain: str = "5wn03t-nm.myshopify.com"
    # The app's client id and secret: the secret also signs admin session tokens.
    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    # "fake" serves the built-in fixture store, for local work and the tests.
    shopify_backend: str = "graphql"

    # --- Parcel2Go ---
    # "parcel2go" or "fake" (fixture prices, test labels, nothing booked).
    provider: str = "parcel2go"
    # https://sandbox.parcel2go.com for testing; credentials are separate per environment.
    p2g_base_url: str = "https://sandbox.parcel2go.com"
    p2g_client_id: str = ""
    p2g_client_secret: str = ""

    # --- the service ---
    db_path: str = "shipping.sqlite3"
    # How often the service reconciles purchases, retries Shopify and refreshes open orders,
    # in seconds. 0 turns the timer off.
    tick_interval_s: int = 60
    # Local development only: open the admin screen without a Shopify admin session.
    dev_skip_admin_auth: bool = False

    @property
    def p2g_environment(self) -> str:
        if self.provider != "parcel2go":
            return "test"
        host = urlparse(self.p2g_base_url).hostname
        return "sandbox" if host == "sandbox.parcel2go.com" else "live"


@lru_cache
def get_settings() -> Settings:
    return Settings()
