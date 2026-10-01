"""A team member's turn (the review of the team build, PR #73, 1 October): it never speaks with the
owner's voice allowance, never hears an upload, never falls back to the owner's assistant, and is
never cut off by somebody else's turn when their assistant is replaced while it is answering.

Through the real app and its door, as tests/test_team.py does; the owner's turns are unchanged.
"""

from __future__ import annotations

import asyncio

import pytest

from app.providers.base import TurnResult
from app.runtime import NoStaffAssistant
from app.tools import authority
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    PROXIED,
    FakeProvider,
    client,
)
from tests.test_team import (  # noqa: F401 - `team` is a fixture
    AS_MIA,
    MIA,
    StaffProvider,
    let_mia_in,
    team,
)


@pytest.fixture
def voice_asked(team, monkeypatch):  # noqa: F811 - fixtures imported from the suite they belong to
    """Every text-to-speech request the turn route makes, recorded and never sent."""
    asked: list = []
    monkeypatch.setattr(team.runtime.voice, "prefetch", lambda text, **kw: asked.append(text))

    async def open_stream(text):
        asked.append(text)
        raise AssertionError("no test may spend a credit")

    monkeypatch.setattr(team.runtime.voice, "open_stream", open_stream)
    return asked


async def test_a_members_turn_never_starts_the_voice_and_the_owners_still_does(team, voice_asked, monkeypatch):  # noqa: F811
    let_mia_in()
    asked: list = []
    monkeypatch.setattr(team.runtime, "staff_provider_factory", lambda person: StaffProvider(asked))
    theirs = await team.post("/turn", json={"text": "What's mine today?", "session_id": "m1", "speak": True}, headers=AS_MIA)
    assert theirs.status_code == 200 and theirs.json()["answer"] == "Your list has one order to pack."
    assert voice_asked == [] and len(asked) == 1
    owners = await team.post("/turn", json={"text": "Hello", "session_id": "o1", "speak": True}, headers=PROXIED)
    assert owners.status_code == 200 and owners.json()["answer"] == "fake answer"
    assert voice_asked == ["fake answer"]                                                   # his still speaks


async def test_a_members_recording_is_refused_and_never_heard(team, monkeypatch):  # noqa: F811
    let_mia_in()
    heard: list = []

    async def from_blob(blob, **kw):
        heard.append(blob)
        raise AssertionError("a team member's recording must never be transcribed")

    monkeypatch.setattr(team.runtime.transcriber, "from_blob", from_blob)
    monkeypatch.setattr(team.runtime, "staff_provider_factory", lambda person: StaffProvider([]))
    refused = await team.post("/turn", data={"session_id": "m2", "speak": "true"},
                              files={"audio": ("q.webm", b"\x1aE\xdf\xa3 not much", "audio/webm")}, headers=AS_MIA)
    assert refused.status_code == 403
    assert refused.json()["code"] == "team_types" and "team types to CLIVE" in refused.json()["detail"]
    assert heard == []


async def test_with_no_way_to_make_their_assistant_a_member_is_refused_not_given_the_owners(team, monkeypatch):  # noqa: F811
    let_mia_in()
    runtime = team.runtime
    monkeypatch.setattr(runtime, "staff_provider_factory", None)
    owners_asked: list = []

    class Owners(FakeProvider):
        async def turn(self, session_id, text):
            owners_asked.append(text)
            return TurnResult(text="the owner's answer", session_id=session_id)

    runtime.provider = Owners()
    with pytest.raises(NoStaffAssistant):
        runtime.provider_for(authority.for_staff("mia", MIA))
    assert runtime.provider_for(authority.for_owner("owner@example.com")) is runtime.provider
    refused = await team.post("/turn", json={"text": "What did George say?", "session_id": "m3"}, headers=AS_MIA)
    assert refused.status_code == 403 and refused.json()["code"] == "no_staff_assistant"
    assert "the owner's answer" not in refused.text and owners_asked == []
    owners = await team.post("/turn", json={"text": "Hello", "session_id": "o3"}, headers=PROXIED)
    assert owners.json()["answer"] == "the owner's answer"                                  # his own, unchanged


class HeldProvider(FakeProvider):
    """A team member's assistant whose turn runs until the test lets it finish."""

    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.stopped = False

    async def stop(self):
        self.stopped = True

    async def turn(self, session_id, text):
        self.entered.set()
        await self.release.wait()
        return TurnResult(text="Packed and labelled.", session_id=session_id)


async def test_a_retired_assistant_is_stopped_only_once_its_turn_ends(team, monkeypatch):  # noqa: F811
    from app.people.store import people

    let_mia_in()
    runtime = team.runtime
    first = HeldProvider()
    made = [first]
    monkeypatch.setattr(runtime, "staff_provider_factory", lambda person: made.pop(0) if made else StaffProvider([]))
    running = asyncio.create_task(team.post("/turn", json={"text": "Pack #1930", "session_id": "m4"}, headers=AS_MIA))
    await asyncio.wait_for(first.entered.wait(), 5)
    people.note({"name": "Mia", "role": "packing and the stock counts"})                     # her card changes mid-turn
    assert runtime.staff_provider("mia") is not first and runtime.retired_providers == [first]
    owners = await team.post("/turn", json={"text": "Hello", "session_id": "o4"}, headers=PROXIED)
    assert owners.status_code == 200 and owners.json()["answer"] == "fake answer"
    assert not first.stopped and runtime.retired_providers == [first]                       # not cut off by his turn
    first.release.set()
    answer = await asyncio.wait_for(running, 5)
    assert answer.status_code == 200 and answer.json()["answer"] == "Packed and labelled."
    assert first.stopped and runtime.retired_providers == []                                # stopped once it ended
    assert runtime.turns_in_flight == {}
