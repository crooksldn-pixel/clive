"""The query engine's own family: the operational questions, answered without a guess (brief §15).

What this fixes was measured on the tablet, not imagined. "Can you see if any of our orders
are undelivered or unfulfilled?" produced three `commerce_query` calls in a row, each refused
with

    Query not understood: sort by : not one of the metrics or groups asked for

and each followed by another invented shape — 15–16 s of Claude, twice, for a question the
Mac can answer from its own order cache in a few hundred milliseconds. Two things were wrong
and both are fixed elsewhere in this pass:

  * the query layer took exactly one sort shape and named none of them in its refusal
    (app/analytics/query.py: every shape now parses, and every refusal carries the schema);
  * "undelivered" had no answer at all, because no carrier is connected — so it is refused
    locally, by name, and never quietly read as "unfulfilled".

What is here is the third thing: these sentences should never reach the model. Two intent
families and one procedure —

    which orders are unfulfilled / undelivered      unfulfilled_orders
    international orders waiting too long           international_orders

— both drawing the same list from the order cache through `commerce_query`, oldest first,
with the working set that makes the list walkable. No model on the path.

The two families are deliberately narrow. `delayed_orders` (app/fastpath/library.py) owns the
words of LATENESS — "which orders are late" is unfulfilled past five days — and these own the
words of STATE and DESTINATION. A signal that took "late" would take that family's sentences
with it, so `_UNFULFILLED` in app/fastpath/intent.py does not contain it.

Read-only, like every recipe: `assert_read_only` holds for these too.
"""

from __future__ import annotations

from typing import Any

from app.analytics.query import DELIVERY_WORD
from app.capabilities import families as capability_families
from app.fastpath import library
from app.fastpath.intent import Family, extend
from app.fastpath.models import Ctx, FastAnswer
from app.fastpath.recipes import CACHE_ANALYTICS, Recipe, register
from app.reads.scheduler import Read, ReadPlan, ReadResult

# What the answer says when the question used the word "undelivered". Exactly the shape of the
# refusal the query layer gives the model (app/analytics/query.py:TRACKING_UNAVAILABLE), said
# the way a person says it: the answer is honest about what it is NOT answering.
NO_TRACKING_NOTE = " — tracking status is not available here."

# Ninety days, for delayed_orders' reason: an order that has been waiting forty-five days is
# the one that matters most, and a thirty-day window is exactly the window that cannot see it.
PERIOD = "last_90_days"


def _asks_about_delivery(ctx: Ctx) -> bool:
    """Whether the question used a delivery word. Read from the words themselves rather than
    from the signal, because the signal deliberately treats "undelivered" as the fulfilment
    state (it is the only thing that can be answered) and this is the other half of that
    bargain: the answer must say which question it did not answer."""
    return any(DELIVERY_WORD.search(word) for word in (ctx.intent.signals.words or ()))


def _plan(ctx: Ctx) -> ReadPlan | None:
    """One read: the orders still to go out, oldest first, through the read layer.

    Through `commerce_query` and not `shopify_list_orders` for the reason `order_list_period`
    gives — a listing publishes a working set, and the set is what makes "next" and a tap on
    the third row the same operation on the same list.

    `sort: "oldest"` is the bare-word shape on purpose. It is the shape a planner reaches for,
    it is now the shape the layer takes, and using it here means the recipe and the model are
    speaking the same language rather than the recipe knowing a private one.
    """
    international = ctx.intent.signals.international
    filters: dict[str, Any] = {"fulfillment": "unfulfilled"}
    if international:
        filters["international"] = True
    return ReadPlan([Read("waiting", "commerce_query", {
        "entity": "orders", "period": PERIOD, "filters": filters, "sort": "oldest", "limit": 25,
        "title": "Abroad, waiting to go out" if international else "Waiting to go out",
    }, source="shopify", cost=120.0)], label="unfulfilled_orders")


