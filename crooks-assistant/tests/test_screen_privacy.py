"""The deploy review's findings on test mode (the b9871787 review):

- a screen copy never keeps what was typed, and its text is redacted by the timeline's own rule
  before it is written, whatever the page sent;
- reports and drawn screens are the owner's alone (0600 files in 0700 folders), from the moment
  they exist;
- nothing test mode writes grows without a bound: a timeline stops at its cap, always-on days
  and sessions started by name age out, and so do the reports drawn from them.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.observability import session as session_module
from app.observability import timeline as timeline_module
from app.observability.session import (
    AUTO_NAME,
    TestSessions,
    private_dir,
    prune_reports,
    write_private_text,
)
from app.observability.timeline import Timeline
from app.routes.observe import scrub_screen
from tests.fake_credentials import shopify_token


class Clock:
    def __init__(self, now: float = 1_790_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _no_names():
    timeline_module.forget_names()
    yield
    timeline_module.forget_names()


# ------------------------------------------------------------------ what a screen copy keeps


def test_what_was_typed_is_masked_even_if_the_page_sent_it():
    html = ('<div id="app"><input class="alpha-input" type="text" value="refund order 1912 to jo@example.com"/>'
            '<textarea class="alpha-text">my card is 4111 1111 1111 1111</textarea></div>')
    out = scrub_screen(html)
    assert "refund" not in out and "jo@example.com" not in out and "4111" not in out
    assert re.search(r'value="•{24}"', out) and re.search(r">•{24}</textarea>", out)
    assert 'class="alpha-input"' in out and 'class="alpha-text"' in out


def test_the_text_on_screen_is_redacted_by_the_timelines_own_rule():
    timeline_module.note_names(["Priya Shah"])
    html = ('<div id="app"><p class="who">Priya Shah</p><p>priya@example.com · 07700 900123 · SW1A 1AA</p>'
            '<button aria-label="Email Priya Shah" title="07700 900123">Reply</button>'
            '<svg viewBox="0 0 24 24"><path d="M4 10v4 M8 7v10 0 0 24 24 12 12 12"/></svg>'
            '<span class="alpha-row-meta">3 days left</span></div>')
    out = scrub_screen(html)
    for leak in ("Priya", "priya@example.com", "07700 900123", "SW1A 1AA"):
        assert leak not in out, leak
    assert "[name]" in out and "[email]" in out and "[phone]" in out and "[postcode]" in out
    assert 'viewBox="0 0 24 24"' in out and 'd="M4 10v4 M8 7v10 0 0 24 24 12 12 12"' in out, "drawing paths untouched"
    assert "3 days left" in out and ">Reply<" in out


def test_a_credential_on_screen_is_not_kept():
    token = shopify_token("screen-privacy")
    out = scrub_screen(f'<div id="app"><pre>token {token}</pre></div>')
    assert token not in out and "shpat_" not in out and "[secret]" in out


# ------------------------------------------------------------------ files only the owner reads


def test_reports_are_private_from_the_moment_they_exist(tmp_path):
    old = os.umask(0o022)
    try:
        target = write_private_text(tmp_path / "reports" / "ts-1.md", "# report\n")
    finally:
        os.umask(old)
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    assert oct(target.parent.stat().st_mode & 0o777) == "0o700"
    assert target.read_text() == "# report\n"
    assert not list(target.parent.glob(".*.tmp")), "no half-written file left behind"
    open_dir = tmp_path / "open"
    open_dir.mkdir(mode=0o755)
    os.chmod(open_dir, 0o755)
    private_dir(open_dir)
    assert oct(open_dir.stat().st_mode & 0o777) == "0o700", "an existing folder is closed too"


def test_the_screen_drawer_writes_its_pictures_privately():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "browser" / "session_screens.js").read_text()
    assert "process.umask(0o077)" in src
    assert "mode: 0o700" in src and "chmodSync(OUT, 0o700)" in src


# ------------------------------------------------------------------ nothing grows without a bound


def test_a_timeline_stops_at_its_cap_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "MAX_TIMELINE_BYTES", 4_000)
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    session = timeline.start("cap")
    for i in range(200):
        timeline.emit("turn_started", session_id="s1", note="x" * 60, i=i)
    assert timeline.flush()
    path = store.timeline_path(session)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert path.stat().st_size <= 4_000 + 200
    assert [e["kind"] for e in lines].count("timeline_full") == 1 and lines[-1]["kind"] == "timeline_full"
    assert timeline.counts["dropped"] > 0


def test_always_on_days_and_named_sessions_both_age_out_and_the_running_one_never(tmp_path):
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock, always=True, keep_days=14, keep_named_days=90)
    running = store.active()
    root = store.root

    def aged(name: str, days: float, *, folder: bool = False) -> Path:
        path = root / name
        if folder:
            path.mkdir()
        else:
            path.write_text("{}\n")
        os.utime(path, (clock.now - days * 86_400, clock.now - days * 86_400))
        return path

    old_day = aged(f"ts-20260101-000000-{AUTO_NAME}.jsonl", 20)
    old_day_screens = aged(f"ts-20260101-000000-{AUTO_NAME}-screens", 20, folder=True)
    recent_named = aged("ts-20260801-120000-tablet-walkthrough.jsonl", 30)
    old_named = aged("ts-20260301-120000-first-run.jsonl", 120)
    old_named_screens = aged("ts-20260301-120000-first-run-screens", 120, folder=True)
    live = store.timeline_path(running)
    live.write_text("{}\n")
    os.utime(live, (clock.now - 400 * 86_400, clock.now - 400 * 86_400))

    removed = store.prune()
    assert removed == 4
    assert not old_day.exists() and not old_day_screens.exists()
    assert not old_named.exists() and not old_named_screens.exists()
    assert recent_named.exists(), "a named session inside its keep stays"
    assert live.exists(), "the session running is never removed, however old its file looks"


def test_reports_age_out_with_the_sessions_they_came_from(tmp_path):
    now = 1_790_000_000.0
    reports = tmp_path / "reports"
    reports.mkdir()
    keep = reports / "ts-20260901-000000-walk.md"
    old = reports / "ts-20260101-000000-walk.md"
    old_pictures = reports / "ts-20260101-000000-walk-screens"
    readme = reports / "README.md"
    for path in (keep, old, readme):
        path.write_text("x")
    old_pictures.mkdir()
    for path, days in ((keep, 10), (old, 120), (old_pictures, 120), (readme, 400)):
        os.utime(path, (now - days * 86_400, now - days * 86_400))
    assert prune_reports(reports, 90, now=now) == 2
    assert keep.exists() and readme.exists() and not old.exists() and not old_pictures.exists()


def test_the_settings_carry_both_ages():
    from config.settings import Settings

    settings = Settings(_env_file=None)
    assert settings.test_session_keep_named_days == 90
    store = TestSessions.from_settings(settings, always=False)
    assert store.keep_days == settings.test_session_keep_days and store.keep_named_days == 90 and not store.always


def test_a_session_started_by_name_ends_by_itself_and_the_day_resumes(tmp_path):
    """The 2026-09-26 deploy review, F-04: a named session left running would never end and never
    age out, and with test mode always on it would stop the day's own session from rolling."""
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock, always=True)
    named = store.start("walkthrough")
    clock.now += 2 * 3600
    store._checked_at = -1.0
    assert store.active().test_session_id == named.test_session_id, "hours in, it is still running"
    clock.now += session_module.NAMED_MAX_S
    store._checked_at = -1.0
    current = store.active()
    assert current is not None and current.name == AUTO_NAME, "past its day, the day's own takes over"
    assert store.last().test_session_id == named.test_session_id and store.last().stopped_at == clock.now
    plain = TestSessions(tmp_path / "plain", clock=clock)
    started = plain.start("left-on")
    clock.now += session_module.NAMED_MAX_S + 1
    plain._checked_at = -1.0
    assert plain.active() is None and plain.last().test_session_id == started.test_session_id


