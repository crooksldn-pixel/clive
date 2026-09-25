"""Midnight, four times over: every path whose answer turned on the wall clock crossing a day.

The acceptance run that crossed 23:00 UTC on 2026-09-24 — midnight in London, in summer —
failed three tests and recorded no names, and the same week an order's age rounded up near a
day boundary and a fixture sat part-way through a day. Each of those is right all day and wrong
for a minute or an hour either side of a midnight, and a suite only sees that if it happens to
be running then. So here the clock is held, at the four instants either side of both midnights
that matter — London's, which is 23:00 UTC in summer, and UTC's:

    22:59:30 UTC   the last half-minute of London's day in summer
    23:00:30 UTC   the first half-minute of London's next day, and still yesterday in UTC
    23:59:30 UTC   an hour into London's day, and the last half-minute of UTC's
    00:00:30 UTC   the new day in both

— on the night that failed, and on a winter night, when London and UTC share one midnight and
the last two instants are London's. Every path is driven at every instant, and what is asserted
is the right answer, not merely that one came back.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from app.analytics import periods
from app.analytics.cache import OrderCache
from app.objectives import store as objective_store
from app.session.models import Session
from app.support.investigate import SHOP_TZ, day_words, working_days_between
from app.tools import analytics_tools
from app.tools.dispatch import dispatch
from experience.fixtures import FixtureShopify, data


def _night(day: int, month: int) -> list[datetime]:
    first = datetime(2026, month, day, tzinfo=UTC)
    second = first + timedelta(days=1)
    return [
        first.replace(hour=22, minute=59, second=30),
        first.replace(hour=23, minute=0, second=30),
        first.replace(hour=23, minute=59, second=30),
        second.replace(hour=0, minute=0, second=30),
    ]


# The night the acceptance run failed (BST), and a night in January (GMT).
SUMMER = _night(24, 9)
WINTER = _night(14, 1)
INSTANTS = SUMMER + WINTER
IDS = [instant.strftime("%Y-%m-%dT%H:%M:%SZ") for instant in INSTANTS]


def held(instant: datetime) -> type[datetime]:
    """`datetime` with `now()` stopped at `instant`, for the module attribute a path reads its
    clock through — the way tests/test_analytics_tools.py:london_now holds the query tools'."""

    class Held(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.astimezone().replace(tzinfo=None)

    return Held


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


@pytest.fixture()
def world_at():
    """The golden world rebuilt at an instant — and rebuilt on the real clock afterwards, by an
    explicit `now`, so neither a world from 2026 nor a held clock outlives the test."""
    yield data.rebase
    data.rebase(datetime.now(UTC))


@pytest.fixture()
def query_at(monkeypatch, world_at):
    """The read a recipe makes through `commerce_query`, at an instant: the golden world built
    then, the fixture shop behind the production order cache, and the query tools' clock held
    there. Everything between the tool call and the rows is the production code."""

    async def ask(instant: datetime, spec: dict) -> dict:
        world_at(instant)
        store = FixtureShopify()
        analytics_tools.bind(OrderCache(lambda: store, clock=instant.timestamp))
        monkeypatch.setattr(analytics_tools, "datetime", held(instant))
        session = Session(session_id="midnight")
        session.turn_id = "turn_midnight"
        calls: list = []
        text = await dispatch("commerce_query", spec, session=session, timeout_s=5, calls=calls)
        assert calls and calls[-1].ok, text
        return calls[-1].result

    try:
        yield ask
    finally:
        analytics_tools.bind(None)


# --------------------------------------------------------------------------- the golden world


@pytest.mark.parametrize("instant", INSTANTS, ids=IDS)
def test_todays_orders_are_placed_today_apart_and_newest_first(instant, world_at):
    """The fixture's orders of today, at each instant: inside the shop's today, each at its own
    moment, and in the order the world says they came in.

    In the first minute of London's day the minute of headroom took everything there was, and
    all three were stamped at midnight exactly — so "the newest" was whichever the sort left
    first, and a listing came out right only because the fixture happened to hand them over in
    order.
    """
    now = world_at(instant)
    today = periods.resolve("today", now=now, tz=data.SHOP_TZ)
    expected = data.world.today()
    placed = [_instant(order.placed_at()) for order in expected]
    assert all(today.contains(p) for p in placed), (
        f"at {instant:%H:%M:%S} UTC, today is {today.start}..{today.end} and the orders are {placed}"
    )
    assert len(set(placed)) == len(placed), f"today's orders share an instant: {placed}"
    assert placed == sorted(placed, reverse=True), f"not newest first: {[o.name for o in expected]} {placed}"
    # The inbox's messages of today are folded into the part of the day that has happened.
    for thread in data.world.threads:
        for message in thread.messages:
            assert data._local(message.days_ago, message.hour) <= now, (message.message_id, now)


@pytest.mark.parametrize("instant", INSTANTS, ids=IDS)
async def test_the_list_of_todays_orders_is_the_worlds_today(instant, query_at):
    """"Show me today's orders": `order_list_period`'s own read, answered at each instant."""
    result = await query_at(instant, {
        "entity": "orders", "period": "today", "sort": [{"metric": "placed_at", "direction": "desc"}],
        "limit": 25, "title": "Orders",
    })
    shown = [row["order_number"] for row in result["rows"]]
    assert shown == [order.name for order in data.world.today()], f"at {instant:%H:%M:%S} UTC: {shown}"


@pytest.mark.parametrize("instant", INSTANTS, ids=IDS)
async def test_the_order_waiting_abroad_is_its_declared_age_at_every_instant(instant, query_at):
    """The international order's age, through `international_waiting_orders`' own read: the
    floor of the time elapsed, never rounded up across a day, from a fixture that is not on a
    day boundary. The answer's "waiting N days" is `int(age_days)` of the first row."""
    spec = data.INTERNATIONAL_ORDER
    result = await query_at(instant, {
        "entity": "orders", "period": "last_90_days",
        "filters": {"fulfillment": "unfulfilled", "international": True}, "sort": "oldest", "limit": 25,
    })
    rows = result["rows"]
    assert [row["order_number"] for row in rows] == [spec.name], rows
    assert int(rows[0]["age_days"]) == int(spec.days_ago), (
        f"at {instant:%H:%M:%S} UTC the order reads {rows[0]['age_days']} days old, not {spec.days_ago}"
    )


async def test_a_harness_started_after_midnight_serves_that_days_world(monkeypatch, world_at):
    """The run that crossed London's midnight: the world was built when the suite was collected,
    at 23:59:30, and a harness started at 00:00:30 served it to an application whose today had
    begun after every one of today's orders. The harness builds the world again when it starts.
    """
    from experience.harness import harness

    collected, started = SUMMER[0], SUMMER[1]
    world_at(collected)
    monkeypatch.setattr(data, "datetime", held(started))
    async with harness():
        assert data.NOW == started.astimezone(data.SHOP_TZ), data.NOW
        today = periods.resolve("today", now=started, tz=data.SHOP_TZ)
        placed = {order.name: _instant(order.placed_at()) for order in data.world.today()}
        assert placed and all(today.contains(p) for p in placed.values()), (today.start, placed)


# --------------------------------------------------------------------------- the product


@pytest.mark.parametrize("instant", INSTANTS, ids=IDS)
def test_a_deadline_tomorrow_is_one_day_away_at_every_instant(instant, tmp_path, monkeypatch):
    """The home screen's "days left" on an objective. Counted from the UTC date, a deadline
    tomorrow read two days away from London's midnight until one in the morning in summer."""
    monkeypatch.setattr(objective_store, "datetime", held(instant))
    tomorrow = instant.astimezone(objective_store.OWNER_TZ).date() + timedelta(days=1)
    made = objective_store.ObjectiveStore(tmp_path).create(
        title="Baptism travel", request="Get my son here for the baptism", deadline=tomorrow.isoformat(),
    )
    assert made.summary()["days_left"] == 1, f"at {instant:%H:%M:%S} UTC, deadline {tomorrow}"


@pytest.mark.parametrize("instant", INSTANTS, ids=IDS)
def test_a_support_finding_names_the_shops_day_at_every_instant(instant):
    """What the investigator tells the owner, and the draft tells the customer: the day a stamp
    fell on, and how many working days have passed since, are London's. Read in UTC, an order
    placed at half past midnight in summer was "placed on" the day before, and a parcel waiting
    since Thursday was still on Thursday for the first hour of Friday."""
    local = instant.astimezone(SHOP_TZ)
    assert day_words(instant.strftime("%Y-%m-%dT%H:%M:%SZ")) == local.strftime("%-d %b %Y")
    placed = datetime.combine(local.date() - timedelta(days=1), time(12), tzinfo=SHOP_TZ)
    assert local.weekday() < 5, "the premise: the day being counted is a working day"
    assert working_days_between(placed, instant) == 1, (
        f"at {instant:%H:%M:%S} UTC ({local:%a %H:%M} in London), placed {placed:%a %H:%M}"
    )
