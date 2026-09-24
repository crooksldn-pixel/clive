"""The aggregation engine: pure functions over the cached order rows. Given a checked query,
the rows covering its period (and the one before, for a comparison), the stock the tool
fetched and the working sets the session holds, it answers with rows, totals, what was
measured and what was derived. No store, no clock beyond the one passed in."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.analytics.periods import Period
from app.analytics.query import DEFAULT_SHOP_COUNTRY, DERIVED, MEASURED, METRICS, Query
from app.analytics.sets import MAX_MEMBERS

MAX_SAMPLE = 5


def _local(ts: float, zone: ZoneInfo) -> datetime:
    return datetime.fromtimestamp(ts, UTC).astimezone(zone)


def _whole_days(now: float, ts: float) -> int:
    """How many whole days have actually passed, floored from the raw difference.

    Never from a value already rounded to one decimal place: an order 14 days and 22h51m old
    is 14.9520... raw, which rounds to 14.9 for display — but once the raw fraction reaches
    .95 that rounding ticks over to 15.0, and a caller that floors the ROUNDED figure then
    reports a day more than has actually passed, for the last ~5% of every day. Flooring the
    unrounded seconds instead is right at every minute, not just most of them.
    """
    return int((now - ts) // 86400)


def _text_match(needle: str, *haystacks: Any) -> bool:
    n = needle.casefold()
    return any(n in str(h or "").casefold() for h in haystacks)


def _words_match(needle: str, item: dict[str, Any]) -> bool:
    """"pink joggers" matches an item whose product, type, sku, variant or colour carry every
    word of it — the owner names things the way the label prints them, in any order."""
    haystack = " ".join(str(item.get(k) or "") for k in ("product", "product_type", "sku", "variant", "colour", "size")).casefold()
    words = [w for w in needle.casefold().split() if w]
    return bool(words) and all(w in haystack for w in words)


def _item_matches(item: dict[str, Any], filters: dict[str, Any]) -> bool:
    if "product" in filters and not _words_match(filters["product"], item):
        return False
    if "product_id" in filters and item.get("product_id") != filters["product_id"]:
        return False
    if "variant_id" in filters and item.get("variant_id") != filters["variant_id"]:
        return False
    if "sku" in filters and not _text_match(filters["sku"], item.get("sku")):
        return False
    # "variant" as words rather than an id: "black / m" names the variant the label prints,
    # and the sku is checked too because half the shop calls the variant by its code.
    if "variant" in filters and not _text_match(filters["variant"], item.get("variant"), item.get("sku")):
        return False
    if "size" in filters and str(item.get("size") or "").casefold() != filters["size"].casefold():
        return False
    if "colour" in filters and str(item.get("colour") or "").casefold() != filters["colour"].casefold():
        return False
    if "product_type" in filters and not _text_match(filters["product_type"], item.get("product_type")):
        return False
    return True


_ITEM_FILTERS = ("product", "product_id", "variant", "variant_id", "sku", "size", "colour", "product_type")


# What Shopify's financial status may be for each payment filter. Only the ones that are a
# SET need saying: "unpaid" is every state that is not money in the bank, and Shopify has no
# single word for it. Anything else is its own name, as it always was.
_PAYMENT_STATES = {
    "unpaid": ("PENDING", "AUTHORIZED", "PARTIALLY_PAID", "EXPIRED", "VOIDED"),
}


def order_matches(order: dict[str, Any], filters: dict[str, Any], *, now: float, sets: dict[str, frozenset[str]] | None = None,
                  shop_country: str = "") -> bool:
    """Whether an order passes the order-level filters. Item-level filters pass when any item
    matches; the items themselves are narrowed by `matching_items`.

    `shop_country` is the other half of the "international" filter — where the shop ships
    from. It is passed in, never looked up: this file reads no store and no settings.
    """
    cancelled = filters.get("cancelled", "false")
    if cancelled == "false" and order.get("cancelled"):
        return False
    if cancelled == "true" and not order.get("cancelled"):
        return False
    fulfillment = filters.get("fulfillment")
    if fulfillment and fulfillment != "any":
        state = str(order.get("fulfillment") or "").upper()
        wanted = {"unfulfilled": ("UNFULFILLED", "PARTIALLY_FULFILLED", "SCHEDULED", "ON_HOLD", "IN_PROGRESS", "OPEN"), "partial": ("PARTIALLY_FULFILLED",), "fulfilled": ("FULFILLED",)}[fulfillment]
        if state not in wanted:
            return False
    payment = filters.get("payment")
    if payment and payment != "any":
        state = str(order.get("financial") or "").upper()
        if state not in _PAYMENT_STATES.get(payment, (payment.upper(),)):
            return False
    if "has_tracking" in filters and bool(order.get("has_tracking")) != filters["has_tracking"]:
        return False
    customer = order.get("customer") or {}
    if "customer_id" in filters and customer.get("customer_id") != filters["customer_id"]:
        return False
    if "customer_email" in filters and str(customer.get("email") or "").casefold() != filters["customer_email"].casefold():
        return False
    if "country_code" in filters and str(order.get("country_code") or "").upper() != filters["country_code"]:
        return False
    if "international" in filters:
        home = (shop_country or DEFAULT_SHOP_COUNTRY).upper()
        where = str(order.get("country_code") or "").upper()
        # An order with no shipping country — a digital order, or an address Shopify withheld —
        # is neither international nor domestic. It is left out of both rather than counted as
        # home: "which of these are going abroad" must not answer with a guess.
        if not where or filters["international"] != (where != home):
            return False
    if "city" in filters and not _text_match(filters["city"], order.get("city")):
        return False
    tags = {str(t).casefold() for t in order.get("tags") or []}
    if "tags" in filters and not all(t.casefold() in tags for t in filters["tags"]):
        return False
    if "not_tags" in filters and any(t.casefold() in tags for t in filters["not_tags"]):
        return False
    total = float(order.get("total") or 0.0)
    if "min_total" in filters and total < filters["min_total"]:
        return False
    if "max_total" in filters and total > filters["max_total"]:
        return False
    age_days = (now - float(order.get("ts") or now)) / 86400
    if "older_than_days" in filters and age_days < filters["older_than_days"]:
        return False
    if "newer_than_days" in filters and age_days > filters["newer_than_days"]:
        return False
    if "in_set" in filters:
        members = (sets or {}).get(filters["in_set"], frozenset())
        if not _in_set(order, members):
            return False
    if "not_in_set" in filters:
        members = (sets or {}).get(filters["not_in_set"], frozenset())
        if _in_set(order, members):
            return False
    if any(k in filters for k in _ITEM_FILTERS) and not any(_item_matches(i, filters) for i in order.get("items") or []):
        return False
    return True


def _in_set(order: dict[str, Any], members: frozenset[str]) -> bool:
    if order.get("order_id") in members:
        return True
    customer = order.get("customer") or {}
    if customer.get("customer_id") in members:
        return True
    return any(i.get("variant_id") in members or i.get("product_id") in members for i in order.get("items") or [])


def matching_items(order: dict[str, Any], filters: dict[str, Any]) -> list[dict[str, Any]]:
    if not any(k in filters for k in _ITEM_FILTERS):
        return list(order.get("items") or [])
    return [i for i in order.get("items") or [] if _item_matches(i, filters)]


def select(rows: list[dict[str, Any]], period: Period, filters: dict[str, Any], *, now: float, sets: dict[str, frozenset[str]] | None = None,
           shop_country: str = "") -> list[dict[str, Any]]:
    start, end = period.start.timestamp(), period.end.timestamp()
    return [o for o in rows if start <= float(o.get("ts") or 0) < end and order_matches(o, filters, now=now, sets=sets, shop_country=shop_country)]


# --------------------------------------------------------------------- grouping keys


def _key_for(group: str, order: dict[str, Any], item: dict[str, Any] | None, zone: ZoneInfo) -> tuple[str, str]:
    """(label, id) for one grouping dimension."""
    if group == "product":
        return (str((item or {}).get("product") or "—"), str((item or {}).get("product_id") or ""))
    if group == "product_type":
        return (str((item or {}).get("product_type") or "—"), "")
    if group == "variant":
        i = item or {}
        label = str(i.get("product") or "—") + (f" · {i.get('variant')}" if i.get("variant") else "")
        return (label, str(i.get("variant_id") or ""))
    if group == "size":
        return (str((item or {}).get("size") or "—"), "")
    if group == "colour":
        return (str((item or {}).get("colour") or "—"), "")
    if group == "customer":
        c = order.get("customer") or {}
        return (str(c.get("name") or c.get("email") or "—"), str(c.get("customer_id") or ""))
    if group == "country":
        return (str(order.get("country_code") or "—"), "")
    if group == "fulfillment":
        return (str(order.get("fulfillment") or "—").lower().replace("_", " "), "")
    if group == "payment":
        return (str(order.get("financial") or "—").lower().replace("_", " "), "")
    local = _local(float(order.get("ts") or 0), zone)
    if group == "day":
        return (local.date().isoformat(), "")
    if group == "week":
        monday = (local - timedelta(days=local.weekday())).date()
        return (f"week of {monday.isoformat()}", monday.isoformat())
    if group == "month":
        return (local.strftime("%Y-%m"), "")
    return ("—", "")


_ITEM_GROUPS = frozenset({"product", "product_type", "variant", "size", "colour"})


class _Bucket:
    __slots__ = ("keys", "units", "revenue", "orders", "customers", "refunded", "unfulfilled_units", "unfulfilled_value", "stock", "stock_known", "lifetime_orders", "lifetime_spent", "first_ts", "last_ts", "variant_ids", "sample", "customer")

    def __init__(self, keys: tuple[tuple[str, str], ...]) -> None:
        self.keys = keys
        self.units = 0
        self.revenue = 0.0
        self.orders: set[str] = set()
        self.customers: set[str] = set()
        self.refunded = 0.0
        self.unfulfilled_units = 0
        self.unfulfilled_value = 0.0
        self.stock: int | None = None
        self.stock_known = False
        self.lifetime_orders = 0
        self.lifetime_spent = 0.0
        self.first_ts = 0.0
        self.last_ts = 0.0
        self.variant_ids: set[str] = set()
        self.sample: list[dict[str, Any]] = []
        self.customer: dict[str, Any] | None = None


def aggregate(
    query: Query, rows: list[dict[str, Any]], *, now: float, tz: str | ZoneInfo = "Europe/London",
    stock: dict[str, dict[str, Any]] | None = None, sets: dict[str, frozenset[str]] | None = None, previous_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The answer to a grouped query (or an orders listing): rows sorted and bounded, totals,
    and — when asked — the same for the period before, with the change between them."""
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    body = _aggregate_period(query, query.period, rows, now=now, zone=zone, stock=stock, sets=sets)
    out: dict[str, Any] = {
        "entity": query.entity, "period": query.period.as_dict(), "filters": {k: v for k, v in query.filters.items() if not (k == "cancelled" and v == "false")},
        "group_by": list(query.group_by), "metrics": list(query.metrics), "sort": [f"{k} {d}" for k, d in query.sort], "limit": query.limit,
        **body,
        # A refund is the order's; shared out over its lines it is an estimate, and says so.
        "measured": [m for m in METRICS if m in query.metrics and m in MEASURED and not (m == "refunded" and body.get("item_level"))],
        "derived": [m for m in METRICS if m in query.metrics and (m in DERIVED or (m == "refunded" and body.get("item_level")))],
        "view": query.view, "title": query.title,
    }
    if query.compare:
        previous = query.period.previous()
        before = _aggregate_period(query, previous, previous_rows if previous_rows is not None else rows, now=now, zone=zone, stock=stock, sets=sets)
        change = {}
        for metric, value in body["totals"].items():
            was = before["totals"].get(metric)
            if isinstance(value, (int, float)) and isinstance(was, (int, float)) and not isinstance(value, bool):
                change[metric] = {"from": was, "to": value, "delta": round(value - was, 2), "pct": (round((value - was) / was * 100, 1) if was else None)}
        out["compare"] = {"period": previous.as_dict(), "totals": before["totals"], "rows": before["rows"][: query.limit], "change": change}
    return out


