#!/usr/bin/env python3
"""A read-only projection of what CLIVE engineering is *actually* doing.

This exists because a branch, a task record and a status report are each easy to
produce without any worker ever having run, and all three have been mistaken for
execution. Nothing here asks a component how it is doing. It looks at the system
and reports what the system can be made to prove:

    process table      is there a worker process, and is it this worker's?
    file mtimes        did that worker write anything, and how long ago?
    systemd            is the unit loaded and running, and is a run in flight?
    watcher state      what did the last run do, and did it succeed?
    git                what branch and SHA is the work actually on?

Where those disagree with a claim, the evidence wins. Where they cannot settle a
question, the answer is UNKNOWN and the reason is named — never a cheerful guess.

    python scripts/agent_state_view.py              # human-readable
    python scripts/agent_state_view.py --json       # one JSON object

Read-only by construction: it opens files, reads /proc, and runs `git` and
`systemctl show` in query form. It writes nothing, starts nothing, and stops
nothing, so it is safe to poll from a dashboard.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "clive.agent_environment_view.v1"

# The vocabulary the Agent Environment may render. There is deliberately no
# value meaning "probably fine" — every one of these is a claim the probe can
# defend, and UNKNOWN is what we say when it cannot.
OFFLINE = "OFFLINE"        # no process exists for this worker
IDLE = "IDLE"              # the process exists and is holding no task
BUILDING = "BUILDING"      # a task is executing, with a write inside fresh_window
REVIEWING = "REVIEWING"    # as BUILDING, but the worker's declared role is reviewer
BLOCKED = "BLOCKED"        # a deterministic blocker was recorded
OWNER_GATE = "OWNER_GATE"  # progress needs an owner decision
STALE = "STALE"            # a task is held open but nothing has moved in stale_window
UNKNOWN = "UNKNOWN"        # the probe could not settle it; reason is always given

DEFAULT_ROSTER = Path(__file__).resolve().parent.parent / "config" / "agent_roster.json"
SKIP_DIRS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache", "node_modules", ".venv"}


@dataclass
class Probe:
    """What one probe actually saw. `notes` is the audit trail for the verdict."""

    status: str = UNKNOWN
    reason: str = "probe did not run"
    current_task: str | None = None
    branch: str | None = None
    head_sha: str | None = None
    last_heartbeat: str | None = None
    last_event: str | None = None
    last_event_at: str | None = None
    blocker: str | None = None
    owner_gate: bool = False
    notes: list[str] = field(default_factory=list)


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 15) -> tuple[int, str]:
    """Run a read-only query. A failure is data, not an exception."""
    try:
        done = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return done.returncode, (done.stdout or done.stderr or "").strip()


# --------------------------------------------------------------------- process


def processes_with_cwd(prefix: str) -> list[dict]:
    """Every live process whose working directory is at or under `prefix`.

    This is the single honest answer to "is a worker running here". A PID file,
    a lock or a task record can all outlive the process they describe; a cwd
    link in /proc cannot, because the kernel drops it when the process dies.
    """
    found = []
    proc = Path("/proc")
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cwd = os.readlink(entry / "cwd")
        except OSError:
            continue  # exited, or not ours to look at — either way, not evidence
        if cwd != prefix and not cwd.startswith(prefix.rstrip("/") + "/"):
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", "replace"
            ).strip()
            stat = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        found.append(
            {
                "pid": int(entry.name),
                "cmdline": cmdline,
                "cpu_seconds": round((int(stat[11]) + int(stat[12])) / os.sysconf("SC_CLK_TCK"), 1),
                "started_at": _iso(_boot_time() + int(stat[19]) / os.sysconf("SC_CLK_TCK")),
                "is_agent": "claude" in cmdline or "node" in cmdline,
            }
        )
    return sorted(found, key=lambda p: p["pid"])


def _boot_time() -> float:
    try:
        for line in Path("/proc/stat").read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except OSError:
        pass
    return 0.0


def newest_write(root: Path) -> tuple[float | None, str | None]:
    """Newest mtime under `root`, ignoring caches and .git.

    Build artefacts are skipped because a stale `__pycache__` touched by an
    unrelated import would otherwise read as a worker still making progress.
    """
    newest_ts: float | None = None
    newest_path: str | None = None
    if not root.is_dir():
        return None, None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = Path(dirpath) / name
            try:
                ts = full.lstat().st_mtime
            except OSError:
                continue
            if newest_ts is None or ts > newest_ts:
                newest_ts, newest_path = ts, str(full.relative_to(root))
    return newest_ts, newest_path


# ------------------------------------------------------------------------ git


def git_facts(worktree: Path) -> tuple[str | None, str | None, int | None]:
    """(branch, head_sha, dirty_file_count) for a checkout, or Nones if it is not one."""
    if not (worktree / ".git").exists():
        return None, None, None
    rc_b, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(worktree))
    rc_s, sha = _run(["git", "rev-parse", "HEAD"], cwd=str(worktree))
    rc_d, dirty = _run(["git", "status", "--porcelain"], cwd=str(worktree))
    return (
        branch if rc_b == 0 else None,
        sha if rc_s == 0 else None,
        len([ln for ln in dirty.splitlines() if ln.strip()]) if rc_d == 0 else None,
    )


# -------------------------------------------------------------------- probes


def probe_worktree_process(cfg: dict, fresh_s: int, stale_s: int) -> Probe:
    """A worker that is a process sitting in a checkout.

    The ordering matters. We ask "does a process exist" before anything else,
    because every other signal here — a branch, a commit, a modified file — can
    be left behind by a worker that died hours ago and would otherwise read as
    activity.
    """
    p = Probe()
    worktree = Path(cfg["worktree"])
    p.notes.append(f"worktree={worktree}")

    if not worktree.is_dir():
        p.status, p.reason = OFFLINE, f"declared worktree {worktree} does not exist"
        return p

    branch, sha, dirty = git_facts(worktree)
    p.branch, p.head_sha = branch, sha
    declared = cfg.get("declared_branch")
    if declared and branch and declared != branch:
        p.notes.append(f"branch mismatch: declared {declared}, checked out {branch}")

    procs = processes_with_cwd(str(worktree))
    agents = [q for q in procs if q["is_agent"]]
    p.notes.append(f"processes_in_worktree={len(procs)} agent_processes={len(agents)}")

    if not agents:
        p.status = OFFLINE
        p.reason = (
            f"no agent process has this worktree as its cwd "
            f"({len(procs)} non-agent process(es) present)"
            if procs
            else "no process has this worktree as its cwd"
        )
        # A shell parked in the directory is the shape of a worker that was set
        # up and never started. Say so rather than letting it read as presence.
        if procs:
            p.notes.append("present processes: " + "; ".join(q["cmdline"][:60] for q in procs))
        return p

    agent = agents[0]
    p.last_heartbeat = agent["started_at"]
    p.notes.append(f"pid={agent['pid']} cpu_s={agent['cpu_seconds']}")

    ts, path = newest_write(worktree)
    p.last_event_at = _iso(ts)
    p.last_event = f"wrote {path}" if path else None
    if ts is None:
        p.status, p.reason = UNKNOWN, "an agent process is alive but no file mtime could be read"
        return p

    age = time.time() - ts
    p.notes.append(f"last_write_age_s={int(age)}")
    p.current_task = cfg.get("declared_task")

    if age <= fresh_s:
        p.status = REVIEWING if cfg.get("_role") == "reviewer" else BUILDING
        p.reason = f"agent process alive and wrote {path} {int(age)}s ago"
    elif age <= stale_s:
        p.status = IDLE
        p.reason = f"agent process alive but has written nothing for {int(age)}s"
    else:
        p.status = STALE
        p.reason = (
            f"agent process alive but its last write was {int(age / 3600)}h ago — "
            "holding a workspace open is not the same as working"
        )
    if dirty:
        p.notes.append(f"uncommitted_files={dirty}")
    return p


def probe_systemd_bridge(cfg: dict, fresh_s: int, stale_s: int) -> Probe:
    """The bridge watcher: a unit that runs an agent when its inbox changes.

    Its own liveness is nearly worthless as a progress signal — it stays green
    forever with nothing to do — so what we report is whether a *run* is in
    flight and what the last one did.
    """
    p = Probe()
    unit = cfg["unit"]
    rc, out = _run(
        ["systemctl", "show", unit, "--property=ActiveState,SubState,MainPID,Description"]
    )
    if rc != 0:
        p.status, p.reason = UNKNOWN, f"systemctl could not be queried: {out[:120]}"
        return p
    props = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
    active, main_pid = props.get("ActiveState", ""), props.get("MainPID", "0")
    p.notes.append(f"unit={unit} ActiveState={active} MainPID={main_pid}")

    if active != "active" or main_pid in ("", "0"):
        p.status, p.reason = OFFLINE, f"unit {unit} is {active or 'unknown'}"
        return p

    p.branch = cfg.get("declared_branch")
    workdir = Path(cfg.get("workdir", ""))
    if workdir.is_dir():
        branch, sha, _ = git_facts(workdir)
        p.branch, p.head_sha = branch or p.branch, sha

    # Is a run actually in flight? The unit's cgroup holds the poll loop and its
    # `sleep`; anything else in there is a dispatched agent. This is why the
    # watcher can be "active (running)" for days having dispatched nothing.
    cgroup = Path(f"/sys/fs/cgroup/system.slice/{unit}/cgroup.procs")
    in_flight: list[str] = []
    if cgroup.is_file():
        try:
            for pid in cgroup.read_text().split():
                try:
                    cmd = (
                        Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
                        .decode("utf-8", "replace").strip()
                    )
                except OSError:
                    continue
                if pid != main_pid and not cmd.startswith("sleep"):
                    in_flight.append(f"{pid}:{cmd[:60]}")
        except OSError as exc:
            p.notes.append(f"cgroup unreadable: {exc}")
    else:
        p.notes.append("cgroup.procs not readable; cannot prove whether a run is in flight")
    p.notes.append(f"in_flight_processes={len(in_flight)}")

    state_dir = Path(cfg.get("state_dir", ""))
    last_run = state_dir / "last-run"
    if last_run.is_file():
        raw = last_run.read_text().strip()
        p.last_event = raw
        parts = raw.split()
        if len(parts) >= 2:
            p.last_event_at = parts[1]
            p.last_heartbeat = parts[1]
        try:
            age = time.time() - last_run.stat().st_mtime
        except OSError:
            age = None
        if parts and parts[0] != "ok":
            p.status = BLOCKED
            p.reason = f"last run did not succeed: {raw}"
            p.blocker = raw
            return p
        if in_flight:
            p.status = BUILDING
            p.reason = f"a dispatched run is in flight ({in_flight[0]})"
            p.current_task = "dispatched inbox run"
            return p
        p.status = IDLE
        p.reason = (
            f"unit is running and healthy but nothing is dispatched; "
            f"last run completed {int(age)}s ago"
            if age is not None
            else "unit is running and healthy but nothing is dispatched"
        )
        if age is not None and age > stale_s:
            p.notes.append(
                f"no run dispatched for {int(age / 3600)}h — this worker only acts when its "
                "inbox changes, so idleness here means nobody has given it work"
            )
        return p

    p.status, p.reason = UNKNOWN, f"unit is active but {last_run} does not exist"
    return p


PROBES = {"worktree_process": probe_worktree_process, "systemd_bridge": probe_systemd_bridge}


# ------------------------------------------------------------------- assembly


def build_view(roster: dict) -> dict:
    fresh_s = int(roster.get("fresh_window_s", 900))
    stale_s = int(roster.get("stale_window_s", 3600))
    records = []
    for worker in roster.get("workers", []):
        cfg = dict(worker.get("probe", {}))
        cfg["_role"] = worker.get("role")
        probe_fn = PROBES.get(cfg.get("kind", ""))
        if probe_fn is None:
            p = Probe(status=UNKNOWN, reason=f"no probe named {cfg.get('kind')!r}")
        else:
            try:
                p = probe_fn(cfg, fresh_s, stale_s)
            except Exception as exc:  # a broken probe must not invent a healthy worker
                p = Probe(status=UNKNOWN, reason=f"probe raised {type(exc).__name__}: {exc}")
        records.append(
            {
                "worker_id": worker["worker_id"],
                "display_name": worker.get("display_name", worker["worker_id"]),
                "role": worker.get("role", "unknown"),
                "status": p.status,
                "status_reason": p.reason,
                "current_task": p.current_task,
                "project": worker.get("project", "clive"),
                "branch": p.branch,
                "head_sha": p.head_sha,
                "last_heartbeat": p.last_heartbeat,
                "last_event": p.last_event,
                "last_event_at": p.last_event_at,
                "blocker": p.blocker,
                "owner_gate": p.owner_gate,
                "evidence": p.notes,
            }
        )
    working = {BUILDING, REVIEWING}
    return {
        "schema": SCHEMA,
        "generated_at": _iso(time.time()),
        "generator": "scripts/agent_state_view.py",
        "host": os.uname().nodename,
        "fresh_window_s": fresh_s,
        "stale_window_s": stale_s,
        "workers": records,
        "totals": {
            "declared": len(records),
            "online": sum(1 for r in records if r["status"] != OFFLINE),
            "working": sum(1 for r in records if r["status"] in working),
            "idle": sum(1 for r in records if r["status"] == IDLE),
            "stale": sum(1 for r in records if r["status"] == STALE),
            "blocked": sum(1 for r in records if r["status"] == BLOCKED),
            "owner_gate": sum(1 for r in records if r["status"] == OWNER_GATE),
            "unknown": sum(1 for r in records if r["status"] == UNKNOWN),
        },
    }


def render(view: dict) -> str:
    lines = [f"CLIVE agent state — {view['generated_at']} on {view['host']}", ""]
    for r in view["workers"]:
        lines.append(f"  {r['status']:<10} {r['display_name']}  ({r['worker_id']}, {r['role']})")
        lines.append(f"             why: {r['status_reason']}")
        if r["branch"]:
            lines.append(f"             branch: {r['branch']} @ {(r['head_sha'] or '?')[:8]}")
        if r["last_event"]:
            lines.append(f"             last event: {r['last_event']} ({r['last_event_at']})")
        if r["blocker"]:
            lines.append(f"             blocker: {r['blocker']}")
        lines.append("")
    t = view["totals"]
    lines.append(
        f"  {t['declared']} declared · {t['working']} working · {t['idle']} idle · "
        f"{t['stale']} stale · {t['blocked']} blocked · {t['unknown']} unknown"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    ap.add_argument("--json", action="store_true", help="emit one JSON object")
    args = ap.parse_args(argv)

    try:
        roster = json.loads(args.roster.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read roster {args.roster}: {exc}", file=sys.stderr)
        return 2

    view = build_view(roster)
    print(json.dumps(view, indent=2) if args.json else render(view))
    # Always 0: this is an observation, and "nothing is running" is a valid
    # observation rather than a failure of the observer.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
