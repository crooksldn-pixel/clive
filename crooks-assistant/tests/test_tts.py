"""Derek: the ElevenLabs voice, and the Android voice that catches him when he falls.

Nothing here touches the network, the Keychain or a paid API: the HTTP layer is a transport
double and the credential is injected. The rules these tests exist to hold are that the tablet
is never left silent — every way ElevenLabs can fail ends in a 503 the tablet reads as "use
your own voice" — and that the API key never reaches the tablet, a log line, an exception or a
health string.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app.clients.elevenlabs_tts import VoiceClient, VoiceUnavailable
from tests.fake_credentials import elevenlabs_key

SECRET = elevenlabs_key("tts")
VOICE_ID = "Q0Et7LOU7VpeoeCRQAVS"
MODEL = "eleven_flash_v2_5"
OUTPUT_FORMAT = "mp3_44100_128"

# Enough of an MP3 frame header to be recognisably audio; nothing decodes it here.
MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 512


@pytest.fixture()
def mock_http(monkeypatch):
    """Route every httpx.AsyncClient created inside the client at a handler we control."""
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


def make(**kwargs) -> VoiceClient:
    client = VoiceClient(
        voice_id=VOICE_ID, voice_name="Derek", model=MODEL, output_format=OUTPUT_FORMAT,
        **kwargs,
    )
    client._key = SECRET  # injected: the Keychain is never read in a test
    return client


def audio(status: int = 200, body: bytes = MP3):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": "audio/mpeg"})

    return handler


def error(status: int, body: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    return handler


# --------------------------------------------------------------------------- the request


async def test_the_request_is_the_one_the_owner_approved(mock_http):
    """Voice, model and format are the settings that were auditioned. If any of them drifts,
    the tablet speaks with a voice nobody chose."""
    holder = mock_http(audio())
    assert await make().synthesise("Twelve orders today.") == MP3

    request = holder["requests"][0]
    assert request.method == "POST"
    assert request.url.path == f"/v1/text-to-speech/{VOICE_ID}/stream"
    assert request.url.params["output_format"] == OUTPUT_FORMAT
    import json

    body = json.loads(request.content)
    assert body == {"text": "Twelve orders today.", "model_id": MODEL}
    # Voice settings are deliberately absent: the voice's own defaults are what was approved.
    assert "voice_settings" not in body


async def test_the_key_travels_in_the_header_and_nowhere_else(mock_http):
    holder = mock_http(audio())
    await make().synthesise("hello")
    request = holder["requests"][0]
    assert request.headers["xi-api-key"] == SECRET
    assert SECRET not in request.content.decode()
    assert SECRET not in str(request.url)


async def test_the_key_is_read_from_the_keychain_server_side(monkeypatch, mock_http):
    reads: list[str] = []

    def fake_get_optional(key: str):
        reads.append(key)
        return SECRET

    from app.secrets import keychain

    monkeypatch.setattr(keychain, "get_optional", fake_get_optional)
    holder = mock_http(audio())
    client = VoiceClient(voice_id=VOICE_ID, model=MODEL, output_format=OUTPUT_FORMAT)
    await client.synthesise("hello")
    assert reads == ["elevenlabs_api_key"]
    assert holder["requests"][0].headers["xi-api-key"] == SECRET


async def test_text_is_bounded_before_it_is_billed(mock_http):
    holder = mock_http(audio())
    await make(max_chars=20).synthesise("x" * 500)
    import json

    assert len(json.loads(holder["requests"][0].content)["text"]) == 20


async def test_a_successful_mp3_arrives_whole(mock_http):
    mock_http(audio(body=MP3 * 3))
    client = make()
    assert await client.synthesise("hello") == MP3 * 3
    assert client.successes == 1 and client.failures == 0
    assert client.last_bytes == len(MP3) * 3


async def test_the_stream_yields_before_it_ends(mock_http):
    """The point of streaming: bytes leave the Mac as they arrive, not after the last one."""
    mock_http(audio(body=MP3))
    stream = await make().open_stream("hello")
    chunks = [chunk async for chunk in stream.chunks()]
    assert chunks and b"".join(chunks) == MP3


# --------------------------------------------------------------------------- failure


@pytest.mark.parametrize(
    "status,body,kind",
    [
        (401, '{"detail":{"status":"invalid_api_key"}}', "rejected"),
        (403, "missing_permissions", "forbidden"),
        (429, "quota exceeded", "credit"),
        (429, '{"detail":{"status":"too_many_concurrent_requests"}}', "rate"),
        (402, "payment required", "credit"),
        (404, '{"detail":{"status":"voice_not_found"}}', "no_voice"),
        (500, "upstream exploded", "server_error"),
        (418, "teapot", "http_418"),
    ],
)
async def test_every_http_failure_has_a_name(mock_http, status, body, kind):
    mock_http(error(status, body))
    client = make()
    with pytest.raises(VoiceUnavailable) as caught:
        await client.synthesise("hello")
    assert caught.value.kind == kind
    assert client.failures == 1 and client.successes == 0


async def test_a_timeout_is_a_named_failure_not_a_hang(monkeypatch):
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    with pytest.raises(VoiceUnavailable) as caught:
        await make(timeout_s=1.0).synthesise("hello")
    assert caught.value.kind == "timeout"


async def test_no_key_is_a_failure_the_owner_can_act_on(monkeypatch):
    from app.secrets import keychain

    monkeypatch.setattr(keychain, "get_optional", lambda key: None)
    client = VoiceClient(voice_id=VOICE_ID)
    with pytest.raises(VoiceUnavailable) as caught:
        await client.synthesise("hello")
    assert caught.value.kind == "no_key"
    assert "set_secrets.py" in str(caught.value)


async def test_an_empty_response_is_a_failure_not_a_silence(mock_http):
    mock_http(audio(body=b""))
    client = make()
    with pytest.raises(VoiceUnavailable) as caught:
        await client.synthesise("hello")
    assert caught.value.kind == "empty_audio"


async def test_a_dead_account_stops_being_asked(mock_http):
    """A rejected key does not recover between two sentences. Asking anyway costs the owner a
    pause before the Android voice starts."""
    mock_http(error(401, "invalid_api_key"))
    client = make(cooldown_s=300.0)
    with pytest.raises(VoiceUnavailable):
        await client.synthesise("hello")
    assert client.cooling_down
    with pytest.raises(VoiceUnavailable) as caught:
        await client.synthesise("hello again")
    assert caught.value.kind == "cooldown"
    assert client.attempts == 1  # the second answer never reached ElevenLabs


async def test_a_recoverable_failure_is_retried_next_time(mock_http):
    mock_http(error(500, "upstream exploded"))
    client = make(cooldown_s=300.0)
    with pytest.raises(VoiceUnavailable):
        await client.synthesise("hello")
    assert not client.cooling_down


async def test_switching_the_voice_off_costs_nothing(mock_http):
    holder = mock_http(audio())
    client = make(enabled=False)
    with pytest.raises(VoiceUnavailable) as caught:
        await client.synthesise("hello")
    assert caught.value.kind == "off"
    assert not holder["requests"]


async def test_nothing_to_say_is_not_a_request(mock_http):
    holder = mock_http(audio())
    with pytest.raises(VoiceUnavailable) as caught:
        await make().synthesise("   ")
    assert caught.value.kind == "empty_text"
    assert not holder["requests"]


# --------------------------------------------------------------------------- the credential


async def test_the_key_never_reaches_a_log_line_or_an_exception(mock_http, caplog):
    """ElevenLabs echoing the key back in an error body is the realistic way it would leak."""
    mock_http(error(401, f'{{"detail":"key {SECRET} is invalid"}}'))
    client = make()
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(VoiceUnavailable) as caught:
            await client.synthesise("hello")
    assert SECRET not in str(caught.value)
    assert SECRET not in client.last_error
    assert SECRET not in caplog.text
    assert "[redacted]" in str(caught.value)


async def test_health_never_names_the_key(monkeypatch):
    client = make()
    ok, detail = client.health()
    assert ok
    assert SECRET not in detail
    assert "Derek" in detail and MODEL in detail and OUTPUT_FORMAT in detail


def test_health_without_a_key_says_how_to_fix_it(monkeypatch):
    from app.secrets import keychain

    monkeypatch.setattr(keychain, "get_optional", lambda key: None)
    ok, detail = VoiceClient(voice_id=VOICE_ID, voice_name="Derek").health()
    assert not ok
    assert "set_secrets.py" in detail


def test_health_costs_nothing(monkeypatch):
    """A health check that synthesises a sentence on every poll is a bill, not a check."""
    def explode(*args, **kwargs):
        raise AssertionError("/health must not call ElevenLabs")

    monkeypatch.setattr(httpx, "AsyncClient", explode)
    assert make().health()[0]


async def test_health_reports_a_cooldown_rather_than_pretending(mock_http):
    mock_http(error(429, "quota exceeded"))
    client = make(cooldown_s=300.0)
    with pytest.raises(VoiceUnavailable):
        await client.synthesise("hello")
    ok, detail = client.health()
    assert not ok
    assert "credit" in detail


# --------------------------------------------------------------------------- one connection


async def test_one_connection_is_reused_across_answers(monkeypatch):
    """A TLS handshake per sentence was a few hundred milliseconds the owner waited for."""
    created = []
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        created.append(1)
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, content=MP3))
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    client = make()
    assert await client.synthesise("One.") == MP3
    assert await client.synthesise("Two.") == MP3
    assert await client.synthesise("Three.") == MP3
    assert len(created) == 1
    await client.aclose()
    assert client._http is None


# --------------------------------------------------------------------------- prefetch


async def drain(chunks) -> bytes:
    return b"".join([c async for c in chunks])


class SlowStream(httpx.AsyncByteStream):
    """An MP3 arriving in pieces with time between them, like ElevenLabs generating it."""

    def __init__(self, pieces, gap_s: float) -> None:
        self.pieces = pieces
        self.gap_s = gap_s

    async def __aiter__(self):
        import asyncio

        for i, piece in enumerate(self.pieces):
            if i:
                await asyncio.sleep(self.gap_s)
            yield piece


async def test_the_first_chunk_is_handed_out_before_the_last_is_generated(mock_http):
    """The point of prefetching is to move the start of the voice earlier, not to wait for
    the whole file: what has arrived goes out now, the rest follows as it is made."""
    import time

    mock_http(lambda request: httpx.Response(200, stream=SlowStream([MP3, MP3, MP3], 0.25)))
    client = make()
    client.prefetch("Twelve orders today.")
    started = time.perf_counter()
    chunks = await client.take_ready("Twelve orders today.")
    first = await chunks.__anext__()
    first_at = time.perf_counter() - started
    rest = await drain(chunks)
    total_at = time.perf_counter() - started
    assert first == MP3
    assert first_at < 0.2, f"first chunk waited {first_at:.2f}s for the rest"
    assert total_at >= 0.45 and rest == MP3 + MP3
    assert client.prefetches == 1 and client.prefetch_hits == 1


async def test_a_prefetched_answer_is_handed_out_once_and_only_once(mock_http):
    holder = mock_http(lambda request: httpx.Response(200, content=MP3))
    client = make()
    assert client.prefetch("Twelve orders today.") is True
    assert await drain(await client.take_ready("Twelve orders today.")) == MP3
    assert await client.take_ready("Twelve orders today.") is None   # not served twice
    assert len(holder["requests"]) == 1


async def test_prefetch_is_the_same_single_request_earlier(mock_http):
    """Asking for it twice while it is in flight is still one request to ElevenLabs."""
    holder = mock_http(lambda request: httpx.Response(200, content=MP3))
    client = make()
    client.prefetch("Hello.")
    client.prefetch("Hello.")
    assert await drain(await client.take_ready("Hello.")) == MP3
    assert len(holder["requests"]) == 1


async def test_prefetch_costs_nothing_when_off_or_cooling(mock_http):
    holder = mock_http(lambda request: httpx.Response(200, content=MP3))
    off = make(enabled=False)
    assert off.prefetch("Hello.") is False
    cooling = make(cooldown_s=300)
    cooling._cooldown_until = 10**12
    assert cooling.prefetch("Hello.") is False
    switched_off = make()
    switched_off.prefetch_enabled = False
    assert switched_off.prefetch("Hello.") is False
    assert make().prefetch("") is False
    assert holder["requests"] == []


async def test_a_failed_prefetch_is_reported_once_not_paid_for_twice(mock_http):
    """The failure is remembered: /speak raises it immediately and does not open a second
    request that would sit through the same timeout."""
    holder = mock_http(lambda request: httpx.Response(402, json={"detail": {"status": "quota_exceeded"}}))
    client = make(cooldown_s=0)
    client.prefetch("Hello.")
    with pytest.raises(VoiceUnavailable) as exc:
        await client.take_ready("Hello.")
    assert exc.value.kind == "credit"
    assert len(holder["requests"]) == 1
    assert await client.take_ready("Hello.") is None   # consumed; the next ask streams afresh


async def test_a_fixed_line_is_synthesised_once_and_free_after_that(mock_http):
    """"I did not catch that" is the same sentence every time; pinned, it costs one request
    for the life of the process and is instant on every repeat."""
    holder = mock_http(lambda request: httpx.Response(200, content=MP3))
    client = make()
    client.prefetch("I did not catch that.", pin=True)
    assert await drain(await client.take_ready("I did not catch that.")) == MP3
    assert await drain(await client.take_ready("I did not catch that.")) == MP3
    client.prefetch("I did not catch that.", pin=True)   # /turn asks again: nothing to do
    assert await drain(await client.take_ready("I did not catch that.")) == MP3
    assert len(holder["requests"]) == 1
    assert client.prefetch_hits == 3


async def test_stale_prefetches_are_dropped(mock_http):
    mock_http(lambda request: httpx.Response(200, content=MP3))
    client = make()
    client.prefetch("Old.")
    await client._inflight["Old."]
    client._ready["Old."].at = 0.0   # synthesised long ago
    client.prefetch("New.")           # any new prefetch sweeps the stale ones
    assert "Old." not in client._ready
    await client._inflight["New."]


async def test_an_interrupted_owner_stops_the_synthesis(mock_http):
    """Barge-in on the tablet never asks /speak; the Mac must not go on generating for it."""
    mock_http(lambda request: httpx.Response(200, stream=SlowStream([MP3] * 6, 0.2)))
    client = make()
    client.prefetch("A long answer nobody will hear.")
    import asyncio

    await asyncio.sleep(0.05)
    assert client.cancel_prefetches() == 1
    await asyncio.sleep(0.05)
    assert client._inflight == {}


async def test_a_pinned_line_that_failed_once_is_tried_again(mock_http):
    """One timeout on "I did not catch that" must not leave every later error line in the
    Android voice until a restart: a failed line is never kept, pinned or not."""
    outcomes = [httpx.Response(408, text="timeout"), httpx.Response(200, content=MP3)]
    holder = mock_http(lambda request: outcomes.pop(0))
    client = make(cooldown_s=0)
    client.prefetch("I did not catch that.", pin=True)
    with pytest.raises(VoiceUnavailable):
        await client.take_ready("I did not catch that.")
    assert "I did not catch that." not in client._ready
    assert client.prefetch("I did not catch that.", pin=True) is True
    assert await drain(await client.take_ready("I did not catch that.")) == MP3
    assert len(holder["requests"]) == 2
    # And now it is kept, free, for good.
    assert await drain(await client.take_ready("I did not catch that.")) == MP3
    assert len(holder["requests"]) == 2


async def test_a_prefetch_cancelled_before_it_started_cannot_hang_speak(mock_http):
    """A cancellation that lands during the handshake, or before the task has run, must still
    finish the entry: otherwise /speak waits on it forever."""
    import asyncio

    mock_http(lambda request: httpx.Response(200, stream=SlowStream([MP3] * 3, 0.3)))
    client = make()
    client.prefetch("I could not work out an answer to that.")
    assert client.cancel_prefetches() == 1        # before the task has run at all
    await asyncio.sleep(0.05)
    assert client._inflight == {}
    # Nothing is left on the shelf: /speak streams afresh rather than waiting on a dead entry.
    assert await asyncio.wait_for(client.take_ready("I could not work out an answer to that."), timeout=2) is None
    client.prefetch("I could not work out an answer to that.")
    first = await asyncio.wait_for((await client.take_ready("I could not work out an answer to that.")).__anext__(), timeout=2)
    assert first == MP3
    client.cancel_prefetches()


async def test_the_voice_refuses_to_be_a_credit_tap(mock_http):
    """A loop against /speak — or a bug — must not spend the account in minutes: past the
    ceiling for one minute, every further request is a named refusal, not a synthesis."""
    holder = mock_http(lambda request: httpx.Response(200, content=MP3))
    client = make(max_per_minute=3)
    for _ in range(3):
        assert await client.synthesise("Hello.") == MP3
    with pytest.raises(VoiceUnavailable) as exc:
        await client.synthesise("Hello.")
    assert exc.value.kind == "rate"
    assert len(holder["requests"]) == 3
    assert client.prefetch("Again.") is True   # the prefetch task itself is refused the same way
    with pytest.raises(VoiceUnavailable):
        await client.take_ready("Again.")
    assert len(holder["requests"]) == 3


async def test_a_burst_is_not_an_empty_account(mock_http):
    """ElevenLabs answers 429 for too many requests at once as well as for no credit. Only
    the second parks the voice for five minutes; a burst is tried again next time."""
    mock_http(error(429, '{"detail":{"status":"too_many_concurrent_requests"}}'))
    client = make(cooldown_s=300.0)
    with pytest.raises(VoiceUnavailable) as caught:
        await client.synthesise("hello")
    assert caught.value.kind == "rate" and not client.cooling_down
    mock_http(audio())
    assert await client.synthesise("hello again")


async def test_a_pinned_line_cut_mid_stream_is_not_kept(mock_http):
    """A fixed line whose stream broke half way would otherwise be replayed clipped for the
    life of the process."""
    import httpx as _httpx

    def cut(request):
        async def body():
            yield MP3[:2]
            raise _httpx.ReadError("gone")

        return _httpx.Response(200, content=body(), headers={"content-type": "audio/mpeg"})

    mock_http(cut)
    client = make()
    assert client.prefetch("I did not catch that.", pin=True)
    await asyncio.sleep(0.05)
    entry = client._ready.get("I did not catch that.")
    assert entry is None or not entry.pinned


async def test_the_voice_id_is_checked_against_elevenlabs_once_an_hour(mock_http):
    """The configured name is a label. Health asks ElevenLabs what it calls the id — free —
    and says so when a .env still carries another voice under Vikram's name."""
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"voice_id": VOICE_ID, "name": "Derek"})

    mock_http(handler)
    client = make()
    client.voice_name = "Vikram"
    # The library name carries a description; that is the same voice, not a mismatch.
    client._voice_actual_name = "Vikram - AI Productivity Assistant"
    assert client.voice_mismatch is None and client.health()[0]
    client._voice_checked_at = 0.0
    assert await client.verify_voice() == "Derek"
    assert await client.verify_voice() == "Derek" and len(seen) == 1, "remembered for an hour"
    ok, detail = client.health()
    assert not ok and "Derek" in detail and "CROOKS_TTS_VOICE_ID" in detail and SECRET not in detail
    client.voice_name = "Derek"
    assert client.health()[0]
    assert not any(p.endswith("/text-to-speech/" + VOICE_ID) or "text-to-speech" in p for p in seen), "no synthesis"
