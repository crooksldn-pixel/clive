"""The test session: what is active, persisted on the Mac so the backend, the CLI and a
restart all agree on it.

`logs/test-sessions/active.json` names the session in progress; `last.json` the one most
recently stopped, so `make test-session-report` with no argument knows which. Both are
written whole and renamed into place, created 0600, in a directory created 0700: the
timeline beside them holds what the owner said and what was answered."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import stat
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

_log = logging.getLogger("crooks.observe")


class Interrupted(Exception):
    """Housekeeping was asked to stop — the service is shutting down — and the walk it was on
    ended at the next entry it came to (round 11, R9-A3b-F-04-SHUTDOWN)."""


# The stop asked of the housekeeping pass running in this thread (app/main.py sets it for the
# pass it runs, and shutdown sets the event). Every walk here over sessions and reports reads it
# before each entry, so a pass asked to stop ends within one filesystem call however many files
# there are: a stop read only BETWEEN a pass's steps left one long step — an age or a report
# check over a big folder — to run on past the unit's deadline, with the runtime left open under
# it (round 11). A context variable, so nothing else is ever stopped by it: a turn's own roll of
# the day, a command's prune, a test calling these directly see none.
HOUSEKEEPING_STOP: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "crooks_housekeeping_stop", default=None)


def checkpoint() -> None:
    """Raise Interrupted if the housekeeping running here has been asked to stop. Called only
    between whole filesystem changes — never between the move and the check of a prune
    (_unlink_if_aged), which must finish once begun — so what an interrupted walk leaves is what
    a walk that had not reached the rest yet would leave."""
    stop = HOUSEKEEPING_STOP.get()
    if stop is not None and stop.is_set():
        raise Interrupted("housekeeping stopped early for shutdown")

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
        """Raises ValueError for a time that is not a finite number: _read takes such a record
        for no record at all (round 8, F-04-STARTUP)."""
        import math

        def when(value) -> float:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"not a time: {value!r}")
            return number

        return cls(
            test_session_id=str(data.get("test_session_id") or ""),
            name=str(data.get("name") or ""),
            started_at=when(data.get("started_at") or 0.0),
            stopped_at=(when(data["stopped_at"]) if data.get("stopped_at") is not None else None),
        )


def session_dir(log_dir: Path, dir_name: str = DIR_NAME) -> Path:
    return Path(log_dir) / dir_name


def new_session_id(name: str, now: float) -> str:
    slug = _SLUG.sub("-", (name or "").lower()).strip("-")[:24] or "session"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return f"ts-{stamp}-{slug}"


# The shape new_session_id() gives a session (and the recorder's "rec-" twin of it): the kind,
# the day, the time, and the slug of its name — absent from sessions recorded before names were
# slugged in. Nothing else is a session id (round 9, F-01).
SESSION_ID = re.compile(r"(?:ts|rec)-[0-9]{8}-[0-9]{6}(?:-[a-z0-9][a-z0-9-]{0,23})?")


def safe_session_id(value: object) -> str | None:
    """`value` when it is a session id in the shape new_session_id() makes, else None. A session
    id names files — its timeline, its report, its proposals — so anything that is not one is
    never used as a name (round 9, F-01: `../web/exposed` in an event would have written a report
    outside reports/)."""
    text = value if isinstance(value, str) else ""
    return text if SESSION_ID.fullmatch(text) else None


def report_target(out_dir: Path, session_id: object, fallback: object, suffix: str) -> Path:
    """Where a report drawn from a session goes: `<out_dir>/<session id><suffix>`, the id checked
    for its shape (the one the timeline's own events carry, or else the timeline file's own name),
    and the result checked to be directly inside `out_dir` once every link on the way is resolved.
    Raises ValueError for anything else: a report is never written anywhere but its folder."""
    carried = str(session_id or "")
    ident = safe_session_id(carried) if carried else safe_session_id(fallback)
    if ident is None:
        raise ValueError("not a test session id: a report is written only under a session's own name")
    folder = Path(out_dir)
    target = folder / f"{ident}{suffix}"
    if target.name != f"{ident}{suffix}" or Path(os.path.realpath(target)).parent != Path(os.path.realpath(folder)):
        raise ValueError("a report's path must stay inside its folder")
    return target


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
    """Remove `path` if it is past `cutoff`: 1 when it went, 0 when it stays.

    A folder goes only when everything in it is past the cutoff too (round 8, F-04-REPORT-LOSS):
    the folder's own time says when a name in it last changed, not when a file in it was last
    written, so an old `ts-…-screens/` could hold a fresh report and was removed whole. Now every
    descendant is looked at first (by its own time, never following a link), and one that is not
    past the cutoff, or one that cannot be looked at, keeps the whole folder. The removal then
    goes file by file, each removed only if it is still the very file that was looked at and still
    old (_unlink_if_aged), and a folder only by rmdir, which refuses one that is not empty:
    something written while it runs stops it, and is kept.

    Housekeeping asked to stop ends it before the next entry (checkpoint): an old folder half
    emptied is only old files gone, and the next pass takes the rest."""
    checkpoint()
    try:
        top = os.lstat(path)
    except OSError:
        return 0
    if top.st_mtime >= cutoff:
        return 0
    if not stat.S_ISDIR(top.st_mode):
        return 1 if _unlink_if_aged(Path(path), cutoff, top) else 0
    order = _expired_tree(Path(path), cutoff)
    if order is None:
        return 0
    try:
        for entry, is_dir in order:
            checkpoint()
            if is_dir:
                os.rmdir(entry)
            elif not _unlink_if_aged(entry, cutoff):
                return 0     # written since it was looked at: it, and what holds it, stay
        os.rmdir(path)
    except OSError:
        return 0
    return 1


def _unlink_if_aged(path: Path, cutoff: float, seen: os.stat_result | None = None) -> bool:
    """Remove one file (or link) only if the name still holds the very file that was looked at and
    it is still past `cutoff` (round 9, F-04-REPORT-LOSS). A check and then an unlink by name
    raced a writer: write_private_text renames a fresh report into place, and a replace landing
    between the look and the unlink had the fresh report removed.

    So nothing is unlinked by the name that was looked at. The name is first moved, in one step, to
    one beside it that nothing else uses; what was moved is then looked at again. The very file
    looked at (the same device and inode), still old: that is removed. Anything else — a report
    renamed into place meanwhile, or the old one written to since — is put back under its own name
    with a hard link, which never replaces anything; if the name has been taken again in the
    meantime, it is left beside it under the moved-to name, which starts with its own, and ages by
    its own time like any report. Either way it is never removed."""
    import uuid

    try:
        before = seen if seen is not None else os.lstat(path)
    except OSError:
        return False
    if stat.S_ISDIR(before.st_mode) or before.st_mtime >= cutoff:
        return False
    moved = path.with_name(f"{path.name}.pruning-{uuid.uuid4().hex[:12]}")
    try:
        os.rename(path, moved)
    except OSError:
        return False
    try:
        now = os.lstat(moved)
    except OSError:
        return False
    if (now.st_dev, now.st_ino) == (before.st_dev, before.st_ino) and now.st_mtime < cutoff:
        try:
            os.unlink(moved)
            return True
        except OSError:
            return False
    try:
        os.link(moved, path, follow_symlinks=False)
    except (OSError, NotImplementedError):
        _log.warning("a report written while it was being aged out is kept beside its name: %s", moved.name)
        return False
    try:
        os.unlink(moved)
    except OSError:
        pass
    return False


def _expired_tree(top: Path, cutoff: float) -> list[tuple[Path, bool]] | None:
    """Everything under `top`, deepest first, as (path, is a folder), when every entry is past
    `cutoff`; None when any is not, or when any part could not be looked at."""
    order: list[tuple[Path, bool]] = []
    failed: list[OSError] = []
    for here, dirs, files in os.walk(top, topdown=False, onerror=failed.append, followlinks=False):
        if failed:
            return None
        for name in [*files, *dirs]:
            checkpoint()
            entry = Path(here) / name
            try:
                info = os.lstat(entry)
            except OSError:
                return None
            if info.st_mtime >= cutoff:
                return None
            # A link to a folder is listed with the folders and never walked: it goes as a link.
            order.append((entry, stat.S_ISDIR(info.st_mode)))
    if failed:
        return None
    # Files before folders within each level (os.walk bottom-up already gives children first), and
    # by name within that, so the removal goes in the same order on every filesystem: which old
    # file goes before a fresh one stops the pass must not depend on how a disk lists a folder.
    return sorted(order, key=lambda e: (-len(e[0].parts), e[1], e[0].name))


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


@dataclass
class Exposure:
    """What tighten() found: what is still open to anyone else, what it could not look at, and
    the links, whose privacy cannot be established from where they are (round 9)."""

    exposed: list[Path]
    unread: list[str]
    linked: list[Path] = field(default_factory=list)


def _open_to_others(info: os.stat_result) -> bool:
    """Readable or writable by anyone but this process's own user: by its mode, or because it is
    someone else's (round 9, F-04-STARTUP: a 0700 folder another user owns is theirs to open)."""
    return bool(info.st_mode & 0o077) or info.st_uid != os.geteuid()


