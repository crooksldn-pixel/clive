#!/usr/bin/env python3
"""The lifecycle of CROOKS OS on the Mac: start it, stop it, restart it, and say truthfully
which of those it is in.

Before this file existed the operations layer could describe the Mac and update it, but it
could not TURN IT ON. `crooks-control status` on a stopped Mac said, in as many words, "`make
up`, or `make install` to have it start at login" — an instruction to open Terminal, which is
the one thing the appliance is meant to remove. A Start button that is really a note telling
the owner to type something is not a Start button.

So: start, stop and restart are typed operations here, each of which

  * works when the backend is COMPLETELY stopped — including when it has never been installed
    as a login service, because "not set up yet" is the most stopped a thing can be;
  * succeeds only when /health answers, never because launchctl exited 0. `launchctl
    kickstart` returns 0 for a service that then dies on its first import. §26: process
    reported started is not the same fact as genuinely healthy, and only the second one is
    worth a green light;
  * fails in the owner's words — "CROOKS OS couldn't start. Python environment unavailable."
    — and keeps the exit status, the stderr and the log path in a `developer` field the app
    puts behind an expansion, because the owner is not going to read `sh: 1: uvicorn: not
    found` and know what to do with it.

The background service is a launchd LaunchAgent (see launchd/*.plist and
scripts/install_launchd.py). That matters for the question this layer must never get wrong:

    CLOSING THE APPLICATION WINDOW IS NOT STOPPING CROOKS OS.

The Control app is a dial on the wall. CROOKS OS is the boiler. Everything below reads the
boiler — the port, /health, and what launchd says about the agents — and nothing below has
any input at all representing whether the app is open. That is not an accident of wording; it
is why `running_state()` takes the three arguments it takes and no fourth one.

Every external command goes through a `Runner`, and everything else the Mac is asked
(is the port open, what does /health say, is Tailscale routing) goes through a `Machine`. On
this Linux build box there is no launchctl and no /health, so the seam is what makes any of
this testable at all: tests supply a Machine that answers as a Mac would. What CANNOT be
tested here is launchctl itself — the verbs, the domain syntax, whether `bootstrap` is the
right one for this macOS. Those are asserted as the commands we would run, and nothing more.
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

# The verbs, in one place, so a grep for what this layer can do to the Mac is a short list.
LAUNCHCTL = "launchctl"
BOOTSTRAP, BOOTOUT, KICKSTART, PRINT = "bootstrap", "bootout", "kickstart", "print"

# How long the owner waits, at most, for a press of Start to become an answer. The backend
# imports the SDK, the Shopify client and whisper's bindings before it binds the port; on a
# cold Mac that is tens of seconds, and giving up at ten would report a failure that was
# only impatience.
START_WAIT_S = 90.0
# Stopping is quick or it is wrong. launchd sends SIGTERM and the backend has a shutdown
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
    appliance layer is allowed to do to the Mac, and one place to substitute in a test."""

    def __call__(self, argv: list[str], *, timeout_s: float = 60.0) -> Ran:
        raise NotImplementedError


class Subprocesses(Runner):
    def __call__(self, argv: list[str], *, timeout_s: float = 60.0) -> Ran:
        try:
            out = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout_s)  # noqa: S603 — a fixed verb list
        except FileNotFoundError:
            # The honest answer on anything that is not a Mac, and on a Mac whose PATH has
            # been mangled. 127 is the shell's own number for it and belongs in `developer`.
            return Ran(tuple(argv), 127, "", f"{argv[0]}: not found")
        except (OSError, subprocess.SubprocessError) as exc:
            return Ran(tuple(argv), 1, "", f"{type(exc).__name__}: {exc}")
        return Ran(tuple(argv), out.returncode, out.stdout or "", out.stderr or "")


