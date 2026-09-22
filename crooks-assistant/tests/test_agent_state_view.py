"""The property under test is refusal.

Every one of these asserts that the view declines to report work it cannot
prove. A dashboard that renders BUILDING because a directory exists, a branch
was pushed or a process is merely alive is worse than no dashboard, because it
launders an assumption into an observation. So the tests below are mostly about
what the view must *not* say.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from scripts import agent_state_view as view


def roster(probe: dict, role: str = "builder") -> dict:
    return {
        "fresh_window_s": 900,
        "stale_window_s": 3600,
        "workers": [
            {
                "worker_id": "w1",
                "display_name": "W One",
                "role": role,
                "project": "clive",
                "probe": probe,
            }
        ],
    }


def only(built: dict) -> dict:
    assert len(built["workers"]) == 1
    return built["workers"][0]


# ----------------------------------------------------------------- worktree


def test_missing_worktree_is_offline_not_unknown(tmp_path):
    """A declared worker whose workspace was never created is absent, not ambiguous."""
    record = only(build(roster({"kind": "worktree_process", "worktree": str(tmp_path / "nope")})))
    assert record["status"] == view.OFFLINE
    assert "does not exist" in record["status_reason"]


def test_worktree_with_no_process_is_offline_however_recent_the_files(tmp_path, monkeypatch):
    """Fresh files prove a worker *was* here. They never prove one is here now."""
    (tmp_path / "just-written.py").write_text("x = 1")
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: [])
    record = only(build(roster({"kind": "worktree_process", "worktree": str(tmp_path)})))
    assert record["status"] == view.OFFLINE
    assert record["current_task"] is None


def test_parked_shell_does_not_count_as_a_worker(tmp_path, monkeypatch):
    """The exact shape of the review worker that was set up and never started."""
    (tmp_path / "f.py").write_text("x = 1")
    monkeypatch.setattr(
        view,
        "processes_with_cwd",
        lambda _p: [
            {
                "pid": 42,
                "cmdline": "bash",
                "cpu_seconds": 0.0,
                "started_at": "2026-09-21T13:18:20Z",
                "is_agent": False,
            }
        ],
    )
    record = only(build(roster({"kind": "worktree_process", "worktree": str(tmp_path)})))
    assert record["status"] == view.OFFLINE
    assert "non-agent" in record["status_reason"]


def agent_proc(pid: int = 7) -> list[dict]:
    return [
        {
            "pid": pid,
            "cmdline": "claude --model claude-opus-5",
            "cpu_seconds": 2545.0,
            "started_at": "2026-09-21T11:35:35Z",
            "is_agent": True,
        }
    ]


def test_live_agent_with_a_fresh_write_is_building(tmp_path, monkeypatch):
    (tmp_path / "f.py").write_text("x = 1")
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: agent_proc())
    record = only(build(roster({"kind": "worktree_process", "worktree": str(tmp_path)})))
    assert record["status"] == view.BUILDING
    assert record["last_event"].startswith("wrote ")


def test_reviewer_role_reports_reviewing_not_building(tmp_path, monkeypatch):
    (tmp_path / "f.py").write_text("x = 1")
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: agent_proc())
    probe = {"kind": "worktree_process", "worktree": str(tmp_path)}
    assert only(build(roster(probe, role="reviewer")))["status"] == view.REVIEWING


@pytest.mark.parametrize(
    ("age_s", "expected"),
    [(60, view.BUILDING), (1800, view.IDLE), (29 * 3600, view.STALE)],
)
def test_status_degrades_with_the_age_of_the_last_write(tmp_path, monkeypatch, age_s, expected):
    """The same live process reads three different ways depending on the evidence.

    This is the whole mechanism: liveness is necessary for BUILDING and nowhere
    near sufficient. The 29h case is the V0.5 worker as actually found.
    """
    target = tmp_path / "f.py"
    target.write_text("x = 1")
    old = time.time() - age_s
    import os

    os.utime(target, (old, old))
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: agent_proc())
    record = only(build(roster({"kind": "worktree_process", "worktree": str(tmp_path)})))
    assert record["status"] == expected


def test_caches_do_not_masquerade_as_progress(tmp_path, monkeypatch):
    """A touched __pycache__ must not resurrect a worker that stopped writing source."""
    source = tmp_path / "f.py"
    source.write_text("x = 1")
    import os

    old = time.time() - 29 * 3600
    os.utime(source, (old, old))
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "f.cpython-312.pyc").write_bytes(b"\x00")  # written just now
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: agent_proc())
    assert only(build(roster({"kind": "worktree_process", "worktree": str(tmp_path)})))[
        "status"
    ] == view.STALE


# ------------------------------------------------------------------- systemd


def test_inactive_unit_is_offline(monkeypatch):
    monkeypatch.setattr(
        view, "_run", lambda *a, **k: (0, "ActiveState=inactive\nSubState=dead\nMainPID=0")
    )
    record = only(build(roster({"kind": "systemd_bridge", "unit": "u.service"})))
    assert record["status"] == view.OFFLINE


def test_active_unit_with_no_dispatch_is_idle_not_building(tmp_path, monkeypatch):
    """The failure this whole file exists to prevent.

    The watcher reports `active (running)` continuously and has done for days.
    Reading that as engineering in progress is precisely the mistake.
    """
    state = tmp_path / "state"
    state.mkdir()
    (state / "last-run").write_text("ok 2026-09-22T07:58:53Z 7f4aa77a")
    monkeypatch.setattr(
        view, "_run", lambda *a, **k: (0, "ActiveState=active\nSubState=running\nMainPID=1049547")
    )
    record = only(
        build(roster({"kind": "systemd_bridge", "unit": "u.service", "state_dir": str(state)}))
    )
    assert record["status"] == view.IDLE
    assert record["current_task"] is None


def test_failed_last_run_is_blocked_and_names_the_blocker(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    (state / "last-run").write_text("fail 2026-09-22T07:58:53Z 7f4aa77a")
    monkeypatch.setattr(
        view, "_run", lambda *a, **k: (0, "ActiveState=active\nSubState=running\nMainPID=99")
    )
    record = only(
        build(roster({"kind": "systemd_bridge", "unit": "u.service", "state_dir": str(state)}))
    )
    assert record["status"] == view.BLOCKED
    assert record["blocker"].startswith("fail ")


def test_unqueryable_systemd_is_unknown_not_offline(monkeypatch):
    """Not knowing and knowing-it-is-absent are different claims; keep them apart."""
    monkeypatch.setattr(view, "_run", lambda *a, **k: (127, "no systemctl"))
    assert only(build(roster({"kind": "systemd_bridge", "unit": "u.service"})))[
        "status"
    ] == view.UNKNOWN


# -------------------------------------------------------------------- shape


def test_an_exploding_probe_yields_unknown_rather_than_a_healthy_worker(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("probe fell over")

    monkeypatch.setitem(view.PROBES, "worktree_process", boom)
    record = only(build(roster({"kind": "worktree_process", "worktree": "/tmp"})))
    assert record["status"] == view.UNKNOWN
    assert "RuntimeError" in record["status_reason"]


def test_unrecognised_probe_kind_is_unknown():
    assert only(build(roster({"kind": "telepathy"})))["status"] == view.UNKNOWN


def test_totals_never_count_a_non_working_status_as_working(tmp_path, monkeypatch):
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: [])
    built = build(roster({"kind": "worktree_process", "worktree": str(tmp_path)}))
    assert built["totals"]["working"] == 0
    assert built["totals"]["declared"] == 1


def test_view_is_json_serialisable_and_carries_its_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: [])
    built = build(roster({"kind": "worktree_process", "worktree": str(tmp_path)}))
    assert built["schema"] == "clive.agent_environment_view.v1"
    assert json.loads(json.dumps(built))["workers"][0]["worker_id"] == "w1"


def test_every_record_carries_the_owner_requested_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: [])
    record = only(build(roster({"kind": "worktree_process", "worktree": str(tmp_path)})))
    for key in (
        "worker_id", "display_name", "role", "status", "current_task", "project", "branch",
        "head_sha", "last_heartbeat", "last_event", "last_event_at", "blocker", "owner_gate",
        "process_started_at",
    ):
        assert key in record, key


build = view.build_view


# ------------------------------------------------- presence, heartbeat, online


def test_a_process_start_time_is_reported_as_such_and_never_as_a_heartbeat(tmp_path, monkeypatch):
    """Presence and liveness are different evidence. Nothing here beats, so nothing is a heartbeat."""
    (tmp_path / "f.py").write_text("x = 1")
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: agent_proc())
    record = only(build(roster({"kind": "worktree_process", "worktree": str(tmp_path)})))
    assert record["status"] == view.BUILDING
    assert record["last_heartbeat"] is None
    assert record["process_started_at"] == "2026-09-21T11:35:35Z"


def test_the_bridge_last_run_timestamp_is_an_event_not_a_heartbeat(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    (state / "last-run").write_text("ok 2026-09-22T07:58:53Z 7f4aa77a")
    monkeypatch.setattr(
        view, "_run", lambda *a, **k: (0, "ActiveState=active\nSubState=running\nMainPID=1049547")
    )
    record = only(
        build(roster({"kind": "systemd_bridge", "unit": "u.service", "state_dir": str(state)}))
    )
    assert record["last_event_at"] == "2026-09-22T07:58:53Z"
    assert record["last_heartbeat"] is None
    assert record["process_started_at"] is None


def test_unknown_is_not_online(monkeypatch):
    """UNKNOWN means presence could not be established; it must never read as present."""
    monkeypatch.setattr(view, "_run", lambda *a, **k: (127, "no systemctl"))
    built = build(roster({"kind": "systemd_bridge", "unit": "u.service"}))
    assert only(built)["status"] == view.UNKNOWN
    assert built["totals"]["unknown"] == 1
    assert built["totals"]["online"] == 0


def test_online_counts_only_established_presence(tmp_path, monkeypatch):
    """A live process that is idle is present; an absent or unobservable worker is not."""
    written = tmp_path / "f.py"
    written.write_text("x = 1")
    old = time.time() - 2000
    os.utime(written, (old, old))
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: agent_proc())
    present = build(roster({"kind": "worktree_process", "worktree": str(tmp_path)}))
    assert only(present)["status"] == view.IDLE
    assert present["totals"]["online"] == 1
    monkeypatch.setattr(view, "processes_with_cwd", lambda _p: [])
    absent = build(roster({"kind": "worktree_process", "worktree": str(tmp_path)}))
    assert only(absent)["status"] == view.OFFLINE
    assert absent["totals"]["online"] == 0
