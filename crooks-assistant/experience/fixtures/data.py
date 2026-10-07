"""The golden world: five people, seven orders, three garments and an inbox that fits them.

Everything a scenario needs to be interesting is here and nothing else is. The shapes are
Shopify's and Gmail's own — `lineItems.edges[].node`, `payload.headers` — because the fixture
clients hand these straight to the production shaping code. A fixture that were already shaped
would prove only that the presenter can copy a dictionary.

Time is relative to the run. "Today's orders" has to find today's orders in five months' time,
so the stamps are computed from the clock at import and then frozen — until a harness starts,
which builds the world again against the clock it will be asked on (`rebase`): two runs an
hour apart see the same world, and a run in a year still has orders placed this morning.

Every name, address, postcode and email here is invented. There is no real customer in this
file and there must never be one: a fixture is committed to the repository and a real address
is not ours to commit.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# A 1x1 grey PNG. The media proxy only forwards Shopify's own CDN hosts, so a fixture image
# has to be a data: URI or it is dropped on the way to the tablet — correctly, and that
# dropping is itself tested. Nothing here is fetched over the network.
PLACEHOLDER_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

SHOP_TIMEZONE = "Europe/London"
SHOP_TZ = ZoneInfo(SHOP_TIMEZONE)
CURRENCY = "GBP"

# The clock the world is built against, fixed until a harness rebases it — and in the SHOP's zone,
# not UTC. A shopkeeper asking for "today's orders" means the shop's day, and the application
# agrees: it asks Shopify for the local day's bounds. Stamping the fixtures in UTC instead put
# every order in the wrong day for the hour either side of midnight UTC, which is a fixture
# that passes all day and fails at eleven at night.
NOW = datetime.now(SHOP_TZ)


def rebase(now: datetime | None = None) -> datetime:
    """Build the world against this clock — the shop's clock now, unless told otherwise.

    Frozen at import was frozen at COLLECTION, and the application reads the clock when it is
    asked. A suite collected before London's midnight and still running after it — 23:00 UTC
    in summer — had a world whose "today" was yesterday by the time a later harness asked for
    today's orders: the application's today began after every one of them, so the list came
    back empty and every scenario that walks it failed. `harness()` calls this when it
    starts, so the world a harness serves is built on the day the application is on. Every
    stamp is made when it is read, from NOW, except the discount windows, stamped again here.
    """
    global NOW
    NOW = (now or datetime.now(SHOP_TZ)).astimezone(SHOP_TZ)
    _stamp_discounts()
    return NOW


# What Royal Mail Tracked 48 costs on every order in this world.
SHIPPING = 5.0


def _local(days_ago: float, hour: int, minute: int = 0) -> datetime:
    """The instant `days_ago` shop-local days back, at a shop-local time of day.

    Today is the exception, and it is the same exception `_today_at` exists for: a message
    stamped "today at 12:00" has not happened yet at eleven in the morning. That made every
    thread from today read as "just now" on the work queue — the column that says how long
    someone has been waiting, which is the whole reason to look at the queue at all. So a time
    of day that is still ahead of us today is folded into the part of the day that has
    happened, keeping the ORDER of today's messages while putting all of them in the past.
    """
    when = (NOW - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if days_ago == 0 and when > NOW:
        midnight = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = (NOW - midnight).total_seconds()
        through_the_day = (hour * 3600 + minute * 60) / 86400.0
        when = midnight + timedelta(seconds=elapsed * through_the_day)
    return when


def _at(days_ago: float, hour: int = 10, minute: int = 0) -> str:
    """A stamp `days_ago` days back, in Shopify's format, which is always UTC."""
    return _local(days_ago, hour, minute).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms(days_ago: float, hour: int = 10, minute: int = 0) -> str:
    """The same instant as Gmail's internalDate: milliseconds since the epoch, as a string."""
    return str(int(_local(days_ago, hour, minute).timestamp() * 1000))


def _rfc2822(days_ago: float, hour: int = 10, minute: int = 0) -> str:
    return _local(days_ago, hour, minute).strftime("%a, %d %b %Y %H:%M:%S %z")


