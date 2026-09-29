"""Round 13, RC-8: which test sessions and reports housekeeping may delete.

- O2-N-01: retention was chosen by `"-always-on" in path.name`, so a session the owner started
  by name, whose slug held those words ("review always on"), was kept for the day session's 14
  days instead of a named session's 90; and a name that slugged to exactly `always-on` made an
  id no one could tell from the day's own.
- O2-N-02: the reports folder was looked at through `os.stat`, which follows a link, so a
  reports path that was a link had the folder it pointed at pruned before the check that says
  "this is a link" ever ran.

The store is driven as the backend and the command line drive it: `start` and `stop` by name,
the daily roll's `_prune`, and `tidy_reports`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.observability import session as session_module
from app.observability.session import (
    AUTO_NAME,
    SESSION_ID,
    AlreadyActive,
    TestSessions,
    prune_reports,
)

NOW = 1_790_000_000.0       # an afternoon in September 2026
DAY = 86_400


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _aged(path: Path, days: float, now: float = NOW) -> Path:
    os.utime(path, (now - days * DAY, now - days * DAY), follow_symlinks=False)
    return path


def _files_of(store: TestSessions, ident: str) -> tuple[Path, Path]:
    """A session's timeline and its screens, as the timeline writer leaves them."""
    timeline = store.timeline_path(ident)
    timeline.write_text('{"event": "turn_finished"}\n')
    screens = store.root / f"{ident}{session_module.SCREENS_SUFFIX}"
    screens.mkdir()
    shot = screens / "0001.png"
    shot.write_bytes(b"png")
    return timeline, screens


def _age_all(paths, days: float) -> None:
    for path in paths:
        if path.is_dir():
            for inner in path.rglob("*"):
                _aged(inner, days)
        _aged(path, days)


# ------------------------------------------------------------------ O2-N-01


@pytest.mark.parametrize("name", ["review always on", "Checkout flow - always on", "Always On", "always-on"])
def test_a_session_started_by_name_is_kept_as_a_named_one_whatever_its_name_says(tmp_path, name):
    clock = Clock()
    store = TestSessions(tmp_path / "logs", clock=clock, always=True, keep_days=14, keep_named_days=90)
    session = store.start(name)
    assert not session.test_session_id.endswith(f"-{AUTO_NAME}"), session.test_session_id
    assert SESSION_ID.fullmatch(session.test_session_id), "still a session id every reader accepts"
    kept = _files_of(store, session.test_session_id)
    store.stop()
    _age_all(kept, 30)
    store._prune(NOW)
    assert all(p.exists() for p in kept), "a named session is kept for keep_named_days, not the day's 14"
    _age_all(kept, 91)
    store._prune(NOW)
    assert not any(p.exists() for p in kept), "and goes at keep_named_days like any named session"


def test_a_named_session_recorded_before_this_round_is_classified_by_its_whole_id(tmp_path):
    """An id already on disk from an earlier build, whose slug holds the words: kept 90 days."""
    store = TestSessions(tmp_path / "logs", clock=Clock(), always=False, keep_days=14, keep_named_days=90)
    store.root.mkdir(parents=True)
    kept = _files_of(store, "ts-20260801-100000-review-always-on")
    _age_all(kept, 30)
    store._prune(NOW)
    assert all(p.exists() for p in kept)


def test_the_day_s_own_session_still_goes_at_keep_days(tmp_path):
    store = TestSessions(tmp_path / "logs", clock=Clock(), always=False, keep_days=14, keep_named_days=90)
    store.root.mkdir(parents=True)
    old = _files_of(store, f"ts-20260801-000001-{AUTO_NAME}")
    recent = _files_of(store, f"ts-20260920-000001-{AUTO_NAME}")
    _age_all(old, 20)
    _age_all(recent, 10)
    store._prune(NOW)
    assert not any(p.exists() for p in old)
    assert all(p.exists() for p in recent)


def test_the_day_s_own_session_keeps_its_own_id(tmp_path):
    store = TestSessions(tmp_path / "logs", clock=Clock(), always=True)
    day = store.active()
    assert day is not None and day.name == AUTO_NAME
    assert day.test_session_id.endswith(f"-{AUTO_NAME}")


def test_a_session_named_always_on_is_the_owner_s_not_the_day_s(tmp_path):
    """Named exactly as the day's own is, it is still his: it does not roll at midnight, and a
    second session started by name does not quietly close it."""
    clock = Clock(NOW)
    store = TestSessions(tmp_path / "logs", clock=clock, always=True)
    mine = store.start(AUTO_NAME)
    store._checked_at = -1.0
    assert store.active().test_session_id == mine.test_session_id
    with pytest.raises(AlreadyActive):
        store.start("another walk")
    clock.now = NOW + 12 * 3600          # past midnight, inside a named session's day
    store._checked_at = -1.0
    assert store.active().test_session_id == mine.test_session_id


# ------------------------------------------------------------------ O2-N-02


def _linked_reports(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "somewhere-else"
    target.mkdir(mode=0o700)
    old = _aged(_write(target / "ts-20260301-100000-walk.md"), 200)
    link = tmp_path / "reports"
    os.symlink(target, link)
    return link, old


def _write(path: Path) -> Path:
    path.write_text("a report")
    os.chmod(path, 0o600)
    return path


def test_a_reports_folder_that_is_a_link_is_not_pruned_through(tmp_path):
    link, old = _linked_reports(tmp_path)
    store = TestSessions(tmp_path / "logs", clock=Clock(), reports_dir=link)
    assert store.tidy_reports(NOW) == 0
    assert old.exists(), "what the link points at is not the reports folder's to prune"
    assert store.tidy_contained is False and "are links" in store.tidy_problem


def test_prune_reports_refuses_a_linked_folder_from_the_command_line_too(tmp_path):
    link, old = _linked_reports(tmp_path)
    assert prune_reports(link, 90, now=NOW) == 0
    assert old.exists()


def test_a_real_reports_folder_is_still_pruned(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    old = _aged(_write(reports / "ts-20260301-100000-walk.md"), 200)
    fresh = _write(reports / "ts-20260920-100000-walk.md")
    store = TestSessions(tmp_path / "logs", clock=Clock(), reports_dir=reports)
    assert store.tidy_reports(NOW) == 1
    assert not old.exists() and fresh.exists() and store.tidy_contained is True
