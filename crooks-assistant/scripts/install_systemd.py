#!/usr/bin/env python3
"""make install, on Linux — have the server start the assistant itself, at boot.

Writes a systemd unit from the template in deploy/systemd/ with this checkout's paths filled
in, enables it so it comes back after a reboot, makes Tailscale serve the port over HTTPS in
the background (which persists), and reads /health back.

    make install     install (or reinstall) and start now
    make status      is it running, what /health says, what the address is
    make restart     restart it (after `git pull`, say)
    make uninstall   stop, disable and remove the unit
    make logs        follow it  (journalctl -u crooks-assistant -f)

The counterpart of scripts/install_launchd.py, which does the same job on the Mac. Both are
reached through the same `make` targets; the Makefile picks by platform, so the Mac's own
deployment is untouched by anything here.

The unit runs as root for now, because the Claude Max login this machine holds lives in
/root/.claude. docs/DEPLOY_LINUX.md says why that is temporary and what replaces it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import launch_common as lc  # noqa: E402

PROC = Path("/proc")


def systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=60)


def credentials_block() -> str:
    """The LoadCredentialEncrypted= lines for whatever scripts/provision_secrets.py has
    encrypted. Generated rather than hand-listed, so provisioning a secret and reinstalling
    is the whole of the operation and a stale name cannot stop the unit starting."""
    import provision_secrets as ps

    from app.secrets import keychain

    lines = []
    for key in keychain.KNOWN_KEYS:
        blob = ps.encrypted_path(key)
        if blob.is_file():
            lines.append(f"LoadCredentialEncrypted={key}:{blob}")
    if not lines:
        return (
            "# No encrypted credentials provisioned yet. Store them with\n"
            "#   python scripts/provision_secrets.py --all\n"
            "# and run `make install` again to load them."
        )
    return "\n".join(lines)


def unit_values() -> dict[str, str]:
    from app.secrets import linux_store
    from config.settings import get_settings

    settings = get_settings()
    return {
        "ROOT": str(lc.ROOT),
        "PYTHON": str(lc.VENV_PYTHON),
        "HOME": str(Path.home()),
        "PATH": lc.service_path([str(lc.VENV_PYTHON)]),
        "CLAUDE": lc.find_claude() or "",
        "HOST": settings.host,
        "PORT": str(settings.port),
        "SECRET_DIR": str(linux_store.store_dir()),
        "CREDENTIALS": credentials_block(),
    }


def rendered_unit(values: dict[str, str] | None = None) -> str:
    template = (lc.SYSTEMD_TEMPLATE).read_text(encoding="utf-8")
    return lc.render(template, values or unit_values())


def preflight() -> list[str]:
    problems = []
    if not lc.VENV_PYTHON.exists():
        problems.append(f"no virtualenv at {lc.VENV_PYTHON} — run: make venv")
    if not lc.find_claude():
        problems.append("the claude CLI was not found — install it and open a new shell")
    if not lc.find_tailscale():
        problems.append("Tailscale was not found — the tablet and the phone need its HTTPS address")
    if not lc.SYSTEMD_TEMPLATE.exists():
        problems.append(f"the unit template is missing at {lc.SYSTEMD_TEMPLATE}")
    return problems


def install(port: int) -> int:
    """Install, start, and keep the new unit only if the service it runs passes every gate.

    Each gate after the unit file is written — systemd reloading it, enabling it, restarting on
    it, /health answering, and what must be true of the process now running (running_problems) —
    aborts the install with exit 1, and first rolls back what the install changed (round 10,
    R9-A1b-F-05B-AVAIL-PREFLIGHT): the unit file as it was (or none), whether it starts at boot,
    and the service as that unit had it, running or stopped. The code in this checkout is not
    this command's to roll back; the deploy that fetched it does that."""
    problems = preflight()
    for problem in problems:
        print(f"  FAIL   {problem}")
    if problems:
        return 1

    lc.LOG_DIR.mkdir(parents=True, exist_ok=True)
    target = lc.SYSTEMD_UNIT_PATH
    before = Before.read(target)
    target.write_text(rendered_unit(), encoding="utf-8")
    target.chmod(0o644)
    print(f"  ok     unit → {target}")

    out = systemctl("daemon-reload")
    if out.returncode != 0:
        print(f"  FAIL   daemon-reload: {(out.stderr or out.stdout).strip()}")
        return roll_back(before)
    out = systemctl("enable", lc.SERVICE_UNIT)
    if out.returncode != 0:
        print(f"  FAIL   enable: {(out.stderr or out.stdout).strip()}")
        return roll_back(before)
    print(f"  ok     {lc.SERVICE_UNIT} enabled (starts at boot)")
    # restart, not start: a reinstall over a running service must pick up the new unit.
    out = systemctl("restart", lc.SERVICE_UNIT)
    if out.returncode != 0:
        print(f"  FAIL   start: {(out.stderr or out.stdout).strip()}")
        print(f"         look in: journalctl -u {lc.SERVICE_UNIT} -n 50")
        return roll_back(before)
    print(f"  ok     {lc.SERVICE_UNIT} started")

    host, note = lc.ensure_serve(port)
    print(f"  https  https://{host}/  ({note})" if host else f"  https  not available: {note}")
    print("  wait   backend starting…")
    health = lc.wait_for_health(f"http://127.0.0.1:{port}/health", timeout_s=90)
    print(f"  health {lc.summarise_health(health)}")
    if health is None:
        print(f"         look in: journalctl -u {lc.SERVICE_UNIT} -n 50")
        return roll_back(before)
    problems = running_problems(health)
    for problem in problems:
        print(f"  FAIL   {problem}")
    if problems:
        print(f"         the install is not done; look in: journalctl -u {lc.SERVICE_UNIT} -n 50")
        return roll_back(before)
    print("  ok     running with --no-proxy-headers, and /health says it can tell who opened each connection")
    print("\n  Done. It starts on boot and restarts on failure. Open the address above.")
    print("  Then, on the owner's phone, open /whoami at that address: it must say \"owner\": true, and")
    print(f"  `journalctl -u {lc.SERVICE_UNIT} | grep 'whoami: id=<its check>'` must show the same line.")
    return 0


