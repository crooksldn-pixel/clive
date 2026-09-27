"""The owner boundary at the model's tools, refused by default (the 2026-09-27 deploy reviews,
round 6 F-NEW-TOOLS and B-01, round 7 F-NEW-TOOLS, F-NEW-TOOLS-PATH and B-01).

A tool runs only for work that holds an active authority (app/tools/authority.py): an owner
request the door let through, revoked the moment its answer has been sent, or bounded service
work explicitly derived from one. What is held here, end to end:

- a turn from anyone but the owner never reaches the model, let alone a tool;
- work with no authority — unscoped, from a route the owner rule does not cover, from a task a
  request left behind after its answer, with an expired or revoked authority — reaches no tool,
  and no handler is ever called;
- concurrent requests keep their own authority;
- the REAL Agent SDK path: the provider's tool callbacks arrive on tasks the SDK started with no
  context of the request's, and they run only under the authority the provider carried from the
  turn — for every registered tool, including one registered after the others; and its
  PreToolUse hook denies a call with no authority before the gate is asked.
"""

from __future__ import annotations

import asyncio
import contextvars
import sys

import pytest

from app.displays import store as displays_store
from app.main import app
from app.providers.base import TurnResult
from app.session.models import Session
from app.tools import authority
from app.tools import dispatch as dispatch_module
from app.tools.dispatch import dispatch
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)

STRANGER = {"Tailscale-User-Login": "someone@example.com", "X-Forwarded-For": "100.64.0.3"}
REFUSED = "REFUSED: this was not asked for by the owner"


