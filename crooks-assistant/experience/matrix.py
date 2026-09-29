"""What can be reached, and how — worked out from the registries rather than written down.

A matrix maintained by hand is a document that is wrong the first time somebody adds a command
and forgets it. Every column here is read from the thing that actually decides:

    voice            said or typed, it is a model turn — every sentence is, since the owner had
                     the word-matching lane removed on 28 September 2026 — so one row stands
                     for all of them, and no command is reached by words
    touch            a semantic command exists for it (app/commands.py REGISTRY), or a tap
                     names a read recipe (app/recipes.py RECIPES)
    touch → voice    the command arms a spoken continuation (commands.SPOKEN_CONTROLS)
    no model         answered without the model: every tap is
    model            the model answers it: every sentence
    fixture test     a golden scenario exercises it (experience/scenarios.py)
    live read test   the same scenario is safe to run against the real shop

The only hand-written part is which scenario covers which operation, and that is a mapping of
names — if a scenario is renamed the matrix says "not covered" rather than quietly lying.
"""

from __future__ import annotations

from typing import Any

# Which golden scenario exercises which semantic operation. A name not in SCENARIOS shows as
# uncovered rather than being silently believed.
COVERAGE: dict[str, tuple[str, ...]] = {
    # Anything said or typed: a model turn, with the reads Claude makes drawn as cards.
    "model_turn": ("order_lookup", "today_orders", "customer_history", "linked_entities", "unsupported_edit",
                   "split_branches", "enrichment", "abandoned_checkouts", "abandoned_window", "compose_open",
                   "compose_dictated", "discount_sentence_defers", "graph_order_to_email",
                   "order_add_item_sentence_defers", "recording_is_observability", "compose_send_spoken"),
    "surface.tab": ("tabs", "nav_click_path"),
    "surface.expand": (),
    "surface.scroll": ("nav_click_path",),
    "open.entity": ("linked_entities", "nav_click_path", "graph_thread_to_order"),
    "order.open_shipping": ("tabs",),
    "order.open_items": (),
    "customer.open_orders": (),
    "voice.bind": ("order_lookup",),
    "voice.cancel": (),
    "navigation.back": ("back", "nav_click_path", "nav_branch_isolation"),
    "navigation.home": ("nav_home_landing",),
    "navigation.forward": (),
    "workflow.next": ("next_previous", "nav_next_position"),
    "workflow.previous": ("next_previous",),
    "interaction.stop": (),
    # The dock's four places, tapped: each names a read recipe.
    "landing_orders": ("landing_orders", "next_previous"),
    "landing_inbox": ("landing_inbox", "needs_reply", "graph_thread_to_order"),
    "landing_sales": ("landing_sales",),
    "landing_products": ("landing_products",),
    "open.area": ("landing_orders", "landing_inbox", "landing_sales", "landing_products", "landing_unknown"),
    "order_add_item": ("order_add_item_picker", "order_add_item_ambiguous", "order_add_item_cancelled"),
    "compose.field": ("compose_dictated",),
    "compose.stage": ("compose_stage",),
    "draft.send_instead": ("compose_send_instead",),
    "order_edit.find": ("order_add_item_picker", "order_add_item_ambiguous", "order_add_item_cancelled",
                        "order_add_item_stale_picker"),
    "order_edit.stage": ("order_add_item_picker", "order_add_item_stale_picker"),
    # The commerce families (brief sections 11 to 14): each creation is reached by touch, and
    # by the model through its tool.
    "discount_code": ("discount_new_code", "discount_code_taken"),
    "discount.open": ("discount_new_code", "discount_code_taken"),
    "discount.field": ("discount_new_code", "discount_code_taken"),
    "discount.stage": ("discount_new_code",),
    "order.open": ("order_new", "order_new_ambiguous"),
    "order.field": ("order_new", "order_new_ambiguous"),
    "order.additem": ("order_new",),
    "order.stage": ("order_new", "order_by_voice"),
    "credit.field": ("store_credit_give",),
    "credit.stage": ("store_credit_give",),
    # `order_customer`, `order_line`, `order.choose`, `order.customer`, `order.removeitem`,
    # `discount.choose`, `discount.discard`, `order.discard` and `credit.discard` have no
    # scenario of their own: each is asserted in tests/ (test_order_create.py,
    # test_discounts.py, test_store_credit.py), where a refused option and a discarded form
    # can be read without a transcript. Shown as uncovered, which is honest.
    "order_customer": (),
    "order_line": (),
    "discount.choose": (),
    "discount.discard": (),
    "order.choose": (),
    "order.customer": (),
    "order.removeitem": (),
    "order.discard": (),
    "credit.discard": (),
}

# Which write tools each staging command CAN prepare. A tap on one of these runs a write tool's
# PREPARE step through the action engine — which one the command's module decides at run time
# (a composer's Save draft is `gmail_draft_new`, its Send `gmail_send_new`, a reply's the reply
# tools), and a tap can be refused before anything is prepared, which some scenarios exist to
# show. So posting a command is not evidence that any particular write was staged: this is the
# set a scenario's declaration below may draw from, and `tests/test_tool_matrix.py` holds every
# `.stage` command in the registry to an entry, and every tool named to a registered write.
STAGES: dict[str, tuple[str, ...]] = {
    "address.stage": ("shopify_order_shipping_address_set",),
    "compose.stage": ("gmail_draft_new", "gmail_send_new", "gmail_draft_reply", "gmail_send_reply"),
    "draft.send_instead": ("gmail_send_new", "gmail_send_reply"),
    "discount.stage": ("shopify_discount_create",),
    "order.stage": ("shopify_order_create",),
    "order_edit.stage": ("shopify_order_add_item",),
    "credit.stage": ("shopify_store_credit_add",),
}

