"""The HTTP surface, driven through ASGI.

The real Claude provider is swapped for a fake before any request is made. On a machine where
the claude CLI is logged in, the real provider WOULD answer — and a test suite that spends the
Max allowance on every run is exactly the mistake the build plan warns about.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.main import app
from app.providers.base import ClaudeProvider, ToolCall, TurnResult


class FakeProvider(ClaudeProvider):
    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def turn(self, session_id: str, text: str) -> TurnResult:
        self.turns.append((session_id, text))
        return TurnResult(text=f"fake answer to {len(text)} chars", session_id=session_id)

    async def health(self) -> tuple[bool, str]:
        return True, "fake"

    async def reset_session(self, session_id: str) -> None:
        pass


@pytest.fixture()
async def client(monkeypatch):
    # Stop the lifespan from starting the real provider at all.
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)

    # /health asks ElevenLabs whether the account is alive. On the owner's Mac the key is in
    # the Keychain and that would be a real call to a paid API on every test run.
    from app.clients.elevenlabs import ScribeClient

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)

    # And the voice must not read the owner's real Keychain entry to report itself healthy.
    from app.clients.elevenlabs_tts import VoiceClient

    monkeypatch.setattr(
        VoiceClient, "health", lambda self: (True, f"key ok · ElevenLabs {self.voice_name}")
    )
    async with app.router.lifespan_context(app):
        app.state.runtime.provider = FakeProvider()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


async def test_health_names_each_subsystem(client):
    body = (await client.get("/health")).json()
    assert body["status"] in {"ok", "degraded"}
    assert {
        "claude", "scribe", "whisper", "speech", "tts", "shopify", "gmail", "knowledge_base",
        "terminology",
    } <= body["checks"].keys()
    for name, check in body["checks"].items():
        # ok and detail are the contract every check keeps, and the tablet reads nothing else.
        # Two checks add one optional field apiece: `whisper` says disabled=True where the host
        # was never given a local recogniser, and `speech` says which redundancy world the
        # reader is in. Anything beyond these is a check inventing its own shape.
        assert {"ok", "detail"} <= set(check), name
        assert set(check) <= {"ok", "detail", "disabled", "redundancy"}, name
    assert "version" in body and "uptime_s" in body


async def test_tools_endpoint_lists_tiers(client):
    tools = (await client.get("/tools")).json()["tools"]
    tiers = {t["name"]: t["tier"] for t in tools}
    assert tiers["mock_danger"] == "RED"
    assert tiers["shopify_order_detail"] == "AMBER"
    assert tiers["shopify_list_orders"] == "GREEN"


async def test_empty_text_is_handled(client):
    body = (await client.post("/turn", json={"text": "  ", "session_id": "e"})).json()
    assert body["error_kind"] == "empty"


async def test_lost_thread_is_answered_from_the_start_and_says_so(client):
    """The backend restarted since the tablet last spoke. It heard the question, so it answers
    it in a fresh conversation and says the earlier thread is gone — not "ask me again"."""
    body = (await client.post("/turn", json={"text": "how many orders today?", "session_id": "ghost", "turns": 2})).json()
    assert body["error_kind"] is None
    assert body["lost_thread"] is True
    assert body["answer"].startswith("I lost our earlier thread, so from the start: ")
    assert "fake answer" in body["answer"]
    # The tablet's count is reset to the fresh session's.
    assert body["turns"] in (0, 1)


async def test_new_session_with_zero_turns_is_not_lost(client):
    body = (await client.post("/turn", json={"text": "hello", "session_id": "fresh", "turns": 0})).json()
    assert body["error_kind"] != "lost_thread"


async def test_state_endpoint_for_unknown_session(client):
    body = (await client.get("/state/nobody")).json()
    assert body == {"session_id": "nobody", "known": False, "state": "READY", "detail": ""}


async def test_undecodable_audio_is_a_named_speech_error(client):
    files = {"audio": ("t.webm", b"\x00" * 64, "audio/webm")}
    body = (await client.post("/turn", data={"session_id": "a", "turns": "0"}, files=files)).json()
    assert body["error_kind"] == "speech"
    assert body["answer"]


async def test_audio_test_reports_decode_failure(client):
    files = {"audio": ("t.webm", b"junk", "audio/webm")}
    body = (await client.post("/audio-test", files=files)).json()
    assert body["ok"] is False and "error" in body


# What the Mac says about ITSELF after the question: the standing capability block, which is
# there on every turn once any capability family is registered (app/families/*, and
# `turn._family_lines`). It is not part of the question and must never be counted as though
# it were — the cap below is on the QUESTION.


async def test_text_is_capped(client):
    body = (await client.post("/turn", json={"text": "x" * 10_000, "session_id": "cap"})).json()
    assert body["error_kind"] is None
    # 2000 chars of question, between the clock line the Mac puts above every question and the
    # context blocks it puts below one — a set, a capability family's state, the last change,
    # the last read-layer query (app/routes/turn.py `_context_lines`). Each is bracketed, so
    # the question is still exactly what was said however many of them there are that turn.
    session_id, sent = app.state.runtime.provider.turns[-1]
    clock, rest = sent.split("\n", 1)
    question = rest.split("\n\n[", 1)[0]
    assert session_id == "cap" and clock.startswith("[Now: ")
    assert question == "x" * 2000, "the question is capped, whatever the Mac appends after it"
    assert body["turns"] == 0  # the fake provider does not bump the session's turn count


async def test_turn_goes_through_the_provider_once(client):
    # The transcript was "hello" until Phase 5 §24, and is a question about the shop now. Not
    # a weakened expectation — a stronger one, of a different module: "hello" no longer
    # reaches the model at all (app/families/interaction.py), because a greeting answered by a
    # round trip to a language model was nine of the live session's unrouted turns. This test
    # is about the PROVIDER path, so it needs a sentence that takes it; the sentence itself was
    # always incidental.
    said = "how much stock of the yard jeans"
    body = (await client.post("/turn", json={"text": said, "session_id": "once"})).json()
    assert body["answer"].startswith("fake answer")
    (session_id, sent), = app.state.runtime.provider.turns
    assert session_id == "once"
    # The question reaches the model once, under the shop's clock — never as bare text. What
    # follows it, after a blank line, is whatever context the Mac has to add this turn: its
    # own lines, each bracketed, so the question itself is still exactly what was said.
    clock, rest = sent.split("\n", 1)
    question = rest.split("\n\n[", 1)[0]
    assert question == said and clock.startswith("[Now: ") and clock.endswith("Europe/London]")
    assert sent.count(said) == 1


async def test_a_spoken_order_number_is_looked_up_before_the_model_is_asked(client, monkeypatch):
    """The Mac already knows "order 1930" is an order number. It runs the lookup the model
    would have run first, through the same gate, hands the model the result, and the card
    still comes from the tool call. A mis-heard number costs one Shopify call, not a turn."""
    from app.routes import turn as turn_module

    seen = []

    async def fake_dispatch(name, args, *, session, timeout_s, calls=None):
        seen.append((name, args))
        session.issue("gid://shopify/Order/1930")
        if calls is not None:
            calls.append(ToolCall(name=name, args=args, ok=True, result={"orders": [{"order_id": "gid://shopify/Order/1930", "order_number": "#1930", "payment": "paid", "fulfillment": "unfulfilled", "total": "£60.00"}]}))
        return '{"orders": [{"order_number": "#1930", "payment": "paid"}]}'

    monkeypatch.setattr("app.tools.dispatch.dispatch", fake_dispatch)
    body = (await client.post("/turn", json={"text": "Find order 1930 and add a note saying customer called", "session_id": "pre"})).json()
    assert seen == [("shopify_find_order", {"query": "1930"})]
    _, sent = app.state.runtime.provider.turns[-1]
    assert "already ran shopify_find_order" in sent and "#1930" in sent and "do not call shopify_find_order for 1930 again" in sent
    assert body["question"] == "Find order 1930 and add a note saying customer called"
    assert [c["name"] for c in body["tool_calls"]][0] == "shopify_find_order"
    assert body["ui"] and body["ui"][0]["type"] == "order", body["ui"]
    assert "prefetch" in body["timings_ms"]
    assert "gid://shopify/Order/1930" in app.state.runtime.sessions.get("pre").issued_ids
    # No order number, or two: nothing is looked up ahead of the model. A read the fast lane
    # makes for itself is not a prefetch, so the check is on the prefetch, by tool.
    seen.clear()
    body = (await client.post("/turn", json={"text": "how many orders today", "session_id": "pre"})).json()
    assert "prefetch" not in body["timings_ms"]
    body = (await client.post("/turn", json={"text": "compare order 1930 with order 1931", "session_id": "pre"})).json()
    assert "prefetch" not in body["timings_ms"]
    assert [name for name, _ in seen if name == "shopify_find_order"] == []
    assert turn_module.is_affirmation("yes") and not turn_module.is_affirmation("yes and cancel it")
    # Words that may answer a question the model asked are not affirmations.
    for word in ("fine", "correct", "that's right", "alright", "please"):
        assert not turn_module.is_affirmation(word), word


def test_only_an_order_the_owner_named_is_looked_up_ahead():
    from app.routes.turn import spoken_order_numbers as spoken

    assert spoken("find order 1938 and add a note") == ["1938"]
    assert spoken("Order number 1938, has it shipped?") == ["1938"]
    assert spoken("invoice no. 1905") == ["1905"]
    assert spoken("order number 2025") == ["2025"], "written as a number, it is an order"
    assert spoken("order #2031") == ["2031"]
    for phrase in ("orders over 500 pounds", "orders from 2025", "orders in the last 100 days", "how many orders in 2025",
                   "order 2025 pounds worth", "the order came in 2025", "order 500 units", "orders today"):
        assert spoken(phrase) == [], phrase
    assert spoken("compare order 1930 with order 1931") == ["1930", "1931"]


async def test_real_provider_is_never_started_by_tests(client):
    from app.providers.max_agent_sdk import MaxAgentSDKProvider

    assert not isinstance(app.state.runtime.provider, MaxAgentSDKProvider)


async def test_reload_kb(client):
    body = (await client.post("/reload-kb")).json()
    assert body["reloaded"] is True


async def test_reset(client):
    body = (await client.post("/reset", data={"session_id": "x"})).json()
    assert body == {"reset": True}


async def test_the_favicon_is_the_page_icon(client):
    """Desktop Chrome asks for it on every visit; a 404 per visit is log noise."""
    response = await client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_index_serves_the_tablet_page(client):
    r = await client.get("/")
    assert r.status_code == 200 and "CROOKS" in r.text


async def test_reload_kb_resets_the_provider_prompt(client):
    provider = app.state.runtime.provider
    provider.prompts = []

    async def set_system_prompt(prompt):
        provider.prompts.append(prompt)

    provider.set_system_prompt = set_system_prompt
    body = (await client.post("/reload-kb")).json()
    assert body["reloaded"] and provider.prompts and "CROOKS" in provider.prompts[0]


async def test_audio_test_returns_playable_wav(client):
    pytest.importorskip("av")
    from tests.test_decode import tone_pcm, webm_opus

    files = {"audio": ("t.webm", webm_opus(tone_pcm(0.5)), "audio/webm")}
    body = (await client.post("/audio-test", files=files)).json()
    assert body["ok"] and body["wav_base64"].startswith("UklGR")  # "RIFF" in base64


async def test_tool_calls_carry_redacted_args(client):
    from app.providers.base import ToolCall, TurnResult

    async def turn(session_id, text):
        return TurnResult(text="ok", session_id=session_id, tool_calls=[
            ToolCall(name="gmail_search", args={"query": "from:jo@example.com", "days": 1})
        ])

    app.state.runtime.provider.turn = turn
    # "hi" until Phase 5 §24, when a greeting stopped reaching the model at all
    # (app/families/interaction.py). The redaction this test is about is unchanged; the
    # transcript only has to be a sentence the provider still takes.
    body = (await client.post("/turn", json={"text": "tell me about the shop", "session_id": "args"})).json()
    call = body["tool_calls"][0]
    assert call["args"]["days"] == "1"
    assert "jo@example.com" not in call["args"]["query"]


# --------------------------------------------------------------------------- POST /speak
#
# The voice is an output layer. Every test below is a way it can fail, and in all of them the
# answer still exists: /turn is untouched, and the tablet is told plainly enough to fall back.


class FakeVoiceStream:
    def __init__(self, body: bytes) -> None:
        self.body = body

    async def chunks(self):
        # Two chunks, because the tablet must survive a body arriving in pieces.
        yield self.body[: len(self.body) // 2]
        yield self.body[len(self.body) // 2 :]


def stub_voice(client_app, *, audio: bytes | None = None, fail: str | None = None):
    """Replace the runtime's ElevenLabs client. No test may spend a credit."""
    from app.clients.elevenlabs_tts import VoiceUnavailable

    voice = client_app.state.runtime.voice
    calls: list[str] = []

    async def open_stream(text: str):
        calls.append(text)
        if fail:
            raise VoiceUnavailable("stubbed failure", kind=fail)
        return FakeVoiceStream(audio or b"\xff\xfb\x90\x00mp3")

    voice.open_stream = open_stream  # type: ignore[method-assign]
    return calls