class Before:
    """What the install is about to change, read before it changes it: the unit file's bytes (None
    when there was none), and whether the unit was enabled and active."""

    def __init__(self, unit: bytes | None, enabled: bool, active: bool) -> None:
        self.unit, self.enabled, self.active = unit, enabled, active

    @classmethod
    def read(cls, target: Path) -> Before:
        unit = target.read_bytes() if target.is_file() else None
        enabled = systemctl("is-enabled", lc.SERVICE_UNIT).stdout.strip() == "enabled"
        active = systemctl("is-active", lc.SERVICE_UNIT).stdout.strip() == "active"
        return cls(unit, enabled, active)


def roll_back(before: Before) -> int:
    """Put back what install() changed, say each step, and return the install's failure (1). The
    unit file as it was, or none; systemd told; enabled at boot as it was; and the service as that
    unit had it — restarted on the old unit if it was running, stopped if it was not. A step that
    fails is said, and the rest are still tried."""
    target = lc.SYSTEMD_UNIT_PATH
    steps: list[tuple[str, bool]] = []
    if before.unit is None:
        steps.append(("stop", systemctl("stop", lc.SERVICE_UNIT).returncode == 0))
        steps.append(("disable", systemctl("disable", lc.SERVICE_UNIT).returncode == 0))
        try:
            target.unlink(missing_ok=True)
            steps.append(("unit removed (there was none before)", True))
        except OSError:
            steps.append(("unit removed (there was none before)", False))
        steps.append(("daemon-reload", systemctl("daemon-reload").returncode == 0))
    else:
        try:
            target.write_bytes(before.unit)
            target.chmod(0o644)
            steps.append(("unit put back as it was", True))
        except OSError:
            steps.append(("unit put back as it was", False))
        steps.append(("daemon-reload", systemctl("daemon-reload").returncode == 0))
        if not before.enabled:
            steps.append(("disable (it was not enabled)", systemctl("disable", lc.SERVICE_UNIT).returncode == 0))
        if before.active:
            steps.append(("restart on the unit as it was", systemctl("restart", lc.SERVICE_UNIT).returncode == 0))
        else:
            steps.append(("stop (it was not running)", systemctl("stop", lc.SERVICE_UNIT).returncode == 0))
    for step, ok in steps:
        print(f"  {'undone' if ok else 'FAIL  '} {step}")
    print("  The install is rolled back." if all(ok for _step, ok in steps)
          else "  The install is NOT fully rolled back: see the steps above.")
    return 1


