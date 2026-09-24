"""The international-waiting age, walked across the clock, through the real turn.

Root cause: `app/analytics/engine.py::_order_row` rounded an order's age to one decimal place
before `app/families/query_language.py` floored THAT rounded value with `int(...)` to say how
many days it had waited. For the last slice of every day — once the true elapsed time's
fraction reaches .95 — rounding to one decimal tips the figure over to the next whole number,
so the floor of the ROUNDED value is a day higher than the floor of the TRUE elapsed time.
`experience/fixtures/data.py:INTERNATIONAL_ORDER` sits at shop-local midnight (deliberately,
see the comment above it), so that slice falls in the hour or so before the next shop-local
midnight — 21:48-23:00 UTC in BST, which is exactly when GitHub (21:51 UTC) and the local
reproduction (22:16 UTC) saw the answer say "15" for an order fourteen days old.

The fix (`app/analytics/engine.py::_whole_days`) floors the unrounded difference directly.
This test drives the real turn `query_international_waiting` drives — the same POST /turn,
the same recipe, the same golden order — with the clock set to each instant the incident
touched, and checks the answer against the floor of the TRUE elapsed time, worked out
independently here rather than copied from the code under test.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.tools import analytics_tools
from experience.fixtures import data
from experience.harness import harness

INTERNATIONAL = "Find a real international order that has been waiting too long and hasn't been fulfilled"

# The order's own placed-at instant, built exactly the way `experience/fixtures/data.py` builds
# it (shop-local midnight, `days_ago` shop-local days before the fixture's own frozen "now").
_SPEC = data.INTERNATIONAL_ORDER
_PLACED = data._local(_SPEC.days_ago, _SPEC.hour)


def _install_clock(monkeypatch, now: datetime) -> None:
    """`app.tools.analytics_tools._now_and_zone` reads `datetime.now(zone)`. This makes that
    read `now`, whatever the wall clock actually says — the same technique
    `tests/test_analytics_tools.py:london_now` uses for a fixed instant."""

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(analytics_tools, "datetime", FixedDatetime)


@pytest.mark.parametrize("hour,minute", [(0, 30), (11, 0), (21, 45), (21, 55), (22, 16), (23, 30)])
async def test_the_international_waiting_age_is_right_at_every_tested_minute_of_the_day(monkeypatch, hour, minute):
    """The golden world's own "today" (`experience/fixtures/data.py:NOW`), at each UTC time of
    day the incident named, standing in for the moment the question was actually asked."""
    reference_date = data.NOW.date()
    now = datetime(reference_date.year, reference_date.month, reference_date.day, hour, minute, tzinfo=UTC)
    true_elapsed_days = (now - _PLACED).total_seconds() / 86400
    expected = int(true_elapsed_days)  # the floor, since it is never negative here
    _install_clock(monkeypatch, now)
    async with harness() as h:
        capture = await h.say(INTERNATIONAL, scenario="international_age_clock", session_id=f"clock-{hour:02d}{minute:02d}")
    assert str(expected) in capture.answer, (
        f"at {hour:02d}:{minute:02d} UTC (true elapsed {true_elapsed_days:.4f} days) "
        f"the answer should say {expected} day(s); got: {capture.answer!r}"
    )
