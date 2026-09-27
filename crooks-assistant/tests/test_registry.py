from __future__ import annotations

import pytest

from app.tools import registry
from app.tools.gate import Tier


def test_all_day1_tools_are_registered():
    from app.tools import gmail_tools, mock, shopify_tools  # noqa: F401

    names = registry.names()
    for expected in (
        "mock_echo", "mock_slow", "mock_danger",
        "shopify_find_order", "shopify_order_detail", "shopify_list_orders",
        "shopify_find_customer", "shopify_inventory", "shopify_sales_summary",
        "shopify_product_info", "gmail_search", "gmail_read_thread",
    ):
        assert expected in names


def test_tiers_match_the_gate():
    from app.tools.gate import classify

    for spec in registry.all_specs():
        if spec.issued_id_args:
            continue  # need an issued id to be anything but denied; covered in test_actions.py
        assert classify(spec.name, {"query": "x", "product": "x", "word": "x"}).tier == spec.tier, spec.name


def test_duplicate_registration_is_an_error():
    with pytest.raises(ValueError):
        registry.tool(name="mock_echo", description="d", input_schema={"type": "object"})(lambda: None)


def test_normalise_tool_name():
    assert registry.normalise_tool_name("mcp__crooks__shopify_inventory") == "shopify_inventory"
    assert registry.normalise_tool_name("mcp__other__thing") == "thing"
    assert registry.normalise_tool_name("plain") == "plain"


async def test_invoke_unknown_tool():
    with pytest.raises(KeyError):
        await registry.invoke("nope", {}, timeout_s=1)


async def test_invoke_bad_args_is_a_tool_error():
    from app.tools import mock  # noqa: F401

    with pytest.raises(registry.ToolError):
        await registry.invoke("mock_echo", {"wrong": 1}, timeout_s=1)


def test_mcp_server_builds_from_registry():
    """With the SDK installed, the adapter must produce a server exposing every tool."""
    pytest.importorskip("claude_agent_sdk")
    from app.tools import mock  # noqa: F401

    async def dispatch(name, args):
        return "ok"

    server = registry.build_mcp_server(dispatch)
    assert server["type"] == "sdk"
    assert server["name"] == registry.MCP_SERVER_NAME
    # The SDK stores the tool list on the instance; count it.
    instance = server["instance"]
    tools = getattr(instance, "_tools", None) or getattr(instance, "tools", None)
    if tools is not None:
        assert len(tools) == len(registry.names())


def test_every_spec_has_an_object_schema():
    for spec in registry.all_specs():
        assert spec.input_schema.get("type") == "object", spec.name
        assert isinstance(spec.tier, Tier)


# --------------------------------------------------------------------------- per-tool ceiling

async def _patient(delay: float = 0.05) -> dict:
    import asyncio

    await asyncio.sleep(delay)
    return {"ok": True}


@pytest.fixture()
def patient_tool():
    """Registered for one test only: the gate treats any tool it does not know as RED, and
    the registry-wide tier test must keep seeing only the real ones."""
    registry.tool(
        name="test_patient_tool", description="slow on purpose",
        input_schema={"type": "object", "properties": {"delay": {"type": "number"}}},
        tier=Tier.GREEN, timeout_s=1.0,
    )(_patient)
    try:
        yield "test_patient_tool"
    finally:
        registry._REGISTRY.pop("test_patient_tool", None)


async def test_a_tool_may_declare_its_own_timeout_ceiling(patient_tool):
    """A Gmail search is a listing, a batched fetch and sometimes a credential refresh; the
    operator's 8 s default is the wrong bound for it. A tool's own ceiling replaces the
    default — and is still a hard bound."""
    assert registry.get(patient_tool).timeout_s == 1.0
    # The caller's tighter budget does not apply: the tool's own does.
    result = await registry.invoke(patient_tool, {"delay": 0.05}, timeout_s=0.01)
    assert result["ok"] is True
    # ...and the tool's own ceiling is enforced.
    with pytest.raises(registry.ToolError, match="did not respond within 1 seconds"):
        await registry.invoke(patient_tool, {"delay": 1.5}, timeout_s=30)