async def test_speak_returns_vikram_as_mp3(client):
    calls = stub_voice(app, audio=b"\xff\xfb\x90\x00" + b"\x00" * 64)
    response = await client.post("/speak", json={"text": "Twelve orders today."})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content.startswith(b"\xff\xfb")
    assert response.headers["x-crooks-model"] == app.state.runtime.voice.model
    assert calls == ["Twelve orders today."]


async def test_speak_says_the_prepared_text_not_the_written_one(client):
    calls = stub_voice(app)
    await client.post("/speak", json={"text": "**Order #1930** came to £60."})
    assert calls == ["Order nineteen thirty came to sixty pounds."]


async def test_speak_never_returns_the_key_or_the_account_detail(client):
    stub_voice(app, fail="rejected")
    response = await client.post("/speak", json={"text": "Twelve orders today."})
    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False and body["kind"] == "rejected"
    # A reason the owner can act on, with nothing from ElevenLabs' own error in it.
    assert "key" in body["reason"]
    assert "xi-api-key" not in response.text and "sk_" not in response.text


async def test_speak_failure_is_a_503_the_tablet_can_fall_back_from(client):
    for kind in ("no_key", "credit", "timeout", "network", "cooldown", "off"):
        stub_voice(app, fail=kind)
        response = await client.post("/speak", json={"text": "Twelve orders today."})
        assert response.status_code == 503, kind
        assert response.json()["kind"] == kind


