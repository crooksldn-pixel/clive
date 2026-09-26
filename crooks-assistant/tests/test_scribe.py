"""ElevenLabs Scribe as the primary recogniser, and whisper.cpp catching it when it falls.

Nothing here touches the network or the Keychain: the HTTP layer is a transport double and the
credential is injected. The rule these tests exist to hold is that the tablet gets an answer —
every way Scribe can fail ends in a Whisper transcript, normalised the same way — and that the
API key never reaches a log line, an exception or a health string.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from app.clients.elevenlabs import ScribeClient, ScribeUnavailable
from app.clients.whisper import Transcript, WhisperClient, WhisperUnavailable
from app.speech.normalise import from_terms
from app.speech.transcribe import Transcriber

av = pytest.importorskip("av")
from tests.test_decode import tone_pcm, webm_opus  # noqa: E402

SECRET = "sk_elevenlabs_test_key_0123456789abcdef"


# --------------------------------------------------------------------------- doubles


class FakeWhisper(WhisperClient):
    def __init__(self, text: str = "the local one heard this", fail: bool = False) -> None:
        super().__init__("http://fake")
        self.text, self.fail, self.calls = text, fail, 0

    async def transcribe(self, wav: bytes, *, prompt: str = "") -> Transcript:
        self.calls += 1
        if self.fail:
            raise WhisperUnavailable("whisper-server is not running")
        return Transcript(text=self.text, ms=9.0, model="small.en")


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


def ok_transcript(text: str = "find the blue wash yard genes"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": text, "language_code": "eng"})

    return handler


def norm():
    return from_terms(["Blue Wash Yard Jeans"], {"cross stars tee": "CRXST★RZ T-Shirt"})


def make(scribe_client, whisper=None, **kwargs) -> Transcriber:
    return Transcriber(
        whisper or FakeWhisper(), norm(), scribe=scribe_client, primary="scribe", **kwargs
    )


def client(**kwargs) -> ScribeClient:
    kwargs.setdefault("cooldown_s", 0.0)
    c = ScribeClient(**kwargs)
    c._key = SECRET
    return c


# --------------------------------------------------------------------------- the happy path


async def test_scribe_transcribes_and_normalises(mock_http):
    mock_http(ok_transcript())
    result = await make(client()).from_blob(webm_opus(tone_pcm(1.0)))
    assert result.ok
    assert result.raw_text == "find the blue wash yard genes"
    # The whole point of keeping the normaliser: Scribe is better, and still says "yard genes".
    assert "Blue Wash Yard Jeans" in result.text
    assert result.engine == "scribe_v2"
    assert result.fallback is False
    assert result.timings_ms["scribe"] >= 0
    assert "whisper" not in result.timings_ms


async def test_request_carries_scribe_v2_english_and_keyterms(mock_http):
    holder = mock_http(ok_transcript())
    await make(client()).from_blob(webm_opus(tone_pcm(1.0)))
    body = holder["requests"][0].read().decode("utf-8", "replace")
    assert holder["requests"][0].url.path.endswith("/speech-to-text")
    assert 'name="model_id"\r\n\r\nscribe_v2' in body
    assert 'name="language_code"\r\n\r\neng' in body
    assert 'name="file"; filename="audio.wav"' in body
    # The catalogue biases Scribe exactly as it biases Whisper's prompt.
    assert 'name="keyterms"\r\n\r\nBlue Wash Yard Jeans' in body
    assert 'name="keyterms"\r\n\r\nCross Stars Tee' in body


async def test_customer_names_are_never_sent_as_keyterms(mock_http):
    holder = mock_http(ok_transcript())
    normaliser = from_terms(["Convict Hoodie", "Jane Shopper"], personal=["Jane Shopper"])
    t = Transcriber(FakeWhisper(), normaliser, scribe=client(), primary="scribe")
    await t.from_blob(webm_opus(tone_pcm(1.0)))
    body = holder["requests"][0].read().decode("utf-8", "replace")
    assert "Convict Hoodie" in body
    assert "Jane Shopper" not in body, "a customer's name is not speech-bias vocabulary"
    # It still corrects transcripts here on this Mac.
    assert "Jane Shopper" in normaliser.catalogue.prompt_terms()


async def test_keyterms_can_be_switched_off(mock_http):
    holder = mock_http(ok_transcript())
    await make(client(), keyterms=False).from_blob(webm_opus(tone_pcm(1.0)))
    assert "keyterms" not in holder["requests"][0].read().decode("utf-8", "replace")


def test_keyterms_obey_the_api_limits():
    c = client(max_keyterms=3)
    terms = c.keyterms(
        ["x" * 60, "one two three four five six", "Jorts", "Jorts", "Windbreaker", "Cellblock", "Yard Jeans"]
    )
    assert terms == ["Windbreaker", "Cellblock", "Yard Jeans"]  # capped, keeping the last ones
    assert all(len(t) < 50 and len(t.split()) <= 5 for t in terms)


async def test_the_live_tablet_sentence_survives_the_whole_pipeline(mock_http):
    """The regression as it reached the tablet: Scribe heard it correctly and the normaliser
    turned "what" into "White". The number is still recovered; nothing else moves."""
    raw = "Order one nine three zero and tell me what they, exactly what they ordered"
    mock_http(ok_transcript(raw))
    normaliser = from_terms(["White", "Black", "Grey", "Blue Wash Yard Jeans"])
    t = Transcriber(FakeWhisper(), normaliser, scribe=client(), primary="scribe")
    result = await t.from_blob(webm_opus(tone_pcm(1.0)))
    assert result.ok
    assert result.raw_text == raw
    assert result.text == "Order 1930 and tell me what they, exactly what they ordered"
    assert result.normalised.order_numbers == ["1930"]


async def test_hallucination_filter_still_applies_to_scribe(mock_http):
    mock_http(ok_transcript("Thank you."))
    result = await make(client()).from_blob(webm_opus(tone_pcm(1.0)))
    assert not result.ok
    assert "did not catch" in result.reason


async def test_silence_never_reaches_scribe(mock_http):
    holder = mock_http(ok_transcript())
    result = await make(client()).from_blob(webm_opus(b"\x00\x00" * 48000))
    assert not result.ok
    assert holder["requests"] == [], "a recording with no signal was sent to a paid API"


# --------------------------------------------------------------------------- fallback


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (httpx.Response(401, json={"detail": "invalid_api_key"}), "rejected"),
        (httpx.Response(403, text="forbidden"), "forbidden"),
        (httpx.Response(402, json={"detail": {"status": "quota_exceeded"}}), "credit"),
        (httpx.Response(429, text="quota exceeded"), "credit"),
        (httpx.Response(429, json={"detail": {"status": "too_many_concurrent_requests"}}), "rate"),
        (httpx.Response(500, text="upstream boom"), "server_error"),
        (httpx.Response(422, text="unprocessable"), "http_422"),
        (httpx.Response(200, text="not json at all"), "bad_response"),
        (httpx.Response(200, json={"nothing": "useful"}), "bad_response"),
    ],
)
async def test_every_scribe_failure_falls_back_to_whisper(mock_http, response, kind):
    mock_http(lambda request: response)
    whisper = FakeWhisper("the local one heard this")
    result = await make(client(), whisper).from_blob(webm_opus(tone_pcm(1.0)))
    assert result.ok, "the tablet must still get an answer"
    assert result.engine == "whisper_fallback"
    assert result.fallback is True
    assert result.raw_text == "the local one heard this"
    assert result.engine_detail.startswith(kind)
    assert whisper.calls == 1
    assert {"scribe", "whisper"} <= result.timings_ms.keys()


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("no route"), "network"),
        (httpx.RemoteProtocolError("died mid-request"), "network"),
    ],
)
async def test_network_trouble_falls_back_to_whisper(mock_http, error, kind):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    mock_http(handler)
    result = await make(client()).from_blob(webm_opus(tone_pcm(1.0)))
    assert result.ok
    assert result.engine == "whisper_fallback"
    assert result.engine_detail.startswith(kind)


async def test_missing_key_falls_back_without_a_request(mock_http):
    """No key in the Keychain is not an outage — it is a Mac that listens to itself."""
    holder = mock_http(ok_transcript())
    c = ScribeClient(cooldown_s=0.0)
    c._key = None
    from app.secrets import keychain

    original = keychain.get_optional
    keychain.get_optional = lambda key: None
    try:
        result = await make(c).from_blob(webm_opus(tone_pcm(1.0)))
    finally:
        keychain.get_optional = original
    assert result.ok
    assert result.engine == "whisper_fallback"
    assert "no_key" in result.engine_detail
    assert holder["requests"] == []


async def test_fallback_output_is_still_normalised(mock_http):
    mock_http(lambda request: httpx.Response(401, text="nope"))
    whisper = FakeWhisper("find the blue wash yard genes")
    result = await make(client(), whisper).from_blob(webm_opus(tone_pcm(1.0)))
    assert result.engine == "whisper_fallback"
    assert "Blue Wash Yard Jeans" in result.text, "the normaliser must run on either engine"


async def test_both_engines_down_is_spoken_not_crashed(mock_http):
    mock_http(lambda request: httpx.Response(500, text="boom"))
    result = await make(client(), FakeWhisper(fail=True)).from_blob(webm_opus(tone_pcm(1.0)))
    assert not result.ok
    assert "speech recognition" in result.reason
    assert "whisper" not in result.reason.lower()
    assert "elevenlabs" not in result.reason.lower()
    assert result.engine == "none"


async def test_an_unexpected_error_still_falls_back(mock_http):
    """A bug in the Scribe path must not reach the tablet as a 500."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise ZeroDivisionError("something nobody planned for")

    mock_http(handler)
    result = await make(client()).from_blob(webm_opus(tone_pcm(1.0)))
    assert result.ok
    assert result.engine == "whisper_fallback"
    assert result.engine_detail == "unexpected: ZeroDivisionError"