def test_gmail_tools_carry_their_own_ceiling():
    from app.tools import gmail_tools  # noqa: F401

    assert registry.get("gmail_search").timeout_s == gmail_tools.GMAIL_TIMEOUT_S
    assert registry.get("gmail_read_thread").timeout_s == gmail_tools.GMAIL_TIMEOUT_S
    assert registry.get("shopify_find_order").timeout_s is None, "the default still applies elsewhere"


def test_the_tool_block_offered_to_the_model_stays_within_its_budget():
    """Every description is read by the model on every turn. A budget, held here: the shared
    staging rules live in the system prompt once, not in each description."""
    import json

    from app.families import load_all
    from app.providers.max_agent_sdk import withheld_tools
    from app.tools import (  # noqa: F401
        analytics_tools,
        batch_tools,
        display_tools,
        engineering_tools,
        gmail_tools,
        gmail_writes,
        shopify_tools,
        shopify_writes,
    )

    # The engineering bridge and the screens are imported here for the same reason as the
    # families below: app/runtime.py offers them, and the suite counted them or not depending on
    # which earlier module had imported them (34,188 bytes alone, 36,342 in the suite).
    #
    # The Phase 3 families' tools are part of the block the model reads (app/runtime.py calls
    # this at boot), and they were being counted or not depending on whether an earlier test
    # module happened to import them: the same assertion produced 24,788 bytes run alone and
    # 26,259 in the suite. Loading them here makes the budget cover what production offers.
    load_all()
    specs = registry.all_specs()
    offered = [s for s in specs if s.name not in withheld_tools(specs, writes_enabled=True)]
    assert offered, "nothing offered"
    for spec in offered:
        assert len(spec.description) <= 600, f"{spec.name}: {len(spec.description)} chars of description"
        assert "spoken yes" not in spec.description, f"{spec.name}: the staging rules belong in the prompt"
    total = sum(len(json.dumps({"name": s.name, "description": s.description, "input_schema": s.input_schema})) for s in offered)
    # 16,000 held the narrow tools. The read layer (commerce_aggregate, commerce_query,
    # inventory_query, commerce_capabilities) is four tools for the questions that used to
    # need one each; its schemas are terse and the language's detail lives in
    # commerce_capabilities, called on demand. The four cost about 4.5 KB together. The
    # four batch tools (tags on and off a set of orders, a set of threads archived, a draft
    # to each customer) are the bulk versions of changes already offered singly; together
    # they cost about 1.7 KB and are withheld, like every write, while changes are off.
    #
    # 24,300 covers what the September session showed missing and nothing else:
    # shopify_order_address (the street address the owner asked for and was told did not
    # exist), gmail_find_in_email (a term checked across every thread, with coverage
    # reported) and batch_email_send (the bulk send, which shares batch_email_drafts's
    # schema object). About 1.7 KB together, half of it paid back by tightening the address
    # tool's per-field descriptions. The block is what every turn ON THE MODEL PATH pays —
    # a fast-lane turn pays none of it — and a tool added here has to earn its bytes.
    #
    # 26_400 covers Phase 3's four families, now that load_all() means they are counted.
    #
    # Order item editing (app/families/order_edit.py) is about 1.05 KB: a read that resolves
    # words to a variant id (shopify_variant_search, ~590 bytes) and the write that adds it
    # (shopify_order_add_item, ~460) — the one thing "add a black hoodie to this order" needed
    # and did not have.
    #
    # The composer (app/families/compose.py) is 2,085 bytes, measured: 1,471 for
    # gmail_compose_open and gmail_compose_fill, and 614 for the `to`/`to_name`/`compose_id`
    # properties on the two new-email tools — paid twice, because those two share one schema
    # object. What it buys is the recipient the shop cannot supply.
    #
    # Every schema here is already pared to the fields the model must name: the detail about
    # calculated orders, about what the customer will owe, and about what may be staged lives
    # in the families and on the cards, not in a description every turn pays for.
    # Measured after the merge: 27,357. The arithmetic, from 24,300 at the end of Phase 2:
    # order item editing about +1,050 (shopify_variant_search ~590, shopify_order_add_item
    # ~460), the composer +2,085 (1,471 for its two reads, 614 for `to`/`to_name`/`compose_id`
    # paid twice because the two new-email tools share one schema object), and the read
    # language came out SMALLER than it went in even after adding international, city, unpaid
    # and the ageing alias — its two per-tool filter blurbs replaced one that was paid twice.
    #
    # Every schema here is already pared to the fields the model must name: the detail about
    # calculated orders, about what the customer will owe, and about what may be staged lives
    # in the families and on the cards, not in a description every turn pays for. And the
    # ceiling is the WORST case — `runtime.withheld_by_family()` takes a family's tools away
    # when the store or the connection cannot serve it, so a Mac missing a scope pays less.
    #
    # 31_200 covers the four commerce families (brief sections 11, 12, 13 and 14), measured
    # tool by tool in this test's own terms:
    #
    #   discount codes (app/families/discounts.py)          1,412
    #       shopify_discount_open      841   the workspace: a code, a percentage OR an
    #                                        amount, a window, a usage limit. The one
    #                                        description the model needs in full, because
    #                                        `percent` is 15 and not 0.15 and getting that
    #                                        wrong is a fifteen-hundred-per-cent discount.
    #       shopify_discount_create    319   one argument: the workspace id.
    #       shopify_discount_check     252   is this code taken?
    #   making an order (app/families/order_create.py)        957
    #       shopify_order_open         625   the customer, and optionally a first item.
    #       shopify_order_create       332   one argument: the workspace id.
    #   store credit (app/families/store_credit.py)           894
    #       shopify_store_credit       577   the customer, the amount, the currency. Named
    #                                        without the "_open" the other two workspaces
    #                                        have, on purpose: the gate refuses any tool
    #                                        whose NAME reads as a mutation unless it carries
    #                                        a reviewed write definition, and "credit_open"
    #                                        contains "edit_".
    #       shopify_store_credit_add   317   one argument: the workspace id.
    #   abandoned checkouts (app/families/abandoned.py)       469
    #       shopify_abandoned_checkouts      the window and a limit. Its description spends
    #                                        its bytes on what the data is NOT — carts are
    #                                        not in the Admin API, unfulfilled orders are a
    #                                        different question — because the alternative is
    #                                        the model answering the wrong question
    #                                        confidently, which is what section 14 is about.
    #
    # 3,732 together, on 27,357 measured after the Phase 3 merge: 31,089, and the ceiling is
    # 31,200 rather than a round number above it because a hundred bytes of headroom is a
    # tool description somebody has to justify.
    #
    # The shape of that cost is the point. Each of the three CREATION families pays for ONE
    # sizeable schema — the workspace, which is where the owner's spoken request lands — and
    # one tiny one, because the write tool takes a single workspace id and nothing else.
    # Every value the mutation is actually sent with (the fraction Shopify wants, the
    # instants a window becomes, the variant ids, the prices, the payment state) is built on
    # the Mac from the Mac's own copy of the workspace, so it costs the model nothing to read
    # and nothing to get wrong. A creation family whose write tool listed its own arguments
    # would have cost several times this and moved the write boundary as well.
    #
    # 31_840 covers ONE tool, and the reason the ceiling moves rather than the description
    # being cut to nothing is the whole of D-4 (docs/phase5/LIVE_SESSION_FORENSICS.md):
    #
    #   the summary read (app/families/summaries.py)          640
    #       commerce_summary   640   a task, a period, a row limit, and one sentence: "never
    #                                read each customer or order on a list to answer one of
    #                                these". turn_be1b384ca420 answered "has anyone bought
    #                                today that has bought before" — correctly, with "one" —
    #                                by listing the day and then making seven
    #                                shopify_customer_history calls, 12,116 ms of it in the
    #                                model, and drawing seven full profile cards. Measured in
    #                                tests/test_n_plus_one.py: 8 requests and 7 per-entity
    #                                reads become 2 and 0, and 4,928 ms become 1,234 ms at
    #                                the live session's own measured cost of a read.
    #
    #                                The ACCOUNT of that — which tasks there are, and what
    #                                read pattern this replaces — is in
    #                                `commerce_capabilities` under "summaries", because the
    #                                rule the read layer's own budget below states is that
    #                                the detail belongs in the tool called on demand.
    #
    # 640 bytes on the model path, once per turn, against seven reads and twelve seconds on
    # the turns this tool takes — and it takes them WITHOUT the model, so a turn that reaches
    # its recipe pays none of the block at all. That is the trade, and it is the only reason
    # to move this number: 31,840 rather than a round number above it, because a hundred
    # bytes of headroom is still a tool description somebody has to justify.
    #
    # 33_930 adds Objective V0 (app/objectives/tools.py, the mobile alpha), 2,199 bytes measured:
    # objective_note 1,288 (one tool for facts, unknowns, blockers, questions, items and their
    # ladder, rather than nine), objective_open 415, objective_show 251, objective_list 245.
    # What it buys is a goal that outlives the conversation; the rules for keeping it live in
    # the system prompt once, not in these descriptions.
    #
    # 35_400 adds the engineering bridge (app/tools/engineering_tools.py), about 1,390 bytes
    # counted in this test's own terms: engineering_status about 310 (no arguments; the six
    # words it reports in are the description) and submit_engineering_request about 1,080 (the
    # loop's request fields, each bounded as the loop bounds it, so the gate refuses what the
    # loop would). What it buys is CLIVE filing its own engineering work, with the owner's tap.
    #
    # 35_680 is build objectives (tests/test_build_from_clive.py), +300 bytes measured
    # (35,376 before, 35,676 after): objective_open's `kind` +110, engineering_status's
    # `areas` +85, submit_engineering_request +105. The submit tool gained the objective it is
    # for and gave up its base, id and checks as required fields (the Mac fills them in), and
    # its descriptions were pared to pay for most of it. What it buys is a build objective the
    # model can file at all: until now it had to know a commit SHA and the builders' checks.
    #
    # 35_765 is the capability-gap record (tests/test_capability_gaps.py), +85 bytes measured
    # (35,676 before, 35,761 after): objective_note's `capability`, the few words a
    # missing_capability blocker names what CLIVE lacks by. What it buys is the same gap
    # counted under one name each time it comes up, which is how the owner sees which gaps come
    # up most and whether the builds CLIVE proposes are for those.
    #
    # 36_345 is the owner's screens (app/tools/display_tools.py, tests/test_displays.py), +775
    # bytes measured (35,567 before, 36,342 after): screen_list 260 (no required argument; an
    # order id asks whether it was packed) and screen_show 515 (the screen by the owner's own
    # name, and one of an order, an objective or a list). The rules for using them are in the
    # system prompt once. What it buys is "put 1047 on the office screen" doing exactly that,
    # and "has 1047 been packed?" answered from what was marked on the screen.
    assert total <= 36_345, f"the tool block is {total} bytes"
    batch = sum(len(json.dumps({"name": s.name, "description": s.description, "input_schema": s.input_schema})) for s in offered if s.name.startswith("batch_"))
    # 2,300 covers the fifth batch tool — the same campaign as batch_email_drafts, sent
    # rather than saved — which shares its schema object and adds two lines of description.
    assert batch <= 2_300, f"the batch tools' schemas are {batch} bytes; the rules belong in the prompt"
    analytic = sum(len(json.dumps({"name": s.name, "description": s.description, "input_schema": s.input_schema})) for s in offered if s.name.startswith(("commerce_", "inventory_query")))
    # 5,000 held the four query-language tools. The fifth, `commerce_summary`, is 640 bytes
    # and is not query-language detail: it takes a task from a closed set of three, a period
    # and a row limit, and its account of itself is in `commerce_capabilities` where this
    # rule says detail belongs. 5,650 is that, with the same hundred-odd bytes of headroom
    # the whole block keeps.
    assert analytic <= 5_650, f"the read layer's schemas are {analytic} bytes; the detail belongs in commerce_capabilities"
