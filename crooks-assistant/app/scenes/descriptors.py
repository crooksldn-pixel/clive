"""Descriptors for the read tools that exist today: app/tools/shopify_tools.py,
app/tools/gmail_tools.py and app/tools/analytics_tools.py.

Each read tool's output is described here — every field's kind, label and pii flag, and the
names of the arguments the tool takes — and registered, so `to_evidence(tool, result, handle=...)` turns its result into Evidence. This is
the only file in app/scenes that knows any connector's name, and it knows them only as data:
what the fields are, never how to draw them. A customer's email address, phone number and
delivery address are pii wherever they appear. Nothing here imports the tools; a result is
read as the plain dictionary a tool returns.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.scenes.evidence import FieldDescriptor, Kind, ToolDescriptors, register

F = FieldDescriptor
MONEY, COUNT, RATIO, DATETIME, DURATION = Kind.MONEY, Kind.COUNT, Kind.RATIO, Kind.DATETIME, Kind.DURATION
STATUS, PERSON, LINK, TEXT, SERIES = Kind.STATUS, Kind.PERSON, Kind.LINK, Kind.TEXT, Kind.SERIES

# The store's own currency, for a price a tool returns as a bare decimal.
STORE_CURRENCY = "GBP"


def _money_of(amount: Any, currency: Any) -> dict[str, Any] | None:
    return {"amount": amount, "currency": currency} if amount is not None and currency else None


# ---------------------------------------------------------------------- shopify

ORDER = (
    F("order_id", LINK, "Order id"),
    F("order_number", TEXT, "Order"),
    F("placed_at", DATETIME, "Placed"),
    F("fulfillment", STATUS, "Fulfilment"),
    F("payment", STATUS, "Payment"),
    F("total", MONEY, "Total"),
    F("customer_name", PERSON, "Customer"),
    F("customer_id", LINK, "Customer id"),
    F("customer_email", TEXT, "Customer email", pii=True),
)

CUSTOMER = (
    F("customer_id", LINK, "Customer id"),
    F("name", PERSON, "Customer"),
    F("email", TEXT, "Email", pii=True),
    F("orders", COUNT, "Orders"),
    F("spent", MONEY, "Spent"),
)

register(ToolDescriptors(
    tool="shopify_find_order", label="Orders found", records="orders", record_id="order_id", fields=ORDER,
    arguments=("query", "limit"),
    facts=(F("orders", COUNT, "Orders found"), F("ambiguous", STATUS, "More than one customer matched")),
))

register(ToolDescriptors(
    tool="shopify_list_orders", label="Recent orders", records="orders", record_id="order_id", fields=ORDER,
    arguments=("days", "limit", "unfulfilled_only", "days_ago"),
    facts=(
        F("count", COUNT, "Orders"),
        F("truncated", STATUS, "More than shown"),
        F("since", DATETIME, "From"),
        F("until", DATETIME, "Until"),
        F("days", DURATION, "Days covered", unit="days"),
    ),
))

register(ToolDescriptors(
    tool="shopify_order_detail", label="Order", records=".", record_id="order_id", arguments=("order_id",),
    fields=ORDER + (
        F("ships_to", TEXT, "Ships to", pii=True),
        F("shipping_address", TEXT, "Delivery address", pii=True),
        F("shipping_method", TEXT, "Shipping method"),
        F("subtotal", MONEY, "Subtotal", path="money.subtotal"),
        F("shipping", MONEY, "Shipping", path="money.shipping"),
        F("tax", MONEY, "Tax", path="money.tax"),
        F("discounts", MONEY, "Discounts", path="money.discounts"),
        F("refunded", MONEY, "Refunded", path="money.refunded"),
        F("outstanding", MONEY, "Outstanding", path="money.outstanding"),
        F("items", COUNT, "Lines"),
        F("fulfillments", COUNT, "Shipments"),
        F("return_status", STATUS, "Returns"),
        F("cancelled_at", DATETIME, "Cancelled"),
        F("note", TEXT, "Note"),
        F("tags", TEXT, "Tags"),
        F("customer_orders", COUNT, "Customer's orders", path="customer.orders"),
        F("customer_spent", MONEY, "Customer's spend", path="customer.spent"),
        F("email_threads", COUNT, "Emails about it", path="email.threads"),
    ),
))

register(ToolDescriptors(
    tool="shopify_order_address", label="Delivery address", records=".", record_id="order_id", arguments=("order_id",),
    fields=(
        F("order_id", LINK, "Order id"),
        F("order_number", TEXT, "Order"),
        F("address", TEXT, "Delivery address", pii=True, path="written"),
        F("recipient", PERSON, "Recipient", pii=True, path="shipping_address.name"),
        F("city", TEXT, "Town", pii=True, path="shipping_address.city"),
        F("postcode", TEXT, "Postcode", pii=True, path="shipping_address.zip"),
        F("country", TEXT, "Country", pii=True, path="shipping_address.country"),
        F("phone", TEXT, "Phone", pii=True),
    ),
))

register(ToolDescriptors(
    tool="shopify_customer_history", label="Customer history", records=".", record_id="customer_id", arguments=("customer_id",),
    fields=CUSTOMER + (
        F("since", DATETIME, "Customer since"),
        F("standing", STATUS, "Standing"),
        F("first_order_at", DATETIME, "First order"),
        F("last_order", TEXT, "Last order", path="last_order.order_number"),
        F("recent", COUNT, "Recent orders shown"),
        F("other_unfulfilled", TEXT, "Other orders to ship"),
        F("email_threads", COUNT, "Emails from them", path="email_threads.threads"),
    ),
))

register(ToolDescriptors(
    tool="shopify_find_customer", label="Customers found", records="customers", record_id="customer_id", fields=CUSTOMER,
    arguments=("query", "limit"),
    facts=(F("count", COUNT, "Customers found"), F("truncated", STATUS, "More than shown"), F("ambiguous", STATUS, "More than one matched")),
))


def _inventory(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Products hold variants; the variants are the rows."""
    variants = [
        {**v, "product": p.get("title"), "product_status": p.get("status")}
        for p in result.get("products") or [] if isinstance(p, Mapping)
        for v in p.get("variants") or [] if isinstance(v, Mapping)
    ]
    return {**result, "variants": variants}