# There was a `Scripted(Runner)` here: a double whose default answer was "0, and nothing said".
# It is gone, and its going is the point. A double that succeeds unconditionally cannot fail,
# so every test built on it measured the double rather than the product — which is how Start
# came to kickstart jobs launchd did not have loaded and nothing went red for it. The double
# the tests use now is tests/fake_launchd.py, which holds launchd's own two facts (which
# labels are loaded, which of those have a process) and enforces the rule that follows from
# them: only bootstrap loads a job, and kickstart on a job that is not loaded FAILS.


@dataclass
class Machine:
    """Everything this layer asks of, or does to, the Mac. A test supplies one of these and
    every branch below becomes reachable without a Mac, a launchd or a listening socket."""

    runner: Runner = field(default_factory=Subprocesses)
    # fresh -> the /health document, or None when nothing is answering.
    read_health: Callable[[bool], dict | None] = lambda fresh: None
    # Is anything at all holding the port? A backend that has bound the port but cannot serve
    # /health is a different state from one that is not there, and the difference is what
    # tells a stuck copy from a stopped one.
    port_open: Callable[[], bool] = lambda: False
    # Tailscale's HTTPS route for the tablet: (host, note).
    ensure_route: Callable[[], tuple[str | None, str]] = lambda: (None, "not asked")
    is_macos: Callable[[], bool] = lc.is_macos
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


# The owner reads the first sentence. The second says what happens next, or what he can do.
# Neither ever contains an exit status, a stack trace or a path: those go in `developer`,
# which the app puts behind an expansion. tests/test_service.py holds every row here to that.
PROBLEMS: dict[str, tuple[str, str]] = {
    # The one row here that names a typed command, and deliberately. Everything else the
    # owner can reach is a button; building a Python environment is minutes of downloading
    # that fails in a dozen ways, and it happens once, on the day the Mac is set up. §5.2's
    # rule is that the RECOVERY from a stopped appliance is not a command line — not that the
    # first-time install of a toolchain can be pretended away.
    "python_missing": (
        "CROOKS OS couldn't start. Python environment unavailable.",
        "The Mac needs its Python side installed once, with: make venv",
    ),
    "repo_missing": (
        "CROOKS OS couldn't start. Its files are not where this Mac expects them.",
        "The project folder has been moved or renamed. Put it back where it was.",
    ),
    "not_macos": (
        "CROOKS OS couldn't start. This machine is not the Mac.",
        "The background service is a macOS login service, and this machine cannot register one.",
    ),
    "supervisor_missing": (
        "CROOKS OS couldn't start. The Mac's login-service manager did not answer.",
        "Nothing was changed. Restarting the Mac is the first thing to try.",
    ),
    "install_refused": (
        "CROOKS OS couldn't start. The Mac refused to register it as a login service.",
        "Nothing was changed. The detail below is what the Mac said.",
    ),
    "start_refused": (
        "CROOKS OS couldn't start. The Mac refused to start the service.",
        "Nothing was changed. The detail below is what the Mac said.",
    ),
    "port_busy": (
        "CROOKS OS couldn't start. Something else is already using its address.",
        "It is not CROOKS OS, so nothing here will close it. Restarting the Mac clears it.",
    ),
    "health_timeout": (
        "CROOKS OS started but never became ready.",
        "It is running and not answering. The log named below says why; Stop, then Start, is the first thing to try.",
    ),
    "stop_refused": (
        "CROOKS OS is still running.",
        "The Mac was asked to stop it and it has not. The detail below is what the Mac said.",
    ),
    # Distinct from stop_refused on purpose. "It was asked and it has not" is a sentence about
    # a manager that said no; 127 is a manager that was never reached, so nothing was asked of
    # anything and nothing was changed. Telling the owner the first when the second happened
    # sends him looking for a stuck service that does not exist.
    "stop_supervisor_missing": (
        "CROOKS OS could not be stopped. The Mac's login-service manager did not answer.",
        "Nothing was changed and CROOKS OS is still running. Restarting the Mac is the first thing to try.",
    ),
    "not_supervised": (
        "CROOKS OS is running in a Terminal window rather than as a login service.",
        "This cannot stop or restart it; the window it is running in can. Close that window, then press Start.",
    ),
}

