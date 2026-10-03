"""The Connections screen's routes end to end (app/routes/connections.py): the door, a fresh passkey
for every change, a key tested before it is stored, stored encrypted in the app tier and live at
once, recorded without its value, and "Sign in with Instagram" from the button to a stored token.

Real passkey signatures (tests/fake_passkey.py), a stand-in cipher (tests/test_secrets_vault.py),
and every service answered by an httpx.MockTransport: nothing reaches the network or a Keychain.
"""

from __future__ import annotations

import hashlib
import json
import logging
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.clients import instagram as instagram_client
from app.connections import instagram as sign_in
from app.connections import ledger, passkeys, service, testers
from app.logging.quiet import QuietPollsFilter
from app.main import app
from app.secrets import keychain, linux_store, vault
from app.speech import voice_prefs
from tests.fake_credentials import DIGITS, HEX, bearer_token, body, elevenlabs_key
from tests.fake_passkey import ORIGIN, RP_ID, Authenticator
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)
from tests.test_secrets_vault import BrokenCipher, FakeCipher

HEADERS = {**PROXIED, "Origin": ORIGIN, "X-Forwarded-Host": RP_ID}
KEY = elevenlabs_key("connections-route")
APP_ID = body("ig-app-id", 16, DIGITS)
APP_SECRET = body("ig-app-secret", 32, HEX)
SHORT = bearer_token("ig-short")
LONG = bearer_token("ig-long")
REDIRECT = f"{ORIGIN}/connections/instagram/callback"

# The genuine functions, captured before conftest's `_no_secrets` replaces them for each test: these
# tests store through the app tier in a temporary directory and read back through it, as production does.
_REAL = {name: getattr(keychain, name) for name in ("get", "get_optional", "present", "where")}


class Services:
    """Every service a key is tested against, or a sign-in talks to."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.elevenlabs = 200
        # The account's voices, as ElevenLabs answers GET /voices/{id}: a name and its own settings.
        self.voices: dict[str, dict] = {}
        self.instagram_token = 200
        self.granted = "instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host, path = request.url.host, request.url.path
        if host == "api.elevenlabs.io" and path.startswith("/v1/voices/"):
            found = self.voices.get(path.rsplit("/", 1)[-1])
            return (httpx.Response(200, json={"voice_id": path.rsplit("/", 1)[-1], **found}) if found
                    else httpx.Response(404, json={"detail": {"status": "voice_not_found"}}))
        if host == "api.elevenlabs.io":
            return httpx.Response(self.elevenlabs, json={"detail": {"status": "invalid_api_key"}}
                                  if self.elevenlabs == 401 else [{"model_id": "scribe_v1"}])
        if host == "api.instagram.com" and path == "/oauth/access_token":
            return httpx.Response(self.instagram_token, json={"data": [
                {"access_token": SHORT, "user_id": "17841400000000000", "permissions": self.granted}]}
                if self.instagram_token == 200 else {"error_type": "OAuthException", "error_message": "MARKER"})
        if host == "graph.instagram.com" and path == "/access_token":
            return httpx.Response(200, json={"access_token": LONG, "token_type": "bearer", "expires_in": 5_183_944})
        if host == "graph.instagram.com" and path.endswith("/me"):
            return httpx.Response(200, json={"user_id": "17841400000000000", "username": "crooksldn"})
        return httpx.Response(404, json={"error": "unexpected call in the test"})


@pytest.fixture
async def world(client, tmp_path, monkeypatch):  # noqa: F811 - fixtures imported from the suite they belong to
    configure(client, logins=f"{OWNER},partner@example.com")
    # Only the owner's device, through Tailscale: the server itself does not speak for him here.
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False})
    monkeypatch.setenv(linux_store.STORE_DIR_ENV, str(tmp_path / "secrets"))
    monkeypatch.delenv(linux_store.CREDENTIALS_ENV, raising=False)
    monkeypatch.setattr(keychain, "_on_linux", lambda: True)
    for name, function in _REAL.items():
        monkeypatch.setattr(keychain, name, function)
    vault.bind(FakeCipher())
    service.configure(state_dir=tmp_path / "secrets" / vault.DIR_NAME)
    voice_prefs.configure(state_dir=tmp_path / "secrets" / vault.DIR_NAME)
    passkeys.reset()
    sign_in.reset()
    services = Services()
    transport = httpx.MockTransport(services)
    monkeypatch.setattr(testers, "http_client", lambda: httpx.AsyncClient(transport=transport))
    monkeypatch.setattr(instagram_client, "http_client", lambda: httpx.AsyncClient(transport=transport))
    instagram_client.configure(state_path=tmp_path / "instagram.json")
    refreshed: list[int] = []

    async def family_states():
        refreshed.append(1)
        return {}

    monkeypatch.setattr(client.runtime, "family_states", family_states)
    client.services = services
    client.refreshed = refreshed
    client.device = Authenticator()
    yield client
    vault.bind()
    passkeys.reset()
    sign_in.reset()


def speaking(http):
    """The runtime's voice, with a key and ElevenLabs answered by the stand-in services."""
    voice = http.runtime.voice
    voice.enabled, voice._key, voice.base_url = True, KEY, "https://api.elevenlabs.io/v1"
    voice._http = httpx.AsyncClient(transport=httpx.MockTransport(http.services))
    return voice


