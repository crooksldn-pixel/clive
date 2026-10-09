"""Shopify Admin GraphQL for Shipping, Admin API 2026-10 (API_VERSION). Every document here is
validated against that schema: `python scripts/validate_graphql.py` (Shopify AI Toolkit). Shopify is the system of record: fulfillment
orders say what ships, InventoryItem holds the customs facts, fulfillments carry tracking.

Same client pattern as crooks-returns (client credentials, retries on throttling), copied
rather than imported so the two services deploy independently.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from shipping.models import Address
from shipping.money import Money, to_minor


class ShopifyError(RuntimeError):
    """Shopify could not be reached or did not answer. A write may or may not have happened."""


class ShopifyRefused(ShopifyError):
    """Shopify answered with userErrors: the write did not happen."""


FO_FIELDS = """
  id status requestStatus updatedAt
  order { id name email phone cancelledAt currencyCode displayFinancialStatus createdAt
          customer { displayName } shippingLine { title } }
  assignedLocation { name address1 address2 city zip countryCode province phone location { id } }
  destination { firstName lastName company address1 address2 city province zip countryCode phone email }
  fulfillments(first: 10) { nodes { id status trackingInfo { number company url } } }
  lineItems(first: 100) {
    nodes {
      id totalQuantity remainingQuantity requiresShipping sku productTitle variantTitle inventoryItemId
      weight { value unit }
      variant { id product { id title productType } }
      lineItem { id discountedUnitPriceAfterAllDiscountsSet { shopMoney { amount currencyCode } } }
    }
  }
"""

Q_OPEN_FOS = (
    """
