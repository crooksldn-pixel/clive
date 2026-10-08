"""Every command the release service runs and every file it touches, behind one seam.

Why it exists: a deploy is commands (git, make, systemctl, journalctl, the health check) and a few
files (the unit, .env's fingerprint, the drop-ins). Routing all of them through one object means
the tests can replace the whole server with a fake one, check every command a run would make, and
prove that a dry run makes none that change anything. Each command carries the name of its step,
so a record and a test can say which step failed without parsing an argument list.

What it promises: arguments are lists, never a shell line; a command that cannot start or runs
past its time is a failed Result, never an exception; a file is written whole or not at all.
"""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Result:
    code: int
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


class Host(Protocol):
    def run(self, step: str, argv: Sequence[str], *, cwd: Path | None = None,
            env: Mapping[str, str] | None = None, input: str | None = None, timeout: float = 600.0) -> Result: ...

    def read(self, path: Path) -> bytes | None: ...

    def read_plain(self, path: Path, limit: int) -> tuple[bytes | None, str]: ...

    def write(self, path: Path, data: bytes, mode: int) -> None: ...

    def remove(self, path: Path) -> None: ...

    def files(self, folder: Path, pattern: str) -> list[Path]: ...

    def writable(self, path: Path) -> bool: ...

    def stat(self, path: Path) -> tuple[int, int] | None: ...

    def sleep(self, seconds: float) -> None: ...

    def now(self) -> datetime: ...

    def name(self) -> str: ...


# What the service's own unit sets for itself and a command it runs must not inherit: PYTHONPATH names
# the pinned copy, and would put its modules in front of the checkout's in `make install`'s Python;
# CREDENTIALS_DIRECTORY is this unit's (its token), never CLIVE's, whose secret store reads that name.
_NOT_INHERITED = ("PYTHONPATH", "CREDENTIALS_DIRECTORY")


def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if k not in _NOT_INHERITED and not k.startswith("CLIVE_RELEASE_")}
    return {**base, "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1", **(extra or {})}


class SystemHost:
    """The real server."""

    def run(self, step: str, argv: Sequence[str], *, cwd: Path | None = None,
            env: Mapping[str, str] | None = None, input: str | None = None, timeout: float = 600.0) -> Result:
        merged = child_env(env)
        try:
            done = subprocess.run(list(argv), cwd=str(cwd) if cwd else None, env=merged, input=input,
                                  capture_output=True, text=True, errors="replace", timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return Result(124, "", f"{step}: still running after {int(timeout)} s, stopped")
        except OSError as exc:
            return Result(127, "", f"{step}: could not start ({type(exc).__name__})")
        return Result(done.returncode, done.stdout or "", done.stderr or "")

    def read(self, path: Path) -> bytes | None:
        try:
            return Path(path).read_bytes()
        except FileNotFoundError:
            return None

    def read_plain(self, path: Path, limit: int) -> tuple[bytes | None, str]:
        """A record in a folder another process writes (CLIVE's approvals, its passkeys), read by this
        root process without trusting what lies there: the file itself, never a link it points along
        (O_NOFOLLOW); opened without waiting, so a pipe cannot hold the tick and its deploy lock; only a
        regular file; at most `limit` bytes. (its bytes, "") when read; (None, "") when it is not
        there; (None, why) when it is there and was not read."""
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            return None, ""
        except OSError:
            return None, "it is a link, or it cannot be opened"
        try:
            found = os.fstat(fd)
            if not stat.S_ISREG(found.st_mode):
                return None, "it is not a plain file"
            chunks, size = [], 0
            while size <= limit:
                chunk = os.read(fd, limit + 1 - size)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            return (None, f"it is larger than {limit} bytes") if size > limit else (b"".join(chunks), "")
        except OSError:
            return None, "it cannot be read"
        finally:
            os.close(fd)

    def write(self, path: Path, data: bytes, mode: int) -> None:
        """Beside it, flushed, renamed over it, the folder flushed: the old file or the new, never half."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.new")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        try:
            view, done = memoryview(data), 0
            while done < len(data):
                done += os.write(fd, view[done:])
            os.fchmod(fd, mode)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            tmp.unlink(missing_ok=True)
            raise
        os.close(fd)
        os.replace(tmp, path)
        folder = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)

    def remove(self, path: Path) -> None:
        Path(path).unlink(missing_ok=True)

    def files(self, folder: Path, pattern: str) -> list[Path]:
        folder = Path(folder)
        return sorted(folder.glob(pattern)) if folder.is_dir() else []

    def writable(self, path: Path) -> bool:
        # access(2) answers EROFS for a read-only mount, so a unit with too narrow a ReadWritePaths
        # is found here, before anything changes, rather than half way through a deploy.
        return os.access(path, os.W_OK)

    def stat(self, path: Path) -> tuple[int, int] | None:
        """(owner uid, mode) of the path itself, a link not followed; None when it is not there."""
        try:
            found = os.lstat(path)
        except OSError:
            return None
        return found.st_uid, found.st_mode

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def now(self) -> datetime:
        return datetime.now(UTC)

    def name(self) -> str:
        return socket.gethostname()
