#!/usr/bin/env python3
"""The lifecycle of CROOKS OS on the Linux server: start it, stop it, restart it, and say
truthfully which of those it is in.

The twin of scripts/service.py, which does this on the Mac through launchd. Same envelope,
same seam — a Machine whose commands a test can replace, so every branch below is reachable
on a machine with no systemd and no listening socket — and the same rule, which is the whole
reason either file exists:

    a start or a restart succeeds only when /health answers, never because systemctl
    exited 0. `systemctl restart` returns 0 for a service that then dies on its first
    import. §26: a process reported started is not the same fact as genuinely healthy,
    and only the second one is worth a green light.

What differs is the supervisor, and only the supervisor. systemd holds one service where
launchd holds two agents; "installed" is a file in /etc/systemd/system, "loaded" is what
`systemctl show` reports, and the verbs are enable, stop and restart rather than bootstrap,
bootout and kickstart. Nothing here knows about plists and nothing in service.py knows about
systemd. scripts/control.py picks one of the two by platform and the app draws the same panel
either way: the state vocabulary, the verdict logic and the shape of every document come from
service.py unchanged, so the two cannot drift in what they mean.

Writing the service file needs root. The service already runs as root on this host (see
deploy/systemd/crooks-assistant.service and docs/DEPLOY_LINUX.md) and so does `make install`.
A Start pressed by a login that cannot write it is refused in the owner's words, and nothing
is half-done.

NOT EXERCISED AGAINST A REAL SYSTEMD BY THE TESTS. What they check is which command would be
run, with which arguments, in which order, and what this layer concludes from each answer.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import launch_common as lc  # noqa: E402

from scripts import service as base  # noqa: E402

# Re-exported, so a caller that dispatches by platform needs one name for each thing.
Machine = base.Machine
Ran = base.Ran
Runner = base.Runner
Subprocesses = base.Subprocesses
START_WAIT_S = base.START_WAIT_S
STOP_WAIT_S = base.STOP_WAIT_S
STATES = base.STATES
RUNNING, RUNNING_WINDOW, UNHEALTHY, STARTING = (
    base.RUNNING, base.RUNNING_WINDOW, base.UNHEALTHY, base.STARTING,
)
STALE, CRASH_LOOPING, STOPPED, NOT_INSTALLED = (
    base.STALE, base.CRASH_LOOPING, base.STOPPED, base.NOT_INSTALLED,
)
stage = base.stage
wait_for_health = base.wait_for_health
wait_for_stop = base.wait_for_stop

# The verbs, in one place, so a grep for what this layer can do to the server is a short list.
SYSTEMCTL = "systemctl"
SHOW, IS_ENABLED, ENABLE, STOP, RESTART, DAEMON_RELOAD = (
    "show", "is-enabled", "enable", "stop", "restart", "daemon-reload",
)
SHOW_PROPERTIES = "--property=LoadState,ActiveState,SubState,MainPID,ExecMainStatus,Result,NRestarts"


# --------------------------------------------------------------------------- human errors

# The same two registers as service.PROBLEMS, for the same reader: "the server" where the
# Mac's table says "the Mac", "service" where it says "login service", and nothing a
# developer wrote. tests/test_service_linux.py holds every row here to that.
PROBLEMS: dict[str, tuple[str, str]] = {
    "python_missing": (
        "CROOKS OS couldn't start. Python environment unavailable.",
        "The server needs its Python side installed once, with: make venv",
    ),
    "repo_missing": (
        "CROOKS OS couldn't start. Its files are not where this server expects them.",
        "The project folder has been moved or renamed. Put it back where it was.",
    ),
    "not_linux": (
        "CROOKS OS couldn't start. This machine is not the server.",
        "The background service is registered with the server's service manager, and this machine does not have one.",
    ),
    "supervisor_missing": (
        "CROOKS OS couldn't start. The server's service manager did not answer.",
        "Nothing was changed. Restarting the server is the first thing to try.",
    ),
    "install_refused": (
        "CROOKS OS couldn't start. The server refused to register it as a service.",
        "Nothing was changed. The detail below is what the server said.",
    ),
    "permission_refused": (
        "CROOKS OS couldn't start. This login is not allowed to register the service.",
        "Nothing was changed. The service is registered from the server's administrator login.",
    ),
    "start_refused": (
        "CROOKS OS couldn't start. The server refused to start the service.",
        "Nothing was changed. The detail below is what the server said.",
    ),
    "port_busy": (
        "CROOKS OS couldn't start. Something else is already using its address.",
        "It is not CROOKS OS, so nothing here will close it. Restarting the server clears it.",
    ),
    "health_timeout": (
        "CROOKS OS started but never became ready.",
        "It is running and not answering. The log named below says why; Stop, then Start, is the first thing to try.",
    ),
    "stop_refused": (
        "CROOKS OS is still running.",
        "The server was asked to stop it and it has not. The detail below is what the server said.",
    ),
    "stop_supervisor_missing": (
        "CROOKS OS could not be stopped. The server's service manager did not answer.",
        "Nothing was changed and CROOKS OS is still running. Restarting the server is the first thing to try.",
    ),
    "not_supervised": (
        "CROOKS OS is running in a terminal session rather than as a service.",
        "This cannot stop or restart it; the session it is running in can. End that session, then press Start.",
    ),
}

# service.DEVELOPERESE, plus the words that are developerese on this platform in particular.
DEVELOPERESE = (*base.DEVELOPERESE, "systemctl", "journalctl", "systemd", "unit")


def problem(code: str, developer: str = "", **extra) -> dict:
    """One failure, in two registers. `human` and `fix` are the owner's; `developer` is the
    expansion field, and is the only place an exit status or a journal command ever appears."""
    human, fix = PROBLEMS[code]
    return {"code": code, "human": human, "fix": fix, "developer": str(developer or "")[:800], **extra}


def shown_fields(text: str) -> dict[str, str]:
    """`systemctl show` answers `Key=value` lines. Read by name, lower-cased, first wins."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().lower(), value.strip()
        if key and key not in out:
            out[key] = value
    return out