class ToolingProvider:
    """A model that, asked anything, lists the screens and puts a list on one."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.asked: list[str] = []
        self.answers: list[str] = []
        self.left_running: asyncio.Task | None = None

    async def start(self): pass
    async def stop(self): pass
    async def health(self): return True, "fake"
    async def reset_session(self, session_id): pass
    async def set_system_prompt(self, prompt): pass
    async def interrupt(self, session_id): return True

    async def turn(self, session_id, text):
        self.asked.append(text)
        session = self.runtime.sessions.get_or_create(session_id)
        self.answers.append(await dispatch("screen_list", {}, session=session, timeout_s=5))
        self.answers.append(await dispatch("screen_show", {"screen": "Office screen", "title": "From a turn", "lines": ["one"]},
                                           session=session, timeout_s=5))
        if "leave something running" in text:
            async def later():
                await asyncio.sleep(0.2)          # well after the answer has been sent
                return await dispatch("screen_list", {}, session=session, timeout_s=5)

            self.left_running = asyncio.get_running_loop().create_task(later())
        return TurnResult(text="done", session_id=session_id)


@pytest.fixture()
def world(client, tmp_path):  # noqa: F811
    from app.tools import display_tools  # noqa: F401  registers the tools

    configure(client, logins=OWNER, local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False, "writes_local_owner": False})
    app.state.allowed_logins = client.runtime.allowed_logins
    screens = displays_store.install(tmp_path / "objectives" / "displays.json")
    screen = screens.register("Office screen")
    provider = ToolingProvider(client.runtime)
    client.runtime.provider = provider
    return client, provider, screens, screen


def _no_handler(monkeypatch):
    """Every way from the dispatcher to a handler, made to fail loudly if reached."""
    def reached(*_a, **_k):
        raise AssertionError("a tool handler was reached without the owner's authority")

    monkeypatch.setattr(dispatch_module, "_read_once", reached)
    monkeypatch.setattr(dispatch_module, "_stage", reached)


# --------------------------------------------------------------------------- through the door


async def test_a_turn_from_anyone_but_the_owner_never_reaches_the_model_or_a_tool(world):
    http, provider, screens, screen = world
    for headers, who in (({}, "the server itself, with the production switches"), (STRANGER, "a stranger's device")):
        refused = await http.post("/turn", json={"text": "put my list on the office screen", "session_id": "s1"}, headers=headers)
        assert refused.status_code == 403, who
    assert provider.asked == [] and provider.answers == [], "the model was never asked"
    assert screens._data["screens"][screen["id"]]["showing"] is None

    answered = await http.post("/turn", json={"text": "put my list on the office screen", "session_id": "s1"}, headers=PROXIED)
    assert answered.status_code == 200, answered.text
    assert provider.asked and not any(a.startswith("REFUSED") for a in provider.answers), provider.answers
    assert screens._data["screens"][screen["id"]]["showing"]["title"] == "From a turn"


async def test_a_task_the_owners_request_left_behind_holds_nothing_once_it_is_answered(world):
    http, provider, _screens, _screen = world
    answered = await http.post("/turn", json={"text": "and leave something running", "session_id": "s2"}, headers=PROXIED)
    assert answered.status_code == 200
    late = await asyncio.wait_for(provider.left_running, timeout=5)
    assert late.startswith(REFUSED), late


async def test_a_route_that_is_not_the_owners_has_no_tool_run_for_it(world, monkeypatch):
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from app import main as main_module

    http, _provider, _screens, _screen = world
    answers: list[str] = []

    async def probe(request):
        session = http.runtime.sessions.get_or_create("probe")
        answers.append(await dispatch("screen_list", {}, session=session, timeout_s=5))
        answers.append(await dispatch("objective_list", {}, session=session, timeout_s=5))
        return PlainTextResponse("ok")

    _no_handler(monkeypatch)
    real_public = main_module.is_public
    monkeypatch.setattr(main_module, "is_public", lambda path: path == "/probe-tools" or real_public(path))
    app.router.routes.insert(0, Route("/probe-tools", probe))
    try:
        for headers in ({}, PROXIED):
            assert (await http.get("/probe-tools", headers=headers)).status_code == 200
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/probe-tools"]
    assert len(answers) == 4 and all(a.startswith(REFUSED) for a in answers), answers


async def test_concurrent_requests_each_keep_their_own_authority(world, monkeypatch):
    """The owner's turn and a request that is not his, in flight at once: each sees its own."""
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from app import main as main_module

    http, provider, _screens, _screen = world
    seen: dict[str, object] = {}

    async def probe(request):
        await asyncio.sleep(0.05)
        seen["probe"] = authority.current()
        return PlainTextResponse("ok")

    real_turn = provider.turn

    async def slow_turn(session_id, text):
        seen["turn_before"] = authority.current()
        await asyncio.sleep(0.1)
        seen["turn_after"] = authority.current()
        return await real_turn(session_id, text)

    provider.turn = slow_turn
    real_public = main_module.is_public
    monkeypatch.setattr(main_module, "is_public", lambda path: path == "/probe-auth" or real_public(path))
    app.router.routes.insert(0, Route("/probe-auth", probe))
    try:
        turn, probe_answer = await asyncio.gather(
            http.post("/turn", json={"text": "put my list on the office screen", "session_id": "s3"}, headers=PROXIED),
            http.get("/probe-auth"),
        )
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/probe-auth"]
    assert turn.status_code == 200 and probe_answer.status_code == 200
    assert seen["probe"] is None
    assert seen["turn_before"] is not None and seen["turn_before"].kind == authority.OWNER
    assert seen["turn_after"] is seen["turn_before"]
    assert seen["turn_before"].revoked, "revoked once its answer was sent"


# --------------------------------------------------------------------------- the dispatcher itself


async def test_with_no_authority_or_a_dead_one_no_handler_is_reached(world, monkeypatch):
    _http, _provider, _screens, _screen = world
    _no_handler(monkeypatch)
    session = Session(session_id="bare")
    revoked = authority.for_owner(OWNER)
    revoked.revoke()
    expired = authority.for_owner(OWNER)
    expired.expires_at = 0.0
    for held in (None, revoked, expired, authority.Authority("root", "x", expires_at=1e18)):
        with authority.acting_as(held):
            for tool, args in (("screen_list", {}), ("screen_show", {"screen": "Office screen", "clear": True}),
                               ("objective_list", {}), ("shopify_order_detail", {"order_id": "gid://shopify/Order/1"})):
                text = await dispatch(tool, args, session=session, timeout_s=5)
                assert text.startswith(REFUSED), (held, tool, text)


