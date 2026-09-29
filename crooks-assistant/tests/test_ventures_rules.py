"""Kill and scale rules: the probabilities behind them and the decisions they make."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from app.ventures.rules import (
    DEFAULT_KILL_RULES,
    Action,
    ConceptResult,
    KillRule,
    decide_concept,
    decide_product,
    poisson_cdf,
    rate_interval,
)

D = Decimal
TARGET = D(40)


def test_poisson_cdf_known_values():
    assert poisson_cdf(0, 3.0) == pytest.approx(math.exp(-3))
    assert poisson_cdf(1, 5.0) == pytest.approx(6 * math.exp(-5))
    assert poisson_cdf(-1, 2.0) == 0.0
    assert poisson_cdf(3, 0.0) == 1.0
    assert poisson_cdf(1500, 1500.0) == pytest.approx(0.5, abs=0.02)   # no underflow at large rates


def test_research_false_kill_rates():
    three_none, five_one = DEFAULT_KILL_RULES
    assert three_none.false_kill() == pytest.approx(0.0498, abs=1e-4)   # about 5%
    assert five_one.false_kill() == pytest.approx(0.0404, abs=1e-4)     # about 4%
    # the "kill at 1-2x the target" folklore throws away 14-37% of on-target concepts
    assert KillRule(D(2), 0).false_kill() == pytest.approx(0.1353, abs=1e-4)
    assert KillRule(D(1), 0).false_kill() == pytest.approx(0.3679, abs=1e-4)


def test_twenty_purchases_leave_a_wide_interval():
    low, high = rate_interval(20)
    assert 20 / high == pytest.approx(0.647, abs=0.002)
    assert 20 / low == pytest.approx(1.637, abs=0.002)
    assert rate_interval(0)[0] == 0.0
    with pytest.raises(ValueError):
        rate_interval(-1)


def test_kill_at_three_times_the_target_with_no_purchase():
    decision = decide_concept(D(120), 0, TARGET)
    assert decision.action is Action.KILL
    assert decision.false_kill == pytest.approx(0.0498, abs=1e-4)


def test_one_purchase_survives_three_times_but_not_five():
    assert decide_concept(D(150), 1, TARGET).action is Action.CONTINUE
    assert decide_concept(D(150), 1, TARGET).next_kill_spend == D(200)
    assert decide_concept(D(200), 1, TARGET).action is Action.KILL


def test_confidently_above_target_is_killed():
    decision = decide_concept(D(400), 2, TARGET)     # 10x the target for two purchases
    assert decision.action is Action.KILL
    assert decision.true_cpa_low > TARGET


def test_scale_at_twenty_purchases_on_target():
    assert decide_concept(D(800), 20, TARGET).action is Action.SCALE
    assert decide_concept(D(820), 20, TARGET).action is Action.CONTINUE


def test_early_scale_only_far_under_target():
    assert decide_concept(D(100), 5, TARGET).action is Action.SCALE         # 0.5x
    assert decide_concept(D(140), 5, TARGET).action is Action.CONTINUE      # 0.7x
    assert decide_concept(D(20), 4, TARGET).action is Action.CONTINUE       # too few to scale


def test_no_spend_no_decision():
    decision = decide_concept(D(0), 0, TARGET)
    assert decision.action is Action.CONTINUE
    assert decision.next_kill_spend == D(120)


@pytest.mark.parametrize("purchases", [-1, 1.0, True])
def test_purchases_must_be_a_whole_number(purchases):
    with pytest.raises(ValueError):
        decide_concept(D(10), purchases, TARGET)


def test_product_is_killed_after_three_failed_concepts():
    concepts = [ConceptResult(f"c{i}", D(120), 0) for i in range(3)]
    decision = decide_product(concepts, target_cpa=TARGET, contribution_per_order=D(50))
    assert decision.action is Action.KILL
    assert "3 different concepts failed" in decision.reason


def test_product_is_killed_when_the_budget_is_spent_at_a_loss():
    concepts = [ConceptResult("a", D(300), 5), ConceptResult("b", D(200), 3)]
    decision = decide_product(concepts, target_cpa=TARGET, contribution_per_order=D(50))
    assert decision.budget == D(480)
    assert decision.contribution_after_ads == D(8 * 50 - 500)
    assert decision.action is Action.KILL


def test_product_continues_past_budget_while_it_pays_its_way():
    concepts = [ConceptResult("a", D(300), 7), ConceptResult("b", D(200), 3)]
    decision = decide_product(concepts, target_cpa=TARGET, contribution_per_order=D(60))
    assert decision.action is Action.CONTINUE
    assert "paying for its advertising" in decision.reason


def test_a_scaling_concept_scales_the_product():
    concepts = [ConceptResult("winner", D(700), 20), ConceptResult("loser", D(130), 0)]
    decision = decide_product(concepts, target_cpa=TARGET, contribution_per_order=D(50))
    assert decision.action is Action.SCALE
    assert "winner" in decision.reason


def test_concept_names_must_be_unique():
    with pytest.raises(ValueError):
        decide_product([ConceptResult("a", D(1), 0), ConceptResult("a", D(2), 0)],
                       target_cpa=TARGET, contribution_per_order=D(1))