def tighten(folder: Path) -> Exposure:
    """A folder of reports made private, what was already in it included: every folder 0700,
    every file 0600. Nothing is read or removed. Says what is still open to anyone else
    afterwards (the folder itself first, if it is one), each checked by the kernel's own answer
    rather than assumed from a chmod that did not complain (the 2026-09-27 deploy review, F-04);
    and what could not be looked at, so that "nothing is exposed" and "could not look" are never
    the same answer (round 7).

    Open to others means by mode or by owner (round 9, F-04-STARTUP): a file or folder another
    user owns is open to that user whatever its mode, since they can change it. The folder itself
    must be a real folder, not a link to one. A link anywhere inside is neither chmod'ed nor
    followed, and is said apart (`linked`): what it points at may be readable by another path,
    and a link's own mode says nothing of that, so its privacy cannot be established here."""
    folder = Path(folder)
    exposed: list[Path] = []
    unread: list[str] = []
    linked: list[Path] = []
    try:
        if stat.S_ISLNK(os.lstat(folder).st_mode):
            return Exposure(exposed, unread, [folder])
    except OSError as exc:
        return Exposure(exposed, [str(getattr(exc, "filename", folder) or folder)])
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    try:
        if _open_to_others(os.lstat(folder)):
            exposed.append(folder)
    except OSError as exc:
        return Exposure(exposed, [str(getattr(exc, "filename", folder) or folder)])
    for here, dirs, files in os.walk(folder, onerror=lambda exc: unread.append(str(exc.filename or ""))):
        for name in [*dirs, *files]:
            checkpoint()     # a check stopped part way is not a clean one: tidy_reports says so
            path = Path(here) / name
            if path.is_symlink():
                linked.append(path)
                continue
            try:
                path.chmod(0o700 if path.is_dir() else 0o600)
            except OSError:
                pass
            try:
                if _open_to_others(os.lstat(path)):
                    exposed.append(path)
            except FileNotFoundError:
                continue   # gone meanwhile: nothing left to expose
            except OSError:
                unread.append(str(path))
    return Exposure(exposed, unread, linked)


