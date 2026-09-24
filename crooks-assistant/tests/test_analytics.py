"""The general read layer, without a store: periods in London time, the bounded language and
its refusals, and the engine over a synthetic month of orders — best sellers by units and by
revenue and by size, the comparison with the period before, average order value, customers
ranked by lifetime spend and filtered by order count, velocity and stock cover, the value
tied up in unfulfilled orders, and delayed orders."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.analytics import engine, periods
from app.analytics.cache import shape_order
from app.analytics.query import MAX_COST, QueryError, estimate_cost, parse

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 9, 9, 15, 30, tzinfo=LONDON)   # a Wednesday


# ----------------------------------------------------------------------------- periods


def test_named_periods_resolve_in_london_time():
    p = periods.resolve("today", now=NOW)
    assert p.start == datetime(2026, 9, 9, tzinfo=LONDON) and p.end == NOW and p.label == "today"
    assert periods.resolve("yesterday", now=NOW).start == datetime(2026, 9, 8, tzinfo=LONDON)
    week = periods.resolve("this week", now=NOW)
    assert week.start == datetime(2026, 9, 7, tzinfo=LONDON) and week.end == NOW, "Monday to now"
    last = periods.resolve("last_week", now=NOW)
    assert last.start == datetime(2026, 8, 31, tzinfo=LONDON) and last.end == datetime(2026, 9, 7, tzinfo=LONDON)
    # A week still running is compared with last week to the same point, never the whole of it.
    assert week.previous().start == datetime(2026, 8, 31, tzinfo=LONDON) and week.previous().end == datetime(2026, 9, 2, 15, 30, tzinfo=LONDON) and week.previous().label == "last week to this point"
    assert last.previous().start == datetime(2026, 8, 24, tzinfo=LONDON) and last.previous().end == last.start, "a whole week is compared with the whole week before"
    month = periods.resolve("this_month", now=NOW)
    assert month.previous().start == datetime(2026, 8, 1, tzinfo=LONDON) and month.previous().end == datetime(2026, 8, 9, 15, 30, tzinfo=LONDON) and month.to_date
    assert periods.resolve("today", now=NOW).previous().end == datetime(2026, 9, 8, 15, 30, tzinfo=LONDON)
    month = periods.resolve("this month", now=NOW)
    assert month.start == datetime(2026, 9, 1, tzinfo=LONDON) and month.previous().start == datetime(2026, 8, 1, tzinfo=LONDON) and month.previous().end == datetime(2026, 8, 9, 15, 30, tzinfo=LONDON)
    assert periods.resolve("last month", now=NOW).start == datetime(2026, 8, 1, tzinfo=LONDON)
    seven = periods.resolve({"days": 7}, now=NOW)
    assert seven.start == datetime(2026, 9, 3, tzinfo=LONDON) and seven.whole_days == 7 and seven.previous().start == datetime(2026, 8, 27, tzinfo=LONDON) and seven.previous().end == seven.start
    assert periods.resolve("last 30 days", now=NOW).kind == "days" and periods.resolve(30, now=NOW).days > 29
    ago = periods.resolve({"days": 1, "days_ago": 1}, now=NOW)
    assert ago.label == "yesterday" and ago.start == datetime(2026, 9, 8, tzinfo=LONDON) and ago.end == datetime(2026, 9, 9, tzinfo=LONDON)
    rng = periods.resolve({"start": "2026-09-01", "end": "2026-09-03"}, now=NOW)
    assert rng.start == datetime(2026, 9, 1, tzinfo=LONDON) and rng.end == datetime(2026, 9, 4, tzinfo=LONDON), "a date names its whole day"
    launch = periods.resolve("since launch", now=NOW)
    assert launch.days > 364 and "year" in launch.label
    assert periods.resolve("this_week", now=NOW).utc_bounds()[0] == "2026-09-06T23:00:00Z", "BST: London midnight is 23:00 UTC"


@pytest.mark.parametrize("bad", ["fortnight", {"days": 0}, {"days": 400}, {"start": "2026-09-05", "end": "2026-09-01"}, True, {"start": "nonsense"}])
def test_periods_outside_the_language_are_refused(bad):
    with pytest.raises(periods.PeriodError):
        periods.resolve(bad, now=NOW)


# ------------------------------------------------------------------------------ language


def test_a_best_sellers_query_parses_with_sensible_defaults():
    q = parse({"entity": "order_line_items", "period": "last_30_days", "group_by": ["product"], "metrics": ["units", "revenue"], "sort": [{"metric": "units", "direction": "desc"}], "limit": 10}, now=NOW)
    assert q.entity == "order_line_items" and q.group_by == ("product",) and q.metrics == ("units", "revenue") and q.sort == (("units", "desc"),) and q.limit == 10
    assert q.filters == {"cancelled": "false"} and q.cost <= MAX_COST and q.view == "auto"
    plain = parse({"group_by": "product"}, now=NOW)
    assert plain.period.kind == "days" and plain.metrics == ("units", "revenue") and plain.sort == (("units", "desc"),)
    sized = parse({"entity": "variants", "period": "this week", "filters": {"product": "Convict Joggers"}, "group_by": ["size"], "metrics": ["units"]}, now=NOW)
    assert sized.group_by == ("size",) and sized.filters["product"] == "Convict Joggers", "a variants query grouped by size is that breakdown"
    cover = parse({"entity": "variants", "period": "last_7_days", "metrics": ["days_cover"], "limit": 5}, now=NOW)
    assert set(cover.metrics) == {"days_cover", "stock", "velocity", "units"} and cover.sort == (("days_cover", "asc"),) and cover.needs_stock
    customers = parse({"entity": "customers", "period": "last_90_days", "filters": {"min_orders": 3}, "metrics": ["lifetime_orders", "lifetime_spent"]}, now=NOW)
    assert customers.group_by == ("customer",) and customers.filters["min_orders"] == 3 and customers.sort == (("lifetime_spent", "desc"),)
    aliased = parse({"entity": "sales", "filters": {"color": "black", "status": "unfulfilled", "country": "gb"}, "group_by": ["color"], "metrics": ["sold", "sales"]}, now=NOW)
    assert aliased.filters == {"colour": "black", "fulfillment": "unfulfilled", "country_code": "GB", "cancelled": "false"} and aliased.group_by == ("colour",) and aliased.metrics == ("units", "revenue")


@pytest.mark.parametrize("spec,words,unknown", [
    ({"entity": "invoices"}, "entity is one of", ["entity:invoices"]),
    ({"filters": {"gender": "m"}}, "Unknown filter", ["filter:gender"]),
    ({"group_by": ["region"]}, "Unknown group_by", ["group:region"]),
    ({"metrics": ["margin"]}, "Unknown metric", ["metric:margin"]),
    ({"limit": 500}, "limit is 1..50", []),
    ({"group_by": ["product", "size", "colour"]}, "at most 2", []),
    ({"entity": "orders", "group_by": ["product"]}, "orders lists orders", []),
    ({"metrics": ["stock"]}, "apply to variants or products", []),
    ({"sort": [{"metric": "revenue"}], "metrics": ["units"]}, "not one of the metrics", []),
    ({"filters": {"product": "<script>"}}, "short plain value", []),
    ({"filters": {"customer_id": "gid://shopify/Order/1"}}, "not a Shopify Customer id", []),
    ({"filters": {"in_set": "orders-1"}}, "not a working set id", []),
    ({"period": "since_launch", "compare": True, "group_by": ["product", "size"], "metrics": ["days_cover"], "entity": "variants", "limit": 50}, "too expensive", []),
    ({"view": "hologram"}, "view is one of", ["view:hologram"]),
    ("not an object", "query is an object", []),
])
def test_queries_outside_the_language_are_refused_by_name(spec, words, unknown):
    with pytest.raises(QueryError) as caught:
        parse(spec, now=NOW)
    assert words in str(caught.value) and caught.value.unknown == unknown


def test_cost_grows_with_period_grouping_stock_and_comparison():
    month = periods.resolve("last_30_days", now=NOW)
    year = periods.resolve("since_launch", now=NOW)
    assert estimate_cost("order_line_items", month, [], ["units"], 10, False) == 1
    assert estimate_cost("order_line_items", month, ["product", "size"], ["units"], 10, False) == 3
    assert estimate_cost("variants", month, ["variant"], ["days_cover"], 50, False) == 5
    assert estimate_cost("order_line_items", month, [], ["units"], 10, True) == 2
    assert estimate_cost("customers", year, ["customer"], ["lifetime_spent"], 10, True) > MAX_COST


# ------------------------------------------------------------------------------- engine


def node(number: int, *, days_ago: float, items: list[tuple[str, str, str, str, int, float]], customer: tuple[str, str, int, float] = ("gid://shopify/Customer/1", "Ann Able", 1, 60.0),
         fulfillment: str = "UNFULFILLED", financial: str = "PAID", cancelled: bool = False, country: str = "GB", tags: list[str] | None = None, refunded: float = 0.0) -> dict:
    created = (NOW - timedelta(days=days_ago)).astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = sum(qty * price for _, _, _, _, qty, price in items)
    return {
        "id": f"gid://shopify/Order/{number}", "name": f"CROOKS-{number}", "createdAt": created, "updatedAt": created, "cancelledAt": created if cancelled else None, "closedAt": None,
        "displayFinancialStatus": financial, "displayFulfillmentStatus": fulfillment, "tags": tags or [],
        "currentTotalPriceSet": {"shopMoney": {"amount": f"{total:.2f}", "currencyCode": "GBP"}}, "subtotalPriceSet": {"shopMoney": {"amount": f"{total:.2f}"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "0.00"}}, "totalRefundedSet": {"shopMoney": {"amount": f"{refunded:.2f}"}}, "totalOutstandingSet": {"shopMoney": {"amount": "0.00"}},
        "customer": {"id": customer[0], "displayName": customer[1], "numberOfOrders": customer[2], "createdAt": "2025-01-01T00:00:00Z", "amountSpent": {"amount": f"{customer[3]:.2f}", "currencyCode": "GBP"}, "defaultEmailAddress": {"emailAddress": customer[1].split()[0].lower() + "@example.com"}},
        "shippingAddress": {"countryCodeV2": country, "city": "London"},
        "fulfillments": [{"status": "SUCCESS", "trackingInfo": [{"number": "RM1"}]}] if fulfillment == "FULFILLED" else [],
        "lineItems": {"pageInfo": {"hasNextPage": False}, "edges": [{"node": {
            "id": f"gid://shopify/LineItem/{number}{i}", "title": product, "quantity": qty, "currentQuantity": qty, "unfulfilledQuantity": qty if fulfillment != "FULFILLED" else 0, "refundableQuantity": qty,
            "sku": f"{product[:2].upper()}-{size}", "variantTitle": f"{colour} / {size}", "discountedTotalSet": {"shopMoney": {"amount": f"{qty * price:.2f}"}},
            "variant": {"id": f"gid://shopify/ProductVariant/{abs(hash((product, colour, size))) % 10000}", "selectedOptions": [{"name": "Colour", "value": colour}, {"name": "Size", "value": size}]},
            "product": {"id": f"gid://shopify/Product/{abs(hash(product)) % 1000}", "title": product, "productType": ptype},
        }} for i, (product, ptype, colour, size, qty, price) in enumerate(items)]},
    }


JOGGERS = ("Convict Joggers", "Joggers")
JEANS = ("Yard Jeans", "Jeans")
HOODIE = ("Convict Hoodie", "Hoodies")


@pytest.fixture()
def rows():
    """A month and a half of orders: joggers outsell jeans in units, jeans in revenue; one
    customer buys three times; one order is cancelled; two are old and unshipped."""
    nodes = [
        node(1001, days_ago=1, items=[(*JOGGERS, "Black", "L", 2, 45.0)], customer=("gid://shopify/Customer/1", "Ann Able", 3, 410.0), fulfillment="FULFILLED"),
        node(1002, days_ago=2, items=[(*JOGGERS, "Black", "M", 1, 45.0), (*JEANS, "Blue", "M", 1, 90.0)], customer=("gid://shopify/Customer/2", "Ben Bold", 1, 135.0)),
        node(1003, days_ago=3, items=[(*JEANS, "Blue", "M", 2, 90.0)], customer=("gid://shopify/Customer/3", "Cy Cole", 5, 900.0), fulfillment="FULFILLED"),
        node(1004, days_ago=4, items=[(*JOGGERS, "Pink", "S", 1, 45.0)], customer=("gid://shopify/Customer/4", "Di Dane", 1, 45.0)),
        node(1005, days_ago=6, items=[(*JOGGERS, "Black", "L", 1, 45.0), (*HOODIE, "Grey", "L", 1, 70.0)], customer=("gid://shopify/Customer/1", "Ann Able", 3, 410.0), fulfillment="FULFILLED"),
        node(1006, days_ago=7, items=[(*JOGGERS, "Black", "M", 3, 45.0)], customer=("gid://shopify/Customer/5", "Ed Eddy", 2, 300.0), cancelled=True),
        node(1007, days_ago=9, items=[(*JEANS, "Black", "L", 1, 90.0)], customer=("gid://shopify/Customer/6", "Flo Fry", 1, 90.0), country="IE"),
        node(1008, days_ago=12, items=[(*JOGGERS, "Black", "L", 2, 45.0)], customer=("gid://shopify/Customer/1", "Ann Able", 3, 410.0), fulfillment="FULFILLED"),
        node(1009, days_ago=20, items=[(*HOODIE, "Grey", "M", 1, 70.0)], customer=("gid://shopify/Customer/7", "Gus Gee", 1, 70.0), tags=["delayed"]),
        node(1010, days_ago=38, items=[(*JEANS, "Blue", "M", 1, 90.0), (*JOGGERS, "Black", "L", 1, 45.0)], customer=("gid://shopify/Customer/3", "Cy Cole", 5, 900.0), fulfillment="FULFILLED"),
        node(1011, days_ago=45, items=[(*JOGGERS, "Pink", "M", 2, 45.0)], customer=("gid://shopify/Customer/8", "Hal Hood", 1, 90.0), fulfillment="FULFILLED", refunded=45.0, financial="PARTIALLY_REFUNDED"),
    ]
    return [shape_order(n, read_at=NOW.timestamp()) for n in nodes]


def run(spec: dict, rows: list[dict], **kwargs) -> dict:
    query = parse(spec, now=NOW)
    return engine.aggregate(query, rows, now=NOW.timestamp(), tz=LONDON, **kwargs)


def by_label(result: dict) -> dict[str, dict]:
    return {r["label"]: r for r in result["rows"]}


def test_best_sellers_by_units_and_by_revenue(rows):
    units = run({"entity": "order_line_items", "period": "last_30_days", "group_by": ["product"], "metrics": ["units", "revenue", "orders", "share"], "sort": [{"metric": "units", "direction": "desc"}]}, rows)
    assert [r["label"] for r in units["rows"]] == ["Convict Joggers", "Yard Jeans", "Convict Hoodie"], "cancelled order 1006's three pairs do not count"
    joggers = by_label(units)["Convict Joggers"]
    assert joggers["units"] == 7 and joggers["revenue"] == 315.0 and joggers["orders"] == 5 and joggers["share"] == 53.8
    assert joggers["key"]["product_id"].startswith("gid://shopify/Product/")
    revenue = run({"entity": "order_line_items", "period": "last_30_days", "group_by": ["product"], "metrics": ["revenue"], "sort": "-revenue"}, rows)
    assert [r["label"] for r in revenue["rows"]] == ["Yard Jeans", "Convict Joggers", "Convict Hoodie"] and revenue["rows"][0]["revenue"] == 360.0
    assert units["totals"]["units"] == 13 and units["totals"]["revenue"] == 815.0 and units["orders_in_period"] == 8
    assert units["measured"] == ["units", "revenue", "orders"] and units["derived"] == ["share"]


def test_best_sellers_by_size_within_one_product(rows):
    sizes = run({"entity": "order_line_items", "period": "last_30_days", "filters": {"product": "joggers"}, "group_by": ["size"], "metrics": ["units"]}, rows)
    assert {r["label"]: r["units"] for r in sizes["rows"]} == {"L": 5, "M": 1, "S": 1}
    colours = run({"entity": "order_line_items", "period": "last_30_days", "filters": {"product": "joggers"}, "group_by": ["colour"], "metrics": ["units"]}, rows)
    assert colours["rows"][0]["label"] == "Black" and colours["rows"][0]["units"] == 6
    matrix = run({"entity": "variants", "period": "last_30_days", "filters": {"product": "joggers"}, "group_by": ["colour", "size"], "metrics": ["units"]}, rows)
    assert by_label(matrix)["Black · L"]["units"] == 5 and matrix["rows"][0]["key"] == {"colour": "Black", "size": "L"} and matrix["group_by"] == ["colour", "size"]


def test_a_period_is_compared_with_the_one_before(rows):
    out = run({"entity": "orders", "period": {"days": 7}, "metrics": ["orders", "revenue", "aov"], "compare": True}, rows)
    assert out["totals"]["orders"] == 5 and out["totals"]["revenue"] == 565.0 and out["totals"]["aov"] == 113.0
    before = out["compare"]
    assert before["period"]["label"] == "the 7 days before" and before["totals"]["orders"] == 2 and before["totals"]["revenue"] == 180.0, "the cancelled order in that week does not count"
    assert before["change"]["revenue"] == {"from": 180.0, "to": 565.0, "delta": 385.0, "pct": 213.9} and before["change"]["orders"]["delta"] == 3


def test_average_order_value_and_sales_by_day(rows):
    days = run({"entity": "orders", "period": {"days": 7}, "metrics": ["orders", "revenue", "aov"]}, rows)
    assert days["totals"]["aov"] == 113.0
    per_day = run({"entity": "order_line_items", "period": {"days": 7}, "group_by": ["day"], "metrics": ["orders", "revenue"], "sort": [{"metric": "day", "direction": "asc"}]}, rows)
    assert [r["label"] for r in per_day["rows"]] == ["2026-09-03", "2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08"]
    weekly = run({"entity": "order_line_items", "period": "last_30_days", "group_by": ["week"], "metrics": ["units"]}, rows)
    assert all(r["label"].startswith("week of ") for r in weekly["rows"])


def test_customers_are_ranked_by_lifetime_spend_and_filtered_by_order_count(rows):
    top = run({"entity": "customers", "period": "last_90_days", "metrics": ["orders", "revenue", "lifetime_orders", "lifetime_spent"], "limit": 3}, rows)
    assert [r["label"] for r in top["rows"]] == ["Cy Cole", "Ann Able", "Ben Bold"] and top["rows"][0]["lifetime_spent"] == 900.0 and top["rows"][1]["orders"] == 3
    assert top["rows"][1]["key"]["customer_id"] == "gid://shopify/Customer/1" and top["rows"][1]["key"]["customer_email"] == "ann@example.com"
    repeat = run({"entity": "customers", "period": "last_90_days", "filters": {"min_orders": 3}, "metrics": ["lifetime_orders"]}, rows)
    assert {r["label"] for r in repeat["rows"]} == {"Ann Able", "Cy Cole"}
    rich = run({"entity": "customers", "period": "last_90_days", "filters": {"min_spent": 250}, "metrics": ["lifetime_spent"]}, rows)
    assert {r["label"] for r in rich["rows"]} == {"Ann Able", "Cy Cole"}, "the cancelled order's customer is not counted"
    once = run({"entity": "customers", "period": "last_90_days", "filters": {"product": "pink joggers", "no_later_order": True}, "metrics": ["orders"]}, rows)
    assert {r["label"] for r in once["rows"]} == {"Di Dane", "Hal Hood"}, "bought the pink joggers and nothing since"
    assert top["totals"]["customers"] == 7 and top["totals"]["lifetime_spent"] == 1740.0, "eight customers, less the one whose only order was cancelled"


def test_velocity_and_stock_cover_are_derived_and_say_so(rows):
    variant_ids = {i["variant_id"]: i for o in rows for i in o["items"]}
    black_l = next(v for v, i in variant_ids.items() if i["product"] == "Convict Joggers" and i["size"] == "L" and i["colour"] == "Black")
    blue_m = next(v for v, i in variant_ids.items() if i["product"] == "Yard Jeans" and i["size"] == "M")
    stock = {black_l: {"available": 3, "tracked": True}, blue_m: {"available": 7, "tracked": True}}
    out = engine.restock_priority(parse({"entity": "variants", "period": {"days": 7}, "metrics": ["days_cover"], "limit": 5}, now=NOW), rows, stock, now=NOW.timestamp(), tz=LONDON)
    first = out["rows"][0]
    assert first["label"] == "Convict Joggers · Black / L" and first["units"] == 3 and first["stock"] == 3 and first["velocity"] == 0.43 and first["days_cover"] == 7.0
    jeans = by_label(out)["Yard Jeans · Blue / M"]
    assert jeans["units"] == 3 and jeans["stock"] == 7 and jeans["days_cover"] == 16.3
    unknown = [r for r in out["rows"] if not r["stock_known"]]
    assert unknown and all(r["days_cover"] is None and r["stock"] is None for r in unknown), "no stock read: no cover, never a guess"
    assert out["derived"] == ["velocity", "days_cover"] and "not a forecast" in out["note"]
    assert [r["days_cover"] is None for r in out["rows"]] == sorted(r["days_cover"] is None for r in out["rows"]), "unknown cover sorts last"


def test_revenue_tied_up_in_unfulfilled_orders_and_delayed_orders(rows):
    unfulfilled = run({"entity": "orders", "period": "last_30_days", "filters": {"fulfillment": "unfulfilled"}, "metrics": ["orders", "revenue", "unfulfilled_value"]}, rows)
    assert unfulfilled["totals"]["orders"] == 4 and unfulfilled["totals"]["unfulfilled_value"] == 340.0 and unfulfilled["totals"]["revenue"] == 340.0
    delayed = run({"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled", "older_than_days": 5}, "sort": [{"metric": "age_days", "direction": "desc"}]}, rows)
    assert [r["order_number"] for r in delayed["rows"]] == ["CROOKS-1009", "CROOKS-1007"] and delayed["rows"][0]["age_days"] == 20.0 and delayed["member_ids"] == ["gid://shopify/Order/1009", "gid://shopify/Order/1007"]
    assert delayed["rows"][0]["tags"] == ["delayed"] and delayed["rows"][1]["country_code"] == "IE"
    uk = run({"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled", "older_than_days": 5, "country_code": "gb"}}, rows)
    assert [r["order_number"] for r in uk["rows"]] == ["CROOKS-1009"]
    tagged = run({"entity": "orders", "period": "last_90_days", "filters": {"not_tags": ["delayed"], "fulfillment": "unfulfilled"}}, rows)
    assert "CROOKS-1009" not in [r["order_number"] for r in tagged["rows"]]
    cancelled = run({"entity": "orders", "period": "last_30_days", "filters": {"cancelled": "true"}}, rows)
    assert [r["order_number"] for r in cancelled["rows"]] == ["CROOKS-1006"]


def test_working_set_membership_narrows_a_query(rows):
    sets = {"set_abc123": frozenset({"gid://shopify/Order/1002", "gid://shopify/Order/1004"})}
    out = run({"entity": "orders", "period": "last_30_days", "filters": {"in_set": "set_abc123"}, "metrics": ["orders", "revenue"]}, rows, sets=sets)
    assert out["totals"]["orders"] == 2 and out["totals"]["revenue"] == 180.0
    rest = run({"entity": "orders", "period": "last_30_days", "filters": {"not_in_set": "set_abc123"}}, rows, sets=sets)
    assert out["totals"]["orders"] + rest["totals"]["orders"] == 8
    by_customer_set = run({"entity": "orders", "period": "last_90_days", "filters": {"in_set": "set_c0ffee"}}, rows, sets={"set_c0ffee": frozenset({"gid://shopify/Customer/1"})})
    assert by_customer_set["totals"]["orders"] == 3, "a set of customers selects their orders"


def test_limits_truncate_and_say_so(rows):
    out = run({"entity": "order_line_items", "period": "last_90_days", "group_by": ["variant"], "metrics": ["units"], "limit": 2}, rows)
    assert len(out["rows"]) == 2 and out["truncated"] and out["row_count"] > 2


def test_age_days_is_truncated_to_a_tenth_so_whole_days_are_the_floor():
    """The presenters say "waiting N days" with int(age_days). That is only the floor of the
    elapsed time if the tenth was truncated, never rounded: 14 days 23 hours must read 14."""
    import math

    from app.analytics.engine import age_days_tenths

    day = 86400.0
    assert age_days_tenths(14.97 * day) == 14.9
    assert int(age_days_tenths(14.97 * day)) == 14
    assert age_days_tenths(20 * day) == 20.0
    assert age_days_tenths(2.3 * day) == 2.3
    assert age_days_tenths(0.05 * day) == 0.0
    for tenths in range(0, 300):
        for extra in (0.0, 0.04, 0.09, 0.099):
            elapsed = tenths / 10 + extra
            assert int(age_days_tenths(elapsed * day)) == math.floor(elapsed), elapsed
