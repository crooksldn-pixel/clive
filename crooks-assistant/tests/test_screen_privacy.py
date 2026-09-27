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
    assert 'viewBox="0 0 24 24"' in out, "a viewBox of four short numbers is kept"
    assert ' d="' not in out, "a path's free-form value is not kept (F-02, fourth round)"
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
    for leak in ("data-greg-evans", "07700900123", "x-customer", "greg@example.com", 'cx="Greg"', ' d="'):
        assert leak not in out, leak
    assert 'r="2"' in out


def test_no_drawing_value_can_carry_a_phone_number_written_as_it_appears():
    """F-02, fourth round: "M 07700 900123" has no seven-digit run and passed the old rule.
    Free-form drawing values are not kept at all, and a number is one short number."""
    html = ('<svg viewBox="0 07700 900123 1" width="07700" height="900123"><path d="M 07700 900123"/>'
            '<polyline points="07700 900123"/><g transform="translate(07700 900123)"><rect x="07700" y="900123"'
            ' width="24" height="12.5" rx="2px" stroke-dasharray="07700 900123"/></g>'
            '<circle cx="-12" cy="0.5" r="1e7"/></svg>')
    out = scrub_screen(html)
    for leak in ("07700", "900123", " d=", "points=", "transform=", "viewBox="):
        assert leak not in out, (leak, out)
    assert 'width="24"' in out and 'height="12.5"' in out and 'rx="2px"' in out
    assert 'cx="-12"' in out and 'cy="0.5"' in out and ' r="' not in out, "1e7 is not a short number"
    assert 'viewBox="0 0 24 24"' in scrub_screen('<svg viewBox="0,0, 24 24"></svg>')


def test_aria_names_are_the_wai_aria_list_and_nothing_else():
    """F-02, fourth round: aria-gregevans matched ^aria-[a-z]{2,20}$ and was kept."""
    out = scrub_screen('<button aria-label="Reply" aria-expanded="false" aria-gregevans="1" aria-x="1" '
                       'aria-labelledby="t1">Reply</button>')
    assert 'aria-label="Reply"' in out and 'aria-expanded="false"' in out and 'aria-labelledby="t1"' in out
    assert "aria-gregevans" not in out and "aria-x" not in out


def test_data_names_are_a_fixed_list_that_covers_every_page_of_clives_own():
    """F-02, fourth round: the data- names come from a list written in the code, not from reading
    the web folder at run time (unreadable folder = empty list; a deploy = a stale one). This test
    reads the pages instead, so a page using a data- name the list lacks fails here, and the name
    is added on purpose."""
    from app.observability import screens

    web = Path(__file__).resolve().parent.parent / "web"
    used: set[str] = set()
    for path in [*web.glob("*.js"), *web.glob("*.html"), *web.glob("*.css")]:
        text = path.read_text(encoding="utf-8")
        used.update(re.findall(r"data-[a-z][a-z0-9-]*", text))
        for camel in re.findall(r"dataset\.([a-zA-Z]+)", text):
            used.add("data-" + re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), camel))
    assert used, "the pages were read"
    missing = sorted(used - screens.DATA_NAMES)
    assert not missing, f"add these to app/observability/screens.py DATA_NAMES (or stop using them): {missing}"
    assert screens.DATA_FREE_TEXT <= screens.DATA_NAMES
    source = (Path(screens.__file__)).read_text(encoding="utf-8")
    assert "glob(" not in source and "read_text" not in source and "lru_cache" not in source, \
        "the rule reads nothing from disk"


