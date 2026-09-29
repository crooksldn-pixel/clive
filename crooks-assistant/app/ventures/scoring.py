"""A product's score and its lifecycle stage, from what the research sources and early tests say.

The score follows the research's structure: demand momentum times economics times one minus
saturation times validation, less a weighted risk. Each factor is between 0 and 1. The four are
combined as a geometric mean, which orders products as their plain product would but reads on a
0-100 scale instead of shrinking towards zero as factors multiply; the weighted risk is then
subtracted on that scale. Every
threshold is a starting prior (docs/product-memory/VENTURE_ENGINE_V1.md) to be recalibrated from
the engine's own tests, not a validated model. The folklore criteria ("wow factor", "not
sold locally", "light and unbreakable") are not scored: the research found no evidence for them.

A missing signal is never good news: an unknown factor scores below the middle and is listed as
missing, so a thinly researched product cannot outrank a well-evidenced one by silence. A product
the compliance screen blocks is excluded, whatever its score."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.ventures.economics import as_rate

ZERO = Decimal(0)
ONE = Decimal(1)


class Stage(StrEnum):
    EMERGING = "EMERGING"
    GROWING = "GROWING"
    PEAKING = "PEAKING"
    DECLINING = "DECLINING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MarketSignals:
    """What the research sources said about a product, as the caller read them.

    ``search_growth_4w``: change in search or trend interest over four weeks (0.35 for +35%).
    ``daily_orders`` and ``lifetime_orders``: order velocity on the supplier marketplace.
    ``advertisers``: distinct advertisers running a near-identical product.
    ``price_change_8w``: change in the going price over eight weeks (-0.15 for down 15%).
    ``complaint_rate``: share of reviews citing poor quality or "not as advertised".
    """

    search_growth_4w: Decimal | None = None
    daily_orders: int | None = None
    lifetime_orders: int | None = None
    advertisers: int | None = None
    price_change_8w: Decimal | None = None
    complaint_rate: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("daily_orders", "lifetime_orders", "advertisers"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a whole number at least 0")
        if self.complaint_rate is not None:
            object.__setattr__(self, "complaint_rate", as_rate("complaint_rate", self.complaint_rate))
        for name in ("search_growth_4w", "price_change_8w"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal")


@dataclass(frozen=True, slots=True)
class CreativeSignals:
    """Early creative-test metrics, when there are any: hook rate (three-second views over
    impressions), click-through rate and add-to-cart rate."""

    hook_rate: Decimal | None = None
    ctr: Decimal | None = None
    add_to_cart_rate: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("hook_rate", "ctr", "add_to_cart_rate"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, as_rate(name, value))


@dataclass(frozen=True, slots=True)
class Priors:
    """The thresholds behind each factor. The research-sourced ones are marked; the rest are the
    engine's own starting assumptions."""

    growth_floor: Decimal = Decimal("-0.10")      # search growth scoring 0
    growth_ceiling: Decimal = Decimal("0.50")     # search growth scoring 1
    orders_ceiling: int = 100                     # daily orders scoring 1
    roas_best: Decimal = Decimal("1.5")           # break-even ROAS scoring 1
    roas_worst: Decimal = Decimal("3.5")          # break-even ROAS scoring 0
    crowded_advertisers: int = 20                 # research: 15-20 advertisers means saturation
    price_collapse: Decimal = Decimal("-0.30")    # an eight-week price fall scoring full saturation
    hook_range: tuple[Decimal, Decimal] = (Decimal("0.15"), Decimal("0.35"))   # research: 25% baseline, 30-40% good
    ctr_range: tuple[Decimal, Decimal] = (Decimal("0.005"), Decimal("0.02"))   # research: 0.8-2% normal
    atc_range: tuple[Decimal, Decimal] = (Decimal("0.03"), Decimal("0.08"))    # research: 5-8% acceptable
    complaint_ceiling: Decimal = Decimal("0.25")  # complaint rate scoring full risk
    owner_gate_risk: Decimal = Decimal("0.25")    # risk added when a safety decision is needed
    risk_weight: Decimal = Decimal("0.25")
    unknown: Decimal = Decimal("0.35")            # an unknown factor: below the middle, never good news


DEFAULT_PRIORS = Priors()


@dataclass(frozen=True, slots=True)
class ProductScore:
    name: str
    score: Decimal
    stage: Stage
    demand: Decimal
    economics: Decimal
    saturation: Decimal
    validation: Decimal
    risk: Decimal
    excluded: bool
    reasons: tuple[str, ...]
    missing: tuple[str, ...] = field(default=())