async def register(http, device=None, *, approval=None):
    device = device or http.device
    begun = await http.post("/connections/passkeys/begin", json={"approval": approval} if approval else {},
                            headers=HEADERS)
    assert begun.status_code == 200, begun.text
    done = await http.post("/connections/passkeys", json={"credential": device.create(begun.json()["publicKey"])},
                           headers=HEADERS)
    assert done.status_code == 200, done.text
    return done.json()["passkey"]


async def approval(http, action, device=None):
    asked = await http.post("/connections/approve", json={"action": action}, headers=HEADERS)
    assert asked.status_code == 200, asked.text
    return (device or http.device).get(asked.json()["publicKey"])


def sealed(values):
    """The values as the page sends them, and the digest its passkey signs (app/routes/connections.py)."""
    text = json.dumps(values)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


async def save(http, name, values):
    text, digest = sealed(values)
    return await http.post(f"/connections/{name}", headers=HEADERS,
                           json={"values_json": text, "approval": await approval(http, f"save:{name}:{digest}")})


# ------------------------------------------------------------------ the page and the door

async def test_the_screen_and_its_state_are_the_owners_and_hold_no_secret(world):
    page = await world.get("/connections", headers=PROXIED)
    assert page.status_code == 200 and "Connections" in page.text and "connections.js" in page.text
    policy = page.headers["content-security-policy"]
    assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert page.headers["x-frame-options"] == "DENY" and page.headers["referrer-policy"] == "no-referrer"
    assert (await world.get("/connections")).status_code == 403          # the server itself, not the owner
    stranger = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
    assert (await world.get("/connections/state", headers=stranger)).status_code == 403
    await register(world)
    assert (await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})).status_code == 200
    state = await world.get("/connections/state", headers={**PROXIED, "X-Forwarded-Host": RP_ID})
    assert state.status_code == 200 and state.headers["cache-control"] == "no-store"
    assert KEY not in state.text
    cards = {c["name"]: c for c in state.json()["connections"]}
    assert cards["elevenlabs"]["state"] == "connected"
    assert cards["elevenlabs"]["fields"][0]["where"] == "saved here"
    assert cards["instagram"]["sign_in"]["redirect_uri"] == REDIRECT
    assert [p["label"] for p in state.json()["passkeys"]] == ["a device"]


# ------------------------------------------------------------------ passkeys at the routes

async def test_a_second_passkey_needs_the_first_to_approve_it(world):
    await register(world)
    refused = await world.post("/connections/passkeys/begin", json={}, headers=HEADERS)
    assert refused.status_code == 403 and refused.json()["code"] == "passkey_missing"
    second = Authenticator()
    await register(world, second, approval=await approval(world, "passkey:add"))
    assert passkeys.count() == 2
    kinds = [c["action"] for c in ledger.recent()]
    assert kinds.count("passkey_added") == 2 and "approval_refused" in kinds


