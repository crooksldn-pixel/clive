"""Production's door, with production's settings as they resolve (the 2026-09-28 deploy review,
round 10: R9-A2-F-NEW-TOOLS-PATH, R9-C-C-01, R9-A1a-F-05A and R9-A1b-F-05A).

The round-9 and round-10 reviewers saw the door's tests force CROOKS_TAILSCALE_VERIFY on with a
settings copy, and drive a model double in place of the provider. Production sets none of the
switches in question: CROOKS_TAILSCALE_VERIFY, CROOKS_LOCAL_OWNER and CROOKS_ENGINEERING_HOST are
unset, so each is its default. Here the settings are built the way the service builds them, from
deploy/env.production.example with those three unset in the environment, and the only values given
are the two the template leaves for the owner to fill in: his login on the allow-list, and changes
switched on (production's own .env has both).

Then one request at a time goes through everything real: the middleware (app/main.py
guard_and_freshness), the proxy decision and the owner rule (app/routes/actions.py proxy_state,
principal_verdict), the kernel's account of the connection and of this host's own addresses read
from a fake /proc by the real readers (app/identity.py _proc_peer_check, host_addresses, bound_here,
this_host — no stand-in for "is this address the server's"), the authority the door stamps
(app/tools/authority.py for_owner), the turn route (app/routes/turn.py), the real Claude provider
(app/providers/max_agent_sdk.py MaxAgentSDKProvider, its SDK options, MCP tool callback and
_dispatch), and the dispatcher (app/tools/dispatch.py). Stood in for: `tailscale whois`, what
tailscale0 holds (an ioctl), the fake pids' pinning, and the `claude` subprocess — a scripted SDK
client that, once queried, calls CLIVE's tools back through the MCP server the provider built, from
a task of its own, as the SDK does. ElevenLabs is a mocked transport.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from app import identity, local_cli
from app import main as main_module
from app.main import app
from app.routes import voice as voice_route
from app.tools import authority
from app.tools import dispatch as dispatch_module
from tests.test_actions import ORDER, TOOL
from tests.test_actions_routes import OWNER, client  # noqa: F401 - `client` is a fixture
from tests.test_live_voice import TOKEN, Clock, ElevenLabs, store_key
from tests.test_proxy_identity import (
    HOST_TAILNET,
    HOST_TAILNET6,
    _addresses,
    _world,
    tailscale_interface,
)
from tests.test_tool_boundary import CallbackClient

TEMPLATE = Path(__file__).resolve().parents[1] / "deploy" / "env.production.example"
PHONE, STRANGER_DEVICE = "100.64.0.9", "100.64.0.3"
STRANGER = "someone@example.com"
TAILSCALED_END, CURL_END, DIRECT_END = 40001, 40002, 40009
HOST_V4, HOST_V6 = HOST_TAILNET[0], HOST_TAILNET6[0]
KEY = "k" * 43
QUESTION = "what's on order 1930?"


def production_settings(monkeypatch):
    """The settings the service builds on the server: the production template read as its .env,
    nothing in the environment for the switches it leaves unset, and the owner's login and
    changes on, as his .env has them."""
    from config.settings import Settings

    for name in ("CROOKS_TAILSCALE_VERIFY", "CROOKS_LOCAL_OWNER", "CROOKS_WRITES_LOCAL_OWNER",
                 "CROOKS_ENGINEERING_HOST", "CROOKS_ALLOWED_LOGINS", "CROOKS_WRITES_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=str(TEMPLATE), allowed_logins=OWNER, writes_enabled=True)


class ScriptedClaude(CallbackClient):
    """The `claude` subprocess, stood in for: asked a question, it calls `script` back through
    CLIVE's MCP tools from its own reader task, as the SDK does. `asked` is every question it was
    put, across every client made."""

    script: list[tuple[str, dict]] = []
    asked: list[str] = []

    async def query(self, text):
        ScriptedClaude.asked.append(text)
        self.calls = list(ScriptedClaude.script)
        await super().query(text)


@pytest.fixture()
async def door(client, tmp_path, monkeypatch):  # noqa: F811
    claude_agent_sdk = pytest.importorskip("claude_agent_sdk")
    from app.providers.max_agent_sdk import MaxAgentSDKProvider

    runtime = client.runtime
    runtime.settings = production_settings(monkeypatch)
    app.state.allowed_logins = runtime.allowed_logins
    proc = _world(tmp_path, {100: ("tailscaled", [777]), 200: ("curl", [888])})
    _addresses(proc, HOST_TAILNET, HOST_TAILNET6)
    tailscale_interface(monkeypatch, HOST_V4)
    monkeypatch.setattr(identity, "PROC", proc)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")
    identity.bind_self_check(None)
    whois = {PHONE: OWNER, STRANGER_DEVICE: STRANGER, HOST_V4: OWNER, HOST_V6: OWNER}
    identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": whois.get(address, "")}})
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")

    CallbackClient.instances = []
    ScriptedClaude.asked = []
    ScriptedClaude.script = [("shopify_order_detail", {"order_id": ORDER}),
                             (TOOL, {"order_id": ORDER, "note": "Customer asked for an exchange"})]
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", ScriptedClaude)
    monkeypatch.setattr(claude_agent_sdk, "create_sdk_mcp_server", lambda name, version, tools: {"tools": tools})
    provider = MaxAgentSDKProvider(system_prompt="sys", cli_path=sys.executable, writes_enabled=True,
                                   session_lookup=runtime.sessions.get_or_create)
    provider._started, provider._auth_mode = True, "cli"
    runtime.provider = provider

    reached: list[tuple[str, authority.Authority | None]] = []
    for step in ("_read_once", "_stage"):
        real = getattr(dispatch_module, step)

        def spy(name, *args, _real=real, **kwargs):
            reached.append((name, authority.current()))
            return _real(name, *args, **kwargs)

        monkeypatch.setattr(dispatch_module, step, spy)

    elevenlabs = ElevenLabs()
    monkeypatch.setattr(voice_route, "PACE", voice_route.Pace(clock=Clock()))
    monkeypatch.setattr(voice_route, "http_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(elevenlabs.handler), timeout=5.0))
    store_key(monkeypatch)

    class Door:
        http = client
        tools_reached = reached
        eleven = elevenlabs

        @staticmethod
        def via(port: int) -> httpx.AsyncClient:
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", port)),
                                     base_url="http://127.0.0.1:8000")

        @staticmethod
        def leave_out_the_servers_address() -> None:
            """A reading of the kernel's own shape that leaves out the server's tailnet IPv4 address
            and holds a carrier-grade NAT address on another interface in its place (S1T-01)."""
            _addresses(proc, ["100.64.50.50"], HOST_TAILNET6)

    try:
        yield Door
    finally:
        await provider.stop()


def test_production_resolves_the_switches_it_leaves_unset_to_their_defaults(monkeypatch):
    """What "production's switches" are, read, not assumed: the template leaves verification, the
    server-as-owner switch and the engineering host unset, and unset is verification on, the
    server not the owner, and filing off."""
    settings = production_settings(monkeypatch)
    for name in ("tailscale_verify", "local_owner", "engineering_host"):
        assert name not in settings.model_fields_set, f"{name} is set by the template or the environment"
    assert settings.tailscale_verify is True and settings.local_owner is False
    assert settings.writes_local_owner is False and settings.engineering_host == "off"
    assert settings.allowed_logins == OWNER and settings.writes_enabled is True


NOT_THE_OWNER = {
    "the server itself, straight to the port": (DIRECT_END, {}, "not_authorised_local"),
    "a stranger's device, through tailscaled": (TAILSCALED_END, {"Tailscale-User-Login": STRANGER, "X-Forwarded-For": STRANGER_DEVICE}, None),
    "the owner's login on a device Tailscale says is not his": (TAILSCALED_END, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": STRANGER_DEVICE}, "identity_unverified"),
    "a process on the server writing Tailscale's headers": (CURL_END, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": PHONE}, None),
    "the server's own IPv4 request through its own tailscale serve": (TAILSCALED_END, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": HOST_V4}, "not_authorised_local"),
    "the server's own IPv6 request through its own tailscale serve": (TAILSCALED_END, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": HOST_V6}, "not_authorised_local"),
    "Funnel, or a tagged node: forwarded with no login": (TAILSCALED_END, {"X-Forwarded-For": PHONE}, None),
    "the server's command key, on the turn route": (DIRECT_END, {local_cli.HEADER: KEY}, "local_key_misused"),
}


def _nothing_reached(door) -> None:
    assert ScriptedClaude.asked == [] and CallbackClient.instances == [], "no Claude client was made or asked"
    assert door.tools_reached == [], "no tool handler was reached"
    assert door.http.store.mutations == []


@pytest.mark.parametrize("who", sorted(NOT_THE_OWNER))
async def test_a_refused_caller_never_reaches_the_model_or_a_tool(door, who):
    """R9-A2-F-NEW-TOOLS-PATH: each caller that is not the owner's verified device is refused at
    the door with production's settings as they resolve, and the real provider is never asked."""
    local_cli.bind_key(KEY)
    port, headers, code = NOT_THE_OWNER[who]
    async with door.via(port) as caller:
        refused = await caller.post("/turn", json={"text": QUESTION, "session_id": f"s-{port}"}, headers=headers)
    assert refused.status_code == 403, (who, refused.text)
    if code:
        assert refused.json().get("code") == code, (who, refused.json())
    _nothing_reached(door)


