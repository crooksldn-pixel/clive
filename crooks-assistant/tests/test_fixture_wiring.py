"""What the golden world is wired to, asserted rather than assumed.

`experience/harness.py` and `experience/browser.py` re-point the tool modules at the fixture
store and the fixture inbox by hand, because the modules hold their clients at module level
and `runtime.build()` gave them the real ones. That hand-wiring is code with no other test
over it: a binding that is wrong in a way no scenario happens to reach stays wrong, and the
first family to reach it pays for it.
"""

from __future__ import annotations

import pytest

from experience.harness import harness


@pytest.fixture()
async def stage():
    async with harness() as h:
        yield h


async def test_the_fixture_world_can_read_the_recipient_off_an_order(stage):
    """A new email to an order's customer, in the golden world, through the same lookup
    production uses.

    The harness bound the write module a `customer=` callable — and it bound the WRONG one:
    `gmail_tools`' email-to-bool sender check, which takes one argument, while
    `gmail_writes._order_customer` calls its lookup with two. So every `gmail_draft_new` and
    `gmail_send_new` carrying an order_id died in the fixture world with a TypeError about
    positional arguments, and no scenario noticed, because none of them reached that path.

    The fix was to bind no lookup at all: the module's own fallback reads the customer off
    the order through `shopify_tools.hydrator()`, which the harness has already pointed at
    the fixture store. This asserts the whole of that — the binding, the fallback and the
    fixture order — so a lookup that cannot be called fails here instead of in whichever
    scenario is written next.
    """
    from app.tools import gmail_writes
    from experience.fixtures import data

    who = await gmail_writes._order_customer(order_id=data.SCENARIO_ORDER.order_id)

    assert who["email"] == data.MIA.email.lower(), who
    assert who["name"] and who["label"] == "#1938", who


def test_the_waiting_order_reports_the_same_age_at_every_hour_of_the_day():
    """An age the system reports is the FLOOR of the elapsed time, so a fixture placed part-way
    through a day sits on a boundary and reports two different ages depending on when you run.

    `query_international_waiting` asserts the declared `days_ago` appears in the answer. The
    order was placed 14 days ago at 11:00, so it had been waiting 14 days after 11am and 13
    days before it: the scenario passed all day and failed every night between midnight and
    11am. It was found at 01:20 in the morning, by the suite, which is the only reason it was
    found at all.

    This walks the clock through a full day and asserts the age never moves. It fails for any
    hour but midnight if the fixture is put back on a boundary.
    """
    from datetime import timedelta

    from experience.fixtures import data

    spec = data.INTERNATIONAL_ORDER
    placed = data._local(spec.days_ago, spec.hour)
    declared = int(spec.days_ago)

    from app.analytics.engine import age_days_tenths

    for hour in range(24):
        for minute in (0, 30, 59):
            # "Now", walked across a whole day, from the same midnight the fixture was built from.
            now = data.NOW.replace(hour=hour, minute=minute, second=0, microsecond=0)
            elapsed = (now - placed) / timedelta(days=1)
            assert int(elapsed) == declared, (
                f"at {hour:02d}:{minute:02d} the order reads as {int(elapsed)} days old, not {declared} — "
                "the fixture is on a floor boundary and the scenario will fail for part of the day"
            )
            # And through the engine, which is what the sentence actually reads. Rounding to a
            # tenth used to lift 14 days 23 hours to 15.0, and int() of that is 15: the scenario
            # failed every night from 21:48 UTC for that reason, not the fixture's.
            reported = int(age_days_tenths(elapsed * 86400))
            assert reported == declared, (
                f"at {hour:02d}:{minute:02d} the engine reports {reported} days, not {declared}"
            )
