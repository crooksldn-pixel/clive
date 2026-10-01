"""The parallel read scheduler.

A turn that needs an order, its customer's history and that customer's recent email is three
reads, two of which depend on the first. Run serially that is three round trips one after
another; run as a graph it is two. This module is the graph.

    plan = ReadPlan([
        Read("order", "shopify_find_order", {"query": "1938"}, source="shopify"),
        Read("history", "shopify_customer_history", args_from=..., after=("order",), source="shopify"),
        Read("email", "gmail_search", args_from=..., after=("order",), source="gmail"),
    ])
    result = await run_plan(plan, session=session)

What it guarantees:

* Only independent reads run together. `after` is the dependency; a read whose dependency
  failed is skipped, not run with a hole in its arguments.
* Per-source concurrency limits, so four parallel reads do not become four simultaneous
  Shopify calls against a leaky bucket, or four Gmail calls against a per-minute quota.
* A cost budget per source per plan. Shopify's calculated query cost is what the order cache
  already paces against (app/analytics/cache.py); a plan declares what it expects to spend
  and stops asking when it is spent.
* Cancellation: one `asyncio.TaskGroup`-shaped run, cancelled as a unit.
* Deterministic merge: results come back keyed by name, in plan order, whatever finished first.
* AN ORIGIN. A plan says whether the OWNER asked for it or the anticipation layer predicted it
  (`origin`, with `why`), which is what makes a predicted read distinguishable from a requested
  one everywhere downstream — the timeline event, the report, the memory entry it fills. A
  requested plan also stands the speculative lane down before it runs.
* A LANE, and with it a PRIORITY (app/reads/budget.py). Five budgets rather than one, in the
  order the owner's attention is in: his foreground read, his navigation's hydration, a
  mutation's precondition, a background job, a guess. Entering one of the first three stands
  the last two down, and the two lower lanes are capped below a source's concurrency so his
  read always finds a slot. That is D-4: one shared budget, scoped to a turn that outlived
  itself, refused the owner's own work because speculation had spent it.
* NO WRITES. A read whose tool has a WriteSpec or a BatchSpec is refused before the plan runs.
  Two writes must never be in flight together, and the way to guarantee that is to have no
  path from here to one.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from app.observability import timeline
from app.reads import budget
from app.tools.context import acting_branch

log = logging.getLogger("crooks.reads")

# How many reads of one source may be in flight at once. Shopify's Admin API is a leaky
# bucket refilling at 50 points a second; Gmail's per-user quota is generous but its
# per-thread fetches are not free. Four and three are what the tablet's screens need.
# One table, read from two places. The semaphore below is PER PLAN and the throttle in
# app/reads/budget.py is global, and the two disagreeing about how much of a source there is
# would be a bug nobody would look for — so the numbers live once, beside the throttle that
# needs them to mean something across plans.
SOURCE_LIMITS: dict[str, int] = budget.SOURCE_SLOTS
DEFAULT_LIMIT = budget.DEFAULT_SLOTS

# What one plan may spend at a source, in that source's own units. Shopify counts calculated
# query cost; Gmail counts requests. Both are ceilings, not targets.
SOURCE_BUDGET: dict[str, float] = {"shopify": 900.0, "gmail": 25.0, "mac": 1000.0}
# What a read of a source costs when it does not report its own.
DEFAULT_COST: dict[str, float] = {"shopify": 60.0, "gmail": 1.0, "mac": 1.0}

# The whole plan. Past this the answer is late enough that a partial one is better.
PLAN_TIMEOUT_S = 12.0
READ_TIMEOUT_S = 8.0


class WriteInPlan(RuntimeError):
    """A plan named a write tool. Reads only; this is a structural guarantee, not a policy."""


@dataclass(slots=True)
class Read:
    """One node. `args` is either a dict or a callable taking the results so far — that is how
    a dependent read gets the id the read before it found, without the caller pre-flattening
    the graph."""

    name: str
    tool: str
    args: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any] | None] = field(default_factory=dict)
    source: str = "shopify"
    after: tuple[str, ...] = ()
    cost: float | None = None
    timeout_s: float = READ_TIMEOUT_S
    # A read the answer can do without. When it fails or is skipped, the plan says so and
    # carries on; a required read failing marks the plan partial.
    optional: bool = True
    # False for a read whose result the recipe works FROM and draws its own card for: its
    # cards are not staged on the glass as it lands (app/progressive.py), so they cannot
    # flash up under the answer and be taken away again when the turn ends.
    draws: bool = True


@dataclass(slots=True)
class ReadPlan:
    reads: list[Read]
    label: str = ""
    timeout_s: float = PLAN_TIMEOUT_S
    # Who wanted this. "requested" is the owner — a question, a tap, a recipe's reads for
    # either; "predicted" is the anticipation layer reading before it was asked (§19 requires
    # the two to be distinguishable). It rides on the plan rather than in a second record
    # because the plan is already what the timeline writes down, and `why` says which rule or
    # which learned transition asked. A requested plan also OUTRANKS speculation: `run_plan`
    # stands the predicted lane down before it starts one.
    origin: str = "requested"
    why: str = ""
    # Which of the five budgets this plan spends, and therefore what it outranks. Left unset
    # it is read from the origin: a predicted plan is speculation and a requested one is the
    # owner's foreground read, which is what every caller meant before lanes existed. A
    # caller that knows better says so — a tap's hydration is NAVIGATION, a mutation's
    # fingerprint read is PRECONDITION.
    lane: str = ""
    # Which unit of work the lane's budget is charged to — the turn, the tap, the proposal.
    # Empty takes the lane the caller is already in, and then the turn: an unnamed unit of
    # work sharing the turn's key is the behaviour this module had before lanes, which is
    # never worse than it.
    key: str = ""
    # Which conversation this plan belongs to, for standing the lower lanes down. Filled from
    # the session by `run_plan` when the caller does not say.
    scope: str = ""
    # Whether `lane` was asked for or read off the origin. A plan that did not ask takes the
    # lane its caller is already in — a recipe run for a TAP reads in the navigation lane
    # without every recipe having to say so.
    lane_explicit: bool = False

    def names(self) -> list[str]:
        return [r.name for r in self.reads]

    def __post_init__(self) -> None:
        if self.lane:
            if self.lane not in budget.PRIORITY:
                raise ValueError(f"{self.lane!r} is not one of {budget.LANES}")
            self.lane_explicit = True
        else:
            self.lane = budget.SPECULATION if self.origin == "predicted" else budget.FOREGROUND


@dataclass(slots=True)
class ReadResult:
    values: dict[str, Any] = field(default_factory=dict)          # name -> the tool's payload
    calls: list[Any] = field(default_factory=list)                # ToolCall, in plan order
    ms: dict[str, float] = field(default_factory=dict)            # name -> milliseconds
    skipped: dict[str, str] = field(default_factory=dict)         # name -> why
    errors: dict[str, str] = field(default_factory=dict)
    critical_path_ms: float = 0.0
    serial_ms: float = 0.0                                        # what running them in turn would have taken
    groups: list[list[str]] = field(default_factory=list)         # what ran together
    spent: dict[str, float] = field(default_factory=dict)
    partial: bool = False

    @property
    def saved_ms(self) -> float:
        """Measured, not claimed: the sum of the read times minus the wall clock they took."""
        return max(0.0, self.serial_ms - self.critical_path_ms)

    def ok(self, name: str) -> bool:
        return name in self.values and self.values[name] is not None


def assert_reads_only(plan: ReadPlan) -> None:
    """Every tool in the plan is a read. Raised before anything runs."""
    from app.tools import registry

    for read in plan.reads:
        try:
            spec = registry.get(read.tool)
        except KeyError as exc:
            raise WriteInPlan(f"{read.tool!r} is not a registered tool") from exc
        if spec.write is not None or spec.batch is not None:
            raise WriteInPlan(
                f"{read.tool!r} is a write tool. The read scheduler runs reads only; a change "
                f"goes through the action engine, one at a time."
            )


def _layers(plan: ReadPlan) -> list[list[Read]]:
    """The plan as waves: everything in a wave is independent of everything else in it.
    A cycle, or a dependency on a name the plan does not contain, never enters a wave, and
    neither does anything that waits on it; the runner reports each as skipped with a reason.
    A missing dependency is not a satisfied one (S5-02: it used to be read as one, so a read
    ran with nothing behind it)."""
    done: set[str] = set()
    waves: list[list[Read]] = []
    remaining = list(plan.reads)
    while remaining:
        wave = [r for r in remaining if all(dep in done for dep in r.after)]
        if not wave:
            break   # a cycle: the rest are reported as skipped by the runner
        waves.append(wave)
        done.update(r.name for r in wave)
        remaining = [r for r in remaining if r.name not in done]
    return waves


def _lane_of(plan: ReadPlan, session: Any, turn_id: str) -> tuple[str, str]:
    """(lane, unit of work) for this plan.

    An explicit lane wins. Otherwise the plan takes the lane its caller is already in, which
    is how a recipe run for a tap reads in the navigation lane without every recipe having to
    know it was tapped. Failing both, the origin decides: a guess is speculation and a
    request is the owner's foreground read.
    """
    ambient_lane, ambient_key = budget.ambient_lane()
    lane = plan.lane if plan.lane_explicit else (ambient_lane or plan.lane)
    key = plan.key or (ambient_key if lane == ambient_lane else "") or turn_id or str(getattr(session, "turn_id", "") or "")
    return lane, key


async def run_plan(plan: ReadPlan, *, session: Any, timeout_s: float | None = None, turn_id: str = "") -> ReadResult:
    """Run the graph, in the plan's lane. Never raises for a read that failed: a failure is a
    name in `errors`."""
    assert_reads_only(plan)
    scope = plan.scope or budget.scope_of(session)
    lane, key = _lane_of(plan, session, turn_id)
    throttle = budget.throttle()
    if lane in budget.OWNER_LANES:
        # The owner has asked for something. Everything below this lane stands down first:
        # a guess and a background job hold a source's rate and nobody is waiting for either.
        # `budget.yield_to` is what decides which lanes are below this one; the anticipation
        # layer registers itself as one of the things that stands down (app/anticipation/
        # engine.py), so this file knows nothing about it.
        #
        # It used to be `if plan.origin != "predicted"` and a direct call into the
        # anticipation engine, which stood down the P2 lane and nothing else — so a background
        # job kept its slot, and the layer had to be installed for a stand-down to happen at
        # all.
        #
        # Which half stands down is the half THIS read is for (round 10): the session's own
        # `acting_branch` is one field for both halves and holds whichever spoke last, so with two
        # halves thinking at once a read for one stood the other's guesses down and left its own
        # running. `acting_branch(session)` is the running request's half first (CURRENT_BRANCH,
        # set per call), then the session's.
        try:
            budget.yield_to(lane, scope=scope, branch_id=acting_branch(session))
        except Exception as exc:  # noqa: BLE001 — a read is not failed by a cancellation
            log.debug("could not stand the lower lanes down: %s", exc)
    from app.tools.dispatch import dispatch

    result = ReadResult()
    by_name = {r.name: r for r in plan.reads}
    started_all = time.perf_counter()
    limits = {source: asyncio.Semaphore(SOURCE_LIMITS.get(source, DEFAULT_LIMIT)) for source in {r.source for r in plan.reads}}
    # Renamed from `budget`: the module of that name is now what says which lane this plan is
    # in, and a local that shadowed it was a bug waiting for the first person to use both.
    allowance = {source: SOURCE_BUDGET.get(source, 100.0) for source in limits}
    order = plan.names()
    calls_by_name: dict[str, Any] = {}

    done_count = 0
    total = len(plan.reads)

    def progress(read: Read) -> None:
        """What the Mac is doing, in the owner's words, while it does it (brief section 12).

        Counts and source names only — "2 of 3 checked", "reading the inbox". Never the
        model's reasoning, which the timeline does not carry and this cannot reach.
        """
        nonlocal done_count
        done_count += 1
        try:
            session.set_state(
                "CHECKING EMAIL" if read.source == "gmail" else "CHECKING SHOPIFY",
                f"{done_count} of {total} read" if total > 1 else read.tool,
            )
        except AttributeError:
            pass

    async def one(read: Read) -> None:
        args = read.args(dict(result.values)) if callable(read.args) else dict(read.args or {})
        if args is None:
            result.skipped[read.name] = "nothing to look up"
            return
        cost = float(read.cost if read.cost is not None else DEFAULT_COST.get(read.source, 1.0))
        if allowance.get(read.source, 0.0) < cost:
            result.skipped[read.name] = f"the {read.source} budget for this answer is spent"
            result.partial = result.partial or not read.optional
            return
        if not throttle.admit(read.source, lane):
            # The global throttle, which the per-plan semaphore above cannot see: speculation
            # in its own plan held its own four Shopify slots while the owner's plan held
            # four more, and both went to the same leaky bucket. A lower lane that is at its
            # share of a source waits for the next question rather than spending his rate.
            result.skipped[read.name] = f"{read.source} is busy with work the owner is waiting on"
            result.partial = result.partial or not read.optional
            return
        allowance[read.source] -= cost
        result.spent[read.source] = result.spent.get(read.source, 0.0) + cost
        own: list[Any] = []
        t0 = time.perf_counter()
        with throttle.holding(read.source, lane), budget.using(lane, key, scope=scope, yielding=False):
            async with limits[read.source]:
                try:
                    with nullcontext() if read.draws else progressive.background():
                        await dispatch(read.tool, args, session=session, timeout_s=read.timeout_s, calls=own)
                except Exception as exc:  # noqa: BLE001 — a failed read is a reported read
                    result.errors[read.name] = str(exc)[:200]
        ms = (time.perf_counter() - t0) * 1000
        progress(read)
        result.ms[read.name] = round(ms, 1)
        result.serial_ms += ms
        if own:
            call = own[-1]
            calls_by_name[read.name] = call
            if call.ok:
                result.values[read.name] = call.result
            else:
                result.errors.setdefault(read.name, str(call.error or "the read did not come back")[:200])
        if read.name in result.errors and not read.optional:
            result.partial = True

    # A predicted read is nobody's question: its cards are not staged onto the glass while the
    # owner is looking at something else (app/progressive.py, and D-4 on what happens when
    # anticipation is allowed to spend the foreground's room).
    from app import progressive

    speculative = progressive.background() if plan.origin == "predicted" else nullcontext()
    # What this plan is going to put on the screen, said BEFORE the first read runs (§15):
    # the workspace names itself and the sections coming, each waiting, rather than the owner
    # watching an empty screen until the graph resolves. Bookkeeping only, and never for a
    # read nobody asked for.
    if plan.origin != "predicted":
        progressive.planning(session, [r.tool for r in plan.reads if r.draws])
    try:
        # The flag is set before the tasks are made: `asyncio.gather` copies the context at
        # creation, so every read in every wave runs with it.
        with speculative:
            # A read that waits on a name the plan does not hold is never dispatched; it is
            # skipped with the name it was waiting for, and anything waiting on IT is skipped
            # below as depending on something that never ran.
            for read in plan.reads:
                absent = [d for d in read.after if d not in by_name]
                if absent:
                    result.skipped[read.name] = f"it waits on {', '.join(absent)}, which this plan does not hold"
                    result.partial = result.partial or not read.optional
            async with asyncio.timeout(plan.timeout_s if timeout_s is None else timeout_s):
                for wave in _layers(plan):
                    runnable = [r for r in wave if all(d in by_name and d not in result.errors and d not in result.skipped for d in r.after)]
                    for read in wave:
                        if read not in runnable:
                            result.skipped[read.name] = "what it needed did not come back"
                            result.partial = result.partial or not read.optional
                    if not runnable:
                        continue
                    result.groups.append([r.name for r in runnable])
                    await asyncio.gather(*(one(r) for r in runnable))
    except TimeoutError:
        result.partial = True
        for read in plan.reads:
            if read.name not in result.values and read.name not in result.errors:
                result.skipped.setdefault(read.name, "the answer was already late")

    for name, read in by_name.items():
        if name not in result.values and name not in result.errors and name not in result.skipped:
            result.skipped[name] = "it depended on something that never ran"
            result.partial = result.partial or not read.optional
    result.critical_path_ms = round((time.perf_counter() - started_all) * 1000, 1)
    result.serial_ms = round(result.serial_ms, 1)
    result.calls = [calls_by_name[name] for name in order if name in calls_by_name]
    result.partial = result.partial or bool(result.errors)

    if timeline.current().active is not None:
        timeline.emit(
            "read_plan", session_id=getattr(session, "session_id", None), turn_id=turn_id or getattr(session, "turn_id", "") or None,
            label=plan.label or None, origin=plan.origin, why=plan.why or None, lane=lane,
            groups=result.groups, fanout=max((len(g) for g in result.groups), default=0),
            critical_path_ms=result.critical_path_ms, serial_ms=result.serial_ms, saved_ms=round(result.saved_ms, 1),
            spent=result.spent, ms=result.ms, skipped=result.skipped or None, errors=list(result.errors) or None,
            partial=result.partial,
        )
    return result
