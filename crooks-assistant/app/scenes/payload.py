"""The render payload: a validated scene with every value in it resolved and worded for display.

`scene_payload(scene, evidence, now=...)` takes the Scene app/scenes/validate.py accepted and
the evidence it was checked against, and returns plain JSON for web/scenes.js to draw: money
with its currency symbol, ratios as a percentage or a multiple as the field's descriptor says,
counts, durations in plain words, times in Europe/London in plain relative words, and series
as numeric arrays. The screen formats nothing; it places text.

Pure and deterministic: no I/O and no clock. Time words are relative to `now`, or to the
latest read when none is given, so the same scene and evidence always give the same payload.
Only what the validated scene bound is shown, so a personal value is here only when the scene
kept it: the evidence is read for what was checked — its label, its summary, how many rows it
found and when — never for a row's values. Every element keeps an id and its justification
for the trace; the justification is not display text and the renderer never draws it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.scenes.evidence import QUANTITIES, Evidence, Kind, Money, Series
from app.scenes.scene import SLOT, Bound, Scene, Shown

LONDON = ZoneInfo("Europe/London")

# What is said for a value evidence did not have.
UNKNOWN = "unknown"

# The symbol a currency is written with; any other is written after the amount by its code.
SYMBOLS = {"GBP": "£", "EUR": "€", "USD": "$", "AUD": "A$", "CAD": "CA$", "NZD": "NZ$", "JPY": "¥"}
# Currencies counted in whole units.
_WHOLE = frozenset({"JPY", "KRW"})

# The plan's closed vocabulary of periods, in words. "as_observed" is said from the read itself.
PERIODS = {
    "today": "today", "yesterday": "yesterday", "this_week": "this week", "last_week": "last week",
    "this_month": "this month", "last_month": "last month", "last_7_days": "last 7 days",
    "last_30_days": "last 30 days", "last_90_days": "last 90 days", "since_launch": "since launch",
}

# A Proposal names an action that already exists, by id alone; this is all it says, since any
# words describing the action were not checked by validation and could carry anyone's details.
PROPOSAL_FALLBACK = "An action is ready for you to review."

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_SECONDS = {
    "second": 1, "seconds": 1, "s": 1, "sec": 1, "secs": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600, "h": 3600, "hr": 3600, "hrs": 3600,
    "day": 86400, "days": 86400, "d": 86400,
    "week": 604800, "weeks": 604800,
}
_MULTIPLE = frozenset({"x", "×"})
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------------------ numbers


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and Decimal(str(value)).is_finite()


def format_number(value: Any, places: int = 1) -> str:
    """A number with thousands separators, rounded half up to at most `places` decimals, with
    no trailing zeros: 1234 → "1,234", 2.50 → "2.5"."""
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    digits = f"{abs(rounded):,.{places}f}"
    if "." in digits:
        digits = digits.rstrip("0").rstrip(".")
    return ("-" if rounded < 0 and digits != "0" else "") + digits


def format_money(money: Money) -> str:
    """An amount with its currency symbol, to the penny: "£3,100.00", "-€12.50", "1,200.00 CHF"."""
    whole = money.currency in _WHOLE
    amount = money.amount.quantize(Decimal(1) if whole else Decimal("0.01"), rounding=ROUND_HALF_UP)
    digits = f"{abs(amount):,.{0 if whole else 2}f}"
    sign = "-" if amount < 0 else ""
    symbol = SYMBOLS.get(money.currency)
    return f"{sign}{symbol}{digits}" if symbol else f"{sign}{digits} {money.currency}"


def _ratio_parts(value: Any, unit: str | None) -> tuple[str, str | None]:
    if unit == "%":
        return f"{format_number(value)}%", None
    if unit in _MULTIPLE:
        return f"{format_number(value)}×", None
    if unit:
        return format_number(value, 2), unit
    # A ratio with no unit is a fraction, said as a percentage.
    return f"{format_number(Decimal(str(value)) * 100)}%", None


def format_ratio(value: Any, unit: str | None = None) -> str:
    """A ratio as its descriptor says: unit "%" is a percentage as given (35 → "35%"), "x" a
    multiple (2.5 → "2.5×"), no unit a fraction said as a percentage (0.125 → "12.5%"), and any
    other unit a number with it ("1.42 units/day")."""
    return _join(*_ratio_parts(value, unit))


def _plural(count: int, word: str) -> tuple[str, str]:
    return f"{count:,}", word if count == 1 else f"{word}s"


def _duration_parts(value: Any, unit: str | None) -> tuple[str, str | None]:
    scale = _SECONDS.get((unit or "seconds").lower())
    if scale is None:
        return format_number(value), unit
    seconds = abs(float(value)) * scale
    if seconds < 60:
        return "under a minute", None
    minutes = round(seconds / 60)
    if minutes < 60:
        return _plural(minutes, "minute")
    hours = round(seconds / 3600)
    if hours < 36 and hours % 24:
        return _plural(hours, "hour")
    days = round(seconds / 86400)
    if days < 90:
        return _plural(days, "day")
    months = round(seconds / (86400 * 30.44))
    if months < 24:
        return _plural(months, "month")
    return _plural(round(seconds / (86400 * 365.25)), "year")


def format_duration(value: Any, unit: str | None = None) -> str:
    """A length of time in plain words, in the largest unit that says it whole: 0.5 days →
    "12 hours", 3 → "3 days", 400 days → "13 months"; under a minute is said so."""
    return _join(*_duration_parts(value, unit))


def _join(main: str, unit: str | None) -> str:
    return f"{main} {unit}" if unit else main


# -------------------------------------------------------------------------- times


def _clock(local: datetime) -> str:
    hour = local.hour % 12 or 12
    half = "am" if local.hour < 12 else "pm"
    return f"{hour}{half}" if local.minute == 0 else f"{hour}:{local.minute:02d}{half}"


def _day(day: date, today: date | None) -> str:
    if today is not None:
        days = (day - today).days
        if days == 0:
            return "today"
        if days == -1:
            return "yesterday"
        if days == 1:
            return "tomorrow"
        if -6 <= days <= -2:
            return _WEEKDAYS[day.weekday()]
    written = f"{day.day} {_MONTHS[day.month - 1]}"
    return written if today is not None and day.year == today.year else f"{written} {day.year}"


def format_when(value: datetime | date, now: datetime | None = None) -> str:
    """A moment in Europe/London in plain relative words: "just now", "45 minutes ago",
    "3 hours ago", "today at 9:15am", "yesterday at 4:30pm", "Monday at 11am", "3 September".
    A datetime is always an instant, said after it is turned to London time, midnight UTC
    included; only a `date` (a day's bucket) is said as its day. Without `now` it is said as
    its date."""
    today = now.astimezone(LONDON).date() if now is not None else None
    if not isinstance(value, datetime):
        return _day(value, today)
    value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    local = value.astimezone(LONDON)
    if now is not None:
        seconds = (now - value).total_seconds()
        if 0 <= seconds < 60:
            return "just now"
        if -60 < seconds < 0:
            return "in a moment"
        minutes = round(abs(seconds) / 60)
        if minutes < 60:
            count, word = _plural(minutes, "minute")
            return f"{count} {word} ago" if seconds > 0 else f"in {count} {word}"
        hours = round(seconds / 3600)
        if 0 < hours < 6:
            count, word = _plural(hours, "hour")
            return f"{count} {word} ago"
    return f"{_day(local.date(), today)} at {_clock(local)}"


def _moment(text: str) -> datetime | date | None:
    """A series point's label as a time: a `date` when it is exactly an ISO date (a day's
    bucket), a datetime when it is an ISO datetime."""
    if not _ISO_DAY.match(text):
        return None
    try:
        if _DATE_ONLY.match(text):
            return date.fromisoformat(text)
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# ------------------------------------------------------------------------ payload


def scene_payload(
    scene: Scene, evidence: Iterable[Evidence] | Mapping[str, Evidence] = (), *, now: datetime | None = None,
) -> dict[str, Any]:
    """The scene as the renderer draws it: an Answer, its elements in order, and — when the
    scene has one — the drill-down to what was checked. `now` is the moment time words are
    relative to (the latest read's when not given)."""
    return _Payload(_pool(evidence), now).scene(scene)


def _pool(evidence: Iterable[Evidence] | Mapping[str, Evidence]) -> dict[str, Evidence]:
    pool: dict[str, Evidence] = {}
    for ev in (evidence.values() if isinstance(evidence, Mapping) else evidence):
        if not isinstance(ev, Evidence):
            raise TypeError("Evidence is given as Evidence objects.")
        pool.setdefault(ev.handle, ev)
    return pool


class _Payload:
    def __init__(self, pool: dict[str, Evidence], now: datetime | None) -> None:
        self.pool = pool
        self.now = now if now is not None else max((ev.observed_at for ev in pool.values()), default=None)

    def scene(self, scene: Scene) -> dict[str, Any]:
        answer = {"id": "answer", "type": "answer", "text": self.prose(scene.answer),
                  "justification": scene.answer.element.justification.strip()}
        drilldown = None
        if scene.drilldown is not None:
            drilldown = {"id": "drilldown", "sources": [
                self.source(s.handle, s.query, s.observed_at, s.records) for s in scene.drilldown.sources
            ]}
        return {
            "answer": answer,
            "elements": [self.element(f"e{n + 1}", shown) for n, shown in enumerate(scene.elements)],
            "drilldown": drilldown,
        }

    # ------------------------------------------------------------------ values

    def parts(self, b: Bound) -> tuple[str, str | None]:
        """A bound value for display: its main text, and a unit said after it where it has one."""
        value = b.value
        if value is None:
            return UNKNOWN, None
        if isinstance(value, Money):
            return format_money(value), None
        if isinstance(value, Series):
            return (self.point(value, value.points[-1].value) if value.points else UNKNOWN), None
        if isinstance(value, datetime):
            return format_when(value, self.now), None
        if _is_number(value):
            if b.kind is Kind.RATIO:
                return _ratio_parts(value, b.unit)
            if b.kind is Kind.DURATION:
                return _duration_parts(value, b.unit)
            return format_number(value, 0 if b.kind is Kind.COUNT else 2), b.unit
        if b.kind is Kind.STATUS:
            words = " ".join(str(value).replace("_", " ").split())
            words = words.lower() if words.isupper() else words
            return words[:1].upper() + words[1:], None
        return str(value), None

    def text(self, b: Bound) -> str:
        return _join(*self.parts(b))

    def value(self, b: Bound) -> dict[str, Any]:
        return {"evidence": b.evidence, "record": b.record, "field": b.field, "kind": str(b.kind),
                "label": b.label, "text": self.text(b), "pii": bool(b.pii)}

    def point(self, series: Series, value: float) -> str:
        if series.currency:
            return format_money(Money(Decimal(str(value)), series.currency))
        if series.unit:
            return f"{format_number(value)} {series.unit}"
        return format_number(value)

    def at(self, label: str) -> str:
        moment = _moment(label)
        return format_when(moment, self.now) if moment is not None else label

    def prose(self, shown: Shown) -> str:
        """The element's prose with each slot filled by its value as the screen says it."""
        return SLOT.sub(lambda m: self.text(shown.values[int(m.group(1))]), getattr(shown.element, "text", ""))

    def source(self, handle: str, summary: str, observed_at: datetime, records: int) -> dict[str, Any]:
        """What one read was, for a drill-down: never its rows."""
        ev = self.pool.get(handle)
        label = (ev.label if ev is not None else "") or summary or "A read"
        return {
            "evidence": handle, "label": label, "summary": summary, "found": records,
            "found_text": f"{records:,} found" if records else "nothing found",
            "checked": format_when(observed_at, self.now), "checked_at": observed_at.isoformat(),
        }

    def evidence_source(self, handle: str) -> dict[str, Any] | None:
        ev = self.pool.get(handle)
        return None if ev is None else self.source(ev.handle, ev.query, ev.observed_at, len(ev.records))

    def caption(self, handle: str) -> str:
        ev = self.pool.get(handle)
        return ev.label if ev is not None else ""

    # ---------------------------------------------------------------- elements

    def element(self, ident: str, shown: Shown) -> dict[str, Any]:
        el = shown.element
        out: dict[str, Any] = {"id": ident, "type": el.type, "justification": el.justification.strip()}
        out.update(getattr(self, f"_{el.type}")(shown))
        return out

    def _finding(self, shown: Shown) -> dict[str, Any]:
        handles = list(dict.fromkeys([*shown.element.evidence, *(b.evidence for b in shown.values)]))
        sources = [s for s in (self.evidence_source(h) for h in handles) if s is not None]
        return {"significance": shown.element.significance, "text": self.prose(shown),
                "values": [self.value(b) for b in shown.values], "sources": sources}

    def _entity(self, shown: Shown) -> dict[str, Any]:
        row = shown.rows[0] if shown.rows else ()
        return {"caption": self.caption(shown.element.evidence), "record": shown.element.record,
                "fields": [self.value(b) for b in row]}

    def _collection(self, shown: Shown) -> dict[str, Any]:
        el = shown.element
        ev = self.pool.get(el.evidence)
        first = shown.rows[0] if shown.rows else ()
        labels = {b.field: b.label for b in first}
        kinds = {b.field: b.kind for b in first}
        for name in el.columns:
            d = ev.descriptor(name) if ev is not None else None
            if d is not None:
                labels.setdefault(name, d.label)
                kinds.setdefault(name, d.kind)
        columns = [{"field": name, "label": labels.get(name, name), "numeric": kinds.get(name) in QUANTITIES}
                   for name in el.columns]
        rows = [{"record": row[0].record if row else None, "cells": [self.text(b) for b in row]} for row in shown.rows]
        total = max(len(ev.records) if ev is not None else 0, len(rows))
        return {"caption": self.caption(el.evidence), "evidence": el.evidence, "columns": columns, "rows": rows,
                "limit": el.limit, "total": total}

    def _measure(self, shown: Shown) -> dict[str, Any]:
        b = shown.values[0]
        main, unit = self.parts(b)
        period = PERIODS.get(shown.element.period)
        if period is None:
            ev = self.pool.get(b.evidence)
            period = f"checked {format_when(ev.observed_at, self.now)}" if ev is not None else ""
        return {"label": b.label, "value": main, "unit": unit, "period": period, "pii": bool(b.pii)}

    def _comparison(self, shown: Shown) -> dict[str, Any]:
        current, previous = shown.values
        direction, difference = self.difference(current, previous)
        return {"label": current.label, "current": self.value(current), "previous": self.value(previous),
                "direction": direction, "difference": difference}

    def difference(self, current: Bound, previous: Bound) -> tuple[str, str]:
        """Which way the current value moved from the previous, and by how much, in words."""
        a, b = current.value, previous.value
        if isinstance(a, Money) and isinstance(b, Money):
            delta, base = a.amount - b.amount, b.amount
            size = format_money(Money(abs(delta), a.currency))
        elif _is_number(a) and _is_number(b):
            delta, base = Decimal(str(a)) - Decimal(str(b)), Decimal(str(b))
            size = self.change(current, abs(delta))
        else:
            return "unknown", ""
        if not delta:
            return "same", "No change"
        words = f"{'Up' if delta > 0 else 'Down'} {size}"
        if current.kind in (Kind.MONEY, Kind.COUNT) and base:
            words += f" ({format_number(abs(delta) / abs(base) * 100, 0)}%)"
        return ("up" if delta > 0 else "down"), words

    def change(self, b: Bound, delta: Decimal) -> str:
        if b.kind is Kind.RATIO:
            if b.unit in _MULTIPLE:
                return f"{format_number(delta)}×"
            if b.unit and b.unit != "%":
                return f"{format_number(delta, 2)} {b.unit}"
            points = format_number(delta if b.unit == "%" else delta * 100)
            return f"{points} {'point' if points == '1' else 'points'}"
        if b.kind is Kind.DURATION:
            return format_duration(delta, b.unit)
        return _join(format_number(delta, 0 if b.kind is Kind.COUNT else 2), b.unit)

    def _trend(self, shown: Shown) -> dict[str, Any]:
        b = shown.values[0]
        series: Series = b.value
        points = series.points
        return {
            "label": b.label, "values": [float(p.value) for p in points],
            "latest": self.point(series, points[-1].value) if points else UNKNOWN,
            "from": self.at(points[0].at) if points else "", "to": self.at(points[-1].at) if points else "",
        }

    def _timeline(self, shown: Shown) -> dict[str, Any]:
        rows = [{"record": at.record, "at": self.text(at),
                 "at_iso": at.value.isoformat() if isinstance(at.value, datetime) else None, "label": self.text(label)}
                for at, label in shown.rows]
        return {"caption": self.caption(shown.element.evidence), "rows": rows}

    def _proposal(self, shown: Shown) -> dict[str, Any]:
        return {"action": shown.element.action, "text": PROPOSAL_FALLBACK}

    def _question(self, shown: Shown) -> dict[str, Any]:
        return {"text": shown.element.text, "options": list(shown.element.options)}
