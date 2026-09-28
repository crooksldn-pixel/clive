"""What the owner's words put on the glass, through /turn, now that every sentence is the
model's (the 2026-09-28 deploy review, round 9, I-tests5 I-02).

tests/test_summaries.py holds the summary surfaces to their shape by calling the read the way
the model calls it. What it no longer does, since the word-matching lane went, is send the
owner's sentence through the turn and look at the whole screen that comes back — which is
where D-4 happened: "has anyone bought today that has bought before" answered, correctly, with
the number one, over seven full customer profiles. This drives the route: the sentence, the
model's read, and every card the turn returns.
"""

from __future__ import annotations

import httpx
import pytest

from app.analytics.cache import OrderCache
from app.main import app
from app.session.manager import SessionManager
from app.tools import analytics_tools
from tests.test_summaries import NODES, NOW, PROFILE_KINDS, RETURNING_ID, FixedDatetime, Store
from tests.test_turn_boundary import OWNER, PROXIED, Scripted, reads


@pytest.fixture()
async def summarising(monkeypatch):
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
        store = Store(NODES)
        analytics_tools.bind(OrderCache(lambda: store, clock=lambda: NOW.timestamp()))
        monkeypatch.setattr(analytics_tools, "datetime", FixedDatetime)
        runtime.sessions = SessionManager()
        runtime.provider = Scripted(runtime)
        runtime.settings = runtime.settings.model_copy(
            update={"writes_enabled": True, "allowed_logins": OWNER, "writes_local_owner": False, "tailscale_verify": False}
        )
        app.state.allowed_logins = runtime.allowed_logins
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                client.runtime, client.model = runtime, runtime.provider
                yield client
        finally:
            analytics_tools.bind(None)


async def test_the_returning_customers_question_draws_one_compact_surface_and_no_profiles(summarising):
    """The owner's sentence through /turn, the model's one summary read, and the WHOLE screen:
    exactly one summary card, carrying the one returning customer as a row, and not one
    customer, order or product profile — whatever the read touched to find him."""
    said = "Has anyone bought today that has bought before, a returning customer?"
    summarising.model.steps = [reads(("commerce_summary", {"task": "returning_customers", "period": "today", "limit": 12}))]
    response = await summarising.post("/turn", json={"text": said, "session_id": "returning"}, headers=PROXIED)
    assert response.status_code == 200, response.text
    body = response.json()

    assert summarising.model.prompts[-1].split("\n")[1] == said
    (call,) = body["tool_calls"]
    assert call["name"] == "commerce_summary" and call["ok"] is True, call
    cards = [item for item in body["ui"] if item["type"] != "context_stack"]
    assert [item["type"] for item in cards] == ["summary_list"], [item["type"] for item in cards]
    assert not [item for item in body["ui"] if item["type"] in PROFILE_KINDS or item["type"].endswith("_workspace")]
    (summary,) = cards
    assert summary["data"]["count"] == 1 and len(summary["data"]["rows"]) == 1
    (row,) = summary["data"]["rows"]
    assert row["label"] == "Cy Cole" and row["sub"] == "Order #1962"
    # The row is a way to the person, not the person drawn: a tap opens him (§18).
    assert (row["kind"], row["ref"], row["command"]) == ("customer", RETURNING_ID, "open.entity")
