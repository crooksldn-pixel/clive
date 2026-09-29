"""The venture engine's order arithmetic: contribution, break-even and the price floor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ventures.economics import UnitCosts, as_amount, as_rate, contribution, price_floor
from app.ventures.markets import MARKETS, Market, format_money, market

D = Decimal


def _costs(**overrides) -> UnitCosts:
    values = dict(product="6", shipping="3", duty="0", per_order_fixed="0.5", payment_rate="0.02",
                  payment_fixed="0.3", returns_rate="0.05", commission_rate="0")
    values.update(overrides)
    return UnitCosts(**values)


def test_contribution_takes_one_order_apart_by_hand():
    order = contribution("30", _costs(), market("US"))
    # net 30; fixed 6 + 3 + 0 + 0.5 + 0.3 = 9.8; card 2% of 30 = 0.6; returns 5% of 30 = 1.5
    assert order.net_revenue == D(30)
    assert order.fixed_costs == D("9.8")
    assert order.rate_costs == D("0.60")
    assert order.returns_allowance == D("1.50")
    assert order.contribution == D("18.10")
    assert order.break_even_cpa == D("18.10")
    assert order.break_even_roas.quantize(D("0.0001")) == D("1.6575")


def test_vat_comes_out_of_the_shown_price_but_fees_are_charged_on_it():
    order = contribution("24", _costs(returns_rate="0"), market("UK"))
    assert order.net_revenue == D(20)
    assert order.rate_costs == D("0.48")      # 2% of the 24 the customer pays, VAT included
    assert order.contribution == D(20) - D("9.8") - D("0.48")


def test_an_order_that_loses_money_before_ads_has_no_break_even():
    order = contribution("8", _costs(), market("US"))
    assert order.contribution < 0
    assert order.break_even_roas is None
    assert order.break_even_cpa is None


@pytest.mark.parametrize("code", ["US", "UK", "EU-DE", "UK-NOVAT"])
def test_the_price_floor_pays_the_target_cpa_and_keeps_the_target_margin(code):
    costs = _costs(commission_rate="0.06")
    target_cpa, target_margin = D("15"), D("0.2")
    floor = price_floor(costs, MARKETS[code], target_cpa=target_cpa, target_margin=target_margin)
    at_floor = contribution(floor.shown_minimum, costs, MARKETS[code])
    assert at_floor.contribution - target_cpa >= target_margin * at_floor.net_revenue
    below = contribution(floor.shown_minimum - D("0.01"), costs, MARKETS[code])
    assert below.contribution - target_cpa < target_margin * below.net_revenue


def test_the_floor_matches_the_research_formula_when_no_tax_is_in_the_price():
    costs = _costs()
    floor = price_floor(costs, market("US"), target_cpa="20", target_margin="0.1")
    expected = (costs.fixed_per_order + D(20)) / (1 - D("0.02") - D("0.05") - D("0.1"))
    assert floor.net_minimum == expected
    assert floor.shown_minimum >= expected
    assert floor.shown_minimum - expected < D("0.01")
    assert floor.landed_multiple == floor.shown_minimum / D(9)


def test_a_cheap_item_needs_a_higher_multiple_than_a_dear_one():
    cheap = price_floor(_costs(product="3"), market("US"), target_cpa="20", target_margin="0.1")
    dear = price_floor(_costs(product="30"), market("US"), target_cpa="20", target_margin="0.1")
    assert cheap.landed_multiple > dear.landed_multiple


def test_no_floor_when_the_rates_take_every_sale():
    with pytest.raises(ValueError, match="no price can pay"):
        price_floor(_costs(payment_rate="0.5", returns_rate="0.3"), market("US"), target_cpa="1", target_margin="0.25")


@pytest.mark.parametrize("bad", [0.5, True, None, [1]])
def test_money_refuses_floats_and_non_numbers(bad):
    with pytest.raises(TypeError):
        as_amount("x", bad)


@pytest.mark.parametrize("bad", ["-1", "NaN", "Infinity", "abc"])
def test_money_refuses_negatives_and_non_finite_values(bad):
    with pytest.raises(ValueError):
        as_amount("x", bad)


@pytest.mark.parametrize("bad", ["1", "-0.1", "1.5"])
def test_rates_must_be_below_one(bad):
    with pytest.raises(ValueError):
        as_rate("x", bad)


def test_costs_have_no_defaults():
    with pytest.raises(TypeError):
        UnitCosts(product=D(1), shipping=D(1))  # type: ignore[call-arg]


def test_markets_and_money_formatting():
    assert market("UK").tax_rate == D("0.20")
    assert market("US").tax_rate == 0
    assert format_money(D("1234.5"), "GBP") == "£1,234.50"
    assert format_money(D("-4.105"), "USD") == "-$4.11"
    assert format_money(D("3"), "CHF") == "3.00 CHF"
    with pytest.raises(ValueError, match="unknown market"):
        market("MARS")
    with pytest.raises(ValueError):
        Market("X", "UK", "GBP", D("1"), "bad")
