"""What speculation costs the owner, and what it saves him. Run: python bench/anticipation.py

Two measurements, and the first is the evidence for the bounds in app/anticipation/engine.py.

CONTENTION — the cost. Hold N speculative reads of one source in flight and then run the read
the owner is actually waiting for, through the same scheduler. What contends is a source's
concurrency: `SOURCE_LIMITS` gives Shopify four simultaneous reads and Gmail three, so every
slot speculation holds is a slot the owner queues behind. The per-read latency is a MODEL
PARAMETER (--latency, milliseconds, swept over two values by default) because that part depends
on the store and the day, not on this code; what the bench measures is the queueing, which
depends only on the limit, the latency and how many slots are taken.

EFFECT — the saving. Through the experience harness, against the fixture world: open a working
set, land on a member, let the anticipation layer read the next one on a hunch, and then move
to it. With the layer on that move is drawn from memory; with it off it is a Shopify read. The
numbers printed are the tap's own (`served_ms`), whether the record had to be read, and the
cache's `predicted_hits` — which is how a turn says it was served something nobody asked for.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.reads.scheduler import SOURCE_LIMITS, Read, ReadPlan, run_plan  # noqa: E402

SPECULATIVE_TOOL = "shopify_order_detail"
REQUESTED_TOOLS = ("shopify_find_order", "shopify_customer_history")


async def _contention(latency_ms: float, holding: int, *, repeats: int = 5) -> float:
    """The owner's two-read plan, with `holding` speculative reads of the same source already
    in flight. Returns the median critical path in milliseconds."""
    import app.tools.shopify_tools  # noqa: F401 — registers the tools the plans name
    from app.providers.base import ToolCall
    from app.session.models import Session
    from app.tools import dispatch as dispatch_mod

    real = dispatch_mod.dispatch

    async def modelled(name, args, *, session, timeout_s, calls=None):  # noqa: ARG001
        await asyncio.sleep(latency_ms / 1000.0)
        if calls is not None:
            calls.append(ToolCall(name=name, args=args, ok=True, duration_ms=latency_ms, result={"read": name}))
        return "{}"

    dispatch_mod.dispatch = modelled
    try:
        out: list[float] = []
        session = Session(session_id="bench")
        for _ in range(repeats):
            held = [
                asyncio.create_task(run_plan(
                    ReadPlan([Read(f"guess{i}", SPECULATIVE_TOOL, {"order_id": str(i)})],
                             label="anticipate:bench", origin="predicted"),
                    session=session,
                ))
                for i in range(holding)
            ]
            await asyncio.sleep(0.005)      # let them take their slots
            started = time.perf_counter()
            await run_plan(
                ReadPlan([Read(name, tool, {}) for name, tool in zip("ab", REQUESTED_TOOLS, strict=False)], label="asked"),
                session=session,
            )
            out.append((time.perf_counter() - started) * 1000)
            for task in held:
                task.cancel()
            await asyncio.gather(*held, return_exceptions=True)
        return round(statistics.median(out), 1)
    finally:
        dispatch_mod.dispatch = real


def budget(most: int) -> None:
    """The constraint the contention measurement rules IN.

    Shopify's Admin API is a leaky bucket: `app/reads/scheduler.py` prices a read at
    DEFAULT_COST points and records the bucket refilling at REFILL points a second. Concurrency
    inside this process is per plan (the measurement above), so what speculation really spends
    is RATE — points the owner's own reads then have to wait for. This prints, per number of
    speculative reads of one source per record opened, what that costs against the refill at
    three cadences of opening records.
    """
    from app.reads.scheduler import DEFAULT_COST

    cost = DEFAULT_COST["shopify"]
    refill = 50.0                     # points a second, as the scheduler's own comment records
    print("BUDGET — what speculation spends of Shopify's refill")
    print(f"  a read costs {cost:.0f} points; the bucket refills at {refill:.0f} a second")
    for cadence in (3.0, 10.0, 30.0):
        row = []
        for holding in range(1, most + 1):
            share = (holding * cost) / (refill * cadence) * 100
            row.append(f"{holding}:{share:>5.0f}%")
        print(f"  a record opened every {cadence:>4.0f}s   " + "   ".join(row))
    print("  Read as: speculative reads per open / the share of the refill they spend.")


async def contention(latencies: tuple[float, ...], most: int) -> None:
    print("CONTENTION — what the owner waits for his own two-read plan")
    print(f"  Shopify's concurrency through the scheduler: {SOURCE_LIMITS['shopify']} reads; Gmail's: {SOURCE_LIMITS['gmail']}")
    for latency in latencies:
        row = []
        base = None
        for holding in range(most + 1):
            ms = await _contention(latency, holding)
            base = ms if base is None else base
            row.append(f"{holding}:{ms:>7.1f}ms{'' if base == 0 else f' (+{ms - base:>5.1f})'}")
        print(f"  read modelled at {latency:>5.0f} ms   " + "   ".join(row))
    print("  Read as: speculative reads held / what the owner's plan then took.")


async def effect() -> None:
    """The saving, end to end, through the harness. Prints one line per configuration."""
    from experience.harness import harness

    for anticipating in (False, True):
        async with harness(admitted=True) as h:
            from app.anticipation import engine as anticipation_mod
            from app.anticipation.learning import Learner
            from app.memory import current as memory
            from app.memory.prefetch import Prefetcher

            anticipation_mod.install(anticipation_mod.Anticipator(
                learner=Learner(), prefetcher=Prefetcher(),
                max_anticipated=4 if anticipating else 0,
                max_speculative=2 if anticipating else 0,
            ))
            listed = await h.touch("open.area", area="orders", session_id="bench")
            first = await h.touch("workflow.next", session_id="bench")
            order_id = (first.entity or {}).get("ref", "")
            if not order_id:
                print("  the working set landed on nothing — fixture world changed?")
                return
            _, enriched = await h.enrich(order_id, session_id="bench")   # "an order opened"
            anticipated = enriched.get("anticipated") or {}
            await asyncio.sleep(0.6)                          # let the background reads land
            before = memory().counts()
            moved = await h.touch("workflow.next", session_id="bench")
            after = memory().counts()
            read_again = bool((moved.raw.get("changed") or {}).get("read"))
            print(
                f"  anticipation {'on ' if anticipating else 'off'}: "
                f"move took {moved.raw.get('served_ms'):>6}ms, "
                f"had to read the record: {str(read_again):<5} "
                f"predicted_hits {before['predicted_hits']}->{after['predicted_hits']}  "
                f"(list {listed.raw.get('served_ms')}ms)"
            )
            print(f"    it read: {[r['why'] for r in anticipated.get('reads') or []]}"
                  f"  state {anticipated.get('state')!r}")
            # And the same move SPOKEN, which is the turn §25's three numbers are reported on:
            # when the facts were held, when the cards existed, what was waited after the facts.
            spoken = await h.say("next", session_id="bench")
            performance = spoken.raw.get("performance") or {}
            print(
                f"    spoken next: lane {performance.get('lane')}, "
                f"facts {performance.get('facts_ms')}ms, workspace {performance.get('workspace_ms')}ms, "
                f"prose wait {performance.get('prose_wait_ms')}ms, "
                f"tool calls {performance.get('tool_calls')}, "
                f"cache {(performance.get('cache') or {}).get('hits')} hits of which "
                f"{(performance.get('cache') or {}).get('predicted_hits')} predicted"
            )
            anticipation_mod.install(None)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latency", type=float, nargs="*", default=[150.0, 400.0])
    parser.add_argument("--most", type=int, default=5, help="most speculative reads to hold")
    parser.add_argument("--only", choices=("contention", "effect"), default="")
    args = parser.parse_args()
    if args.only != "effect":
        await contention(tuple(args.latency), args.most)
        budget(args.most)
    if args.only != "contention":
        print("EFFECT — moving to the next record after an order card came up")
        await effect()


if __name__ == "__main__":
    asyncio.run(main())