def _today_at(fraction: float) -> datetime:
    """An instant this far through the day so far: 0.0 is just after midnight, 1.0 is now.

    Today's orders are placed this way rather than at a fixed hour, because a question about
    today covers midnight until NOW and nothing else. An order stamped "today at 9am" is in
    the future for anyone running the suite before nine, and one stamped "two hours ago" is
    YESTERDAY for anyone running it before two — either way the fixture works in the afternoon
    and reports "no orders today" at breakfast, which is a flaky test with a plausible-sounding
    failure. A fraction of the elapsed day is inside the window whatever the hour, and keeps
    the three orders in a fixed order relative to each other.
    """
    midnight = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (NOW - midnight).total_seconds()
    # A minute of headroom, so the newest order is never stamped in the same second as "now" —
    # but not in the first two minutes of the day, when a minute is most of what there is. With
    # the headroom taken there, every one of today's orders was stamped at midnight exactly
    # until a minute past, and "the newest" was whichever the sort happened to leave first.
    # Half of what has elapsed keeps them apart and in the past; the two meet at two minutes.
    span = elapsed - 60 if elapsed > 120 else elapsed / 2
    at = midnight + timedelta(seconds=max(0.0, min(fraction, 1.0) * span))
    return at


def _today_iso(fraction: float) -> str:
    return _today_at(fraction).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _money(amount: str) -> dict[str, Any]:
    return {"shopMoney": {"amount": amount, "currencyCode": CURRENCY}}


# --------------------------------------------------------------------------- the catalogue

PRODUCTS: list[dict[str, Any]] = [
    {
        "id": "gid://shopify/Product/9001",
        "title": "Convict Hoodie",
        "productType": "Hoodies",
        "status": "ACTIVE",
        "totalInventory": 26,
        "featuredImage": {"url": PLACEHOLDER_IMAGE, "width": 320, "height": 320},
        "variants": [
            {"id": "gid://shopify/ProductVariant/9101", "title": "Black / S", "sku": "CRK-HOOD-BLK-S", "price": "60.00",
             "inventoryQuantity": 2, "options": [("Colour", "Black"), ("Size", "S")]},
            {"id": "gid://shopify/ProductVariant/9102", "title": "Black / M", "sku": "CRK-HOOD-BLK-M", "price": "60.00",
             "inventoryQuantity": 4, "options": [("Colour", "Black"), ("Size", "M")]},
            {"id": "gid://shopify/ProductVariant/9103", "title": "Black / L", "sku": "CRK-HOOD-BLK-L", "price": "60.00",
             "inventoryQuantity": 11, "options": [("Colour", "Black"), ("Size", "L")]},
            {"id": "gid://shopify/ProductVariant/9104", "title": "Bone / M", "sku": "CRK-HOOD-BON-M", "price": "60.00",
             "inventoryQuantity": 9, "options": [("Colour", "Bone"), ("Size", "M")]},
        ],
    },
    {
        "id": "gid://shopify/Product/9002",
        "title": "Yard Jeans",
        "productType": "Denim",
        "status": "ACTIVE",
        "totalInventory": 13,
        "featuredImage": {"url": PLACEHOLDER_IMAGE, "width": 320, "height": 320},
        "variants": [
            {"id": "gid://shopify/ProductVariant/9201", "title": "Indigo / 30", "sku": "CRK-JEAN-IND-30", "price": "24.00",
             "inventoryQuantity": 0, "options": [("Colour", "Indigo"), ("Size", "30")]},
            {"id": "gid://shopify/ProductVariant/9202", "title": "Indigo / 32", "sku": "CRK-JEAN-IND-32", "price": "24.00",
             "inventoryQuantity": 9, "options": [("Colour", "Indigo"), ("Size", "32")]},
            {"id": "gid://shopify/ProductVariant/9203", "title": "Blue Wash / 32", "sku": "CRK-JEAN-BLW-32", "price": "26.00",
             "inventoryQuantity": 4, "options": [("Colour", "Blue Wash"), ("Size", "32")]},
        ],
    },
    {
        "id": "gid://shopify/Product/9003",
        "title": "Crooks Cap",
        "productType": "Headwear",
        "status": "ACTIVE",
        "totalInventory": 31,
        "featuredImage": {"url": PLACEHOLDER_IMAGE, "width": 320, "height": 320},
        "variants": [
            {"id": "gid://shopify/ProductVariant/9301", "title": "Black / One size", "sku": "CRK-CAP-BLK", "price": "18.00",
             "inventoryQuantity": 31, "options": [("Colour", "Black"), ("Size", "One size")]},
        ],
    },
]

VARIANTS: dict[str, dict[str, Any]] = {}
for _product in PRODUCTS:
    for _variant in _product["variants"]:
        VARIANTS[_variant["id"]] = {**_variant, "product": _product}


# --------------------------------------------------------------------------- the people

@dataclass(frozen=True)
class Person:
    customer_id: str
    name: str
    email: str
    since_days: int
    orders: int
    spent: str


