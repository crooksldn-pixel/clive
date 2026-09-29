"""An objective has a shape that fits what it is for, and the owner designs it by talking.

Round 12. George, 29 September: "clive's objectives are bare and rather simple, there is no way
to actually design an objective inside of it to give it more character for what it's set out to
achieve, for example, telling clive that samples have started xyz shows the same as saying give
[two of the team] these tasks to do later." The two people here are named Rosa and Kit: names in
tests are invented, and the sentence is his in every other word.

What is held here, through `POST /turn` on an admitted harness with a scripted model making the
calls Claude would make for his own two sentences (the model is scripted; what is asserted is
what the Mac stores and what the tablet is sent to draw):

* "samples have started for the AW drop with Northfield" is a PROJECT at its sampling stage,
  waiting on Northfield, with the rest of its stages after it, and CLIVE is told the one thing it
  could not fill (the date) so it can ask it in one question;
* "give Rosa and Kit these tasks to do later: …" is DELEGATED TASKS grouped by person;
* the two draw as two different cards, and each stays editable by voice: the next stage, a task
  for Kit, Rosa's marked done, the deadline changed;
* a record written by the store before round 12 loads and reads exactly as it did;
* nothing an objective holds reaches the shop, and authorising a work item stays the owner's.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from app.objectives import store as store_module
from app.objectives.store import ObjectiveError, ObjectiveStore
from experience.harness import harness

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "objectives"

SAMPLES = "Samples have started for the AW drop with Northfield"
DELEGATE = ("Give Rosa and Kit these tasks to do later: Rosa, steam the AW samples and photograph "
            "the swatches; Kit, update the size chart")
STAGES = ["Sampling", "Approval", "Production", "Delivery"]


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


@pytest.fixture()
async def desk(tmp_path):
    async with harness(admitted=True) as h:
        # The objectives this test makes, and only these: a store of its own, as after a restart.
        h.objectives = store_module.install(tmp_path / "objectives")
        yield h


def card_of(capture) -> dict:
    (card,) = [i["data"] for i in capture.surfaces if i["type"] == "objective"]
    return card


def open_project(**extra):
    """What Claude calls for the samples sentence: the list first, then a project at Sampling."""
    return (("objective_list", {}),
            ("objective_open", {"title": "AW drop", "request": SAMPLES, "kind": "project", "stages": STAGES,
                                "stage": "Sampling", "waiting_on": "Northfield", "people": ["Northfield (factory)"],
                                **extra}))


def open_tasks():
    """What Claude calls for the delegation sentence: one task per job, each with who."""
    return (("objective_list", {}),
            ("objective_open", {"title": "Rosa and Kit's tasks", "request": DELEGATE, "kind": "tasks", "tasks": [
                {"who": "Rosa", "text": "Steam the AW samples"},
                {"who": "Rosa", "text": "Photograph the swatches"},
                {"who": "Kit", "text": "Update the size chart"},
            ]}))


def note(objective_id: str, **args):
    return ("objective_note", {"objective_id": objective_id, **args})


# ------------------------------------------------------------------ George's two sentences


async def test_samples_have_started_is_a_project_at_its_sampling_stage(desk):
    said = await desk.ask(SAMPLES, *open_project(), reply="The AW drop is in sampling with Northfield. When does it need to land?")
    assert said.status == 200 and said.unmakeable == {}, said.unmakeable
    (obj,) = desk.objectives.live()
    assert obj.kind == "project" and [s["name"] for s in obj.stages] == STAGES
    assert [s["state"] for s in obj.stages] == ["current", "upcoming", "upcoming", "upcoming"]
    assert obj.stages[0]["waiting_on"] == "Northfield" and obj.stages[0]["started_at"]
    assert obj.people == [{"name": "Northfield", "role": "factory"}]
    assert obj.tasks == [] and obj.items == [], "a project, not a to-do list"
    # The one thing it could not fill, for the one short question in the reply.
    assert obj.missing() == [{"field": "deadline", "means": "the date it has to be finished by"}]
    # What the tablet is sent: the project, stage by stage, with the one it is at.
    assert said.surface_types[:1] == ["objective"]
    card = card_of(said)
    assert card["kind"] == "project" and card["objective_id"] == obj.id and "groups" not in card
    assert [(s["name"], s["state"]) for s in card["stages"]] == [
        ("Sampling", "current"), ("Approval", "upcoming"), ("Production", "upcoming"), ("Delivery", "upcoming")]
    assert card["stages"][0]["waiting_on"] == "Northfield"
    assert card["attention"] == "doing" and card["attention_reason"] == "at Sampling · waiting on Northfield"
    # And the home row reads as a project too.
    row = obj.summary()
    assert row["stage"] == {"name": "Sampling", "index": 0, "count": 4, "waiting_on": "Northfield", "due": None}
    assert row["doing"] == "Sampling · waiting on Northfield" and row["next"] == ["Approval", "Production", "Delivery"]


async def test_give_two_people_these_tasks_is_delegated_tasks_by_person(desk):
    said = await desk.ask(DELEGATE, *open_tasks(), reply="Done: two for Rosa and one for Kit, for later.")
    assert said.status == 200 and said.unmakeable == {}, said.unmakeable
    (obj,) = desk.objectives.live()
    assert obj.kind == "tasks" and obj.stages == [] and obj.items == []
    assert [(t["who"], t["text"], t["done"], t["due"]) for t in obj.tasks] == [
        ("Rosa", "Steam the AW samples", False, None),
        ("Rosa", "Photograph the swatches", False, None),
        ("Kit", "Update the size chart", False, None),
    ]
    assert obj.missing() == [], "nothing to ask: who does what is all there, and 'later' is no date"
    card = card_of(said)
    assert card["kind"] == "tasks" and "stages" not in card
    assert [(g["who"], g["open"], g["done"], [t["text"] for t in g["tasks"]]) for g in card["groups"]] == [
        ("Rosa", 2, 0, ["Steam the AW samples", "Photograph the swatches"]),
        ("Kit", 1, 0, ["Update the size chart"]),
    ]
    assert obj.summary()["people_tasks"] == [{"who": "Rosa", "open": 2, "done": 0}, {"who": "Kit", "open": 1, "done": 0}]


async def test_the_two_sentences_no_longer_show_the_same_thing(desk):
    """The complaint itself: both used to be a title over a list of proposed items."""
    project = card_of(await desk.ask(SAMPLES, *open_project()))
    tasks = card_of(await desk.ask(DELEGATE, *open_tasks()))
    assert (project["kind"], tasks["kind"]) == ("project", "tasks")
    assert "stages" in project and "groups" not in project
    assert "groups" in tasks and "stages" not in tasks
    rows = {o["kind"]: o for o in (await desk.client.get("/objectives", headers=_owner())).json()["objectives"]}
    assert rows["project"]["stage"]["name"] == "Sampling" and rows["project"]["people_tasks"] == []
    assert rows["tasks"]["stage"] is None and [p["who"] for p in rows["tasks"]["people_tasks"]] == ["Rosa", "Kit"]


# ------------------------------------------------------------------ editable by voice


async def test_a_project_is_moved_on_and_redated_by_voice(desk):
    await desk.ask(SAMPLES, *open_project())
    (obj,) = desk.objectives.live()
    said = await desk.ask("It has to land by the 14th of November",
                          note(obj.id, action="set", deadline="2026-11-14"))
    assert said.unmakeable == {} and desk.objectives.get(obj.id).deadline == "2026-11-14"
    assert card_of(said)["deadline"] == "2026-11-14" and desk.objectives.get(obj.id).missing() == []
    said = await desk.ask("Northfield's samples are approved, move it on", note(obj.id, action="stage", stage="next",
                                                                               waiting_on="Northfield"))
    moved = desk.objectives.get(obj.id)
    assert [s["state"] for s in moved.stages] == ["done", "current", "upcoming", "upcoming"]
    assert moved.stages[0]["done_at"] and moved.stages[1]["waiting_on"] == "Northfield"
    assert [(s["name"], s["state"]) for s in card_of(said)["stages"]][:2] == [("Sampling", "done"), ("Approval", "current")]
    said = await desk.ask("Change the deadline to the 21st", note(obj.id, action="set", deadline="2026-11-21"))
    assert desk.objectives.get(obj.id).deadline == "2026-11-21" and card_of(said)["deadline"] == "2026-11-21"
    said = await desk.ask("Production's started", note(obj.id, action="stage", stage="Production"))
    assert [s["state"] for s in desk.objectives.get(obj.id).stages] == ["done", "done", "current", "upcoming"]
    said = await desk.ask("Actually we're back in approval", note(obj.id, action="stage", stage="approval"))
    back = desk.objectives.get(obj.id)
    assert [s["state"] for s in back.stages] == ["done", "current", "upcoming", "upcoming"]
    assert back.stages[2]["started_at"] is None, "a stage it moved back from is upcoming again"


async def test_tasks_are_added_ticked_and_moved_by_voice(desk):
    await desk.ask(DELEGATE, *open_tasks())
    (obj,) = desk.objectives.live()
    said = await desk.ask("Add a task for Kit: pack the returns by Friday",
                          note(obj.id, action="task", who="kit", text="Pack the returns", due="2026-10-02"))
    assert said.unmakeable == {}
    kit = [t for t in desk.objectives.get(obj.id).tasks if t["who"] == "Kit"]
    assert [(t["text"], t["due"]) for t in kit] == [("Update the size chart", None), ("Pack the returns", "2026-10-02")]
    said = await desk.ask("Mark Rosa's done", note(obj.id, action="task", who="Rosa", done=True))
    rosa = [t for t in desk.objectives.get(obj.id).tasks if t["who"] == "Rosa"]
    assert all(t["done"] and t["done_at"] for t in rosa)
    groups = {g["who"]: g for g in card_of(said)["groups"]}
    assert (groups["Rosa"]["open"], groups["Rosa"]["done"]) == (0, 2)
    assert (groups["Kit"]["open"], groups["Kit"]["done"]) == (2, 0)
    # One task, by its id: moved to Rosa, then taken off.
    chart = next(t for t in desk.objectives.get(obj.id).tasks if t["text"] == "Update the size chart")
    await desk.ask("Give the size chart to Rosa instead", note(obj.id, action="task", item_id=chart["id"], who="Rosa"))
    assert next(t for t in desk.objectives.get(obj.id).tasks if t["id"] == chart["id"])["who"] == "Rosa"
    said = await desk.ask("Take the returns off Kit's list", note(obj.id, action="drop", item_id=next(
        t["id"] for t in desk.objectives.get(obj.id).tasks if t["text"] == "Pack the returns")))
    assert [t["text"] for t in desk.objectives.get(obj.id).tasks if t["who"] == "Kit"] == []
    assert [g["who"] for g in card_of(said)["groups"]] == ["Rosa"]


async def test_asking_where_it_is_shows_it_in_its_shape(desk):
    """In a later conversation: "where are we with the AW drop?" finds it and shows it, stages and
    all — the card is drawn from a read of the record, not only from a change to it."""
    await desk.ask(SAMPLES, *open_project(), session_id="monday")
    (obj,) = desk.objectives.live()
    said = await desk.ask("Where are we with the AW drop?", ("objective_list", {}),
                          ("objective_show", {"objective_id": obj.id}), session_id="tuesday")
    assert said.unmakeable == {} and said.reads == []
    card = card_of(said)
    assert card["objective_id"] == obj.id and card["stages"][0]["state"] == "current"


async def test_nothing_an_objective_holds_reaches_the_shop(desk):
    """Stages move and tasks tick on CLIVE's own record: no read of the shop, no change sent."""
    mutations = getattr(desk.store, "mutations_sent", None)
    await desk.ask(SAMPLES, *open_project())
    (project,) = desk.objectives.live()
    said = await desk.ask("Move it to production", note(project.id, action="stage", stage="Production"))
    assert said.reads == [] and getattr(desk.store, "mutations_sent", None) == mutations
    assert not [i for i in said.surfaces if i["type"] in ("confirmation", "batch_action")], "nothing to confirm: nothing is sent"