async def test_removing_a_passkey_needs_a_passkey(world):
    shown = await register(world)
    path = f"/connections/passkeys/{shown['id']}/remove"
    assert (await world.post(path, json={}, headers=HEADERS)).status_code == 403
    done = await world.post(path, headers=HEADERS,
                            json={"approval": await approval(world, f"passkey:remove:{shown['id']}")})
    assert done.status_code == 200 and passkeys.count() == 0


async def test_a_change_needs_this_clives_own_address_as_its_origin(world):
    await register(world)
    for origin in ("https://elsewhere.ts.net", "http://clive.tailnet-test.ts.net", ""):
        headers = {**HEADERS, "Origin": origin} if origin else {k: v for k, v in HEADERS.items() if k != "Origin"}
        asked = await world.post("/connections/approve", json={"action": "disconnect:elevenlabs"}, headers=headers)
        assert asked.status_code == 403, origin


async def test_every_change_needs_its_own_fresh_passkey(world):
    await register(world)
    text, digest = sealed({"elevenlabs_api_key": KEY})
    missing = await world.post("/connections/elevenlabs", json={"values_json": text}, headers=HEADERS)
    assert missing.status_code == 403 and missing.json()["code"] == "passkey_missing"
    other = await approval(world, f"save:youtube:{digest}")
    wrong = await world.post("/connections/elevenlabs", json={"values_json": text, "approval": other}, headers=HEADERS)
    assert wrong.status_code == 403 and wrong.json()["code"] == "passkey_stale"
    good = await approval(world, f"save:elevenlabs:{digest}")
    first = await world.post("/connections/elevenlabs", json={"values_json": text, "approval": good}, headers=HEADERS)
    assert first.status_code == 200
    again = await world.post("/connections/elevenlabs", json={"values_json": text, "approval": good}, headers=HEADERS)
    assert again.status_code == 403 and again.json()["code"] == "passkey_stale"


async def test_an_unknown_action_is_never_given_a_prompt(world):
    await register(world)
    for action in ("save:gmail", "save:nothing", "save:elevenlabs", "save:elevenlabs:" + "0" * 63,
                   "save:elevenlabs:" + "G" * 64, "drop:everything", "passkey:remove:../x", "x" * 2000):
        asked = await world.post("/connections/approve", json={"action": action}, headers=HEADERS)
        assert asked.status_code == 400, action


# ------------------------------------------------------------------ saving a key

async def test_a_saved_key_was_tested_first_is_encrypted_live_at_once_and_recorded_without_its_value(world, caplog):
    caplog.set_level(logging.DEBUG)
    await register(world)
    world.runtime.voice._key = "the-old-cached-key"
    done = await save(world, "elevenlabs", {"elevenlabs_api_key": "  " + KEY + "\n"})
    assert done.status_code == 200, done.text
    assert done.json()["result"]["ok"] is True and KEY not in done.text
    asked = [c for c in world.services.calls if c.url.host == "api.elevenlabs.io"]
    assert asked and asked[-1].headers["xi-api-key"] == KEY and KEY not in str(asked[-1].url)
    assert linux_store.read("elevenlabs_api_key") == KEY and linux_store.where("elevenlabs_api_key") == "app"
    stored = (linux_store.store_dir() / vault.DIR_NAME / "elevenlabs_api_key.cred").read_bytes()
    assert KEY.encode() not in stored
    assert world.runtime.voice._key is None                 # the old key is dropped: live at once
    assert world.refreshed                                   # and the families asked again
    change = ledger.recent()[0]
    assert change["action"] == "saved" and change["keys"] == ["elevenlabs_api_key"]
    assert KEY not in json.dumps(ledger.recent()) and KEY not in caplog.text


async def test_a_key_that_fails_its_test_is_never_stored(world):
    await register(world)
    world.services.elevenlabs = 401
    done = await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})
    assert done.status_code == 422 and done.json()["code"] == "test_failed"
    assert "refused that key" in done.json()["detail"]
    assert linux_store.where("elevenlabs_api_key") == ""
    assert ledger.recent()[0]["action"] == "refused" and ledger.recent()[0]["ok"] is False