# Words that mean a sentence was written for a developer and not for the owner. The test
# suite scans every human line above for them, because the failure this layer exists to
# prevent is a menu bar that says "Process returned exit status 127".
DEVELOPERESE = (
    "exit status", "exit code", "returncode", "return code", "traceback", "errno",
    "stderr", "stdout", "exception", "none", "null", "subprocess", "launchctl",
    "posix", "stack", "0x", "http 5", "socket",
)


def problem(code: str, developer: str = "", **extra) -> dict:
    """One failure, in two registers. `human` and `fix` are the owner's; `developer` is the
    expansion field, and is the only place an exit status or a log path ever appears."""
    human, fix = PROBLEMS[code]
    return {"code": code, "human": human, "fix": fix, "developer": str(developer or "")[:800], **extra}


# --------------------------------------------------------------------------- launchd


def printed_fields(text: str) -> dict[str, str]:
    """`launchctl print` answers with an indented tree of `key = value`. Only the top few
    matter here — state, pid, last exit code — and they are read by name rather than by
    position, because the shape of that tree differs between macOS versions."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().lower(), value.strip()
        if key and key not in out:
            out[key] = value
    return out


class Launchd:
    """The login-service manager, as this layer uses it. Five verbs and no more: print,
    bootstrap, bootout, kickstart, and writing the plist that bootstrap reads.

    NOT EXERCISED ON THIS MACHINE. Linux has no launchctl, so what the tests below can check
    is which command would be run, with which arguments, in which order, and what this layer
    concludes from each answer — never that macOS accepts them.
    """

    def __init__(self, machine: Machine, *, agent_dir: Path | None = None, root: Path | None = None,
                 uid: int | None = None) -> None:
        self.machine = machine
        self.root = Path(root) if root else ROOT
        self.agent_dir = Path(agent_dir) if agent_dir else (Path.home() / "Library" / "LaunchAgents")
        self._uid = uid

    @property
    def uid(self) -> int:
        return self._uid if self._uid is not None else lc.uid()

    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    def plist_path(self, label: str) -> Path:
        return self.agent_dir / f"{label}.plist"

    def installed(self, label: str) -> bool:
        """The plist FILE is on disk. This is "installed" and it is never "running": a
        bootout unloads the job and leaves the file exactly where it was, so a Stop followed
        by a Start finds this True with launchd holding nothing at all."""
        return self.plist_path(label).exists()

    def loaded(self, label: str) -> bool:
        """launchd has the job. The only thing that knows this is launchd, which is why it is
        asked rather than inferred from the disk. `kickstart` on a job that is not loaded does
        not start it — it exits 3, "Could not find service" — so this is the question that has
        to be right before anything is kicked."""
        return bool(self.state(label)["loaded"])

    def rendered(self, values: dict[str, str] | None = None) -> dict[str, str]:
        """The agents' plists with this checkout's paths filled in. One renderer, shared with
        `make install`, so a Start button and a typed install cannot write different files."""
        values = values or lc.plist_values(root=self.root, python=self.root / ".venv" / "bin" / "python")
        return {label: lc.render((lc.LAUNCHD_DIR / filename).read_text(encoding="utf-8"), values)
                for label, filename in lc.AGENTS.items()}

    def state(self, label: str) -> dict:
        """What the Mac says about one agent. `loaded` means launchd knows it; `pid` means it
        is actually a process right now. The two come apart exactly when it matters: a service
        that crashes on boot is loaded forever and has a pid for a second at a time."""
        ran = self.machine.runner([LAUNCHCTL, PRINT, f"{self.domain}/{label}"], timeout_s=20)
        row = {"label": label, "installed": self.installed(label), "loaded": False,
               "pid": None, "last_exit_code": None, "detail": ""}
        if not ran.ok:
            # `print` on an unknown label exits non-zero. That is "not loaded", not an error.
            row["detail"] = ran.said[:200]
            return row
        fields = printed_fields(ran.stdout)
        row["loaded"] = True
        for key in ("pid",):
            if fields.get(key, "").isdigit():
                row[key] = int(fields[key])
        code = fields.get("last exit code", "")
        if code.lstrip("-").isdigit():
            row["last_exit_code"] = int(code)
        row["detail"] = fields.get("state", "")
        return row

    def write_agents(self) -> list[tuple[str, Path]]:
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        written = []
        for label, body in self.rendered().items():
            target = self.plist_path(label)
            # launchd will not reload a changed plist in place, so the old copy goes first.
            self.machine.runner([LAUNCHCTL, BOOTOUT, f"{self.domain}/{label}"], timeout_s=30)
            target.write_text(body, encoding="utf-8")
            written.append((label, target))
        return written

    def bootstrap(self, label: str) -> Ran:
        ran = self.machine.runner([LAUNCHCTL, BOOTSTRAP, self.domain, str(self.plist_path(label))], timeout_s=30)
        if ran.ok:
            return ran
        # Older macOS does not have `bootstrap`. The legacy verb does the same job.
        return self.machine.runner([LAUNCHCTL, "load", "-w", str(self.plist_path(label))], timeout_s=30)

    def bootout(self, label: str) -> Ran:
        return self.machine.runner([LAUNCHCTL, BOOTOUT, f"{self.domain}/{label}"], timeout_s=30)

    def kickstart(self, label: str) -> Ran:
        # -k: stop it first if it is running. One verb for start and for restart, which is
        # why `make restart` and the Start button cannot drift apart.
        return self.machine.runner([LAUNCHCTL, KICKSTART, "-k", f"{self.domain}/{label}"], timeout_s=60)


def supervisor(machine: Machine, *, root: Path | None = None) -> Launchd:
    """The seam control.py and update.py use to get this platform's supervisor. The server's
    twin, scripts/service_linux.py, exposes the same name for systemd."""
    return Launchd(machine, root=root)


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

# The sentence this whole file exists to be able to say truthfully.
WINDOW_NOTE = (
    "Closing the CROOKS Control window does not stop CROOKS OS. CROOKS OS is a background "
    "service the Mac starts at login; the app is the dial, not the boiler. Every line above "
    "is read from the service itself — the port, /health and the Mac's login-service "
    "manager — and never from whether this app happens to be open."
)

_SENTENCE = {
    RUNNING: "CROOKS OS is running as a login service. Closing this window will not stop it.",
    RUNNING_WINDOW: "CROOKS OS is running, but in a Terminal window rather than as a login service. Closing that window WILL stop it.",
    UNHEALTHY: "CROOKS OS is running, but part of it is not working.",
    STARTING: "CROOKS OS is starting.",
    STALE: "CROOKS OS is not answering, but something is still holding its address.",
    CRASH_LOOPING: "CROOKS OS keeps stopping as soon as it starts.",
    STOPPED: "CROOKS OS is stopped.",
    NOT_INSTALLED: "CROOKS OS is not set up on this Mac yet.",
}

# The one word the app colours a dot with. Deliberately coarser than the state above: four
# facts about a boiler — on, coming on, stuck, off.
_PLAIN = {
    RUNNING: "running", RUNNING_WINDOW: "running", UNHEALTHY: "running",
    STARTING: "starting", STALE: "stuck",
    CRASH_LOOPING: "stopped", STOPPED: "stopped", NOT_INSTALLED: "stopped",
}


def running_state(*, answering: bool, health: dict | None, agents: list[dict], unwell: list[str] | None = None) -> dict:
    """Is CROOKS OS running? Three inputs, and there is deliberately no fourth.

    `answering` is the port; `health` is what /health said; `agents` is what the Mac's
    login-service manager says about each agent. Whether the Control app is open is not among
    them and cannot be, which is the whole point: the app closing can no more change this
    answer than closing the airing cupboard door can turn the boiler off.

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