def _private(folder: Path) -> bool:
    """A real folder (not a link to one), this process's own, that no one else can enter. Whose
    it is counts too (round 8): a 0700 folder someone else made is private to them, not to us."""
    try:
        info = os.lstat(folder)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o077 and info.st_uid == os.geteuid()


def _same_folder(folder: Path, before: os.stat_result) -> bool:
    try:
        now = os.lstat(folder)
    except OSError:
        return False
    return (now.st_dev, now.st_ino) == (before.st_dev, before.st_ino)


def withhold(folder: Path, exposed: list[Path]) -> tuple[int, list[Path]]:
    """What tighten() could not make private is taken out of reach without being destroyed: moved,
    under a name nothing else has, into a 0700 folder of its own inside the reports folder, where
    no one else can reach it whatever its own mode (F-04). Never removed (round 7, F-04-REPORT-
    LOSS: a report is the owner's, and a permission problem is not a reason to lose it). What
    cannot be moved is left where it is and returned as still exposed, for the caller to refuse
    to go on with. Returns (how many were withheld, what is still exposed).

    Checked after the move as well as before it (round 8, F-04-REPORT-LOSS): the private folder
    must still be the same real folder, ours and closed to everyone else, with the report in it.
    If it is not, it is closed again; if that fails, the report is returned as still exposed.
    The report's own mode is tightened too, where that now works."""
    import uuid

    folder = Path(folder)
    kept = folder / WITHHELD
    left: list[Path] = []
    withheld = 0
    for path in exposed:
        checkpoint()
        if path == folder:
            left.append(path)   # the folder itself: nowhere to move it to
            continue
        if not path.exists() and not path.is_symlink():
            continue            # moved already, inside a folder withheld before it
        try:
            kept.mkdir(mode=0o700, exist_ok=True)
            kept.chmod(0o700)
        except OSError:
            pass
        if not _private(kept):
            left.append(path)
            continue
        try:
            path.relative_to(kept)
            continue            # already inside the private folder: out of reach as it is
        except ValueError:
            pass
        try:
            before = os.lstat(kept)
        except OSError:
            left.append(path)
            continue
        target = kept / f"{uuid.uuid4().hex}-{path.name}"
        if target.exists() or target.is_symlink():
            left.append(path)           # never over anything
            continue
        try:
            os.rename(path, target)     # a name nothing has: nothing is replaced
        except OSError:
            left.append(path)
            continue
        if not (_private(kept) and _same_folder(kept, before)):
            try:
                kept.chmod(0o700)
            except OSError:
                pass
        if not (_private(kept) and _same_folder(kept, before) and os.path.lexists(target)):
            _log.error("a withheld report's folder is not private after the move: %s", target)
            left.append(target)
            continue
        try:
            is_dir = stat.S_ISDIR(os.lstat(target).st_mode)
            if not os.path.islink(target):
                target.chmod(0o700 if is_dir else 0o600)
        except OSError:
            pass                        # out of reach inside the folder whatever its own mode
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


