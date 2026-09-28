#!/usr/bin/env python3
"""Run the experience suite and write down what happened.

    python scripts/experience.py                 the golden scenarios against the fixture world
    python scripts/experience.py --scenario back just one, by name
    python scripts/experience.py --list          what there is to run
    python scripts/experience.py --live          the real shop and inbox, read-only, no writes
    python scripts/experience.py --ui            drive the page in a browser and take pictures

The `make` targets and the three words on the PATH (crooks-test, crooks-test-ui,
crooks-test-live, crooks-test-scenario) all come here.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

BOLD, DIM, GREEN, RED, AMBER, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[0m"
MARK = {"PASS": f"{GREEN}✓{RESET}", "PARTIAL": f"{AMBER}~{RESET}", "FAIL": f"{RED}✗{RESET}"}


async def run(args: argparse.Namespace) -> int:
    from experience import report as report_mod
    from experience.harness import harness
    from experience.scenarios import SCENARIOS, run_all

    if args.list:
        for name, fn in SCENARIOS:
            print(f"  {name:20} {(fn.__doc__ or '').strip().splitlines()[0][:70] if fn.__doc__ else ''}")
        return 0

    mode = "live read-only" if args.live else "fixture"
    print(f"{BOLD}CROOKS OS · experience{RESET}  {DIM}{mode}{RESET}")
    if args.live:
        from experience.live import credentials_available

        ready, why = credentials_available()
        if not ready:
            print(f"{AMBER}Live mode needs the real credentials on this machine: {why}.{RESET}")
            print(f"{DIM}Run `make experience` for the fixture world, which needs nothing.{RESET}")
            return 2
        print(f"{AMBER}LIVE READ-ONLY TEST MODE — real reads, no change can be executed.{RESET}")
        print(f"{DIM}A narrowed set of scenarios runs: the rest name a fixture record.{RESET}")

    shots: list[Path] = []
    async with harness(live=args.live, admitted=True) as h:
        results = await run_all(h, only=args.scenario)
        if args.ui:
            from experience.browser import capture_screens

            shots = await capture_screens(h, out=ROOT / ".cache" / "experience-shots",
                                          only=args.scenario)

    width = max((len(r.name) for r in results), default=10)
    for r in results:
        print(f"  {MARK.get(r.status, '?')} {r.name:{width}}  {DIM}{r.title}{RESET}")
        if r.error:
            print(f"      {RED}{r.error}{RESET}")
        for c in r.failures:
            print(f"      {RED}fail{RESET} {c.what} {DIM}{c.detail}{RESET}")

    guarantees = []
    if args.live:
        from experience.live import guarantees as live_guarantees

        guarantees = live_guarantees()
    out = report_mod.write(results, mode=mode, guarantees=guarantees, screenshots=shots)

    passed = sum(1 for r in results if r.status == "PASS")
    print()
    print(f"{BOLD}{passed}/{len(results)} scenarios pass{RESET}   report: {DIM}{out}{RESET}")
    if shots:
        print(f"{len(shots)} screenshots   {DIM}{out / 'screenshots'}{RESET}")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CROOKS OS experience suite.")
    parser.add_argument("--scenario", default="", help="run one scenario by name")
    parser.add_argument("--list", action="store_true", help="list the scenarios")
    parser.add_argument("--live", action="store_true",
                        help="use the real Shopify and Gmail credentials, read-only")
    parser.add_argument("--ui", action="store_true",
                        help="also drive the page in a browser and take screenshots")
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