async def test_bounded_service_work_holds_its_own_derived_authority(world):
    """A speculative read the owner's request started may finish after the answer: it holds a
    service authority derived from the owner's, named and expiring by itself — never the
    request's, and never one derived from nothing."""
    from app.memory.prefetch import Prefetcher

    _http, _provider, _screens, _screen = world
    owner = authority.for_owner(OWNER)
    session = Session(session_id="prefetch")
    results: dict[str, str] = {}

    async def read(tag):
        await asyncio.sleep(0.1)
        results[tag] = await dispatch("screen_list", {}, session=session, timeout_s=5)

    prefetcher = Prefetcher()
    with authority.acting_as(owner):
        assert prefetcher.start("k-owner", lambda: read("owner"), scope="s")
    owner.revoke()                                  # the request has been answered
    with authority.acting_as(None):
        assert prefetcher.start("k-none", lambda: read("none"), scope="s")
    await asyncio.sleep(0.4)
    assert not results["owner"].startswith(REFUSED), results
    assert results["none"].startswith(REFUSED)
    assert owner.derive("x", 10) is None, "nothing derives from a revoked authority"
    fresh = authority.for_owner(OWNER)
    derived = fresh.derive("prefetch:x", 10_000)
    assert derived.kind == authority.SERVICE and derived.purpose == "prefetch:x"
    assert derived.expires_at - fresh.expires_at < authority.MAX_SERVICE_S, "bounded however long is asked for"
    assert derived.derive("again", 1) is None, "a service authority derives nothing"


# --------------------------------------------------------------------------- the real SDK path


class CallbackClient:
    """A fake `claude` subprocess that calls CLIVE's tools back the way the SDK does: from a
    reader task started when it connected, with a context of its own — not the request's."""

    instances: list = []

    def __init__(self, options=None):
        self.options = options
        self.calls: list[tuple[str, dict]] = []
        self.results: list[str] = []
        self.before_call = None
        CallbackClient.instances.append(self)

    async def connect(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.reader = asyncio.get_running_loop().create_task(self._reader(), context=contextvars.Context())

    async def _reader(self):
        from app.tools import registry

        tools = {t.name: t for t in self.options.mcp_servers[registry.MCP_SERVER_NAME]["tools"]}
        while True:
            name, args = await self.inbox.get()
            out = await tools[name].handler(args)
            await self.outbox.put(out["content"][0]["text"])

    async def disconnect(self):
        self.reader.cancel()

    async def interrupt(self):
        pass

    async def get_server_info(self):
        return {"account": {"apiKeySource": "claude.ai", "apiProvider": "firstParty"}}

    async def query(self, text):
        self.text = text

    async def receive_response(self):
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        for name, args in self.calls:
            if self.before_call is not None:
                self.before_call()
            await self.inbox.put((name, args))
            self.results.append(await self.outbox.get())
        yield AssistantMessage(content=[TextBlock(text="done")], model="fake")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="cli")


@pytest.fixture()
def sdk(monkeypatch, tmp_path):
    claude_agent_sdk = pytest.importorskip("claude_agent_sdk")
    from app.providers.max_agent_sdk import MaxAgentSDKProvider
    from app.tools import display_tools  # noqa: F401

    CallbackClient.instances = []
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", CallbackClient)
    monkeypatch.setattr(claude_agent_sdk, "create_sdk_mcp_server", lambda name, version, tools: {"tools": tools})
    sessions: dict[str, Session] = {}
    p = MaxAgentSDKProvider(system_prompt="sys", cli_path=sys.executable,
                            session_lookup=lambda sid: sessions.setdefault(sid, Session(session_id=sid)))
    p._started, p._auth_mode = True, "cli"
    screens = displays_store.install(tmp_path / "objectives" / "displays.json")
    screens.register("Office screen")
    return p


