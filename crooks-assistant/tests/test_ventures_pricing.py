"""Price presentation, the free-shipping threshold and the reference-price rules."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.ventures.pricing import (
    PricePoint,
    UkUsRule,
    changes_left_digit,
    check_reference_price,
    free_shipping_threshold,
    present_price,
    price_on,
)

D = Decimal
SALE = date(2026, 11, 20)


@pytest.mark.parametrize(("floor", "style", "expected"), [
    ("26.40", "charm", "26.99"),
    ("26.00", "charm", "26.99"),
    ("26.99", "charm", "26.99"),
    ("26.995", "charm", "27.99"),
    ("26.40", "round", "27"),
    ("27", "round", "27"),
])
def test_presented_price_is_never_below_the_floor(floor, style, expected):
    price = present_price(D(floor), style)
    assert price == D(expected)
    assert price >= D(floor)


def test_unknown_style_is_refused():
    with pytest.raises(ValueError):
        present_price(D(10), "fancy")


def test_left_digit_rule():
    assert changes_left_digit(D("19.99"))
    assert changes_left_digit(D("99.99"))
    assert changes_left_digit(D("9.99"))
    assert not changes_left_digit(D("26.99"))
    assert not changes_left_digit(D("19.50"))


def test_free_shipping_threshold_is_a_clean_multiple_of_the_median():
    assert free_shipping_threshold(D("32")) == D(45)        # 32 x 1.4 = 44.8, up to 45
    assert free_shipping_threshold(D("40"), "1.3") == D(55)  # 52, up to 55
    with pytest.raises(ValueError):
        free_shipping_threshold(D("40"), "3")


def _history(*points: tuple[int, str]) -> list[PricePoint]:
    """Points as (days before the sale, price)."""
    return [PricePoint(SALE - timedelta(days=days), D(price)) for days, price in points]


def test_price_on_reads_the_price_in_force():
    history = _history((60, "30"), (10, "25"))
    assert price_on(history, SALE - timedelta(days=61)) is None
    assert price_on(history, SALE - timedelta(days=30)) == D(30)
    assert price_on(history, SALE - timedelta(days=5)) == D(25)


def test_eu_reduction_is_measured_from_the_lowest_price_of_30_days():
    history = _history((90, "30"), (20, "27"), (12, "30"))
    check = check_reference_price(history, reference="30", sale="24", sale_starts=SALE, region="EU")
    assert not check.allowed
    assert check.discount_basis == D(27)
    assert "lowest price of the previous 30 days" in check.reasons[0]
    fair = check_reference_price(history, reference="27", sale="24", sale_starts=SALE, region="EU")
    assert fair.allowed
    assert fair.discount_percent == D("11.1")
    understated = check_reference_price(history, reference="26", sale="24", sale_starts=SALE, region="EU")
    assert not understated.allowed, "the prior price shown must be the price actually charged"


def test_eu_needs_30_days_of_history():
    check = check_reference_price(_history((20, "30")), reference="30", sale="24", sale_starts=SALE, region="EU")
    assert not check.allowed
    assert "30 days" in check.reasons[0]


def test_uk_us_reference_must_be_the_settled_price():
    settled = _history((120, "30"))
    assert check_reference_price(settled, reference="30", sale="24", sale_starts=SALE, region="UK").allowed
    recent = _history((120, "24"), (20, "30"))
    check = check_reference_price(recent, reference="30", sale="24", sale_starts=SALE, region="US")
    assert not check.allowed
    assert any("28 days" in reason for reason in check.reasons)
    assert any("90 days" in reason for reason in check.reasons)


def test_uk_us_rule_is_tunable():
    recent = _history((120, "24"), (20, "30"))
    lenient = UkUsRule(consecutive_days=14, lookback_days=20, share_of_lookback=D("0.5"))
    assert check_reference_price(recent, reference="30", sale="24", sale_starts=SALE, region="UK", rule=lenient).allowed


def test_a_sale_price_that_is_not_lower_is_not_a_reduction():
    check = check_reference_price(_history((120, "30")), reference="30", sale="30", sale_starts=SALE, region="UK")
    assert not check.allowed
    assert "not below" in check.reasons[0]


def test_bad_history_and_region_are_refused():
    with pytest.raises(ValueError, match="same day"):
        check_reference_price(_history((40, "30"), (40, "29")), reference="30", sale="20", sale_starts=SALE, region="EU")
    with pytest.raises(ValueError, match="region"):
        check_reference_price(_history((40, "30")), reference="30", sale="20", sale_starts=SALE, region="CA")
