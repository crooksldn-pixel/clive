"""Objectives by touch, part A: the owner's touches on one objective, and six seconds to take each back.

On his own screen George makes a stage now (double-tap, or drag "now" along the stages), ticks a
task, hands a task to someone else (press and drag it onto their group) and drags the date it must
land by. Each is one of the owner's routes (app/routes/objectives.py), answered with the record and
an undo offer; `POST /objectives/{id}/undo` puts back exactly what that touch changed. What is held
here, through the routes and the store:

* each touch changes the record the ordinary way, as the owner, and offers {token, ttl_s: 6, says};
* a touch that changes nothing writes nothing and says so instead;
* the undo restores the stages (states and dates), the tasks (who, done) and the deadline exactly,
  as one more change with an "Undone: ..." event;
* it is refused, in words and with nothing changed, after a later change, after the window, for
  another objective's token, and the second time;
* tokens are kept in memory only, bounded, never written or logged;
* the record stays one the store before round 12 reads; and nothing reaches the shop.

Every name here is invented (Rosa, Kit, Northfield).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.objectives import store as store_module
from app.objectives.store import RECORD_FIELDS, UNDO_KEPT, ObjectiveError, ObjectiveStore

STAGES = ["Sampling", "Approval", "Production", "Delivery"]
TRUNK = "547f652f"
ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "objectives"
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def owner(tmp_path):
    """The owner's routes on a store of their own, asked from the server itself, as
    tests/test_followups_app_page.py has it."""
    from app.routes import objectives

    store = store_module.install(tmp_path / "objectives")
    app = FastAPI()
    app.include_router(objectives.router)
    settings = SimpleNamespace(writes_local_owner=True, tailscale_verify=False, tailscale_cli="")
    app.state.runtime = SimpleNamespace(allowed_logins=("owner@example.test",), settings=settings)
    return SimpleNamespace(client=TestClient(app), store=store, root=tmp_path / "objectives")


def project(store: ObjectiveStore):
    """The AW drop at Approval, Sampling done, with dates on its stages and a deadline."""
    made = store.create(title="AW drop", request="Samples have started for the AW drop with Northfield", kind="project",
                        stages=STAGES, stage="Sampling", waiting_on="Northfield", deadline="2026-11-14")
    store.design(made.id, stage="Approval", due="2026-10-09", waiting_on="you")
    store.design(made.id, stage="Production", due="2026-11-20")
    store.move_stage(made.id, "Approval")
    return store.get(made.id)


def tasks(store: ObjectiveStore):
    made = store.create(title="Rosa and Kit's tasks", request="Give Rosa and Kit these to do later", kind="tasks", tasks=[
        {"who": "Rosa", "text": "Steam the AW samples"}, {"who": "Rosa", "text": "Photograph the swatches", "due": "2026-10-02"},
        {"who": "Kit", "text": "Update the size chart"}])
    return store.get(made.id)


def shape(obj) -> dict:
    """Exactly what a touch can change, as the record holds it."""
    return {"stages": obj.stages, "tasks": obj.tasks, "deadline": obj.deadline}


def offered(answer) -> dict:
    body = answer.json()
    assert answer.status_code == 200, answer.text
    undo = body["undo"]
    assert set(undo) == {"token", "ttl_s", "says"} and undo["ttl_s"] == 6 and undo["says"], undo
    assert body["said"] is None
    return body


# ------------------------------------------------------------------ the touches


def test_a_stage_is_made_now_by_the_owner_and_offered_back(owner):
    obj = project(owner.store)
    body = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "production"}))
    assert [s["state"] for s in body["stages"]] == ["done", "done", "current", "upcoming"]
    assert body["undo"]["says"] == "Production is now"
    assert body["events"][-1]["by"] == "owner" and body["events"][-1]["kind"] == "stage"
    assert body["card"]["stages"][2]["state"] == "current", "the card both screens draw is in the answer"
    back = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Sampling"}))
    assert back["undo"]["says"] == "Back to Sampling"
    on = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "next"}))
    assert on["undo"]["says"] == "Approval is now"


def test_a_project_not_yet_started_is_started_by_its_stage(owner):
    made = owner.store.create(title="Winter drop", request="Get the winter drop made", kind="project", stages=STAGES)
    body = offered(owner.client.post(f"/objectives/{made.id}/stage", json={"stage": "Approval"}))
    assert [s["state"] for s in body["stages"]] == ["done", "current", "upcoming", "upcoming"]
    assert body["undo"]["says"] == "Started: Approval is now"


def test_a_touch_that_changes_nothing_writes_nothing_and_says_so(owner):
    obj = project(owner.store)
    events = len(obj.events)
    same = owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Approval"})
    assert same.status_code == 200 and same.json()["undo"] is None
    assert same.json()["said"] == "Approval is already where it is now."
    due = owner.client.post(f"/objectives/{obj.id}/deadline", json={"deadline": "2026-11-14"})
    assert due.json()["undo"] is None and due.json()["said"].startswith("It is already due ")
    t = tasks(owner.store)
    rosa = t.tasks[0]["id"]
    mine = owner.client.post(f"/objectives/{t.id}/tasks/{rosa}", json={"who": "rosa"})
    assert mine.json()["undo"] is None and mine.json()["said"] == "That is already Rosa's."
    open_ = owner.client.post(f"/objectives/{t.id}/tasks/{rosa}", json={"done": False})
    assert open_.status_code == 200 and open_.json()["undo"] is None
    assert len(owner.store.get(obj.id).events) == events and len(owner.store.get(t.id).events) == len(t.events)


def test_a_task_is_handed_over_and_ticked_and_the_tick_answers_as_before(owner):
    t = tasks(owner.store)
    swatches = t.tasks[1]["id"]
    moved = offered(owner.client.post(f"/objectives/{t.id}/tasks/{swatches}", json={"who": "kit"}))
    assert moved["undo"]["says"] == "Moved to Kit"
    assert next(x for x in moved["tasks"] if x["id"] == swatches)["who"] == "Kit", "spelt as the objective spells Kit"
    assert [g["who"] for g in moved["card"]["groups"]] == ["Rosa", "Kit"]
    assert [x["text"] for x in moved["card"]["groups"][1]["tasks"]] == ["Photograph the swatches", "Update the size chart"]
    ticked = offered(owner.client.post(f"/objectives/{t.id}/tasks/{swatches}", json={"done": True}))
    assert ticked["undo"]["says"] == "Done: Photograph the swatches"
    assert next(x for x in ticked["tasks"] if x["id"] == swatches)["done"] is True
    assert ticked["events"][-1]["by"] == "owner"
    both = offered(owner.client.post(f"/objectives/{t.id}/tasks/{swatches}", json={"who": "Rosa", "done": False}))
    assert both["undo"]["says"] == "Moved to Rosa, open"
    empty = owner.client.post(f"/objectives/{t.id}/tasks/{swatches}", json={})
    assert empty.status_code == 400 and empty.json()["detail"] == "Say whether it is done, or who it is for."
    missing = owner.client.post(f"/objectives/{t.id}/tasks/t_00000000", json={"done": True})
    assert missing.status_code == 400 and "no task" in missing.json()["detail"]


def test_the_deadline_is_moved_and_says_what_would_land_after_it(owner):
    obj = project(owner.store)
    earlier = offered(owner.client.post(f"/objectives/{obj.id}/deadline", json={"deadline": "2026-11-01"}))
    assert earlier["deadline"] == "2026-11-01"
    assert earlier["undo"]["says"].endswith("; Production would land after it")
    later = offered(owner.client.post(f"/objectives/{obj.id}/deadline", json={"deadline": "2026-11-30"}))
    assert later["undo"]["says"].endswith("; everything still lands in time")
    off = offered(owner.client.post(f"/objectives/{obj.id}/deadline", json={"deadline": ""}))
    assert off["deadline"] is None and off["undo"]["says"] == "No deadline now"
    bad = owner.client.post(f"/objectives/{obj.id}/deadline", json={"deadline": "the 30th"})
    assert bad.status_code == 400 and "not a date" in bad.json()["detail"]


def test_a_stage_on_an_objective_without_stages_is_refused_in_words(owner):
    t = tasks(owner.store)
    refused = owner.client.post(f"/objectives/{t.id}/stage", json={"stage": "next"})
    assert refused.status_code == 400 and refused.json()["detail"] == "Only a project has stages."
    obj = project(owner.store)
    unknown = owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Shipping"})
    assert unknown.status_code == 400 and "There is no stage 'Shipping'" in unknown.json()["detail"]


# ------------------------------------------------------------------ the undo


def test_undo_puts_back_exactly_what_a_stage_move_changed(owner):
    obj = project(owner.store)
    before = shape(obj)
    assert before["stages"][0]["done_at"] and before["stages"][1]["started_at"]
    moved = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Delivery"}))
    assert moved["stages"][1]["done_at"] and moved["stages"][3]["started_at"]
    undone = owner.client.post(f"/objectives/{obj.id}/undo", json={"token": moved["undo"]["token"]})
    assert undone.status_code == 200, undone.text
    assert undone.json()["said"] == "Back at Approval, as it was"
    after = owner.store.get(obj.id)
    assert shape(after) == before, "the states and the times each stage started and finished, exactly"
    assert after.events[-1]["kind"] == "undo" and after.events[-1]["by"] == "owner"
    assert after.events[-1]["text"] == "Undone: Delivery is now."
    assert undone.json()["card"]["stages"][1]["state"] == "current"


def test_undo_puts_back_a_tick_a_hand_over_and_a_deadline(owner):
    t = tasks(owner.store)
    swatches = t.tasks[1]["id"]
    before = shape(t)
    ticked = offered(owner.client.post(f"/objectives/{t.id}/tasks/{swatches}", json={"done": True}))
    put = owner.client.post(f"/objectives/{t.id}/undo", json={"token": ticked["undo"]["token"]})
    assert put.json()["said"] == "“Photograph the swatches” is open again"
    assert shape(owner.store.get(t.id)) == before, "done and done_at, exactly as they were"
    moved = offered(owner.client.post(f"/objectives/{t.id}/tasks/{swatches}", json={"who": "Kit"}))
    put = owner.client.post(f"/objectives/{t.id}/undo", json={"token": moved["undo"]["token"]})
    assert put.json()["said"] == "“Photograph the swatches” is Rosa's again"
    assert shape(owner.store.get(t.id)) == before
    obj = project(owner.store)
    was = shape(obj)
    due = offered(owner.client.post(f"/objectives/{obj.id}/deadline", json={"deadline": "2026-10-30"}))
    put = owner.client.post(f"/objectives/{obj.id}/undo", json={"token": due["undo"]["token"]})
    assert put.status_code == 200 and put.json()["deadline"] == "2026-11-14"
    assert put.json()["said"].startswith("Due ") and put.json()["said"].endswith(" again")
    assert shape(owner.store.get(obj.id)) == was


def test_undo_is_refused_once_the_objective_has_changed_since(owner):
    obj = project(owner.store)
    moved = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Production"}))
    owner.store.add_fact(obj.id, "Northfield say the run starts Monday", source="owner")   # CLIVE, meanwhile
    now = shape(owner.store.get(obj.id))
    events = len(owner.store.get(obj.id).events)
    refused = owner.client.post(f"/objectives/{obj.id}/undo", json={"token": moved["undo"]["token"]})
    assert refused.status_code == 400 and refused.json()["detail"] == "It has changed since, so nothing was undone."
    assert shape(owner.store.get(obj.id)) == now and len(owner.store.get(obj.id).events) == events
    # A second touch overtakes the first touch's offer too.
    first = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Delivery"}))
    offered(owner.client.post(f"/objectives/{obj.id}/deadline", json={"deadline": "2026-12-01"}))
    late = owner.client.post(f"/objectives/{obj.id}/undo", json={"token": first["undo"]["token"]})
    assert late.status_code == 400 and "changed since" in late.json()["detail"]


def test_undo_is_refused_after_its_window(owner, monkeypatch):
    obj = project(owner.store)
    clock = {"now": 1000.0}
    monkeypatch.setattr(store_module, "_clock", lambda: clock["now"])
    on_time = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Production"}))
    clock["now"] += 9.0                     # six seconds on the glass, a little slack on the way
    assert owner.client.post(f"/objectives/{obj.id}/undo", json={"token": on_time["undo"]["token"]}).status_code == 200
    too_late = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Delivery"}))
    now = shape(owner.store.get(obj.id))
    clock["now"] += 10.5
    refused = owner.client.post(f"/objectives/{obj.id}/undo", json={"token": too_late["undo"]["token"]})
    assert refused.status_code == 400 and refused.json()["detail"] == "It is too late to undo that, so nothing was undone."
    assert shape(owner.store.get(obj.id)) == now


def test_undo_is_only_for_the_objective_it_came_from_and_only_once(owner):
    obj = project(owner.store)
    other = tasks(owner.store)
    moved = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Production"}))
    token = moved["undo"]["token"]
    elsewhere = owner.client.post(f"/objectives/{other.id}/undo", json={"token": token})
    assert elsewhere.status_code == 400
    assert elsewhere.json()["detail"] == "That undo belongs to another objective, so nothing was undone."
    assert shape(owner.store.get(other.id)) == shape(other)
    assert owner.client.post(f"/objectives/{obj.id}/undo", json={"token": token}).status_code == 200
    again = owner.client.post(f"/objectives/{obj.id}/undo", json={"token": token})
    assert again.status_code == 400 and again.json()["detail"] == "That can no longer be undone, so nothing was changed."
    unknown = owner.client.post(f"/objectives/{obj.id}/undo", json={"token": "not-a-token"})
    assert unknown.status_code == 400 and "no longer" in unknown.json()["detail"]


def test_the_undo_offers_are_bounded_and_never_written_or_logged(owner, caplog):
    caplog.set_level(logging.DEBUG)
    obj = project(owner.store)
    tokens = []
    for i in range(UNDO_KEPT + 3):
        answer = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": STAGES[i % 2]}))
        tokens.append(answer["undo"]["token"])
    assert len(owner.store._undos) == UNDO_KEPT
    for token in tokens:
        for path in owner.root.rglob("*"):
            if path.is_file():
                assert token not in path.read_text(encoding="utf-8"), f"{path.name} holds an undo token"
        assert token not in caplog.text
    oldest = owner.client.post(f"/objectives/{obj.id}/undo", json={"token": tokens[0]})
    assert oldest.status_code == 400 and "no longer" in oldest.json()["detail"]
    # A store opened again, as after a restart, knows none of them.
    assert len(ObjectiveStore(owner.root)._undos) == 0
    with pytest.raises(ObjectiveError, match="no longer"):
        ObjectiveStore(owner.root).undo(obj.id, tokens[-1])


# ------------------------------------------------------------------ the record as it always was


def _trunk_store():
    """The store before round 12, from its own source, as tests/test_objective_rollback.py loads it."""
    text = (FIXTURES / f"store_{TRUNK}.py.txt").read_text(encoding="utf-8")
    try:
        shown = subprocess.run(["git", "show", f"{TRUNK}:crooks-assistant/app/objectives/store.py"],
                               cwd=REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        shown = None
    if shown is not None and shown.returncode == 0:
        assert shown.stdout == text
    name = f"touch_trunk_objectives_store_{TRUNK}"
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(text, f"<{TRUNK}:app/objectives/store.py>", "exec"), module.__dict__)
    return name, module


def test_after_touches_and_undos_the_record_is_one_the_store_before_round_12_reads(owner):
    obj = project(owner.store)
    t = tasks(owner.store)
    moved = offered(owner.client.post(f"/objectives/{obj.id}/stage", json={"stage": "Production"}))
    owner.client.post(f"/objectives/{obj.id}/undo", json={"token": moved["undo"]["token"]})
    offered(owner.client.post(f"/objectives/{obj.id}/deadline", json={"deadline": "2026-10-30"}))
    handed = offered(owner.client.post(f"/objectives/{t.id}/tasks/{t.tasks[0]['id']}", json={"who": "Kit"}))
    owner.client.post(f"/objectives/{t.id}/undo", json={"token": handed["undo"]["token"]})
    for objective_id in (obj.id, t.id):
        record = json.loads((owner.root / f"{objective_id}.json").read_text(encoding="utf-8"))
        assert list(record) == list(RECORD_FIELDS), "the record keeps the old store's keys and no others"
    name, trunk = _trunk_store()
    try:
        old = trunk.ObjectiveStore(owner.root)
        assert sorted(o.id for o in old.all()) == sorted([obj.id, t.id])
        assert old.get(obj.id).deadline == "2026-10-30"
        assert [e["kind"] for e in old.get(obj.id).events][-3:] == ["stage", "undo", "design"]
        json.dumps({**old.get(t.id).to_dict(), "summary": old.get(t.id).summary()})
    finally:
        sys.modules.pop(name, None)
    # And read again by this build, as after a restart, design and all.
    again = ObjectiveStore(owner.root).get(obj.id)
    assert again.current_stage()[1]["name"] == "Approval" and again.deadline == "2026-10-30"
    assert ObjectiveStore(owner.root).get(t.id).tasks[0]["who"] == "Rosa"


# ------------------------------------------------------------------ the owner's alone, and nothing leaves


@pytest.fixture()
async def desk(tmp_path):
    from experience.harness import harness

    async with harness(admitted=True) as h:
        h.objectives = store_module.install(tmp_path / "objectives")
        yield h


async def test_touches_and_undos_reach_nothing_outside_and_are_the_owners_alone(desk, monkeypatch):
    from experience.harness import TABLET_HEADERS

    asked: list[str] = []
    real = desk.store.mutate

    async def mutate(name, variables):
        asked.append(name)
        return await real(name, variables)

    monkeypatch.setattr(desk.store, "mutate", mutate)
    obj = project(desk.objectives)
    t = tasks(desk.objectives)
    reads = len(desk.store.queries)
    head = dict(TABLET_HEADERS)
    moves = [
        (f"/objectives/{obj.id}/stage", {"stage": "Production"}),
        (f"/objectives/{obj.id}/deadline", {"deadline": "2026-10-30"}),
        (f"/objectives/{t.id}/tasks/{t.tasks[0]['id']}", {"done": True}),
        (f"/objectives/{t.id}/tasks/{t.tasks[1]['id']}", {"who": "Kit"}),
    ]
    stranger = {"Tailscale-User-Login": "someone@example.com", "X-Forwarded-For": "100.64.0.9"}
    for url, body in moves:
        refused = await desk.client.post(url, json=body, headers=stranger)
        assert refused.status_code == 403, (url, refused.text)
        answer = await desk.client.post(url, json=body, headers=head)
        assert answer.status_code == 200, answer.text
        objective_id = url.split("/")[2]
        token = answer.json()["undo"]["token"]
        assert (await desk.client.post(f"/objectives/{objective_id}/undo", json={"token": token}, headers=stranger)).status_code == 403
        undone = await desk.client.post(f"/objectives/{objective_id}/undo", json={"token": token}, headers=head)
        assert undone.status_code == 200, undone.text
    assert shape(desk.objectives.get(obj.id)) == shape(obj) and shape(desk.objectives.get(t.id)) == shape(t)
    assert len(desk.store.queries) == reads, "no read of the shop"
    assert asked == [] and desk.store.mutations_sent == 0 and desk.store.drafts == []


# ------------------------------------------------------------------ the touch on the glass, under Node


@pytest.mark.skipif(NODE is None, reason="node is not installed here")
def test_the_touch_layer_under_node():
    """The gestures, the bar and Undo on the page's own code (tests/web/objective-touch.test.js): tap
    and double-tap told apart, one tick for two taps, "now" and the date dragged with the stages that
    would land late red before the finger lets go, a task handed over and settled, the bar's six
    seconds, and every word as text. Skipped only where Node is absent, as tests/test_web_js.py does."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "objective-touch.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