@pytest.mark.parametrize("values, code", [
    ({"shopify_client_secret": "x"}, "bad_field"),
    ({"elevenlabs_api_key": "\x1b[A" + "k" * 20}, "bad_value"),
    ({"elevenlabs_api_key": "   "}, "nothing"),
    ("a string", "bad_request"),
])
async def test_what_no_key_could_be_is_refused_before_any_test(world, values, code):
    await register(world)
    done = await save(world, "elevenlabs", values)
    assert done.status_code == 400 and done.json()["code"] == code
    assert not [c for c in world.services.calls if c.url.host == "api.elevenlabs.io"]


async def test_a_server_that_cannot_encrypt_stores_nothing_and_says_why(world):
    await register(world)
    vault.bind(BrokenCipher(encrypt_fails=True))
    done = await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})
    assert done.status_code == 400 and done.json()["code"] == "store_unavailable"
    assert "No TPM2 device" in done.json()["detail"]
    vault.bind(FakeCipher())
    assert linux_store.where("elevenlabs_api_key") == ""


async def test_an_unknown_connection_is_not_found(world):
    await register(world)
    assert (await world.post("/connections/nothing/test", json={}, headers=HEADERS)).status_code == 404


# ------------------------------------------------------------------ testing and disconnecting

async def test_test_asks_again_with_what_is_stored_and_needs_no_passkey(world):
    await register(world)
    await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})
    world.services.elevenlabs = 401
    tested = await world.post("/connections/elevenlabs/test", json={}, headers=HEADERS)
    assert tested.status_code == 200 and tested.json()["result"]["ok"] is False
    state = await world.get("/connections/state", headers=PROXIED)
    card = next(c for c in state.json()["connections"] if c["name"] == "elevenlabs")
    assert card["state"] == "needs_attention"


async def test_disconnecting_takes_the_key_away_even_from_the_older_tiers(world):
    await register(world)
    await save(world, "elevenlabs", {"elevenlabs_api_key": KEY})
    linux_store.store_dir().mkdir(parents=True, exist_ok=True)
    (linux_store.store_dir() / "elevenlabs_api_key").write_text(elevenlabs_key("older"))
    refused = await world.post("/connections/elevenlabs/disconnect", json={}, headers=HEADERS)
    assert refused.status_code == 403
    done = await world.post("/connections/elevenlabs/disconnect", headers=HEADERS,
                            json={"approval": await approval(world, "disconnect:elevenlabs")})
    assert done.status_code == 200
    assert linux_store.read("elevenlabs_api_key") is None
    state = await world.get("/connections/state", headers=PROXIED)
    card = next(c for c in state.json()["connections"] if c["name"] == "elevenlabs")
    assert card["state"] == "not_connected" and card["fields"][0]["where"] == "disconnected here"
    assert ledger.recent()[0]["action"] == "disconnected"


# ------------------------------------------------------------------ Sign in with Instagram

async def _start_sign_in(world) -> str:
    await register(world)
    kept = await save(world, "instagram", {"instagram_app_id": APP_ID, "instagram_app_secret": APP_SECRET})
    assert kept.status_code == 200 and kept.json()["result"]["checked"] is False
    started = await world.post("/connections/instagram/sign-in", headers=HEADERS,
                               json={"approval": await approval(world, "signin:instagram")})
    assert started.status_code == 200, started.text
    url = started.json()["url"]
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "www.instagram.com", "/oauth/authorize")
    assert query["client_id"] == [APP_ID] and query["redirect_uri"] == [REDIRECT]
    assert query["scope"] == [",".join(sign_in.SCOPES)] and query["response_type"] == ["code"]
    assert APP_SECRET not in url
    return query["state"][0]


