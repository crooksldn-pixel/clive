"""The recipes themselves.

Each one is a plan (which reads, and which of them are independent) and a render (the one
sentence that answers, and the cards behind it). Between them they cover the work the
September test session showed being done over and over: an order, a customer, a period's
sales, the inbox's reply state, moving through a set, and the two questions the assistant is
asked about itself.

Nothing here writes. Nothing here calls a model.
"""

from __future__ import annotations

import re
import time
from typing import Any

from app.fastpath import correction
from app.fastpath.models import Ctx, FastAnswer
from app.fastpath.recipes import (
    CACHE_ANALYTICS,
    CACHE_EMAIL,
    CACHE_ENTITY,
    CACHE_HOT,
    CACHE_NONE,
    Recipe,
    register,
)
from app.reads.scheduler import Read, ReadPlan, ReadResult

# --------------------------------------------------------------- shared helpers

# The named periods, from the words that name them. Deliberately narrow: a period the map
# does not recognise sends the turn to Claude rather than guessing at "the last little while".
_PERIODS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("today",), "today"),
    (("yesterday",), "yesterday"),
    (("last", "week"), "last_week"),
    (("this", "week"), "this_week"),
    (("last", "month"), "last_month"),
    (("this", "month"), "this_month"),
    (("week",), "this_week"),
    (("month",), "this_month"),
)
_DAY_WINDOWS = {"7": "last_7_days", "seven": "last_7_days", "30": "last_30_days", "thirty": "last_30_days", "90": "last_90_days", "ninety": "last_90_days"}


# The periods this extractor may return: the ones `_PERIODS` and `_DAY_WINDOWS` name, which
# are the ones app/analytics/periods.py resolves. A correction to anything else — "tomorrow"
# — is a real correction about a period the read layer has no answer for, and declining is
# the honest end of it.
_RESOLVABLE = frozenset({name for _, name in _PERIODS} | set(_DAY_WINDOWS.values()))


def period_from(words: tuple[str, ...]) -> str | None:
    """The named period the request asks for, or None when it names none — or names two.

    "This week against last week" is two periods and a comparison, and which one is the
    subject is a judgement rather than a lookup. A deterministic parser that guesses there
    would answer the wrong question quickly, so it declines and Claude takes the turn.

    Two periods are NOT always two questions, though. "Today's, uh, yesterday's orders" names
    two and asks about one, and declining there sent the turn to a caller whose fallback was
    "today" — so the owner was answered for the word he had just taken back (D-8). A spoken
    correction is resolved first, and only an unresolved pair declines.
    """
    have = set(words)
    fixed = correction.corrected(words, correction.PERIOD)
    if fixed:
        return fixed if fixed in _RESOLVABLE else None
    if {"this", "last"} <= have or {"today", "yesterday"} <= have:
        return None
    if "days" in have or "day" in have:
        for word in words:
            if word in _DAY_WINDOWS:
                return _DAY_WINDOWS[word]
    for needed, name in _PERIODS:
        if set(needed) <= have:
            return name
    return None


# "By colour", "by size", "per day": a grouping the read layer already has a name for.
# Closed set, taken from app/analytics/query.py GROUPS — a word that is not one of these is
# not guessed at, and the turn goes to Claude, who can ask what was meant.
_DIMENSIONS: dict[str, str] = {
    "colour": "colour", "color": "colour", "colours": "colour", "colors": "colour",
    "size": "size", "sizes": "size", "product": "product", "products": "product",
    "variant": "variant", "variants": "variant", "type": "product_type", "types": "product_type",
    "day": "day", "daily": "day", "week": "week", "weekly": "week", "month": "month",
    "monthly": "month", "country": "country", "customer": "customer", "customers": "customer",
}


def dimension_from(words: tuple[str, ...]) -> str | None:
    """The grouping the request names after "by" or "per", when it names exactly one."""
    found: set[str] = set()
    for index, word in enumerate(words):
        if word in ("by", "per") and index + 1 < len(words):
            group = _DIMENSIONS.get(words[index + 1])
            if group:
                found.add(group)
    return next(iter(found)) if len(found) == 1 else None


def _order_of(result: ReadResult, name: str = "find") -> dict[str, Any] | None:
    """The one order a search found, when it found exactly one."""
    found = result.values.get(name)
    orders = found.get("orders") if isinstance(found, dict) else None
    if isinstance(orders, list) and len(orders) == 1 and isinstance(orders[0], dict):
        return orders[0]
    return None


def _hedge(body: dict[str, Any]) -> str:
    """What the read itself says about its own completeness, added to the answer rather than
    left in the payload for nobody. The order cache says `complete: False` with a `note`
    while it is still filling — which is exactly the first questions after a restart."""
    if not isinstance(body, dict) or body.get("complete") is not False:
        return ""
    note = " ".join(str(body.get("note") or "").split())
    return f" {note}" if note else " CROOKS is still reading recent orders, so this is what it holds so far."


def _how_many(body: dict[str, Any], shown: int) -> str:
    """How many there are, not how many fitted. A limit of 25 against 61 matching orders was
    being spoken as "25 orders are unfulfilled"."""
    total = body.get("row_count")
    if isinstance(total, int) and total > shown:
        return f"{total} (showing {shown})"
    return str(shown)


def _period_words(body: dict[str, Any], fallback: str = "the period") -> str:
    """The period as a person says it. The read layer's own label first; its slug, spelled
    out, second — "last_30_days" was being read aloud with the underscores in it."""
    period = body.get("period") if isinstance(body.get("period"), dict) else {}
    label = str(period.get("label") or "").strip()
    if label:
        return label
    slug = str(period.get("name") or period.get("period") or "").strip()
    return slug.replace("_", " ") if slug else fallback


# What the Mac's own reads call money. Shopify's shape is already a string with its currency
# in it ("45.00 GBP"); the read layer's is a bare number with the currency beside it. One
# answer must not contain both shapes.
_SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€"}


def _money(value: Any, currency: str = "GBP") -> str:
    if isinstance(value, str):
        parts = value.split()
        if len(parts) == 2 and parts[1].isalpha():
            value, currency = parts[0], parts[1].upper()
    try:
        return f"{_SYMBOL.get(currency.upper(), currency.upper() + ' ')}{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value or "")


def _order_line(order: dict[str, Any]) -> str:
    """An order in a sentence: who, how much, and where it has got to."""
    number = str(order.get("order_number") or "").lstrip("#")
    who = str((order.get("customer") or {}).get("name") or order.get("customer_name") or "").strip()
    total = _money(order.get("total") or order.get("total_price"))
    state = str(order.get("fulfillment_status") or order.get("fulfillment") or "").replace("_", " ").lower()
    bits = [f"{number}" if number else "That order"]
    if who:
        bits.append(f"is {who}'s")
    if total:
        bits.append(f"for {total}")
    line = " ".join(bits)
    if state and state not in ("null", "none"):
        line += f", {state}"
    return line + "."


def _remember(ctx: Ctx, kind: str, ref: str, label: str, *, tab: str = "") -> None:
    ctx.branch.visit(kind, ref, label, tab=tab)
    ctx.session.remember_context(kind, label, ref)
    ctx.session.set_focus(kind, ref)


# ------------------------------------------------------------ capability truth


def _capability_plan(ctx: Ctx) -> ReadPlan | None:      # noqa: ARG001 — no source is read
    return None


def _capability_summary(ctx: Ctx, result: ReadResult) -> FastAnswer:   # noqa: ARG001
    # Imported by name, not as a module: app/capabilities/__init__.py re-exports `delta` and
    # `build` as functions, so `from app.capabilities import delta` gets the function and
    # `delta_mod.spoken_delta` is an AttributeError at the worst possible moment.
    from app.capabilities.manifest import build as build_manifest
    from app.capabilities.manifest import spoken_summary
    from app.capabilities.surface import build_surface

    manifest = _current_manifest(ctx, build_manifest)
    spoken = spoken_summary(manifest)
    # The sentence and the card are built from the same manifest, so the screen cannot list a
    # capability the spoken answer denies. Thirty capabilities are a list, not a paragraph.
    surface = build_surface(manifest, spoken=spoken, states=_capability_states(ctx))
    return FastAnswer(answer=spoken, surfaces=[surface],
                      trace={"source": "manifest", "fingerprint": manifest.get("fingerprint")})


