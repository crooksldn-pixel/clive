"""Abandoned checkouts (brief §14), asked out loud.

Phase 2's answer to "how many people abandoned their basket this week and what were they
trying to buy?" was "I don't have a tool for that". Two things have to be true now, and only
one of them is about having the tool:

* the question is answered from a read, with cards drawn from what the model read;
* the cards say WHICH abandonment it is. The golden world has a checkout that was left and
  then paid for, so "six abandoned" versus "seven begun" is a real distinction here and not
  a hypothetical one — and the cards carry the limitation the Admin API imposes, because a
  shop that acts on "twelve people abandoned their baskets" is acting on a number Shopify
  never gave it.

Every sentence is the model's (since 28 September 2026), so the harness's model makes the one
read Claude makes for these questions, and what is asserted is what the Mac drew from it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from experience.fixtures import data
from experience.harness import Harness
from experience.scenarios import Result, a_model_turn, a_surface, check, grounded

HOODIE_TITLE, HOODIE_VARIANT = "Convict Hoodie", "Black / M"      # gid://shopify/ProductVariant/9102


def _amount(value) -> float | None:
    found = re.search(r"£\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", str(value or ""))
    return float(found.group(1).replace(",", "")) if found else None


def _metrics(c) -> dict[str, str]:
    return {str(m.get("label")): str(m.get("value")) for m in (c.data("metric_group").get("metrics") or [])}


def _rows(c) -> list[dict]:
    return [r for r in (c.data("ranking").get("rows") or []) if isinstance(r, dict)]


def _window(days: float) -> list[dict]:
    """The golden world's abandoned checkouts inside a window, worked out here from the
    fixture rather than read off the answer, so the answer can disagree."""
    return [c for c in data.ABANDONED if not c["completed"] and c["days_ago"] <= days]


async def abandoned_checkouts(h: Harness) -> Result:
    """The whole question, spoken: how many, worth what, and what keeps being left behind."""
    r = Result("abandoned_checkouts", "What's been abandoned in the last fortnight?")
    session = "aban1"
    h.configure()
    c = await h.ask("how many abandoned checkouts", ("shopify_abandoned_checkouts", {"days": 14}),
                    scenario="abandoned_checkouts", session_id=session)
    r.captures.append(c)
    r.checks.append(a_model_turn(c))
    r.checks += a_surface(c, "metric_group", what="draws the figures")
    r.checks += a_surface(c, "ranking", what="draws what keeps being left behind")

    metrics = _metrics(c)
    r.checks.append(check("the figures are the three that answer the question",
                          set(metrics) == {"checkouts abandoned", "not taken", "average each"},
                          f"metrics={metrics}"))
    if grounded(h):
        window = _window(14)
        expected = round(sum(data.abandoned_total(x) for x in window), 2)
        r.checks.append(check("the count is the golden world's own, and excludes the one that was paid for",
                              metrics.get("checkouts abandoned") == str(len(window)),
                              f"said={metrics.get('checkouts abandoned')!r} expected={len(window)}"))
        r.checks.append(check("and the value is the arithmetic over the catalogue's prices",
                              _amount(metrics.get("not taken")) == expected,
                              f"said={metrics.get('not taken')!r} expected={expected}"))
        rows = _rows(c)
        # By name: a variant is not a record the tablet can open, so the row carries no
        # destination (app/presentation.py `_withhold_dead_refs`, §18).
        r.checks.append(check("the item that keeps appearing is the one that keeps appearing",
                              bool(rows) and rows[0].get("label") == HOODIE_TITLE and rows[0].get("sublabel") == HOODIE_VARIANT,
                              f"first={rows[0] if rows else None}"))
        r.checks.append(check("ranked by how many checkouts, with the units beside them",
                              bool(rows) and (rows[0].get("primary") or {}).get("label") == "checkouts"
                              and (rows[0].get("secondary") or {}).get("label") == "units",
                              f"first={rows[0] if rows else None}"))
        r.checks.append(check("and the ranking says it is not ranked by value",
                              "not by value" in str(c.data("ranking").get("note") or ""),
                              f"note={c.data('ranking').get('note')!r}"))

    # The thing this family exists for.
    r.checks.append(check("the card says it is checkouts, not baskets, and not orders waiting to go out",
                          "not baskets left on the site" in str(c.data("metric_group").get("note") or "")
                          and "not orders waiting to go out" in str(c.data("metric_group").get("note") or ""),
                          f"note={c.data('metric_group').get('note')!r}"))
    r.checks.append(check("nothing was changed by asking", getattr(h.store, "mutations_sent", -1) == 0,
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    return r


def _window_start(days: int) -> str:
    """The first instant of a `days` window as Shopify's search is given it: midnight that many
    days back in the shop's own zone, in UTC. Worked out here, apart from the application's
    own `_since`, so the request can disagree with it."""
    first = (datetime.now(ZoneInfo(data.SHOP_TIMEZONE)) - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return first.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


async def abandoned_window(h: Harness) -> Result:
    """A shorter window is a different answer, and the shop does the filtering."""
    r = Result("abandoned_window", "Abandoned this week")
    session = "aban2"
    h.configure()
    asked = len(getattr(h.store, "queries", []))
    starts = {_window_start(7)}
    c = await h.ask("what's been abandoned this week", ("shopify_abandoned_checkouts", {"days": 7}),
                    scenario="abandoned_window", session_id=session)
    starts.add(_window_start(7))     # either side of a midnight the ask ran across
    r.captures.append(c)
    r.checks.append(a_model_turn(c))
    r.checks += a_surface(c, "metric_group", what="draws the figures")
    r.checks.append(check("the card names the window it used",
                          "in the last week" in str(c.data("metric_group").get("subtitle") or ""),
                          f"subtitle={c.data('metric_group').get('subtitle')!r}"))
    if grounded(h):
        # The read went to Shopify with the seven-day date filter: the window is the shop's own
        # search, not a filter applied to everything after the fact. Read off the request the
        # fixture store recorded, not off an operation's name (the 2026-09-30 deploy review,
        # X2-02: any read mentioning "abandoned" used to be taken as the proof).
        sent = [variables for operation, variables in getattr(h.store, "queries", [])[asked:]
                if operation == "CrooksAbandonedCheckouts"]
        filters = [str((variables or {}).get("q") or "") for variables in sent]
        r.checks.append(check("the seven-day window reached Shopify as its date filter",
                              bool(filters) and all(any(f"created_at:>='{start}'" in q for start in starts) for q in filters),
                              f"filters={filters} expected from={sorted(starts)}"))
        # Exactly the golden world's week, count and value: a zero, or the fortnight's figure,
        # is a wrong answer and fails here (it used to pass anything at or below the fortnight).
        week = _window(7)
        expected = round(sum(data.abandoned_total(x) for x in week), 2)
        metrics = _metrics(c)
        r.checks.append(check("the count is the golden world's own for the week",
                              bool(week) and metrics.get("checkouts abandoned") == str(len(week)),
                              f"said={metrics.get('checkouts abandoned')!r} expected={len(week)}"))
        r.checks.append(check("and the value is the arithmetic over the week's checkouts",
                              _amount(metrics.get("not taken")) == expected,
                              f"said={metrics.get('not taken')!r} expected={expected}"))
    return r


SCENARIOS = (
    ("abandoned_checkouts", abandoned_checkouts),
    ("abandoned_window", abandoned_window),
)
