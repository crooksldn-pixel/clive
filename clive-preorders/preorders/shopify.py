"""Shopify Admin GraphQL 2026-10: everything CLIVE Preorders reads from or writes to Shopify.

Every document below is validated against the 2026-10 schema (scripts/validate_graphql.py).
Mutations are never re-sent after a 5xx or a lost reply: the caller reads Shopify back.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

log = logging.getLogger("preorders.shopify")

API_VERSION = "2026-10"
APP_GROUP_ID = "clive-preorders"  # SellingPlanGroup.appId: how Liquid tells our plans apart
METAFIELD_NAMESPACE = "$app"
METAFIELD_KEY = "preorder"


class ShopifyError(Exception):
    """No clear answer (unreachable, 5xx, throttled, unreadable): it may or may not be done."""


class ShopifyRefused(ShopifyError):
    """A definite answer: Shopify refused it (userErrors). Nothing was changed."""

    def __init__(self, message: str, codes: list[str] | None = None) -> None:
        super().__init__(message)
        self.codes = codes or []


# ------------------------------------------------------------------ documents

Q_VARIANTS = """
query PreorderVariants($first: Int!, $after: String, $query: String) {
  productVariants(first: $first, after: $after, query: $query) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id title sku position inventoryPolicy
      price
      product { id title handle featuredMedia { preview { image { url } } } }
      inventoryItem {
        id tracked
        inventoryLevels(first: 10) {
          nodes { location { id } quantities(names: ["available", "committed", "incoming", "on_hand"]) { name quantity } }
        }
      }
    }
  }
}
"""

Q_LOCATIONS = """
query PreorderLocations {
  locations(first: 20) { nodes { id name isActive fulfillsOnlineOrders } }
}
"""

M_GROUP_CREATE = """
mutation PreorderGroupCreate($input: SellingPlanGroupInput!, $resources: SellingPlanGroupResourceInput) {
  sellingPlanGroupCreate(input: $input, resources: $resources) {
    sellingPlanGroup { id sellingPlans(first: 5) { nodes { id } } }
    userErrors { field message code }
  }
}
"""

M_GROUP_UPDATE = """
mutation PreorderGroupUpdate($id: ID!, $input: SellingPlanGroupInput!) {
  sellingPlanGroupUpdate(id: $id, input: $input) {
    sellingPlanGroup { id sellingPlans(first: 5) { nodes { id } } }
    userErrors { field message code }
  }
}
"""

M_GROUP_ADD = """
mutation PreorderGroupAddVariants($id: ID!, $variants: [ID!]!) {
  sellingPlanGroupAddProductVariants(id: $id, productVariantIds: $variants) {
    sellingPlanGroup { id }
    userErrors { field message code }
  }
}
"""

M_GROUP_REMOVE = """
mutation PreorderGroupRemoveVariants($id: ID!, $variants: [ID!]!) {
  sellingPlanGroupRemoveProductVariants(id: $id, productVariantIds: $variants) {
    removedProductVariantIds
    userErrors { field message code }
  }
}
"""

Q_GROUP = """
query PreorderGroup($id: ID!) {
  sellingPlanGroup(id: $id) {
    id appId
    sellingPlans(first: 5) { nodes { id } }
    productVariants(first: 250) { nodes { id } }
  }
}
"""

M_VARIANTS_UPDATE = """
mutation PreorderVariantsUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id inventoryPolicy }
    userErrors { field message code }
  }
}
"""

M_METAFIELDS_SET = """
mutation PreorderMetafieldsSet($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id ownerType }
    userErrors { field message code }
  }
}
"""

M_INVENTORY_ADJUST = """
mutation PreorderReceive($input: InventoryAdjustQuantitiesInput!, $key: String!) {
  inventoryAdjustQuantities(input: $input) @idempotent(key: $key) {
    inventoryAdjustmentGroup { id }
    userErrors { field message code }
  }
}
"""

Q_ORDER = """
query PreorderOrder($id: ID!) {
  order(id: $id) {
    id name createdAt cancelledAt email currencyCode test
    customer { displayName }
    lineItems(first: 100) {
      nodes {
        id sku title variantTitle quantity currentQuantity unfulfilledQuantity
        variant { id }
        product { id }
        sellingPlan { sellingPlanId name }
        originalUnitPriceSet { shopMoney { amount currencyCode } }
        discountedUnitPriceAfterAllDiscountsSet { shopMoney { amount } }
      }
    }
    fulfillmentOrders(first: 20) {
      nodes { id status fulfillAt lineItems(first: 50) { nodes { lineItem { id } } } }
    }
  }
}
"""

Q_ORDERS_SINCE = """
query PreorderOrdersSince($first: Int!, $after: String, $query: String) {
  orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes { id lineItems(first: 100) { nodes { sellingPlan { sellingPlanId } } } }
  }
}
"""

M_FO_OPEN = """
mutation PreorderReleaseFulfillmentOrder($id: ID!) {
  fulfillmentOrderOpen(id: $id) {
    fulfillmentOrder { id status }
    userErrors { field message }
  }
}
"""

DOCUMENTS = (
    "Q_VARIANTS",
    "Q_LOCATIONS",
    "M_GROUP_CREATE",
    "M_GROUP_UPDATE",
    "M_GROUP_ADD",
    "M_GROUP_REMOVE",
    "Q_GROUP",
    "M_VARIANTS_UPDATE",
    "M_METAFIELDS_SET",
    "M_INVENTORY_ADJUST",
    "Q_ORDER",
    "Q_ORDERS_SINCE",
    "M_FO_OPEN",
)


# ------------------------------------------------------------------ what comes back


@dataclass
class VariantSnap:
    variant_id: str
    product_id: str
    product_title: str
    variant_title: str
    sku: str
    inventory_item_id: str | None
    inventory_policy: str  # DENY | CONTINUE
    tracked: bool
    available: int
    committed: int
    incoming: int
    on_hand: int
    price_minor: int
    position: int = 0
    image_url: str | None = None
    handle: str = ""


@dataclass
class OrderLineSnap:
    line_item_id: str
    variant_id: str | None
    product_id: str | None
    sku: str
    title: str
    quantity: int
    current_quantity: int
    unfulfilled_quantity: int
    selling_plan_id: str | None
    selling_plan_name: str | None
    unit_price_minor: int
    discounted_unit_minor: int
    currency: str


@dataclass
class FulfillmentOrderSnap:
    id: str
    status: str
    fulfill_at: str | None
    line_item_ids: list[str] = field(default_factory=list)


@dataclass
class OrderSnap:
    order_id: str
    name: str
    created_at: str
    cancelled_at: str | None
    email: str | None
    customer_name: str | None
    currency: str
    lines: list[OrderLineSnap]
    fulfillment_orders: list[FulfillmentOrderSnap]
    test: bool = False


@dataclass
class PlanSpec:
    """One preorder offer as a Shopify selling plan group with one plan."""

    merchant_code: str
    group_name: str
    plan_name: str
    description: str
    dispatch_at: str | None  # ISO date-time, or None (date to be confirmed)
    discount_percent: float  # 0: no discount


class ShopifyPort(Protocol):
    def variants(self, query: str | None = None) -> list[VariantSnap]: ...
    def locations(self) -> list[dict[str, Any]]: ...
    def create_plan_group(self, spec: PlanSpec, variant_ids: list[str]) -> tuple[str, str]: ...
    def replace_plan(self, group_id: str, old_plan_id: str | None, spec: PlanSpec) -> str: ...
    def group_variants(self, group_id: str) -> set[str] | None: ...
    def add_to_group(self, group_id: str, variant_ids: list[str]) -> None: ...
    def remove_from_group(self, group_id: str, variant_ids: list[str]) -> None: ...
    def set_inventory_policy(self, product_id: str, policies: dict[str, str]) -> None: ...
    def set_variant_metafields(self, values: dict[str, str]) -> None: ...
    def adjust_available(
        self, inventory_item_id: str, location_id: str, delta: int, key: str, reference: str
    ) -> str: ...
    def order(self, order_id: str) -> OrderSnap | None: ...
    def orders_with_plans(self, since_iso: str, plan_ids: set[str]) -> list[str]: ...
    def open_fulfillment_order(self, fo_id: str) -> str: ...


def _minor(amount: Any) -> int:
    try:
        return round(float(amount) * 100)
    except (TypeError, ValueError):
        return 0


def plan_input(spec: PlanSpec) -> dict[str, Any]:
    """The PRE_ORDER selling plan: 100% at checkout, no remaining balance, fulfilment fixed at the
    dispatch date, inventory reserved on sale (received stock covers preorders first), and the
    preorder discount when there is one."""
    delivery: dict[str, Any] = (
        {"fulfillmentTrigger": "EXACT_TIME", "fulfillmentExactTime": spec.dispatch_at}
        if spec.dispatch_at
        else {"fulfillmentTrigger": "UNKNOWN"}
    )
    plan: dict[str, Any] = {
        "name": spec.plan_name,
        "options": [spec.plan_name],
        "description": spec.description,
        "category": "PRE_ORDER",
        "billingPolicy": {
            "fixed": {
                "checkoutCharge": {"type": "PERCENTAGE", "value": {"percentage": 100}},
                "remainingBalanceChargeTrigger": "NO_REMAINING_BALANCE",
            }
        },
        "deliveryPolicy": {"fixed": delivery},
        "inventoryPolicy": {"reserve": "ON_SALE"},
    }
    if spec.discount_percent > 0:
        plan["pricingPolicies"] = [
            {
                "fixed": {
                    "adjustmentType": "PERCENTAGE",
                    "adjustmentValue": {"percentage": spec.discount_percent},
                }
            }
        ]
    return plan


# ------------------------------------------------------------------ the real client


class GraphQLShopify:
    def __init__(
        self,
        shop_domain: str,
        client_id: str,
        client_secret: str,
        api_version: str = API_VERSION,
        http: httpx.Client | None = None,
    ) -> None:
        self.shop = shop_domain
        self.client_id, self.client_secret = client_id, client_secret
        self.api_version = api_version
        self._http = http or httpx.Client(timeout=30)
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token[1] - 300:
                return self._token[0]
            r = self._http.post(
                f"https://{self.shop}/admin/oauth/access_token",
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
            )
            if r.status_code != 200:
                raise ShopifyError(f"Shopify refused the app credentials ({r.status_code}).")
            body = r.json()
            self._token = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
            return self._token[0]

    def _call(self, document: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        mutation = document.lstrip().startswith("mutation")
        for attempt in range(4):
            try:
                r = self._http.post(
                    f"https://{self.shop}/admin/api/{self.api_version}/graphql.json",
                    json={"query": document, "variables": variables or {}},
                    headers={"X-Shopify-Access-Token": self._access_token()},
                )
            except httpx.HTTPError as exc:
                raise ShopifyError(f"Shopify could not be reached: {exc}") from exc
            if r.status_code >= 500 and mutation:
                raise ShopifyError(f"Shopify answered {r.status_code}; it may have been done.")
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(0.5 * 2**attempt)
                continue
            if r.status_code != 200:
                raise ShopifyError(f"Shopify answered {r.status_code}.")
            try:
                body = r.json()
            except ValueError as exc:
                raise ShopifyError("Shopify sent an unreadable answer.") from exc
            errors = body.get("errors")
            if errors:
                if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors):
                    time.sleep(0.5 * 2**attempt)
                    continue
                messages = "; ".join(str(e.get("message", "error")) for e in errors)
                if any("access" in str(e.get("message", "")).lower() for e in errors):
                    raise ShopifyRefused(messages, ["ACCESS_DENIED"])
                raise ShopifyError(messages)
            return body["data"]
        raise ShopifyError("Shopify is busy; try again shortly.")

    @staticmethod
    def _payload(data: dict[str, Any], root: str) -> dict[str, Any]:
        payload = data.get(root) or {}
        errors = payload.get("userErrors") or []
        if errors:
            raise ShopifyRefused(
                "; ".join(str(e.get("message")) for e in errors),
                [str(e.get("code") or "") for e in errors],
            )
        return payload

    # --- catalogue

    def variants(self, query: str | None = None) -> list[VariantSnap]:
        out: list[VariantSnap] = []
        after = None
        while True:
            data = self._call(Q_VARIANTS, {"first": 50, "after": after, "query": query})
            conn = data["productVariants"]
            for n in conn["nodes"]:
                totals = {"available": 0, "committed": 0, "incoming": 0, "on_hand": 0}
                item = n.get("inventoryItem") or {}
                for level in (item.get("inventoryLevels") or {}).get("nodes") or []:
                    for q in level.get("quantities") or []:
                        if q.get("name") in totals:
                            totals[q["name"]] += int(q.get("quantity") or 0)
                product = n.get("product") or {}
                featured = (
                    ((product.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}
                ).get("url")
                out.append(
                    VariantSnap(
                        variant_id=n["id"],
                        product_id=product.get("id", ""),
                        product_title=product.get("title", ""),
                        variant_title=n.get("title") or "",
                        sku=n.get("sku") or "",
                        inventory_item_id=item.get("id"),
                        inventory_policy=n.get("inventoryPolicy") or "DENY",
                        tracked=bool(item.get("tracked", True)),
                        price_minor=_minor(n.get("price")),
                        position=int(n.get("position") or 0),
                        image_url=featured,
                        handle=product.get("handle") or "",
                        **totals,
                    )
                )
            if not conn["pageInfo"]["hasNextPage"]:
                return out
            after = conn["pageInfo"]["endCursor"]

    def locations(self) -> list[dict[str, Any]]:
        return list(self._call(Q_LOCATIONS)["locations"]["nodes"])

    # --- selling plans

    def create_plan_group(self, spec: PlanSpec, variant_ids: list[str]) -> tuple[str, str]:
        data = self._call(
            M_GROUP_CREATE,
            {
                "input": {
                    "name": spec.group_name,
                    "merchantCode": spec.merchant_code,
                    "appId": APP_GROUP_ID,
                    "options": ["Pre-order"],
                    "sellingPlansToCreate": [plan_input(spec)],
                },
                "resources": {"productVariantIds": variant_ids},
            },
        )
        group = self._payload(data, "sellingPlanGroupCreate")["sellingPlanGroup"]
        return group["id"], group["sellingPlans"]["nodes"][0]["id"]

    def replace_plan(self, group_id: str, old_plan_id: str | None, spec: PlanSpec) -> str:
        """A new plan in place of the old one (date or discount changed). Orders already placed
        keep what they bought; new orders get the new plan."""
        data = self._call(
            M_GROUP_UPDATE,
            {
                "id": group_id,
                "input": {
                    "name": spec.group_name,
                    "sellingPlansToCreate": [plan_input(spec)],
                    "sellingPlansToDelete": [old_plan_id] if old_plan_id else [],
                },
            },
        )
        group = self._payload(data, "sellingPlanGroupUpdate")["sellingPlanGroup"]
        ids = [n["id"] for n in group["sellingPlans"]["nodes"] if n["id"] != old_plan_id]
        if not ids:
            raise ShopifyError("The new selling plan wasn't returned.")
        return ids[0]

    def group_variants(self, group_id: str) -> set[str] | None:
        group = self._call(Q_GROUP, {"id": group_id}).get("sellingPlanGroup")
        if group is None:
            return None
        return {n["id"] for n in group["productVariants"]["nodes"]}

    def add_to_group(self, group_id: str, variant_ids: list[str]) -> None:
        if variant_ids:
            data = self._call(M_GROUP_ADD, {"id": group_id, "variants": variant_ids})
            self._payload(data, "sellingPlanGroupAddProductVariants")

    def remove_from_group(self, group_id: str, variant_ids: list[str]) -> None:
        if variant_ids:
            data = self._call(M_GROUP_REMOVE, {"id": group_id, "variants": variant_ids})
            self._payload(data, "sellingPlanGroupRemoveProductVariants")

    # --- variants

    def set_inventory_policy(self, product_id: str, policies: dict[str, str]) -> None:
        if not policies:
            return
        data = self._call(
            M_VARIANTS_UPDATE,
            {
                "productId": product_id,
                "variants": [{"id": v, "inventoryPolicy": p} for v, p in policies.items()],
            },
        )
        self._payload(data, "productVariantsBulkUpdate")

    def set_variant_metafields(self, values: dict[str, str]) -> None:
        items = list(values.items())
        for i in range(0, len(items), 25):  # metafieldsSet takes at most 25
            data = self._call(
                M_METAFIELDS_SET,
                {
                    "metafields": [
                        {
                            "ownerId": vid,
                            "namespace": METAFIELD_NAMESPACE,
                            "key": METAFIELD_KEY,
                            "type": "json",
                            "value": value,
                        }
                        for vid, value in items[i : i + 25]
                    ]
                },
            )
            self._payload(data, "metafieldsSet")

    # --- inventory

    def adjust_available(
        self, inventory_item_id: str, location_id: str, delta: int, key: str, reference: str
    ) -> str:
        data = self._call(
            M_INVENTORY_ADJUST,
            {
                "key": key,
                "input": {
                    "name": "available",
                    "reason": "received",
                    "referenceDocumentUri": reference,
                    "changes": [
                        {
                            "inventoryItemId": inventory_item_id,
                            "locationId": location_id,
                            "delta": delta,
                        }
                    ],
                },
            },
        )
        group = self._payload(data, "inventoryAdjustQuantities").get("inventoryAdjustmentGroup")
        return (group or {}).get("id", "")

    # --- orders

    def order(self, order_id: str) -> OrderSnap | None:
        o = self._call(Q_ORDER, {"id": order_id}).get("order")
        if o is None:
            return None
        lines = []
        for n in o["lineItems"]["nodes"]:
            plan = n.get("sellingPlan") or {}
            original = (n.get("originalUnitPriceSet") or {}).get("shopMoney") or {}
            discounted = (n.get("discountedUnitPriceAfterAllDiscountsSet") or {}).get(
                "shopMoney"
            ) or {}
            lines.append(
                OrderLineSnap(
                    line_item_id=n["id"],
                    variant_id=(n.get("variant") or {}).get("id"),
                    product_id=(n.get("product") or {}).get("id"),
                    sku=n.get("sku") or "",
                    title=" · ".join(x for x in (n.get("title"), n.get("variantTitle")) if x),
                    quantity=int(n.get("quantity") or 0),
                    current_quantity=int(n.get("currentQuantity") or 0),
                    unfulfilled_quantity=int(n.get("unfulfilledQuantity") or 0),
                    selling_plan_id=plan.get("sellingPlanId"),
                    selling_plan_name=plan.get("name"),
                    unit_price_minor=_minor(original.get("amount")),
                    discounted_unit_minor=_minor(discounted.get("amount")),
                    currency=original.get("currencyCode") or o.get("currencyCode") or "GBP",
                )
            )
        fos = [
            FulfillmentOrderSnap(
                id=f["id"],
                status=f["status"],
                fulfill_at=f.get("fulfillAt"),
                line_item_ids=[x["lineItem"]["id"] for x in f["lineItems"]["nodes"]],
            )
            for f in o["fulfillmentOrders"]["nodes"]
        ]
        return OrderSnap(
            order_id=o["id"],
            name=o["name"],
            created_at=o["createdAt"],
            cancelled_at=o.get("cancelledAt"),
            email=o.get("email"),
            customer_name=(o.get("customer") or {}).get("displayName"),
            currency=o.get("currencyCode") or "GBP",
            lines=lines,
            fulfillment_orders=fos,
            test=bool(o.get("test")),
        )

    def orders_with_plans(self, since_iso: str, plan_ids: set[str]) -> list[str]:
        found: list[str] = []
        after = None
        query = f"created_at:>='{since_iso}'"
        while True:
            data = self._call(Q_ORDERS_SINCE, {"first": 50, "after": after, "query": query})
            conn = data["orders"]
            for o in conn["nodes"]:
                plans = {
                    (n.get("sellingPlan") or {}).get("sellingPlanId")
                    for n in o["lineItems"]["nodes"]
                }
                if plans & plan_ids:
                    found.append(o["id"])
            if not conn["pageInfo"]["hasNextPage"]:
                return found
            after = conn["pageInfo"]["endCursor"]

    def open_fulfillment_order(self, fo_id: str) -> str:
        data = self._call(M_FO_OPEN, {"id": fo_id})
        return self._payload(data, "fulfillmentOrderOpen")["fulfillmentOrder"]["status"]
