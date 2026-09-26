"""Provider logic that does not need a live Claude: result classification, error mapping, the
billing guard, and — with the SDK installed — that the options object actually constructs."""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.providers.anthropic_api import AnthropicAPIProvider
from app.providers.max_agent_sdk import (
    BillingGuardError,
    MaxAgentSDKProvider,
    assert_no_payg_credentials,
    classify_claude_error,
    result_kind,
    usage_limit_line,
)
from tests.fake_credentials import anthropic_key


class R:
    def __init__(self, **kw):
        self.subtype, self.is_error, self.result, self.errors, self.api_error_status = "success", False, "", [], None
        self.__dict__.update(kw)


def test_success_result_is_none():
    assert result_kind(R()) is None
    assert result_kind(None) is None


@pytest.mark.parametrize(
    "msg,kind",
    [
        (R(subtype="error_max_turns", is_error=True), "max_turns"),
        (R(is_error=True, api_error_status=429), "usage_limit"),
        (R(is_error=True, result="You've hit your usage limit"), "usage_limit"),
        (R(is_error=True, api_error_status=401), "auth"),
        (R(is_error=True, api_error_status=500), "api_error"),
        (R(is_error=True, subtype="error_during_execution"), "unknown"),
    ],
)
def test_result_kinds(msg, kind):
    assert result_kind(msg) == kind


@pytest.mark.parametrize(
    "detail,expect",
    [
        ("Resets at 3pm (UTC)", "resets at 3pm UTC"),
        ("try again in 45 minutes", "resets in 45 minutes"),
        ("resets at 15:00 UTC", "resets at " + __import__("app.providers.max_agent_sdk", fromlist=["local_clock"]).local_clock("15:00 UTC")),
        ("limit reached", "rolling five-hour window"),
    ],
)
def test_usage_limit_line_reads_back_reset_time(detail, expect):
    assert expect in usage_limit_line(detail)
    assert "retry" in usage_limit_line(detail).lower() or "try again" in usage_limit_line(detail)


def test_the_reset_time_is_read_in_the_macs_own_clock():
    """"15:00 UTC" is four o'clock in London in summer. The owner hears his clock."""
    from datetime import UTC, datetime

    from app.providers.max_agent_sdk import local_clock

    local = datetime.now(UTC).replace(hour=15, minute=0, second=0, microsecond=0).astimezone()
    assert local_clock("15:00 UTC") == local.strftime("%H:%M")
    assert local_clock("3pm UTC") == "3pm UTC"          # not a bare clock: left alone
    assert local_clock("45 minutes") == "45 minutes"


def test_billing_guard(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", anthropic_key("billing-guard"))
    with pytest.raises(BillingGuardError):
        assert_no_payg_credentials()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "x")
    with pytest.raises(BillingGuardError):
        assert_no_payg_credentials()


