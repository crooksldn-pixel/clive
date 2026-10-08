#!/usr/bin/env python3
"""The shared vocabulary of CROOKS OS's lifecycle layer: the seam, the states, the waits.

scripts/service_linux.py is the lifecycle itself — start, stop and restart through systemd on
the server — and it is built from what is here: the `Machine` a test can substitute, the states
CROOKS OS can be found in and the one verdict that decides between them, and the waits that make
/health, never a supervisor's exit code, the only proof that something started or stopped.

This file used to be the Mac's lifecycle as well, through launchd LaunchAgents, for the CROOKS
Control menu-bar app. The Mac runtime and the menu-bar app were deleted on the owner's ruling of
8 October (DEC-071, ruling 38; DEC-058: the Mac is not a CROOKS OS host), and with them the
launchd half of this file. What stayed is what the server's lifecycle shares, unchanged in
meaning.

    CLOSING A WINDOW IS NOT STOPPING CROOKS OS.

Everything below reads the service — the port, /health, and what the supervisor says — and
nothing has any input at all representing whether any window is open. That is why
`running_state()` takes the three arguments it takes and no fourth one.
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import launch_common as lc  # noqa: E402

# How long the owner waits, at most, for a press of Start to become an answer. The backend
# imports the SDK and the Shopify client before it binds the port; on a cold machine that is
# tens of seconds, and giving up at ten would report a failure that was only impatience.
START_WAIT_S = 90.0
# Stopping is quick or it is wrong. The supervisor sends SIGTERM and the backend has a shutdown
# handler; if the port is still held after this, something is stuck and saying so is the job.
STOP_WAIT_S = 20.0
POLL_S = 1.0


# --------------------------------------------------------------------------- the seam


@dataclass(frozen=True)
class Ran:
    """One external command, and what it said. Never raises: a command that does not exist is
    a state to report, not a traceback to print at the owner."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def said(self) -> str:
        return ((self.stderr or self.stdout) or "").strip()[:400]


class Runner:
    """Every external command this layer runs. One class, so there is one list of what the
    lifecycle layer is allowed to do to the machine, and one place to substitute in a test."""

    def __call__(self, argv: list[str], *, timeout_s: float = 60.0) -> Ran:
        raise NotImplementedError


class Subprocesses(Runner):
    def __call__(self, argv: list[str], *, timeout_s: float = 60.0) -> Ran:
        try:
            out = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout_s)  # noqa: S603 — a fixed verb list
        except FileNotFoundError:
            # The honest answer on a machine without the supervisor, or whose PATH has been
            # mangled. 127 is the shell's own number for it and belongs in `developer`.
            return Ran(tuple(argv), 127, "", f"{argv[0]}: not found")
        except (OSError, subprocess.SubprocessError) as exc:
            return Ran(tuple(argv), 1, "", f"{type(exc).__name__}: {exc}")
        return Ran(tuple(argv), out.returncode, out.stdout or "", out.stderr or "")


# There was a `Scripted(Runner)` here: a double whose default answer was "0, and nothing said".
# It is gone, and its going is the point. A double that succeeds unconditionally cannot fail,
# so every test built on it measured the double rather than the product. The double the tests
# use is tests/test_service_linux.py's SystemdDouble, which holds systemd's own facts and the
# rules that follow from them: a restart of a service systemd does not have FAILS.


@dataclass
class Machine:
    """Everything this layer asks of, or does to, the machine. A test supplies one of these and
    every branch becomes reachable without a supervisor or a listening socket."""

    runner: Runner = field(default_factory=Subprocesses)
    # fresh -> the /health document, or None when nothing is answering.
    read_health: Callable[[bool], dict | None] = lambda fresh: None
    # Is anything at all holding the port? A backend that has bound the port but cannot serve
    # /health is a different state from one that is not there, and the difference is what
    # tells a stuck copy from a stopped one.
    port_open: Callable[[], bool] = lambda: False
    # Tailscale's HTTPS route for the tablet: (host, note).
    ensure_route: Callable[[], tuple[str | None, str]] = lambda: (None, "not asked")
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic
    log_dir: Path = ROOT / "logs"

    @classmethod
    def real(cls, port: int, *, read_health=None) -> Machine:
        return cls(
            runner=Subprocesses(),
            read_health=read_health or (lambda fresh: lc.fetch_health(f"http://127.0.0.1:{port}/health" + ("?fresh=1" if fresh else ""))),
            port_open=lambda: lc.port_open("127.0.0.1", port),
            ensure_route=lambda: lc.ensure_serve(port),
        )


# --------------------------------------------------------------------------- human errors


# Words that mean a sentence was written for a developer and not for the owner. The test
# suite scans every human line of scripts/service_linux.py for them (which adds its own),
# because the failure this layer exists to prevent is a status line that says "Process
# returned exit status 127".
DEVELOPERESE = (
    "exit status", "exit code", "returncode", "return code", "traceback", "errno",
    "stderr", "stdout", "exception", "none", "null", "subprocess", "launchctl",
    "posix", "stack", "0x", "http 5", "socket",
)


