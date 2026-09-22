#!/usr/bin/env python3
"""make install — have the Mac start the assistant itself, at login, with no Terminal open.

Writes two launchd agents from the templates in launchd/ — the backend and whisper-server —
with this checkout's paths filled in, loads them into your login session, makes Tailscale
serve port 8000 over HTTPS in the background (which persists), and reads /health back.

    make install     install (or reinstall) and start now
    make status      is it running AS A LOGIN SERVICE, what does /health say, what is the
                     address. Exits 0 only when both are true — a backend answering from a
                     Terminal window is not a supervised one, and the number says so
    make restart     restart both services (after `git pull`, say)
    make uninstall   stop and remove the agents

These are LaunchAgents, not daemons: they run inside your login session, so the claude CLI's
own login and the Keychain both work exactly as they do in a Terminal. The Mac has to be logged
in (the lid can be shut; sleep is what you want to prevent — System Settings → Energy).

Since Phase 6 the mechanism lives in `scripts/service.py`, and this file is the typed command
for it. That is deliberate: `crooks-control start` and `make install` now register, start and
verify through exactly the same code, so a button and a typed line cannot leave the Mac in two
different states — and the launchd verbs have one place to be wrong in rather than two.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import launch_common as lc  # noqa: E402
import service as svc  # noqa: E402

AGENT_DIR = Path.home() / "Library" / "LaunchAgents"

# There was a `launchctl(*args)` here: this file's own subprocess wrapper, from before the
# verbs moved into scripts/service.py. Since that move nothing has called it, and a second,
# unused route to the one external command this appliance runs is exactly the thing a reading
# of the source has to be able to rule out. It is gone. Every launchctl invocation in this
# program now goes through service.Runner, which is the one place it can be got wrong.


def _machine(port: int) -> svc.Machine:
    return svc.Machine.real(port)


def _launchd(port: int) -> svc.Launchd:
    return svc.Launchd(_machine(port), agent_dir=AGENT_DIR)


def rendered_plists(values: dict[str, str] | None = None) -> dict[str, str]:
    return svc.Launchd(svc.Machine(), agent_dir=AGENT_DIR).rendered(values)


def preflight() -> list[str]:
    problems = []
    if not lc.VENV_PYTHON.exists():
        problems.append(f"no virtualenv at {lc.VENV_PYTHON} — run: make venv")
    if not lc.find_claude():
        problems.append("the claude CLI was not found — install it and open a new Terminal")
    if not lc.find_tailscale():
        problems.append("Tailscale was not found — the tablet needs its HTTPS address")
    return problems


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


def install(port: int) -> int:
    """Register the agents and start them. Always rewrites the plists — that is what makes
    this a reinstall as well as an install, and why it is not just `service.start`, which
    leaves an existing registration alone."""
    problems = preflight()
    for problem in problems:
        print(f"  FAIL   {problem}")
    if problems:
        return 1
    lc.LOG_DIR.mkdir(parents=True, exist_ok=True)
    launchd = _launchd(port)
    # bootout, write, bootstrap — launchd will not reload a changed plist in place.
    for label, target in launchd.write_agents():
        ran = launchd.bootstrap(label)
        if not ran.ok:
            print(f"  FAIL   {label}: {ran.said}")
            return 1
        launchd.kickstart(label)
        print(f"  ok     {label} → {target}")
    host, note = lc.ensure_serve(port)
    print(f"  https  https://{host}/  ({note})" if host else f"  https  not available: {note}")
    print("  wait   backend starting…")
    health = svc.wait_for_health(_machine(port), timeout_s=60)
    print(f"  health {lc.summarise_health(health)}")
    if health is None:
        print(f"         look in {lc.LOG_DIR}/assistant.err.log")
        return 1
    print("\n  Done. Both services now start when you log in. Open the address above on the tablet.")
    return 0


def uninstall() -> int:
    launchd = _launchd(_port_or_default())
    for label in lc.AGENTS:
        launchd.bootout(label)
        target = launchd.plist_path(label)
        if target.exists():
            target.unlink()
        print(f"  ok     {label} removed")
    print("  Tailscale still serves port 8000; `tailscale serve reset` clears that if you want.")
    return 0


def restart(port: int) -> int:
    """The same restart the Control app's button runs: kickstart both agents, then READ
    /health BACK. The old version of this printed launchctl's exit code and called it done,
    which is exactly the lie §26 is about — a service that dies on its first import kickstarts
    perfectly well."""
    machine = _machine(port)
    out = svc.restart(machine, svc.Launchd(machine, agent_dir=AGENT_DIR), port=port)
    _print_stages(out)
    return 0 if out["ok"] else 1


def status(port: int) -> int:
    machine = _machine(port)
    # Read once and hand it on: /health is a real piece of work on the Mac (a Shopify query,
    # a Gmail profile, half a second of whisper), and asking for it twice to print one screen
    # is the kind of waste that turns a status command into something people avoid running.
    health = machine.read_health(False)
    life = svc.lifecycle(machine, svc.Launchd(machine, agent_dir=AGENT_DIR), port=port, health=health)
    for agent in life["agents"]:
        if not agent["installed"] and not agent["loaded"]:
            print(f"  --     {agent['label']}: not installed (make install)")
            continue
        pid = agent["pid"]
        print(f"  {'ok    ' if pid else 'DOWN  '} {agent['label']}: {agent['detail'] or 'unknown'}{' pid ' + str(pid) if pid else ''}")
    host, note = lc.serve_status(port)
    print(f"  https  https://{host}/" if host else f"  https  {note}")
    print(f"  health {lc.summarise_health(health)}")
    print(f"  state  {life['human']}")
    # ANSWERING and SUPERVISED are two different facts, and this code says the second one as
    # well as the first. `make up` leaves a backend running as a child of a Terminal window:
    # it answers /health perfectly and it dies when the window is closed. Exiting 0 over that
    # told every script, monitor and person downstream that the Mac was installed and looked
    # after, which is precisely what it was not. The sentence above already says which of the
    # two was found; now the number agrees with it.
    return 0 if (life["healthy"] and life["supervised"]) else 1


def _port_or_default() -> int:
    try:
        from config.settings import get_settings

        return get_settings().port
    except Exception:  # noqa: BLE001 — uninstall must work on a checkout whose settings will not load
        return 8000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--uninstall", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--restart", action="store_true")
    group.add_argument("--print", action="store_true", help="show the rendered plists and exit")
    args = parser.parse_args(argv)

    if args.print:
        for label, body in rendered_plists().items():
            print(f"# {label}\n{body}\n")
        return 0
    if not lc.is_macos():
        print("launchd is macOS only. On other systems use: make up")
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
