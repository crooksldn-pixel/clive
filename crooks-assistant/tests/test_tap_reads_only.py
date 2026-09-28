"""A tap's recipe reaches reads, and only reads, through the same dispatcher and the same
authority as every tool (the 2026-09-28 deploy review, round 9, E-01).

`POST /command` runs a recipe for a tap that names a place or a form's read
(app/routes/command.py `_run_recipe` → app/recipes.py `run`). The reviewer could not see the
runner and so could not say whether a tap could reach a live write. These drive the real
/command route, the real recipe runner, the real read scheduler and the real dispatcher, with
a recipe made to misbehave in each way it could: a plan naming a write it never declared, a
declaration that names a write, a bulk change. Each is refused before anything is dispatched;
the reads a real landing makes are dispatched as reads, under the owner authority the door
gave the tap's request.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app import recipes
from app.reads.scheduler import Read, ReadPlan, WriteInPlan, run_plan
from app.session.models import Session
from app.tools import authority
from tests.test_turn_boundary import A, shop, tap  # noqa: F401 — `shop` is the fixture

WRITES_AND_BULK = ("shopify_order_cancel", "shopify_refund_create", "shopify_store_credit_add",
                   "shopify_order_note_append", "batch_order_tags_add")


@pytest.fixture()
def dispatched(monkeypatch):
    """Every tool the dispatcher is asked for during the test, with the authority it ran under."""
    from app.tools import dispatch as dispatch_module

    seen: list[tuple[str, str | None]] = []
    real = dispatch_module.dispatch

    async def spy(name, args, **kwargs):
        held = authority.current()
        seen.append((name, held.kind if held is not None and held.active else None))
        return await real(name, args, **kwargs)

    monkeypatch.setattr(dispatch_module, "dispatch", spy)
    return seen


def _misbehaving(tool: str, *, declared: bool) -> recipes.Recipe:
    """The Orders landing, made to plan a change instead of its reads."""
    honest = recipes.RECIPES["landing_orders"]

    def plan(ctx):
        return ReadPlan([Read("change", tool, {"order_id": A, "tags": ["x"]}, source="shopify")], label="victim")

    return replace(honest, plan=plan, read_primitives=(tool,) if declared else honest.read_primitives)


@pytest.mark.parametrize("tool", WRITES_AND_BULK)
@pytest.mark.parametrize("declared", [False, True], ids=["planned-not-declared", "declared"])
async def test_a_tap_whose_recipe_plans_a_change_is_refused_before_anything_is_dispatched(shop, dispatched, monkeypatch, tool, declared):  # noqa: F811
    monkeypatch.setitem(recipes.RECIPES, "landing_orders", _misbehaving(tool, declared=declared))
    body = await tap(shop, "open.area", "taps", area="orders")

    assert body["ok"] is False and body["code"] == "landing_unavailable", body
    assert tool not in [name for name, _ in dispatched], f"the tap dispatched {tool}"
    session = shop.runtime.sessions.get("taps")
    assert session.proposals == [] and session.batches == {}, "a tap staged a change"
    assert shop.store.mutations == []
    # And the refusal is one the owner can act on: the same tap, offered back.
    assert body["changed"]["retry"] == {"command": "open.area", "area": "orders"}


async def test_the_read_scheduler_refuses_a_change_in_any_plan_whoever_built_it():
    """The second wall, under the recipe's own: a plan with a write in it raises before its
    first read runs, whatever put it together."""
    for tool in WRITES_AND_BULK:
        with pytest.raises(WriteInPlan):
            await run_plan(ReadPlan([Read("change", tool, {"order_id": A}, source="shopify")]), session=Session(session_id="s"))


async def test_a_landing_reads_through_the_dispatcher_as_the_owner_and_reads_only(shop, dispatched):  # noqa: F811
    """The honest landings: every tool they reach is a registered read, run by the one
    dispatcher (so by the gate) under the owner authority the door gave this tap."""
    from app.tools import registry

    for area in ("orders", "email", "sales", "products"):
        await tap(shop, "open.area", f"land-{area}", area=area)
    assert dispatched, "the landings read nothing"
    for name, held in dispatched:
        spec = registry.get(name)
        assert spec.write is None and spec.batch is None, f"a landing reached {name}"
        assert held == authority.OWNER, f"{name} ran under {held!r}, not the tap's owner authority"


async def test_a_recipe_run_with_no_authority_reads_nothing(dispatched):
    """Outside a request the door let through there is no authority, and the dispatcher runs no
    tool for a recipe any more than for the model."""
    from app.families import load_all

    load_all()
    session = Session(session_id="nobody")
    answer = await recipes.run(recipes.RECIPES["landing_inbox"], recipes.Ctx(runtime=None, session=session, branch=session.branch()))
    assert dispatched and all(held is None for _, held in dispatched)
    assert session.proposals == []
    assert answer.deferred or not answer.calls or all(not c.ok for c in answer.calls)


async def test_a_test_that_asks_for_no_authority_holds_none_and_no_tool_runs_in_it():
    """F-A2-FIXTURE, as the round-9 reviewers asked to see it: this module grants nothing
    (tests/conftest.py `owner_asking` is not autouse), so a dispatch here — a read or a change
    — is refused before any handler, exactly as production refuses work nobody asked for."""
    from app.tools.dispatch import dispatch

    assert authority.current() is None
    session = Session(session_id="no-one")
    session.issue(A)
    for name, args in (("shopify_find_order", {"query": "1938"}), ("shopify_order_cancel", {"order_id": A})):
        calls: list = []
        said = await dispatch(name, args, session=session, timeout_s=2, calls=calls)
        assert said.startswith("REFUSED") and [c.error for c in calls] == ["no owner authority"], (name, said)
    assert session.proposals == []
