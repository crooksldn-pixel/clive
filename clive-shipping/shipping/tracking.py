"""Where a bought label's parcel is, as Shopify's carrier tracking says. The one place that maps it.

Shopify keeps carrier tracking on the Fulfillment (Admin API 2026-10): `displayStatus`
(FulfillmentDisplayStatus), `inTransitAt`, `deliveredAt`, `estimatedDeliveryAt`. Checked on the
live store 2026-10-07:
  * UK Royal Mail parcels go LABEL_PURCHASED / LABEL_PRINTED → CONFIRMED → IN_TRANSIT →
    OUT_FOR_DELIVERY → DELIVERED, with `deliveredAt` set.
  * Channel Islands Royal Mail parcels stop at IN_TRANSIT: Royal Mail hands them to Guernsey or
    Jersey Post and Shopify gets no later event. They can never show Delivered from Shopify.
  * `Fulfillment.status` is SUCCESS from the moment the fulfilment exists. It is never taken as
    delivered.

Stages: unknown, pre_transit, in_transit, out_for_delivery, delivery_attempted,
ready_for_pickup, delivered, exception (delayed, failure, not delivered), cancelled.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from shipping.shopify import FulfillmentTracking

DISPLAY_STAGE = {
    # before the carrier has it
    "LABEL_PURCHASED": "pre_transit",
    "LABEL_PRINTED": "pre_transit",
    "CONFIRMED": "pre_transit",
    "FULFILLED": "pre_transit",
    "MARKED_AS_FULFILLED": "pre_transit",
    "SUBMITTED": "pre_transit",
    # moving
    "CARRIER_PICKED_UP": "in_transit",
    "IN_TRANSIT": "in_transit",
    "PICKED_UP": "in_transit",
    "OUT_FOR_DELIVERY": "out_for_delivery",
    "ATTEMPTED_DELIVERY": "delivery_attempted",
    "READY_FOR_PICKUP": "ready_for_pickup",
    # arrived
    "DELIVERED": "delivered",
    # problems: shown as warnings, never as delivered
    "DELAYED": "exception",
    "FAILURE": "exception",
    "NOT_DELIVERED": "exception",
    "CANCELED": "cancelled",
    "LABEL_VOIDED": "cancelled",
}

MOVING = ("in_transit", "out_for_delivery", "delivery_attempted", "ready_for_pickup", "exception")

LABELS = {
    "unknown": "No carrier update yet",
    "pre_transit": "Waiting for the carrier",
    "in_transit": "In transit",
    "out_for_delivery": "Out for delivery",
    "delivery_attempted": "Delivery attempted",
    "ready_for_pickup": "Ready for pickup",
    "delivered": "Delivered",
    "exception": "Carrier reports a problem",
    "cancelled": "Fulfilment cancelled in Shopify",
}


def stage_of(f: FulfillmentTracking) -> str:
    """Delivered needs Shopify's own delivered date or status; a successful fulfilment isn't."""
    if f.delivered_at or f.display_status == "DELIVERED":
        return "delivered"
    found = DISPLAY_STAGE.get(f.display_status or "")
    if found:
        return found
    return "in_transit" if f.in_transit_at else "unknown"


def _norm(number: str | None) -> str:
    return "".join((number or "").split()).upper()


def match(
    candidates: list[FulfillmentTracking], fulfillment_id: str | None, number: str | None
) -> FulfillmentTracking | None:
    """CLIVE's own fulfilment: by its id, else by its tracking number. Never "the first one":
    an order can have several fulfilments, and a wrong one would report someone else's parcel."""
    if fulfillment_id:
        found = next((f for f in candidates if f.id == fulfillment_id), None)
        if found is not None:
            return found
    want = _norm(number)
    if not want:
        return None
    hits = [f for f in candidates if want in {_norm(n) for n in f.numbers}]
    return hits[0] if len(hits) == 1 else None


# Polling: Shopify, not the carrier, is asked, and only about parcels still on their way.
FRESH = {  # stage -> how soon to look again
    "unknown": timedelta(hours=2),
    "pre_transit": timedelta(hours=2),
    "in_transit": timedelta(hours=2),
    "out_for_delivery": timedelta(hours=1),
    "delivery_attempted": timedelta(hours=2),
    "ready_for_pickup": timedelta(hours=6),
    "exception": timedelta(hours=4),
}
QUIET_AFTER = timedelta(days=5)  # no news for this long: look twice a day
QUIET_EVERY = timedelta(hours=12)
GIVE_UP_AFTER = timedelta(days=30)  # since the label: stop asking, say so


def next_check(
    stage: str, now: datetime, changed_at: datetime, bought_at: datetime
) -> datetime | None:
    """When to read this parcel's tracking again; None: never (delivered, cancelled, or no
    news for a month, as with Channel Islands parcels)."""
    if stage in ("delivered", "cancelled"):
        return None
    if now - bought_at >= GIVE_UP_AFTER:
        return None
    if now - changed_at >= QUIET_AFTER:
        return now + QUIET_EVERY
    return now + FRESH.get(stage, timedelta(hours=2))