async def test_whisper_primary_never_calls_scribe(mock_http):
    holder = mock_http(ok_transcript())
    t = Transcriber(FakeWhisper(), norm(), scribe=client(), primary="whisper")
    result = await t.from_blob(webm_opus(tone_pcm(1.0)))
    assert result.ok
    assert result.engine == "whisper"
    assert result.fallback is False
    assert holder["requests"] == []


# --------------------------------------------------------------------------- cooldown


async def test_a_rejected_key_opens_a_cooldown_instead_of_retrying(mock_http):
    holder = mock_http(lambda request: httpx.Response(401, text="invalid_api_key"))
    c = client(cooldown_s=300.0)
    t = make(c)
    first = await t.from_blob(webm_opus(tone_pcm(1.0)))
    second = await t.from_blob(webm_opus(tone_pcm(1.0)))
    assert first.engine == second.engine == "whisper_fallback"
    assert len(holder["requests"]) == 1, "a rejected key was retried on the next sentence"
    assert second.engine_detail.startswith("cooldown")
    assert c.cooling_down


async def test_a_timeout_does_not_open_a_cooldown(mock_http):
    """A slow minute is not a broken account; the next sentence tries Scribe again."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    holder = mock_http(handler)
    c = client(cooldown_s=300.0)
    t = make(c)
    await t.from_blob(webm_opus(tone_pcm(1.0)))
    await t.from_blob(webm_opus(tone_pcm(1.0)))
    assert len(holder["requests"]) == 2
    assert not c.cooling_down


async def test_success_clears_a_cooldown(mock_http):
    c = client(cooldown_s=300.0)
    c._cooldown_until = 0.0
    mock_http(ok_transcript("hello"))
    await c.transcribe(b"wav", keyterms=[])
    assert not c.cooling_down
    assert c.successes == 1 and c.attempts == 1


# --------------------------------------------------------------------------- the secret


async def test_the_key_is_sent_as_a_header_and_never_in_the_body(mock_http):
    holder = mock_http(ok_transcript())
    await make(client()).from_blob(webm_opus(tone_pcm(1.0)))
    request = holder["requests"][0]
    assert request.headers["xi-api-key"] == SECRET
    assert SECRET not in request.read().decode("utf-8", "replace")


async def test_no_secret_reaches_the_logs_or_the_error(mock_http, caplog):
    """An API that echoes the key back must not turn a log file into a credential store."""
    mock_http(lambda request: httpx.Response(401, text=f"invalid key: {SECRET}"))
    c = client()
    with caplog.at_level(logging.DEBUG):
        result = await make(c).from_blob(webm_opus(tone_pcm(1.0)))
    assert result.ok and result.fallback
    assert SECRET not in result.engine_detail
    assert "[redacted]" in result.engine_detail
    assert SECRET not in c.last_error
    assert SECRET not in caplog.text
    assert SECRET not in str(result.as_dict())


async def test_health_detail_carries_no_secret(mock_http):
    mock_http(lambda request: httpx.Response(401, text=f"bad key {SECRET}"))
    ok, detail = await client().health()
    assert not ok
    assert SECRET not in detail
    assert "401" in detail


async def test_health_is_ok_without_spending_credit(mock_http):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=[{"model_id": "eleven_v3"}])
        return httpx.Response(
            200, json={"tier": "creator", "character_count": 10, "character_limit": 100}
        )

    holder = mock_http(handler)
    ok, detail = await client().health()
    assert ok
    assert "key ok" in detail and "creator" in detail and "scribe_v2" in detail
    paths = [str(r.url.path) for r in holder["requests"]]
    assert paths[0].endswith("/models"), "the probe must not need the user_read permission"
    assert all(r.method == "GET" for r in holder["requests"])
    assert not any(p.endswith("/speech-to-text") for p in paths), "health must not spend credit"


async def test_health_tolerates_a_key_scoped_to_speech_to_text(mock_http):
    """The real CROOKS key: valid, and not permitted to read the account. ElevenLabs answers
    401 missing_permissions for that, which must not read as "the key is dead"."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=[{"model_id": "eleven_v3"}])
        return httpx.Response(
            401,
            json={"detail": {"status": "missing_permissions", "message": "needs user_read"}},
        )

    mock_http(handler)
    ok, detail = await client().health()
    assert ok, "a key that cannot read the account can still transcribe"
    assert "quota unreadable" in detail


