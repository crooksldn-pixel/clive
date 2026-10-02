"""How many have sold of what a number counts, read from the shop's own orders (objectives by touch, C).

A number on an objective ("shift the last 200 hoodies by the 18th") holds only what the owner said:
what is counted, the target, the day counting starts (app/objectives/store.py `_number`). What has
sold is read here, each time the objective is drawn, from the order cache the sales figures already
use (app/analytics/cache.py, through app/tools/analytics_tools.py `cache`), so the count and the
answer to "how many hoodies have we sold?" cannot disagree: the same rows, the same matching of his
words to a product (every word of "grey hoodie" in its product, type, sku, variant, colour or size,
app/analytics/engine.py `_words_match`) and the same rule that a cancelled order is not a sale. A
unit is what is still on the order after returns and removals (the line's current quantity, which
the cache keeps; the quantity ordered only for a row read before it kept that). A day is the shop's
own day, in its time zone as Shopify gives it. Matching by words is broad ("Loopback Hoodie" is also
in "Loopback Zip Hoodie"), so the answer names what it counted: the products matched, the most sold
first, a few by name and how many more.

What comes back: the units sold on each day from the first day to today, the total, the pace, and
where the pace takes it:

  pace       the average a day over the last 14 whole days (yesterday back; fewer when counting
             started more recently). Today is not in it: a day still under way would drag the pace
             down every morning. With no whole day counted yet there is no pace, and that is said.
  lands      the day the total reaches the target at that pace: today plus the days the rest needs,
             rounded up. Already reached: the day it was crossed. No pace, or more than a year away
             at it: no day. Worked out in whole numbers (the units of the pace's days over their
             count), never a rounded average, so the day it lands and how many it reaches by the
             deadline cannot disagree by a hair of a float.
  deadline   with one: landing on or before it, how many days early; landing after it (or not at
             all), late, with how many it reaches by then and how many short, never a negative
             "days early". With no whole day counted yet nothing is projected, so nothing is called
             short; a deadline already gone says what it actually reached by then.

Nothing here writes, stages or changes anything, in the shop or in CLIVE's records: it is a read of
rows the cache already holds, and the cache reads Shopify again only when its own five minutes are
up. When the shop cannot be read, or the cache does not yet cover every day asked for, the answer
says so in words and carries no figure at all: a count of part of the days would be a smaller number
presented as the real one. Each answer, a count or why there is none, is kept for a minute (`TTL_S`)
per thing and first day, so the home's refresh and a sheet opening do not each walk the cache, and
while the shop cannot be reached a poll does not ask it again for every numbered objective: the
shop's time zone is asked once, by one call that every count waiting on it shares, and a failure to
read it is kept for the minute too.
"""

from __future__ import annotations

import asyncio
import logging
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

MATCHED_NAMED = 3         # products named in "what was counted"; the rest are "and N more"
UNREAD = "Shopify could not be read just now, so nothing is counted."

# What was counted, or why not, per (thing, first day, today): (when, the answer). Bounded, in this
# process only.
_kept: OrderedDict[tuple[str, str, str], tuple[float, dict[str, Any]]] = OrderedDict()
# The shop's time zone, per client: the zone once read, the one call in flight that every count
# shares, or when it last could not be read.
_zones: dict[int, dict[str, Any]] = {}


def forget() -> None:
    """Drop every kept count and zone (the tests, and nothing else, need a fresh read)."""
    _kept.clear()
    _zones.clear()


def _keep(key: tuple[str, str, str], answer: dict[str, Any]) -> dict[str, Any]:
    _kept[key] = (time.monotonic(), answer)
    _kept.move_to_end(key)
    while len(_kept) > KEPT:
        _kept.popitem(last=False)
    return answer


async def _zone(client: Any, timeout_s: float) -> Any:
    """The shop's time zone, asked of the shop once for all the counts that need it at the same
    moment, and not asked again for a minute after it could not be read (it raises then)."""
    held = _zones.setdefault(id(client), {"client": client})
    if held.get("client") is not client:              # an id reused by a new client: start again
        held.clear()
        held["client"] = client
    if "zone" in held:
        return held["zone"]
    failed = held.get("failed")
    if failed is not None and time.monotonic() - failed < TTL_S:
        raise RuntimeError("the shop could not be read a moment ago")
    loop = asyncio.get_running_loop()
    task = held.get("task")
    if task is None or task.get_loop() is not loop or (task.done() and (task.cancelled() or task.exception())):
        task = held["task"] = loop.create_task(client.timezone())
    try:
        zone = await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
    except Exception:
        held["failed"] = time.monotonic()
        if task.done():
            held.pop("task", None)
        raise
    held["zone"] = zone
    held.pop("task", None)
    held.pop("failed", None)
    return zone


def _units(item: dict[str, Any]) -> int:
    """What is still on the order of one line: after returns and removals where the cache has it."""
    current = item.get("current_quantity")
    if isinstance(current, int) and not isinstance(current, bool):
        return max(0, current)
    return max(0, int(item.get("quantity") or 0))


