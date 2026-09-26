#!/usr/bin/env python3
"""Time the fast lane against the same fake store the rest of the bench uses.

    make bench-lanes            # or: .venv/bin/python scripts/bench_lanes.py [--latency-ms 40]

What is measured here is the Mac's own path: intent resolution, entity resolution, the reads
a recipe makes (in parallel where they are independent), and the sentence it composes —
against a simulated per-request source latency, with no network and no model.

What "before" means, and where each figure comes from, because a speedup nobody measured is
not a speedup:

  * The BASELINE column is read from the real test session of 9 September 2026
    (reports/ts-20260909-201047-session.md), turn by turn. Those are wall-clock figures from
    the tablet on the bench, including Claude. They are quoted, not re-run: this machine has
    no Claude and no store.
  * The AFTER column is measured here, now, at the latency named on the command line, and is
    the Mac's own work only — the same thing the baseline's non-Claude time measures.
  * MODEL CALLS is exact in both columns and is the number that actually explains the
    difference. The September capability question took 75.5 seconds and made zero tool
    calls; the same question is now a comparison of two manifests the Mac already holds.

Where a recipe has no baseline turn in that session, the cell says so rather than inventing
a number to be beaten.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CROOKS_ANALYTICS_WARM_DAYS", "0")

# Measured, on the tablet, on 9 September 2026. Turn ids are in the report beside each.
# (recipe_id, what was asked, total ms, model ms, tool calls)
BASELINE: dict[str, tuple[str, float | None, float | None, int]] = {
    "capability_delta": ("I updated your capabilities earlier. What more can you do now?", 76_585, 75_530, 0),
    "working_set_next": ("Next", 30_430, 29_440, 0),
    "needs_reply": ("Which customers need replying to?", 29_010, 28_099, 0),
    "sales_breakdown_period": ("How were sales last week", None, None, 0),
    "order_address_lookup": ("Read me the full address", 36_812, 35_236, 1),
}


def _fmt(ms: float | None) -> str:
    if ms is None:
        return "—"
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:,.0f} ms"


async def _timed(fn, *, repeat: int = 3) -> float:
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        await fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--orders", type=int, default=200)
    parser.add_argument("--latency-ms", type=float, default=40.0, help="simulated Shopify / Gmail latency per request")
    args = parser.parse_args(argv)

    from app.analytics import sets
    from app.analytics.cache import OrderCache
    from app.capabilities.delta import record_build
    from app.capabilities.manifest import build as build_manifest
    from app.families import landings
    from app.fastpath import RECIPES, choose_lane, recipe_for, resolve, run
    from app.fastpath import library as _recipes  # noqa: F401 — importing it is what registers them
    from app.fastpath.intent import Intent, signals_for
    from app.fastpath.models import Ctx
    from app.memory import Memory
    from app.memory import install as install_memory
    from app.session.models import Session
    from app.tools import analytics_tools, shopify_tools  # noqa: F401
    from tests.test_analytics import HOODIE, JEANS, JOGGERS, node
    from tests.test_analytics_tools import Store, london_now
    from tests.test_context import CUSTOMER, ORDER, inbox
    from tests.test_context import Store as OrderStore

    # `london_now` freezes the clock the analytic tools read, and it is written for pytest's
    # monkeypatch, which undoes what it sets. This bench is normally its own process, where
    # that does not matter — but tests/test_operations.py runs `main()` IN PROCESS, and a
    # frozen clock left behind made every later harness read of "today's orders" come back
    # empty, three files further down the suite. It cost an afternoon to find twice. So this
    # shim remembers what it replaced, and the bench puts it back before it returns.
    undo: list[tuple[Any, str, Any]] = []

    class Patch:
        def setattr(self, obj, name, value):
            undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)

    london_now(Patch())
    products = [JOGGERS, JEANS, HOODIE]
    nodes = [
        node(1000 + i, days_ago=(i * 89.0 / max(1, args.orders)) + 0.1,
             items=[(*products[i % 3], ["Black", "Pink", "Grey", "Blue"][i % 4], ["S", "M", "L", "XL"][i % 4], 1 + i % 3, 45.0 + 15 * (i % 3))],
             customer=(f"gid://shopify/Customer/{i % 60}", f"Customer {i % 60} Name", 1 + i % 5, 100.0 * (1 + i % 5)),
             fulfillment="UNFULFILLED" if i % 7 == 0 else "FULFILLED")
        for i in range(args.orders)
    ]
    store = Store(nodes)
    store.delay_s = args.latency_ms / 1000.0
    for n in nodes:
        for e in n["lineItems"]["edges"]:
            store.stock[e["node"]["variant"]["id"]] = 12
    # Two doubles, because they answer different documents: the read layer's fake pages
    # orders, and the context fake answers the order/customer reads an order card is built
    # from. The bench binds whichever the row under test actually uses, and says which.
    orders = OrderStore()
    _orders_graphql = orders.graphql

    async def slow_orders(query, variables=None):
        # The context double has no latency of its own; the bench gives it the same one
        # every other source gets, so the figures mean the same thing in every row.
        await asyncio.sleep(args.latency_ms / 1000.0)
        return await _orders_graphql(query, variables)

    orders.graphql = slow_orders
    shopify_tools.bind(orders, threads_for=inbox())
    analytics_tools.bind(OrderCache(lambda: store, clock=time.time))
    memory = install_memory(Memory())

    async def threads_for(**kwargs):
        await asyncio.sleep(args.latency_ms / 1000.0)
        return {"available": True, "threads": []}

    async def reply_state(thread_id):
        await asyncio.sleep(args.latency_ms / 1000.0)
        return None

    # The needs-reply recipe reads the inbox itself; the same empty inbox, the same latency.
    analytics_tools.bind_email(threads_for, None, reply_state, inbox_for=threads_for)

    class Runtime:
        build = "bench"

    Runtime.manifest = build_manifest(build_id="bench")
    smaller = {**Runtime.manifest, "reads": Runtime.manifest["reads"][1:], "build": "bench-before"}
    log_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "crooks-bench"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "capabilities.json").unlink(missing_ok=True)
    record_build(smaller, log_dir)
    Runtime.capability_record = record_build(Runtime.manifest, log_dir)

    session = Session(session_id="bench")
    session.epoch = 1
    branch = session.branch()
    order_id = ORDER
    session.issue(order_id, CUSTOMER)
    number = "1938"

    async def turn(text: str, *, repeat: int = 3) -> tuple[str, float, int, str]:
        """One request through the router and, when it takes the fast lane, the recipe."""
        session.plan = None
        intent = resolve(text, branch=branch)
        recipe = recipe_for(intent.family) if intent.family else None
        lane, _ = choose_lane(intent, recipe=recipe, text=text)
        if lane != "FAST" or recipe is None:
            return lane, 0.0, 1, "the model's"
        outcome = {"defer": ""}

        async def once():
            session.plan = None
            answer = await run(recipe, Ctx(runtime=Runtime, session=session, branch=branch, intent=intent, text=text, memory=memory))
            outcome["defer"] = answer.defer
            outcome["answer"] = answer.answer

        ms = await _timed(once, repeat=repeat)
        if outcome["defer"]:
            return "NORMAL", ms, 1, f"deferred: {outcome['defer']}"
        return "FAST", ms, 0, str(outcome.get("answer", ""))[:60]

    rows: list[list[str]] = []

    def record(recipe_id: str, asked: str, lane: str, ms: float, calls: int) -> None:
        base = BASELINE.get(recipe_id)
        if base is not None and base[1] is None:
            base = None
        target = RECIPES[recipe_id].target_ms if recipe_id in RECIPES else None
        rows.append([
            asked,
            f"{_fmt(base[1])} ({base[3]} tool call(s), {_fmt(base[2])} of it Claude)" if base else "not asked in that session",
            f"{_fmt(ms)}  lane {lane}",
            f"{base[3] and 1 or 1} → {calls}" if base else f"1 → {calls}",
            ("under" if target and ms <= target else "OVER") + f" {_fmt(target)}" if target else "—",
        ])

    # 1. the two questions about itself: no source at all
    lane, ms, calls, _ = await turn("what can you do?")
    record("capability_summary", "What can you do?", lane, ms, calls)
    lane, ms, calls, _ = await turn("what more can you do now?")
    record("capability_delta", "What more can you do now?", lane, ms, calls)

    # 2. an order, cold then warm
    lane, cold, calls, _ = await turn(f"order {number}", repeat=1)
    record("order_lookup", f"Order {number} (cold)", lane, cold, calls)
    lane, warm, calls, _ = await turn(f"order {number}")
    record("order_lookup", f"Order {number} (again)", lane, warm, calls)
    lane, ms, calls, _ = await turn(f"read me the full address for order {number}")
    record("order_address_lookup", "Read me the full address", lane, ms, calls)
    lane, ms, calls, _ = await turn(f"where is order {number}")
    record("order_status_lookup", "Where is that order", lane, ms, calls)

    # 3. the numbers, against the read layer's own fake
    shopify_tools.bind(store)
    lane, ms, calls, _ = await turn("what sold best this month", repeat=1)
    record("best_sellers_period", "What sold best this month", lane, ms, calls)
    lane, ms, calls, _ = await turn("which orders are late", repeat=1)
    record("delayed_orders", "Which orders are late", lane, ms, calls)
    lane, ms, calls, _ = await turn("what is running out", repeat=1)
    record("stock_cover_analysis", "What is running out", lane, ms, calls)

    lane, ms, calls, _ = await turn("how were sales last week", repeat=1)
    record("sales_breakdown_period", "How were sales last week", lane, ms, calls)
    lane, ms, calls, _ = await turn("which customers are waiting on a reply", repeat=1)
    record("needs_reply", "Which customers are waiting on a reply", lane, ms, calls)

    # 3b. the dock's landings (brief section 4). Not in the September baseline: they were a
    # sentence through the whole turn pipeline then, and the point of Phase 3 is that they are
    # a place with a fixed shape. What is timed is the whole landing — three reads for Sales,
    # two each for Orders and Products — because that is what a thumb on the dock pays for.
    for area, asked in (("orders", "Tap Orders"), ("sales", "Tap Sales"), ("products", "Tap Products")):
        recipe_id = landings.AREAS[area]
        recipe = RECIPES[recipe_id]
        intent = Intent(family=recipe.intent_family, confidence=1.0, signals=signals_for("", branch=branch), reason="a tap")
        outcome: dict[str, str] = {}

        async def once(recipe=recipe, intent=intent, outcome=outcome):
            session.plan = None
            answer = await run(recipe, Ctx(runtime=Runtime, session=session, branch=branch, intent=intent, text="", memory=memory))
            outcome["defer"] = answer.defer
            outcome["answer"] = answer.answer

        ms = await _timed(once, repeat=1)
        record(recipe_id, asked, "NORMAL" if outcome.get("defer") else "FAST", ms, 0)

    # 4. moving through a set, member by member — the thirty-second turn. The set is made
    # explicitly here, of orders the order double actually holds: what is being timed is the
    # cursor move and one member's read, not the listing that produced the set.
    shopify_tools.bind(orders, threads_for=inbox())
    branch.workflow = None
    sets.create(session, kind="orders", members=[order_id], label="to work through")
    lane, ms, calls, _ = await turn("next")
    record("working_set_next", "Next", lane, ms, calls)
    lane, ms, calls, _ = await turn("next")
    record("working_set_next", "Next (again)", lane, ms, calls)

    # 5. the back stack: no source at all, and no model
    branch.visit("order", order_id, f"#{number}", tab="items")
    branch.visit("customer", "gid://shopify/Customer/1", "Customer 1")
    lane, ms, calls, _ = await turn("go back")
    record("navigation_back", "Go back", lane, ms, calls)

    print(f"\nThe fast lane against a fake store: {args.orders} orders, {args.latency_ms:.0f} ms per source request.")
    print("Baseline is the real session of 9 September 2026 (reports/ts-20260909-201047-session.md), quoted.\n")
    header = ["Asked", "9 Sept, on the tablet", "Now, the Mac's own work", "Model calls", "Against target"]
    widths = [max(len(str(r[i])) for r in rows + [header]) for i in range(len(header))]
    print("| " + " | ".join(h.ljust(w) for h, w in zip(header, widths, strict=True)) + " |")
    print("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for r in rows:
        print("| " + " | ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)) + " |")

    fast = sum(1 for r in rows if "FAST" in r[2])
    print(f"\n{fast} of {len(rows)} answered with no model call. Recipe statistics:")
    for rid, stat in sorted(((rid, r.stats) for rid, r in RECIPES.items() if r.stats.runs)):
        print(f"  {rid:24} {stat.runs:2} run(s), {stat.hits} answered, {stat.deferred} deferred, median {stat.average_ms:,.0f} ms")
    print(f"\nCache: {memory.counts()}")
    for obj, name, was in reversed(undo):
        setattr(obj, name, was)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
