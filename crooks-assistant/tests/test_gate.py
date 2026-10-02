"""The gate is the security architecture. These tests are the reason to trust it."""

from __future__ import annotations

import pytest

from app.session.models import Session
from app.tools import mock
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify


@pytest.fixture()
def session() -> Session:
    mock.reset_counters()
    return Session(session_id="test")


# --- fail-closed behaviour -------------------------------------------------

def test_unknown_tool_is_red():
    assert classify("some_tool_we_never_wrote").tier is Tier.RED


def test_empty_name_is_red():
    assert classify("").tier is Tier.RED


@pytest.mark.parametrize(
    "name",
    [
        "gmail_send_message", "gmail_create_draft", "shopify_update_order",
        "shopify_cancel_order", "gmail_trash_thread", "shopify_create_refund",
        "gmail_label_thread", "shopify_set_inventory", "delete_everything",
    ],
)
def test_mutation_verbs_are_red_even_if_unregistered(name):
    """A write tool added by accident is blocked by its own name, before any rule table."""
    assert classify(name).tier is Tier.RED


def test_mock_danger_is_red():
    assert classify("mock_danger").tier is Tier.RED


# --- MCP prefix normalisation ---------------------------------------------

def test_mcp_prefixed_names_classify_identically():
    """The documented trap: prefixed names silently missing every rule."""
    assert classify("mcp__crooks__mock_echo").tier is Tier.GREEN
    assert classify("mcp__crooks__mock_danger").tier is Tier.RED
    assert classify("mcp__crooks__gmail_send_message").tier is Tier.RED


# --- issued-id ledger ------------------------------------------------------

def test_detail_tool_rejects_unissued_id():
    d = classify("shopify_order_detail", {"order_id": "gid://shopify/Order/999"}, issued_ids=[])
    assert d.tier is Tier.RED
    # The reason tells the model how to recover, and says nothing was refused: a denial the
    # model recovers from must not read, on the tablet or in its answer, as "not allowed".
    assert "not an id this conversation has looked up" in d.reason
    assert "shopify_find_order" in d.reason and "Nothing is refused" in d.reason
    # And the decision itself says this is a wrong turning, not a rule: the dispatcher tells
    # the model to put it right rather than to announce a refusal to the owner.
    assert d.recoverable is True
    assert classify("shopify_cancel_order", {"order_id": "gid://shopify/Order/1"}, ["gid://shopify/Order/1"]).recoverable is False


def test_detail_tool_accepts_issued_id():
    oid = "gid://shopify/Order/4832"
    assert classify("shopify_order_detail", {"order_id": oid}, issued_ids=[oid]).tier is Tier.AMBER


def test_a_customer_id_is_not_an_order_id_even_if_issued():
    cid = "gid://shopify/Customer/77"
    d = classify("shopify_order_detail", {"order_id": cid}, issued_ids=[cid])
    assert d.tier is Tier.RED and "kind of id" in d.reason


def test_thread_ids_must_look_like_gmail_thread_ids():
    d = classify("gmail_read_thread", {"thread_id": "gid://shopify/Order/1"}, issued_ids=["gid://shopify/Order/1"])
    assert d.tier is Tier.RED
    assert classify("gmail_read_thread", {"thread_id": "18f2a9c0b1d2e3f4"}, issued_ids=["18f2a9c0b1d2e3f4"]).tier is Tier.AMBER


def test_detail_tool_rejects_missing_id():
    assert classify("shopify_order_detail", {}, issued_ids=["x"]).tier is Tier.RED


def test_malformed_id_is_red():
    d = classify("gmail_read_thread", {"thread_id": "'; DROP TABLE --"}, issued_ids=["a"])
    assert d.tier is Tier.RED


# --- argument bounds -------------------------------------------------------

@pytest.mark.parametrize("limit", [0, -1, 51, 10_000, "banana", "12x"])
def test_out_of_range_limit_is_red(limit):
    assert classify("shopify_list_orders", {"limit": limit}).tier is Tier.RED


def test_in_range_limit_is_green():
    assert classify("shopify_list_orders", {"limit": 20}).tier is Tier.GREEN


def test_out_of_range_days_is_red():
    assert classify("gmail_search", {"days": 9999}).tier is Tier.RED


# --- PII tools are amber, not green ---------------------------------------

