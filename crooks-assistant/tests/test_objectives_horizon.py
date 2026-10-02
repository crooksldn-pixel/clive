"""The next six weeks on the home, and the pinch between three distances (objectives by touch, B).

George's approved design draws every live objective on one line of 42 days from today, each
stage's date marked on its day. For that the home's list (GET /objectives, `Objective.summary()`)
now carries each stage's date beside its name and state, and nothing else in the summary changed:
the rest of the page reads it exactly as before.

The page half (web/horizon.js, web/distances.js) is proved under Node by
tests/web/horizon.test.js, run here so CI runs it: the pinch's arithmetic, whose fingers a pinch
is (never the orb's), the horizon laid out from fixtures, the marks in dots, and text only.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.objectives import store as store_module

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed here")

STAGES = ["Sampling", "Approval", "Production", "Delivery"]
# Everything the home's list says of an objective, as it said it before this change.
SUMMARY_KEYS = {
    "id", "title", "status", "attention", "attention_reason", "deadline", "days_left", "doing", "next",
    "blocked_by", "needs_you", "unknowns", "facts", "updated_at", "kind", "engineering", "stage", "stages",
    "people_tasks", "check_in",
}


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


def test_each_stage_in_the_summary_carries_its_date(s):
    obj = s.create(title="AW drop", request="Samples have started for the AW drop with Northfield", kind="project",
                   stages=STAGES, stage="Sampling", waiting_on="Northfield", deadline="2026-11-06")
    s.design(obj.id, stage="Sampling", due="2026-10-02")
    s.design(obj.id, stage="Delivery", due="2026-11-08")
    row = s.get(obj.id).summary()
    assert row["stages"] == [
        {"name": "Sampling", "state": "current", "due": "2026-10-02"},
        {"name": "Approval", "state": "upcoming", "due": None},
        {"name": "Production", "state": "upcoming", "due": None},
        {"name": "Delivery", "state": "upcoming", "due": "2026-11-08"},
    ]


def test_nothing_else_in_the_summary_changed(s):
    project = s.create(title="AW drop", request="AW drop", kind="project", stages=STAGES, stage="Sampling",
                       waiting_on="Northfield", deadline="2026-11-06")
    tasks = s.create(title="Rosa and Kit", request="Tasks", kind="tasks",
                     tasks=[{"who": "Rosa", "text": "Steam the samples"}, {"who": "Kit", "text": "Size chart"}])
    business = s.create(title="Restock the tees", request="Restock the tees")
    for obj in (project, tasks, business):
        row = s.get(obj.id).summary()
        assert set(row) == SUMMARY_KEYS, sorted(set(row) ^ SUMMARY_KEYS)
        assert all(set(st) == {"name", "state", "due"} for st in row["stages"])
    row = s.get(project.id).summary()
    assert row["stage"] == {"name": "Sampling", "index": 0, "count": 4, "waiting_on": "Northfield", "due": None}
    assert row["people_tasks"] == [] and row["deadline"] == "2026-11-06"
    assert s.get(tasks.id).summary()["stages"] == [] and s.get(business.id).summary()["stages"] == []
    assert s.get(tasks.id).summary()["people_tasks"] == [{"who": "Rosa", "open": 1, "done": 0}, {"who": "Kit", "open": 1, "done": 0}]


@needs_node
def test_the_horizon_and_the_distances_under_node():
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "horizon.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
