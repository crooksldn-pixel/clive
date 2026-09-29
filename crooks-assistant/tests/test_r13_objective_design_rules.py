"""Round 13, RC-9: an objective's design keeps everything the owner said, or says why not.

- S6-02: tasks past the 60th and people past the 12th were dropped without a word: an objective
  opened with 61 tasks held 60, and the owner was told it was done.
- S6-03: a task said again with a new date kept its old date, while the history recorded the
  repeat as if nothing had changed.
- S6-04: stages reordered kept each stage's state where it landed, so a done stage could sit
  after the current one; the next "next" then made it upcoming again and wiped when it was done.

The store is the honest unit for each rule (the model reaches it through `objective_open` and
`objective_note`, which pass these through as given); the tools' own schemas are held too.
"""

from __future__ import annotations

import asyncio

import pytest

from app.objectives import store as store_module
from app.objectives import tools
from app.objectives.store import MAX_PEOPLE, MAX_STAGES, MAX_TASKS, ObjectiveError
from app.tools.registry import ToolError

STAGES = ["Sampling", "Approval", "Production", "Delivery"]


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


def _tasks(n: int) -> list[dict]:
    return [{"who": ("Rosa", "Kit")[i % 2], "text": f"Pack order box {i + 1}"} for i in range(n)]


def _people(n: int) -> list[str]:
    return [f"Person {chr(65 + i)} (studio)" for i in range(n)]


def _project(s, stage: str = "Approval"):
    return s.create(title="AW drop", request="Samples have started", kind="project", stages=STAGES, stage=stage)


def _states(obj) -> list[tuple[str, str]]:
    return [(st["name"], st["state"]) for st in obj.stages]


# ------------------------------------------------------------------ S6-02: no silent caps


def test_more_tasks_than_an_objective_holds_are_refused_and_nothing_is_recorded(s):
    with pytest.raises(ObjectiveError) as refused:
        s.create(title="Packing", request="Give Rosa and Kit these", kind="tasks", tasks=_tasks(MAX_TASKS + 1))
    assert f"at most {MAX_TASKS} tasks" in str(refused.value) and "nothing was recorded" in str(refused.value)
    assert s.all() == []


def test_as_many_tasks_as_it_holds_are_all_kept_and_a_task_said_twice_is_one(s):
    obj = s.create(title="Packing", request="Give Rosa and Kit these", kind="tasks",
                   tasks=_tasks(MAX_TASKS) + [_tasks(1)[0]])
    assert len(obj.tasks) == MAX_TASKS


def test_one_task_past_the_limit_on_a_full_objective_is_refused(s):
    obj = s.create(title="Packing", request="Give Rosa and Kit these", kind="tasks", tasks=_tasks(MAX_TASKS))
    with pytest.raises(ObjectiveError, match=f"at most {MAX_TASKS} tasks"):
        s.task(obj.id, who="Kit", text="One more")
    assert len(s.get(obj.id).tasks) == MAX_TASKS


def test_more_people_than_an_objective_names_are_refused_when_opened_or_changed(s):
    with pytest.raises(ObjectiveError) as refused:
        s.create(title="Shoot", request="The shoot", people=_people(MAX_PEOPLE + 1))
    assert f"at most {MAX_PEOPLE} people" in str(refused.value) and "nothing was recorded" in str(refused.value)
    assert s.all() == []
    obj = s.create(title="Shoot", request="The shoot", people=_people(2))
    with pytest.raises(ObjectiveError, match=f"at most {MAX_PEOPLE} people"):
        s.design(obj.id, people=_people(MAX_PEOPLE + 1))
    assert [p["name"] for p in s.get(obj.id).people] == ["Person A", "Person B"]
    # The same person twice is one person, not one of the twelve.
    kept = s.design(obj.id, people=_people(MAX_PEOPLE) + ["Person A (studio)"])
    assert len(kept.people) == MAX_PEOPLE


def test_the_model_is_told_the_limits_and_is_refused_past_them(s):
    with pytest.raises(ToolError, match=f"at most {MAX_TASKS} tasks"):
        asyncio.run(tools.objective_open("Packing", "Give Rosa and Kit these", kind="tasks", tasks=_tasks(MAX_TASKS + 1)))
    from app.tools import registry

    shape = registry.get("objective_open").input_schema["properties"]
    assert shape["tasks"]["maxItems"] == MAX_TASKS
    assert shape["people"]["maxItems"] == MAX_PEOPLE
    assert shape["stages"]["maxItems"] == MAX_STAGES
    noted = registry.get("objective_note").input_schema["properties"]
    assert noted["people"]["maxItems"] == MAX_PEOPLE
    assert noted["stages"]["maxItems"] == MAX_STAGES