def classify_stage(signals: MarketSignals, priors: Priors = DEFAULT_PRIORS) -> tuple[Stage, str]:
    """Where a product sits in its lifecycle, by operator rules of thumb the research could not
    validate; the reason says which rule decided."""
    growth, price = signals.search_growth_4w, signals.price_change_8w
    if growth is not None and growth < Decimal("-0.10"):
        return Stage.DECLINING, f"search interest fell {-growth:.0%} in four weeks"
    if price is not None and price <= Decimal("-0.15"):
        return Stage.DECLINING, f"the going price fell {-price:.0%} in eight weeks"
    if signals.advertisers is not None and signals.advertisers > priors.crowded_advertisers:
        return Stage.PEAKING, f"{signals.advertisers} advertisers run a near-identical product"
    if (
        signals.lifetime_orders is not None
        and signals.daily_orders is not None
        and signals.lifetime_orders < 5000
        and 20 <= signals.daily_orders <= 50
    ):
        return Stage.EMERGING, "under 5,000 lifetime orders, selling 20-50 a day"
    if growth is not None and growth > Decimal("0.10"):
        return Stage.GROWING, f"search interest rose {growth:.0%} in four weeks"
    return Stage.UNKNOWN, "no rule of thumb applies to the signals given"


def score_product(
    name: str,
    *,
    signals: MarketSignals,
    tests: CreativeSignals,
    break_even_roas: Decimal | None,
    compliance_outcome: str,
    priors: Priors = DEFAULT_PRIORS,
) -> ProductScore:
    """Score one product. ``compliance_outcome`` is the screen's BLOCK, OWNER or CLEAR."""
    if compliance_outcome not in ("BLOCK", "OWNER", "CLEAR"):
        raise ValueError("compliance_outcome must be BLOCK, OWNER or CLEAR")
    reasons: list[str] = []
    missing: list[str] = []

    demand_parts = []
    if signals.search_growth_4w is not None:
        demand_parts.append(_scale(signals.search_growth_4w, priors.growth_floor, priors.growth_ceiling))
    if signals.daily_orders is not None:
        demand_parts.append(_scale(Decimal(signals.daily_orders), ZERO, Decimal(priors.orders_ceiling)))
    if demand_parts:
        demand = _mean(demand_parts)
    else:
        demand = priors.unknown
        missing.append("demand (search growth or order velocity)")

    if break_even_roas is None:
        economics = ZERO
        reasons.append("the order loses money before any advertising")
    else:
        economics = _scale(break_even_roas, priors.roas_worst, priors.roas_best)

    saturation_parts = []
    if signals.advertisers is not None:
        saturation_parts.append(_scale(Decimal(signals.advertisers), ZERO, Decimal(priors.crowded_advertisers)))
    if signals.price_change_8w is not None and signals.price_change_8w < 0:
        saturation_parts.append(_scale(signals.price_change_8w, ZERO, priors.price_collapse))
    if saturation_parts:
        saturation = max(saturation_parts)
    else:
        saturation = ONE - priors.unknown
        missing.append("saturation (advertiser count or price trend)")

    validation_parts = []
    for value, (low, high) in (
        (tests.hook_rate, priors.hook_range),
        (tests.ctr, priors.ctr_range),
        (tests.add_to_cart_rate, priors.atc_range),
    ):
        if value is not None:
            validation_parts.append(_scale(value, low, high))
    if validation_parts:
        validation = _mean(validation_parts)
    else:
        validation = priors.unknown
        missing.append("validation (no creative test yet)")

    risk = ZERO
    if signals.complaint_rate is not None:
        risk = _scale(signals.complaint_rate, ZERO, priors.complaint_ceiling)
    else:
        missing.append("return risk (complaint rate from reviews)")
    if compliance_outcome == "OWNER":
        risk = min(ONE, risk + priors.owner_gate_risk)
        reasons.append("needs the owner's safety decision before any test")

    merit = _geometric_mean((demand, economics, ONE - saturation, validation))
    score = (max(ZERO, merit - priors.risk_weight * risk) * 100).quantize(Decimal("0.1"))
    stage, why = classify_stage(signals, priors)
    reasons.append(f"stage {stage}: {why}")
    excluded = compliance_outcome == "BLOCK"
    if excluded:
        reasons.insert(0, "blocked by the compliance screen; not ranked")
    return ProductScore(
        name=name, score=score, stage=stage, demand=demand, economics=economics,
        saturation=saturation, validation=validation, risk=risk, excluded=excluded,
        reasons=tuple(reasons), missing=tuple(missing),
    )


def rank(scores: Sequence[ProductScore], limit: int = 5) -> list[ProductScore]:
    """The best products for the owner to look at: blocked ones out, highest score first, then by
    name so equal scores always come out in the same order. Five at most by default, because
    agents and people both choose worse from long lists (Microsoft's Magentic Marketplace)."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    eligible = [s for s in scores if not s.excluded]
    return sorted(eligible, key=lambda s: (-s.score, s.name))[:limit]


def _scale(value: Decimal, zero_at: Decimal, one_at: Decimal) -> Decimal:
    """Map ``value`` linearly so ``zero_at`` gives 0 and ``one_at`` gives 1, clamped to [0, 1]."""
    if one_at == zero_at:
        raise ValueError("a factor's two ends must differ")
    return min(ONE, max(ZERO, (value - zero_at) / (one_at - zero_at)))


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO) / len(values)


def _geometric_mean(values: Sequence[Decimal]) -> Decimal:
    """The nth root of the product; zero when any factor is zero."""
    product = ONE
    for value in values:
        product *= value
    if product <= 0:
        return ZERO
    return (product.ln() / len(values)).exp()