# Which write tools each scenario's TAPS really prepare, scenario by scenario. Declared rather
# than inferred, because only a run can tell which write a staging command prepared or whether
# it was refused (the 2026-09-28 deploy review, round 9, H-06: the audit used to credit every
# write a posted command could stage, so the stale-picker scenario, whose Add is refused by
# design, was reported as staging the add). Held both ways: `experience/tool_matrix.py` credits
# a declared tool only when the scenario's code posts a command that can prepare it, and
# `tests/test_experience.py` runs every scenario and requires the writes the audit credits it
# with to be exactly the writes it staged. A write the scenario's scripted MODEL stages is read
# off its code instead (`tool_matrix.scenario_strings`) and held to the same run.
TAP_STAGED: dict[str, tuple[str, ...]] = {
    "compose_stage": ("gmail_draft_new",),
    "compose_send_instead": ("gmail_draft_new", "gmail_send_new"),
    "compose_send_spoken": ("gmail_draft_new",),
    "discount_new_code": ("shopify_discount_create",),
    "order_new": ("shopify_order_create",),
    "order_by_voice": ("shopify_order_create",),
    "order_add_item_picker": ("shopify_order_add_item",),
    "store_credit_give": ("shopify_store_credit_add",),
}

# Operations a live read-only run must not exercise, whatever their scenario does. Nothing is
# here yet because every scenario is a read — the list exists so that adding a write-shaped
# scenario has somewhere obvious to declare it.
NOT_LIVE_SAFE: frozenset[str] = frozenset()


def build() -> list[dict[str, Any]]:
    """One row per semantic operation, derived."""
    from app import commands, recipes
    from app.families import load_all
    from experience.scenarios import BY_NAME

    load_all()
    rows: list[dict[str, Any]] = []

    # Every sentence, said or typed: the model's, with its tools. One row, because nothing on
    # the Mac tells one sentence from another any more.
    scenarios = COVERAGE.get("model_turn", ())
    rows.append({
        "operation": "model_turn",
        "reached_by": "a sentence",
        "voice": True, "touch": False, "touch_then_voice": False,
        "no_model": False, "model": True,
        "fixture_test": [s for s in scenarios if s in BY_NAME],
        "live_read_test": "model_turn" not in NOT_LIVE_SAFE and bool(scenarios),
    })

    for recipe in recipes.RECIPES.values():
        scenarios = COVERAGE.get(recipe.recipe_id, ())
        rows.append({
            "operation": recipe.recipe_id,
            "reached_by": "tap recipe",
            "voice": False, "touch": True, "touch_then_voice": False,
            "no_model": True, "model": False,
            "fixture_test": [s for s in scenarios if s in BY_NAME],
            "live_read_test": recipe.recipe_id not in NOT_LIVE_SAFE and bool(scenarios),
        })

    for command in commands.public():
        name = command["name"]
        scenarios = COVERAGE.get(name, ())
        rows.append({
            "operation": name,
            "reached_by": "semantic command",
            "voice": bool(command["voice"]),
            "touch": bool(command["touch"]),
            "touch_then_voice": bool(command.get("touch_then_voice")),
            # A command is deterministic by construction: it never consults the model.
            "no_model": True,
            "model": False,
            "fixture_test": [s for s in scenarios if s in BY_NAME],
            "live_read_test": name not in NOT_LIVE_SAFE and bool(scenarios),
        })

    rows.sort(key=lambda r: (r["reached_by"], r["operation"]))
    return rows


def uncovered() -> list[str]:
    """Operations no golden scenario exercises. Printed rather than hidden: a matrix whose
    only job is to look complete is worse than no matrix."""
    return [r["operation"] for r in build() if not r["fixture_test"]]


def _tick(value: Any) -> str:
    return "✓" if value else "·"


def markdown() -> str:
    rows = build()
    out = [
        "# Feature matrix",
        "",
        "Derived from the command registry, the tap recipes and the scenario list — not",
        "maintained by hand. Every sentence is a model turn. A row with no scenario is a gap, and",
        "is listed as one below.",
        "",
        "| Operation | Reached by | Voice | Touch | Touch→Voice | No model | Model | Fixture test | Live read |",
        "|---|---|:-:|:-:|:-:|:-:|:-:|---|:-:|",
    ]
    for r in rows:
        out.append(
            f"| `{r['operation']}` | {r['reached_by']} | {_tick(r['voice'])} | {_tick(r['touch'])} "
            f"| {_tick(r['touch_then_voice'])} | {_tick(r['no_model'])} | {_tick(r['model'])} "
            f"| {', '.join(r['fixture_test']) or '—'} | {_tick(r['live_read_test'])} |"
        )
    gaps = uncovered()
    out += ["", f"## Not covered by a scenario ({len(gaps)})", ""]
    out += [f"- `{name}`" for name in gaps] or ["- none"]
    out += [""]
    return "\n".join(out)