MIA = Person("gid://shopify/Customer/7001", "Mia Jones", "mia.jones@example.com", 420, 3, "213.00")
DAVID = Person("gid://shopify/Customer/7002", "David Randall", "david.randall@example.com", 200, 2, "104.00")
MILLIE = Person("gid://shopify/Customer/7003", "Millie Fenwick", "millie.fenwick@example.com", 95, 1, "84.00")
# Writes in from an address that is not the one on her order: the cross-thread correlation case.
PRIYA = Person("gid://shopify/Customer/7004", "Priya Raman", "priya.raman@example.com", 60, 1, "18.00")
PEOPLE = {p.customer_id: p for p in (MIA, DAVID, MILLIE, PRIYA)}

# Not a customer. Exists so "who needs replying to" has something it must not offer.
NEWSLETTER_SENDER = "no-reply@shipping-updates.example.net"


def _customer_node(person: Person) -> dict[str, Any]:
    return {
        "id": person.customer_id,
        "displayName": person.name,
        "numberOfOrders": str(person.orders),
        "createdAt": _at(person.since_days),
        "amountSpent": {"amount": person.spent, "currencyCode": CURRENCY},
        "defaultEmailAddress": {"emailAddress": person.email},
    }


# --------------------------------------------------------------------------- the orders

@dataclass
class OrderSpec:
    number: int
    person: Person
    days_ago: float
    hour: int
    total: str
    fulfillment: str                  # UNFULFILLED / FULFILLED / PARTIALLY_FULFILLED
    financial: str                    # PAID / REFUNDED / VOIDED
    items: list[tuple[str, int]]      # (variant id, quantity)
    address: dict[str, Any]
    tracking: str = ""
    carrier: str = ""
    cancelled_days_ago: float | None = None
    cancel_reason: str = ""
    note: str = ""
    tags: list[str] = field(default_factory=list)
    # Set for orders placed today: how far through the day so far, 0.0 to 1.0.
    today_fraction: float | None = None

    def placed_at(self) -> str:
        return _today_iso(self.today_fraction) if self.today else _at(self.days_ago, self.hour)

    @property
    def today(self) -> bool:
        return self.today_fraction is not None

    @property
    def order_id(self) -> str:
        return f"gid://shopify/Order/{self.number}"

    @property
    def name(self) -> str:
        return f"#{self.number}"


_WINDSOR = {"name": "Mia Jones", "firstName": "Mia", "lastName": "Jones", "address1": "12 Bridge Street", "address2": "", "city": "Windsor",
            "provinceCode": "", "zip": "SL4 1QN", "country": "United Kingdom", "countryCodeV2": "GB",
            "phone": "", "company": ""}
_LEEDS = {"name": "David Randall", "firstName": "David", "lastName": "Randall", "address1": "4 Kirkgate", "address2": "Flat 2", "city": "Leeds",
          "provinceCode": "", "zip": "LS1 6BY", "country": "United Kingdom", "countryCodeV2": "GB",
          "phone": "", "company": ""}
# Deliberately missing its house number: the "did anyone email us their house number" scenario
# turns on the inbox supplying what the order does not.
_BRISTOL_NO_NUMBER = {"name": "Millie Fenwick", "firstName": "Millie", "lastName": "Fenwick", "address1": "Sefton Park Road", "address2": "", "city": "Bristol",
                      "provinceCode": "", "zip": "BS7 9AL", "country": "United Kingdom", "countryCodeV2": "GB",
                      "phone": "", "company": ""}
_MANCHESTER = {"name": "Priya Raman", "firstName": "Priya", "lastName": "Raman", "address1": "88 Oldham Road", "address2": "", "city": "Manchester",
               "provinceCode": "", "zip": "M4 5EG", "country": "United Kingdom", "countryCodeV2": "GB",
               "phone": "", "company": ""}