async def test_speak_says_nothing_rather_than_paying_to_say_nothing(client):
    calls = stub_voice(app)
    for text in ("", "   ", "...", "***"):
        response = await client.post("/speak", json={"text": text})
        assert response.status_code == 204
    assert calls == []


async def test_speak_never_logs_the_answer(client, caplog):
    import logging

    stub_voice(app)
    with caplog.at_level(logging.DEBUG, logger="crooks.speak"):
        await client.post("/speak", json={"text": "Jane Smith's order 1930 is late."})
    assert "Jane" not in caplog.text


async def test_a_turn_still_answers_when_the_voice_is_broken(client):
    """The point of the whole design: TTS is not a dependency of Shopify, Gmail or Claude."""
    stub_voice(app, fail="credit")
    turn = (await client.post("/turn", json={"text": "how many orders today"})).json()
    assert turn["answer"]
    assert turn["error_kind"] is None
    assert (await client.post("/speak", json={"text": turn["answer"]})).status_code == 503


# The ElevenLabs voices this project has been given permission to speak with, by id. The id
# is the only part ElevenLabs acts on; the name is what this code calls it, and the pair has
# to agree or /health reports one voice while the tablet hears another. Adding a voice is a
# line here and a line in config/settings.py, deliberately, in that order.
APPROVED_VOICES = {
    "Q0Et7LOU7VpeoeCRQAVS": "Derek",     # the production voice
    "9375G6zswFk7v9bKTVQF": "Vikram",    # "AI Productivity Assistant"; used before Derek
}
PRODUCTION_VOICE_ID = "Q0Et7LOU7VpeoeCRQAVS"


async def test_health_names_the_voice(client):
    settings = app.state.runtime.settings
    body = (await client.get("/health")).json()
    assert body["voice"]["voice"] == settings.tts_voice_name
    assert body["voice"]["model"] == settings.tts_model
    assert body["voice"]["provider"] == "elevenlabs"
    # Whatever voice is configured is the one health names — not a name written into the page.
    assert settings.tts_voice_name in body["checks"]["tts"]["detail"]


