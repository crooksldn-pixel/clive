"""CLIVE Preorders: the application layer.

Our database is the operational truth for inbound batches, allocations and preorder lines;
Shopify is the truth for orders, inventory and what is on sale. `sync_offer` makes Shopify match
our offers (desired-state convergence: idempotent, safe to run any time, run after every change
and on the timer). Order ingestion re-reads each order from Shopify and upserts its lines by
Shopify id, so a webhook that comes twice, late or out of order changes nothing it shouldn't.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from preorders import domain
from preorders.domain import (
    OPEN_BATCH,
    BatchStatus,
    CommerceState,
    LineState,
    Mode,
    OfferStatus,
)
from preorders.selling_plans import PlansUnavailable, SellingPlanPort
from preorders.settings import Settings
from preorders.shopify import PlanSpec, ShopifyError, ShopifyPort, ShopifyRefused
from preorders.store import Store, iso, new_id, now

log = logging.getLogger("preorders.service")


class ActionError(Exception):
    def __init__(self, message: str, status: int = 409, code: str = "refused") -> None:
        super().__init__(message)
        self.status, self.code = status, code


def numeric(gid: str | None) -> str:
    return (gid or "").rsplit("/", 1)[-1]


def parse_day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ActionError("Dates are YYYY-MM-DD.", 422, "bad_date") from exc


def plan_time(day: date | None) -> str | None:
    """Shopify's fulfilment time for the plan: midday UTC on the dispatch day."""
    return f"{day.isoformat()}T12:00:00Z" if day else None


