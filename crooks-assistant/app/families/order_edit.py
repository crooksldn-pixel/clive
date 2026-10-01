"""Reviewed order item editing (brief §10): adding a line to an order that already exists.

"Add a black hoodie to this order" was refused all through Phase 2 — honestly, because line
items could not be changed. This is the family that changes that, and everything in it exists
to answer one question before the owner's finger moves: WHICH garment, and WHAT does it cost
the customer.

The shape, end to end:

    a control on the order card  →  order_edit.find      a read: the catalogue's candidates
    a candidate and a quantity   →  order_edit.stage     a proposal: Shopify prices the edit
    the hold on that card        →  /actions/…/commit    the one mutation

Three things about it are deliberate.

**The picker is a read.** `order_edit.find` runs a recipe that calls
`shopify_variant_search` and draws a `variant_picker`. It stages nothing, proposes nothing and
cannot: a recipe naming a write tool is a crash at start-up (app/recipes.py). The owner is
choosing, and choosing is not authorising.

**The consequence is Shopify's arithmetic, not ours.** `order_edit.stage` prepares through the
one action engine, and the write tool's PREPARE step runs `orderEditBegin` and
`orderEditAddVariant` — which build and price a CalculatedOrder and change nothing on the real
order. So the card says what the line costs, what the order becomes and what the customer will
owe, from Shopify itself, before anything is applied. `orderEditCommit` is the only mutation
the gesture authorises.

**Said out loud, it is the model's.** "Add a black hoodie to this order" is a model turn
like every other sentence; Claude reads the catalogue and stages `shopify_order_add_item` with
the same tools. The touch path is complete on its own: a control on the order card, a picker,
a card, a hold.

**A line that is not in the catalogue** — "add a £15 rush alteration to order 1930", the
owner's decision 8 of 1 October 2026 — is the same edit with `orderEditAddCustomItem` in place
of `orderEditAddVariant`: Claude stages `shopify_order_add_custom_item` with a title, a unit
price and a quantity, the price is in the order's own currency, and the card, the hold and
the proof are the variant's. It is spoken only: there is no picker for something the shop
does not list.
"""

from __future__ import annotations

from typing import Any

from app.capabilities.families import CapabilityFamily
from app.capabilities.families import register as register_family
from app.commands import Command, Outcome, may_open
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command
from app.presentation import MAX_PICKER_QUANTITY, variant_picker
from app.reads.scheduler import Read, ReadPlan, ReadResult
from app.recipes import CACHE_NONE, Ctx, Recipe, RecipeAnswer, register
from app.surfaces import Entity, Freshness, Surface

# The write this family stages, and the read that feeds it. Named once, here, so the
# capability family, the recipe and the command cannot drift apart.
WRITE_TOOL = "shopify_order_add_item"
SEARCH_TOOL = "shopify_variant_search"
OPERATION = "order_edit_add_line"
# A line that is not a catalogue product, on the same order edit (spoken only; no command).
CUSTOM_WRITE_TOOL = "shopify_order_add_custom_item"
CUSTOM_OPERATION = "order_edit_add_custom_line"
SCOPE = "write_order_edits"

# What the tablet may post to narrow the picker, and how much of it. Words, not arguments:
# they reach a READ, and the Mac reads the price and builds every execution argument itself.
MAX_WORD_CHARS = {"product": 60, "colour": 30, "size": 20}


# ------------------------------------------------------------------ the picker (a read)


def _picker_plan(ctx: Ctx) -> ReadPlan | None:
    """One read: the variants matching the words, or the catalogue's first few when there are
    none. `slots` is where a tap's words arrive (app/routes/command.py)."""
    slots = ctx.slots or {}
    product = str(slots.get("product") or ctx.text or "").strip()[: MAX_WORD_CHARS["product"]]
    return ReadPlan([
        Read("variants", SEARCH_TOOL, {
            "product": product,
            "colour": str(slots.get("colour") or "").strip()[: MAX_WORD_CHARS["colour"]],
            "size": str(slots.get("size") or "").strip()[: MAX_WORD_CHARS["size"]],
            "limit": 8,
        }, source="shopify", cost=90.0, optional=False),
    ], label="order_add_item")


