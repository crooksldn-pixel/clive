"""engineering_team.py: a read-only view across several objectives at once.

The dispatcher and its worker processes are the real ones (``World``, from
test_engineering_dispatcher.py); only the script under test is new, and it must
never tick, launch, write a record or change a file.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_engineering_dispatcher import REGISTRY, World  # noqa: E402

from app.orchestrator.contracts import TaskStatus  # noqa: E402
from app.orchestrator.workers import ClaudeCodeWorker  # noqa: E402
from app.orchestrator.workers.base import worker_marker  # noqa: E402

import scripts.engineering_team as engineering_team  # noqa: E402

WIDGET_MISSING = {"report": {"status": "blocked", "summary": "cannot", "reason": "the widget is missing"}}


def _run_until(d, predicate, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d.tick()
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting for the predicate")


def _wait_alive(w: World, objective_id: str, timeout: float = 20.0):
    attempt = w.store.read_attempts(objective_id)[0]
    worker = ClaudeCodeWorker(cli=str(w.cli))
    marker = worker_marker(attempt.attempt_id, attempt.worker.session.session_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = worker.live_pids(marker)
        if pids:
            return attempt, pids
        time.sleep(0.05)
    raise AssertionError(f"{objective_id}'s worker never came alive")


def _two_objectives(tmp_path: Path) -> World:
    """obj-a hangs mid-run (a live builder, RUNNING); obj-b reports blocked immediately."""
    w = World(tmp_path, max_concurrent=2)
    w.scenarios({"hang": True}, WIDGET_MISSING)
    w.objective(objective_id="obj-a", target_branch="clive/objective/obj-a")
    w.objective(objective_id="obj-b", target_branch="clive/objective/obj-b")
    d = w.dispatcher()
    d.tick()
    _run_until(d, lambda: (s := w.store.read_task_state("obj-b", 1)) is not None and s.status is TaskStatus.BLOCKED)
    return w


def _argv(w: World, *, as_json: bool = False) -> list[str]:
    args = ["--store", str(w.store.root), "--repo", str(w.repo), "--registry", str(REGISTRY),
            "--runtime-root", str(w.config.runtime_root), "--workspace-root", str(w.config.workspace_root),
            "--max-concurrent", str(w.config.max_concurrent)]
    return [*args, "--json"] if as_json else args


def _snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_lists_every_objective_with_correct_totals_and_json_matches_text(tmp_path, capsys):
    w = _two_objectives(tmp_path)
    attempt_a, pids_a = _wait_alive(w, "obj-a")
    attempt_b = w.store.read_attempts("obj-b")[0]
    assert attempt_a.attempt_id != attempt_b.attempt_id  # two objectives, two distinct attempts

    assert engineering_team.run(_argv(w)) == 0
    text = capsys.readouterr().out
    lines = text.strip("\n").splitlines()

    line_a = next(line for line in lines if line.startswith("obj-a "))
    assert "stage=RUNNING" in line_a and f"attempt={attempt_a.attempt_id}" in line_a
    assert "builder=claude-code-cli" in line_a and str(pids_a[0]) in line_a

    line_b = next(line for line in lines if line.startswith("obj-b "))
    assert "stage=BLOCKED" in line_b and f"attempt={attempt_b.attempt_id}" in line_b
    assert "blocker=" in line_b and "the widget is missing" in line_b

    assert "totals: building=1 reviewing=0 blocked=1 complete=0 other=0" in lines
    assert lines[-1] == "max-concurrent=2 free=1"  # one builder slot free of two, obj-a holding the other

    assert engineering_team.run(_argv(w, as_json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"] == {"building": 1, "reviewing": 0, "blocked": 1, "complete": 0, "other": 0}
    assert payload["max_concurrent"] == 2 and payload["free_slots"] == 1

    rows = {row["objective_id"]: row for row in payload["objectives"]}
    assert rows["obj-a"]["stage"] == "RUNNING" and rows["obj-a"]["attempt_id"] == attempt_a.attempt_id
    assert rows["obj-a"]["builder"] == "claude-code-cli" and pids_a[0] in rows["obj-a"]["pids"]
    assert rows["obj-b"]["stage"] == "BLOCKED" and rows["obj-b"]["attempt_id"] == attempt_b.attempt_id
    assert "the widget is missing" in rows["obj-b"]["blocker"]

    # --json prints exactly what the text prints, rendered from the same report
    assert engineering_team.render(payload) == text.strip("\n")


def test_the_script_writes_nothing(tmp_path):
    w = _two_objectives(tmp_path)
    _wait_alive(w, "obj-a")

    store_before = _snapshot(w.store.root)
    runtime_before = _snapshot(w.config.runtime_root)
    workspace_before = _snapshot(w.config.workspace_root)

    assert engineering_team.run(_argv(w)) == 0
    assert engineering_team.run(_argv(w, as_json=True)) == 0

    assert _snapshot(w.store.root) == store_before
    assert _snapshot(w.config.runtime_root) == runtime_before
    assert _snapshot(w.config.workspace_root) == workspace_before
