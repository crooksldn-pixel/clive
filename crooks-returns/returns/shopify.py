"""Shopify Admin GraphQL. Every document here was checked against the Admin schema (2026-10)
before it was written down; nothing is ever built from a caller's string. Shopify is the
system of record: each approved request becomes a real Return on the order, so it shows in the
Shopify admin, in Shopify's reports and to CLIVE's own Shopify reads."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Protocol

import httpx

from returns.models import (
    Order,
    OrderLine,
    OrderMoney,
    Reason,
    Return,
    Transaction,
    Variant,
    to_amount,
    to_pence,
)
from returns.settings import Settings

log = logging.getLogger("returns.shopify")


class ShopifyError(RuntimeError):
    """A call failed. The message is fit for a staff screen, not for a customer."""


class ShopifyRefused(ShopifyError):
    """Shopify answered with user errors: nothing was changed, for the reason given."""


# Shopify's reason library is keyed by stable handles; these are the ones each of our reasons
# maps to, best first. An unmatched reason is still sent, as a note on the return line.
REASON_HANDLES: dict[Reason, list[str]] = {
    # The first handle of each is the one the CROOKS store's library uses (checked 2026-10-03).
    Reason.too_small: ["too-small", "too_small", "size-too-small"],
    Reason.too_big: ["too-big", "too_big", "size-too-large"],
    Reason.changed_mind: ["changed-my-mind", "unwanted", "unwanted_2", "changed-mind"],
    Reason.not_as_described: ["item-not-as-described", "not_as_described", "not-as-described"],
    Reason.faulty: ["damaged-or-defective", "defective", "damaged"],
    Reason.wrong_item: ["received-the-wrong-item", "wrong-item", "received-wrong-item"],
}


class ShopifyPort(Protocol):
    def find_orders(self, digits: str) -> list[Order]: ...
    def get_order(self, order_id: str) -> Order | None: ...
    def order_money(self, order_id: str) -> OrderMoney: ...
    def reason_ids(self) -> dict[str, str]: ...
    def create_return(self, ret: Return, reason_ids: dict[str, str]) -> dict[str, Any]: ...
    def attach_shipping(
        self,
        rfo_id: str,
        tracking: str | None,
        tracking_url: str | None,
        label_url: str | None,
        notify: bool,
    ) -> str: ...
    def process_return(self, payload: dict[str, Any], key: str) -> str: ...
    def credit(self, customer_id: str, pence: int, currency: str, key: str) -> str: ...
    def read_return(self, return_id: str) -> dict[str, Any]: ...
    def exchange_holds(self, order_id: str, line_item_ids: list[str]) -> list[str]: ...
    def cancel_return(self, return_id: str) -> str: ...
    def staff_member(self, id_token: str) -> str | None: ...


# ------------------------------------------------------------------------------- documents

ORDER_FIELDS = """
  id name createdAt email phone currencyCode
  customer { id firstName lastName defaultEmailAddress { emailAddress }
             defaultPhoneNumber { phoneNumber } }
  shippingAddress { firstName lastName address1 address2 city province zip countryCodeV2 phone }
  billingAddress { zip phone }
  totalShippingPriceSet { shopMoney { amount } }
  fulfillments(first: 20) { id status createdAt deliveredAt displayStatus }