async def test_a_tick_and_a_turn_on_the_same_objective_both_land(desk):
    """A tap on a task while CLIVE is still answering about the same objective: the record is
    changed under one lock, one change after the other, so neither is lost."""
    await desk.ask(DELEGATE, *open_tasks())
    (obj,) = desk.objectives.live()
    first = obj.tasks[0]
    tick = desk.client.post(f"/objectives/{obj.id}/tasks/{first['id']}", json={"done": True}, headers=_owner())
    turn = desk.ask("Add one for Kit: pack the returns", note(obj.id, action="task", who="Kit", text="Pack the returns"))
    ticked, said = await asyncio.gather(tick, turn)
    assert ticked.status_code == 200 and said.status == 200
    got = desk.objectives.get(obj.id)
    assert next(t for t in got.tasks if t["id"] == first["id"])["done"] is True
    assert [t["text"] for t in got.tasks if t["who"] == "Kit"] == ["Update the size chart", "Pack the returns"]


def test_the_screens_show_a_project_by_its_stages_and_tasks_by_person(s):
    """The TV and the remote draw an objective from its summary (app/displays/views.py): a
    project is doing its stage and next are the stages after it; delegated tasks are next."""
    from app.displays import views

    project = s.create(title="AW drop", request=SAMPLES, kind="project", stages=STAGES, stage="Sampling",
                       waiting_on="Northfield")
    shown = views.objective_view(project.summary(), project.items)["objective"]
    assert shown["doing"] == "Sampling · waiting on Northfield" and shown["next"] == ["Approval", "Production", "Delivery"]
    tasks = s.create(title="Jobs", request=DELEGATE, kind="tasks", tasks=[{"who": "Rosa", "text": "Steam the AW samples"},
                                                                          {"who": "Kit", "text": "Update the size chart"}])
    shown = views.objective_view(tasks.summary(), tasks.items)["objective"]
    assert shown["doing"] is None and shown["next"] == ["Rosa: Steam the AW samples", "Kit: Update the size chart"]


