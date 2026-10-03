"""A fixture shop for the customers workstream (app/customers): people whose names speech gets
wrong, orders placed on days counted back from today, refunds in each of the provider's states,
an inbox that answers the search it is given, and a Gmail that sends and can be read back.

Not a test module: the customers tests and the browser check build their worlds from it. Every
name, address and email here is invented.

The days are counted back from the shop's today, so "last week" finds last week's order whatever
day the suite runs on: an order placed seven days ago is always in the calendar week before.
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyClient, ShopifyError

LONDON = ZoneInfo("Europe/London")
TODAY = datetime.now(LONDON).date()
INVOICE_HOST = "crooksldn.com"


def stamp(days_ago: int, hour: int = 11, minute: int = 0) -> str:
    """Shopify's UTC stamp for a shop-local moment `days_ago` days back."""
    local = datetime.combine(TODAY - timedelta(days=days_ago), time(hour, minute), LONDON)
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def money(amount: float) -> dict[str, Any]:
    return {"shopMoney": {"amount": f"{amount:.2f}", "currencyCode": "GBP"}}


# --------------------------------------------------------------------------- the catalogue


def _variant(number: int, product: str, colour: str, size: str | None, sku: str, price: str, *, for_sale: bool = True) -> dict[str, Any]:
    options = [("Colour", colour)] + ([("Size", size)] if size else [])
    return {"id": f"gid://shopify/ProductVariant/{number}", "product": product, "title": " / ".join(v for _, v in options),
            "sku": sku, "price": price, "for_sale": for_sale, "options": options}


PRODUCTS = {
    "gid://shopify/Product/7001": {"title": "Loopback Hoodie", "status": "ACTIVE"},
    "gid://shopify/Product/7002": {"title": "Convict T-Shirt", "status": "ACTIVE"},
    "gid://shopify/Product/7003": {"title": "Yard Jeans", "status": "ACTIVE"},
    "gid://shopify/Product/7004": {"title": "Convict Cap", "status": "ACTIVE"},
}
VARIANTS = {v["id"]: v for v in (
    _variant(7101, "gid://shopify/Product/7001", "Grey", "S", "LB-HOOD-GRY-S", "65.00"),
    _variant(7102, "gid://shopify/Product/7001", "Grey", "M", "LB-HOOD-GRY-M", "65.00"),
    _variant(7103, "gid://shopify/Product/7001", "Black", "L", "LB-HOOD-BLK-L", "65.00"),
    _variant(7201, "gid://shopify/Product/7002", "Black", "S", "CV-TEE-BLK-S", "30.00"),
    _variant(7202, "gid://shopify/Product/7002", "Black", "M", "CV-TEE-BLK-M", "30.00"),
    _variant(7203, "gid://shopify/Product/7002", "Grey", "S", "CV-TEE-GRY-S", "30.00"),
    _variant(7301, "gid://shopify/Product/7003", "Indigo", "32", "YD-JEAN-IND-32", "85.00"),
    _variant(7401, "gid://shopify/Product/7004", "Black", None, "CV-CAP-BLK", "18.00"),
)}


def vid(number: int) -> str:
    return f"gid://shopify/ProductVariant/{number}"


# --------------------------------------------------------------------------- the people

ALICIA, ALISON, ELISE, THEO, ELLIS, MIA = (f"gid://shopify/Customer/{n}" for n in (9201, 9202, 9203, 9204, 9205, 9206))
PEOPLE: dict[str, dict[str, Any]] = {
    ALICIA: {"name": "Alicia Grant", "first": "Alicia", "email": "alicia.grant@example.com"},
    ALISON: {"name": "Alison Grey", "first": "Alison", "email": "alison.grey@example.org"},
    ELISE: {"name": "Elise Hart", "first": "Elise", "email": "elise.hart@example.net"},
    THEO: {"name": "Theo Marsh", "first": "Theo", "email": "theo.marsh@example.com"},
    ELLIS: {"name": "Ellis Moore", "first": "Ellis", "email": "ellis.moore@example.com"},
    MIA: {"name": "Mia Jones", "first": "Mia", "email": "mia.jones@example.com"},
}

# A refund, and what the payment provider said about the money.
CARD = {"company": "Visa", "number": "•••• •••• •••• 4242"}


