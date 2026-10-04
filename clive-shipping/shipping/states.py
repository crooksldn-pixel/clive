"""The shipment state machine. Every status change goes through move(), which refuses any
transition not listed here, so no code path can jump a shipment from ready to fulfilled."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from shipping.models import Event, Shipment
from shipping.models import ShipmentStatus as S

ALLOWED: dict[S, frozenset[S]] = {
    S.discovered: frozenset({S.needs_attention, S.ready, S.cancelled}),
    S.needs_attention: frozenset({S.ready, S.needs_attention, S.cancelled}),
    S.ready: frozenset({S.needs_attention, S.ready, S.purchasing, S.cancelled}),
    # A buy either fails cleanly (nothing charged), becomes uncertain, or succeeds.
    S.purchasing: frozenset({S.ready, S.reconciliation_required, S.label_purchased}),
    S.reconciliation_required: frozenset({S.label_purchased, S.ready}),
    S.label_purchased: frozenset({S.fulfilled, S.fulfillment_failed, S.void_requested}),
    S.fulfillment_failed: frozenset({S.fulfilled, S.fulfillment_failed, S.void_requested}),
    S.fulfilled: frozenset({S.in_transit, S.delivered, S.void_requested}),
    S.in_transit: frozenset({S.delivered}),
    S.delivered: frozenset(),
    S.void_requested: frozenset({S.voided, S.void_rejected}),
    S.void_rejected: frozenset({S.void_requested}),
    S.voided: frozenset(),
    S.cancelled: frozenset(),
}


class IllegalTransition(RuntimeError):
    pass


def move(
    shipment: Shipment,
    to: S,
    *,
    at: datetime,
    actor: str,
    event: str,
    detail: dict[str, Any] | None = None,
    verified: bool = False,
) -> None:
    if to not in ALLOWED[shipment.status]:
        raise IllegalTransition(f"{shipment.id}: {shipment.status.value} -> {to.value}")
    shipment.status = to
    shipment.timeline.append(
        Event(at=at, type=event, actor=actor, detail=detail or {}, verified=verified)
    )
