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
    problems = preflight()
    for problem in problems:
        print(f"  FAIL   {problem}")
    if problems:
        return 1

    lc.LOG_DIR.mkdir(parents=True, exist_ok=True)
    target = lc.SYSTEMD_UNIT_PATH
    target.write_text(rendered_unit(), encoding="utf-8")
    target.chmod(0o644)
    print(f"  ok     unit → {target}")

    out = systemctl("daemon-reload")
    if out.returncode != 0:
        print(f"  FAIL   daemon-reload: {(out.stderr or out.stdout).strip()}")
        return 1
    out = systemctl("enable", lc.SERVICE_UNIT)
    if out.returncode != 0:
        print(f"  FAIL   enable: {(out.stderr or out.stdout).strip()}")
        return 1
    print(f"  ok     {lc.SERVICE_UNIT} enabled (starts at boot)")
    # restart, not start: a reinstall over a running service must pick up the new unit.
    out = systemctl("restart", lc.SERVICE_UNIT)
    if out.returncode != 0:
        print(f"  FAIL   start: {(out.stderr or out.stdout).strip()}")
        print(f"         look in: journalctl -u {lc.SERVICE_UNIT} -n 50")
        return 1
    print(f"  ok     {lc.SERVICE_UNIT} started")

    host, note = lc.ensure_serve(port)
    print(f"  https  https://{host}/  ({note})" if host else f"  https  not available: {note}")
    print("  wait   backend starting…")
    health = lc.wait_for_health(f"http://127.0.0.1:{port}/health", timeout_s=90)
    print(f"  health {lc.summarise_health(health)}")
    if health is None:
        print(f"         look in: journalctl -u {lc.SERVICE_UNIT} -n 50")
        return 1
    print("\n  Done. It starts on boot and restarts on failure. Open the address above.")
    return 0


def uninstall() -> int:
    systemctl("stop", lc.SERVICE_UNIT)
    systemctl("disable", lc.SERVICE_UNIT)
    if lc.SYSTEMD_UNIT_PATH.exists():
        lc.SYSTEMD_UNIT_PATH.unlink()
    systemctl("daemon-reload")
    print(f"  ok     {lc.SERVICE_UNIT} stopped, disabled and removed")
    print("  Tailscale still serves the port; `tailscale serve reset` clears that if you want.")
    return 0


def restart(port: int) -> int:
    out = systemctl("restart", lc.SERVICE_UNIT)
    print(f"  {'ok    ' if out.returncode == 0 else 'FAIL  '} {lc.SERVICE_UNIT} {(out.stderr or '').strip()}")
    health = lc.wait_for_health(f"http://127.0.0.1:{port}/health", timeout_s=90)
    print(f"  health {lc.summarise_health(health)}")
    return 0 if health else 1


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
    return 0 if active == "active" and health else 1


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
