"""The analytic cards: the read layer's results become a ranking, a table, a comparison, a
matrix of sizes, a trend or a group of figures — every value formatted on the Mac as text,
the view chosen from the model's checked intent or the shape of the data, and nothing the
tool did not return."""

from __future__ import annotations

from app.analytics.present import build, choose_view, fmt
from app.presentation import UI_TYPES, present
from app.providers.base import ToolCall

PERIOD = {"label": "last 30 days", "start": "2026-08-11T00:00:00+01:00", "end": "2026-09-09T15:30:00+01:00", "days": 29.6, "timezone": "Europe/London", "kind": "days"}
COVERAGE = {"complete": True, "covered_days": 90.0, "read_age_s": 12.0, "note": None}


def aggregate(**over) -> dict:
    base = {
        "entity": "order_line_items", "period": PERIOD, "filters": {}, "group_by": ["product"], "metrics": ["units", "revenue", "share"], "sort": ["units desc"], "limit": 10,
        "rows": [
            {"key": {"product": "Convict Joggers", "product_id": "gid://shopify/Product/1"}, "label": "Convict Joggers", "units": 41, "revenue": 1845.0, "share": 53.8},
            {"key": {"product": "Yard Jeans", "product_id": "gid://shopify/Product/2"}, "label": "Yard Jeans", "units": 22, "revenue": 1980.0, "share": 28.9},
        ],
        "row_count": 2, "truncated": False, "totals": {"units": 76, "revenue": 4812.5, "share": 100.0, "orders": 63}, "orders_in_period": 63, "currency": "GBP",
        "measured": ["units", "revenue"], "derived": ["share"], "view": "auto", "title": "", "coverage": COVERAGE, "source": "Shopify orders", "cost": 2,
    }
    base.update(over)
    return base


def test_formatting_is_the_macs_and_money_carries_its_currency():
    assert fmt("revenue", 1845, "GBP") == "£1,845.00" and fmt("aov", 87.333, "EUR") == "€87.33" and fmt("units", 41, "GBP") == "41"
    assert fmt("share", 53.8, "GBP") == "54%" and fmt("velocity", 1.857, "GBP") == "1.86" and fmt("days_cover", 1.62, "GBP") == "1.6" and fmt("days_cover", None, "GBP") == "—"
    assert fmt("last_order_at", "2026-09-08T10:00:00+01:00", "GBP") == "2026-09-08" and fmt("age_days", 20.4, "GBP") == "20"


def test_best_sellers_become_a_ranking_with_bars_and_a_legend():
    (item,) = build(aggregate(), tool="commerce_aggregate")
    assert item["type"] == "ranking"
    d = item["data"]
    assert d["title"] == "Best sellers" and d["subtitle"] == "last 30 days" and d["mode"] == ""
    first = d["rows"][0]
    assert first == {"rank": 1, "label": "Convict Joggers", "sublabel": "", "ref": "gid://shopify/Product/1", "kind": "product", "primary": {"key": "units", "label": "units", "value": "41"}, "secondary": {"key": "revenue", "label": "revenue", "value": "£1,845.00"}, "pct": 54, "lines": [], "known": True}
    assert d["totals"] == [{"key": "units", "label": "units", "value": "76"}, {"key": "revenue", "label": "revenue", "value": "£4,812.50"}]
    assert d["measured"] == ["units", "revenue"] and d["derived"] == ["share"] and d["complete"] is True


def test_the_view_follows_the_intent_or_the_shape():
    assert choose_view(aggregate()) == "ranking"
    assert choose_view(aggregate(view="table")) == "table"
    assert choose_view(aggregate(compare={"period": PERIOD, "totals": {}, "rows": [], "change": {}})) == "comparison"
    assert choose_view(aggregate(entity="orders", group_by=[], rows=[])) == "metrics"
    assert choose_view(aggregate(group_by=["day"])) == "trend"
    assert choose_view(aggregate(entity="variants", group_by=["colour", "size"])) == "matrix"
    assert choose_view(aggregate(entity="variants", group_by=["variant"], mode="restock_priority")) == "ranking"
    assert choose_view(aggregate(entity="orders", group_by=[], view="list", rows=[{"order_id": "x"}])) == "list"