"""

Q_FIND_ORDERS = (
    "query ReturnsOrderLookup($query: String!) {\n  orders(first: 5, query: $query) { nodes {"
    + ORDER_FIELDS
    + "} }\n}"
)

Q_ORDER = "query ReturnsOrder($id: ID!) {\n  order(id: $id) {" + ORDER_FIELDS + "}\n}"

# Shopify caps one query at a cost of 1000. Asking for every product's variants inside the
# returnable items cost 1367 on the live store, so the items and their products are fetched
# separately: the items first, then up to PRODUCTS_PER_QUERY products per query.
Q_RETURNABLE = """
query ReturnsReturnable($orderId: ID!) {
  returnableFulfillments(orderId: $orderId, first: 10) {
    nodes {
      id
      returnableFulfillmentLineItems(first: 50) {
        nodes {
          quantity
          fulfillmentLineItem {
            id
            lineItem {
              id title variantTitle sku quantity
              image { url }
              discountedUnitPriceAfterAllDiscountsSet { shopMoney { amount } }
              variant { id price selectedOptions { name value } product { id } }
            }
          }
        }
      }
    }
  }
}
"""

PRODUCTS_PER_QUERY = 10

Q_PRODUCTS = """
query ReturnsProducts($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Product {
      id tags
      options { name optionValues { name } }
      measurements: metafield(namespace: "crooks", key: "measurements") { value }
      variants(first: 100) {
        nodes { id title sku price availableForSale inventoryQuantity selectedOptions { name value } }
      }
    }
  }
}
"""

Q_MONEY = """
query ReturnsOrderMoney($id: ID!) {
  order(id: $id) {
    id
    transactions(first: 50) { id kind status gateway amountSet { shopMoney { amount } } }
    totalShippingPriceSet { shopMoney { amount } }
  }
}
"""

Q_REASONS = """
query ReturnsReasons {
  returnReasonDefinitions(first: 250) { nodes { id handle deleted } }
}
"""

Q_RETURN = """
query ReturnsReturnRead($id: ID!) {
  return(id: $id) {
    id name status
    returnLineItems(first: 50) { nodes { ... on ReturnLineItem { id quantity fulfillmentLineItem { id } } } }
    exchangeLineItems(first: 50) { nodes { id lineItems { id variant { id } } } }
    reverseFulfillmentOrders(first: 5) {
      nodes { id status reverseDeliveries(first: 5) { nodes { id } } }
    }
    refunds(first: 10) { nodes { id totalRefundedSet { shopMoney { amount } } } }
  }
}
"""

M_RETURN_CREATE = """
mutation ReturnsReturnCreate($input: ReturnInput!) {
  returnCreate(returnInput: $input) {
    return {
      id name status
      reverseFulfillmentOrders(first: 5) {
        nodes { id lineItems(first: 50) { nodes { id fulfillmentLineItem { id } } } }
      }
      exchangeLineItems(first: 50) { nodes { id } }
      returnLineItems(first: 50) { nodes { ... on ReturnLineItem { id fulfillmentLineItem { id } } } }
    }
    userErrors { field message code }
  }
}
"""

Q_EXCHANGE_HOLDS = """
query ReturnsExchangeHolds($id: ID!) {
  order(id: $id) {
    fulfillmentOrders(first: 20) {
      nodes { status fulfillmentHolds { reason } lineItems(first: 20) { nodes { lineItem { id } } } }
    }
  }
}
"""

Q_APP_SCOPES = """
query ReturnsAppScopes {
  currentAppInstallation { accessScopes { handle } }
}
"""

# What the service needs; `returns-ctl check` compares the installed app against this.
REQUIRED_SCOPES = (
    "read_orders",
    "read_customers",
    "read_products",
    "read_returns",
    "write_returns",
    "read_merchant_managed_fulfillment_orders",
    "read_assigned_fulfillment_orders",
    "read_third_party_fulfillment_orders",
    "read_store_credit_accounts",
    "read_store_credit_account_transactions",
    "write_store_credit_account_transactions",
)

M_RETURN_PROCESS = """
mutation ReturnsReturnProcess($input: ReturnProcessInput!, $key: String!) {
  returnProcess(input: $input) @idempotent(key: $key) {
    return { id status }
    userErrors { field message code }
  }
}
"""

M_REVERSE_DELIVERY = """
mutation ReturnsReverseDelivery($rfoId: ID!, $tracking: ReverseDeliveryTrackingInput,
                                $label: ReverseDeliveryLabelInput, $notify: Boolean) {
  reverseDeliveryCreateWithShipping(reverseFulfillmentOrderId: $rfoId, reverseDeliveryLineItems: [],
                                    trackingInput: $tracking, labelInput: $label,
                                    notifyCustomer: $notify) {
    reverseDelivery { id }
    userErrors { field message code }
  }
}
"""

M_CREDIT = """
mutation ReturnsStoreCreditBonus($id: ID!, $input: StoreCreditAccountCreditInput!, $key: String!) {
  storeCreditAccountCredit(id: $id, creditInput: $input) @idempotent(key: $key) {
    storeCreditAccountTransaction { id }
    userErrors { field message code }
  }
}
"""

M_CANCEL = """
mutation ReturnsReturnCancel($id: ID!) {
  returnCancel(id: $id) {
    return { id status }
    userErrors { field message code }
  }
}
"""


# ------------------------------------------------------------------------------- parsing


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _options(variant: dict[str, Any]) -> dict[str, str]:
    return {o["name"]: o["value"] for o in variant.get("selectedOptions") or []}


def size_option_of(options: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    """The product's size option and its values in the shop's own order (smallest first, as
    the product page lists them). None when the product has no option called size."""
    for option in options:
        if "size" in option["name"].casefold():
            return option["name"], [v["name"] for v in option.get("optionValues") or []]
    return None, []


def parse_size_chart(raw: str | None) -> list[dict[str, str]]:
    """crooks.measurements: a JSON list of rows, each with a "size" and its measurements.
    Anything else (missing, malformed) is no chart rather than an error."""
    try:
        rows = json.loads(raw) if raw else []
    except ValueError:
        return []
    if not isinstance(rows, list):
        return []
    return [
        {str(k): str(v) for k, v in row.items()}
        for row in rows
        if isinstance(row, dict) and row.get("size")
    ]


def parse_order(node: dict[str, Any], returnable: list[dict[str, Any]]) -> Order:
    customer = node.get("customer") or {}
    ship = node.get("shippingAddress") or {}
    bill = node.get("billingAddress") or {}
    fulfillments = [f for f in node.get("fulfillments") or [] if f.get("status") == "SUCCESS"]
    shipped = [d for d in (_dt(f.get("createdAt")) for f in fulfillments) if d]
    delivered = [d for d in (_dt(f.get("deliveredAt")) for f in fulfillments) if d]
    lines = []
    for rf in returnable:
        for item in rf["returnableFulfillmentLineItems"]["nodes"]:
            fli = item["fulfillmentLineItem"]
            li = fli["lineItem"]
            variant = li.get("variant") or {}
            product = variant.get("product") or {}
            siblings = [
                Variant(
                    id=v["id"],
                    title=v["title"],
                    sku=v.get("sku"),
                    price_pence=to_pence(v["price"]),
                    # Untracked stock reads as None: trust availableForSale alone then.
                    available=bool(v.get("availableForSale"))
                    and (v.get("inventoryQuantity") is None or v["inventoryQuantity"] > 0),
                    options=_options(v),
                )
                for v in (product.get("variants") or {}).get("nodes", [])
            ]
            size_option, sizes = size_option_of(product.get("options") or [])
            price = li["discountedUnitPriceAfterAllDiscountsSet"]["shopMoney"]["amount"]
            lines.append(
                OrderLine(
                    fulfillment_line_item_id=fli["id"],
                    line_item_id=li["id"],
                    title=li["title"],
                    variant_title=li.get("variantTitle"),
                    sku=li.get("sku"),
                    image_url=(li.get("image") or {}).get("url"),
                    variant_id=variant.get("id"),
                    variant_price_pence=to_pence(variant["price"])
                    if variant.get("price")
                    else None,
                    product_id=product.get("id"),
                    tags=product.get("tags") or [],
                    ordered_qty=li.get("quantity") or item["quantity"],
                    returnable_qty=item["quantity"],
                    unit_paid_pence=to_pence(price),
                    siblings=siblings,
                    options=_options(variant),
                    size_option=size_option,
                    sizes=sizes,
                    size_chart=parse_size_chart((product.get("measurements") or {}).get("value")),
                )
            )
    name = " ".join(x for x in (customer.get("firstName"), customer.get("lastName")) if x)
    return Order(
        id=node["id"],
        name=node["name"],
        created_at=_dt(node["createdAt"]),
        email=node.get("email"),
        phone=node.get("phone"),
        currency=node.get("currencyCode") or "GBP",
        customer_id=customer.get("id"),
        customer_name=name or None,
        customer_email=(customer.get("defaultEmailAddress") or {}).get("emailAddress"),
        customer_phone=(customer.get("defaultPhoneNumber") or {}).get("phoneNumber"),
        shipping_zip=ship.get("zip"),
        billing_zip=bill.get("zip"),
        shipping_phone=ship.get("phone"),
        billing_phone=bill.get("phone"),
        shipping_address=ship,
        shipping_pence=to_pence(
            ((node.get("totalShippingPriceSet") or {}).get("shopMoney") or {}).get("amount")
        ),
        fulfilled_at=min(shipped) if shipped else None,
        delivered_at=max(delivered) if delivered else None,
        lines=lines,
    )


def reason_ids_from(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Our reason -> Shopify ReturnReasonDefinition id, from the live library."""
    live = {n["handle"]: n["id"] for n in nodes if not n.get("deleted")}
    out = {}
    for reason, handles in REASON_HANDLES.items():
        for handle in handles:
            if handle in live:
                out[reason.value] = live[handle]
                break
    return out


