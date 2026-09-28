"""Read budgets with strict priority (§11) — D-4.

    turn_6089e7517986  commerce_aggregate  REFUSED: this turn has been reading for too long
    00:25:48           open.area           ok=False  code=landing_unavailable

One budget was shared by speculation, hydration and the owner's own foreground request, and
it was scoped to a long-lived turn — so reads nobody asked for could refuse the thing the
owner did ask for, and a turn that had been reading could refuse a tap that came after it.

The order the budgets enforce:

    1  active owner foreground read
    2  owner navigation hydration
    3  mutation precondition / verification
    4  active branch requested background job
    5  anticipation / speculation

Background and speculative work yields immediately, and lanes 4 and 5 can never spend what
lanes 1 to 3 need.
"""

from __future__ import annotations

import asyncio

import pytest

from app.reads import budget
from app.reads.scheduler import Read, ReadPlan, run_plan
from experience.harness import harness


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        yield h


@pytest.fixture(autouse=True)
def _fresh_throttle():
    budget.throttle().reset()
    yield
    budget.throttle().reset()


# ------------------------------------------------------------------ the shape of the thing


def test_the_lanes_are_the_five_the_brief_names_in_its_order():
    assert budget.LANES == (
        budget.FOREGROUND, budget.NAVIGATION, budget.PRECONDITION,
        budget.BACKGROUND, budget.SPECULATION,
    )
    assert [budget.PRIORITY[lane] for lane in budget.LANES] == [1, 2, 3, 4, 5]
    assert budget.outranks(budget.FOREGROUND, budget.SPECULATION)
    assert budget.outranks(budget.NAVIGATION, budget.BACKGROUND)
    assert not budget.outranks(budget.SPECULATION, budget.PRECONDITION)


def test_each_lane_spends_its_own_budget_and_no_other():
    ledger = budget.Ledger()
    for _ in range(budget.BUDGETS[budget.SPECULATION].calls + 3):
        ledger.record(budget.SPECULATION, "guess", cost=2)
    assert ledger.check(budget.SPECULATION, "guess", cost=1), "the speculative lane never ran out"
    assert not ledger.check(budget.FOREGROUND, "turn_1", cost=4), (
        "speculation spent the owner's budget — this is D-4"
    )
    assert not ledger.check(budget.NAVIGATION, "tap_1", cost=4)
    assert not ledger.check(budget.PRECONDITION, "prop_1", cost=4)


def test_a_long_lived_key_never_contaminates_the_next_one():
    """A turn that read a great deal must not refuse the tap that comes after it."""
    ledger = budget.Ledger()
    while not ledger.check(budget.FOREGROUND, "turn_orders", cost=6):
        ledger.record(budget.FOREGROUND, "turn_orders", cost=6)
    assert ledger.check(budget.FOREGROUND, "turn_orders", cost=6)
    assert not ledger.check(budget.FOREGROUND, "turn_sales", cost=6), "the next turn inherited the last one's spend"
    assert not ledger.check(budget.NAVIGATION, "tap_sales", cost=6), "a tap inherited a turn's spend"


def test_the_owners_read_is_never_refused_a_slot():
    """Fill a source with speculation and then ask for it in each of the owner's three lanes.

    The guarantee is stated as "never refused" rather than "a slot is reserved", because that
    is what the code does and it is the stronger of the two: his reads are what the source is
    for, and the pacing of them is the scheduler's per-plan semaphore.
    """
    throttle = budget.Throttle()
    held = []
    while throttle.admit("shopify", budget.SPECULATION):
        held.append(throttle.take("shopify", budget.SPECULATION))
    assert len(held) == budget.SOURCE_SLOTS["shopify"], "the source's global limit did not bind"
    assert not throttle.admit("shopify", budget.SPECULATION)
    assert not throttle.admit("shopify", budget.BACKGROUND), "a background job took a full source"
    for lane in (budget.FOREGROUND, budget.NAVIGATION, budget.PRECONDITION):
        assert throttle.admit("shopify", lane), f"{lane} was locked out by speculation"
    for one in held:
        throttle.give_back(one)
    assert throttle.in_flight("shopify") == 0