# ------------------------------------------------------------------ S6-03: a date said is a date kept


def test_a_task_said_again_with_a_new_date_takes_the_new_date(s):
    obj = s.create(title="Jobs", request="Kit's jobs", kind="tasks",
                   tasks=[{"who": "Kit", "text": "Update the size chart", "due": "2026-10-02"}])
    got = s.task(obj.id, who="Kit", text="update the size chart", due="2026-10-09")
    assert [(t["who"], t["text"], t["due"]) for t in got.tasks] == [("Kit", "Update the size chart", "2026-10-09")]
    assert "9 Oct 2026" in got.events[-1]["text"]


def test_a_task_said_again_with_its_own_date_or_none_is_unchanged(s):
    obj = s.create(title="Jobs", request="Kit's jobs", kind="tasks",
                   tasks=[{"who": "Kit", "text": "Update the size chart", "due": "2026-10-02"}])
    for due in ("2026-10-02", None):
        got = s.task(obj.id, who="Kit", text="Update the size chart", due=due)
        assert [(t["text"], t["due"]) for t in got.tasks] == [("Update the size chart", "2026-10-02")]


def test_one_task_listed_twice_with_two_dates_is_asked_about_not_guessed(s):
    with pytest.raises(ObjectiveError, match="two dates"):
        s.create(title="Jobs", request="Kit's jobs", kind="tasks", tasks=[
            {"who": "Kit", "text": "Update the size chart", "due": "2026-10-02"},
            {"who": "Kit", "text": "Update the size chart", "due": "2026-10-09"}])
    assert s.all() == []
    # Once with a date and once without: the date is the one thing said, so it is kept.
    obj = s.create(title="Jobs", request="Kit's jobs", kind="tasks", tasks=[
        {"who": "Kit", "text": "Update the size chart"},
        {"who": "Kit", "text": "Update the size chart", "due": "2026-10-09"}])
    assert [(t["text"], t["due"]) for t in obj.tasks] == [("Update the size chart", "2026-10-09")]


# ------------------------------------------------------------------ S6-04: stages stay in order


def test_a_reorder_that_puts_a_done_stage_after_the_current_one_is_refused(s):
    obj = _project(s, stage="Approval")                      # Sampling done, Approval current
    done_at = obj.stages[0]["done_at"]
    with pytest.raises(ObjectiveError) as refused:
        s.design(obj.id, stages=["Approval", "Production", "Delivery", "Sampling"])
    assert "Sampling" in str(refused.value) and "done" in str(refused.value)
    kept = s.get(obj.id)
    assert _states(kept) == [("Sampling", "done"), ("Approval", "current"), ("Production", "upcoming"),
                             ("Delivery", "upcoming")]
    moved = s.move_stage(obj.id, "next")
    assert moved.stages[0]["state"] == "done" and moved.stages[0]["done_at"] == done_at, "when it was done is kept"


def test_a_new_stage_before_where_the_project_is_is_refused(s):
    obj = _project(s, stage="Production")
    with pytest.raises(ObjectiveError) as refused:
        s.design(obj.id, stages=["Sampling", "Approval", "Photo shoot", "Production", "Delivery"])
    assert "Photo shoot" in str(refused.value) and "Production" in str(refused.value)
    assert [st["name"] for st in s.get(obj.id).stages] == STAGES


def test_an_upcoming_stage_before_a_done_one_is_refused_with_no_stage_current(s):
    obj = _project(s, stage="Approval")
    s.move_stage(obj.id, "Delivery")
    s.move_stage(obj.id, "next")                              # every stage done
    with pytest.raises(ObjectiveError):
        s.design(obj.id, stages=["Sampling", "Photo shoot", "Approval", "Production", "Delivery"])


@pytest.mark.parametrize(("stages", "states"), [
    (["Sampling", "Approval", "Delivery", "Production"],
     ["done", "current", "upcoming", "upcoming"]),                                # later stages swapped
    (["Sampling", "Approval", "Photo shoot", "Production", "Delivery"],
     ["done", "current", "upcoming", "upcoming", "upcoming"]),                    # a new one after where it is
    (["Sampling", "Production", "Delivery"],
     ["done", "upcoming", "upcoming"]),                                           # the current one taken out
])
def test_a_reorder_that_keeps_the_order_of_what_is_done_is_made(s, stages, states):
    obj = _project(s, stage="Approval")
    got = s.design(obj.id, stages=stages)
    assert [st["state"] for st in got.stages] == states
    assert got.stages[0]["done_at"] == obj.stages[0]["done_at"]
