"""The dock's four landings — Orders, Inbox, Sales, Products — as workspaces (brief §4).

On the bench the dock "did not behave like useful navigation unless the assistant was already
in another interaction": each icon asked a sentence through the whole turn pipeline, and a
sentence about today's orders on a quiet afternoon drew an empty list. A landing is not a
question. It is a place, and a place has a fixed shape whatever was said before it:

    Orders    what has to go out (oldest first, a set to walk) and what came in today
    Inbox     who is waiting on a reply (the queue), then what else people have written
    Sales     the week against the week before, today so far, and what is selling
    Products  the best sellers of the month and what is closest to running out

Each is a FAST recipe — deterministic reads through the read scheduler, no model — reached
two ways that resolve to the same recipe: a tap on the dock posts the semantic command
`open.area` (touch; `app/routes/command.py` runs the named recipe), and "open orders" /
"open the inbox" / "show me sales" spoken resolve to the same recipe through an intent
family. Products by voice has no signal of its own ("products" is not a word the router
knows) and reaches the model; the tap is the way in, and the report says so.

Read-only, like every recipe: `assert_read_only` holds for these too.
"""

from __future__ import annotations

from typing import Any

from app import commands as commands_mod
from app.commands import Command, Outcome
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command
from app.fastpath import library
from app.fastpath.intent import Family, extend, signal
from app.fastpath.models import Ctx, FastAnswer
from app.fastpath.recipes import CACHE_ANALYTICS, CACHE_EMAIL, Recipe, register
from app.reads.scheduler import Read, ReadPlan, ReadResult

# The Products landing's own word. The router knows "stock" and "running out" but not
# "products", so "open products" — one of the four things the dock offers — reached the model
# while the other three did not. A family brings its own word (app/fastpath/intent.signal).
PRODUCT_WORDS = frozenset({"products", "product", "inventory", "merchandise", "range"})
_SAYS_PRODUCTS = signal(
    "says_products_area",
    lambda s: s.stock or bool(set(s.words) & PRODUCT_WORDS),
)

AREAS: dict[str, str] = {
    "orders": "landing_orders",
    "email": "landing_inbox",
    "sales": "landing_sales",
    "products": "landing_products",
}

# The same table, where `navigation.home` can find it. A command must not import a family —
# `app/commands.py` is the bottom of the stack and the families sit on top of it — so the
# families hand their landings down instead. Home is then "the recipe for this half's area",
# resolved in one place for the tap and the sentence both (app/commands.py:home_target).
commands_mod.LANDING_FOR.update(AREAS)


# ------------------------------------------------------------------------------ orders

# What each place is called on the trail, so a Back that lands on one can name it.
AREA_LABELS = {"orders": "Orders", "email": "Inbox", "sales": "Sales", "products": "Products"}


def _arrived(ctx: Ctx, area: str) -> None:
    """This half is now in this place.

    A landing is a stop on the trail, and the place a Home goes back to. It is recorded here
    rather than in the command that names the recipe, because a landing that could not be
    drawn is not somewhere the owner arrived — and the two landings that open a working set
    refine this stop with the set a moment later (`library._open_workflow`).
    """
    from app.session.branch import LANDING_KIND

    ctx.branch.enter(area=area, kind=LANDING_KIND, ref=area, label=AREA_LABELS.get(area, area))


def _orders_plan(ctx: Ctx) -> ReadPlan | None:
    """What must go out, and what came in. Two independent reads, in parallel."""
    return ReadPlan([
        Read("open", "commerce_query", {
            "entity": "orders", "period": "last_30_days", "filters": {"fulfillment": "unfulfilled"},
            "sort": [{"metric": "age_days", "direction": "desc"}], "limit": 25, "title": "To go out",
        }, source="shopify", cost=120.0),
        Read("today", "commerce_query", {
            "entity": "orders", "period": "today", "sort": [{"metric": "placed_at", "direction": "desc"}],
            "limit": 25, "title": "Today",
        }, source="shopify", cost=120.0),
    ], label="landing_orders")