def _aggregate_period(query: Query, period: Period, rows: list[dict[str, Any]], *, now: float, zone: ZoneInfo, stock: dict[str, dict[str, Any]] | None, sets: dict[str, frozenset[str]] | None) -> dict[str, Any]:
    # The shop's country travels with the query (app/analytics/query.py resolves it once), so
    # the tool, the fast recipe and a test all compare an order's destination with the same
    # home country.
    orders = select(rows, period, query.filters, now=now, sets=sets, shop_country=str(query.extra.get("shop_country") or ""))
    if query.entity == "orders":
        return _orders_listing(query, orders, now=now, zone=zone)
    groups = tuple(query.group_by) if query.group_by else ()
    item_level = query.entity in ("order_line_items", "products", "variants") or any(g in _ITEM_GROUPS for g in groups)
    buckets: dict[tuple[tuple[str, str], ...], _Bucket] = {}
    total = _Bucket(())
    for order in orders:
        items = matching_items(order, query.filters) if item_level else []
        if item_level and not items:
            continue
        targets: list[tuple[tuple[tuple[str, str], ...], dict[str, Any] | None]] = []
        if item_level:
            for item in items:
                targets.append((tuple(_key_for(g, order, item, zone) for g in groups), item))
        else:
            targets.append((tuple(_key_for(g, order, None, zone) for g in groups), None))
        for keys, item in targets:
            bucket = buckets.get(keys)
            if bucket is None:
                bucket = buckets[keys] = _Bucket(keys)
            for b in (bucket, total):
                _fold(b, order, item, item_level)
    if query.entity == "customers":
        _lifetime(buckets, orders)
        _lifetime({(): total}, orders)
        if query.filters.get("repeat") is not None or "min_orders" in query.filters or "max_orders" in query.filters or "min_spent" in query.filters or "max_spent" in query.filters or query.filters.get("no_later_order"):
            buckets = {k: b for k, b in buckets.items() if _customer_passes(b, query.filters, rows, period)}
    if query.needs_stock:
        for b in buckets.values():
            _stock_for(b, stock or {})
        _stock_for(total, stock or {})
    if "min_units" in query.filters:
        buckets = {k: b for k, b in buckets.items() if b.units >= query.filters["min_units"]}
    if "max_stock" in query.filters:
        buckets = {k: b for k, b in buckets.items() if b.stock is not None and b.stock <= query.filters["max_stock"]}
    total_units = sum(b.units for b in buckets.values()) or total.units
    shaped = [_row(b, query, period, now=now, zone=zone, total_units=total_units) for b in buckets.values()]
    shaped = _sorted(shaped, query.sort)
    truncated = len(shaped) > query.limit
    out = {
        "rows": shaped[: query.limit], "row_count": len(shaped), "truncated": truncated,
        "totals": _totals(total, query, period, now=now, zone=zone, orders=len(orders)),
        "orders_in_period": len(orders), "currency": next((str(o.get("currency")) for o in orders if o.get("currency")), "GBP"),
        # What "revenue" is here: line values after discounts for anything broken down by
        # item, the order's total (shipping and tax in) for orders as wholes.
        "revenue_basis": "line items after discounts, before shipping and tax" if item_level else "order totals, shipping and tax included",
        "item_level": item_level,
    }
    if "refunded" in query.metrics:
        # A refund is counted against the order it was made on, in the period that order was
        # placed — not in the period the refund was made.
        out["refunded_basis"] = "refunds against orders placed in the period, not refunds made in it"
    id_key = {"customers": "customer_id", "products": "product_id", "variants": "variant_id"}.get(query.entity)
    if id_key:
        # Every member the ranking matched, for a working set — the rows are the few shown;
        # "everyone who spent over £250" is all of them unless a limit was asked for.
        chosen = shaped[: query.limit] if query.limit_explicit else shaped
        out["member_ids"] = list(dict.fromkeys(str(r["key"][id_key]) for r in chosen if r.get("key", {}).get(id_key)))[:MAX_MEMBERS]
        out["member_labels"] = {str(r["key"][id_key]): str(r.get("label") or "") for r in chosen if r.get("key", {}).get(id_key)}
    return out