ORDERS: list[OrderSpec] = [
    # Today. The scenario order: multi-item, unfulfilled, a customer with history.
    OrderSpec(1938, MIA, 0, 9, "84.00", "UNFULFILLED", "PAID",
              [("gid://shopify/ProductVariant/9102", 1), ("gid://shopify/ProductVariant/9202", 1)],
              _WINDSOR, note="", tags=["vip"], today_fraction=0.5),
    # Today. Single item, unfulfilled — the second row of "today's orders".
    OrderSpec(1940, PRIYA, 0, 11, "18.00", "UNFULFILLED", "PAID",
              [("gid://shopify/ProductVariant/9301", 1)], _MANCHESTER, today_fraction=0.9),
    # Today. Fulfilled and tracked, so "today's orders" is not uniformly unfulfilled.
    OrderSpec(1939, DAVID, 0, 8, "60.00", "FULFILLED", "PAID",
              [("gid://shopify/ProductVariant/9103", 1)], _LEEDS,
              tracking="AB1234567890GB", carrier="Royal Mail", today_fraction=0.15),
    # Four days ago, fulfilled but never tracked: the untracked case.
    OrderSpec(1936, MILLIE, 4, 14, "84.00", "FULFILLED", "PAID",
              [("gid://shopify/ProductVariant/9104", 1), ("gid://shopify/ProductVariant/9203", 1)],
              _BRISTOL_NO_NUMBER),
    # Twelve days ago, cancelled and refunded.
    OrderSpec(1929, DAVID, 12, 16, "44.00", "UNFULFILLED", "REFUNDED",
              [("gid://shopify/ProductVariant/9201", 1), ("gid://shopify/ProductVariant/9301", 1)],
              _LEEDS, cancelled_days_ago=11, cancel_reason="CUSTOMER"),
    # Mia's history: two older orders, so "what else has she ordered" has an answer.
    OrderSpec(1912, MIA, 45, 12, "60.00", "FULFILLED", "PAID",
              [("gid://shopify/ProductVariant/9101", 1)], _WINDSOR,
              tracking="CD2233445566GB", carrier="Royal Mail"),
    OrderSpec(1876, MIA, 120, 10, "69.00", "FULFILLED", "PAID",
              [("gid://shopify/ProductVariant/9301", 1), ("gid://shopify/ProductVariant/9203", 1)],
              _WINDSOR, tracking="EF3344556677GB", carrier="Royal Mail"),
]

BY_ID = {o.order_id: o for o in ORDERS}
BY_NAME = {o.name: o for o in ORDERS}

# The order every "show me order N" scenario asks for.
SCENARIO_ORDER = BY_NAME["#1938"]


def line_item_node(index: int, variant_id: str, quantity: int, *, fulfilled: bool) -> dict[str, Any]:
    variant = VARIANTS[variant_id]
    product = variant["product"]
    total = f"{float(variant['price']) * quantity:.2f}"
    return {
        "id": f"gid://shopify/LineItem/{index}",
        "title": product["title"],
        "quantity": quantity,
        "currentQuantity": quantity,
        "refundableQuantity": 0 if fulfilled else quantity,
        "unfulfilledQuantity": 0 if fulfilled else quantity,
        "variantTitle": variant["title"],
        "sku": variant["sku"],
        "originalTotalSet": _money(total),
        "discountedTotalSet": _money(total),
        "image": {"url": PLACEHOLDER_IMAGE, "width": 320, "height": 320},
        "variant": {
            "id": variant["id"],
            "inventoryQuantity": variant["inventoryQuantity"],
            "inventoryItem": {"id": variant["id"].replace("ProductVariant", "InventoryItem"), "tracked": True},
            "selectedOptions": [{"name": n, "value": v} for n, v in variant["options"]],
        },
        "product": {"id": product["id"], "title": product["title"], "productType": product["productType"]},
    }


