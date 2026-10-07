"""The release service's own state: one deploy at a time, the line CLIVE shows, and what not to retry.

Why it exists: three things must outlive one tick of the timer.
- The lock: one deploy at a time, whoever started it (the timer, or a person running a tick by hand).
- The status: one line George reads on CLIVE's Builds screen (app/release/status.py reads it), saying
  what the service did last, in words, with the SHA's own title.
- What it will not do again on its own: a SHA that was tried and rolled back is never tried again
  automatically (it would deploy and roll back every five minutes), and a rollback that failed
  stops the service (HALT) until a person has looked and removed the file.

Every file is written whole or not at all (host.write), in the service's own folder.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from pathlib import Path
from typing import Any

STATUS_SCHEMA = "clive.release.status.v1"
STATUS_FILE = "status.json"
HALT_FILE = "HALT"
LOCK_FILE = "deploy.lock"
STATES = ("off", "no_rule", "up_to_date", "waiting", "would_deploy", "deployed", "rolled_back", "halted")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class LockHeld(Exception):
    """Another deploy holds the lock."""


class Lock:
    """An exclusive, non-blocking lock on <state>/deploy.lock, released when the holder exits or dies."""

    def __init__(self, state_dir: Path) -> None:
        self.path = Path(state_dir) / LOCK_FILE
        self._fd: int | None = None

    def __enter__(self) -> Lock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise LockHeld() from None
        self._fd = fd
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


def lock_held(state_dir: Path) -> bool:
    """Whether a deploy holds the lock now, asked without creating anything (a dry run writes nothing)."""
    path = Path(state_dir) / LOCK_FILE
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def _json(host, path: Path) -> dict[str, Any] | None:
    raw = host.read(path)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"reason": "the file is there but cannot be read"}
    return data if isinstance(data, dict) else {"reason": "the file is there but cannot be read"}


def _dump(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def write_status(host, state_dir: Path, *, state: str, line: str, at: str, mode: str, sha: str = "",
                 title: str = "", branch: str = "") -> dict[str, Any]:
    if state not in STATES:
        raise ValueError(f"not a release state: {state}")
    status = {"schema": STATUS_SCHEMA, "state": state, "line": line[:400], "at": at, "mode": mode,
              "sha": sha if _SHA.fullmatch(sha or "") else "", "title": title[:160], "record_branch": branch}
    host.write(Path(state_dir) / STATUS_FILE, _dump(status), 0o644)
    return status


def failed_before(host, state_dir: Path, sha: str) -> dict[str, Any] | None:
    return _json(host, Path(state_dir) / "failed" / f"{sha}.json") if _SHA.fullmatch(sha or "") else None


def mark_failed(host, state_dir: Path, sha: str, *, at: str, reason: str) -> None:
    host.write(Path(state_dir) / "failed" / f"{sha}.json", _dump({"sha": sha, "at": at, "reason": reason}), 0o600)


def halted(host, state_dir: Path) -> dict[str, Any] | None:
    return _json(host, Path(state_dir) / HALT_FILE)


def halt(host, state_dir: Path, *, at: str, reason: str, sha: str) -> None:
    host.write(Path(state_dir) / HALT_FILE, _dump({"at": at, "reason": reason, "sha": sha}), 0o600)


def deploy_dir(state_dir: Path, sha: str) -> Path:
    """Where one attempt keeps what it captured before anything changed (the unit) and its record."""
    return Path(state_dir) / "deploys" / sha[:8]
