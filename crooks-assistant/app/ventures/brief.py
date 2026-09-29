"""One candidate in, one decision package out: the first thing the venture engine's button makes.

A brief screens the product, prices it from its floor, takes one order apart, sets the kill and
scale lines, scores it, times it against the retail calendar and says what the owner would be
asked to decide. It is a planning estimate from the figures the caller supplied. Nothing is
spent, listed, published or sent to produce it, and nothing it says executes: the asks are
written for the owner, in the words of CLIVE's decision kinds, and go no further.

The input is a JSON object (``SCHEMA_IN``); unknown keys are refused so a typo cannot silently
drop a cost. Money and rates are strings or JSON numbers read as Decimal, never floats."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal

from app.ventures.compliance import ProductFacts, Screen, screen
from app.ventures.economics import (
    Contribution,
    PriceFloor,
    UnitCosts,
    as_amount,
    as_rate,
    contribution,
    price_floor,
)
from app.ventures.markets import Market, format_money, market
from app.ventures.pricing import STYLES, changes_left_digit, present_price
from app.ventures.rules import (
    DEFAULT_KILL_RULES,
    DEFAULT_PRODUCT,
    DEFAULT_SCALE,
    ConceptResult,
    ProductDecision,
    decide_product,
    purchases_phrase,
)
from app.ventures.scoring import CreativeSignals, MarketSignals, ProductScore, score_product
from app.ventures.seasons import EVENTS, LaunchPlan, event_label, next_event_date, plan_launch

SCHEMA_IN = "clive.venture_candidate.v1"
SCHEMA_OUT = "clive.venture_brief.v1"

# Context for the break-even line, not an input to any decision: Triple Whale's median Meta
# ecommerce ROAS for August 2025 to July 2026, as reported in the 2026-09-29 research.
MEDIAN_META_ROAS = Decimal("1.88")

_TOP = {"schema", "name", "note", "market", "costs", "target_cpa", "target_margin", "product",
        "signals", "tests", "delivery_days", "price_style", "price", "event", "concepts"}
_REQUIRED = {"name", "market", "costs", "target_cpa", "target_margin", "product", "delivery_days"}
_COSTS = {"product", "shipping", "duty", "per_order_fixed", "payment_rate", "payment_fixed",
          "returns_rate", "commission_rate"}
_PRODUCT = {"categories", "for_children", "documents", "hood_or_neck_drawstrings", "listing_text"}
_SIGNALS = {"search_growth_4w", "daily_orders", "lifetime_orders", "advertisers", "price_change_8w",
            "complaint_rate"}
_TESTS = {"hook_rate", "ctr", "add_to_cart_rate"}
_CONCEPT = {"name", "spend", "purchases"}
_PRICE_SOURCES = {
    "owner": "your price",
    "charm": "the first price ending in .99 at or over the floor",
    "round": "the floor rounded up to a whole unit",
}


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    market: Market
    costs: UnitCosts
    target_cpa: Decimal
    target_margin: Decimal
    facts: ProductFacts
    signals: MarketSignals
    tests: CreativeSignals
    delivery_days: int
    price_style: str = "charm"
    price: Decimal | None = None
    event: str | None = None
    concepts: tuple[ConceptResult, ...] = ()
    note: str = ""


def load_candidate(data: Mapping[str, object]) -> Candidate:
    """A Candidate from its JSON form, refusing unknown keys, missing keys and floats."""
    data = _mapping("candidate", data)
    _keys("candidate", data, _TOP, _REQUIRED)
    schema = data.get("schema", SCHEMA_IN)
    if schema != SCHEMA_IN:
        raise ValueError(f"schema must be {SCHEMA_IN}, not {schema!r}")
    costs = _mapping("costs", data["costs"])
    _keys("costs", costs, _COSTS, _COSTS)
    product = _mapping("product", data["product"])
    _keys("product", product, _PRODUCT, {"categories", "for_children"})
    signals = _mapping("signals", data.get("signals", {}))
    _keys("signals", signals, _SIGNALS, set())
    tests = _mapping("tests", data.get("tests", {}))
    _keys("tests", tests, _TESTS, set())
    style = data.get("price_style", "charm")
    if style not in STYLES:
        raise ValueError(f"price_style must be one of {', '.join(STYLES)}")
    event = data.get("event")
    if event is not None and event not in EVENTS:
        raise ValueError(f"event must be one of {', '.join(EVENTS)}")
    concepts = []
    for raw in _list("concepts", data.get("concepts", [])):
        concept = _mapping("concept", raw)
        _keys("concept", concept, _CONCEPT, _CONCEPT)
        concepts.append(ConceptResult(
            name=_text("concept name", concept["name"]),
            spend=as_amount("concept spend", concept["spend"]),
            purchases=_whole("concept purchases", concept["purchases"]),
        ))
    price = data.get("price")
    return Candidate(
        name=_text("name", data["name"]),
        market=market(_text("market", data["market"])),
        costs=UnitCosts(**{key: costs[key] for key in _COSTS}),
        target_cpa=as_amount("target_cpa", data["target_cpa"], positive=True),
        target_margin=as_rate("target_margin", data["target_margin"]),
        facts=ProductFacts(
            categories=frozenset(_strings("categories", product["categories"])),
            for_children=_flag("for_children", product["for_children"]),
            documents=frozenset(_strings("documents", product.get("documents", []))),
            hood_or_neck_drawstrings=_flag("hood_or_neck_drawstrings", product.get("hood_or_neck_drawstrings", False)),
            listing_text=_text("listing_text", product.get("listing_text", ""), empty=True),
        ),
        signals=MarketSignals(
            search_growth_4w=_optional_decimal("search_growth_4w", signals.get("search_growth_4w")),
            daily_orders=_optional_whole("daily_orders", signals.get("daily_orders")),
            lifetime_orders=_optional_whole("lifetime_orders", signals.get("lifetime_orders")),
            advertisers=_optional_whole("advertisers", signals.get("advertisers")),
            price_change_8w=_optional_decimal("price_change_8w", signals.get("price_change_8w")),
            complaint_rate=_optional_decimal("complaint_rate", signals.get("complaint_rate")),
        ),
        tests=CreativeSignals(**{key: _optional_decimal(key, tests.get(key)) for key in _TESTS}),
        delivery_days=_whole("delivery_days", data["delivery_days"]),
        price_style=str(style),
        price=None if price is None else as_amount("price", price, positive=True),
        event=None if event is None else str(event),
        concepts=tuple(concepts),
        note=_text("note", data.get("note", ""), empty=True),
    )


@dataclass(frozen=True, slots=True)
class Brief:
    candidate: Candidate
    today: date
    verdict: str
    headline: str
    screen: Screen
    floor: PriceFloor | None
    price: Decimal | None
    price_source: str
    order: Contribution | None
    score: ProductScore
    test_budget: Decimal
    results: ProductDecision | None
    launch: LaunchPlan | None
    asks: tuple[str, ...]
    notes: tuple[str, ...]


def build_brief(candidate: Candidate, today: date) -> Brief:
    """Everything the owner needs to decide whether to fund a test of this product."""
    c = candidate

    def money(amount: Decimal) -> str:
        return format_money(amount, c.market.currency)

    checked = screen(c.facts, [c.market.region])
    notes: list[str] = []
    floor: PriceFloor | None
    try:
        floor = price_floor(c.costs, c.market, target_cpa=c.target_cpa, target_margin=c.target_margin)
    except ValueError as error:
        floor = None
        notes.append(str(error))
    if c.price is not None:
        price, source = c.price, "owner"
    elif floor is not None:
        price, source = present_price(floor.shown_minimum, c.price_style), c.price_style
    else:
        price, source = None, "none"
    order = contribution(price, c.costs, c.market) if price is not None else None
    roas = order.break_even_roas if order is not None else None
    score = score_product(c.name, signals=c.signals, tests=c.tests, break_even_roas=roas,
                          compliance_outcome=checked.outcome)
    budget = DEFAULT_PRODUCT.budget_multiple * c.target_cpa
    results = None
    if c.concepts and order is not None:
        results = decide_product(c.concepts, target_cpa=c.target_cpa,
                                 contribution_per_order=max(order.contribution, Decimal(0)))
    launch = None
    if c.event is not None:
        event_day = next_event_date(c.event, c.market.code, today)
        launch = plan_launch(event_day, delivery_days=c.delivery_days, today=today)

    below_floor = floor is not None and price is not None and price < floor.shown_minimum
    if checked.outcome == "BLOCK":
        verdict, headline = "BLOCKED", checked.summary
    elif floor is None:
        verdict = "NOT_VIABLE"
        headline = f"No price can pay {money(c.target_cpa)} per purchase and keep {c.target_margin:.0%}."
    elif order is None or order.contribution <= 0:
        verdict, headline = "NOT_VIABLE", "An order loses money before any advertising."
    elif below_floor:
        verdict = "NOT_VIABLE"
        headline = (f"At {money(price)} an order cannot pay {money(c.target_cpa)} per purchase and keep "
                    f"{c.target_margin:.0%}; the floor is {money(floor.shown_minimum)}.")
    elif checked.outcome == "OWNER":
        verdict, headline = "NEEDS_OWNER", checked.summary
    else:
        verdict = "READY_TO_PROPOSE"
        headline = f"Worth proposing a test at {money(price)}."

    asks: list[str] = []
    if verdict in ("NEEDS_OWNER", "READY_TO_PROPOSE"):
        for finding in checked.findings:
            if finding.outcome == "OWNER":
                asks.append(f"SAFETY: {finding.why}. The default is to reject.")
        asks.append(
            f"PRODUCT_DIRECTION: fund a test of up to {money(budget)} "
            f"({DEFAULT_PRODUCT.budget_multiple}x the target cost per purchase), across at least "
            "three genuinely different creative concepts."
        )
    if launch is not None and c.event is not None and not launch.feasible:
        notes.append(f"Too late for {event_label(c.event, c.market.code)} on {launch.event.isoformat()} "
                     f"at {c.delivery_days} days' delivery.")
    if c.note:
        notes.append(c.note)
    return Brief(c, today, verdict, headline, checked, floor, price, source, order, score, budget,
                 results, launch, tuple(asks), tuple(notes))


def render_markdown(brief: Brief) -> str:
    """The brief as the owner reads it."""
    c = brief.candidate

    def money(amount: Decimal) -> str:
        return format_money(amount, c.market.currency)

    target = c.target_cpa
    lines = [
        f"# Venture brief: {c.name}",
        "",
        f"**Verdict: {brief.verdict.replace('_', ' ')}.** {brief.headline}",
        "",
        f"{c.market.label}. Prepared {brief.today.isoformat()} from the figures supplied. "
        "A planning estimate: nothing was spent, listed, published or sent.",
        "",
        "## Compliance",
        "",
        brief.screen.summary,
    ]
    for finding in brief.screen.findings:
        clears = f" Clears with: {'; '.join(finding.clears_with)}." if finding.clears_with else ""
        lines.append(f"- {finding.outcome} ({finding.rule}): {finding.why}.{clears}")
    lines += ["", "## Price", ""]
    if brief.floor is None:
        lines.append("- No floor: no price meets the targets (see the notes).")
    else:
        f = brief.floor
        lines.append(f"- Floor: {money(f.shown_minimum)}, {f.landed_multiple:.1f}x the landed cost of "
                     f"{money(f.landed)}, paying {money(f.target_cpa)} per purchase and keeping "
                     f"{f.target_margin:.0%} of net revenue.")
    if brief.price is not None:
        left = " It changes the left digit, where a .99 ending helps most." if (
            brief.price_source == "charm" and changes_left_digit(brief.price)) else ""
        lines.append(f"- Price: {money(brief.price)}, {_PRICE_SOURCES[brief.price_source]}.{left}")
    if brief.order is not None:
        o = brief.order
        lines += ["", f"## One order at {money(o.price)}", ""]
        lines.append(f"- Net of tax {money(o.net_revenue)}; costs {money(o.fixed_costs)} fixed, "
                     f"{money(o.rate_costs)} in fees and commission, {money(o.returns_allowance)} "
                     "set aside for returns.")
        lines.append(f"- Contribution before advertising: {money(o.contribution)} "
                     f"({o.margin_on_price:.0%} of the price).")
        if o.break_even_roas is not None:
            at_median = o.contribution - o.price / MEDIAN_META_ROAS
            lines.append(f"- Break-even ROAS {_roas_up(o.break_even_roas)}; break-even cost per purchase "
                         f"{money(o.contribution)}.")
            lines.append(f"- At the median Meta ecommerce ROAS of {MEDIAN_META_ROAS} (Triple Whale, "
                         f"August 2025 to July 2026) an order would {'make' if at_median >= 0 else 'lose'} "
                         f"{money(abs(at_median))} after advertising: profit has to come from doing "
                         "better than the median.")
            lines.append(f"- After the target {money(target)} per purchase it keeps "
                         f"{o.margin_after(target):.0%} of net revenue.")
    if brief.verdict != "BLOCKED":
        lines += ["", "## Test plan", ""]
        for rule in DEFAULT_KILL_RULES:
            lines.append(f"- Kill a concept at {money(rule.spend_multiple * target)} spent with "
                         f"{'no purchase' if rule.max_purchases == 0 else 'at most ' + purchases_phrase(rule.max_purchases)}: "
                         f"a concept that was on target would be killed {rule.false_kill():.0%} of the time.")
        lines.append(f"- Scale a concept at {DEFAULT_SCALE.min_purchases} purchases at or under "
                     f"{money(target)} each, or from {DEFAULT_SCALE.early_min_purchases} purchases at "
                     f"or under {money(target * DEFAULT_SCALE.early_max_cpa_ratio)} each.")
        lines.append(f"- Stop the product after {DEFAULT_PRODUCT.max_failed_concepts} failed concepts, "
                     f"or once {money(brief.test_budget)} is spent and it still loses money.")
    if brief.results is not None:
        r = brief.results
        lines += ["", "## Results so far", "", f"- Product: {r.action}, {r.reason}.",
                  f"- {money(r.spent)} spent of the {money(r.budget)} test budget, "
                  f"{purchases_phrase(r.purchases)}, {money(r.contribution_after_ads)} after advertising."]
        for name, d in r.concepts:
            lines.append(f"- {name}: {d.action}, {d.reason}.")
    s = brief.score
    lines += ["", "## Score", "",
              f"- {s.score} of 100{' (excluded: blocked)' if s.excluded else ''}; stage {s.stage}.",
              f"- Demand {s.demand:.2f}, economics {s.economics:.2f}, saturation {s.saturation:.2f}, "
              f"validation {s.validation:.2f}, risk {s.risk:.2f}."]
    lines += [f"- {reason[0].upper()}{reason[1:]}." for reason in s.reasons]
    if s.missing:
        lines.append(f"- Missing: {'; '.join(s.missing)}.")
    if brief.launch is not None and c.event is not None:
        p = brief.launch
        lines += ["", f"## Timing for {event_label(c.event, c.market.code)} ({p.event.isoformat()})", "",
                  f"- Start testing by {p.test_start.isoformat()}, scaling by {p.scale_start.isoformat()}; "
                  f"the last customer order that arrives in time is {p.order_cutoff.isoformat()}."]
        lines += [f"- {warning[0].upper()}{warning[1:]}." for warning in p.warnings]
    lines += ["", "## What you would be asked to decide", ""]
    lines += [f"- {ask}" for ask in brief.asks] or ["- Nothing: the product is not proposed."]
    if brief.notes:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in brief.notes]
    return "\n".join(lines) + "\n"


def brief_to_dict(brief: Brief) -> dict[str, object]:
    """The brief as JSON-safe data: money and rates as strings, probabilities to four places."""
    c = brief.candidate
    order = brief.order
    return {
        "schema": SCHEMA_OUT,
        "name": c.name,
        "market": c.market.code,
        "currency": c.market.currency,
        "prepared": brief.today.isoformat(),
        "verdict": brief.verdict,
        "headline": brief.headline,
        "external_effects": "none",
        "compliance": {
            "outcome": brief.screen.outcome,
            "findings": [
                {"outcome": f.outcome, "rule": f.rule, "why": f.why, "clears_with": list(f.clears_with)}
                for f in brief.screen.findings
            ],
        },
        "floor": None if brief.floor is None else {
            "shown": str(brief.floor.shown_minimum),
            "landed_multiple": str(brief.floor.landed_multiple.quantize(Decimal("0.01"))),
        },
        "price": None if brief.price is None else str(brief.price),
        "price_source": brief.price_source,
        "order": None if order is None else {
            "net_revenue": _cents(order.net_revenue),
            "contribution": _cents(order.contribution),
            "break_even_roas": None if order.break_even_roas is None else str(_roas_up(order.break_even_roas)),
            "margin_after_target_cpa": str(order.margin_after(c.target_cpa).quantize(Decimal("0.0001"))),
        },
        "test_budget": _cents(brief.test_budget),
        "kill_lines": [
            {"spend": _cents(rule.spend_multiple * c.target_cpa), "max_purchases": rule.max_purchases,
             "false_kill": round(rule.false_kill(), 4)}
            for rule in DEFAULT_KILL_RULES
        ],
        "results": None if brief.results is None else {
            "action": str(brief.results.action),
            "reason": brief.results.reason,
            "spent": _cents(brief.results.spent),
            "purchases": brief.results.purchases,
            "contribution_after_ads": _cents(brief.results.contribution_after_ads),
            "concepts": {name: str(d.action) for name, d in brief.results.concepts},
        },
        "score": {
            "score": str(brief.score.score),
            "stage": str(brief.score.stage),
            "excluded": brief.score.excluded,
            "missing": list(brief.score.missing),
        },
        "launch": None if brief.launch is None else {
            "event": brief.launch.event.isoformat(),
            "test_start": brief.launch.test_start.isoformat(),
            "scale_start": brief.launch.scale_start.isoformat(),
            "order_cutoff": brief.launch.order_cutoff.isoformat(),
            "feasible": brief.launch.feasible,
            "warnings": list(brief.launch.warnings),
        },
        "asks": list(brief.asks),
        "notes": list(brief.notes),
    }


def _roas_up(roas: Decimal) -> Decimal:
    """A break-even ROAS to two places, rounded up: it is a bar to clear, so it is never shown lower
    than it is."""
    return roas.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def _cents(amount: Decimal) -> str:
    return str(amount.quantize(Decimal("0.01")))


def _keys(what: str, data: Mapping[str, object], allowed: set[str], required: set[str]) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"{what} has unknown keys: {', '.join(sorted(unknown))}")
    missing = required - set(data)
    if missing:
        raise ValueError(f"{what} is missing: {', '.join(sorted(missing))}")


def _mapping(what: str, value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{what} must be an object")
    return value


def _list(what: str, value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{what} must be a list")
    return value


def _strings(what: str, value: object) -> list[str]:
    items = _list(what, value)
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"{what} must be a list of strings")
    return [str(item) for item in items]


def _text(what: str, value: object, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{what} must be {'text' if empty else 'non-empty text'}")
    return value


def _flag(what: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{what} must be true or false")
    return value


def _whole(what: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{what} must be a whole number at least 0")
    return value


def _optional_whole(what: str, value: object) -> int | None:
    return None if value is None else _whole(what, value)


def _optional_decimal(what: str, value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float) or not isinstance(value, Decimal | int | str):
        raise ValueError(f"{what} must be a number written as a string or a JSON number")
    try:
        decimal = Decimal(value)
    except ArithmeticError:
        raise ValueError(f"{what} is not a number: {value!r}") from None
    if not decimal.is_finite():
        raise ValueError(f"{what} must be finite")
    return decimal
