"""Periods, resolved in the shop's own time zone. "This week" is Monday to now in London,
whatever the clock on the Mac says; "last week" is the whole of the week before; a relative
"last 7 days" ends now and starts seven midnights back. Every period knows the one before it,
for a comparison."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

MAX_DAYS = 365          # "since launch" is bounded: a year of orders is what the Mac keeps in reach
DEFAULT_DAYS = 30

NAMED = ("today", "yesterday", "this_week", "last_week", "this_month", "last_month", "last_7_days", "last_30_days", "last_90_days", "since_launch")

# What the owner says, to the period it means. Spoken forms are matched loosely by the tool.
ALIASES = {
    "today": "today", "yesterday": "yesterday", "this week": "this_week", "week": "this_week", "last week": "last_week",
    "this month": "this_month", "month": "this_month", "last month": "last_month", "last 7 days": "last_7_days", "past week": "last_7_days",
    "7 days": "last_7_days", "last 30 days": "last_30_days", "past month": "last_30_days", "30 days": "last_30_days",
    "last 90 days": "last_90_days", "90 days": "last_90_days", "quarter": "last_90_days", "since launch": "since_launch", "all time": "since_launch", "ever": "since_launch",
}


class PeriodError(ValueError):
    """The period asked for is not one the layer understands, or is out of bounds."""


@dataclass(frozen=True, slots=True)
class Period:
    start: datetime          # inclusive, tz-aware (shop zone)
    end: datetime            # exclusive, tz-aware (shop zone)
    label: str
    kind: str                # the named period, "days", or "range"

    @property
    def days(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 86400)

    @property
    def whole_days(self) -> int:
        """The number of calendar days the period spans, for a velocity: a period that ends now
        still counts today as a day. Counted by date, so a clock change is not a day."""
        days = (self.end.date() - self.start.date()).days
        if self.end.time() != self.end.min.time() or days == 0:
            days += 1
        return max(1, days)

    @property
    def to_date(self) -> bool:
        """A period still running (this week, this month, today): the figures are "so far"."""
        return self.kind in ("this_week", "this_month", "today")

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def previous(self) -> Period:
        """The period immediately before this one — the comparison. A period still running
        (this week on a Wednesday) is compared with the same stretch of the one before
        (last week to Wednesday at this time), never with the whole of it: "down 60% on
        last week" every midweek would be the calendar, not the shop."""
        span = self.end - self.start
        if self.kind == "this_week":
            start = self.start - timedelta(days=7)
            return Period(start, start + span, "last week to this point", "last_week_to_date")
        if self.kind == "last_week":
            return Period(self.start - timedelta(days=7), self.start, "the week before", "last_week")
        if self.kind == "this_month":
            first_of_previous = (self.start.replace(day=1) - timedelta(days=1)).replace(day=1)
            end = min(first_of_previous + span, self.start)
            return Period(first_of_previous, end, "last month to this point", "last_month_to_date")
        if self.kind == "last_month":
            first_of_previous = (self.start.replace(day=1) - timedelta(days=1)).replace(day=1)
            return Period(first_of_previous, self.start, "the month before", "last_month")
        if self.kind == "today":
            start = self.start - timedelta(days=1)
            return Period(start, start + span, "yesterday to this time", "yesterday_to_date")
        if self.kind in ("days", "yesterday", "since_launch"):
            # A period that ends now is a number of whole days; the one before is as many, ending at its start.
            return Period(self.start - timedelta(days=self.whole_days), self.start, f"the {self.whole_days} day{'s' if self.whole_days != 1 else ''} before", "days")
        return Period(self.start - span, self.start, "the period before", self.kind)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "start": self.start.isoformat(), "end": self.end.isoformat(),
            "days": round(self.days, 2), "timezone": str(self.start.tzinfo), "kind": self.kind,
        }

    def utc_bounds(self) -> tuple[str, str]:
        """ISO-8601 UTC bounds, the form Shopify's search takes."""
        from datetime import UTC

        return self.start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), self.end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def resolve(spec: Any, *, now: datetime | None = None, tz: str | ZoneInfo = "Europe/London") -> Period:
    """A period from what the model passed: a name ("this_week"), a number of days, or a
    dict — {"days": 7}, {"days": 7, "days_ago": 1}, {"start": "2026-09-01", "end": "2026-09-08"},
    {"name": "last_month"}. Bounded to a year."""
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    now = (now or datetime.now(zone)).astimezone(zone)
    if spec is None or spec == "":
        spec = "last_30_days"
    if isinstance(spec, dict):
        if spec.get("name") or spec.get("period"):
            return resolve(str(spec.get("name") or spec.get("period")), now=now, tz=zone)
        if spec.get("start") or spec.get("end"):
            return _range(spec, now, zone)
        if "days" in spec:
            return _days(spec.get("days"), spec.get("days_ago", 0), now, zone)
        raise PeriodError("A period is a name (this_week, last_month, last_7_days…), {\"days\": N} or {\"start\", \"end\"}.")
    if isinstance(spec, bool):
        raise PeriodError("A period is not true or false.")
    if isinstance(spec, (int, float)):
        return _days(spec, 0, now, zone)
    name = str(spec).strip().lower().replace("-", " ").replace("_", " ")
    key = ALIASES.get(name) or name.replace(" ", "_")
    if key == "today":
        return Period(_midnight(now), now, "today", "today")
    if key == "yesterday":
        return Period(_midnight(now) - timedelta(days=1), _midnight(now), "yesterday", "yesterday")
    if key == "this_week":
        return Period(_midnight(now) - timedelta(days=now.weekday()), now, "this week", "this_week")
    if key == "last_week":
        start = _midnight(now) - timedelta(days=now.weekday() + 7)
        return Period(start, start + timedelta(days=7), "last week", "last_week")
    if key == "this_month":
        return Period(_midnight(now).replace(day=1), now, "this month", "this_month")
    if key == "last_month":
        this_first = _midnight(now).replace(day=1)
        return Period((this_first - timedelta(days=1)).replace(day=1), this_first, "last month", "last_month")
    if key in ("last_7_days", "last_30_days", "last_90_days"):
        days = int(key.split("_")[1])
        return _days(days, 0, now, zone)
    if key == "since_launch":
        period = _days(MAX_DAYS, 0, now, zone)
        return Period(period.start, period.end, "the last year (the server keeps a year of orders)", "since_launch")
    if key.isdigit():
        return _days(int(key), 0, now, zone)
    raise PeriodError(f"Unknown period {spec!r}. Use one of {', '.join(NAMED)}, {{\"days\": N}} or {{\"start\", \"end\"}}.")


