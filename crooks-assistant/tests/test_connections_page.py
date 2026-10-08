"""The Connections screen's purpose (app/connections/service.py, catalog.py, routes/connections.py).

George, 2 October 2026: "Improve the current connections screen, design + purpose. For me it's
currently messy, it asks for API keys when not needed and is clunky to use." What is held here, on
the answer the screen is drawn from:

- a working connection asks for no key; one not connected asks for exactly the keys it is missing;
  one whose key the service refused asks for that key again, and one whose service only did not
  answer asks for none (Check again puts it right);
- Instagram asks to sign in, never for a token, once its app is in; a sign-in running out is the
  owner's to see before it stops;
- Gmail, set up at the server, asks for nothing here, and reads as connected when it answers,
  wherever its credential lives;
- each connection says what it unlocks from the capability registry itself, and what stops
  without it;
- opening the screen asks every connected service again, each at most once a minute, changes
  nothing, needs the owner, and never answers with a secret.

The page's own drawing of these is tests/web/connections.test.js (run below) and, in a real
browser, tests/test_connections_browser.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.clients import gmail as gmail_client
from app.clients import instagram as instagram_client
from app.connections import catalog, ledger, service, testers
from app.secrets import vault
from tests.fake_credentials import DIGITS, HEX, bearer_token, body
from tests.test_connections_routes import (  # noqa: F401 - `world` is a fixture, `client` the one it stands on
    HEADERS,
    KEY,
    PROXIED,
    client,
    register,
    save,
    world,
)

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


async def cards(http, path="/connections/state"):
    answer = await (http.get(path, headers=PROXIED) if path.endswith("state") else http.post(path, json={}, headers=HEADERS))
    assert answer.status_code == 200, answer.text
    return {c["name"]: c for c in answer.json()["connections"]}, answer


def calls_to(http, host):
    return [c for c in http.services.calls if c.url.host == host]


# ------------------------------------------------------------------ a key only where one is needed

async def test_a_working_connection_asks_for_no_key(world):  # noqa: F811 - the fixture imported above
    await register(world)
    assert (await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})).status_code == 200
    shown, _ = await cards(world)
    voice = shown["elevenlabs"]
    assert (voice["state"], voice["group"], voice["fix"], voice["needs"]) == ("connected", "working", "", [])
    assert voice["tested_at"], "a working row says when it was checked"


async def test_a_missing_key_asks_for_exactly_the_keys_missing(world):  # noqa: F811 - the fixture imported above
    shown, _ = await cards(world)
    assert (shown["elevenlabs"]["group"], shown["elevenlabs"]["needs"]) == ("add", ["elevenlabs_api_key"])
    assert shown["ship24"]["needs"] == ["ship24_api_key"] and shown["youtube"]["needs"] == ["youtube_api_key"]
    assert shown["shopify"]["needs"] == ["shopify_client_id", "shopify_client_secret"]
    vault.store("shopify_client_id", body("page-shopify-id", 32, HEX))
    shown, _ = await cards(world)
    assert shown["shopify"]["needs"] == ["shopify_client_secret"], "only what is still missing"


async def test_a_refused_key_asks_for_that_key_and_a_service_that_did_not_answer_asks_for_none(world):  # noqa: F811 - the fixture imported above
    await register(world)
    await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})
    world.services.elevenlabs = 401
    await world.post("/connections/elevenlabs/test", json={}, headers=HEADERS)
    shown, _ = await cards(world)
    refused = shown["elevenlabs"]
    assert (refused["group"], refused["fix"], refused["needs"]) == ("attention", "key", ["elevenlabs_api_key"])
    world.services.elevenlabs = 503
    await world.post("/connections/elevenlabs/test", json={}, headers=HEADERS)
    shown, _ = await cards(world)
    down = shown["elevenlabs"]
    assert (down["group"], down["fix"], down["needs"]) == ("attention", "retry", [])


async def test_instagram_asks_to_sign_in_never_for_a_token_once_its_app_is_in(world):  # noqa: F811 - the fixture imported above
    shown, _ = await cards(world)
    assert shown["instagram"]["needs"] == ["instagram_app_id", "instagram_app_secret"]
    await register(world)
    kept = await save(world, "instagram", {"instagram_app_id": body("page-ig", 16, DIGITS),
                                           "instagram_app_secret": body("page-ig-secret", 32, HEX)})
    assert kept.status_code == 200, kept.text
    shown, _ = await cards(world)
    ready = shown["instagram"]
    assert (ready["group"], ready["fix"], ready["needs"], ready["sign_in"]["ready"]) == ("add", "signin", [], True)


@pytest.fixture
def instagram_forgotten():
    """What this process learned about the Instagram token goes with the test that taught it."""
    yield
    instagram_client.reset()


async def test_a_sign_in_running_out_needs_the_owner_before_it_stops(world, instagram_forgotten):  # noqa: F811 - the fixture imported above
    await register(world)
    await save(world, "instagram", {"instagram_app_id": body("page-ig", 16, DIGITS),
                                    "instagram_app_secret": body("page-ig-secret", 32, HEX)})
    vault.store("instagram_access_token", bearer_token("page-ig-token"))
    await world.post("/connections/instagram/test", json={}, headers=HEADERS)
    shown, _ = await cards(world)
    assert shown["instagram"]["state"] == "connected"
    instagram_client._note(expires_at=time.time() + 3 * 86400 + 600)
    shown, _ = await cards(world)
    ending = shown["instagram"]
    assert (ending["group"], ending["fix"], ending["needs"], ending["expires_in_days"]) == ("attention", "signin", [], 3)
    assert "runs out in 3 days" in ending["detail"]


async def _instagram_signed_in(http):
    await register(http)
    await save(http, "instagram", {"instagram_app_id": body("page-ig", 16, DIGITS),
                                   "instagram_app_secret": body("page-ig-secret", 32, HEX)})
    vault.store("instagram_access_token", bearer_token("page-ig-token"))


async def test_instagram_missing_a_permission_is_put_right_by_signing_in_again(world, monkeypatch, instagram_forgotten):  # noqa: F811
    """The review of 889f3284 (note 3): a token that lacks a permission, or a scope Instagram has
    not granted, is put right by signing in again and allowing it, not by a new key or by waiting."""
    await _instagram_signed_in(world)

    async def lacks(values, settings, changed=frozenset()):
        return testers.Outcome(False, "Instagram accepted the token but it lacks a permission CLIVE needs.",
                               fix="service")

    monkeypatch.setitem(testers.TESTERS, "instagram", lacks)
    await world.post("/connections/instagram/test", json={}, headers=HEADERS)
    shown, _ = await cards(world)
    assert (shown["instagram"]["group"], shown["instagram"]["fix"], shown["instagram"]["needs"]) == ("attention", "signin", [])


@pytest.mark.parametrize("family, kind", [
    ({"state": "MISSING_SCOPE", "detail": "instagram_business_manage_messages not granted"}, ""),
    ({"state": "TEMPORARILY_UNAVAILABLE", "detail": "@crooksldn: the last call was refused (permission)"}, "permission"),
])
async def test_instagram_refusing_its_sign_in_asks_to_sign_in_again(world, instagram_forgotten, family, kind):  # noqa: F811
    await _instagram_signed_in(world)
    await world.post("/connections/instagram/test", json={}, headers=HEADERS)
    if kind:
        instagram_client._note(last_error_kind=kind)
    world.runtime.family_states_table = {"instagram": family}
    shown, _ = await cards(world)
    ig = shown["instagram"]
    assert (ig["group"], ig["fix"], ig["needs"]) == ("attention", "signin", [])
    assert "(permission)" not in ig["detail"], "said in our words"


# ------------------------------------------------------------------ Gmail, set up at the server

async def test_gmail_asks_for_nothing_here_and_is_connected_when_it_answers(world, tmp_path, monkeypatch):  # noqa: F811 - the fixture imported above
    shown, _ = await cards(world)
    assert (shown["gmail"]["group"], shown["gmail"]["fix"], shown["gmail"]["needs"]) == ("add", "server", [])
    # The credential in the original set-up's token.json, which the client still reads.
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gmail_client, "TOKEN_PATH", token)
    answers = {"health": (True, "owner@example.com · read, compose (verified by Google)")}
    monkeypatch.setattr(world.runtime, "gmail", SimpleNamespace(health=lambda: answers["health"]))
    shown, _ = await cards(world, "/connections/check")
    gmail = shown["gmail"]
    assert (gmail["state"], gmail["who"], gmail["needs"], gmail["testable"]) == ("connected", "owner@example.com", [], True)
    answers["health"] = (False, "Gmail refresh was rejected (invalid_grant).")
    tested = await world.post("/connections/gmail/test", json={}, headers=HEADERS)
    assert tested.status_code == 200 and tested.json()["result"]["ok"] is False
    shown, _ = await cards(world)
    assert (shown["gmail"]["group"], shown["gmail"]["fix"], shown["gmail"]["needs"]) == ("attention", "server", [])
    assert "invalid_grant" not in json.dumps(shown["gmail"]), "said in our words"


# ------------------------------------------------------------------ the check on opening

def _rewind(name: str, seconds: float) -> None:
    """Make a connection's last test `seconds` older, as time passing would."""
    from datetime import UTC, datetime, timedelta

    table = ledger.last_tests()
    at = datetime.fromisoformat(table[name]["at"]) - timedelta(seconds=seconds)
    table[name]["at"] = at.astimezone(UTC).isoformat(timespec="seconds")
    ledger._replace(ledger._folder() / ledger.TESTS, json.dumps(table))