def test_data_values_that_are_free_text_are_kept_empty_and_the_rest_only_as_tokens():
    timeline_module.note_names(["Greg Evans"])
    try:
        out = scrub_screen(
            '<li data-label="Greg Evans" data-customer-name="Evans" data-ask="refund Greg" data-said="call him"'
            ' data-args="order=1047&amp;email=greg@example.com" data-state="held" data-ref="gid://shopify/Order/1047"'
            ' data-kind="order" data-tone="calm words here">x</li>')
    finally:
        timeline_module.forget_names()
    for leak in ("Evans", "refund", "call him", "greg@example.com", "calm words"):
        assert leak not in out, leak
    for kept in ('data-label=""', 'data-customer-name=""', 'data-ask=""', 'data-said=""', 'data-args=""',
                 'data-state="held"', 'data-ref="gid://shopify/Order/1047"', 'data-kind="order"', 'data-tone=""'):
        assert kept in out, kept


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


def test_an_event_the_writer_is_holding_is_still_pending(tmp_path, monkeypatch):
    """F-10, fourth round: between the writer taking a batch off the queue and that batch
    reaching the file, the queue is empty, and the event must still be in somebody's count.
    Counts never call that settled and flush waits for it."""
    import queue
    import threading

    taken, release = threading.Event(), threading.Event()

    class HoldingQueue(queue.Queue):
        """The writer's first get: the event leaves the queue, then the writer stalls before it
        has done anything else with it (the window the review found)."""

        def get(self, *args, **kwargs):
            item = super().get(*args, **kwargs)
            if not taken.is_set():
                taken.set()
                assert release.wait(5)
            return item

    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    timeline._queue = HoldingQueue(maxsize=100)
    timeline.start("held")
    assert taken.wait(5), "the writer took the start event"
    assert timeline._queue.qsize() == 0, "the queue is empty: the event is in the writer's hands"
    held = timeline.counts
    assert held["pending"] == 1 and held["settled"] is False and held["on_disk"] == 0
    assert timeline.flush(timeout_s=0.1) is False, "flush does not return early while the writer holds it"
    release.set()
    assert timeline.flush(timeout_s=5)
    after_get = timeline.counts
    assert after_get["pending"] == 0 and after_get["settled"] and after_get["on_disk"] == 1

    # And while the batch is being written: still pending until the file has it.
    in_write, let_write = threading.Event(), threading.Event()
    real_append = timeline._append

    def slow_append(path, lines):
        in_write.set()
        assert let_write.wait(5)
        return real_append(path, lines)

    monkeypatch.setattr(timeline, "_append", slow_append)
    timeline.emit("turn_started")
    assert in_write.wait(5)
    writing = timeline.counts
    assert writing["pending"] == 1 and writing["settled"] is False and writing["on_disk"] == 1
    let_write.set()
    assert timeline.flush(timeout_s=5)
    done = timeline.counts
    assert done["pending"] == 0 and done["settled"] is True and done["on_disk"] == 2 and done["this_process"] == 2


def test_a_write_that_fails_settles_as_dropped_not_as_written(tmp_path, monkeypatch):
    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    timeline.start("fails")
    assert timeline.flush()

    def broken(path, lines):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(timeline, "_append", broken)
    for _ in range(3):
        timeline.emit("turn_started")
    assert timeline.flush(timeout_s=5)
    counts = timeline.counts
    assert counts["pending"] == 0 and counts["settled"] and counts["dropped"] == 3 and counts["on_disk"] == 1


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


def test_housekeeping_runs_once_at_startup_before_the_first_request(tmp_path, monkeypatch):
    """F-04, fourth round: periodic was not enough; a restart must not leave a stale day, an aged
    session or an open report waiting up to HOUSEKEEPING_S for the first tick."""
    import asyncio

    from app import main as main_module
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    passes: list[object] = []
    monkeypatch.setattr(main_module, "housekeep_once", lambda runtime: passes.append(runtime) and "")
    monkeypatch.setattr(main_module, "HOUSEKEEPING_S", 3600)

    async def boot():
        async with main_module.app.router.lifespan_context(main_module.app):
            assert len(passes) == 1, "one pass ran before the app said it was ready"
            assert passes[0] is main_module.app.state.runtime
            assert main_module.app.state.housekeeper.check()["ok"] is True

    asyncio.run(boot())


