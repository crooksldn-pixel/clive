"""When he says it happened, as a window of days: "last week", "Tuesday", "the 28th".

A date said in conversation is soft. "Last week" on a Friday usually means the calendar week
before, and sometimes means "about a week ago"; "Tuesday" means the latest Tuesday. So every
phrase is two windows: the CORE, which is what the words mean, and the NEAR, which is what a
person who said them might also have meant. An order inside the core fits; one inside the near
half fits; one outside does not, and is said not to. Nothing is read here and nothing is
guessed: a phrase this module does not know is said not to be known, never stretched to fit.

Days are the shop's days (app/analytics/periods.py keeps the same rule for the same reason): an
order placed at half past midnight in London is that day's order, whatever UTC says.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

SHOP_TZ = ZoneInfo("Europe/London")

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_SHORT_DAYS = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "weds": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december")
_SHORT_MONTHS = {m[:3]: i + 1 for i, m in enumerate(_MONTHS)} | {"sept": 9}
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "couple": 2, "few": 3}
# Words around a date that are not the date.
_FILLER = re.compile(r"\b(?:on|the|around|about|roughly|maybe|probably|sometime|some time|in|of|at|ish|"
                     r"morning|afternoon|evening|night|ordered|placed|bought)\b")


@dataclass(frozen=True)
class When:
    said: str
    start: date          # the core window, inclusive
    end: date
    near_start: date     # what the words might also mean, inclusive
    near_end: date
    label: str           # the window as words: "last week (Mon 21 – Sun 27 Sep)"

    def fit(self, day: date | None) -> float:
        """1.0 inside what the words mean, 0.5 inside what they might mean, 0 otherwise."""
        if day is None:
            return 0.0
        if self.start <= day <= self.end:
            return 1.0
        if self.near_start <= day <= self.near_end:
            return 0.5
        return 0.0

    def bounds(self) -> tuple[date, date]:
        """The widest window, for a search: nothing that could fit is left out of it."""
        return self.near_start, self.near_end


def shop_day(stamp: Any, tz: ZoneInfo = SHOP_TZ) -> date | None:
    """Shopify's UTC stamp as the shop's calendar day."""
    if isinstance(stamp, datetime):
        moment = stamp
    else:
        try:
            moment = datetime.fromisoformat(str(stamp or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    return moment.astimezone(tz).date()


def day_words(day: date | None, today: date | None = None) -> str:
    """"Tue 22 Sep", with the year when it is not this one."""
    if day is None:
        return ""
    words = f"{day.strftime('%a')} {day.day} {day.strftime('%b')}"
    if today is not None and day.year != today.year:
        words += f" {day.year}"
    return words


def _span(start: date, end: date, today: date) -> str:
    if start == end:
        return day_words(start, today)
    return f"{day_words(start, today)} – {day_words(end, today)}"


def _window(said: str, start: date, end: date, near_start: date, near_end: date, today: date, label: str) -> When:
    end, near_end = min(end, today), min(near_end, today)
    return When(said=said, start=start, end=end, near_start=min(near_start, start), near_end=max(near_end, end),
                label=f"{label} ({_span(start, end, today)})" if label else _span(start, end, today))


def parse(said: Any, today: date) -> When | None:
    """The window a phrase names, relative to `today` (the shop's today); None when the phrase
    is not one this module knows."""
    raw = " ".join(str(said or "").split())
    text = raw.lower().replace(",", " ")
    if not text:
        return None
    text = " ".join(_FILLER.sub(" ", text).split())
    for parser in (_relative, _weekday, _numbered_ago, _calendar, _explicit_date):
        found = parser(raw, text, today)
        if found is not None:
            return found
    return None


def _relative(raw: str, text: str, today: date) -> When | None:
    monday = today - timedelta(days=today.weekday())
    first = today.replace(day=1)
    last_month_end = first - timedelta(days=1)
    table = {
        "today": (today, today, today - timedelta(days=1), today, "today"),
        "yesterday": (today - timedelta(days=1), today - timedelta(days=1), today - timedelta(days=2), today, "yesterday"),
        "day before yesterday": (today - timedelta(days=2), today - timedelta(days=2), today - timedelta(days=3), today - timedelta(days=1), "the day before yesterday"),
        "this week": (monday, today, monday - timedelta(days=2), today, "this week"),
        "last week": (monday - timedelta(days=7), monday - timedelta(days=1), today - timedelta(days=14), today, "last week"),
        "a week ago": (today - timedelta(days=9), today - timedelta(days=5), today - timedelta(days=14), today - timedelta(days=3), "about a week ago"),
        "week ago": (today - timedelta(days=9), today - timedelta(days=5), today - timedelta(days=14), today - timedelta(days=3), "about a week ago"),
        "this month": (first, today, first - timedelta(days=5), today, "this month"),
        "last month": (last_month_end.replace(day=1), last_month_end, last_month_end.replace(day=1) - timedelta(days=5), first + timedelta(days=5), "last month"),
        "other day": (today - timedelta(days=6), today - timedelta(days=1), today - timedelta(days=10), today, "the other day"),
        "recently": (today - timedelta(days=14), today, today - timedelta(days=30), today, "recently"),
        "lately": (today - timedelta(days=14), today, today - timedelta(days=30), today, "recently"),
        "just now": (today, today, today - timedelta(days=1), today, "today"),
        "last weekend": (monday - timedelta(days=2), monday - timedelta(days=1), monday - timedelta(days=4), monday, "last weekend"),
        "this weekend": (monday + timedelta(days=5), monday + timedelta(days=6), monday + timedelta(days=4), monday + timedelta(days=7), "this weekend"),
        "weekend": (monday - timedelta(days=2) if today.weekday() < 5 else monday + timedelta(days=5),
                    monday - timedelta(days=1) if today.weekday() < 5 else monday + timedelta(days=6),
                    monday - timedelta(days=4), today, "the weekend"),
    }
    entry = table.get(text)
    if entry is None:
        return None
    start, end, near_start, near_end, label = entry
    return _window(raw, start, end, near_start, near_end, today, label)


def _weekday(raw: str, text: str, today: date) -> When | None:
    words = text.split()
    if not words:
        return None
    qualifier = words[0] if words[0] in ("last", "this", "past") and len(words) > 1 else ""
    name = words[-1] if qualifier else (words[0] if len(words) == 1 else "")
    target = _WEEKDAYS.index(name) if name in _WEEKDAYS else _SHORT_DAYS.get(name)
    if target is None or (qualifier and len(words) != 2):
        return None
    offset = (today.weekday() - target) % 7
    if qualifier in ("last", "past") and offset == 0:
        offset = 7
    day = today - timedelta(days=offset)
    if qualifier in ("last", "past"):
        # "Last Tuesday" said on a Thursday is two days ago to most people and nine to some.
        return _window(raw, day, day, day - timedelta(days=8), day + timedelta(days=1), today, "")
    if offset == 0:
        # "Friday" said on a Friday is today, or the Friday before.
        return _window(raw, day, day, day - timedelta(days=8), day, today, "")
    return _window(raw, day, day, day - timedelta(days=1), day + timedelta(days=1), today, "")


def _numbered_ago(raw: str, text: str, today: date) -> When | None:
    found = re.fullmatch(r"(?:a\s+)?(\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple|few)"
                         r"(?:\s+of)?\s+(day|days|week|weeks|month|months)\s+(?:ago|back|before)", text)
    if found is None:
        return None
    count_word, unit = found.group(1), found.group(2)
    count = int(count_word) if count_word.isdigit() else _NUMBERS.get(count_word, 0)
    if count <= 0:
        return None
    vague = count_word in ("couple", "few")
    if unit.startswith("day"):
        centre, spread, near = count, (1 if vague else 0), (2 if count > 4 or vague else 1)
    elif unit.startswith("week"):
        centre, spread, near = 7 * count, (5 if vague else 2), 6
    else:
        centre, spread, near = 30 * count, 10, 20
    start, end = today - timedelta(days=centre + spread), today - timedelta(days=max(0, centre - spread))
    return _window(raw, start, end, start - timedelta(days=near), end + timedelta(days=near), today, "")


def _calendar(raw: str, text: str, today: date) -> When | None:
    """A month on its own: "in September", "September"."""
    month = _month(text)
    if month is None or len(text.split()) != 1:
        return None
    year = today.year if month <= today.month else today.year - 1
    start = date(year, month, 1)
    end = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
    return _window(raw, start, end, start - timedelta(days=3), end + timedelta(days=3), today, "")


def _month(word: str) -> int | None:
    word = word.strip().lower().rstrip(".")
    if word in _MONTHS:
        return _MONTHS.index(word) + 1
    return _SHORT_MONTHS.get(word)


def _explicit_date(raw: str, text: str, today: date) -> When | None:
    """"28th", "28 September", "September 28", "28 Sept", "28/9", "28/09/2026", "2026-09-28"."""
    day: date | None = None
    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    slash = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?", text)
    words = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?(?:\s+([a-z]+))?", text) or re.fullmatch(r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?", text)
    try:
        if iso:
            day = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        elif slash:
            year = int(slash.group(3)) if slash.group(3) else None
            if year is not None and year < 100:
                year += 2000
            day = _latest(int(slash.group(1)), int(slash.group(2)), year, today)
        elif words:
            first, second = words.group(1), words.group(2)
            if first.isdigit():
                number, month = int(first), (_month(second) if second else None)
                if second and month is None:
                    return None
            else:
                number, month = int(second), _month(first)
                if month is None:
                    return None
            day = _latest(number, month, None, today)
    except ValueError:
        return None
    if day is None or day > today:
        return None
    return _window(raw, day, day, day - timedelta(days=1), day + timedelta(days=1), today, "")


def _latest(number: int, month: int | None, year: int | None, today: date) -> date | None:
    """The latest date on or before today with this day of the month (and month, and year)."""
    if month is None:
        candidate = today.replace(day=1)
        for _ in range(3):
            try:
                found = candidate.replace(day=number)
            except ValueError:
                found = None
            if found is not None and found <= today:
                return found
            candidate = (candidate - timedelta(days=1)).replace(day=1)
        return None
    if year is not None:
        return date(year, month, number)
    found = date(today.year, month, number)
    return found if found <= today else date(today.year - 1, month, number)