async def test_sign_in_with_instagram_ends_with_a_tested_long_lived_token_in_the_app_tier(world):
    state = await _start_sign_in(world)
    back = await world.get(f"/connections/instagram/callback?code=AQBcode123456&state={state}", headers=PROXIED)
    assert back.status_code == 303 and back.headers["location"] == "/connections?done=signed_in#instagram"
    token_call = next(c for c in world.services.calls if c.url.host == "api.instagram.com")
    sent = parse_qs(token_call.content.decode())
    assert token_call.method == "POST" and APP_SECRET not in str(token_call.url)
    assert sent["client_secret"] == [APP_SECRET] and sent["redirect_uri"] == [REDIRECT] and sent["code"] == ["AQBcode123456"]
    assert linux_store.read("instagram_access_token") == LONG
    assert linux_store.where("instagram_access_token") == "app"
    assert instagram_client.state()["expires_at"] > instagram_client.state()["refreshed_at"]
    actions = [c["action"] for c in ledger.recent()]
    assert actions[0] == "signed_in" and ledger.recent()[0]["ok"] is True
    replay = await world.get(f"/connections/instagram/callback?code=AQBcode123456&state={state}", headers=PROXIED)
    assert replay.headers["location"] == "/connections?error=stale#instagram"


async def test_a_sign_in_cancelled_on_instagram_changes_nothing(world):
    state = await _start_sign_in(world)
    back = await world.get(f"/connections/instagram/callback?error=access_denied&error_reason=user_denied&state={state}",
                           headers=PROXIED)
    assert back.headers["location"] == "/connections?error=cancelled#instagram"
    assert linux_store.where("instagram_access_token") == ""
    again = await world.get(f"/connections/instagram/callback?code=AQBcode123456&state={state}", headers=PROXIED)
    assert again.headers["location"] == "/connections?error=stale#instagram"


async def test_a_sign_in_cannot_be_finished_by_another_login(world):
    state = await _start_sign_in(world)
    partner = {"Tailscale-User-Login": "partner@example.com", "X-Forwarded-For": "100.64.0.10"}
    back = await world.get(f"/connections/instagram/callback?code=AQBcode123456&state={state}", headers=partner)
    assert back.headers["location"] == "/connections?error=not_yours#instagram"
    assert linux_store.where("instagram_access_token") == ""


async def test_instagrams_refusal_is_named_in_our_words_never_its_own(world):
    state = await _start_sign_in(world)
    world.services.instagram_token = 400
    back = await world.get(f"/connections/instagram/callback?code=AQBcode123456&state={state}", headers=PROXIED)
    assert back.headers["location"] == "/connections?error=refused#instagram"
    assert "MARKER" not in json.dumps(ledger.recent())


async def test_permissions_left_unticked_are_named(world):
    state = await _start_sign_in(world)
    world.services.granted = "instagram_business_basic"
    await world.get(f"/connections/instagram/callback?code=AQBcode123456&state={state}", headers=PROXIED)
    detail = ledger.recent()[0]["detail"]
    assert "did not allow messages and comments" in detail


async def test_sign_in_needs_the_app_id_and_secret_first(world):
    await register(world)
    started = await world.post("/connections/instagram/sign-in", headers=HEADERS,
                               json={"approval": await approval(world, "signin:instagram")})
    assert started.status_code == 400 and started.json()["code"] == "needs_app"


# ------------------------------------------------------------------ the log

def test_the_access_log_never_carries_a_connections_query():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("100.64.0.9:1", "GET", "/connections/instagram/callback?code=AQBsecret&state=s", "1.1", 303),
                               None)
    assert QuietPollsFilter().filter(record) is True
    assert "AQBsecret" not in record.getMessage() and "[not logged]" in record.getMessage()
    plain = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                              ("100.64.0.9:1", "GET", "/turn?x=1", "1.1", 200), None)
    QuietPollsFilter().filter(plain)
    assert "/turn?x=1" in plain.getMessage()


def test_the_app_serves_every_connections_route_where_the_door_walk_can_see_it():
    # In the schema, so tests/test_proxy_identity.py's walk of every route refuses each to a stranger.
    paths = {path for path in app.openapi()["paths"] if path.startswith("/connections")}
    assert {"/connections", "/connections/state", "/connections/approve", "/connections/passkeys/begin",
            "/connections/passkeys", "/connections/instagram/sign-in", "/connections/instagram/callback",
            "/connections/{name}", "/connections/{name}/test", "/connections/{name}/disconnect"} <= paths


