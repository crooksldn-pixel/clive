"""Product score, lifecycle stage and ranking."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ventures.scoring import (
    CreativeSignals,
    MarketSignals,
    Stage,
    classify_stage,
    rank,
    score_product,
)

D = Decimal


def _score(name="p", signals=None, tests=None, roas=D("1.8"), outcome="CLEAR"):
    return score_product(name, signals=signals or MarketSignals(), tests=tests or CreativeSignals(),
                         break_even_roas=roas, compliance_outcome=outcome)


def test_stages_follow_the_rules_of_thumb():
    assert classify_stage(MarketSignals(search_growth_4w=D("-0.2")))[0] is Stage.DECLINING
    assert classify_stage(MarketSignals(price_change_8w=D("-0.2")))[0] is Stage.DECLINING
    assert classify_stage(MarketSignals(advertisers=25))[0] is Stage.PEAKING
    assert classify_stage(MarketSignals(lifetime_orders=3000, daily_orders=30))[0] is Stage.EMERGING
    assert classify_stage(MarketSignals(search_growth_4w=D("0.3")))[0] is Stage.GROWING
    assert classify_stage(MarketSignals())[0] is Stage.UNKNOWN


def test_missing_signals_are_never_good_news():
    evidenced = _score(signals=MarketSignals(search_growth_4w=D("0.3"), daily_orders=60, advertisers=4,
                                             complaint_rate=D("0.02")),
                       tests=CreativeSignals(hook_rate=D("0.32"), ctr=D("0.015"), add_to_cart_rate=D("0.06")))
    silent = _score()
    assert evidenced.score > silent.score
    assert len(silent.missing) == 4
    assert evidenced.missing == ()


def test_crowding_and_complaints_lower_the_score():
    base = MarketSignals(search_growth_4w=D("0.3"), daily_orders=60, complaint_rate=D("0.02"))
    open_market = _score(signals=MarketSignals(**{**_fields(base), "advertisers": 2}))
    crowded = _score(signals=MarketSignals(**{**_fields(base), "advertisers": 19}))
    complained = _score(signals=MarketSignals(**{**_fields(base), "advertisers": 2, "complaint_rate": D("0.2")}))
    assert open_market.score > crowded.score
    assert open_market.score > complained.score


def test_an_order_that_loses_money_scores_zero_economics():
    result = _score(roas=None)
    assert result.economics == 0
    assert result.score == 0


def test_blocked_products_are_excluded_and_owner_gates_add_risk():
    assert _score(outcome="BLOCK").excluded
    assert _score(outcome="OWNER").risk > _score(outcome="CLEAR").risk
    with pytest.raises(ValueError):
        _score(outcome="MAYBE")


def test_rank_is_deterministic_limited_and_skips_blocked():
    scores = [_score(name=n, signals=MarketSignals(daily_orders=d)) for n, d in
              [("b", 50), ("a", 50), ("c", 90), ("d", 10), ("e", 30), ("f", 70)]]
    scores.append(_score(name="z", signals=MarketSignals(daily_orders=100), outcome="BLOCK"))
    ranked = rank(scores)
    assert [s.name for s in ranked] == ["c", "f", "a", "b", "e"]
    assert rank(scores, limit=2) == ranked[:2]
    with pytest.raises(ValueError):
        rank(scores, limit=0)


def test_signals_are_validated():
    with pytest.raises(ValueError):
        MarketSignals(daily_orders=-1)
    with pytest.raises(TypeError):
        MarketSignals(search_growth_4w=0.3)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CreativeSignals(ctr=D("1.2"))


def _fields(signals: MarketSignals) -> dict:
    return {name: getattr(signals, name) for name in MarketSignals.__slots__}
