#!/usr/bin/env python3
"""crooks-update — bring this Mac up to date, in one word, safely.

    crooks-update              fetch, fast-forward, install what changed, restart, verify
    crooks-update --check      say what WOULD happen and change nothing
    crooks-update --branch X   update a branch other than the one checked out
    crooks-update --test       run the offline suite after the fast-forward, before the restart
    crooks-update --json       one JSON document instead of the lines, for CROOKS Control

Eight stages, each of which reports itself and any of which stops the run:

    1  find      the checkout this command belongs to
    2  branch    it is the branch you meant, and the tree is clean enough to move
    3  fetch     from the remote
    4  pull      FAST-FORWARD ONLY — never a merge, never a rebase, never a reset
    5  deps      only when the dependency files actually changed
    6  tests     the offline suite, when --test asks for it — nothing restarts if it fails
    7  restart   the backend and whisper-server, through launchd
    8  verify    /health, read back, with the build id

What it will not do, by construction:

  * touch .env, or anything in logs/, or any credential (they are not in git, and nothing
    here writes them)
  * discard local work: a dirty tree or a diverged branch STOPS the update and says so.
    There is no --force, and no reset.
  * decide to update itself. This runs when George types it, and not otherwise; nothing in
    CROOKS OS calls it. `crooks-control apply` is the same rule wearing a button: it runs
    when George clicks it, and never on a timer or on a boot.

--json prints one document and no lines. That document is the contract CROOKS Control
renders — both SHAs, every stage, the local work that stopped it — and tests/test_control.py
holds it to its shape, so the Swift side cannot drift from this side.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

# Files whose change means the dependencies need installing again. Anything else is code.
DEP_FILES = ("pyproject.toml", "uv.lock", "requirements.txt")
# Never written, never checked out over, never mentioned to git by this command.
NEVER_TOUCH = (".env", "logs", "reports", ".venv")

OK, FAIL, SKIP = "  ok   ", "  FAIL ", "  --   "
# The version of the --json document. CROOKS Control refuses a number it does not know
# rather than rendering a field that has moved under it.
CONTRACT = 1
# The offline suite, exactly as `make test` runs it. --test runs it between the fast-forward
# and the restart, so a build that does not pass here never becomes the running build.
TEST_COMMAND = (".venv/bin/pytest", "-q", "-m", "not live")
TEST_TIMEOUT_S = 1800

# What each stage said, in order, and whether to print it as it is said. A run collects both:
# the lines are for the owner at the keyboard, and the same records are the JSON document's
# "stages" for the app.
_LINES: list[dict] = []
_QUIET = False
_STATE_WORD = {OK: "ok", FAIL: "fail", SKIP: "skip"}


def say(state: str, stage: str, detail: str) -> None:
    _LINES.append({"stage": stage, "state": _STATE_WORD[state], "detail": detail})
    if not _QUIET:
        print(f"{state} {stage:<8} {detail}")


def short(sha: str) -> str:
    """A SHA as the owner reads it: ten characters, and never git's own abbreviation — an
    abbreviation that grows with the repository is not an identifier two processes can
    compare."""
    return (sha or "")[:10]


class Stopped(RuntimeError):
    """A stage said no. The message is what the owner reads; nothing is undone."""


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    # ROOT is looked up at call time, not bound as a default: a default would freeze the
    # checkout at import and make this untestable against any other one.
    out = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, timeout=120)
    if check and out.returncode != 0:
        raise Stopped((out.stderr or out.stdout or "git failed").strip().splitlines()[-1][:300])
    return (out.stdout or "").strip()


def stage_find() -> Path:
    top = Path(git("rev-parse", "--show-toplevel"))
    say(OK, "repo", str(top))
    return top


# The letters git puts in the two status columns. Anything else there is a path.
_STATUS_CHARS = "MADRCTU?!"


def _porcelain_path(line: str) -> str:
    """The path out of a `git status --porcelain` line. Two status characters, a space, then
    the path — or "old -> new" for a rename, where the new name is the one that matters.

    Not a fixed offset, because `git()` strips the output it returns: an unstaged change on
    the FIRST line arrives as "M path" rather than " M path", and reading from column three
    then ate the first character of the path. A `.env` edited by hand is exactly that line,
    and "env" does not match NEVER_TOUCH — so the bug stopped an update it should have let
    through. The status letters are read off instead.
    """
    text = line.strip()
    cut = 0
    while cut < len(text) and text[cut] in _STATUS_CHARS:
        cut += 1
    path = text[cut:].strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip('"')


def dirty_paths() -> list[str]:
    """Every path git calls changed here, tracked or not. Read once and passed around: the
    plan the app renders and the refusal the update raises have to be the same answer."""
    seen = (_porcelain_path(line) for line in git("status", "--porcelain").splitlines() if line.strip())
    return [path for path in seen if path]


def blocking_changes(dirty: list[str]) -> list[str]:
    """The dirty paths that stop an update. Everything except NEVER_TOUCH: .env is the owner's
    own configuration, logs/ and reports/ are what the Mac has written, .venv is built."""
    return [d for d in dirty if not any(d == p or d.startswith(f"{p}/") or f"/{p}/" in d or d.endswith(f"/{p}") for p in NEVER_TOUCH)]


def stage_branch(wanted: str, dirty: list[str] | None = None) -> str:
    """The branch this update moves, and the one recovery this stage performs itself.

    A rollback checks out an older build and leaves the checkout with no branch attached.
    That used to be a dead end: Update refused ("`git checkout <branch>` first"), Mark good
    refused, and the only way forward was a Terminal — at exactly the moment the owner had
    just recovered from a bad build by pressing a button. So when the checkout is detached
    on a build that is part of the wanted branch's history, which is what a rollback leaves,
    this stage comes forward onto the branch itself. It is a fast-forward of HEAD to a
    branch that already contains it; no work exists here to lose, because the dirty-tree
    check below runs first and a detached checkout with local changes is still refused.
    """
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = dirty_paths() if dirty is None else dirty
    blocking = blocking_changes(dirty)
    if blocking:
        listed = ", ".join(blocking[:5])
        raise Stopped(f"There are local changes here ({listed}{'…' if len(blocking) > 5 else ''}). Commit or stash them; this command will not throw work away.")
    if branch == "HEAD":
        if not wanted:
            raise Stopped("This checkout is on a build with no branch attached (a rollback leaves it that way), and no branch was named to come forward onto. Press Update in CROOKS Control, which names it.")
        head = git("rev-parse", "HEAD")
        on_branch = subprocess.run(["git", "merge-base", "--is-ancestor", head, wanted], cwd=ROOT,
                                   capture_output=True, text=True).returncode == 0
        if not on_branch:
            raise Stopped(f"This checkout is on a build that is not part of {wanted}, so nothing was moved. Press Roll back to return to the last known-good build, then Update.")
        moved = subprocess.run(["git", "checkout", "-q", wanted, "--"], cwd=ROOT, capture_output=True, text=True)
        if moved.returncode != 0:
            raise Stopped(f"This checkout could not be put back on {wanted}, so nothing was moved: {(moved.stderr or moved.stdout).strip()[:200]}")
        say(OK, "branch", f"came forward onto {wanted} from a build with no branch attached (a rollback leaves it that way)")
        branch = wanted
    if wanted and branch != wanted:
        raise Stopped(f"This checkout is on {branch}, not {wanted}, so nothing was moved: this command does not switch branches.")
    say(OK, "branch", branch + (f"  ({len(dirty)} untracked/ignored file(s) left alone)" if dirty else ""))
    return branch


def stage_fetch(branch: str) -> tuple[str, str, int, int]:
    remote = git("config", f"branch.{branch}.remote", check=False) or "origin"
    git("fetch", remote, branch)
    local = git("rev-parse", "HEAD")
    upstream = git("rev-parse", f"{remote}/{branch}")
    behind = int(git("rev-list", "--count", f"HEAD..{remote}/{branch}") or 0)
    ahead = int(git("rev-list", "--count", f"{remote}/{branch}..HEAD") or 0)
    say(OK, "fetch", f"{remote}/{branch}  {behind} to come, {ahead} of yours not pushed")
    return local, upstream, behind, ahead


def stage_pull(branch: str, behind: int, ahead: int, *, check_only: bool) -> tuple[bool, list[str]]:
    if behind == 0:
        say(SKIP, "pull", "already up to date")
        return False, []
    if ahead:
        raise Stopped(
            f"This branch has {ahead} commit(s) the remote does not, so it cannot fast-forward. "
            "Push or rebase them yourself; this command will not rewrite your history."
        )
    remote = git("config", f"branch.{branch}.remote", check=False) or "origin"
    changed = git("diff", "--name-only", "HEAD", f"{remote}/{branch}", "--").splitlines()
    if check_only:
        say(SKIP, "pull", f"would fast-forward {behind} commit(s), {len(changed)} file(s)")
        return False, changed
    git("merge", "--ff-only", f"{remote}/{branch}")
    say(OK, "pull", f"fast-forwarded {behind} commit(s), {len(changed)} file(s)")
    return True, changed


def dep_changes(changed: list[str]) -> list[str]:
    """The dependency files in a list of changed paths — the reason to reinstall, or not."""
    return [f for f in changed if Path(f).name in DEP_FILES]


def stage_deps(changed: list[str], *, check_only: bool) -> bool:
    needed = dep_changes(changed)
    if not needed:
        say(SKIP, "deps", "unchanged")
        return False
    if check_only:
        say(SKIP, "deps", f"would reinstall ({', '.join(needed)})")
        return False
    pip = ROOT / ".venv" / "bin" / "pip"
    if not pip.exists():
        raise Stopped("There is no .venv here, so the suite cannot be run and nothing was restarted. This machine's Python side needs setting up again before an update can be tested.")
    out = subprocess.run([str(pip), "install", "-q", "-e", ".[dev]"], cwd=ROOT, capture_output=True, text=True, timeout=900)
    if out.returncode != 0:
        raise Stopped("Installing the dependencies failed:\n" + (out.stderr or out.stdout)[-600:])
    say(OK, "deps", f"reinstalled ({', '.join(needed)})")
    return True


def stage_tests(*, check_only: bool, enabled: bool) -> bool:
    """The offline suite, between the fast-forward and the restart.

    Off unless asked for, because `crooks-update` is the two-minute command George types when
    he wants the new code running and the suite is six of those minutes. CROOKS Control's
    Update button asks for it: a click has no way to read a test failure afterwards, so the
    failure has to arrive before anything restarts. A failure here means the code on disk has
    moved and the running build has not — which is exactly what the rollback decision is for.
    """
    if not enabled:
        say(SKIP, "tests", "not asked for (crooks-update --test, or the Control app's Update)")
        return False
    if check_only:
        say(SKIP, "tests", "would run " + " ".join(TEST_COMMAND))
        return False
    pytest_bin = ROOT / TEST_COMMAND[0]
    if not pytest_bin.exists():
        raise Stopped(f"There is no {TEST_COMMAND[0]} here, so the suite cannot be run and nothing was restarted. This machine's Python side needs setting up again before an update can be tested.")
    out = subprocess.run([str(pytest_bin), *TEST_COMMAND[1:]], cwd=ROOT, capture_output=True, text=True, timeout=TEST_TIMEOUT_S)
    tail = (out.stdout or out.stderr or "").strip().splitlines()
    if out.returncode != 0:
        raise Stopped(
            "The offline suite did not pass on the new code, so nothing was restarted:\n  "
            + "\n  ".join(tail[-6:])
            + "\nThe running build is untouched. `crooks-control rollback` puts the checkout back."
        )
    say(OK, "tests", tail[-1][:120] if tail else "passed")
    return True


def mac_for(port: int):
    """The machine this stage acts on, as (machine, supervisor): the Mac and its launchd, or
    the server and its systemd. One function, so a test can hand the restart stage a machine
    that is not one without also replacing the decision under test. The name is the Mac's,
    from when it was the only one, and stays because tests replace it by name."""
    import launch_common as lc

    from scripts import service as svc

    machine = svc.Machine.real(port)
    if lc.is_macos():
        return machine, svc.supervisor(machine, root=ROOT)
    from scripts import service_linux as linux

    return machine, linux.supervisor(machine, root=ROOT)


def lifecycle_module_for(supervisor):
    """The module whose start/stop/restart know this supervisor. Decided by the supervisor
    handed in, not by the host: a test that hands the Mac's launchd in on a Linux runner gets
    the Mac's layer and the Mac's sentences."""
    from scripts import service, service_linux

    return service_linux if isinstance(supervisor, service_linux.Systemd) else service


def _mac_module():
    from scripts import service

    return service


# What the owner is told to do when the restart is the thing that failed. §5.2: the recovery
# from a stopped appliance is a BUTTON. This stage used to end by telling him to open a
# Terminal and run the installer once — printed at exactly the moment an owner has had his
# code moved and his Mac left down, and carried verbatim into the `stop.reason` the app
# draws. Since scripts/service.py can register and start the agents itself, there is nothing
# left for a Terminal to do here, and nothing in this file names a shell command for it.
PRESS_INSTEAD = (
    "Your code IS updated; only the restart failed. In CROOKS Control, press Start; "
    "if that does not bring it back, press Roll back."
)
# The server has no Control app window, but it has the same commands, and naming them is
# what the no-terminal rule allows: the remedy is CROOKS OS's own command, not a shell recipe.
START_INSTEAD = (
    "Your code IS updated; only the restart failed. `crooks-control start` brings it back; "
    "if that does not, `crooks-control rollback` puts the previous build back."
)


def stage_restart(*, check_only: bool, port: int) -> None:
    """Stage 7, and the only stage that is not the same code on both platforms — but the same
    RULE on both. service.restart() through launchd on the Mac, service_linux.restart() through
    systemd on the server: each registers the service first where the supervisor does not have
    it, each is the very code the Control app's Restart button runs, so the typed command and
    the button cannot leave the machine in two different states, and each succeeds only when
    /health answers — never because launchctl or systemctl exited 0.
    """
    import launch_common as lc

    what = " and ".join(lc.service_labels())
    if check_only:
        say(SKIP, "restart", f"would restart {what}")
        return
    machine, supervisor = mac_for(port)
    out = lifecycle_module_for(supervisor).restart(machine, supervisor, port=port)
    if not out["ok"]:
        problem = out.get("problem") or {}
        detail = str(problem.get("developer") or "")[:300]
        raise Stopped(
            (problem.get("human") or out.get("human") or "The services would not restart.")
            + (f"\n  {detail}" if detail else "")
            + "\n" + (START_INSTEAD if lifecycle_module_for(supervisor) is not _mac_module() else PRESS_INSTEAD)
        )
    say(OK, "restart", out["human"])


def stage_verify(*, check_only: bool, port: int) -> dict | None:
    import launch_common as lc

    if check_only:
        say(SKIP, "verify", "would read /health back")
        return None
    health = lc.wait_for_health(f"http://127.0.0.1:{port}/health", timeout_s=90)
    if not health:
        raise Stopped("The backend did not come back healthy within 90 seconds. Nothing was undone: the new code is in place and the service is still trying. Roll back returns to the last known-good build if it does not recover on its own.")
    say(OK, "verify", lc.summarise_health(health))
    return health


def report(port: int) -> None:
    """The concise status the owner reads at the end. Same shape as crooks-status."""
    from scripts.status import show

    print()
    show(port)


def _document(**fields) -> dict:
    """The --json document, with every key present whatever happened. A field that appears
    only on the happy path is a field the app has to guess about."""
    doc = {
        "contract": CONTRACT, "command": "crooks-update", "ok": False, "check": False,
        "repo": "", "branch": "",
        # The build on this Mac, the build being offered, and how far apart they are.
        "current": None, "candidate": None, "behind": 0, "ahead": 0, "fast_forward": False,
        # The owner's uncommitted work: what is here, what of it stops the update.
        "local_work": {"dirty": [], "blocking": [], "stops": False},
        "deps": [], "changed_files": 0,
        # What actually happened, stage by stage.
        "moved": False, "tested": False, "restarted": False, "verified": False,
        "stages": [], "stop": None, "next": "unknown",
    }
    doc.update(fields)
    return doc


def run(*, check: bool = False, branch: str = "", test: bool = False, quiet: bool = False) -> tuple[int, dict]:
    """The whole command, once, as (exit code, document). `quiet` prints nothing and is what
    --json and CROOKS Control use; everything else is identical either way — one flow, so a
    button cannot take a different path through this than the typed command does.

    The quiet is put back afterwards whatever happened: a stage called on its own — by a
    test, or by another script — prints its line, and a run that swallowed the next caller's
    output would be a silence nobody could explain.
    """
    global _LINES, _QUIET

    _LINES, _QUIET = [], quiet
    try:
        return _run(check=check, branch=branch, test=test, quiet=quiet)
    finally:
        _QUIET = False


def _run(*, check: bool, branch: str, test: bool, quiet: bool) -> tuple[int, dict]:
    from config.settings import get_settings

    port = get_settings().port
    doc = _document(check=check, stages=_LINES)
    if not quiet:
        print("crooks-update" + ("  (check only — nothing will change)" if check else ""))
    stage = "repo"
    try:
        doc["repo"] = str(stage_find())
        stage = "branch"
        dirty = dirty_paths()
        blocking = blocking_changes(dirty)
        doc["local_work"] = {"dirty": dirty, "blocking": blocking, "stops": bool(blocking)}
        doc["branch"] = branch_now = stage_branch(branch, dirty)
        head = git("rev-parse", "HEAD")
        doc["current"] = {"sha": head, "short": short(head)}
        stage = "fetch"
        _local, upstream, behind, ahead = stage_fetch(branch_now)
        doc["candidate"] = {"sha": upstream, "short": short(upstream)}
        doc["behind"], doc["ahead"] = behind, ahead
        # Fast-forward is the ONLY way this command moves. Anything of the owner's that the
        # remote does not have makes it impossible, and that is a stop, never a rewrite.
        doc["fast_forward"] = ahead == 0
        stage = "pull"
        moved, changed = stage_pull(branch_now, behind, ahead, check_only=check)
        doc["moved"], doc["changed_files"] = moved, len(changed)
        stage = "deps"
        doc["deps"] = dep_changes(changed)
        stage_deps(changed, check_only=check)
        stage = "tests"
        doc["tested"] = stage_tests(check_only=check, enabled=test and (moved or (check and behind > 0)))
        if moved:
            stage = "restart"
            stage_restart(check_only=check, port=port)
            doc["restarted"] = not check
            stage = "verify"
            health = stage_verify(check_only=check, port=port)
            doc["verified"] = health is not None
            if health is not None:
                doc["current"]["build"] = str(health.get("build") or "")
        elif not check:
            say(SKIP, "restart", "nothing changed, so nothing was restarted")
    except Stopped as exc:
        doc["stop"] = {"stage": stage, "reason": str(exc)}
        doc["next"] = "blocked"
        if not quiet:
            print(f"{FAIL} {exc}")
            print("\nNothing was changed. Fix the line above and run crooks-update again.")
        return 1, doc
    except (OSError, subprocess.SubprocessError) as exc:
        doc["stop"] = {"stage": stage, "reason": f"{type(exc).__name__}: {exc}"}
        doc["next"] = "blocked"
        if not quiet:
            print(f"{FAIL} {type(exc).__name__}: {exc}")
        return 1, doc
    doc["ok"] = True
    doc["next"] = (
        "up_to_date" if doc["behind"] == 0
        else "click_to_apply" if check
        else "verify_the_tablet"
    )
    if not check:
        if not quiet:
            report(port)
    return 0, doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="say what would happen; change nothing")
    parser.add_argument("--branch", default="", help="the branch this checkout should be on")
    parser.add_argument("--test", action="store_true", help="run the offline suite after the fast-forward, before the restart")
    parser.add_argument("--json", action="store_true", help="one JSON document instead of the lines; what CROOKS Control reads")
    args = parser.parse_args(argv)
    code, doc = run(check=args.check, branch=args.branch, test=args.test, quiet=args.json)
    if args.json:
        # A stopped git command quotes what it was doing, and a remote URL can carry a token
        # in it. The document goes out through the same redactor the app's documents do —
        # imported here rather than at the top, because control.py reads this module.
        from scripts.control import redact

        print(json.dumps(redact(doc), indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