def test_billing_guard_passes_when_clean(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert_no_payg_credentials()


def test_typed_sdk_errors_are_classified():
    sdk = pytest.importorskip("claude_agent_sdk")
    assert classify_claude_error(sdk.CLINotFoundError("x"))[0] == "cli_missing"
    assert classify_claude_error(RuntimeError("usage limit reached"))[0] == "usage_limit"
    assert classify_claude_error(RuntimeError("401 unauthorized"))[0] == "auth"
    assert classify_claude_error(ValueError("???"))[0] == "unknown"


async def test_stub_provider_never_works():
    p = AnthropicAPIProvider()
    for coro in (p.start(), p.turn("s", "hi"), p.health(), p.stop(), p.reset_session("s")):
        with pytest.raises(NotImplementedError):
            await coro


def test_stub_provider_imports_no_sdk_and_reads_no_key():
    import inspect

    from app.providers import anthropic_api

    src = inspect.getsource(anthropic_api)
    assert "import anthropic" not in src
    assert "ANTHROPIC_API_KEY" not in src
    assert "keychain" not in src


def test_options_construct_with_no_builtin_tools(monkeypatch):
    """With the SDK installed, prove the options object we build removes every built-in."""
    pytest.importorskip("claude_agent_sdk")
    from app.tools import mock  # noqa: F401 — registers tools

    p = MaxAgentSDKProvider(system_prompt="sys", model="sonnet", cli_path=sys.executable)
    p._auth_mode = "cli"
    opts = p._options()
    assert opts.tools == []
    assert opts.permission_mode == "dontAsk"
    assert opts.setting_sources == []
    assert "crooks" in opts.mcp_servers
    assert all(name.startswith("mcp__crooks__") for name in opts.allowed_tools)
    # RED tools are disallowed at the SDK layer too, not only denied by the hook.
    assert "mcp__crooks__mock_danger" in opts.disallowed_tools
    assert "mcp__crooks__mock_danger" not in opts.allowed_tools
    # The diagnostic mocks are for the test suite: never offered, never a schema byte.
    assert "mcp__crooks__mock_echo" not in opts.allowed_tools and "mcp__crooks__mock_echo" in opts.disallowed_tools
    assert "PreToolUse" in opts.hooks
    assert opts.env == {}  # CLI mode injects nothing
    assert opts.system_prompt == "sys"


async def test_turn_before_start_is_honest():
    p = MaxAgentSDKProvider(system_prompt="sys")
    res = await p.turn("s", "hi")
    assert res.error_kind == "not_started"


async def test_health_reports_cli_auth_caveat():
    """auth=cli is the normal mode: say what it needs (a logged-in Mac), not that it is broken."""
    p = MaxAgentSDKProvider(system_prompt="sys", cli_path=sys.executable)
    p._started, p._auth_mode = True, "cli"
    ok, detail = await p.health()
    assert ok and "auth=cli" in detail and "logged-in" in detail
    assert "NOT" not in detail


def _live_conversation(session, branch_id: str = ""):
    """A conversation with a turn in flight for `session`, the way _turn_locked leaves it."""
    from app.providers.max_agent_sdk import _Conversation, _Holder, conversation_key

    holder = _Holder()
    conv = _Conversation(key=conversation_key(session.session_id, branch_id), session_id=session.session_id, branch_id=branch_id, client=object(), holder=holder)
    holder.conversation = conv
    conv.begin(session)
    return conv


def test_red_hook_events_are_recorded_as_tool_calls():
    from app.session.models import Session

    p = MaxAgentSDKProvider(system_prompt="sys")
    session = Session(session_id="s")
    session.refuse("mock_danger", {}, "refused by gate")
    conv = _live_conversation(session)
    p._on_tool_event("mock_danger", "RED", "DENY", holder=conv.holder)
    assert conv.calls and conv.calls[0].name == "mock_danger" and not conv.calls[0].ok
    assert session.state == "THINKING" and "refused" in session.state_detail


def test_tool_events_drive_live_state():
    from app.session.models import Session

    p = MaxAgentSDKProvider(system_prompt="sys")
    session = Session(session_id="s")
    conv = _live_conversation(session)
    p._on_tool_event("shopify_list_orders", "GREEN", holder=conv.holder)
    assert session.state == "CHECKING SHOPIFY"
    p._on_tool_event("gmail_search", "GREEN", holder=conv.holder)
    assert session.state == "CHECKING EMAIL"


def test_a_hook_event_with_no_turn_behind_it_touches_nothing():
    """A client whose conversation has ended (or a spare that never had one) can still fire
    the hook if the CLI is late; it records nothing and moves no session."""
    from app.providers.max_agent_sdk import _Holder

    p = MaxAgentSDKProvider(system_prompt="sys")
    p._on_tool_event("shopify_list_orders", "GREEN", holder=_Holder())


async def test_set_system_prompt_drops_open_clients():
    class FakeClient:
        def __init__(self): self.closed = False
        async def disconnect(self): self.closed = True

    from app.providers.max_agent_sdk import _Conversation, _Holder

    p = MaxAgentSDKProvider(system_prompt="old")
    fake = FakeClient()
    holder = _Holder()
    p._conversations["s"] = _Conversation(key="s", session_id="s", branch_id="", client=fake, holder=holder, last_used=0)
    await p.set_system_prompt("new")
    assert p._system_prompt == "new"
    assert fake.closed and not p._conversations and holder.conversation is None


def test_broader_billing_guard(monkeypatch):
    for name in ("ANTHROPIC_API_KEY_HELPER", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv(name, "1")
        with pytest.raises(BillingGuardError):
            assert_no_payg_credentials()
        monkeypatch.delenv(name)


# --------------------------------------------------------------------------- pre-warming


class FakeSDKClient:
    instances: list = []

    def __init__(self, options=None):
        self.options = options
        self.connected = False
        self.closed = False
        FakeSDKClient.instances.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.closed = True

    async def get_server_info(self):
        return {"account": {"apiKeySource": "claude.ai", "apiProvider": "firstParty"}}


async def test_a_new_conversation_takes_the_prewarmed_client(monkeypatch):
    pytest.importorskip("claude_agent_sdk")
    import claude_agent_sdk

    from app.tools import mock  # noqa: F401 — registers tools

    FakeSDKClient.instances = []
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", FakeSDKClient)
    p = MaxAgentSDKProvider(system_prompt="sys", cli_path=sys.executable)
    p._started, p._auth_mode = True, "cli"

    p._prewarm_soon()
    await p._spare_task
    spare = p._spare
    assert spare is not None and spare.connected
    assert len(FakeSDKClient.instances) == 1

    # The first turn of a conversation adopts it instead of connecting, and a replacement
    # starts warming for the conversation after this one.
    client = await p._client_for("s1")
    assert client is spare and p._spare is None
    await p._spare_task
    assert p._spare is not None and p._spare is not spare
    assert len(FakeSDKClient.instances) == 2

    # A new knowledge base drops both — the spare was connected with the old prompt.
    await p.set_system_prompt("new")
    assert spare.closed
    await p._spare_task
    assert p._spare is not None and p._spare.options.system_prompt == "new"

    # Stopping disconnects everything and warms nothing more.
    await p.stop()
    assert all(c.closed for c in FakeSDKClient.instances)
    assert p._spare is None and p._spare_task is None


async def test_prewarm_failure_is_a_warning_not_a_broken_provider(monkeypatch, caplog):
    pytest.importorskip("claude_agent_sdk")
    import claude_agent_sdk

    class Broken(FakeSDKClient):
        async def connect(self):
            raise RuntimeError("no cli")

    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", Broken)
    p = MaxAgentSDKProvider(system_prompt="sys", cli_path=sys.executable)
    p._started, p._auth_mode = True, "cli"
    p._prewarm_soon()
    await p._spare_task
    assert p._spare is None
    assert "could not pre-warm" in caplog.text


def test_write_tools_are_withheld_from_the_model_unless_writes_are_on():
    from app.providers.max_agent_sdk import withheld_tools
    from app.tools import registry, shopify_tools  # noqa: F401

    specs = registry.all_specs()
    off = withheld_tools(specs, writes_enabled=False)
    on = withheld_tools(specs, writes_enabled=True)
    assert "shopify_order_note_append" in off and "mock_danger" in off and "mock_echo" in off
    assert "shopify_order_note_append" not in on and "mock_danger" in on and "mock_slow" in on
    assert "shopify_order_detail" not in off and "shopify_order_detail" not in on


async def test_a_tool_call_from_a_turn_the_owner_has_left_is_refused(monkeypatch):
    """Claude was still working when the owner cancelled or asked something else: its tool
    calls now act for nobody, and the dispatcher never sees them."""
    from app.providers import max_agent_sdk
    from app.session.models import Session

    async def never(*a, **k):
        raise AssertionError("dispatch must not run for an abandoned turn")

    monkeypatch.setattr(max_agent_sdk, "dispatch", never)
    provider = max_agent_sdk.MaxAgentSDKProvider(system_prompt="sys")
    session = Session(session_id="left")
    session.epoch = 2
    conv = _live_conversation(session)
    session.epoch = 3
    text = await provider._dispatch("shopify_find_order", {"query": "1930"}, holder=conv.holder)
    assert text.startswith("REFUSED") and "moved on" in text


async def test_the_other_halfs_instruction_does_not_refuse_this_halfs_tool_calls(monkeypatch):
    """The session's epoch moves for either half's instruction. A turn on the left half is
    still answering its own question when the owner asks the right half something: its tool
    calls must run. Only an instruction to the LEFT half — or a cancel aimed at it — refuses."""
    from app.providers import max_agent_sdk
    from app.session.models import Session

    ran: list[str] = []

    async def record(tool_name, args, **kw):
        ran.append(tool_name)
        return "ok"

    monkeypatch.setattr(max_agent_sdk, "dispatch", record)
    provider = max_agent_sdk.MaxAgentSDKProvider(system_prompt="sys")
    session = Session(session_id="two")
    left = session.branch()
    left.instruction_seq = 4
    conv = _live_conversation(session, left.branch_id)
    # The right half speaks: the session epoch moves.
    session.epoch += 1
    assert (await provider._dispatch("shopify_find_order", {"query": "1930"}, holder=conv.holder)) == "ok"
    # The left half is spoken to again: this turn is answering a replaced question.
    left.instruction_seq += 1
    text = await provider._dispatch("shopify_find_order", {"query": "1930"}, holder=conv.holder)
    assert text.startswith("REFUSED")
    # Or cancelled by name.
    left.instruction_seq -= 1
    left.abandoned = True
    assert (await provider._dispatch("shopify_find_order", {}, holder=conv.holder)).startswith("REFUSED")
    assert ran == ["shopify_find_order"]


async def test_a_tool_call_carries_its_own_half_into_the_engine(monkeypatch):
    """Two halves stage at once. The engine stamps a proposal with the acting branch, and
    the session's field says whichever half spoke last — so the call's own half travels on
    the task the call runs in (app/tools/context.CURRENT_BRANCH) and the engine reads that."""
    from app.providers import max_agent_sdk
    from app.session.models import Session
    from app.tools.context import acting_branch

    seen: list[tuple[str, str]] = []

    async def record(tool_name, args, *, session, **kw):
        before = acting_branch(session)
        await asyncio.sleep(0)          # the other half's call runs in between
        seen.append((before, acting_branch(session)))
        return "ok"

    monkeypatch.setattr(max_agent_sdk, "dispatch", record)
    provider = max_agent_sdk.MaxAgentSDKProvider(system_prompt="sys")
    session = Session(session_id="two")
    left = session.branch().branch_id
    right = "b_right"
    from app.session.branch import Branch

    session.branches[right] = Branch(branch_id=right, session_id="two")
    session.acting_branch = right          # the right half spoke last
    conv = _live_conversation(session, left)
    await asyncio.gather(
        provider._dispatch("shopify_find_order", {}, holder=conv.holder),
        provider._dispatch("shopify_find_order", {}, holder=_live_conversation(session, right).holder),
    )
    # Each call saw its own half, before and after yielding to the other one.
    assert sorted(seen) == sorted([(left, left), (right, right)])
    assert acting_branch(session) == right   # outside a tool call the session's own word stands
