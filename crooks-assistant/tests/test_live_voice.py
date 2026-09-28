"""POST /voice/live: the single-use key for the live words under the owner's thumb.

The phone opens ElevenLabs' realtime speech-to-text itself, with a key the server mints from its
own. What is proved here: the owner gets a key, the socket's address and its query (and never a
keyterm); anyone the owner rule refuses gets nothing, under production's switches, at the door
and at the route; no stored key, the setting off, or an ElevenLabs that says no or says nothing
in time is a 503 with a plain reason and never an exception's text; the pace holds; the
server's key never appears in an answer or a log line, nor the minted one in a log line; and
(round 9, C-02) only a key-shaped string is handed on, with the short life the page honours.
tests/test_live_voice_owner.py proves the owner rule under production's switches (C-01).

ElevenLabs is a mocked transport throughout. Nothing here reaches the network.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from app.actions.ledger import NullLedger
from app.main import app
from app.routes import voice as voice_route
from app.secrets import keychain
from app.session.manager import SessionManager
from tests import fake_credentials as fake
from tests.test_actions_routes import OWNER, PROXIED, FakeProvider, configure

KEY = fake.elevenlabs_key("live-voice")
TOKEN = fake.elevenlabs_single_use_token("live-voice")
STRANGER = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
SOCKET = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
PARAMS = {"model_id": "scribe_v2_realtime", "audio_format": "pcm_16000", "language_code": "en", "commit_strategy": "manual"}


class Clock:
    """The pace's clock, moved by hand: a limit is arithmetic, not a sleep."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ElevenLabs:
    """The token endpoint, as a transport. `answer` is what it says to the next mint: a status
    and a body, or an exception to raise, or a coroutine to await first (a slow answer)."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.answer = (200, {"token": TOKEN})

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        answer = self.answer
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return await answer(request)
        status, body = answer
        content = body if isinstance(body, str) else json.dumps(body)
        return httpx.Response(status, content=content, headers={"content-type": "application/json"})


@pytest.fixture()
async def client(monkeypatch):
    """The app, started as the suite starts it: no real Claude, no real health probes."""
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        runtime.actions.ledger = NullLedger()
        runtime.sessions = SessionManager()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            c.runtime = runtime
            yield c


@pytest.fixture()
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(voice_route, "PACE", voice_route.Pace(clock=clock))
    return clock


@pytest.fixture()
def elevenlabs(monkeypatch, clock):
    fake_api = ElevenLabs()
    monkeypatch.setattr(voice_route, "http_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake_api.handler), timeout=5.0))
    return fake_api


def store_key(monkeypatch, value: str | None = KEY) -> None:
    """The server's ElevenLabs key, as the secret store answers for it (the suite's own fixture
    answers None for every secret)."""
    monkeypatch.setattr(keychain, "get_optional", lambda key: value if key == "elevenlabs_api_key" else None)


async def ask(client, headers=None):
    return await client.post("/voice/live", headers=headers if headers is not None else PROXIED, json={})


# ------------------------------------------------------------------ the owner gets a key


async def test_the_owner_gets_a_single_use_key_the_socket_and_its_query(client, elevenlabs, monkeypatch):
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    answer = await ask(client)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"token": TOKEN, "url": SOCKET, "params": PARAMS, "expires_in_s": voice_route.EXPIRES_IN_S}
    assert answer.headers["cache-control"] == "no-store"
    # Minted once, at the documented path, with the server's key in the one header it belongs in.
    assert len(elevenlabs.calls) == 1
    call = elevenlabs.calls[0]
    assert call.method == "POST"
    assert str(call.url) == "https://api.elevenlabs.io/v1/single-use-token/realtime_scribe"
    assert call.headers["xi-api-key"] == KEY
    # No keyterms: the owner had them removed because they rewrote his words.
    assert not any("keyterm" in name for name in answer.json()["params"])
    assert "keyterm" not in str(call.url) and "keyterm" not in call.content.decode()


async def test_the_server_itself_speaking_for_the_owner_gets_one_too(client, elevenlabs, monkeypatch):
    """The offline world's default: a request made on the server, with CROOKS_LOCAL_OWNER on."""
    configure(client, logins=OWNER)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": True})
    store_key(monkeypatch)
    assert (await ask(client, headers={})).status_code == 200


def test_the_socket_follows_the_rest_base_it_is_configured_with():
    assert voice_route.socket_url("https://api.elevenlabs.io/v1") == SOCKET
    assert voice_route.socket_url("https://api.eu.residency.elevenlabs.io/v1/") == (
        "wss://api.eu.residency.elevenlabs.io/v1/speech-to-text/realtime")