async def _turn(p, calls, *, held, before_call=None):
    """One turn in which the model calls `calls`; returns what each call answered."""
    async def run():
        with authority.acting_as(held):
            conv = await p._conversation_for("s")
            conv.client.calls = list(calls)
            conv.client.before_call = before_call
            await p.turn_on_branch("s", "go")
            return conv.client.results

    return await run()


async def test_the_real_provider_carries_the_turns_authority_to_the_sdks_own_tasks(sdk):
    owner = authority.for_owner(OWNER)
    answered = await _turn(sdk, [("screen_list", {})], held=owner)
    assert "Office screen" in answered[0] and not answered[0].startswith("REFUSED"), answered
    await sdk.stop()


async def test_the_real_provider_refuses_every_tool_without_authority(sdk, monkeypatch):
    from app.families import load_all
    from app.objectives import tools as objective_tools  # noqa: F401
    from app.tools import (  # noqa: F401 — every tool the runtime offers
        analytics_tools,
        batch_tools,
        engineering_tools,
        gmail_tools,
        gmail_writes,
        registry,
        shopify_tools,
        shopify_writes,
    )

    load_all()
    _no_handler(monkeypatch)
    names = [spec.name for spec in registry.all_specs()]
    assert len(names) > 40
    answered = await _turn(sdk, [(n, {}) for n in names], held=None)
    assert len(answered) == len(names) and all(a.startswith("REFUSED") for a in answered), answered
    await sdk.stop()


async def test_a_tool_registered_after_the_others_is_refused_the_same_way(sdk, monkeypatch):
    from app.tools import registry
    from app.tools.gate import Tier

    ran: list[str] = []

    @registry.tool(name="zz_added_later", description="t", input_schema={"type": "object", "properties": {}}, tier=Tier.GREEN)
    async def zz_added_later() -> dict:
        ran.append("ran")
        return {"ok": True}

    try:
        answered = await _turn(sdk, [("zz_added_later", {})], held=None)
        assert answered[0].startswith("REFUSED") and ran == []
    finally:
        registry._REGISTRY.pop("zz_added_later", None)
    await sdk.stop()


async def test_the_real_provider_refuses_once_the_request_has_been_answered(sdk, monkeypatch):
    """The request's authority revoked mid-turn (its answer sent, or the backstop reached): the
    SDK's next callback is refused though the turn is still running."""
    _no_handler(monkeypatch)
    owner = authority.for_owner(OWNER)
    answered = await _turn(sdk, [("screen_list", {})], held=owner, before_call=owner.revoke)
    assert answered[0].startswith("REFUSED"), answered
    await sdk.stop()


async def test_the_pretooluse_hook_denies_a_call_with_no_authority(sdk):
    from app.providers.max_agent_sdk import _Holder
    from app.tools import registry

    holder = _Holder()
    hook = sdk._hook_for(holder)
    name = f"mcp__{registry.MCP_SERVER_NAME}__screen_list"
    denied = await hook({"tool_name": name, "tool_input": {}}, None, None)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    with authority.acting_as(authority.for_owner(OWNER)):
        conv = await sdk._conversation_for("h")
    conv.holder.conversation = conv
    conv.begin(Session(session_id="h"), authority=None)
    denied = await sdk._hook_for(conv.holder)({"tool_name": name, "tool_input": {}}, None, None)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    conv.begin(Session(session_id="h"), authority=authority.for_owner(OWNER))
    allowed = await sdk._hook_for(conv.holder)({"tool_name": name, "tool_input": {}}, None, None)
    assert allowed == {}
    await sdk.stop()
