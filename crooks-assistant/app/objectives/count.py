"""How many have sold of what a number counts, read from the shop's own orders (objectives by touch, C).

A number on an objective ("shift the last 200 hoodies by the 18th") holds only what the owner said:
what is counted, the target, the day counting starts (app/objectives/store.py `_number`). What has
sold is read here, each time the objective is drawn, from the order cache the sales figures already
use (app/analytics/cache.py, through app/tools/analytics_tools.py `cache`), so the count and the
answer to "how many hoodies have we sold?" cannot disagree: the same rows, the same matching of his
words to a product (every word of "grey hoodie" in its product, type, sku, variant, colour or size,
app/analytics/engine.py `_words_match`), the same rule that a cancelled order is not a sale, and the
same unit, the quantity ordered. A day is the shop's own day, in its time zone as Shopify gives it.

What comes back: the units sold on each day from the first day to today, the total, the pace, and
where the pace takes it:

  pace       the average a day over the last 14 whole days (yesterday back; fewer when counting
             started more recently). Today is not in it: a day still under way would drag the pace
             down every morning. With no whole day counted yet there is no pace, and that is said.
  lands      the day the total reaches the target at that pace: today plus the days the rest needs,
             rounded up. Already reached: the day it was crossed. No pace, or more than a year away
             at it: no day.
  deadline   with one: how many days early or late that is, and, when it would be late, how many it
             reaches by then and how many short of the target that leaves (with no whole day counted
             yet, nothing is projected, so nothing is called short; a deadline already gone says what
             it actually reached by then).

Nothing here writes, stages or changes anything, in the shop or in CLIVE's records: it is a read of
rows the cache already holds, and the cache reads Shopify again only when its own five minutes are
up. When the shop cannot be read, or the cache does not yet cover every day asked for, the answer
says so in words and carries no figure at all: a count of part of the days would be a smaller number
presented as the real one. Each count is kept for a minute (`TTL_S`) per thing and first day, so the
home's refresh and a sheet opening do not each walk the cache.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_start
from typing import Any

from app.analytics import engine
from app.analytics.periods import Period

log = logging.getLogger("crooks.objectives")

PACE_DAYS = 14
TTL_S = 60.0
READ_TIMEOUT_S = 4.0
FAR_DAYS = 366            # a day further than this at the pace is not a day anyone can plan by
KEPT = 64
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# What was counted, per (thing, first day, today): (when, the days). Bounded, in this process only.
_kept: OrderedDict[tuple[str, str, str], tuple[float, dict[str, Any]]] = OrderedDict()


def forget() -> None:
    """Drop every kept count (the tests, and nothing else, need a fresh read)."""
    _kept.clear()


def _cache():
    """The order cache the sales tools read; refused in words where none is configured."""
    from app.tools import analytics_tools

    return analytics_tools.cache()


def _said(day: date, today: date) -> str:
    out = f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"
    return out if day.year == today.year else f"{out} {day.year}"


def _unread(number: dict[str, Any], why: str) -> dict[str, Any]:
    return {"counted": False, "why": why, "of": number.get("of"), "target": number.get("target"),
            "since": number.get("since"), "unit": number.get("unit")}


async def _days(of: str, first: date, today: date, zone: Any, now: datetime, timeout_s: float) -> dict[str, Any]:
    """The units of `of` sold on each day from `first` to `today`, from the cache, or why not."""
    key = (of.casefold(), first.isoformat(), today.isoformat())
    kept = _kept.get(key)
    if kept is not None and time.monotonic() - kept[0] < TTL_S:
        return kept[1]
    period = Period(datetime.combine(first, day_start.min, tzinfo=zone), now, f"since {first.isoformat()}", "range")
    view = await _cache().view(period, timeout_s=timeout_s)
    if not view.complete:
        return {"why": view.note or "The shop's orders are still being read, so nothing is counted yet."}
    filters = {"product": of}
    per_day = [0] * ((today - first).days + 1)
    for order in engine.select(view.rows, period, filters, now=now.timestamp()):
        when = datetime.fromtimestamp(float(order.get("ts") or 0), UTC).astimezone(zone).date()
        index = (when - first).days
        if 0 <= index < len(per_day):
            per_day[index] += sum(int(i.get("quantity") or 0) for i in engine.matching_items(order, filters))
    synced = view.synced_at
    days = {"per_day": per_day, "synced": synced,
            "counted_at": datetime.fromtimestamp(synced, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if synced else None}
    _kept[key] = (time.monotonic(), days)
    _kept.move_to_end(key)
    while len(_kept) > KEPT:
        _kept.popitem(last=False)
    return days


async def count(number: dict[str, Any] | None, *, deadline: str | None = None, now: datetime | None = None,
                timeout_s: float = READ_TIMEOUT_S) -> dict[str, Any] | None:
    """The count for one number, as the owner's screen draws it; None when there is no number."""
    if not number:
        return None
    of, since = str(number.get("of") or ""), str(number.get("since") or "")
    try:
        first = date.fromisoformat(since)
        target = int(number["target"])
    except (KeyError, TypeError, ValueError):
        return _unread(number, "The number has no start day or target it can be counted from.")
    try:
        cache = _cache()
        zone = await asyncio.wait_for(cache._client().timezone(), timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001 — an unread shop is said, never a figure
        log.info("objective number not counted: %s", type(exc).__name__)
        return _unread(number, "Shopify could not be read just now, so nothing is counted.")
    here = (now or datetime.now(zone)).astimezone(zone)
    today = here.date()
    if first > today:
        return _unread(number, f"Counting starts {_said(first, today)}.")
    try:
        days = await _days(of, first, today, zone, here, timeout_s)
    except Exception as exc:  # noqa: BLE001
        log.info("objective number not counted: %s", type(exc).__name__)
        return _unread(number, "Shopify could not be read just now, so nothing is counted.")
    if "why" in days:
        return _unread(number, days["why"])
    # How long ago the cache read the shop, at this answer: a count kept for a minute still says its age.
    age = max(0, int(time.time() - days["synced"])) if days["synced"] else None
    return {"counted": True, "of": of, "target": target, "since": since, "unit": number.get("unit"),
            "today": today.isoformat(), "counted_at": days["counted_at"], "age_s": age,
            **project(days["per_day"], target, first, today, deadline)}


def project(per_day: list[int], target: int, first: date, today: date, deadline: str | None) -> dict[str, Any]:
    """Where the pace takes the count: the total, the pace and the day the target is reached, and
    against the deadline, days early or late and, late, how many by then and how many short."""
    total = sum(per_day)
    whole = per_day[:-1][-PACE_DAYS:]
    pace = sum(whole) / len(whole) if whole else None
    out: dict[str, Any] = {"per_day": list(per_day), "total": total, "pace": round(pace, 2) if pace is not None else None,
                           "pace_days": len(whole), "lands": None, "reached_on": None, "far": False,
                           "deadline": deadline, "days_early": None, "by_deadline": None, "short": None}
    lands: date | None = None
    if total >= target:
        running = 0
        for index, sold in enumerate(per_day):
            running += sold
            if running >= target:
                lands = first + timedelta(days=index)
                out["reached_on"] = lands.isoformat()
                break
    elif pace:
        ahead = math.ceil((target - total) / pace)
        if ahead <= FAR_DAYS:
            lands = today + timedelta(days=ahead)
        else:
            out["far"] = True
    if lands is not None:
        out["lands"] = lands.isoformat()
    try:
        due = date.fromisoformat(str(deadline)) if deadline else None
    except ValueError:
        due = None
    if due is None:
        return out
    if lands is not None:
        out["days_early"] = (due - lands).days
    if lands is None or lands > due:
        if due < today:
            # Gone: what it actually reached by the end of that day, never a projection.
            upto = (due - first).days
            by = sum(per_day[: upto + 1]) if upto >= 0 else 0
        elif pace is None:
            return out                     # no whole day counted yet: nothing to project from
        else:
            by = math.floor(total + pace * (due - today).days)
        out["by_deadline"] = by
        out["short"] = max(0, target - by)
    return out


def short(tally: dict[str, Any] | None) -> dict[str, Any]:
    """What the home row and the next six weeks need of a count: no days, only where it stands.
    Late is a target not reached that the pace, or the days already gone, leave short by the
    deadline; a target reached, even after its date, is reached."""
    if not tally:
        return {}
    if not tally.get("counted"):
        return {"counted": False, "why": tally.get("why")}
    late = bool(tally.get("short")) and not tally.get("reached_on")
    return {"counted": True, "sold": tally["total"], "lands": tally.get("lands"), "reached_on": tally.get("reached_on"),
            "far": bool(tally.get("far")), "late": late, "days_early": tally.get("days_early"),
            "by_deadline": tally.get("by_deadline"), "short": tally.get("short")}


def pace_words(tally: dict[str, Any] | None) -> str:
    """Where the pace takes it, in the screen's own words ("At this pace: 200 by Wed 14 Oct, 4 days
    early"; web/objective-number.js says the same from the same figures). Only from the count, and
    nothing when there is no count to say it from."""
    if not tally or not tally.get("counted"):
        return ""
    today = date.fromisoformat(tally["today"])
    target = f"{tally['target']:,}"
    if tally.get("reached_on"):
        return f"{target} reached on {_said(date.fromisoformat(tally['reached_on']), today)}"
    if tally.get("short"):
        due = date.fromisoformat(tally["deadline"])
        if due < today:
            return f"Was due {_said(due, today)}: {tally['by_deadline']:,} by then, {tally['short']:,} short"
        return f"At this pace: {tally['by_deadline']:,} by {_said(due, today)}, {tally['short']:,} short"
    if not tally.get("lands"):
        if tally.get("far"):
            return f"At this pace, more than a year to {target}"
        if tally.get("pace") is None:
            return "No whole day counted yet, so no pace to go by"
        return f"Nothing sold in the last {tally['pace_days']} days, so no pace to go by"
    words = f"At this pace: {target} by {_said(date.fromisoformat(tally['lands']), today)}"
    early = tally.get("days_early")
    if early is None:
        return words
    if early == 0:
        return f"{words}, on the day"
    return f"{words}, {early} day{'' if early == 1 else 's'} early"
