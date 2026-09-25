"""An empty ElevenLabs account is an empty account, not a bad key — and /health says so.

On 2026-09-25 the voice was down and the assistant said "the ElevenLabs key was rejected" while
/health reported the voice ok. ElevenLabs had answered 401 with detail quota_exceeded ("You
have 0 credits remaining") for both Derek and Scribe. These tests hold the three things that
went wrong: the failure is classed `credit` whatever the status code, the owner is told in plain
words what happened and what brings it back, and /health is not ok until the next success.

Nothing here touches the network, the Keychain or a paid API: ElevenLabs is a transport double
and the credential is injected.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.clients.elevenlabs import ScribeClient, ScribeUnavailable
from app.clients.elevenlabs_tts import VoiceClient, VoiceUnavailable
from app.clients.whisper import WhisperClient, WhisperUnavailable
from app.routes.health import _health, _live_voice
from app.routes.speak import speak
from app.speech.normalise import from_terms
from app.speech.transcribe import Transcriber
from app.speech.voice_reasons import LISTENING_CREDIT_SPOKEN

SECRET = "sk_elevenlabs_test_key_0123456789abcdef"
VOICE_ID = "Q0Et7LOU7VpeoeCRQAVS"
MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 512

# What ElevenLabs actually sent from 2026-09-22, for speech and for Scribe alike.
QUOTA = {
    "detail": {
        "status": "quota_exceeded",
        "message": "This request exceeds your quota of 10000. You have 0 credits remaining, "
        "while 42 credits are required for this request.",
    }
}
CREDITS_ONLY = {"detail": {"message": "You have 0 credits remaining."}}
INVALID_KEY = {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}


@pytest.fixture()
def mock_http(monkeypatch):
    """Route every httpx.AsyncClient created inside the clients at a handler we control."""
    holder: dict[str, object] = {"handler": None, "requests": []}
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            holder["requests"].append(request)
            return holder["handler"](request)

        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    def install(handler):
        holder["handler"] = handler
        return holder

    return install


def voice(**kwargs) -> VoiceClient:
    client = VoiceClient(voice_id=VOICE_ID, voice_name="Derek", **kwargs)
    client._key = SECRET
    return client


def scribe(**kwargs) -> ScribeClient:
    client = ScribeClient(**kwargs)
    client._key = SECRET
    return client


def elevenlabs(account: dict):
    """ElevenLabs as it answers: the key lists models and names the voice either way; speech
    and transcription answer 401 quota_exceeded while the account is empty."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/models"):
            return httpx.Response(200, json=[{"model_id": "scribe_v2"}])
        if path.endswith("/user/subscription"):
            return httpx.Response(200, json={"tier": "creator", "character_count": 10000, "character_limit": 10000})
        if path.startswith("/v1/voices/"):
            return httpx.Response(200, json={"voice_id": VOICE_ID, "name": "Derek"})
        if account["empty"]:
            return httpx.Response(401, json=QUOTA)
        if path.endswith("/speech-to-text"):
            return httpx.Response(200, json={"text": "twelve orders today"})
        return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})

    return handler


# --------------------------------------------------------------------------- classification


@pytest.mark.parametrize("status", [401, 402, 429])
@pytest.mark.parametrize("body", [QUOTA, CREDITS_ONLY])
async def test_an_empty_account_is_credit_for_the_voice(mock_http, status, body):
    mock_http(lambda request: httpx.Response(status, json=body))
    client = voice()
    with pytest.raises(VoiceUnavailable) as caught:
        await client.synthesise("Twelve orders today.")
    assert caught.value.kind == "credit"
    assert client._key == SECRET, "an empty account is not a reason to drop the key"


@pytest.mark.parametrize("status", [401, 402, 429])
@pytest.mark.parametrize("body", [QUOTA, CREDITS_ONLY])
async def test_an_empty_account_is_credit_for_scribe(mock_http, status, body):
    mock_http(lambda request: httpx.Response(status, json=body))
    client = scribe()
    with pytest.raises(ScribeUnavailable) as caught:
        await client.transcribe(b"wav", keyterms=[])
    assert caught.value.kind == "credit"
    assert client._key == SECRET


async def test_an_invalid_key_is_still_rejected_by_the_voice(mock_http):
    mock_http(lambda request: httpx.Response(401, json=INVALID_KEY))
    with pytest.raises(VoiceUnavailable) as caught:
        await voice().synthesise("Twelve orders today.")
    assert caught.value.kind == "rejected"