def prune_withheld(folder: Path, keep_days: int, *, now: float | None = None) -> int:
    """What withhold() took out of reach ages like any report (round 8, F-04-REPORT-LOSS): by its
    own time, which a move does not change, whatever it is called there. The names withhold()
    gives start with a UUID, so the `ts-*` pass never matched one and nothing there ever went."""
    folder = Path(folder)
    if not _private(folder):
        return 0     # never through a link, or in a folder that is not ours: nothing removed there
    try:
        entries = list(folder.iterdir())
    except OSError:
        return 0
    cutoff = (time.time() if now is None else now) - max(1, int(keep_days)) * 86_400
    return sum(_remove_if_older(path, cutoff) for path in entries)


def _read(path: Path) -> TestSession | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("test_session_id"):
        return None
    try:
        return TestSession.from_dict(data)
    except (TypeError, ValueError, OverflowError):
        # A record whose times are not times is no record (round 8, F-04-STARTUP): raising here
        # stopped the day's roll, every event's session lookup and the command line's stop alike.
        # Said once for each version of the file, not on every look at it.
        try:
            version = (str(path), path.stat().st_mtime_ns)
        except OSError:
            version = (str(path), -1)
        if _UNREADABLE.get(version[0]) != version[1]:
            _UNREADABLE[version[0]] = version[1]
            _log.warning("test-session record at %s is not readable as one; taken as none", path)
        return None


