"""Round 12's objectives, read by the store production rolls back to.

A deploy that fails rolls back to the previous build, and the owner can roll back by hand. The
store before round 12 (547f652f, and production's 6a29e310, whose store is the same file) reads a
record with `Objective(**data)`, so one key it does not know takes the objective off his home or
answers him with a 500. Here that store itself — its own source, loaded under another name — is
pointed at a folder the round-12 store has written every kind of objective into, and it must list
and open every one; what it writes after the rollback must then be read again, design and all,
when the build rolls forward. The copy of its source in tests/fixtures is held to the commit
whenever this checkout has the commit, so the test cannot drift from the store it stands for.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.objectives.store import RECORD_FIELDS, ObjectiveStore

TRUNK = "547f652f"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "objectives"
SOURCE = FIXTURES / f"store_{TRUNK}.py.txt"
REPO = Path(__file__).resolve().parents[2]
STAGES = ["Sampling", "Approval", "Production", "Delivery"]


def _trunk_source() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    try:
        shown = subprocess.run(["git", "show", f"{TRUNK}:crooks-assistant/app/objectives/store.py"],
                               cwd=REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        shown = None
    if shown is not None and shown.returncode == 0:
        assert shown.stdout == text, f"tests/fixtures copy differs from {TRUNK}'s own store"
    return text


@pytest.fixture
def trunk():
    """The trunk's store module, as it is, under a name of its own."""
    name = f"trunk_objectives_store_{TRUNK}"
    module = types.ModuleType(name)
    sys.modules[name] = module          # dataclasses resolves annotations through sys.modules
    try:
        exec(compile(_trunk_source(), f"<{TRUNK}:app/objectives/store.py>", "exec"), module.__dict__)
        yield module
    finally:
        sys.modules.pop(name, None)


def _every_kind(root: Path) -> dict[str, str]:
    """One of each thing the round-12 store writes, each changed the ways a day changes it."""
    s = ObjectiveStore(root)
    project = s.create(title="AW drop", request="Samples have started for the AW drop with Northfield", kind="project",
                       stages=STAGES, stage="Sampling", waiting_on="Northfield", people=["Northfield (factory)"],
                       purpose="Stock for the AW launch", check_every_days=7)
    s.design(project.id, deadline="2026-11-14", stage="Approval", due="2026-10-09", waiting_on="you")
    s.move_stage(project.id, "next")
    s.propose(project.id, "Chase Northfield for a sample date", needs_owner=False)
    tasks = s.create(title="Rosa and Kit's tasks", request="Give Rosa and Kit these to do later", kind="tasks",
                     tasks=[{"who": "Rosa", "text": "Steam the AW samples"}, {"who": "Kit", "text": "Update the size chart"}])
    s.task(tasks.id, who="Rosa", done=True, by="owner")
    s.task(tasks.id, who="Kit", text="Pack the returns", due="2026-10-02")
    business = s.create(title="Lookbook shoot", request="Get the SS26 lookbook shot", deadline="2026-10-14")
    s.add_fact(business.id, "The drop goes live on the 14th", source="owner")
    s.add_blocker(business.id, "No studio-booking tool", kind="missing_capability", capability="studio booking")
    s.ask_owner(business.id, "Which models do you want?")
    s.propose(business.id, "Book the studio", needs_owner=True)
    build = s.create(title="Packing screen", request="Show today's packing list big", kind="build")
    s.link_engineering(build.id, request_id="eng_1a2b3c", host="clive-worker-01", target_branch="clive/objective/packing")
    closed = s.create(title="Old errand", request="Something finished", kind="tasks", tasks=[{"who": "Kit", "text": "x"}])
    s.set_status(closed.id, "done", by="owner")
    return {"project": project.id, "tasks": tasks.id, "business": business.id, "build": build.id, "closed": closed.id}


def test_the_store_production_rolls_back_to_lists_and_opens_every_round_12_record(tmp_path, trunk):
    root = tmp_path / "objectives"
    ids = _every_kind(root)
    for objective_id in ids.values():
        record = json.loads((root / f"{objective_id}.json").read_text(encoding="utf-8"))
        assert list(record) == list(RECORD_FIELDS), "the record keeps the old store's keys and no others"
        assert (root / "design" / f"{objective_id}.json").exists(), "the design is beside it"
    old = trunk.ObjectiveStore(root)
    listed = old.all()
    assert sorted(o.id for o in listed) == sorted(ids.values()), "every objective listed, nothing else"
    assert sorted(o.id for o in old.live()) == sorted(v for k, v in ids.items() if k != "closed")
    for kind, objective_id in ids.items():
        obj = old.get(objective_id)
        summary = obj.summary()                       # what GET /objectives draws the home from
        assert summary["id"] == objective_id and summary["title"], kind
        json.dumps({**obj.to_dict(), "summary": summary})   # what GET /objectives/{id} sends
    assert old.get(ids["business"]).summary()["attention"] == "needs_you"
    assert old.get(ids["closed"]).summary()["attention"] == "done"
    assert old.get(ids["build"]).summary()["engineering"][0]["request_id"] == "eng_1a2b3c"