def _fold(b: _Bucket, order: dict[str, Any], item: dict[str, Any] | None, item_level: bool) -> None:
    order_id = str(order.get("order_id") or "")
    customer_id = str((order.get("customer") or {}).get("customer_id") or "")
    new_order = order_id not in b.orders
    b.orders.add(order_id)
    if customer_id:
        b.customers.add(customer_id)
    if item_level and item is not None:
        quantity = int(item.get("quantity") or 0)
        line_total = float(item.get("total") or 0.0)
        b.units += quantity
        b.revenue += line_total
        unfulfilled = int(item.get("unfulfilled_quantity") or 0)
        b.unfulfilled_units += unfulfilled
        # Money at the item's own level: what is still to ship is this line's unfulfilled
        # units at this line's price; a refund is the order's, shared out by the line's share
        # of the order (marked derived by the caller). Never the whole order's figure on
        # every one of its products.
        if quantity and unfulfilled and not order.get("cancelled"):
            b.unfulfilled_value += line_total * unfulfilled / quantity
        order_total = float(order.get("total") or 0.0)
        if order_total > 0 and float(order.get("refunded") or 0.0):
            b.refunded += float(order["refunded"]) * min(1.0, line_total / order_total)
        if item.get("variant_id"):
            b.variant_ids.add(str(item["variant_id"]))
        if len(b.sample) < MAX_SAMPLE and new_order:
            b.sample.append({"order_id": order_id, "order_number": order.get("order_number")})
    elif new_order:
        b.units += int(order.get("units") or sum(int(i.get("quantity") or 0) for i in order.get("items") or []))
        b.revenue += float(order.get("total") or 0.0)
        b.unfulfilled_units += int(order.get("unfulfilled_units") or 0)
        b.refunded += float(order.get("refunded") or 0.0)
        if str(order.get("fulfillment") or "").upper() != "FULFILLED" and not order.get("cancelled"):
            b.unfulfilled_value += float(order.get("total") or 0.0)
        if len(b.sample) < MAX_SAMPLE:
            b.sample.append({"order_id": order_id, "order_number": order.get("order_number")})
    if new_order:
        ts = float(order.get("ts") or 0)
        b.first_ts = ts if not b.first_ts or ts < b.first_ts else b.first_ts
        b.last_ts = max(b.last_ts, ts)
        if b.customer is None and order.get("customer"):
            b.customer = dict(order["customer"])