# ------------------------------------------------------------------ the record


def test_a_project_needs_its_stages_and_tasks_need_their_people(s):
    with pytest.raises(ObjectiveError, match="needs its stages"):
        s.create(title="AW drop", request=SAMPLES, kind="project")
    with pytest.raises(ObjectiveError, match="Only a project has stages"):
        s.create(title="t", request="r", kind="tasks", stages=STAGES, tasks=[{"who": "Kit", "text": "x"}])
    with pytest.raises(ObjectiveError, match="needs its tasks"):
        s.create(title="t", request="r", kind="tasks")
    with pytest.raises(ObjectiveError, match="who is to do it"):
        s.create(title="t", request="r", kind="tasks", tasks=[{"who": "", "text": "x"}])
    with pytest.raises(ObjectiveError, match="at most 10"):
        s.create(title="t", request="r", kind="project", stages=[f"Stage {i}" for i in range(11)])
    with pytest.raises(ObjectiveError, match="named twice"):
        s.create(title="t", request="r", kind="project", stages=["Sampling", "sampling"])
    with pytest.raises(ObjectiveError, match="There is no stage 'Shooting'; the stages are Sampling"):
        s.create(title="t", request="r", kind="project", stages=STAGES, stage="Shooting")
    assert s.all() == [], "a refused objective is not half-written"