def _picker_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:
    """The picker card, and a sentence that says how many there are to choose from.

    Deferring rather than drawing an empty card is the rule here as everywhere: a card
    offering nothing to add is worse than a sentence saying the words matched nothing, and the
    model can find a product this cannot.
    """
    body = result.values.get("variants")
    if not isinstance(body, dict):
        return RecipeAnswer(answer="", defer="the catalogue did not answer")
    order_id = ctx.entity("order")
    if not order_id:
        # The command checks this before the recipe runs; a recipe that trusted it would draw
        # a picker whose Add button had no order to add to.
        return RecipeAnswer(answer="", defer="no order is open to add to")
    candidates = [c for c in (body.get("candidates") or []) if isinstance(c, dict)]
    if not candidates:
        asked = " ".join(str(v) for v in (body.get("asked") or {}).values() if str(v or "").strip())
        return RecipeAnswer(answer="", defer=f"nothing in the catalogue matches {asked!r}" if asked else "the catalogue is empty")
    label = _order_label(ctx)
    data = variant_picker(body, order_id=order_id, order_number=label, quantity=1)
    surface = Surface(
        surface_type="variant_picker",
        ui_type="variant_picker",
        data=data,
        entity=Entity(kind="order", ref=order_id, label=label),
        title="Add to the order",
        subtitle=f"{data['count']} to choose from" if data["count"] != 1 else "One match",
        freshness=Freshness(source="shopify", complete=not result.partial),
    )
    if data["confident_variant_id"]:
        first = data["candidates"][0]
        variant = f", {first['variant']}" if first["variant"] else ""
        words = f"One match: {first['title']}{variant} at {first['price']}. Tap Add to prepare it."
    else:
        words = f"{data['count']} to choose from. Pick one and tap Add."
    if data["note"]:
        words = f"{words} {data['note']}"
    return RecipeAnswer(
        answer=words, calls=list(result.calls), drawn=[], surfaces=[surface], partial=result.partial,
        trace={"candidates": len(data["candidates"]), "confident": bool(data["confident_variant_id"])},
    )


def _order_label(ctx: Ctx) -> str:
    found = getattr(ctx.branch, "entity", None) or {}
    return str(found.get("label") or "")


register(Recipe(
    recipe_id="order_add_item", required_entities=("order",),
    read_primitives=(SEARCH_TOOL,), parallel_nodes=(("variants",),), ui="variant_picker",
    # Never cached: what is for sale and what is in stock is exactly what must not be stale on
    # the card the owner is about to add from.
    cache_policy=CACHE_NONE, target_ms=1200,
    plan=_picker_plan, render=_picker_render,
))


# ------------------------------------------------------------------ the commands (touch)


def _open_picker(ctx: CommandCtx) -> Outcome:
    """A control on the order card. Names the recipe and the words to narrow it by; reads and
    stages nothing itself (a command is synchronous — see app/commands.py).

    The order is the one on screen. The tablet may name it, and then it must be that one: a
    posted id that is issued but is not what the owner is looking at would prepare a change
    to an order he cannot see.
    """
    entity = getattr(ctx.branch, "entity", None) or {}
    open_order = str(entity.get("ref") or "") if entity.get("kind") == "order" else ""
    if not open_order:
        return Outcome.refused("no_order", "There is no order open to add anything to.")
    asked = ctx.arg("order_id")
    if asked and asked != open_order:
        return Outcome.refused("wrong_order", "That is not the order on screen.")
    slots = {key: ctx.arg(key)[:limit] for key, limit in MAX_WORD_CHARS.items()}
    return Outcome(answer="", changed={"recipe": "order_add_item", "slots": slots,
                                       "entity": {"kind": "order", "ref": open_order, "label": str(entity.get("label") or "")}})


def _stage_add_item(ctx: CommandCtx) -> Outcome:
    """"Add to order" on the picker. The tablet posts which order, which variant and how many
    — three identities and a small integer — and the Mac does everything else.

    What it does NOT post is a single argument of the mutation. The price, the calculated
    order, the new total and what the customer will owe are read and built on the Mac by the
    write tool's PREPARE step (app/tools/shopify_writes.py), stored on the proposal, and sent
    only after the hold. This returns the change to be prepared; `app/routes/command.py`
    prepares it through the same gate and the same action engine a model-proposed change goes
    through, and answers with the confirmation card.

    The order is the one this half has open, and nothing else. A picker is drawn for the order
    on screen (`_open_picker`), but the Add button carries the order id it was drawn with, and
    a picker left on the glass after the owner has moved to another order still posts the old
    one. That order was issued to this conversation, so `may_open` alone would pass it, and the
    card would have been labelled with the NEW order's number while it changed the old one
    (the 2026-09-28 deploy review, round 9, E-01). So a posted order must be the open order;
    anything else is refused, and the label comes from that same validated order. The item is
    bound the same way: when this half's screen holds the picker, the variant must be one of
    its rows, drawn for this order.
    """
    order_id, variant_id = ctx.arg("order_id"), ctx.arg("variant_id")
    entity = getattr(ctx.branch, "entity", None) or {}
    open_order = str(entity.get("ref") or "") if entity.get("kind") == "order" else ""
    if not open_order:
        return Outcome.refused("no_order", "There is no order open to add anything to.")
    if order_id and order_id != open_order:
        return Outcome.refused(
            "wrong_order",
            "That picker was for a different order from the one on screen. Open the picker again on this order.",
        )
    order_id = open_order
    if not variant_id:
        return Outcome.refused("no_target", "That says which order or which item is being added.")
    # Issued to THIS conversation, and of the right kind. The gate checks both again before
    # the tool runs; checking here means the refusal is a sentence rather than a tool error,
    # and that a guessed id never reaches a Shopify read.
    if not may_open(ctx, "order", order_id):
        return Outcome.refused("not_held", "I do not have that order to hand; open it again.")
    if variant_id not in (getattr(ctx.session, "issued_ids", None) or frozenset()):
        return Outcome.refused("unknown_variant", "That item is not one I have looked up; open the picker again.")
    # And the item is one THIS order's picker offered, when this half's screen holds it. An
    # issued variant is any the conversation has been shown — a hoodie from a picker drawn for
    # another order, or from an earlier search — and the Add on this picker can only mean a
    # row of this picker. Where the screen this half last drew holds no picker (a record the
    # Mac keeps bounded, and which a later answer on the half replaces), the checks above are
    # the whole of it: the open order, and an item this conversation looked up; the card that
    # follows names both before the hold.
    picker = _picker_on_screen(ctx.branch)
    if picker is not None:
        if str(picker.get("order_id") or "") != order_id:
            return Outcome.refused(
                "wrong_order",
                "That picker was for a different order from the one on screen. Open the picker again on this order.",
            )
        offered = {str(c.get("variant_id") or "") for c in picker.get("candidates") or [] if isinstance(c, dict)}
        if variant_id not in offered:
            return Outcome.refused("not_on_picker", "That item is not one this order's picker offered; choose it there again.")
    quantity, problem = _quantity(ctx.arg("quantity", "1"))
    if problem:
        return Outcome.refused("bad_quantity", problem)
    # `order_id` IS the open order now, so the label beside it is that order's own.
    return Outcome(answer="", changed={
        "stage": {"tool": WRITE_TOOL, "args": {"order_id": order_id, "variant_id": variant_id, "quantity": quantity}},
        "entity": {"kind": "order", "ref": order_id, "label": str(entity.get("label") or "")},
    })