def test_github_tokens_are_credentials_to_the_shared_rule():
    from tests.fake_credentials import github_fine_grained_token, github_token

    for token in (github_token("rule"), github_token("rule", kind="s"), github_fine_grained_token("rule")):
        out = timeline_module.scrub_text(f"token {token} here")
        assert token not in out and "[secret]" in out


def test_the_daily_roll_ages_and_tightens_the_reports_too(tmp_path):
    """F-04 and F-03, second round: not only when someone runs a report command."""
    clock = Clock()
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o755)
    os.chmod(reports, 0o755)
    old = reports / "ts-20260101-000000-walk.md"
    recent = reports / "ts-20260901-000000-walk.md"
    pictures = reports / "ts-20260901-000000-walk-screens"
    for path in (old, recent):
        path.write_text("x")
        os.chmod(path, 0o644)
    pictures.mkdir(mode=0o755)
    os.chmod(pictures, 0o755)
    (pictures / "0001-error.png").write_bytes(b"png")
    os.chmod(pictures / "0001-error.png", 0o644)
    os.utime(old, (clock.now - 120 * 86_400, clock.now - 120 * 86_400))
    os.utime(recent, (clock.now - 5 * 86_400, clock.now - 5 * 86_400))
    store = TestSessions(tmp_path / "logs", clock=clock, always=True, reports_dir=reports)
    assert store.active() is not None   # the roll: the day's own session starts
    assert not old.exists() and recent.exists()
    assert oct(reports.stat().st_mode & 0o777) == "0o700"
    assert oct(recent.stat().st_mode & 0o777) == "0o600"
    assert oct(pictures.stat().st_mode & 0o777) == "0o700"
    assert oct((pictures / "0001-error.png").stat().st_mode & 0o777) == "0o600"