def order_node(spec: OrderSpec) -> dict[str, Any]:
    """One order in Shopify's own shape. Every read in the application is shaped from this."""
    fulfilled = spec.fulfillment == "FULFILLED"
    items = [
        line_item_node(1000 + spec.number * 10 + i, variant_id, quantity, fulfilled=fulfilled)
        for i, (variant_id, quantity) in enumerate(spec.items)
    ]
    subtotal = sum(float(VARIANTS[v]["price"]) * q for v, q in spec.items)
    fulfillments: list[dict[str, Any]] = []
    if fulfilled:
        fulfillments = [{
            "id": f"gid://shopify/Fulfillment/{spec.number}",
            "status": "SUCCESS",
            "createdAt": _today_iso(min(1.0, (spec.today_fraction or 0) + 0.05)) if spec.today else _at(max(0.0, spec.days_ago - 1), 15),
            "trackingInfo": ([{"number": spec.tracking, "company": spec.carrier,
                               "url": f"https://track.example/{spec.tracking}"}] if spec.tracking else []),
        }]
    placed = spec.placed_at()
    return {
        "id": spec.order_id,
        "name": spec.name,
        "createdAt": placed,
        "processedAt": placed,
        "updatedAt": placed,
        "cancelledAt": _at(spec.cancelled_days_ago, 9) if spec.cancelled_days_ago is not None else None,
        "cancelReason": spec.cancel_reason or None,
        "closedAt": None,
        "displayFulfillmentStatus": spec.fulfillment,
        "displayFinancialStatus": spec.financial,
        "tags": list(spec.tags),
        "note": spec.note,
        "email": spec.person.email,
        # The money adds up, which it did not: `spec.total` was the goods alone while the
        # order also carried £5 of postage, so every order card showed Subtotal £84.00 +
        # Shipping £5.00 + Tax £0.00 = Total £84.00. Shopify's totalPriceSet includes
        # shipping, so the fixture was not modelling the shop it stands in for, and the one
        # card the owner reads most had arithmetic on it that does not work.
        "currentTotalPriceSet": _money(f"{subtotal + SHIPPING:.2f}"),
        "totalPriceSet": _money(f"{subtotal + SHIPPING:.2f}"),
        "subtotalPriceSet": _money(f"{subtotal:.2f}"),
        "totalShippingPriceSet": _money(f"{SHIPPING:.2f}"),
        "totalTaxSet": _money("0.00"),
        "totalRefundedSet": _money(spec.total if spec.financial == "REFUNDED" else "0.00"),
        "totalOutstandingSet": _money("0.00"),
        "customer": _customer_node(spec.person),
        "shippingAddress": dict(spec.address),
        "billingAddress": dict(spec.address),
        "shippingLine": {"title": "Royal Mail Tracked 48"},
        "fulfillments": fulfillments,
        "refunds": ([{"id": f"gid://shopify/Refund/{spec.number}", "createdAt": _at(11, 9),
                      "totalRefundedSet": _money(spec.total)}] if spec.financial == "REFUNDED" else []),
        "lineItems": {"pageInfo": {"hasNextPage": False}, "edges": [{"node": n} for n in items]},
    }


# --------------------------------------------------------------------------- the inbox

MAILBOX = "orders@crooksldn.example"


@dataclass
class Message:
    message_id: str
    thread_id: str
    sender: str                 # "Name <addr>"
    to: str
    subject: str
    body: str
    days_ago: float
    hour: int
    labels: list[str]

    @property
    def outbound(self) -> bool:
        return "SENT" in self.labels


@dataclass
class Thread:
    thread_id: str
    messages: list[Message]
    # The order this thread is really about, when it is about one. The correlation the
    # application derives is checked against this, never seeded from it.
    about_order: str = ""


def _msg(mid: str, tid: str, sender: str, subject: str, body: str, days_ago: float, hour: int,
         labels: list[str] | None = None, to: str = MAILBOX) -> Message:
    return Message(mid, tid, sender, to, subject, body, days_ago, hour, labels or ["INBOX", "UNREAD"])


# Gmail thread and message ids are lowercase hex, and `app/tools/gate.py:_ID_KIND` holds them to
# that shape — an id of the wrong form is not one this conversation was issued, whatever else is
# true of it. The readable ids this world used ("t_mia_1938") were therefore refused by the
# production guard, so no offline run could open an email at all: every tap on a thread came back
# "I no longer have that one to hand", and the whole email leg of the graph was untestable here.
# They are hex now, derived from those readable names so a failure can still be traced back to
# the thread it is about.
THREADS: list[Thread] = [
    # 1. Inbound, unanswered, about a live order. The needs-reply case.
    Thread("aa70d3f83dbef06e", [
        _msg("bbe40b57bc810975", "aa70d3f83dbef06e", f"Mia Jones <{MIA.email}>", "Order 1938 — can I add to it?",
             "Hi, I have just placed order 1938. Is it too late to add a cap to it? Thanks, Mia.",
             0, 12),
    ], about_order="#1938"),

    # 2. Inbound then our reply: answered, so it must NOT appear in needs-reply.
    Thread("58361c4d87dfeee5", [
        _msg("f8c90502519407ee", "58361c4d87dfeee5", f"David Randall <{DAVID.email}>", "Where is 1939?",
             "Morning — any tracking for order 1939 yet?", 1, 9),
        _msg("a59b1035eb72180a", "58361c4d87dfeee5", f"CROOKS <{MAILBOX}>", "Re: Where is 1939?",
             "Hi David, 1939 went out with Royal Mail, tracking AB1234567890GB. CROOKS",
             1, 11, labels=["SENT"], to=DAVID.email),
    ], about_order="#1939"),

    # 3. The house number. Millie's order has a street but no number; she sent it by email,
    #    in a thread that never mentions the order number.
    Thread("7acacac7e3eac001", [
        _msg("e3839e304572fbc6", "7acacac7e3eac001", f"Millie Fenwick <{MILLIE.email}>", "Delivery address",
             "Sorry — I think I left the house number off. It is 41 Sefton Park Road, Bristol BS7 9AL.",
             3, 16),
    ], about_order=""),

    # 4. A reply that arrived in its own thread rather than on the original: the cross-thread
    #    correlation case. Priya's order is 1940; this thread names it only in the body.
    Thread("c28cf65d31fe6cbb", [
        _msg("792550885738f37a", "c28cf65d31fe6cbb", f"Priya Raman <{PRIYA.email}>", "Cap",
             "Following up on my order 1940 — is the black cap the adjustable one?", 0, 13),
    ], about_order="#1940"),

    # 5. A notification. Not a customer, must never be offered as needing a reply.
    Thread("a413d264183cfe94", [
        _msg("402b445d24bb77d8", "a413d264183cfe94", f"Shipping Updates <{NEWSLETTER_SENDER}>",
             "Your weekly carrier report is ready",
             "This is an automated message. Do not reply. View your report online.",
             0, 6, labels=["INBOX", "UNREAD", "CATEGORY_UPDATES"]),
    ]),

    # 6. An older answered thread, for a customer's email history.
    Thread("fe128e8f1ec5a51e", [
        _msg("0c2bb5fd5350c039", "fe128e8f1ec5a51e", f"Mia Jones <{MIA.email}>", "Order 1912 arrived",
             "Got it, thank you — the hoodie fits perfectly.", 40, 10, labels=["INBOX"]),
        _msg("12f0298fd262b702", "fe128e8f1ec5a51e", f"CROOKS <{MAILBOX}>", "Re: Order 1912 arrived",
             "Glad to hear it, Mia. CROOKS", 40, 15, labels=["SENT"], to=MIA.email),
    ], about_order="#1912"),
]