def _picker_on_screen(branch: Any) -> dict[str, Any] | None:
    """The data of the variant picker this half last drew, or None when its screen holds none.

    Read from `branch.last_ui`, the Mac's own copy of what the half shows (app/session/
    branch.py:shown), which both a tap and a sentence write — never from anything the tablet
    posts, since the question is whether what it posted came from here.
    """
    for item in getattr(branch, "last_ui", None) or []:
        if isinstance(item, dict) and item.get("type") == "variant_picker" and isinstance(item.get("data"), dict):
            return item["data"]
    return None


def _quantity(value: str) -> tuple[int, str]:
    """The stepper's number, as a number. A form field is a string; a quantity that is not a
    small whole number is refused here rather than being clamped, because clamping a typo to
    1 and adding it to a paid order is a change nobody asked for."""
    try:
        quantity = int(str(value or "1").strip())
    except (TypeError, ValueError):
        return 0, "How many is not a number."
    if not 1 <= quantity <= MAX_PICKER_QUANTITY:
        return 0, f"How many must be between 1 and {MAX_PICKER_QUANTITY}."
    return quantity, ""


# Touch only, both of them. A spoken instruction to add something is a model turn, and the
# model stages the same write tool itself.
register_command(Command("order_edit.find", "Find the item to add to this order", _open_picker,
                         voice=False, needs_entity=("order",)))
register_command(Command("order_edit.stage", "Prepare adding the chosen item to this order", _stage_add_item,
                         voice=False, needs_entity=("order",)))


# ------------------------------------------------------------------ the capability state


async def _probe(runtime: Any) -> dict[str, Any]:
    """Whether this Mac could edit an order right now. One read — the scopes the store has
    granted, cached with the rest of the capability table — and never a mutation.

    A store that has not granted `write_order_edits` gets MISSING_SCOPE with the scope named,
    which does two things: the capability card and /health say which permission is wanted, and
    `runtime.withheld_by_family()` stops the model being offered the write tool at all, so it
    does not spend a turn trying an operation the store could only refuse.
    """
    try:
        granted = set(await runtime.shopify.access_scopes())
    except Exception as exc:  # noqa: BLE001 — Shopify not answering is not a missing grant
        return {"state": "TEMPORARILY_UNAVAILABLE",
                "detail": f"the Shopify scope check did not answer ({type(exc).__name__})", "scope": SCOPE}
    if SCOPE not in granted:
        return {"state": "MISSING_SCOPE",
                "detail": f"the store has not granted {SCOPE}; add it on the Dev Dashboard and approve it in the store admin",
                "scope": SCOPE}
    return {"state": "READY", "detail": "ready — an item can be added to an order", "scope": SCOPE}


register_family(CapabilityFamily(
    key="order_edit",
    label="Order item editing",
    area="orders",
    what="Add an item, or a custom item, to an existing order, priced by Shopify before you authorise it",
    operations=(OPERATION, CUSTOM_OPERATION),
    tools=(SEARCH_TOOL, WRITE_TOOL, CUSTOM_WRITE_TOOL),
    scopes=(SCOPE,),
    state="READY",
    probe=_probe,
))
