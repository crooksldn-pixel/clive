"""Parcel tracking in the conversation: where a parcel is, from the carrier's own scans, through
Ship24 (app/clients/ship24.py). "Where is order 2106?" is the order's fulfilment (its tracking
number, from shopify_order_detail) and then this.

A read. Nothing here can change anything in Shopify: the client talks to api.ship24.com and
nothing else, and no Shopify client is reachable from this module. On a per-shipment plan the
first look-up of a number Ship24 is not tracking yet starts a tracker for it there (one shipment
of the plan); the result says so (`new_tracker`), and asking again reads that tracker and spends
nothing more.

GREEN: the result is a carrier, a status and the carrier's scans (a time, a depot or town, the
carrier's words). The recipient Ship24 may hold is never read (app/clients/ship24.py `summary`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.capabilities.families import CapabilityFamily, register
from app.clients import ship24 as client
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

TOOLS = ("track_parcel",)
# A first look-up waits on the carrier (app/clients/ship24.py LOOKUP_TIMEOUT_S), after a quick
# read of any tracker that already exists; this is that, and a little over.
TIMEOUT_S = client.READ_TIMEOUT_S + client.LOOKUP_TIMEOUT_S + 5.0


async def _probe(_runtime: Any) -> dict[str, str]:
    """No key is DISCONNECTED, which takes track_parcel off what the model is offered and tells it
    why in one line; a key is READY. No call to Ship24: what the key's plan is, and whether it is
    still good, is said by the look-up itself, in words."""
    if not client.api_key():
        return {"state": "DISCONNECTED", "detail": client.NOT_CONNECTED}
    return {"state": "READY", "detail": "Ship24 is connected"}


FAMILY = register(CapabilityFamily(
    key="parcel_tracking", label="Parcel tracking", area="shipping",
    what="where a parcel is, from the carrier's own scans (Ship24)",
    tools=TOOLS, state="READY", detail="ready", probe=_probe,
))


@tool(
    name="track_parcel",
    description=("Where a parcel is, from the carrier's own scans (Ship24): carrier, status, estimated "
                 "delivery, latest events. The tracking number is on the order's fulfilment "
                 "(shopify_order_detail); never guess one. Changes nothing in Shopify."),
    input_schema={
        "type": "object",
        "properties": {
            "tracking_number": {"type": "string"},
            "courier": {"type": "string", "description": "Optional: the fulfilment's carrier."},
        },
        "required": ["tracking_number"],
    },
    tier=Tier.GREEN,
    timeout_s=TIMEOUT_S,
)
async def track_parcel(tracking_number: str, courier: str = "") -> dict[str, Any]:
    try:
        found = await client.track(tracking_number, courier)
    except client.Ship24Unavailable as exc:
        raise ToolError(str(exc)) from None
    out = {**found, "checked_at": datetime.now(UTC).isoformat(timespec="seconds")}
    notes = []
    if found.get("new_tracker"):
        notes.append("Ship24 started tracking this number just now (one shipment of the plan).")
    if not found.get("events"):
        notes.append("No carrier scans yet: a parcel handed over today often has none until its first scan.")
    if notes:
        out["note"] = " ".join(notes)
    return out