def _lifetime(buckets: dict, orders: list[dict[str, Any]]) -> None:
    for b in buckets.values():
        if b.keys and b.customer:
            b.lifetime_orders = int(b.customer.get("orders") or 0)
            b.lifetime_spent = float(b.customer.get("spent") or 0.0)
        elif not b.keys:
            seen: dict[str, dict[str, Any]] = {}
            for o in orders:
                c = o.get("customer") or {}
                if c.get("customer_id"):
                    seen[c["customer_id"]] = c
            b.lifetime_orders = sum(int(c.get("orders") or 0) for c in seen.values())
            b.lifetime_spent = round(sum(float(c.get("spent") or 0.0) for c in seen.values()), 2)


def _customer_passes(b: _Bucket, filters: dict[str, Any], rows: list[dict[str, Any]], period: Period) -> bool:
    if "min_orders" in filters and b.lifetime_orders < filters["min_orders"]:
        return False
    if "max_orders" in filters and b.lifetime_orders > filters["max_orders"]:
        return False
    if "min_spent" in filters and b.lifetime_spent < filters["min_spent"]:
        return False
    if "max_spent" in filters and b.lifetime_spent > filters["max_spent"]:
        return False
    if filters.get("repeat") is True and b.lifetime_orders < 2:
        return False
    if filters.get("repeat") is False and b.lifetime_orders >= 2:
        return False
    if filters.get("no_later_order"):
        # Their latest order the Mac holds is one of the matching ones: nothing bought since.
        customer_id = (b.customer or {}).get("customer_id")
        later = [o for o in rows if (o.get("customer") or {}).get("customer_id") == customer_id and not o.get("cancelled") and float(o.get("ts") or 0) > b.last_ts]
        if later:
            return False
    return True