def test_starting_owner_work_stands_the_lower_lanes_down():
    stood_down: list[budget.Standdown] = []
    token = budget.on_yield(lambda ask: stood_down.append(ask) or 1)
    try:
        assert budget.yield_to(budget.FOREGROUND, scope="owner|s1", branch_id="br_1") == 2
        assert [ask.lane for ask in stood_down] == [budget.BACKGROUND, budget.SPECULATION]
        assert {ask.scope for ask in stood_down} == {"owner|s1"}
        assert {ask.branch_id for ask in stood_down} == {"br_1"}, "a stand-down lost which half asked"
        stood_down.clear()
        # Speculation asking to run stands nothing down: there is nothing below it.
        assert budget.yield_to(budget.SPECULATION, scope="owner|s1") == 0
        assert stood_down == []
    finally:
        budget.off_yield(token)


# ------------------------------------------------------------------ the session's own reads


async def _speculate(stage, times: int, session_id: str = "s1") -> None:
    """Run the anticipation layer's own read shape until its bound stops it, under the authority
    that layer holds when it runs: a service authority derived from the owner's for its reads
    alone (app/memory/prefetch.py; round 8, F-NEW-TOOLS), not the owner's own."""
    from app.memory.prefetch import current as prefetcher
    from app.tools import authority

    owner = authority.current()
    service = owner.derive("prefetch:test", 30, tools=prefetcher().readable_tools()) if owner is not None else None
    session = stage.runtime.sessions.get_or_create(session_id)
    with authority.acting_as(service):
        for n in range(times):
            plan = ReadPlan(
                [Read("guess", "commerce_query", {
                    "entity": "orders", "period": "today", "limit": 10, "title": f"guess {n}",
                }, source="shopify", cost=120.0)],
                label="anticipate:test", origin="predicted", why="a hunch",
            )
            await run_plan(plan, session=session, turn_id=getattr(session, "turn_id", ""))


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_speculation_at_its_cap_does_not_refuse_the_owners_dock_command(stage):
    """The D-4 regression, in the order the live session hit it."""
    await stage.say("show me today's orders")
    await _speculate(stage, 12)
    tap = await stage.touch("open.area", area="orders")
    assert tap.status == 200
    assert tap.raw.get("ok") is True, f"the dock landing was refused: {tap.raw.get('code')} {tap.raw.get('detail')}"
    assert tap.surfaces, "the landing came back with nothing on it"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_read_heavy_turn_does_not_refuse_the_tap_that_follows_it(stage):
    """Opening Sales after exploring orders must get Sales."""
    from app.tools.dispatch import dispatch

    session = stage.runtime.sessions.get_or_create("s1")
    await stage.say("show me today's orders")
    refusals = 0
    for days in range(1, 14):
        rendered = await dispatch(
            "commerce_query",
            {"entity": "orders", "period": {"days": days}, "limit": 10},
            session=session, timeout_s=8.0,
        )
        refusals += rendered.startswith("REFUSED")
    assert refusals, "the turn budget never ran out, so this test proves nothing"

    tap = await stage.touch("open.area", area="sales")
    assert tap.raw.get("ok") is True, f"Sales was refused after exploring orders: {tap.raw.get('code')}"
    assert tap.surfaces, "Sales drew nothing"
    assert tap.raw.get("changed", {}).get("area") == "sales"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_speculation_never_spends_the_owners_turn_budget(stage):
    from app.tools.dispatch import dispatch

    session = stage.runtime.sessions.get_or_create("s1")
    await stage.say("show me today's orders")
    before = budget.ledger_for(session).spent(budget.FOREGROUND, session.turn_id)
    await _speculate(stage, 12)
    after = budget.ledger_for(session).spent(budget.FOREGROUND, session.turn_id)
    assert after == before, "speculation was charged to the owner's turn"
    rendered = await dispatch(
        "commerce_query", {"entity": "orders", "period": "yesterday", "limit": 10},
        session=session, timeout_s=8.0,
    )
    assert not rendered.startswith("REFUSED"), f"the owner's own read was refused: {rendered[:120]}"