query OpenFulfillmentOrders($first: Int!, $after: String, $query: String) {
  fulfillmentOrders(first: $first, after: $after, query: $query, includeClosed: false) {
    pageInfo { hasNextPage endCursor }
    nodes {"""
    + FO_FIELDS
    + """}
  }
}"""
)

Q_FO = (
    "query FulfillmentOrder($id: ID!) { node(id: $id) { ... on FulfillmentOrder {"
    + FO_FIELDS
    + "} } }"
)

Q_INVENTORY_ITEMS = """
query InventoryItems($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on InventoryItem {
      id harmonizedSystemCode countryCodeOfOrigin
      measurement { weight { value unit } }
    }
  }
}"""

Q_PRODUCT_ITEMS = """
query ProductInventoryItems($id: ID!) {
  product(id: $id) { id title variants(first: 100) { nodes { id title inventoryItem { id } } } }
}"""

M_INVENTORY_ITEM_UPDATE = """
mutation InventoryItemUpdate($id: ID!, $input: InventoryItemInput!) {
  inventoryItemUpdate(id: $id, input: $input) {
    inventoryItem { id harmonizedSystemCode countryCodeOfOrigin measurement { weight { value unit } } }
    userErrors { field message }
  }
}"""

M_FULFILLMENT_CREATE = """
mutation FulfillmentCreate($fulfillment: FulfillmentInput!) {
  fulfillmentCreate(fulfillment: $fulfillment) {
    fulfillment { id status trackingInfo { number company url } }
    userErrors { field message }
  }
}"""

Q_LOCATIONS = """
query Locations {
  locations(first: 20) { nodes { id name isActive fulfillsOnlineOrders address { address1 address2 city zip countryCode provinceCode phone } } }
}"""

GRAMS = {"GRAMS": 1.0, "KILOGRAMS": 1000.0, "OUNCES": 28.349523125, "POUNDS": 453.59237}


def grams(weight: dict[str, Any] | None) -> int | None:
    if not weight or weight.get("value") in (None, 0, 0.0):
        return None
    return round(float(weight["value"]) * GRAMS.get(weight.get("unit") or "GRAMS", 1.0))


# --------------------------------------------------------------------------- snapshots


@dataclass
class FoLine:
    id: str
    quantity: int  # remaining to fulfil: what this shipment carries
    title: str
    variant_title: str
    sku: str | None
    variant_id: str | None
    product_id: str | None
    product_type: str
    inventory_item_id: str | None
    unit_value: Money
    weight_g: int | None  # from the fulfillment order line (Shopify's variant weight)


@dataclass
class ItemFacts:
    hs_code: str | None
    origin_country: str | None
    weight_g: int | None


@dataclass
class FoSnapshot:
    id: str
    status: str
    order_id: str
    order_name: str
    order_cancelled: bool
    currency: str
    destination: Address
    origin: Address
    origin_location_id: str | None
    lines: list[FoLine]
    tracking_numbers: list[str] = field(default_factory=list)
    # The order's Order.displayFinancialStatus, as Shopify gave it (None: not given). Read
    # through shipping.payment.payment(), never compared as a string anywhere else.
    financial_status: str | None = None
    order_created_at: str | None = None  # Order.createdAt: when the customer ordered
    customer_name: str | None = None  # Order.customer.displayName; None: guest or deleted
    # The delivery method chosen at checkout (Order.shippingLine.title); None: the order has
    # none (a draft or manual order). Decides a UK label's service (shipping/domestic.py).
    shipping_line: str | None = None

    @property
    def open(self) -> bool:
        return self.status in ("OPEN", "IN_PROGRESS", "SCHEDULED", "ON_HOLD") and not (
            self.order_cancelled
        )


def parse_fo(node: dict[str, Any]) -> FoSnapshot:
    order = node.get("order") or {}
    d = node.get("destination") or {}
    loc = node.get("assignedLocation") or {}
    lines = []
    for li in (node.get("lineItems") or {}).get("nodes") or []:
        if not li.get("requiresShipping", True) or not li.get("remainingQuantity"):
            continue
        price = (
            (li.get("lineItem") or {}).get("discountedUnitPriceAfterAllDiscountsSet") or {}
        ).get("shopMoney") or {}
        variant = li.get("variant") or {}
        product = variant.get("product") or {}
        lines.append(
            FoLine(
                id=li["id"],
                quantity=int(li["remainingQuantity"]),
                title=product.get("title") or li.get("productTitle") or "",
                variant_title=li.get("variantTitle") or "",
                sku=li.get("sku"),
                variant_id=variant.get("id"),
                product_id=product.get("id"),
                product_type=product.get("productType") or "",
                inventory_item_id=li.get("inventoryItemId"),
                unit_value=Money(
                    minor=to_minor(price.get("amount")),
                    currency=price.get("currencyCode") or order.get("currencyCode") or "GBP",
                ),
                weight_g=grams(li.get("weight")),
            )
        )
    numbers = [
        t.get("number")
        for f in (node.get("fulfillments") or {}).get("nodes") or []
        for t in f.get("trackingInfo") or []
    ]
    return FoSnapshot(
        id=node["id"],
        status=node.get("status") or "",
        order_id=order.get("id") or "",
        order_name=order.get("name") or "",
        order_cancelled=bool(order.get("cancelledAt")),
        financial_status=order.get("displayFinancialStatus"),
        order_created_at=order.get("createdAt"),
        customer_name=((order.get("customer") or {}).get("displayName") or None),
        shipping_line=((order.get("shippingLine") or {}).get("title") or None),
        currency=order.get("currencyCode") or "GBP",
        destination=Address(
            name=" ".join(x for x in (d.get("firstName"), d.get("lastName")) if x),
            company=d.get("company") or "",
            line1=d.get("address1") or "",
            line2=d.get("address2") or "",
            city=d.get("city") or "",
            region=d.get("province") or "",
            postcode=d.get("zip") or "",
            country=d.get("countryCode") or "",
            phone=d.get("phone") or order.get("phone") or "",
            email=d.get("email") or order.get("email") or "",
        ),
        origin=Address(
            name=loc.get("name") or "",
            line1=loc.get("address1") or "",
            line2=loc.get("address2") or "",
            city=loc.get("city") or "",
            region=loc.get("province") or "",
            postcode=loc.get("zip") or "",
            country=loc.get("countryCode") or "",
            phone=loc.get("phone") or "",
        ),
        origin_location_id=(loc.get("location") or {}).get("id"),
        lines=lines,
        tracking_numbers=[n for n in numbers if n],
    )


@dataclass
class FulfillmentTracking:
    """One Shopify Fulfillment as the carrier last reported it (Admin API 2026-10)."""

    id: str
    status: str  # FulfillmentStatus: SUCCESS means the fulfilment exists, not delivered
    display_status: str | None  # FulfillmentDisplayStatus, e.g. IN_TRANSIT, DELIVERED
    in_transit_at: str | None
    delivered_at: str | None
    estimated_delivery_at: str | None
    updated_at: str | None
    numbers: list[str] = field(default_factory=list)
    # The order's displayFinancialStatus at the same read (for after-purchase warnings).
    financial_status: str | None = None
    order_created_at: str | None = None
    customer_name: str | None = None
    # The carrier's scans as Shopify keeps them (FulfillmentEvent), oldest first.
    events: list[dict[str, Any]] = field(default_factory=list)


def parse_fulfillment(
    node: dict[str, Any],
    financial: str | None = None,
    created: str | None = None,
    customer: str | None = None,
) -> FulfillmentTracking:
    order = node.get("order") or {}
    return FulfillmentTracking(
        id=node["id"],
        status=node.get("status") or "",
        display_status=node.get("displayStatus"),
        in_transit_at=node.get("inTransitAt"),
        delivered_at=node.get("deliveredAt"),
        estimated_delivery_at=node.get("estimatedDeliveryAt"),
        updated_at=node.get("updatedAt"),
        numbers=[t.get("number") for t in node.get("trackingInfo") or [] if t.get("number")],
        financial_status=order.get("displayFinancialStatus") or financial,
        order_created_at=order.get("createdAt") or created,
        customer_name=((order.get("customer") or {}).get("displayName") or customer),
        # Read newest first (the latest 30: Shopify refuses `last` without a cursor); kept
        # oldest first.
        events=sorted(
            (
                {
                    "status": e.get("status"),
                    "at": e.get("happenedAt"),
                    "message": (e.get("message") or "")[:300],
                    "city": e.get("city"),
                    "province": e.get("province"),
                    "country": e.get("country"),
                }
                for e in (node.get("events") or {}).get("nodes") or []
                if isinstance(e, dict) and e.get("happenedAt")
            ),
            key=lambda e: e["at"],
        ),
    )


class ShopifyPort(Protocol):
    def open_fulfillment_orders(self) -> list[FoSnapshot]: ...
    def fulfillment_order(self, fo_id: str) -> FoSnapshot | None: ...
    def item_facts(self, inventory_item_ids: list[str]) -> dict[str, ItemFacts]: ...
    def product_items(self, product_id: str) -> list[str]: ...
    def update_item(
        self,
        inventory_item_id: str,
        *,
        hs_code: str | None = None,
        origin_country: str | None = None,
        weight_g: int | None = None,
    ) -> None: ...
    def create_fulfillment(
        self,
        fo_id: str,
        lines: list[tuple[str, int]],
        company: str,
        number: str,
        url: str | None,
        notify: bool,
    ) -> str: ...
    def fulfillment_tracking(self, fulfillment_id: str) -> FulfillmentTracking | None: ...
    def order_fulfillments(self, order_id: str) -> list[FulfillmentTracking]: ...
    def staff_member(self, id_token: str) -> str | None: ...
    def shop_timezone(self) -> str | None: ...


TRACKING_FIELDS = """
  id status displayStatus inTransitAt deliveredAt estimatedDeliveryAt updatedAt
  trackingInfo(first: 5) { number company url }
  events(first: 30, sortKey: HAPPENED_AT, reverse: true) {
    nodes { status happenedAt message city province country }
  }