class PreordersService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        shopify: ShopifyPort,
        plans: SellingPlanPort,
        clock: Callable[[], datetime] = now,
    ) -> None:
        self.s = settings
        self.store = store
        self.shopify = shopify
        self.plans = plans
        self.clock = clock
        self.shop = settings.shop_domain
        self._location: str | None = settings.location_id or None
        # Set by app.build_service (comms needs the service, the service sends through comms).
        self.comms: Any = None
        self.waitlist: Any = None

    def today(self) -> date:
        return self.clock().astimezone(UTC).date()

    def _event(
        self, kind: str, subject: str, detail: dict[str, Any] | None = None, actor: str = "system"
    ) -> None:
        self.store.event(self.shop, kind, subject, detail, actor)

    # ================================================================== catalogue

    def refresh_catalog(self, product_id: str | None = None) -> int:
        """Shopify's variants and inventory (available, committed, incoming, on hand) into the
        local snapshot the screens and state rules read."""
        query = f"product_id:{numeric(product_id)}" if product_id else None
        snaps = self.shopify.variants(query)
        at = iso(self.clock())
        with self.store.tx():
            for v in snaps:
                self.store.x(
                    """INSERT INTO catalog (variant_id, shop, product_id, product_title,
                    variant_title, sku, inventory_item_id, inventory_policy, tracked, available,
                    committed, incoming, on_hand, price_minor, image_url, position, refreshed_at,
                    handle) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT (variant_id) DO UPDATE SET product_title=excluded.product_title,
                    variant_title=excluded.variant_title, sku=excluded.sku,
                    inventory_item_id=excluded.inventory_item_id,
                    inventory_policy=excluded.inventory_policy, tracked=excluded.tracked,
                    available=excluded.available, committed=excluded.committed,
                    incoming=excluded.incoming, on_hand=excluded.on_hand,
                    price_minor=excluded.price_minor, image_url=excluded.image_url,
                    position=excluded.position, refreshed_at=excluded.refreshed_at,
                    handle=excluded.handle""",
                    (
                        v.variant_id,
                        self.shop,
                        v.product_id,
                        v.product_title,
                        v.variant_title,
                        v.sku,
                        v.inventory_item_id,
                        v.inventory_policy,
                        int(v.tracked),
                        v.available,
                        v.committed,
                        v.incoming,
                        v.on_hand,
                        v.price_minor,
                        v.image_url,
                        v.position,
                        at,
                        v.handle,
                    ),
                )
        return len(snaps)

    def variant(self, variant_id: str) -> dict[str, Any]:
        row = self.store.one("SELECT * FROM catalog WHERE variant_id = ?", (variant_id,))
        if row is None:
            raise ActionError("That variant isn't in the catalogue; refresh it.", 404, "not_found")
        return row

    def location_id(self) -> str:
        if self._location:
            return self._location
        found = [loc for loc in self.shopify.locations() if loc.get("isActive")]
        if not found:
            raise ActionError("Shopify has no active location to receive stock into.")
        found.sort(key=lambda loc: not loc.get("fulfillsOnlineOrders"))
        self._location = str(found[0]["id"])
        return self._location

    # ================================================================== batches

    def create_batch(
        self,
        *,
        reference: str,
        expected_arrival_at: str | None,
        expected_dispatch_at: str | None,
        supplier_reference: str = "",
        notes: str = "",
        status: str = "ORDERED",
        lines: list[dict[str, Any]] | None = None,
        actor: str,
    ) -> dict[str, Any]:
        reference = reference.strip()
        if not 1 <= len(reference) <= 80:
            raise ActionError("Give the batch a name, e.g. 'T-Shirt Restock'.", 422)
        arrival, dispatch = parse_day(expected_arrival_at), parse_day(expected_dispatch_at)
        if arrival and dispatch and dispatch < arrival:
            raise ActionError("Dispatch can't be before the stock arrives.", 422)
        if status not in BatchStatus.__members__ or status in ("RECEIVED", "PARTIALLY_RECEIVED"):
            raise ActionError("A new batch is planned, ordered, in transit or delayed.", 422)
        bid, at = new_id("bat"), iso(self.clock())
        with self.store.tx():
            self.store.insert(
                "batches",
                {
                    "id": bid,
                    "shop": self.shop,
                    "reference": reference,
                    "status": status,
                    "supplier_reference": supplier_reference.strip()[:120],
                    "expected_arrival_at": arrival.isoformat() if arrival else None,
                    "expected_dispatch_at": dispatch.isoformat() if dispatch else None,
                    "notes": notes.strip()[:2000],
                    "created_at": at,
                    "updated_at": at,
                },
            )
            for line in lines or []:
                self._add_line(bid, line)
            self._event("batch_created", bid, {"reference": reference}, actor)
        return self.batch(bid)

    def _add_line(self, batch_id: str, line: dict[str, Any]) -> str:
        v = self.variant(str(line.get("variant_id")))
        expected = int(line.get("expected_quantity") or 0)
        given = line.get("preorder_allocation")  # absent or empty: preorder what's coming
        allocation = expected if given is None else int(given)
        if expected <= 0:
            raise ActionError(
                f"{v['product_title']} {v['variant_title']}: how many are coming?", 422
            )
        if not 0 <= allocation <= expected:
            raise ActionError("Preorder allocation is between 0 and the quantity coming.", 422)
        lid, at = new_id("bln"), iso(self.clock())
        try:
            self.store.insert(
                "batch_lines",
                {
                    "id": lid,
                    "batch_id": batch_id,
                    "product_id": v["product_id"],
                    "variant_id": v["variant_id"],
                    "inventory_item_id": v["inventory_item_id"],
                    "sku": v["sku"],
                    "product_title": v["product_title"],
                    "variant_title": v["variant_title"],
                    "expected_quantity": expected,
                    "received_quantity": 0,
                    "preorder_allocation": allocation,
                    "created_at": at,
                    "updated_at": at,
                },
            )
        except sqlite3.IntegrityError as exc:
            raise ActionError(f"{v['variant_title']} is already in this batch.", 409) from exc
        return lid

    def add_batch_line(self, batch_id: str, line: dict[str, Any], actor: str) -> dict[str, Any]:
        b = self._batch_row(batch_id)
        if b["status"] not in OPEN_BATCH:
            raise ActionError("This batch is closed.")
        with self.store.tx():
            lid = self._add_line(batch_id, line)
            self._event("batch_line_added", batch_id, {"line": lid}, actor)
        return self.batch(batch_id)

    def update_batch_line(
        self,
        line_id: str,
        *,
        expected_quantity: int | None = None,
        preorder_allocation: int | None = None,
        actor: str,
    ) -> dict[str, Any]:
        with self.store.tx():
            line = self._line_row(line_id)
            expected = line["expected_quantity"] if expected_quantity is None else expected_quantity
            allocation = (
                line["preorder_allocation"] if preorder_allocation is None else preorder_allocation
            )
            sold = self.sold_for_line(line_id)
            if expected < line["received_quantity"]:
                raise ActionError(f"{line['received_quantity']} have already been received.", 422)
            if allocation > expected:
                raise ActionError(
                    "Preorder allocation can't be more than the quantity coming.", 422
                )
            if allocation < sold:
                raise ActionError(
                    f"{sold} are already preordered: the allocation can't go below that.", 422
                )
            self.store.update(
                "batch_lines",
                "id",
                line_id,
                {
                    "expected_quantity": expected,
                    "preorder_allocation": allocation,
                    "updated_at": iso(self.clock()),
                },
            )
            self._event(
                "allocation_changed",
                line["batch_id"],
                {"line": line_id, "expected": expected, "allocation": allocation},
                actor,
            )
        self.sync_offers_for_batch(line["batch_id"])
        return self.batch(line["batch_id"])

    def _batch_row(self, batch_id: str) -> dict[str, Any]:
        b = self.store.one("SELECT * FROM batches WHERE id = ? AND shop = ?", (batch_id, self.shop))
        if b is None:
            raise ActionError("Batch not found.", 404, "not_found")
        return b

    def _line_row(self, line_id: str) -> dict[str, Any]:
        line = self.store.one("SELECT * FROM batch_lines WHERE id = ?", (line_id,))
        if line is None:
            raise ActionError("Batch line not found.", 404, "not_found")
        return line

    def sold_for_line(self, batch_line_id: str) -> int:
        """Units preordered against one batch line: live lines only (cancelled and refunded units
        give their capacity back). Derived every time, never a stored counter."""
        return int(
            self.store.value(
                "SELECT COALESCE(SUM(current_quantity), 0) FROM preorder_lines WHERE "
                "batch_line_id = ?"
                " AND cancelled_at IS NULL",
                (batch_line_id,),
            )
            or 0
        )

    def batch(self, batch_id: str) -> dict[str, Any]:
        b = self._batch_row(batch_id)
        lines = self.store.all(
            "SELECT * FROM batch_lines WHERE batch_id = ? ORDER BY product_title, variant_title",
            (batch_id,),
        )
        out_lines = []
        for ln in lines:
            sold = self.sold_for_line(ln["id"])
            out_lines.append(
                {
                    **ln,
                    "sold": sold,
                    "remaining": domain.remaining(ln["preorder_allocation"], sold),
                    "oversold": domain.oversold(ln["preorder_allocation"], sold),
                    "outstanding": ln["expected_quantity"] - ln["received_quantity"],
                    "buffer": ln["expected_quantity"] - ln["preorder_allocation"],
                }
            )
        totals = {
            "expected": sum(x["expected_quantity"] for x in out_lines),
            "received": sum(x["received_quantity"] for x in out_lines),
            "allocation": sum(x["preorder_allocation"] for x in out_lines),
            "sold": sum(x["sold"] for x in out_lines),
        }
        totals["remaining"] = max(totals["allocation"] - totals["sold"], 0)
        offers = self.store.all("SELECT * FROM offers WHERE batch_id = ?", (batch_id,))
        receipts = self.store.all(
            "SELECT r.* FROM receipts r JOIN batch_lines l ON l.id = r.batch_line_id "
            "WHERE l.batch_id = ? ORDER BY r.created_at DESC",
            (batch_id,),
        )
        return {
            **b,
            "lines": out_lines,
            "totals": totals,
            "offers": offers,
            "receipts": receipts,
            "affected": self.affected(batch_id),
        }

    def batches(self) -> list[dict[str, Any]]:
        rows = self.store.all(
            "SELECT id FROM batches WHERE shop = ? ORDER BY CASE status WHEN 'RECEIVED' THEN 1 "
            "WHEN 'CANCELLED' THEN 2 ELSE 0 END, expected_arrival_at IS NULL, "
            "expected_arrival_at",
            (self.shop,),
        )
        return [self.batch(r["id"]) for r in rows]

    def set_batch_status(self, batch_id: str, status: str, actor: str) -> dict[str, Any]:
        if status not in ("PLANNED", "ORDERED", "IN_TRANSIT", "DELAYED", "CANCELLED"):
            raise ActionError("Receiving stock sets received statuses; pick another.", 422)
        b = self._batch_row(batch_id)
        if b["status"] in ("RECEIVED", "CANCELLED"):
            raise ActionError("This batch is closed.")
        if status == "CANCELLED" and self.affected(batch_id)["units"]:
            raise ActionError(
                "Customers have preordered from this batch: move them to another "
                "date or refund them in Shopify before cancelling it."
            )
        with self.store.tx():
            self.store.update(
                "batches", "id", batch_id, {"status": status, "updated_at": iso(self.clock())}
            )
            if status == "CANCELLED":
                self.store.x(
                    "UPDATE offers SET status = 'CLOSED', updated_at = ? WHERE batch_id = ?",
                    (iso(self.clock()), batch_id),
                )
            self._event("batch_status", batch_id, {"status": status}, actor)
        self.sync_offers_for_batch(batch_id)
        return self.batch(batch_id)

    # ================================================================== offers

    def offer(self, offer_id: str) -> dict[str, Any]:
        o = self.store.one("SELECT * FROM offers WHERE id = ? AND shop = ?", (offer_id, self.shop))
        if o is None:
            raise ActionError("Preorder not found.", 404, "not_found")
        return o

    def offer_dispatch(self, offer: dict[str, Any]) -> date | None:
        if offer.get("dispatch_at"):
            return parse_day(offer["dispatch_at"])
        b = self._batch_row(offer["batch_id"])
        return parse_day(b["expected_dispatch_at"])

    def configure_offer(
        self,
        *,
        product_id: str,
        batch_id: str,
        discount_type: str = "NONE",
        discount_value: float = 0,
        dispatch_at: str | None = None,
        variants: list[str] | None = None,
        mode: str = "AUTO",
        actor: str,
    ) -> dict[str, Any]:
        """Create or change the preorder for one product from one batch. Variants offered are
        those of the product in the batch (or the subset given). Saved as a draft until
        activated; a live offer re-syncs at once."""
        b = self._batch_row(batch_id)
        if b["status"] not in OPEN_BATCH:
            raise ActionError("This batch is closed.")
        if not domain.discount_ok(discount_type, float(discount_value)):
            raise ActionError("A preorder discount is none, or a percentage between 1 and 99.", 422)
        if mode not in Mode.__members__:
            raise ActionError("Unknown mode.", 422)
        day = parse_day(dispatch_at)
        lines = self.store.all(
            "SELECT * FROM batch_lines WHERE batch_id = ? AND product_id = ?",
            (batch_id, product_id),
        )
        if not lines:
            raise ActionError("That product has nothing in this batch: add its sizes first.", 422)
        chosen = set(variants) if variants is not None else {ln["variant_id"] for ln in lines}
        at = iso(self.clock())
        with self.store.tx():
            existing = self.store.one(
                "SELECT * FROM offers WHERE shop = ? AND product_id = ? AND batch_id = ?",
                (self.shop, product_id, batch_id),
            )
            oid = existing["id"] if existing else new_id("off")
            if existing is None:
                self.store.insert(
                    "offers",
                    {
                        "id": oid,
                        "shop": self.shop,
                        "product_id": product_id,
                        "product_title": lines[0]["product_title"],
                        "batch_id": batch_id,
                        "status": OfferStatus.DRAFT,
                        "mode": mode,
                        "discount_type": discount_type,
                        "discount_value": float(discount_value),
                        "dispatch_at": day.isoformat() if day else None,
                        "created_at": at,
                        "updated_at": at,
                    },
                )
            else:
                self.store.update(
                    "offers",
                    "id",
                    oid,
                    {
                        "mode": mode,
                        "discount_type": discount_type,
                        "discount_value": float(discount_value),
                        "dispatch_at": day.isoformat() if day else None,
                        "updated_at": at,
                    },
                )
            for ln in lines:
                self.store.x(
                    """INSERT INTO offer_variants (id, offer_id, variant_id, batch_line_id,
                    enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT (offer_id, variant_id) DO UPDATE SET enabled = excluded.enabled,
                    updated_at = excluded.updated_at""",
                    (
                        new_id("ofv"),
                        oid,
                        ln["variant_id"],
                        ln["id"],
                        int(ln["variant_id"] in chosen),
                        at,
                        at,
                    ),
                )
            self._event(
                "offer_saved",
                oid,
                {"discount": discount_value, "dispatch": dispatch_at, "mode": mode},
                actor,
            )
        if self.offer(oid)["status"] == OfferStatus.ACTIVE:
            self.sync_offer(oid)
        return self.offer_view(oid)

    def activate_offer(self, offer_id: str, actor: str) -> dict[str, Any]:
        o = self.offer(offer_id)
        b = self._batch_row(o["batch_id"])
        if b["status"] not in OPEN_BATCH:
            raise ActionError("This batch is closed.")
        if self.offer_dispatch(o) is None:
            raise ActionError("Set the expected dispatch date first: customers are told it.", 422)
        enabled = self.store.all(
            "SELECT ov.variant_id, bl.preorder_allocation FROM offer_variants ov JOIN batch_lines "
            "bl ON bl.id = ov.batch_line_id WHERE ov.offer_id = ? AND ov.enabled = 1",
            (offer_id,),
        )
        if not any(r["preorder_allocation"] > 0 for r in enabled):
            raise ActionError("No size has a preorder allocation.", 422)
        clash = self.store.one(
            "SELECT o.product_title, c.variant_title FROM offer_variants ov "
            "JOIN offers o ON o.id = ov.offer_id JOIN catalog c ON c.variant_id = ov.variant_id "
            "WHERE o.status = 'ACTIVE' AND o.id != ? AND ov.enabled = 1 AND ov.variant_id IN "
            "(SELECT variant_id FROM offer_variants WHERE offer_id = ? AND enabled = 1)",
            (offer_id, offer_id),
        )
        if clash:
            raise ActionError(
                f"{clash['variant_title']} is already on preorder from another "
                "batch. One open preorder per size."
            )
        with self.store.tx():
            self.store.update(
                "offers",
                "id",
                offer_id,
                {"status": OfferStatus.ACTIVE, "updated_at": iso(self.clock())},
            )
            self._event("offer_activated", offer_id, {}, actor)
        self.sync_offer(offer_id)
        return self.offer_view(offer_id)

    def close_offer(self, offer_id: str, actor: str) -> dict[str, Any]:
        self.offer(offer_id)
        with self.store.tx():
            self.store.update(
                "offers",
                "id",
                offer_id,
                {"status": OfferStatus.CLOSED, "updated_at": iso(self.clock())},
            )
            self._event("offer_closed", offer_id, {}, actor)
        self.sync_offer(offer_id)
        return self.offer_view(offer_id)

    def offer_view(self, offer_id: str) -> dict[str, Any]:
        o = self.offer(offer_id)
        rows = self.store.all(
            "SELECT ov.*, bl.preorder_allocation, bl.expected_quantity, bl.received_quantity, "
            "c.variant_title, c.sku, c.available, c.inventory_policy FROM offer_variants ov "
            "JOIN batch_lines bl ON bl.id = ov.batch_line_id "
            "LEFT JOIN catalog c ON c.variant_id = ov.variant_id WHERE ov.offer_id = ? "
            "ORDER BY c.position",
            (offer_id,),
        )
        day = self.offer_dispatch(o)
        variants = []
        for r in rows:
            sold = self.sold_for_line(r["batch_line_id"])
            variants.append(
                {
                    **r,
                    "sold": sold,
                    "remaining": domain.remaining(r["preorder_allocation"], sold),
                    "state": self.state_of(r["variant_id"]).value,
                }
            )
        return {
            **o,
            "dispatch": day.isoformat() if day else None,
            "dispatch_words": domain.dispatch_words(day),
            "variants": variants,
            "plans_available": self.plans.available,
            "plans_reason": self.plans.reason,
        }

    # ================================================================== state

    def _live_offer_variant(self, variant_id: str) -> dict[str, Any] | None:
        return self.store.one(
            "SELECT ov.*, o.status AS offer_status, o.mode, o.id AS offer_id, o.batch_id, "
            "bl.preorder_allocation, b.status AS batch_status FROM offer_variants ov "
            "JOIN offers o ON o.id = ov.offer_id JOIN batch_lines bl ON bl.id = ov.batch_line_id "
            "JOIN batches b ON b.id = o.batch_id WHERE ov.variant_id = ? AND ov.enabled = 1 "
            "ORDER BY o.status = 'ACTIVE' DESC, o.updated_at DESC LIMIT 1",
            (variant_id,),
        )

    def state_of(self, variant_id: str) -> CommerceState:
        cat = self.store.one("SELECT available FROM catalog WHERE variant_id = ?", (variant_id,))
        available = cat["available"] if cat else 0
        ov = self._live_offer_variant(variant_id)
        if ov is None:
            return domain.derive_state(
                available=available, offer_active=False, allocation=0, sold=0
            )
        active = (
            ov["offer_status"] == OfferStatus.ACTIVE
            and ov["batch_status"] in OPEN_BATCH
            and self.plans.available
        )
        override = CommerceState(ov["override_state"]) if ov.get("override_state") else None
        return domain.derive_state(
            available=available,
            offer_active=active,
            allocation=ov["preorder_allocation"],
            sold=self.sold_for_line(ov["batch_line_id"]),
            mode=Mode(ov["mode"]),
            override=override,
        )

    # ================================================================== Shopify convergence

    def plan_spec(self, offer: dict[str, Any]) -> PlanSpec:
        day = self.offer_dispatch(offer)
        pct = float(offer["discount_value"]) if offer["discount_type"] == "PERCENTAGE" else 0.0
        paid = "Paid in full today."
        return PlanSpec(
            merchant_code=f"clive-preorder-{offer['id']}",
            group_name="Pre-order",
            plan_name=domain.plan_name(day),
            description=f"{domain.dispatch_words(day)}. {paid} Ships separately from items in "
            "stock.",
            dispatch_at=plan_time(day),
            discount_percent=pct,
        )

    def sync_offers_for_batch(self, batch_id: str) -> None:
        for o in self.store.all("SELECT id FROM offers WHERE batch_id = ?", (batch_id,)):
            self.sync_offer(o["id"])

    def sync_all(self) -> None:
        for o in self.store.all(
            "SELECT id FROM offers WHERE shop = ? AND (status = 'ACTIVE' OR "
            "selling_plan_group_id IS NOT NULL)",
            (self.shop,),
        ):
            self.sync_offer(o["id"])

    def sync_offer(self, offer_id: str) -> dict[str, Any]:
        """Make Shopify match this offer. Order matters for safety: opening attaches the plan
        before allowing sale past zero; closing stops sale past zero before detaching."""
        o = self.offer(offer_id)
        try:
            result = self._converge(o)
            self.store.update(
                "offers", "id", offer_id, {"synced_at": iso(self.clock()), "sync_error": None}
            )
            return result
        except PlansUnavailable as exc:
            self.store.update("offers", "id", offer_id, {"sync_error": str(exc)})
            return {"ok": False, "error": str(exc)}
        except ShopifyError as exc:
            log.warning("selling plan sync for %s failed: %s", offer_id, exc)
            self.store.update("offers", "id", offer_id, {"sync_error": f"Shopify: {exc}"[:300]})
            self._event("sync_failed", offer_id, {"error": str(exc)[:200]})
            return {"ok": False, "error": str(exc)}

    def _converge(self, o: dict[str, Any]) -> dict[str, Any]:
        b = self._batch_row(o["batch_id"])
        live = o["status"] == OfferStatus.ACTIVE and b["status"] in OPEN_BATCH
        rows = self.store.all(
            "SELECT ov.*, bl.preorder_allocation FROM offer_variants ov JOIN batch_lines bl "
            "ON bl.id = ov.batch_line_id WHERE ov.offer_id = ?",
            (o["id"],),
        )
        desired: set[str] = set()
        states: dict[str, CommerceState] = {}
        for r in rows:
            sold = self.sold_for_line(r["batch_line_id"])
            if (
                live
                and r["enabled"]
                and r["override_state"] != CommerceState.NOTIFY_ME
                and domain.remaining(r["preorder_allocation"], sold) > 0
            ):
                desired.add(r["variant_id"])
            states[r["variant_id"]] = self.state_of(r["variant_id"])
        if not self.plans.available:
            if live:
                raise PlansUnavailable(self.plans.reason)
            return {"ok": True, "attached": []}
        group = o["selling_plan_group_id"]
        spec = self.plan_spec(o)
        signature = f"{spec.dispatch_at}|{spec.discount_percent}"
        if group is None and desired:
            group, plan = self.plans.create(spec, [])
            self._remember_plan(o["id"], plan, spec)
            self.store.update(
                "offers",
                "id",
                o["id"],
                {
                    "selling_plan_group_id": group,
                    "selling_plan_id": plan,
                    "plan_signature": signature,
                },
            )
            self._event("selling_plan_created", o["id"], {"group": group, "plan": plan})
        elif group and live and o["plan_signature"] != signature:
            plan = self.plans.replace(group, o["selling_plan_id"], spec)
            self.store.x(
                "UPDATE selling_plans SET retired_at = ? WHERE plan_id = ?",
                (iso(self.clock()), o["selling_plan_id"]),
            )
            self._remember_plan(o["id"], plan, spec)
            self.store.update(
                "offers", "id", o["id"], {"selling_plan_id": plan, "plan_signature": signature}
            )
            self._event("selling_plan_replaced", o["id"], {"plan": plan})
        members: set[str] = set()
        if group:
            found = self.plans.members(group)
            if found is None:  # deleted in Shopify: start again on the next pass
                self.store.update(
                    "offers",
                    "id",
                    o["id"],
                    {
                        "selling_plan_group_id": None,
                        "selling_plan_id": None,
                        "plan_signature": None,
                    },
                )
                self._event("selling_plan_missing", o["id"], {"group": group})
                return {"ok": False, "error": "selling plan group missing in Shopify"}
            members = found
        # Stop selling past zero first, then detach; attach first, then allow past zero.
        policies_off, policies_on, restore = {}, {}, {}
        for r in rows:
            vid = r["variant_id"]
            cat = self.store.one("SELECT * FROM catalog WHERE variant_id = ?", (vid,))
            if cat is None:
                continue
            current = cat["inventory_policy"]
            if live and r["enabled"]:
                want = (
                    "CONTINUE"
                    if (vid in desired and states[vid] == CommerceState.PREORDER)
                    else "DENY"
                )
                if r["original_policy"] is None and want != current:
                    self.store.update("offer_variants", "id", r["id"], {"original_policy": current})
                if want != current:
                    (policies_on if want == "CONTINUE" else policies_off)[vid] = want
            elif r["original_policy"] and r["original_policy"] != current:
                restore[vid] = r["original_policy"]
        if policies_off:
            self.shopify.set_inventory_policy(o["product_id"], policies_off)
            self._note_policies(policies_off)
        if group and members - desired:
            self.plans.detach(group, sorted(members - desired))
        if group and desired - members:
            self.plans.attach(group, sorted(desired - members))
        if policies_on:
            self.shopify.set_inventory_policy(o["product_id"], policies_on)
            self._note_policies(policies_on)
        if restore:
            self.shopify.set_inventory_policy(o["product_id"], restore)
            self._note_policies(restore)
        self._sync_metafields(o, rows, desired)
        return {"ok": True, "attached": sorted(desired)}

    def _note_policies(self, policies: dict[str, str]) -> None:
        for vid, policy in policies.items():
            self.store.x(
                "UPDATE catalog SET inventory_policy = ? WHERE variant_id = ?", (policy, vid)
            )

    def _remember_plan(self, offer_id: str, plan_id: str, spec: PlanSpec) -> None:
        self.store.x(
            "INSERT OR IGNORE INTO selling_plans (plan_id, offer_id, dispatch_at, "
            "discount_percent, name, created_at) VALUES (?,?,?,?,?,?)",
            (
                plan_id,
                offer_id,
                (spec.dispatch_at or "")[:10] or None,
                spec.discount_percent,
                spec.plan_name,
                iso(self.clock()),
            ),
        )

    def _sync_metafields(
        self, o: dict[str, Any], rows: list[dict[str, Any]], desired: set[str]
    ) -> None:
        """A small storefront-readable summary per variant ($app:preorder). The database stays
        the operational truth; this is for the theme and other apps."""
        day = self.offer_dispatch(o)
        changed: dict[str, str] = {}
        for r in rows:
            state = self.state_of(r["variant_id"])
            value = json.dumps(
                {
                    "state": state.value,
                    "dispatch_by": day.isoformat()
                    if (day and r["variant_id"] in desired)
                    else None,
                    "selling_plan_id": o["selling_plan_id"] if r["variant_id"] in desired else None,
                    "discount_percent": float(o["discount_value"])
                    if o["discount_type"] == "PERCENTAGE"
                    else 0,
                },
                sort_keys=True,
            )
            if value != r["last_metafield"]:
                changed[r["variant_id"]] = value
        if changed:
            self.shopify.set_variant_metafields(changed)
            for vid, value in changed.items():
                self.store.x(
                    "UPDATE offer_variants SET last_metafield = ? WHERE offer_id = ? "
                    "AND variant_id = ?",
                    (value, o["id"], vid),
                )

    # ================================================================== orders

    def record_webhook(self, event_id: str, topic: str, resource_id: str) -> bool:
        """Remember a webhook to process; False if it was already seen (Shopify retries)."""
        try:
            self.store.insert(
                "webhook_inbox",
                {
                    "event_id": event_id,
                    "topic": topic,
                    "resource_id": resource_id,
                    "received_at": iso(self.clock()),
                },
            )
            return True
        except sqlite3.IntegrityError:
            log.info("duplicate webhook %s (%s) ignored", event_id, topic)
            return False

    def process_inbox(self, limit: int = 50) -> int:
        rows = self.store.all(
            "SELECT * FROM webhook_inbox WHERE processed_at IS NULL AND attempts < 10 "
            "ORDER BY received_at LIMIT ?",
            (limit,),
        )
        done = 0
        seen_orders: set[str] = set()
        for r in rows:
            try:
                if r["topic"].startswith("orders/"):
                    if r["resource_id"] not in seen_orders:  # one re-read per order per pass
                        self.ingest_order(r["resource_id"])
                        seen_orders.add(r["resource_id"])
                elif r["topic"] == "inventory_levels/update":
                    self.inventory_changed(r["resource_id"])
                self.store.update(
                    "webhook_inbox",
                    "event_id",
                    r["event_id"],
                    {"processed_at": iso(self.clock()), "error": None},
                )
                done += 1
            except (ShopifyError, ActionError) as exc:
                log.warning("webhook %s (%s) not processed yet: %s", r["event_id"], r["topic"], exc)
                self.store.x(
                    "UPDATE webhook_inbox SET attempts = attempts + 1, error = ? "
                    "WHERE event_id = ?",
                    (str(exc)[:300], r["event_id"]),
                )
        return done

    def inventory_changed(self, inventory_item_id: str) -> None:
        """Shopify's stock moved: re-read that product and re-converge its offers."""
        row = self.store.one(
            "SELECT product_id FROM catalog WHERE inventory_item_id = ?", (inventory_item_id,)
        )
        if row is None:
            return
        self.refresh_catalog(row["product_id"])
        for o in self.store.all(
            "SELECT id FROM offers WHERE product_id = ? AND status = 'ACTIVE'", (row["product_id"],)
        ):
            self.sync_offer(o["id"])

    def ingest_order(self, order_id: str) -> list[dict[str, Any]]:
        """Read the order from Shopify and upsert its preorder lines. Idempotent: any number of
        webhooks, in any order, give the same rows. The promise each line was bought with comes
        from the selling plan it was bought on, never from today's settings."""
        snap = self.shopify.order(order_id)
        if snap is None:
            return []
        plans = {r["plan_id"]: r for r in self.store.all("SELECT * FROM selling_plans")}
        at = iso(self.clock())
        touched_lines: set[str] = set()
        touched_offers: set[str] = set()
        with self.store.tx():
            for line in snap.lines:
                plan = plans.get(line.selling_plan_id or "")
                if plan is None:
                    self._check_unplanned(snap, line)
                    continue
                offer = self.offer(plan["offer_id"])
                ov = self.store.one(
                    "SELECT * FROM offer_variants WHERE offer_id = ? AND variant_id = ?",
                    (offer["id"], line.variant_id),
                )
                batch_line_id = ov["batch_line_id"] if ov else None
                fulfilled = max(line.current_quantity - line.unfulfilled_quantity, 0)
                existing = self.store.one(
                    "SELECT * FROM preorder_lines WHERE line_item_id = ?", (line.line_item_id,)
                )
                if existing is None:
                    current_day = self.offer_dispatch(offer)
                    self.store.insert(
                        "preorder_lines",
                        {
                            "id": new_id("pol"),
                            "shop": self.shop,
                            "order_id": snap.order_id,
                            "order_name": snap.name,
                            "line_item_id": line.line_item_id,
                            "customer_name": snap.customer_name,
                            "customer_email": snap.email,
                            "product_id": line.product_id,
                            "variant_id": line.variant_id,
                            "sku": line.sku,
                            "title": line.title,
                            "selling_plan_id": line.selling_plan_id,
                            "offer_id": offer["id"],
                            "batch_id": offer["batch_id"],
                            "batch_line_id": batch_line_id,
                            "quantity": line.quantity,
                            "current_quantity": line.current_quantity,
                            "fulfilled_quantity": fulfilled,
                            "unit_price_minor": line.discounted_unit_minor,
                            "discount_minor": max(
                                line.unit_price_minor - line.discounted_unit_minor, 0
                            ),
                            "currency": line.currency,
                            "promised_dispatch_at": plan["dispatch_at"],
                            "current_dispatch_at": current_day.isoformat()
                            if current_day
                            else plan["dispatch_at"],
                            "state": LineState.AWAITING_STOCK,
                            "cancelled_at": snap.cancelled_at,
                            "ordered_at": snap.created_at,
                            "created_at": at,
                            "updated_at": at,
                        },
                    )
                    self._event(
                        "preorder_placed",
                        snap.order_id,
                        {
                            "line": line.line_item_id,
                            "units": line.current_quantity,
                            "offer": offer["id"],
                        },
                    )
                    self._convert_waitlist(snap.email, line.variant_id)
                else:
                    self.store.update(
                        "preorder_lines",
                        "id",
                        existing["id"],
                        {
                            "order_name": snap.name,
                            "customer_name": snap.customer_name,
                            "customer_email": snap.email,
                            "current_quantity": line.current_quantity,
                            "fulfilled_quantity": fulfilled,
                            "cancelled_at": snap.cancelled_at,
                            "updated_at": at,
                        },
                    )
                if batch_line_id:
                    touched_lines.add(batch_line_id)
                touched_offers.add(offer["id"])
        for lid in touched_lines:
            self.recompute_ready(lid)
        # Shopify's stock moved with this order (preorders are committed when bought): read it
        # now rather than waiting for the inventory webhook, so screens and states are current.
        for pid in {self.offer(oid)["product_id"] for oid in touched_offers}:
            self.refresh_catalog(pid)
        for oid in touched_offers:
            self.sync_offer(oid)  # the order that used the last unit closes the offer here
        return self.store.all("SELECT * FROM preorder_lines WHERE order_id = ?", (snap.order_id,))

    def _check_unplanned(self, snap: Any, line: Any) -> None:
        """A line bought without our plan for a variant we had set to sell past zero: the theme
        didn't attach the plan (or a crafted cart). Shown to staff; never guessed into a
        preorder."""
        if not line.variant_id or snap.cancelled_at:
            return
        ov = self._live_offer_variant(line.variant_id)
        if ov is None or ov["offer_status"] != OfferStatus.ACTIVE:
            return
        cat = self.store.one(
            "SELECT inventory_policy, available FROM catalog WHERE variant_id = ?",
            (line.variant_id,),
        )
        if cat and cat["inventory_policy"] == "CONTINUE" and cat["available"] <= 0:
            self.store.x(
                "INSERT OR IGNORE INTO unplanned_lines (line_item_id, shop, order_id, order_name,"
                " variant_id, quantity, seen_at) VALUES (?,?,?,?,?,?,?)",
                (
                    line.line_item_id,
                    self.shop,
                    snap.order_id,
                    snap.name,
                    line.variant_id,
                    line.current_quantity,
                    iso(self.clock()),
                ),
            )
            log.warning(
                "order %s line %s bought a preorder variant without the plan",
                snap.name,
                line.line_item_id,
            )

    def _convert_waitlist(self, email: str | None, variant_id: str | None) -> None:
        if not email or not variant_id:
            return
        self.store.x(
            "UPDATE waitlist SET status = 'CONVERTED', converted_at = ? WHERE shop = ? AND "
            "variant_id = ? AND email = ? AND status IN ('ACTIVE', 'NOTIFIED')",
            (iso(self.clock()), self.shop, variant_id, email.strip().lower()),
        )

    def recompute_ready(self, batch_line_id: str) -> None:
        """Which preorders the stock received for this batch line covers, oldest first."""
        bl = self._line_row(batch_line_id)
        with self.store.tx():
            lines = self.store.all(
                "SELECT * FROM preorder_lines WHERE batch_line_id = ?", (batch_line_id,)
            )
            fulfilled = sum(x["fulfilled_quantity"] for x in lines if not x["cancelled_at"])
            open_ = [
                domain.OpenLine(
                    x["id"],
                    datetime.fromisoformat(x["ordered_at"]),
                    x["current_quantity"] - x["fulfilled_quantity"],
                )
                for x in lines
                if not x["cancelled_at"]
            ]
            ready = domain.ready_units(open_, bl["received_quantity"] - fulfilled)
            for x in lines:
                units_open = (
                    0 if x["cancelled_at"] else x["current_quantity"] - x["fulfilled_quantity"]
                )
                state = domain.line_state(
                    cancelled=bool(x["cancelled_at"]),
                    units_open=units_open,
                    fulfilled=x["fulfilled_quantity"],
                    ready=ready.get(x["id"], 0),
                )
                if state != x["state"] or ready.get(x["id"], 0) != x["ready_quantity"]:
                    self.store.update(
                        "preorder_lines",
                        "id",
                        x["id"],
                        {
                            "state": state,
                            "ready_quantity": ready.get(x["id"], 0),
                            "updated_at": iso(self.clock()),
                        },
                    )
                    if state == LineState.READY:
                        self._event("preorder_ready", x["order_id"], {"line": x["line_item_id"]})

    # ================================================================== dates

    def affected(self, batch_id: str) -> dict[str, int]:
        """Unfulfilled preorder units, lines, orders and customers waiting on a batch."""
        row = (
            self.store.one(
                "SELECT COALESCE(SUM(current_quantity - fulfilled_quantity), 0) AS units, "
                "COUNT(*) AS lines, COUNT(DISTINCT order_id) AS orders, "
                "COUNT(DISTINCT COALESCE(customer_email, order_id)) AS customers FROM "
                "preorder_lines "
                "WHERE batch_id = ? AND cancelled_at IS NULL AND state IN ('AWAITING_STOCK', "
                "'READY')",
                (batch_id,),
            )
            or {}
        )
        return {k: int(row.get(k) or 0) for k in ("units", "lines", "orders", "customers")}

    def change_dispatch(
        self,
        batch_id: str,
        *,
        expected_dispatch_at: str,
        expected_arrival_at: str | None = None,
        delayed: bool = False,
        actor: str,
    ) -> dict[str, Any]:
        """Move the batch's dates. Open preorder lines get the new current date; the date each
        customer was promised is kept as it was. Customers are only emailed by `notify_delay`,
        which the merchant chooses (Save & notify)."""
        b = self._batch_row(batch_id)
        if b["status"] not in OPEN_BATCH:
            raise ActionError("This batch is closed.")
        new = parse_day(expected_dispatch_at)
        if new is None:
            raise ActionError("Give the new expected dispatch date.", 422)
        arrival = (
            parse_day(expected_arrival_at)
            if expected_arrival_at
            else parse_day(b["expected_arrival_at"])
        )
        if arrival and new < arrival:
            raise ActionError("Dispatch can't be before the stock arrives.", 422)
        old = b["expected_dispatch_at"]
        status = "DELAYED" if delayed else b["status"]
        with self.store.tx():
            self.store.update(
                "batches",
                "id",
                batch_id,
                {
                    "expected_dispatch_at": new.isoformat(),
                    "expected_arrival_at": arrival.isoformat() if arrival else None,
                    "status": status,
                    "updated_at": iso(self.clock()),
                },
            )
            self.store.x(
                "UPDATE preorder_lines SET current_dispatch_at = ?, updated_at = ? WHERE "
                "batch_id = ? AND cancelled_at IS NULL AND state IN ('AWAITING_STOCK', 'READY') "
                "AND offer_id IN (SELECT id FROM offers WHERE batch_id = ? AND dispatch_at IS "
                "NULL)",
                (new.isoformat(), iso(self.clock()), batch_id, batch_id),
            )
            self._event(
                "dispatch_changed",
                batch_id,
                {"from": old, "to": new.isoformat(), "delayed": delayed},
                actor,
            )
        self.sync_offers_for_batch(batch_id)
        return {"batch": self.batch(batch_id), "previous": old}

    # ================================================================== receiving stock

    def receive(self, batch_line_id: str, quantity: int, key: str, actor: str) -> dict[str, Any]:
        """Record stock that physically arrived and add it to Shopify's available quantity.

        Written down before Shopify is asked, with an idempotency key Shopify honours: a retry
        (lost reply, double click) can never add the stock twice. A partial receipt leaves the
        rest outstanding."""
        if quantity <= 0:
            raise ActionError("Receive at least one.", 422)
        if not 8 <= len(key) <= 80:
            raise ActionError("Missing request key.", 422)
        with self.store.tx():
            existing = self.store.one("SELECT * FROM receipts WHERE idempotency_key = ?", (key,))
            line = self._line_row(batch_line_id)
            b = self._batch_row(line["batch_id"])
            if existing is not None:
                if existing["batch_line_id"] != batch_line_id or existing["quantity"] != quantity:
                    raise ActionError("That request key was used for a different receipt.")
                if existing["status"] == "APPLIED":
                    return {"receipt": existing, "replayed": True, "batch": self.batch(b["id"])}
                receipt = existing  # PENDING or UNKNOWN: send again with the same key
            else:
                pending = int(
                    self.store.value(
                        "SELECT COALESCE(SUM(quantity), 0) FROM receipts WHERE batch_line_id = "
                        "? AND "
                        "status IN ('PENDING', 'UNKNOWN')",
                        (batch_line_id,),
                    )
                    or 0
                )
                if pending:
                    raise ActionError(
                        "A receipt for this size hasn't been confirmed by Shopify "
                        "yet: retry that one first."
                    )
                outstanding = line["expected_quantity"] - line["received_quantity"]
                if quantity > outstanding:
                    raise ActionError(f"Only {outstanding} are still expected for this size.", 422)
                if b["status"] in ("RECEIVED", "CANCELLED"):
                    raise ActionError("This batch is closed.")
                receipt = {
                    "id": new_id("rcp"),
                    "batch_line_id": batch_line_id,
                    "quantity": quantity,
                    "idempotency_key": key,
                    "location_id": None,
                    "status": "PENDING",
                    "actor": actor,
                    "created_at": iso(self.clock()),
                }
                self.store.insert("receipts", receipt)
        if not line["inventory_item_id"]:
            raise ActionError("This variant has no inventory item in Shopify.")
        location = self.location_id()
        self.store.update("receipts", "id", receipt["id"], {"location_id": location})
        try:
            self.shopify.adjust_available(
                line["inventory_item_id"],
                location,
                quantity,
                key,
                f"crooks://preorders/batches/{b['id']}",
            )
        except ShopifyRefused as exc:
            self.store.update(
                "receipts", "id", receipt["id"], {"status": "FAILED", "error": str(exc)[:300]}
            )
            log.warning("receipt %s refused by Shopify: %s", receipt["id"], exc)
            raise ActionError(f"Shopify refused the stock change: {exc}", 409) from exc
        except ShopifyError as exc:
            self.store.update(
                "receipts", "id", receipt["id"], {"status": "UNKNOWN", "error": str(exc)[:300]}
            )
            log.warning("receipt %s outcome unknown: %s", receipt["id"], exc)
            raise ActionError(
                "Shopify didn't confirm the stock change. Press Receive again: the "
                "same request can't add the stock twice.",
                503,
                "unknown",
            ) from exc
        with self.store.tx():
            self.store.update(
                "receipts",
                "id",
                receipt["id"],
                {"status": "APPLIED", "applied_at": iso(self.clock()), "error": None},
            )
            self.store.x(
                "UPDATE batch_lines SET received_quantity = received_quantity + ?, "
                "updated_at = ? WHERE id = ?",
                (quantity, iso(self.clock()), batch_line_id),
            )
            lines = self.store.all("SELECT * FROM batch_lines WHERE batch_id = ?", (b["id"],))
            full = all(x["received_quantity"] >= x["expected_quantity"] for x in lines)
            status = "RECEIVED" if full else "PARTIALLY_RECEIVED"
            self.store.update(
                "batches", "id", b["id"], {"status": status, "updated_at": iso(self.clock())}
            )
            if full:
                self.store.x(
                    "UPDATE offers SET status = 'CLOSED', updated_at = ? WHERE "
                    "batch_id = ? AND status = 'ACTIVE'",
                    (iso(self.clock()), b["id"]),
                )
            self._event(
                "stock_received",
                b["id"],
                {"line": batch_line_id, "units": quantity, "receipt": receipt["id"]},
                actor,
            )
        self.recompute_ready(batch_line_id)
        try:
            self.refresh_catalog(line["product_id"])
        except ShopifyError as exc:
            log.warning("catalogue refresh after receipt failed: %s", exc)
        self.sync_offers_for_batch(b["id"])
        return {
            "receipt": {**receipt, "status": "APPLIED"},
            "replayed": False,
            "batch": self.batch(b["id"]),
        }

    def release_preview(self, batch_id: str) -> dict[str, Any]:
        rows = self.store.all(
            "SELECT DISTINCT order_id, order_name FROM preorder_lines WHERE batch_id = ? AND "
            "state = 'READY' AND released_at IS NULL",
            (batch_id,),
        )
        return {"orders": len(rows), "names": [r["order_name"] for r in rows][:20]}

    def release_ready(self, batch_id: str, actor: str) -> dict[str, Any]:
        """Open the scheduled fulfilment orders of preorders the received stock covers, so they
        can ship before the promised date. Explicit; Shopify still owns fulfilment. Each order
        is re-read first, so a repeat after a lost reply sees what Shopify actually did, and a
        fulfilment order someone already opened is counted, not opened twice. A line is marked
        released only once its fulfilment order is known to be open."""
        opened: list[str] = []
        already: list[str] = []
        skipped: list[dict[str, str]] = []
        for r in self.store.all(
            "SELECT DISTINCT order_id FROM preorder_lines WHERE batch_id = ? AND state = 'READY' "
            "AND released_at IS NULL",
            (batch_id,),
        ):
            snap = self.shopify.order(r["order_id"])
            if snap is None:
                continue
            ready = {
                x["line_item_id"]
                for x in self.store.all(
                    "SELECT line_item_id FROM preorder_lines WHERE order_id = ? AND state = "
                    "'READY' AND released_at IS NULL",
                    (r["order_id"],),
                )
            }
            for fo in snap.fulfillment_orders:
                lines = set(fo.line_item_ids) & ready
                if not lines:
                    continue
                if fo.status == "SCHEDULED":
                    if not set(fo.line_item_ids) <= ready:
                        continue  # it also holds lines still waiting for stock
                    try:
                        self.shopify.open_fulfillment_order(fo.id)
                    except ShopifyRefused as exc:
                        skipped.append({"order": snap.name, "why": str(exc)})
                        continue
                    opened.append(snap.name)
                else:
                    already.append(snap.name)
                self._mark_released(lines)
        if opened or already or skipped:
            self._event(
                "preorders_released",
                batch_id,
                {"orders": opened, "already_open": already, "skipped": skipped},
                actor,
            )
        return {"opened": opened, "already_open": already, "skipped": skipped}

    def _mark_released(self, line_item_ids: set[str]) -> None:
        at = iso(self.clock())
        with self.store.tx():
            for lid in line_item_ids:
                self.store.x(
                    "UPDATE preorder_lines SET released_at = ?, updated_at = ? "
                    "WHERE line_item_id = ? AND released_at IS NULL",
                    (at, at, lid),
                )

    # ================================================================== for the rest of CLIVE

    def classify_line(self, line_item_id: str) -> dict[str, Any]:
        """The stable answer for CLIVE Shipping: can this line be dispatched now?"""
        row = self.store.one("SELECT * FROM preorder_lines WHERE line_item_id = ?", (line_item_id,))
        state = LineState(row["state"]) if row else None
        out: dict[str, Any] = {
            "line_item_id": line_item_id,
            "classification": domain.classify(state).value,
            "preorder": row is not None,
        }
        if row:
            batch = self._batch_row(row["batch_id"]) if row["batch_id"] else None
            out.update(
                {
                    "order_id": row["order_id"],
                    "order_name": row["order_name"],
                    "expected_dispatch_at": row["current_dispatch_at"],
                    "promised_dispatch_at": row["promised_dispatch_at"],
                    "selling_plan_id": row["selling_plan_id"],
                    "preorder_offer": row["offer_id"],
                    "inbound_batch": {
                        "id": batch["id"],
                        "reference": batch["reference"],
                        "status": batch["status"],
                    }
                    if batch
                    else None,
                    "quantity": row["current_quantity"],
                    "ready_quantity": row["ready_quantity"],
                    "fulfilled_quantity": row["fulfilled_quantity"],
                    "state": row["state"],
                }
            )
        return out

    def classify_order(self, order_id: str) -> dict[str, Any]:
        """Every line of an order, as CLIVE Shipping should treat it. Reads the order from
        Shopify; a line on one of our plans that hasn't been ingested yet is ingested first, so
        a preorder is never called in stock. Lines on no plan of ours are ordinary."""
        snap = self.shopify.order(order_id)
        if snap is None:
            raise ActionError("Order not found in Shopify.", 404, "not_found")
        ours = {r["plan_id"] for r in self.store.all("SELECT plan_id FROM selling_plans")}
        known = {
            r["line_item_id"]
            for r in self.store.all(
                "SELECT line_item_id FROM preorder_lines WHERE order_id = ?", (snap.order_id,)
            )
        }
        if any(x.selling_plan_id in ours and x.line_item_id not in known for x in snap.lines):
            self.ingest_order(snap.order_id)  # its webhook hasn't been processed yet
        return {
            "order_id": snap.order_id,
            "order_name": snap.name,
            "lines": [
                {**self.classify_line(x.line_item_id), "title": x.title, "variant_id": x.variant_id}
                for x in snap.lines
            ],
        }

    # ================================================================== screens

    def overview(self) -> dict[str, Any]:
        today = self.today().isoformat()
        soon = (self.today() + timedelta(days=7)).isoformat()
        open_lines = (
            "FROM preorder_lines WHERE shop = ? AND cancelled_at IS NULL AND state IN "
            "('AWAITING_STOCK', 'READY')"
        )
        units = int(
            self.store.value(
                f"SELECT COALESCE(SUM(current_quantity - fulfilled_quantity), 0) {open_lines}",
                (self.shop,),
            )
            or 0
        )
        revenue = int(
            self.store.value(
                f"SELECT COALESCE(SUM((current_quantity - fulfilled_quantity) * "
                f"unit_price_minor), 0)"
                f" {open_lines}",
                (self.shop,),
            )
            or 0
        )
        due = int(
            self.store.value(
                f"SELECT COALESCE(SUM(current_quantity - fulfilled_quantity)"
                f", 0) {open_lines} AND current_dispatch_at <= ?",
                (self.shop, soon),
            )
            or 0
        )
        late = (
            self.store.one(
                f"SELECT COUNT(DISTINCT order_id) AS orders, COALESCE(SUM(current_quantity - "
                f"fulfilled_quantity), 0) AS units {open_lines} AND current_dispatch_at < ?",
                (self.shop, today),
            )
            or {}
        )
        delayed_units = int(
            self.store.value(
                f"SELECT COALESCE(SUM(current_quantity - fulfilled_quantity), 0) {open_lines} AND "
                f"(current_dispatch_at > promised_dispatch_at OR batch_id IN (SELECT id FROM "
                f"batches "
                f"WHERE status = 'DELAYED'))",
                (self.shop,),
            )
            or 0
        )
        products = int(
            self.store.value(
                "SELECT COUNT(DISTINCT product_id) FROM offers WHERE shop = ? AND status = "
                "'ACTIVE'",
                (self.shop,),
            )
            or 0
        )
        batches = [x for x in self.batches() if x["status"] in OPEN_BATCH]
        inbound = sum(x["totals"]["expected"] - x["totals"]["received"] for x in batches)
        waiting = int(
            self.store.value(
                "SELECT COUNT(*) FROM waitlist WHERE shop = ? AND status = 'ACTIVE'", (self.shop,)
            )
            or 0
        )
        attention = []
        delayed = [x for x in batches if x["status"] == BatchStatus.DELAYED]
        if delayed:
            attention.append(
                {
                    "kind": "delayed",
                    "count": len(delayed),
                    "text": f"{len(delayed)} batch{'es' if len(delayed) > 1 else ''} delayed",
                }
            )
        if late.get("orders"):
            attention.append(
                {
                    "kind": "late",
                    "count": late["orders"],
                    "text": f"{late['orders']} orders now past their expected dispatch date",
                }
            )
        sold_out = [
            ln
            for x in batches
            for ln in x["lines"]
            if ln["preorder_allocation"] and ln["remaining"] == 0
        ]
        if sold_out:
            have = "variants have" if len(sold_out) > 1 else "variant has"
            attention.append(
                {
                    "kind": "sold_through",
                    "count": len(sold_out),
                    "text": f"{len(sold_out)} {have} sold through the full preorder allocation",
                }
            )
        oversold = [ln for x in batches for ln in x["lines"] if ln["oversold"]]
        if oversold:
            attention.append(
                {
                    "kind": "oversold",
                    "count": len(oversold),
                    "text": f"{sum(x['oversold'] for x in oversold)} units preordered "
                    "beyond the allocation (checkouts at the same moment)",
                }
            )
        unplanned = int(
            self.store.value(
                "SELECT COUNT(*) FROM unplanned_lines WHERE shop = ? AND resolved_at IS NULL",
                (self.shop,),
            )
            or 0
        )
        if unplanned:
            attention.append(
                {
                    "kind": "unplanned",
                    "count": unplanned,
                    "text": f"{unplanned} order lines bought a preorder size without "
                    "the preorder plan",
                }
            )
        failing = self.store.all(
            "SELECT id, product_title, sync_error FROM offers WHERE shop = ? "
            "AND status = 'ACTIVE' AND sync_error IS NOT NULL",
            (self.shop,),
        )
        if failing:
            attention.append(
                {
                    "kind": "sync",
                    "count": len(failing),
                    "text": f"{len(failing)} preorders aren't in step with Shopify: "
                    f"{failing[0]['sync_error']}",
                }
            )
        unknown = int(
            self.store.value("SELECT COUNT(*) FROM receipts WHERE status = 'UNKNOWN'") or 0
        )
        if unknown:
            attention.append(
                {
                    "kind": "receipt",
                    "count": unknown,
                    "text": f"{unknown} stock receipts not confirmed by Shopify",
                }
            )
        return {
            "revenue_minor": revenue,
            "units": units,
            "inbound_units": inbound,
            "waitlist": waiting,
            "products": products,
            "due_7_days": due,
            "delayed_units": delayed_units,
            "attention": attention,
            "batches": [
                {
                    k: x[k]
                    for k in (
                        "id",
                        "reference",
                        "status",
                        "expected_arrival_at",
                        "expected_dispatch_at",
                        "totals",
                    )
                }
                for x in batches
            ][:6],
            "plans_available": self.plans.available,
            "plans_reason": self.plans.reason,
        }

    def products(self, view: str = "all", q: str = "") -> list[dict[str, Any]]:
        """Every catalogue variant with its preorder position, for the Products index."""
        args: list[Any] = [self.shop]
        where = "c.shop = ?"
        if q:
            where += " AND (c.product_title LIKE ? OR c.sku LIKE ? OR c.variant_title LIKE ?)"
            args += [f"%{q}%"] * 3
        rows = self.store.all(
            f"SELECT c.* FROM catalog c WHERE {where} ORDER BY c.product_title, c.position", args
        )
        waits = {
            r["variant_id"]: r["n"]
            for r in self.store.all(
                "SELECT variant_id, COUNT(*) AS n FROM waitlist WHERE shop = ? AND status = "
                "'ACTIVE' "
                "GROUP BY variant_id",
                (self.shop,),
            )
        }
        inbound = {
            r["variant_id"]: r["n"]
            for r in self.store.all(
                "SELECT bl.variant_id, SUM(bl.expected_quantity - bl.received_quantity) AS n FROM "
                "batch_lines bl JOIN batches b ON b.id = bl.batch_id WHERE b.status IN ('PLANNED', "
                "'ORDERED', 'IN_TRANSIT', 'DELAYED', 'PARTIALLY_RECEIVED') GROUP BY bl.variant_id"
            )
        }
        out = []
        for c in rows:
            ov = self._live_offer_variant(c["variant_id"])
            state = self.state_of(c["variant_id"])
            allocation = ov["preorder_allocation"] if ov else 0
            sold = self.sold_for_line(ov["batch_line_id"]) if ov else 0
            offer = self.offer(ov["offer_id"]) if ov else None
            day = self.offer_dispatch(offer) if offer else None
            label, tone = domain.badge(
                state,
                had_offer=bool(ov and ov["offer_status"] == "ACTIVE"),
                capacity_left=domain.remaining(allocation, sold),
                delayed=bool(ov and ov["batch_status"] == "DELAYED"),
            )
            row = {
                "variant_id": c["variant_id"],
                "product_id": c["product_id"],
                "product": c["product_title"],
                "variant": c["variant_title"],
                "sku": c["sku"],
                "image_url": c["image_url"],
                "state": state.value,
                "badge": label,
                "tone": tone,
                "available": c["available"],
                "committed": c["committed"],
                "shopify_incoming": c["incoming"],
                "on_hand": c["on_hand"],
                "inbound": int(inbound.get(c["variant_id"], 0)),
                "allocation": allocation,
                "preordered": sold,
                "remaining": domain.remaining(allocation, sold),
                "dispatch": day.isoformat() if day else None,
                "discount": (
                    f"{offer['discount_value']:g}%"
                    if offer and offer["discount_type"] == "PERCENTAGE"
                    else ""
                ),
                "offer_id": offer["id"] if offer else None,
                "offer_status": offer["status"] if offer else None,
                "waitlist": int(waits.get(c["variant_id"], 0)),
            }
            if view == "in_stock" and state != CommerceState.IN_STOCK:
                continue
            if view == "preorder" and state != CommerceState.PREORDER:
                continue
            if view == "waitlist" and label != "Waitlist":
                continue
            if view == "sold_out" and label != "Sold out":
                continue
            out.append(row)
        return out

    def preorder_lines(self, view: str = "all", q: str = "") -> list[dict[str, Any]]:
        where, args = ["p.shop = ?"], [self.shop]
        today = self.today().isoformat()
        if view == "awaiting":
            where.append("p.state = 'AWAITING_STOCK'")
        elif view == "ready":
            where.append("p.state = 'READY'")
        elif view == "delayed":
            where.append(
                "p.state IN ('AWAITING_STOCK', 'READY') AND (p.current_dispatch_at > "
                "p.promised_dispatch_at OR p.current_dispatch_at < ? OR b.status = "
                "'DELAYED')"
            )
            args.append(today)
        elif view == "fulfilled":
            where.append("p.state = 'FULFILLED'")
        elif view == "cancelled":
            where.append("p.state = 'CANCELLED'")
        if q:
            where.append(
                "(p.order_name LIKE ? OR p.customer_name LIKE ? OR p.title LIKE ? OR p.sku LIKE ?)"
            )
            args += [f"%{q}%"] * 4
        rows = self.store.all(
            "SELECT p.*, b.reference AS batch_reference, b.status AS batch_status FROM "
            "preorder_lines p LEFT JOIN batches b ON b.id = p.batch_id WHERE "
            + " AND ".join(where)
            + " ORDER BY p.ordered_at DESC LIMIT 500",
            args,
        )
        for r in rows:
            r["late"] = bool(
                r["state"] in ("AWAITING_STOCK", "READY")
                and r["current_dispatch_at"]
                and r["current_dispatch_at"] < today
            )
            r["moved"] = bool(
                r["promised_dispatch_at"]
                and r["current_dispatch_at"]
                and r["current_dispatch_at"] != r["promised_dispatch_at"]
            )
        return rows
