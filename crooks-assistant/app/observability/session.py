"""The test session: what is active, persisted on the Mac so the backend, the CLI and a
restart all agree on it.

`logs/test-sessions/active.json` names the session in progress; `last.json` the one most
recently stopped, so `make test-session-report` with no argument knows which. Both are
written whole and renamed into place, created 0600, in a directory created 0700: the
timeline beside them holds what the owner said and what was answered."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_log = logging.getLogger("crooks.observe")

DIR_NAME = "test-sessions"
ACTIVE_FILE = "active.json"
LAST_FILE = "last.json"
# The name of the day-long session the backend starts itself when test mode is always on.
AUTO_NAME = "always-on"
SCREENS_SUFFIX = "-screens"
# A session started by name is the owner's, and is kept longer than a day of always-on test
# mode, but not for ever (CROOKS_TEST_SESSION_KEEP_NAMED_DAYS).
KEEP_NAMED_DAYS = 90
# A session started by name ends by itself after this long (the 2026-09-26 deploy review, F-04):
# left running, it would never end, never be pruned, and with test mode always on it would stop
# the day's own session from ever rolling. A walkthrough is hours, not days.
NAMED_MAX_S = 24 * 3600
# One timeline file stops growing here (app/observability/timeline.py): a day of always-on test
# mode holds a few megabytes; this is the bound on a runaway.
MAX_TIMELINE_BYTES = 64 * 1024 * 1024
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


def _remove_if_older(path: Path, cutoff: float) -> int:
    import shutil

    try:
        if path.stat().st_mtime >= cutoff:
            return 0
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink()
        return 1
    except OSError:
        return 0


def private_dir(path: Path) -> Path:
    """A folder only its owner can read: created 0700, and made so if it already exists."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if path.stat().st_mode & 0o077:
            path.chmod(0o700)
    except OSError:
        pass
    return path


def write_private_text(path: Path, text: str) -> Path:
    """A report, created 0600 in a 0700 folder and renamed into place: never readable by
    anyone else, not even for the moment between writing and a chmod."""
    path = Path(path)
    private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)
    return path


WITHHELD = ".withheld"


def tighten(folder: Path) -> list[Path]:
    """A folder of reports made private, what was already in it included: every folder 0700,
    every file 0600. Nothing is read or removed. Returns what is still open to anyone else
    afterwards (the folder itself first, if it is one), each checked by the kernel's own answer
    rather than assumed from a chmod that did not complain (the 2026-09-27 deploy review, F-04)."""
    folder = Path(folder)
    exposed: list[Path] = []
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    try:
        if folder.stat().st_mode & 0o077:
            exposed.append(folder)
    except OSError:
        return exposed
    try:
        paths = list(folder.rglob("*"))
    except OSError:
        paths = []
    for path in paths:
        if path.is_symlink():
            continue
        try:
            path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError:
            pass
        try:
            if path.stat().st_mode & 0o077:
                exposed.append(path)
        except OSError:
            continue   # gone meanwhile: nothing left to expose
    return exposed


def withhold(folder: Path, exposed: list[Path]) -> tuple[int, list[Path]]:
    """What tighten() could not make private is taken out of reach: moved into a 0700 folder of
    its own inside the reports folder, or, if even that is refused, removed — a report is drawn
    from a session and can be drawn again; one that anyone can read cannot be left (F-04: fail
    closed). Returns (how many were withheld, what is still exposed)."""
    folder = Path(folder)
    kept = folder / WITHHELD
    left: list[Path] = []
    withheld = 0
    for path in exposed:
        if path == folder:
            left.append(path)   # the folder itself: nowhere to move it to
            continue
        if not path.exists() and not path.is_symlink():
            continue
        try:
            kept.mkdir(mode=0o700, exist_ok=True)
            kept.chmod(0o700)
            if kept.stat().st_mode & 0o077:
                raise PermissionError("the withheld folder is not private")
            os.replace(path, kept / f"{int(time.time())}-{path.name}")
            withheld += 1
            continue
        except OSError:
            pass
        _remove_if_older(path, float("inf"))
        if path.exists() or path.is_symlink():
            left.append(path)
        else:
            withheld += 1
    return withheld, left