_UNREADABLE: dict[str, int] = {}


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
        # True only once a check has run to its end and found every report private; False when one
        # is left exposed or could not be checked; None before any check has run (round 8,
        # F-04-STARTUP: it began True, so a start-up whose check was skipped read as a clean one).
        self.tidy_contained: bool | None = None
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
        (files 0600, folders 0700, including any written before that was the rule).

        Never raises, and never says "contained" without having looked (round 8, F-04-STARTUP):
        `tidy_contained` is False from the moment it starts until the whole check has run. A
        configured path that is not there holds no reports and is contained; one that is there
        but cannot be looked at or listed, or is not a folder, is "could not be checked", not
        "nothing exposed". Anything raised on the way is the same."""
        self.tidy_problem = ""
        self.tidy_contained = False
        if self.reports_dir is None:
            self.tidy_contained = True     # no reports folder configured: nothing to keep private
            return 0
        try:
            return self._tidy_reports(now)
        except Interrupted:
            # Stopped part way for shutdown: not a check that ran to its end, so not contained, and
            # said as what it was. The pass that asked is ending; it is told too.
            self.tidy_problem = "the report check stopped early for shutdown"
            self.tidy_contained = False
            raise
        except Exception as exc:  # noqa: BLE001 - said, and not contained, whatever it was
            self.tidy_problem = f"the reports could not be checked ({type(exc).__name__})"
            self.tidy_contained = False
            _log.error("reports could not be checked", exc_info=True)
            return 0

    def _tidy_reports(self, now: float | None) -> int:
        folder = self.reports_dir
        try:
            info = os.stat(folder)
        except FileNotFoundError:
            self.tidy_contained = True     # not there: no report to expose
            return 0
        except OSError as exc:
            self.tidy_problem = "the reports folder could not be checked"
            _log.error("reports folder could not be looked at: %s", exc)
            return 0
        if not stat.S_ISDIR(info.st_mode):
            self.tidy_problem = "the reports path is not a folder, so it could not be checked"
            _log.error("reports path is not a folder: %s", folder)
            return 0
        try:
            os.listdir(folder)
        except OSError as exc:
            self.tidy_problem = "the reports folder could not be read, so it could not be checked"
            _log.error("reports folder could not be listed: %s", exc)
            return 0
        when = self.clock() if now is None else now
        removed = prune_reports(self.reports_dir, self.keep_named_days, now=when)
        removed += prune_withheld(self.reports_dir / WITHHELD, self.keep_named_days, now=when)
        found = tighten(self.reports_dir)
        withheld, left = withhold(self.reports_dir, found.exposed)
        if withheld:
            _log.warning("%d report(s) could not be made private and were withheld", withheld)
        problems = []
        if left:
            problems.append(f"{len(left)} report path(s) are readable by others and could not be withheld")
            _log.error("reports left readable by others: %s", ", ".join(str(p) for p in left))
        if found.unread:
            problems.append(f"{len(found.unread)} report path(s) could not be checked")
            _log.error("reports that could not be checked: %s", ", ".join(found.unread))
        # A link is not moved (withheld, what it points at would still be where it was) and not
        # removed (it is not ours to judge): it is said, and it keeps the reports from being
        # called private until the owner takes it out (round 9, F-04-STARTUP).
        if found.linked:
            problems.append(f"{len(found.linked)} report path(s) are links, whose privacy cannot be established")
            _log.error("links among the reports: %s", ", ".join(str(p) for p in found.linked))
        # Said in counts, never names: this line reaches /health. Not contained means the start-up
        # refuses to go on (app/main.py).
        self.tidy_problem = "; ".join(problems)
        self.tidy_contained = not problems
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