def _days(days: Any, days_ago: Any, now: datetime, zone: ZoneInfo) -> Period:
    try:
        n = int(days)
        ago = int(days_ago or 0)
    except (TypeError, ValueError) as exc:
        raise PeriodError("days and days_ago are whole numbers.") from exc
    if n < 1 or n > MAX_DAYS:
        raise PeriodError(f"days must be 1..{MAX_DAYS}.")
    if ago < 0 or ago > MAX_DAYS:
        raise PeriodError(f"days_ago must be 0..{MAX_DAYS}.")
    if ago == 0:
        # Ends now, starts n midnights back: "last 7 days" includes today so far and the six days before.
        start = _midnight(now) - timedelta(days=n - 1)
        return Period(start, now, "today" if n == 1 else f"last {n} days", "days")
    end = _midnight(now) - timedelta(days=ago - 1)
    start = end - timedelta(days=n)
    label = "yesterday" if n == 1 and ago == 1 else f"{n} days ending {ago} day{'s' if ago != 1 else ''} ago"
    return Period(start, end, label, "days")


def _range(spec: dict, now: datetime, zone: ZoneInfo) -> Period:
    try:
        start = datetime.fromisoformat(str(spec.get("start"))).replace(tzinfo=zone) if spec.get("start") else None
        end = datetime.fromisoformat(str(spec.get("end"))).replace(tzinfo=zone) if spec.get("end") else None
    except ValueError as exc:
        raise PeriodError("start and end are dates, YYYY-MM-DD.") from exc
    if end is None:
        end = now
    elif end.hour == 0 and end.minute == 0 and end.second == 0 and "T" not in str(spec.get("end")):
        end = end + timedelta(days=1)   # a date names its whole day
    if start is None:
        start = end - timedelta(days=DEFAULT_DAYS)
    if end <= start:
        raise PeriodError("end must be after start.")
    if (end - start) > timedelta(days=MAX_DAYS):
        raise PeriodError(f"A period covers at most {MAX_DAYS} days.")
    return Period(start, min(end, now), f"{start.date().isoformat()} to {min(end, now).date().isoformat()}", "range")