register(ToolDescriptors(
    tool="shopify_inventory", label="Stock", records="variants", record_id="variant_id", extract=_inventory,
    arguments=("product", "size", "limit"),
    fields=(
        F("variant_id", LINK, "Variant id"),
        F("product", TEXT, "Product"),
        F("product_status", STATUS, "Product status"),
        F("variant", TEXT, "Variant"),
        F("sku", TEXT, "SKU"),
        F("available", COUNT, "Available"),
        F("oversold_by", COUNT, "Oversold by"),
        F("tracked", STATUS, "Stock tracked"),
    ),
    facts=(F("products", COUNT, "Products checked"), F("truncated", STATUS, "More than checked")),
))


def _sales(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Revenue is a number beside the result's currency; the days are rows and two series."""
    currency = result.get("currency")
    days = [d for d in result.get("by_day") or [] if isinstance(d, Mapping)]
    return {
        **result,
        "revenue": _money_of(result.get("revenue"), currency),
        "by_day": [{**d, "revenue": _money_of(d.get("revenue"), currency)} for d in days],
        "revenue_by_day": {"points": days, "currency": currency},
        "orders_by_day": days,
    }


register(ToolDescriptors(
    tool="shopify_sales_summary", label="Sales", records="by_day", record_id="date", extract=_sales,
    arguments=("days", "days_ago", "by_day"),
    fields=(F("date", DATETIME, "Day"), F("orders", COUNT, "Orders"), F("revenue", MONEY, "Sales")),
    facts=(
        F("orders", COUNT, "Orders"),
        F("revenue", MONEY, "Sales"),
        F("complete", STATUS, "Complete"),
        F("since", DATETIME, "From"),
        F("until", DATETIME, "Until"),
        F("days", DURATION, "Days covered", unit="days"),
        F("revenue_by_day", SERIES, "Sales by day", points=("date", "revenue")),
        F("orders_by_day", SERIES, "Orders by day", unit="orders", points=("date", "orders")),
        F("caveat", TEXT, "Caveat"),
    ),
))

register(ToolDescriptors(
    tool="shopify_product_info", label="Products", records="products", record_id="product_id",
    arguments=("product", "size", "limit"),
    fields=(
        F("product_id", LINK, "Product id"),
        F("title", TEXT, "Product"),
        F("status", STATUS, "Status"),
        F("description", TEXT, "Description"),
        F("fabric", TEXT, "Fabric"),
        F("cut", TEXT, "Cut"),
        F("origin", TEXT, "Made in"),
        F("care", TEXT, "Care"),
        F("measurements", COUNT, "Sizes measured"),
    ),
))

register(ToolDescriptors(
    tool="shopify_variant_search", label="Variants", records="candidates", record_id="variant_id",
    arguments=("product", "colour", "size", "limit"),
    fields=(
        F("variant_id", LINK, "Variant id"),
        F("product_id", LINK, "Product id"),
        F("title", TEXT, "Product"),
        F("variant", TEXT, "Variant"),
        F("sku", TEXT, "SKU"),
        F("price", MONEY, "Price", currency=STORE_CURRENCY),
        F("available", COUNT, "Available"),
        F("for_sale", STATUS, "For sale"),
    ),
    facts=(F("count", COUNT, "Matches"), F("confident", STATUS, "One clear match"), F("truncated", STATUS, "More than shown")),
))


# ------------------------------------------------------------------------ gmail

register(ToolDescriptors(
    tool="gmail_search", label="Inbox", records="threads", record_id="thread_id",
    arguments=("query", "days", "limit", "include_bulk"),
    fields=(
        F("thread_id", LINK, "Thread id"),
        F("message_id", LINK, "Message id"),
        F("from", PERSON, "From"),
        F("from_email", TEXT, "From address", pii=True),
        F("subject", TEXT, "Subject"),
        F("date", DATETIME, "Received"),
        F("snippet", TEXT, "Snippet"),
        F("likely_bulk", STATUS, "Bulk mail"),
        F("authenticated", STATUS, "Sender verified"),
        F("known_customer", STATUS, "Known customer"),
    ),
    facts=(F("count", COUNT, "Threads"),),
))

register(ToolDescriptors(
    tool="gmail_read_thread", label="Email thread", records="messages", record_id="message_id", arguments=("thread_id",),
    fields=(
        F("message_id", LINK, "Message id"),
        F("from", PERSON, "From"),
        F("from_email", TEXT, "From address", pii=True),
        F("date", DATETIME, "Sent"),
        F("subject", TEXT, "Subject"),
        F("body", TEXT, "Message"),
        F("outbound", STATUS, "Sent by us"),
    ),
    facts=(
        F("thread_id", LINK, "Thread id"),
        F("message_count", COUNT, "Messages"),
        F("messages_shown", COUNT, "Messages read"),
        F("truncated", STATUS, "Older messages not read"),
        F("latest_direction", STATUS, "Last message"),
        F("awaiting_reply", STATUS, "Awaiting our reply"),
    ),
))

register(ToolDescriptors(
    tool="gmail_find_in_email", label="Search in email", records="matches", record_id="message_id",
    arguments=("contains", "sender", "mentions", "days"),
    fields=(
        F("message_id", LINK, "Message id"),
        F("thread_id", LINK, "Thread id"),
        F("subject", TEXT, "Subject"),
        F("date", DATETIME, "Sent"),
        F("from", TEXT, "From address", pii=True),
        F("outbound", STATUS, "Sent by us"),
        F("where", STATUS, "Found in"),
        # The tool looks for house numbers and postcodes: the line it found is an address.
        F("excerpt", TEXT, "Line found", pii=True),
    ),
    facts=(
        F("contains", TEXT, "Looked for", pii=True),
        F("threads_found", COUNT, "Threads found"),
        F("threads_checked", COUNT, "Threads read"),
        F("threads_unreadable", COUNT, "Threads unreadable"),
        F("complete", STATUS, "Every thread read"),
        F("match_count", COUNT, "Matches"),
    ),
))


# -------------------------------------------------------------------- analytics

# The metrics that are amounts of money; the query language returns them as numbers beside
# the result's currency (an order row carries its own).
_MONEY_METRICS = ("total", "revenue", "aov", "refunded", "unfulfilled_value", "lifetime_spent")
_TIME_GROUPS = ("day", "week", "month")
_TRENDS = {"revenue": "revenue_trend", "units": "units_trend", "orders": "orders_trend"}


def _commerce(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """Rows keyed by what they group, amounts as money, and — for a breakdown by day, week
    or month — the metrics as series."""
    currency = result.get("currency")
    raw_rows = [r for r in result.get("rows") or [] if isinstance(r, Mapping)]
    rows = []
    for r in raw_rows:
        key = r.get("key") if isinstance(r.get("key"), Mapping) else {}
        row = {**r, **{m: _money_of(r[m], r.get("currency") or currency) for m in _MONEY_METRICS if m in r}}
        row["id"] = r.get("order_id") or next((v for k, v in key.items() if k.endswith("_id") and v), None) or r.get("label")
        row["customer_email"] = r.get("customer_email") or key.get("customer_email")
        rows.append(row)

    def amounts(totals: Any) -> dict[str, Any]:
        if not isinstance(totals, Mapping):
            return {}
        return {k: (_money_of(v, currency) if k in _MONEY_METRICS else v) for k, v in totals.items()}

    compare = result.get("compare") if isinstance(result.get("compare"), Mapping) else {}
    out: dict[str, Any] = {**result, "rows": rows, "totals": amounts(result.get("totals")), "previous": amounts(compare.get("totals"))}
    groups = list(result.get("group_by") or [])
    if len(groups) == 1 and groups[0] in _TIME_GROUPS:
        ordered = sorted(raw_rows, key=lambda r: str(r.get("label") or ""))
        for metric, name in _TRENDS.items():
            points = [{"at": r.get("label"), "value": r.get(metric)} for r in ordered if metric in r]
            if points:
                out[name] = {"points": points, "currency": currency if metric in _MONEY_METRICS else None}
    return out


COMMERCE_ROWS = (
    F("order_id", LINK, "Order id"),
    F("order_number", TEXT, "Order"),
    F("placed_at", DATETIME, "Placed"),
    F("age_days", DURATION, "Waiting", unit="days"),
    F("fulfillment", STATUS, "Fulfilment"),
    F("payment", STATUS, "Payment"),
    F("total", MONEY, "Total"),
    F("customer_name", PERSON, "Customer"),
    F("customer_id", LINK, "Customer id"),
    F("customer_email", TEXT, "Customer email", pii=True),
    F("country_code", TEXT, "Country"),
    F("items", COUNT, "Lines"),
    F("has_tracking", STATUS, "Tracking"),
    F("cancelled", STATUS, "Cancelled"),
    F("label", TEXT, "Name"),
    F("units", COUNT, "Units"),
    F("revenue", MONEY, "Sales"),
    F("orders", COUNT, "Orders"),
    F("customers", COUNT, "Customers"),
    F("aov", MONEY, "Average order"),
    F("refunded", MONEY, "Refunded"),
    F("unfulfilled_value", MONEY, "To ship"),
    F("share", RATIO, "Share", unit="%"),
    F("stock", COUNT, "In stock"),
    F("velocity", RATIO, "Sold per day", unit="units/day"),
    F("days_cover", DURATION, "Days of cover", unit="days"),
    F("lifetime_orders", COUNT, "Lifetime orders"),
    F("lifetime_spent", MONEY, "Lifetime spend"),
    F("last_order_at", DATETIME, "Last order"),
    F("first_order_at", DATETIME, "First order"),
)

COMMERCE_FACTS = (
    F("row_count", COUNT, "Matches"),
    F("truncated", STATUS, "More than shown"),
    F("complete", STATUS, "Complete"),
    F("period", TEXT, "Period", path="period.label"),
    F("orders", COUNT, "Orders", path="totals.orders"),
    F("revenue", MONEY, "Sales", path="totals.revenue"),
    F("units", COUNT, "Units", path="totals.units"),
    F("customers", COUNT, "Customers", path="totals.customers"),
    F("aov", MONEY, "Average order", path="totals.aov"),
    F("refunded", MONEY, "Refunded", path="totals.refunded"),
    F("unfulfilled_value", MONEY, "To ship", path="totals.unfulfilled_value"),
    F("previous_orders", COUNT, "Orders before", path="previous.orders"),
    F("previous_revenue", MONEY, "Sales before", path="previous.revenue"),
    F("previous_units", COUNT, "Units before", path="previous.units"),
    F("revenue_trend", SERIES, "Sales over time"),
    F("units_trend", SERIES, "Units over time", unit="units"),
    F("orders_trend", SERIES, "Orders over time", unit="orders"),
)

for _tool, _label, _arguments in (
    ("commerce_aggregate", "Sales breakdown",
     ("entity", "period", "filters", "group_by", "metrics", "sort", "limit", "compare", "view", "title")),
    ("commerce_query", "Matching records", ("entity", "period", "filters", "sort", "limit", "metrics", "title")),
    ("inventory_query", "Restock priority", ("period", "product", "colour", "size", "limit", "max_days_cover", "title")),
):
    register(ToolDescriptors(
        tool=_tool, label=_label, records="rows", record_id="id", extract=_commerce, fields=COMMERCE_ROWS, facts=COMMERCE_FACTS,
        arguments=_arguments,
    ))

register(ToolDescriptors(
    tool="email_query", label="Who has emailed", records="rows", record_id="customer_id", arguments=("set_id", "days"),
    fields=(
        F("customer_id", LINK, "Customer id"),
        F("customer_name", PERSON, "Customer"),
        F("customer_email", TEXT, "Customer email", pii=True),
        F("orders", TEXT, "Orders"),
        F("emailed", STATUS, "Has emailed"),
        F("threads", COUNT, "Threads"),
        F("replied", STATUS, "We replied"),
        F("needs_reply", STATUS, "Waiting on us"),
        F("latest_direction", STATUS, "Last message"),
        F("latest_inbound_at", DATETIME, "Their last email"),
        F("latest_outbound_at", DATETIME, "Our last reply"),
        F("last_subject", TEXT, "Last subject"),
        F("last_date", DATETIME, "Last email"),
        F("confidence", STATUS, "Match"),
        F("checked", STATUS, "Checked"),
    ),
    facts=(
        F("set_label", TEXT, "Set"),
        F("days", DURATION, "Days looked back", unit="days"),
        F("customers", COUNT, "Customers checked"),
        F("contacted", COUNT, "Have emailed", path="counts.contacted"),
        F("not_contacted", COUNT, "Have not emailed", path="counts.not_contacted"),
        F("replied", COUNT, "Replied to", path="counts.replied"),
        F("needs_reply", COUNT, "Waiting on a reply", path="counts.needs_reply"),
        F("unchecked", COUNT, "Could not be checked", path="counts.unchecked"),
    ),
))


def _capabilities(result: Mapping[str, Any]) -> Mapping[str, Any]:
    return {**result, "entities": [{"entity": e} for e in result.get("entities") or [] if isinstance(e, str)]}


register(ToolDescriptors(
    tool="commerce_capabilities", label="What the read language covers", records="entities", record_id="entity",
    extract=_capabilities, fields=(F("entity", TEXT, "Entity"),), facts=(F("read_only", STATUS, "Read only"),),
))
