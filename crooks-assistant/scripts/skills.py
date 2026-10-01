#!/usr/bin/env python3
"""Install, uninstall and list the skills CLIVE has adopted from the digester (app/skills/install.py).

    python scripts/skills.py install ARTIFACT_ID --store DIR --quarantine DIR
        [--skills-dir DIR] [--skill NAME ...]
    python scripts/skills.py uninstall NAME [--skills-dir DIR]
    python scripts/skills.py list [--skills-dir DIR]

install reads the artifact's records in the digest store at --store (only reads: the store is
never created or written) and installs each approved skill — the owner's builder_skill decision,
or CLIVE's curated proposal — byte for byte from its quarantined copy under --quarantine into
--skills-dir (default crooks-assistant/.state/skills, which git ignores; a skills directory
anywhere else inside this repository is refused), with its licence and provenance.json. --skill
installs only the skills named. Nothing from a skill is executed, imported or installed anywhere
else, and there is no network.

One line is printed per skill: installed, already installed, refused (held, owner, conflict or
name) with the reason, deferred (scripts) with the files, or not approved, with why. A blocked
artifact, which has no skills to name, is refused as held: one line, or one per --skill named.
Anything from the artifact is printed through intake.shown and scan.redact.

uninstall removes an install wholly and says whether its bytes still matched; a name not
installed changes nothing. list prints one line per install.

Exit status: 0 every approved skill asked for is installed or already installed (and uninstall
or list done); 2 an approved skill was refused or deferred, or the artifact was blocked in
quarantine (or uninstall refused a link or a folder that is not an install); 1 could not run (bad
arguments, no such artifact in the store, a quarantined copy that does not match its digest, a
skills directory inside the repository, or a file that cannot be written: each skill settled
before it is still printed)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The script runs standalone (python scripts/skills.py); it must find the app package.
_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from app.digest import scan  # noqa: E402
from app.digest.intake import shown  # noqa: E402
from app.skills.install import (  # noqa: E402
    ALREADY,
    DEFAULT_SKILLS_DIR,
    DEFERRED,
    HELD,
    INSTALLED,
    REFUSED,
    InstallError,
    Outcome,
    UninstallRefused,
    install,
    installed,
    uninstall,
)

DONE = 0
FAILED = 1
HELD_BACK = 2


class _Parser(argparse.ArgumentParser):
    """Bad arguments exit 1, so that 2 always means a skill was refused or deferred."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(FAILED, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Install, uninstall and list the skills CLIVE has adopted.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    adding = commands.add_parser("install", help="install an artifact's approved skills")
    adding.add_argument("artifact_id", help="the artifact's id in the digest store (art-...)")
    adding.add_argument("--store", type=Path, required=True, help="the digest store, only read")
    adding.add_argument("--quarantine", type=Path, required=True,
                        help="the quarantine root holding the artifact's copy")
    adding.add_argument("--skill", action="extend", nargs="+", metavar="NAME",
                        help="install only the skills named")
    removing = commands.add_parser("uninstall", help="remove an installed skill")
    removing.add_argument("name", help="the installed skill's name")
    listing = commands.add_parser("list", help="list the installed skills")
    for sub in (adding, removing, listing):
        sub.add_argument("--skills-dir", type=Path, default=DEFAULT_SKILLS_DIR,
                         help=f"where skills are installed (default {DEFAULT_SKILLS_DIR})")
    return parser


def _shown(text: object, limit: int = 300) -> str:
    """Text that may come from the artifact, as it may be printed."""
    return shown(scan.redact(str(text)), limit)


def _line(outcome: Outcome) -> str:
    name = _shown(outcome.name, 80)
    if outcome.status == INSTALLED:
        return f"installed {name}: approved by {outcome.approved_by} -> {outcome.path}"
    if outcome.status == ALREADY:
        return f"already installed {name}: {outcome.path}"
    if outcome.status == REFUSED:
        return f"refused {name} ({outcome.kind}): {_shown(outcome.reason)}"
    if outcome.status == DEFERRED:
        files = ", ".join(_shown(path, 160) for path in outcome.files)
        return f"deferred {name} ({outcome.kind}): {_shown(outcome.reason)}: {files}"
    return f"not approved {name}: {_shown(outcome.reason)}"


def _install(args: argparse.Namespace) -> int:
    # Each line is printed as its skill is settled, so a failure part way (a disk that fills)
    # still leaves every skill already installed said before the error.
    try:
        outcomes = install(args.store, args.quarantine, args.artifact_id, args.skills_dir,
                           only=args.skill, on_outcome=lambda outcome: print(_line(outcome), flush=True))
    except InstallError as error:
        print(f"skills: {_shown(error, 2000)}", file=sys.stderr)
        return FAILED
    # A blocked artifact's held line names no approved skill (it has none to name), and it is
    # held back all the same.
    if any(o.status in (REFUSED, DEFERRED) and (o.approved or o.kind == HELD) for o in outcomes):
        return HELD_BACK
    return DONE


def _uninstall(args: argparse.Namespace) -> int:
    try:
        removal = uninstall(args.skills_dir, args.name)
    except UninstallRefused as error:
        print(f"skills: refused: {_shown(error, 2000)}", file=sys.stderr)
        return HELD_BACK
    if not removal.removed:
        print(f"not installed {removal.name}: nothing to remove")
    elif removal.matched:
        print(f"uninstalled {removal.name}: its bytes still matched what was installed")
    else:
        print(f"uninstalled {removal.name}: its bytes no longer matched what was installed")
    return DONE


def _list(args: argparse.Namespace) -> int:
    for record in installed(args.skills_dir):
        source = record.get("source") or {}
        digest = record.get("digest_record") or {}
        print(f"{_shown(record.get('name'), 80)}: from {_shown(source.get('origin'), 200)} "
              f"({_shown(digest.get('artifact_id'), 40)}), approved by "
              f"{_shown(digest.get('approved_by'), 20)}, installed {_shown(record.get('installed_at'), 40)}")
    return DONE


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run = {"install": _install, "uninstall": _uninstall, "list": _list}[args.command]
    try:
        return run(args)
    except (OSError, ValueError) as error:
        print(f"skills: {type(error).__name__}: {_shown(error, 2000)}", file=sys.stderr)
        return FAILED


if __name__ == "__main__":
    sys.exit(main())
