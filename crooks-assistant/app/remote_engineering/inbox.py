"""GitHub as transport only: a bounded remote name and ref, never an arbitrary URL or shell.

Every call here runs ``git`` with an argv list (never a shell string), against a
remote name and branch that must already look like a git identifier, not a URL. The
adapter fetches only the one configured remote and the one dedicated inbox branch; it
never accepts a URL, a refspec with wildcards, or a shell fragment from request content.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .errors import InboxError

DEFAULT_INBOX_BRANCH = "clive/control/owner-inbox"
DEFAULT_INBOX_DIRECTORY = "requests"

_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _validate_name(value: str, *, what: str) -> str:
    if (
        not value
        or value.startswith(("-", "/"))
        or value.endswith("/")
        or ".." in value
        or not _NAME_RE.fullmatch(value)
    ):
        raise InboxError(f"{what} {value!r} is not a bounded git identifier")
    return value


def _validate_remote(value: str) -> str:
    _validate_name(value, what="remote")
    if "://" in value or "@" in value or ":" in value:
        raise InboxError(f"remote {value!r} must be a configured remote name, never a URL")
    return value


def fetch_inbox(
    repo: Path, *, remote: str = "origin", branch: str = DEFAULT_INBOX_BRANCH, timeout_s: int = 60
) -> str:
    """Fetch exactly one remote's one branch and return the commit it now points at."""
    remote = _validate_remote(remote)
    branch = _validate_name(branch, what="inbox branch")
    proc = subprocess.run(
        ["git", "fetch", "--quiet", remote, branch],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise InboxError(f"fetch of {remote} {branch} failed: {(proc.stderr or proc.stdout).strip()}")
    rev = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}^{{commit}}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    sha = rev.stdout.strip()
    if rev.returncode != 0 or len(sha) != 40:
        raise InboxError(f"refs/remotes/{remote}/{branch} did not resolve to a commit after fetch")
    return sha


def discover_requests(
    repo: Path, ref_sha: str, directory: str = DEFAULT_INBOX_DIRECTORY
) -> tuple[tuple[str, bytes], ...]:
    """Every ``*.json`` request file under ``directory`` at ``ref_sha``, by name, oldest path order."""
    directory = directory.strip("/")
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", ref_sha, "--", directory],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if listing.returncode != 0:
        raise InboxError(f"cannot list {directory!r} at {ref_sha}: {listing.stderr.strip()}")
    names = sorted(name for name in listing.stdout.split("\0") if name.endswith(".json"))
    out: list[tuple[str, bytes]] = []
    for name in names:
        show = subprocess.run(
            ["git", "show", f"{ref_sha}:{name}"], cwd=str(repo), capture_output=True, timeout=60
        )
        if show.returncode != 0:
            raise InboxError(f"cannot read {name!r} at {ref_sha}: {show.stderr.decode(errors='replace').strip()}")
        out.append((name, show.stdout))
    return tuple(out)