def test_a_comparison_names_both_periods_and_the_change():
    result = aggregate(entity="orders", group_by=[], metrics=["orders", "revenue", "aov"], totals={"orders": 83, "revenue": 4812.0, "aov": 57.98}, view="comparison",
                       period={**PERIOD, "label": "this week"},
                       compare={"period": {**PERIOD, "label": "last week"}, "totals": {"orders": 72, "revenue": 4109.0, "aov": 57.07}, "rows": [], "change": {"orders": {"from": 72, "to": 83, "delta": 11, "pct": 15.3}, "revenue": {"from": 4109.0, "to": 4812.0, "delta": 703.0, "pct": 17.1}, "aov": {"from": 57.07, "to": 57.98, "delta": 0.91, "pct": 1.6}}})
    (item,) = build(result, tool="commerce_aggregate")
    d = item["data"]
    assert item["type"] == "comparison" and d["current"]["label"] == "this week" and d["previous"]["label"] == "last week"
    assert d["current"]["metrics"][1] == {"key": "revenue", "label": "revenue", "value": "£4,812.00"} and d["previous"]["metrics"][0]["value"] == "72"
    assert d["changes"][1] == {"key": "revenue", "label": "revenue", "delta": "+£703.00", "pct": "+17.1%", "direction": "up"}


def test_a_size_and_colour_breakdown_is_a_matrix_with_sizes_in_order():
    rows = [
        {"key": {"colour": "Black", "size": "L"}, "label": "Black · L", "units": 13},
        {"key": {"colour": "Black", "size": "S"}, "label": "Black · S", "units": 2},
        {"key": {"colour": "Pink", "size": "M"}, "label": "Pink · M", "units": 5},
        {"key": {"colour": "Black", "size": "XL"}, "label": "Black · XL", "units": 4},
    ]
    (item,) = build(aggregate(entity="variants", group_by=["colour", "size"], metrics=["units"], rows=rows), tool="commerce_aggregate")
    d = item["data"]
    assert item["type"] == "variant_matrix" and d["rows"] == ["Black", "Pink"] and d["cols"] == ["S", "M", "L", "XL"] and d["row_label"] == "Colour" and d["col_label"] == "Size"
    assert {"row": "Black", "col": "L", "value": 13, "display": "13"} in d["cells"] and d["metric"] == "units"


def test_a_daily_breakdown_is_a_trend_in_date_order():
    rows = [{"key": {"day": "2026-09-08"}, "label": "2026-09-08", "revenue": 300.0}, {"key": {"day": "2026-09-07"}, "label": "2026-09-07", "revenue": 120.5}]
    (item,) = build(aggregate(group_by=["day"], metrics=["revenue"], rows=rows, totals={"revenue": 420.5}), tool="commerce_aggregate")
    d = item["data"]
    assert item["type"] == "trend" and [p["label"] for p in d["points"]] == ["2026-09-07", "2026-09-08"] and d["points"][0]["display"] == "£120.50" and d["total"] == "£420.50"


def test_figures_alone_are_a_metric_group_marking_what_is_derived():
    (item,) = build(aggregate(entity="orders", group_by=[], metrics=["orders", "unfulfilled_value", "aov"], rows=[], totals={"orders": 23, "unfulfilled_value": 1481.0, "aov": 64.39}, measured=["orders", "unfulfilled_value"], derived=["aov"], coverage={**COVERAGE, "complete": False}), tool="commerce_aggregate")
    d = item["data"]
    assert item["type"] == "metric_group" and d["metrics"] == [{"key": "orders", "label": "orders", "value": "23", "measured": True}, {"key": "unfulfilled_value", "label": "unfulfilled value", "value": "£1,481.00", "measured": True}, {"key": "aov", "label": "avg order", "value": "£64.39", "measured": False}]
    assert d["complete"] is False and "partial" in d["subtitle"]