async def test_the_configured_voice_is_the_one_that_was_approved(client):
    """Derek is the approved production voice, from the default in the code to the URL the
    request goes to. A `.env` line still wins over the default, so the check that matters at
    run time is not this one: /health asks ElevenLabs whose voice the id really is and fails
    when they disagree. What is proved here is that nothing between the setting and the
    request substitutes a voice of its own, and that an id and a name never drift apart."""
    from config.settings import Settings

    # 1. the default in the code, with nothing configured at all
    bare = Settings(_env_file=None)
    assert (bare.tts_voice_id, bare.tts_voice_name) == (PRODUCTION_VOICE_ID, "Derek")
    assert (bare.tts_model, bare.tts_output_format) == ("eleven_flash_v2_5", "mp3_44100_128")

    # 2. the settings this process is running with: an approved id, under its own name
    settings = app.state.runtime.settings
    assert settings.tts_voice_id in APPROVED_VOICES, "an unapproved ElevenLabs voice id"
    assert settings.tts_voice_name == APPROVED_VOICES[settings.tts_voice_id]
    assert settings.tts_model == "eleven_flash_v2_5"
    assert settings.tts_output_format == "mp3_44100_128"

    # 3. the client the runtime built, and the request it would send
    voice = app.state.runtime.voice
    assert (voice.voice_id, voice.voice_name) == (settings.tts_voice_id, settings.tts_voice_name)
    url = voice._url(stream=True)
    assert url.endswith(
        f"/text-to-speech/{settings.tts_voice_id}/stream"
        f"?output_format={settings.tts_output_format}"
    )
    assert voice._payload("hello")["model_id"] == settings.tts_model

    # 4. what the health page says, and what the tablet is told
    body = (await client.get("/health?fresh=1")).json()
    assert body["voice"]["voice"] == settings.tts_voice_name
    assert body["voice"]["model"] == settings.tts_model
    assert body["voice"]["output_format"] == settings.tts_output_format


# --------------------------------------------------------------------------- the ui contract


async def test_turn_returns_structured_ui_chosen_from_tool_results(client):
    """The cards come from the tool payloads, and the payloads themselves stay on the Mac."""
    from app.providers.base import ToolCall, TurnResult

    async def turn(session_id, text):
        app.state.runtime.sessions.get_or_create(session_id)   # as the real provider does
        return TurnResult(text="Order 1930 is unfulfilled.", session_id=session_id, tool_calls=[
            ToolCall(name="shopify_find_order", args={"query": "1930"}, result={"orders": [{
                "order_id": "gid://shopify/Order/1", "order_number": "CROOKS-1930", "total": "60.00 GBP",
                "fulfillment": "UNFULFILLED", "payment": "PAID", "customer_name": "Jo Bloggs",
                "customer_id": "gid://shopify/Customer/2", "placed_at": "2026-09-08T10:00:00Z",
            }]}),
        ])

    app.state.runtime.provider.turn = turn
    body = (await client.post("/turn", json={"text": "show me order 1930", "session_id": "ui1"})).json()
    assert [item["type"] for item in body["ui"]] == ["order", "context_stack"]
    assert body["ui"][0]["data"]["order_number"] == "#1930"
    assert body["ui"][0]["data"]["total"] == "£60.00"
    assert "result" not in body["tool_calls"][0]


async def test_error_turns_carry_an_error_card(client):
    body = (await client.post("/turn", json={"text": "  ", "session_id": "ui2"})).json()
    assert body["ui"] == [{"type": "error", "data": {
        "service": "speech", "kind": "empty", "title": "Didn't catch that", "recovery": "Hold the orb while you speak.",
    }}]


async def test_ui_is_always_present_and_a_list(client):
    body = (await client.post("/turn", json={"text": "hello", "session_id": "ui3"})).json()
    assert isinstance(body["ui"], list)


# --------------------------------------------------------------------------- speed


async def test_the_voice_starts_before_the_tablet_asks_for_it(client):
    """With speak=1 on /turn the answer is synthesised at once; /speak then serves it whole
    and no second ElevenLabs request is made."""
    calls = stub_voice(app, audio=b"\xff\xfb\x90\x00" + b"\x00" * 32)
    turn = (await client.post("/turn", json={"text": "how many orders today", "session_id": "pf", "speak": True})).json()
    spoken = (await client.post("/speak", json={"text": turn["answer"]}))
    assert spoken.status_code == 200
    assert spoken.headers.get("x-crooks-prefetched") == "1"
    assert spoken.content.startswith(b"\xff\xfb")
    assert len(calls) == 1
    # Asking again is a fresh request: nothing is served twice from memory.
    again = await client.post("/speak", json={"text": turn["answer"]})
    assert again.headers.get("x-crooks-prefetched") is None
    assert len(calls) == 2


async def test_no_prefetch_unless_the_caller_will_speak(client):
    calls = stub_voice(app)
    await client.post("/turn", json={"text": "hello", "session_id": "nopf"})
    await client.post("/turn", data={"text": "hello", "session_id": "nopf2", "turns": "0"})
    await asyncio.sleep(0)
    assert calls == []


async def test_health_is_cached_briefly_and_fresh_on_request(client):
    first = (await client.get("/health")).json()
    second = (await client.get("/health")).json()
    fresh = (await client.get("/health?fresh=1")).json()
    assert first["cached"] is False and second["cached"] is True and fresh["cached"] is False
    assert second["checks"] == first["checks"]


async def test_the_catalogue_refresh_never_blocks_a_turn(client):
    runtime = app.state.runtime
    runtime._catalogue_refreshed_at = 0.0
    runtime.refresh_catalogue_soon()
    task = runtime._catalogue_task
    assert task is not None and not task.done()   # scheduled, not awaited
    await task
    assert runtime._catalogue_refreshed_at > 0