def test_a_project_not_yet_started_asks_where_it_is_and_finishing_every_stage_is_not_closing_it(s):
    obj = s.create(title="SS27 drop", request="Plan the SS27 drop", kind="project", stages=STAGES)
    assert [m["field"] for m in obj.missing()] == ["stage", "deadline"]
    assert obj.summary()["stage"] is None and obj.summary()["attention"] == "idle"
    s.move_stage(obj.id, "next")                    # not started: next is the first stage
    assert s.get(obj.id).current_stage()[1]["name"] == "Sampling"
    for _ in STAGES:
        s.move_stage(obj.id, "next")
    done = s.get(obj.id)
    assert all(st["state"] == "done" for st in done.stages) and done.stage_line() == "Every stage done"
    assert done.attention_() == ("idle", "every stage is done") and done.status == "active", "only the owner closes it"
    with pytest.raises(ObjectiveError, match="already done"):
        s.move_stage(obj.id, "next")


def test_names_are_one_person_whatever_the_transcript_capitalised(s):
    obj = s.create(title="t", request="r", kind="tasks", tasks=[{"who": "rosa", "text": "Steam the samples"}])
    s.task(obj.id, who="ROSA", text="Photograph the swatches")
    s.task(obj.id, who="Rosa", text="steam the samples")          # said twice: one task
    got = s.get(obj.id)
    assert [(t["who"], t["text"]) for t in got.tasks] == [("Rosa", "Steam the samples"), ("Rosa", "Photograph the swatches")]
    assert [g["who"] for g in got.task_groups()] == ["Rosa"]
    with pytest.raises(ObjectiveError, match="Kit has no task"):
        s.task(obj.id, who="kit", done=True)
    with pytest.raises(ObjectiveError, match="Nothing to change"):
        s.task(obj.id, item_id=got.tasks[0]["id"])