# --------------------------------------------------------------------------- what state is it in


RUNNING = "RUNNING"
RUNNING_WINDOW = "RUNNING_WINDOW"
UNHEALTHY = "UNHEALTHY"
STARTING = "STARTING"
STALE = "STALE"
CRASH_LOOPING = "CRASH_LOOPING"
STOPPED = "STOPPED"
NOT_INSTALLED = "NOT_INSTALLED"

STATES = (RUNNING, RUNNING_WINDOW, UNHEALTHY, STARTING, STALE, CRASH_LOOPING, STOPPED, NOT_INSTALLED)

# The server's sentences (scripts/service_linux.py says each again, as its own).
_SENTENCE = {
    RUNNING: "CROOKS OS is running as a service on this server.",
    RUNNING_WINDOW: "CROOKS OS is running, but in a terminal session rather than as a service. Ending that session WILL stop it.",
    UNHEALTHY: "CROOKS OS is running, but part of it is not working.",
    STARTING: "CROOKS OS is starting.",
    STALE: "CROOKS OS is not answering, but something is still holding its address.",
    CRASH_LOOPING: "CROOKS OS keeps stopping as soon as it starts.",
    STOPPED: "CROOKS OS is stopped.",
    NOT_INSTALLED: "CROOKS OS is not set up on this server yet.",
}

# The one word a status colours a dot with. Deliberately coarser than the state above: four
# facts about a boiler — on, coming on, stuck, off.
_PLAIN = {
    RUNNING: "running", RUNNING_WINDOW: "running", UNHEALTHY: "running",
    STARTING: "starting", STALE: "stuck",
    CRASH_LOOPING: "stopped", STOPPED: "stopped", NOT_INSTALLED: "stopped",
}


def running_state(*, answering: bool, health: dict | None, agents: list[dict], unwell: list[str] | None = None) -> dict:
    """Is CROOKS OS running? Three inputs, and there is deliberately no fourth.

    `answering` is the port; `health` is what /health said; `agents` is what the service
    manager says about each service it supervises. Whether any window is open is not among them
    and cannot be, which is the whole point: a window closing can no more change this answer
    than closing the airing cupboard door can turn the boiler off.

    `unwell` is the essential subsystems the caller found down in /health — it is the
    control layer that owns the list of which three those are, and this function does not
    invent a second opinion about it.
    """
    supervised = any(agent.get("pid") for agent in agents)
    known = any(agent.get("loaded") or agent.get("installed") for agent in agents)
    if health is not None:
        state = UNHEALTHY if unwell else (RUNNING if supervised else RUNNING_WINDOW)
    elif answering:
        # Bound the port, cannot serve /health: a copy that is stuck part-way up, or one that
        # is wedged. Either way a Start on top of it would fail to bind and restart for ever.
        state = STALE
    elif supervised:
        state = STARTING
    elif known:
        crashed = [a for a in agents if a.get("loaded") and (a.get("last_exit_code") or 0) != 0]
        state = CRASH_LOOPING if crashed else STOPPED
    else:
        state = NOT_INSTALLED
    sentence = _SENTENCE[state]
    if state == UNHEALTHY:
        sentence = f"CROOKS OS is running, but {', '.join(unwell or [])} " + ("is" if len(unwell or []) == 1 else "are") + " not working."
    return {
        "state": state, "crooks_os": _PLAIN[state], "human": sentence,
        "supervised": supervised, "answering": bool(answering or health is not None),
        "healthy": health is not None and not unwell,
    }


_UNREAD = object()


def wait_for_health(machine: Machine, *, timeout_s: float, still_starting: Callable[[], bool] | None = None) -> dict | None:
    """Poll /health until it answers or the time is up. This — not the supervisor's exit code —
    is what a successful Start is. `still_starting` lets the wait give up early when the thing
    being waited for has already died, so a crash on import is reported in two seconds rather
    than ninety."""
    deadline = machine.now() + timeout_s
    while True:
        health = machine.read_health(False)
        if health is not None:
            return health
        if machine.now() >= deadline:
            return None
        if still_starting is not None and not still_starting():
            return None
        machine.sleep(POLL_S)


def wait_for_stop(machine: Machine, *, timeout_s: float) -> bool:
    """True once nothing is holding the port. A stop that reports success while the old copy
    is still listening is the same lie in the other direction."""
    deadline = machine.now() + timeout_s
    while True:
        if not machine.port_open() and machine.read_health(False) is None:
            return True
        if machine.now() >= deadline:
            return False
        machine.sleep(POLL_S)


def stage(name: str, state: str, detail: str = "") -> dict:
    return {"stage": name, "state": state, "detail": str(detail)[:300]}


def _outcome(stages: list[dict], *, lifecycle_after: dict, problem_: dict | None, next_: str, human: str, **extra) -> dict:
    return {"stages": stages, "problem": problem_, "lifecycle": lifecycle_after,
            "next": next_, "human": human, "ok": problem_ is None, **extra}