def refund(days_ago: int, amount: float, status: str, *, error: str = "", details: dict | None = None) -> dict[str, Any]:
    return {"id": f"gid://shopify/Refund/{uuid.uuid4().int % 10**8}", "createdAt": stamp(days_ago, 14, 2), "note": None,
            "totalRefundedSet": money(amount),
            "transactions": {"edges": [{"node": {
                "kind": "REFUND", "status": status, "gateway": "shopify_payments", "formattedGateway": "Shopify Payments",
                "processedAt": stamp(days_ago, 14, 2), "errorCode": error or None, "amountSet": money(amount),
                "paymentDetails": details if details is not None else dict(CARD)}}]}}


# (number, customer, days ago, [(variant, quantity)], postcode, town, extra)
ORDERS: list[tuple[int, str, int, list[tuple[int, int]], str, str, dict[str, Any]]] = [
    (2201, ALICIA, 7, [(7102, 1)], "SL6 4AB", "Maidenhead", {"refunds": [refund(1, 45.0, "SUCCESS")], "shipped": 6, "note": "Asked for a gift receipt"}),
    (2150, ALICIA, 40, [(7203, 1)], "SL6 4AB", "Maidenhead", {"shipped": 39}),
    (2202, ALISON, 8, [(7103, 1)], "RG1 2CD", "Reading", {"refunds": [refund(0, 20.0, "PENDING")]}),
    (2190, ELISE, 21, [(7101, 1)], "OX1 3EF", "Oxford", {"refunds": [refund(3, 65.0, "FAILURE", error="CARD_DECLINED")]}),
    (2203, THEO, 2, [(7301, 1)], "SL4 5GH", "Windsor", {}),
    (2204, ELLIS, 7, [(7401, 1)], "HP10 9JK", "Wooburn", {}),
    (2205, MIA, 12, [(7201, 1)], "SL7 1LM", "Marlow", {}),
]


def _total(items: list[tuple[int, int]]) -> float:
    return round(sum(float(VARIANTS[vid(v)]["price"]) * q for v, q in items) + 5.0, 2)