def _stock_for(b: _Bucket, stock: dict[str, dict[str, Any]]) -> None:
    known = [stock[v] for v in b.variant_ids if v in stock and stock[v].get("tracked") and isinstance(stock[v].get("available"), int)]
    if known:
        b.stock = sum(int(s["available"]) for s in known)
        b.stock_known = True


def _row(b: _Bucket, query: Query, period: Period, *, now: float, zone: ZoneInfo, total_units: int) -> dict[str, Any]:
    key: dict[str, Any] = {}
    for group, (label, ident) in zip(query.group_by, b.keys, strict=False):
        key[group] = label
        if ident:
            key[f"{group}_id"] = ident
    row: dict[str, Any] = {"key": key, "label": " · ".join(label for label, _ in b.keys) or "all"}
    if query.entity in ("products", "variants") and b.sample:
        row["sample_orders"] = b.sample
    if query.entity == "customers" and b.customer:
        row["key"]["customer_email"] = b.customer.get("email")
    for metric in query.metrics:
        row[metric] = _metric(b, metric, period, now=now, zone=zone, total_units=total_units)
    if query.needs_stock:
        row["stock_known"] = b.stock_known
        row["variant_ids"] = sorted(b.variant_ids)[:12]
    return row


def _metric(b: _Bucket, metric: str, period: Period, *, now: float, zone: ZoneInfo, total_units: int) -> Any:
    if metric == "units":
        return b.units
    if metric == "revenue":
        return round(b.revenue, 2)
    if metric == "orders":
        return len(b.orders)
    if metric == "customers":
        return len(b.customers)
    if metric == "aov":
        return round(b.revenue / len(b.orders), 2) if b.orders else None
    if metric == "refunded":
        return round(b.refunded, 2)
    if metric == "unfulfilled_units":
        return b.unfulfilled_units
    if metric == "unfulfilled_value":
        return round(b.unfulfilled_value, 2)
    if metric == "share":
        return round(100 * b.units / total_units, 1) if total_units else None
    if metric == "stock":
        return b.stock
    if metric == "velocity":
        return round(b.units / period.whole_days, 2)
    if metric == "days_cover":
        velocity = b.units / period.whole_days
        if b.stock is None:
            return None
        return round(b.stock / velocity, 1) if velocity > 0 else None
    if metric == "lifetime_orders":
        return b.lifetime_orders
    if metric == "lifetime_spent":
        return round(b.lifetime_spent, 2)
    if metric == "last_order_at":
        return _local(b.last_ts, zone).isoformat() if b.last_ts else None
    if metric == "first_order_at":
        return _local(b.first_ts, zone).isoformat() if b.first_ts else None
    if metric == "age_days":
        return round((now - b.last_ts) / 86400, 1) if b.last_ts else None
    return None