def _current_manifest(ctx: Ctx, build_manifest) -> dict[str, Any]:
    """What this build can do, as it stands now.

    The runtime's manifest is built once at boot, and it lists no changes at all while writes
    are off — so a manifest from a boot with writes off would tell the owner this Mac cannot
    change anything, minutes after changes had been switched on. Rebuilt whenever it disagrees
    with the setting that holds now. Never assumed on: saying "I can change things" while they
    are off is the worst answer available.
    """
    settings = getattr(ctx.runtime, "settings", None)
    writes_on = bool(getattr(settings, "writes_enabled", False))
    manifest = getattr(ctx.runtime, "manifest", None)
    if not manifest or bool(manifest.get("writes_enabled")) != writes_on:
        manifest = build_manifest(build_id=getattr(ctx.runtime, "build", ""), writes_enabled=writes_on)
    return manifest


def _capability_states(ctx: Ctx) -> dict[str, dict[str, Any]] | None:
    """The per-change table /health computed on its last run, when there is one.

    Read from the runtime's cache rather than recomputed: working out whether a change is
    possible asks Shopify and Google for their scopes, and a question about what the assistant
    can do must not become two network round trips. Absent, every change reads as "unknown",
    which is the honest answer when nobody has checked.
    """
    cached = getattr(ctx.runtime, "capability_states", None)
    return cached if isinstance(cached, dict) and cached else None


def _capability_delta(ctx: Ctx, result: ReadResult) -> FastAnswer:     # noqa: ARG001
    from app.capabilities.delta import delta as compute_delta
    from app.capabilities.delta import spoken_delta
    from app.capabilities.surface import build_surface

    record = getattr(ctx.runtime, "capability_record", None)
    if not record:
        # No previous build to compare against — a fresh Mac, or a log directory that has
        # been cleared. "What can you do now?" is still a question this machine can answer
        # from its own registry, so it answers it, rather than handing a question about
        # itself to the model and drawing nothing.
        return _capability_summary(ctx, result)
    from app.capabilities.manifest import build as build_manifest

    spoken = spoken_delta(record)
    moved = compute_delta(record)
    # The card lists what this build can do NOW; the record says only what moved since the
    # last one. Building the card from the record instead described the build that was
    # recorded, which is a different question from the one that was asked.
    surface = build_surface(
        _current_manifest(ctx, build_manifest), spoken=spoken, states=_capability_states(ctx),
        changed={
            "since": moved.get("previous_build") or "",
            "added": [f"{e.get('name')}: {e.get('what')}" for e in (moved.get("added") or [])],
            "gone": [f"{e.get('name')}: {e.get('what')}" for e in (moved.get("removed") or [])],
        },
    )
    return FastAnswer(answer=spoken, surfaces=[surface],
                      trace={"source": "capability delta", "fingerprint": (record.get("current") or {}).get("fingerprint")})


register(Recipe(
    recipe_id="capability_summary", intent_family="capability_summary",
    read_primitives=(), ui="capability", cache_policy=CACHE_NONE, min_confidence=0.7,
    target_ms=50, plan=_capability_plan, render=_capability_summary,
))
register(Recipe(
    recipe_id="capability_delta", intent_family="capability_delta",
    read_primitives=(), ui="capability", cache_policy=CACHE_NONE, min_confidence=0.7,
    target_ms=50, plan=_capability_plan, render=_capability_delta,
))


# ------------------------------------------------------------------ navigation


def _nav_plan(ctx: Ctx) -> ReadPlan | None:
    """Read the record the trail just landed on, when the Mac no longer holds it.

    The runner has already moved the trail (app/fastpath/runner.py:_advance), so `ctx.moved`
    says where. Memory usually has it — going back to something just looked at is not a new
    question — and then this reads nothing at all. When memory has dropped it, the alternative
    is announcing a move and leaving the screen where it was.
    """
    from app.commands import _SET_KIND, MEMBER_READ, replay
    from app.commands import Ctx as CommandCtx

    moved = getattr(ctx, "moved", None) or {}
    kind, ref = str(moved.get("kind") or ""), str(moved.get("ref") or "")
    if not moved.get("landed") or not ref:
        return None
    entry = ctx.branch.here
    if entry is not None and entry.is_workspace:
        # A listing or a landing. Its own cards come back when it kept them; when it did not —
        # a draw that failed, a stop whose cards have been trimmed — the PLACE is read again by
        # its own recipe rather than announced over an empty screen.
        return None if entry.ui else _landing_plan(ctx, entry.area)
    if replay(CommandCtx(ctx.runtime, ctx.session, ctx.branch), kind, ref):
        return None                      # held: nothing to read
    tool, argument, _ = MEMBER_READ.get(_SET_KIND.get(kind, ""), ("", "", ""))
    if not tool:
        return None
    return ReadPlan([Read("landed", tool, {argument: ref},
                          source="gmail" if tool.startswith("gmail_") else "shopify")],
                    label=f"navigation:{moved.get('direction') or 'back'}")


def _navigated(ctx: Ctx, result: ReadResult, *, words) -> FastAnswer:
    """The sentence and the cards for a trail move the runner already made.

    The move is `app/commands.py:move_nav` — the same function a tap reaches, so there is one
    implementation of Back. What is left here is drawing the workspace it landed on: the cards
    kept with a listing, the record from memory when the Mac holds it, or the read the plan
    made when it does not.
    """
    from app.commands import AsUi, replay
    from app.commands import Ctx as CommandCtx

    moved = getattr(ctx, "moved", None) or {}
    if not moved.get("landed"):
        return FastAnswer(answer=words(None), trace={"nav": moved.get("direction"), "landed": False})
    kind, ref, label = str(moved.get("kind") or ""), str(moved.get("ref") or ""), str(moved.get("label") or "")
    entry = ctx.branch.here
    if entry is not None and entry.is_workspace:
        # A listing cannot be replayed from the entity cache — there is no `list_id` in memory
        # — so its own cards come back.
        if entry.ui:
            return FastAnswer(answer=words(label), surfaces=[AsUi(u) for u in entry.ui],
                              trace={"nav": moved.get("direction"), "landed": True, "ref": ref,
                                     "workspace": entry.kind, "drawn": True})
        # None kept, so the plan read the place again; draw it with its own recipe.
        recipe = _landing_recipe(entry.area)
        if recipe is not None and recipe.render is not None and result.values:
            drawn = recipe.render(ctx, result)
            if not drawn.deferred:
                drawn.trace = {**(drawn.trace or {}), "nav": moved.get("direction"), "landing": recipe.recipe_id}
                return drawn
        return FastAnswer(answer=words(label),
                          trace={"nav": moved.get("direction"), "landed": True, "ref": ref,
                                 "workspace": entry.kind, "drawn": False})
    calls = list(result.calls) or replay(CommandCtx(ctx.runtime, ctx.session, ctx.branch), kind, ref)
    return FastAnswer(answer=words(label), calls=calls, partial=result.partial,
                      trace={"nav": moved.get("direction"), "landed": True, "ref": ref,
                             "drawn": bool(calls), "read": bool(result.calls)})


def _nav_back(ctx: Ctx, result: ReadResult) -> FastAnswer:
    return _navigated(ctx, result, words=lambda label: (
        f"Back to {label}." if label else "That is as far back as this conversation goes."))


def _landing_recipe(area: str):
    """The recipe that draws one of the dock's places.

    The table belongs to the landings themselves (app/families/landings.py) and is handed down
    to `app/commands.py` so that a command need not import a family. This reads it from there
    rather than keeping a second copy that could disagree.
    """
    from app.commands import LANDING_FOR
    from app.fastpath.recipes import RECIPES

    return RECIPES.get(LANDING_FOR.get(str(area or ""), ""))


def _landing_plan(ctx: Ctx, area: str) -> ReadPlan | None:
    recipe = _landing_recipe(area)
    return recipe.plan(ctx) if recipe is not None and recipe.plan is not None else None