@pytest.mark.parametrize("name", ["shopify_find_customer"])
def test_pii_tools_are_amber(name):
    assert classify(name, {"query": "jo"}).tier is Tier.AMBER


def test_purity_gate_does_not_mutate_args():
    args = {"limit": 20}
    classify("shopify_list_orders", args)
    assert args == {"limit": 20}


# --- the one that matters: RED never executes -----------------------------

async def test_red_tool_handler_never_runs(session):
    assert mock.DANGER_CALLS == 0
    out = await dispatch("mock_danger", {}, session=session, timeout_s=5)
    assert mock.DANGER_CALLS == 0, "RED tool executed — stop the build"
    assert out.startswith("REFUSED")
    assert session.refusals and session.refusals[0].tool_name == "mock_danger"
    assert session.proposals == [], "a refusal is never a proposal: nothing can authorise it"


async def test_red_tool_via_mcp_prefix_never_runs(session):
    await dispatch("mcp__crooks__mock_danger", {}, session=session, timeout_s=5)
    assert mock.DANGER_CALLS == 0


async def test_green_tool_runs(session):
    out = await dispatch("mock_echo", {"word": "banana"}, session=session, timeout_s=5)
    assert "banana" in out
    assert mock.ECHO_CALLS == 1


async def test_timeout_is_reported_not_raised(session):
    out = await dispatch("mock_slow", {}, session=session, timeout_s=0.2)
    assert out.startswith("ERROR")
    assert "did not respond" in out


async def test_unissued_detail_call_is_not_run_end_to_end(session):
    """Nothing is read for an id this conversation has not looked up. The model is told to
    look it up rather than to tell the owner it could not — that is a step it skipped, not a
    permission it lacks, and the difference is what the owner hears."""
    out = await dispatch(
        "shopify_order_detail",
        {"order_id": "gid://shopify/Order/1"},
        session=session,
        timeout_s=5,
    )
    assert out.startswith("NOT YET") and "shopify_find_order" in out
    assert "could not do this" not in out


async def test_ids_from_a_result_become_usable(session):
    """Issuing is what makes a follow-up question work: search, then ask about that one."""
    from app.tools.dispatch import _harvest_ids

    _harvest_ids({"orders": [{"order_id": "gid://shopify/Order/4832"}]}, session)
    assert "gid://shopify/Order/4832" in session.issued_ids
    assert classify(
        "shopify_order_detail",
        {"order_id": "gid://shopify/Order/4832"},
        issued_ids=session.issued_ids,
    ).tier is Tier.AMBER


# --- the gate consults the registry's own declaration ----------------------

def test_registry_amber_tier_is_honoured_even_without_a_rule():
    from app.tools import registry

    registry.tool(name="shopify_find_customer_probe", description="d", input_schema={"type": "object"}, tier=Tier.AMBER)(lambda **k: None)
    # Not in the gate's own tables; still AMBER because the registry says so — but unknown
    # to the allowlist, so RED wins. The allowlist is the outer wall.
    assert classify("shopify_find_customer_probe").tier is Tier.RED
    registry._REGISTRY.pop("shopify_find_customer_probe")


def test_registry_issued_id_args_are_enforced():
    """shopify_order_detail declares order_id in the registry; the gate needs it issued."""
    from app.tools import shopify_tools  # noqa: F401

    assert classify("shopify_order_detail", {"order_id": "gid://shopify/Order/9"}, issued_ids=[]).tier is Tier.RED


async def test_client_errors_reach_the_model_readably(session):
    """A Shopify throttle must be reported as a throttle, not 'failed unexpectedly'."""
    from app.clients.shopify import ShopifyError
    from app.tools import registry

    @registry.tool(name="shopify_find_order_probe", description="d", input_schema={"type": "object"})
    async def probe():
        raise ShopifyError("Shopify is rate-limiting us. Try again in a moment.")

    try:
        # Not in the gate allowlist, so call invoke's error path through dispatch's handler
        # by temporarily allowing it.
        from app.tools import gate

        gate._KNOWN_TOOLS = frozenset(gate._KNOWN_TOOLS | {"shopify_find_order_probe"})
        out = await dispatch("shopify_find_order_probe", {}, session=session, timeout_s=5)
        assert out.startswith("ERROR: Shopify is rate-limiting")
        assert "unexpectedly" not in out
    finally:
        registry._REGISTRY.pop("shopify_find_order_probe", None)
        gate._KNOWN_TOOLS = frozenset(gate._KNOWN_TOOLS - {"shopify_find_order_probe"})


