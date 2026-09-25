"""The fast lane: what it takes, what it refuses to take, and what it does when it takes it.

The rule this file exists to hold: being quick is never a reason to answer a different
question. Every case below that ends in NORMAL is a case where the Mac could have guessed
and chose not to.
"""

from __future__ import annotations

import json

import pytest

from app.analytics import sets as working_sets
from app.fastpath import choose_lane, recipe_for, resolve
from app.fastpath.intent import mutating
from app.fastpath.library import dimension_from, period_from
from app.fastpath.models import Ctx
from app.fastpath.recipes import RECIPES, assert_read_only
from app.fastpath.runner import _unresolved, run
from app.session.branch import Branch, Workflow
from app.session.models import Session


@pytest.fixture()
def branch():
    return Branch(branch_id="br_test", session_id="s1")


def lane_for(text: str, branch) -> tuple[str, str]:
    intent = resolve(text, branch=branch)
    recipe = recipe_for(intent.family) if intent.family else None
    return choose_lane(intent, recipe=recipe, text=text)[0], intent.family


# --------------------------------------------------------------- what it takes

FAST_CASES = [
    ("next", "working_set_next"),
    ("go back", "navigation_back"),
    ("what can you do?", "capability_summary"),
    ("what more can you do now?", "capability_delta"),
    ("order 1938", "order_lookup"),
    ("where is order 1938", "order_status_lookup"),
    ("has order 1938 shipped?", "order_status_lookup"),
    ("read me the full address for order 1938", "order_address_lookup"),
    ("what sold best this month", "best_sellers_period"),
    ("how were sales last week", "sales_breakdown_period"),
    ("which orders are late", "delayed_orders"),
    ("what is running out", "stock_cover_analysis"),
    ("who needs replying to", "needs_reply"),
]


@pytest.mark.parametrize(("text", "family"), FAST_CASES)
def test_the_ordinary_questions_take_the_fast_lane(text, family, branch):
    lane, got = lane_for(text, branch)
    assert (lane, got) == ("FAST", family), text


# ------------------------------------------------------------ what it refuses

NEVER_FAST = [
    ("cancel order 1938", "a change"),
    ("refund order 1938", "a change"),
    ("add a note to 1938 saying he called", "a change"),
    ("archive those emails", "a change"),
    ("email everyone who has not replied", "a change"),
    ("how much stock of the yard jeans", "one product, not a restock ranking"),
    ("who are our top customers", "a customer ranking makes a set"),
    ("show me order 1938 and tell me if the customer has written in", "two questions"),
]


@pytest.mark.parametrize(("text", "why"), NEVER_FAST)
def test_what_the_fast_lane_declines(text, why, branch):
    lane, _ = lane_for(text, branch)
    assert lane in ("NORMAL", "DEEP"), f"{text!r} should not be fast: {why}"


# Routing is structure; whether the data supports a deterministic answer is the recipe's own
# check. These read as best-seller questions and are routed as such — and then the recipe
# declines to build a plan, so the turn goes to Claude with nothing invented.
DECLINED_AT_PLAN = [
    ("what sold best by material last month", "best_sellers_period"),
    ("how does this week compare against last week", "sales_breakdown_period"),
]


@pytest.mark.parametrize(("text", "recipe_id"), DECLINED_AT_PLAN)
def test_a_recipe_declines_to_plan_what_it_cannot_read_exactly(text, recipe_id, branch):
    session = Session(session_id="s1")
    intent = resolve(text, branch=branch)
    recipe = recipe_for(intent.family)
    assert recipe is not None and recipe.recipe_id == recipe_id
    ctx = Ctx(runtime=None, session=session, branch=branch, intent=intent, text=text)
    assert recipe.plan(ctx) is None, f"{text!r} must not be planned deterministically"


def test_a_mutation_verb_leaves_the_lane_whatever_else_it_says(branch):
    for text in ("cancel it", "refund the lot", "archive them", "fulfil 1938", "tag these as vip"):
        assert resolve(text, branch=branch).family == ""
        assert resolve(text, branch=branch).reason == "asks for a change"


def test_a_gerund_after_a_question_word_is_not_an_instruction():
    assert not mutating(("who", "needs", "replying", "to"))
    assert not mutating(("which", "customers", "are", "waiting", "on", "an", "email"))
    assert mutating(("reply", "to", "millie"))
    assert mutating(("email", "them", "all"))
    assert mutating(("cancel", "it")) and mutating(("what", "should", "i", "cancel"))


