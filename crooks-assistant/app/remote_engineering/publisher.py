"""Publish a read-only projection of remote engineering state to one bounded Git ref.

The projection is disposable output. Kernel/objective/receipt records remain authoritative.
This module never checks out a branch or mutates the working tree: it builds a one-file Git
commit with plumbing commands and pushes only to the configured status ref.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .errors import InboxError
from .inbox import _validate_name, _validate_remote

DEFAULT_STATUS_BRANCH = "clive/control/status"
DEFAULT_STATUS_PATH = "status.json"


def _git(repo: Path, *args: str, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode(errors="replace").strip()
        raise InboxError(f"git {' '.join(args[:3])} failed: {detail[-1000:]}")
    return proc


def _validate_status_path(value: str) -> str:
    value = value.strip("/")
    if (
        not value
        or value.startswith(".")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or not value.endswith(".json")
    ):
        raise InboxError(f"status path {value!r} is not a bounded repository-relative JSON path")
    return value


def publish_status(
    repo: Path,
    status: dict,
    *,
    remote: str = "origin",
    branch: str = DEFAULT_STATUS_BRANCH,
    path: str = DEFAULT_STATUS_PATH,
) -> str:
    """Publish exactly one JSON projection file and return its commit SHA.

    Re-publishing identical bytes is idempotent. The status branch is independent from
    the owner inbox branch, and each push is fast-forward from the currently fetched
    status head. A concurrent update therefore fails closed instead of being overwritten.
    """
    repo = Path(repo)
    remote = _validate_remote(remote)
    branch = _validate_name(branch, what="status branch")
    path = _validate_status_path(path)
    payload = (json.dumps(status, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode()

    fetch = _git(repo, "fetch", "--quiet", remote, branch, check=False)
    if fetch.returncode not in (0, 1, 128):
        detail = (fetch.stderr or fetch.stdout).decode(errors="replace").strip()
        raise InboxError(f"fetch of status branch {remote} {branch} failed: {detail[-1000:]}")

    ref = f"refs/remotes/{remote}/{branch}"
    rev = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    parent = rev.stdout.decode().strip() if rev.returncode == 0 else ""

    if parent:
        existing = _git(repo, "show", f"{parent}:{path}", check=False)
        if existing.returncode == 0 and existing.stdout == payload:
            return parent

    blob = _git(repo, "hash-object", "-w", "--stdin", input_bytes=payload).stdout.decode().strip()
    tree_line = f"100644 blob {blob}\t{path}\n".encode()
    tree = _git(repo, "mktree", input_bytes=tree_line).stdout.decode().strip()
    commit_args = [
        "-c", "user.name=CLIVE Remote Engineering",
        "-c", "user.email=remote-engineering@clive.invalid",
        "commit-tree", tree,
    ]
    if parent:
        commit_args += ["-p", parent]
    commit = _git(repo, *commit_args, input_bytes=b"Remote engineering status projection\n").stdout.decode().strip()
    _git(repo, "push", "--quiet", remote, f"{commit}:refs/heads/{branch}")
    return commit
