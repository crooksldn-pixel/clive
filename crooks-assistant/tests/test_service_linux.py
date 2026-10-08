"""scripts/service_linux.py: the server's lifecycle, against a systemd that behaves like one.

What tests/test_service.py held the Mac's lifecycle to until the Mac runtime was deleted
(DEC-071, ruling 38), held here for the server: nothing succeeds because systemctl exited 0,
every failure the owner reads is in the owner's words, and the layer runs nothing but
systemctl. The double below models the facts systemd itself holds — whether the service is
loaded, enabled and active, its pid and how its last main process ended — and the rules that
follow from them: `restart` on a service systemd does not have fails, `enable` on a file
systemd has not read fails, `stop` exits 0 the moment the signal is sent.

NOT PROVED HERE: that a real systemd accepts these verbs. There is no systemd in this test
process. What is proved is which commands would run, in which order, and what this layer
concludes from each answer.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import service_linux as svc
from scripts.service import Ran

UNIT = "crooks-assistant.service"
PORT = 8000


class SystemdDouble:
    """One systemd, holding only what systemd holds."""

    def __init__(self, *, loaded=False, enabled=False, active=False, pid=4242, last_exit_code=0,
                 result=None, absent=False, refuse=(), on_restart=None, on_stop=None) -> None:
        self.loaded, self.enabled, self.active = loaded, enabled, active
        self.pid, self.last_exit_code = pid, last_exit_code
        self.result = result
        self.absent = absent
        self.refuse = set(refuse)
        self.on_restart, self.on_stop = on_restart, on_stop
        self.calls: list[list[str]] = []

    def verbs(self) -> list[str]:
        return [c[1] for c in self.calls if c and c[0] == "systemctl" and len(c) > 1]

    def __call__(self, argv, *, timeout_s: float = 60.0) -> Ran:
        argv = list(argv)
        self.calls.append(argv)
        if not argv or argv[0] != "systemctl":
            return Ran(tuple(argv), 0, "", "")
        if self.absent:
            return Ran(tuple(argv), 127, "", "systemctl: not found")
        verb = argv[1]
        if verb in self.refuse:
            return Ran(tuple(argv), 1, "", f"Failed to {verb} {UNIT}: Access denied")
        if verb == "show":
            result = self.result or ("success" if self.last_exit_code == 0 else "exit-code")
            body = "\n".join([
                f"LoadState={'loaded' if self.loaded else 'not-found'}",
                f"ActiveState={'active' if self.active else 'inactive'}",
                f"SubState={'running' if self.active else 'dead'}",
                f"MainPID={self.pid if self.active else 0}",
                f"ExecMainStatus={self.last_exit_code}",
                f"Result={result}",
                "NRestarts=0",
            ])
            return Ran(tuple(argv), 0, body + "\n", "")
        if verb == "is-enabled":
            if not self.loaded:
                return Ran(tuple(argv), 1, "", f"Failed to get unit file state for {UNIT}: No such file or directory")
            return Ran(tuple(argv), 0 if self.enabled else 1, "enabled\n" if self.enabled else "disabled\n", "")
        if verb == "daemon-reload":
            self.loaded = True  # the file the caller just wrote is now something systemd has read
            return Ran(tuple(argv), 0, "", "")
        if verb == "enable":
            if not self.loaded:
                return Ran(tuple(argv), 1, "", f"Failed to enable unit: Unit file {UNIT} does not exist.")
            self.enabled = True
            return Ran(tuple(argv), 0, "", "")
        if verb == "stop":
            if not self.loaded:
                return Ran(tuple(argv), 5, "", f"Failed to stop {UNIT}: Unit {UNIT} not loaded.")
            self.active = False
            if self.on_stop is not None:
                self.on_stop()
            return Ran(tuple(argv), 0, "", "")
        if verb == "restart":
            # THE rule: a restart of a service systemd does not have is not a start.
            if not self.loaded:
                return Ran(tuple(argv), 5, "", f"Failed to restart {UNIT}: Unit {UNIT} not found.")
            self.active = True
            if self.on_restart is not None:
                self.on_restart()
            return Ran(tuple(argv), 0, "", "")
        return Ran(tuple(argv), 0, "", "")


class Server:
    """A server as this layer sees it: a health document that appears and disappears, a port,
    a clock that only moves when the layer sleeps."""

    def __init__(self, tmp_path: Path, systemd: SystemdDouble, *, healthy: bool = False) -> None:
        self.health = {"build": "b", "checks": {}} if healthy else None
        self.port = healthy
        self.clock = 0.0
        self.systemd = systemd
        root = tmp_path / "checkout"
        (root / "app").mkdir(parents=True)
        (root / "app" / "main.py").write_text("app = None\n")
        (root / ".venv" / "bin").mkdir(parents=True)
        (root / ".venv" / "bin" / "python").write_text("")
        self.root = root
        self.unit_dir = tmp_path / "systemd"
        self.machine = svc.Machine(
            runner=systemd,
            read_health=lambda fresh=False: self.health,
            port_open=lambda: self.port,
            ensure_route=lambda: ("crooks.tail.ts.net", "already configured"),
            sleep=self.tick,
            now=lambda: self.clock,
            log_dir=tmp_path / "logs",
        )

    def tick(self, seconds: float) -> None:
        self.clock += seconds

    def comes_up(self) -> None:
        self.health, self.port = {"build": "b", "checks": {}}, True

    def goes_down(self) -> None:
        self.health, self.port = None, False

    def supervisor(self, **over) -> svc.Systemd:
        options = dict(root=self.root, unit_dir=self.unit_dir,
                       render=lambda: "[Unit]\nDescription=test\n", is_linux=lambda: True)
        options.update(over)
        return svc.Systemd(self.machine, **options)


# ---------------------------------------------------------------------- what state is it in


def test_a_service_systemd_has_never_heard_of_is_not_loaded_and_is_not_an_error(tmp_path):
    server = Server(tmp_path, SystemdDouble())
    row = server.supervisor().state()
    assert row["loaded"] is False and row["pid"] is None and row["installed"] is False
    assert svc.lifecycle(server.machine, server.supervisor(), port=PORT)["state"] == svc.NOT_INSTALLED


def test_a_service_that_dies_on_every_start_reads_as_crash_looping(tmp_path):
    server = Server(tmp_path, SystemdDouble(loaded=True, enabled=True, active=False, last_exit_code=1))
    assert svc.lifecycle(server.machine, server.supervisor(), port=PORT)["state"] == svc.CRASH_LOOPING


def test_a_stop_that_ended_by_signal_is_a_stop_and_not_a_crash(tmp_path):
    """systemd records the signal number as the exit status of a service it stopped; Result
    says whether that was success. A clean stop must not read as a crash loop."""
    server = Server(tmp_path, SystemdDouble(loaded=True, enabled=True, active=False, last_exit_code=15, result="success"))
    assert server.supervisor().state()["last_exit_code"] == 0
    assert svc.lifecycle(server.machine, server.supervisor(), port=PORT)["state"] == svc.STOPPED


def test_running_as_a_service_and_running_in_a_session_are_different_sentences(tmp_path):
    supervised = Server(tmp_path / "a", SystemdDouble(loaded=True, enabled=True, active=True), healthy=True)
    window = Server(tmp_path / "b", SystemdDouble(loaded=True, enabled=True, active=False), healthy=True)
    assert svc.lifecycle(supervised.machine, supervised.supervisor(), port=PORT)["state"] == svc.RUNNING
    assert svc.lifecycle(window.machine, window.supervisor(), port=PORT)["state"] == svc.RUNNING_WINDOW


# ---------------------------------------------------------------------------------- start


def test_start_from_a_server_where_nothing_has_ever_been_installed(tmp_path):
    systemd = SystemdDouble()
    server = Server(tmp_path, systemd)
    systemd.on_restart = server.comes_up
    out = svc.start(server.machine, server.supervisor(), port=PORT, wait_s=30)
    assert out["ok"] is True and out["next"] == "running"
    assert (server.unit_dir / UNIT).exists(), "the service file was written from the renderer"
    assert systemd.verbs()[-4:-1] == ["daemon-reload", "is-enabled", "enable"] or "enable" in systemd.verbs()
    assert systemd.verbs().index("enable") < systemd.verbs().index("restart")
    assert [s["stage"] for s in out["stages"]] == ["check", "install", "start", "route", "verify"]


def test_systemctl_exiting_zero_is_not_a_successful_start(tmp_path):
    """The lie §26 is about, and the reason this file exists."""
    systemd = SystemdDouble(loaded=True, enabled=True)
    server = Server(tmp_path, systemd)
    out = svc.start(server.machine, server.supervisor(), port=PORT, wait_s=10)
    assert "restart" in systemd.verbs()
    assert out["ok"] is False and out["problem"]["code"] == "health_timeout"
    assert out["stages"][-1] == {"stage": "verify", "state": "fail", "detail": "nothing answered within 10s"}


def test_start_on_a_server_that_is_already_running_touches_nothing(tmp_path):
    systemd = SystemdDouble(loaded=True, enabled=True, active=True)
    server = Server(tmp_path, systemd, healthy=True)
    out = svc.start(server.machine, server.supervisor(), port=PORT)
    assert out["ok"] is True and out["next"] == "already_running"
    assert set(systemd.verbs()) == {"show"}


def test_a_start_by_a_login_that_may_not_write_the_service_file_says_so(tmp_path):
    systemd = SystemdDouble()
    server = Server(tmp_path, systemd)
    supervisor = server.supervisor()

    def refused() -> Path:
        raise PermissionError("[Errno 13] Permission denied: '/etc/systemd/system/crooks-assistant.service'")

    supervisor.write_unit = refused  # type: ignore[method-assign]
    out = svc.start(server.machine, supervisor, port=PORT)
    assert out["ok"] is False and out["problem"]["code"] == "permission_refused"
    assert "restart" not in systemd.verbs(), "nothing was started on a half-registered service"
    assert "Permission denied" in out["problem"]["developer"]


def test_a_start_on_a_machine_with_no_systemctl_names_the_manager_not_the_service(tmp_path):
    systemd = SystemdDouble(absent=True)
    server = Server(tmp_path, systemd)
    out = svc.start(server.machine, server.supervisor(), port=PORT)
    assert out["ok"] is False and out["problem"]["code"] == "supervisor_missing"


def test_the_server_that_is_not_linux_is_refused_before_anything_runs(tmp_path):
    systemd = SystemdDouble()
    server = Server(tmp_path, systemd)
    out = svc.start(server.machine, server.supervisor(is_linux=lambda: False), port=PORT)
    assert out["ok"] is False and out["problem"]["code"] == "not_linux"
    assert set(systemd.verbs()) <= {"show"}


def test_an_address_held_by_something_that_is_not_ours_is_never_touched(tmp_path):
    systemd = SystemdDouble()
    server = Server(tmp_path, systemd)
    server.port = True  # something listens, /health does not answer, no service registered
    out = svc.start(server.machine, server.supervisor(), port=PORT)
    assert out["ok"] is False and out["problem"]["code"] == "port_busy"
    assert "stop" not in systemd.verbs()


# ----------------------------------------------------------------------------------- stop


def test_stop_stops_the_service_and_checks_the_address_is_free(tmp_path):
    systemd = SystemdDouble(loaded=True, enabled=True, active=True)
    server = Server(tmp_path, systemd, healthy=True)
    systemd.on_stop = server.goes_down
    out = svc.stop(server.machine, server.supervisor(), port=PORT)
    assert out["ok"] is True and out["next"] == "stopped"
    assert "stop" in systemd.verbs()
    assert out["stages"][-1]["stage"] == "verify" and out["stages"][-1]["state"] == "ok"


def test_a_stop_that_did_not_stop_it_says_so(tmp_path):
    systemd = SystemdDouble(loaded=True, enabled=True, active=True)
    server = Server(tmp_path, systemd, healthy=True)
    out = svc.stop(server.machine, server.supervisor(), port=PORT, wait_s=5)
    assert out["ok"] is False and out["problem"]["code"] == "stop_refused"


def test_stopping_something_already_stopped_is_not_a_failure(tmp_path):
    systemd = SystemdDouble(loaded=True, enabled=True, active=False)
    server = Server(tmp_path, systemd)
    out = svc.stop(server.machine, server.supervisor(), port=PORT)
    assert out["ok"] is True and out["next"] == "already_stopped"
    assert "stop" not in systemd.verbs()


def test_a_backend_running_in_a_session_is_not_systemds_to_stop(tmp_path):
    systemd = SystemdDouble(loaded=True, enabled=True, active=False)
    server = Server(tmp_path, systemd, healthy=True)
    out = svc.stop(server.machine, server.supervisor(), port=PORT)
    assert out["ok"] is False and out["problem"]["code"] == "not_supervised"


# -------------------------------------------------------------------------------- restart


def test_restart_restarts_and_then_reads_health_back(tmp_path):
    systemd = SystemdDouble(loaded=True, enabled=True, active=True)
    server = Server(tmp_path, systemd, healthy=True)
    out = svc.restart(server.machine, server.supervisor(), port=PORT, wait_s=10)
    assert out["ok"] is True and out["next"] == "running"
    assert systemd.verbs().count("restart") == 1
    assert [s["stage"] for s in out["stages"]] == ["check", "restart", "route", "verify"]


def test_a_restart_that_does_not_come_back_is_a_failure(tmp_path):
    systemd = SystemdDouble(loaded=True, enabled=True, active=True)
    server = Server(tmp_path, systemd, healthy=True)
    systemd.on_restart = server.goes_down
    out = svc.restart(server.machine, server.supervisor(), port=PORT, wait_s=10)
    assert out["ok"] is False and out["problem"]["code"] == "health_timeout"


def test_restarting_a_server_that_was_never_set_up_starts_it(tmp_path):
    systemd = SystemdDouble()
    server = Server(tmp_path, systemd)
    systemd.on_restart = server.comes_up
    out = svc.restart(server.machine, server.supervisor(), port=PORT, wait_s=30)
    assert out["ok"] is True and out["next"] == "running"
    assert out["stages"][0]["stage"] == "check" and "start" in out["stages"][0]["detail"]
    assert "enable" in systemd.verbs()


# --------------------------------------------------------------------------------- hygiene


def test_no_failure_the_owner_reads_is_written_for_a_developer():
    for code, (human, fix) in svc.PROBLEMS.items():
        for word in svc.DEVELOPERESE:
            assert word not in human.lower(), f"{code}.human says {word!r}"
            assert word not in fix.lower(), f"{code}.fix says {word!r}"


def test_the_layer_runs_nothing_but_systemctl(tmp_path):
    systemd = SystemdDouble()
    server = Server(tmp_path, systemd)
    systemd.on_restart = server.comes_up
    svc.start(server.machine, server.supervisor(), port=PORT, wait_s=5)
    svc.stop(server.machine, server.supervisor(), port=PORT, wait_s=5)
    svc.restart(server.machine, server.supervisor(), port=PORT, wait_s=5)
    assert all(call[0] == "systemctl" for call in systemd.calls), systemd.calls


def test_no_document_this_layer_produces_carries_anything_unserialisable(tmp_path):
    systemd = SystemdDouble(loaded=True, enabled=True, active=True)
    server = Server(tmp_path, systemd, healthy=True)
    for out in (
        svc.lifecycle(server.machine, server.supervisor(), port=PORT),
        svc.restart(server.machine, server.supervisor(), port=PORT, wait_s=5),
        svc.stop(server.machine, server.supervisor(), port=PORT, wait_s=5),
    ):
        json.dumps(out)