async def test_the_server_itself_never_sets_up_a_passkey_or_changes_a_key(world):
    """The 1 October review (finding 1): with CROOKS_LOCAL_OWNER on, the server is the owner for his
    reads, but a process on it must not take the first passkey, approve a change or store a key."""
    world.runtime.settings = world.runtime.settings.model_copy(update={"local_owner": True})
    local = {"Origin": ORIGIN, "Host": RP_ID}
    text, digest = sealed({"elevenlabs_api_key": KEY})
    for path, sent in (("/connections/passkeys/begin", {}), ("/connections/approve", {"action": f"save:elevenlabs:{digest}"}),
                       ("/connections/elevenlabs", {"values_json": text}),
                       ("/connections/elevenlabs/disconnect", {}), ("/connections/elevenlabs/test", {})):
        refused = await world.post(path, json=sent, headers=local)
        assert refused.status_code == 403 and refused.json()["code"] == "not_from_the_server", path
    assert passkeys.count() == 0


async def test_an_approval_covers_the_values_it_was_given_for_and_no_others(world):
    """The 1 October review (finding 3): a passkey tap approved for one key never stores another, even
    one sent in the same request by something on the owner's device."""
    await register(world)
    text, digest = sealed({"elevenlabs_api_key": KEY})
    swapped, _ = sealed({"elevenlabs_api_key": elevenlabs_key("someone-elses")})
    approved = await approval(world, f"save:elevenlabs:{digest}")
    done = await world.post("/connections/elevenlabs", json={"values_json": swapped, "approval": approved},
                            headers=HEADERS)
    assert done.status_code == 403 and done.json()["code"] == "passkey_stale"
    assert linux_store.where("elevenlabs_api_key") == ""
    assert not [c for c in world.services.calls if c.url.host == "api.elevenlabs.io"]
    for unreadable in (None, "", "{not json", {"elevenlabs_api_key": KEY}):
        refused = await world.post("/connections/elevenlabs", headers=HEADERS, json={
            "values_json": unreadable, "approval": await approval(world, f"save:elevenlabs:{digest}")})
        assert refused.status_code == 400 and refused.json()["code"] == "bad_request", unreadable


async def test_the_approval_covers_the_exact_text_the_page_sent(world):
    """The page sends JSON.stringify's compact text; the server hashes what it received, never a
    re-serialisation, so a digest of the same values written another way is not this approval."""
    await register(world)
    compact = '{"elevenlabs_api_key":"' + KEY + '"}'
    digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()
    spaced, spaced_digest = sealed({"elevenlabs_api_key": KEY})
    assert spaced != compact and spaced_digest != digest
    other = await world.post("/connections/elevenlabs", headers=HEADERS, json={
        "values_json": compact, "approval": await approval(world, f"save:elevenlabs:{spaced_digest}")})
    assert other.status_code == 403 and other.json()["code"] == "passkey_stale"
    done = await world.post("/connections/elevenlabs", headers=HEADERS, json={
        "values_json": compact, "approval": await approval(world, f"save:elevenlabs:{digest}")})
    assert done.status_code == 200, done.text
    assert linux_store.read("elevenlabs_api_key") == KEY


# ------------------------------------------------------------------ the voice