async def test_a_budget_refusal_is_not_reported_as_a_missing_landing(stage, monkeypatch):
    """`landing_unavailable` means "that could not be drawn"; a spent budget is not that.

    At 00:25:48 the owner was told a screen that exists could not be drawn, when the truth
    was that the one budget there was had been spent two questions earlier. He cannot act on
    the first sentence and can act on the second.

    The navigation lane is narrowed to nothing so the tap's own fresh budget is spent on its
    first read — which is the only way to reach this branch now that a tap starts fresh.
    """
    monkeypatch.setitem(budget.BUDGETS, budget.NAVIGATION, budget.Budget(calls=0, cost=0, elapsed_s=0.0))
    tap = await stage.touch("open.area", area="orders")
    assert tap.raw.get("ok") is False, "the budget was not actually spent, so this proves nothing"
    assert tap.raw.get("code") == "read_budget_spent", (
        f"a budget refusal came back as {tap.raw.get('code')!r}: {tap.raw.get('detail')}"
    )
    assert "could not be drawn" not in str(tap.raw.get("detail") or "")


async def test_a_landing_that_really_cannot_be_drawn_still_says_so(stage, monkeypatch):
    """The other half of the same distinction: a recipe that defers for its own reasons is
    still `landing_unavailable`, and narrowing the code to budgets only must not swallow it."""
    import dataclasses

    from app.recipes import RECIPES, RecipeAnswer

    monkeypatch.setitem(RECIPES, "landing_orders", dataclasses.replace(
        RECIPES["landing_orders"],
        render=lambda ctx, result: RecipeAnswer(answer="", defer="the order reads did not answer"),
    ))
    tap = await stage.touch("open.area", area="orders")
    assert tap.raw.get("ok") is False
    assert tap.raw.get("code") == "landing_unavailable", tap.raw


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_owner_asking_stands_the_speculative_lane_down(stage):
    """`run_plan` already did this for speculation; now it does it for background work too,
    and it is the budget layer that decides which lanes are below the one asking."""
    session = stage.runtime.sessions.get_or_create("s1")
    stood: list[str] = []
    token = budget.on_yield(lambda ask: stood.append(ask.lane) or 0)
    try:
        await run_plan(
            ReadPlan([Read("mine", "commerce_query", {"entity": "orders", "period": "today", "limit": 5},
                           source="shopify", cost=120.0)], label="owner"),
            session=session, turn_id=session.turn_id,
        )
    finally:
        budget.off_yield(token)
    assert budget.BACKGROUND in stood and budget.SPECULATION in stood


def test_a_writes_precondition_and_proof_read_in_lane_three():
    """The lane is not decoration: a change's `observe` — called before the mutation to check
    the entity has not moved, and after it to prove what happened — runs in it.

    Wrapped at registration (app/tools/registry.py), because the action engine calls these
    callables directly and a lane that each write tool's author had to remember to enter is a
    lane one of them will forget.
    """
    import app.tools.shopify_writes  # noqa: F401
    from app.tools import registry

    seen: list[tuple[str, str]] = []
    spec = registry.get("shopify_order_note_append")
    assert spec.write is not None

    async def look() -> str:
        seen.append(budget.current_lane())
        return "observed"

    # The registration wrapper is what is under test, so it is applied to a fresh callable
    # rather than reaching into the one the shop's tool registered.
    wrapped = registry._proving_in_lane_three(
        type(spec.write)(**{**{f: getattr(spec.write, f) for f in spec.write.__slots__}, "observe": look}),
        "test_tool",
    )
    asyncio.run(wrapped.observe())
    assert seen and seen[0][0] == budget.PRECONDITION
    assert seen[0][1].startswith("test_tool:observe#"), "each proof needs its own unit of work"
    assert budget.must_be_fresh(budget.PRECONDITION), "a proof could be served from what is held"
    # And the lane is given back: a proof must not leave the next read in lane three.
    assert budget.ambient_lane() == ("", "")


