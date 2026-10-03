"""Configuration. Policy lives here, never in a request: what a customer is offered and what a
change does are decided by these values and printed on every preview, so CLIVE and the portal
always quote the same thing."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> str | None:
    # RETURNS_ENV_FILE set to nothing reads no file: the tests run that way.
    return os.environ.get("RETURNS_ENV_FILE", ".env") or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RETURNS_", env_file=_env_file(), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Shopify ---
    shop_domain: str = "5wn03t-nm.myshopify.com"
    api_version: str = "2026-10"
    # "client_credentials" (Dev Dashboard app, the same set-up CLIVE uses) or "static_token".
    shopify_auth_mode: str = "client_credentials"
    shopify_client_id: str = ""
    # Also the key Shopify signs app proxy requests and webhooks with.
    shopify_client_secret: str = ""
    shopify_static_token: str = ""
    # "fake" serves the built-in fixture store, for local work and the tests.
    shopify_backend: str = "graphql"
    # Where a restocked return goes back on the shelf. Empty: items are recorded as needing
    # processing and nothing is restocked automatically.
    restock_location_id: str = ""

    # --- the service ---
    # The address Shopify and customers reach this service on (label links point here).
    public_base_url: str = "http://127.0.0.1:8100"
    db_path: str = "returns.sqlite3"
    # Signs portal sessions and label links. Must be long and random in production.
    session_secret: str = "dev-only-change-me"
    session_ttl_s: int = 3600
    # Wrong lookups allowed per order number in 15 minutes: the guard against guessing.
    lookup_order_limit: int = 5
    # Wrong lookups allowed per address in 15 minutes. Through the app proxy every customer
    # arrives from Shopify's servers, so this is a coarse flood guard, not a per-person limit.
    lookup_ip_limit: int = 300
    # Local development only: accept portal calls that did not come through the app proxy.
    dev_skip_proxy_signature: bool = False
    # Local development only: open the admin screen without a Shopify admin session.
    dev_skip_admin_auth: bool = False
    # Pilot mode: when set, only these order numbers (comma-separated digits) can use the portal.
    # Lets the service run against the real store, on the Staging theme, before launch.
    pilot_order_numbers: str = ""
    timezone: str = "Europe/London"

    # --- policy (decided 2026-10-03) ---
    # Consumer Contracts Regulations: 14 days from delivery to ask for a change-of-mind return.
    window_days: int = 14
    # Consumer Rights Act: faulty, wrong or misdescribed goods may be rejected for 30 days.
    fault_window_days: int = 30
    # When the carrier has not reported delivery, assume it this many days after dispatch.
    # Generous on purpose: a later assumed delivery only ever widens the customer's window.
    transit_fallback_days: int = 3
    # Products carrying one of these tags cannot be returned for a change of mind (sealed
    # hygiene goods, personalised items). Faulty goods are always returnable.
    non_returnable_tags: str = "non-returnable"
    # Store credit bonus by value of the credited items, "from_pence:bonus_pence" bands.
    # Owner's examples: a £25 tee credits £30, a £60 item credits £70.
    credit_bonus_bands: str = "0:500,4000:1000"
    # What a Royal Mail return label costs CROOKS (Click & Drop price, no premium). The customer
    # pays it only on a change-of-mind refund with a label; empty: that option is not offered.
    return_label_cost_pence: int | None = None
    # Refund the original delivery charge when every item of the order comes back for a refund.
    refund_outbound_shipping_on_full_return: bool = True
    # How long a return may sit approved with "label later" before it is flagged overdue.
    label_due_hours: int = 24
    # How often the service checks for overdue labels by itself, in seconds. 0 turns it off.
    tick_interval_s: int = 900
    # Let Shopify send its own return emails (label, refund). Edit them in Shopify admin ->
    # Settings -> Notifications so they carry the CROOKS look.
    shopify_notify_customer: bool = True

    # --- Royal Mail Click & Drop ---
    clickdrop_api_key: str = ""
    clickdrop_base_url: str = "https://api.parcel.royalmail.com/api/v1"
    # Tracked Returns service code on the CROOKS account. Confirm in Click & Drop before use.
    clickdrop_service_code: str = ""
    clickdrop_package_format: str = "parcel"
    clickdrop_weight_grams: int = 600
    returns_address_name: str = "CROOKS LDN Returns"
    returns_address_line1: str = ""
    returns_address_line2: str = ""
    returns_address_city: str = ""
    returns_address_postcode: str = ""
    returns_address_country: str = "GB"

    # --- CLIVE ---
    # Bearer keys, comma-separated. Read keys see everything; write keys may also act.
    clive_read_keys: str = ""
    clive_write_keys: str = ""
    clive_webhook_url: str = ""
    clive_webhook_secret: str = ""

    def bonus_bands(self) -> list[tuple[int, int]]:
        bands = []
        for part in self.credit_bonus_bands.split(","):
            if part.strip():
                floor, bonus = part.split(":")
                bands.append((int(floor), int(bonus)))
        return sorted(bands)

    def pilot_orders(self) -> set[str]:
        return parse_order_numbers(self.pilot_order_numbers)

    def excluded_tags(self) -> set[str]:
        return {t.strip().casefold() for t in self.non_returnable_tags.split(",") if t.strip()}

    def keys(self, kind: str) -> set[str]:
        raw = self.clive_write_keys if kind == "write" else self.clive_read_keys
        found = {k.strip() for k in raw.split(",") if k.strip()}
        # A write key can always read.
        return found | (self.keys("write") if kind == "read" else set())


def parse_order_numbers(raw: str) -> set[str]:
    """ "2129, #2130 CROOKS-2131" -> {"2129", "2130", "2131"}."""
    return {"".join(c for c in p if c.isdigit()) for p in raw.replace(" ", ",").split(",")} - {""}


@lru_cache
def get_settings() -> Settings:
    return Settings()