def _home_recipe(ctx: Ctx):
    """The landing recipe this half's Home resolves to. One decision, shared with the tap."""
    from app.commands import home_target

    area, recipe_id = home_target(ctx.branch)
    return _landing_recipe(area) if recipe_id else None


def _home_plan(ctx: Ctx) -> ReadPlan | None:
    """"Back to the assistant", said. It is the dock's landing for this half's area and not a
    walk back along the trail: the same place the Assistant chip reaches, read by the same
    recipe, so the two cannot show different screens."""
    recipe = _home_recipe(ctx)
    return recipe.plan(ctx) if recipe is not None and recipe.plan is not None else None


def _nav_home(ctx: Ctx, result: ReadResult) -> FastAnswer:
    recipe = _home_recipe(ctx)
    if recipe is None or recipe.render is None:
        return FastAnswer(answer="", defer="this half has no landing to go back to")
    answer = recipe.render(ctx, result)
    if not answer.deferred:
        answer.trace = {**(answer.trace or {}), "nav": "home", "landing": recipe.recipe_id}
    return answer


def _replay(ctx: Ctx, entry) -> list[Any]:
    """A card rebuilt from what the Mac still holds, rather than read again. Nothing is shown
    that memory cannot supply; a stop whose entry has gone leaves the sentence on its own."""
    from app.memory import ENTITY
    from app.memory import current as memory
    from app.providers.base import ToolCall

    held = memory().get(ENTITY, f"{entry.kind}:{entry.ref}", allow_stale=True)
    if held is None:
        return []
    tool = {"order": "shopify_order_detail", "customer": "shopify_customer_history", "email_thread": "gmail_read_thread"}.get(entry.kind, "")
    if not tool:
        return []
    return [ToolCall(name=tool, args={f"{entry.kind}_id": entry.ref}, ok=True, result=held.value)]


# Back reads the record it landed on when memory has dropped it, and reads the PLACE again
# when the stop it landed on is a listing that kept no cards. Both sets of primitives are
# declared, because `assert_read_only` is checked against what a recipe can actually cause.
register(Recipe(recipe_id="navigation_back", intent_family="navigation_back", ui="context_stack",
                read_primitives=("shopify_order_detail", "shopify_customer_history", "gmail_read_thread",
                                 "commerce_query", "email_query", "gmail_search",
                                 "commerce_aggregate", "inventory_query"),
                cache_policy=CACHE_HOT, min_confidence=0.75, target_ms=100, plan=_nav_plan, render=_nav_back))
# Home reads what its landing reads, which is why its primitives are the union of the four
# landings' (app/families/landings.py) rather than none: it delegates, and `assert_read_only`
# is checked against what it can actually cause.
register(Recipe(recipe_id="navigation_home", intent_family="navigation_home", ui="order_list",
                read_primitives=("commerce_query", "email_query", "gmail_search",
                                 "commerce_aggregate", "inventory_query"),
                cache_policy=CACHE_HOT, min_confidence=0.75, target_ms=2500,
                plan=_home_plan, render=_nav_home))


# -------------------------------------------------------------- working sets

def _member_plan(ctx: Ctx) -> ReadPlan | None:
    """The read for wherever the cursor now landed. One read, of one member.

    The runner has already moved the cursor (`app/fastpath/runner.py:_advance`, which calls the
    same `move_cursor` a tap reaches), so `ctx.moved` says which member this is — and says when
    the move was refused. That refusal is the point: this used to clamp the cursor into range
    with `min(max(...))`, which turned "next" at the end of a list into another read of the
    last member, announced as though it had moved. At the ends there is nothing to read.
    """
    from app.commands import MEMBER_READ

    moved = getattr(ctx, "moved", None) or {}
    if not moved.get("moved"):
        return None
    tool, arg, _ = MEMBER_READ.get(str(moved.get("set_kind") or ""), ("", "", ""))
    if not tool:
        return None
    return ReadPlan([Read("member", tool, {arg: str(moved["ref"])},
                          source="gmail" if tool.startswith("gmail_") else "shopify")],
                    label=f"workflow:{moved.get('set_kind')}")


def _member_answer(ctx: Ctx, result: ReadResult) -> FastAnswer:
    """What the cursor landed on — or that it did not move.

    The end-of-list sentences are `app/commands.BOUND_WORDS`, the same ones a tapped Next
    speaks, so the two ways of saying "next" agree about where a list ends.
    """
    from app.commands import BOUND_WORDS

    workflow = ctx.branch.workflow
    moved = getattr(ctx, "moved", None) or {}
    if not moved.get("moved"):
        code = str(moved.get("code") or "")
        if code in BOUND_WORDS:
            return FastAnswer(answer=BOUND_WORDS[code],
                              trace={"cursor": moved.get("cursor"), "bound": code, "moved": False})
        return FastAnswer(answer="", defer="the set this was working through has gone")
    ref, label = str(moved["ref"]), str(moved.get("label") or moved["ref"])
    set_kind, kind = str(moved.get("set_kind") or ""), str(moved.get("kind") or "order")
    where = f"{workflow.position} of {workflow.total}" if workflow else ""
    body = result.values.get("member")
    if isinstance(body, dict):
        _remember(ctx, kind, ref, label)
        if set_kind == "orders":
            head = _order_line(body)
        elif set_kind == "customers":
            head = _customer_line(body, label)
        else:
            head = f"{body.get('subject') or label}."
        return FastAnswer(answer=f"{head} {where}.", calls=list(result.calls), partial=result.partial,
                          trace={"set_id": moved.get("set_id"), "cursor": moved.get("cursor"), "ref": ref})
    return FastAnswer(answer=f"{label}. {where}. I could not read the rest of it just now.",
                      partial=True,
                      trace={"set_id": moved.get("set_id"), "cursor": moved.get("cursor"), "ref": ref, "read": "failed"})


def _next(ctx: Ctx, result: ReadResult) -> FastAnswer:
    return _member_answer(ctx, result)


def _previous(ctx: Ctx, result: ReadResult) -> FastAnswer:
    return _member_answer(ctx, result)


register(Recipe(
    recipe_id="working_set_next", intent_family="working_set_next", required_entities=("workflow",),
    read_primitives=("shopify_order_detail", "shopify_customer_history", "gmail_read_thread"),
    ui="order", cache_policy=CACHE_ENTITY, min_confidence=0.75, target_ms=750,
    plan=_member_plan, render=_next,
))
register(Recipe(
    recipe_id="working_set_previous", intent_family="working_set_previous", required_entities=("workflow",),
    read_primitives=("shopify_order_detail", "shopify_customer_history", "gmail_read_thread"),
    ui="order", cache_policy=CACHE_ENTITY, min_confidence=0.75, target_ms=750,
    plan=_member_plan, render=_previous,
))


# ------------------------------------------------------------------- an order


def _order_plan(ctx: Ctx) -> ReadPlan | None:
    """Find the order, then read it in full. The second read depends on the first, so the
    plan is two waves rather than one — and says so."""
    number = ctx.order_number
    known = ctx.entity("order")
    if number:
        return ReadPlan([
            Read("find", "shopify_find_order", {"query": number}, source="shopify", cost=30.0),
            Read("detail", "shopify_order_detail", _detail_args, source="shopify", after=("find",), cost=90.0),
        ], label="order_lookup")
    if known and not _names_another_order(ctx, known):
        return ReadPlan([Read("detail", "shopify_order_detail", {"order_id": known}, source="shopify", cost=90.0)], label="order_lookup")
    return None


def _detail_args(values: dict[str, Any]) -> dict[str, Any] | None:
    found = values.get("find")
    orders = found.get("orders") if isinstance(found, dict) else None
    if isinstance(orders, list) and len(orders) == 1 and isinstance(orders[0], dict) and orders[0].get("order_id"):
        return {"order_id": str(orders[0]["order_id"])}
    return None


