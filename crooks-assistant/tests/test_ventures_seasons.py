"""Retail dates by market and launch timing."""

from __future__ import annotations

from datetime import date

import pytest

from app.ventures.seasons import (
    EVENTS,
    easter,
    event_date,
    event_label,
    next_event_date,
    nth_weekday,
    plan_launch,
    supplier_slowdowns,
)


@pytest.mark.parametrize(("year", "expected"), [
    (2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)),
    (2027, date(2027, 3, 28)), (2028, date(2028, 4, 16)), (2030, date(2030, 4, 21)),
])
def test_easter(year, expected):
    assert easter(year) == expected


@pytest.mark.parametrize(("event", "market", "expected"), [
    ("black_friday", "US", date(2026, 11, 27)),
    ("cyber_monday", "UK", date(2026, 11, 30)),
    ("mothers_day", "UK", date(2027, 3, 7)),
    ("mothers_day", "US", date(2027, 5, 9)),
    ("mothers_day", "EU-ES", date(2027, 5, 2)),
    ("mothers_day", "EU-DE", date(2027, 5, 9)),
    ("mothers_day", "EU-FR", date(2027, 5, 30)),
    ("fathers_day", "UK", date(2027, 6, 20)),
    ("fathers_day", "EU-DE", date(2027, 5, 6)),
    ("fathers_day", "EU-IT", date(2027, 3, 19)),
])
def test_event_dates_for_2026_27(event, market, expected):
    year = expected.year
    assert event_date(event, market, year) == expected


def test_french_mothers_day_is_a_sunday_at_the_end_of_may_or_start_of_june():
    # 2024: the last Sunday of May was 26 May and Pentecost was 19 May, so it stays
    assert event_date("mothers_day", "EU-FR", 2024) == date(2024, 5, 26)
    # 2023: Pentecost fell on the last Sunday of May (28 May), so it moved to 4 June
    assert event_date("mothers_day", "EU-FR", 2023) == date(2023, 6, 4)
    for year in range(2025, 2060):
        day = event_date("mothers_day", "EU-FR", year)
        assert day.weekday() == 6
        assert day.month in (5, 6)


def test_nth_weekday_last():
    assert nth_weekday(2027, 5, 6, -1) == date(2027, 5, 30)
    assert nth_weekday(2026, 12, 6, -1) == date(2026, 12, 27)


def test_next_event_rolls_into_next_year():
    assert next_event_date("halloween", "UK", date(2026, 11, 1)) == date(2027, 10, 31)
    assert next_event_date("halloween", "UK", date(2026, 10, 31)) == date(2026, 10, 31)


def test_every_event_has_a_date_and_label_in_every_market():
    for market in ("UK", "UK-NOVAT", "US", "EU-DE", "EU-FR", "EU-ES", "EU-IT", "EU-NL", "EU-IE"):
        for event in EVENTS:
            assert event_date(event, market, 2027).year == 2027
            assert event_label(event, market)
    assert event_label("mothers_day", "UK") == "Mothering Sunday"
    assert event_label("mothers_day", "UK-NOVAT") == "Mothering Sunday"
    assert event_label("mothers_day", "EU-IE") == "Mothering Sunday"
    assert event_label("mothers_day", "US") == "Mother's Day"
    with pytest.raises(ValueError):
        event_date("diwali", "UK", 2027)


def test_halloween_2026_is_too_late_from_china_and_golden_week_is_in_the_way():
    plan = plan_launch(date(2026, 10, 31), delivery_days=20, today=date(2026, 9, 29))
    assert plan.order_cutoff == date(2026, 10, 8)
    assert plan.scale_start == date(2026, 9, 24)
    assert plan.test_start == date(2026, 9, 14)
    assert not plan.feasible
    assert any("Golden Week" in warning for warning in plan.warnings)


def test_christmas_2026_is_still_reachable():
    plan = plan_launch(date(2026, 12, 25), delivery_days=20, today=date(2026, 9, 29))
    assert plan.feasible
    assert plan.test_start == date(2026, 11, 8)


def test_valentines_2027_meets_the_spring_festival():
    plan = plan_launch(date(2027, 2, 14), delivery_days=15, today=date(2026, 9, 29))
    assert any("Spring Festival" in warning for warning in plan.warnings)
    windows = supplier_slowdowns(2027)
    assert [w.name for w in windows] == ["Spring Festival", "Golden Week"]


@pytest.mark.parametrize("bad", [-1, 2.5, True])
def test_plan_needs_whole_days(bad):
    with pytest.raises(ValueError):
        plan_launch(date(2026, 12, 25), delivery_days=bad, today=date(2026, 9, 29))
