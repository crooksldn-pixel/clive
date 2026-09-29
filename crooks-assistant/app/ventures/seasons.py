"""Retail dates by market and the arithmetic of launching in time for them.

Dates are computed from their rules (Easter by the anonymous Gregorian algorithm, "second Sunday
of May" and so on) rather than typed in, so they stay right in later years. Chinese New Year is
lunar and is the one table here. The supplier slowdown around it is the engine's own assumption:
factories close for longer than the official holiday, so the window runs from ten days before to
twenty after.

Launch timing is a subtraction (research): the last day a customer can order is the event less
the delivery time and a buffer for the order to be placed; paid scaling has to start a ramp
before that, and creative testing a test period before scaling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

CHINESE_NEW_YEAR = {
    2025: date(2025, 1, 29),
    2026: date(2026, 2, 17),
    2027: date(2027, 2, 6),
    2028: date(2028, 1, 26),
    2029: date(2029, 2, 13),
    2030: date(2030, 2, 3),
}
EVENTS = ("valentines", "mothers_day", "fathers_day", "halloween", "black_friday", "cyber_monday", "christmas")
_LABELS = {
    "valentines": "Valentine's Day",
    "mothers_day": "Mother's Day",
    "fathers_day": "Father's Day",
    "halloween": "Halloween",
    "black_friday": "Black Friday",
    "cyber_monday": "Cyber Monday",
    "christmas": "Christmas",
}


def _country(market: str) -> str:
    """The country a market code dates its events by: EU-FR is FR, UK-NOVAT is UK."""
    return market.split("-")[-1] if market.startswith("EU-") else market.split("-")[0]


def event_label(event: str, market: str) -> str:
    """How the owner would name the event: Mothering Sunday in the UK and Ireland."""
    if event == "mothers_day" and _country(market) in ("UK", "IE"):
        return "Mothering Sunday"
    try:
        return _LABELS[event]
    except KeyError:
        raise ValueError(f"unknown event {event!r}") from None


def easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``th ``weekday`` (Monday 0) of a month; ``n = -1`` is the last."""
    if n == -1:
        last = (date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


SUNDAY, THURSDAY = 6, 3


def event_date(event: str, market: str, year: int) -> date:
    """When ``event`` falls in ``market`` (a market code such as UK, US or EU-FR) in ``year``."""
    country = _country(market)
    if event == "valentines":
        return date(year, 2, 14)
    if event == "halloween":
        return date(year, 10, 31)
    if event == "christmas":
        return date(year, 12, 25)
    if event in ("black_friday", "cyber_monday"):
        friday = nth_weekday(year, 11, THURSDAY, 4) + timedelta(days=1)
        return friday if event == "black_friday" else friday + timedelta(days=3)
    if event == "mothers_day":
        if country in ("UK", "IE"):
            return easter(year) - timedelta(days=21)        # Mothering Sunday, fourth Sunday of Lent
        if country == "ES":
            return nth_weekday(year, 5, SUNDAY, 1)
        if country == "FR":
            last = nth_weekday(year, 5, SUNDAY, -1)
            pentecost = easter(year) + timedelta(days=49)
            return last if last != pentecost else nth_weekday(year, 6, SUNDAY, 1)
        if country in ("US", "DE", "IT", "NL"):
            return nth_weekday(year, 5, SUNDAY, 2)
    if event == "fathers_day":
        if country == "DE":
            return easter(year) + timedelta(days=39)        # Ascension Day
        if country in ("ES", "IT"):
            return date(year, 3, 19)                        # St Joseph's Day
        if country in ("UK", "IE", "US", "FR", "NL"):
            return nth_weekday(year, 6, SUNDAY, 3)
    raise ValueError(f"no date for {event!r} in {market!r}; events: {', '.join(EVENTS)}")


def next_event_date(event: str, market: str, today: date) -> date:
    """The next time ``event`` falls in ``market`` on or after ``today``."""
    this_year = event_date(event, market, today.year)
    return this_year if this_year >= today else event_date(event, market, today.year + 1)


@dataclass(frozen=True, slots=True)
class Slowdown:
    name: str
    start: date
    end: date


def supplier_slowdowns(year: int) -> tuple[Slowdown, ...]:
    """China's Golden Week and the Spring Festival window for ``year``, when supplier orders slow."""
    windows = [Slowdown("Golden Week", date(year, 10, 1), date(year, 10, 7))]
    new_year = CHINESE_NEW_YEAR.get(year)
    if new_year is not None:
        windows.append(Slowdown("Spring Festival", new_year - timedelta(days=10), new_year + timedelta(days=20)))
    return tuple(sorted(windows, key=lambda window: window.start))


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    event: date
    order_cutoff: date
    scale_start: date
    test_start: date
    feasible: bool
    warnings: tuple[str, ...]


def plan_launch(
    event: date,
    *,
    delivery_days: int,
    today: date,
    order_buffer_days: int = 3,
    ramp_days: int = 14,
    test_days: int = 10,
) -> LaunchPlan:
    """Work back from ``event``: the last day a customer can order, when paid scaling must start,
    and when creative testing must start. ``delivery_days`` is the slow end of delivery, not the
    advertised one (sellers report 10-25 days where China-direct shipping advertises 7-17)."""
    for name, value in (("delivery_days", delivery_days), ("order_buffer_days", order_buffer_days),
                        ("ramp_days", ramp_days), ("test_days", test_days)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a whole number of days at least 0")
    cutoff = event - timedelta(days=delivery_days + order_buffer_days)
    scale_start = cutoff - timedelta(days=ramp_days)
    test_start = scale_start - timedelta(days=test_days)
    warnings: list[str] = []
    feasible = test_start >= today
    if not feasible:
        warnings.append(
            f"too late at this delivery time: testing had to start by {test_start.isoformat()}"
        )
    for year in range(test_start.year, cutoff.year + 1):
        for window in supplier_slowdowns(year):
            if window.start <= cutoff and window.end >= test_start:
                warnings.append(
                    f"{window.name} ({window.start.isoformat()} to {window.end.isoformat()}) falls "
                    "inside the plan: supplier orders and restocks slow down"
                )
    return LaunchPlan(event, cutoff, scale_start, test_start, feasible, tuple(warnings))