def test_harvest_records_personal_strings_but_not_order_names(session):
    from app.tools.dispatch import _harvest_ids

    _harvest_ids(
        {"orders": [{"order_id": "gid://shopify/Order/1", "name": "CROOKS-1928", "customer_name": "Anna Denning",
                     "customer_id": "gid://shopify/Customer/7"}],
         "threads": [{"thread_id": "t1", "from": "Jo Bloggs", "from_email": "jo@example.com"}]},
        session,
    )
    assert {"Anna Denning", "Jo Bloggs", "jo@example.com"} <= session.pii_seen
    assert "CROOKS-1928" not in session.pii_seen


# --- the engineering loop and the screens: names on the allow-list, and nothing else moved ---

def test_the_allow_list_gained_engineering_status_the_screens_and_nothing_else():
    """The changes the engineering bridge and the owner's screens made to the gate. The bridge
    added one read; the screens added their tools (app/tools/display_tools.py; screen_pair in
    round 8, B-02; screen_off and screen_remote in round 9, then YouTube's screen_play and
    screen_video, which carry nobody's details) and one issued-id rule, so a slip is only ever
    drawn from an order this conversation looked up. Round 12 added one read, shopify_order_build,
    which changes only the Mac's copy of an order being built (app/families/order_create.py).
    Every other table is as it was: the same mutation verbs, the same
    personal-data reads, the same id kinds, the same bounds."""
    from app.tools import gate

    assert "engineering_status" in gate._KNOWN_TOOLS
    assert {"screen_list", "screen_show", "screen_pair"} <= gate._KNOWN_TOOLS
    assert {"screen_off", "screen_remote"} <= gate._KNOWN_TOOLS
    assert {"screen_play", "screen_video"} <= gate._KNOWN_TOOLS
    # Round 12: shopify_order_build, every spoken change to an order being built (a Mac-side
    # edit; creating still goes through shopify_order_create's hold), and show_again, a read
    # that puts back on the owner's app what the conversation already showed him; its `ref` is
    # an issued-id argument declared on its ToolSpec.
    assert {"shopify_order_build", "show_again"} <= gate._KNOWN_TOOLS
    # And close_screen, which clears the owner's own app ("close that", "put it away"): no
    # arguments, and nothing but the Mac's record of what the half shows is touched.
    assert "close_screen" in gate._KNOWN_TOOLS
    # Instagram's three reads (app/tools/instagram_tools.py): AMBER on their ToolSpecs, and
    # instagram_thread's conversation_id an issued-id argument declared there, so the other
    # tables below are unchanged.
    assert {"instagram_inbox", "instagram_thread", "instagram_comments"} <= gate._KNOWN_TOOLS
    # The team and the work list (app/people/tools.py, app/work/tools.py): like the objective tools,
    # they change only CLIVE's own records, stage nothing and let nobody in; the owner-only steps
    # are the tools' own refusal. Named without a mutation verb, so the tables below are unchanged.
    assert {"people_list", "person_note", "work_list", "work_note"} <= gate._KNOWN_TOOLS
    # The owner's installed skills (2026-10-01): reads of the skill files the installer put on this
    # machine. Neither is a mutation by name, so the verb rule cannot stage them.
    skills = {"skill_list", "skill_read"}
    assert skills <= gate._KNOWN_TOOLS
    assert not any(gate._looks_like_mutation(name) for name in skills)
    assert not skills & gate._PII_TOOLS
    # Parcel tracking (app/tools/ship24_tools.py, 2026-10-02): one read of a parcel's carrier scans
    # from Ship24, GREEN on its ToolSpec, named without a mutation verb and reaching no Shopify
    # client, so the tables below are unchanged.
    assert "track_parcel" in gate._KNOWN_TOOLS and not gate._looks_like_mutation("track_parcel")
    assert "track_parcel" not in gate._PII_TOOLS
    assert len(gate._KNOWN_TOOLS) == 54, ("33 before, engineering_status, screen_list, screen_show, screen_pair, "
                                          "screen_off and screen_remote, then screen_play and screen_video, "
                                          "then round 12's shopify_order_build, show_again and close_screen, "
                                          "then instagram_inbox, instagram_thread and instagram_comments, "
                                          "then people_list, person_note, work_list and work_note, "
                                          "then skill_list and skill_read, then track_parcel")
    assert gate._MUTATION_VERBS == (
        "send", "create", "update", "delete", "modify", "write", "draft", "reply", "forward",
        "trash", "archive", "label", "cancel", "refund", "fulfil", "fulfill", "publish",
        "set_", "add_", "remove_", "edit_", "post_", "put_", "patch_", "destroy", "append",
        "restore", "commit", "approve", "execute", "adjust",
    )
    assert len(gate._PII_TOOLS) == 6 and "engineering_status" not in gate._PII_TOOLS
    assert not {"screen_list", "screen_show", "screen_play", "screen_video"} & gate._PII_TOOLS
    assert len(gate._ISSUED_ID_ARGS) == 4 and "engineering_status" not in gate._ISSUED_ID_ARGS
    # Round 6, B-05: an objective put on a screen is an issued id too, of its own kind.
    assert gate._ISSUED_ID_ARGS["screen_show"] == ("order_id", "objective_id")
    assert set(gate._ID_KIND) == {
        "order_id", "customer_id", "line_item_id", "variant_id", "thread_id",
        "evidence_message_id", "set_id", "workspace_id", "objective_id",
    }
    assert gate._ID_KIND["objective_id"].pattern == r"^obj_[0-9a-f]{8}$"
    assert (gate._MAX_LIMIT, gate._MAX_DAYS) == (50, 365)