def test_restock_priority_shows_measured_and_derived_lines_and_unknown_stock_as_unknown():
    rows = [
        {"key": {"variant": "Convict Joggers · Black / L", "variant_id": "gid://shopify/ProductVariant/1"}, "label": "Convict Joggers · Black / L", "stock": 3, "units": 13, "velocity": 1.86, "days_cover": 1.6, "stock_known": True},
        {"key": {"variant": "Yard Jeans · Blue / M", "variant_id": "gid://shopify/ProductVariant/2"}, "label": "Yard Jeans · Blue / M", "stock": None, "units": 4, "velocity": 0.57, "days_cover": None, "stock_known": False},
    ]
    (item,) = build(aggregate(entity="variants", group_by=["variant"], metrics=["stock", "units", "velocity", "days_cover"], measured=["units", "stock"], derived=["velocity", "days_cover"], rows=rows, mode="restock_priority", note="Not a forecast.", title="Restock priority"), tool="inventory_query")
    d = item["data"]
    assert d["mode"] == "restock" and d["title"] == "Restock priority"
    first = d["rows"][0]
    assert first["primary"] == {"key": "days_cover", "label": "days cover", "value": "1.6"} and first["secondary"] == {"key": "stock", "label": "in stock", "value": "3"}
    assert [(line["label"], line["value"], line["derived"]) for line in first["lines"]] == [("in stock", "3", False), ("sold in period", "13", False), ("a day", "1.86", True), ("days cover", "1.6", True)]
    assert d["rows"][1]["known"] is False and d["rows"][1]["primary"]["value"] == "—" and d["note"] == "Not a forecast."


def test_a_listing_is_the_order_list_the_tablet_already_draws():
    result = {"entity": "orders", "period": PERIOD, "filters": {"fulfillment": "unfulfilled", "older_than_days": 5}, "group_by": [], "metrics": ["orders", "revenue"], "view": "list", "title": "Delayed orders", "currency": "GBP", "coverage": COVERAGE,
              "rows": [{"order_id": "gid://shopify/Order/1", "order_number": "CROOKS-1938", "placed_at": "2026-09-01T10:00:00+01:00", "age_days": 8.2, "fulfillment": "UNFULFILLED", "payment": "PAID", "total": 60.0, "currency": "GBP", "customer_name": "Daniel Stub", "customer_id": "gid://shopify/Customer/7", "customer_email": "daniel@example.com", "country_code": "GB", "tags": [], "items": 1, "has_tracking": False, "cancelled": False}],
              "row_count": 1, "truncated": False, "totals": {"orders": 1, "revenue": 60.0, "unfulfilled_value": 60.0}, "member_ids": ["gid://shopify/Order/1"]}
    (item,) = build(result, tool="commerce_query")
    assert item["type"] == "order_list" and item["data"]["title"] == "Delayed orders" and item["data"]["orders"][0]["order_number"] == "#1938" and item["data"]["orders"][0]["total"] == "£60.00"
    assert item["data"]["value"] == "£60.00" and item["data"]["count"] == 1 and "member_ids" not in item["data"]


def test_the_cards_pass_the_presentation_layers_gate_and_a_reused_result_draws_nothing():
    items = present([ToolCall(name="commerce_aggregate", args={}, ok=True, result=aggregate())])
    assert [i["type"] for i in items] == ["ranking"] and all(i["type"] in UI_TYPES for i in items)
    assert present([ToolCall(name="commerce_aggregate", args={}, ok=True, result={"reused": True})]) == []
    hostile = aggregate(title="<b>x</b>" * 30, rows=[{"key": {"product": "<img src=x>"}, "label": "<img src=x>", "units": 1, "revenue": 1.0}])
    (item,) = build(hostile, tool="commerce_aggregate")
    assert len(item["data"]["title"]) == 60 and item["data"]["rows"][0]["label"] == "<img src=x>", "bounded, and text stays text: the tablet draws it as text, never as markup"
