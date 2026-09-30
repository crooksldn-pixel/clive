"""Closing an objective out, complete or removed, through a tool call: it leaves the live list,
and every word of it is kept and can be read again by its id or found among the closed ones."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.objectives import store as store_module
from app.objectives import tools
from app.objectives.store import ObjectiveStore
from app.tools import gate
from app.tools.registry import ToolError


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


def _run(coro):
    return asyncio.run(coro)


def _listed(**kwargs) -> list[str]:
    return [o["id"] for o in _run(tools.objective_list(**kwargs))["objectives"]]


def _full_objective(s) -> str:
    """An objective with something of every kind on it: facts with sources, an unknown, a blocker,
    a question, an owner's note, work items and a design (people, tasks)."""
    obj = s.create(title="Son to UK", request="Get my son here for the baptism on 13 October",
                   deadline="2026-10-13", people=["Rosa (sister)"])
    s.add_fact(obj.id, "He is in Ethiopia", source="owner")
    s.add_fact(obj.id, "A visitor visa takes about three weeks", source="general knowledge, not verified live")
    s.add_unknown(obj.id, "Which passport he holds")
    s.add_blocker(obj.id, "No flight-booking capability", kind="missing_capability", capability="flight booking")
    s.ask_owner(obj.id, "Where exactly is he now?")
    s.owner_note(obj.id, "The church is St Mary's in Camberwell")
    s.propose(obj.id, "Research visa requirements", needs_owner=False)
    s.propose(obj.id, "Book a flight", needs_owner=True)
    s.task(obj.id, who="Rosa", text="Find his birth certificate", due="2026-10-01")
    s.progress(obj.id, "Visa research under way")
    return obj.id


def test_a_tool_call_closes_an_objective_as_complete_and_it_leaves_the_live_list(s):
    oid = _full_objective(s)
    other = s.create(title="Autumn drop", request="Get the autumn drop out").id
    assert set(_listed()) == {oid, other}

    answer = _run(tools.objective_note(oid, "close", status="done", text="That's all sorted now, close it off"))

    assert answer["recorded"] == "close" and answer["objective"]["status"] == "done"
    assert _listed() == [other], "a closed objective is not in the live list"
    assert s.get(oid).status == "done"
    assert [o.id for o in s.live()] == [other]


def test_a_tool_call_removes_an_objective_and_it_leaves_the_live_list(s):
    oid = _full_objective(s)

    _run(tools.objective_note(oid, "close", status="dropped", text="Forget that one, take it off the list"))

    assert _listed() == []
    assert s.get(oid).status == "dropped"


def test_nothing_of_a_closed_objective_is_deleted_and_it_reads_in_full_by_its_id(s, tmp_path):
    oid = _full_objective(s)
    before = s.get(oid).to_dict()

    _run(tools.objective_note(oid, "close", status="done", text="Done, he landed yesterday"))

    # As after a restart: a fresh store reads the files on the disk.
    after = ObjectiveStore(tmp_path / "objectives").get(oid).to_dict()
    for key in ("title", "request", "deadline", "facts", "unknowns", "blockers", "attention", "items",
                "tasks", "people", "purpose", "done_when", "kind", "engineering", "created_at"):
        assert after[key] == before[key], key
    # The history is the same history, with the close added at its end.
    assert after["events"][:len(before["events"])] == before["events"]
    closing = after["events"][len(before["events"]):]
    assert len(closing) == 1 and closing[0]["kind"] == "status"
    assert closing[0]["text"].startswith("done") and "Done, he landed yesterday" in closing[0]["text"]
    assert (tmp_path / "objectives" / f"{oid}.json").exists()
    assert (tmp_path / "objectives" / "design" / f"{oid}.json").exists()

    shown = _run(tools.objective_show(oid))
    assert shown["id"] == oid and shown["status"] == "done"
    assert [f["text"] for f in shown["facts"]] == ["He is in Ethiopia", "A visitor visa takes about three weeks",
                                                   "The church is St Mary's in Camberwell"]
    assert shown["facts"][0]["source"] == "owner"
    assert shown["unknowns"][0]["text"] == "Which passport he holds"
    assert shown["blockers"][0]["text"] == "No flight-booking capability"
    assert shown["attention"][0]["text"] == "Where exactly is he now?"
    assert {i["text"] for i in shown["items"]} == {"Research visa requirements", "Book a flight"}
    assert shown["tasks"][0]["who"] == "Rosa" and shown["people"][0]["name"] == "Rosa"
    assert shown["events"][-1]["text"].endswith("Done, he landed yesterday")