async def test_opening_the_screen_asks_each_connected_service_at_most_once_a_minute(world):  # noqa: F811 - the fixture imported above
    await register(world)
    await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})
    asked = len(calls_to(world, "api.elevenlabs.io"))
    await cards(world, "/connections/check")
    assert len(calls_to(world, "api.elevenlabs.io")) == asked, "tested a moment ago: not asked again"
    _rewind("elevenlabs", 61)
    shown, _ = await cards(world, "/connections/check")
    assert len(calls_to(world, "api.elevenlabs.io")) == asked + 1
    assert shown["elevenlabs"]["state"] == "connected"
    await cards(world, "/connections/check")
    assert len(calls_to(world, "api.elevenlabs.io")) == asked + 1, "opened again within the minute"
    others = {c.url.host for c in world.services.calls} - {"api.elevenlabs.io"}
    assert not others, f"only connected services are asked: {others}"


async def test_screens_opened_at_once_ask_each_service_once(world):  # noqa: F811 - the fixture imported above
    """The review of 889f3284: five screens opening together asked ElevenLabs five times, because a
    check claimed what it would ask only after a wait in which the others chose the same."""
    import asyncio

    await register(world)
    await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})
    _rewind("elevenlabs", 61)
    asked = len(calls_to(world, "api.elevenlabs.io"))
    answers = await asyncio.gather(*(world.post("/connections/check", json={}, headers=HEADERS) for _ in range(5)))
    assert all(a.status_code == 200 for a in answers)
    assert len(calls_to(world, "api.elevenlabs.io")) == asked + 1