def test_two_clauses_are_never_one_fast_answer(branch):
    one = resolve("order 1938", branch=branch)
    two = resolve("order 1938 and what did she buy before", branch=branch)
    assert one.family == "order_lookup" and two.family == ""


# --------------------------------------------------------------- the pieces

def test_the_period_map_declines_what_it_cannot_read():
    assert period_from(("sales", "this", "month")) == "this_month"
    assert period_from(("best", "sellers", "last", "week")) == "last_week"
    assert period_from(("last", "7", "days")) == "last_7_days"
    assert period_from(("how", "are", "we", "doing")) is None
    assert period_from(("this", "week", "against", "last", "week")) is None


def test_the_dimension_map_declines_two_and_declines_the_unknown():
    assert dimension_from(("by", "colour")) == "colour"
    assert dimension_from(("sales", "per", "day")) == "day"
    assert dimension_from(("by", "material")) is None
    assert dimension_from(("by", "colour", "and", "by", "size")) is None


def test_every_recipe_is_read_only_and_declared():
    import app.tools.analytics_tools  # noqa: F401
    import app.tools.gmail_tools  # noqa: F401
    import app.tools.shopify_tools  # noqa: F401

    assert_read_only()
    for recipe in RECIPES.values():
        assert recipe.plan is not None and recipe.render is not None, recipe.recipe_id
        assert recipe.min_confidence >= 0.7, recipe.recipe_id
        for group in recipe.parallel_nodes:
            assert group, recipe.recipe_id


def test_a_recipe_that_names_a_write_tool_is_a_crash_not_a_surprise():
    from dataclasses import replace

    import app.tools.shopify_writes  # noqa: F401 — registers the write tool this names

    victim = replace(RECIPES["order_lookup"], read_primitives=("shopify_order_note_append",))
    with pytest.raises(RuntimeError, match="cannot write"):
        assert_read_only({"victim": victim})


# ------------------------------------------------------------- the cursor

def test_next_is_a_cursor_move_and_one_read(branch):
    session = Session(session_id="s1")
    ws = working_sets.create(session, kind="orders", members=["o1", "o2", "o3"], label="late orders")
    branch.workflow = Workflow(workflow_id="wf1", set_id=ws.set_id, kind="orders", total=3, cursor=0)
    recipe = RECIPES["working_set_next"]
    ctx = Ctx(runtime=None, session=session, branch=branch, intent=resolve("next", branch=branch), text="next")
    assert _unresolved(recipe, ctx) == ""
    from app.fastpath.runner import _advance

    _advance(recipe, ctx)
    assert branch.workflow.cursor == 1 and branch.workflow.position == 2
    _advance(recipe, ctx)
    _advance(recipe, ctx)
    assert branch.workflow.cursor == 2, "the cursor stops at the end rather than running past it"
    _advance(RECIPES["working_set_previous"], ctx)
    assert branch.workflow.cursor == 1


def test_next_with_a_listing_but_no_workflow_adopts_the_newest_set(branch):
    session = Session(session_id="s1")
    working_sets.create(session, kind="orders", members=["o1", "o2"], label="late")
    ctx = Ctx(runtime=None, session=session, branch=branch, intent=resolve("next", branch=branch), text="next")
    assert _unresolved(RECIPES["working_set_next"], ctx) == ""
    assert branch.workflow is not None and branch.workflow.cursor == -1
    from app.fastpath.runner import _advance

    _advance(RECIPES["working_set_next"], ctx)
    assert branch.workflow.cursor == 0, "the first Next lands on the first member"


def test_next_with_nothing_open_defers_rather_than_guessing(branch):
    session = Session(session_id="s1")
    ctx = Ctx(runtime=None, session=session, branch=branch, intent=resolve("next", branch=branch), text="next")
    assert _unresolved(RECIPES["working_set_next"], ctx) == "the set being worked through"


async def test_a_recipe_that_cannot_answer_defers_and_never_invents(branch):
    """A recipe with nothing to read defers rather than answering from nothing.

    order_lookup is the case: no order number in the words and no order open, so there is
    nothing to look up. It must go to Claude rather than pick an order.
    """
    session = Session(session_id="s1")
    session.turn_id = "turn_x"
    recipe = RECIPES["order_lookup"]

    class Runtime:
        pass

    # No number in the words and no order open: `_order_plan` has nothing to build a read
    # from and returns None, whatever store happens to be bound in this process.
    assert branch.entity is None
    answer = await run(recipe, Ctx(runtime=Runtime(), session=session, branch=branch,
                                   intent=resolve("show me the order", branch=branch), text="show me the order"))
    assert answer.deferred, f"answered {answer.answer!r} with nothing to look up"


