"""Configuration, from PREORDERS_* environment variables (or .env). Live secrets are set on the
server only, never in the repo."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str | None:
    # PREORDERS_ENV_FILE set to nothing reads no file: the tests and dev server run that way.
    return os.environ.get("PREORDERS_ENV_FILE", ".env") or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PREORDERS_", env_file=_env_file(), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Shopify (the same CROOKS Operations app as Returns and Shipping) ---
    shop_domain: str = "5wn03t-nm.myshopify.com"
    shopify_client_id: str = ""
    shopify_client_secret: str = ""
    # "fake" serves the built-in fixture store, for local work and the tests.
    shopify_backend: str = "graphql"
    # Selling plans need the purchase-option scopes (docs/preorders/IMPLEMENTATION_PLAN.md §5).
    # "off": nothing is offered as a preorder on the storefront; everything else works.
    selling_plans: str = "off"  # off | shopify
    # The location stock is received into. Empty: the shop's first active location.
    location_id: str = ""

    # --- email (transactional only; never marketing) ---
    # "off": nothing is sent and every send is refused with a reason. "resend": Resend's API.
    email_provider: str = "off"  # off | resend
    resend_api_key: SecretStr = SecretStr("")
    email_from: str = "CROOKS <orders@crooksldn.com>"
    email_reply_to: str = ""
    store_url: str = "https://crooksldn.com"

    # --- CLIVE (/api/v1): comma-separated bearer keys; a write key can read ---
    clive_read_keys: str = ""
    clive_write_keys: str = ""

    # --- the service ---
    db_path: str = "preorders.sqlite3"
    # How often the webhook inbox is processed and Shopify re-converged, in seconds. 0: off.
    tick_interval_s: int = 30
    # Full reconciliation against Shopify, in minutes. 0: only when asked.
    reconcile_every_min: int = 60
    # Local work only: the admin API answers without a Shopify session token.
    dev_skip_admin_auth: bool = Field(default=False)
    # Waitlist signups through the app proxy: at most this many per address per hour.
    signup_ip_limit: int = 20

    def keys(self, kind: str) -> list[str]:
        def split(raw: str) -> list[str]:
            return [k.strip() for k in raw.split(",") if k.strip()]

        write = split(self.clive_write_keys)
        return write if kind == "write" else split(self.clive_read_keys) + write


@lru_cache
def get_settings() -> Settings:
    return Settings()
