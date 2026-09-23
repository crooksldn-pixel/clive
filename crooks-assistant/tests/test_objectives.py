"""Objective V0: durable, honest about state, and the owner's decisions stay the owner's."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.objectives import store as store_module
from app.objectives.store import ObjectiveError, ObjectiveStore
from app.tools import gate


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


def test_an_objective_survives_a_fresh_store(tmp_path, s):
    obj = s.create(title="Son to UK", request="Get my son here for the baptism on 13 October", deadline="2026-10-13")
    s.add_fact(obj.id, "He is in Ethiopia", source="owner")
    s.add_unknown(obj.id, "Which passport he holds")
    again = ObjectiveStore(tmp_path / "objectives").get(obj.id)  # as after a restart
    assert again.request.startswith("Get my son") and again.deadline == "2026-10-13"
    assert again.facts[0]["source"] == "owner" and again.open_("unknowns")[0]["text"] == "Which passport he holds"
    assert [e["kind"] for e in again.events] == ["created", "fact", "unknown"]


def test_the_ladder_is_enforced_and_authorisation_is_the_owners(s):
    obj = s.create(title="t", request="r")
    s.propose(obj.id, "Research visa requirements", needs_owner=False)
    s.propose(obj.id, "Book a flight", needs_owner=True)
    research, flight = s.get(obj.id).items
    s.advance(obj.id, research["id"], "started")
    s.advance(obj.id, research["id"], "completed")
    with pytest.raises(ObjectiveError, match="evidence"):
        s.advance(obj.id, research["id"], "verified")
    with pytest.raises(ObjectiveError, match="approval"):
        s.advance(obj.id, flight["id"], "started")
    with pytest.raises(ObjectiveError, match="Only the owner"):
        s.advance(obj.id, flight["id"], "authorised")
    s.authorise(obj.id, flight["id"])
    s.advance(obj.id, flight["id"], "started")
    states = {i["text"]: i["state"] for i in s.get(obj.id).items}
    assert states == {"Research visa requirements": "completed", "Book a flight": "started"}
    with pytest.raises(ObjectiveError, match="Only the owner closes"):
        s.set_status(obj.id, "done")


def test_blockers_and_questions_open_and_resolve(s):
    obj = s.create(title="t", request="r")
    s.add_blocker(obj.id, "No flight-booking capability", kind="missing_capability")
    assert s.get(obj.id).status == "blocked"
    s.ask_owner(obj.id, "Where exactly is he now?")
    question = s.get(obj.id).open_("attention")[0]
    s.resolve(obj.id, question["id"], note="Bahir Dar", by="owner")
    assert s.get(obj.id).open_("attention") == [] and s.get(obj.id).summary()["needs_you"] == []


def test_regression_resolved_questions_and_open_blocker_show_blocked_not_needs_you(s):
    """George's dogfood defect: every question answered, a capability blocker still open, but the
    stored status was stale at 'waiting' — the headline must read 'blocked', never 'needs_you'."""
    obj = s.create(title="t", request="r")
    s.ask_owner(obj.id, "Which date can he leave?")
    question = s.get(obj.id).open_("attention")[0]
    s.resolve(obj.id, question["id"], note="The 5th", by="owner")
    s.add_blocker(obj.id, "No flight-booking capability", kind="missing_capability")
    s.set_status(obj.id, "waiting", by="owner")
    summary = s.get(obj.id).summary()
    assert summary["status"] == "waiting"
    assert summary["attention"] == "blocked"
    assert "flight-booking" in summary["attention_reason"]


def test_attention_precedence_idle_doing_blocked(s):
    idle = s.create(title="idle", request="r")
    assert idle.summary()["attention"] == "idle"

    doing = s.create(title="doing", request="r")
    s.propose(doing.id, "Draft the itinerary", needs_owner=False)
    item = s.get(doing.id).items[0]
    s.advance(doing.id, item["id"], "started")
    summary = s.get(doing.id).summary()
    assert summary["attention"] == "doing"
    assert "Draft the itinerary" in summary["attention_reason"]

    blocked = s.create(title="blocked", request="r")
    s.add_blocker(blocked.id, "No flight-booking capability", kind="missing_capability")
    summary = s.get(blocked.id).summary()
    assert summary["attention"] == "blocked"
    assert "flight-booking" in summary["attention_reason"]


def test_attention_needs_you_from_a_question_or_an_awaiting_approval(s):
    question = s.create(title="question", request="r")
    s.ask_owner(question.id, "Which date can he leave?")
    summary = s.get(question.id).summary()
    assert summary["attention"] == "needs_you"
    assert "Which date" in summary["attention_reason"]

    approval = s.create(title="approval", request="r")
    s.propose(approval.id, "Book a flight", needs_owner=True)
    summary = s.get(approval.id).summary()
    assert summary["attention"] == "needs_you"
    assert "Book a flight" in summary["attention_reason"]

    # needs_you outranks an open blocker
    both = s.create(title="both", request="r")
    s.add_blocker(both.id, "No flight-booking capability", kind="missing_capability")
    s.ask_owner(both.id, "Which date can he leave?")
    assert s.get(both.id).summary()["attention"] == "needs_you"


def test_owner_set_done_and_dropped_stay_as_set(s):
    obj = s.create(title="t", request="r")
    s.propose(obj.id, "Book a flight", needs_owner=True)  # would otherwise be needs_you
    s.set_status(obj.id, "done", by="owner")
    assert s.get(obj.id).summary()["attention"] == "done"

    obj2 = s.create(title="t2", request="r")
    s.add_blocker(obj2.id, "No flight-booking capability", kind="missing_capability")  # would be blocked
    s.set_status(obj2.id, "dropped", by="owner")
    assert s.get(obj2.id).summary()["attention"] == "dropped"


def test_the_tools_are_local_reads_to_the_gate():
    for name in ("objective_open", "objective_list", "objective_show", "objective_note"):
        decision = gate.classify(name, {})
        assert decision.tier is gate.Tier.GREEN and decision.disposition is gate.Disposition.EXECUTE_NOW, name


def test_the_model_tool_cannot_authorise_or_close(s):
    from app.objectives import tools
    from app.tools.registry import ToolError

    obj = s.create(title="t", request="r")
    s.propose(obj.id, "Submit the passport application", needs_owner=True)
    item = s.get(obj.id).items[0]
    with pytest.raises(ToolError):
        asyncio.run(tools.objective_note(obj.id, "advance", item_id=item["id"], state="authorised"))
    with pytest.raises(ToolError):
        asyncio.run(tools.objective_note(obj.id, "advance", item_id=item["id"], state="started"))
    with pytest.raises(ToolError):
        asyncio.run(tools.objective_note(obj.id, "status", status="done"))
    assert s.get(obj.id).items[0]["state"] == "proposed"


def test_the_owners_routes_create_answer_and_authorise(s, monkeypatch):
    from fastapi import FastAPI

    from app.routes import objectives

    app = FastAPI()
    app.include_router(objectives.router)
    client = TestClient(app)
    made = client.post("/objectives", json={"request": "Organise the baptism travel", "deadline": "2026-10-13"}).json()
    s.propose(made["id"], "Buy the ticket", needs_owner=True)
    s.ask_owner(made["id"], "Which date can he leave?")
    obj = s.get(made["id"])
    assert client.post(f"/objectives/{obj.id}/items/{obj.items[0]['id']}/authorise").json()["items"][0]["state"] == "authorised"
    answered = client.post(f"/objectives/{obj.id}/answer/{obj.attention[0]['id']}", json={"text": "From the 5th"}).json()
    assert answered["summary"]["needs_you"] == [] and answered["facts"][-1] == {**answered["facts"][-1], "source": "owner"}
    listing = client.get("/objectives").json()
    assert listing["objectives"][0]["title"] == "Organise the baptism travel" and listing["needs_you"] == 0
    assert client.get("/objectives/obj_00000000").status_code == 404
    assert client.post(f"/objectives/{obj.id}/status", json={"status": "done"}).json()["status"] == "done"