"""

Q_FULFILLMENT_TRACKING = (
    "query FulfillmentTracking($id: ID!) { node(id: $id) { ... on Fulfillment {"
    + TRACKING_FIELDS
    + " order { id displayFinancialStatus createdAt customer { displayName } } } } }"
)

Q_ORDER_FULFILLMENTS = (
    "query OrderFulfillments($id: ID!) { order(id: $id) { id displayFinancialStatus createdAt"
    " customer { displayName }"
    " fulfillments(first: 10) {" + TRACKING_FIELDS + "} } }"  # x30 events: within query cost
)

Q_SHOP_TIMEZONE = "query ShopTimezone { shop { ianaTimezone } }"

API_VERSION = "2026-10"

# Every GraphQL document the app sends, for scripts/validate_graphql.py.
DOCUMENTS = (
    "Q_OPEN_FOS",
    "Q_FO",
    "Q_INVENTORY_ITEMS",
    "Q_PRODUCT_ITEMS",
    "M_INVENTORY_ITEM_UPDATE",
    "M_FULFILLMENT_CREATE",
    "Q_LOCATIONS",
    "Q_FULFILLMENT_TRACKING",
    "Q_ORDER_FULFILLMENTS",
    "Q_SHOP_TIMEZONE",
)


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
        for attempt in range(4):
            try:
                r = self._http.post(
                    f"https://{self.shop}/admin/api/{self.api_version}/graphql.json",
                    json={"query": document, "variables": variables or {}},
                    headers={"X-Shopify-Access-Token": self._access_token()},
                )
            except httpx.HTTPError as exc:
                raise ShopifyError(f"Shopify could not be reached: {exc}") from exc
            if r.status_code >= 500 and document.lstrip().startswith("mutation"):
                # It may have been done: never sent again blind. The caller reads Shopify back
                # (fulfil re-reads the order before trying again).
                raise ShopifyError(f"Shopify answered {r.status_code}; it may have been done.")
            if r.status_code == 429 or r.status_code >= 500:  # 429: refused, safe to repeat
                time.sleep(0.5 * 2**attempt)
                continue
            if r.status_code != 200:
                raise ShopifyError(f"Shopify answered {r.status_code}.")
            body = r.json()
            errors = body.get("errors")
            if errors:
                if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors):
                    time.sleep(0.5 * 2**attempt)
                    continue
                raise ShopifyError("; ".join(e.get("message", "error") for e in errors))
            return body["data"]
        raise ShopifyError("Shopify is busy; try again shortly.")

    @staticmethod
    def _payload(data: dict[str, Any], root: str) -> dict[str, Any]:
        payload = data[root]
        errors = payload.get("userErrors") or []
        if errors:
            raise ShopifyRefused("; ".join(e["message"] for e in errors))
        return payload

    def open_fulfillment_orders(self) -> list[FoSnapshot]:
        out, after = [], None
        while True:
            data = self._call(Q_OPEN_FOS, {"first": 50, "after": after, "query": "status:open"})
            page = data["fulfillmentOrders"]
            out += [parse_fo(n) for n in page["nodes"]]
            if not page["pageInfo"]["hasNextPage"]:
                return out
            after = page["pageInfo"]["endCursor"]

    def fulfillment_order(self, fo_id: str) -> FoSnapshot | None:
        node = self._call(Q_FO, {"id": fo_id}).get("node")
        return parse_fo(node) if node else None

    def fulfillment_tracking(self, fulfillment_id: str) -> FulfillmentTracking | None:
        node = self._call(Q_FULFILLMENT_TRACKING, {"id": fulfillment_id}).get("node")
        return parse_fulfillment(node) if node and node.get("id") else None

    def order_fulfillments(self, order_id: str) -> list[FulfillmentTracking]:
        order = self._call(Q_ORDER_FULFILLMENTS, {"id": order_id}).get("order") or {}
        paid, created = order.get("displayFinancialStatus"), order.get("createdAt")
        who = (order.get("customer") or {}).get("displayName")
        return [parse_fulfillment(n, paid, created, who) for n in order.get("fulfillments") or []]

    def shop_timezone(self) -> str | None:
        """The store's own time zone (Shop.ianaTimezone), for showing when orders were placed."""
        return ((self._call(Q_SHOP_TIMEZONE).get("shop") or {}).get("ianaTimezone")) or None

    def staff_member(self, id_token: str) -> str | None:
        """The name of the staff member behind an admin session token, by exchanging it for an
        online token (which carries the user), as Returns does. Only for the history; None if
        refused or slow."""
        try:
            r = self._http.post(
                f"https://{self.shop}/admin/oauth/access_token",
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "subject_token": id_token,
                    "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                    "requested_token_type": "urn:shopify:params:oauth:token-type:online-access-token",
                },
                timeout=5,  # only a name for the history: never worth a long wait
            )
            user = (r.json().get("associated_user") or {}) if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return None
        name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
        return name or user.get("email") or None

    def item_facts(self, inventory_item_ids: list[str]) -> dict[str, ItemFacts]:
        out: dict[str, ItemFacts] = {}
        for i in range(0, len(inventory_item_ids), 50):
            data = self._call(Q_INVENTORY_ITEMS, {"ids": inventory_item_ids[i : i + 50]})
            for n in data["nodes"]:
                if n:
                    out[n["id"]] = ItemFacts(
                        hs_code=n.get("harmonizedSystemCode") or None,
                        origin_country=n.get("countryCodeOfOrigin") or None,
                        weight_g=grams((n.get("measurement") or {}).get("weight")),
                    )
        return out

    def product_items(self, product_id: str) -> list[str]:
        product = self._call(Q_PRODUCT_ITEMS, {"id": product_id}).get("product") or {}
        return [
            v["inventoryItem"]["id"]
            for v in (product.get("variants") or {}).get("nodes", [])
            if v.get("inventoryItem")
        ]

    def update_item(
        self,
        inventory_item_id: str,
        *,
        hs_code: str | None = None,
        origin_country: str | None = None,
        weight_g: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if hs_code:
            payload["harmonizedSystemCode"] = hs_code
        if origin_country:
            payload["countryCodeOfOrigin"] = origin_country
        if weight_g:
            payload["measurement"] = {"weight": {"value": float(weight_g), "unit": "GRAMS"}}
        self._payload(
            self._call(M_INVENTORY_ITEM_UPDATE, {"id": inventory_item_id, "input": payload}),
            "inventoryItemUpdate",
        )

    def create_fulfillment(
        self,
        fo_id: str,
        lines: list[tuple[str, int]],
        company: str,
        number: str,
        url: str | None,
        notify: bool,
    ) -> str:
        tracking: dict[str, Any] = {"company": company, "number": number}
        if url:
            tracking["url"] = url
        data = self._call(
            M_FULFILLMENT_CREATE,
            {
                "fulfillment": {
                    "lineItemsByFulfillmentOrder": [
                        {
                            "fulfillmentOrderId": fo_id,
                            "fulfillmentOrderLineItems": [
                                {"id": i, "quantity": q} for i, q in lines
                            ],
                        }
                    ],
                    "trackingInfo": tracking,
                    "notifyCustomer": notify,
                }
            },
        )
        return self._payload(data, "fulfillmentCreate")["fulfillment"]["id"]