def test_a_stop_that_did_not_settle_never_presents_its_count_as_final(tmp_path, monkeypatch, caplog):
    """F-10, round 6: Timeline.stop dropped flush's answer and `make test-session-stop` printed
    the file's count as the session's. The stop keeps whether it settled, the stop route carries
    the counts, and the CLI line says "not final" unless the backend said nothing was pending."""
    import threading

    from scripts.test_session import stopped_line

    clock = Clock()
    store = TestSessions(tmp_path, clock=clock)
    timeline = Timeline(store, clock=clock)
    timeline.start("stop")
    assert timeline.flush()
    hold = threading.Event()
    real_append = timeline._append

    def held(path, lines):
        assert hold.wait(10)
        return real_append(path, lines)

    monkeypatch.setattr(timeline, "_append", held)
    monkeypatch.setattr(timeline, "flush", lambda timeout_s=2.0: Timeline.flush(timeline, timeout_s=0.05))
    timeline.emit("turn_started")
    session = timeline.stop()
    assert session is not None and timeline.stop_settled is False
    assert "count is not final" in caplog.text
    counts = timeline.counts
    assert counts["settled"] is False and counts["pending"] >= 1
    line = stopped_line({"events": counts, "path": "/x.jsonl"})
    assert "not final" in line and "still being written" in line
    hold.set()
    assert Timeline.flush(timeline, timeout_s=5)
    final = timeline.counts
    assert final["settled"] is True
    # Round 7, F-10: the flush the stop did timed out, so even counts that settled afterwards are
    # not the stop's total unless the stop itself settled.
    late = stopped_line({"events": final, "stop_settled": False, "path": "/x.jsonl"})
    assert "not final" in late and "the stop's own flush did not settle" in late
    assert stopped_line({"events": final, "stop_settled": True, "path": "/x.jsonl"}).endswith("(final; 0 dropped)")
    assert "not final" in stopped_line({"events": final, "path": "/x.jsonl"}), "an answer that does not say is not final"
    assert "not final" in stopped_line({"events": {"written": 3}, "path": "/x.jsonl"}), "an older backend's answer is not final"


# --------------------------------------------------------------------------- round 6, F-04