def prune_reports(out_dir: Path, keep_days: int, *, now: float | None = None) -> int:
    """Reports drawn from sessions (ts-….md, ts-…-proposals.md, ts-…-screens/) older than
    `keep_days`: they carry what the sessions carried, so they go when the sessions would."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - max(1, int(keep_days)) * 86_400
    return sum(_remove_if_older(path, cutoff) for path in out_dir.glob("ts-*"))


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
                 always: bool = False, keep_days: int = 14, keep_named_days: int = KEEP_NAMED_DAYS,
                 reports_dir: Path | None = None) -> None:
        # `dir_name`, because a production recording is NOT a test session and must not share
        # a directory with one: `make test-session-report` finds the last test session by
        # reading this folder, and a recording landing in it would be reported as one.
        self.root = session_dir(log_dir, dir_name)
        self.clock = clock
        # Test mode always on (CROOKS_TEST_SESSION_ALWAYS): with no session running, the day's
        # own is started here, on the first question asked of it, and yesterday's is closed.
        self.always = bool(always)
        self.keep_days = max(1, int(keep_days or 14))
        self.keep_named_days = max(self.keep_days, int(keep_named_days or KEEP_NAMED_DAYS))
        # The reports drawn from sessions: aged and kept private by the daily roll too, not only
        # when someone next runs a report command (the 2026-09-26 deploy review, F-04 and F-03).
        self.reports_dir = Path(reports_dir) if reports_dir else None
        self.tidy_problem = ""   # what the last tidy_reports could not put right, in counts
        self._cached: TestSession | None = None
        self._checked_at = -1.0
        self._mtime = -1.0

    @classmethod
    def from_settings(cls, settings, **kwargs) -> TestSessions:
        """The store as the settings configure it: where, whether always on, and for how long."""
        options = {
            "always": bool(getattr(settings, "test_session_always", False)),
            "keep_days": int(getattr(settings, "test_session_keep_days", 14) or 14),
            "keep_named_days": int(getattr(settings, "test_session_keep_named_days", KEEP_NAMED_DAYS) or KEEP_NAMED_DAYS),
            "reports_dir": getattr(settings, "reports_dir", None),
        }
        options.update(kwargs)
        return cls(settings.log_dir, **options)

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
        if current is not None and current.name != AUTO_NAME and now - current.started_at > NAMED_MAX_S:
            try:
                self._ensure_root()
                self._close(current, now)
            except OSError:
                pass
            current = None
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
            self.tidy_reports(now)
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
        """Delete always-on days older than `keep_days`, and sessions started by name older
        than `keep_named_days`, each with its screens. The session running is never touched."""
        running = self._cached.test_session_id if self._cached is not None else None
        removed = 0
        for path in self.root.glob("ts-*"):
            ident = path.name.removesuffix(".jsonl").removesuffix(SCREENS_SUFFIX)
            if running and ident == running:
                continue
            days = self.keep_days if path.name.startswith("ts-") and f"-{AUTO_NAME}" in path.name else self.keep_named_days
            removed += _remove_if_older(path, now - days * 86_400)
        return removed

    def tidy_reports(self, now: float | None = None) -> int:
        """The reports folder, as the sessions are: old reports gone, the rest the owner's alone
        (files 0600, folders 0700, including any written before that was the rule)."""
        self.tidy_problem = ""
        if self.reports_dir is None or not self.reports_dir.is_dir():
            return 0
        when = self.clock() if now is None else now
        removed = prune_reports(self.reports_dir, self.keep_named_days, now=when)
        removed += prune_reports(self.reports_dir / WITHHELD, self.keep_named_days, now=when)
        withheld, left = withhold(self.reports_dir, tighten(self.reports_dir))
        if withheld:
            _log.warning("%d report(s) could not be made private and were withheld", withheld)
        if left:
            # Said in counts, never names: this line reaches /health.
            self.tidy_problem = f"{len(left)} report path(s) are readable by others and could not be withheld"
            _log.error("reports left readable by others: %s", ", ".join(str(p) for p in left))
        return removed

    def prune(self) -> int:
        """Apply the ages now. The backend does it each day as always-on test mode rolls; the
        command line does it as a session is started by name."""
        try:
            return self._prune(self.clock()) if self.root.exists() else 0
        except OSError:
            return 0

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
