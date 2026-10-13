"""An in-memory Shopify for the tests and the dev server: the same port as GraphQLShopify, with
Shopify's rules that matter here.

- A checkout line on a selling plan that reserves ON_SALE commits its units at once (available
  goes down, committed up); a variant set to DENY refuses a line it hasn't stock for.
- inventoryAdjustQuantities with an idempotency key applies once, whatever the retries.
- `fail_next(method, "unknown" | "refused")` makes the next call fail as Shopify can.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from preorders.shopify import (
    FulfillmentOrderSnap,
    OrderLineSnap,
    OrderSnap,
    PlanSpec,
    ShopifyError,
    ShopifyRefused,
    VariantSnap,
)

_ids = itertools.count(1000)


def gid(kind: str) -> str:
    return f"gid://shopify/{kind}/{next(_ids)}"


@dataclass
class FakePlan:
    id: str
    spec: PlanSpec


@dataclass
class FakeGroup:
    id: str
    name: str
    plans: list[FakePlan]
    variants: set[str] = field(default_factory=set)


class FakeShopify:
    def __init__(self) -> None:
        self.variants_by_id: dict[str, VariantSnap] = {}
        self.groups: dict[str, FakeGroup] = {}
        self.orders: dict[str, OrderSnap] = {}
        self.metafields: dict[str, str] = {}
        self.adjustments: dict[str, int] = {}  # idempotency key -> delta applied
        self.location = {
            "id": "gid://shopify/Location/1",
            "name": "Studio",
            "isActive": True,
            "fulfillsOnlineOrders": True,
        }
        self.calls: list[str] = []
        self._fail: dict[str, str] = {}
        self.access_denied = False

    # --- test helpers

    def add_product(self, title: str, sizes: dict[str, int], price_minor: int = 4000) -> str:
        product_id = gid("Product")
        for pos, (size, available) in enumerate(sizes.items(), start=1):
            vid = gid("ProductVariant")
            self.variants_by_id[vid] = VariantSnap(
                variant_id=vid,
                product_id=product_id,
                product_title=title,
                variant_title=size,
                sku=f"{title[:3].upper()}-{size}",
                inventory_item_id=gid("InventoryItem"),
                inventory_policy="DENY",
                tracked=True,
                available=available,
                committed=0,
                incoming=0,
                on_hand=available,
                price_minor=price_minor,
                position=pos,
                handle=title.lower().replace(" ", "-"),
            )
        return product_id

    def variant(self, product_id: str, size: str) -> VariantSnap:
        return next(
            v
            for v in self.variants_by_id.values()
            if v.product_id == product_id and v.variant_title == size
        )

    def fail_next(self, method: str, kind: str = "unknown") -> None:
        self._fail[method] = kind

    def _maybe_fail(self, method: str) -> None:
        self.calls.append(method)
        if self.access_denied and method in ("create_plan_group", "replace_plan", "add_to_group"):
            raise ShopifyRefused(
                "Access denied for sellingPlanGroupCreate field.", ["ACCESS_DENIED"]
            )
        kind = self._fail.pop(method, None)
        if kind == "unknown":
            raise ShopifyError("Shopify answered 502; it may have been done.")
        if kind == "refused":
            raise ShopifyRefused("Shopify refused it.", ["INVALID"])

    def plan_of(self, variant_id: str) -> str | None:
        for g in self.groups.values():
            if variant_id in g.variants and g.plans:
                return g.plans[-1].id
        return None

    def checkout(
        self,
        lines: list[tuple[str, int, str | None]],
        *,
        email: str = "ann@example.com",
        name: str = "Ann Example",
        at: datetime | None = None,
    ) -> str:
        """Place an order as Shopify checkout would: (variant, quantity, selling plan id)."""
        for vid, qty, plan in lines:
            v = self.variants_by_id[vid]
            if plan is not None:
                if not any(
                    vid in g.variants and any(p.id == plan for p in g.plans)
                    for g in self.groups.values()
                ):
                    raise ValueError("That selling plan isn't offered for this variant.")
            if v.inventory_policy == "DENY" and v.available < qty:
                raise ValueError(f"{v.product_title} {v.variant_title} is sold out.")
        order_id = gid("Order")
        snaps = []
        for vid, qty, plan in lines:
            v = self.variants_by_id[vid]
            v.available -= qty
            v.committed += qty
            spec = next(
                (p.spec for g in self.groups.values() for p in g.plans if p.id == plan), None
            )
            disc = round(v.price_minor * (1 - (spec.discount_percent if spec else 0) / 100))
            snaps.append(
                OrderLineSnap(
                    line_item_id=gid("LineItem"),
                    variant_id=vid,
                    product_id=v.product_id,
                    sku=v.sku,
                    title=f"{v.product_title} · {v.variant_title}",
                    quantity=qty,
                    current_quantity=qty,
                    unfulfilled_quantity=qty,
                    selling_plan_id=plan,
                    selling_plan_name=spec.plan_name if spec else None,
                    unit_price_minor=v.price_minor,
                    discounted_unit_minor=disc,
                    currency="GBP",
                )
            )
        fos = [
            FulfillmentOrderSnap(
                id=gid("FulfillmentOrder"),
                status="OPEN",
                fulfill_at=None,
                line_item_ids=[s.line_item_id for s in snaps if not s.selling_plan_id],
            )
        ]
        planned = [s.line_item_id for s in snaps if s.selling_plan_id]
        if planned:
            fos.append(
                FulfillmentOrderSnap(
                    id=gid("FulfillmentOrder"),
                    status="SCHEDULED",
                    fulfill_at=None,
                    line_item_ids=planned,
                )
            )
        self.orders[order_id] = OrderSnap(
            order_id=order_id,
            name=f"#{1000 + len(self.orders) + 1}",
            created_at=(at or datetime.now(UTC)).isoformat(),
            cancelled_at=None,
            email=email,
            customer_name=name,
            currency="GBP",
            lines=snaps,
            fulfillment_orders=[f for f in fos if f.line_item_ids],
        )
        return order_id

    def cancel(self, order_id: str) -> None:
        o = self.orders[order_id]
        o.cancelled_at = datetime.now(UTC).isoformat()
        for line in o.lines:
            v = self.variants_by_id[line.variant_id or ""]
            v.available += line.current_quantity
            v.committed -= line.current_quantity
            line.current_quantity = 0
            line.unfulfilled_quantity = 0

    def refund(self, order_id: str, line_item_id: str, qty: int) -> None:
        line = next(x for x in self.orders[order_id].lines if x.line_item_id == line_item_id)
        line.current_quantity -= qty
        line.unfulfilled_quantity = max(line.unfulfilled_quantity - qty, 0)
        v = self.variants_by_id[line.variant_id or ""]
        v.available += qty
        v.committed -= qty

    def fulfil(self, order_id: str, line_item_id: str) -> None:
        line = next(x for x in self.orders[order_id].lines if x.line_item_id == line_item_id)
        v = self.variants_by_id[line.variant_id or ""]
        v.committed -= line.unfulfilled_quantity
        v.on_hand -= line.unfulfilled_quantity
        line.unfulfilled_quantity = 0

    # --- the port

    def variants(self, query: str | None = None) -> list[VariantSnap]:
        self._maybe_fail("variants")
        found = list(self.variants_by_id.values())
        if query and query.startswith("product_id:"):
            pid = query.split(":", 1)[1]
            found = [v for v in found if v.product_id.endswith(f"/{pid}")]
        return [VariantSnap(**v.__dict__) for v in found]

    def locations(self) -> list[dict[str, Any]]:
        self._maybe_fail("locations")
        return [dict(self.location)]

    def create_plan_group(self, spec: PlanSpec, variant_ids: list[str]) -> tuple[str, str]:
        self._maybe_fail("create_plan_group")
        g = FakeGroup(
            id=gid("SellingPlanGroup"),
            name=spec.group_name,
            plans=[FakePlan(gid("SellingPlan"), spec)],
            variants=set(variant_ids),
        )
        self.groups[g.id] = g
        return g.id, g.plans[0].id

    def replace_plan(self, group_id: str, old_plan_id: str | None, spec: PlanSpec) -> str:
        self._maybe_fail("replace_plan")
        g = self.groups[group_id]
        g.plans = [p for p in g.plans if p.id != old_plan_id] + [FakePlan(gid("SellingPlan"), spec)]
        return g.plans[-1].id

    def group_variants(self, group_id: str) -> set[str] | None:
        self._maybe_fail("group_variants")
        g = self.groups.get(group_id)
        return set(g.variants) if g else None

    def add_to_group(self, group_id: str, variant_ids: list[str]) -> None:
        self._maybe_fail("add_to_group")
        self.groups[group_id].variants |= set(variant_ids)

    def remove_from_group(self, group_id: str, variant_ids: list[str]) -> None:
        self._maybe_fail("remove_from_group")
        self.groups[group_id].variants -= set(variant_ids)

    def set_inventory_policy(self, product_id: str, policies: dict[str, str]) -> None:
        self._maybe_fail("set_inventory_policy")
        for vid, policy in policies.items():
            self.variants_by_id[vid].inventory_policy = policy

    def set_variant_metafields(self, values: dict[str, str]) -> None:
        self._maybe_fail("set_variant_metafields")
        self.metafields.update(values)

    def adjust_available(
        self, inventory_item_id: str, location_id: str, delta: int, key: str, reference: str
    ) -> str:
        self._maybe_fail("adjust_available")
        if key not in self.adjustments:  # @idempotent: a retry with the same key applies once
            v = next(
                x for x in self.variants_by_id.values() if x.inventory_item_id == inventory_item_id
            )
            v.available += delta
            v.on_hand += delta
            self.adjustments[key] = delta
        return f"gid://shopify/InventoryAdjustmentGroup/{abs(hash(key)) % 10**8}"

    def order(self, order_id: str) -> OrderSnap | None:
        self._maybe_fail("order")
        o = self.orders.get(order_id)
        if o is None:
            return None
        return OrderSnap(
            **{
                **o.__dict__,
                "lines": [OrderLineSnap(**x.__dict__) for x in o.lines],
                "fulfillment_orders": [
                    FulfillmentOrderSnap(**{**f.__dict__, "line_item_ids": list(f.line_item_ids)})
                    for f in o.fulfillment_orders
                ],
            }
        )

    def orders_with_plans(self, since_iso: str, plan_ids: set[str]) -> list[str]:
        self._maybe_fail("orders_with_plans")
        return [
            o.order_id
            for o in self.orders.values()
            if o.created_at >= since_iso and {x.selling_plan_id for x in o.lines} & plan_ids
        ]

    def open_fulfillment_order(self, fo_id: str) -> str:
        self._maybe_fail("open_fulfillment_order")
        for o in self.orders.values():
            for f in o.fulfillment_orders:
                if f.id == fo_id:
                    if f.status != "SCHEDULED":
                        raise ShopifyRefused("The fulfillment order isn't scheduled.")
                    f.status = "OPEN"
                    return f.status
        raise ShopifyRefused("Not found.")