async def test_health_reports_a_genuinely_bad_key(mock_http):
    mock_http(lambda request: httpx.Response(401, json={"detail": {"status": "invalid_api_key"}}))
    ok, detail = await client().health()
    assert not ok
    assert "rejected" in detail


async def test_health_is_not_ok_while_cooling_down(mock_http):
    mock_http(lambda request: httpx.Response(200, json=[{"model_id": "eleven_v3"}]))
    c = client(cooldown_s=300.0)
    c._cooldown_until = __import__("time").time() + 300
    c.last_error_kind = "credit"
    ok, detail = await c.health()
    assert not ok
    assert "SKIPPING Scribe" in detail


async def test_health_without_a_key_names_the_fix(monkeypatch):
    from app.secrets import keychain

    monkeypatch.setattr(keychain, "get_optional", lambda key: None)
    ok, detail = await ScribeClient().health()
    assert not ok
    assert "set_secrets.py elevenlabs_api_key" in detail


def test_elevenlabs_api_key_is_a_known_secret():
    from app.secrets import keychain

    assert "elevenlabs_api_key" in keychain.KNOWN_KEYS
    keychain._validate("elevenlabs_api_key")  # does not raise


async def test_scribe_unavailable_is_the_only_error_shape(mock_http):
    """The transcriber only catches ScribeUnavailable; anything else would reach the tablet
    as a 500. Every documented failure must therefore arrive as that one type."""
    mock_http(lambda request: httpx.Response(418, text="teapot"))
    with pytest.raises(ScribeUnavailable) as caught:
        await client().transcribe(b"wav", keyterms=[])
    assert caught.value.kind == "http_418"