async def test_the_servers_own_request_on_a_reading_missing_its_address_never_reaches_the_model(door):
    """S1T-01 through the whole path: the kernel's reading leaves the server's tailnet address out
    and holds a tailnet-range address on another interface. The server's own request is refused at
    the door — and so is the owner's phone, until the reading is whole again."""
    door.leave_out_the_servers_address()
    self_request = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": HOST_V4}
    phone = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": PHONE}
    async with door.via(TAILSCALED_END) as caller:
        for headers in (self_request, phone):
            refused = await caller.post("/turn", json={"text": QUESTION, "session_id": "s-self"}, headers=headers)
            assert refused.status_code == 403 and refused.json()["who"] == "unverified proxy", refused.text
    _nothing_reached(door)


async def test_the_owners_phone_is_answered_by_the_real_provider_under_his_authority_alone(door):
    http = door.http
    http.runtime.sessions.get_or_create("owner-1").issue(ORDER)
    phone = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": PHONE}
    async with door.via(TAILSCALED_END) as caller:
        whoami = (await caller.get("/whoami", headers=phone)).json()
        assert whoami["through"] == "tailscale" and whoami["owner"] is True, whoami
        answered = await caller.post("/turn", json={"text": QUESTION, "session_id": "owner-1"}, headers=phone)
    assert answered.status_code == 200, answered.text
    assert len(ScriptedClaude.asked) == 1 and QUESTION in ScriptedClaude.asked[0]
    assert [name for name, _ in door.tools_reached] == ["shopify_order_detail", TOOL]
    held = {id(during): during for _, during in door.tools_reached}
    assert len(held) == 1, "every handler ran under the one authority this request was given"
    (granted,) = held.values()
    assert granted is not None and granted.kind == authority.OWNER and granted.who == OWNER
    results = [r for c in CallbackClient.instances for r in c.results]
    assert results and not any(r.startswith("REFUSED") for r in results), results
    assert http.store.mutations == [], "a change is staged for his tap, never applied by the turn"
    assert granted.revoked, "dead once the answer was sent"


