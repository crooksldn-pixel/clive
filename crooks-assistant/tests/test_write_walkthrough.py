"""The whole phase-1 write experience, end to end, with nothing mocked but Shopify and the
model: what the owner says, what the Mac does, what Claude is told, what the voice says, what
the card shows, what the tap does.

This is the test that answers "what will actually happen tomorrow". It runs the real routes,
the real gate, the real action engine, the real presentation and the real speakable transform
against a fake store; the only stand-in for Claude is a class that calls the real tool through
the real dispatcher and answers as the tool result instructs it to.
"""

from __future__ import annotations

import httpx
import pytest

from app.actions.ledger import ActionLedger
from app.main import app
from app.providers.base import TurnResult
from app.session.manager import SessionManager
from app.tools import shopify_tools
from app.tools.dispatch import dispatch
from tests.test_actions import ORDER, TOOL, FakeStore

OWNER = "owner@example.com"
PROXIED = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}
QUESTION = "Find order 1930 and add an internal note: customer called about the exchange"
NOTE = "Customer called about the exchange"

# Nothing the assistant says about a prepared change may read as a prohibition, or as a change
# that has already happened.
FORBIDDEN = ("not allowed", "isn't allowed", "aren't allowed", "not permitted", "read-only",
             "cannot", "permission", "added the note", "note added", "i have added", "done it")