BY_THREAD = {t.thread_id: t for t in THREADS}

# A draft sitting in the mailbox, so the draft surface has something real to open.
DRAFTS = [{
    "draft_id": "d_mia_1938",
    "message_id": "m_draft_1",
    "thread_id": "aa70d3f83dbef06e",
    "to": MIA.email,
    "subject": "Re: Order 1938 — can I add to it?",
    "body": "Hi Mia, I have added the cap to 1938 and it will go out today. CROOKS",
}]


def gmail_message_payload(message: Message) -> dict[str, Any]:
    """A message as the Gmail API returns it, body included."""
    encoded = base64.urlsafe_b64encode(message.body.encode("utf-8")).decode("ascii").rstrip("=")
    return {
        "id": message.message_id,
        "threadId": message.thread_id,
        "labelIds": list(message.labels),
        "internalDate": _ms(message.days_ago, message.hour),
        "snippet": message.body[:120],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": message.sender},
                {"name": "To", "value": message.to},
                {"name": "Subject", "value": message.subject},
                {"name": "Date", "value": _rfc2822(message.days_ago, message.hour)},
                {"name": "Message-ID", "value": f"<{message.message_id}@example>"},
            ],
            "body": {"data": encoded, "size": len(message.body)},
        },
    }


# --------------------------------------------------------------------------- the whole thing

@dataclass(frozen=True)
class World:
    """What a scenario asserts against. Read-only, and the same in every process."""

    orders: list[OrderSpec]
    people: dict[str, Person]
    threads: list[Thread]
    products: list[dict[str, Any]]
    mailbox: str = MAILBOX
    timezone: str = SHOP_TIMEZONE
    currency: str = CURRENCY

    def order(self, name: str) -> OrderSpec:
        return BY_NAME[name if name.startswith("#") else f"#{name}"]

    def today(self) -> list[OrderSpec]:
        """The orders a question about today should find, newest first.

        An order is today's when it was placed minutes ago rather than days ago — which is
        always inside the window a question about today asks for, whatever time the suite runs.
        """
        return sorted([o for o in self.orders if o.today], key=lambda o: -(o.today_fraction or 0))

    def orders_of(self, person: Person) -> list[OrderSpec]:
        return sorted([o for o in self.orders if o.person is person], key=lambda o: o.days_ago)

    def threads_of(self, person: Person) -> list[Thread]:
        return [t for t in self.threads if any(person.email in m.sender for m in t.messages)]

    def needs_reply(self) -> list[Thread]:
        """Threads whose last message came in and was never answered, from a real customer."""
        out = []
        for thread in self.threads:
            last = max(thread.messages, key=lambda m: (-m.days_ago, m.hour))
            if last.outbound:
                continue
            if not any(p.email in last.sender for p in self.people.values()):
                continue
            out.append(thread)
        return out


world = World(orders=ORDERS, people=PEOPLE, threads=THREADS, products=PRODUCTS)


