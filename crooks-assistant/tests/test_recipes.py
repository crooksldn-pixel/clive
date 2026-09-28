"""The recipes a tap names: read-only by construction, and the landings' own words.

Carried over from the fast lane's tests when that lane was removed (28 September 2026): the
same guarantees now hold for the only recipes left, the ones a button names.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app import recipes
from app.families import landings, load_all
from app.reads.scheduler import ReadResult
from app.session.branch import Branch
from app.session.models import Session

load_all()


def test_every_recipe_is_read_only_and_declared():
    import app.tools.analytics_tools  # noqa: F401
    import app.tools.gmail_tools  # noqa: F401
    import app.tools.shopify_tools  # noqa: F401

    recipes.assert_read_only()
    assert recipes.RECIPES, "the landings and the forms register their recipes on load"
    for recipe in recipes.RECIPES.values():
        assert recipe.plan is not None and recipe.render is not None, recipe.recipe_id
        for group in recipe.parallel_nodes:
            assert group, recipe.recipe_id


def test_only_taps_have_recipes():
    """What is left is what a button names: the dock's four places and the forms' reads."""
    assert set(recipes.RECIPES) == {
        "landing_orders", "landing_inbox", "landing_sales", "landing_products",
        "order_customer", "order_line", "order_add_item", "discount_code",
    }


def test_a_recipe_that_names_a_write_tool_is_a_crash_not_a_surprise():
    import app.tools.shopify_writes  # noqa: F401 — registers the write tool this names

    victim = replace(recipes.RECIPES["landing_orders"], read_primitives=("shopify_order_note_append",))
    with pytest.raises(RuntimeError, match="cannot write"):
        recipes.assert_read_only({"victim": victim})


def test_a_recipe_naming_a_tool_the_build_does_not_carry_is_a_crash():
    victim = replace(recipes.RECIPES["landing_orders"], read_primitives=("shopify_invented_tool",))
    with pytest.raises(RuntimeError, match="not a registered tool"):
        recipes.assert_read_only({"victim": victim})


async def test_a_recipe_that_needs_an_open_order_refuses_without_one():
    session = Session(session_id="s")
    ctx = recipes.Ctx(runtime=None, session=session, branch=session.branch())
    answer = await recipes.run(recipes.RECIPES["order_add_item"], ctx)
    assert answer.deferred and "order" in answer.defer


# ------------------------------------------------------------------ the landings' words


def test_a_comparison_that_was_asked_for_is_spoken():
    """The engine's shape is {metric: {from, to, delta, pct}}. Reading a `revenue_pct` that
    has never existed meant the comparison was paid for in query cost and thrown away."""
    body = {
        "period": {"label": "this week"}, "totals": {"revenue": 1240.5, "orders": 42, "aov": 29.54},
        "currency": "GBP",
        "compare": {"period": {"label": "last week"}, "change": {"revenue": {"from": 1000.0, "to": 1240.5, "delta": 240.5, "pct": 24.1}}},
    }
    ctx = recipes.Ctx(runtime=None, session=Session(session_id="s"), branch=Branch(branch_id="b"))
    answer = landings._week_render(ctx, ReadResult(values={"agg": body})).answer
    assert "£1,240.50" in answer and "42 orders" in answer
    assert "24% up on last week" in answer
    assert "this_week" not in answer, "a slug is not how a person says a period"


def test_a_count_is_how_many_there_are_not_how_many_fitted():
    assert landings._how_many({"row_count": 61, "truncated": True}, 25) == "61 (showing 25)"
    assert landings._how_many({"row_count": 4}, 4) == "4"
    assert landings._how_many({}, 7) == "7"


def test_a_read_that_is_not_complete_says_so_in_the_answer():
    assert landings._hedge({"complete": True}) == ""
    assert landings._hedge({}) == ""
    hedged = landings._hedge({"complete": False, "note": "Shopify could not be read fully; figures cover what the server holds."})
    assert "cover what the server holds" in hedged
    assert "still reading" in landings._hedge({"complete": False})


def test_money_is_one_format_whichever_shape_it_arrived_in():
    assert landings._money("45.00 GBP") == "£45.00"
    assert landings._money(1240.5) == "£1,240.50"
    assert landings._money(99.0, "USD") == "$99.00"
    assert landings._money("12.00 EUR") == "€12.00"
    assert landings._money(None) == ""


def test_the_branch_back_stack_restores_the_tab_and_the_scroll():
    branch = Branch(branch_id="br_test", session_id="s1")
    branch.visit("order", "o1", "#1938", tab="overview")
    branch.mark(tab="shipping", scroll=420)
    branch.visit("customer", "c1", "Millie Rogers", tab="orders")
    assert branch.entity["ref"] == "c1"
    back = branch.back()
    assert back.ref == "o1" and branch.tab == "shipping" and branch.scroll == 420
    forward = branch.forward()
    assert forward.ref == "c1" and branch.tab == "orders"
    branch.visit("order", "o2", "#1939")
    assert branch.forward() is None, "going somewhere new truncates the forward history"
