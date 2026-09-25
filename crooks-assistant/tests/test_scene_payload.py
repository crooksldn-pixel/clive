"""app/scenes/payload.py: a validated scene as the renderer draws it (Generative UI V1, 2a of 4).

Every value resolved and worded for display, deterministically, and a personal value only
where the validated scene kept it. Everything here is synthetic and offline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.scenes import SceneContext, to_evidence, validate_scene
from app.scenes.evidence import FieldDescriptor, Kind, Money, Registry, ToolDescriptors
from app.scenes.payload import (
    PROPOSAL_FALLBACK,
    format_duration,
    format_money,
    format_number,
    format_ratio,
    format_when,
    scene_payload,
)

NOW = datetime(2026, 9, 24, 17, 0, tzinfo=UTC)   # a Thursday; 6pm in London (BST)
SESSION = "sess-payload"


# ------------------------------------------------------------------ synthetic reads


def _customer_row(n: int, *, waiting: bool = False) -> dict:
    emailed = waiting or n < 7
    return {
        "customer_id": f"gid://shopify/Customer/{700 + n}", "customer_name": f"Customer {n}",
        "customer_email": f"customer{n}@example.com", "orders": [f"CROOKS-{1900 + n}"], "emailed": emailed,
        "threads": 1 if emailed else 0, "replied": (not waiting) if emailed else None,
        "latest_inbound_at": (NOW - timedelta(hours=2 * n + 1)).isoformat() if emailed else None,
        "latest_direction": ("inbound" if waiting else "outbound") if emailed else "none",
        "needs_reply": waiting, "confidence": "confident" if emailed else "none", "checked": True,
    }


def _mail(rows: int, waiting: int = 0):
    data = [_customer_row(n, waiting=n < waiting) for n in range(rows)]
    counts = {"contacted": sum(1 for r in data if r["emailed"]), "not_contacted": sum(1 for r in data if not r["emailed"]),
              "replied": sum(1 for r in data if r["replied"]), "needs_reply": sum(1 for r in data if r["needs_reply"]), "unchecked": 0}
    result = {"set_id": "ws1", "set_label": "customers, last 30 days", "days": 30, "customers": rows, "counts": counts, "rows": data}
    return to_evidence("email_query", result, handle="ev-mail", args={"set_id": "ws1", "days": 30}, observed_at=NOW, session_id=SESSION)


def _sales():
    days = [("2026-09-20", 410.0), ("2026-09-21", 380.5), ("2026-09-22", 520.0), ("2026-09-23", 610.25), ("2026-09-24", 1179.25)]
    result = {
        "entity": "orders", "group_by": ["day"], "currency": "GBP",
        "rows": [{"key": {"day": d}, "label": d, "revenue": v, "orders": 4} for d, v in days],
        "totals": {"orders": 40, "revenue": 3100.0, "unfulfilled_value": 1234.5},
        "compare": {"totals": {"orders": 35, "revenue": 2800.0}},
    }
    return to_evidence("commerce_aggregate", result, handle="ev-sales", args={"period": "last_7_days"}, observed_at=NOW, session_id=SESSION)


ADS = ToolDescriptors(
    tool="ads_campaign_report", label="Ad campaigns", records="campaigns", record_id="campaign_id", arguments=("period",),
    fields=(
        FieldDescriptor("campaign_id", Kind.LINK, "Campaign id"),
        FieldDescriptor("name", Kind.TEXT, "Campaign"),
        FieldDescriptor("spend", Kind.MONEY, "Spend"),
        FieldDescriptor("roas", Kind.RATIO, "Return on ad spend", unit="x"),
    ),
    facts=(
        FieldDescriptor("spend", Kind.MONEY, "Spend", path="totals.spend"),
        FieldDescriptor("roas", Kind.RATIO, "Return on ad spend", unit="x", path="totals.roas"),
        FieldDescriptor("daily_spend", Kind.SERIES, "Daily spend", currency="GBP", points=("day", "spend"), path="totals.daily"),
    ),
)


def _full_scene(contact_details: bool = False):
    mail, sales = _mail(25, waiting=3), _sales()
    plan = {
        "answer": {"text": "{0} customers are waiting on a reply.", "values": [{"evidence": "ev-mail", "field": "needs_reply"}],
                   "justification": "The owner asked who is waiting."},
        "elements": [
            {"type": "finding", "significance": "ACTION_REQUIRED", "text": "{0} customers have been waiting since this morning.",
             "values": [{"evidence": "ev-mail", "field": "needs_reply"}], "evidence": ["ev-mail"], "justification": "They need a reply."},
            {"type": "collection", "evidence": "ev-mail", "columns": ["customer_name", "customer_email", "latest_inbound_at", "threads"],
             "limit": 8, "justification": "Who is waiting."},
            {"type": "entity", "evidence": "ev-mail", "record": "r1", "fields": ["customer_name", "customer_email", "threads", "latest_direction"],
             "justification": "Who wrote first."},
            {"type": "timeline", "evidence": "ev-mail", "at": "latest_inbound_at", "label": "customer_name", "limit": 3,
             "justification": "When they wrote."},
            {"type": "measure", "value": {"evidence": "ev-sales", "field": "unfulfilled_value"}, "period": "last_7_days",
             "justification": "Money waiting to ship."},
            {"type": "comparison", "current": {"evidence": "ev-sales", "field": "revenue"},
             "previous": {"evidence": "ev-sales", "field": "previous_revenue"}, "justification": "This week against last."},
            {"type": "trend", "series": {"evidence": "ev-sales", "field": "revenue_trend"}, "justification": "How the week went."},
            {"type": "proposal", "action": "act-1", "justification": "Draft the replies."},
            {"type": "question", "text": "Shall I draft the replies?", "options": ["Yes", "Not yet"], "justification": "Needs the owner."},
        ],
    }
    context = SceneContext(request="who is waiting on a reply", session_id=SESSION, actions=frozenset({"act-1"}),
                           max_elements=12, contact_details=contact_details)
    scene, _ = validate_scene(plan, [mail, sales], context)
    return scene, [mail, sales]


def _by_type(payload: dict) -> dict:
    return {e["type"]: e for e in payload["elements"]}


# ------------------------------------------------------------------ formatting per kind


def test_money_is_written_with_its_currency_symbol():
    assert format_money(Money(Decimal("3100"), "GBP")) == "£3,100.00"
    assert format_money(Money(Decimal("840.505"), "GBP")) == "£840.51"
    assert format_money(Money(Decimal("-12.5"), "EUR")) == "-€12.50"
    assert format_money(Money(Decimal("19.99"), "USD")) == "$19.99"
    assert format_money(Money(Decimal("1200"), "CHF")) == "1,200.00 CHF"
    assert format_money(Money(Decimal("1500.4"), "JPY")) == "¥1,500"


def test_ratios_are_percentages_or_multiples_as_the_descriptor_says():
    assert format_ratio(35.0, "%") == "35%"
    assert format_ratio(12.25, "%") == "12.3%"
    assert format_ratio(2.5, "x") == "2.5×"
    assert format_ratio(0.125) == "12.5%"
    assert format_ratio(1.4219, "units/day") == "1.42 units/day"


def test_counts_and_numbers():
    assert format_number(1234) == "1,234"
    assert format_number(2.50) == "2.5"
    assert format_number(-0.04) == "0"
    assert format_number(10.71, 0) == "11"


@pytest.mark.parametrize(("value", "unit", "words"), [
    (3, "days", "3 days"),
    (1, "days", "1 day"),
    (0.5, "days", "12 hours"),
    (1.25, "days", "30 hours"),
    (1.6, "days", "2 days"),
    (45, "minutes", "45 minutes"),
    (20, "seconds", "under a minute"),
    (400, "days", "13 months"),
    (1000, "days", "3 years"),
    (7, "fortnights", "7 fortnights"),
])
def test_durations_are_plain_words(value, unit, words):
    assert format_duration(value, unit) == words


@pytest.mark.parametrize(("value", "words"), [
    (NOW - timedelta(seconds=30), "just now"),
    (NOW - timedelta(minutes=45), "45 minutes ago"),
    (NOW - timedelta(minutes=1), "1 minute ago"),
    (NOW - timedelta(hours=3), "3 hours ago"),
    (datetime(2026, 9, 24, 8, 15, tzinfo=UTC), "today at 9:15am"),        # BST: an hour ahead of UTC
    (datetime(2026, 9, 23, 15, 30, tzinfo=UTC), "yesterday at 4:30pm"),
    (datetime(2026, 9, 21, 10, 0, tzinfo=UTC), "Monday at 11am"),
    (datetime(2026, 9, 1, 12, 0, tzinfo=UTC), "1 September at 1pm"),
    (datetime(2025, 12, 25, 12, 0, tzinfo=UTC), "25 December 2025 at 12pm"),
    (datetime(2026, 9, 22, tzinfo=UTC), "Tuesday"),                        # a date with no time of day
    (datetime(2026, 9, 24, tzinfo=UTC), "today"),
    (NOW + timedelta(minutes=20), "in 20 minutes"),
    (datetime(2026, 9, 25, 9, 0, tzinfo=UTC), "tomorrow at 10am"),
])
def test_datetimes_are_relative_words_in_london(value, words):
    assert format_when(value, NOW) == words


def test_london_time_decides_the_day():
    # Half past midnight in London is still before midnight in UTC.
    late = datetime(2026, 9, 24, 23, 30, tzinfo=UTC)
    assert format_when(datetime(2026, 9, 24, 17, 0, tzinfo=UTC), late) == "yesterday at 6pm"
    # In winter London is on UTC.
    winter = datetime(2026, 12, 10, 18, 0, tzinfo=UTC)
    assert format_when(datetime(2026, 12, 10, 9, 15, tzinfo=UTC), winter) == "today at 9:15am"


# ------------------------------------------------------------------ the payload


def test_every_element_is_resolved_and_formatted_from_evidence():
    scene, evidence = _full_scene()
    payload = scene_payload(scene, evidence, now=NOW, actions={"act-1": "Draft replies to the three customers waiting."})
    json.dumps(payload)   # plain JSON, nothing else

    assert payload["answer"] == {"id": "answer", "type": "answer", "text": "3 customers are waiting on a reply.",
                                 "justification": "The owner asked who is waiting."}
    assert [e["type"] for e in payload["elements"]] == [
        "finding", "collection", "entity", "timeline", "measure", "comparison", "trend", "proposal", "question"]
    assert [e["id"] for e in payload["elements"]] == [f"e{n}" for n in range(1, 10)]
    assert all(e["justification"] for e in payload["elements"])
    assert payload["drilldown"] is None
    by = _by_type(payload)

    finding = by["finding"]
    assert finding["significance"] == "ACTION_REQUIRED"
    assert finding["text"] == "3 customers have been waiting since this morning."
    assert [s["label"] for s in finding["sources"]] == ["Who has emailed"]
    assert finding["sources"][0]["found"] == 25 and finding["sources"][0]["found_text"] == "25 found"
    assert finding["sources"][0]["checked"] == "just now"

    collection = by["collection"]
    assert [c["label"] for c in collection["columns"]] == ["Customer", "Their last email", "Threads"]
    assert [c["numeric"] for c in collection["columns"]] == [False, False, True]
    assert collection["limit"] == 8 and len(collection["rows"]) == 8 and collection["total"] == 25
    assert collection["rows"][0] == {"record": "r1", "cells": ["Customer 0", "1 hour ago", "1"]}
    assert collection["rows"][2]["cells"][1] == "5 hours ago"
    assert collection["rows"][3]["cells"][1] == "today at 11am"
    assert collection["rows"][7]["cells"] == ["Customer 7", "unknown", "0"]
    assert collection["caption"] == "Who has emailed"

    entity = by["entity"]
    assert [(f["label"], f["text"]) for f in entity["fields"]] == [("Customer", "Customer 0"), ("Threads", "1"), ("Last message", "Inbound")]

    timeline = by["timeline"]
    assert [r["label"] for r in timeline["rows"]] == ["Customer 2", "Customer 1", "Customer 0"]
    assert [r["at"] for r in timeline["rows"]] == ["5 hours ago", "3 hours ago", "1 hour ago"]

    assert {k: by["measure"][k] for k in ("label", "value", "unit", "period")} == {
        "label": "To ship", "value": "£1,234.50", "unit": None, "period": "last 7 days"}

    comparison = by["comparison"]
    assert comparison["current"]["text"] == "£3,100.00" and comparison["previous"]["text"] == "£2,800.00"
    assert comparison["previous"]["label"] == "Sales before"
    assert comparison["direction"] == "up" and comparison["difference"] == "Up £300.00 (11%)"

    trend = by["trend"]
    assert trend["values"] == [410.0, 380.5, 520.0, 610.25, 1179.25]
    assert all(isinstance(v, float) for v in trend["values"])
    assert trend["latest"] == "£1,179.25" and trend["from"] == "Sunday" and trend["to"] == "today"

    assert by["proposal"]["action"] == "act-1" and by["proposal"]["text"] == "Draft replies to the three customers waiting."
    assert by["question"]["text"] == "Shall I draft the replies?" and by["question"]["options"] == ["Yes", "Not yet"]

    # Without its words, a proposal says only that an action is ready.
    assert _by_type(scene_payload(scene, evidence, now=NOW))["proposal"]["text"] == PROPOSAL_FALLBACK


def test_the_2026_09_24_case_is_one_answer_and_a_drill_down():
    mail = _mail(25)
    plan = {
        "answer": {"text": "Nobody is waiting on a reply: all {0} customers who emailed have been answered.",
                   "values": [{"evidence": "ev-mail", "field": "replied"}], "justification": "The owner asked whether any customer needs a reply."},
        "elements": [
            {"type": "collection", "evidence": "ev-mail", "columns": ["customer_name", "customer_email"], "limit": 25,
             "justification": "The customers that were checked."},
        ],
    }
    scene, _ = validate_scene(plan, [mail], SceneContext.for_request("any customers who need a reply", session_id=SESSION))
    payload = scene_payload(scene, [mail], now=NOW + timedelta(minutes=2))

    assert payload["answer"]["text"] == "Nobody is waiting on a reply: all 7 customers who emailed have been answered."
    assert payload["elements"] == []
    assert payload["drilldown"]["sources"] == [{
        "evidence": "ev-mail", "label": "Who has emailed", "summary": "Who has emailed by set_id, days", "found": 25,
        "found_text": "25 found", "checked": "2 minutes ago", "checked_at": NOW.isoformat(),
    }]
    assert "@" not in json.dumps(payload)


def test_the_ads_connector_scene_needs_no_code_of_its_own():
    registry = Registry()
    registry.register(ADS)
    daily = [90, 110, 150, 130, 120, 115, 125.5]
    result = {
        "campaigns": [
            {"campaign_id": "c1", "name": "Autumn denim", "spend": {"amount": "512.40", "currency": "GBP"}, "roas": 1.4},
            {"campaign_id": "c2", "name": "Hoodies", "spend": {"amount": "328.10", "currency": "GBP"}, "roas": 4.2},
        ],
        "totals": {"spend": "840.50 GBP", "roas": 2.5,
                   "daily": [{"day": f"2026-09-{d}", "spend": s} for d, s in zip(range(18, 25), daily, strict=True)]},
    }
    ads = registry.to_evidence("ads_campaign_report", result, handle="ads-1", args={"period": "last_7_days"}, observed_at=NOW, session_id=SESSION)
    plan = {
        "answer": {"text": "Advertising cost {0} this week at a return on spend of {1}.",
                   "values": [{"evidence": "ads-1", "field": "spend"}, {"evidence": "ads-1", "field": "roas"}],
                   "justification": "The owner asked how the advertising did."},
        "elements": [
            {"type": "finding", "significance": "RISK", "text": "{0} returned only {1} on its spend.",
             "values": [{"evidence": "ads-1", "field": "name", "record": "r1"}, {"evidence": "ads-1", "field": "roas", "record": "r1"}],
             "evidence": ["ads-1"], "justification": "The weakest is barely paying for itself."},
            {"type": "trend", "series": {"evidence": "ads-1", "field": "daily_spend"}, "justification": "Where the week's spend went."},
        ],
    }
    scene, _ = validate_scene(plan, [ads], SceneContext.for_request("how did the ads do this week", session_id=SESSION))
    payload = scene_payload(scene, [ads], now=NOW)

    assert payload["answer"]["text"] == "Advertising cost £840.50 this week at a return on spend of 2.5×."
    finding, trend = payload["elements"]
    assert finding["text"] == "Autumn denim returned only 1.4× on its spend."
    assert [(v["label"], v["text"]) for v in finding["values"]] == [("Campaign", "Autumn denim"), ("Return on ad spend", "1.4×")]
    assert trend["values"] == [90.0, 110.0, 150.0, 130.0, 120.0, 115.0, 125.5]
    assert trend["latest"] == "£125.50" and trend["from"] == "Friday" and trend["to"] == "today"


def test_durations_and_ratios_come_through_their_descriptors():
    rows = [{"order_id": f"gid://o/{n}", "order_number": f"#{1000 + n}", "age_days": age, "share": 12.5 * (n + 1),
             "velocity": 1.25, "total": 40.0, "currency": "GBP"} for n, age in enumerate((0.5, 1.25, 3.2))]
    orders = to_evidence("commerce_query", {"entity": "orders", "rows": rows, "row_count": 3, "currency": "GBP",
                                            "totals": {"orders": 3}}, handle="ev-orders", observed_at=NOW, session_id=SESSION)
    plan = {
        "answer": {"text": "The oldest order has waited {0}.", "values": [{"evidence": "ev-orders", "field": "age_days", "record": "r3"}],
                   "justification": "Asked how long orders wait."},
        "elements": [
            {"type": "entity", "evidence": "ev-orders", "record": "r2", "fields": ["order_number", "age_days", "share", "velocity", "total"],
             "justification": "The second order."},
            {"type": "measure", "value": {"evidence": "ev-orders", "field": "age_days", "record": "r1"}, "justification": "The newest."},
        ],
    }
    scene, _ = validate_scene(plan, [orders], SceneContext(session_id=SESSION))
    payload = scene_payload(scene, [orders], now=NOW)
    assert payload["answer"]["text"] == "The oldest order has waited 3 days."
    entity, measure = payload["elements"]
    assert [f["text"] for f in entity["fields"]] == ["#1001", "30 hours", "25%", "1.25 units/day", "£40.00"]
    assert (measure["value"], measure["unit"], measure["period"]) == ("12", "hours", "checked just now")


# ------------------------------------------------------------------ pii


def test_pii_is_in_the_payload_only_when_the_validated_scene_kept_it():
    scene, evidence = _full_scene(contact_details=False)
    payload = scene_payload(scene, evidence, now=NOW)
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "@" not in dumped and "example.com" not in dumped
    by = _by_type(payload)
    assert "customer_email" not in [c["field"] for c in by["collection"]["columns"]]
    assert "Customer email" not in [f["label"] for f in by["entity"]["fields"]]
    assert not any(f["pii"] for f in by["entity"]["fields"])

    scene, evidence = _full_scene(contact_details=True)
    payload = scene_payload(scene, evidence, now=NOW)
    by = _by_type(payload)
    assert [c["field"] for c in by["collection"]["columns"]] == ["customer_name", "customer_email", "latest_inbound_at", "threads"]
    assert by["collection"]["rows"][0]["cells"][1] == "customer0@example.com"
    email = next(f for f in by["entity"]["fields"] if f["field"] == "customer_email")
    assert email["text"] == "customer0@example.com" and email["pii"] is True


def test_a_drill_down_or_a_finding_never_carries_a_row_of_the_evidence():
    """What was checked is described by its label, summary, count and time — never its rows."""
    mail = _mail(12, waiting=2)
    plan = {
        "answer": {"text": "{0} customers are waiting on a reply.", "values": [{"evidence": "ev-mail", "field": "needs_reply"}],
                   "justification": "Asked."},
        "elements": [{"type": "finding", "significance": "CONTEXT", "text": "They wrote this afternoon.", "evidence": ["ev-mail"],
                      "justification": "When they wrote."}],
    }
    scene, _ = validate_scene(plan, [mail], SceneContext(session_id=SESSION))
    dumped = json.dumps(scene_payload(scene, [mail], now=NOW))
    for literal in ("@", "example.com", "Customer 0", "Customer 1", "gid://"):
        assert literal not in dumped, literal


# ------------------------------------------------------------------ determinism


def test_the_payload_is_deterministic():
    scene, evidence = _full_scene()
    first = scene_payload(scene, evidence, now=NOW)
    again = scene_payload(scene, list(evidence), now=NOW)
    assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True)
    by_handle = scene_payload(scene, {ev.handle: ev for ev in evidence}, now=NOW)
    assert by_handle == first
    # With no `now`, time words are relative to the latest read, never to the clock.
    assert scene_payload(scene, evidence) == first
    # A later `now` changes the words, and only them.
    later = scene_payload(scene, evidence, now=NOW + timedelta(days=2))
    assert _by_type(later)["timeline"]["rows"][-1]["at"] == "Thursday at 5pm"
    assert later["answer"] == first["answer"]


def test_evidence_that_is_not_evidence_is_refused():
    scene, _ = _full_scene()
    with pytest.raises(TypeError):
        scene_payload(scene, [{"handle": "ev-mail"}])