async def test_the_voice_is_the_owners_and_only_with_a_passkey_for_those_very_settings(world):
    await register(world)
    stranger = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
    assert (await world.get("/connections/voice", headers=stranger)).status_code == 403
    assert (await world.get("/connections/voice")).status_code == 403        # the server itself

    shown = await world.get("/connections/voice", headers=HEADERS)
    assert shown.status_code == 200
    body = shown.json()
    assert body["voice"]["voice_name"] == world.runtime.settings.tts_voice_name
    assert body["chosen"] is False and "eleven_flash_v2_5" in body["models"]
    assert body["sliders"]["speed"] == {"min": 0.7, "max": 1.2}
    assert "key" not in shown.text.lower() or "api_key" not in shown.text

    wanted = {"voice_id": "9375G6zswFk7v9bKTVQF", "voice_name": "Vikram", "style": 0.4}
    text, digest = sealed(wanted)
    bare = await world.post("/connections/voice", json={"values_json": text}, headers=HEADERS)
    assert bare.status_code == 403 and bare.json()["code"] == "passkey_missing"

    # An approval for one set of settings never stores another.
    other, _ = sealed({"voice_id": "Q0Et7LOU7VpeoeCRQAVS", "voice_name": "Derek"})
    crossed = await world.post("/connections/voice", headers=HEADERS,
                               json={"values_json": other, "approval": await approval(world, f"voice:{digest}")})
    assert crossed.status_code == 403

    done = await world.post("/connections/voice", headers=HEADERS,
                            json={"values_json": text, "approval": await approval(world, f"voice:{digest}")})
    assert done.status_code == 200, done.text
    assert done.json()["voice"] == {"voice_id": "9375G6zswFk7v9bKTVQF", "voice_name": "Vikram",
                                    "model": world.runtime.settings.tts_model, "style": 0.4}
    # Live, with no restart: the client the runtime holds is already speaking as the new voice.
    assert world.runtime.voice.voice_id == "9375G6zswFk7v9bKTVQF"
    assert world.runtime.voice._payload("hi")["voice_settings"] == {"style": 0.4}
    assert (await world.get("/connections/voice", headers=HEADERS)).json()["chosen"] is True
    # And it is recorded as a change, without anything of the key in it.
    assert any(entry["connection"] == "elevenlabs" for entry in ledger.recent(5))


async def test_the_voice_change_is_kept_and_read_back_after_a_restart(world):
    await register(world)
    wanted = {"voice_id": "9375G6zswFk7v9bKTVQF", "voice_name": "Vikram", "speed": 1.1}
    text, digest = sealed(wanted)
    await world.post("/connections/voice", headers=HEADERS,
                     json={"values_json": text, "approval": await approval(world, f"voice:{digest}")})
    # What a restart would read: the record itself, not the client that was changed in memory.
    assert voice_prefs.read() == wanted


async def test_a_voices_own_settings_are_what_elevenlabs_reports_and_nothing_is_made_up(world):
    """The post-deploy review of 3 October: an untouched slider said "(the voice's own)" beside a
    number nobody had reported. The screen now asks ElevenLabs for the voice's own settings and is
    told only those it reports; a voice that reports none gets none."""
    await register(world)
    speaking(world)
    world.services.voices = {
        "9375G6zswFk7v9bKTVQF": {"name": "Vikram", "settings": {"stability": 0.71, "use_speaker_boost": True,
                                                                "latency": 3}},
        "Q0Et7LOU7VpeoeCRQAVS": {"name": "Derek", "settings": None},
    }
    stranger = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
    assert (await world.get("/connections/voice/voices/9375G6zswFk7v9bKTVQF", headers=stranger)).status_code == 403
    shown = await world.get("/connections/voice/voices/9375G6zswFk7v9bKTVQF", headers=HEADERS)
    assert shown.status_code == 200, shown.text
    assert shown.json()["own"] == {"stability": 0.71, "use_speaker_boost": True}
    assert shown.json()["voice_name"] == "Vikram" and KEY not in shown.text
    bare = await world.get("/connections/voice/voices/Q0Et7LOU7VpeoeCRQAVS", headers=HEADERS)
    assert bare.status_code == 200 and bare.json()["own"] == {}
    asked = [c for c in world.services.calls if c.url.path.startswith("/v1/voices/")]
    assert [c.headers["xi-api-key"] for c in asked] == [KEY, KEY]
    assert (await world.get("/connections/voice/voices/not-a-voice", headers=HEADERS)).status_code == 404
    gone = await world.get("/connections/voice/voices/" + "Z" * 20, headers=HEADERS)
    assert gone.status_code == 502 and gone.json()["code"] == "voice_unavailable"