def _order_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    detail = result.values.get("detail")
    if not isinstance(detail, dict):
        found = _order_of(result)
        if found is None:
            return FastAnswer(answer="", defer="the order did not resolve to exactly one record")
        _remember(ctx, "order", str(found.get("order_id") or ""), str(found.get("order_number") or ""))
        return FastAnswer(answer=_order_line(found), calls=list(result.calls), partial=True, trace={"detail": "not read"})
    _remember(ctx, "order", str(detail.get("order_id") or ""), str(detail.get("order_number") or ""), tab="overview")
    items = detail.get("items") or []
    line = _order_line(detail)
    if items:
        first = items[0] if isinstance(items[0], dict) else {}
        more = f" and {len(items) - 1} more" if len(items) > 1 else ""
        line += f" {first.get('quantity') or 1} × {first.get('title') or 'item'}{more}."
    return FastAnswer(answer=line, calls=list(result.calls), partial=result.partial, trace={"order_id": detail.get("order_id")})


def _status_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    detail = result.values.get("detail")
    if not isinstance(detail, dict):
        return FastAnswer(answer="", defer="the order was not read")
    _remember(ctx, "order", str(detail.get("order_id") or ""), str(detail.get("order_number") or ""), tab="shipping")
    number = str(detail.get("order_number") or "").lstrip("#")
    fulfilments = [f for f in (detail.get("fulfillments") or []) if isinstance(f, dict)]
    state = str(detail.get("fulfillment_status") or "").replace("_", " ").lower() or "not fulfilled"
    if fulfilments:
        first = fulfilments[0]
        carrier = str(first.get("company") or first.get("carrier") or "").strip()
        tracking = str(first.get("tracking_number") or "").strip()
        words = f"{number} went out{f' with {carrier}' if carrier else ''}"
        if tracking:
            words += f", tracking {tracking}"
        return FastAnswer(answer=words + ".", calls=list(result.calls), trace={"order_id": detail.get("order_id"), "state": state})
    age = detail.get("age_days")
    tail = f" It was placed {int(age)} days ago." if isinstance(age, (int, float)) and age else ""
    return FastAnswer(answer=f"{number} is {state}; nothing has shipped yet.{tail}", calls=list(result.calls), trace={"order_id": detail.get("order_id"), "state": state})


def _address_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    """The full shipping address, because the owner asked for it. The card carries it; the
    spoken line carries it too, which is the point of the question. Neither reaches the
    timeline: dispatch writes a result's shape, never its contents."""
    detail = result.values.get("detail")
    if not isinstance(detail, dict):
        return FastAnswer(answer="", defer="the order was not read")
    address = detail.get("shipping_address")
    if not isinstance(address, dict):
        return FastAnswer(answer=f"{str(detail.get('order_number') or 'That order').lstrip('#')} has no shipping address on it.",
                          calls=list(result.calls), trace={"address": "none"})
    _remember(ctx, "order", str(detail.get("order_id") or ""), str(detail.get("order_number") or ""), tab="shipping")
    ctx.session.remember_pii(*[str(v) for v in address.get("lines") or []], str(address.get("zip") or ""), str(address.get("name") or ""))
    parts = [*(address.get("lines") or []), address.get("city"), address.get("province"), address.get("zip"), address.get("country")]
    written = ", ".join(str(p).strip() for p in parts if str(p or "").strip())
    who = str(address.get("name") or "").strip()
    number = str(detail.get("order_number") or "").lstrip("#")
    return FastAnswer(answer=f"{number} ships to {who + ', ' if who else ''}{written}.", calls=list(result.calls),
                      trace={"order_id": detail.get("order_id"), "address": "read"})


register(Recipe(
    recipe_id="order_lookup", intent_family="order_lookup", required_entities=("order",),
    read_primitives=("shopify_find_order", "shopify_order_detail"),
    parallel_nodes=(("find",), ("detail",)), ui="order", cache_policy=CACHE_ENTITY,
    min_confidence=0.75, target_ms=1000, plan=_order_plan, render=_order_render,
))
register(Recipe(
    recipe_id="order_status_lookup", intent_family="order_status_lookup", required_entities=("order",),
    read_primitives=("shopify_find_order", "shopify_order_detail"),
    parallel_nodes=(("find",), ("detail",)), ui="order", cache_policy=CACHE_ENTITY,
    min_confidence=0.75, target_ms=1000, plan=_order_plan, render=_status_render,
))
register(Recipe(
    recipe_id="order_address_lookup", intent_family="order_address_lookup", required_entities=("order",),
    read_primitives=("shopify_find_order", "shopify_order_detail"),
    parallel_nodes=(("find",), ("detail",)), ui="order", cache_policy=CACHE_ENTITY,
    min_confidence=0.72, target_ms=1000, plan=_order_plan, render=_address_render,
))


# ----------------------------------------------------------------- a customer


def _order_list_plan(ctx: Ctx) -> ReadPlan | None:
    """The orders in a period, as a list to work through.

    Through the read layer rather than `shopify_list_orders`, for one reason: `commerce_query`
    publishes a working set, and a set is what makes the list navigable. "Next", "the third
    one" and a tap on the third row are then the same cursor on the same members. A plain
    listing draws the same card and leaves the owner with nothing to walk.
    """
    return ReadPlan([Read("listing", "commerce_query", {
        "entity": "orders", "period": period_from(ctx.intent.signals.words) or "today",
        "sort": [{"metric": "placed_at", "direction": "desc"}], "limit": 25,
        "title": "Orders",
    }, source="shopify", cost=120.0)], label="order_list_period")


def _order_list_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    """A sentence about the shape of the list, and the list itself on screen.

    The sentence deliberately does not read the orders out. Seven orders spoken is a minute of
    talking nobody listens to; "seven today, three still to go out" is what a person says, and
    the rows are there to be looked at and tapped.
    """
    body = result.values.get("listing")
    if not isinstance(body, dict):
        return FastAnswer(answer="", defer="the order list did not come back")
    rows = [r for r in (body.get("rows") or []) if isinstance(r, dict)]
    period = _period_words(body, fallback="in that period")
    if not rows:
        return FastAnswer(answer=f"No orders {period}." + _hedge(body), calls=list(result.calls), trace={"rows": 0})
    # The set the cursor walks, so "next", "the third one" and a tap on the third row are one
    # operation on one list.
    _open_workflow(ctx, body, kind="orders", operation="review", set_id=_set_id_of(body))
    unfulfilled = sum(1 for r in rows if "unfulfilled" in str(r.get("fulfillment") or r.get("status") or "").lower())
    words = f"{_how_many(body, len(rows))} order{'s' if len(rows) != 1 else ''} {period}"
    if unfulfilled:
        words += f"; {unfulfilled} still to go out"
    return FastAnswer(answer=words + "." + _hedge(body), calls=list(result.calls), partial=result.partial,
                      trace={"rows": len(rows), "unfulfilled": unfulfilled, "set_id": _set_id_of(body)})


register(Recipe(
    recipe_id="order_list_period", intent_family="order_list_period",
    read_primitives=("commerce_query",), parallel_nodes=(("listing",),), ui="order_list",
    cache_policy=CACHE_ANALYTICS, min_confidence=0.74, target_ms=1200,
    plan=_order_list_plan, render=_order_list_render,
))
# Showing the open order again is the same procedure as looking it up: `_order_plan` already
# falls back to the branch's current entity when no number was said, which is exactly this
# case. A second recipe rather than a second condition, because recipe_for maps one family to
# one recipe and the two families are genuinely different questions.
_DIGITS = re.compile(r"\b(\d{3,6})\b")


def _names_another_order(ctx: Ctx, known: str) -> bool:
    """Whether the sentence names a number that is not the order currently open.

    This is the guard that stands between "tell me about it" and "tell me about 1936" when
    1938 is on screen. `spoken_order_numbers` deliberately will not extract a bare number — a
    bare 2025 is a year, "over 500" is money — so a sentence with a bare number in it reaches
    the recipes with no order number at all, and every recipe that falls back to the open
    record then answers confidently about the wrong order: the right shape of answer, the
    wrong customer's address, spoken aloud and remembered as PII.

    So: digits in the sentence that match neither the open order's label nor its ref mean this
    question is not about what is on screen. Defer, and let a lane that can look 1936 up do it.
    """
    said = {m for m in _DIGITS.findall(ctx.text or "")}
    if not said:
        return False
    entity = getattr(ctx.branch, "entity", None) or {}
    mine = set(_DIGITS.findall(str(entity.get("label") or ""))) | set(_DIGITS.findall(known))
    return not (said & mine)