def order_node(number: int, added: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An order as the evidence search and the order read both ask for it; `added` is the refunds
    made since the world was built (CustomersShop.refunds_made)."""
    _n, customer, days, items, postcode, town, extra = next(o for o in ORDERS if o[0] == number)
    person = PEOPLE[customer]
    first, _, last = person["name"].partition(" ")
    lines = [{"node": {
        "id": f"gid://shopify/LineItem/{number}{i}", "title": PRODUCTS[VARIANTS[vid(v)]["product"]]["title"],
        "variantTitle": VARIANTS[vid(v)]["title"], "sku": VARIANTS[vid(v)]["sku"], "quantity": q, "currentQuantity": q,
        "refundableQuantity": q, "unfulfilledQuantity": 0 if extra.get("shipped") else q,
        "originalTotalSet": money(float(VARIANTS[vid(v)]["price"]) * q), "discountedTotalSet": money(float(VARIANTS[vid(v)]["price"]) * q),
        "image": None, "variant": {"id": vid(v), "inventoryQuantity": 4, "inventoryItem": {"id": f"gid://shopify/InventoryItem/{v}", "tracked": True},
                                   "selectedOptions": [{"name": n, "value": val} for n, val in VARIANTS[vid(v)]["options"]]},
        "product": {"id": VARIANTS[vid(v)]["product"], "title": PRODUCTS[VARIANTS[vid(v)]["product"]]["title"]},
    }} for i, (v, q) in enumerate(items)]
    refunds = copy.deepcopy(extra.get("refunds") or []) + copy.deepcopy(added or [])
    refunded = sum(float(r["totalRefundedSet"]["shopMoney"]["amount"]) for r in refunds)
    total = _total(items)
    return {
        "id": f"gid://shopify/Order/{number}", "name": f"CROOKS-{number}", "email": person["email"],
        "createdAt": stamp(days), "processedAt": stamp(days), "updatedAt": stamp(days), "cancelledAt": None, "cancelReason": None, "closedAt": None,
        "displayFulfillmentStatus": "FULFILLED" if extra.get("shipped") else "UNFULFILLED",
        "displayFinancialStatus": "PARTIALLY_REFUNDED" if refunds else "PAID", "returnStatus": "NO_RETURN", "fullyPaid": True,
        "tags": [], "note": extra.get("note"), "refundable": True,
        "currentTotalPriceSet": money(total - refunded), "totalPriceSet": money(total),
        "subtotalPriceSet": money(total - 5.0), "totalShippingPriceSet": money(5.0),
        "totalTaxSet": money(0.0), "totalDiscountsSet": money(0.0), "totalRefundedSet": money(refunded), "totalOutstandingSet": money(0.0),
        "shippingLine": {"title": "Royal Mail Tracked 48"},
        "shippingAddress": {"firstName": first, "lastName": last, "company": None, "address1": "1 Example Street", "address2": None,
                            "city": town, "province": None, "provinceCode": None, "zip": postcode, "country": "United Kingdom",
                            "countryCodeV2": "GB", "phone": None},
        "customer": {"id": customer, "displayName": person["name"], "numberOfOrders": str(sum(1 for o in ORDERS if o[1] == customer)),
                     "createdAt": stamp(60), "amountSpent": money(100.0), "defaultEmailAddress": {"emailAddress": person["email"]}},
        "lineItems": {"edges": lines, "pageInfo": {"hasNextPage": False}},
        "fulfillments": ([{"id": f"gid://shopify/Fulfillment/{number}", "status": "SUCCESS", "displayStatus": "DELIVERED",
                           "createdAt": stamp(extra["shipped"], 9), "trackingInfo": [{"company": "Royal Mail", "number": "RM123", "url": None}]}]
                         if extra.get("shipped") else []),
        "refunds": refunds,
        "events": {"edges": []},
    }


# --------------------------------------------------------------------------- the shop


class CustomersShop(ShopifyClient):
    """Shopify, as far as these reads and the one draft go. Searches orders only by what
    Shopify's order search takes; a customer search finds a name by the beginnings of its words."""

    def __init__(self) -> None:
        super().__init__("crooks-test.myshopify.com", "2025-07")
        self._shop = {"name": "CROOKS LDN", "myshopifyDomain": "crooks-test.myshopify.com", "ianaTimezone": "Europe/London", "currencyCode": "GBP"}
        self._tz = LONDON
        self.queries: list[tuple[str, dict]] = []
        self.mutations: list[tuple[str, dict]] = []
        self.drafts: dict[str, dict[str, Any]] = {}
        self.draft_number = 6000
        self.twist: dict[str, Any] = {}
        # Refunds made through CLIVE since the world was built, by order number, and the state the
        # payment provider has reached on each (a test moves it from PENDING to SUCCESS).
        self.refunds_made: dict[int, list[dict[str, Any]]] = {}

    def node(self, number: int) -> dict[str, Any]:
        return order_node(number, self.refunds_made.get(number))

    def settle_refunds(self, status: str) -> None:
        for made in self.refunds_made.values():
            for r in made:
                for edge in r["transactions"]["edges"]:
                    edge["node"]["status"] = status

    # ---- searches

    def _orders(self, q: str | None) -> list[dict[str, Any]]:
        q = str(q or "")
        out = []
        for number, customer, days, items, *_rest in sorted(ORDERS, key=lambda o: o[2]):
            name = re.search(r"\bname:#?(\d+)", q)
            if name and str(number) != name.group(1):
                continue
            email = re.search(r'\bemail:"?([^"\s]+)"?', q)
            if email and PEOPLE[customer]["email"] != email.group(1).lower():
                continue
            ids = re.findall(r"\bcustomer_id:(\d+)", q)
            if ids and customer.rsplit("/", 1)[-1] not in ids:
                continue
            skus = re.findall(r"\bsku:([^\s()]+)", q)
            if skus and not any(VARIANTS[vid(v)]["sku"] in skus for v, _ in items):
                continue
            created = stamp(days)
            lower = re.search(r"created_at:>='([^']+)'", q)
            upper = re.search(r"created_at:<'([^']+)'", q)
            if (lower and created < lower.group(1)) or (upper and created >= upper.group(1)):
                continue
            out.append(self.node(number))
        return out

    @staticmethod
    def _people(q: str) -> list[dict[str, Any]]:
        term = q.strip().strip('"').lower()
        if term.startswith("email:"):
            rows = [(i, p) for i, p in PEOPLE.items() if p["email"] == term[6:].strip().strip('"')]
        else:
            said = term.split()
            rows = [(i, p) for i, p in PEOPLE.items() if said and (term == p["email"] or all(
                any(w.startswith(s) for w in re.split(r"[\s-]+", p["name"].lower())) for s in said))]
        return [{"id": i, "displayName": p["name"], "numberOfOrders": str(sum(1 for o in ORDERS if o[1] == i)),
                 "defaultEmailAddress": {"emailAddress": p["email"]}, "amountSpent": money(100.0)} for i, p in rows]

    def _product(self, product_id: str) -> dict[str, Any]:
        product = PRODUCTS[product_id]
        variants = [v for v in VARIANTS.values() if v["product"] == product_id]
        return {"id": product_id, "title": product["title"], "status": product["status"],
                "variants": {"edges": [{"node": {
                    "id": v["id"], "title": v["title"], "sku": v["sku"], "price": v["price"], "availableForSale": v["for_sale"],
                    "inventoryQuantity": 4, "selectedOptions": [{"name": n, "value": val} for n, val in v["options"]]}} for v in variants]}}

    def _customer_orders(self, customer: str) -> dict[str, Any] | None:
        person = PEOPLE.get(customer)
        if person is None:
            return None
        theirs = sorted([o for o in ORDERS if o[1] == customer], key=lambda o: o[2])
        nodes = [self.node(o[0]) for o in theirs]

        def brief(node: dict[str, Any]) -> dict[str, Any]:
            return {k: node[k] for k in ("id", "name", "createdAt", "processedAt", "cancelledAt", "displayFulfillmentStatus",
                                         "displayFinancialStatus", "returnStatus", "note", "currentTotalPriceSet", "totalPriceSet")} | {
                "lineItems": {"edges": [{"node": {"title": e["node"]["title"], "quantity": e["node"]["quantity"],
                                                  "variantTitle": e["node"]["variantTitle"]}} for e in node["lineItems"]["edges"]]},
                "fulfillments": [{"createdAt": f["createdAt"], "displayStatus": f["displayStatus"], "trackingInfo": [{"company": "Royal Mail"}]}
                                 for f in node["fulfillments"]],
                "refunds": [{"createdAt": r["createdAt"], "totalRefundedSet": r["totalRefundedSet"], "transactions": r["transactions"]}
                            for r in node["refunds"]],
            }

        return {"id": customer, "displayName": person["name"], "numberOfOrders": str(len(theirs)), "createdAt": stamp(60), "tags": [],
                "amountSpent": money(sum(_total(o[3]) for o in theirs)), "defaultEmailAddress": {"emailAddress": person["email"]},
                "lastOrder": {"id": nodes[0]["id"], "name": nodes[0]["name"]} if nodes else None,
                "firstOrder": {"edges": [{"node": {k: nodes[-1][k] for k in ("id", "name", "processedAt", "createdAt")}}]} if nodes else {"edges": []},
                "openOrders": {"edges": [{"node": {"id": n["id"], "name": n["name"], "cancelledAt": None, "displayFulfillmentStatus": n["displayFulfillmentStatus"]}}
                                         for n in nodes if n["displayFulfillmentStatus"] != "FULFILLED"]},
                "orders": {"edges": [{"node": brief(n)} for n in nodes[:5]]}}

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = dict(variables or {})
        self.queries.append((query, variables))
        if "CrooksScopes" in query:
            return {"data": {"currentAppInstallation": {"accessScopes": [{"handle": h} for h in (
                "read_orders", "write_orders", "read_customers", "read_products", "read_draft_orders", "write_draft_orders")]}}}
        if "CrooksOrderEvidence" in query or "FindOrders" in query:
            found, size = self._orders(variables.get("q")), int(variables.get("n") or 25)
            return {"data": {"orders": {"pageInfo": {"hasNextPage": len(found) > size}, "edges": [{"node": o} for o in found[:size]]}}}
        if "CrooksOrderRows" in query:
            found = self._orders(variables.get("q"))
            return {"data": {"orders": {"pageInfo": {"hasNextPage": False},
                                        "edges": [{"cursor": f"c{o['name']}", "node": o} for o in found]}}}
        if "CrooksOrderByName" in query:
            digits = str(variables.get("q") or "").rsplit(":", 1)[-1]
            return {"data": {"orders": {"edges": [{"node": self.node(int(digits))}] if any(str(o[0]) == digits for o in ORDERS) else []}}}
        if "CrooksOrderContext" in query or "CrooksRefundState" in query:
            number = int(str(variables.get("id") or "0").rsplit("/", 1)[-1])
            return {"data": {"order": self.node(number) if any(o[0] == number for o in ORDERS) else None}}
        if "CrooksSuggestedRefund" in query:
            number = int(str(variables.get("id") or "0").rsplit("/", 1)[-1])
            node = self.node(number)
            left = float(node["currentTotalPriceSet"]["shopMoney"]["amount"])
            return {"data": {"order": {"id": node["id"], "name": node["name"], "suggestedRefund": {
                "amountSet": money(left), "subtotalSet": money(left), "totalTaxSet": money(0.0), "maximumRefundableSet": money(left),
                "shipping": {"amountSet": money(0.0), "maximumRefundableSet": money(5.0)},
                "suggestedTransactions": [{"amountSet": money(left), "maximumRefundableSet": money(left), "gateway": "shopify_payments",
                                           "kind": "SUGGESTED_REFUND", "parentTransaction": {"id": f"gid://shopify/OrderTransaction/{number}1"}}],
                "refundLineItems": []}}}}
        if "CrooksCustomersNamed" in query or "FindCustomers" in query or "CrooksCustomerCandidates" in query:
            everyone = self._people(str(variables.get("q") or ""))
            start, size = int(variables.get("after") or 0), int(variables.get("n") or 5)
            return {"data": {"customers": {"pageInfo": {"hasNextPage": start + size < len(everyone), "endCursor": str(start + size)},
                                           "edges": [{"node": n} for n in everyone[start:start + size]]}}}
        if "CrooksCustomerOrders" in query:
            return {"data": {"customer": self._customer_orders(str(variables.get("id") or ""))}}
        if "CrooksCheckoutCustomer" in query:
            person = PEOPLE.get(str(variables.get("id") or ""))
            return {"data": {"customer": person and {"id": variables["id"], "displayName": person["name"], "firstName": person["first"],
                                                     "defaultEmailAddress": {"emailAddress": person["email"]}}}}
        if "CrooksVariantSearch" in query:
            term = str(variables.get("q") or "").strip().lower()
            if term.startswith("sku:"):
                chosen = sorted({v["product"] for v in VARIANTS.values() if v["sku"].lower() == term[4:]})
            else:
                chosen = [pid for pid, p in PRODUCTS.items() if all(w in p["title"].lower() for w in term.split())]
            return {"data": {"products": {"pageInfo": {"hasNextPage": False}, "edges": [{"node": self._product(pid)} for pid in chosen]}}}
        if "CrooksVariantForOrderEdit" in query:
            v = VARIANTS.get(str(variables.get("id") or ""))
            return {"data": {"productVariant": v and {
                "id": v["id"], "title": v["title"], "sku": v["sku"], "price": v["price"], "availableForSale": v["for_sale"], "inventoryQuantity": 4,
                "selectedOptions": [{"name": n, "value": val} for n, val in v["options"]],
                "product": {"id": v["product"], "title": PRODUCTS[v["product"]]["title"], "status": PRODUCTS[v["product"]]["status"]}}}}
        if "CrooksCheckoutDraft" in query or "CrooksDraftPaymentLink" in query:
            draft = self.drafts.get(str(variables.get("id") or ""))
            return {"data": {"draftOrder": copy.deepcopy(draft) if draft else None,
                             "shop": {"myshopifyDomain": "crooks-test.myshopify.com", "primaryDomain": {"host": INVOICE_HOST}}}}
        raise AssertionError(f"the customers shop has no answer for {query[:60]!r}")

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        for key, value in variables.items():
            if isinstance(value, dict) and reviewed.validate is not None:
                assert reviewed.validate(key, value), f"{name}.{key} is not the reviewed shape: {value}"
        self.mutations.append((name, copy.deepcopy(variables)))
        if name == "refund_create":
            body = variables["input"]
            number = int(str(body["orderId"]).rsplit("/", 1)[-1])
            amount = sum(float(t["amount"]) for t in body["transactions"])
            made = refund(0, amount, "PENDING")
            made["createdAt"] = made["transactions"]["edges"][0]["node"]["processedAt"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.refunds_made.setdefault(number, []).append(made)
            return {"data": {"refundCreate": {"refund": {"id": made["id"], "createdAt": made["createdAt"],
                                                         "totalRefundedSet": made["totalRefundedSet"]}, "userErrors": []}}}
        if name != "draft_order_create":
            raise AssertionError(f"nothing else may reach the shop ({name})")
        body = variables["input"]
        self.draft_number += 1
        draft_id = f"gid://shopify/DraftOrder/{self.draft_number}"
        lines = []
        for line in body["lineItems"]:
            v = VARIANTS[line["variantId"]]
            lines.append({"node": {"title": PRODUCTS[v["product"]]["title"], "variantTitle": v["title"], "quantity": line["quantity"],
                                   "variant": {"id": v["id"]}, "discountedTotalSet": money(float(v["price"]) * line["quantity"])}})
        goods = sum(float(e["node"]["discountedTotalSet"]["shopMoney"]["amount"]) for e in lines)
        self.drafts[draft_id] = {
            "id": draft_id, "name": f"#D{self.draft_number}", "status": "OPEN", "email": body.get("email"),
            "invoiceUrl": f"https://{INVOICE_HOST}/58817151183/invoices/{uuid.uuid4().hex[:20]}",
            "customer": {"id": body["customerId"], "displayName": PEOPLE[body["customerId"]]["name"]}, "order": None,
            "totalPriceSet": money(goods), "subtotalPriceSet": money(goods), "totalShippingPriceSet": money(0.0), "totalTaxSet": money(0.0),
            "lineItems": {"edges": lines}, "tags": list(body.get("tags") or []),
        }
        self.drafts[draft_id].update(self.twist)
        return {"data": {"draftOrderCreate": {"draftOrder": {k: v for k, v in self.drafts[draft_id].items() if k != "invoiceUrl"}, "userErrors": []}}}


def fail_the_draft(shop: CustomersShop) -> None:
    async def refuse(name: str, variables: dict) -> dict:
        raise ShopifyError("Shopify did not answer.")

    shop.mutate = refuse  # type: ignore[method-assign]


# --------------------------------------------------------------------------- the inbox


def threads() -> list[dict[str, Any]]:
    """Thread summaries as gmail_tools.threads_for returns them."""
    def at(days_ago: int, hour: int) -> str:
        local = datetime.combine(TODAY - timedelta(days=days_ago), time(hour, 0), LONDON)
        return local.strftime("%a, %d %b %Y %H:%M:%S %z")

    return [
        {"thread_id": "19a0c0ffee000001", "message_id": "m1", "from": "Alicia Grant", "from_email": "alicia.grant@example.com",
         "subject": "Gift receipt for my hoodie order", "date": at(6, 10), "snippet": "Could you put a gift receipt in please?",
         "likely_bulk": False, "authenticated": True},
        {"thread_id": "19a0c0ffee000002", "message_id": "m2", "from": "CROOKS", "from_email": "studio@crooks.example",
         "subject": "Re: Gift receipt for my hoodie order", "date": at(5, 9), "snippet": "Done — it's in the parcel.",
         "likely_bulk": False, "authenticated": True, "to": "alicia.grant@example.com"},
        {"thread_id": "19a0c0ffee000003", "message_id": "m3", "from": "Royal Mail", "from_email": "noreply@royalmail.example",
         "subject": "Delivery update for CROOKS-2201", "date": at(4, 8), "snippet": "Your parcel CROOKS-2201 was delivered",
         "likely_bulk": False, "authenticated": True},
        {"thread_id": "19a0c0ffee000004", "message_id": "m4", "from": "Somebody Else", "from_email": "someone@example.net",
         "subject": "Wholesale enquiry", "date": at(2, 12), "snippet": "Do you do wholesale?", "likely_bulk": False, "authenticated": True},
    ]


def inbox(store: list[dict[str, Any]] | None = None):
    """gmail_tools.threads_for, answering the search it is given: from the sender, or naming one
    of the terms in the subject, the snippet or (for an address) the sender."""
    held = store if store is not None else threads()
    calls: list[dict[str, Any]] = []

    async def threads_for(*, sender: str = "", terms=(), days: int = 60, limit: int = 3) -> dict[str, Any]:
        calls.append({"sender": sender, "terms": list(terms), "days": days, "limit": limit})
        out = []
        for t in held:
            text = f"{t['subject']} {t['snippet']}"
            # An address is found in the From, the To or the words, as Gmail finds a quoted address.
            if (sender and t["from_email"] == sender) or any(term and (term in text or term in (t["from_email"], t.get("to"))) for term in terms):
                out.append({k: v for k, v in t.items() if k != "to"})
        return {"available": True, "threads": out[:limit]}

    threads_for.calls = calls
    threads_for.held = held
    return threads_for


# --------------------------------------------------------------------------- the running world

OWNER = "owner@example.com"
PROXIED = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}
# The shop's own mailbox, so a thread it started reads as ours.
OURS = "studio@crooks.example"


def outbox():
    """Gmail for sending, from tests/test_gmail_writes.py: a message sent is found again by its
    own Message-ID in Sent, which is the proof the engine reads."""
    from tests.test_gmail_writes import FakeGmail

    return FakeGmail()


async def world_fixture(monkeypatch, tmp_path):
    """The real app, its lifespan, routes, gate and engine, with this shop, this inbox, a Gmail
    that sends, and Claude scripted (tests/test_r12_orders.py `Scripted`)."""
    import httpx

    from app.actions.ledger import ActionLedger
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk
    from app.session.manager import SessionManager
    from app.tools import gmail_writes, shopify_tools
    from tests.test_r12_orders import Scripted

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    async def ours() -> str:
        return OURS

    monkeypatch.setattr(shopify_tools, "_our_address", ours)
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        store = CustomersShop()
        runtime.shopify = store
        mail = inbox()
        shopify_tools.bind(store, threads_for=mail)
        sent = outbox()
        runtime.settings = runtime.settings.model_copy(
            update={"writes_enabled": True, "allowed_logins": OWNER, "writes_local_owner": False, "tailscale_verify": False}
        )
        gmail_writes.bind(sent, policy=lambda: runtime.settings)
        runtime.gmail = sent
        from app.families import checkout_link

        checkout_link._made.clear()
        runtime.actions.ledger = ActionLedger(tmp_path)
        runtime.sessions = SessionManager()
        runtime.sessions.on_drop.append(runtime.actions.forget_session)
        runtime.provider = Scripted(runtime)
        app.state.allowed_logins = runtime.allowed_logins
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            client.runtime, client.store, client.model, client.inbox, client.gmail = runtime, store, runtime.provider, mail, sent
            yield client


async def say(client, text: str, *steps, session_id: str = "c1") -> dict:
    """He says `text`; Claude makes `steps`; the body is what the tablet gets back."""
    from tests.test_r12_orders import calls_

    client.model.steps.append(calls_(*steps))
    response = await client.post("/turn", json={"text": text, "session_id": session_id}, headers=PROXIED)
    assert response.status_code == 200, response.text
    return response.json()


async def hold(client, proposal_id: str, session_id: str = "c1") -> dict:
    """The owner's hold on a card: armed, held long enough, then committed."""
    armed = await client.post(f"/actions/{proposal_id}/arm", data={"session_id": session_id}, headers=PROXIED)
    assert armed.status_code == 200, armed.text
    client.runtime.actions.find(proposal_id).armed_at -= 1.0
    done = await client.post(f"/actions/{proposal_id}/commit", data={"session_id": session_id},
                             headers={**PROXIED, "X-Crooks-Arm": armed.json()["nonce"]})
    assert done.status_code == 200, done.text
    return done.json()


def cards(body: dict, kind: str) -> list[dict[str, Any]]:
    return [i["data"] for i in body["ui"] if i["type"] == kind and not i.get("kept")]


def result(client, name: str) -> dict[str, Any]:
    """What the model was handed by the last call of `name`."""
    return next(c.result for c in reversed(client.model.calls) if c.name == name)