async def test_one_connection_is_reused_across_recordings(monkeypatch):
    """The handshake to ElevenLabs is paid once per process, not once per sentence."""
    created = []
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        created.append(1)
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"text": "twelve orders"})
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    from app.clients.elevenlabs import ScribeClient

    client = ScribeClient()
    client._key = "sk_test_key_0123456789abcdef"
    assert (await client.transcribe(b"wav")).text == "twelve orders"
    assert (await client.transcribe(b"wav")).text == "twelve orders"
    assert len(created) == 1
    await client.aclose()


async def test_a_restricted_key_is_asked_about_its_quota_once_an_hour(mock_http):
    """The real key answers 401 to the account endpoint on every poll. Asking every 45 s
    changes nothing and fills the log with refusals; ask once, remember the answer."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=[{"model_id": "eleven_v3"}])
        return httpx.Response(
            401, json={"detail": {"status": "missing_permissions", "message": "needs user_read"}}
        )

    holder = mock_http(handler)
    c = client()
    for _ in range(3):
        ok, detail = await c.health()
        assert ok and "quota unreadable" in detail
    paths = [str(r.url.path) for r in holder["requests"]]
    assert paths.count("/v1/models") == 3 or sum(p.endswith("/models") for p in paths) == 3
    assert sum(p.endswith("/subscription") for p in paths) == 1

    # The memory expires: an hour later it is asked again.
    c._quota_memo = (0.0, *c._quota_memo[1:])
    await c.health()
    paths = [str(r.url.path) for r in holder["requests"]]
    assert sum(p.endswith("/subscription") for p in paths) == 2