# --------------------------------------------------------------------------- systemd


class Systemd:
    """The server's service manager, as this layer uses it. Six verbs and no more: show,
    is-enabled, enable, stop, restart, and writing the service file that enable reads."""

    def __init__(self, machine: Machine, *, root: Path | None = None, unit: str | None = None,
                 unit_dir: Path | None = None, render: Callable[[], str] | None = None,
                 is_linux: Callable[[], bool] | None = None) -> None:
        self.machine = machine
        self.root = Path(root) if root else ROOT
        self.unit = unit or lc.SERVICE_UNIT
        self.unit_dir = Path(unit_dir) if unit_dir else lc.SYSTEMD_DIR
        self._render = render
        self.is_linux = is_linux or lc.is_linux

    @property
    def unit_path(self) -> Path:
        return self.unit_dir / self.unit

    def installed(self) -> bool:
        """The service FILE is on disk. Installed is never running: `systemctl stop` leaves
        the file exactly where it was."""
        return self.unit_path.exists()

    def loaded(self) -> bool:
        """systemd has the service. Asked of systemd, not inferred from the disk: a file
        written without a daemon-reload is a service systemd has never heard of."""
        return bool(self.state()["loaded"])

    def enabled(self) -> bool:
        """Will start at boot. `is-enabled` prints the word and exits 0 only for that."""
        ran = self.machine.runner([SYSTEMCTL, IS_ENABLED, self.unit], timeout_s=20)
        return ran.ok and ran.stdout.strip() == "enabled"

    def rendered(self) -> str:
        """This checkout's service file, from the same renderer `make install` uses, so a
        Start and a typed install cannot write different files."""
        if self._render is not None:
            return self._render()
        from scripts import install_systemd

        return install_systemd.rendered_unit()

    def state(self) -> dict:
        """What the server says about the service, in the row shape service.running_state
        reads. `loaded` means systemd knows it; `pid` means it is a process right now;
        `last_exit_code` is how the last main process ended, which is what tells a service
        that dies on every start from one that is simply stopped. A stop that ended by
        signal is a successful stop, not a crash, so Result=success reads as 0."""
        ran = self.machine.runner([SYSTEMCTL, SHOW, self.unit, SHOW_PROPERTIES], timeout_s=20)
        row = {"label": self.unit, "installed": self.installed(), "loaded": False,
               "pid": None, "last_exit_code": None, "detail": ""}
        if not ran.ok:
            row["detail"] = ran.said[:200]
            return row
        fields = shown_fields(ran.stdout)
        row["loaded"] = fields.get("loadstate") == "loaded"
        pid = fields.get("mainpid", "")
        if pid.isdigit() and int(pid) > 0:
            row["pid"] = int(pid)
        code = fields.get("execmainstatus", "")
        if fields.get("result") == "success":
            row["last_exit_code"] = 0
        elif code.lstrip("-").isdigit():
            row["last_exit_code"] = int(code)
        row["detail"] = "/".join(
            part for part in (fields.get("activestate", ""), fields.get("substate", "")) if part
        )
        return row

    def write_unit(self) -> Path:
        """Render and install the service file, then have systemd read it. Raises
        PermissionError where this login may not write it; the caller turns that into the
        owner's sentence rather than a traceback."""
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        self.unit_path.write_text(self.rendered(), encoding="utf-8")
        self.unit_path.chmod(0o644)
        self.machine.runner([SYSTEMCTL, DAEMON_RELOAD], timeout_s=60)
        return self.unit_path

    def enable(self) -> Ran:
        return self.machine.runner([SYSTEMCTL, ENABLE, self.unit], timeout_s=30)

    def stop(self) -> Ran:
        return self.machine.runner([SYSTEMCTL, STOP, self.unit], timeout_s=30)

    def restart(self) -> Ran:
        # start-or-restart in one verb, which is why `make restart` and the Start button
        # cannot drift apart.
        return self.machine.runner([SYSTEMCTL, RESTART, self.unit], timeout_s=60)


