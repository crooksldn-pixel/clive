"""Publish a read-only projection of remote engineering state to one bounded Git ref.

The projection is disposable output. Kernel/objective/receipt records remain authoritative.
This module never checks out a branch or mutates the working tree: it builds a one-file Git
commit with plumbing commands and pushes only to the configured status ref.

Bounds, all fail-closed:

- the status branch must live under ``clive/control/`` and may never be the owner inbox;
- an existing status branch is only ever extended if its tip is already a pure projection
  (exactly one file, the status path), so a misconfigured branch name can never replace
  real repository content with a status file;
- the push is a plain fast-forward from the freshly fetched status head, never forced, so
  a concurrent update is refused instead of overwritten;
- every git call is time-bounded, so a hung transport cannot stall the control loop;
- a projection whose only difference is its ``generated_at`` stamp is not republished
  until ``heartbeat_s`` has elapsed, so an idle loop does not push a commit every cycle.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from .errors import InboxError
from .inbox import DEFAULT_INBOX_BRANCH, _validate_name, _validate_remote

DEFAULT_STATUS_BRANCH = "clive/control/status"
DEFAULT_STATUS_PATH = "status.json"
DEFAULT_STATUS_HEARTBEAT_S = 600.0
STATUS_BRANCH_NAMESPACE = "clive/control/"
VOLATILE_KEYS = ("generated_at",)

_LOCAL_TIMEOUT_S = 30
_TRANSPORT_TIMEOUT_S = 120


def _git(
    repo: Path,
    *args: str,
    input_bytes: bytes | None = None,
    check: bool = True,
    timeout_s: int = _LOCAL_TIMEOUT_S,
) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        raise InboxError(f"git {' '.join(args[:2])} exceeded {timeout_s}s; nothing was published") from None
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
        or "/" in value
        or not value.endswith(".json")
    ):
        raise InboxError(f"status path {value!r} is not a bounded repository-relative JSON path")
    return value


def _validate_status_branch(value: str) -> str:
    value = _validate_name(value, what="status branch")
    if not value.startswith(STATUS_BRANCH_NAMESPACE) or value == DEFAULT_INBOX_BRANCH:
        raise InboxError(
            f"status branch {value!r} must be a dedicated ref under {STATUS_BRANCH_NAMESPACE!r}, "
            "separate from the owner inbox"
        )
    return value


def _semantic(document: object) -> object:
    if isinstance(document, dict):
        return {key: value for key, value in document.items() if key not in VOLATILE_KEYS}
    return document


def _stamp(document: object) -> datetime | None:
    if not isinstance(document, dict) or not isinstance(document.get("generated_at"), str):
        return None
    try:
        stamp = datetime.fromisoformat(document["generated_at"])
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def _remote_head(repo: Path, remote: str, branch: str) -> str:
    """The status branch's current remote head, or "" when it does not exist yet. Errors raise."""
    probe = _git(
        repo, "ls-remote", "--exit-code", remote, f"refs/heads/{branch}",
        check=False, timeout_s=_TRANSPORT_TIMEOUT_S,
    )
    if probe.returncode == 2:
        return ""
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).decode(errors="replace").strip()
        raise InboxError(f"cannot read status branch {remote} {branch}: {detail[-1000:]}")
    _git(
        repo, "fetch", "--quiet", "--no-tags", remote,
        f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}",
        timeout_s=_TRANSPORT_TIMEOUT_S,
    )
    rev = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}^{{commit}}", check=False)
    head = rev.stdout.decode().strip()
    if rev.returncode != 0 or len(head) != 40:
        raise InboxError(f"status branch {remote} {branch} did not resolve to a commit after fetch")
    return head


def _require_pure_projection(repo: Path, head: str, path: str, branch: str) -> None:
    listing = _git(repo, "ls-tree", "-r", "-z", "--name-only", head).stdout.decode(errors="replace")
    entries = [name for name in listing.split("\0") if name]
    if entries != [path]:
        raise InboxError(
            f"status branch {branch} at {head} holds {len(entries)} path(s), not only {path!r}; "
            "refusing to overwrite a branch that is not a pure status projection"
        )


def publish_status(
    repo: Path,
    status: dict,
    *,
    remote: str = "origin",
    branch: str = DEFAULT_STATUS_BRANCH,
    path: str = DEFAULT_STATUS_PATH,
    heartbeat_s: float = DEFAULT_STATUS_HEARTBEAT_S,
) -> str:
    """Publish exactly one JSON projection file and return the commit SHA now at the status head.

    Re-publishing identical content is idempotent, and so is re-publishing content that differs
    only in ``generated_at`` while the published copy is younger than ``heartbeat_s``. The status
    branch is independent from the owner inbox branch, and each push is fast-forward from the
    freshly fetched status head. A concurrent update therefore fails closed instead of being
    overwritten.
    """
    repo = Path(repo)
    remote = _validate_remote(remote)
    branch = _validate_status_branch(branch)
    path = _validate_status_path(path)
    payload = (json.dumps(status, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode()

    parent = _remote_head(repo, remote, branch)
    if parent:
        _require_pure_projection(repo, parent, path, branch)
        existing = _git(repo, "show", f"{parent}:{path}", check=False)
        if existing.returncode == 0:
            if existing.stdout == payload:
                return parent
            try:
                published = json.loads(existing.stdout)
            except ValueError:
                published = None
            fresh = json.loads(payload)
            if published is not None and _semantic(published) == _semantic(fresh):
                before, now = _stamp(published), _stamp(fresh)
                if before is not None and now is not None and 0 <= (now - before).total_seconds() < heartbeat_s:
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
    _git(repo, "push", "--quiet", remote, f"{commit}:refs/heads/{branch}", timeout_s=_TRANSPORT_TIMEOUT_S)
    return commit