# --------------------------------------------------------------------------- the council's tests


async def test_speak_streams_the_prefetched_answer_before_it_has_all_arrived(client):
    """The first bytes of a prefetched answer leave for the tablet while ElevenLabs is still
    producing the rest. This is the test the first speed commit did not have. The route is
    called directly: the ASGI test transport buffers bodies, which is the very thing the
    tablet's player must not do."""
    import time

    from fastapi.responses import StreamingResponse

    from app.routes.speak import speak

    class SlowVoiceStream:
        async def chunks(self):
            yield b"\xff\xfb\x90\x00" + b"\x01" * 64
            await asyncio.sleep(0.4)
            yield b"\x02" * 64

    voice = app.state.runtime.voice
    calls = []

    async def open_stream(text):
        calls.append(text)
        return SlowVoiceStream()

    voice.open_stream = open_stream  # type: ignore[method-assign]
    turn = (await client.post("/turn", json={"text": "how many orders", "session_id": "slow", "speak": True})).json()

    class FakeRequest:
        app = client._transport.app  # type: ignore[attr-defined]

        async def json(self):
            return {"text": turn["answer"]}

    started = time.perf_counter()
    response = await speak(FakeRequest())
    assert isinstance(response, StreamingResponse)
    assert response.headers.get("x-crooks-prefetched") == "1"
    first_at = None
    total = b""
    async for chunk in response.body_iterator:
        if first_at is None:
            first_at = time.perf_counter() - started
        total += chunk
    assert first_at is not None and first_at < 0.25, f"first byte after {first_at:.2f}s"
    assert total.startswith(b"\xff\xfb") and total.endswith(b"\x02" * 64)
    assert len(calls) == 1


async def test_the_prefetch_key_is_what_speak_will_ask_for(client):
    """/turn prefetches the speakable form of the answer and /speak looks up the speakable
    form of the text the tablet sends; if those ever drift apart every answer is synthesised
    twice. The tablet sends the answer verbatim, so this holds them together."""
    calls = stub_voice(app)
    provider = app.state.runtime.provider

    async def turn(session_id, text):
        from app.providers.base import TurnResult

        return TurnResult(text="**Order #1930** came to £60.", session_id=session_id)

    provider.turn = turn
    body = (await client.post("/turn", json={"text": "order 1930", "session_id": "key", "speak": True})).json()
    await client.post("/speak", json={"text": body["answer"]})
    assert calls == ["Order nineteen thirty came to sixty pounds."]


async def test_a_fixed_error_line_is_never_synthesised_twice(client):
    calls = stub_voice(app)
    for _ in range(3):
        body = (await client.post("/turn", json={"text": "  ", "session_id": "err", "speak": True})).json()
        assert body["error_kind"] == "empty"
        assert (await client.post("/speak", json={"text": body["answer"]})).status_code == 200
    assert len(calls) == 1


async def test_a_prefetch_that_hit_a_blip_is_tried_once_more_but_a_timeout_is_not(client):
    """A 5xx or a burst refusal a round trip ago says nothing about now: one fresh request,
    the same one the tablet would have made. A slow ElevenLabs is not asked twice."""
    from app.clients.elevenlabs_tts import VoiceUnavailable

    voice = app.state.runtime.voice
    calls: list[str] = []

    async def flaky(text: str):
        calls.append(text)
        if len(calls) == 1:
            raise VoiceUnavailable("stubbed 502", kind="server_error")
        return FakeVoiceStream(b"\xff\xfb\x90\x00mp3")

    voice.open_stream = flaky  # type: ignore[method-assign]
    body = (await client.post("/turn", json={"text": "hello", "session_id": "blip", "speak": True})).json()
    await asyncio.sleep(0)
    response = await client.post("/speak", json={"text": body["answer"]})
    assert response.status_code == 200 and len(calls) == 2


async def test_a_failed_prefetch_is_reported_at_once_without_a_second_request(client):
    calls = stub_voice(app, fail="timeout")
    body = (await client.post("/turn", json={"text": "hello", "session_id": "tmo", "speak": True})).json()
    response = await client.post("/speak", json={"text": body["answer"]})
    assert response.status_code == 503 and response.json()["kind"] == "timeout"
    assert len(calls) == 1


async def test_state_carries_what_was_heard_while_thinking(client):
    await client.post("/turn", json={"text": "show me order 1930", "session_id": "heard"})
    body = (await client.get("/state/heard")).json()
    assert body["heard"] == "show me order 1930"


async def test_cancel_stops_prefetches_and_asks_the_provider_to_interrupt(client):
    provider = app.state.runtime.provider
    asked = []

    async def interrupt(session_id):
        asked.append(session_id)
        return True

    provider.interrupt = interrupt
    body = (await client.post("/cancel", data={"session_id": "busy"})).json()
    assert body == {"cancelled": True, "interrupted": True, "prefetches_stopped": 0, "revoked": []}
    assert asked == ["busy"]


async def test_the_installed_app_is_served_from_the_root(client):
    """Chrome installs from the manifest and the worker; both live at the root so the app's
    scope is the whole site, and the worker carries the build it was served with."""
    manifest = await client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert manifest.json()["name"] == "CROOKS OS"
    assert manifest.headers.get("cache-control") == "no-cache"

    worker = await client.get("/sw.js")
    assert worker.status_code == 200
    assert "javascript" in worker.headers["content-type"]
    assert worker.headers.get("cache-control") == "no-cache"
    assert "__BUILD__" not in worker.text

    ping = (await client.get("/ping")).json()
    assert ping["ok"] is True and ping["build"]
    assert "crooks-shell-${BUILD}" in worker.text and f"const BUILD = '{ping['build']}';" in worker.text

    for icon in ("icon-192.png", "icon-512.png", "icon-maskable-192.png", "icon-maskable-512.png"):
        response = await client.get(f"/static/{icon}")
        assert response.status_code == 200 and response.headers["content-type"] == "image/png", icon


