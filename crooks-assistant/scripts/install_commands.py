#!/usr/bin/env python3
"""make commands — put crooks-update, crooks-status and crooks-watch on the PATH.

Writes three small shell wrappers into ~/.local/bin (created if it is not there), each of
which runs this checkout's own Python against this checkout's own scripts. Nothing is copied:
a `git pull` updates the commands with everything else, because the wrapper points at the
files rather than containing them.

    make commands            install (or refresh) the three
    make commands-remove     take them off again

~/.local/bin is used because it needs no sudo and is on the PATH of a default macOS zsh
login shell. If it is not on yours, the command says the one line to add.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = Path.home() / ".local" / "bin"

# name -> (script, the arguments that name implies). The four test commands are one script
# with a switch each, because they are one thing done four ways and a second copy of the
# runner would be a second thing to keep in step.
COMMANDS = {
    "crooks-update": ("scripts/update.py", ""),
    "crooks-status": ("scripts/status.py", ""),
    "crooks-watch": ("scripts/watch.py", ""),
    "crooks-test": ("scripts/experience.py", ""),
    "crooks-test-ui": ("scripts/experience.py", "--ui"),
    "crooks-test-live": ("scripts/experience.py", "--live"),
    "crooks-test-scenario": ("scripts/experience.py", "--scenario"),
}

WRAPPER = """#!/bin/sh
# Written by `make commands` in {root}. Points at the checkout rather than copying it, so a
# git pull updates this command too. Delete it, or run `make commands-remove`, to undo.
exec "{python}" "{script}" {fixed} "$@"
"""


def python_for(root: Path) -> Path:
    venv = root / ".venv" / "bin" / "python"
    return venv if venv.exists() else Path(sys.executable)


def install(root: Path = ROOT, bin_dir: Path = BIN) -> int:
    bin_dir.mkdir(parents=True, exist_ok=True)
    python = python_for(root)
    for name, (script, fixed) in COMMANDS.items():
        target = bin_dir / name
        target.write_text(WRAPPER.format(root=root, python=python, script=root / script, fixed=fixed), encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"  ok     {target}")
    path = os.environ.get("PATH", "")
    if str(bin_dir) not in path.split(os.pathsep):
        print(f"\n  {bin_dir} is not on your PATH. Add this line to ~/.zshrc, then open a new Terminal:")
        print(f'    export PATH="{bin_dir}:$PATH"')
    else:
        print("\n  Try it: crooks-status")
    return 0


def remove(bin_dir: Path = BIN) -> int:
    for name in COMMANDS:
        target = bin_dir / name
        if target.exists():
            target.unlink()
            print(f"  ok     {target} removed")
        else:
            print(f"  --     {target} was not there")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args(argv)
    return remove() if args.remove else install()


if __name__ == "__main__":
    sys.exit(main())