# ------------------------------------------------------------------ R9-C-C-01: the live words' key


async def test_nobody_but_the_owners_phone_mints_a_live_voice_key_through_the_real_door(door):
    """R9-C-C-01 with production's settings as they resolve and this host's addresses read, not
    stood in for: every caller in NOT_THE_OWNER, and the server's own request on a reading that
    leaves its address out, is refused a key and ElevenLabs is never asked; the owner's phone gets
    one."""
    local_cli.bind_key(KEY)
    for who, (port, headers, _code) in sorted(NOT_THE_OWNER.items()):
        async with door.via(port) as caller:
            refused = await caller.post("/voice/live", headers=headers, json={})
        assert refused.status_code == 403 and TOKEN not in refused.text and "token" not in refused.json(), who
    assert door.eleven.calls == []
    async with door.via(TAILSCALED_END) as caller:
        minted = await caller.post("/voice/live", headers={"Tailscale-User-Login": OWNER, "X-Forwarded-For": PHONE}, json={})
    assert minted.status_code == 200 and minted.json()["token"] == TOKEN and len(door.eleven.calls) == 1
    door.leave_out_the_servers_address()
    async with door.via(TAILSCALED_END) as caller:
        for forwarded in (HOST_V4, PHONE):
            refused = await caller.post("/voice/live", headers={"Tailscale-User-Login": OWNER, "X-Forwarded-For": forwarded}, json={})
            assert refused.status_code == 403 and "token" not in refused.json()
    assert len(door.eleven.calls) == 1


