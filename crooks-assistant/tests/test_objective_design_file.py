"""The design file beside an objective's record: it can never hide, break or split the objective.

Round 12, second independent check. The design (stages, tasks, people…) lives in
design/obj_x.json so that the store production rolls back to can still read obj_x.json
(tests/test_objective_rollback.py). Two files make three new ways to fail, each held here:

* a design file that cannot be read (damaged, not a design, malformed) hid a healthy objective
  from the home and made GET /objectives/{id} a 500. Now the objective reads as its plain kind
  from its record, the damage is logged without a word of its content, and the file is kept
  aside, renamed .damaged, never overwritten by the next write;
* a design that does not belong with its record — another objective's, another kind's, a format
  this build does not know, a history the record does not have — is treated the same way. The
  probe that found it: a "tasks" objective read back carrying stages ['a', 'b'];
* a crash between the two writes split an objective. A write now puts the new design down as a
  pending file, then the record, then makes the pending design the design; each design names the
  record it was written with (its id, kind and the last event it had), so whichever point a write
  stops at, what is read is the whole old objective or the whole new one. Tested by failing each
  step in turn.

And the tidying: a design file whose record does not exist (a creation cut short) is removed once
it is a day old; nothing else is. Objectives are never deleted anywhere — done and dropped are
states of a record that stays — so there is no deletion for the design to follow.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import types

import pytest
from fastapi.testclient import TestClient

from app.objectives import store as store_module
from app.objectives.store import RECORD_FIELDS, ObjectiveStore

STAGES = ["Sampling", "Approval", "Production", "Delivery"]
SECRET = "Northfield-private-price-list-4471"   # a word no log line may carry


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


def design_file(s, objective_id):
    return s.root / "design" / f"{objective_id}.json"


def aside(s):
    return sorted(p.name for p in (s.root / "design").glob("*.damaged"))


def tasks_objective(s):
    return s.create(title="Rosa and Kit's tasks", request="Give Rosa and Kit these to do later", kind="tasks",
                    tasks=[{"who": "Rosa", "text": "Steam the AW samples"}, {"who": "Kit", "text": "Update the size chart"}])


def project_objective(s):
    return s.create(title="AW drop", request="Samples have started", kind="project", stages=STAGES, stage="Sampling",
                    waiting_on="Northfield")


def owner_client():
    from types import SimpleNamespace

    from fastapi import FastAPI

    from app.routes import objectives

    app = FastAPI()
    app.include_router(objectives.router)
    settings = SimpleNamespace(writes_local_owner=True, tailscale_verify=False, tailscale_cli="")
    app.state.runtime = SimpleNamespace(allowed_logins=("team@crooksldn.com",), settings=settings)
    return TestClient(app)


# ------------------------------------------------------------------ 1. a design that cannot be read


@pytest.mark.parametrize("damage", [
    f'{{"version": 3, "stages": [{{"name": "{SECRET}"',                        # cut off mid-write
    f'["{SECRET}"]',                                                            # JSON, not a design
    "",                                                                         # empty
])
def test_a_design_that_cannot_be_read_never_hides_or_breaks_the_objective(s, caplog, damage):
    obj = project_objective(s)
    design_file(s, obj.id).write_text(damage, encoding="utf-8")
    with caplog.at_level(logging.DEBUG, logger="crooks.objectives"):
        got = s.get(obj.id)
        listed = s.all()
    assert got.kind == "project" and got.stages == [] and got.title == "AW drop", "the plain objective, from its record"
    assert [o.id for o in listed] == [obj.id], "still on the home"
    kept = aside(s)
    assert len(kept) == 1 and kept[0].startswith(obj.id) and kept[0].endswith(".damaged")
    assert (s.root / "design" / kept[0]).read_text(encoding="utf-8") == damage, "kept aside exactly as it was"
    said = [r.getMessage() for r in caplog.records if "design" in r.getMessage()]
    assert said, "the damage is logged"
    assert not any(SECRET in line for line in said), "and not a word of its content with it"
    # The next change writes a fresh design; the damaged one is not touched.
    s.progress(obj.id, "Still going")
    assert (s.root / "design" / kept[0]).read_text(encoding="utf-8") == damage
    assert aside(s) == kept


def test_through_the_owners_routes_a_damaged_design_is_not_a_500(s):
    obj = tasks_objective(s)
    design_file(s, obj.id).write_text("{not json", encoding="utf-8")
    client = owner_client()
    shown = client.get(f"/objectives/{obj.id}")
    assert shown.status_code == 200 and shown.json()["kind"] == "tasks" and shown.json()["tasks"] == []
    assert shown.json()["card"]["kind"] == "tasks"
    listing = client.get("/objectives")
    assert listing.status_code == 200 and [o["id"] for o in listing.json()["objectives"]] == [obj.id]


def test_a_record_that_cannot_be_read_is_an_answer_not_a_500(s):
    obj = tasks_objective(s)
    (s.root / f"{obj.id}.json").write_text("{not json", encoding="utf-8")
    shown = owner_client().get(f"/objectives/{obj.id}")
    assert shown.status_code == 404 and "cannot be read" in shown.json()["detail"]
    assert s.all() == [], "a damaged record is skipped on the home, as it always was"


# ------------------------------------------------------------------ 2. a design that is not this record's


def _rewrite(path, **changes):
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, **changes}), encoding="utf-8")


def test_the_probes_split_objective_reads_as_its_plain_kind(s):
    """A "tasks" record with a project's design beside it — stages ['a', 'b'] — is a design that
    does not agree with its record: it is ignored and kept aside, and the tasks objective reads
    as what its record says it is."""
    obj = tasks_objective(s)
    _rewrite(design_file(s, obj.id), kind="project", tasks=[], stages=[
        {"id": "s_00000001", "name": "a", "state": "current", "due": None, "waiting_on": None, "started_at": None, "done_at": None},
        {"id": "s_00000002", "name": "b", "state": "upcoming", "due": None, "waiting_on": None, "started_at": None, "done_at": None}])
    got = s.get(obj.id)
    assert got.kind == "tasks" and got.stages == [] and got.tasks == []
    assert len(aside(s)) == 1 and ".kind." in aside(s)[0]


@pytest.mark.parametrize(("why", "change"), [
    ("foreign", {"id": "obj_00000000"}),                      # another objective's design
    ("version", {"version": 99}),                             # a format this build does not know
    ("history", {"after": "0" * 16}),                         # written after an event this record never had
    ("ahead", {"events": 999}),                               # written for a record that was never written
    ("unreadable", {"stages": "Sampling, Approval"}),         # a design, malformed
    ("unreadable", {"tasks": [{"who": "Rosa"}]}),             # a task with no words
])
def test_a_design_that_does_not_agree_with_its_record_is_ignored_and_kept_aside(s, why, change):
    obj = project_objective(s)
    _rewrite(design_file(s, obj.id), **change)
    got = s.get(obj.id)
    assert got.kind == "project" and got.stages == []
    assert len(aside(s)) == 1 and f".{why}." in aside(s)[0]


def test_a_healthy_design_is_used_and_a_record_changed_by_the_old_store_keeps_it(s):
    """Agreement is not equality: the store production rolls back to appends events to the
    record and never touches the design, and the design still belongs to that record."""
    obj = project_objective(s)
    record = s.root / f"{obj.id}.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["events"].append({"at": "2026-10-01T09:00:00Z", "kind": "progress", "text": "Samples ship Friday", "by": "clive"})
    data["updated_at"] = "2026-10-01T09:00:00Z"
    record.write_text(json.dumps(data), encoding="utf-8")
    got = s.get(obj.id)
    assert [st["name"] for st in got.stages] == STAGES and got.current_stage()[1]["name"] == "Sampling"
    assert aside(s) == []


# ------------------------------------------------------------------ 3. a write cut short at each step


def _state(s, objective_id):
    obj = ObjectiveStore(s.root).get(objective_id)
    return {k: v for k, v in obj.to_dict().items()}


CHANGES = {
    "a stage move": lambda s, o: s.move_stage(o.id, "next", waiting_on="you"),
    "a kind change": lambda s, o: s.design(o.id, kind="project", stages=["a", "b"]),
    "a tick": lambda s, o: s.task(o.id, who="Rosa", done=True, by="owner"),
    "a new task": lambda s, o: s.task(o.id, who="Kit", text="Pack the returns"),
}


def _break_at(monkeypatch, s, objective_id, step):
    """Make the write fail at `step`: 1 the pending design, 2 the record, 3 the pending design
    becoming the design. Each is the os.replace that finishes that step."""
    real = os.replace
    record = str(s.root / f"{objective_id}.json")
    pending = str(s.root / "design" / f"{objective_id}.next.json")
    design = str(s.root / "design" / f"{objective_id}.json")

    def replace(src, dst):
        src, dst = str(src), str(dst)
        hit = {1: dst == pending, 2: dst == record, 3: src == pending and dst == design}[step]
        if hit:
            raise OSError("the machine stopped here")
        return real(src, dst)

    monkeypatch.setattr(store_module.os, "replace", replace)


@pytest.mark.parametrize("step", [1, 2, 3])
@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_write_cut_short_at_any_step_leaves_the_old_objective_or_the_new(s, monkeypatch, change, step):
    obj = tasks_objective(s) if change != "a stage move" else project_objective(s)
    before = _state(s, obj.id)
    # What the change would make, found on a copy, so the failing run can be compared with it.
    twin = ObjectiveStore(s.root.parent / "twin")
    for path in s.root.rglob("*.json"):
        target = twin.root / path.relative_to(s.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    CHANGES[change](twin, obj)
    after = _state(twin, obj.id)
    assert after != before

    _break_at(monkeypatch, s, obj.id, step)
    with pytest.raises(OSError):
        CHANGES[change](s, obj)
    monkeypatch.undo()

    now = _state(s, obj.id)
    # Steps 1 and 2 stop before the record is replaced: the old objective. Step 3 stops after it:
    # the new one.
    expected = before if step <= 2 else after
    assert _same(now, expected), f"{change} cut at step {step}: neither the old objective nor the new"
    assert aside(s) == [], "an unfinished write is not damage"
    # And the next change carries on from exactly that state.
    s.progress(obj.id, "Carrying on")
    carried = _state(s, obj.id)
    assert _same({**carried, "events": carried["events"][:-1]}, now)
    assert not (s.root / "design" / f"{obj.id}.next.json").exists()


def _same(one: dict, other: dict) -> bool:
    """The same objective, but for what differs between two runs of one change: the random ids
    it gives a new stage or task, and the times it stamps."""
    def plain(value):
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()
                    if k not in ("updated_at", "at", "started_at", "done_at") and not (k == "id" and str(v)[:2] in ("s_", "t_"))}
        if isinstance(value, list):
            return [plain(v) for v in value]
        return value
    return plain(one) == plain(other)


def test_a_write_cut_short_is_still_readable_by_the_store_production_rolls_back_to(s, monkeypatch):
    obj = tasks_objective(s)
    _break_at(monkeypatch, s, obj.id, 3)
    with pytest.raises(OSError):
        s.task(obj.id, who="Rosa", done=True)
    monkeypatch.undo()
    from tests.test_objective_rollback import _trunk_source

    module = types.ModuleType("trunk_store_for_cut_write")
    sys.modules[module.__name__] = module
    try:
        exec(compile(_trunk_source(), "<547f652f store>", "exec"), module.__dict__)
        assert [o.id for o in module.ObjectiveStore(s.root).all()] == [obj.id]
    finally:
        sys.modules.pop(module.__name__, None)
    record = json.loads((s.root / f"{obj.id}.json").read_text(encoding="utf-8"))
    assert list(record) == list(RECORD_FIELDS)


def test_every_change_to_an_objective_adds_to_its_history_or_writes_nothing(s):
    """What makes a design name its record without doubt: every write adds an event, and a
    change that changes nothing is not written at all."""
    obj = tasks_objective(s)
    s.task(obj.id, who="Rosa", done=True)
    rosa = next(t for t in s.get(obj.id).tasks if t["who"] == "Rosa")
    written = (s.root / f"{obj.id}.json").stat().st_mtime_ns
    events = len(s.get(obj.id).events)
    time.sleep(0.01)
    s.task(obj.id, item_id=rosa["id"], done=True)             # already done: nothing to write
    assert (s.root / f"{obj.id}.json").stat().st_mtime_ns == written and len(s.get(obj.id).events) == events


# ------------------------------------------------------------------ 4. tidying, and deletion


def test_a_design_with_no_record_is_removed_once_it_is_a_day_old_and_nothing_else_is(s):
    kept = tasks_objective(s)
    folder = s.root / "design"
    old_orphan = folder / "obj_0badc0de.json"
    old_pending = folder / "obj_0badc0df.next.json"
    fresh_orphan = folder / "obj_0badc0e0.json"
    for path in (old_orphan, old_pending, fresh_orphan):
        path.write_text("{}", encoding="utf-8")
    day_ago = time.time() - 26 * 3600
    for path in (old_orphan, old_pending, design_file(s, kept.id)):
        os.utime(path, (day_ago, day_ago))
    design_file(s, kept.id).parent.joinpath("obj_12345678.20260101T000000Z.unreadable.damaged").write_text("x")
    store_module.ObjectiveStore(s.root).all()
    assert not old_orphan.exists() and not old_pending.exists()
    assert fresh_orphan.exists(), "a creation cut short less than a day ago is left alone"
    assert design_file(s, kept.id).exists(), "a design with its record is never tidied"
    assert aside(s) == ["obj_12345678.20260101T000000Z.unreadable.damaged"], "set-aside files are evidence, kept"


def test_objectives_are_never_deleted_so_there_is_no_deletion_for_the_design_to_follow():
    from app.routes import objectives

    assert not [r for r in objectives.router.routes if "DELETE" in getattr(r, "methods", set())]
    assert not [name for name in dir(ObjectiveStore) if "delete" in name or "remove" in name]
