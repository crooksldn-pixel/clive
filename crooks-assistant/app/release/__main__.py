"""python -m app.release — the release service's command line.

Why it exists: the timer runs `tick`; a person (or the Termius Claude, at George's word) runs the
rest. It is run from the service's pinned copy (docs/RELEASE_SERVICE.md), as root on the server.

    tick                          what the timer runs: off unless switched on and a rule named
    plan [--sha SHA]              the dry run: every fact, the verdict, the steps; writes nothing
    status                        the line CLIVE shows on the Builds screen
    waive SHA --by NAME [--words] George's waiver of the exact-SHA review for exactly SHA, written
                                  on the host (root-only folder), for the owner_waiver rule

    --env FILE                    read the settings from FILE instead of the environment
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.release import authority, github, service, status
from app.release import settings as settings_module
from app.release.host import SystemHost

_SHA = re.compile(r"^[0-9a-f]{40}$")


def waive(host: SystemHost, settings, sha: str, by: str, words: str) -> int:
    if not _SHA.fullmatch(sha):
        print("A waiver is for an exact commit: give all 40 characters of the SHA.")
        return 2
    if not by.strip():
        print("Say who gives the waiver (--by).")
        return 2
    record = {"schema": authority.WAIVER_SCHEMA, "sha": sha, "repository": settings.repository,
              "waives": "exact_sha_review", "given_by": by.strip()[:80],
              "given_at": datetime.now(UTC).isoformat(timespec="seconds"), "words": words.strip()[:200],
              "source": "host", "passkey": None}
    folder = Path(settings.waivers_dir)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    host.write(folder / f"{sha}.json", (json.dumps(record, indent=1) + "\n").encode("utf-8"), 0o600)
    print(f"Waiver written: {folder / (sha + '.json')} ({record['given_by']}, {record['given_at']}).")
    if os.geteuid() != 0:
        print("Note: written by a user other than root, so the release service will not believe it.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.release", description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, help="read the settings from this file")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tick")
    planned = commands.add_parser("plan")
    planned.add_argument("--sha", help="the SHA to ask about (only clive/trunk's head is ever deployed)")
    commands.add_parser("status")
    waived = commands.add_parser("waive")
    waived.add_argument("sha")
    waived.add_argument("--by", required=True)
    waived.add_argument("--words", default="")
    args = parser.parse_args(argv)

    settings = settings_module.load(args.env)
    host = SystemHost()
    if args.command == "status":
        now = status.read(settings.state_dir)
        print(now["line"] + (f" ({now['at']})" if now["at"] else ""))
        return 0
    if args.command == "waive":
        return waive(host, settings, args.sha.strip().lower(), args.by, args.words)
    token = github.read_token(settings.token_name)
    if args.command == "plan":
        return service.plan(host, settings, token=token, requested=(args.sha or "").strip().lower() or None)
    return service.tick(host, settings, token=token)


if __name__ == "__main__":
    sys.exit(main())
