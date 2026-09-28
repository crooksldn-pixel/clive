"""Duplicate reads (§12) — D-13.

    turn_26db2bafe507   commerce_query ×2   gmail_search ×2
    turn_6089e7517986   gmail_search   ×2   shopify_order_detail ×2

Two presentation paths asking for the same entity must cause ONE network request. Keyed on
the tool, the canonical arguments, the entity, the scope and the freshness the caller needs —
so a card title, which changes nothing that is read, does not make a second request.

And the rule that outranks the saving: a precondition or verification read is ALWAYS fresh.
Nothing here may ever hand a mutation stale data.
"""

from __future__ import annotations

import asyncio

import pytest

from app.reads import budget, dedupe
from experience.harness import harness


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        dedupe.current().reset()
        yield h


@pytest.fixture()
def fresh():
    # The registry is what says whether a tool is a read, and it is populated by importing
    # the tool modules. A unit test that skipped this would be asserting against an empty
    # registry, which is exactly the state in which everything looks like a write.
    import app.tools.analytics_tools  # noqa: F401
    import app.tools.gmail_tools  # noqa: F401
    import app.tools.shopify_tools  # noqa: F401

    d = dedupe.install(dedupe.Dedupe())
    yield d
    dedupe.install(dedupe.Dedupe())


# ------------------------------------------------------------------ the key


def test_the_key_carries_tool_args_entity_scope_and_freshness():
    key = dedupe.key_for("shopify_order_detail", {"order_id": "gid://1"}, scope="owner")
    assert key.tool == "shopify_order_detail"
    assert key.entity == "gid://1"
    assert key.scope == "owner"
    assert key.freshness == dedupe.REUSABLE
    fresh_key = dedupe.key_for("shopify_order_detail", {"order_id": "gid://1"}, scope="owner", must_be_fresh=True)
    assert fresh_key.freshness == dedupe.FRESH and str(fresh_key) != str(key)


def test_two_presentation_paths_of_one_entity_are_one_key():
    """A card's title is presentation. It must not make a second request."""
    left = dedupe.key_for("commerce_query", {"entity": "orders", "period": "today", "limit": 25, "title": "Today"}, scope="o")
    right = dedupe.key_for("commerce_query", {"entity": "orders", "period": "today", "limit": 25, "title": "Orders"}, scope="o")
    assert str(left) == str(right)
    # And a different question is still a different key.
    other = dedupe.key_for("commerce_query", {"entity": "orders", "period": "yesterday", "limit": 25}, scope="o")
    assert str(other) != str(left)


def test_an_order_named_two_ways_is_one_key():
    assert str(dedupe.key_for("shopify_find_order", {"query": "#1938"}, scope="o")) == str(
        dedupe.key_for("shopify_find_order", {"query": " 1938 "}, scope="o")
    )


# ------------------------------------------------------------------ coalescing


async def test_one_flight_serves_both_callers(fresh):
    calls = 0

    async def read():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return {"order_id": "gid://1"}

    both = await asyncio.gather(*(
        fresh.read("shopify_order_detail", {"order_id": "gid://1"}, scope="o", lane=budget.FOREGROUND, factory=read)
        for _ in range(2)
    ))
    assert calls == 1, "two callers made two requests"
    assert both[0]["order_id"] == both[1]["order_id"] == "gid://1"
    assert fresh.stats()["requests_avoided"] == 1
    assert fresh.stats()["provider_calls_saved"] == 1


async def test_a_read_a_moment_later_is_served_from_what_was_just_read(fresh):
    calls = 0

    async def read():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {"threads": [{"thread_id": "t1"}]}

    for _ in range(3):
        await fresh.read("gmail_search", {"query": "newer_than:1d"}, scope="o", lane=budget.FOREGROUND, factory=read)
    assert calls == 1
    assert fresh.stats()["requests_avoided"] == 2
    assert fresh.stats()["latency_saved_ms"] > 0


async def test_a_failed_read_is_not_remembered(fresh):
    calls = 0

    async def read():
        nonlocal calls
        calls += 1
        raise RuntimeError("shopify said no")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await fresh.read("shopify_find_order", {"query": "1938"}, scope="o", lane=budget.FOREGROUND, factory=read)
    assert calls == 2, "a failure was cached"


async def test_a_reused_payload_cannot_be_edited_by_its_first_caller(fresh):
    async def read():
        return {"rows": [{"order_number": "1938"}]}

    first = await fresh.read("commerce_query", {"entity": "orders"}, scope="o", lane=budget.FOREGROUND, factory=read)
    first["rows"].append({"order_number": "9999"})
    second = await fresh.read("commerce_query", {"entity": "orders"}, scope="o", lane=budget.FOREGROUND, factory=read)
    assert len(second["rows"]) == 1, "the held copy was edited by the caller that read it"


# ------------------------------------------------------------------ freshness that must hold


async def test_a_precondition_read_is_never_served_from_the_recent_table(fresh):
    calls = 0

    async def read():
        nonlocal calls
        calls += 1
        return {"order_id": "gid://1", "tags": ["a"] * calls}

    await fresh.read("shopify_order_detail", {"order_id": "gid://1"}, scope="o", lane=budget.FOREGROUND, factory=read)
    again = await fresh.read("shopify_order_detail", {"order_id": "gid://1"}, scope="o", lane=budget.PRECONDITION, factory=read)
    assert calls == 2, "a precondition read was answered from what was already held"
    assert again["tags"] == ["a", "a"]


