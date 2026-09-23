"""The replaceable worker-driver seam: launch a builder, observe it, stop it.

A driver owns execution machinery only: a process, its environment, its event
stream. It decides nothing about the lifecycle. What it returns are observations
(``Started``, ``Activity``, ``Finished``) that the dispatcher maps onto kernel
verbs; the mapping, the fences and the candidate identity stay in CLIVE.

A driver must be restart-safe: everything it needs to re-attach to a running
worker is in the ``LaunchRecord`` it returned plus the log file it writes, and
``live_pids`` must find the worker's processes from the host alone, so a
dispatcher that lost its memory never launches a second worker for an attempt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

__all__ = [
    "Activity",
    "Finished",
    "LaunchRecord",
    "LaunchSpec",
    "Started",
    "WorkerDriver",
    "WorkerLaunchError",
    "pid_alive",
    "pid_start_ticks",
    "processes_with_marker",
]

FinishedStatus = Literal["completed", "blocked", "owner_decision_required", "error"]
ErrorClass = Literal["none", "transient", "deterministic"]


class WorkerLaunchError(RuntimeError):
    """The worker could not be launched. ``transient`` says whether retrying can help."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class LaunchSpec:
    task_id: str
    task_revision: int
    attempt_id: str
    fencing_token: int
    session_id: str
    workspace: Path
    home: Path
    log_path: Path
    stderr_path: Path
    prompt: str


@dataclass(frozen=True)
class LaunchRecord:
    pid: int
    pid_start_ticks: int | None
    argv: tuple[str, ...]
    env_names: tuple[str, ...]
    launched_at: datetime


@dataclass(frozen=True)
class Started:
    """The worker's own first report of itself: session, cwd and the surface it can use."""

    session_id: str
    cwd: str
    model: str | None
    tools: tuple[str, ...]
    mcp_servers: tuple[str, ...]
    plugins: tuple[str, ...]
    skills: int
    slash_commands: int
    permission_mode: str | None
    api_key_source: str | None


@dataclass(frozen=True)
class Activity:
    """Something the worker actually did. ``edited`` names a file a successful edit wrote."""

    at: datetime | None
    kind: Literal["assistant", "tool_use", "tool_result", "rate_limit", "other"]
    detail: str = ""
    edited: str | None = None
    denied: bool = False
    rate_limited: bool = False


@dataclass(frozen=True)
class Finished:
    status: FinishedStatus
    summary: str = ""
    reason: str = ""
    error_class: ErrorClass = "none"
    detail: dict = field(default_factory=dict)


Observation = Started | Activity | Finished


class WorkerDriver(Protocol):
    principal_id: str
    kind: str

    def launch(self, spec: LaunchSpec) -> LaunchRecord: ...

    def read(self, log_path: Path, offset: int) -> tuple[list[Observation], int]: ...

    def verify_started(self, started: Started, spec: LaunchSpec) -> list[str]: ...

    def diagnose_exit(self, stderr_path: Path) -> tuple[str, bool]: ...

    def live_pids(self, attempt_id: str) -> list[int]: ...

    def kill(self, attempt_id: str) -> None: ...


# ---- host process facts (Linux /proc), shared by drivers --------------------

def pid_start_ticks(pid: int) -> int | None:
    """The process start time in clock ticks: a pid plus this names one process, not a reused pid."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return int(stat.rsplit(")", 1)[1].split()[19])


def pid_alive(pid: int, start_ticks: int | None) -> bool:
    now = pid_start_ticks(pid)
    if now is None:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    if state == "Z":
        return False
    return start_ticks is None or now == start_ticks


def processes_with_marker(name: str, value: str) -> list[int]:
    """Every live process whose environment carries ``name=value`` (the attempt marker)."""
    needle = f"{name}={value}".encode()
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            env = (entry / "environ").read_bytes()
        except OSError:
            continue
        if needle in env.split(b"\0") and pid_alive(int(entry.name), None):
            found.append(int(entry.name))
    return sorted(found)
