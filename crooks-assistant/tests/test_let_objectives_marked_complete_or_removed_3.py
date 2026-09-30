"""Closing an objective out: complete or removed, off the live list, nothing deleted.

The owner: "Build a way to close an objective out (complete or removed) so it no longer appears
in the live list, while keeping its full record — facts, notes, history — intact and retrievable
later by its id or by searching ... Nothing should be deleted outright."
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.objectives import store as store_module
from app.objectives import tools
from app.objectives.store import ObjectiveError, ObjectiveStore
from app.tools import gate
from app.tools.registry import ToolError


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


def _run(coro):
    return asyncio.run(coro)


def _listed() -> list[str]:
    return [o["id"] for o in _run(tools.objective_list())["objectives"]]


def _rich(s, title: str = "Son to UK") -> str:
    """An objective with something of every kind on it."""
    obj = s.create(title=title, request="Get my son here for the baptism on 13 October", deadline="2026-10-13")
    s.add_fact(obj.id, "He is in Bahir Dar", source="owner")
    s.add_unknown(obj.id, "Which passport he holds")
    s.add_blocker(obj.id, "No flight-booking capability", kind="missing_capability")
    s.ask_owner(obj.id, "Which date can he leave?")
    s.propose(obj.id, "Research visa requirements", needs_owner=False)
    s.progress(obj.id, "Spoke to the embassy about the visa")
    s.owner_note(obj.id, "His aunt can travel with him")
    return obj.id


def _record(tmp_path, objective_id: str) -> dict:
    return json.loads((tmp_path / "objectives" / f"{objective_id}.json").read_text(encoding="utf-8"))


def test_marked_complete_through_the_tool_leaves_the_live_list(s):
    kept, done = _rich(s, "Keep going"), _rich(s)
    assert sorted(_listed()) == sorted([kept, done])

    result = _run(tools.objective_note(done, "close", status="done", text="The owner says he has arrived"))

    assert result["recorded"] == "close" and result["objective"]["status"] == "done"
    assert "nothing was deleted" in result["kept"]
    assert _listed() == [kept]
    assert [o.id for o in s.live()] == [kept] and [o.id for o in s.closed()] == [done]


def test_removed_through_the_tool_leaves_the_live_list(s):
    gone = _rich(s)
    _run(tools.objective_note(gone, "close", status="dropped", text="Not needed any more, the owner said"))
    assert _listed() == []
    assert s.get(gone).status == "dropped"


def test_a_closed_objective_is_whole_by_its_id(s, tmp_path):
    oid = _rich(s)
    before = s.get(oid).to_dict()
    _run(tools.objective_note(oid, "close", status="done", text="All done"))

    shown = _run(tools.objective_show(oid))
    assert shown["status"] == "done"
    for key in ("title", "request", "deadline", "facts", "unknowns", "blockers", "attention", "items"):
        assert shown[key] == before[key], key
    assert [f["text"] for f in shown["facts"]] == ["He is in Bahir Dar", "His aunt can travel with him"]
    assert shown["unknowns"][0]["text"] == "Which passport he holds"
    assert shown["blockers"][0]["text"] == "No flight-booking capability"
    assert shown["attention"][0]["text"] == "Which date can he leave?"

    # The whole history is kept, with the closing and the owner's words at its end.
    after = ObjectiveStore(tmp_path / "objectives").get(oid)   # as after a restart
    assert after.events[:-1] == before["events"]
    assert after.events[-1]["kind"] == "status" and "All done" in after.events[-1]["text"]
    assert after.status == "done" and after.facts == before["facts"]


def test_nothing_is_deleted_record_and_design_stay_on_disk(s, tmp_path):
    project = s.create(title="AW drop", request="The AW drop", kind="project", deadline="2026-12-01",
                       stages=["Sampling", "Approval", "Production"], stage="Sampling", people=["Northfield (factory)"])
    s.add_fact(project.id, "Samples due Friday", source="owner")
    record_before = _record(tmp_path, project.id)
    design = tmp_path / "objectives" / "design" / f"{project.id}.json"
    assert design.exists()
    files_before = sorted(p.name for p in (tmp_path / "objectives").rglob("*") if p.is_file())

    _run(tools.objective_note(project.id, "close", status="dropped", text="The drop is cancelled"))

    assert sorted(p.name for p in (tmp_path / "objectives").rglob("*") if p.is_file()) == files_before
    record_after = _record(tmp_path, project.id)
    for key, value in record_before.items():
        if key in ("status", "status_set_by", "updated_at", "events"):
            continue
        assert record_after[key] == value, key
    assert record_after["events"][:len(record_before["events"])] == record_before["events"]
    closed = s.get(project.id)
    assert [st["name"] for st in closed.stages] == ["Sampling", "Approval", "Production"]
    assert closed.people == [{"name": "Northfield", "role": "factory"}]


def test_a_closed_objective_is_found_by_searching(s):
    closed, live = _rich(s), s.create(title="Trip to Milan", request="Book the Milan trip").id
    _run(tools.objective_note(closed, "close", status="done", text="He arrived"))

    found = _run(tools.objective_list(search="bahir dar"))
    assert [o["id"] for o in found["objectives"]] == [closed]
    assert found["objectives"][0]["status"] == "done"
    # A search reads the live ones too, and a status finds every closed one.
    assert [o["id"] for o in _run(tools.objective_list(search="milan"))["objectives"]] == [live]
    assert [o["id"] for o in _run(tools.objective_list(search="done"))["objectives"]] == [closed]
    assert _run(tools.objective_list(search="nothing like this"))["objectives"] == []
    # Without words, the list is the live one.
    assert _listed() == [live]
    with pytest.raises(ObjectiveError):
        s.search("   ")


def test_closing_needs_the_owners_words_and_a_closed_status(s):
    oid = _rich(s)
    with pytest.raises(ToolError, match="empty"):
        _run(tools.objective_note(oid, "close", status="done"))
    with pytest.raises(ToolError, match="done .complete. or dropped .removed."):
        _run(tools.objective_note(oid, "close", status="waiting", text="x"))
    assert s.get(oid).status != "done" and oid in _listed()

    _run(tools.objective_note(oid, "close", status="done", text="Finished"))
    with pytest.raises(ToolError, match="already closed"):
        _run(tools.objective_note(oid, "close", status="dropped", text="again"))
    with pytest.raises(ToolError):
        _run(tools.objective_note("obj_00000000", "close", status="done", text="x"))


def test_the_status_action_still_cannot_close_and_status_active_puts_it_back(s):
    oid = _rich(s)
    with pytest.raises(ToolError, match="use action close"):
        _run(tools.objective_note(oid, "status", status="done"))
    assert oid in _listed()

    _run(tools.objective_note(oid, "close", status="dropped", text="Drop it"))
    assert oid not in _listed()
    _run(tools.objective_note(oid, "status", status="active", text="It is back on"))
    assert oid in _listed()
    assert [f["text"] for f in s.get(oid).facts] == ["He is in Bahir Dar", "His aunt can travel with him"]


def test_the_owners_screen_closing_stays_the_owners(s):
    oid = _rich(s)
    s.set_status(oid, "done", by="owner")
    assert s.get(oid).summary()["attention"] == "done" and oid not in _listed()
    assert [o.id for o in s.search("bahir")] == [oid]


def test_closing_and_searching_stay_local_reads_to_the_gate():
    for name, args in (("objective_note", {"objective_id": "obj_12345678", "action": "close", "status": "done",
                                           "text": "done"}),
                       ("objective_list", {"search": "visa"})):
        decision = gate.classify(name, args)
        assert decision.tier is gate.Tier.GREEN and decision.disposition is gate.Disposition.EXECUTE_NOW, name


def test_close_and_search_fit_the_tool_block_budget():
    """`close` and `search` are paid for inside the ceiling tests/test_registry.py holds the tool
    block to (43,880 bytes before, 43,900 after), not by raising it."""
    from app.families import load_all
    from app.providers.max_agent_sdk import withheld_tools
    from app.tools import (  # noqa: F401
        analytics_tools,
        batch_tools,
        close_screen,
        display_tools,
        engineering_tools,
        gmail_tools,
        gmail_writes,
        instagram_tools,
        registry,
        shopify_tools,
        shopify_writes,
        show_again,
    )

    load_all()
    specs = registry.all_specs()
    offered = [s for s in specs if s.name not in withheld_tools(specs, writes_enabled=True)]
    assert {"objective_list", "objective_note"} <= {s.name for s in offered}
    total = sum(len(json.dumps({"name": s.name, "description": s.description, "input_schema": s.input_schema})) for s in offered)
    assert total <= 43_902, f"the tool block is {total} bytes"