def lifecycle(machine: Machine, launchd: Launchd, *, port: int, health=_UNREAD,
              unwell: list[str] | None = None, ask_launchd: bool = True) -> dict:
    """The whole lifecycle picture: the verdict, the agents behind it, and the sentence about
    the window. `health` is passed in when the caller has already read it — a status poll
    reads /health once and hands it here rather than doubling the request. The default is a
    sentinel rather than None because None is itself an answer: "I asked, and nothing is
    there", which must not be mistaken for "nobody has asked yet"."""
    if health is _UNREAD:
        health = machine.read_health(False)
    agents = [launchd.state(label) for label in lc.AGENTS] if ask_launchd else []
    verdict = running_state(answering=machine.port_open() if health is None else True,
                            health=health, agents=agents, unwell=unwell)
    return {**verdict, "agents": agents, "port": port, "window": WINDOW_NOTE,
            "logs": str(machine.log_dir)}


# --------------------------------------------------------------------------- preflight


def preflight(*, root: Path | None = None, machine: Machine | None = None) -> dict | None:
    """Everything that must be true before a Start can possibly work, in the order in which
    a failure is most likely. Returns a problem or None."""
    root = Path(root) if root else ROOT
    if not (root / "app" / "main.py").exists():
        return problem("repo_missing", f"{root}/app/main.py is not there")
    python = root / ".venv" / "bin" / "python"
    if not python.exists():
        return problem("python_missing", f"no interpreter at {python}")
    if machine is not None and not machine.is_macos():
        return problem("not_macos", f"sys.platform is {sys.platform!r}; launchd is macOS only")
    return None