# ------------------------------------------------------------------ nobody else does


async def test_a_caller_the_owner_rule_refuses_gets_nothing_under_the_production_switches(client, elevenlabs, monkeypatch):
    """Production: an allow-list naming the owner, no CROOKS_LOCAL_OWNER and no
    CROOKS_WRITES_LOCAL_OWNER. A process on the server and a stranger's device are refused at
    the door, and ElevenLabs is never asked for a key on their behalf."""
    configure(client, logins=OWNER, local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False})
    store_key(monkeypatch)
    local = await ask(client, headers={})
    assert local.status_code == 403 and local.json()["code"] == "not_authorised_local"
    stranger = await ask(client, headers=STRANGER)
    assert stranger.status_code == 403
    for refused in (local, stranger):
        assert "token" not in refused.json() and TOKEN not in refused.text and KEY not in refused.text
    assert elevenlabs.calls == []

    # And the route's own check stands without the door: called directly with the same request.
    from starlette.requests import Request

    scope = {"type": "http", "method": "POST", "path": "/voice/live", "headers": [], "app": app,
             "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000), "query_string": b""}
    direct = await voice_route.live(Request(scope))
    assert direct.status_code == 403
    assert elevenlabs.calls == []


async def test_with_no_allow_list_nobody_gets_a_key(client, elevenlabs, monkeypatch):
    configure(client, logins="")
    store_key(monkeypatch)
    assert (await ask(client)).status_code == 403
    assert elevenlabs.calls == []


# ------------------------------------------------------------------ 503, in plain words


async def test_no_stored_key_is_a_503_with_a_plain_reason(client, elevenlabs, monkeypatch):
    configure(client, logins=OWNER)
    store_key(monkeypatch, None)
    answer = await ask(client)
    assert answer.status_code == 503
    assert answer.json() == {"live": False, "why": "No ElevenLabs key is stored on the server."}
    assert answer.headers["cache-control"] == "no-store"
    assert elevenlabs.calls == []


async def test_the_setting_off_is_a_503_and_nothing_is_minted(client, elevenlabs, monkeypatch):
    configure(client, logins=OWNER)
    client.runtime.settings = client.runtime.settings.model_copy(update={"live_transcript": False})
    store_key(monkeypatch)
    answer = await ask(client)
    assert answer.status_code == 503
    assert answer.json()["live"] is False and "CROOKS_LIVE_TRANSCRIPT" in answer.json()["why"]
    assert elevenlabs.calls == []


def test_the_setting_is_read_from_its_environment_name(monkeypatch):
    from config.settings import Settings

    assert Settings().live_transcript is True
    monkeypatch.setenv("CROOKS_LIVE_TRANSCRIPT", "false")
    assert Settings().live_transcript is False


@pytest.mark.parametrize(("answer", "why"), [
    ((401, {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}), "ElevenLabs refused the server's key."),
    ((401, {"detail": {"status": "quota_exceeded", "message": "0 credits remaining"}}), "The ElevenLabs account has no credit left."),
    ((403, {"detail": {"status": "missing_permissions"}}), "ElevenLabs refused the server's key."),
    ((429, {"detail": "too_many_concurrent_requests"}), "ElevenLabs is busy; the next hold tries again."),
    ((500, "upstream exploded: Traceback (most recent call last)"), "ElevenLabs had a problem of its own."),
    ((422, {"detail": "unprocessable"}), "ElevenLabs would not start live words (422)."),
    ((200, {"not_a_token": True}), "ElevenLabs answered without a key."),
    ((200, "not json at all"), "ElevenLabs answered without a key."),
    ((200, ["a", "list"]), "ElevenLabs answered without a key."),
    (httpx.ReadTimeout("read timed out after 5.0s"), "ElevenLabs did not answer in time."),
    (httpx.ConnectError("[Errno -2] Name or service not known"), "ElevenLabs could not be reached."),
], ids=["rejected", "credit", "forbidden", "busy", "server", "other", "no-token", "not-json", "not-object",
        "timeout", "unreachable"])
async def test_elevenlabs_saying_no_is_a_503_in_plain_words(client, elevenlabs, monkeypatch, answer, why):
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    elevenlabs.answer = answer
    response = await ask(client)
    assert response.status_code == 503
    assert response.json() == {"live": False, "why": why}
    assert response.headers["cache-control"] == "no-store"
    # Never an exception's text, and never ElevenLabs' own words.
    for leaked in ("Traceback", "Errno", "timed out after", "invalid_api_key", "exploded", "Error"):
        assert leaked not in response.text


async def test_five_seconds_is_the_whole_wait(client, elevenlabs, monkeypatch):
    """However ElevenLabs spends the time (connecting, or answering slowly), the mint gives up
    at TIMEOUT_S, and says so plainly."""
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    monkeypatch.setattr(voice_route, "TIMEOUT_S", 0.05)

    async def slow(request):
        await asyncio.sleep(1.0)
        return httpx.Response(200, json={"token": TOKEN})

    elevenlabs.answer = slow
    response = await ask(client)
    assert response.status_code == 503
    assert response.json()["why"] == "ElevenLabs did not answer in time."


# ------------------------------------------------------------------ the pace


async def test_one_key_per_one_and_a_half_seconds(client, elevenlabs, monkeypatch, clock):
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    assert (await ask(client)).status_code == 200
    clock.advance(1.0)
    early = await ask(client)
    assert early.status_code == 429
    assert early.json()["live"] is False and early.json()["why"]
    assert early.headers["retry-after"] == "1" and early.headers["cache-control"] == "no-store"
    clock.advance(0.6)
    assert (await ask(client)).status_code == 200
    assert len(elevenlabs.calls) == 2, "a refused ask never reaches ElevenLabs"


async def test_forty_keys_in_ten_minutes_and_no_more(client, elevenlabs, monkeypatch, clock):
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    for _ in range(40):
        assert (await ask(client)).status_code == 200
        clock.advance(2.0)
    over = await ask(client)
    assert over.status_code == 429
    # The first of the forty leaves the window 600 s after it was minted; 80 s have passed.
    assert int(over.headers["retry-after"]) == 520
    clock.advance(520)
    assert (await ask(client)).status_code == 200
    assert len(elevenlabs.calls) == 41


async def test_a_failed_mint_still_counts_against_the_pace(client, elevenlabs, monkeypatch, clock):
    """Every ask that reaches ElevenLabs is ElevenLabs' to count, whatever it answered: a page
    retrying a refusal in a loop is held to the same pace as one that succeeds."""
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    elevenlabs.answer = (500, "busy")
    assert (await ask(client)).status_code == 503
    assert (await ask(client)).status_code == 429
    assert len(elevenlabs.calls) == 1


def test_the_pace_on_its_own():
    clock = Clock()
    pace = voice_route.Pace(gap_s=1.5, limit=3, window_s=10.0, clock=clock)
    assert pace.take() == 0.0
    assert pace.take() == pytest.approx(1.5)
    clock.advance(1.5)
    assert pace.take() == 0.0
    clock.advance(1.5)
    assert pace.take() == 0.0
    clock.advance(1.5)
    assert pace.take() == pytest.approx(10.0 - 4.5)
    clock.advance(5.5)
    assert pace.take() == 0.0
    pace.reset()
    assert pace.take() == 0.0


# ------------------------------------------------------------------ the key stays on the server


async def test_the_key_never_appears_in_an_answer_or_a_log_line(client, elevenlabs, monkeypatch, clock, caplog):
    """The server's key in no answer and no log line, whatever happened; the minted key in the
    owner's answer only, and in no log line. ElevenLabs' error bodies are exactly where a key
    would be echoed back, so one of them does."""
    caplog.set_level(logging.DEBUG)
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    answers = []
    for answer in [
        (200, {"token": TOKEN}),
        (401, {"detail": {"status": "invalid_api_key", "message": f"Invalid API key: {KEY}"}}),
        (500, f"echo {KEY} {TOKEN}"),
        httpx.ReadTimeout(f"timed out sending {KEY}"),
        (200, {"token": TOKEN}),
    ]:
        elevenlabs.answer = answer
        answers.append(await ask(client))
        clock.advance(2.0)
    answers.append(await ask(client, headers=STRANGER))   # refused at the door
    assert [a.status_code for a in answers] == [200, 503, 503, 503, 200, 403]
    for answer in answers:
        assert KEY not in answer.text
        assert KEY not in json.dumps(dict(answer.headers))
    assert TOKEN in answers[0].text
    logged = caplog.text + "".join(str(record.args) for record in caplog.records)
    assert KEY not in logged
    assert TOKEN not in logged
    assert "live words unavailable" in caplog.text, "a refusal is logged, in the route's own words"


# ------------------------------------------------------------------ what is handed on, and for how long


@pytest.mark.parametrize("token", [
    TOKEN,
    fake.elevenlabs_single_use_token("long", length=400),
    fake.jwt("live-voice"),
    fake.body("base64-shaped", 44, fake.BASE64) + "==",
], ids=["prefixed", "long", "jwt-shaped", "base64-shaped"])
async def test_a_key_shaped_answer_is_handed_on_exactly_with_a_short_life(client, elevenlabs, monkeypatch, token):
    """C-02: a string of token characters, of a bearer token's length, is handed on as it came,
    with the life the page is to honour: seconds, not ElevenLabs' fifteen minutes."""
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    elevenlabs.answer = (200, {"token": token})
    answer = await ask(client)
    assert answer.status_code == 200, answer.text
    assert answer.json()["token"] == token
    life = answer.json()["expires_in_s"]
    assert isinstance(life, int) and 0 < life <= 60 and life < 15 * 60
    assert life > voice_route.TIMEOUT_S, "long enough to outlast the mint's own wait"


@pytest.mark.parametrize("token", [
    12345,
    {"value": "nested"},
    ["a", "list"],
    True,
    "",
    "   ",
    "too-short",
    "x" * 2049,
    "Jane Doe asked about order #1042 at 12 High Street",
    "<img src=x onerror=alert(1)>aaaaaaaaaaaa",
    "tokén-with-an-accent-and-more",
    "line-one-of-a-key\nline-two-of-a-key",
    'quote"in-the-middle-of-a-long-value',
    "semicolon;in-the-middle-of-a-long-value",
], ids=["number", "object", "list", "boolean", "empty", "blank", "short", "enormous", "a-sentence", "markup",
        "non-ascii", "newline", "quote", "semicolon"])
async def test_anything_else_in_the_token_field_is_not_handed_on_or_logged(client, elevenlabs, monkeypatch, caplog, token):
    """C-02: the route no longer hands on any non-empty string. Whatever else ElevenLabs puts in
    the field is refused in the route's own words: a 503 with no key, and neither the answer nor
    a log line carries what was in the field."""
    caplog.set_level(logging.DEBUG)
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    elevenlabs.answer = (200, {"token": token})
    answer = await ask(client)
    assert answer.status_code == 503, answer.text
    assert answer.json()["live"] is False and "token" not in answer.json()
    assert answer.json()["why"] in ("ElevenLabs answered without a key.",
                                    "ElevenLabs answered with something that is not a key.")
    if isinstance(token, str) and token.strip():
        assert token.strip() not in answer.text
        logged = caplog.text + "".join(str(record.args) for record in caplog.records)
        assert token.strip() not in logged


def test_the_shape_is_what_a_socket_query_can_carry_unescaped_and_no_more():
    """The accepted characters are URL-safe token characters: nothing that ends a query value,
    starts a fragment, or would read as markup, whitespace or a sentence."""
    shape = voice_route.TOKEN_SHAPE
    for bad in ("a&b" * 8, "a#b" * 8, "a?b" * 8, "a b" * 8, "a<b" * 8, "a%b" * 8, "a'b" * 8, "a,b" * 8):
        assert not shape.fullmatch(bad), bad
    assert shape.fullmatch("A-z_0.9~+/=" * 2)


async def test_the_servers_own_key_sent_back_as_the_token_is_never_handed_on(client, elevenlabs, monkeypatch, caplog):
    """C-02: the server's key is key-shaped too. An answer that puts it (or something holding
    it) in the token field is refused like any other thing that is not a single-use key."""
    caplog.set_level(logging.DEBUG)
    configure(client, logins=OWNER)
    store_key(monkeypatch)
    for echoed in (KEY, f"{KEY}.suffix", f"prefix.{KEY}"):
        elevenlabs.answer = (200, {"token": echoed})
        answer = await ask(client)
        assert answer.status_code == 503 and KEY not in answer.text
        voice_route.PACE.reset()
    assert KEY not in caplog.text


def test_the_page_holds_a_key_to_the_same_shape_and_to_the_life_it_is_given():
    """The page's own copy of the rule (web/live-voice.js TOKEN_SHAPE) is this one, so a key the
    Mac hands on is one the page will use; and the page honours no life longer than a minute."""
    import re as _re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "web" / "live-voice.js").read_text(encoding="utf-8")
    page = _re.search(r"const TOKEN_SHAPE = /\^(.+?)\$/;", source)
    assert page is not None, "web/live-voice.js no longer states TOKEN_SHAPE"
    assert page.group(1) == voice_route.TOKEN_SHAPE.pattern
    ceiling = _re.search(r"const MAX_LIFE_S = (\d+);", source)
    assert ceiling is not None and 0 < voice_route.EXPIRES_IN_S <= int(ceiling.group(1))