def return_input(ret: Return, reason_ids: dict[str, str]) -> dict[str, Any]:
    lines = []
    for line in ret.lines:
        item: dict[str, Any] = {
            "fulfillmentLineItemId": line.fulfillment_line_item_id,
            "quantity": line.quantity,
            "returnReasonNote": (
                f"{line.reason.value}: {line.note}" if line.note else line.reason.value
            )[:255],
        }
        if line.reason.value in reason_ids:
            item["returnReasonDefinitionId"] = reason_ids[line.reason.value]
        lines.append(item)
    payload: dict[str, Any] = {
        "orderId": ret.order_id,
        "requestedAt": ret.created_at.isoformat(),
        "returnLineItems": lines,
    }
    exchanges = []
    for line in ret.lines:
        if not line.exchange_variant_id:
            continue
        item: dict[str, Any] = {"variantId": line.exchange_variant_id, "quantity": 1}
        # Price the swap at what the customer paid: without this, a discounted order's swap is
        # charged at full price and Shopify holds it for the difference.
        off = (line.exchange_price_pence or line.unit_paid_pence) - line.unit_paid_pence
        if off > 0:
            item["appliedDiscount"] = {
                "description": "Exchange at the price paid",
                "value": {"amount": {"amount": to_amount(off), "currencyCode": ret.currency}},
            }
        # One line per unit, so the discount means the same whatever Shopify multiplies it by.
        exchanges.extend(dict(item) for _ in range(line.quantity))
    if exchanges:
        payload["exchangeLineItems"] = exchanges
    if ret.money.fee_pence:
        payload["returnShippingFee"] = {
            "amount": {"amount": to_amount(ret.money.fee_pence), "currencyCode": ret.currency}
        }
    return payload


