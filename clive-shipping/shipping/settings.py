"""Configuration, from SHIPPING_* environment variables (or .env). Live secrets are set on the
server only, never in the repo."""

from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str | None:
    # SHIPPING_ENV_FILE set to nothing reads no file: the tests and dev server run that way.
    return os.environ.get("SHIPPING_ENV_FILE", ".env") or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHIPPING_", env_file=_env_file(), env_file_encoding="utf-8", extra="ignore"
    )

    printnode_enabled: bool = Field(default=False, validation_alias="PRINTNODE_ENABLED")
    printnode_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="PRINTNODE_API_KEY", exclude=True
    )
    printnode_printer_id: int = Field(default=75883753, validation_alias="PRINTNODE_PRINTER_ID")

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

    # --- Easyship (public API 2024-09) ---
    # A production ("prod_...") or sandbox ("sand_...") access token; the token decides which
    # Easyship is used. Empty: Easyship isn't asked. Set on the server only.
    easyship_access_token: str = ""

    # --- the service ---
    db_path: str = "shipping.sqlite3"
    # How often the service reconciles purchases, retries Shopify and refreshes open orders,
    # in seconds. 0 turns the timer off.
    tick_interval_s: int = 60
    # Local development only: open the admin screen without a Shopify admin session.
    dev_skip_admin_auth: bool = False
    # With global buying disabled, orders a label may be bought for (comma-separated). Empty:
    # no buying; preparing, pricing and previewing still work. The owner adds one order
    # at a time on the server to authorise that label, then removes it.
    authorised_orders: str = ""
    # Global authorisation only; the existing guarded purchase flow still applies.
    buying_enabled: bool = False
    # CLIVE's keys for /api/v1 (comma-separated, set on the server only). A write key can
    # also read. Empty: the API answers nothing.
    clive_read_keys: str = ""
    clive_write_keys: str = ""

    def keys(self, kind: str) -> list[str]:
        """The keys allowed to read, or to act. Acting implies reading."""
        split = lambda v: [k.strip() for k in v.split(",") if k.strip()]  # noqa: E731
        write = split(self.clive_write_keys)
        return write if kind == "write" else split(self.clive_read_keys) + write

    def authorised(self) -> set[str]:
        parts = self.authorised_orders.replace(" ", ",").split(",")
        return {"".join(c for c in p if c.isdigit()) for p in parts} - {""}

    @property
    def easyship_environment(self) -> str:
        token = self.easyship_access_token.strip()
        return (
            "live" if token.startswith("prod_") else "sandbox" if token.startswith("sand_") else ""
        )

    @property
    def p2g_environment(self) -> str:
        if self.provider != "parcel2go":
            return "test"
        host = urlparse(self.p2g_base_url).hostname
        return "sandbox" if host == "sandbox.parcel2go.com" else "live"


@lru_cache
def get_settings() -> Settings:
    return Settings()