async def test_a_precondition_read_does_not_join_a_speculative_flight(fresh):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def read():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"order_id": "gid://1", "n": calls}

    guess = asyncio.create_task(fresh.read(
        "shopify_order_detail", {"order_id": "gid://1"}, scope="o", lane=budget.SPECULATION, factory=read))
    await started.wait()
    release.set()
    proof = await fresh.read(
        "shopify_order_detail", {"order_id": "gid://1"}, scope="o", lane=budget.PRECONDITION, factory=read)
    await guess
    assert calls == 2, "the proof of a change joined a guess"
    assert proof["n"] == 2


async def test_a_proven_change_drops_what_was_held_about_that_record(fresh):
    calls = 0

    async def read():
        nonlocal calls
        calls += 1
        return {"order_id": "gid://shopify/Order/1", "n": calls}

    await fresh.read("shopify_order_detail", {"order_id": "gid://shopify/Order/1"}, scope="o", lane=budget.FOREGROUND, factory=read)
    from app.memory import invalidate_for_write

    invalidate_for_write("order", "gid://shopify/Order/1")
    again = await fresh.read("shopify_order_detail", {"order_id": "gid://shopify/Order/1"}, scope="o", lane=budget.FOREGROUND, factory=read)
    assert calls == 2 and again["n"] == 2, "a changed order was served from before the change"


async def test_nothing_here_can_hold_a_write(fresh):
    import app.tools.shopify_writes  # noqa: F401

    with pytest.raises(dedupe.NotAReadError):
        await fresh.read("shopify_order_note_append", {"order_id": "x"}, scope="o",
                         lane=budget.FOREGROUND, factory=lambda: None)


# ------------------------------------------------------------------ through the real path


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_one_order_asked_for_twice_is_one_shopify_request(stage):
    """Through `dispatch`, which is the only path from the model or a recipe to a tool.

    The operation counted is the order lookup itself. `shopify_find_order` also starts the
    order's enrichment in the background (app/context/order.py::find_by_number), and counting
    every operation the fixture shop sees would be counting a race rather than the claim.
    """
    from app.tools.dispatch import dispatch

    session = stage.runtime.sessions.get_or_create("s1")
    session.turn_id = "turn_dedupe"
    dedupe.current().reset()
    stage.store.forget_scenario()

    both = await asyncio.gather(*(
        dispatch("shopify_find_order", {"query": "1938"}, session=session, timeout_s=8.0)
        for _ in range(2)
    ))
    lookups = [op for op, _ in stage.store.queries if op == "CrooksOrderByName"]
    assert len(lookups) == 1, f"two presentation paths made {len(lookups)} lookups"
    assert both[0] and both[1] and "1938" in both[0]
    assert dedupe.current().stats()["provider_calls_saved"] >= 1


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_turn_that_read_twice_now_reads_once(stage):
    """turn_6089e7517986's shape: a search, then the same search from another path."""
    from app.tools.dispatch import dispatch

    session = stage.runtime.sessions.get_or_create("s1")
    session.turn_id = "turn_6089e7517986"
    stage.store.forget_scenario()
    for _ in range(2):
        await dispatch("gmail_search", {"query": "newer_than:2d", "limit": 5}, session=session, timeout_s=8.0)
    assert dedupe.current().stats()["requests_avoided"] >= 1


async def test_what_was_avoided_is_measured_not_claimed(stage):
    stats = dedupe.current().stats()
    for field in ("requests_avoided", "latency_saved_ms", "provider_calls_saved", "served", "coalesced", "reused"):
        assert field in stats, f"{field} is not measured"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_the_whole_scenario_suite_reads_less_than_it_used_to(stage):
    """The measurement over the golden scenarios rather than one contrived pair.

    A floor rather than a figure: the exact number moves when a scenario is added, and a test
    that pinned it would fail for the wrong reason. What must not move is that a real
    session's worth of work avoids a substantial share of its reads, and that every avoided
    read is a provider call that did not happen — `provider_calls_saved` equals
    `requests_avoided` here because every tool in PURE_READS talks to Shopify or Gmail.

    The milliseconds are small against the fixture shop, which answers instantly. Against the
    real one, where the live session measured 17,302 ms of reading, each of these costs
    150-400 ms.
    """
    from experience.scenarios import SCENARIOS

    dedupe.current().reset()
    for _name, scenario in SCENARIOS:
        await scenario(stage)
    stats = dedupe.current().stats()
    assert stats["requests_avoided"] >= 25, stats
    assert stats["provider_calls_saved"] == stats["requests_avoided"], stats
    assert stats["latency_saved_ms"] > 0, stats
    assert stats["requests_avoided"] > stats["served"] * 0.25, (
        f"less than a quarter of the reads were avoided: {stats}"
    )
    # And the tools the live session ran twice are in the saving.
    for tool in ("gmail_search", "shopify_order_detail"):
        assert stats["by_tool"].get(tool), f"{tool} never avoided a request: {stats['by_tool']}"