async def test_each_proof_gets_its_own_budget():
    """Two changes in one conversation must not share a precondition budget: the bound is on
    one proof, not on how many changes the owner has made."""
    import app.tools.shopify_writes  # noqa: F401
    from app.tools import registry

    keys: list[str] = []

    async def look() -> str:
        keys.append(budget.current_lane()[1])
        return "observed"

    spec = registry.get("shopify_order_note_append")
    wrapped = registry._proving_in_lane_three(
        type(spec.write)(**{**{f: getattr(spec.write, f) for f in spec.write.__slots__}, "observe": look}),
        "test_tool",
    )
    await wrapped.observe()
    await wrapped.observe()
    assert len(set(keys)) == 2, f"two proofs shared one budget: {keys}"


async def test_reads_stay_reads_whatever_lane_they_are_in():
    """The non-negotiable, restated where the lanes are chosen: no lane can name a write."""
    import app.tools.shopify_writes  # noqa: F401
    from app.reads.scheduler import WriteInPlan, assert_reads_only

    for lane in budget.LANES:
        plan = ReadPlan([Read("x", "shopify_order_note_append", {})], lane=lane)
        with pytest.raises(WriteInPlan):
            assert_reads_only(plan)


def test_the_non_negotiables_hold_at_the_lane_boundary():
    """Four rules that must not be weakened by anything in this pass, asserted where the new
    code could have weakened them."""
    import app.tools.batch_tools  # noqa: F401
    import app.tools.shopify_writes  # noqa: F401

    # Reads never mutate, and speculation may never write or commit: a prediction's tool is
    # checked against the registry and the plan is refused before it runs.
    from app.anticipation.engine import Anticipator
    from app.reads import dedupe
    from app.tools.gate import Disposition, classify

    layer = Anticipator()
    for tool in ("shopify_order_note_append", "batch_order_tags_add", "shopify_order_cancel"):
        assert not layer._readable(tool), f"{tool} could be predicted"
    assert not layer._readable("shopify_do_whatever"), "an unregistered tool was readable"

    # Nothing in the dedupe layer can hold, join or reuse a change.
    for tool in ("shopify_order_note_append", "batch_order_tags_add"):
        assert tool not in dedupe.PURE_READS
    # Unknown writes fail closed, in any lane.
    for lane in budget.LANES:
        with budget.using(lane, "x"):
            assert classify("shopify_do_whatever", {}, ()).disposition is Disposition.DENY
            assert classify("shopify_delete_everything", {}, ()).disposition is Disposition.DENY


async def test_a_speculative_plan_is_in_the_speculative_lane():
    assert ReadPlan([], origin="predicted").lane == budget.SPECULATION
    assert ReadPlan([], origin="requested").lane == budget.FOREGROUND
    assert ReadPlan([], lane=budget.NAVIGATION).lane == budget.NAVIGATION


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_two_lanes_run_at_once_without_one_starving_the_other(stage):
    """The whole point: speculation in flight must not delay the owner's read behind it."""
    session = stage.runtime.sessions.get_or_create("s1")
    slow = asyncio.gather(*(_speculate(stage, 3) for _ in range(3)))
    result = await run_plan(
        ReadPlan([Read("mine", "commerce_query", {"entity": "orders", "period": "today", "limit": 5},
                       source="shopify", cost=120.0)], label="owner"),
        session=session, turn_id="turn_owner",
    )
    await slow
    assert result.ok("mine"), f"the owner's read did not come back: {result.errors} {result.skipped}"