def test_the_design_is_changed_only_where_it_is_said(s):
    obj = s.create(title="AW drop", request=SAMPLES, kind="project", stages=STAGES, stage="Sampling",
                   purpose="Stock for the AW launch", people=["Northfield (factory)"])
    s.design(obj.id, done_when="Delivered to the unit", check_every_days=7)
    s.design(obj.id, stages=["Sampling", "Second samples", "Approval", "Production", "Delivery"])
    s.design(obj.id, stage="Production", due="2026-11-01", waiting_on="Northfield")
    got = s.get(obj.id)
    assert got.purpose == "Stock for the AW launch" and got.done_when == "Delivered to the unit"
    assert got.check_every_days == 7 and got.people == [{"name": "Northfield", "role": "factory"}]
    assert [(st["name"], st["state"]) for st in got.stages][:2] == [("Sampling", "current"), ("Second samples", "upcoming")]
    assert got.stages[3]["due"] == "2026-11-01" and got.current_stage()[1]["name"] == "Sampling", "set moves nothing"
    s.design(obj.id, purpose="", check_every_days=0)
    got = s.get(obj.id)
    assert got.purpose is None and got.check_every_days is None
    with pytest.raises(ObjectiveError, match="not a date"):
        s.design(obj.id, deadline="next Friday")
    with pytest.raises(ObjectiveError, match="Nothing to change"):
        s.design(obj.id)
    with pytest.raises(ObjectiveError, match="belong to a stage"):
        s.design(obj.id, waiting_on="Northfield")
    # A tasks objective made a project, when it was opened as the wrong kind.
    wrong = s.create(title="Samples", request=SAMPLES, kind="tasks", tasks=[{"who": "Northfield", "text": "Make samples"}])
    s.design(wrong.id, kind="project", stages=STAGES)
    s.move_stage(wrong.id, "Sampling", waiting_on="Northfield")
    assert s.get(wrong.id).kind == "project" and s.get(wrong.id).stage_line() == "Sampling · waiting on Northfield"