def supervisor(machine: Machine, *, root: Path | None = None) -> Systemd:
    """The seam control.py and update.py use to get this platform's supervisor."""
    return Systemd(machine, root=root)


# --------------------------------------------------------------------------- what state is it in


WINDOW_NOTE = (
    "CROOKS OS on this server is a background service that starts at boot and comes back on "
    "its own if it stops. Every line above is read from the service itself — the port, /health "
    "and the server's service manager — and never from whether any window happens to be open."
)

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


def running_state(*, answering: bool, health: dict | None, agents: list[dict],
                  unwell: list[str] | None = None) -> dict:
    """service.running_state's verdict — the same three inputs, the same decision, one
    source of truth for what the states mean — with the server's sentence for each state."""
    verdict = base.running_state(answering=answering, health=health, agents=agents, unwell=unwell)
    if verdict["state"] != UNHEALTHY:
        verdict["human"] = _SENTENCE[verdict["state"]]
    return verdict


_UNREAD = base._UNREAD


def lifecycle(machine: Machine, systemd: Systemd, *, port: int, health=_UNREAD,
              unwell: list[str] | None = None, ask_launchd: bool = True) -> dict:
    """The whole lifecycle picture, in the shape service.lifecycle produces. `ask_launchd` is
    the caller's word for "ask the supervisor" and is kept so both modules take the same
    keyword; here it costs one `systemctl show`."""
    if health is _UNREAD:
        health = machine.read_health(False)
    agents = [systemd.state()] if ask_launchd else []
    verdict = running_state(answering=machine.port_open() if health is None else True,
                            health=health, agents=agents, unwell=unwell)
    return {**verdict, "agents": agents, "port": port, "window": WINDOW_NOTE,
            "logs": str(machine.log_dir)}