def test_engineering_status_is_a_green_read_held_to_the_same_bounds():
    from app.tools import engineering_tools  # noqa: F401

    d = classify("engineering_status")
    assert d.tier is Tier.GREEN and d.disposition is Disposition.EXECUTE_NOW
    assert classify("mcp__crooks__engineering_status").disposition is Disposition.EXECUTE_NOW
    # No special case: the general bounds still apply to it like to any read.
    assert classify("engineering_status", {"limit": 0}).disposition is Disposition.DENY


def test_filing_is_staged_by_the_existing_issued_id_rule_and_never_executed():
    from app.tools import engineering_tools  # noqa: F401

    head = "1" * 40
    # No base and no checks: those are the Mac's own, and a request naming either is denied
    # (the 2026-09-26 deploy review, F-06).
    args = {
        "inbox_id": head, "request_id": "bridge-gate-one", "title": "t", "requested_outcome": "o",
        "allowed_paths": ["crooks-assistant/app/engineering_bridge"],
    }
    unread = classify("submit_engineering_request", args, issued_ids=[])
    assert unread.disposition is Disposition.DENY and unread.recoverable, "the inbox has not been read yet"
    staged = classify("submit_engineering_request", args, issued_ids=[head])
    assert staged.disposition is Disposition.STAGE_FOR_OWNER and staged.tier is Tier.RED
    assert not staged.executes
    missing = {k: v for k, v in args.items() if k != "inbox_id"}
    assert classify("submit_engineering_request", missing, issued_ids=[head]).disposition is Disposition.DENY
    assert classify("submit_engineering_request", {**args, "force": True}, issued_ids=[head]).disposition is Disposition.DENY
    too_long = {**args, "requested_outcome": "o" * 20001}
    assert classify("submit_engineering_request", too_long, issued_ids=[head]).disposition is Disposition.DENY
    for own_gate in ({"base_ref": "main"}, {"base_sha": "a" * 40}, {"checks": [{"name": "ok", "argv": ["true"]}]}):
        assert classify("submit_engineering_request", {**args, **own_gate}, issued_ids=[head]).disposition is Disposition.DENY


def test_the_other_decisions_are_unchanged():
    oid = "gid://shopify/Order/4832"
    assert classify("shopify_order_detail", {"order_id": oid}, issued_ids=[oid]).disposition is Disposition.EXECUTE_NOW
    assert classify("shopify_order_detail", {"order_id": oid}, issued_ids=[]).recoverable is True
    assert classify("shopify_find_customer", {"query": "jo"}).tier is Tier.AMBER
    assert classify("shopify_list_orders", {"limit": 20}).tier is Tier.GREEN
    assert classify("gmail_search", {"days": 9999}).disposition is Disposition.DENY
    assert classify("mock_danger").disposition is Disposition.DENY
    assert classify("some_tool_we_never_wrote").disposition is Disposition.DENY
    assert classify("gmail_create_draft").disposition is Disposition.DENY
    assert classify("engineering_submit_unregistered").disposition is Disposition.DENY