def test_a_check_in_falls_due_when_the_record_goes_quiet(s):
    obj = s.create(title="AW drop", request=SAMPLES, kind="project", stages=STAGES, stage="Sampling",
                   check_every_days=7)
    today = datetime.now(UTC).date()
    assert obj.check_in(today) == {"every_days": 7, "quiet_days": 0, "due": False}
    assert obj.attention_()[0] == "doing"
    quiet = s.get(obj.id)
    quiet.updated_at = (datetime.now(UTC) - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert quiet.check_in() == {"every_days": 7, "quiet_days": 9, "due": True}
    assert quiet.attention_() == ("check_in", "no update for 9 days; you check in every 7")
    # A question for him still comes first, and a word about it resets the clock.
    quiet.attention.append({"id": "a_1", "text": "Which colourways?", "at": "", "resolved_at": None})
    assert quiet.attention_()[0] == "needs_you"
    s.progress(obj.id, "Northfield say the samples ship Friday")
    assert s.get(obj.id).check_in()["due"] is False
    assert date.fromisoformat(s.get(obj.id).updated_at[:10]) == today


def test_the_design_is_not_written_out_again_as_a_to_do_list(s):
    """The complaint's own failure, refused where it would happen: CLIVE proposing each of the
    people's tasks, or a stage, as its own work items."""
    tasks = s.create(title="Jobs", request=DELEGATE, kind="tasks", tasks=[{"who": "Rosa", "text": "Steam the AW samples"}])
    for said in ("Rosa: steam the AW samples", "Steam the AW samples"):
        with pytest.raises(ObjectiveError, match="already Rosa's task"):
            s.propose(tasks.id, said, needs_owner=False)
    project = s.create(title="AW drop", request=SAMPLES, kind="project", stages=STAGES, stage="Sampling")
    with pytest.raises(ObjectiveError, match="already a stage"):
        s.propose(project.id, "approval", needs_owner=False)
    s.propose(project.id, "Chase Northfield for a sample date", needs_owner=False)
    assert [i["text"] for i in s.get(project.id).items] == ["Chase Northfield for a sample date"]


def test_the_ladder_is_untouched_by_the_design(s):
    """Tasks and stages are records of what people are doing; they cannot approve CLIVE's own
    work items, and the model's tool still cannot authorise or close."""
    from app.objectives import tools
    from app.tools.registry import ToolError

    obj = s.create(title="AW drop", request=SAMPLES, kind="project", stages=STAGES, stage="Sampling")
    s.propose(obj.id, "Pay Northfield's sampling invoice", needs_owner=True)
    item = s.get(obj.id).items[0]
    for args in ({"action": "task", "item_id": item["id"], "done": True},
                 {"action": "drop", "item_id": item["id"]},
                 {"action": "advance", "item_id": item["id"], "state": "authorised"},
                 {"action": "status", "status": "done"}):
        with pytest.raises(ToolError):
            asyncio.run(tools.objective_note(obj.id, **args))
    asyncio.run(tools.objective_note(obj.id, "stage", stage="next"))
    got = s.get(obj.id)
    assert got.items[0]["state"] == "proposed" and got.attention_()[0] == "needs_you"
    assert got.status == "active"


def test_the_tools_return_the_card_and_what_is_missing_and_the_model_never_reads_the_card(s):
    from app.objectives import tools
    from app.tools.dispatch import _render

    opened = asyncio.run(tools.objective_open("AW drop", SAMPLES, kind="project", stages=STAGES, stage="Sampling"))
    assert opened["missing"] == [{"field": "deadline", "means": "the date it has to be finished by"}]
    assert opened["_surfaces"][0]["type"] == "objective" and "_surfaces" not in json.loads(_render(opened))
    noted = asyncio.run(tools.objective_note(opened["id"], "stage", stage="next"))
    assert noted["_surfaces"][0]["data"]["stages"][1]["state"] == "current"
    shown = asyncio.run(tools.objective_show(opened["id"]))
    assert shown["_surfaces"][0]["data"]["stages"][1]["state"] == "current" and "missing" not in shown
    tasks = asyncio.run(tools.objective_open("Jobs", DELEGATE, kind="tasks", tasks=[{"who": "Kit", "text": "Chart"}]))
    noted = asyncio.run(tools.objective_note(tasks["id"], "task", who="Rosa", text="Steam"))
    assert [row[1:] for row in noted["ids"]["tasks"]] == [("Kit", "Chart", "open"), ("Rosa", "Steam", "open")]


def test_one_turn_that_opens_and_changes_an_objective_draws_one_card(s):
    from app.presentation import present
    from app.providers.base import ToolCall

    obj = s.create(title="AW drop", request=SAMPLES, kind="project", stages=STAGES, stage="Sampling")
    from app.objectives import cards

    first = {"_surfaces": [cards.surface(obj)]}
    s.move_stage(obj.id, "next")
    second = {"_surfaces": [cards.surface(s.get(obj.id))]}
    items = present([ToolCall(name="objective_open", args={}, ok=True, result=first),
                     ToolCall(name="objective_note", args={}, ok=True, result=second)])
    (only,) = [i for i in items if i["type"] == "objective"]
    assert only["data"]["stages"][1]["state"] == "current", "the card as the turn left it"
    assert present([ToolCall(name="objective_list", args={}, ok=True, result={"objectives": []})]) == []


def test_the_prompt_teaches_the_kinds_by_what_the_thing_is(tmp_path):
    """The model chooses the kind; the prompt says how, once, with the owner's own two sentences."""
    from app.kb.loader import build_system_prompt, load

    prompt = build_system_prompt(load(tmp_path))
    for phrase in ("chosen by what the thing is, not by the words", "is a project at Sampling",
                   "never a list of to-dos", "one task per job, each with who",
                   "nothing is sent to them, so never say you told them", "ONE short question",
                   "never a list or a form", "orders, books and pays for nothing", "only from what he said",
                   "never propose them again as work items"):
        assert phrase in prompt, phrase


# ------------------------------------------------------------------ an old record


@pytest.mark.parametrize("name", ["business_v1.json", "build_v1.json"])
def test_a_record_written_before_round_12_reads_exactly_as_it_did(tmp_path, name):
    """Copies of records as the trunk's store (547f652f) wrote them, and the summary the trunk
    made of each (tests/fixtures/objectives): the migration fills the design fields with
    nothing and changes nothing that was there."""
    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert "version" not in raw and "stages" not in raw, "the fixture is a version-1 record"
    root = tmp_path / "objectives"
    root.mkdir()
    (root / f"{raw['id']}.json").write_text(json.dumps(raw), encoding="utf-8")
    loaded = ObjectiveStore(root).get(raw["id"])
    before = json.loads((FIXTURES / "summaries_v1.json").read_text(encoding="utf-8"))[name]
    now = loaded.summary()
    assert {k: now[k] for k in before} == before, "every field the trunk showed reads the same"
    assert (loaded.stages, loaded.tasks, loaded.people, loaded.purpose, loaded.check_every_days) == ([], [], [], None, None)
    assert now["stage"] is None and now["people_tasks"] == [] and now["check_in"] is None
    assert {k: v for k, v in loaded.to_dict().items() if k in raw} == raw, "nothing already there was touched"
    assert ObjectiveStore(root).all()[0].id == raw["id"]
    # The first change writes it in the current format, keeping all of it.
    ObjectiveStore(root).progress(raw["id"], "Still going")
    rewritten = json.loads((root / f"{raw['id']}.json").read_text(encoding="utf-8"))
    assert rewritten["version"] == 2 and rewritten["facts"] == raw["facts"] and rewritten["items"] == raw["items"]


def test_a_record_older_still_without_kind_loads_as_business(tmp_path):
    raw = json.loads((FIXTURES / "business_v1.json").read_text(encoding="utf-8"))
    for key in ("kind", "engineering", "status_set_by"):
        raw.pop(key)
    root = tmp_path / "objectives"
    root.mkdir()
    (root / f"{raw['id']}.json").write_text(json.dumps(raw), encoding="utf-8")
    loaded = ObjectiveStore(root).get(raw["id"])
    assert loaded.kind == "business" and loaded.engineering == []


def test_a_record_from_a_newer_build_is_skipped_not_rewritten(tmp_path):
    raw = {**json.loads((FIXTURES / "business_v1.json").read_text(encoding="utf-8")), "version": 3, "sparkles": True}
    root = tmp_path / "objectives"
    root.mkdir()
    path = root / f"{raw['id']}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert ObjectiveStore(root).all() == []
    assert json.loads(path.read_text(encoding="utf-8")) == raw


# ------------------------------------------------------------------ the owner's tap


async def test_the_owner_ticks_a_task_on_his_screen_and_only_he_can(desk):
    await desk.ask(DELEGATE, *open_tasks())
    (obj,) = desk.objectives.live()
    task = obj.tasks[0]
    ticked = await desk.client.post(f"/objectives/{obj.id}/tasks/{task['id']}", json={"done": True}, headers=_owner())
    assert ticked.status_code == 200
    body = ticked.json()
    assert body["tasks"][0]["done"] is True and body["card"]["groups"][0]["done"] == 1
    assert body["events"][-1]["by"] == "owner"
    again = await desk.client.post(f"/objectives/{obj.id}/tasks/{task['id']}", json={"done": False}, headers=_owner())
    assert again.json()["tasks"][0]["done"] is False
    missing = await desk.client.post(f"/objectives/{obj.id}/tasks/t_00000000", json={"done": True}, headers=_owner())
    assert missing.status_code == 400 and "no task" in missing.json()["detail"]
    stranger = await desk.client.post(f"/objectives/{obj.id}/tasks/{task['id']}", json={"done": True},
                                      headers={"Tailscale-User-Login": "someone@example.com", "X-Forwarded-For": "100.64.0.9"})
    assert stranger.status_code == 403 and desk.objectives.get(obj.id).tasks[0]["done"] is False


def _owner() -> dict[str, str]:
    from experience.harness import TABLET_HEADERS

    return dict(TABLET_HEADERS)