def _totals(total: _Bucket, query: Query, period: Period, *, now: float, zone: ZoneInfo, orders: int) -> dict[str, Any]:
    out = {m: _metric(total, m, period, now=now, zone=zone, total_units=total.units) for m in query.metrics}
    out.setdefault("orders", len(total.orders) or orders)
    out.setdefault("customers", len(total.customers))
    if "share" in out:
        out["share"] = 100.0 if total.units else None
    return out


def _sorted(rows: list[dict[str, Any]], sort: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    def value(row: dict[str, Any], key: str) -> Any:
        if key in row:
            return row[key]
        return row.get("key", {}).get(key)

    out = list(rows)
    for key, direction in reversed(sort):
        # None sorts last whichever way: an unknown cover is not the most urgent.
        out.sort(key=lambda r, k=key: ((v := value(r, k)) is None, (v if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v or ""))), reverse=False)
        if direction == "desc":
            known = [r for r in out if value(r, key) is not None]
            unknown = [r for r in out if value(r, key) is None]
            out = list(reversed(known)) + unknown
    return out


def _orders_listing(query: Query, orders: list[dict[str, Any]], *, now: float, zone: ZoneInfo) -> dict[str, Any]:
    key, direction = query.sort[0] if query.sort else ("created_at", "desc")
    if key in ("created_at", "placed_at"):
        orders.sort(key=lambda o: float(o.get("ts") or 0), reverse=direction == "desc")
    elif key in ("total", "revenue"):
        orders.sort(key=lambda o: float(o.get("total") or 0), reverse=direction == "desc")
    elif key == "age_days":
        orders.sort(key=lambda o: float(o.get("ts") or 0), reverse=direction != "desc")
    shaped = [_order_row(o, now=now, zone=zone) for o in orders]
    revenue = round(sum(float(o.get("total") or 0) for o in orders), 2)
    unfulfilled = round(sum(float(o.get("total") or 0) for o in orders if str(o.get("fulfillment") or "").upper() != "FULFILLED" and not o.get("cancelled")), 2)
    totals = {"orders": len(orders), "revenue": revenue, "unfulfilled_value": unfulfilled, "units": sum(int(i.get("quantity") or 0) for o in orders for i in o.get("items") or []),
              "customers": len({(o.get("customer") or {}).get("customer_id") for o in orders if (o.get("customer") or {}).get("customer_id")}),
              "refunded": round(sum(float(o.get("refunded") or 0) for o in orders), 2)}
    if "aov" in query.metrics:
        totals["aov"] = round(revenue / len(orders), 2) if orders else None
    # The set a listing makes holds every match; when the model asked for a number ("the five
    # oldest"), it holds exactly the rows shown.
    members = [o["order_id"] for o in orders][:MAX_MEMBERS] if not query.limit_explicit else [r["order_id"] for r in shaped[: query.limit]]
    return {"rows": shaped[: query.limit], "row_count": len(shaped), "truncated": len(shaped) > query.limit, "totals": totals, "orders_in_period": len(orders), "member_ids": members,
            "revenue_basis": "order totals, shipping and tax included", "item_level": False,
            "currency": next((str(o.get("currency")) for o in orders if o.get("currency")), "GBP")}


