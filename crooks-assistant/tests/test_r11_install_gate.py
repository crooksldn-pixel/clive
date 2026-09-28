"""`make install`'s gates on the server, and what a failed one leaves behind (the 2026-09-28 deploy
review, round 10: R9-A1a-F-05B-AVAIL-PREFLIGHT, R9-A1b-F-05B-AVAIL-PREFLIGHT, R9-A1b-A1B-STATUS).

The reviewers could see that `install_systemd.running_problems` checks the running process's own
command line and /health's proxy_identity check, but not that a failed gate undoes anything: the
install returned 1 and left the new unit written, enabled and running. Now every gate after the
unit is written — systemd reloading it, enabling it, restarting on it, /health answering, the
running process's flag, /health's proxy_identity, and this host being able to tell its own requests
from a device's (identity.tailnet_self_check, S1T-01) — rolls back what the install changed before
it returns 1: the unit file as it was (or none), enabled as it was, and the service restarted on
the old unit if it was running, stopped if it was not. What is stood in for is systemctl, the
service's /proc/<MainPID>/cmdline, Tailscale serve and the /health answer; the gates' own code runs.
The real phone's /whoami against the staging copy is the deploy's, and cannot be a test.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app import identity

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
UNIT = "crooks-assistant.service"
GOOD_ARGV = ["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--port", "8000", "--no-proxy-headers"]
HEALTHY = {"status": "ok", "checks": {"proxy_identity": {"ok": True, "detail": "uvicorn started with --no-proxy-headers"}}}
OLD_UNIT = b"[Unit]\nDescription=the unit as it was\n"
NEW_UNIT = "[Unit]\nDescription=the unit this build renders\n"


def _installer():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("install_systemd_r11_gate", SCRIPTS / "install_systemd.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Host:
    """systemctl, the service's /proc and the unit file, as the installer sees them. `failing` names
    the systemctl verb that exits non-zero on the install's own call to it."""

    def __init__(self, tmp_path: Path, monkeypatch, *, previous: bytes | None, enabled: bool = True,
                 active: bool = True, failing: str = "", argv: list[str] = GOOD_ARGV,
                 health: dict | None = HEALTHY, host_whole: tuple[bool, str] = (True, "whole")) -> None:
        self.installer = _installer()
        self.calls: list[tuple[str, ...]] = []
        self.failing = failing
        self.enabled, self.active = enabled, active
        self.unit = tmp_path / "system" / UNIT
        self.unit.parent.mkdir(parents=True)
        if previous is not None:
            self.unit.write_bytes(previous)
        proc = tmp_path / "proc"
        (proc / "4242").mkdir(parents=True)
        (proc / "4242" / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        installer = self.installer
        monkeypatch.setattr(installer, "PROC", proc)
        monkeypatch.setattr(installer, "systemctl", self.systemctl)
        monkeypatch.setattr(installer, "preflight", lambda: [])
        monkeypatch.setattr(installer, "rendered_unit", lambda values=None: NEW_UNIT)
        monkeypatch.setattr(installer.lc, "SYSTEMD_UNIT_PATH", self.unit)
        monkeypatch.setattr(installer.lc, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(installer.lc, "ensure_serve", lambda port: ("crooks.example.ts.net", "serving"))
        monkeypatch.setattr(installer.lc, "wait_for_health", lambda url, timeout_s=90: health)
        monkeypatch.setattr(identity, "tailnet_self_check", lambda: host_whole)

    def systemctl(self, *args: str) -> subprocess.CompletedProcess:
        self.calls.append(args)
        verb = args[0]
        out, code = "", 0
        if verb == "is-enabled":
            out = "enabled" if self.enabled else "disabled"
        elif verb == "is-active":
            out = "active" if self.active else "inactive"
        elif verb == "show":
            out = "4242"
        elif verb == self.failing and self.calls.count(args) == 1:
            code = 1
        return subprocess.CompletedProcess(["systemctl", *args], code, stdout=out + "\n", stderr="refused" if code else "")


GATES = {
    "systemd will not reload the unit": {"failing": "daemon-reload"},
    "systemd will not enable it": {"failing": "enable"},
    "the service will not start on it": {"failing": "restart"},
    "/health never answers": {"health": None},
    "the running process lacks --no-proxy-headers": {"argv": GOOD_ARGV[:-1]},
    "the running process says --proxy-headers last": {"argv": [*GOOD_ARGV, "--proxy-headers"]},
    "/health's proxy_identity is not ok": {"health": {"status": "degraded", "checks": {"proxy_identity": {"ok": False, "detail": "rewritten"}}}},
    "/health carries no proxy_identity": {"health": {"status": "ok", "checks": {}}},
    "this host cannot tell its own requests apart": {"host_whole": (False, "tailscale0 holds no IPv4 address")},
}


@pytest.mark.parametrize("gate", sorted(GATES))
def test_a_failed_gate_puts_the_unit_and_the_service_back_as_they_were(tmp_path, monkeypatch, capsys, gate):
    host = Host(tmp_path, monkeypatch, previous=OLD_UNIT, **GATES[gate])
    assert host.installer.install(8000) == 1
    out = capsys.readouterr().out
    assert host.unit.read_bytes() == OLD_UNIT, "the unit file is the one that was there"
    last_reload = max(i for i, call in enumerate(host.calls) if call == ("daemon-reload",))
    assert host.calls[last_reload + 1:] == [("restart", UNIT)], "reloaded, then restarted on the unit as it was"
    assert "The install is rolled back." in out and "Done." not in out, out


@pytest.mark.parametrize("gate", sorted(GATES))
def test_a_first_install_that_fails_a_gate_leaves_no_unit_and_nothing_running(tmp_path, monkeypatch, capsys, gate):
    host = Host(tmp_path, monkeypatch, previous=None, enabled=False, active=False, **GATES[gate])
    assert host.installer.install(8000) == 1
    assert not host.unit.exists()
    tail = host.calls[-3:]
    assert ("stop", UNIT) in host.calls and ("disable", UNIT) in host.calls and tail[-1] == ("daemon-reload",)
    assert "The install is rolled back." in capsys.readouterr().out


def test_a_service_that_was_stopped_and_disabled_is_left_so(tmp_path, monkeypatch, capsys):
    host = Host(tmp_path, monkeypatch, previous=OLD_UNIT, enabled=False, active=False, health=None)
    assert host.installer.install(8000) == 1
    last_reload = max(i for i, call in enumerate(host.calls) if call == ("daemon-reload",))
    assert host.calls[last_reload + 1:] == [("disable", UNIT), ("stop", UNIT)]
    assert host.unit.read_bytes() == OLD_UNIT


def test_a_rollback_step_that_fails_is_said_and_the_rest_are_still_tried(tmp_path, monkeypatch, capsys):
    host = Host(tmp_path, monkeypatch, previous=OLD_UNIT, health=None)
    real = host.systemctl

    def refusing_the_second_restart(*args):
        done = real(*args)
        if args == ("restart", UNIT) and host.calls.count(args) == 2:
            done.returncode = 1
        return done

    monkeypatch.setattr(host.installer, "systemctl", refusing_the_second_restart)
    assert host.installer.install(8000) == 1
    out = capsys.readouterr().out
    assert "FAIL   restart on the unit as it was" in out and "NOT fully rolled back" in out
    assert host.unit.read_bytes() == OLD_UNIT


def test_every_gate_passed_keeps_the_new_unit_and_says_what_the_phone_must_show(tmp_path, monkeypatch, capsys):
    host = Host(tmp_path, monkeypatch, previous=OLD_UNIT)
    assert host.installer.install(8000) == 0
    out = capsys.readouterr().out
    assert host.unit.read_text() == NEW_UNIT
    assert ("stop", UNIT) not in host.calls and host.calls.count(("restart", UNIT)) == 1
    assert "Done." in out and "/whoami" in out and "whoami: id=" in out and "rolled back" not in out


@pytest.mark.parametrize("health,expect", [
    (HEALTHY, 0),
    ({"status": "ok", "limited": True, "checks": {"proxy_identity": {"ok": True, "detail": "x"}}}, 1),
    ({"status": "ok", "checks": {}}, 1),
    (None, 1),
])
@pytest.mark.parametrize("active", ["active", "inactive", "failed", ""])
def test_make_status_exits_0_only_for_an_active_unit_whose_health_carries_its_checks(monkeypatch, capsys, health, expect, active):
    """A1B-STATUS, whole: `make status` is 0 only when the unit is active AND /health answered
    with its checks — never on a limited answer, one without checks, no answer, or a unit that is
    not running."""
    installer = _installer()

    def systemctl(*args):
        out = active if args[0] == "is-active" else "enabled"
        return subprocess.CompletedProcess(["systemctl", *args], 0, stdout=out + "\n", stderr="")

    monkeypatch.setattr(installer, "systemctl", systemctl)
    monkeypatch.setattr(installer.lc, "serve_status", lambda port: ("crooks.example.ts.net", ""))
    monkeypatch.setattr(installer.lc, "fetch_health", lambda url, timeout_s=8.0: health)
    assert installer.status(8000) == (expect if active == "active" else 1)
