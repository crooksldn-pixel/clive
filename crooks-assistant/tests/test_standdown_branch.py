"""Which half's guesses stand down when the owner asks something (round 10, the residual the turn
fixer found in app/reads/scheduler.py run_plan and app/anticipation/engine.py owner_read).

Both read `session.acting_branch`: one field for both halves of a split workspace, holding
whichever half spoke last. With both halves thinking at once — the left asked, the right asked
straight after — the left's own read stood down the RIGHT half's speculative reads and left its
own running, which is the wrong half twice. Now both ask `acting_branch(session)`
(app/tools/context.py): the running call's own half (CURRENT_BRANCH, set per call) first, the
session's field only when nothing running says.
"""

from __future__ import annotations

import asyncio

import pytest

from app.anticipation import engine as engine_mod
from app.anticipation.models import P2
from app.memory.prefetch import Prefetcher
from app.reads import budget
from app.reads.scheduler import Read, ReadPlan, run_plan
from app.session.models import Session
from app.tools.context import CURRENT_BRANCH

LEFT, RIGHT = "b_left", "b_right"


def _held_open() -> asyncio.Future:
    return asyncio.get_running_loop().create_future()


@pytest.fixture()
async def split():
    """A conversation split in two, each half with a speculative read in flight, and the right
    half the last to have spoken (so the session's own field names it)."""
    session = Session(session_id="split", login="owner@example.com")
    session.acting_branch = RIGHT
    prefetcher = Prefetcher()
    anticipator = engine_mod.Anticipator(prefetcher=prefetcher)
    engine_mod.install(anticipator)
    scope = engine_mod.scope_of(session)
    futures = {}
    for half in (LEFT, RIGHT):
        futures[half] = _held_open()

        async def guess(future=futures[half]):
            return await future

        assert prefetcher.start(f"{scope}|{half}", guess, scope=scope, lane=P2, branch_id=half)
    tasks = {half: prefetcher._tasks[f"{scope}|{half}"] for half in (LEFT, RIGHT)}
    try:
        yield session, anticipator, tasks
    finally:
        engine_mod.install(None)
        for future in futures.values():
            if not future.done():
                future.cancel()
        await asyncio.sleep(0)


async def _settle():
    for _ in range(3):
        await asyncio.sleep(0)


async def test_the_owners_read_stands_down_the_half_that_is_speaking_not_the_last_to_speak(split):
    """The left half asks (its call runs with CURRENT_BRANCH = left), while the session's own field
    still says right. The left's guess stops; the right's goes on."""
    session, anticipator, tasks = split
    token = CURRENT_BRANCH.set(LEFT)
    try:
        assert anticipator.owner_read(session) == 1
    finally:
        CURRENT_BRANCH.reset(token)
    await _settle()
    assert tasks[LEFT].cancelled(), "the half that asked stood its own guess down"
    assert not tasks[RIGHT].done(), "the other half's guess is left alone"


async def test_a_read_plan_in_the_owners_lane_stands_down_the_half_it_runs_for(split):
    """The same through the read layer: run_plan in the owner's foreground lane asks budget.yield_to
    to stand down the lanes below it, for the half its call runs for."""
    session, _anticipator, tasks = split
    asked: list[str] = []
    listener = budget.on_yield(lambda ask: asked.append(ask.branch_id) or 0)
    token = CURRENT_BRANCH.set(LEFT)
    try:
        await run_plan(ReadPlan(reads=[], label="left asks", lane=budget.FOREGROUND, lane_explicit=True), session=session)
    finally:
        CURRENT_BRANCH.reset(token)
        budget.off_yield(listener)
    await _settle()
    assert asked and set(asked) == {LEFT}, asked
    assert tasks[LEFT].cancelled() and not tasks[RIGHT].done()


async def test_with_nothing_running_for_a_half_the_session_says_which(split):
    """Outside a model call (CURRENT_BRANCH empty) the half the request said it was speaking to
    decides, as before."""
    session, anticipator, tasks = split
    assert anticipator.owner_read(session) == 1
    await _settle()
    assert tasks[RIGHT].cancelled() and not tasks[LEFT].done()


def test_the_read_layer_and_the_anticipation_layer_ask_the_one_accessor():
    """Neither reads the session's field for itself any more."""
    import inspect

    from app.reads import scheduler

    for module in (scheduler, engine_mod):
        source = inspect.getsource(module)
        assert 'getattr(session, "acting_branch"' not in source, module.__name__
        assert "acting_branch(session)" in source, module.__name__
    assert Read  # the plan's own type, imported as the scheduler exports it