# --------------------------------------------------------------------------- preflight


def preflight(*, root: Path | None = None, systemd: Systemd | None = None) -> dict | None:
    """Everything that must be true before a Start can possibly work. A problem, or None."""
    root = Path(root) if root else ROOT
    if not (root / "app" / "main.py").exists():
        return problem("repo_missing", f"{root}/app/main.py is not there")
    python = root / ".venv" / "bin" / "python"
    if not python.exists():
        return problem("python_missing", f"no interpreter at {python}")
    if systemd is not None and not systemd.is_linux():
        return problem("not_linux", f"sys.platform is {sys.platform!r}; systemd is Linux only")
    return None


def _refusal(ran: Ran, what: str) -> dict:
    """systemctl said no. 127 is the manager not being there at all; every other code is
    systemd having an opinion. The owner reads a different sentence for each."""
    if ran.returncode == 127:
        return problem("supervisor_missing", f"{what}: {ran.said}")
    return problem("start_refused", f"{what}: {ran.said}")


def _outcome(stages: list[dict], *, lifecycle_after: dict, problem_: dict | None, next_: str,
             human: str, **extra) -> dict:
    return base._outcome(stages, lifecycle_after=lifecycle_after, problem_=problem_,
                         next_=next_, human=human, **extra)


def _register(systemd: Systemd, stages: list[dict]) -> dict | None:
    """Rung 4 of a start: make sure the server has the service and will start it at boot.
    Returns a problem, or None when the server has it."""
    wrote = False
    if not systemd.installed():
        try:
            systemd.write_unit()
            wrote = True
        except PermissionError as exc:
            stages.append(stage("install", "fail", "this login may not write the service file"))
            return problem("permission_refused", f"{systemd.unit_path}: {exc}")
        except OSError as exc:
            stages.append(stage("install", "fail", "the service file could not be written"))
            return problem("install_refused", f"{systemd.unit_path}: {exc}")
    if not systemd.enabled():
        ran = systemd.enable()
        if not ran.ok:
            stages.append(stage("install", "fail", systemd.unit))
            if ran.returncode == 127:
                return problem("supervisor_missing", f"{systemd.unit}: {ran.said}")
            return problem("install_refused", f"{systemd.unit}: {ran.said}")
        stages.append(stage("install", "ok",
                            "service file written and registered to start at boot" if wrote
                            else "registered to start at boot"))
    elif wrote:
        stages.append(stage("install", "ok", "service file written"))
    else:
        stages.append(stage("install", "skip", "already registered as a service"))
    return None


# --------------------------------------------------------------------------- start