async def test_the_capability_delta_answers_the_answerable_part(branch):
    """With no previous build recorded there is no delta — but "what more can you do now" is
    still a question about this Mac, and this Mac has the register that answers it.

    It used to defer, which sent a question about the assistant to the model and drew no card
    at all. Answering the summary is not inventing: it comes from the same registry, and the
    spoken line says plainly what it is.
    """
    session = Session(session_id="s1")
    session.turn_id = "turn_x"
    recipe = RECIPES["capability_delta"]

    class Runtime:
        capability_record = None
        manifest = None
        build = "test"

        class settings:      # noqa: N801 — a stand-in, not a class in the app
            writes_enabled = False

    answer = await run(recipe, Ctx(runtime=Runtime(), session=session, branch=branch,
                                   intent=resolve("what more can you do now", branch=branch), text="x"))
    assert not answer.deferred and answer.answer.strip()
    assert answer.surfaces and answer.surfaces[0].surface_type == "capability"
    # Never claims a change is possible while changes are off.
    assert answer.surfaces[0].data["writes_enabled"] is False
    assert answer.surfaces[0].data["counts"]["changes"] == 0


# --------------------------------------------------------------- navigation

def test_the_branch_back_stack_restores_the_tab_and_the_scroll(branch):
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


def test_a_branch_remembers_a_name_it_resolved_and_forgets_it_when_it_is_old(branch):
    branch.learn("millie rogers", "customer", "c1", "Millie Rogers", clock=lambda: 1000.0)
    assert branch.resolve("Millie Rogers", clock=lambda: 1100.0)["ref"] == "c1"
    assert branch.resolve("millie rogers", clock=lambda: 9000.0) is None


# ------------------------------------------------- the acceptance scenarios, in miniature

@pytest.fixture()
async def turning(monkeypatch):
    """/turn over a real app with fake sources: what the tablet would actually get."""
    import httpx

    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk
    from app.providers.base import TurnResult
    from app.session.manager import SessionManager
    from app.tools import shopify_tools
    from tests.test_context import Store, inbox

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", lambda self: (True, "fake scribe"))
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    class Provider:
        prompts: list[str] = []

        async def start(self): pass
        async def stop(self): pass
        async def health(self): return True, "fake"
        async def reset_session(self, session_id): pass
        async def set_system_prompt(self, prompt): pass
        async def interrupt(self, session_id): return True

        async def turn(self, session_id, text):
            Provider.prompts.append(text)
            return TurnResult(text="the model answered", session_id=session_id)

    Provider.prompts = []
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = Provider()
        runtime.sessions = SessionManager()
        store = Store()
        runtime.shopify = store
        shopify_tools.bind(store, threads_for=inbox())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.runtime = runtime
            c.provider = Provider
            yield c


async def ask(client, text: str, session_id: str = "acc") -> dict:
    response = await client.post("/turn", json={"text": text, "session_id": session_id})
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_the_capability_question_is_answered_from_the_manifest_not_the_model(turning):
    body = await ask(turning, "what can you do?")
    assert body["lane"] == "FAST" and body["recipe_id"] == "capability_summary"
    assert turning.provider.prompts == []
    assert "I can " in body["answer"] and "shopify_" not in body["answer"]
    assert body["performance"]["model_calls"] == 0


async def test_b_an_order_lookup_is_two_reads_a_card_and_no_model(turning):
    body = await ask(turning, "show me order 1938")
    assert body["lane"] == "FAST"
    assert [c["name"] for c in body["tool_calls"]] == ["shopify_find_order", "shopify_order_detail"]
    assert any(i["type"] == "order" for i in body["ui"])
    assert turning.provider.prompts == []


async def test_g_the_full_address_is_read_when_it_is_asked_for(turning):
    await ask(turning, "show me order 1938")
    body = await ask(turning, "read me the full address on that order")
    assert body["lane"] == "FAST" and body["recipe_id"] == "order_address_lookup"
    assert "ships to" in body["answer"].lower()
    assert any(char.isdigit() for char in body["answer"]), "a street number is a street number"