async def test_an_invalid_key_is_still_rejected_by_scribe(mock_http):
    mock_http(lambda request: httpx.Response(401, json=INVALID_KEY))
    with pytest.raises(ScribeUnavailable) as caught:
        await scribe().transcribe(b"wav", keyterms=[])
    assert caught.value.kind == "rejected"


# --------------------------------------------------------------------------- what is said


class FakeRequest:
    def __init__(self, voice_client: VoiceClient, text: str) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(runtime=SimpleNamespace(voice=voice_client)))
        self._body = {"text": text}

    async def json(self) -> dict:
        return self._body


def plainly_credit(reason: str) -> None:
    lowered = reason.lower()
    assert "credits are used up" in lowered and "paused" in lowered
    assert "comes back by itself" in lowered and "topped up" in lowered
    assert "rejected" not in lowered and "key" not in lowered
    assert "mac" not in lowered.split() and "host" not in lowered


async def test_speak_says_the_credits_are_used_up_not_the_key_rejected(mock_http):
    mock_http(lambda request: httpx.Response(401, json=QUOTA))
    client = voice(cooldown_s=300.0)
    response = await speak(FakeRequest(client, "Twelve orders today."))
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["kind"] == "credit"
    plainly_credit(body["reason"])
    assert "voice" in body["reason"]
    assert SECRET not in response.body.decode()

    # The next five minutes are a cooldown; the owner is still told why, not "unavailable".
    again = json.loads((await speak(FakeRequest(client, "And another thing."))).body)
    assert again["kind"] == "cooldown"
    plainly_credit(again["reason"])


async def test_a_host_that_cannot_hear_says_the_credits_are_used_up(mock_http):
    """A host with no local recogniser behind Scribe says what the owner can act on."""
    pytest.importorskip("av")
    from tests.test_decode import tone_pcm, webm_opus

    mock_http(lambda request: httpx.Response(401, json=QUOTA))
    transcriber = Transcriber(
        WhisperClient("http://fake"), from_terms(["Blue Wash Yard Jeans"]),
        scribe=scribe(cooldown_s=300.0), primary="scribe", whisper_enabled=False,
    )
    result = await transcriber.from_blob(webm_opus(tone_pcm(1.0)))
    assert not result.ok
    assert result.reason == LISTENING_CREDIT_SPOKEN
    plainly_credit(result.reason)
    assert result.engine_detail and SECRET not in result.engine_detail


def test_a_scribe_that_is_not_out_of_credit_keeps_its_own_words():
    client = scribe()
    client.failing, client.last_error_kind = True, "server_error"
    transcriber = Transcriber(WhisperClient("http://fake"), from_terms([]), scribe=client, primary="scribe")
    exc = WhisperUnavailable("down")
    assert transcriber._unheard_reason(exc) == exc.spoken


# --------------------------------------------------------------------------- health


def runtime_with(voice_client: VoiceClient, scribe_client: ScribeClient, tmp_path: Path) -> SimpleNamespace:
    async def ok(detail: str):
        return True, detail

    class Writes:
        state, detail = "off", "writes are off"

    async def writes():
        return Writes()

    async def empty():
        return {}

    return SimpleNamespace(
        build="test-build", uptime_s=1.0, manifest=None, order_cache=None,
        settings=SimpleNamespace(
            whisper_enabled=False, scribe_model="scribe_v2", whisper_model="small.en",
            whisper_bin_dir=tmp_path / "whisper.cpp",
        ),
        transcriber=SimpleNamespace(primary="scribe"),
        provider=SimpleNamespace(health=lambda: ok("claude")),
        shopify=SimpleNamespace(health=lambda: ok("store")),
        gmail=SimpleNamespace(health=lambda: (True, "profile")),
        whisper=SimpleNamespace(health=lambda: ok("unused")),
        scribe=scribe_client,
        voice=voice_client,
        kb=SimpleNamespace(empty=False, files=["a.md"], chars=10),
        normaliser=SimpleNamespace(catalogue=["term"]),
        sessions=SimpleNamespace(count=lambda: 0),
        write_status=writes,
        capabilities=empty,
        family_states=empty,
    )


