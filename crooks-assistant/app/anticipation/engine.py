"""The anticipation layer: one place that decides what to read before it is asked for.

The pieces already existed — a tiered cache, an in-flight coalescer, a bounded prefetcher, a
parallel read scheduler. What did not exist was a layer that decides. This is it, and it is
deliberately small: it takes a `Signal` (the owner opened an order), asks the rules and the
learned table what is worth reading, and starts what the bounds allow through the machinery
that was already there.

    level 1   app/anticipation/rules.py     deterministic
    level 2   app/anticipation/learning.py  transition probabilities from real use
    level 3   `suggestions()`               high confidence only, offered, never executed

Every hard rule of §18 is mechanical here rather than advisory:

* **Never a write.** A prediction's tool is checked against the registry (`write is None and
  batch is None`) and then run through `run_plan`, which refuses a write tool before the plan
  starts. An internal prediction can only name something in the closed table in
  app/anticipation/internal.py. There is no third path, so there is no path to a mutation.
* **The owner outranks it.** This layer REGISTERS ITSELF as something that stands down
  (`app/reads/budget.py::on_yield`), and the read scheduler stands the lower lanes down
  whenever a plan in one of the owner's three lanes starts — his foreground read, his
  navigation's hydration, a mutation's precondition. It is registered rather than called by
  name so the scheduler knows nothing about anticipation, and so anything else that holds
  work nobody is waiting on can stand down the same way. A context change — a different
  record on that half — cancels that half's speculation outright. The other half is
  untouched: he did not ask it anything.
* **Deduped and coalesced.** A prediction whose key is already in flight is skipped; a
  prediction whose answer is already fresh in the tiered cache is skipped; what does run goes
  into that same cache, so the requested read that follows finds it there instead of asking
  Shopify a second time.
* **Bounded.** Per conversation: `MAX_PER_SOURCE` reads of any one source, `MAX_ANTICIPATED`
  that spend a source's rate at all, and of those at most `MAX_SPECULATIVE` of the P2 kind.
  The numbers are measured rather than chosen — see the constants, and bench/anticipation.py.
* **Isolated.** Everything is keyed by scope (login and conversation). One owner's speculation
  is never cancelled by, counted against, or served to another's.

What it writes down: one `anticipation` event per signal and one `prediction` event per
prediction started, plus `origin="predicted"` on the read plan and on the memory entry's
provenance. That is what answers "why was this prefetched?" — see `explain()`, and
GET /anticipation, which is the debug view §19 asks for.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.anticipation import rules as rules_mod
from app.anticipation.learning import SUGGEST_THRESHOLD, Learner
from app.anticipation.learning import current as learner_current
from app.anticipation.models import (
    LEVEL_SUGGESTION,
    P1,
    P2,
    PREDICTED,
    Prediction,
    Signal,
)
from app.reads import budget
from app.tools.context import acting_branch

log = logging.getLogger("crooks.anticipation")

# The three bounds, and where the numbers come from. MEASURED, not chosen —
# bench/anticipation.py, whose two halves rule one worry out and the real one in.
#
# The worry that turns out NOT to bind is in-process queueing. Hold five speculative reads of
# one source in flight and the owner's own two-read plan of that same source is unaffected:
# +0.2 to +0.4 ms at a read modelled at 150 ms, and the same at 400 ms. The scheduler's
# `SOURCE_LIMITS` semaphore is built PER PLAN, so speculation in its own plan never takes a
# slot from his. Worth knowing, and worth not designing around.
#
# What does bind is RATE. The scheduler prices a Shopify read at 60 points and records the
# bucket refilling at 50 a second, so speculation spends refill the owner's next read needs.
# At the fastest cadence the tablet actually produces — a record every three seconds, which is
# a thumb on Next through a working set — one speculative Shopify read per open spends 40% of
# the refill, two spend 80%, and three spend 120%: past the refill, which is where his own
# reads begin to wait. Ten seconds between records and even five are comfortable, but the
# bound has to hold at the fast cadence, not the comfortable one.
#
# Hence: at most TWO anticipated reads of any one source, which is the bound that matters, and
# at most four SOURCE-SPENDING reads in total (so Shopify at two and Gmail at two, together).
# Of those four at most two may be the speculative P2 kind, so a guess about the next record
# can never crowd out the reads about the record on screen. The brief asks for roughly 2-4
# concurrent speculative reads; this is four, with the per-source half at two. Re-run the bench
# and move them if the store's pricing changes.
#
# CLIVE's own internal reads (source "mac", app/anticipation/internal.py — none at present; the
# shipping context was the one until the old Easyship boundary went, DEC-071 ruling 24) spend no
# source budget and are not counted against the four. They are still bounded: `MAX_PER_SIGNAL`
# here and `MAX_IN_FLIGHT` per scope in the prefetcher, which is the outer wall for everything.
MAX_ANTICIPATED = 4
MAX_PER_SOURCE = 2
MAX_SPECULATIVE = 2
# The sources whose rate speculation spends, and therefore the ones the bounds above count.
# "mac" is not one of them: an internal read asks something inside this process.
SPENDING_SOURCES = ("shopify", "gmail")
# What one signal may start, however many rules fire. A signal that wants eight reads is a rule
# problem, not a budget to spend.
MAX_PER_SIGNAL = 6
# How many predictions are kept for the debug view. Bounded: this is a diagnostic, not a log.
HISTORY = 200
# How often the learned table is written to disk. Every fifth thing learned rather than every
# one: the file is small, but this runs beside a request the owner is waiting on.
SAVE_EVERY = 5


@dataclass
class Started:
    """One prediction that actually ran, kept for the debug view."""

    key: str
    tier: str
    tool: str
    why: str
    level: int
    confidence: float
    observations: int
    scope: str
    branch_id: str = ""
    ref: str = ""
    at: float = 0.0
    outcome: str = "in_flight"      # in_flight | landed | empty | cancelled

    def public(self, now: float) -> dict[str, Any]:
        return {
            "key": self.key, "tier": self.tier, "read": self.tool, "why": self.why,
            "level": self.level, "confidence": round(self.confidence, 3),
            "observations": self.observations, "origin": PREDICTED,
            "record": self.ref or None, "age_s": round(max(0.0, now - self.at), 1),
            "outcome": self.outcome,
        }


@dataclass
class Decision:
    """What one signal produced. Returned so a caller (and a test) can see the reasoning."""

    state: str = ""
    scope: str = ""
    started: list[Prediction] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    learned: str = ""                                   # the transition recorded, if any
    cancelled: int = 0


class Anticipator:
    def __init__(
        self, *, learner: Learner | None = None, prefetcher: Any = None, memory: Any = None,
        max_anticipated: int = MAX_ANTICIPATED, max_speculative: int = MAX_SPECULATIVE,
        max_per_source: int = MAX_PER_SOURCE, clock=time.time,
    ) -> None:
        self._learner = learner
        self._prefetcher = prefetcher
        self._memory = memory
        self.max_anticipated = int(max_anticipated)
        self.max_speculative = int(max_speculative)
        self.max_per_source = int(max_per_source)
        self.clock = clock
        # Per scope, then per half: where each half of the conversation was last, so a
        # transition can be recorded and a context change noticed. Nested under the scope so
        # that forgetting a conversation forgets both its halves (S5-03: keyed flat as
        # "scope|branch_id", `forget(scope)` removed nothing and an ended conversation could
        # feed a false transition to whoever spoke next under that scope).
        self._last: dict[str, dict[str, tuple[str, str, str]]] = {}   # scope -> branch_id -> (state, kind, ref)
        self._history: deque[Started] = deque(maxlen=HISTORY)
        self._suggestions: dict[str, list[dict[str, Any]]] = {}
        self.signals = 0
        self.started = 0
        self.skipped = 0
        self.cancelled = 0
        self.refused_writes = 0

    # ------------------------------------------------------------------ dependencies

    @property
    def learner(self) -> Learner:
        return self._learner if self._learner is not None else learner_current()

    @property
    def prefetcher(self) -> Any:
        if self._prefetcher is not None:
            return self._prefetcher
        from app.memory.prefetch import current as prefetch_current

        return prefetch_current()

    @property
    def memory(self) -> Any:
        if self._memory is not None:
            return self._memory
        from app.memory import current as memory_current

        return memory_current()

    # ------------------------------------------------------------------ the decision

    async def on_signal(self, signal: Signal, *, session: Any, learn: bool = True) -> Decision:
        """Record what the owner did, and start what is worth reading because of it.

        Never raises: this runs beside a request the owner is waiting on, and a bug in a
        prediction must not cost him the answer he asked for.
        """
        decision = Decision(state=signal.state, scope=signal.scope)
        try:
            self.signals += 1
            # Where this HALF of the conversation was. The split workspace is two places the
            # owner works (app/session/branch.py), and moving on one is not moving on the
            # other: keyed per branch, so a transition is learned per half and a context
            # change cancels only that half's speculation.
            halves = self._last.setdefault(signal.scope, {})
            previous = halves.get(signal.branch_id)
            if learn and previous is not None and previous[0]:
                edge = self.learner.observe(previous[0], signal.event)
                if edge is not None:
                    decision.learned = f"{edge.state}->{edge.event}"
                    if self.learner.observed % SAVE_EVERY == 0:
                        self.learner.save()
            if previous is not None and (previous[1], previous[2]) != (signal.kind, signal.ref):
                # The owner moved to a different record. Everything read on a hunch about the
                # last one is about the wrong thing now.
                decision.cancelled = self.prefetcher.cancel_scope(signal.scope, branch_id=signal.branch_id)
                self.cancelled += decision.cancelled
            halves[signal.branch_id] = (signal.state, signal.kind, signal.ref)

            predictions = self._predictions(signal)
            decision.suggestions = self._suggest(signal)
            for prediction in predictions[:MAX_PER_SIGNAL]:
                why_not = self._refuse(prediction, signal)
                if why_not:
                    decision.skipped[prediction.key] = why_not
                    self.skipped += 1
                    continue
                if self._start(prediction, signal, session):
                    decision.started.append(prediction)
                else:
                    decision.skipped[prediction.key] = "the prefetcher was full"
                    self.skipped += 1
        except Exception as exc:  # noqa: BLE001 — anticipation never costs the owner a turn
            log.warning("anticipation on %s failed: %s: %s", signal.event, type(exc).__name__, exc)
            decision.skipped.setdefault("_error", type(exc).__name__)
        self._emit(signal, decision)
        return decision

    def _predictions(self, signal: Signal) -> list[Prediction]:
        """Level 1 and level 2 as one ordered list.

        The two levels meet in two ways, and both matter under a budget that cannot run
        everything:

        * A learned transition whose read a deterministic rule ALREADY makes does not add a
          second read — it raises that read's priority and records how many observations are
          behind it. Which of Shopify's two anticipated slots gets used first is exactly what
          "begin preloading that read in future" means when four reads want three slots.
        * A learned transition whose read no rule makes for this event is a new prediction, at
          P2, level 2. That is how the layer learns to read the customer's history after the
          inbox was checked, which no deterministic rule fires on.
        """
        learned = {edge.event: edge for edge in self.learner.likely(signal.state)}
        out: list[Prediction] = []
        seen: set[str] = set()
        for prediction in rules_mod.deterministic(signal):
            if prediction.key in seen:
                continue
            seen.add(prediction.key)
            rule = rules_mod.RULES.get(prediction.why)
            edge = learned.get(rule.predicts) if rule is not None else None
            if edge is not None:
                from dataclasses import replace

                prediction = replace(
                    prediction, confidence=edge.confidence, observations=edge.observations,
                    why=f"{prediction.why}+learned",
                )
            out.append(prediction)
        for event, edge in learned.items():
            guess = rules_mod.for_event(signal, event, confidence=edge.confidence, observations=edge.observations)
            if guess is not None and guess.key not in seen:
                seen.add(guess.key)
                out.append(guess)
        # P1 before P2, and within a tier the reads the owner has actually been observed to
        # want next before the ones that are only rules.
        out.sort(key=lambda p: (0 if p.tier == P1 else 1, -p.observations, p.why))
        return out

    def _refuse(self, prediction: Prediction, signal: Signal) -> str:
        """Why this prediction must not run, in the owner's words, or empty."""
        if self.max_anticipated <= 0:
            # The off switch, and it has to be one thing: bounding the source-spending reads
            # to nothing while the Mac's own internal reads carried on would be a layer that
            # says it is off and is not. A bench half that measures "without anticipation"
            # measures without any of it.
            return "anticipation is switched off"
        if prediction.internal:
            from app.anticipation import internal

            if not internal.known(prediction.internal):
                return "there is no such internal read"
        elif not self._readable(prediction.tool):
            self.refused_writes += 1
            return "not a read"
        if prediction.memory:
            tier, key = prediction.memory
            if self.memory.get(tier, key) is not None:
                return "already held, and fresh"
        prefetcher = self.prefetcher
        if prediction.source in SPENDING_SOURCES:
            # Only source-spending reads count against these two. The Mac's own internal reads
            # spend nothing and are bounded by the prefetcher's own per-scope wall.
            spending = sum(
                prefetcher.in_flight_for(signal.scope, source=source)
                for source in SPENDING_SOURCES
            )
            if spending >= self.max_anticipated:
                return "this conversation already has as much in flight as it may"
            if prefetcher.in_flight_for(signal.scope, source=prediction.source) >= self.max_per_source:
                # The bound that matters: a source's rate belongs to the owner first.
                return f"{prediction.source} already has as much read on a hunch as it may"
        if prediction.speculative and prefetcher.in_flight_for(signal.scope, lane=P2) >= self.max_speculative:
            return "the speculative lane is full"
        from app.memory.coalesce import current as coalescer

        if coalescer().in_flight(prediction.key):
            return "the same read is already in flight"
        return ""

    def _readable(self, tool: str) -> bool:
        """A registered tool with no write and no batch. Asked of the registry at decision
        time, so a tool that gains a write later stops being predictable the moment it does."""
        if not tool:
            return False
        try:
            from app.tools import registry

            spec = registry.get(tool)
        except Exception:  # noqa: BLE001 — an unregistered tool is not readable
            return False
        return spec.write is None and spec.batch is None

    def _start(self, prediction: Prediction, signal: Signal, session: Any) -> bool:
        record = Started(
            key=prediction.key, tier=prediction.tier, tool=prediction.tool or f"internal:{prediction.internal}",
            why=prediction.why, level=prediction.level, confidence=prediction.confidence,
            observations=prediction.observations, scope=signal.scope, branch_id=signal.branch_id,
            ref=signal.ref, at=self.clock(),
        )

        async def read() -> Any:
            value = await self._read(prediction, session)
            record.outcome = "landed" if value is not None else "empty"
            if value is not None and prediction.memory:
                tier, key = prediction.memory
                self.memory.put(
                    tier, key, value, source=prediction.source, query=prediction.why,
                    provenance={
                        # The distinguishing mark, on the record that was already there: an
                        # entry the owner never asked for says so, and says why it exists.
                        "origin": PREDICTED, "why": prediction.why, "level": prediction.level,
                        "confidence": round(prediction.confidence, 3), "tier": prediction.tier,
                        "ref": signal.ref, "scope": signal.scope,
                    },
                )
            return value

        ok = self.prefetcher.start(
            # Keyed by SCOPE and key: the same read wanted by two conversations is two
            # prefetches, because one of them may be cancelled and the other not. What they
            # do share is the answer — the tiered cache is one cache, which is the point.
            f"{signal.scope}|{prediction.key}", read, branch_id=signal.branch_id,
            scope=signal.scope, lane=prediction.tier, source=prediction.source,
        )
        if not ok:
            return False
        self.started += 1
        self._history.append(record)
        from app.observability import timeline

        timeline.emit(
            "prediction", session_id=signal.session_id, branch_id=signal.branch_id or None,
            key=prediction.key, tier=prediction.tier, origin=PREDICTED, level=prediction.level,
            read=record.tool, why=prediction.why, confidence=round(prediction.confidence, 3),
            observations=prediction.observations, entity=signal.kind or None, ref=signal.ref or None,
        )
        return True

    async def _read(self, prediction: Prediction, session: Any) -> Any:
        """Make the read. Through the read scheduler for a tool — which refuses writes, paces
        the source and records the plan as PREDICTED — or through the closed internal table.

        Coalesced by the read's identity, NOT by the conversation's: two conversations that
        want the same record want one request. The scope keeps their prefetch TASKS apart, so
        one can be cancelled without the other losing its answer; the flight underneath is
        shared, and so is the tiered cache it lands in.
        """
        if prediction.internal:
            from app.anticipation import internal

            return await internal.run(prediction.internal, prediction.args)
        from app.memory.coalesce import current as coalescer
        from app.reads.scheduler import Read, ReadPlan, run_plan

        async def once() -> Any:
            plan = ReadPlan(
                [Read(prediction.key.split(":", 1)[0] or "read", prediction.tool, dict(prediction.args), source=prediction.source)],
                label=f"anticipate:{prediction.why}", origin=PREDICTED, why=prediction.why,
            )
            result = await run_plan(plan, session=session, turn_id=getattr(session, "turn_id", "") or "")
            return next(iter(result.values.values()), None)

        return await coalescer().run(prediction.key, once)

    # ------------------------------------------------------------------ level 3

    def _suggest(self, signal: Signal) -> list[dict[str, Any]]:
        """What the owner could be told, at high confidence only. A recommendation and nothing
        else: nothing in this layer acts on a suggestion, and no suggestion can name a change
        — the vocabulary it draws on is the event list, which holds only reads and moves."""
        out: list[dict[str, Any]] = []
        for edge in self.learner.likely(signal.state, threshold=SUGGEST_THRESHOLD):
            out.append({
                "next": edge.event, "confidence": round(edge.confidence, 3),
                "observations": edge.observations, "level": LEVEL_SUGGESTION,
                "why": f"after {edge.state} you usually {edge.event.replace('_', ' ')}",
            })
        self._suggestions[signal.scope] = out
        return out

    def suggestions(self, scope: str) -> list[dict[str, Any]]:
        return list(self._suggestions.get(scope) or [])

    # ------------------------------------------------------------------ standing down

    def owner_read(self, session: Any) -> int:
        """The owner asked for something, said as a session rather than as a lane.

        One line now: `stand_down` is the whole of it, and the read layer reaches that
        directly through `app/reads/budget.py::yield_to`. Kept because "the owner read
        something" is the sentence a caller has, and because a caller that has a session and
        not a scope should not have to build one.

        The half is the one this request is for — `acting_branch(session)`: the running call's
        own half (CURRENT_BRANCH), else the one the request said it was speaking to, never simply
        whichever half spoke last (round 10: the session's `acting_branch` is one field for both
        halves). Empty means one workspace, and then the whole conversation stands down.
        """
        return self.stand_down(budget.Standdown(
            scope=scope_of(session), lane=budget.SPECULATION,
            branch_id=acting_branch(session),
        ))

    def stand_down(self, ask: Any) -> int:
        """The read layer is starting work the owner is waiting on: give up what is below it.

        Registered with `app/reads/budget.py::on_yield`, so this is reached for each yielding
        lane in turn. Only SPECULATION is ours: the P2 lane is a guess about the record the
        owner has not looked at yet, and stopping it costs nothing anybody is waiting for.

        The P1 lane is deliberately NOT stopped. It is the reads about the record on screen —
        the thing he is about to ask about — and throwing them away on every question would
        take the fast half of the product away to protect the fast half of the product. It
        yields the SOURCE instead, which is what actually matters: both lanes run in the
        SPECULATION lane of `run_plan`, where the throttle caps them below Shopify's and
        Gmail's concurrency so his own read always finds a slot.
        """
        if getattr(ask, "lane", "") != budget.SPECULATION:
            return 0
        scope = str(getattr(ask, "scope", "") or "")
        branch_id = str(getattr(ask, "branch_id", "") or "")
        stopped = self.prefetcher.cancel_scope(scope, lane=P2, branch_id=branch_id)
        if not stopped:
            return 0
        self.cancelled += stopped
        for record in self._history:
            if (record.scope == scope and record.outcome == "in_flight" and record.tier == P2
                    and (not branch_id or record.branch_id == branch_id)):
                record.outcome = "cancelled"
        from app.observability import timeline

        timeline.emit(
            "anticipation_cancelled", session_id=None, cancelled=stopped,
            why="the owner asked for something",
        )
        return stopped

    def forget(self, scope: str) -> int:
        """Everything for one conversation, dropped: its speculative reads and the position of
        every half of it. For a session ending, and for a test that wants a clean slate."""
        stopped = self.prefetcher.cancel_scope(scope)
        self.cancelled += stopped
        self._last.pop(scope, None)
        self._suggestions.pop(scope, None)
        return stopped

    # ------------------------------------------------------------------ the debug view

    def explain(self, key: str = "", *, scope: str = "") -> list[dict[str, Any]]:
        """"Why was this prefetched?" — newest first, with the rule or learned transition that
        asked for it, its confidence and how many observations were behind it."""
        now = self.clock()
        rows = [
            record.public(now) for record in reversed(self._history)
            if (not key or record.key == key) and (not scope or record.scope == scope)
        ]
        return rows

    def counts(self) -> dict[str, Any]:
        return {
            "signals": self.signals, "started": self.started, "skipped": self.skipped,
            "cancelled": self.cancelled, "refused_writes": self.refused_writes,
            "max_anticipated": self.max_anticipated, "max_speculative": self.max_speculative,
            "max_per_source": self.max_per_source,
        }

    def report(self, *, scope: str = "") -> dict[str, Any]:
        """Everything the owner's debug view shows: the bounds, what has been predicted, why,
        and the learned table behind it."""
        return {
            "counts": self.counts(),
            "predictions": self.explain(scope=scope),
            "learned": self.learner.inspect(),
            "suggestions": {s: rows for s, rows in self._suggestions.items() if not scope or s == scope},
            "prefetch": self.prefetcher.counts(),
        }

    # ------------------------------------------------------------------ internals

    def _emit(self, signal: Signal, decision: Decision) -> None:
        from app.observability import timeline

        if timeline.current().active is None:
            return
        timeline.emit(
            "anticipation", session_id=signal.session_id, branch_id=signal.branch_id or None,
            event=signal.event, state=signal.state, entity=signal.kind or None, ref=signal.ref or None,
            started=[p.key for p in decision.started], levels=[p.level for p in decision.started],
            skipped=decision.skipped or None, learned=decision.learned or None,
            suggestions=len(decision.suggestions) or None, cancelled=decision.cancelled or None,
            in_flight=self.prefetcher.in_flight_for(signal.scope),
        )


