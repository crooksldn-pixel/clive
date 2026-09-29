"""When to stop a test, when to keep going and when to scale, from arithmetic rather than folklore.

Purchases in a test are treated as arriving at random at a steady rate: with a true cost per
purchase ``C``, spending ``S`` buys on average ``S / C`` purchases, and the count is Poisson.
That gives each rule a measurable cost. If a concept is exactly on target, the chance of seeing
no purchase after spending 3x the target is e^-3, about 5%; the chance of at most one after 5x is
6e^-5, about 4%. The common "kill at 1-2x the target" rule throws away 14-37% of concepts that
were in fact on target.

Scaling works the other way round. Twenty purchases still leave the true cost per purchase
anywhere between about 0.65x and 1.64x the observed figure (95%, exact Poisson interval), so a
concept is scaled on fewer than 20 purchases only when it looks far better than target.

Every threshold is a parameter. The defaults are the research's starting priors
(docs/product-memory/VENTURE_ENGINE_V1.md), to be recalibrated from the engine's own results,
and are expressed as multiples of the target, never as fixed sums, because advertising prices
move (Meta's median CPM rose about 20% and then 13% in consecutive years)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.ventures.economics import as_amount


class Action(StrEnum):
    KILL = "KILL"
    CONTINUE = "CONTINUE"
    SCALE = "SCALE"


def poisson_cdf(k: int, rate: float) -> float:
    """P(N <= k) for N ~ Poisson(rate), summed in log space so large rates do not underflow."""
    if rate < 0:
        raise ValueError("rate must be at least 0")
    if k < 0:
        return 0.0
    if rate == 0:
        return 1.0
    logs = [-rate + i * math.log(rate) - math.lgamma(i + 1) for i in range(k + 1)]
    peak = max(logs)
    return min(1.0, math.exp(peak) * math.fsum(math.exp(value - peak) for value in logs))


def rate_interval(events: int, confidence: float = 0.95) -> tuple[float, float]:
    """The exact (Garwood) two-sided interval for a Poisson rate after observing ``events``."""
    if events < 0:
        raise ValueError("events must be at least 0")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    tail = (1 - confidence) / 2
    upper = _solve(lambda rate: poisson_cdf(events, rate) - tail, events)
    lower = 0.0 if events == 0 else _solve(lambda rate: poisson_cdf(events - 1, rate) - (1 - tail), events)
    return lower, upper


def _solve(falling, start: int) -> float:
    """The root of a function that falls as the rate grows, by bisection."""
    low, high = 0.0, max(10.0, 3.0 * start + 30.0)
    while falling(high) > 0:
        high *= 2
    for _ in range(200):
        middle = (low + high) / 2
        if falling(middle) > 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


@dataclass(frozen=True, slots=True)
class KillRule:
    """Kill once spend reaches ``spend_multiple`` times the target with at most ``max_purchases``."""

    spend_multiple: Decimal
    max_purchases: int

    def false_kill(self) -> float:
        """The chance this rule kills a concept whose true cost per purchase is exactly on target."""
        return poisson_cdf(self.max_purchases, float(self.spend_multiple))


DEFAULT_KILL_RULES: tuple[KillRule, ...] = (KillRule(Decimal(3), 0), KillRule(Decimal(5), 1))


@dataclass(frozen=True, slots=True)
class ScalePolicy:
    """When a concept has earned more budget.

    ``min_purchases`` and ``max_cpa_ratio``: scale once there are this many purchases at or under
    this multiple of the target (research: 20, at target). ``early_max_cpa_ratio``: below
    ``min_purchases``, scale only at or under this multiple (research: 0.6).
    ``early_min_purchases`` is the engine's own floor under that early rule, so a single lucky
    purchase never scales anything; it is an assumption, not a research figure.
    """

    min_purchases: int = 20
    max_cpa_ratio: Decimal = Decimal(1)
    early_max_cpa_ratio: Decimal = Decimal("0.6")
    early_min_purchases: int = 5
    confidence: float = 0.95


DEFAULT_SCALE = ScalePolicy()


@dataclass(frozen=True, slots=True)
class ConceptDecision:
    action: Action
    reason: str
    spend: Decimal
    purchases: int
    target_cpa: Decimal
    observed_cpa: Decimal | None
    true_cpa_low: Decimal | None
    true_cpa_high: Decimal | None
    false_kill: float | None
    next_kill_spend: Decimal | None


def decide_concept(
    spend: object,
    purchases: int,
    target_cpa: object,
    *,
    kill_rules: Sequence[KillRule] = DEFAULT_KILL_RULES,
    scale: ScalePolicy = DEFAULT_SCALE,
) -> ConceptDecision:
    """KILL, CONTINUE or SCALE one creative concept from what it has spent and bought."""
    paid = as_amount("spend", spend)
    target = as_amount("target_cpa", target_cpa, positive=True)
    if isinstance(purchases, bool) or not isinstance(purchases, int) or purchases < 0:
        raise ValueError("purchases must be a whole number at least 0")
    rules = sorted(kill_rules, key=lambda rule: rule.spend_multiple)
    multiple = paid / target
    observed = paid / purchases if purchases else None
    low = high = None
    if purchases:
        rate_low, rate_high = rate_interval(purchases, scale.confidence)
        low = paid / Decimal(repr(rate_high))
        high = paid / Decimal(repr(rate_low))

    def decision(action: Action, reason: str, false_kill: float | None = None) -> ConceptDecision:
        return ConceptDecision(
            action=action, reason=reason, spend=paid, purchases=purchases, target_cpa=target,
            observed_cpa=observed, true_cpa_low=low, true_cpa_high=high, false_kill=false_kill,
            next_kill_spend=_next_kill(rules, multiple, purchases, target),
        )

    for rule in rules:
        if multiple >= rule.spend_multiple and purchases <= rule.max_purchases:
            return decision(
                Action.KILL,
                f"spent {rule.spend_multiple}x the target with {purchases_phrase(purchases)}; a "
                f"concept that was on target would look this bad {rule.false_kill():.0%} of the time",
                rule.false_kill(),
            )
    if purchases >= 2 and low is not None and low > target:
        return decision(
            Action.KILL,
            f"even the optimistic end of the true cost per purchase ({low:.2f}) is above the target",
            (1 - scale.confidence) / 2,
        )
    if observed is not None:
        if purchases >= scale.min_purchases and observed <= target * scale.max_cpa_ratio:
            return decision(Action.SCALE, f"{purchases} purchases at or under the target")
        if purchases >= scale.early_min_purchases and observed <= target * scale.early_max_cpa_ratio:
            return decision(
                Action.SCALE,
                f"{purchases} purchases at {observed / target:.2f}x the target, far enough under it "
                "to scale before 20",
            )
    return decision(Action.CONTINUE, "not enough evidence either way yet")


def purchases_phrase(count: int) -> str:
    """"no purchase", "one purchase", "3 purchases"."""
    return "no purchase" if count == 0 else "one purchase" if count == 1 else f"{count} purchases"


def _next_kill(rules: Sequence[KillRule], multiple: Decimal, purchases: int, target: Decimal) -> Decimal | None:
    for rule in rules:
        if purchases <= rule.max_purchases and multiple < rule.spend_multiple:
            return rule.spend_multiple * target
    return None


@dataclass(frozen=True, slots=True)
class ConceptResult:
    """What one creative concept has spent and bought so far."""

    name: str
    spend: Decimal
    purchases: int


@dataclass(frozen=True, slots=True)
class ProductPolicy:
    """When a whole product is stopped: after ``max_failed_concepts`` genuinely different concepts
    have been killed, or once ``budget_multiple`` times the target cost per purchase has been spent
    and the product's contribution after advertising is still negative (research: three concepts;
    10-15x the target, 12x here)."""

    max_failed_concepts: int = 3
    budget_multiple: Decimal = Decimal(12)


DEFAULT_PRODUCT = ProductPolicy()


@dataclass(frozen=True, slots=True)
class ProductDecision:
    action: Action
    reason: str
    budget: Decimal
    spent: Decimal
    purchases: int
    contribution_after_ads: Decimal
    concepts: tuple[tuple[str, ConceptDecision], ...]


def decide_product(
    concepts: Sequence[ConceptResult],
    *,
    target_cpa: object,
    contribution_per_order: object,
    policy: ProductPolicy = DEFAULT_PRODUCT,
    kill_rules: Sequence[KillRule] = DEFAULT_KILL_RULES,
    scale: ScalePolicy = DEFAULT_SCALE,
) -> ProductDecision:
    """KILL, CONTINUE or SCALE a product from the results of its concepts."""
    target = as_amount("target_cpa", target_cpa, positive=True)
    margin = as_amount("contribution_per_order", contribution_per_order)
    names = [concept.name for concept in concepts]
    if len(set(names)) != len(names):
        raise ValueError("two concepts share a name")
    decided = tuple(
        (c.name, decide_concept(c.spend, c.purchases, target, kill_rules=kill_rules, scale=scale))
        for c in concepts
    )
    spent = sum((d.spend for _, d in decided), Decimal(0))
    bought = sum(d.purchases for _, d in decided)
    net = bought * margin - spent
    budget = policy.budget_multiple * target
    killed = [name for name, d in decided if d.action is Action.KILL]
    scaling = [name for name, d in decided if d.action is Action.SCALE]

    def result(action: Action, reason: str) -> ProductDecision:
        return ProductDecision(action, reason, budget, spent, bought, net, decided)

    if scaling:
        return result(Action.SCALE, f"scale {', '.join(scaling)}")
    if len(killed) >= policy.max_failed_concepts:
        return result(Action.KILL, f"{len(killed)} different concepts failed")
    if spent >= budget and net < 0:
        return result(Action.KILL, "the test budget is spent and the product still loses money")
    if spent >= budget:
        return result(Action.CONTINUE, "the test budget is spent, but the product is paying for its advertising so far")
    return result(Action.CONTINUE, "within the test budget")