def test_a_stalled_writer_cannot_grow_memory_without_end(tmp_path, monkeypatch):
    """F-09: pending events are bounded where they come in, and a drop is counted there."""
    monkeypatch.setattr(timeline_module, "MAX_PENDING_EVENTS", 10)
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    timeline.start("stalled")
    monkeypatch.setattr(timeline, "_ensure_writer", lambda: None)   # the writer never runs
    timeline._queue = __import__("queue").Queue(maxsize=10)
    kept = [timeline.emit("turn_started", i=i) for i in range(50)]
    assert sum(1 for e in kept if e is not None) == 10
    assert timeline._queue.qsize() == 10 and timeline.counts["dropped"] == 40
    monkeypatch.setattr(timeline_module, "MAX_PENDING_BYTES", 10)
    timeline._queue = __import__("queue").Queue(maxsize=1000)
    timeline._pending_bytes = 0
    assert timeline.emit("turn_started", note="x" * 200) is None, "past the byte bound, dropped at once"


def test_attribute_names_are_allow_listed_and_drawing_values_are_numbers_only():
    """F-02, third round: an arbitrary attribute NAME is written down too, and a drawing value
    is not a place for a phone number."""
    timeline_module.note_names(["Greg Evans"])
    try:
        out = scrub_screen(
            '<div id="app" data-alpha="objective" data-snap-top="12" data-greg-evans="x" data-07700900123="y" '
            'x-customer="greg@example.com" style="color: red; content: \'greg@example.com\'">'
            '<svg viewBox="0 0 24 24"><path d="M 07700900123 1"/><path d="M4 10v4"/><circle cx="Greg" r="2"/></svg></div>')
    finally:
        timeline_module.forget_names()
    assert 'data-alpha="objective"' in out and 'data-snap-top="12"' in out
    for leak in ("data-greg-evans", "07700900123", "x-customer", "greg@example.com", 'cx="Greg"'):
        assert leak not in out, leak
    assert 'd="M4 10v4"' in out and 'r="2"' in out


def test_the_counts_call_written_only_what_is_on_disk(tmp_path, monkeypatch):
    """F-10: an event still waiting may yet be dropped, so it is pending, not written."""
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    timeline.start("counts")
    assert timeline.flush()
    # The writer stays blocked on the queue it was reading; what comes now waits in a new one.
    timeline._queue = __import__("queue").Queue(maxsize=100)
    timeline.emit("turn_started")
    timeline.emit("turn_started")
    counts = timeline.counts
    assert counts["written"] == counts["on_disk"] == 1, "only the start event is on disk"
    assert counts["pending"] == 2 and counts["settled"] is False


def test_housekeeping_runs_on_a_clock_with_nobody_using_the_service(tmp_path):
    """F-04, third round: the roll, the ages and the reports, from a timer in the backend."""
    from app.main import HOUSEKEEPING_S, housekeep_once

    assert HOUSEKEEPING_S <= 3600
    clock = Clock()
    reports = tmp_path / "reports"
    reports.mkdir()
    old = reports / "ts-20260101-000000-walk.md"
    old.write_text("x")
    os.utime(old, (clock.now - 120 * 86_400, clock.now - 120 * 86_400))

    class Runtime:
        tests = TestSessions(tmp_path / "logs", clock=clock, always=True, reports_dir=reports)

    housekeep_once(Runtime())
    assert not old.exists() and Runtime.tests.active() is not None
    housekeep_once(object())   # nothing to keep: nothing happens, nothing raises