def running_argv(unit: str = lc.SERVICE_UNIT) -> list[str] | None:
    """The command line of the process systemd says is the service now: /proc/<MainPID>/cmdline.
    None when there is no such process or it cannot be read."""
    out = systemctl("show", "-p", "MainPID", "--value", unit)
    pid = (out.stdout or "").strip()
    if out.returncode != 0 or not pid.isdigit() or int(pid) <= 0:
        return None
    try:
        raw = (PROC / pid / "cmdline").read_bytes()
    except OSError:
        return None
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def running_problems(health: dict | None) -> list[str]:
    """What must be true of the service that is running now, read after it has answered, or the
    install has not done its job (round 8, F-05B-AVAIL-PREFLIGHT): its own command line says
    --no-proxy-headers (the unit file saying so is not the process running it), and /health's
    proxy_identity check is ok. Every forwarded request is refused without both."""
    from app import identity

    problems = []
    argv = running_argv()
    if argv is None:
        problems.append(f"the running {lc.SERVICE_UNIT} could not be found or its command line read (MainPID)")
    elif not identity.proxy_headers_off(argv):
        problems.append(f"the running {lc.SERVICE_UNIT} was not started with --no-proxy-headers: {' '.join(argv)[:200]}")
    check = ((health or {}).get("checks") or {}).get("proxy_identity")
    if not isinstance(check, dict) or check.get("ok") is not True:
        detail = check.get("detail") if isinstance(check, dict) else "no proxy_identity check in the answer"
        problems.append(f"/health checks.proxy_identity is not ok: {detail}")
    # And this host can tell a request it sent itself from the owner's device (round 10, S1T-01):
    # its address tables hold the Tailscale interface's own addresses. Without it every forwarded
    # request is refused; the install says so here rather than leave it to his phone.
    ok, why = identity.tailnet_self_check()
    if not ok:
        problems.append(f"this host cannot tell its own requests from the owner's devices: {why}")
    return problems


def uninstall() -> int:
    systemctl("stop", lc.SERVICE_UNIT)
    systemctl("disable", lc.SERVICE_UNIT)
    if lc.SYSTEMD_UNIT_PATH.exists():
        lc.SYSTEMD_UNIT_PATH.unlink()
    systemctl("daemon-reload")
    print(f"  ok     {lc.SERVICE_UNIT} stopped, disabled and removed")
    print("  Tailscale still serves the port; `tailscale serve reset` clears that if you want.")
    return 0


def _print_stages(out: dict) -> None:
    marks = {"ok": "  ok    ", "skip": "  --    ", "warn": "  note  ", "fail": "  FAIL  "}
    for stage in out["stages"]:
        print(f"{marks.get(stage['state'], '  ?     ')}{stage['stage']:<8} {stage['detail']}")
    print(f"\n  {out['human']}")
    if out.get("problem"):
        problem = out["problem"]
        print(f"  {problem['fix']}")
        print(f"  detail: {problem['developer']}")
    if out.get("note"):
        print(f"  {out['note']}")


def restart(port: int) -> int:
    """The same restart CROOKS Control's button and crooks-update run on this platform:
    scripts/service_linux.restart(), which restarts the service and then READS /HEALTH BACK.
    A `systemctl restart` that exits 0 for a service that dies on its first import is exactly
    the lie §26 is about, and it is what this used to print and call done."""
    from scripts import service_linux as svc

    machine = svc.Machine.real(port)
    out = svc.restart(machine, svc.Systemd(machine), port=port)
    _print_stages(out)
    return 0 if out["ok"] else 1


def status(port: int) -> int:
    active = systemctl("is-active", lc.SERVICE_UNIT).stdout.strip()
    enabled = systemctl("is-enabled", lc.SERVICE_UNIT).stdout.strip()
    if active == "active":
        print(f"  ok     {lc.SERVICE_UNIT}: active ({enabled or 'unknown'} at boot)")
    else:
        print(f"  DOWN   {lc.SERVICE_UNIT}: {active or 'not installed'} ({enabled or 'not enabled'})")
    host, note = lc.serve_status(port)
    print(f"  https  https://{host}/" if host else f"  https  {note}")
    health = lc.fetch_health(f"http://127.0.0.1:{port}/health")
    print(f"  health {lc.summarise_health(health)}")
    return 0 if active == "active" and health_known(health) else 1


def health_known(health: dict | None) -> bool:
    """Whether /health answered with its checks, so what it says of them is known (round 9,
    A1B-STATUS). A `limited` answer — liveness alone, what a reader the owner rule refuses gets —
    or one with no checks at all says nothing of the essentials, and a status that reads it as
    well would call an unknown state a working one."""
    if not isinstance(health, dict) or lc.health_limited(health):
        return False
    checks = health.get("checks")
    return isinstance(checks, dict) and bool(checks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--uninstall", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--restart", action="store_true")
    group.add_argument("--print", action="store_true", help="show the rendered unit and exit")
    args = parser.parse_args(argv)

    if args.print:
        print(rendered_unit())
        return 0
    if not lc.is_linux():
        print("systemd is Linux only. On the Mac use: make install (launchd)")
        return 1
    from config.settings import get_settings

    port = get_settings().port
    if args.uninstall:
        return uninstall()
    if args.status:
        return status(port)
    if args.restart:
        return restart(port)
    return install(port)


if __name__ == "__main__":
    raise SystemExit(main())