def wait_for_health(machine: Machine, *, timeout_s: float, still_starting: Callable[[], bool] | None = None) -> dict | None:
    """Poll /health until it answers or the time is up. This — not launchctl's exit code — is
    what a successful Start is. `still_starting` lets the wait give up early when the thing
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


def _refusal(ran: Ran, label: str) -> dict:
    """launchctl said no. Which no it was matters: 127 is the manager not being there at all
    (a Mac whose PATH has been broken, or a machine that is not a Mac), and every other code
    is launchd having an opinion. The owner reads a different sentence for each."""
    if ran.returncode == 127:
        return problem("supervisor_missing", f"{label}: {ran.said}")
    return problem("start_refused", f"{label}: {ran.said}")


def stage(name: str, state: str, detail: str = "") -> dict:
    return {"stage": name, "state": state, "detail": str(detail)[:300]}


def _outcome(stages: list[dict], *, lifecycle_after: dict, problem_: dict | None, next_: str, human: str, **extra) -> dict:
    return {"stages": stages, "problem": problem_, "lifecycle": lifecycle_after,
            "next": next_, "human": human, "ok": problem_ is None, **extra}


# --------------------------------------------------------------------------- start


def start(machine: Machine, launchd: Launchd, *, port: int, wait_s: float = START_WAIT_S, route: bool = True) -> dict:
    """Turn CROOKS OS on, from wherever it is — running, stopped, never installed, or stuck.

    The ladder, in order, and every rung is a state the Mac is actually found in:

      1  already answering        -> say so and touch nothing
      2  the files or the venv are not there -> a sentence the owner can act on
      3  stuck on the port        -> ours, so clear it; not ours, so refuse to fight it
      4  not installed as a login service -> install it. This is the rung that makes Start
         work on a Mac where nothing has ever been typed into a Terminal.
      5  kickstart
      6  the tablet's HTTPS route (a warning if it fails; the Mac is still up)
      7  /health, read back. ONLY this makes the Start a success.
    """
    stages: list[dict] = []
    before = lifecycle(machine, launchd, port=port)
    if before["state"] in (RUNNING, RUNNING_WINDOW, UNHEALTHY):
        stages.append(stage("check", "skip", before["human"]))
        return _outcome(stages, lifecycle_after=before, problem_=None,
                        next_="already_running", human=before["human"], before=before)

    bad = preflight(root=launchd.root, machine=machine)
    if bad is not None:
        stages.append(stage("check", "fail", bad["code"]))
        return _outcome(stages, lifecycle_after=before, problem_=bad, next_="blocked", human=bad["human"], before=before)
    stages.append(stage("check", "ok", before["human"]))

    if before["state"] == STALE:
        # Something has the port and will not answer. If it is one of ours, stopping it is
        # exactly the right thing and the owner should not have to know it happened. If it is
        # not ours, killing it is not this layer's business — we do not know what it is.
        if not any(agent.get("loaded") or agent.get("installed") for agent in before["agents"]):
            held = problem("port_busy", f"127.0.0.1:{port} is accepting connections and /health does not answer; no CROOKS agent is loaded, so this is not CROOKS OS")
            stages.append(stage("clear", "fail", "the address is held by something that is not CROOKS OS"))
            return _outcome(stages, lifecycle_after=before, problem_=held, next_="blocked", human=held["human"], before=before)
        for label in lc.AGENTS:
            launchd.bootout(label)
        cleared = wait_for_stop(machine, timeout_s=STOP_WAIT_S)
        stages.append(stage("clear", "ok" if cleared else "warn",
                            "the stuck copy was stopped" if cleared else "it is still holding the address; starting anyway"))

    # WHETHER LAUNCHD HAS THE JOB, asked of launchd. Not whether the plist file exists: the
    # file is written once and stays for ever, and `stop` boots the job out without touching
    # it. Reading the file here is why Stop-then-Start — the single most ordinary sequence an
    # owner performs — did nothing: the file was there, so this said "already registered",
    # skipped the bootstrap, and kickstarted a job launchd had never heard of.
    #
    # Asked FRESH, after the stale-copy clearing above rather than from `before`, because that
    # clearing boots the agents out and so changes the very answer being read.
    unloaded = [label for label in lc.AGENTS if not launchd.loaded(label)]
    if unloaded:
        # write_agents boots each label out before rewriting it, so every label is unloaded by
        # the time bootstrap runs and none of them is bootstrapped twice.
        launchd.write_agents()
        for label in lc.AGENTS:
            ran = launchd.bootstrap(label)
            if not ran.ok:
                # Which no it was, again. 127 is the manager not being there — a broken PATH —
                # and "the Mac refused to register it" is a sentence about a launchd that had
                # an opinion, which sends the owner looking for a permission problem.
                refused = (problem("supervisor_missing", f"{label}: {ran.said}")
                           if ran.returncode == 127
                           else problem("install_refused", f"{label}: {ran.said}"))
                stages.append(stage("install", "fail", label))
                return _outcome(stages, lifecycle_after=lifecycle(machine, launchd, port=port),
                                problem_=refused, next_="blocked", human=refused["human"], before=before)
        stages.append(stage("install", "ok", f"{len(unloaded)} login service(s) registered"))
    else:
        stages.append(stage("install", "skip", "already registered as a login service"))

    for label in lc.AGENTS:
        ran = launchd.kickstart(label)
        if not ran.ok:
            refused = _refusal(ran, label)
            stages.append(stage("start", "fail", label))
            return _outcome(stages, lifecycle_after=lifecycle(machine, launchd, port=port),
                            problem_=refused, next_="blocked", human=refused["human"], before=before)
    stages.append(stage("start", "ok", f"{len(lc.AGENTS)} service(s) started"))

    if route:
        host, note = machine.ensure_route()
        stages.append(stage("route", "ok" if host else "warn", f"https://{host}/" if host else note))

    def still_starting() -> bool:
        """Is there still something to wait for? A service launchd has given up on — no pid
        and no longer loaded — is never going to answer, and waiting the remaining eighty
        seconds for it teaches the owner that Start takes a minute and a half to fail."""
        return any((agent.get("pid") or agent.get("loaded")) for agent in (launchd.state(label) for label in lc.AGENTS))

    health = wait_for_health(machine, timeout_s=wait_s, still_starting=still_starting)
    after = lifecycle(machine, launchd, port=port, health=health)
    if health is None:
        # §26, the one that matters: launchctl exited 0 and the service is NOT up. This is
        # the single most likely place for this layer to have lied, so it is the one place
        # where nothing but /health counts.
        timed_out = problem("health_timeout", f"no answer on 127.0.0.1:{port}/health within {wait_s:.0f}s; see {machine.log_dir}/assistant.err.log")
        stages.append(stage("verify", "fail", f"nothing answered within {wait_s:.0f}s"))
        return _outcome(stages, lifecycle_after=after, problem_=timed_out, next_="blocked", human=timed_out["human"], before=before)
    stages.append(stage("verify", "ok", lc.summarise_health(health)))
    return _outcome(stages, lifecycle_after=after, problem_=None, next_="running",
                    human="CROOKS OS is running.", before=before)


# --------------------------------------------------------------------------- stop


STOP_NOTE = (
    "The login service stays registered, so CROOKS OS starts again the next time this Mac is "
    "logged in — which is what an appliance should do. `make uninstall` takes it off for good."
)


def stop(machine: Machine, launchd: Launchd, *, port: int, wait_s: float = STOP_WAIT_S) -> dict:
    """Turn CROOKS OS off, and prove it went off.

    Nothing here reports success from launchctl's exit code. bootout returns 0 for a label
    that was not loaded, and it returns 0 the instant the signal is sent — neither of which
    is the fact the owner is asking about, which is whether the thing has stopped.
    """
    stages: list[dict] = []
    before = lifecycle(machine, launchd, port=port)
    if before["state"] in (STOPPED, NOT_INSTALLED, CRASH_LOOPING) and not before["answering"]:
        stages.append(stage("check", "skip", before["human"]))
        return _outcome(stages, lifecycle_after=before, problem_=None, next_="already_stopped",
                        human="CROOKS OS is already stopped.", before=before, note=STOP_NOTE)
    if before["state"] == RUNNING_WINDOW:
        # `make up` ran it as a child of a Terminal. bootout has nothing to boot out, and
        # waiting twenty seconds for a port that nobody here can free would end in
        # "CROOKS OS is still running" — true, and useless, and hiding the actual reason.
        refused = problem("not_supervised", f"127.0.0.1:{port} is answering but no CROOKS agent holds a pid; it is not launchd's to stop")
        stages.append(stage("check", "fail", "it is not running as a login service"))
        return _outcome(stages, lifecycle_after=before, problem_=refused, next_="blocked",
                        human=refused["human"], before=before, note=STOP_NOTE)
    said: list[str] = []
    asked = 0
    for label in lc.AGENTS:
        ran = launchd.bootout(label)
        if ran.returncode == 127:
            # The manager is not there at all. Nothing was asked of anything, and this is
            # known NOW — on the first command — rather than twenty seconds later when the
            # port is found still held and the wrong sentence ("it was asked and it has not")
            # gets printed over it. A launchctl that is not there is not a successful stop.
            absent = problem("stop_supervisor_missing", f"{label}: {ran.said}")
            stages.append(stage("stop", "fail", "the Mac's login-service manager did not answer"))
            return _outcome(stages, lifecycle_after=lifecycle(machine, launchd, port=port),
                            problem_=absent, next_="blocked", human=absent["human"],
                            before=before, note=STOP_NOTE)
        if ran.ok:
            asked += 1
        elif ran.said:
            said.append(f"{label}: {ran.said}")
    # The number the owner reads is the number of services the Mac was really asked about. A
    # bootout of a label launchd does not hold exits 3 and asks nothing.
    stages.append(stage("stop", "ok" if asked else "warn", f"{asked} service(s) asked to stop"))
    went = wait_for_stop(machine, timeout_s=wait_s)
    after = lifecycle(machine, launchd, port=port)
    if not went:
        refused = problem("stop_refused", "; ".join(said) or f"127.0.0.1:{port} is still accepting connections {wait_s:.0f}s after bootout")
        stages.append(stage("verify", "fail", "it is still answering"))
        return _outcome(stages, lifecycle_after=after, problem_=refused, next_="blocked", human=refused["human"], before=before, note=STOP_NOTE)
    stages.append(stage("verify", "ok", "nothing is answering on the port"))
    return _outcome(stages, lifecycle_after=after, problem_=None, next_="stopped",
                    human="CROOKS OS is stopped.", before=before, note=STOP_NOTE)


# --------------------------------------------------------------------------- restart


def restart(machine: Machine, launchd: Launchd, *, port: int, wait_s: float = START_WAIT_S, route: bool = True) -> dict:
    """Stop and start in one press, and — the part `make restart` never did — read /health
    back afterwards and say whether it came up.

    A restart of a service that was never installed is a start, so it falls through to one
    rather than telling the owner that there is nothing to restart. That is the difference
    between an appliance and a tool.

    A backend running in a Terminal window is the one thing this cannot restart, and it says
    so rather than kickstarting agents that are not the process the owner can see. Getting
    that wrong would be the worst failure available here: the restore half of a failed update
    calls this, and a restart that reported success without restarting anything would leave
    the old code running against rolled-back files and call it recovered.
    """
    before = lifecycle(machine, launchd, port=port)
    if before["state"] == RUNNING_WINDOW:
        refused = problem("not_supervised", f"127.0.0.1:{port} is answering but no CROOKS agent holds a pid; a kickstart would not touch it")
        return _outcome([stage("check", "fail", "it is not running as a login service")],
                        lifecycle_after=before, problem_=refused, next_="blocked",
                        human=refused["human"], before=before)
    # The same fact start() reads, and for the same reason: a restart of a job launchd does
    # not have is a start, and kickstarting it would fail with "Could not find service". The
    # agents were read a moment ago by lifecycle(), so they are read from there rather than
    # asking launchd the same question twice.
    if any(not row.get("loaded") for row in before["agents"]) or not before["agents"]:
        out = start(machine, launchd, port=port, wait_s=wait_s, route=route)
        out["stages"].insert(0, stage("check", "skip", "not registered as a login service yet, so this is a start"))
        out["before"] = before
        return out
    bad = preflight(root=launchd.root, machine=machine)
    if bad is not None:
        return _outcome([stage("check", "fail", bad["code"])], lifecycle_after=before,
                        problem_=bad, next_="blocked", human=bad["human"], before=before)
    stages = [stage("check", "ok", before["human"])]
    for label in lc.AGENTS:
        ran = launchd.kickstart(label)
        if not ran.ok:
            refused = _refusal(ran, label)
            stages.append(stage("restart", "fail", label))
            return _outcome(stages, lifecycle_after=lifecycle(machine, launchd, port=port),
                            problem_=refused, next_="blocked", human=refused["human"], before=before)
    stages.append(stage("restart", "ok", f"{len(lc.AGENTS)} service(s) restarted"))
    if route:
        host, note = machine.ensure_route()
        stages.append(stage("route", "ok" if host else "warn", f"https://{host}/" if host else note))
    health = wait_for_health(machine, timeout_s=wait_s)
    after = lifecycle(machine, launchd, port=port, health=health)
    if health is None:
        timed_out = problem("health_timeout", f"no answer on 127.0.0.1:{port}/health within {wait_s:.0f}s after a restart; see {machine.log_dir}/assistant.err.log")
        stages.append(stage("verify", "fail", f"nothing answered within {wait_s:.0f}s"))
        return _outcome(stages, lifecycle_after=after, problem_=timed_out, next_="blocked", human=timed_out["human"], before=before)
    stages.append(stage("verify", "ok", lc.summarise_health(health)))
    return _outcome(stages, lifecycle_after=after, problem_=None, next_="running",
                    human="CROOKS OS restarted and is running.", before=before)