def _reopen_plan(ctx: Ctx) -> ReadPlan | None:
    """Show the open order again — but only if it IS the order being asked about.

    "Show it again" means the record on screen. "Show me 1912 again" names a different one and
    is not a re-render, so this defers and the turn goes to a path that can look 1912 up.
    """
    known = ctx.entity("order")
    if not known or _names_another_order(ctx, known):
        return None
    return ReadPlan([Read("detail", "shopify_order_detail", {"order_id": known},
                          source="shopify", cost=90.0)], label="order_reopen")


register(Recipe(
    recipe_id="order_reopen", intent_family="order_reopen", required_entities=("order",),
    read_primitives=("shopify_order_detail",), parallel_nodes=(("detail",),), ui="order",
    cache_policy=CACHE_ENTITY, min_confidence=0.74, target_ms=700,
    plan=_reopen_plan, render=_order_render,
))


def _customer_plan(ctx: Ctx) -> ReadPlan | None:
    """A name this branch has already resolved needs no search: read the history straight."""
    said = ctx.intent.slots.get("name") or ""
    known = ctx.branch.resolve(said) if said else None
    if known and known.get("kind") == "customer":
        return ReadPlan([Read("history", "shopify_customer_history", {"customer_id": known["ref"]}, source="shopify", cost=60.0)], label="customer_lookup")
    if said:
        return ReadPlan([
            Read("find", "shopify_find_customer", {"query": said}, source="shopify", cost=30.0),
            Read("history", "shopify_customer_history", _history_args, source="shopify", after=("find",), cost=60.0),
        ], label="customer_lookup")
    return None


def _history_args(values: dict[str, Any]) -> dict[str, Any] | None:
    found = values.get("find")
    people = found.get("customers") if isinstance(found, dict) else None
    if isinstance(people, list) and len(people) == 1 and isinstance(people[0], dict) and people[0].get("customer_id"):
        return {"customer_id": str(people[0]["customer_id"])}
    return None


def _customer_line(history: dict[str, Any], fallback: str = "") -> str:
    """A customer in a sentence, from the shape `shape_customer_history` actually returns:
    `orders` is a COUNT (an int, or None when Shopify did not say) and `spent` is already
    money as a string. Reading them as a list and a number produced "0 orders, in total" for
    every customer walked with "Next" — a confident sentence that was simply false."""
    name = str(history.get("name") or fallback or "They").strip()
    count = history.get("orders")
    spent = str(history.get("spent") or "").strip()
    if not isinstance(count, int):
        # Shopify did not give a count. Say what is known and nothing more.
        return f"{name}." if not spent else f"{name}, {spent} spent with us."
    orders = "no orders yet" if count == 0 else f"{count} order{'' if count == 1 else 's'}"
    return f"{name}: {orders}" + (f", {spent} in total." if spent else ".")


def _customer_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    history = result.values.get("history")
    if not isinstance(history, dict):
        return FastAnswer(answer="", defer="the customer did not resolve to exactly one record")
    name = str(history.get("name") or ctx.intent.slots.get("name") or "").strip()
    ref = str(history.get("customer_id") or "")
    # D-14: which record this answer is about, when it is not the one on screen. The failing
    # turn said "[customer B]: 1 order, 60.0 GBP in total" over a question about customer A,
    # and nothing in the sentence said whose history it was reading. Naming the person the
    # words named — and saying plainly when the screen was showing somebody else — is the
    # difference between an answer and a false fact.
    moved = _switched_record(ctx, ref)
    _remember(ctx, "customer", ref, name, tab="orders")
    if ctx.intent.slots.get("name"):
        ctx.branch.learn(ctx.intent.slots["name"], "customer", ref, name)
    recent = [o for o in (history.get("recent") or []) if isinstance(o, dict)]
    last = recent[0] if recent else {}
    tail = ""
    if last:
        tail = f" The last was {str(last.get('order_number') or '').lstrip('#')}"
        if last.get("total"):
            tail += f", {_money(last['total'])}"
        if last.get("placed_at"):
            tail += f" on {str(last['placed_at'])[:10]}"
        tail += "."
    return FastAnswer(answer=_customer_line(history, name) + tail + moved, calls=list(result.calls),
                      partial=result.partial, trace={"customer_id": ref, "switched": bool(moved)})


def _switched_record(ctx: Ctx, ref: str) -> str:
    """One clause, when the record this answer is about is not the one that was on screen.

    D-14's rule said out loud. The words named somebody; the screen was showing somebody
    else; the answer is about the person the words named, and it says so rather than leaving
    the owner to notice that the name changed.
    """
    if not ref:
        return ""
    held = getattr(ctx.branch, "entity", None) or {}
    if not held.get("ref") or str(held.get("ref")) == str(ref):
        return ""
    label = str(held.get("label") or "").strip()
    where = f" (you were on {label})" if label else ""
    return f" That is who you named{where}."


def _customer_history_plan(ctx: Ctx) -> ReadPlan | None:
    """"What else has this customer ordered?" — the person is whoever the open record belongs
    to, so nothing has to be resolved from the words.

    Two shapes. With a customer open it is one read. With an ORDER open the customer is not
    known until the order has been read, so it is two waves — the same find-then-detail
    pattern the order recipes use, and the scheduler runs them in dependency order.

    And ONE refusal, which is D-14. If the request NAMES a person, this plan must not run at
    all. The live session asked what one customer had ordered in his lifetime; this plan read
    the order that happened to be in focus, read that order's customer, and the turn spoke a
    different person's order history as a statement of fact. The router blocks the sentence
    now (`names_a_person`), and this is the same refusal said again where the read is actually
    issued: a named person outranks the record in focus, always, and the shape that got it
    wrong — order_detail on a held order driving a customer-history answer — cannot recur.
    """
    if ctx.intent.slots.get("name"):
        return None
    customer = ctx.entity("customer")
    if customer:
        return ReadPlan([Read("history", "shopify_customer_history", {"customer_id": customer},
                              source="shopify", cost=60.0)], label="customer_history")
    order = ctx.entity("order")
    if order:
        return ReadPlan([
            Read("detail", "shopify_order_detail", {"order_id": order}, source="shopify", cost=90.0),
            Read("history", "shopify_customer_history", _history_from_order, source="shopify", after=("detail",), cost=60.0),
        ], label="customer_history")
    return None


def _history_from_order(values: dict[str, Any]) -> dict[str, Any] | None:
    detail = values.get("detail")
    customer = detail.get("customer") if isinstance(detail, dict) else None
    ref = customer.get("customer_id") if isinstance(customer, dict) else None
    return {"customer_id": str(ref)} if ref else None


def _customer_history_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    """The same card and the same sentence as a lookup by name — this is the same question
    asked a different way, and answering it differently would be a second implementation of
    one thing. What differs is only how the customer was found.

    And that difference is worth one line here. Reached from an order, the plan reads the order
    first, purely to learn whose it is — so `present()` was handed two reads and drew two
    cards, putting the order the owner is already looking at back on screen ABOVE the answer,
    with the customer card starting 800 pixels down. Only the history is drawn; the order read
    still reaches the log.
    """
    answer = _customer_render(ctx, result)
    history = [c for c in answer.calls if getattr(c, "name", "") == "shopify_customer_history"]
    if history and len(history) != len(answer.calls):
        answer.drawn = history
    return answer


register(Recipe(
    recipe_id="customer_history_lookup", intent_family="customer_history_lookup",
    # Deliberately none. `required_entities` means ALL of them (app/fastpath/runner.py), and
    # this recipe needs EITHER a customer or an order to work from — declaring both made it
    # defer every time only an order was open, which is the commonest way to ask it. The plan
    # returns None when there is nothing to work from, and a plan of None is already a defer.
    required_entities=(),
    read_primitives=("shopify_order_detail", "shopify_customer_history"),
    parallel_nodes=(("detail",), ("history",)), ui="customer", cache_policy=CACHE_ENTITY,
    min_confidence=0.74, target_ms=1500, plan=_customer_history_plan, render=_customer_history_render,
))