# ------------------------------------------------------- appended: the order going abroad
#
# APPENDED, not inserted: every table above keeps the order and the numbering it had, because
# other tests index these fixtures by position and by number. The new records are added to the
# same objects `world` already holds, so the world sees them without a line above changing.
#
# Why it exists: "find a real international order that has been waiting too long and hasn't
# been fulfilled" was asked on the tablet, and the golden world had nothing but GB addresses —
# so the question could only ever be answered "there are none", which is not the answer the
# query engine's family is for. This is one order, going to Dublin, unfulfilled, older than
# ten days: the oldest thing waiting to go out in the whole world.

# Where the shop itself is. The "international" filter is "not this country" — see
# app/analytics/query.py:shop_country_from — and the fixture shop reports it, so the fixture
# exercises the shop-query path rather than the constant behind it.
SHOP_COUNTRY = "GB"

FIONN = Person("gid://shopify/Customer/7005", "Fionn Doherty", "fionn.doherty@example.com", 260, 1, "78.00")
PEOPLE[FIONN.customer_id] = FIONN

_DUBLIN = {"name": "Fionn Doherty", "firstName": "Fionn", "lastName": "Doherty", "address1": "18 Camden Street Lower",
           "address2": "", "city": "Dublin", "provinceCode": "", "zip": "D02 XE01", "country": "Ireland",
           "countryCodeV2": "IE", "phone": "", "company": ""}

# Hour 0, deliberately. The age the system reports is the FLOOR of the elapsed time, so an
# order placed 14 days ago at 11:00 has been waiting 14 days after 11am and 13 days before it
# — and `query_international_waiting` asserts the declared 14 appears in the answer. That test
# passed all day and failed every night between midnight and 11am. Placing it at the start of
# the day takes the fixture off the floor boundary: elapsed is then 14 days plus however far
# into today it is, which floors to 14 at every hour.
INTERNATIONAL_ORDER = OrderSpec(1927, FIONN, 14, 0, "78.00", "UNFULFILLED", "PAID",
                                [("gid://shopify/ProductVariant/9102", 1), ("gid://shopify/ProductVariant/9301", 1)],
                                _DUBLIN)
ORDERS.append(INTERNATIONAL_ORDER)
BY_ID[INTERNATIONAL_ORDER.order_id] = INTERNATIONAL_ORDER
BY_NAME[INTERNATIONAL_ORDER.name] = INTERNATIONAL_ORDER
# --------------------------------------------------------------------------- the composer
# APPENDED for app/families/compose.py. The address a shoot is booked at: nobody in this
# world has ordered anything, which is the whole point — it is the recipient Shopify cannot
# supply, and the bench sentence was refused for want of it. Invented, like every other
# address in this file, and it must stay so.
COMPOSE_TO = "1232candlestickhorse@gmail.com"
COMPOSE_SENTENCE = (
    "Write an email to a model asking if they're free for a shoot next Sunday. "
    f"Their email is {COMPOSE_TO}. Don't send it yet."
)
COMPOSE_DICTATED = (
    "Write an email to a model asking if they're free for a shoot next Sunday. "
    "Their email is 1232 candlestick horse at gmail dot com. Don't send it yet."
)
COMPOSE_SUBJECT = "Free for a shoot on Sunday?"
COMPOSE_BODY = "Hi, are you free for a shoot next Sunday? Let me know and I'll send the call sheet."


def next_sunday(now: datetime | None = None) -> str:
    """The Sunday a scenario should expect, worked out in the SHOP's zone from the SHOP's
    clock — the same two facts `app/families/compose.py::resolve_when` uses, and computed
    here independently so the check can fail if that function's rule ever changes."""
    today = (now or datetime.now(SHOP_TZ)).date()
    ahead = (6 - today.weekday()) % 7
    return (today + timedelta(days=ahead or 7)).isoformat()


