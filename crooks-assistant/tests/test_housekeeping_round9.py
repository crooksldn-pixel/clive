"""Reports, the timeline and shutdown (the 2026-09-28 deploy review, round 9, part A3b):

- F-04-REPORT-LOSS: pruning looked at an aged report and then unlinked its name, so a fresh report
  renamed into place in between was removed. Only the very file looked at, still old, goes now.
- F-04-STARTUP: the start-up check counted modes, not owners, and passed over links. A report
  someone else owns, a reports folder someone else owns, and a link anywhere among them, are not
  private, and say so.
- F-04-SHUTDOWN: a housekeeping pass that outran the deadline had shutdown exit with accepted
  timeline events still in the daemon writer; the normal close never drained it either.
- F-A3B-SHORT-WRITE: the timeline made one os.write per batch and counted every line written
  whatever it took.
- F-10: a writer that could not hold the writer lock wrote its batch anyway, unseen by a command
  deciding whether a count is final.
"""

from __future__ import annotations

import errno
import os
import threading
from pathlib import Path

import pytest

from app.observability import session as session_module
from app.observability import timeline as timeline_module
from app.observability.session import TestSessions, prune_reports, write_private_text
from app.observability.timeline import Timeline, count_events, read_events, writer_alive

NOW = 1_790_000_000.0


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _aged(path: Path, days: float, now: float = NOW) -> Path:
    os.utime(path, (now - days * 86_400, now - days * 86_400), follow_symlinks=False)
    return path


def _replace_just_before_it_is_moved(monkeypatch, target: Path, *, text: str) -> None:
    """A writer that renames a fresh report into `target` in the window between the pruner's look
    at that name and its move (or, in a pruner that removes by name, its unlink) of it. Keyed to that
    rename rather than to a count of looks, so it lands in the same window however many times the
    walk happens to look at a name on this filesystem (CI's differs from a developer's)."""
    real_rename, real_unlink = os.rename, os.unlink
    done = [False]

    def land(path) -> None:
        if not done[0] and Path(path) == target:
            done[0] = True
            write_private_text(target, text)

    def rename(src, dst, *args, **kwargs):
        land(src)
        return real_rename(src, dst, *args, **kwargs)

    def unlink(path, *args, **kwargs):
        # A pruner that removes by the name it looked at (round 9's) meets the writer here.
        land(path)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(session_module.os, "rename", rename)
    monkeypatch.setattr(session_module.os, "unlink", unlink)


# ------------------------------------------------------------------ F-04-REPORT-LOSS