register(Recipe(
    recipe_id="customer_purchase_lookup", intent_family="customer_purchase_lookup", required_entities=("customer",),
    read_primitives=("shopify_find_customer", "shopify_customer_history"),
    parallel_nodes=(("find",), ("history",)), ui="customer", cache_policy=CACHE_ENTITY,
    min_confidence=0.72, target_ms=1500, plan=_customer_plan, render=_customer_render,
))


# ----------------------------------------------------------------- the numbers


def _best_sellers_plan(ctx: Ctx) -> ReadPlan | None:
    words = ctx.intent.signals.words
    period = period_from(words)
    if period is None:
        # No period named at all is "recently" and has a sensible default; a period the map
        # DECLINED (two of them, an ambiguity) must not be defaulted over — that is exactly
        # the case it declined for. The sibling recipe honours this and so must this one.
        if ctx.intent.signals.period:
            return None
        period = "last_30_days"
    # "By colour" and "by size" are the same question with one dimension changed, which is
    # what the read layer is for. A "by" the map does not know is not guessed at: the plan
    # declines and Claude takes the turn.
    if any(w in ("by", "per") for w in words):
        group = dimension_from(words)
        if group is None:
            return None
    else:
        group = "product"
    entity = "variants" if group in ("size", "colour", "variant") else "order_line_items"
    return ReadPlan([Read("agg", "commerce_aggregate", {
        "entity": entity, "period": period, "group_by": [group],
        "metrics": ["units", "revenue"], "sort": [{"metric": "units", "direction": "desc"}],
        "limit": 10, "view": "ranking", "title": f"Best sellers by {group}" if group != "product" else "Best sellers",
    }, source="shopify", cost=120.0)], label="best_sellers")


def _breakdown_plan(ctx: Ctx) -> ReadPlan | None:
    period = period_from(ctx.intent.signals.words)
    if period is None:
        return None
    return ReadPlan([Read("agg", "commerce_aggregate", {
        "entity": "orders", "period": period, "metrics": ["revenue", "orders", "aov"],
        "compare": True, "view": "metrics", "title": "Sales",
    }, source="shopify", cost=120.0)], label="sales_breakdown")


def _aggregate_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    body = result.values.get("agg")
    if not isinstance(body, dict):
        return FastAnswer(answer="", defer="the read layer did not answer")
    # The analytics tool itself records the query it ran (app/tools/analytics_tools.py); the
    # payload has no `query` key, and writing one from it set the follow-up hint to None.
    rows = [r for r in (body.get("rows") or []) if isinstance(r, dict)]
    period = _period_words(body)
    if not rows:
        totals = body.get("totals") or {}
        if totals:
            return FastAnswer(answer=_totals_line(totals, period, str(body.get("currency") or "GBP")) + _hedge(body), calls=list(result.calls), trace={"rows": 0})
        return FastAnswer(answer=f"Nothing sold in {period}." + _hedge(body), calls=list(result.calls), trace={"rows": 0})
    top = rows[0]
    label = str(top.get("label") or top.get("product") or "").strip()
    units = top.get("units")
    words = f"Best in {period}: {label}"
    if units is not None:
        words += f", {int(units)} units"
    if top.get("revenue") is not None:
        words += f" and {_money(top['revenue'], str(body.get('currency') or 'GBP'))}"
    if len(rows) > 1:
        second = rows[1]
        words += f". Then {str(second.get('label') or '').strip()}"
        if second.get("units") is not None:
            words += f" on {int(second['units'])}"
    return FastAnswer(answer=words + "." + _hedge(body), calls=list(result.calls), partial=result.partial, trace={"rows": len(rows), "period": period})


def _totals_line(totals: dict[str, Any], period: str, currency: str = "GBP") -> str:
    bits = []
    if totals.get("revenue") is not None:
        bits.append(_money(totals["revenue"], currency))
    if totals.get("orders") is not None:
        bits.append(f"{int(totals['orders'])} orders")
    if totals.get("aov") is not None:
        bits.append(f"{_money(totals['aov'], currency)} average")
    head = period[:1].upper() + period[1:] if period else "The period"
    return (f"{head}: " + ", ".join(bits) + ".") if bits else f"Nothing to report for {period}."


def _breakdown_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    body = result.values.get("agg")
    if not isinstance(body, dict):
        return FastAnswer(answer="", defer="the read layer did not answer")
    totals = body.get("totals") or {}
    period = _period_words(body)
    line = _totals_line(totals, period, str(body.get("currency") or "GBP"))
    # The engine's shape is {metric: {"from", "to", "delta", "pct"}}. Reading a `revenue_pct`
    # that has never existed meant the comparison was requested, paid for in query cost, and
    # thrown away — half an answer to the question actually asked.
    compare = body.get("compare") if isinstance(body.get("compare"), dict) else {}
    change = compare.get("change") if isinstance(compare.get("change"), dict) else {}
    moved = change.get("revenue") if isinstance(change.get("revenue"), dict) else change.get("orders")
    if isinstance(moved, dict) and isinstance(moved.get("pct"), (int, float)):
        pct = moved["pct"]
        before = _period_words(compare, fallback="the period before")
        line += f" That is {abs(pct):.0f}% {'up on' if pct >= 0 else 'down on'} {before}."
    return FastAnswer(answer=line + _hedge(body), calls=list(result.calls), partial=result.partial, trace={"period": period})


register(Recipe(
    recipe_id="best_sellers_period", intent_family="best_sellers_period",
    read_primitives=("commerce_aggregate",), parallel_nodes=(("agg",),), ui="ranking",
    cache_policy=CACHE_ANALYTICS, min_confidence=0.72, target_ms=2500,
    plan=_best_sellers_plan, render=_aggregate_render,
))
register(Recipe(
    recipe_id="sales_breakdown_period", intent_family="sales_breakdown_period",
    read_primitives=("commerce_aggregate",), parallel_nodes=(("agg",),), ui="metric_group",
    cache_policy=CACHE_ANALYTICS, min_confidence=0.72, target_ms=2500,
    plan=_breakdown_plan, render=_breakdown_render,
))


# ------------------------------------------------------------- late and low


def _delayed_plan(ctx: Ctx) -> ReadPlan | None:
    # Ninety days, as the read layer's own catalogue answers this question: an order that has
    # been waiting forty-five days is the one that matters most, and a thirty-day window is
    # exactly the window that cannot see it.
    return ReadPlan([Read("late", "commerce_query", {
        "entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled", "older_than_days": 5},
        "sort": [{"metric": "age_days", "direction": "desc"}], "limit": 25, "title": "Waiting to go out",
    }, source="shopify", cost=120.0)], label="delayed_orders")


def _delayed_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    body = result.values.get("late")
    if not isinstance(body, dict):
        return FastAnswer(answer="", defer="the read layer did not answer")
    rows = [r for r in (body.get("rows") or []) if isinstance(r, dict)]
    _open_workflow(ctx, body, kind="orders", operation="review")
    if not rows:
        return FastAnswer(answer="Nothing is sitting unfulfilled past five days." + _hedge(body), calls=list(result.calls), trace={"rows": 0})
    oldest = rows[0]
    return FastAnswer(
        answer=f"{_how_many(body, len(rows))} orders are unfulfilled past five days; the oldest is {str(oldest.get('order_number') or '').lstrip('#')} at {int(oldest.get('age_days') or 0)} days." + _hedge(body),
        calls=list(result.calls), partial=result.partial, trace={"rows": len(rows), "row_count": body.get("row_count")},
    )


def _stock_plan(ctx: Ctx) -> ReadPlan | None:
    return ReadPlan([Read("stock", "inventory_query", {"period": period_from(ctx.intent.signals.words) or "last_7_days", "limit": 10}, source="shopify", cost=120.0)], label="stock_cover")


