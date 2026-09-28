"""Every typed or spoken request is a model turn, with the words exactly as they were said.

The owner, 28 September 2026: "get rid of the fast path actions and inbuilt voice term base
because sometimes even just mentioning a word means nothing gets done but look up order xyz,
and the terms block means certain words such as Clive - is registered as Plaid."

So two things are held here. Nothing matches the words in front of the model — no phrase, no
order number, no intent — and nothing is looked up before it is asked. And nothing between the
microphone and the model tells the recogniser which words to expect or rewrites what it
heard.
"""

from __future__ import annotations

import httpx
import pytest

from app.clients.elevenlabs import ScribeClient
from app.clients.whisper import Transcript, WhisperClient
from app.speech.transcribe import Transcriber
from tests.fake_credentials import elevenlabs_key


@pytest.fixture()
async def turning(monkeypatch):
    """/turn over the real app, with a fake shop and a model that writes down what it is
    handed — and how many shop reads had happened by the moment it was asked."""
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk
    from app.providers.base import TurnResult
    from app.session.manager import SessionManager
    from app.tools import shopify_tools
    from tests.test_context import Store, inbox

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", lambda self: (True, "fake scribe"))
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    store = Store()

    class Provider:
        prompts: list[str] = []
        reads_before: list[int] = []

        async def start(self): pass
        async def stop(self): pass
        async def health(self): return True, "fake"
        async def reset_session(self, session_id): pass
        async def set_system_prompt(self, prompt): pass
        async def interrupt(self, session_id): return True

        async def turn(self, session_id, text):
            Provider.prompts.append(text)
            Provider.reads_before.append(len(store.queries))
            return TurnResult(text="the model answered", session_id=session_id)

    Provider.prompts, Provider.reads_before = [], []
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = Provider()
        runtime.sessions = SessionManager()
        runtime.shopify = store
        shopify_tools.bind(store, threads_for=inbox())
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.runtime, c.provider, c.store = runtime, Provider, store
            yield c


async def ask(client, text: str, session_id: str = "m1") -> dict:
    response = await client.post("/turn", json={"text": text, "session_id": session_id})
    assert response.status_code == 200, response.text
    return response.json()


def said_line(prompt: str) -> str:
    """The owner's own words in what the model was handed: the line after the clock."""
    lines = prompt.split("\n")
    assert lines[0].startswith("[Now: "), prompt[:80]
    return lines[1]


# --------------------------------------------------------------------- the words, typed


async def test_an_order_number_in_passing_goes_to_the_model_with_the_words_intact(turning):
    """The shape the owner described: a number mentioned in a sentence about something else
    used to be looked up (and could be answered) before the model saw the sentence."""
    text = "did you see order 1047 when you looked at the stock?"
    body = await ask(turning, text)

    assert len(turning.provider.prompts) == 1, "the model is asked, exactly once"
    prompt = turning.provider.prompts[0]
    assert said_line(prompt) == text, "the model gets the sentence exactly as it was said"
    assert "shopify_find_order" not in prompt and "CLIVE already ran" not in prompt
    # Nothing was looked up first: the shop had not been asked anything when the model was.
    assert turning.provider.reads_before == [0]
    assert turning.store.queries == []
    assert body["answer"] == "the model answered"
    assert body["question"] == text
    assert body["tool_calls"] == [], "no lookup rode along in front of the model's own calls"
    assert body["lane"] == "NORMAL" and "recipe_id" not in body
    performance = body["performance"]
    assert performance["model_calls"] == 1 and performance["lane"] == "NORMAL"
    assert "fast_path_hit" not in performance and "recipe_id" not in performance
    assert performance["model_input_chars"] > 0 and performance["tool_schema_bytes"] > 0


@pytest.mark.parametrize("text", [
    "order 1938",
    "show me order 1938",
    "next",
    "go back",
    "stop",
    "hi",
    "what can you do?",
    "what more can you do now?",
    "show me today's orders",
    "which customers need replying to?",
    "open the inbox",
    "are you working right now?",
    "log that the split button is broken",
    "how many abandoned checkouts this week",
    "create a 15% discount code called TEST15",
])
async def test_sentences_the_fast_lane_used_to_take_are_all_model_turns(turning, text):
    body = await ask(turning, text, session_id="m2")
    assert [said_line(p) for p in turning.provider.prompts] == [text]
    assert turning.provider.reads_before == [0]
    assert body["answer"] == "the model answered" and body["lane"] == "NORMAL"


async def test_words_said_after_a_tapped_control_go_to_the_model_with_the_control_beside_them(turning):
    """A tapped Add a note binds the next sentence to its order. Whether the words are the
    note or a new question is the model's to judge; the owner's words are never rewritten."""
    await ask(turning, "hello", session_id="m3")
    branch = turning.runtime.sessions.get("m3").branch()
    branch.bind_voice("order.add_note", kind="order", ref="gid://shopify/Order/1938", label="#1938",
                      prompt="Add a note", phrase="Adding a note to #1938")
    body = await ask(turning, "how many orders today", session_id="m3")
    prompt = turning.provider.prompts[-1]
    assert said_line(prompt) == "how many orders today"
    assert "order.add_note" in prompt and "#1938" in prompt
    assert "if they ask for something else, do that instead" in prompt
    assert body["question"] == "how many orders today", "the tablet shows his words, not the note"


async def test_no_speech_keeps_the_context_and_says_so_briefly(turning):
    await ask(turning, "hello", session_id="m4")
    branch = turning.runtime.sessions.get("m4").branch()
    branch.visit("order", "gid://shopify/Order/1938", "#1938")
    before = branch.entity
    body = await ask(turning, "   ", session_id="m4")
    assert body["error_kind"] == "empty" and body["answer"] == "I did not catch that."
    assert turning.runtime.sessions.get("m4").branch().entity == before, "the screen keeps its place"
    assert len(turning.provider.prompts) == 1, "nothing was put to the model for nothing said"


# -------------------------------------------------------------------- the words, spoken


class NoWhisper(WhisperClient):
    def __init__(self) -> None:
        super().__init__("http://fake")

    async def transcribe(self, wav: bytes) -> Transcript:
        raise AssertionError("Scribe answered; the fallback is not asked")


async def test_what_scribe_heard_is_exactly_what_the_model_receives(turning):
    pytest.importorskip("av")
    from tests.test_decode import tone_pcm, webm_opus

    heard = "Clive, show me today's orders"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"text": heard, "language_code": "eng"})

    scribe = ScribeClient(cooldown_s=0.0)
    scribe._key = elevenlabs_key("every-turn")
    scribe._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    turning.runtime.transcriber = Transcriber(NoWhisper(), scribe=scribe, primary="scribe")

    response = await turning.post(
        "/turn", data={"session_id": "m5"},
        files={"audio": ("clip.webm", webm_opus(tone_pcm(1.0)), "audio/webm")},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    # The request Scribe received carried the audio and nothing about which words to expect.
    (sent,) = requests
    form = sent.read().decode("utf-8", "replace")
    assert sent.url.path.endswith("/speech-to-text")
    assert 'name="file"; filename="audio.wav"' in form
    assert "keyterms" not in form
    assert "Plaid" not in form

    # And the words reached the model exactly as heard: "Clive" is still Clive.
    (prompt,) = turning.provider.prompts
    assert said_line(prompt) == heard
    assert body["question"] == heard
    assert body["transcript"]["text"] == heard and body["transcript"]["raw_text"] == heard
    assert "matches" not in body["transcript"]
    await scribe.aclose()