async def test_the_live_voice_route_refuses_on_its_own_if_the_door_were_ever_opened(door, monkeypatch):
    """The route's own check (voice._refused, the same principal_verdict) with the door's owner
    rule taken off /voice/live: a forged, a stranger's and the server's own request are still
    refused, by the route, and ElevenLabs is not asked."""
    real_public = main_module.is_public
    monkeypatch.setattr(main_module, "is_public", lambda path: path == "/voice/live" or real_public(path))
    cases = ((TAILSCALED_END, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": HOST_V4}, "not_authorised_local"),
             (TAILSCALED_END, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": STRANGER_DEVICE}, "identity_unverified"),
             (DIRECT_END, {}, "not_authorised_local"))
    for port, headers, code in cases:
        async with door.via(port) as caller:
            refused = await caller.post("/voice/live", headers=headers, json={})
        assert refused.status_code == 403 and refused.json() == {"code": code, "detail": refused.json()["detail"]}, refused.text
    assert door.eleven.calls == []


# ------------------------------------------------------------------ F-05A: the command key, the same door


async def test_the_command_key_is_the_servers_own_command_or_nothing_under_production_settings(door):
    """R9-A1a-F-05A and R9-A1b-F-05A with the settings as they resolve: on each of the three
    test-session routes, the owner's verified phone carrying the right key, a wrong one or an empty
    one is refused at the door, and so is the server's own request through tailscale serve with
    the right key; straight to the port the right key is let in and a wrong or empty one is not;
    the phone without the header is the owner. (The phone itself, against the staging copy, is the
    deploy's check.)"""
    local_cli.bind_key(KEY)
    phone = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": PHONE}
    self_request = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": HOST_V4}
    routes = (("POST", "/test-session/start"), ("GET", "/test-session/status"), ("POST", "/test-session/stop"))
    async with door.via(TAILSCALED_END) as device, door.via(DIRECT_END) as server:
        for method, path in routes:
            for headers in ({**phone, local_cli.HEADER: KEY}, {**phone, local_cli.HEADER: "k" * 42},
                            {**phone, local_cli.HEADER: ""}, {**self_request, local_cli.HEADER: KEY}):
                refused = await device.request(method, path, headers=headers, json={"name": "x"})
                assert refused.status_code == 403 and refused.json()["code"] == "local_key_misused", (path, headers)
            for value in ("k" * 42, ""):
                refused = await server.request(method, path, headers={local_cli.HEADER: value}, json={"name": "x"})
                assert refused.status_code == 403 and refused.json()["code"] == "local_key_misused", (path, repr(value))
            assert (await server.request(method, path, json={"name": "x"})).status_code == 403, "no key, no owner"
        started = await server.post("/test-session/start", headers={local_cli.HEADER: KEY}, json={"name": "the server's"})
        assert started.status_code == 200 and started.json()["started"] is True, started.text
        assert (await device.get("/test-session/status", headers=phone)).json()["active"] is True
        stopped = await server.post("/test-session/stop", headers={local_cli.HEADER: KEY})
        assert stopped.status_code == 200 and stopped.json()["stopped"] is True
    _nothing_reached(door)