def _stock_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    body = result.values.get("stock")
    if not isinstance(body, dict):
        return FastAnswer(answer="", defer="the read layer did not answer")
    rows = [r for r in (body.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return FastAnswer(answer="Nothing is close to running out on recent sales." + _hedge(body), calls=list(result.calls), trace={"rows": 0})
    first = rows[0]
    cover = first.get("days_cover")
    words = f"Closest to running out: {str(first.get('label') or '').strip()}"
    if isinstance(cover, (int, float)):
        words += f", about {cover:.0f} days of cover"
    if first.get("stock") is not None:
        words += f" on {int(first['stock'])} in stock"
    return FastAnswer(answer=words + f". {_how_many(body, len(rows))} on the list." + _hedge(body), calls=list(result.calls), partial=result.partial, trace={"rows": len(rows)})


register(Recipe(
    recipe_id="delayed_orders", intent_family="delayed_orders", read_primitives=("commerce_query",),
    parallel_nodes=(("late",),), ui="table", cache_policy=CACHE_ANALYTICS, min_confidence=0.72,
    target_ms=2500, plan=_delayed_plan, render=_delayed_render,
))
register(Recipe(
    recipe_id="stock_cover_analysis", intent_family="stock_cover_analysis", read_primitives=("inventory_query",),
    parallel_nodes=(("stock",),), ui="ranking", cache_policy=CACHE_ANALYTICS, min_confidence=0.72,
    target_ms=2500, plan=_stock_plan, render=_stock_render,
))


# ------------------------------------------------------------------ the inbox


# How far back to look, and what to call it. The family boosts on a period, so a period
# reaches this recipe — and it was read for the routing and then thrown away: the plan always
# asked for seven days and the sentence always said "this week", so "show me today's emails"
# was answered with the week's. A window the owner did not ask for, named as though he had.
_INBOX_WINDOW: dict[str, tuple[int, str]] = {
    "today": (1, "today"),
    "yesterday": (2, "since yesterday"),
    "this_week": (7, "this week"),
    "last_7_days": (7, "in the last seven days"),
    "this_month": (30, "this month"),
    "last_30_days": (30, "in the last thirty days"),
    "last_90_days": (90, "in the last ninety days"),
}
_INBOX_DEFAULT = (7, "this week")


def _inbox_window(ctx: Ctx) -> tuple[int, str]:
    named = period_from(ctx.intent.signals.words)
    return _INBOX_WINDOW.get(named or "", _INBOX_DEFAULT)


def _inbox_plan(ctx: Ctx) -> ReadPlan | None:
    days, _ = _inbox_window(ctx)
    return ReadPlan([Read("inbox", "gmail_search", {"query": "", "days": days, "limit": 12}, source="gmail", cost=2.0)], label="inbox_state")


def _inbox_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    body = result.values.get("inbox")
    days, when = _inbox_window(ctx)
    if not isinstance(body, dict):
        return FastAnswer(answer="", defer="the inbox did not answer")
    threads = [t for t in (body.get("threads") or []) if isinstance(t, dict)]
    real = [t for t in threads if not t.get("likely_bulk")]
    if not real:
        return FastAnswer(answer=f"Nothing from a person in the inbox {when}.", calls=list(result.calls),
                          trace={"threads": 0, "days": days})
    newest = real[0]
    return FastAnswer(answer=f"{len(real)} threads from people {when}; the newest is {newest.get('from') or 'someone'} about {newest.get('subject') or 'no subject'}.",
                      calls=list(result.calls), partial=result.partial, trace={"threads": len(real), "days": days})


def _needs_reply_plan(ctx: Ctx) -> ReadPlan | None:
    """Who is waiting on us: recent customers, then their inbox state, at customer level and
    across threads. Two waves — the second needs the set the first makes."""
    return ReadPlan([
        Read("customers", "commerce_query", {"entity": "customers", "period": "last_30_days", "limit": 25, "title": "Recent customers"}, source="shopify", cost=120.0),
        Read("mail", "email_query", _needs_reply_args, source="gmail", after=("customers",), cost=8.0, timeout_s=10.0),
    ], label="needs_reply", timeout_s=16.0)


def _needs_reply_args(values: dict[str, Any]) -> dict[str, Any] | None:
    set_id = _set_id_of(values.get("customers"))
    return {"set_id": set_id, "days": 30} if set_id else None


def _set_id_of(body: Any, key: str = "set") -> str:
    """The working set a listing made. The read layer publishes it under `set` (the whole
    public shape) — `set_id` at the top level is what the batch tools' own results use — so
    both are looked for rather than one being assumed."""
    if not isinstance(body, dict):
        return ""
    held = body.get(key)
    if isinstance(held, dict) and held.get("set_id"):
        return str(held["set_id"])
    return str(body.get("set_id") or "")


# The same question, asked again inside this window, gets the short form: the owner has just
# heard "1 of 25 customers checked" and is asking whether anything has changed, not for the
# scope of the check read out a second time.
NEEDS_REPLY_REPEAT_S = 600.0


def _first_names(rows: list[dict[str, Any]], limit: int = 3) -> str:
    names = [str(r.get("customer_name") or "someone").split()[0] for r in rows[:limit]]
    rest = len(rows) - len(names)
    if rest > 0:
        names.append(f"{rest} other{'s' if rest > 1 else ''}")
    if len(names) <= 1:
        return names[0] if names else "nobody"
    return ", ".join(names[:-1]) + " and " + names[-1]


def _asked_again(ctx: Ctx, *, clock=time.time) -> bool:
    """Whether this is a repeat of the question within the window; stamps the session either
    way. A session without the attribute (a bare stand-in in a test) is never a repeat."""
    now = float(clock())
    last = float(getattr(ctx.session, "last_needs_reply_at", 0.0) or 0.0)
    try:
        ctx.session.last_needs_reply_at = now
    except AttributeError:
        return False
    return bool(last) and 0 <= now - last < NEEDS_REPLY_REPEAT_S


def _needs_reply_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    body = result.values.get("mail")
    if not isinstance(body, dict):
        return FastAnswer(answer="", defer="the inbox correlation did not come back")
    rows = [r for r in (body.get("rows") or []) if isinstance(r, dict)]
    waiting = [r for r in rows if r.get("needs_reply")]
    counts = body.get("counts") or {}
    unchecked = int(counts.get("unchecked") or 0)
    total = int(counts.get("contacted") or 0) + int(counts.get("not_contacted") or 0) + unchecked or len(rows)
    again = _asked_again(ctx)
    # What "next" walks here is the MESSAGES, not the people. Opening the customers set meant
    # tapping Next on "Waiting on a reply" drew Mia Jones's customer profile — three orders,
    # £213 lifetime — instead of the message she is waiting on an answer to. The queue is a
    # queue of things to reply to, so its cursor moves along the threads.
    #
    # And the thread ids go into `issued_ids`, because this card puts them on the screen. The
    # gate's rule is that a conversation may only reach a record it was shown, and the surface
    # is built here rather than harvested from a tool result, so nothing else would have
    # issued them — which made every row of this card unopenable by the very check that
    # exists to protect it.
    _open_waiting_threads(ctx, body, waiting)
    waiting_set = _set_id_of(body, "set_needs_reply")
    if waiting_set and ctx.branch.workflow is None:
        _open_workflow(ctx, body, kind="customers", operation="reply", set_id=waiting_set)
    tail = f" {unchecked} could not be checked." if unchecked else ""
    if not waiting:
        answer = "Still nobody." if again else f"Nobody is waiting on a reply — {len(rows)} of {total} customers checked.{tail}"
        return FastAnswer(answer=answer, calls=list(result.calls),
                          partial=bool(unchecked) or result.partial, trace={"rows": len(rows), "waiting": 0, "unchecked": unchecked, "repeat": again})
    if again:
        # "Still just Mia." — no scope sentence: it was said the first time, and the owner is
        # asking whether anything moved, not how wide the check was.
        answer = f"Still {'just ' if len(waiting) == 1 else ''}{_first_names(waiting)}."
    else:
        names = ", ".join(str(r.get("customer_name") or "someone") for r in waiting[:3])
        answer = f"{len(waiting)} of {len(rows)} customers checked are waiting on a reply: {names}{' and others' if len(waiting) > 3 else ''}.{tail}"
    return FastAnswer(
        answer=answer,
        surfaces=[_waiting_surface(waiting, unchecked=unchecked)], drawn=[],
        calls=list(result.calls), partial=bool(unchecked) or result.partial,
        trace={"rows": len(rows), "waiting": len(waiting), "unchecked": unchecked, "repeat": again},
    )


def _open_waiting_threads(ctx: Ctx, body: dict[str, Any], waiting: list[dict[str, Any]]) -> None:
    """Make the queue walkable and its rows openable: one set of the threads being waited on."""
    from app.analytics import sets as working_sets

    threads = [str(r.get("last_thread_id") or "") for r in waiting]
    threads = [t for t in threads if t]
    if not threads:
        return
    issue = getattr(ctx.session, "issue", None)
    if callable(issue):
        issue(*threads)
    parent = working_sets.get(ctx.session, _set_id_of(body))
    if parent is None:
        return
    labels = {
        str(r.get("last_thread_id") or ""): str(r.get("customer_name") or r.get("last_subject") or "")[:60]
        for r in waiting if r.get("last_thread_id")
    }
    made = working_sets.derive(
        ctx.session, parent, members=threads, label="Waiting on a reply", step="correlate",
        kind="emails", labels=labels, detail={"tool": "email_query", "which": "waiting"}, focus=False,
    )
    _open_workflow(ctx, body, kind="emails", operation="reply", set_id=made.set_id)


def _since(when: Any, *, now: float | None = None) -> str:
    """How long ago, in the words a person would use. Worked out here because the Mac owns the
    clock and the shop's timezone; the renderer prints whatever string it is given."""
    import datetime as _dt

    text = str(when or "").strip()
    if not text:
        return ""
    # Gmail's own stamp is epoch milliseconds, which is what reaches here; an ISO string is
    # accepted too because the Shopify side speaks that. Anything else is handed back as it
    # came rather than guessed at — a wrong "3h ago" is worse than a date.
    if text.lstrip("-").isdigit():
        value = float(text)
        at = value / 1000.0 if abs(value) > 1e11 else value
    else:
        try:
            stamp = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=_dt.UTC)
        at = stamp.timestamp()
    seconds = (_dt.datetime.now(_dt.UTC).timestamp() if now is None else now) - at
    if seconds < 0:
        return "just now"
    if seconds < 90 * 60:
        return f"{max(1, int(seconds // 60))}m ago"
    if seconds < 36 * 3600:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _waiting_surface(waiting: list[dict[str, Any]], *, unchecked: int = 0):
    """The people waiting on us, as the thing the question asked for.

    This recipe used to hand its raw reads to `present()`, which built whatever the analytic
    results implied: a revenue RANKING of recent customers, a working set, a metric group, a
    table, and a second working set — 1,886 pixels, five cards, three of them titled "Recent
    customers", and not one of them saying who was waiting. The spoken answer named the three
    people correctly while the screen showed a leaderboard.

    So the answer is drawn from the rows the recipe already has, and says the three things the
    owner needs to decide without opening anything: who, what about, and how long they have
    been waiting. Tapping a row opens that thread — the thread id is on the row, so nothing has
    to be looked up again.
    """
    from app.surfaces import Freshness, Surface

    threads = []
    for row in waiting[:10]:
        # The order numbers the THREADS name, when the correlation found any — that is what
        # the email is about — and the customer's recent orders otherwise. With how sure the
        # link between this person and these threads is, because the row is a decision to
        # reply and a wrong link is a reply to the wrong question.
        related = [str(o).lstrip("#") for o in (row.get("related_orders") or []) if o][:3]
        orders = [f"#{o}" for o in related] or [str(o) for o in (row.get("orders") or []) if o][:2]
        confidence = str(row.get("confidence") or "")
        count = int(row.get("thread_count") or row.get("threads") or 0)
        threads.append({
            "thread_id": str(row.get("last_thread_id") or ""),
            "from": str(row.get("customer_name") or row.get("customer_email") or "someone"),
            "subject": str(row.get("last_subject") or "(no subject)"),
            # What ties it to the shop, which is why this is one system and not two.
            # §26: the confidence in words, not in the correlator's own token. This line
            # read "#1938 · confident" on the glass — `confident` and `possible` are how
            # app/families/order_email.py grades a link, and neither is a thing a person
            # says. A certain link needs no adjective: the order number IS the claim. An
            # uncertain one must be visibly uncertain, because the row is a decision to
            # reply and a wrong link is a reply to the wrong question — so it says so.
            "snippet": " · ".join(filter(None, [
                (f"maybe {', '.join(orders)}" if confidence == "possible" and orders
                 else ", ".join(orders)),
                "not sure which order" if confidence == "possible" and not orders else "",
                f"{count} threads" if count > 1 else "",
            ])),
            "date": _since(row.get("latest_inbound_at")),
            "known_customer": True,
            "related_orders": related,
            "confidence": confidence[:12],
        })
    note = f"{unchecked} could not be checked." if unchecked else ""
    return Surface(
        surface_type="work_queue",
        ui_type="email_list",
        data={"title": "Waiting on a reply", "count": len(waiting), "threads": threads, "note": note},
        title="Waiting on a reply",
        subtitle=f"{len(waiting)} waiting" + (f" · {note}" if note else ""),
        freshness=Freshness(source="gmail", complete=not unchecked,
                            caveat=note or ""),
    )


# Which of the dock's places a set of each kind belongs to, so a listing lands the branch
# somewhere Home and Back can name. The reply queue lists CUSTOMERS and is the inbox.
SET_AREA = {"orders": "orders", "emails": "email", "customers": "email",
            "products": "products", "variants": "products"}


def _open_workflow(ctx: Ctx, body: dict[str, Any], *, kind: str, operation: str, set_id: str = "",
                   area: str = "") -> None:
    """A listing becomes something to work through: the branch takes its cursor to the top.
    "Next" is then arithmetic, which is the whole point.

    And the LISTING ITSELF becomes a stop on the trail. That is new, and it is what makes Back
    worth pressing: the owner starts at a list, opens a row, follows a relation, and the way
    back out was missing its first step — the list was never on the trail, because only
    records were, so the deepest Back he could reach was the first record he had opened.
    """
    from app.analytics import sets as working_sets
    from app.session.branch import LIST_KIND, Workflow

    set_id = set_id or _set_id_of(body)
    if not set_id:
        return
    ws = working_sets.get(ctx.session, set_id)
    if ws is None or not ws.members:
        return
    ctx.branch.set_id = ws.set_id
    # Before the first member, so the first "Next" lands on it — the same place a set adopted
    # by a bare "Next" starts from (app/fastpath/runner.py).
    workflow_id = f"wf_{int(time.time() * 1000) % 10**9:09d}"
    ctx.branch.workflow = Workflow(workflow_id=workflow_id, set_id=ws.set_id, kind=kind, label=ws.label, operation=operation, cursor=-1, total=len(ws.members))
    ctx.branch.enter(area=area or SET_AREA.get(kind, ""), kind=LIST_KIND, ref=ws.set_id,
                     label=ws.label, set_id=ws.set_id, set_kind=kind, set_label=ws.label,
                     total=len(ws.members), operation=operation, workflow_id=workflow_id)


register(Recipe(
    recipe_id="inbox_state", intent_family="inbox_state", read_primitives=("gmail_search",),
    parallel_nodes=(("inbox",),), ui="email_list", cache_policy=CACHE_EMAIL, min_confidence=0.74,
    target_ms=2500, plan=_inbox_plan, render=_inbox_render,
))
register(Recipe(
    recipe_id="needs_reply", intent_family="needs_reply", read_primitives=("commerce_query", "email_query"),
    parallel_nodes=(("customers",), ("mail",)), ui="email_list", cache_policy=CACHE_EMAIL,
    min_confidence=0.74, target_ms=4000, plan=_needs_reply_plan, render=_needs_reply_render,
))