async def test_a_check_that_breaks_is_recorded_and_not_asked_again_within_the_minute(world, monkeypatch):  # noqa: F811
    """A tester that fails in a way it does not name still counts as asked: the row says to check
    again, and opening the screen again within the minute does not ask again."""
    await register(world)
    await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})
    _rewind("elevenlabs", 61)
    broke: list[int] = []

    async def breaks(values, settings):
        broke.append(1)
        raise RuntimeError("an answer nobody expected")

    monkeypatch.setitem(testers.TESTERS, "elevenlabs", breaks)
    shown, _ = await cards(world, "/connections/check")
    assert broke == [1]
    voice = shown["elevenlabs"]
    assert (voice["group"], voice["fix"], voice["needs"]) == ("attention", "retry", [])
    assert "an answer nobody expected" not in json.dumps(voice), "said in our words"
    await cards(world, "/connections/check")
    assert broke == [1], "asked again within the minute"


async def test_the_check_is_the_owners_changes_nothing_and_never_answers_with_a_secret(world):  # noqa: F811 - the fixture imported above
    stranger = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
    assert (await world.post("/connections/check", json={}, headers=stranger)).status_code == 403
    assert (await world.post("/connections/check", json={})).status_code == 403          # the server itself
    await register(world)
    await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})
    before = ledger.recent()
    _rewind("elevenlabs", 120)
    _, answer = await cards(world, "/connections/check")
    assert ledger.recent() == before, "a check is not a change"
    assert KEY not in answer.text and answer.headers["cache-control"] == "no-store"
    assert answer.json()["check_every_s"] == 60 and answer.json()["now"]