def test_rolled_back_changed_and_rolled_forward_nothing_is_lost(tmp_path, trunk):
    """After a rollback the old store changes a record and makes a new one; rolled forward, the
    new store reads both, and the design the old store never saw is still there."""
    root = tmp_path / "objectives"
    ids = _every_kind(root)
    old = trunk.ObjectiveStore(root)
    old.progress(ids["project"], "Northfield say the samples ship Friday")
    old.add_fact(ids["tasks"], "Kit is off on Friday", source="owner")
    made_after_rollback = old.create(title="Returns", request="Sort the returns shelf").id
    new = ObjectiveStore(root)
    project = new.get(ids["project"])
    assert project.kind == "project" and project.current_stage()[1]["name"] == "Approval"
    assert project.stages[1]["waiting_on"] == "you" and project.deadline == "2026-11-14"
    assert project.purpose == "Stock for the AW launch" and project.check_every_days == 7
    assert project.events[-1]["text"] == "Northfield say the samples ship Friday"
    tasks = new.get(ids["tasks"])
    assert [(t["who"], t["text"], t["done"]) for t in tasks.tasks] == [
        ("Rosa", "Steam the AW samples", True), ("Kit", "Update the size chart", False), ("Kit", "Pack the returns", False)]
    assert tasks.facts[-1]["text"] == "Kit is off on Friday"
    plain = new.get(made_after_rollback)
    assert plain.kind == "business" and plain.stages == [] and plain.missing() == []
    assert made_after_rollback in {o.id for o in new.all()}


def test_the_old_store_does_not_trip_over_the_design_folder(tmp_path, trunk):
    """The design files live in design/, which the old store never lists: nothing in it is taken
    for an objective, even a design file named exactly like one."""
    root = tmp_path / "objectives"
    ids = _every_kind(root)
    (root / "gaps.json").write_text("{}", encoding="utf-8")          # the neighbours in the folder
    (root / "displays.json").write_text("{}", encoding="utf-8")
    listed = trunk.ObjectiveStore(root).all()
    assert len(listed) == len(ids)
    assert all(path.parent.name == "design" for path in root.rglob("obj_*.json") if path.parent != root)


def test_round_12s_first_cut_is_read_and_split_so_the_old_store_can_read_it(tmp_path, trunk):
    """Round 12's first cut wrote the design inside the record. It was never deployed, but a
    development Mac may hold one: it is read, and its next write splits it."""
    root = tmp_path / "objectives"
    root.mkdir()
    raw = json.loads((FIXTURES / "business_v1.json").read_text(encoding="utf-8"))
    raw.update({"kind": "tasks", "version": 2, "purpose": None, "done_when": None, "people": [], "stages": [],
                "check_every_days": None, "tasks": [{"id": "t_0000abcd", "who": "Kit", "text": "Pack the returns",
                                                     "due": None, "done": False, "done_at": None, "at": raw["created_at"]}]})
    (root / f"{raw['id']}.json").write_text(json.dumps(raw), encoding="utf-8")
    assert trunk.ObjectiveStore(root).all() == [], "the old store cannot read the first cut: why it was split"
    new = ObjectiveStore(root)
    assert [t["text"] for t in new.get(raw["id"]).tasks] == ["Pack the returns"]
    new.progress(raw["id"], "Still to do")
    assert [o.id for o in trunk.ObjectiveStore(root).all()] == [raw["id"]]
    assert [t["text"] for t in ObjectiveStore(root).get(raw["id"]).tasks] == ["Pack the returns"]


def test_a_design_key_from_a_newer_build_is_kept_not_dropped(tmp_path):
    root = tmp_path / "objectives"
    s = ObjectiveStore(root)
    obj = s.create(title="t", request="r", kind="tasks", tasks=[{"who": "Kit", "text": "x"}])
    path = root / "design" / f"{obj.id}.json"
    design = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**design, "version": 3, "colour": "blue"}), encoding="utf-8")
    s.progress(obj.id, "Still going")
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert kept["colour"] == "blue" and kept["version"] == 3 and kept["tasks"][0]["text"] == "x"