def start(machine: Machine, systemd: Systemd, *, port: int, wait_s: float = START_WAIT_S,
          route: bool = True) -> dict:
    """Turn CROOKS OS on, from wherever it is. The same ladder as service.start, one service
    wide, and every rung a state the server is actually found in:

      1  already answering        -> say so and touch nothing
      2  the files or the venv are not there -> a sentence the owner can act on
      3  stuck on the port        -> ours, so clear it; not ours, so refuse to fight it
      4  not registered           -> write the service file and enable it
      5  systemctl restart
      6  the tablet's HTTPS route (a warning if it fails; the server is still up)
      7  /health, read back. ONLY this makes the Start a success.
    """
    stages: list[dict] = []
    before = lifecycle(machine, systemd, port=port)
    if before["state"] in (RUNNING, RUNNING_WINDOW, UNHEALTHY):
        stages.append(stage("check", "skip", before["human"]))
        return _outcome(stages, lifecycle_after=before, problem_=None,
                        next_="already_running", human=before["human"], before=before)

    bad = preflight(root=systemd.root, systemd=systemd)
    if bad is not None:
        stages.append(stage("check", "fail", bad["code"]))
        return _outcome(stages, lifecycle_after=before, problem_=bad, next_="blocked",
                        human=bad["human"], before=before)
    stages.append(stage("check", "ok", before["human"]))

    if before["state"] == STALE:
        if not any(row.get("loaded") or row.get("installed") for row in before["agents"]):
            held = problem("port_busy", f"127.0.0.1:{port} is accepting connections and /health does not answer; the service is not registered, so this is not CROOKS OS")
            stages.append(stage("clear", "fail", "the address is held by something that is not CROOKS OS"))
            return _outcome(stages, lifecycle_after=before, problem_=held, next_="blocked",
                            human=held["human"], before=before)
        systemd.stop()
        cleared = wait_for_stop(machine, timeout_s=STOP_WAIT_S)
        stages.append(stage("clear", "ok" if cleared else "warn",
                            "the stuck copy was stopped" if cleared
                            else "it is still holding the address; starting anyway"))

    refused = _register(systemd, stages)
    if refused is not None:
        return _outcome(stages, lifecycle_after=lifecycle(machine, systemd, port=port),
                        problem_=refused, next_="blocked", human=refused["human"], before=before)

    ran = systemd.restart()
    if not ran.ok:
        refused = _refusal(ran, systemd.unit)
        stages.append(stage("start", "fail", systemd.unit))
        return _outcome(stages, lifecycle_after=lifecycle(machine, systemd, port=port),
                        problem_=refused, next_="blocked", human=refused["human"], before=before)
    stages.append(stage("start", "ok", "1 service started"))

    if route:
        host, note = machine.ensure_route()
        stages.append(stage("route", "ok" if host else "warn", f"https://{host}/" if host else note))

    def still_starting() -> bool:
        row = systemd.state()
        return bool(row.get("pid") or row.get("loaded"))

    health = wait_for_health(machine, timeout_s=wait_s, still_starting=still_starting)
    after = lifecycle(machine, systemd, port=port, health=health)
    if health is None:
        # §26, the one that matters: systemctl exited 0 and the service is NOT up.
        timed_out = problem("health_timeout", f"no answer on 127.0.0.1:{port}/health within {wait_s:.0f}s; see journalctl -u {systemd.unit} -n 50")
        stages.append(stage("verify", "fail", f"nothing answered within {wait_s:.0f}s"))
        return _outcome(stages, lifecycle_after=after, problem_=timed_out, next_="blocked",
                        human=timed_out["human"], before=before)
    stages.append(stage("verify", "ok", lc.summarise_health(health)))
    return _outcome(stages, lifecycle_after=after, problem_=None, next_="running",
                    human="CROOKS OS is running.", before=before)


# --------------------------------------------------------------------------- stop


STOP_NOTE = (
    "The service stays registered, so CROOKS OS starts again the next time this server boots — "
    "which is what an appliance should do. Uninstalling is the only thing that takes it off "
    "for good."
)


