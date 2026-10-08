"""What /health tells a caller the owner rule refuses: liveness, and nothing of the owner's.

These lived in tests/test_pad.py until the CROOKS Pad was removed from the app on the owner's
ruling of 8 October (DEC-071, ruling 40). The pad's own tests went with it; these guard /health
itself, which is live, so they moved here unchanged apart from the pad: the heartbeat each one
posted first is gone, and so is the `pad` block the owner's whole document used to carry.

Round 7 and round 8 of the 2026-09-27 deploy review (F-NEW-PAD) are why they exist: /health is
public, so anything that can reach the port can ask, and such a caller gets liveness alone —
whether the server is well overall, which build, how long it has been up, and the two checks that
say whether its own guards are working. tests/test_followups_voice_records.py builds on the
helpers here.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.actions.ledger import NullLedger
from app.main import app
from app.observability import timeline as timeline_module
from app.observability.session import TestSessions
from app.observability.timeline import Timeline
from app.session.manager import SessionManager
from tests.test_actions_routes import PROXIED, FakeProvider, configure


@pytest.fixture()
async def client(monkeypatch, tmp_path):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        runtime.actions.ledger = NullLedger()
        runtime.sessions = SessionManager()
        runtime.tests = TestSessions(tmp_path / "logs")
        runtime.timeline = timeline_module.install(Timeline(runtime.tests))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.runtime = runtime
            c.tmp = tmp_path
            yield c
        runtime.timeline.stop()
        timeline_module.install(timeline_module.NullTimeline())


async def test_the_public_health_check_keeps_the_session_to_the_owner(client):
    """Round 7, F-NEW-PAD: public /health served the test session's name and whether it was
    recording to anyone who could reach the port. Liveness stays public; that block is the
    owner's."""
    configure(client, logins="owner@example.com", local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False})
    here = (await client.get("/health")).json()
    # Round 8, F-NEW-PAD: not blocks withheld from the rest, but liveness alone, marked so.
    assert "pad" not in here and "observability" not in here and here["limited"] is True
    assert here["status"] in ("ok", "degraded") and "checks" in here, "liveness is still everyone's"
    mine = (await client.get("/health", headers=PROXIED)).json()
    assert "observability" in mine and "withheld" not in mine


# ------------------------------------------------ round 8, F-NEW-PAD: liveness, and nothing else


LIVENESS_KEYS = {"status", "build", "uptime_s", "checks", "limited"}
SECRET_DETAIL = "shop-detail-for-owner@example.com"


def _limited_to_liveness(body: dict) -> None:
    """Exactly what a caller the owner rule refuses may read, and nothing of the owner's. The
    service always runs its housekeeper, so its check is always there: a verdict, passing or
    failing, and nothing else (round 12, T1-04: a missing one passed on a default)."""
    assert set(body) == LIVENESS_KEYS, sorted(body)
    assert body["limited"] is True and body["status"] in ("ok", "degraded")
    assert set(body["checks"]) == {"proxy_identity", "housekeeping"}, sorted(body["checks"])
    assert set(body["checks"]["proxy_identity"]) == {"ok", "detail"}
    assert isinstance(body["checks"]["proxy_identity"]["ok"], bool)
    housekeeping = body["checks"]["housekeeping"]
    assert isinstance(housekeeping, dict) and set(housekeeping) == {"ok"}, housekeeping
    assert isinstance(housekeeping["ok"], bool), housekeeping
    text = str(body)
    for owners in (SECRET_DETAIL, "RuntimeError", "sessions", "writes", "capabilities", "families",
                   "orders_cache", "manifest", "voice", "speech", "pad", "observability", "cached"):
        assert owners not in text, owners


async def _production_with_a_failing_check(client):
    """Production's switches, a conversation open and a check failing with an exception whose
    text is the owner's business."""
    configure(client, logins="owner@example.com", local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False})
    client.runtime.sessions.get_or_create("open-conversation")

    async def failing():
        raise RuntimeError(SECRET_DETAIL)

    client.runtime.shopify.health = failing
    app.state.health_cache = None