# --------------------------------------------------------------------------- the discounts
# APPENDED for app/families/discounts.py. Two codes that already exist, because the read the
# family makes BEFORE it creates anything is a read of a real conflict: a scenario asserting
# "SUMMER15 is taken and the card says what by" has to have something for it to be taken by.
# One is a percentage and one is money off, so both shapes of Shopify's `customerGets.value`
# union are exercised rather than the one shape a test happened to write.
#
# Strictly additive: no order number and no list position moves for these.
DISCOUNTS: dict[str, dict[str, Any]] = {
    "SUMMER15": {
        "id": "gid://shopify/DiscountCodeNode/8801",
        "title": "Summer sale",
        "status": "ACTIVE",
        "startsAt": None,   # stamped by _stamp_discounts, from _DISCOUNT_DAYS
        "endsAt": None,
        "usageLimit": None,
        "asyncUsageCount": 46,
        "value": {"__typename": "DiscountPercentage", "percentage": 0.15},
    },
    "FRIENDS5": {
        "id": "gid://shopify/DiscountCodeNode/8802",
        "title": "Friends and family",
        "status": "EXPIRED",
        "startsAt": None,   # stamped by _stamp_discounts, from _DISCOUNT_DAYS
        "endsAt": None,
        "usageLimit": 200,
        "asyncUsageCount": 188,
        "value": {"__typename": "DiscountAmount", "amount": {"amount": "5.00", "currencyCode": CURRENCY}},
    },
}
# Each code's window as days before NOW — when it started and, for the expired one, when it
# ended. Held as days rather than stamps because this is the one table here that is stamped
# when it is built instead of when it is read, so `rebase` has to be able to stamp it again.
_DISCOUNT_DAYS: dict[str, tuple[float, float | None]] = {"SUMMER15": (30, None), "FRIENDS5": (120, 60)}


def _stamp_discounts() -> None:
    for code, (starts, ends) in _DISCOUNT_DAYS.items():
        DISCOUNTS[code]["startsAt"] = _at(starts)
        DISCOUNTS[code]["endsAt"] = _at(ends) if ends is not None else None


_stamp_discounts()
# A code nothing in the golden world uses, for the scenario that creates one.
DISCOUNT_FREE_CODE = "AUTUMN20"


# ---------------------------------------------------------------- the abandoned checkouts
# APPENDED for app/families/abandoned.py. Five checkouts begun and not paid for, and one
# that WAS paid for in the end — the recovered one, which exists so that the filter on
# `completedAt` is a filter over something rather than a line of code nothing exercises.
#
# The Black / M hoodie is in three of the five, which is what makes "the one that keeps
# appearing" a real ranking rather than a list of one; one of those three has two of them,
# so counting per checkout and counting units give different numbers and a scenario can tell
# which the card did. Strictly additive: no order number and no list position moves.
ABANDONED: list[dict[str, Any]] = [
    {
        "id": "gid://shopify/AbandonedCheckout/5501", "name": "#C5501", "days_ago": 0.4,
        "completed": False, "customer": MIA,
        "lines": [("gid://shopify/ProductVariant/9102", 1), ("gid://shopify/ProductVariant/9301", 1)],
    },
    {
        "id": "gid://shopify/AbandonedCheckout/5502", "name": "#C5502", "days_ago": 1.5,
        "completed": False, "customer": None,
        "lines": [("gid://shopify/ProductVariant/9102", 2)],
    },
    {
        "id": "gid://shopify/AbandonedCheckout/5503", "name": "#C5503", "days_ago": 3.2,
        "completed": False, "customer": PRIYA,
        "lines": [("gid://shopify/ProductVariant/9104", 1)],
    },
    {
        "id": "gid://shopify/AbandonedCheckout/5504", "name": "#C5504", "days_ago": 6.8,
        "completed": False, "customer": MILLIE,
        "lines": [("gid://shopify/ProductVariant/9102", 1), ("gid://shopify/ProductVariant/9104", 1)],
    },
    {
        "id": "gid://shopify/AbandonedCheckout/5505", "name": "#C5505", "days_ago": 11.0,
        "completed": False, "customer": None,
        "lines": [("gid://shopify/ProductVariant/9301", 3)],
    },
    # Begun, left, and then paid for. Not an abandonment, and the read must not count it.
    {
        "id": "gid://shopify/AbandonedCheckout/5506", "name": "#C5506", "days_ago": 2.0,
        "completed": True, "customer": DAVID,
        "lines": [("gid://shopify/ProductVariant/9102", 1)],
    },
    # Older than the fortnight the family looks at by default, so the window is a window.
    {
        "id": "gid://shopify/AbandonedCheckout/5507", "name": "#C5507", "days_ago": 40.0,
        "completed": False, "customer": None,
        "lines": [("gid://shopify/ProductVariant/9301", 1)],
    },
]


def abandoned_total(checkout: dict[str, Any]) -> float:
    """What the checkout was worth: the catalogue's prices plus postage, the same arithmetic
    the shop does for an order. Computed here so a scenario asserting a total is asserting
    arithmetic over the golden catalogue rather than a number somebody typed in."""
    goods = sum(float(VARIANTS[v]["price"]) * q for v, q in checkout["lines"])
    return round(goods + SHIPPING, 2)