def _render(ctx: Ctx, result: ReadResult) -> FastAnswer:
    body = result.values.get("waiting")
    if not isinstance(body, dict):
        return FastAnswer(answer="", defer="the read layer did not answer")
    rows = [r for r in (body.get("rows") or []) if isinstance(r, dict)]
    international = ctx.intent.signals.international
    kind = "international order" if international else "order"
    note = NO_TRACKING_NOTE if _asks_about_delivery(ctx) else ""
    if not rows:
        # Said in the words of the filter that was actually applied. "Nothing is undelivered"
        # would be a claim about something nothing here can see.
        nothing = f"No {kind}s are unfulfilled." if international else "Nothing is unfulfilled."
        return FastAnswer(answer=nothing + note + library._hedge(body), calls=list(result.calls),
                          partial=result.partial, trace={"rows": 0, "international": international})
    # The list becomes the thing being worked through: oldest first, so "next" walks the queue
    # in the order the orders should go out in.
    library._open_workflow(ctx, body, kind="orders", operation="review")
    oldest = rows[0]
    number = str(oldest.get("order_number") or "").lstrip("#")
    days = int(oldest.get("age_days") or 0)
    count = library._how_many(body, len(rows))
    one = len(rows) == 1
    words = (f"{count} {kind}{'' if one else 's'} {'is' if one else 'are'} unfulfilled; the oldest is "
             f"{number}, waiting {days} day{'' if days == 1 else 's'}.")
    return FastAnswer(
        answer=words + note + library._hedge(body), calls=list(result.calls), partial=result.partial,
        trace={"rows": len(rows), "row_count": body.get("row_count"), "international": international,
               "delivery_asked": bool(note)},
    )


# --------------------------------------------------------------------------- registration

register(Recipe(
    recipe_id="unfulfilled_orders", intent_family="unfulfilled_orders", read_primitives=("commerce_query",),
    parallel_nodes=(("waiting",),), ui="order_list", cache_policy=CACHE_ANALYTICS,
    min_confidence=0.7, target_ms=1500, plan=_plan, render=_render,
))
register(Recipe(
    recipe_id="international_waiting_orders", intent_family="international_orders", read_primitives=("commerce_query",),
    parallel_nodes=(("waiting",),), ui="order_list", cache_policy=CACHE_ANALYTICS,
    min_confidence=0.7, target_ms=1500, plan=_plan, render=_render,
))

# Both families need the same things ruled out: a number (that is one order, not a list), a
# figure (that is the sales card), the inbox, stock, a ranking, an address, a named person.
# `delayed` is deliberately NOT blocked — these sentences say "waiting" and mean this list.
_NOT_THIS = ("mutation", "order_number", "metric", "email", "stock", "running_out", "ranking",
             "address", "possessive_name", "again", "bought")
# The base is high because these sentences are long: "find a real international order that has
# been waiting too long and hasn't been fulfilled" is fifteen words with a clause join in it,
# and the join costs 0.25. A family that scored 0.72 flat could never win a sentence a person
# actually says. The narrowness is in `needs` — a state word or a destination word, and an
# order — not in the score.
extend([
    Family("unfulfilled_orders", needs=("order", "unfulfilled"), boosts=("question", "waiting", "listing"),
           blocks=_NOT_THIS + ("international", "deixis"), base=0.9, floor=0.7, max_words=16),
    # "That order" is fine here: "find a real international order THAT has been waiting too
    # long" points at nothing on screen — the pronoun is grammar, not deixis — and blocking it
    # cost the sentence the whole session was about.
    Family("international_orders", needs=("order", "international"), boosts=("question", "waiting", "unfulfilled"),
           blocks=_NOT_THIS, base=0.9, floor=0.7, max_words=16),
])

# What this Mac cannot know, in the one table that reaches /health, the manifest and the model's
# own context (app/capabilities/families.py, app/routes/turn.py:_family_lines). Registered as a
# family precisely so the model is TOLD once, at the top of the turn, rather than discovering it
# a refused query at a time — which is what cost the tablet 45 s on one question.
#
# DISCONNECTED rather than NOT_SUPPORTED_BY_STORE: the shop can be told a tracking number, and
# often is. What is missing is anything that reports back, and that is a provider nobody has
# connected. `detail` carries no full stop: `families.words()` adds one, and the line the model
# reads is short because it is paid on every model-path turn.
#
# Only this one. A READY read family would add a line to every turn saying the Mac can list
# orders — which the tool block already says, in more detail, for nothing extra.
capability_families.register(capability_families.CapabilityFamily(
    key="delivery_tracking", label="Delivery status", area="shipping",
    what="whether a parcel has actually arrived",
    state="DISCONNECTED",
    detail="no carrier is connected, so whether a parcel arrived is not a fact CLIVE holds — "
           "only fulfilled/unfulfilled, and whether a tracking number exists",
))