async def test_l_next_is_a_cursor_move_not_a_question_for_the_model(turning):
    from app.analytics import sets as working_sets

    await ask(turning, "show me order 1938")
    session = turning.runtime.sessions.get("acc")
    entity = session.branch().entity
    working_sets.create(session, kind="orders", members=[entity["ref"]], label="to work through")
    body = await ask(turning, "next")
    assert body["lane"] == "FAST" and body["recipe_id"] == "working_set_next"
    assert turning.provider.prompts == [], "no model call for a cursor increment"
    assert "1 of 1" in body["answer"]
    assert body["branch"]["workflow"]["position"] == 1


async def test_m_a_change_is_never_the_fast_lanes(turning):
    body = await ask(turning, "add a note to order 1938 saying he called")
    assert body["lane"] == "NORMAL"
    assert turning.provider.prompts, "a change goes to Claude, and through the gate"


async def test_r_navigation_is_answered_from_where_the_conversation_is(turning):
    await ask(turning, "show me order 1938")
    body = await ask(turning, "go back")
    assert body["lane"] == "FAST" and body["recipe_id"] == "navigation_back"
    assert turning.provider.prompts == []


async def test_s_no_speech_keeps_the_context_and_says_so_briefly(turning):
    await ask(turning, "show me order 1938")
    before = turning.runtime.sessions.get("acc").branch().entity
    body = await ask(turning, "   ")
    assert body["error_kind"] == "empty" and body["answer"] == "I did not catch that."
    assert body["ui"] == [] or all(i["type"] != "order" for i in body["ui"])
    assert turning.runtime.sessions.get("acc").branch().entity == before, "the screen keeps its place"


async def test_u_every_turn_records_which_lane_answered_it(turning):
    fast = await ask(turning, "what can you do?")
    slow = await ask(turning, "add a note to order 1938 saying he called")
    assert fast["performance"]["fast_path_hit"] is True and fast["performance"]["model_calls"] == 0
    assert slow["performance"]["fast_path_hit"] is False and slow["performance"]["model_calls"] == 1
    assert slow["performance"]["model_input_chars"] > 0 and slow["performance"]["tool_schema_bytes"] > 0
    assert fast["performance"]["branch_id"] and fast["performance"]["turn_total_ms"] > 0


# ------------------------------------------- what the adversarial review found (pass D)

DIRECTION_IS_NOT_A_DIRECTION = [
    ("what's the last order", "an order, not the one before this one"),
    ("next week's sales", "a period, not the next member"),
    ("read me the last email", "an email, not the one before this one"),
    ("back to the previous customer", "a customer"),
]


@pytest.mark.parametrize(("text", "why"), DIRECTION_IS_NOT_A_DIRECTION)
def test_a_direction_word_beside_a_thing_is_not_a_direction(text, why, branch):
    """"Next" is a direction. "Next week's sales" is a question about sales, and was being
    answered by walking a working set — a question about an order answered with a customer,
    at "0 of 3", with the owner's place in the set moved."""
    from app.session.branch import Workflow

    branch.workflow = Workflow(workflow_id="wf", set_id="set_a", kind="customers", total=3, cursor=0)
    intent = resolve(text, branch=branch)
    assert intent.family not in ("working_set_next", "working_set_previous", "navigation_back"), f"{text!r}: {why}"


def test_the_bare_directions_still_work(branch):
    from app.session.branch import Workflow

    branch.workflow = Workflow(workflow_id="wf", set_id="set_a", kind="orders", total=3, cursor=0)
    assert resolve("next", branch=branch).family == "working_set_next"
    assert resolve("previous", branch=branch).family == "working_set_previous"
    assert resolve("the one before", branch=branch).family == "working_set_previous"
    assert resolve("the one before that", branch=branch).family == "working_set_previous"
    assert resolve("back", branch=branch).family == "navigation_back"


def test_a_customer_is_described_from_the_shape_shopify_actually_returns():
    """`shape_customer_history` gives `orders` (a count) and `spent` (money as a string).
    Reading them as `orders_count` and `total_spent` announced every customer as having zero
    orders and no lifetime spend — a confident sentence that was simply false."""
    from app.fastpath.library import _customer_line

    real = {"name": "Millie Rogers", "orders": 3, "spent": "410.00 GBP", "recent": []}
    assert _customer_line(real) == "Millie Rogers: 3 orders, 410.00 GBP in total."
    assert _customer_line({"name": "Gus", "orders": 1, "spent": "60.00 GBP"}) == "Gus: 1 order, 60.00 GBP in total."
    assert _customer_line({"name": "New", "orders": 0, "spent": ""}) == "New: no orders yet."
    # Shopify did not say. Nothing is invented in either direction.
    unknown = _customer_line({"name": "Unknown", "orders": None, "spent": "120.00 GBP"})
    assert "0 order" not in unknown and "120.00 GBP" in unknown


