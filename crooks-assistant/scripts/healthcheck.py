#!/usr/bin/env python3
"""The production health check: is CROOKS OS well, in one line and one exit code.

    python scripts/healthcheck.py          one line; exit 0 well, 1 not
    python scripts/healthcheck.py -v       every check, one per line
    python scripts/healthcheck.py --json   the raw /health document

Written to be run by a person at a prompt, by a systemd timer, or by anything that reads an
exit code. It invents no opinion of its own about whether the machine is well: "the
essentials" are the three `scripts/control.py` already names — hearing, Claude, Shopify —
because a second definition of healthy is a second thing to keep in step, and the first one
to drift is the one nobody is looking at.

The distinction this makes, and the reason it is not just `curl /health`:

    down        nothing is answering the port at all
    unhealthy   an essential subsystem is down — the assistant cannot do its job
    degraded    something non-essential is down, or deliberately not deployed here
    ok          everything that is deployed is working

`degraded` exits 0. A server that was never given a local speech fallback is not a broken
server, and a check that goes red for a thing you decided not to install is a check that
trains you to ignore it. A subsystem that is *supposed* to be here and is not working is a
different matter, and that is what exit 1 means.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import launch_common as lc  # noqa: E402
from control import ESSENTIAL  # noqa: E402 — one definition of "essential", not two

DOWN, UNHEALTHY, DEGRADED, OK = "down", "unhealthy", "degraded", "ok"


def checks_of(health: dict | None) -> dict[str, dict]:
    raw = (health or {}).get("checks")
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    return {str(c.get("name") or ""): c for c in (raw or []) if isinstance(c, dict)}


def verdict(health: dict | None) -> tuple[str, str]:
    """(state, one line). The line names what is wrong, in the owner's words."""
    if not health:
        return DOWN, "nothing is answering"
    checks = checks_of(health)
    if not checks:
        return DOWN, "answered without any checks"

    failing = [name for name, check in checks.items() if not check.get("ok")]
    essential_down = [name for name in ESSENTIAL if name in failing]
    if essential_down:
        plain = ", ".join(lc.PLAIN_NAMES.get(name, name) for name in essential_down)
        return UNHEALTHY, f"NOT working: {plain}"

    # A check that is off by configuration reports itself ok with a detail saying so; it is
    # not counted here, which is the whole point of `disabled` being distinct from `failed`.
    if failing:
        plain = ", ".join(lc.PLAIN_NAMES.get(name, name) for name in failing)
        return DEGRADED, f"working, but down: {plain}"

    speech = checks.get("speech") or {}
    if speech.get("redundancy") == "none":
        # True and worth saying every time: this host hears through ElevenLabs alone.
        return OK, "all good — no local speech fallback on this host (by design)"
    return OK, "all good"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="one line per check")
    parser.add_argument("--json", action="store_true", help="the raw /health document")
    parser.add_argument("--port", type=int, default=0, help="override the configured port")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    port = args.port
    if not port:
        from config.settings import get_settings

        port = get_settings().port

    health = lc.fetch_health(f"http://127.0.0.1:{port}/health", timeout_s=args.timeout)
    if args.json:
        print(json.dumps(health, indent=2, sort_keys=True) if health else "{}")
        return 0 if health and verdict(health)[0] in (OK, DEGRADED) else 1

    state, line = verdict(health)
    build = (health or {}).get("build") or "?"
    print(f"{state.upper():<9} {line}" + (f"  (build {build})" if health else ""))

    if args.verbose and health:
        for name, check in sorted(checks_of(health).items()):
            mark = "ok  " if check.get("ok") else "DOWN"
            print(f"  {mark}  {name:<16} {str(check.get('detail') or '')[:88]}")

    return 0 if state in (OK, DEGRADED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