def test_closed_objectives_are_listed_and_found_by_their_words(s):
    oid = _full_objective(s)
    removed = s.create(title="Pop-up in Soho", request="Find a pop-up space in Soho for December").id
    s.add_fact(removed, "Carnaby Street units start at 4,000 a week", source="https://example.com/units")
    live = s.create(title="Autumn drop", request="Get the autumn drop out").id
    _run(tools.objective_note(oid, "close", status="done", text="All done"))
    _run(tools.objective_note(removed, "close", status="dropped", text="We're not doing the pop-up"))

    assert _listed() == [live]
    assert set(_listed(closed=True)) == {oid, removed}
    # Found by any words on the record: a fact, a note, the history — in any case.
    assert _listed(closed=True, query="ethiopia") == [oid]
    assert _listed(closed=True, query="St Mary's Camberwell") == [oid]
    assert _listed(closed=True, query="carnaby") == [removed]
    assert _listed(closed=True, query="not doing the pop-up") == [removed]
    assert _listed(closed=True, query="autumn") == [], "a live objective is not among the closed ones"
    assert _listed(query="autumn") == [live]
    assert _listed(closed=True, query="nothing like this") == []
    listed = {o["id"]: o for o in _run(tools.objective_list(closed=True))["objectives"]}
    assert listed[oid]["status"] == "done" and listed[removed]["status"] == "dropped"
    assert listed[oid]["facts"] == 3


def test_an_objective_the_owner_closed_on_the_screen_is_among_the_closed_ones_too(s):
    oid = s.create(title="t", request="r").id
    s.set_status(oid, "done", by="owner")
    assert _listed() == [] and _listed(closed=True) == [oid]


def test_closing_needs_the_owners_words_and_a_closing_status(s):
    oid = _full_objective(s)
    events = len(s.get(oid).events)
    with pytest.raises(ToolError, match="owner"):
        _run(tools.objective_note(oid, "close", status="done"))
    with pytest.raises(ToolError, match="owner"):
        _run(tools.objective_note(oid, "close", status="done", text="   "))
    with pytest.raises(ToolError, match="done"):
        _run(tools.objective_note(oid, "close", status="active", text="close it"))
    with pytest.raises(ToolError):
        _run(tools.objective_note(oid, "close", text="close it"))
    # The status action still cannot close: the owner's words are what closing needs.
    with pytest.raises(ToolError, match="Only the owner"):
        _run(tools.objective_note(oid, "status", status="done", text="close it"))
    assert _listed() == [oid] and len(s.get(oid).events) == events, "a refused close changes nothing"
    with pytest.raises(ToolError):
        _run(tools.objective_note("obj_00000000", "close", status="done", text="close it"))


def test_a_closed_objective_is_not_closed_twice_and_can_be_put_back(s):
    oid = _full_objective(s)
    _run(tools.objective_note(oid, "close", status="dropped", text="Drop it"))
    with pytest.raises(ToolError, match="already closed"):
        _run(tools.objective_note(oid, "close", status="done", text="Close it"))
    assert s.get(oid).status == "dropped"

    _run(tools.objective_note(oid, "status", status="active", text="Actually we need it again"))
    assert _listed() == [oid] and _listed(closed=True) == []
    assert len(s.get(oid).facts) == 3


def test_the_close_is_recorded_as_made_at_the_owners_word_not_as_the_owners_tap(s):
    oid = s.create(title="t", request="r").id
    s.add_blocker(oid, "No flight-booking capability", kind="missing_capability")
    _run(tools.objective_note(oid, "close", status="done", text="It's finished"))
    obj = s.get(oid)
    assert obj.status == "done" and obj.status_set_by == "clive"
    assert obj.events[-1]["by"] == "clive" and "as the owner asked: It's finished" in obj.events[-1]["text"]


def test_the_closed_record_reads_as_it_was_written(s, tmp_path):
    oid = _full_objective(s)
    _run(tools.objective_note(oid, "close", status="done", text="Done"))
    record = json.loads((tmp_path / "objectives" / f"{oid}.json").read_text(encoding="utf-8"))
    assert record["status"] == "done" and len(record["facts"]) == 3 and record["unknowns"] and record["blockers"]


def test_listing_and_closing_stay_local_reads_to_the_gate():
    for name, args in (("objective_list", {"closed": True, "query": "visa"}),
                       ("objective_note", {"objective_id": "obj_12345678", "action": "close",
                                           "status": "done", "text": "close it"})):
        decision = gate.classify(name, args)
        assert decision.tier is gate.Tier.GREEN and decision.disposition is gate.Disposition.EXECUTE_NOW, name