def _rows(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    return [r for r in (body.get("rows") or []) if isinstance(r, dict)]


def _call_named(result: ReadResult, node: str):
    """The tool call behind a read node, so the card is drawn from exactly that read."""
    body = result.values.get(node)
    for call in result.calls:
        if getattr(call, "ok", False) and getattr(call, "result", None) is body and body is not None:
            return call
    return None


def _orders_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    open_body, today_body = result.values.get("open"), result.values.get("today")
    if not isinstance(open_body, dict) and not isinstance(today_body, dict):
        return FastAnswer(answer="", defer="the order reads did not answer")
    _arrived(ctx, "orders")
    waiting, today = _rows(open_body), _rows(today_body)
    # The set the cursor walks is the operational one: the orders still to go out, oldest
    # first. On a day with nothing waiting, today's orders are the set.
    primary = "open" if waiting else "today"
    body = open_body if waiting else today_body
    if isinstance(body, dict):
        library._open_workflow(ctx, body, kind="orders", operation="review")
    if waiting:
        oldest = waiting[0]
        words = f"{library._how_many(open_body, len(waiting))} order{'s' if len(waiting) != 1 else ''} to go out; the oldest is {str(oldest.get('order_number') or '').lstrip('#')} at {int(oldest.get('age_days') or 0)} days."
    else:
        words = "Nothing is waiting to go out."
    words += f" {len(today)} order{'s' if len(today) != 1 else ''} today." if today else " None in today yet."
    drawn = [c for c in (_call_named(result, primary), _call_named(result, "today" if primary == "open" else "open")) if c is not None]
    return FastAnswer(answer=words + library._hedge(open_body if isinstance(open_body, dict) else today_body),
                      calls=list(result.calls), drawn=drawn, partial=result.partial,
                      trace={"waiting": len(waiting), "today": len(today), "primary": primary})


# ------------------------------------------------------------------------------- inbox


def _inbox_plan(ctx: Ctx) -> ReadPlan | None:
    """The needs-reply queue's read of the inbox, and the recent threads beside it. Neither
    waits for the other."""
    queue = library._needs_reply_plan(ctx)
    recent = library._inbox_plan(ctx)
    reads = list(queue.reads if queue else []) + list(recent.reads if recent else [])
    return ReadPlan(reads, label="landing_inbox", timeout_s=16.0) if reads else None


def _inbox_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    queue = library._needs_reply_render(ctx, result)
    recent = library._inbox_render(ctx, result)
    if queue.deferred and recent.deferred:
        return FastAnswer(answer="", defer=f"{queue.defer}; {recent.defer}")
    _arrived(ctx, "email")
    parts = [a.answer for a in (queue, recent) if not a.deferred and a.answer]
    surfaces = list(queue.surfaces) if not queue.deferred else []
    # The queue is the recipe's own card; the recent threads are drawn from the search read.
    drawn = [c for c in [_call_named(result, "inbox")] if c is not None] if not recent.deferred else []
    return FastAnswer(answer=" ".join(parts), calls=list(result.calls), surfaces=surfaces, drawn=drawn,
                      partial=result.partial or queue.partial or recent.partial,
                      trace={"queue": (queue.trace or {}).get("waiting"), "threads": (recent.trace or {}).get("threads")})


# ------------------------------------------------------------------------------- sales


def _sales_plan(ctx: Ctx) -> ReadPlan | None:
    return ReadPlan([
        Read("agg", "commerce_aggregate", {
            "entity": "orders", "period": "last_7_days", "metrics": ["revenue", "orders", "aov"],
            "compare": True, "view": "metrics", "title": "This week",
        }, source="shopify", cost=120.0),
        Read("today", "commerce_aggregate", {
            "entity": "orders", "period": "today", "metrics": ["revenue", "orders"], "view": "metrics", "title": "Today",
        }, source="shopify", cost=120.0),
        Read("top", "commerce_aggregate", {
            "entity": "order_line_items", "period": "last_7_days", "group_by": ["product"],
            "metrics": ["units", "revenue"], "sort": [{"metric": "units", "direction": "desc"}],
            "limit": 5, "view": "ranking", "title": "Selling this week",
        }, source="shopify", cost=120.0),
    ], label="landing_sales")


def _sales_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    week = library._breakdown_render(ctx, result)
    if week.deferred:
        return week
    _arrived(ctx, "sales")
    words = week.answer
    today = result.values.get("today")
    if isinstance(today, dict) and isinstance(today.get("totals"), dict) and today["totals"]:
        # Today's figure is said, not drawn: two metric cards on an 8-inch screen is one too
        # many, and "today so far" is a number the owner hears and moves on from.
        totals = today["totals"]
        revenue, orders = totals.get("revenue"), totals.get("orders")
        if isinstance(revenue, (int, float)):
            words += f" Today so far, {library._money(revenue, str(today.get('currency') or 'GBP'))}"
            words += f" on {int(orders)} order{'s' if int(orders) != 1 else ''}." if isinstance(orders, (int, float)) else "."
    drawn = [c for c in (_call_named(result, "agg"), _call_named(result, "top")) if c is not None]
    return FastAnswer(answer=words, calls=list(result.calls), drawn=drawn, partial=result.partial,
                      trace={"today": bool(today), "top": len(_rows(result.values.get("top")))})


# ---------------------------------------------------------------------------- products


def _products_plan(ctx: Ctx) -> ReadPlan | None:
    return ReadPlan([
        Read("top", "commerce_aggregate", {
            "entity": "order_line_items", "period": "last_30_days", "group_by": ["product"],
            "metrics": ["units", "revenue"], "sort": [{"metric": "units", "direction": "desc"}],
            "limit": 8, "view": "ranking", "title": "Best sellers, 30 days",
        }, source="shopify", cost=120.0),
        Read("stock", "inventory_query", {"period": "last_7_days", "limit": 8}, source="shopify", cost=120.0),
    ], label="landing_products")


def _products_render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    top = _rows(result.values.get("top"))
    stock = _rows(result.values.get("stock"))
    if not isinstance(result.values.get("top"), dict) and not isinstance(result.values.get("stock"), dict):
        return FastAnswer(answer="", defer="the product reads did not answer")
    _arrived(ctx, "products")
    words = []
    if top:
        first = top[0]
        label = str(first.get("label") or first.get("product") or "").strip()
        units = first.get("units")
        words.append(f"Best seller this month: {label}" + (f", {int(units)} units." if units is not None else "."))
    else:
        words.append("Nothing sold this month.")
    if stock:
        first = stock[0]
        cover = first.get("days_cover")
        line = f"Closest to running out: {str(first.get('label') or '').strip()}"
        if isinstance(cover, (int, float)):
            line += f", about {cover:.0f} days of cover"
        words.append(line + ".")
    else:
        words.append("Nothing is close to running out.")
    drawn = [c for c in (_call_named(result, "top"), _call_named(result, "stock")) if c is not None]
    return FastAnswer(answer=" ".join(words), calls=list(result.calls), drawn=drawn, partial=result.partial,
                      trace={"top": len(top), "stock": len(stock)})


# --------------------------------------------------------------------------- registration

register(Recipe(
    recipe_id="landing_orders", intent_family="landing_orders", read_primitives=("commerce_query",),
    parallel_nodes=(("open", "today"),), ui="order_list", cache_policy=CACHE_ANALYTICS,
    min_confidence=0.72, target_ms=1500, plan=_orders_plan, render=_orders_render,
))
register(Recipe(
    recipe_id="landing_inbox", intent_family="landing_inbox", read_primitives=("email_query", "gmail_search"),
    parallel_nodes=(("mail", "inbox"),), ui="email_list", cache_policy=CACHE_EMAIL,
    min_confidence=0.72, target_ms=4000, plan=_inbox_plan, render=_inbox_render,
))
register(Recipe(
    recipe_id="landing_sales", intent_family="landing_sales", read_primitives=("commerce_aggregate",),
    parallel_nodes=(("agg", "today", "top"),), ui="metric_group", cache_policy=CACHE_ANALYTICS,
    min_confidence=0.72, target_ms=2500, plan=_sales_plan, render=_sales_render,
))
register(Recipe(
    recipe_id="landing_products", intent_family="landing_products", read_primitives=("commerce_aggregate", "inventory_query"),
    parallel_nodes=(("top", "stock"),), ui="ranking", cache_policy=CACHE_ANALYTICS,
    min_confidence=0.72, target_ms=2500, plan=_products_plan, render=_products_render,
))

# Spoken: a short "open …" / "show me …" with the area's own word and nothing else in it.
# Anything more specific — a period, a number, a name, "waiting" — is another family's, and
# the blocks keep these out of its way: "show me today's orders" stays a list of today's.
_QUIET = ("mutation", "period", "order_number", "customer", "waiting", "ranking", "running_out", "status", "address", "deixis", "again", "delayed", "bought", "possessive_name")
extend([
    Family("landing_orders", needs=("listing", "order"), blocks=_QUIET + ("metric", "email", "stock"), base=0.82, floor=0.72, max_words=4),
    Family("landing_inbox", needs=("listing", "email"), blocks=_QUIET + ("metric", "order", "stock"), base=0.84, floor=0.72, max_words=4),
    Family("landing_sales", needs=("listing", "metric"), blocks=_QUIET + ("order", "email", "stock"), base=0.82, floor=0.72, max_words=4),
    Family("landing_products", needs=("listing", _SAYS_PRODUCTS), blocks=_QUIET + ("metric", "order", "email"), base=0.82, floor=0.72, max_words=4),
])


def _open_area(ctx: CommandCtx) -> Outcome:
    """A dock icon. The command names the recipe; the route runs it (a command is synchronous
    and reads nothing itself — see app/commands.py — and a landing is three reads)."""
    area = ctx.arg("area") or ctx.arg("kind")
    recipe_id = AREAS.get(area)
    if not recipe_id:
        return Outcome.refused("unknown_area", f"There is no landing called {area!r}. The dock has {', '.join(AREAS)}.")
    return Outcome(answer="", changed={"recipe": recipe_id, "area": area})


register_command(Command("open.area", "Open a dock landing", _open_area, voice=False))