def _title(item: dict[str, Any], words: list[str]) -> str:
    """A matched line as the owner would name it: its product, and its colour or variant when one of
    his words is found only there ("grey hoodie" counts the Loopback Hoodie in Grey)."""
    product = " ".join(str(item.get("product") or "").split()) or "A product with no title"
    extra = " ".join(str(item.get("colour") or item.get("variant") or "").split())
    if extra and any(w not in product.casefold() and w in extra.casefold() for w in words):
        return f"{product} ({extra})"
    return product


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
    """The units of `of` sold on each day from `first` to `today`, from the cache, and what matched;
    or why not. Either is kept for a minute."""
    key = (of.casefold(), first.isoformat(), today.isoformat())
    kept = _kept.get(key)
    if kept is not None and time.monotonic() - kept[0] < TTL_S:
        return kept[1]
    period = Period(datetime.combine(first, day_start.min, tzinfo=zone), now, f"since {first.isoformat()}", "range")
    try:
        view = await _cache().view(period, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001 — an unread shop is said, never a figure
        log.info("objective number not counted: %s", type(exc).__name__)
        return _keep(key, {"why": UNREAD})
    if not view.complete:
        return _keep(key, {"why": view.note or "The shop's orders are still being read, so nothing is counted yet."})
    filters = {"product": of}
    words = [w for w in of.casefold().split() if w]
    per_day = [0] * ((today - first).days + 1)
    titles: dict[str, int] = {}
    for order in engine.select(view.rows, period, filters, now=now.timestamp()):
        when = datetime.fromtimestamp(float(order.get("ts") or 0), UTC).astimezone(zone).date()
        index = (when - first).days
        if not 0 <= index < len(per_day):
            continue
        for item in engine.matching_items(order, filters):
            units = _units(item)
            per_day[index] += units
            name = _title(item, words)
            titles[name] = titles.get(name, 0) + units
    named = sorted(titles, key=lambda t: (-titles[t], t.casefold()))
    synced = view.synced_at
    return _keep(key, {"per_day": per_day, "synced": synced, "matched": named[:MATCHED_NAMED],
                       "matched_more": max(0, len(named) - MATCHED_NAMED),
                       "counted_at": datetime.fromtimestamp(synced, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if synced else None})


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
        zone = await _zone(cache._client(), timeout_s)
    except Exception as exc:  # noqa: BLE001 — an unread shop is said, never a figure
        log.info("objective number not counted: %s", type(exc).__name__)
        return _unread(number, UNREAD)
    here = (now or datetime.now(zone)).astimezone(zone)
    today = here.date()
    if first > today:
        return _unread(number, f"Counting starts {_said(first, today)}.")
    days = await _days(of, first, today, zone, here, timeout_s)
    if "why" in days:
        return _unread(number, days["why"])
    # How long ago the cache read the shop, at this answer: a count kept for a minute still says its age.
    age = max(0, int(time.time() - days["synced"])) if days["synced"] else None
    return {"counted": True, "of": of, "target": target, "since": since, "unit": number.get("unit"),
            "today": today.isoformat(), "counted_at": days["counted_at"], "age_s": age,
            "matched": list(days["matched"]), "matched_more": days["matched_more"],
            **project(days["per_day"], target, first, today, deadline)}


def project(per_day: list[int], target: int, first: date, today: date, deadline: str | None) -> dict[str, Any]:
    """Where the pace takes the count: the total, the pace and the day the target is reached, and
    against the deadline, days early, or late with how many by then and how many short.

    The pace is `sold` units over `days` whole days, and everything it projects is worked out from
    those two whole numbers (web/objective-number.js does the same), so "lands after the deadline"
    and "short of the target by the deadline" are one fact, never two that a float can split."""
    total = sum(per_day)
    recent = per_day[:-1][-PACE_DAYS:]
    sold, days = sum(recent), len(recent)
    pace = sold / days if days else None
    out: dict[str, Any] = {"per_day": list(per_day), "total": total, "pace": round(pace, 2) if pace is not None else None,
                           "pace_days": days, "lands": None, "reached_on": None, "far": False,
                           "deadline": deadline, "days_early": None, "by_deadline": None, "short": None,
                           "at_deadline": None}
    lands: date | None = None
    if total >= target:
        running = 0
        for index, units in enumerate(per_day):
            running += units
            if running >= target:
                lands = first + timedelta(days=index)
                out["reached_on"] = lands.isoformat()
                break
    elif sold:
        ahead = -(-(target - total) * days // sold)          # whole days, rounded up
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
    if due < today:
        # What it actually reached by the end of that day, whatever the target: never a projection.
        upto = (due - first).days
        out["at_deadline"] = sum(per_day[: upto + 1]) if upto >= 0 else 0
    if lands is not None and lands <= due:
        out["days_early"] = (due - lands).days
        return out
    if out["reached_on"]:
        return out                         # reached, after its date: reached, not short
    if due < today:
        by = out["at_deadline"]
    elif pace is None:
        return out                         # no whole day counted yet: nothing to project from
    else:
        by = total + sold * (due - today).days // days
    if by >= target:
        return out                         # a deadline further than a year, which the pace still makes
    out["by_deadline"] = by
    out["short"] = target - by
    return out


def short(tally: dict[str, Any] | None) -> dict[str, Any]:
    """What the home row and the next six weeks need of a count: no days, only where it stands.
    Late is a target not reached that the pace, or the days already gone, leave short by the
    deadline; a target reached, even after its date, is reached."""
    if not tally:
        return {}
    if not tally.get("counted"):
        return {"counted": False, "why": tally.get("why")}
    late = bool(tally.get("short")) and tally["short"] > 0 and not tally.get("reached_on")
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
    if early is None or early < 0:
        return words
    if early == 0:
        return f"{words}, on the day"
    return f"{words}, {early} day{'' if early == 1 else 's'} early"