def parse_created(node: dict[str, Any]) -> dict[str, Any]:
    rfos = node["reverseFulfillmentOrders"]["nodes"]
    return {
        "return_id": node["id"],
        "return_name": node.get("name"),
        "reverse_fulfillment_order_ids": [r["id"] for r in rfos],
        "rfo_line_item_ids": {
            li["fulfillmentLineItem"]["id"]: li["id"]
            for r in rfos
            for li in r["lineItems"]["nodes"]
            if li.get("fulfillmentLineItem")
        },
        "return_line_item_ids": {
            li["fulfillmentLineItem"]["id"]: li["id"]
            for li in node["returnLineItems"]["nodes"]
            if li.get("fulfillmentLineItem")
        },
        "exchange_line_item_ids": [e["id"] for e in node["exchangeLineItems"]["nodes"]],
    }


# ------------------------------------------------------------------------------- the client


class GraphQLShopify:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()
        self._http = httpx.Client(timeout=30)
        self._reasons: dict[str, str] | None = None

    @property
    def endpoint(self) -> str:
        return f"https://{self.s.shop_domain}/admin/api/{self.s.api_version}/graphql.json"

    def _access_token(self) -> str:
        if self.s.shopify_auth_mode == "static_token":
            return self.s.shopify_static_token
        with self._lock:
            if self._token and time.time() < self._token[1] - 300:
                return self._token[0]
            r = self._http.post(
                f"https://{self.s.shop_domain}/admin/oauth/access_token",
                json={
                    "client_id": self.s.shopify_client_id,
                    "client_secret": self.s.shopify_client_secret,
                    "grant_type": "client_credentials",
                },
            )
            if r.status_code != 200:
                raise ShopifyError(f"Shopify refused the app credentials ({r.status_code}).")
            body = r.json()
            self._token = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
            return self._token[0]

    def staff_member(self, id_token: str) -> str | None:
        """The name of the staff member behind an admin session token, by exchanging it for an
        online token (which carries the user). Used only to sign the timeline; None if refused."""
        try:
            r = self._http.post(
                f"https://{self.s.shop_domain}/admin/oauth/access_token",
                json={
                    "client_id": self.s.shopify_client_id,
                    "client_secret": self.s.shopify_client_secret,
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "subject_token": id_token,
                    "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                    "requested_token_type": "urn:shopify:params:oauth:token-type:online-access-token",
                },
            )
            user = r.json().get("associated_user") or {} if r.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return None
        name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
        return name or user.get("email") or None

    def _call(self, document: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(4):
            r = self._http.post(
                self.endpoint,
                json={"query": document, "variables": variables or {}},
                headers={"X-Shopify-Access-Token": self._access_token()},
            )
            if r.status_code == 429 or r.status_code >= 500:
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

    # ------------------------------------------------------------------------ reads

    def _returnable(self, order_id: str) -> list[dict[str, Any]]:
        nodes = self._call(Q_RETURNABLE, {"orderId": order_id})["returnableFulfillments"]["nodes"]
        variants = [
            item["fulfillmentLineItem"]["lineItem"].get("variant")
            for rf in nodes
            for item in rf["returnableFulfillmentLineItems"]["nodes"]
        ]
        ids = sorted({v["product"]["id"] for v in variants if v and v.get("product")})
        products: dict[str, dict[str, Any]] = {}
        for i in range(0, len(ids), PRODUCTS_PER_QUERY):
            found = self._call(Q_PRODUCTS, {"ids": ids[i : i + PRODUCTS_PER_QUERY]})["nodes"]
            products.update({p["id"]: p for p in found if p})
        # Put each product's details where parse_order reads them: on the line's variant.
        for v in variants:
            if v and v.get("product"):
                v["product"] = products.get(v["product"]["id"], v["product"])
        return nodes

    def find_orders(self, digits: str) -> list[Order]:
        nodes = self._call(Q_FIND_ORDERS, {"query": f"name:#{digits}"})["orders"]["nodes"]
        # The search is loose; keep only the order whose number is exactly the one asked for.
        exact = [n for n in nodes if "".join(c for c in n["name"] if c.isdigit()) == digits]
        return [parse_order(n, self._returnable(n["id"])) for n in exact]

    def get_order(self, order_id: str) -> Order | None:
        node = self._call(Q_ORDER, {"id": order_id})["order"]
        return parse_order(node, self._returnable(order_id)) if node else None

    def order_money(self, order_id: str) -> OrderMoney:
        node = self._call(Q_MONEY, {"id": order_id})["order"]
        return OrderMoney(
            transactions=[
                Transaction(
                    id=t["id"],
                    kind=t["kind"],
                    status=t["status"],
                    gateway=t.get("gateway"),
                    amount_pence=to_pence(t["amountSet"]["shopMoney"]["amount"]),
                )
                for t in node["transactions"]
            ],
            shipping_pence=to_pence(node["totalShippingPriceSet"]["shopMoney"]["amount"]),
        )

    def reason_ids(self) -> dict[str, str]:
        if self._reasons is None:
            nodes = self._call(Q_REASONS)["returnReasonDefinitions"]["nodes"]
            self._reasons = reason_ids_from(nodes)
        return self._reasons

    def read_return(self, return_id: str) -> dict[str, Any]:
        node = self._call(Q_RETURN, {"id": return_id})["return"]
        if not node:
            raise ShopifyError("Shopify has no such return.")
        return node

    def app_scopes(self) -> list[str]:
        installation = self._call(Q_APP_SCOPES)["currentAppInstallation"]
        return [s["handle"] for s in installation["accessScopes"]]

    def exchange_holds(self, order_id: str, line_item_ids: list[str]) -> list[str]:
        """Hold reasons on the fulfilment orders carrying these exchange items (empty: free)."""
        nodes = self._call(Q_EXCHANGE_HOLDS, {"id": order_id})["order"]["fulfillmentOrders"][
            "nodes"
        ]
        wanted = set(line_item_ids)
        return [
            h["reason"]
            for fo in nodes
            if any(li["lineItem"]["id"] in wanted for li in fo["lineItems"]["nodes"])
            for h in fo.get("fulfillmentHolds") or []
        ]

    # ----------------------------------------------------------------------- writes

    def create_return(self, ret: Return, reason_ids: dict[str, str]) -> dict[str, Any]:
        data = self._call(M_RETURN_CREATE, {"input": return_input(ret, reason_ids)})
        return parse_created(self._payload(data, "returnCreate")["return"])

    def attach_shipping(
        self,
        rfo_id: str,
        tracking: str | None,
        tracking_url: str | None,
        label_url: str | None,
        notify: bool,
    ) -> str:
        variables: dict[str, Any] = {"rfoId": rfo_id, "notify": notify}
        if tracking:
            variables["tracking"] = {
                "number": tracking,
                **({"url": tracking_url} if tracking_url else {}),
            }
        if label_url:
            variables["label"] = {"fileUrl": label_url}
        data = self._call(M_REVERSE_DELIVERY, variables)
        return self._payload(data, "reverseDeliveryCreateWithShipping")["reverseDelivery"]["id"]

    def process_return(self, payload: dict[str, Any], key: str) -> str:
        data = self._call(M_RETURN_PROCESS, {"input": payload, "key": key})
        return self._payload(data, "returnProcess")["return"]["status"]

    def credit(self, customer_id: str, pence: int, currency: str, key: str) -> str:
        data = self._call(
            M_CREDIT,
            {
                "id": customer_id,
                "key": key,
                "input": {
                    "creditAmount": {"amount": to_amount(pence), "currencyCode": currency},
                    "notify": True,
                },
            },
        )
        return self._payload(data, "storeCreditAccountCredit")["storeCreditAccountTransaction"][
            "id"
        ]

    def cancel_return(self, return_id: str) -> str:
        data = self._call(M_CANCEL, {"id": return_id})
        return self._payload(data, "returnCancel")["return"]["status"]
