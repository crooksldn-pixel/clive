"""CLIVE_SCENES on POST /turn (Generative UI V1, 3a of 4).

Off — the default — the response is exactly what it was: nothing is planned and no field is
added. On, the response also carries `scene`, a validated scene with its decision trace, and
every other field is as it would have been. A planner that fails costs the scene, never the
turn. The provider is a double; nothing here reaches a live system.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.main import app
from app.providers.base import ClaudeProvider, TurnResult
from app.routes import turn as turn_module
from tests.test_scene_planner import REPLY_ANSWER, _september_calls

# A sentence that goes to the model rather than to a recipe (see tests/test_routes.py).
QUESTION = "tell me about the shop"
# What every turn response had before scenes, in its order. A turn with the setting off has
# exactly these and no more.
KEYS = [
    "session_id", "turn_id", "test_session_id", "turns", "answer", "question", "error_kind", "lost_thread", "state",
    "last_state", "build", "writes", "revoked", "tool_calls", "transcript", "timings_ms", "ui", "lane", "recipe_id",
    "branch", "branches", "partial", "performance", "workspace",
]


class ScriptedProvider(ClaudeProvider):
    """Answers every turn with the 2026-09-24 reads and a true sentence about them."""

    def __init__(self) -> None:
        self.turns = 0

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def turn(self, session_id: str, text: str) -> TurnResult:
        self.turns += 1
        return TurnResult(text=REPLY_ANSWER, session_id=session_id, tool_calls=_september_calls())

    async def health(self) -> tuple[bool, str]:
        return True, "scripted"

    async def reset_session(self, session_id: str) -> None:
        pass


@pytest.fixture()
async def client(monkeypatch):
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
        app.state.runtime.provider = ScriptedProvider()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


@pytest.fixture()
def scenes(monkeypatch):
    """CLIVE_SCENES as the owner would set it, read afresh; unset (off) until a test sets it."""

    def switch(value: str | None) -> None:
        if value is None:
            monkeypatch.delenv("CLIVE_SCENES", raising=False)
        else:
            monkeypatch.setenv("CLIVE_SCENES", value)
        turn_module.scenes_enabled.cache_clear()

    switch(None)
    yield switch
    turn_module.scenes_enabled.cache_clear()


@pytest.fixture()
def planned(monkeypatch):
    """How many times the scene path was entered."""
    from app.scenes import planner

    calls = []
    real = planner.scene_for_turn

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(planner, "scene_for_turn", counting)
    return calls


async def _turn(client, session_id: str) -> tuple[bytes, dict]:
    response = await client.post("/turn", json={"text": QUESTION, "session_id": session_id})
    assert response.status_code == 200
    return response.content, response.json()


def _volatile(a: dict, b: dict) -> set[str]:
    """The fields that differ between two turns with the same setting: ids, clocks and
    measurements. Everything else must be identical."""
    return {k for k in a if a.get(k) != b.get(k)}


def _stable(body: dict, volatile: set[str]) -> str:
    return json.dumps({k: v for k, v in body.items() if k not in volatile and k != "scene"}, sort_keys=True)


def test_the_setting_is_off_unless_it_is_set(scenes, tmp_path, monkeypatch):
    assert turn_module.scenes_enabled() is False
    scenes("true")
    assert turn_module.scenes_enabled() is True
    scenes("false")
    assert turn_module.scenes_enabled() is False
    # Read as every other setting is: from the .env file config/settings.py reads, too.
    scenes(None)
    env = tmp_path / ".env"
    env.write_text("CROOKS_PORT=8000\nCLIVE_SCENES=on\n")
    monkeypatch.setenv("CROOKS_ENV_FILE", str(env))
    turn_module.scenes_enabled.cache_clear()
    assert turn_module.scenes_enabled() is True


async def test_off_the_response_is_unchanged(client, scenes, planned):
    raw, off = await _turn(client, "off-1")
    assert list(off) == KEYS, "no field added, none moved"
    assert b'"scene"' not in raw
    assert planned == [], "nothing is planned with the setting off"
    assert off["answer"] == REPLY_ANSWER and off["ui"], "the cards are drawn as they always were"
    scenes("false")
    _, again = await _turn(client, "off-2")
    assert list(again) == KEYS and planned == []


async def test_on_the_response_carries_a_valid_scene_and_nothing_else_changes(client, scenes, planned, monkeypatch):
    _, off_a = await _turn(client, "a")
    _, off_b = await _turn(client, "b")
    volatile = _volatile(off_a, off_b)
    assert not volatile & {"answer", "question", "ui", "tool_calls", "error_kind", "lane", "writes"}

    scenes("1")
    _, on = await _turn(client, "c")
    assert list(on) == KEYS + ["scene"]
    assert _stable(on, volatile) == _stable(off_a, volatile), "the cards, the spoken answer and every other field are as they were"
    assert len(planned) == 1

    scene = on["scene"]
    assert set(scene) == {"answer", "elements", "drilldown", "trace"}
    assert scene["answer"]["text"] == on["answer"] == REPLY_ANSWER
    assert scene["elements"] == []
    assert [s["evidence"] for s in scene["drilldown"]["sources"]] == ["ev1", "ev2", "ev3"]
    assert sum(s["found"] for s in scene["drilldown"]["sources"]) == 40
    assert [(e["target"], e["decision"]) for e in scene["trace"]] == [("answer", "kept"), ("drilldown", "kept")]
    dumped = json.dumps(scene)
    assert "@" not in dumped and "example.com" not in dumped

    # The turn log keeps what it always kept: the scene is not written into it.
    logged = []
    monkeypatch.setattr(app.state.runtime.turnlog, "write", lambda record, names=(): logged.append(record))
    await _turn(client, "d")
    assert logged and "scene" not in logged[-1]


async def test_a_planner_exception_never_breaks_a_turn(client, scenes, monkeypatch, caplog):
    from app.scenes import planner

    _, off_a = await _turn(client, "x")
    _, off_b = await _turn(client, "y")
    volatile = _volatile(off_a, off_b)

    def broken(question, answer, calls, context):
        raise RuntimeError(f"could not plan for jo@example.com: {answer}")

    monkeypatch.setattr(planner, "plan_scene", broken)
    scenes("true")
    with caplog.at_level(logging.WARNING, logger="crooks.turn"):
        raw, body = await _turn(client, "z")
    assert list(body) == KEYS and b'"scene"' not in raw
    assert _stable(body, volatile) == _stable(off_a, volatile)
    assert "scene not built: RuntimeError" in caplog.text
    assert "jo@example.com" not in caplog.text and REPLY_ANSWER not in caplog.text, "logged by its kind alone"

    # And a failure anywhere else on the path — here, in the validator — is the same.
    monkeypatch.setattr(planner, "plan_scene", lambda *a: {"answer": {"text": ""}})
    _, body = await _turn(client, "w")
    assert list(body) == KEYS and body["answer"] == REPLY_ANSWER
