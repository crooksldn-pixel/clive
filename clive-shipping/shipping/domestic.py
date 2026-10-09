"""UK orders (domestic): which Royal Mail service a label is bought with, decided by the owner.

Two services only, Royal Mail Tracked 24 and Tracked 48 through Shopify Shipping. Which one an
order gets is decided by the delivery method the customer chose at checkout (the order's
shipping line), through an explicit mapping set on the server:

    SHIPPING_DOMESTIC_SHIPPING_LINES="Tracked 24=24; Tracked 48=48"

A shipping line that isn't in the mapping (or an order without one, e.g. a draft order) is
never guessed: the order waits in Needs attention until a person picks the service for it.

Shopify Shipping buys a label for a carrier and service code (`preferredRateSelection`). Shopify
publishes no list of those codes and has no API to look them up (Shopify staff, dev forum, July
2026), so each service's code is a server setting, e.g.

    SHIPPING_SHOPIFY_TRACKED_24_RATE="<carrierCode>/<serviceCode>"

Empty means that service can't be bought here: CLIVE never falls back to Shopify's default rate
selection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TRACKED_24 = "tracked_24"
TRACKED_48 = "tracked_48"
SERVICES = {TRACKED_24: "Tracked 24", TRACKED_48: "Tracked 48"}
CARRIER = "Royal Mail"
# The digits the mapping uses for each service ("Tracked 24=24").
BY_DIGITS = {"24": TRACKED_24, "48": TRACKED_48}
# How long each service takes, as Royal Mail describes it (working days), for the screen only.
DAYS = {TRACKED_24: (1, 1), TRACKED_48: (2, 3)}


def norm(title: str | None) -> str:
    """A shipping line title as compared: case and spacing don't matter, the words do."""
    return re.sub(r"\s+", " ", (title or "").strip()).casefold()


def parse_lines(raw: str) -> dict[str, str]:
    """ "Tracked 24=24; Tracked 48=48" -> {"tracked 24": "tracked_24", ...}. A bad entry is an
    error at startup, never ignored: a mapping that is silently half-read would buy the wrong
    service."""
    out: dict[str, str] = {}
    for part in re.split(r"[;\n]", raw or ""):
        if not part.strip():
            continue
        title, sep, value = part.rpartition("=")
        key, digits = norm(title), value.strip()
        if not sep or not key:
            raise ValueError(f"'{part.strip()}' should read 'Shipping line title=24' (or =48).")
        if digits not in BY_DIGITS:
            raise ValueError(f"'{part.strip()}' maps to '{digits}': only 24 or 48 are allowed.")
        if key in out and out[key] != BY_DIGITS[digits]:
            raise ValueError(f"The shipping line '{title.strip()}' is mapped twice.")
        out[key] = BY_DIGITS[digits]
    return out


@dataclass(frozen=True)
class RateCode:
    """Shopify Shipping's own codes for one service (`preferredRateSelection`)."""

    carrier_code: str
    service_code: str


def parse_rate(raw: str) -> RateCode | None:
    """ "carrier/service" -> RateCode; "" -> None (not set: that service can't be bought)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    carrier, sep, service = raw.partition("/")
    if not sep or not carrier.strip() or not service.strip():
        raise ValueError(f"'{raw}' should read '<carrierCode>/<serviceCode>'.")
    return RateCode(carrier.strip(), service.strip())


@dataclass(frozen=True)
class DomesticPolicy:
    """What the server says about UK labels. `enabled` False: UK orders aren't shown or bought."""

    enabled: bool = False
    lines: dict[str, str] = field(default_factory=dict)
    rates: dict[str, RateCode | None] = field(default_factory=dict)

    def service_for(self, shipping_line: str | None) -> str | None:
        """The mapped service for a checkout delivery method; None: not mapped (ask a person)."""
        return self.lines.get(norm(shipping_line)) if shipping_line else None

    def rate(self, service: str) -> RateCode | None:
        return self.rates.get(service)


def title(service: str | None) -> str:
    """ "tracked_24" -> "Tracked 24"."""
    return SERVICES.get(service or "", service or "")