async def test_a_caller_the_owner_rule_refuses_gets_liveness_before_and_after_the_owner(client, monkeypatch):
    """A headerless request from the server with production's switches, and a device carrying the
    owner's login that Tailscale says is someone else's: each gets liveness alone, fresh or cached,
    before the owner has asked and after — and the owner's own verified device gets the whole
    document, fresh or cached, before them and after. The two answers are made per request from
    one shared result, so neither is ever served to the other."""
    from app import identity

    await _production_with_a_failing_check(client)
    client.runtime.settings = client.runtime.settings.model_copy(update={"tailscale_verify": True})
    identity.bind_peer_check(lambda client_, server: (True, "opened by tailscaled (pid 1)"))
    identity.bind_self_check(lambda address: False)
    identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": "owner@example.com" if address == "100.64.0.9" else "other@example.com"}})
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")
    not_his = {"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.3"}

    first = (await client.get("/health")).json()                 # fills the cache, refused
    _limited_to_liveness(first)
    _limited_to_liveness((await client.get("/health", headers=not_his)).json())
    mine = (await client.get("/health", headers=PROXIED)).json()  # the owner, from the cache
    assert mine["cached"] is True and "limited" not in mine
    assert mine["sessions"] >= 1 and SECRET_DETAIL in mine["checks"]["shopify"]["detail"]
    assert {"writes", "capabilities", "families", "orders_cache", "observability"} <= set(mine)
    again = (await client.get("/health")).json()                 # refused again, from the cache
    _limited_to_liveness(again)
    assert again["build"] == mine["build"] and again["status"] == mine["status"]

    # And the other way about: the owner fills the cache, then the refused caller reads it.
    app.state.health_cache = None
    mine = (await client.get("/health?fresh=1", headers=PROXIED)).json()
    assert mine["cached"] is False and SECRET_DETAIL in mine["checks"]["shopify"]["detail"]
    _limited_to_liveness((await client.get("/health")).json())
    _limited_to_liveness((await client.get("/health?fresh=1")).json())
    assert (await client.get("/health", headers=PROXIED)).json()["checks"]["shopify"]["ok"] is False


async def test_the_servers_own_key_reads_the_whole_health_directly_and_never_through_the_proxy(client):
    """The host's own status readers carry the server's key (app/local_cli.py) and keep the whole
    document on loopback. Through `tailscale serve` the key is refused outright — even from the
    owner's own device, which would have had the whole document without it."""
    from app import local_cli

    await _production_with_a_failing_check(client)
    key = "k" * 43
    local_cli.bind_key(key)
    direct = await client.get("/health", headers={local_cli.HEADER: key})
    assert direct.status_code == 200 and "limited" not in direct.json()
    assert SECRET_DETAIL in direct.json()["checks"]["shopify"]["detail"] and direct.json()["sessions"] >= 1
    for value in (key, "wrong", ""):
        proxied = await client.get("/health", headers={**PROXIED, local_cli.HEADER: value})
        assert proxied.status_code == 403 and proxied.json()["code"] == "local_key_misused", repr(value)
    for value in ("k" * 42, ""):
        wrong = await client.get("/health", headers={local_cli.HEADER: value})
        assert wrong.status_code == 403 and wrong.json()["code"] == "local_key_misused", repr(value)
    # The key opens /health to be read, and nothing else about it.
    assert (await client.post("/health", headers={local_cli.HEADER: key})).status_code == 403
    _limited_to_liveness((await client.get("/health")).json())


def test_the_identity_checks_detail_is_only_ever_one_of_its_own_sentences(monkeypatch):
    """The one detail liveness keeps must never carry an exception's text: every sentence
    served_without_proxy_headers can say is written in the code, the count of rewritten requests
    being the only thing that varies."""
    import re

    from app import identity

    allowed = re.compile(
        r"not started by uvicorn from the command line: nothing to check"
        r"|uvicorn started with --no-proxy-headers"
        r"|uvicorn was started without --no-proxy-headers: every forwarded request is refused"
        r"|this process's command line could not be read"
        r"|\d+ forwarded request\(s\) arrived with their address already replaced")
    uvicorn = ["python", "-m", "uvicorn", "app.main:app"]
    for seen in (0, 3):
        monkeypatch.setattr(identity, "rewritten_seen", seen)
        for argv in (["python", "-m", "pytest"], uvicorn, [*uvicorn, "--no-proxy-headers"],
                     [*uvicorn, "--no-proxy-headers", "--proxy-headers"], None):
            _ok, detail = identity.served_without_proxy_headers(argv)
            assert allowed.fullmatch(detail), detail

    def unreadable(self):
        raise PermissionError("an exception's own words")

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    assert identity.served_without_proxy_headers() == (False, "this process's command line could not be read")