async def test_the_page_and_its_scripts_are_never_cached_for_long(client):
    for path in ("/", "/static/app.js"):
        response = await client.get(path)
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache"
    health = (await client.get("/health?fresh=1")).json()
    assert len(health["build"]) == 12


async def test_allowed_logins_refuse_a_stranger_and_admit_the_owner_and_the_mac(client):
    app.state.allowed_logins = ("owner@example.com",)
    try:
        stranger = await client.get("/health", headers={"Tailscale-User-Login": "someone@else.com"})
        assert stranger.status_code == 403
        owner = await client.get("/health", headers={"Tailscale-User-Login": "Owner@Example.com"})
        assert owner.status_code == 200
        local = await client.get("/health")   # no header: the Mac itself
        assert local.status_code == 200
        # Proxied by Tailscale but carrying no login (Funnel, a tagged node): refused.
        anonymous = await client.get("/health", headers={"X-Forwarded-For": "100.64.0.9"})
        assert anonymous.status_code == 403
    finally:
        app.state.allowed_logins = ()


async def test_an_abandoned_question_is_not_voiced(client):
    """/cancel lands while Claude is still thinking; when that turn ends, its answer must not
    be synthesised for a tablet that has already moved on."""
    calls = stub_voice(app)
    provider = app.state.runtime.provider
    gate = asyncio.Event()

    async def slow_turn(session_id, text):
        from app.providers.base import TurnResult

        app.state.runtime.sessions.get_or_create(session_id)
        await gate.wait()
        return TurnResult(text="Too late to matter.", session_id=session_id)

    provider.turn = slow_turn
    turn = asyncio.create_task(client.post("/turn", json={"text": "long one", "session_id": "gone", "speak": True}))
    await asyncio.sleep(0.05)
    cancelled = (await client.post("/cancel", data={"session_id": "gone"})).json()
    assert cancelled["cancelled"] is True
    gate.set()
    body = (await turn).json()
    assert body["answer"] == "Too late to matter."
    await asyncio.sleep(0)
    assert calls == []
    # The next question is voiced as normal.
    provider.turn = FakeProvider().turn
    await client.post("/turn", json={"text": "next", "session_id": "gone", "speak": True})
    assert len(calls) == 1


async def test_the_last_question_is_not_shown_while_the_next_is_heard(client):
    await client.post("/turn", json={"text": "first question", "session_id": "stale"})
    assert (await client.get("/state/stale")).json()["heard"] == "first question"
    provider = app.state.runtime.provider
    gate = asyncio.Event()

    async def slow_turn(session_id, text):
        from app.providers.base import TurnResult

        await gate.wait()
        return TurnResult(text="ok", session_id=session_id)

    provider.turn = slow_turn
    turn = asyncio.create_task(client.post("/turn", json={"text": "second question", "session_id": "stale"}))
    await asyncio.sleep(0.05)
    # Mid-turn the state carries the new question (or nothing), never the old one.
    heard = (await client.get("/state/stale")).json()["heard"]
    assert heard in ("", "second question")
    gate.set()
    await turn


async def test_a_hold_during_hearing_still_abandons_the_question(client):
    """/cancel can land before the turn has reached Claude — during transcription, or before
    the session's first turn exists at all. It must still keep the answer from being voiced."""
    calls = stub_voice(app)
    provider = app.state.runtime.provider
    gate = asyncio.Event()

    async def slow_turn(session_id, text):
        from app.providers.base import TurnResult

        await gate.wait()
        return TurnResult(text="Never voiced.", session_id=session_id)

    provider.turn = slow_turn
    # A brand-new session: /cancel arrives first (the tablet's hold landed while the Mac was
    # still transcribing), then the turn proceeds.
    await client.post("/cancel", data={"session_id": "early"})
    turn = asyncio.create_task(client.post("/turn", json={"text": "long", "session_id": "early", "speak": True}))
    await asyncio.sleep(0.05)
    gate.set()
    await turn
    await asyncio.sleep(0)
    # The turn reset the flag at its start, so this cancel was for "before"; the next hold
    # during the turn is what counts.
    assert len(calls) == 1
    calls.clear()
    gate.clear()
    turn = asyncio.create_task(client.post("/turn", json={"text": "long again", "session_id": "early", "speak": True}))
    await asyncio.sleep(0.05)
    await client.post("/cancel", data={"session_id": "early"})
    gate.set()
    await turn
    await asyncio.sleep(0)
    assert calls == []


async def test_speak_streams_through_the_real_middleware(client):
    """The streaming test above calls the route directly. This one drives the whole ASGI app —
    middleware included — and times the body messages, so a middleware that buffers the
    response (the classic BaseHTTPMiddleware regression) cannot return unnoticed."""
    import json
    import time

    class SlowVoiceStream:
        async def chunks(self):
            yield b"\\xff\\xfb\\x90\\x00" + b"\\x01" * 64
            await asyncio.sleep(0.4)
            yield b"\\x02" * 64

    voice = app.state.runtime.voice

    async def open_stream(text):
        return SlowVoiceStream()

    voice.open_stream = open_stream  # type: ignore[method-assign]
    body = json.dumps({"text": "Twelve orders today."}).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/speak", "raw_path": b"/speak", "query_string": b"",
        "root_path": "", "headers": [(b"content-type", b"application/json"), (b"host", b"t"),
                                     (b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8000), "state": {},
    }
    sent_body = False
    arrivals: list[tuple[float, bytes]] = []
    started = time.perf_counter()

    async def receive():
        nonlocal sent_body
        if sent_body:
            await asyncio.sleep(3600)
        sent_body = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            arrivals.append((time.perf_counter() - started, message["body"]))

    await app(scope, receive, send)
    assert arrivals, "no body arrived"
    first_at, first = arrivals[0]
    assert first.startswith(b"\\xff\\xfb")
    assert first_at < 0.25, f"the middleware held the first chunk for {first_at:.2f}s"
    assert b"".join(chunk for _, chunk in arrivals).endswith(b"\\x02" * 64)