def test_a_report_that_cannot_be_made_private_is_withheld_and_what_is_left_is_said(tmp_path, monkeypatch):
    """F-04, round 6: tighten() swallowed every failure, so a report the service could not make
    private stayed readable and nothing said so. Now what is still open afterwards is found by
    the kernel's own answer, taken out of reach (a 0700 folder of its own, or removed), and what
    even that cannot close is logged as an error and turns /health's housekeeping check red."""
    from pathlib import Path

    from app.observability import session as session_module

    clock = Clock()
    reports = tmp_path / "reports"
    reports.mkdir()
    stuck = reports / "ts-20260927-000000-walk.md"
    fine = reports / "ts-20260927-000000-other.md"
    for path in (stuck, fine):
        path.write_text("owner's words")
        os.chmod(path, 0o644)
    real_chmod = Path.chmod

    def chmod(self, mode, *args, **kwargs):
        if self.name == stuck.name:
            raise PermissionError("not the owner of this file")
        return real_chmod(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", chmod)
    store = TestSessions(tmp_path / "logs", clock=clock, always=False, reports_dir=reports)
    store.tidy_reports()
    assert not stuck.exists(), "left where anyone could read it"
    withheld = list((reports / session_module.WITHHELD).iterdir())
    assert [p.name.split("-", 1)[1] for p in withheld] == [stuck.name]
    assert oct((reports / session_module.WITHHELD).stat().st_mode & 0o777) == "0o700"
    assert oct(fine.stat().st_mode & 0o777) == "0o600" and store.tidy_problem == ""

    # Now nothing can be moved either: it stays, and that is said, in counts.
    stuck.write_text("owner's words")
    os.chmod(stuck, 0o644)
    monkeypatch.setattr(session_module.os, "rename", lambda *a, **k: (_ for _ in ()).throw(PermissionError("no")))
    store.tidy_reports()
    assert stuck.exists() and store.tidy_problem == "1 report path(s) are readable by others and could not be withheld"
    assert store.tidy_contained is False
    assert "walk" not in store.tidy_problem, "a problem that reaches /health names no file"

    from app.main import Housekeeper, housekeep_once

    class Runtime:
        tests = store

    assert housekeep_once(Runtime()) == store.tidy_problem
    keeper = Housekeeper(Runtime())
    keeper.run_pass()
    check = keeper.check()
    assert check["ok"] is False and "could not be withheld" in check["detail"]


def test_the_housekeeping_timer_is_started_again_whatever_stops_it():
    """F-04, round 6: the periodic pass was a bare task; one exception or a stray cancel ended it
    for good and nothing noticed. The keeper starts it again, counts it, and /health says so."""
    import asyncio

    from app.main import Housekeeper

    ran: list[int] = []

    def flaky(runtime):
        ran.append(len(ran))
        if len(ran) == 2:
            raise RuntimeError("a pass that broke")
        return ""

    async def scenario():
        keeper = Housekeeper(object(), interval_s=0.01, pass_fn=flaky)
        await keeper.first_pass()
        keeper.start()
        for _ in range(200):
            await asyncio.sleep(0.01)
            if len(ran) >= 4:
                break
        assert keeper.restarts >= 1 and len(ran) >= 4, (keeper.restarts, ran)
        assert "RuntimeError" in keeper.check()["detail"]
        # A cancel nobody asked for is a stop too.
        before = keeper.restarts
        keeper._task.cancel()
        for _ in range(100):
            await asyncio.sleep(0.01)
            if keeper.restarts > before and len(ran) >= 6:
                break
        assert keeper.restarts == before + 1 and "cancelled" in keeper.check()["detail"]
        assert await keeper.stop() is True
        count = len(ran)
        await asyncio.sleep(0.05)
        assert len(ran) == count, "nothing is scheduled once it is stopped"

    asyncio.run(scenario())


def test_shutdown_waits_for_a_pass_already_running_before_the_runtime_is_closed(monkeypatch):
    """F-04, round 6: cancelling a task awaiting asyncio.to_thread does not stop the thread, so a
    pass could still be running while runtime.aclose() tore down what it was using. Shutdown now
    stops scheduling and waits for that pass; the runtime is closed after it, never during it."""
    import asyncio
    import threading

    from app import main as main_module
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    order: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def slow_pass(runtime):
        if order:                     # the first pass, before serving, is quick
            started.set()
            release.wait(5)
            order.append("pass finished")
        else:
            order.append("first pass")
        return ""

    monkeypatch.setattr(main_module, "housekeep_once", slow_pass)
    monkeypatch.setattr(main_module, "HOUSEKEEPING_S", 0.01)

    async def boot():
        async with main_module.app.router.lifespan_context(main_module.app):
            runtime = main_module.app.state.runtime
            real_aclose = runtime.aclose

            async def aclose():
                order.append("runtime closed")
                await real_aclose()

            runtime.aclose = aclose
            while not started.is_set():
                await asyncio.sleep(0.01)
            threading.Timer(0.2, release.set).start()
        # (leaving the block is the shutdown)

    asyncio.run(boot())
    assert order == ["first pass", "pass finished", "runtime closed"], order


# --------------------------------------------------------------------------- round 7, F-04


def _exposed_reports(tmp_path, monkeypatch, *, names):
    """A reports folder where chmod is refused for `names` (files or folders)."""
    from pathlib import Path

    reports = tmp_path / "reports"
    reports.mkdir()
    real_chmod = Path.chmod

    def chmod(self, mode, *args, **kwargs):
        if self.name in names:
            raise PermissionError("not the owner of this file")
        return real_chmod(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", chmod)
    return reports


def test_a_report_that_cannot_be_moved_is_never_deleted_whatever_its_age(tmp_path, monkeypatch):
    """Round 7, F-04-REPORT-LOSS: when a report could not be moved out of reach, withhold()
    removed it — any age, a folder of screen copies by rmtree. It now leaves it where it is, says
    so, and the service will not start with it that way. A fresh report and a fresh folder."""
    from app.observability import session as session_module

    fresh = "ts-20260927-000000-walk.md"
    pictures = "ts-20260927-000000-walk-screens"
    reports = _exposed_reports(tmp_path, monkeypatch, names={fresh, pictures})
    (reports / fresh).write_text("the owner's report")
    os.chmod(reports / fresh, 0o644)
    (reports / pictures).mkdir()
    os.chmod(reports / pictures, 0o755)
    (reports / pictures / "0001.json").write_text("{}")
    monkeypatch.setattr(session_module.os, "rename", lambda *a, **k: (_ for _ in ()).throw(PermissionError("no")))
    store = TestSessions(tmp_path / "logs", clock=Clock(), always=False, reports_dir=reports)
    store.tidy_reports()
    assert (reports / fresh).read_text() == "the owner's report", "never deleted"
    assert (reports / pictures / "0001.json").exists(), "a folder is never removed either"
    assert store.tidy_contained is False and "2 report path(s)" in store.tidy_problem
    assert "shutil" not in session_module.withhold.__code__.co_names and "_remove_if_older" not in session_module.withhold.__code__.co_names


def test_moving_a_report_out_of_reach_never_overwrites_anything(tmp_path, monkeypatch):
    from app.observability import session as session_module

    reports = _exposed_reports(tmp_path, monkeypatch, names={"ts-a.md"})
    (reports / "ts-a.md").write_text("new")
    os.chmod(reports / "ts-a.md", 0o644)
    kept = reports / session_module.WITHHELD
    kept.mkdir(mode=0o700)
    import uuid

    monkeypatch.setattr(uuid, "uuid4", lambda: type("U", (), {"hex": "same"})())
    (kept / "same-ts-a.md").write_text("already withheld")
    withheld, left = session_module.withhold(reports, [reports / "ts-a.md"])
    assert (kept / "same-ts-a.md").read_text() == "already withheld", "never over anything"
    assert withheld == 0 and left == [reports / "ts-a.md"] and (reports / "ts-a.md").read_text() == "new"


def test_a_reports_folder_that_cannot_be_made_private_or_read_is_not_contained(tmp_path, monkeypatch):
    """Round 7, F-04-STARTUP: the folder itself left open, or a walk that could not finish, is
    not "nothing exposed"."""
    from app.observability import session as session_module

    reports = _exposed_reports(tmp_path, monkeypatch, names={"reports"})
    os.chmod(reports, 0o755)
    store = TestSessions(tmp_path / "logs", clock=Clock(), always=False, reports_dir=reports)
    store.tidy_reports()
    assert store.tidy_contained is False and "readable by others" in store.tidy_problem

    other = tmp_path / "other"
    other.mkdir()
    (other / "deep").mkdir()
    real_walk = os.walk

    def broken_walk(top, onerror=None, **kwargs):
        if onerror is not None:
            onerror(PermissionError(13, "denied", str(other / "deep")))
        yield from real_walk(top, onerror=onerror, **kwargs)

    monkeypatch.setattr(session_module.os, "walk", broken_walk)
    found = session_module.tighten(other)
    assert found.unread == [str(other / "deep")] and found.exposed == []
    store2 = TestSessions(tmp_path / "logs2", clock=Clock(), always=False, reports_dir=other)
    store2.tidy_reports()
    assert store2.tidy_contained is False and "could not be checked" in store2.tidy_problem


def test_the_service_will_not_start_with_reports_it_cannot_keep_private(monkeypatch):
    import asyncio

    from app import main as main_module
    from app.observability.session import TestSessions as Sessions
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)

    def exposed(self, now=None):
        self.tidy_problem = "1 report path(s) are readable by others and could not be withheld"
        self.tidy_contained = False
        return 0

    monkeypatch.setattr(Sessions, "tidy_reports", exposed)
    served: list[bool] = []

    async def boot():
        async with main_module.app.router.lifespan_context(main_module.app):
            served.append(True)

    with pytest.raises(RuntimeError, match="will not start with reports it cannot keep private"):
        asyncio.run(boot())
    assert served == [], "it never answered anything"


def test_shutdown_never_closes_the_runtime_under_a_pass_that_outlasts_the_wait(monkeypatch):
    """Round 7, F-04-SHUTDOWN: stop() waited 60 s and then the runtime was closed regardless.
    Now a pass still running when the wait is over keeps its runtime: aclose is not called."""
    import asyncio
    import threading

    from app import main as main_module
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(main_module, "SHUTDOWN_WAIT_S", 0.2)
    monkeypatch.setattr(main_module, "HOUSEKEEPING_S", 0.01)
    started, release = threading.Event(), threading.Event()
    order: list[str] = []

    def stuck_pass(runtime):
        if not order:
            order.append("first pass")
            return ""
        started.set()
        release.wait(10)
        order.append("pass finished")
        return ""

    monkeypatch.setattr(main_module, "housekeep_once", stuck_pass)

    async def boot():
        async with main_module.app.router.lifespan_context(main_module.app):
            runtime = main_module.app.state.runtime

            async def aclose():
                order.append("runtime closed")

            runtime.aclose = aclose
            while not started.is_set():
                await asyncio.sleep(0.01)
            # The pass outlasts the 0.2 s wait, finishing only at 0.6 s.
            threading.Timer(0.6, release.set).start()

    try:
        asyncio.run(boot())    # the loop's own close waits for the thread; the runtime is never closed
    finally:
        release.set()
    assert order == ["first pass", "pass finished"], order
    assert "runtime closed" not in order, "never closed under the pass, not even after it"


def test_the_control_apps_stop_never_calls_a_snapshot_recorded(tmp_path, monkeypatch):
    """Round 7, F-10: scripts/session_ops.py said "Recorded N event(s)" once two reads of the file
    agreed, which a stalled writer produces exactly. It now reads the backend's own answer."""
    from scripts import session_ops

    path = tmp_path / "ts.jsonl"
    path.write_text('{"kind":"a"}\n{"kind":"b"}\n')
    answers = {
        "held": {"stopped": True, "test_session_id": "ts-x", "path": str(path), "stop_settled": False,
                 "events": {"on_disk": 2, "pending": 3, "settled": False}},
        "settled": {"stopped": True, "test_session_id": "ts-x", "path": str(path), "stop_settled": True,
                    "events": {"on_disk": 2, "pending": 0, "settled": True}},
    }
    for which, expect_final in (("held", False), ("settled", True)):
        monkeypatch.setattr(session_ops, "call", lambda port, method, route, body=None, which=which, **k: answers[which])
        out = session_ops.stop_and_analyse(8000, log_dir=tmp_path / "logs", analyse=False,
                                           sleep=lambda s: None, now=iter(range(100)).__next__)
        assert out["final"] is expect_final, which
        if expect_final:
            assert out["human"] == "Recorded 2 event(s) in ts-x."
        else:
            assert "not final" in out["human"] and "3 were still being written" in out["human"]
            assert "Recorded" not in out["human"]


async def test_the_stop_route_says_whether_its_flush_settled(tmp_path, monkeypatch):
    import httpx

    from app.main import app
    from tests.test_actions_routes import as_owner

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        as_owner(runtime)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
            assert (await http.post("/test-session/start", json={"name": "route-settle"})).json()["started"]
            monkeypatch.setattr(runtime.timeline, "flush", lambda timeout_s=2.0: False)
            stopped = (await http.post("/test-session/stop")).json()
    assert stopped["stopped"] is True and stopped["stop_settled"] is False
    from app.observability.timeline import stop_is_final

    assert stop_is_final(stopped) is False
