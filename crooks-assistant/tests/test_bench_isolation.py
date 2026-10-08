"""The bench's seal (app/bench/isolation.py): a bench run cannot reach anything outside the fake shop,
and fails closed the moment anything tries.

George approved the bench on one condition: it runs against the fake shop, "no real customers, no
writes possible". What is held here:

  - every way out is refused while the seal is on, and recorded as a breach with where it came from:
    any internet connection (loopback too, since a local proxy would carry it on), a host lookup, a
    real HTTP client of any kind (Shopify, Instagram, Ship24, CROOKS Returns, YouTube, GitHub, and
    whatever is added next, because they all build an httpx transport), Gmail's real service and
    credentials, and the Shopify and ElevenLabs client classes themselves (the Whisper client went
    with the local recogniser, DEC-071 ruling 39);
  - below the socket class, the audit hook refuses every connect, send, port and lookup Python's
    socket module makes past loopback, loopback judged by address, never by a name's first characters;
  - no secret reads but the Max plan's own token from a token file; a key CLIVE makes for itself is
    kept in memory and never reaches a store;
  - a run whose world is not the fake shop stops before it asks a single question;
  - the read-only latch goes down for a run, and no write can be applied;
  - an Anthropic API key in the environment stops the bench before anything (MAP rule 5);
  - leaving the seal puts every seam back.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from app import readonly
from app.bench import persona
from app.bench.isolation import BenchIsolationError, Seal, is_loopback
from app.bench.models import MaxPlanModel
from app.bench.runner import Caps, Run
from app.bench.store import Bench
from app.providers.max_agent_sdk import BillingGuardError
from app.secrets import keychain


@pytest.fixture
def latch_put_back(monkeypatch):
    """The latch is one-way in a real process. The suite is one process, so a test that latches it
    has it lifted again on the way out, by monkeypatch, never by anything in app/."""
    monkeypatch.setattr(readonly, "_engaged", readonly._engaged)
    monkeypatch.setattr(readonly, "_reason", readonly._reason)


def test_every_way_out_is_refused_and_recorded():
    from app.clients import crooks_returns, instagram, ship24, youtube
    from app.clients.elevenlabs import ScribeClient
    from app.clients.gmail import GmailClient
    from app.clients.shopify import ShopifyClient
    from experience.fixtures import FixtureShopify

    real_before = ShopifyClient("x.myshopify.com", "2025-07")      # built before the seal, like CLIVE's own at boot
    with Seal(latch=False) as seal:
        seal.arm_clients()
        attempts = [
            lambda: socket.create_connection(("93.184.216.34", 443)),
            lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("127.0.0.1", 9)),
            lambda: socket.getaddrinfo("example.com", 443),
            lambda: httpx.AsyncClient(),
            lambda: httpx.Client(),
            lambda: instagram.http_client(),
            lambda: crooks_returns.http_client(5.0),
            lambda: ship24.http_client(5.0),
            lambda: youtube.http_client(),
            lambda: real_before._client(),
            lambda: ShopifyClient("x.myshopify.com", "2025-07"),
            lambda: GmailClient().service(),
            lambda: ScribeClient(),
        ]
        for attempt in attempts:
            with pytest.raises(BenchIsolationError):
                attempt()
        assert seal.count() == len(attempts)
        assert {b["what"] for b in seal.breaches} >= {"a network connection", "looking up a host", "a real HTTP client",
                                                      "a real Shopify connection", "a real Shopify client", "a real Gmail service"}
        assert all(b["from"] and b["at"] for b in seal.breaches)
        # The fake shop's own client is built as before, and loopback names still resolve.
        assert type(FixtureShopify()).__name__ == "FixtureShopify"
        assert socket.getaddrinfo("localhost", 80)
    # Every seam is put back on the way out.
    httpx.AsyncClient()
    assert ShopifyClient("x.myshopify.com", "2025-07").shop_domain == "x.myshopify.com"


def _on(make, act):
    """A socket made, used once, and closed whatever happened."""
    def attempt():
        sock = make()
        try:
            return act(sock)
        finally:
            sock.close()
    return attempt


def test_what_never_passes_the_socket_class_is_refused_and_recorded_too():
    """Review note N1 (8 Oct): a UDP send, a TCP fast-open send, the C-level _socket's own connect,
    gethostbyname and a name starting "127." all went out with no breach. Each is refused now."""
    import _socket

    inet, udp, tcp = socket.AF_INET, socket.SOCK_DGRAM, socket.SOCK_STREAM
    attempts = {
        "a UDP send": _on(lambda: socket.socket(inet, udp), lambda s: s.sendto(b"x", ("8.8.8.8", 53))),
        "a TCP fast-open send": _on(lambda: socket.socket(inet, tcp), lambda s: s.sendto(b"x", socket.MSG_FASTOPEN, ("1.1.1.1", 80))),
        "a sendmsg": _on(lambda: socket.socket(inet, udp), lambda s: s.sendmsg([b"x"], [], 0, ("8.8.8.8", 53))),
        "a send to a name": _on(lambda: socket.socket(inet, udp), lambda s: s.sendto(b"x", ("example.com", 53))),
        "_socket's connect": _on(lambda: _socket.socket(inet, tcp), lambda s: s.connect(("1.1.1.1", 80))),
        "_socket's connect_ex": _on(lambda: _socket.socket(inet, tcp), lambda s: s.connect_ex(("1.1.1.1", 443))),
        "_socket's send": _on(lambda: _socket.socket(inet, udp), lambda s: s.sendto(b"x", ("8.8.8.8", 53))),
        "_socket's sendmsg": _on(lambda: _socket.socket(inet, udp), lambda s: s.sendmsg([b"x"], [], 0, ("9.9.9.9", 53))),
        "a port open to the network": _on(lambda: socket.socket(inet, udp), lambda s: s.bind(("0.0.0.0", 0))),
        "gethostbyname": lambda: socket.gethostbyname("example.com"),
        "gethostbyname_ex": lambda: socket.gethostbyname_ex("example.com"),
        "gethostbyaddr": lambda: socket.gethostbyaddr("1.1.1.1"),
        "getnameinfo": lambda: socket.getnameinfo(("1.1.1.1", 80), 0),
        "_socket's getaddrinfo": lambda: _socket.getaddrinfo("example.com", 443),
        "a name starting 127.": lambda: socket.getaddrinfo("127.example.com", 80),
    }
    with Seal(latch=False) as seal:
        for name, attempt in attempts.items():
            with pytest.raises(BenchIsolationError):
                attempt()
            assert seal.count() == list(attempts).index(name) + 1, f"{name}: refused, but not recorded once"
        assert {b["what"] for b in seal.breaches} == {"sending on the network", "a network connection",
                                                       "a port open to the network", "looking up a host"}
        # Loopback is still this machine's own, judged by its address: a send, a port, a lookup.
        _on(lambda: _socket.socket(inet, udp), lambda s: s.sendto(b"x", ("127.0.0.1", 9)))()
        _on(lambda: socket.socket(inet, udp), lambda s: s.bind(("127.0.0.1", 0)))()
        assert socket.getaddrinfo("127.0.0.2", 80) and socket.gethostbyname("localhost")
        assert seal.count() == len(attempts)
    # Python cannot take the hook out; with no seal on it lets everything through.
    _on(lambda: _socket.socket(inet, udp), lambda s: s.bind(("0.0.0.0", 0)))()


@pytest.mark.parametrize("host", ["127.0.0.1", "127.255.0.9", "::1", "::1%lo", "::ffff:127.0.0.1", "localhost",
                                  "LOCALHOST.", b"127.0.0.1"])
def test_loopback_is_judged_by_its_address(host):
    assert is_loopback(host)


@pytest.mark.parametrize("host", ["127.example.com", "127.0.0.1.nip.io", "localhost.example.com", "1.1.1.1", "0.0.0.0",
                                  "::", "::ffff:1.1.1.1", "", None])
def test_anything_else_is_not_loopback(host):
    assert not is_loopback(host)


def test_no_secret_but_the_plans_own_token_and_nothing_is_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("CROOKS_SECRET_DIR", str(tmp_path / "secrets"))
    token = tmp_path / "plan-token"
    token.write_text("the-plans-token\n", encoding="utf-8")
    with Seal(latch=False):
        assert keychain.get_optional("claude_oauth_token") is None                 # no token file: the CLI's own login
    with Seal(latch=False, token_file=token):
        assert keychain.get("claude_oauth_token") == "the-plans-token"
        for key in ("shopify_client_id", "shopify_client_secret", "gmail_token", "elevenlabs_api_key",
                    "instagram_access_token", "github_engineering_inbox_token", "ship24_api_key", "crooks_returns_write_key"):
            assert not keychain.present(key)
            with pytest.raises(keychain.SecretMissing):
                keychain.get(key)
        keychain.set_secret("media_signing_key", "made-in-this-run")              # CLIVE's own, made at start-up
        assert keychain.get("media_signing_key") == "made-in-this-run"
        assert MaxPlanModel(cli_path=str(token))._auth_env(str(token)) == {"CLAUDE_CODE_OAUTH_TOKEN": "the-plans-token"}
    assert not (tmp_path / "secrets").exists()                                    # nothing reached a store
    assert keychain.get_optional("media_signing_key") is None                     # the suite's own stand-in again


async def test_a_run_whose_world_is_not_the_fake_shop_stops_before_it_asks(tmp_path, monkeypatch):
    from app.clients.shopify import ShopifyClient
    from app.tools import shopify_tools

    real = ShopifyClient("x.myshopify.com", "2025-07")
    george = persona.load(only=["george"])[0]
    question_set = {"set_id": "qs-20261008-0100-abcdef", "sha256": "abcdef", "questions": [
        {"id": "q001", "persona": "george", "access": "owner", "category": "in_scope", "turns": ["show me order 1938"]},
        {"id": "q002", "persona": "george", "access": "owner", "category": "in_scope", "turns": ["and 1940"]}]}
    bench = Bench(tmp_path / "bench")
    prepare = Run._prepare

    async def wired_wrong(self, h, chosen):
        await prepare(self, h, chosen)
        shopify_tools.bind(real)              # a wiring slip: the tools now hold a real shop

    monkeypatch.setattr(Run, "_prepare", wired_wrong)
    with Seal(latch=False, scratch=tmp_path) as seal:
        run = Run(question_set, bench=bench, seal=seal, caps=Caps(concurrency=1), mode="scripted", people={"george": george})
        run_id = await run.go()
    manifest = bench.manifest(run_id)
    assert manifest["status"] == "stopped" and "seal" in manifest["stopped"] and manifest["breaches"] >= 1
    [first] = bench.results(run_id)                                               # the second was never asked
    assert first["turns"] == [] and "not the fake shop" in first["error"]
    assert first["safety"]["breaches"][0]["what"] == "a world that is not the fake shop"
    assert manifest["not_run"] == 1


def test_the_latch_goes_down_for_a_run_and_no_change_can_be_applied(latch_put_back):
    with Seal(latch=True):
        assert readonly.active()
        with pytest.raises(readonly.WriteRefused):
            readonly.assert_writable("a refund")
    assert readonly.active(), "a latched process stays read-only after the run"


async def test_an_api_key_stops_the_bench_before_anything(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-pay-as-you-go-key")
    with pytest.raises(BillingGuardError):
        Seal(latch=False).__enter__()
    with pytest.raises(BillingGuardError):
        await MaxPlanModel().complete(purpose="judge", system="s", prompt="p", context={})
    httpx.AsyncClient()                                                           # the refused seal left nothing behind


def test_the_plans_model_is_given_no_tools_no_servers_and_nothing_from_this_machine(tmp_path, monkeypatch):
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    monkeypatch.setattr("app.providers.max_agent_sdk.cli_logged_in", lambda path: True)
    options = MaxPlanModel(model="sonnet", cli_path=str(cli)).options("the rubric")
    assert options.tools == [] and options.mcp_servers == {} and options.allowed_tools == []
    assert options.setting_sources == [] and options.max_turns == 1 and options.strict_mcp_config is True
    assert options.permission_mode == "dontAsk" and options.model == "sonnet" and options.env == {}
    monkeypatch.setattr("app.providers.max_agent_sdk.cli_logged_in", lambda path: False)
    with pytest.raises(RuntimeError, match="no Max-plan login"):
        MaxPlanModel(cli_path=str(cli)).options("the rubric")


async def test_a_bench_runs_assistants_load_no_mcp_server_of_the_hosts_and_clives_own_are_unchanged(tmp_path, monkeypatch):
    """Review note N5 (8 Oct): CLIVE's provider set no strict_mcp_config, so on worker-01 the claude CLI
    could bring George's own MCP servers and connectors into a bench turn (their tools were still denied
    by the gate, but that barrier was not the seal's). A bench run's assistants, the owner's and the
    team's, are strict now; CLIVE's own, as app/runtime.py makes them, name nothing new."""
    from app.bench.runner import fake_world
    from app.people.store import people as people_store
    from app.providers.max_agent_sdk import MaxAgentSDKProvider
    from config.settings import get_settings

    for name, folder in (("CROOKS_OBJECTIVES_DIR", "objectives"), ("CROOKS_SECRET_DIR", "secrets"), ("CROOKS_LOG_DIR", "logs")):
        monkeypatch.setenv(name, str(tmp_path / folder))
    get_settings.cache_clear()
    started = []

    async def start(self):                                                        # no claude CLI in the suite
        started.append(self)

    monkeypatch.setattr(MaxAgentSDKProvider, "start", start)
    people = {p.id: p for p in persona.load(only=["george", "emily-and-the-packers"])}
    chosen = [{"id": "q001", "persona": "george", "access": "owner", "category": "in_scope", "turns": ["hi"]},
              {"id": "q002", "persona": "emily-and-the-packers", "access": "staff", "category": "in_scope", "turns": ["hi"]}]
    question_set = {"set_id": "qs-20261008-0100-abcdef", "sha256": "abcdef", "questions": chosen}

    def options(provider):
        provider._auth_mode = "cli"                                               # the CLI's own login: no token read
        return provider._options()

    with Seal(latch=False, scratch=tmp_path) as seal:
        run = Run(question_set, bench=Bench(tmp_path / "bench"), seal=seal, caps=Caps(concurrency=1), mode="max", people=people)
        async with fake_world() as h:
            clives_own = h.runtime.staff_provider_factory                          # as app/runtime.py made it
            await run._prepare(h, chosen)
            owner, card = h.runtime.provider, run.cards["emily-and-the-packers"]
            staff = h.runtime.staff_provider(card)
            assert started == [owner] and isinstance(staff, MaxAgentSDKProvider) and staff is not owner
            assert options(owner).strict_mcp_config is True and options(staff).strict_mcp_config is True
            theirs = clives_own(people_store.get(card))
            assert theirs.strict_mcp_config is True and options(theirs).strict_mcp_config is True
    plain = MaxAgentSDKProvider(system_prompt="sys")
    assert plain.strict_mcp_config is False and options(plain).strict_mcp_config is False
    # Not even named by default: a plain provider's options are the call they were, whatever SDK the server
    # has; production's assistants are now strict too (DEC-071 ruling 26), so theirs name it as the bench's do.
    import claude_agent_sdk

    named, real = [], claude_agent_sdk.ClaudeAgentOptions

    def recorded(**kwargs):
        named.append(set(kwargs))
        return real(**kwargs)

    monkeypatch.setattr(claude_agent_sdk, "ClaudeAgentOptions", recorded)
    options(plain)
    options(theirs)
    options(owner)
    assert ["strict_mcp_config" in n for n in named] == [False, True, True]