def _order_row(o: dict[str, Any], *, now: float, zone: ZoneInfo) -> dict[str, Any]:
    c = o.get("customer") or {}
    ts = float(o.get("ts") or now)
    return {
        "order_id": o.get("order_id"), "order_number": o.get("order_number"), "placed_at": _local(ts, zone).isoformat(),
        # `age_days` is for display and sorting, at one decimal place. `age_whole_days` is the
        # number a sentence says: whole days actually waited, floored from `now - ts` itself —
        # never from `age_days`, which is already rounded and so reads a day high for the last
        # sliver of every day.
        "age_days": round((now - ts) / 86400, 1), "age_whole_days": _whole_days(now, ts), "fulfillment": o.get("fulfillment"), "payment": o.get("financial"),
        "total": o.get("total"), "currency": o.get("currency"), "customer_name": c.get("name"), "customer_id": c.get("customer_id"), "customer_email": c.get("email"),
        "country_code": o.get("country_code"), "tags": list(o.get("tags") or [])[:10], "items": len(o.get("items") or []), "has_tracking": bool(o.get("has_tracking")),
        "cancelled": bool(o.get("cancelled")),
    }


def restock_priority(query: Query, rows: list[dict[str, Any]], stock: dict[str, dict[str, Any]], *, now: float, tz: str | ZoneInfo = "Europe/London", sets: dict[str, frozenset[str]] | None = None) -> dict[str, Any]:
    """Variants by how soon they run out: stock and units sold measured, velocity and cover
    derived from them. A variant with stock and no sales has no cover to estimate."""
    out = aggregate(query, rows, now=now, tz=tz, stock=stock, sets=sets)
    out["note"] = (
        f"Velocity is units sold over the last {query.period.whole_days} day(s) divided by the days; cover is stock divided by that. "
        "An estimate from recent sales, not a forecast; a variant with no sales in the period has no cover to estimate."
    )
    return out