def scope_of(session: Any) -> str:
    """The isolation key of a session object, in the same shape `Signal.scope` uses.

    One definition, in app/reads/budget.py, because the read layer keys its budgets and its
    stand-downs by the same thing and two copies of an isolation key is how one conversation
    comes to be served another's.
    """
    return budget.scope_of(session)


_current: Anticipator | None = None


# The registration token for the installed layer's stand-down, so installing another one
# does not leave two layers listening and a cancellation counted twice.
_YIELD_TOKEN: list[int] = []


def current() -> Anticipator:
    global _current
    if _current is None:
        _current = Anticipator()
        _register(_current)
    return _current


def install(anticipator: Anticipator | None) -> Anticipator:
    global _current
    _current = anticipator
    layer = current()
    _register(layer)
    return layer


def _register(layer: Anticipator) -> None:
    """Tell the read layer that this is something that stands down. Once: the token from the
    last registration is withdrawn first."""
    while _YIELD_TOKEN:
        budget.off_yield(_YIELD_TOKEN.pop())
    _YIELD_TOKEN.append(budget.on_yield(layer.stand_down))


def owner_read(session: Any) -> int:
    """Module-level, because the read scheduler calls it and should not know about the class."""
    if _current is None:
        return 0
    return _current.owner_read(session)


async def observe(signal: Signal, *, session: Any) -> Decision:
    """The one entry point a route uses."""
    return await current().on_signal(signal, session=session)