class ModelThatAddsANote:
    """Claude, as far as the routes are concerned: it reads the prompt it is given, calls the
    real tool through the real gate, and says what the tool result tells it to say."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.prompts: list[str] = []
        self.tool_results: list[str] = []

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self): return True, "fake"
    async def reset_session(self, session_id): ...
    async def set_system_prompt(self, prompt): ...
    async def interrupt(self, session_id): return True

    async def turn(self, session_id: str, text: str) -> TurnResult:
        self.prompts.append(text)
        session = self.runtime.sessions.get_or_create(session_id)
        calls: list = []
        result = await dispatch(
            TOOL, {"order_id": ORDER, "note": NOTE}, session=session, timeout_s=5, calls=calls
        )
        self.tool_results.append(result)
        return TurnResult(
            text="Order 1930. The note about the exchange is ready — tap the card to apply it.",
            tool_calls=calls, session_id=session_id,
        )


@pytest.fixture()
async def walk(monkeypatch, tmp_path):
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
        store = FakeStore(note="Gift wrap please")
        base_graphql = store.graphql

        async def graphql(query, variables=None):
            # The search the Mac runs ahead of the model, before it has an id to read by.
            if "orders(first:" in query:
                return {"data": {"orders": {"edges": [{"node": store._order()}]}}}
            return await base_graphql(query, variables)

        store.graphql = graphql   # type: ignore[method-assign]
        runtime.shopify = store
        shopify_tools.bind(store)
        runtime.actions.ledger = ActionLedger(tmp_path)
        runtime.sessions = SessionManager()
        runtime.sessions.on_drop.append(runtime.actions.forget_session)
        runtime.provider = ModelThatAddsANote(runtime)
        runtime.settings = runtime.settings.model_copy(
            update={"writes_enabled": True, "allowed_logins": OWNER, "writes_local_owner": False, "tailscale_verify": False}
        )
        app.state.allowed_logins = runtime.allowed_logins

        spoken: list[str] = []

        async def open_stream(text: str):
            spoken.append(text)

            class Stream:
                async def chunks(self):
                    yield b"\xff\xfb\x90\x00mp3"

            return Stream()

        runtime.voice.open_stream = open_stream   # type: ignore[method-assign]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            client.store = store
            client.runtime = runtime
            client.spoken = spoken
            yield client


async def test_the_owner_asks_for_a_note_and_gets_a_card_that_says_only_that_it_is_ready(walk):
    body = (await walk.post("/turn", json={"text": QUESTION, "session_id": "w1", "speak": True}, headers=PROXIED)).json()

    # The Mac looked the order up before the model was asked, and told it so.
    prompt = walk.runtime.provider.prompts[-1]
    assert "already ran shopify_find_order" in prompt and "#1930" in prompt
    assert prompt.startswith("[Now: ")
    assert [c["name"] for c in body["tool_calls"]] == ["shopify_find_order", "shopify_order_note_append"]
    assert all(c["ok"] for c in body["tool_calls"])

    # The model was told the change is prepared, has NOT happened, and carries the words.
    told = walk.runtime.provider.tool_results[-1]
    assert told.startswith("PROPOSED") and "It has NOT happened" in told and NOTE in told
    assert "spoken yes cannot apply it" in told

    # The answer says it is ready to tap, and nothing else.
    answer = body["answer"]
    assert "ready" in answer.lower() and "tap the card" in answer.lower()
    for word in FORBIDDEN:
        assert word not in answer.lower(), word
    assert body["error_kind"] is None and not [i for i in body["ui"] if i["type"] == "error"]

    # The card is amber, pending, tappable from here, with the note in its own words.
    (card,) = [i["data"] for i in body["ui"] if i["type"] == "confirmation"]
    assert card["risk"] == "amber" and card["status"] == "pending"
    assert card["commit"] == {"allowed": True} and card["summary"] == NOTE
    assert card["interaction"]["kind"] == "tap_commit" and card["interaction"]["label"] == "Tap to apply"
    assert card["interaction"]["armed_after_ms"] == 650 and card["interaction"]["footer"] == "nothing happens until you tap"
    assert body["writes"]["allowed"] is True and body["writes"]["caller"] == OWNER
    assert "execution" not in card and "before" not in card

    # Nothing has been sent, the order is untouched, and the ledger says proposed and delivered.
    assert walk.store.mutations == [] and walk.store.note == "Gift wrap please"
    assert [e["event"] for e in walk.runtime.actions.ledger.read()] == ["PROPOSED", "DELIVERED"]

    # The spoken line is the answer, read the way the office says an order number.
    assert walk.spoken == ["Order nineteen thirty. The note about the exchange is ready — tap the card to apply it."]
    # And the turn is over: the screen is not left saying the Mac is still checking Shopify.
    assert (await walk.get("/state/w1")).json()["state"] == "READY"


async def test_saying_yes_out_loud_applies_nothing_and_the_tap_does(walk):
    body = (await walk.post("/turn", json={"text": QUESTION, "session_id": "w2", "speak": True}, headers=PROXIED)).json()
    (card,) = [i["data"] for i in body["ui"] if i["type"] == "confirmation"]
    proposal_id = card["proposal_id"]

    # Out loud: nothing happens, the card stays, and the model is not asked again.
    prompts = len(walk.runtime.provider.prompts)
    said_yes = (await walk.post("/turn", json={"text": "yes", "session_id": "w2", "speak": True}, headers=PROXIED)).json()
    assert said_yes["answer"] == "Nothing happens until you tap the card. It is still waiting on the tablet."
    assert len(walk.runtime.provider.prompts) == prompts
    assert said_yes["revoked"] == [] and walk.store.mutations == []
    assert [i["data"]["status"] for i in said_yes["ui"] if i["type"] == "confirmation"] == ["pending"]

    # The tap: one mutation, proven by a re-read, and only then a success card and an undo.
    tapped = (await walk.post(f"/actions/{proposal_id}/commit", data={"session_id": "w2"}, headers=PROXIED)).json()
    assert tapped["status"] == "verified" and tapped["code"] == "verified"
    assert tapped["spoken"] == "Note added to order 1930."
    assert [i["type"] for i in tapped["ui"]] == ["success", "order"]
    assert tapped["undo"]["proposal_id"] and tapped["undo"]["undo_of"] == proposal_id
    assert len(walk.store.mutations) == 1
    assert walk.store.note == f"Gift wrap please\n{NOTE}"

    # A second tap is not a second change.
    again = (await walk.post(f"/actions/{proposal_id}/commit", data={"session_id": "w2"}, headers=PROXIED)).json()
    assert again["code"] == "already_executed" and len(walk.store.mutations) == 1

    # The ledger tells the whole story, and carries none of the note.
    events = [e["event"] for e in walk.runtime.actions.ledger.read()]
    assert events == ["PROPOSED", "DELIVERED", "EXECUTING", "EXECUTED", "VERIFIED", "PROPOSED"]
    raw = walk.runtime.actions.ledger.path.read_text(encoding="utf-8")
    assert NOTE not in raw and "exchange" not in raw
    assert walk.runtime.actions.ledger.path.stat().st_mode & 0o077 == 0


async def test_a_tablet_that_may_not_apply_changes_is_told_before_it_taps(walk):
    """The other side of the same turn: the card never looks tappable when it is not, the
    voice says which switch is in the way, and nothing reads as a prohibition on the order."""
    walk.runtime.settings = walk.runtime.settings.model_copy(update={"writes_enabled": False})
    body = (await walk.post("/turn", json={"text": QUESTION, "session_id": "w3", "speak": True}, headers=PROXIED)).json()
    (card,) = [i["data"] for i in body["ui"] if i["type"] == "confirmation"]
    assert card["commit"] == {"allowed": False, "code": "writes_disabled",
                              "reason": "Changes are switched off on the server (CROOKS_WRITES_ENABLED)."}
    assert body["answer"].endswith("Changes are switched off on the Mac, so I can't apply that.")
    assert "not allowed" not in body["answer"].lower()
    assert walk.store.mutations == []
    # The model was told before it spoke, so it never offers a tap the Mac would refuse.
    told = walk.runtime.provider.tool_results[-1]
    assert "cannot be applied from where the owner is" in told and "Do NOT tell them to use the card" in told
    # And a spoken yes over a blocked card says the same thing, in its own fixed line.
    said_yes = (await walk.post("/turn", json={"text": "go ahead", "session_id": "w3", "speak": True}, headers=PROXIED)).json()
    assert said_yes["answer"].startswith("That is prepared, but it cannot be applied from this tablet.")
    assert "tap the card" not in said_yes["answer"].lower()
    # And the tap, if it happens anyway, is refused with the same words and no mutation.
    refused = await walk.post(f"/actions/{card['proposal_id']}/commit", data={"session_id": "w3"}, headers=PROXIED)
    assert refused.status_code == 403 and refused.json()["code"] == "writes_disabled"
    assert walk.store.mutations == []
