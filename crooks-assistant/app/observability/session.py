"""The test session: what is active, persisted on the Mac so the backend, the CLI and a
restart all agree on it.

`logs/test-sessions/active.json` names the session in progress; `last.json` the one most
recently stopped, so `make test-session-report` with no argument knows which. Both are
written whole and renamed into place, created 0600, in a directory created 0700: the
timeline beside them holds what the owner said and what was answered."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

DIR_NAME = "test-sessions"
ACTIVE_FILE = "active.json"
LAST_FILE = "last.json"
# The name of the day-long session the backend starts itself when test mode is always on.
AUTO_NAME = "always-on"
SCREENS_SUFFIX = "-screens"
# How long a cached answer to "is a session active" stands before the file is looked at again.
# Every event asks; the file changes only when someone runs start or stop.
RECHECK_S = 1.0

_SLUG = re.compile(r"[^a-z0-9]+")


class AlreadyActive(RuntimeError):
    """A session is running; stop it before starting another."""


@dataclass(slots=True)
class TestSession:
    test_session_id: str
    name: str
    started_at: float
    stopped_at: float | None = None

    @property
    def active(self) -> bool:
        return self.stopped_at is None

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TestSession:
        return cls(
            test_session_id=str(data.get("test_session_id") or ""),
            name=str(data.get("name") or ""),
            started_at=float(data.get("started_at") or 0.0),
            stopped_at=(float(data["stopped_at"]) if data.get("stopped_at") is not None else None),
        )


def session_dir(log_dir: Path, dir_name: str = DIR_NAME) -> Path:
    return Path(log_dir) / dir_name


def new_session_id(name: str, now: float) -> str:
    slug = _SLUG.sub("-", (name or "").lower()).strip("-")[:24] or "session"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return f"ts-{stamp}-{slug}"


def _day(ts: float) -> str:
    return time.strftime("%Y%m%d", time.localtime(ts))


def _write_private(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _read(path: Path) -> TestSession | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("test_session_id"):
        return None
    return TestSession.from_dict(data)


class TestSessions:
    """The session state on disk, read by whoever asks: the backend on every event (cached
    for a second), the CLI once per command."""

    __test__ = False   # not a pytest class, whatever its name says

    def __init__(self, log_dir: Path, *, clock=time.time, dir_name: str = DIR_NAME,
                 always: bool = False, keep_days: int = 14) -> None:
        # `dir_name`, because a production recording is NOT a test session and must not share
        # a directory with one: `make test-session-report` finds the last test session by
        # reading this folder, and a recording landing in it would be reported as one.
        self.root = session_dir(log_dir, dir_name)
        self.clock = clock
        # Test mode always on (CROOKS_TEST_SESSION_ALWAYS): with no session running, the day's
        # own is started here, on the first question asked of it, and yesterday's is closed.
        self.always = bool(always)
        self.keep_days = max(1, int(keep_days or 14))
        self._cached: TestSession | None = None
        self._checked_at = -1.0
        self._mtime = -1.0

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            if self.root.stat().st_mode & 0o077:
                self.root.chmod(0o700)
        except OSError:
            pass

    @property
    def active_path(self) -> Path:
        return self.root / ACTIVE_FILE

    def timeline_path(self, session: TestSession | str) -> Path:
        ident = session.test_session_id if isinstance(session, TestSession) else str(session)
        return self.root / f"{ident}.jsonl"

    def screens_dir(self, session: TestSession | str) -> Path:
        ident = session.test_session_id if isinstance(session, TestSession) else str(session)
        return self.root / f"{ident}{SCREENS_SUFFIX}"

    def active(self) -> TestSession | None:
        """The session in progress, or None. The file is looked at again at most once a second,
        so a start or stop from the CLI is noticed within that, without a restart. With test
        mode always on there is always one: the day's own, started here if need be."""
        now = self.clock()
        if 0 <= now - self._checked_at < RECHECK_S:
            return self._cached
        self._checked_at = now
        current = self._read_active()
        if self.always:
            current = self._keep_alive(current, now)
        return current

    def _read_active(self) -> TestSession | None:
        try:
            mtime = self.active_path.stat().st_mtime
        except OSError:
            self._cached, self._mtime = None, -1.0
            return None
        if mtime != self._mtime or self._cached is None:
            self._mtime = mtime
            self._cached = _read(self.active_path)
        return self._cached

    def _keep_alive(self, current: TestSession | None, now: float) -> TestSession | None:
        """Today's always-on session: kept if it is running, started if nothing is, rolled if
        the one running is an always-on session from another day. A session started by name is
        never touched."""
        if current is not None and not (current.name == AUTO_NAME and _day(current.started_at) != _day(now)):
            return current
        try:
            self._ensure_root()
            if current is not None:
                self._close(current, now)
            session = TestSession(test_session_id=new_session_id(AUTO_NAME, now), name=AUTO_NAME, started_at=now)
            _write_private(self.active_path, session.as_dict())
            self._cached, self._mtime = session, self.active_path.stat().st_mtime
            self._prune(now)
            return session
        except OSError:
            return current

    def _close(self, current: TestSession, now: float) -> None:
        current.stopped_at = now
        _write_private(self.root / LAST_FILE, current.as_dict())
        try:
            self.active_path.unlink()
        except OSError:
            pass
        self._cached, self._mtime = None, -1.0

    def _prune(self, now: float) -> int:
        """Delete always-on days older than `keep_days`, with their screens. Named sessions are
        the owner's and are kept whatever their age."""
        import shutil

        cutoff = now - self.keep_days * 86_400
        removed = 0
        for path in self.root.glob(f"ts-*-{AUTO_NAME}*"):
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def start(self, name: str) -> TestSession:
        self._ensure_root()
        current = self.active()
        if current is not None and self.always and current.name == AUTO_NAME:
            # A session started by name takes over from the day's own; the day's resumes as a
            # new always-on session when the named one is stopped.
            self._close(current, self.clock())
            current = None
        if current is not None:
            raise AlreadyActive(current.test_session_id)
        now = self.clock()
        session = TestSession(test_session_id=new_session_id(name, now), name=(name or "").strip()[:80] or "session", started_at=now)
        _write_private(self.active_path, session.as_dict())
        self._checked_at = -1.0
        return session

    def stop(self) -> TestSession | None:
        self._checked_at = -1.0
        current = self.active()
        if current is None:
            return None
        current.stopped_at = self.clock()
        self._ensure_root()
        _write_private(self.root / LAST_FILE, current.as_dict())
        try:
            self.active_path.unlink()
        except OSError:
            pass
        self._checked_at = -1.0
        self._cached = None
        return current

    def last(self) -> TestSession | None:
        return _read(self.root / LAST_FILE)

    def find(self, ref: str = "") -> Path | None:
        """The timeline named by a session id (or the start of one); with no name, the active
        session's, else the last stopped one's."""
        ref = (ref or "").strip()
        if not ref:
            session = self.active() or self.last()
            if session is None:
                return None
            path = self.timeline_path(session)
            return path if path.exists() else None
        if "/" in ref or ".." in ref:
            return None
        exact = self.root / (ref if ref.endswith(".jsonl") else f"{ref}.jsonl")
        if exact.exists():
            return exact
        matches = sorted(p for p in self.root.glob("*.jsonl") if p.name.startswith(ref))
        return matches[-1] if matches else None