def test_a_report_renamed_into_place_while_it_was_being_aged_out_is_kept(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    report = _aged(write_private_text(reports / "ts-20260101-000000-walk.md", "last spring's report"), 120)
    _replace_just_before_it_is_moved(monkeypatch, report, text="today's report")
    assert prune_reports(reports, 90, now=NOW) == 0
    assert report.read_text() == "today's report", "the fresh report is where it was written"
    assert sorted(p.name for p in reports.iterdir()) == [report.name], "nothing left beside it"


def test_a_report_renamed_into_an_old_folder_while_it_was_being_aged_out_is_kept(tmp_path, monkeypatch):
    """The descendant case: the folder and all in it old when looked at; a screen copy inside is
    replaced by a fresh one just before its own removal."""
    reports = tmp_path / "reports"
    screens = reports / "ts-20260101-000000-walk-screens"
    screens.mkdir(parents=True, mode=0o700)
    first = _aged(write_private_text(screens / "0001.json", "{}"), 120)
    later = _aged(write_private_text(screens / "0002.json", '{"old": true}'), 120)
    _aged(screens, 120)
    # The walk found the folder and all in it old; the fresh copy lands just before its removal.
    _replace_just_before_it_is_moved(monkeypatch, later, text='{"fresh": true}')
    assert prune_reports(reports, 90, now=NOW) == 0
    assert later.read_text() == '{"fresh": true}' and screens.is_dir(), "the fresh copy and its folder stay"
    assert not first.exists(), "what was old and untouched went"


def test_an_old_report_nobody_touches_still_ages_out(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    old = _aged(write_private_text(reports / "ts-20260101-000000-walk.md", "old"), 120)
    folder = reports / "ts-20260101-000000-walk-screens"
    folder.mkdir()
    _aged(write_private_text(folder / "0001.json", "{}"), 120)
    _aged(folder, 120)
    fresh = write_private_text(reports / "ts-20260927-000000-walk.md", "new")
    assert prune_reports(reports, 90, now=NOW) == 2
    assert not old.exists() and not folder.exists() and fresh.read_text() == "new"
    assert sorted(p.name for p in reports.iterdir()) == [fresh.name]


def test_a_name_taken_again_while_a_report_is_put_back_keeps_both(tmp_path, monkeypatch):
    """Two writers in the window: the one moved aside is put back with a link that never replaces
    anything, so when the name is taken again it stays beside it, under a name that begins with
    its own and ages by its own time."""
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    report = _aged(write_private_text(reports / "ts-20260101-000000-walk.md", "old"), 120)
    _replace_just_before_it_is_moved(monkeypatch, report, text="first writer")
    real_link = os.link

    def link(src, dst, *args, **kwargs):
        write_private_text(Path(dst), "second writer")
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(session_module.os, "link", link)
    assert prune_reports(reports, 90, now=NOW) == 0
    texts = sorted(p.read_text() for p in reports.iterdir())
    assert texts == ["first writer", "second writer"], texts
    assert all(p.name.startswith(report.name) for p in reports.iterdir())


# ------------------------------------------------------------------ F-04-STARTUP


def test_a_report_owned_by_someone_else_is_not_private_whatever_its_mode(tmp_path, monkeypatch):
    """A 0600 file another user owns is theirs to open; a 0700 folder likewise. Withheld (moved
    into the owner's own private folder, out of that user's reach), never deleted."""
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    theirs = write_private_text(reports / "ts-20260927-000000-walk.md", "the owner's words")
    folder = reports / "ts-20260927-000000-walk-screens"
    folder.mkdir(mode=0o700)
    write_private_text(folder / "0001.json", "{}")
    real = os.lstat
    me = os.geteuid()

    class Stat:
        def __init__(self, st):
            self._st = st

        def __getattr__(self, name):
            return me + 1 if name == "st_uid" else getattr(self._st, name)

    def lstat(path, *args, **kwargs):
        answer = real(path, *args, **kwargs)
        return Stat(answer) if Path(path).name in (theirs.name, folder.name) else answer

    monkeypatch.setattr(session_module.os, "lstat", lstat)
    exposure = session_module.tighten(reports)
    assert set(exposure.exposed) == {theirs, folder}
    store = TestSessions(tmp_path / "logs", clock=Clock(), reports_dir=reports)
    store.tidy_reports(NOW)
    assert not theirs.exists() and not folder.exists(), "out of that user's reach"
    kept = sorted(p.name for p in (reports / session_module.WITHHELD).iterdir())
    assert len(kept) == 2 and any(k.endswith(theirs.name) for k in kept), kept
    assert store.tidy_contained is True, "withheld inside a folder only the service's user can enter"


def test_a_reports_folder_someone_else_owns_is_not_contained(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    real = os.lstat

    class Stat:
        def __init__(self, st):
            self._st = st

        def __getattr__(self, name):
            return os.geteuid() + 1 if name == "st_uid" else getattr(self._st, name)

    monkeypatch.setattr(session_module.os, "lstat",
                        lambda path, *a, **k: Stat(real(path, *a, **k)) if Path(path) == reports else real(path, *a, **k))
    store = TestSessions(tmp_path / "logs", clock=Clock(), reports_dir=reports)
    store.tidy_reports(NOW)
    assert store.tidy_contained is False and "readable by others" in store.tidy_problem


def test_a_link_among_the_reports_is_not_called_private(tmp_path):
    """A link's own mode says nothing of what it points at, which may be readable by another path.
    It is neither followed nor moved nor removed: it is said, and the reports are not contained
    until the owner takes it out."""
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    elsewhere = tmp_path / "web" / "exposed.md"
    elsewhere.parent.mkdir()
    elsewhere.write_text("a report readable from the web folder")
    os.chmod(elsewhere, 0o644)
    link = reports / "ts-20260927-000000-walk.md"
    os.symlink(elsewhere, link)
    store = TestSessions(tmp_path / "logs", clock=Clock(), reports_dir=reports)
    store.tidy_reports(NOW)
    assert store.tidy_contained is False and "are links" in store.tidy_problem
    assert link.is_symlink() and elsewhere.stat().st_mode & 0o777 == 0o644, "neither followed nor moved"
    link.unlink()
    store.tidy_reports(NOW)
    assert store.tidy_contained is True
    # The reports folder itself a link: not contained either.
    real = tmp_path / "real-reports"
    real.mkdir(mode=0o700)
    linked = tmp_path / "linked-reports"
    os.symlink(real, linked)
    store = TestSessions(tmp_path / "logs2", clock=Clock(), reports_dir=linked)
    store.tidy_reports(NOW)
    assert store.tidy_contained is False and "are links" in store.tidy_problem


# ------------------------------------------------------------------ F-A3B-SHORT-WRITE


def test_a_short_write_is_finished_and_every_line_is_whole(tmp_path, monkeypatch):
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    real_write = os.write
    calls = [0]

    def short(fd, data):
        calls[0] += 1
        chunk = bytes(data[: max(1, len(data) // 3)])     # a third at a time, at most
        return real_write(fd, chunk)

    session = timeline.start("short writes")
    assert timeline.flush()
    # os.write is the process's own: short from here, for the timeline's writer (the session's
    # own small files are written before and after).
    monkeypatch.setattr(timeline_module.os, "write", short)
    for n in range(20):
        timeline.emit("turn_started", n=n, text="x" * 200)
    assert timeline.flush(timeout_s=5)
    monkeypatch.undo()
    path = store.timeline_path(session)
    lines = path.read_bytes().split(b"\n")
    assert lines[-1] == b"" and all(line.startswith(b"{") and line.endswith(b"}") for line in lines[:-1])
    assert len(read_events(path)) == count_events(path) == 21 and calls[0] > 20
    stopped = timeline.stop()
    counts = timeline.counts
    assert stopped is not None and timeline.stop_settled is True
    assert counts["on_disk"] == 22 and counts["pending"] == 0 and counts["dropped"] == 0 and counts["this_process"] == 22


def test_a_write_that_fails_part_way_counts_only_whole_lines_and_leaves_no_part_line(tmp_path, monkeypatch):
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    session = timeline.start("disk fills")
    assert timeline.flush()
    real_write = os.write
    budget = {"bytes": None}

    def filling(fd, data):
        if budget["bytes"] is None:
            return real_write(fd, data)
        if budget["bytes"] <= 0:
            raise OSError(errno.ENOSPC, "No space left on device")
        chunk = bytes(data[: budget["bytes"]])
        budget["bytes"] -= len(chunk)
        return real_write(fd, chunk)

    monkeypatch.setattr(timeline_module.os, "write", filling)
    gate = threading.Event()
    real_append = timeline._append

    def gated(path, lines):
        gate.wait(5)
        return real_append(path, lines)

    monkeypatch.setattr(timeline, "_append", gated)
    for n in range(5):
        timeline.emit("turn_started", n=n)
    one = len((timeline_module.json.dumps({"x": 1}) + "\n").encode())
    budget["bytes"] = 2 * 130 + one      # room for about two lines and part of a third
    gate.set()
    assert timeline.flush(timeout_s=5)
    path = store.timeline_path(session)
    raw = path.read_bytes()
    assert raw.endswith(b"\n") and all(line.startswith(b"{") and line.endswith(b"}") for line in raw.split(b"\n")[:-1])
    counts = timeline.counts
    assert counts["on_disk"] == len(read_events(path)) == 1 + counts["this_process"] - 1
    assert counts["dropped"] == 5 - (counts["on_disk"] - 1) and counts["pending"] == 0


# ------------------------------------------------------------------ F-10


def test_a_writer_that_cannot_hold_the_lock_writes_nothing_a_command_would_miss(tmp_path, monkeypatch):
    """The finding's sequence: the backend's writer cannot take its hold on the writer lock (here
    the shared flock fails outright), and then a command, finding no writer holding the lock, reads
    the file's count as final. Nothing may land after that: an event accepted without the hold
    would. So none is accepted, or written, without it."""
    import fcntl

    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    session = store.start("no lock")
    timeline = Timeline(store, clock=clock)
    real_flock = fcntl.flock

    def failing(fd, operation):
        if operation & fcntl.LOCK_SH:
            raise OSError(errno.ENOLCK, "No locks available")
        return real_flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", failing)
    assert timeline.emit("turn_started") is None, "not accepted without the hold"
    assert timeline.counts["pending"] == 0 and timeline.counts["dropped"] == 1
    assert writer_alive(store.root) is False, "the command's own check succeeds and sees no writer"
    final = count_events(store.timeline_path(session))
    assert timeline.flush(timeout_s=1)
    assert count_events(store.timeline_path(session)) == final, "nothing lands after the count was called final"

    # Accepted while a command held the lock for a moment, then the writer's own hold fails: the
    # batch is dropped, never written unprotected.
    busy = {"left": 1}

    def busy_then_failing(fd, operation):
        if operation & fcntl.LOCK_SH and operation & fcntl.LOCK_NB and busy["left"]:
            busy["left"] -= 1
            raise BlockingIOError(errno.EWOULDBLOCK, "held by a command")
        return failing(fd, operation)

    monkeypatch.setattr(fcntl, "flock", busy_then_failing)
    assert timeline.emit("turn_started") is not None, "accepted: the writer takes the hold before it writes"
    assert timeline.flush(timeout_s=5)
    assert count_events(store.timeline_path(session)) == final and timeline.counts["dropped"] == 2
    assert writer_alive(store.root) is False

    # With the lock working again, events are written as before.
    monkeypatch.setattr(fcntl, "flock", real_flock)
    assert timeline.emit("turn_started") is not None and timeline.flush(timeout_s=5)
    assert count_events(store.timeline_path(session)) == final + 1
    assert writer_alive(store.root) is True, "and now a command sees the writer"


# ------------------------------------------------------------------ F-04-SHUTDOWN


def _boot_with_a_slow_writer(monkeypatch, tmp_path, *, deadline_s: float, finish_after_s: float | None,
                             write_s: float) -> tuple[Path, list[str], threading.Event]:
    """Boot the app with a real timeline on a session of its own whose writer takes `write_s` over
    each batch, emit events, let a housekeeping pass run on (ending `finish_after_s` into the
    shutdown, or not until released), and shut down. Returns the session's timeline, the order of
    what happened, and the release."""
    import asyncio
    import time

    from app import main as main_module
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(main_module, "SHUTDOWN_WAIT_S", min(0.1, deadline_s))
    monkeypatch.setattr(main_module, "SHUTDOWN_DEADLINE_S", deadline_s)
    monkeypatch.setattr(main_module, "SHUTDOWN_CLOSE_BY_S", deadline_s + 1.0)
    monkeypatch.setattr(main_module, "SHUTDOWN_EXIT_BY_S", deadline_s + 6.0, raising=False)
    monkeypatch.setattr(main_module, "SHUTDOWN_FLUSH_S", 5.0, raising=False)
    monkeypatch.setattr(main_module, "HOUSEKEEPING_S", 0.01)
    started, release = threading.Event(), threading.Event()
    order: list[str] = []

    def slow_pass(runtime):
        if not order:
            order.append("first pass")
            return ""
        started.set()
        release.wait(30)
        order.append("pass finished")
        return ""

    monkeypatch.setattr(main_module, "housekeep_once", slow_pass)
    store = TestSessions(tmp_path / "logs", clock=time.time)
    timeline = Timeline(store)
    real_append = timeline._append

    def slow_append(path, lines):
        time.sleep(write_s)
        return real_append(path, lines)

    monkeypatch.setattr(timeline, "_append", slow_append)
    session = store.start("shutdown")
    path = store.timeline_path(session)

    async def boot():
        async with main_module.app.router.lifespan_context(main_module.app):
            runtime = main_module.app.state.runtime

            async def aclose():
                order.append("runtime closed")

            runtime.aclose = aclose
            runtime.timeline = timeline
            timeline_module.install(timeline)
            while not started.is_set():
                await asyncio.sleep(0.01)
            for n in range(3):
                timeline.emit("turn_finished", n=n)
            if finish_after_s is not None:
                threading.Timer(finish_after_s, release.set).start()

    try:
        asyncio.run(boot())
    finally:
        timeline_module.install(timeline_module.NullTimeline())
    return path, order, release


def test_accepted_events_are_on_disk_when_a_pass_outruns_the_shutdown_deadline(tmp_path, monkeypatch):
    """The runtime is left open under the pass, as before; the timeline, which shares nothing with
    the pass, is drained all the same before shutdown returns."""
    path, order, release = _boot_with_a_slow_writer(monkeypatch, tmp_path, deadline_s=0.3, finish_after_s=None,
                                                    write_s=1.2)
    try:
        assert "runtime closed" not in order, "never closed under the pass"
        assert count_events(path) == 3, "every accepted event reached the file before shutdown returned"
    finally:
        release.set()


def test_accepted_events_are_on_disk_after_a_normal_shutdown_too(tmp_path, monkeypatch):
    path, order, _release = _boot_with_a_slow_writer(monkeypatch, tmp_path, deadline_s=3.0, finish_after_s=0.05,
                                                     write_s=1.2)
    assert order[-2:] == ["pass finished", "runtime closed"], order
    assert count_events(path) == 3


@pytest.mark.parametrize("pending", [True, False])
def test_the_drain_is_bounded_and_says_what_it_could_not_write(tmp_path, monkeypatch, caplog, pending):
    import asyncio

    from app import main as main_module

    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    timeline.start("drain")
    assert timeline.flush()
    release = threading.Event()
    real_append = timeline._append
    monkeypatch.setattr(timeline, "_append", lambda path, lines: (release.wait(10), real_append(path, lines))[1])
    if pending:
        timeline.emit("turn_finished")

    class Runtime:
        pass

    runtime = Runtime()
    runtime.timeline = timeline
    try:
        settled = asyncio.run(main_module.drain_timelines(runtime, timeout_s=0.2))
    finally:
        release.set()
    assert settled is (not pending)
    assert ("still being written when the process exited" in caplog.text) is pending


def test_the_removal_goes_in_the_same_order_however_the_disk_lists_a_folder(tmp_path, monkeypatch):
    """Which old file goes before a fresh one stops the pass is by name, not by how a filesystem
    happens to list a folder: the descendant case holds with the listing reversed (the CI runner's
    disk listed it the other way round from a developer's)."""
    real = os.walk

    def reversed_walk(*args, **kwargs):
        for here, dirs, files in real(*args, **kwargs):
            yield here, list(reversed(sorted(dirs))), list(reversed(sorted(files)))

    monkeypatch.setattr(session_module.os, "walk", reversed_walk)
    test_a_report_renamed_into_an_old_folder_while_it_was_being_aged_out_is_kept(tmp_path, monkeypatch)
