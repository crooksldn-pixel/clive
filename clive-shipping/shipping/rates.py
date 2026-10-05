"""Choosing a service: one clear recommendation, plus cheapest and fastest when they differ.

The rule (deterministic; no guessing at carrier quality we have no evidence for):

1. Candidates are the provider's quotes for this parcel (door delivery, parcel fits).
2. "Reasonable" candidates have a delivery estimate of at most `max_days` (10). If none
   qualify, all candidates are considered.
3. The cheapest reasonable price sets the bar. Services within the allowance of it count as
   comparable: max(£1.00, 10% of the cheapest price). Nothing materially dearer is ever chosen
   for convenience.
4. Among comparable services:
   a. a carrier the merchant prefers (Setup), in their order, comes first;
   b. then customs paperwork expected: electronic, then unknown, then paper (printing and
      attaching A4 invoices is real work: a few pence don't outweigh it);
   c. then price, then the delivery estimate.
5. "Cheapest" is the cheapest candidate and "Fastest" the shortest estimate, each shown only
   when it differs from the recommendation (fastest only when it is actually quicker).

Customs paperwork per service is known only after buying (Parcel2Go's RequiresCommercialInvoice
is true for every international service). Knowledge comes from this shop's own labels, by
service and destination country; before any, from dated sandbox evidence, shown as "expected".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from shipping.models import CustomsMode, Quote
from shipping.money import Money

MAX_DAYS = 10
ALLOWANCE_MIN_MINOR = 100
ALLOWANCE_PCT = 10

# Seen in the Parcel2Go sandbox on 2026-10-05 (eight paid orders, GB to DE and US): which
# services filed customs electronically and which returned invoice copies to print. Used only
# until this shop's own labels say otherwise. Keys are service-slug prefixes.
SANDBOX_PAPERWORK: dict[str, tuple[CustomsMode, int]] = {
    "dpd-": (CustomsMode.electronic, 0),
    "landmark-": (CustomsMode.electronic, 0),
    "upsc-via-ocs": (CustomsMode.electronic, 0),
    "myhermes-international": (CustomsMode.paper, 3),
    "ups-access-point": (CustomsMode.paper, 4),
}
SANDBOX_SOURCE = "Parcel2Go sandbox, 5 Oct 2026"


@dataclass(frozen=True)
class Paperwork:
    mode: CustomsMode  # electronic, paper, or unknown
    copies: int = 0
    source: str = ""  # "your labels" or the sandbox evidence; "" when unknown

    @property
    def summary(self) -> str:
        if self.mode == CustomsMode.electronic:
            return "No customs paperwork expected"
        if self.mode == CustomsMode.paper:
            n = self.copies or "some"
            return f"Expect {n} A4 customs cop{'y' if self.copies == 1 else 'ies'} to print"
        if self.mode == CustomsMode.not_required:
            return "No customs on this route"
        return "Customs paperwork not known yet"


UNKNOWN = Paperwork(CustomsMode.unknown)


def sandbox_paperwork(service_code: str) -> Paperwork:
    for prefix, (mode, copies) in SANDBOX_PAPERWORK.items():
        if service_code.startswith(prefix):
            return Paperwork(mode, copies, SANDBOX_SOURCE)
    return UNKNOWN


@dataclass
class Option:
    quote: Quote
    paperwork: Paperwork
    roles: list[str] = field(default_factory=list)  # recommended, cheapest, fastest
    reason: str = ""


@dataclass
class Recommendation:
    recommended: Option | None
    cheapest: Option | None  # only when different from recommended
    fastest: Option | None  # only when different and quicker
    options: list[Option]  # every candidate, cheapest first


_PAPERWORK_RANK = {
    CustomsMode.electronic: 0,
    CustomsMode.not_required: 0,
    CustomsMode.unknown: 1,
    CustomsMode.paper: 2,
}


def recommend(
    quotes: Sequence[Quote],
    paperwork: Callable[[Quote], Paperwork] = lambda q: sandbox_paperwork(q.service_code),
    preferred_carriers: Sequence[str] = (),
    max_days: int = MAX_DAYS,
) -> Recommendation:
    options = sorted(
        (Option(q, paperwork(q)) for q in quotes),
        key=lambda o: (o.quote.amount.minor, o.quote.est_days_max or 99),
    )
    if not options:
        return Recommendation(None, None, None, [])
    reasonable = [
        o for o in options if o.quote.est_days_max is not None and o.quote.est_days_max <= max_days
    ] or options
    cheapest = reasonable[0]
    bar = cheapest.quote.amount.minor
    allowance = max(ALLOWANCE_MIN_MINOR, bar * ALLOWANCE_PCT // 100)
    comparable = [o for o in reasonable if o.quote.amount.minor <= bar + allowance]
    prefs = [p.lower() for p in preferred_carriers]

    def preference(o: Option) -> int:
        carrier = o.quote.carrier.lower()
        return prefs.index(carrier) if carrier in prefs else len(prefs)

    best = min(
        comparable,
        key=lambda o: (
            preference(o),
            _PAPERWORK_RANK.get(o.paperwork.mode, 1),
            o.quote.amount.minor,
            o.quote.est_days_max or 99,
        ),
    )
    best.roles.append("recommended")
    best.reason = _why(best, cheapest, preference(best) < len(prefs))

    cheapest_shown = None
    overall_cheapest = options[0]
    if overall_cheapest is not best:
        overall_cheapest.roles.append("cheapest")
        notes = [f"{_money_diff(best, overall_cheapest)} less than the recommendation"]
        if overall_cheapest.paperwork.mode == CustomsMode.paper:
            summary = overall_cheapest.paperwork.summary
            notes.append(summary[:1].lower() + summary[1:])
        days = overall_cheapest.quote.est_days_max
        if days is not None and days > max_days:
            notes.append(f"up to {days} days")
        overall_cheapest.reason = "; ".join(notes)
        cheapest_shown = overall_cheapest

    fastest_shown = None
    timed = [o for o in options if o.quote.est_days_max is not None]
    if timed:
        quickest = min(timed, key=lambda o: (o.quote.est_days_max or 99, o.quote.amount.minor))
        quick_days, best_days = quickest.quote.est_days_max or 99, best.quote.est_days_max
        if quickest is not best and (best_days is None or quick_days < best_days):
            quickest.roles.append("fastest")
            if "cheapest" in quickest.roles:  # cheaper and quicker: keep the cheapest note
                quickest.reason = f"Up to {quickest.quote.est_days_max} days; {quickest.reason}"
            else:
                quickest.reason = (
                    f"Up to {quickest.quote.est_days_max} days; {_more_or_less(quickest, best)} "
                    "than the recommendation"
                )
            fastest_shown = quickest
    return Recommendation(best, cheapest_shown, fastest_shown, options)


def _more_or_less(a: Option, b: Option) -> str:
    """ "£0.50 more" or "£0.50 less": a's price against b's."""
    word = "more" if a.quote.amount.minor >= b.quote.amount.minor else "less"
    return f"{_money_diff(a, b)} {word}"


def _money_diff(a: Option, b: Option) -> str:
    return str(Money(minor=abs(a.quote.amount.minor - b.quote.amount.minor)))


def _why(best: Option, cheapest: Option, preferred: bool) -> str:
    parts = []
    if preferred:
        parts.append(f"your preferred carrier ({best.quote.carrier})")
    if best is cheapest:
        parts.append("the cheapest reasonable service")
    else:
        parts.append(f"within {_money_diff(best, cheapest)} of the cheapest")
    paperless = best.paperwork.mode == CustomsMode.electronic
    if paperless and cheapest.paperwork.mode != CustomsMode.electronic:
        parts.append("with no customs paperwork to print")
    if best.quote.est_days_max:
        parts.append(f"up to {best.quote.est_days_max} days")
    return "Recommended: " + ", ".join(parts) + "."