async def test_voice_health_is_not_ok_while_the_account_is_empty_and_recovers(mock_http):
    account = {"empty": True}
    mock_http(elevenlabs(account))
    client = voice(cooldown_s=300.0)
    assert client.health()[0], "nothing has been tried yet"

    with pytest.raises(VoiceUnavailable):
        await client.synthesise("Twelve orders today.")
    ok, detail = client.health()
    assert not ok
    assert "(credit)" in detail and "credits are used up" in detail and "topped up" in detail
    assert "rejected" not in detail and SECRET not in detail
    assert client.failing_kind == "credit"

    # The plan is topped up and the cooldown runs out: the next sentence speaks, and health
    # says ok again.
    account["empty"] = False
    client.clear_cooldown()
    assert await client.synthesise("Twelve orders today.") == MP3
    ok, detail = client.health()
    assert ok and detail.startswith("key ok")
    assert client.failing_kind == ""


async def test_voice_health_is_not_ok_after_any_failed_attempt_until_a_success(mock_http):
    """Not only the sticky kinds: whatever the latest attempt was, it is what health reports."""
    outcomes = [httpx.Response(500, text="upstream exploded"), httpx.Response(200, content=MP3)]
    mock_http(lambda request: outcomes.pop(0))
    client = voice(cooldown_s=300.0)
    with pytest.raises(VoiceUnavailable):
        await client.synthesise("hello")
    ok, detail = client.health()
    assert not ok and "(server_error)" in detail
    assert await client.synthesise("hello") == MP3
    assert client.health()[0]


async def test_scribe_health_is_not_ok_while_the_account_is_empty_and_recovers(mock_http):
    account = {"empty": True}
    mock_http(elevenlabs(account))
    client = scribe(cooldown_s=300.0)
    with pytest.raises(ScribeUnavailable):
        await client.transcribe(b"wav", keyterms=[])
    ok, detail = await client.health()
    assert not ok, "the key still lists models, but nothing can be transcribed"
    assert "(credit)" in detail and "credits are used up" in detail and "topped up" in detail
    assert "rejected" not in detail and SECRET not in detail

    account["empty"] = False
    client.clear_cooldown()
    assert (await client.transcribe(b"wav", keyterms=[])).text == "twelve orders today"
    ok, detail = await client.health()
    assert ok and detail.startswith("key ok")


async def test_scribe_health_probe_answered_with_an_empty_account_is_not_a_bad_key(mock_http):
    mock_http(lambda request: httpx.Response(401, json=QUOTA))
    ok, detail = await scribe().health()
    assert not ok
    assert "credits are used up" in detail and "rejected" not in detail


async def test_health_route_reports_the_kind_and_the_reason_then_ok_again(mock_http, tmp_path):
    account = {"empty": True}
    mock_http(elevenlabs(account))
    voice_client, scribe_client = voice(cooldown_s=300.0), scribe(cooldown_s=300.0)
    runtime = runtime_with(voice_client, scribe_client, tmp_path)

    with pytest.raises(VoiceUnavailable):
        await voice_client.synthesise("Twelve orders today.")
    with pytest.raises(ScribeUnavailable):
        await scribe_client.transcribe(b"wav", keyterms=[])

    down = await _health(runtime)
    assert down["status"] == "degraded"
    assert down["voice"]["ok"] is False and down["checks"]["tts"]["ok"] is False
    assert down["voice"]["failure_kind"] == "credit"
    plainly_credit(down["voice"]["reason"])
    assert down["speech"]["scribe_ok"] is False
    assert down["speech"]["scribe_failure_kind"] == "credit"
    plainly_credit(down["speech"]["scribe_reason"])
    assert SECRET not in json.dumps(down)

    account["empty"] = False
    voice_client.clear_cooldown()
    scribe_client.clear_cooldown()
    assert await voice_client.synthesise("Twelve orders today.") == MP3

    # A cached answer from while it was down does not go on saying so once the voice speaks.
    cached = _live_voice(runtime, down)
    assert cached["voice"]["ok"] is True and cached["checks"]["tts"]["ok"] is True
    assert cached["voice"]["failure_kind"] is None and cached["voice"]["reason"] is None
    assert down["voice"]["ok"] is False, "the cached result itself is not changed"

    await scribe_client.transcribe(b"wav", keyterms=[])
    up = await _health(runtime)
    assert up["voice"]["ok"] is True and up["voice"]["failure_kind"] is None and up["voice"]["reason"] is None
    assert up["speech"]["scribe_ok"] is True and up["speech"]["scribe_reason"] is None
    assert up["checks"]["tts"]["ok"] is True and up["checks"]["speech"]["ok"] is True
