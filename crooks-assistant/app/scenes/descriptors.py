"""Descriptors for the existing read tools, and an adapter from each tool's result to Evidence.

Every function here reads the SAME dict its tool already returns (app/tools/shopify_tools.py,
app/tools/gmail_tools.py, app/tools/analytics_tools.py) and describes it as typed evidence.
None of it decides what is shown — that is app/scenes/scene.py and app/scenes/validate.py — and
none of it is imported by the live app. Customer email, phone and address fields are marked
`pii=True` throughout, Shopify and Gmail alike: a contact detail is a contact detail whichever
connector read it.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.scenes.evidence import Evidence, FieldDescriptor, FieldKind, money, series_point

_MONEY_RE = re.compile(r"^(-?[0-9]+(?:\.[0-9]+)?)\s+([A-Za-z]{3})$")


def _parse_money(text: object) -> dict[str, Any] | None:
    """A "12.50 GBP" string, as both app/tools/shopify_tools.py and app/context/order.py write
    it, as a money value — or None when there is nothing to parse."""
    if not isinstance(text, str):
        return None
    match = _MONEY_RE.match(text.strip())
    if not match:
        return None
    return money(float(match.group(1)), match.group(2).upper())


# ------------------------------------------------------------------------------- shopify_tools

_ORDER_SUMMARY_FIELDS = [
    FieldDescriptor(name="order_number", kind=FieldKind.TEXT, label="Order"),
    FieldDescriptor(name="order_link", kind=FieldKind.LINK, label="Order"),
    FieldDescriptor(name="placed_at", kind=FieldKind.DATETIME, label="Placed"),
    FieldDescriptor(name="fulfillment", kind=FieldKind.STATUS, label="Fulfilment"),
    FieldDescriptor(name="payment", kind=FieldKind.STATUS, label="Payment"),
    FieldDescriptor(name="total", kind=FieldKind.MONEY, label="Total", currency="GBP"),
    FieldDescriptor(name="customer_name", kind=FieldKind.PERSON, label="Customer"),
    FieldDescriptor(name="customer_email", kind=FieldKind.TEXT, label="Email", pii=True),
]


def _order_summary_record(o: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_number": o.get("order_number"),
        "order_link": {"ref": o.get("order_id"), "label": o.get("order_number") or ""},
        "placed_at": o.get("placed_at"),
        "fulfillment": o.get("fulfillment"),
        "payment": o.get("payment"),
        "total": _parse_money(o.get("total")),
        "customer_name": o.get("customer_name"),
        "customer_email": o.get("customer_email"),
    }


def from_shopify_find_order(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [_order_summary_record(o) for o in result.get("orders") or []]
    return Evidence(
        handle=handle, source_tool="shopify_find_order", observed_at=observed_at,
        query_summary=f"Shopify orders matching {result.get('query') or ''}".strip(),
        fields=_ORDER_SUMMARY_FIELDS, records=records,
    )


def from_shopify_list_orders(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [_order_summary_record(o) for o in result.get("orders") or []]
    return Evidence(
        handle=handle, source_tool="shopify_list_orders", observed_at=observed_at,
        query_summary=f"Shopify orders, {result.get('since', '')} to {result.get('until', '')}",
        fields=_ORDER_SUMMARY_FIELDS, records=records,
    )


_ORDER_DETAIL_FIELDS = [
    *_ORDER_SUMMARY_FIELDS,
    FieldDescriptor(name="subtotal", kind=FieldKind.MONEY, label="Subtotal", currency="GBP"),
    FieldDescriptor(name="shipping", kind=FieldKind.MONEY, label="Shipping", currency="GBP"),
    FieldDescriptor(name="tax", kind=FieldKind.MONEY, label="Tax", currency="GBP"),
    FieldDescriptor(name="refunded", kind=FieldKind.MONEY, label="Refunded", currency="GBP"),
    FieldDescriptor(name="outstanding", kind=FieldKind.MONEY, label="Outstanding", currency="GBP"),
    FieldDescriptor(name="note", kind=FieldKind.TEXT, label="Note"),
    FieldDescriptor(name="ships_to", kind=FieldKind.TEXT, label="Ships to"),
    FieldDescriptor(name="tags", kind=FieldKind.TEXT, label="Tags"),
]


def from_shopify_order_detail(order: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    money_block = order.get("money") or {}
    record = {
        **_order_summary_record(order),
        "total": _parse_money(money_block.get("total")) or _parse_money(order.get("total")),
        "subtotal": _parse_money(money_block.get("subtotal")),
        "shipping": _parse_money(money_block.get("shipping")),
        "tax": _parse_money(money_block.get("tax")),
        "refunded": _parse_money(money_block.get("refunded")),
        "outstanding": _parse_money(money_block.get("outstanding")),
        "note": order.get("note") or "",
        "ships_to": order.get("ships_to") or "",
        "tags": ", ".join(order.get("tags") or []),
    }
    return Evidence(
        handle=handle, source_tool="shopify_order_detail", observed_at=observed_at,
        query_summary=f"Shopify order detail for {order.get('order_number') or order.get('order_id') or ''}",
        fields=_ORDER_DETAIL_FIELDS, records=[record],
    )


_ADDRESS_FIELDS = [
    FieldDescriptor(name="order_number", kind=FieldKind.TEXT, label="Order"),
    FieldDescriptor(name="address", kind=FieldKind.TEXT, label="Address", pii=True),
    FieldDescriptor(name="phone", kind=FieldKind.TEXT, label="Phone", pii=True),
]


def from_shopify_order_address(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    record = {
        "order_number": result.get("order_number"),
        "address": result.get("written") or "",
        "phone": result.get("phone") or "",
    }
    return Evidence(
        handle=handle, source_tool="shopify_order_address", observed_at=observed_at,
        query_summary=f"Delivery address for order {result.get('order_number') or ''}",
        fields=_ADDRESS_FIELDS, records=[record],
    )


_CUSTOMER_HISTORY_FIELDS = [
    FieldDescriptor(name="customer_name", kind=FieldKind.PERSON, label="Customer"),
    FieldDescriptor(name="customer_email", kind=FieldKind.TEXT, label="Email", pii=True),
    FieldDescriptor(name="orders", kind=FieldKind.COUNT, label="Orders"),
    FieldDescriptor(name="spent", kind=FieldKind.MONEY, label="Lifetime spend", currency="GBP"),
    FieldDescriptor(name="since", kind=FieldKind.DATETIME, label="Customer since"),
    FieldDescriptor(name="standing", kind=FieldKind.STATUS, label="Standing"),
    FieldDescriptor(name="first_order_at", kind=FieldKind.DATETIME, label="First order"),
    FieldDescriptor(name="other_unfulfilled", kind=FieldKind.TEXT, label="Other orders still to ship"),
]


def from_shopify_customer_history(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    record = {
        "customer_name": result.get("name"),
        "customer_email": result.get("email"),
        "orders": result.get("orders"),
        "spent": _parse_money(result.get("spent")),
        "since": result.get("since"),
        "standing": result.get("standing"),
        "first_order_at": result.get("first_order_at"),
        "other_unfulfilled": ", ".join(str(o) for o in result.get("other_unfulfilled") or []),
    }
    return Evidence(
        handle=handle, source_tool="shopify_customer_history", observed_at=observed_at,
        query_summary=f"Shopify customer history for {result.get('name') or result.get('customer_id') or ''}",
        fields=_CUSTOMER_HISTORY_FIELDS, records=[record],
    )


_CUSTOMER_SEARCH_FIELDS = [
    FieldDescriptor(name="customer_name", kind=FieldKind.PERSON, label="Customer"),
    FieldDescriptor(name="customer_email", kind=FieldKind.TEXT, label="Email", pii=True),
    FieldDescriptor(name="orders", kind=FieldKind.COUNT, label="Orders"),
    FieldDescriptor(name="spent", kind=FieldKind.MONEY, label="Lifetime spend", currency="GBP"),
]


def from_shopify_find_customer(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [
        {
            "customer_name": c.get("name"),
            "customer_email": c.get("email"),
            "orders": c.get("orders"),
            "spent": _parse_money(c.get("spent")),
        }
        for c in result.get("customers") or []
    ]
    return Evidence(
        handle=handle, source_tool="shopify_find_customer", observed_at=observed_at,
        query_summary=f"Shopify customers matching {result.get('query') or ''}".strip(),
        fields=_CUSTOMER_SEARCH_FIELDS, records=records,
    )


_INVENTORY_FIELDS = [
    FieldDescriptor(name="product", kind=FieldKind.TEXT, label="Product"),
    FieldDescriptor(name="variant", kind=FieldKind.TEXT, label="Variant"),
    FieldDescriptor(name="sku", kind=FieldKind.TEXT, label="SKU"),
    FieldDescriptor(name="available", kind=FieldKind.COUNT, label="Available"),
    FieldDescriptor(name="tracked", kind=FieldKind.STATUS, label="Tracked"),
]


def from_shopify_inventory(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [
        {
            "product": p.get("title"),
            "variant": v.get("variant"),
            "sku": v.get("sku"),
            "available": v.get("available"),
            "tracked": v.get("tracked"),
        }
        for p in result.get("products") or []
        for v in p.get("variants") or []
    ]
    return Evidence(
        handle=handle, source_tool="shopify_inventory", observed_at=observed_at,
        query_summary=f"Shopify stock for {result.get('product') or ''}".strip(),
        fields=_INVENTORY_FIELDS, records=records,
    )


_SALES_SUMMARY_FIELDS = [
    FieldDescriptor(name="orders", kind=FieldKind.COUNT, label="Orders"),
    FieldDescriptor(name="revenue", kind=FieldKind.MONEY, label="Revenue", currency="GBP"),
    FieldDescriptor(name="complete", kind=FieldKind.STATUS, label="Complete"),
    FieldDescriptor(name="by_day", kind=FieldKind.SERIES, label="Revenue by day"),
]


def from_shopify_sales_summary(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    currency = result.get("currency") or "GBP"
    by_day = [series_point(b.get("date"), b.get("revenue")) for b in result.get("by_day") or []]
    record = {
        "orders": result.get("orders"),
        "revenue": money(result.get("revenue") or 0.0, currency),
        "complete": result.get("complete"),
        "by_day": by_day,
    }
    return Evidence(
        handle=handle, source_tool="shopify_sales_summary", observed_at=observed_at,
        query_summary=f"Shopify sales, {result.get('since', '')} to {result.get('until', '')}",
        fields=_SALES_SUMMARY_FIELDS, records=[record],
    )


_PRODUCT_INFO_FIELDS = [
    FieldDescriptor(name="title", kind=FieldKind.TEXT, label="Product"),
    FieldDescriptor(name="status", kind=FieldKind.STATUS, label="Status"),
    FieldDescriptor(name="description", kind=FieldKind.TEXT, label="Description"),
]


def from_shopify_product_info(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [
        {"title": p.get("title"), "status": p.get("status"), "description": p.get("description") or ""}
        for p in result.get("products") or []
    ]
    return Evidence(
        handle=handle, source_tool="shopify_product_info", observed_at=observed_at,
        query_summary=f"Shopify product info for {result.get('product') or ''}".strip(),
        fields=_PRODUCT_INFO_FIELDS, records=records,
    )


_VARIANT_SEARCH_FIELDS = [
    FieldDescriptor(name="product", kind=FieldKind.TEXT, label="Product"),
    FieldDescriptor(name="variant", kind=FieldKind.TEXT, label="Variant"),
    FieldDescriptor(name="sku", kind=FieldKind.TEXT, label="SKU"),
    FieldDescriptor(name="price", kind=FieldKind.MONEY, label="Price", currency="GBP"),
    FieldDescriptor(name="available", kind=FieldKind.COUNT, label="Available"),
    FieldDescriptor(name="for_sale", kind=FieldKind.STATUS, label="For sale"),
]


def from_shopify_variant_search(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [
        {
            "product": c.get("title"),
            "variant": c.get("variant"),
            "sku": c.get("sku"),
            "price": money(float(c["price"]), "GBP") if c.get("price") else None,
            "available": c.get("available"),
            "for_sale": c.get("for_sale"),
        }
        for c in result.get("candidates") or []
    ]
    asked = " ".join(v for v in (result.get("asked") or {}).values() if v)
    return Evidence(
        handle=handle, source_tool="shopify_variant_search", observed_at=observed_at,
        query_summary=f"Shopify variants matching {asked}".strip(),
        fields=_VARIANT_SEARCH_FIELDS, records=records,
    )


# --------------------------------------------------------------------------------- gmail_tools

_THREAD_FIELDS = [
    FieldDescriptor(name="from_name", kind=FieldKind.PERSON, label="From"),
    FieldDescriptor(name="from_email", kind=FieldKind.TEXT, label="Email", pii=True),
    FieldDescriptor(name="subject", kind=FieldKind.TEXT, label="Subject"),
    FieldDescriptor(name="date", kind=FieldKind.DATETIME, label="Date"),
    FieldDescriptor(name="snippet", kind=FieldKind.TEXT, label="Snippet"),
    FieldDescriptor(name="likely_bulk", kind=FieldKind.STATUS, label="Likely bulk"),
    FieldDescriptor(name="authenticated", kind=FieldKind.STATUS, label="Authenticated"),
]


def _thread_record(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "from_name": t.get("from"),
        "from_email": t.get("from_email"),
        "subject": t.get("subject"),
        "date": t.get("date"),
        "snippet": t.get("snippet"),
        "likely_bulk": bool(t.get("likely_bulk")),
        "authenticated": bool(t.get("authenticated")),
    }


def from_gmail_search(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [_thread_record(t) for t in result.get("threads") or []]
    return Evidence(
        handle=handle, source_tool="gmail_search", observed_at=observed_at,
        query_summary=f"Gmail search: {result.get('query') or ''}".strip(),
        fields=_THREAD_FIELDS, records=records,
    )


_MESSAGE_FIELDS = [
    FieldDescriptor(name="from_name", kind=FieldKind.PERSON, label="From"),
    FieldDescriptor(name="from_email", kind=FieldKind.TEXT, label="Email", pii=True),
    FieldDescriptor(name="subject", kind=FieldKind.TEXT, label="Subject"),
    FieldDescriptor(name="date", kind=FieldKind.DATETIME, label="Date"),
    FieldDescriptor(name="body", kind=FieldKind.TEXT, label="Body"),
    FieldDescriptor(name="outbound", kind=FieldKind.STATUS, label="Outbound"),
]


def from_gmail_read_thread(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [
        {
            "from_name": m.get("from"),
            "from_email": m.get("from_email"),
            "subject": m.get("subject"),
            "date": m.get("date"),
            "body": m.get("body"),
            "outbound": bool(m.get("outbound")),
        }
        for m in result.get("messages") or []
    ]
    return Evidence(
        handle=handle, source_tool="gmail_read_thread", observed_at=observed_at,
        query_summary=f"Gmail thread {result.get('thread_id') or ''}",
        fields=_MESSAGE_FIELDS, records=records,
    )


_MATCH_FIELDS = [
    FieldDescriptor(name="subject", kind=FieldKind.TEXT, label="Subject"),
    FieldDescriptor(name="date", kind=FieldKind.DATETIME, label="Date"),
    FieldDescriptor(name="from_email", kind=FieldKind.TEXT, label="Email", pii=True),
    FieldDescriptor(name="where", kind=FieldKind.STATUS, label="Where"),
    FieldDescriptor(name="excerpt", kind=FieldKind.TEXT, label="Excerpt"),
]


def from_gmail_find_in_email(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [
        {
            "subject": m.get("subject"),
            "date": m.get("date"),
            "from_email": m.get("from"),
            "where": m.get("where"),
            "excerpt": m.get("excerpt"),
        }
        for m in result.get("matches") or []
    ]
    return Evidence(
        handle=handle, source_tool="gmail_find_in_email", observed_at=observed_at,
        query_summary=f"Gmail search for {result.get('contains') or ''}".strip(),
        fields=_MATCH_FIELDS, records=records,
    )


# ---------------------------------------------------------------------------- analytics_tools

# commerce_aggregate, commerce_query (customers) and inventory_query all shape their rows the
# same way (app/analytics/engine.py `_row`): a "key" of the group_by labels, and one entry per
# metric. What each group and metric IS — its kind, its unit or currency — is fixed by the
# query language itself (app/analytics/query.py GROUPS, METRICS), so one table describes them
# for every tool built on it, rather than one per tool.
_GROUP_FIELD: dict[str, tuple[str, FieldKind]] = {
    "product": ("Product", FieldKind.TEXT),
    "product_type": ("Product type", FieldKind.TEXT),
    "variant": ("Variant", FieldKind.TEXT),
    "size": ("Size", FieldKind.TEXT),
    "colour": ("Colour", FieldKind.TEXT),
    "day": ("Day", FieldKind.DATETIME),
    "week": ("Week", FieldKind.DATETIME),
    "month": ("Month", FieldKind.DATETIME),
    "customer": ("Customer", FieldKind.PERSON),
    "country": ("Country", FieldKind.TEXT),
    "fulfillment": ("Fulfilment", FieldKind.STATUS),
    "payment": ("Payment", FieldKind.STATUS),
}

_METRIC_FIELD: dict[str, tuple[str, FieldKind, str | None, str | None]] = {
    "units": ("Units", FieldKind.COUNT, None, None),
    "revenue": ("Revenue", FieldKind.MONEY, None, "GBP"),
    "orders": ("Orders", FieldKind.COUNT, None, None),
    "customers": ("Customers", FieldKind.COUNT, None, None),
    "aov": ("Average order value", FieldKind.MONEY, None, "GBP"),
    "refunded": ("Refunded", FieldKind.MONEY, None, "GBP"),
    "unfulfilled_units": ("Unfulfilled units", FieldKind.COUNT, None, None),
    "unfulfilled_value": ("Unfulfilled value", FieldKind.MONEY, None, "GBP"),
    "share": ("Share of units", FieldKind.RATIO, "%", None),
    "stock": ("Stock", FieldKind.COUNT, None, None),
    "velocity": ("Velocity", FieldKind.RATIO, "units/day", None),
    "days_cover": ("Days of cover", FieldKind.DURATION, "days", None),
    "lifetime_orders": ("Lifetime orders", FieldKind.COUNT, None, None),
    "lifetime_spent": ("Lifetime spend", FieldKind.MONEY, None, "GBP"),
    "last_order_at": ("Last order", FieldKind.DATETIME, None, None),
    "first_order_at": ("First order", FieldKind.DATETIME, None, None),
    "age_days": ("Age", FieldKind.DURATION, "days", None),
}


def _bucket_fields(group_by: list[str], metrics: list[str], entity: str) -> list[FieldDescriptor]:
    fields: list[FieldDescriptor] = []
    for group in group_by:
        label, kind = _GROUP_FIELD.get(group, (group.replace("_", " ").title(), FieldKind.TEXT))
        fields.append(FieldDescriptor(name=group, kind=kind, label=label))
        if group == "customer" and entity == "customers":
            fields.append(FieldDescriptor(name="customer_email", kind=FieldKind.TEXT, label="Email", pii=True))
    for metric in metrics:
        spec = _METRIC_FIELD.get(metric)
        if spec is None:
            continue
        label, kind, unit, currency = spec
        fields.append(FieldDescriptor(name=metric, kind=kind, label=label, unit=unit, currency=currency))
    return fields


def _bucket_record(row: dict[str, Any], group_by: list[str], metrics: list[str], entity: str) -> dict[str, Any]:
    key = row.get("key") or {}
    record: dict[str, Any] = {group: key.get(group) for group in group_by}
    if entity == "customers" and "customer" in group_by:
        record["customer_email"] = key.get("customer_email")
    for metric in metrics:
        spec = _METRIC_FIELD.get(metric)
        if spec is None:
            continue
        _, kind, _, currency = spec
        value = row.get(metric)
        record[metric] = money(value, currency) if kind == FieldKind.MONEY and value is not None else value
    return record


def _bucket_evidence(result: dict[str, Any], *, handle: str, source_tool: str, observed_at: datetime | str, query_summary: str) -> Evidence:
    group_by = list(result.get("group_by") or [])
    metrics = list(result.get("metrics") or [])
    entity = str(result.get("entity") or "")
    records = [_bucket_record(r, group_by, metrics, entity) for r in result.get("rows") or []]
    return Evidence(
        handle=handle, source_tool=source_tool, observed_at=observed_at, query_summary=query_summary,
        fields=_bucket_fields(group_by, metrics, entity), records=records,
    )


def _period_summary(result: dict[str, Any]) -> str:
    period = result.get("period")
    label = period.get("label") if isinstance(period, dict) else None
    return str(label or "recent activity")


def from_commerce_aggregate(result: dict[str, Any], *, handle: str, observed_at: datetime | str, query_summary: str = "") -> Evidence:
    return _bucket_evidence(
        result, handle=handle, source_tool="commerce_aggregate", observed_at=observed_at,
        query_summary=query_summary or _period_summary(result),
    )


def from_inventory_query(result: dict[str, Any], *, handle: str, observed_at: datetime | str, query_summary: str = "") -> Evidence:
    return _bucket_evidence(
        result, handle=handle, source_tool="inventory_query", observed_at=observed_at,
        query_summary=query_summary or f"Restock priority, {_period_summary(result)}",
    )


_ORDER_LISTING_FIELDS = [
    FieldDescriptor(name="order_number", kind=FieldKind.TEXT, label="Order"),
    FieldDescriptor(name="order_link", kind=FieldKind.LINK, label="Order"),
    FieldDescriptor(name="placed_at", kind=FieldKind.DATETIME, label="Placed"),
    FieldDescriptor(name="age_days", kind=FieldKind.DURATION, label="Age", unit="days"),
    FieldDescriptor(name="fulfillment", kind=FieldKind.STATUS, label="Fulfilment"),
    FieldDescriptor(name="payment", kind=FieldKind.STATUS, label="Payment"),
    FieldDescriptor(name="total", kind=FieldKind.MONEY, label="Total", currency="GBP"),
    FieldDescriptor(name="customer_name", kind=FieldKind.PERSON, label="Customer"),
    FieldDescriptor(name="customer_email", kind=FieldKind.TEXT, label="Email", pii=True),
    FieldDescriptor(name="country_code", kind=FieldKind.TEXT, label="Country"),
    FieldDescriptor(name="items", kind=FieldKind.COUNT, label="Items"),
    FieldDescriptor(name="tags", kind=FieldKind.TEXT, label="Tags"),
    FieldDescriptor(name="has_tracking", kind=FieldKind.STATUS, label="Has tracking"),
    FieldDescriptor(name="cancelled", kind=FieldKind.STATUS, label="Cancelled"),
]


def _order_listing_record(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_number": r.get("order_number"),
        "order_link": {"ref": r.get("order_id"), "label": r.get("order_number") or ""},
        "placed_at": r.get("placed_at"),
        "age_days": r.get("age_days"),
        "fulfillment": r.get("fulfillment"),
        "payment": r.get("payment"),
        "total": money(r.get("total") or 0.0, r.get("currency") or "GBP"),
        "customer_name": r.get("customer_name"),
        "customer_email": r.get("customer_email"),
        "country_code": r.get("country_code"),
        "items": r.get("items"),
        "tags": ", ".join(r.get("tags") or []),
        "has_tracking": bool(r.get("has_tracking")),
        "cancelled": bool(r.get("cancelled")),
    }


def from_commerce_query(result: dict[str, Any], *, handle: str, observed_at: datetime | str, query_summary: str = "") -> Evidence:
    entity = str(result.get("entity") or "orders")
    summary = query_summary or _period_summary(result)
    if entity == "orders":
        records = [_order_listing_record(r) for r in result.get("rows") or []]
        return Evidence(
            handle=handle, source_tool="commerce_query", observed_at=observed_at, query_summary=summary,
            fields=_ORDER_LISTING_FIELDS, records=records,
        )
    return _bucket_evidence(result, handle=handle, source_tool="commerce_query", observed_at=observed_at, query_summary=summary)


EMAIL_QUERY_FIELDS = [
    FieldDescriptor(name="customer_name", kind=FieldKind.PERSON, label="Customer"),
    FieldDescriptor(name="customer_email", kind=FieldKind.TEXT, label="Email", pii=True),
    FieldDescriptor(name="orders", kind=FieldKind.TEXT, label="Orders"),
    FieldDescriptor(name="emailed", kind=FieldKind.STATUS, label="Emailed us"),
    FieldDescriptor(name="threads", kind=FieldKind.COUNT, label="Threads"),
    FieldDescriptor(name="last_subject", kind=FieldKind.TEXT, label="Last subject"),
    FieldDescriptor(name="last_date", kind=FieldKind.TEXT, label="Last date"),
    FieldDescriptor(name="latest_direction", kind=FieldKind.STATUS, label="Latest direction"),
    FieldDescriptor(name="needs_reply", kind=FieldKind.STATUS, label="Needs a reply"),
    FieldDescriptor(name="confidence", kind=FieldKind.STATUS, label="Confidence"),
    FieldDescriptor(name="related_orders", kind=FieldKind.TEXT, label="Related orders"),
]


def from_email_query(result: dict[str, Any], *, handle: str, observed_at: datetime | str) -> Evidence:
    records = [
        {
            "customer_name": r.get("customer_name"),
            "customer_email": r.get("customer_email"),
            "orders": ", ".join(str(o) for o in r.get("orders") or [] if o),
            "emailed": bool(r.get("emailed")),
            "threads": int(r.get("threads") or 0),
            "last_subject": r.get("last_subject") or "",
            "last_date": r.get("last_date") or "",
            "latest_direction": r.get("latest_direction") or "none",
            "needs_reply": bool(r.get("needs_reply")),
            "confidence": r.get("confidence") or "none",
            "related_orders": ", ".join(str(o) for o in r.get("related_orders") or [] if o),
        }
        for r in result.get("rows") or []
    ]
    return Evidence(
        handle=handle, source_tool="email_query", observed_at=observed_at,
        query_summary=f"Email check for {result.get('set_label') or result.get('set_id') or 'a set'}, last {result.get('days')} days",
        fields=EMAIL_QUERY_FIELDS, records=records,
    )