async def test_a_question_asked_over_the_last_one_leaves_the_first_unvoiced(client):
    """The tablet does not wait for /cancel before sending the next question. The first turn's
    answer, arriving after the second has started, must not be voiced: the conversation has
    moved past it, whatever the abandoned flag says by then."""
    calls = stub_voice(app)
    provider = app.state.runtime.provider
    gate = asyncio.Event()
    fake = FakeProvider()

    async def slow_turn(session_id, text):
        from app.providers.base import TurnResult

        await gate.wait()
        return TurnResult(text="Never voiced.", session_id=session_id)

    provider.turn = slow_turn
    first = asyncio.create_task(client.post("/turn", json={"text": "first", "session_id": "over", "speak": True}))
    await asyncio.sleep(0.05)
    provider.turn = fake.turn
    second = (await client.post("/turn", json={"text": "second", "session_id": "over", "speak": True})).json()
    assert second["answer"].startswith("fake answer")
    assert len(calls) == 1
    gate.set()
    body = (await first).json()
    assert body["answer"] == "Never voiced."
    await asyncio.sleep(0)
    assert len(calls) == 1, "the first answer was not synthesised"


async def test_the_state_says_transcribing_while_the_recogniser_runs(client):
    runtime = app.state.runtime
    seen = {}

    async def fake_from_blob(blob, filename_hint=""):
        seen["state"] = (await client.get("/state/hear")).json()["state"]
        from app.speech.transcribe import SpeechResult

        return SpeechResult(ok=False, reason="I did not catch that.", timings_ms={})

    original = runtime.transcriber.from_blob
    runtime.transcriber.from_blob = fake_from_blob
    try:
        body = (await client.post("/turn", data={"session_id": "hear"}, files={"audio": ("t.webm", b"\x00" * 64, "audio/webm")})).json()
    finally:
        runtime.transcriber.from_blob = original
    assert seen["state"] == "TRANSCRIBING"
    assert body["error_kind"] == "speech"
    assert (await client.get("/state/hear")).json()["state"] == "READY"


async def test_the_microphone_diagnostic_keeps_nothing_unless_captures_are_on(client):
    """/audio-test decodes and plays back what the Mac heard. It is a diagnostic, not an
    archive: the office's voice reaches the disk only when captures are asked for."""
    pytest.importorskip("av")
    from tests.test_decode import tone_pcm, webm_opus

    files = {"audio": ("t.webm", webm_opus(tone_pcm(0.5)), "audio/webm")}
    body = (await client.post("/audio-test", files=files)).json()
    assert body["ok"] is True and body["saved_to"] is None
    assert body["wav_base64"], "it still plays back what it heard"


# ------------------------------------------------------------- a cancel names its own half
#
# The provider side of concurrent halves is tests/test_branch_concurrency.py; these two are
# here because they need this module's app fixture and voice stub.


async def test_a_cancel_on_one_half_leaves_the_other_halfs_answer_spoken(client):
    """The owner holds the orb on the right half while the left half is still thinking. The
    cancel the tablet posts names the right half; the left half's answer, when it lands, is
    voiced and keeps its cards. A cancel naming the left half abandons it, as before."""
    calls = stub_voice(app)
    runtime = app.state.runtime
    live = runtime.sessions.get_or_create("halves")
    left = live.branch().branch_id
    forked = (await client.post("/branches/fork", data={"session_id": "halves"})).json()
    right = forked["branch_id"]
    gate = asyncio.Event()

    async def slow_turn(session_id, text):
        await gate.wait()
        return TurnResult(text="The left half's answer.", session_id=session_id)

    runtime.provider.turn = slow_turn
    turn = asyncio.create_task(client.post("/turn", json={"text": "left question", "session_id": "halves", "speak": True, "branch_id": left}))
    await asyncio.sleep(0.05)
    cancelled = (await client.post("/cancel", data={"session_id": "halves", "branch_id": right})).json()
    assert cancelled["cancelled"] is True and cancelled["revoked"] == []
    assert live.branches[right].abandoned is True and live.branches[left].abandoned is False
    assert live.abandoned is False
    gate.set()
    body = (await turn).json()
    assert body["answer"] == "The left half's answer."
    await asyncio.sleep(0)
    assert len(calls) == 1                      # spoken: nobody cancelled THIS half

    # Now the left half itself.
    gate.clear()
    turn = asyncio.create_task(client.post("/turn", json={"text": "left again", "session_id": "halves", "speak": True, "branch_id": left}))
    await asyncio.sleep(0.05)
    assert (await client.post("/cancel", data={"session_id": "halves", "branch_id": left})).json()["cancelled"] is True
    gate.set()
    body = (await turn).json()
    assert body["answer"] == "The left half's answer."
    await asyncio.sleep(0)
    assert len(calls) == 1                      # not spoken: this half was cancelled