# ------------------------------------------------------------------ what each one is for

def test_each_connection_says_what_it_unlocks_from_the_registry_and_what_stops_without_it():
    from app.capabilities import families
    from app.families import load_all
    from app.tools import (  # noqa: F401 - register their families
        engineering_tools,
        instagram_tools,
        messaging_tools,
        returns_tools,
        ship24_tools,
        shipping_tools,
    )

    load_all()
    for connection in catalog.CONNECTIONS:
        assert connection.what and connection.without.startswith("Without it"), connection.name
        assert connection.unlocks or connection.abilities, connection.name
        for key in connection.unlocks:
            assert families.get(key) is not None, f"{connection.name} names {key}, which is not a registered family"
    shopify = service._unlocks(catalog.get("shopify"), {"order_refund": {"state": "READ_ONLY"}})
    assert {"label": "Refunding", "state": "READ_ONLY"} in shopify
    assert all(u["state"] != "NOT_IMPLEMENTED" for u in shopify)


def test_what_the_voice_falls_back_to_is_said_for_this_server():
    voice = catalog.get("elevenlabs")
    speak = SimpleNamespace(voice_name="Derek")
    with_whisper = SimpleNamespace(settings=SimpleNamespace(stt_primary="scribe", whisper_enabled=True), voice=speak)
    without = SimpleNamespace(settings=SimpleNamespace(stt_primary="scribe", whisper_enabled=False), voice=speak)
    assert "server's own recogniser" in service._without(with_whisper, voice)
    assert "can't hear you" in service._without(without, voice)
    assert service._what(without, voice) == "Hears you and speaks in Derek's voice."


@pytest.mark.parametrize("outcome, fix", [
    (testers.Outcome(False, "refused"), "key"),
    (testers.Outcome(False, "not answering", fix="retry"), "retry"),
    (testers.Outcome(False, "switch it on there", fix="service"), "service"),
])
def test_a_failed_test_names_what_puts_it_right(outcome, fix):
    assert outcome.as_dict()["fix"] == fix
    assert "fix" not in testers.Outcome(True, "fine").as_dict()


async def test_a_service_that_does_not_answer_is_retry_not_a_new_key(monkeypatch):
    import httpx

    def down(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(testers, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(down)))
    outcome = await testers.run("ship24", {"ship24_api_key": body("page-ship24", 32)}, None)
    assert not outcome.ok and outcome.fix == "retry"


# ------------------------------------------------------------------ the page's rows, under Node

@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_rows_under_node():
    result = subprocess.run([NODE, "--test", str(ROOT / "tests" / "web" / "connections.test.js")],
                            capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_voice_panel_under_node():
    """tests/web/connections-voice.test.js: a slider or the speaker boost is sent only when he moved
    it or it is stored, and an untouched one shows the voice's own value only as ElevenLabs reported it."""
    result = subprocess.run([NODE, "--test", str(ROOT / "tests" / "web" / "connections-voice.test.js")],
                            capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
