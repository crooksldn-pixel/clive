"""CB-14: the observer says the engineering lifecycle is unknown when it read no records.

A roster without an engineering store is legitimate, but it must not read as a healthy,
empty campus: the view names why the lifecycle records were not read, never reports a task
count of zero for records it did not read, and renders an unknown lifecycle differently
from a known empty one. Temporary rosters and stores only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.orchestrator.contracts import EngineeringTask, TaskKind
from app.orchestrator.lifecycle import Kernel, LifecycleStore, PrincipalRegistry
from scripts import agent_state_view as view

BASE = "a" * 40
MEMORY = "e" * 40
T0 = datetime(2026, 9, 22, 22, 0, tzinfo=UTC)


class FakeGit:
    def commit_exists(self, sha: str) -> bool:
        return sha in {BASE, MEMORY}

    def rev_parse(self, ref: str) -> str | None:
        return BASE if ref == "work" else None


def roster(tmp_path: Path, store_root: Path | None) -> dict:
    out = {
        "fresh_window_s": 900,
        "stale_window_s": 3600,
        "workers": [
            {"worker_id": "w1", "display_name": "W One", "role": "builder", "principal_id": "claude",
             "probe": {"kind": "worktree_process", "worktree": str(tmp_path / "no-such-worktree")}},
            {"worker_id": "gpt-reviewer", "display_name": "GPT", "role": "reviewer", "principal_id": "gpt",
             "probe": {"kind": "records_only"}},
        ],
    }
    if store_root is not None:
        out["engineering_store"] = str(store_root)
    return out


def store_with_one_task(root: Path) -> Path:
    kernel = Kernel(LifecycleStore(root), PrincipalRegistry({}), FakeGit(), operator="tests",
                    clock=lambda: T0, journal=False)
    kernel.create_task(EngineeringTask(
        task_id="t-1", revision=1, stream_id="stream", kind=TaskKind.REPAIR,
        objective="repair one bounded defect", repository="o/r", base_sha=BASE,
        target_branch="work", product_memory_sha=MEMORY, required_evidence=("pytest",),
        authorising_reference="owner mandate", created_at=T0,
    ))
    return root


def empty_store(root: Path) -> Path:
    LifecycleStore(root).ensure_layout()  # laid out as the kernel lays it out, holding no tasks
    return root


def broken_store(root: Path) -> Path:
    (root / "tasks").mkdir(parents=True)
    (root / "tasks" / "t.r1.json").write_text("{not json")
    return root


def worker_facts(built: dict) -> list[tuple]:
    return [(w["worker_id"], w["status"], w["status_reason"], w["status_source"]) for w in built["workers"]]



def test_no_store_declared_says_the_lifecycle_is_unknown(tmp_path):
    built = view.build_view(roster(tmp_path, None))
    eng = built["engineering"]
    assert eng["lifecycle"] == "UNKNOWN"
    assert eng["task_count"] is None
    assert eng["store_root"] is None
    assert isinstance(eng["problem"], str) and eng["problem"].startswith("no engineering store declared")
    assert "engineering lifecycle is unknown" in eng["problem"]
    assert built["tasks"] == []
    assert built["schema"] == view.SCHEMA


@pytest.mark.parametrize("kind", ["missing", "unreadable"])
def test_a_declared_store_that_could_not_be_read_is_unknown_with_its_existing_wording(tmp_path, kind):
    root = tmp_path / "nowhere" if kind == "missing" else broken_store(tmp_path / "broken")
    built = view.build_view(roster(tmp_path, root))
    eng = built["engineering"]
    assert eng["lifecycle"] == "UNKNOWN"
    assert eng["task_count"] is None
    prefix = "declared engineering store" if kind == "missing" else "engineering store unreadable"
    assert eng["problem"].startswith(prefix)
    assert built["tasks"] == []


def test_a_read_store_is_known_and_counts_its_tasks(tmp_path):
    root = store_with_one_task(tmp_path / "engineering")
    built = view.build_view(roster(tmp_path, root))
    eng = built["engineering"]
    assert eng["lifecycle"] == "KNOWN"
    assert eng["problem"] is None
    assert eng["task_count"] == len(built["tasks"]) == 1


def test_a_read_empty_store_is_the_only_place_a_zero_count_appears(tmp_path):
    root = empty_store(tmp_path / "engineering")
    built = view.build_view(roster(tmp_path, root))
    eng = built["engineering"]
    assert eng["lifecycle"] == "KNOWN" and eng["problem"] is None
    assert eng["task_count"] == 0 and built["tasks"] == []
    for unread in (None, tmp_path / "nowhere", broken_store(tmp_path / "broken")):
        assert view.build_view(roster(tmp_path, unread))["engineering"]["task_count"] is None


def test_render_says_unknown_in_one_line_and_a_known_empty_store_differently(tmp_path):
    for unread in (None, tmp_path / "nowhere", broken_store(tmp_path / "broken")):
        built = view.build_view(roster(tmp_path, unread))
        text = view.render(built)
        lines = [ln for ln in text.splitlines() if "engineering lifecycle unknown" in ln.lower()]
        assert len(lines) == 1, text
        assert " ".join(built["engineering"]["problem"].split()) in lines[0]
        assert "none recorded" not in text

    root = empty_store(tmp_path / "engineering")
    known_empty = view.render(view.build_view(roster(tmp_path, root)))
    assert "lifecycle unknown" not in known_empty.lower()
    assert "Engineering tasks: none recorded" in known_empty

    unknown = view.render(view.build_view(roster(tmp_path, None)))
    assert unknown.splitlines()[-1] != known_empty.splitlines()[-1]


def test_render_lists_tasks_when_the_store_holds_them(tmp_path):
    root = store_with_one_task(tmp_path / "engineering")
    text = view.render(view.build_view(roster(tmp_path, root)))
    assert "Engineering tasks (from the kernel's records):" in text
    assert "t-1 r1" in text
    assert "lifecycle unknown" not in text.lower()


def test_worker_statuses_and_totals_do_not_depend_on_whether_a_store_was_declared(tmp_path):
    root = empty_store(tmp_path / "engineering")
    views = [view.build_view(roster(tmp_path, s))
             for s in (None, tmp_path / "nowhere", broken_store(tmp_path / "broken"), root)]
    assert worker_facts(views[0]) == [
        ("w1", view.OFFLINE, f"declared worktree {tmp_path / 'no-such-worktree'} does not exist", "probe"),
        ("gpt-reviewer", view.UNKNOWN,
         "no probe can observe this worker; only CLIVE lifecycle records can place it", "probe"),
    ]
    for other in views[1:]:
        assert worker_facts(other) == worker_facts(views[0])
        assert other["totals"] == views[0]["totals"]


def test_main_exits_zero_without_a_store_and_writes_nothing(tmp_path, capsys):
    path = tmp_path / "roster.json"
    path.write_text(json.dumps(roster(tmp_path, None)), encoding="utf-8")
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    assert view.main(["--roster", str(path)]) == 0
    assert "Engineering lifecycle unknown: no engineering store declared" in capsys.readouterr().out
    assert view.main(["--roster", str(path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["engineering"]["lifecycle"] == "UNKNOWN" and doc["engineering"]["task_count"] is None

    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
