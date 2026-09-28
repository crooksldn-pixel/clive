"""Recipes: the fixed reads a tap names.

A tap on the dock's Orders, a customer name typed into the order form, a code typed into the
discount form: each is a control that names exactly what it wants, and what it wants is a
read with a known shape. The command (app/commands.py) is synchronous and reads nothing, so
it names a recipe and `POST /command` runs it here — through the read scheduler and the
registered read tools, with no model on the path, because a button is not a sentence and
there is nothing to understand.

Only taps reach this. Words never do: every typed or spoken request is a model turn
(app/routes/turn.py). That is the owner's decision of 28 September 2026 — a word-matching
lane in front of the model could meet a sentence that merely mentioned an order number with a
canned lookup of that order instead of what was asked, and the lane went.

READ ONLY. `assert_read_only()` is checked at start-up and again before each run; a recipe
naming a write tool is a crash at start-up, not a surprise in production. A recipe cannot
stage, arm or commit a change.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.observability import timeline
from app.reads.scheduler import ReadPlan, ReadResult, run_plan

log = logging.getLogger("crooks.recipes")

# What a recipe's reads are worth caching as.
CACHE_NONE = "none"
CACHE_HOT = "hot"
CACHE_ENTITY = "entity"
CACHE_ANALYTICS = "analytics"
CACHE_EMAIL = "email"

# A tap that has not been answered by here has stopped being worth waiting for; the route
# says so and offers the tap again rather than holding the screen.
BUDGET_MS = 5_000


@dataclass(slots=True)
class Ctx:
    """Everything a recipe may read. Deliberately small: a recipe that needs more than this
    is not a recipe, it is a question for the model."""

    runtime: Any
    session: Any
    branch: Any
    # What the tapped control narrowed the read to — a product's words from a picker, say.
    # Identities and small values only; never an execution argument (those the Mac builds).
    slots: dict[str, Any] = field(default_factory=dict)
    # Words the control carried, when it carried any. Empty for a plain tap.
    text: str = ""
    memory: Any = None

    def entity(self, kind: str) -> str:
        """The branch's current entity, when it is of this kind."""
        found = getattr(self.branch, "entity", None) or {}
        return str(found.get("ref") or "") if found.get("kind") == kind else ""


@dataclass(slots=True)
class RecipeAnswer:
    """What a recipe produces: a sentence, the reads behind it and any cards it built itself.
    The same pieces a model turn is presented from, so the presentation layer, the turn log
    and the timeline do not need to know which one they are looking at."""

    answer: str
    calls: list[Any] = field(default_factory=list)
    # Cards this recipe built itself, for answers that are not derived from a tool result
    # (a workspace, the reply queue). Put in front of the tool cards as they stand.
    surfaces: list[Any] = field(default_factory=list)
    # Which of `calls` should become cards, when that is not all of them. `None` — the usual
    # case — means all of them. `calls` always reaches the log and the timeline whatever this
    # says: what was read is a fact about the tap, and what is worth looking at is a decision
    # about the answer.
    drawn: list[Any] | None = None
    # Set when part of what was asked could not be read. The answer says so in words.
    partial: bool = False
    # What the recipe did, for the timeline: read names, where the time went.
    trace: dict[str, Any] = field(default_factory=dict)
    # A recipe that cannot honestly answer says why here, and the tap is refused with it.
    defer: str = ""

    @property
    def deferred(self) -> bool:
        return bool(self.defer)


@dataclass(slots=True)
class Stats:
    """How a recipe has actually been doing. Measured, never assumed."""

    runs: int = 0
    hits: int = 0
    deferred: int = 0
    failures: int = 0
    total_ms: float = 0.0
    last_ms: float = 0.0
    last_success: float = 0.0

    @property
    def average_ms(self) -> float:
        return round(self.total_ms / self.runs, 1) if self.runs else 0.0

    def record(self, ms: float, *, ok: bool, deferred: bool = False, clock=time.time) -> None:
        self.runs += 1
        self.total_ms += ms
        self.last_ms = round(ms, 1)
        if deferred:
            self.deferred += 1
        elif ok:
            self.hits += 1
            self.last_success = clock()
        else:
            self.failures += 1

    def public(self) -> dict[str, Any]:
        return {"runs": self.runs, "hits": self.hits, "deferred": self.deferred, "failures": self.failures,
                "average_ms": self.average_ms, "last_ms": self.last_ms, "last_success": self.last_success or None}


@dataclass(frozen=True, slots=True)
class Recipe:
    recipe_id: str
    # What must be open before this may run at all ("order", "customer"). An unmet one
    # refuses the tap rather than reading for a record that is not there.
    required_entities: tuple[str, ...] = ()
    read_primitives: tuple[str, ...] = ()
    # Which of the reads are independent, as the plan expresses it. Documentation the tests
    # assert against, so a dependency added to `plan` without updating this is caught.
    parallel_nodes: tuple[tuple[str, ...], ...] = ()
    ui: str = "assistant"
    cache_policy: str = CACHE_NONE
    # Milliseconds this recipe should finish in.
    target_ms: int = 1000
    plan: Callable[[Ctx], ReadPlan | None] | None = None
    render: Callable[[Ctx, ReadResult], RecipeAnswer] | None = None
    stats: Stats = field(default_factory=Stats)

    def public(self) -> dict[str, Any]:
        return {
            "recipe_id": self.recipe_id, "required_entities": list(self.required_entities),
            "reads": list(self.read_primitives), "parallel_nodes": [list(g) for g in self.parallel_nodes],
            "ui": self.ui, "cache_policy": self.cache_policy, "target_ms": self.target_ms,
            "stats": self.stats.public(),
        }