def stop(machine: Machine, systemd: Systemd, *, port: int, wait_s: float = STOP_WAIT_S) -> dict:
    """Turn CROOKS OS off, and prove it went off. `systemctl stop` returns 0 the instant the
    signal is sent, which is not the fact the owner is asking about."""
    stages: list[dict] = []
    before = lifecycle(machine, systemd, port=port)
    if before["state"] in (STOPPED, NOT_INSTALLED, CRASH_LOOPING) and not before["answering"]:
        stages.append(stage("check", "skip", before["human"]))
        return _outcome(stages, lifecycle_after=before, problem_=None, next_="already_stopped",
                        human="CROOKS OS is already stopped.", before=before, note=STOP_NOTE)
    if before["state"] == RUNNING_WINDOW:
        refused = problem("not_supervised", f"127.0.0.1:{port} is answering but the service holds no pid; it is not systemd's to stop")
        stages.append(stage("check", "fail", "it is not running as a service"))
        return _outcome(stages, lifecycle_after=before, problem_=refused, next_="blocked",
                        human=refused["human"], before=before, note=STOP_NOTE)
    ran = systemd.stop()
    if ran.returncode == 127:
        absent = problem("stop_supervisor_missing", f"{systemd.unit}: {ran.said}")
        stages.append(stage("stop", "fail", "the server's service manager did not answer"))
        return _outcome(stages, lifecycle_after=lifecycle(machine, systemd, port=port),
                        problem_=absent, next_="blocked", human=absent["human"],
                        before=before, note=STOP_NOTE)
    stages.append(stage("stop", "ok" if ran.ok else "warn",
                        "the service was asked to stop" if ran.ok else f"the server said: {ran.said[:120]}"))
    went = wait_for_stop(machine, timeout_s=wait_s)
    after = lifecycle(machine, systemd, port=port)
    if not went:
        refused = problem("stop_refused", ran.said or f"127.0.0.1:{port} is still accepting connections {wait_s:.0f}s after the stop")
        stages.append(stage("verify", "fail", "it is still answering"))
        return _outcome(stages, lifecycle_after=after, problem_=refused, next_="blocked",
                        human=refused["human"], before=before, note=STOP_NOTE)
    stages.append(stage("verify", "ok", "nothing is answering on the port"))
    return _outcome(stages, lifecycle_after=after, problem_=None, next_="stopped",
                    human="CROOKS OS is stopped.", before=before, note=STOP_NOTE)


# --------------------------------------------------------------------------- restart


def restart(machine: Machine, systemd: Systemd, *, port: int, wait_s: float = START_WAIT_S,
            route: bool = True) -> dict:
    """Stop and start in one press, and read /health back afterwards. A restart of a service
    the server does not have is a start, so it falls through to one; a backend running in a
    terminal session is the one thing this cannot restart, and it says so."""
    before = lifecycle(machine, systemd, port=port)
    if before["state"] == RUNNING_WINDOW:
        refused = problem("not_supervised", f"127.0.0.1:{port} is answering but the service holds no pid; a restart would not touch it")
        return _outcome([stage("check", "fail", "it is not running as a service")],
                        lifecycle_after=before, problem_=refused, next_="blocked",
                        human=refused["human"], before=before)
    if not before["agents"] or any(not row.get("loaded") for row in before["agents"]):
        out = start(machine, systemd, port=port, wait_s=wait_s, route=route)
        out["stages"].insert(0, stage("check", "skip", "not registered as a service yet, so this is a start"))
        out["before"] = before
        return out
    bad = preflight(root=systemd.root, systemd=systemd)
    if bad is not None:
        return _outcome([stage("check", "fail", bad["code"])], lifecycle_after=before,
                        problem_=bad, next_="blocked", human=bad["human"], before=before)
    stages = [stage("check", "ok", before["human"])]
    ran = systemd.restart()
    if not ran.ok:
        refused = _refusal(ran, systemd.unit)
        stages.append(stage("restart", "fail", systemd.unit))
        return _outcome(stages, lifecycle_after=lifecycle(machine, systemd, port=port),
                        problem_=refused, next_="blocked", human=refused["human"], before=before)
    stages.append(stage("restart", "ok", "1 service restarted"))
    if route:
        host, note = machine.ensure_route()
        stages.append(stage("route", "ok" if host else "warn", f"https://{host}/" if host else note))
    health = wait_for_health(machine, timeout_s=wait_s)
    after = lifecycle(machine, systemd, port=port, health=health)
    if health is None:
        timed_out = problem("health_timeout", f"no answer on 127.0.0.1:{port}/health within {wait_s:.0f}s after a restart; see journalctl -u {systemd.unit} -n 50")
        stages.append(stage("verify", "fail", f"nothing answered within {wait_s:.0f}s"))
        return _outcome(stages, lifecycle_after=after, problem_=timed_out, next_="blocked",
                        human=timed_out["human"], before=before)
    stages.append(stage("verify", "ok", lc.summarise_health(health)))
    return _outcome(stages, lifecycle_after=after, problem_=None, next_="running",
                    human="CROOKS OS restarted and is running.", before=before)
