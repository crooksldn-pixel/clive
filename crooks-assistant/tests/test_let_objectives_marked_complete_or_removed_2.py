"""An objective closed out, complete or removed, by a tool call: it leaves the live list and
nothing on it is deleted. Its facts, notes, blockers and history are read back by its id, and it
is found again among the closed, by listing them or by searching them."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.objectives import store as store_module
from app.objectives import tools
from app.objectives.store import ObjectiveError, ObjectiveStore
from app.tools import authority, gate
from app.tools.registry import ToolError

OWNER_SAID = "That trip is done, take it off the list"


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


def run(coro):
    return asyncio.run(coro)


def _full_record(s: ObjectiveStore) -> str:
    """An objective with something of every kind on it: facts (one the owner's note), an unknown,
    a blocker, a question, a work item, a task and a history."""
    obj = s.create(title="Son to UK", request="Get my son here for the baptism on 13 October", deadline="2026-10-13",
                   purpose="The baptism")
    s.add_fact(obj.id, "He is in Ethiopia", source="owner")
    s.owner_note(obj.id, "His passport number ends 4471")
    s.add_unknown(obj.id, "Which passport he holds")
    s.add_blocker(obj.id, "No flight-booking capability", kind="missing_capability")
    s.ask_owner(obj.id, "Where exactly is he now?")
    s.propose(obj.id, "Research visa requirements", needs_owner=False)
    s.progress(obj.id, "Checked the embassy's opening hours")
    return obj.id


def _live_ids() -> list[str]:
    return [o["id"] for o in run(tools.objective_list())["objectives"]]


def test_a_tool_call_marks_an_objective_complete_and_it_leaves_the_live_list(s):
    kept = s.create(title="AW drop", request="Get the AW drop out").id
    closing = _full_record(s)
    assert set(_live_ids()) == {kept, closing}

    noted = run(tools.objective_note(closing, "complete", text=OWNER_SAID))
    assert noted["recorded"] == "complete" and noted["objective"]["status"] == "done"
    assert _live_ids() == [kept]
    assert [o.id for o in s.live()] == [kept]
    got = s.get(closing)
    assert got.status == "done" and got.events[-1]["kind"] == "status"
    assert OWNER_SAID in got.events[-1]["text"] and "complete" in got.events[-1]["text"]


def test_a_tool_call_marks_an_objective_removed_and_it_leaves_the_live_list(s):
    closing = _full_record(s)
    noted = run(tools.objective_note(closing, "remove", text="Forget the trip"))
    assert noted["objective"]["status"] == "dropped"
    assert _live_ids() == []
    assert "removed" in s.get(closing).events[-1]["text"]


def test_through_the_real_dispatcher_as_the_owner(s):
    """The tool call the model makes: a local read to the gate, run at once, and the objective
    it names is off the live list afterwards."""
    from app.session.models import Session
    from app.tools.dispatch import dispatch

    closing = _full_record(s)
    args = {"objective_id": closing, "action": "complete", "text": OWNER_SAID}
    decision = gate.classify("objective_note", args)
    assert decision.tier is gate.Tier.GREEN and decision.disposition is gate.Disposition.EXECUTE_NOW
    session = Session(session_id="close-objective")
    with authority.acting_as(authority.for_owner("owner@example.com")):
        said = run(dispatch("objective_note", args, session=session, timeout_s=5))
        assert not said.startswith(("REFUSED", "NOT YET", "ERROR")), said
        listed = run(dispatch("objective_list", {}, session=session, timeout_s=5))
        assert closing not in listed
        closed = run(dispatch("objective_list", {"closed": True}, session=session, timeout_s=5))
        assert closing in closed
    assert s.get(closing).status == "done"


def test_the_whole_record_is_kept_and_read_back_by_its_id(s, tmp_path):
    closing = _full_record(s)
    before = s.get(closing).to_dict()
    files_before = sorted(p.relative_to(s.root) for p in s.root.rglob("*") if p.is_file())
    run(tools.objective_note(closing, "remove", text="Forget the trip"))

    after = s.get(closing).to_dict()
    for key in ("facts", "unknowns", "blockers", "attention", "items", "tasks", "stages", "people", "engineering",
                "title", "request", "deadline", "purpose", "created_at", "kind"):
        assert after[key] == before[key], key
    assert after["events"][:len(before["events"])] == before["events"], "the history is only added to"
    assert len(after["events"]) == len(before["events"]) + 1
    assert [f["text"] for f in after["facts"]] == ["He is in Ethiopia", "His passport number ends 4471"]
    assert after["blockers"][0]["resolved_at"] is None and after["attention"][0]["resolved_at"] is None
    # Nothing on the disk is gone: the record and its design are where they were.
    files_after = sorted(p.relative_to(s.root) for p in s.root.rglob("*") if p.is_file())
    assert files_after == files_before and (s.root / f"{closing}.json").exists()

    shown = run(tools.objective_show(closing))
    assert shown["status"] == "dropped"
    assert [f["text"] for f in shown["facts"]] == ["He is in Ethiopia", "His passport number ends 4471"]
    assert shown["blockers"][0]["text"] == "No flight-booking capability"
    assert shown["unknowns"][0]["text"] == "Which passport he holds"
    assert "Forget the trip" in shown["events"][-1]["text"]

    # And after a restart, still closed and still whole.
    again = ObjectiveStore(tmp_path / "objectives")
    assert again.get(closing).to_dict()["facts"] == before["facts"] and again.get(closing).status == "dropped"
    assert again.live() == [] and [o.id for o in again.closed()] == [closing]


def test_closed_objectives_are_listed_and_searched(s):
    trip = _full_record(s)
    shoot = s.create(title="Lookbook shoot", request="Get the SS26 lookbook shot").id
    live = s.create(title="AW drop", request="Get the AW drop out").id
    run(tools.objective_note(trip, "complete", text=OWNER_SAID))
    run(tools.objective_note(shoot, "remove", text="We are not doing the shoot"))

    closed = run(tools.objective_list(closed=True))
    assert closed["closed"] is True and {o["id"] for o in closed["objectives"]} == {trip, shoot}
    assert {o["id"]: o["status"] for o in closed["objectives"]} == {trip: "done", shoot: "dropped"}
    assert live not in {o["id"] for o in closed["objectives"]}
    # Found by anything in its record: its title, a fact, a note, a blocker, its history.
    for words in ("son", "ethiopia", "passport 4471", "flight-booking", "embassy"):
        found = run(tools.objective_list(closed=True, search=words))["objectives"]
        assert [o["id"] for o in found] == [trip], words
    assert [o["id"] for o in run(tools.objective_list(closed=True, search="LOOKBOOK"))["objectives"]] == [shoot]
    assert run(tools.objective_list(closed=True, search="nothing like this"))["objectives"] == []
    # The live list is searched the same way, and never shows a closed one.
    assert [o["id"] for o in run(tools.objective_list(search="drop"))["objectives"]] == [live]
    assert run(tools.objective_list(search="ethiopia"))["objectives"] == []


def test_closing_needs_the_owners_words_and_happens_once(s):
    obj = s.create(title="t", request="r").id
    with pytest.raises(ToolError, match="owner's request"):
        run(tools.objective_note(obj, "complete"))
    assert s.get(obj).status == "active" and _live_ids() == [obj]
    with pytest.raises(ObjectiveError, match="complete or removed"):
        s.close(obj, "deleted", note=OWNER_SAID)
    run(tools.objective_note(obj, "complete", text=OWNER_SAID))
    with pytest.raises(ToolError, match="already closed"):
        run(tools.objective_note(obj, "remove", text="and remove it"))
    assert s.get(obj).status == "done"


def test_the_owners_own_status_is_still_his_and_a_closed_one_can_come_back(s):
    """The status action still cannot set done or dropped as the owner; closing is its own
    action, recorded as CLIVE's on the owner's words. Reopened, it is live again, whole."""
    obj = _full_record(s)
    with pytest.raises(ToolError, match="Only the owner"):
        run(tools.objective_note(obj, "status", status="done"))
    run(tools.objective_note(obj, "complete", text=OWNER_SAID))
    closed = s.get(obj)
    assert closed.status_set_by == "clive" and closed.events[-1]["by"] == "clive"
    run(tools.objective_note(obj, "status", status="active", text="Actually it is not finished"))
    assert _live_ids() == [obj] and len(s.get(obj).facts) == 2


def test_a_closed_record_still_reads_in_the_store_a_rollback_would_run(s):
    """Closing adds no key to the record: the store before round 12 still reads it, closed."""
    import sys
    import types
    from pathlib import Path

    obj = _full_record(s)
    run(tools.objective_note(obj, "remove", text="Forget the trip"))
    raw = json.loads((s.root / f"{obj}.json").read_text(encoding="utf-8"))
    assert list(raw) == list(store_module.RECORD_FIELDS)
    source = Path(__file__).resolve().parent / "fixtures" / "objectives" / "store_547f652f.py.txt"
    name = "closed_objective_trunk_store_547f652f"
    old = types.ModuleType(name)
    sys.modules[name] = old             # dataclasses resolves annotations through sys.modules
    try:
        exec(compile(source.read_text(encoding="utf-8"), f"<547f652f:{source.name}>", "exec"), old.__dict__)
        rolled_back = old.ObjectiveStore(s.root)
        assert rolled_back.get(obj).status == "dropped" and rolled_back.live() == []
        assert [f["text"] for f in rolled_back.get(obj).facts] == ["He is in Ethiopia", "His passport number ends 4471"]
    finally:
        sys.modules.pop(name, None)


def test_the_model_is_offered_closing_and_the_closed_list():
    from app.tools import registry

    note = registry.get("objective_note").input_schema["properties"]
    assert {"complete", "remove"} <= set(note["action"]["enum"])
    assert "dropped" not in note["status"]["enum"], "the status action could never drop one; remove does"
    listing = registry.get("objective_list").input_schema["properties"]
    assert listing == {"closed": {"type": "boolean"}, "search": {"type": "string"}}
    for name in ("objective_list", "objective_show", "objective_note"):
        assert gate.classify(name, {}).disposition is gate.Disposition.EXECUTE_NOW, name