RECIPES: dict[str, Recipe] = {}


def register(recipe: Recipe) -> Recipe:
    RECIPES[recipe.recipe_id] = recipe
    return recipe


def assert_read_only(recipes: dict[str, Recipe] | None = None) -> None:
    """Every read primitive named by every recipe is a read tool. Called at start-up and
    before each run: a recipe's inability to write is structural."""
    from app.tools import registry

    for recipe in (recipes or RECIPES).values():
        for tool in recipe.read_primitives:
            try:
                spec = registry.get(tool)
            except KeyError as exc:
                # Fail closed. A name the registry does not carry is a name nobody has
                # checked. This runs at start-up, with every tool module imported
                # (app/runtime.py), so an unknown name is a mistake.
                raise RuntimeError(f"recipe {recipe.recipe_id} names {tool}, which is not a registered tool") from exc
            if spec.write is not None or spec.batch is not None:
                raise RuntimeError(f"recipe {recipe.recipe_id} names the write tool {tool}; a recipe cannot write")


async def run(recipe: Recipe, ctx: Ctx) -> RecipeAnswer:
    """One recipe, end to end. Never raises: a failure defers, and the route refuses the tap
    with the reason and the same tap offered back."""
    assert_read_only({recipe.recipe_id: recipe})
    started = time.perf_counter()
    answer: RecipeAnswer
    try:
        missing = _unresolved(recipe, ctx)
        if missing:
            answer = RecipeAnswer(answer="", defer=f"{missing} is not open")
        else:
            plan = recipe.plan(ctx) if recipe.plan else None
            result = ReadResult()
            if plan is not None:
                result = await run_plan(plan, session=ctx.session, timeout_s=min(plan.timeout_s, BUDGET_MS / 1000),
                                        turn_id=getattr(ctx.session, "turn_id", ""))
            answer = recipe.render(ctx, result) if recipe.render else RecipeAnswer(answer="", defer="no renderer")
            if not answer.deferred:
                _keep(recipe, ctx, result)
                answer.trace.setdefault("reads", list(result.values))
                answer.trace.setdefault("critical_path_ms", result.critical_path_ms)
    except Exception as exc:  # noqa: BLE001 — a recipe never takes the app down
        log.warning("recipe %s failed: %s", recipe.recipe_id, exc)
        answer = RecipeAnswer(answer="", defer=f"{type(exc).__name__}")
    ms = (time.perf_counter() - started) * 1000
    recipe.stats.record(ms, ok=not answer.deferred, deferred=answer.deferred)
    answer.trace["ms"] = round(ms, 1)
    answer.trace["recipe_id"] = recipe.recipe_id
    if timeline.current().active is not None:
        timeline.emit(
            "recipe", session_id=getattr(ctx.session, "session_id", None),
            branch_id=getattr(ctx.branch, "branch_id", None), recipe_id=recipe.recipe_id,
            ms=round(ms, 1), target_ms=recipe.target_ms, ok=not answer.deferred,
            defer=answer.defer or None, partial=answer.partial or None,
            trace={k: v for k, v in answer.trace.items() if k not in ("recipe_id",)},
        )
    return answer


def _unresolved(recipe: Recipe, ctx: Ctx) -> str:
    """The first required entity that is not open on this half, by name."""
    for needed in recipe.required_entities:
        if needed in ("order", "customer") and not ctx.entity(needed):
            return f"no {needed}"
    return ""


def _keep(recipe: Recipe, ctx: Ctx, result: ReadResult) -> None:
    """What was read, into the tier its recipe says. An entity read goes under its own id, so
    a Back onto the same order does not touch Shopify."""
    from app.memory import ANALYTICS, EMAIL, ENTITY, HOT
    from app.memory import current as memory

    if recipe.cache_policy == CACHE_NONE:
        return
    tier = {CACHE_HOT: HOT, CACHE_ENTITY: ENTITY, CACHE_ANALYTICS: ANALYTICS, CACHE_EMAIL: EMAIL}.get(recipe.cache_policy)
    if tier is None:
        return
    store = memory()
    for name, value in result.values.items():
        if not isinstance(value, dict):
            continue
        key = _key_for(tier, name, value, ctx)
        if not key:
            continue
        store.put(tier, key, value, source=("gmail" if name in ("mail", "inbox") else "shopify"),
                  query=recipe.recipe_id, provenance={"recipe": recipe.recipe_id, "read": name, "ref": _ref_of(value)})


def _ref_of(value: dict[str, Any]) -> str:
    for key in ("order_id", "customer_id", "thread_id", "set_id"):
        if value.get(key):
            return str(value[key])
    return ""


def _key_for(tier: str, name: str, value: dict[str, Any], ctx: Ctx) -> str:
    from app.memory import ANALYTICS, ENTITY

    if tier == ENTITY:
        for key, kind in (("order_id", "order"), ("customer_id", "customer"), ("thread_id", "email_thread")):
            if value.get(key):
                return f"{kind}:{value[key]}"
        return ""
    if tier == ANALYTICS:
        from app.memory.store import fingerprint

        return fingerprint(name, value.get("query") or {})
    return f"{ctx.session.session_id}:{name}"