async def test_a_cancel_without_a_half_still_abandons_the_session(client):
    calls = stub_voice(app)
    runtime = app.state.runtime
    gate = asyncio.Event()

    async def slow_turn(session_id, text):
        runtime.sessions.get_or_create(session_id)
        await gate.wait()
        return TurnResult(text="Too late.", session_id=session_id)

    runtime.provider.turn = slow_turn
    turn = asyncio.create_task(client.post("/turn", json={"text": "long one", "session_id": "whole", "speak": True}))
    await asyncio.sleep(0.05)
    assert (await client.post("/cancel", data={"session_id": "whole"})).json()["cancelled"] is True
    gate.set()
    assert (await turn).json()["answer"] == "Too late."
    await asyncio.sleep(0)
    assert calls == []


# ------------------------------------- a compound answer is one turn, not two


async def test_a_partial_recipe_hands_its_cards_and_its_words_to_the_model_in_one_turn(client):
    """Brief section 16: the workspace is drawn by the Mac and the sentence is written by
    Claude, in ONE answer.

    The recipe used to return its own sentence and arm the branch, so the owner had to ask
    twice — which is what the bench's thirty-five-second compound turn cost him once already.
    Now a `partial` answer carrying a `continuation` does not end the turn: its cards are kept,
    its reads reach the log, and the continuation goes in front of the model.
    """
    from app.fastpath.models import FastAnswer
    from app.providers.base import ToolCall, TurnResult
    from app.surfaces import Freshness, Surface

    runtime = app.state.runtime
    seen: list[str] = []

    async def turn(session_id, text):
        seen.append(text)
        return TurnResult(text="They are waiting on the second hoodie. I have drafted the reply.", session_id=session_id)

    runtime.provider.turn = turn

    drawn = ToolCall(name="shopify_order_detail", args={"order_id": "gid://shopify/Order/1"}, ok=True,
                     result={"order_id": "gid://shopify/Order/1", "order_number": "#1938", "items": []})
    surface = Surface(surface_type="reply_state", ui_type="metric_group",
                      data={"title": "Waiting", "metrics": [{"label": "since", "value": "5h"}]},
                      title="Waiting", subtitle="", freshness=Freshness(source="gmail", complete=True, caveat=""))

    def answered():
        return FastAnswer(
            answer="Mia wrote about 1938 five hours ago.",
            calls=[drawn], drawn=[drawn], surfaces=[surface], partial=True,
            continuation="[The Mac has read the order and the thread. Say in one sentence what "
                         "they are waiting for, then call gmail_draft_reply(thread_id='t1', order_id='o1', body=…).]",
            trace={"ms": 4.0, "critical_path_ms": 3.7},
        )

    import app.routes.turn as turn_mod
    from app.fastpath import RECIPES
    from app.fastpath.intent import Intent, signals_for

    # The routing of this sentence has its own tests (tests/test_graph.py); what is under test
    # here is what happens AFTER a recipe says "partial, and here is what to tell Claude".
    real_fast, real_route = turn_mod._fast, turn_mod._route
    recipe = RECIPES["order_email_reply"]

    def route(text, branch):
        return "FAST", "under test", Intent(family=recipe.intent_family, confidence=1.0, signals=signals_for(text, branch=branch)), recipe

    async def fast(runtime_, session, branch, intent, recipe_, text):
        return answered()

    turn_mod._fast, turn_mod._route = fast, route
    try:
        body = (await client.post("/turn", json={"text": "have they emailed about this order and draft the reply",
                                                 "session_id": "compound"})).json()
    finally:
        turn_mod._fast, turn_mod._route = real_fast, real_route

    # ONE answer, in two halves, in that order: the sentence the Mac READ leads, and the
    # sentence the model WROTE follows it. The order is the point — a fact that was read
    # cannot be displaced by one that was generated, and it is what the owner still hears
    # if the model fails.
    assert body["answer"] == ("Mia wrote about 1938 five hours ago. "
                              "They are waiting on the second hoodie. I have drafted the reply."), body["answer"]
    # The model was asked, and the continuation was in front of it.
    assert seen and "gmail_draft_reply" in seen[-1] and "one sentence" in seen[-1]
    # The recipe's cards survived into that answer, in front of the model's own.
    types = [item["type"] for item in body["ui"]]
    assert "metric_group" in types and "order" in types, types
    # And the turn is recorded as the NORMAL lane that it became, with the recipe's reads on it.
    assert body["lane"] == "NORMAL"
    assert any(call["name"] == "shopify_order_detail" for call in body.get("tool_calls") or []), body.get("tool_calls")


async def test_a_partial_recipe_with_nothing_to_hand_over_still_answers_on_its_own(client):
    """`partial` alone does not mean "ask the model": a recipe that read part of what was asked
    and said so keeps its own answer. Only a continuation moves the turn on."""
    from app.fastpath.models import FastAnswer
    from app.providers.base import TurnResult

    runtime = app.state.runtime
    asked: list[str] = []

    async def turn(session_id, text):
        asked.append(text)
        return TurnResult(text="should not be reached", session_id=session_id)

    runtime.provider.turn = turn
    import app.routes.turn as turn_mod

    real_fast = turn_mod._fast

    async def fast(runtime_, session, branch, intent, recipe, text):
        return FastAnswer(answer="Three orders today; the inbox did not answer.", partial=True, trace={"ms": 2.0})

    turn_mod._fast = fast
    try:
        body = (await client.post("/turn", json={"text": "show me today's orders", "session_id": "partial-only"})).json()
    finally:
        turn_mod._fast = real_fast
    _ = FastAnswer

    assert body["answer"].startswith("Three orders today")
    assert body["lane"] == "FAST"
    assert asked == [], "the model was asked for an answer the recipe had already given"