def test_a_comparison_that_was_asked_for_is_spoken():
    """The engine's shape is {metric: {from, to, delta, pct}}. Reading a `revenue_pct` that
    has never existed meant the comparison was paid for in query cost and thrown away."""
    from app.fastpath.library import _breakdown_render
    from app.fastpath.models import Ctx
    from app.reads.scheduler import ReadResult

    body = {
        "period": {"label": "this week"}, "totals": {"revenue": 1240.5, "orders": 42, "aov": 29.54},
        "currency": "GBP",
        "compare": {"period": {"label": "last week"}, "change": {"revenue": {"from": 1000.0, "to": 1240.5, "delta": 240.5, "pct": 24.1}}},
    }
    result = ReadResult(values={"agg": body})
    ctx = Ctx(runtime=None, session=Session(session_id="s"), branch=Branch(branch_id="b"), intent=resolve("how were sales this week", branch=None), text="x")
    answer = _breakdown_render(ctx, result).answer
    assert "£1,240.50" in answer and "42 orders" in answer
    assert "24% up on last week" in answer
    assert "this_week" not in answer, "a slug is not how a person says a period"


def test_a_count_is_how_many_there_are_not_how_many_fitted():
    from app.fastpath.library import _how_many

    assert _how_many({"row_count": 61, "truncated": True}, 25) == "61 (showing 25)"
    assert _how_many({"row_count": 4}, 4) == "4"
    assert _how_many({}, 7) == "7"


def test_a_read_that_is_not_complete_says_so_in_the_answer():
    from app.fastpath.library import _hedge

    assert _hedge({"complete": True}) == ""
    assert _hedge({}) == ""
    hedged = _hedge({"complete": False, "note": "Shopify could not be read fully; figures cover what the server holds."})
    assert "cover what the server holds" in hedged
    assert "still reading" in _hedge({"complete": False})


def test_the_two_period_guard_is_not_defeated_by_a_default(branch):
    """`period_from` declines an ambiguous two-period question so the turn goes to Claude.
    Defaulting to thirty days over that decline answered a question about two named windows
    with a month."""
    from app.fastpath.library import _best_sellers_plan
    from app.fastpath.models import Ctx

    session = Session(session_id="s")
    for text in ("what sold best this week compared to last week", "what sold best today or yesterday"):
        intent = resolve(text, branch=branch)
        if intent.family != "best_sellers_period":
            continue
        assert _best_sellers_plan(Ctx(runtime=None, session=session, branch=branch, intent=intent, text=text)) is None, text
    # With no period named at all, the default is still there and still sensible.
    plan = _best_sellers_plan(Ctx(runtime=None, session=session, branch=branch, intent=resolve("what sold best", branch=branch), text="x"))
    assert plan is not None and plan.reads[0].args["period"] == "last_30_days"


def test_a_name_the_branch_resolved_is_never_written_down(branch):
    """`Signals.as_dict()` goes to the timeline on every turn. A customer's name is not an
    id, a count or a controlled word, and telemetry carries only those."""
    branch.learn("millie rogers", "customer", "c1", "Millie Rogers")
    recorded = resolve("has millie rogers bought before", branch=branch).public()
    assert recorded["signals"]["known_name"] is True
    assert "millie" not in json.dumps(recorded).lower()


def test_what_did_you_do_is_not_a_question_about_capabilities(branch):
    for text in ("what did you do", "what have you done", "what did you change"):
        assert resolve(text, branch=branch).family != "capability_summary", text
    assert resolve("what can you do", branch=branch).family == "capability_summary"
    assert resolve("what else are you able to do", branch=branch).family == "capability_summary"


def test_money_is_one_format_whichever_shape_it_arrived_in():
    from app.fastpath.library import _money

    assert _money("45.00 GBP") == "£45.00"
    assert _money(1240.5) == "£1,240.50"
    assert _money(99.0, "USD") == "$99.00"
    assert _money("12.00 EUR") == "€12.00"
    assert _money(None) == ""


def test_a_recipe_naming_a_tool_the_build_does_not_carry_is_a_crash():
    from dataclasses import replace

    from app.fastpath.recipes import RECIPES, assert_read_only

    victim = replace(RECIPES["order_lookup"], read_primitives=("shopify_invented_tool",))
    with pytest.raises(RuntimeError, match="not a registered tool"):
        assert_read_only({"victim": victim})
