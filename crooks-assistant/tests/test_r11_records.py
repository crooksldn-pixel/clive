"""Records, the timeline and shutdown (the 2026-09-28 deploy review, round 10, answered in round 11):

- R9-A3b-F-04-SHUTDOWN and CFG-02: shutdown read its stop only BETWEEN housekeeping's steps, so one
  step over a big folder ran on past the unit's deadline, the runtime was left unclosed under it, and
  uvicorn — with no bound on its graceful drain — let one held connection keep the app's shutdown
  from starting at all before SIGKILL. Now every walk reads the stop before each entry, uvicorn
  cancels what is still running after SHUTDOWN_GRACEFUL_S, and the budget adds up inside the unit's
  TimeoutStopSec.
- O1 F-01 and R9-A3b-F-10: an event was accepted while a command held the writer lock for its look,
  and written once the writer took the lock; the command, letting go and finding no writer, had
  already called the count final. Now nothing is accepted without the hold.
- R9-A3b-F-04-STARTUP: the service will not start with a link among its reports or a reports folder
  another user owns — through the real start-up, not only the check.
- R9-A3a-A3a-LIVE-CLEAN: the live gap record's shape (ten rows, already clean, one copy already
  kept) goes through the real start-up and comes out byte for byte, with no second copy.
- R9-E-families1-E-05: every module under app/, scripts/ and config/ imports, every import in them —
  the lazy ones inside functions included — resolves to a module or a name that exists, and nothing
  names a module deleted with the fast lane.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import json
import os
import pkgutil
import re
import threading
import time
from pathlib import Path

import pytest

from app.observability import session as session_module
from app.observability import timeline as timeline_module
from app.observability.session import RECHECK_S, TestSessions, write_private_text
from app.observability.timeline import WRITER_LOCK, Timeline, count_events, writer_alive

ROOT = Path(__file__).resolve().parent.parent
UNIT = ROOT / "deploy" / "systemd" / "crooks-assistant.service"
DAY = 86_400


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _no_provider(monkeypatch) -> None:
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)


# ------------------------------------------------------------------ the unit and the budget


def _unit_line(prefix: str) -> str:
    (line,) = [ln for ln in UNIT.read_text(encoding="utf-8").splitlines() if ln.startswith(prefix)]
    return line


def test_the_units_stop_and_the_apps_shutdown_budget_are_one_plan():
    """CFG-02: ExecStart bounds uvicorn's graceful drain, and everything after it — housekeeping
    stopped, the runtime closed, the timeline drained — fits inside TimeoutStopSec with room for
    the process to exit. The rest of ExecStart is as it was, --no-proxy-headers last."""
    from app import main as main_module

    exec_start = _unit_line("ExecStart=")
    assert exec_start == ("ExecStart={{PYTHON}} -m uvicorn app.main:app --host {{HOST}} --port {{PORT}} "
                          f"--timeout-graceful-shutdown {main_module.SHUTDOWN_GRACEFUL_S} --no-proxy-headers")
    assert _unit_line("TimeoutStopSec=") == f"TimeoutStopSec={main_module.UNIT_STOP_S}"
    assert _unit_line("KillSignal=") == "KillSignal=SIGINT"
    m = main_module
    assert 0 < m.SHUTDOWN_WAIT_S < m.SHUTDOWN_DEADLINE_S < m.SHUTDOWN_CLOSE_BY_S < m.SHUTDOWN_EXIT_BY_S
    assert m.SHUTDOWN_FLUSH_MIN_S <= m.SHUTDOWN_FLUSH_S
    # The latest the lifespan can end (lifespan: a close is given at least 1 s, a drain at least
    # SHUTDOWN_FLUSH_MIN_S), after uvicorn's drain and its 0.1 s pause, with the margin to spare.
    lifespan_ends = max(m.SHUTDOWN_EXIT_BY_S, m.SHUTDOWN_CLOSE_BY_S + m.SHUTDOWN_FLUSH_MIN_S,
                        m.SHUTDOWN_DEADLINE_S + 1.0 + m.SHUTDOWN_FLUSH_MIN_S)
    assert m.SHUTDOWN_GRACEFUL_S + 0.1 + lifespan_ends + m.SHUTDOWN_EXIT_MARGIN_S <= m.UNIT_STOP_S


def test_the_installer_renders_the_bounded_drain_into_the_unit_it_installs():
    """`make install` (and so the deploy, which re-renders the unit) writes these lines as they are."""
    import importlib.util as util

    spec = util.spec_from_file_location("install_systemd_r11", ROOT / "scripts" / "install_systemd.py")
    installer = util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    unit = installer.rendered_unit({
        "ROOT": "/r", "PYTHON": "/p", "HOME": "/root", "PATH": "/usr/bin", "CLAUDE": "/c",
        "HOST": "127.0.0.1", "PORT": "8000", "SECRET_DIR": "/s", "CREDENTIALS": "",
    })
    assert ("ExecStart=/p -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 15 "
            "--no-proxy-headers") in unit.splitlines()
    assert "TimeoutStopSec=45" in unit.splitlines()
    from app import identity

    argv = ["/p", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000",
            "--timeout-graceful-shutdown", "15", "--no-proxy-headers"]
    assert identity.served_without_proxy_headers(argv)[0] is True, "the proxy check still reads the flag"


# ------------------------------------------------------------------ an overlong housekeeping step


def _aged_file(path: Path, days: float) -> Path:
    when = time.time() - days * DAY
    os.utime(path, (when, when), follow_symlinks=False)
    return path


def test_an_overlong_housekeeping_step_is_stopped_inside_it_so_the_runtime_closes_and_the_timeline_drains(
        tmp_path, monkeypatch):
    """R9-A3b-F-04-SHUTDOWN. A pass is ageing a reports folder whose walk would take tens of
    seconds (every look at an entry slowed), and shutdown comes. Round 10 read the stop only
    between steps: the step ran on past the deadline, the runtime was left open and shutdown
    ended with the housekeeping still going. Now the walk ends at the next entry: the pass
    finishes at once, the runtime is closed after it, and the timeline's accepted events — held
    by a slow writer — are on disk before shutdown returns. What the walk had not reached is still
    there for the next pass, the fresh report is untouched, and nothing is left half moved."""
    from app import main as main_module

    _no_provider(monkeypatch)
    monkeypatch.setattr(main_module, "SHUTDOWN_WAIT_S", 0.2)
    monkeypatch.setattr(main_module, "SHUTDOWN_DEADLINE_S", 3.0)
    monkeypatch.setattr(main_module, "SHUTDOWN_CLOSE_BY_S", 4.0)
    monkeypatch.setattr(main_module, "SHUTDOWN_EXIT_BY_S", 10.0)
    monkeypatch.setattr(main_module, "SHUTDOWN_FLUSH_S", 6.0)
    monkeypatch.setattr(main_module, "HOUSEKEEPING_S", 0.2)

    reports = tmp_path / "big-reports"
    reports.mkdir(mode=0o700)
    aged = [_aged_file(write_private_text(reports / f"ts-20260101-{n:06d}-walk.md", "old"), 120) for n in range(300)]
    fresh = write_private_text(reports / "ts-20260927-000000-today.md", "today's report")
    walking = threading.Event()
    real_lstat = os.lstat

    def slow_lstat(path, *args, **kwargs):
        if str(path).startswith(str(reports)):
            walking.set()
            time.sleep(0.05)       # 300 entries, two looks each: a walk of thirty seconds
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(session_module.os, "lstat", slow_lstat)
    keeping = TestSessions(tmp_path / "keeping", reports_dir=reports)

    store = TestSessions(tmp_path / "logs")
    line = Timeline(store)
    real_append = line._append
    monkeypatch.setattr(line, "_append", lambda path, lines: (time.sleep(1.0), real_append(path, lines))[1])
    session = store.start("shutdown mid-walk")
    order: list[str] = []
    took: list[float] = []

    async def boot():
        async with main_module.app.router.lifespan_context(main_module.app):
            runtime = main_module.app.state.runtime
            runtime.tests = keeping           # the timer's next pass walks the big folder

            async def aclose():
                order.append("runtime closed")

            runtime.aclose = aclose
            runtime.timeline = line
            timeline_module.install(line)
            for _ in range(1000):
                if walking.is_set() and any(not p.exists() for p in aged):
                    break
                await asyncio.sleep(0.01)
            assert walking.is_set() and any(not p.exists() for p in aged), "the pass is part way through the walk"
            for n in range(3):
                line.emit("turn_finished", n=n)
            took.append(time.monotonic())     # leaving the block is the shutdown

    try:
        asyncio.run(boot())
    finally:
        timeline_module.install(timeline_module.NullTimeline())
    took[0] = time.monotonic() - took[0]
    keeper = main_module.app.state.housekeeper
    assert order == ["runtime closed"], "closed after the pass, not left open under it"
    assert took[0] < 3.0 + 6.0, took
    assert "stopped early for shutdown" in keeper.last_problem, keeper.last_problem
    assert keeping.tidy_contained is False and "stopped early for shutdown" in keeping.tidy_problem
    assert count_events(store.timeline_path(session)) == 3, "every accepted event reached the file"
    left = [p for p in aged if p.exists()]
    assert 0 < len(left) < len(aged), "the walk began, and ended long before its end"
    assert fresh.read_text() == "today's report"
    assert not [p for p in reports.iterdir() if ".pruning-" in p.name], "nothing left half moved"


def test_a_stop_asked_of_a_walk_ends_it_before_the_next_entry_and_nothing_else_is_ever_stopped(tmp_path):
    """The stop is the housekeeping pass's alone: prune_reports called with no stop set (a command,
    a turn's own roll of the day) runs to its end, and with one set ends before its next entry."""
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    for n in range(5):
        _aged_file(write_private_text(reports / f"ts-20260101-{n:06d}-walk.md", "old"), 120)
    stop = threading.Event()
    stop.set()
    token = session_module.HOUSEKEEPING_STOP.set(stop)
    try:
        with pytest.raises(session_module.Interrupted):
            session_module.prune_reports(reports, 90)
    finally:
        session_module.HOUSEKEEPING_STOP.reset(token)
    assert len(list(reports.iterdir())) == 5, "stopped before the first entry"
    assert session_module.prune_reports(reports, 90) == 5, "with no stop set it runs to its end"


# ------------------------------------------------------------------ a connection held at a stop


async def test_a_connection_held_open_at_a_stop_no_longer_keeps_the_apps_shutdown_from_running(tmp_path, monkeypatch):
    """CFG-02, as far as a test can hold a connection: the real lifespan under a real uvicorn
    server with the graceful drain bounded, a request that never finishes, and the stop SIGINT
    asks for. The request is cancelled once the drain's time is up, and the lifespan's shutdown
    then runs: the runtime is closed and the event the held request emitted — pending behind a
    slow writer — is on disk before the server has finished."""
    import uvicorn
    from fastapi import FastAPI

    from app import main as main_module

    _no_provider(monkeypatch)
    store = TestSessions(tmp_path / "logs")
    line = Timeline(store)
    real_append = line._append
    monkeypatch.setattr(line, "_append", lambda path, lines: (time.sleep(2.0), real_append(path, lines))[1])
    session = store.start("held connection")
    held = asyncio.Event()
    closed: list[bool] = []
    app = FastAPI(lifespan=main_module.lifespan)

    @app.get("/hold")
    async def hold():
        line.emit("turn_started", turn_id="turn_held")
        held.set()
        await asyncio.sleep(3600)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, timeout_graceful_shutdown=1,
                                           lifespan="on", http="h11", ws="none", log_level="warning"))
    serving = asyncio.ensure_future(server.serve())
    try:
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        runtime = app.state.runtime

        async def aclose():
            closed.append(True)

        runtime.aclose = aclose
        runtime.timeline = line
        port = server.servers[0].sockets[0].getsockname()[1]
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /hold HTTP/1.1\r\nHost: t\r\n\r\n")
        await writer.drain()
        await asyncio.wait_for(held.wait(), 10)
        began = time.monotonic()
        server.should_exit = True             # what uvicorn's SIGINT handler does
        await asyncio.wait_for(asyncio.shield(serving), 20)
        took = time.monotonic() - began
        writer.close()
    finally:
        if not serving.done():
            server.force_exit = True
            await asyncio.wait_for(serving, 10)
    assert closed == [True], "the lifespan's shutdown ran, held connection and all"
    assert count_events(store.timeline_path(session)) == 1, "the held request's event was drained"
    assert took < 1 + 8, took


# ------------------------------------------------------------------ O1 F-01: the writer lock


def test_an_event_emitted_while_a_command_holds_the_writer_lock_never_lands_in_a_count_it_called_final(
        tmp_path, monkeypatch):
    """O1 F-01 / R9-A3b-F-10, the interleaving itself. A backend that has not written yet looks up
    its session (cached: running), meets the command's exclusive hold, and — in round 10 — took the
    event anyway, for its writer to write once it had the lock. The command, having stopped the
    session on disk and waited its RECHECK_S, let go, found no writer (the writer thread had not
    been scheduled yet), called the file's count final, and the event then landed in it.

    Now nothing is accepted before the hold is taken, and the session is looked up again once it
    is: whichever way the race after the command lets go runs, a count the command calls final is
    the file's last."""
    import fcntl

    clock = Clock(1_790_000_000.0)
    command = TestSessions(tmp_path, clock=clock)
    session = command.start("walk")
    backend = TestSessions(tmp_path, clock=clock)
    line = Timeline(backend, clock=clock)
    assert line.own is not None, "the backend has the session running, cached"
    real_flock = fcntl.flock
    met = threading.Event()

    def flock(fd, operation):
        if operation & fcntl.LOCK_SH and operation & fcntl.LOCK_NB:
            try:
                return real_flock(fd, operation)
            except BlockingIOError:
                met.set()
                raise
        if operation & fcntl.LOCK_SH:
            time.sleep(0.3)       # a writer thread that is not scheduled at once
        return real_flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", flock)
    monkeypatch.setattr(timeline_module, "WRITER_LOCK_WAIT_S", 10.0, raising=False)
    command.stop()
    fd = os.open(command.root / WRITER_LOCK, os.O_RDONLY | os.O_CREAT, 0o600)
    real_flock(fd, fcntl.LOCK_EX)
    got: dict = {}
    emitter = threading.Thread(target=lambda: got.setdefault("event", line.emit("turn_finished", n=1)))
    emitter.start()
    try:
        assert met.wait(5), "the backend met the command's hold"
        clock.now += RECHECK_S + 0.2          # no_backend_verdict's wait after its stop
    finally:
        real_flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    alive = writer_alive(command.root)
    counted = count_events(command.timeline_path(session))
    emitter.join(10)
    assert not emitter.is_alive()
    assert line.flush(timeout_s=5)
    assert got["event"] is None, "an event for a session the command had stopped is not taken"
    if alive is False:
        assert count_events(command.timeline_path(session)) == counted, "nothing landed in a count called final"
    assert line.counts["pending"] == 0


def test_a_command_holding_the_writer_lock_too_long_costs_one_bounded_wait_and_no_accepted_event(tmp_path, monkeypatch):
    """No event is accepted without the hold, and a command stuck holding the lock costs the turn's
    path one wait of WRITER_LOCK_WAIT_S, not one per event."""
    import fcntl

    monkeypatch.setattr(timeline_module, "WRITER_LOCK_WAIT_S", 0.1)
    monkeypatch.setattr(timeline_module, "WRITER_LOCK_BACKOFF_S", 0.4)
    store = TestSessions(tmp_path)
    session = store.start("stuck command")
    line = Timeline(store)
    fd = os.open(store.root / WRITER_LOCK, os.O_RDONLY | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        began = time.monotonic()
        assert line.emit("turn_started") is None
        first = time.monotonic() - began
        began = time.monotonic()
        assert line.emit("turn_started") is None
        second = time.monotonic() - began
        assert first >= 0.1 and second < 0.05, (first, second)
        assert line.counts["pending"] == 0 and line.counts["dropped"] == 2
        assert writer_alive(store.root) is True, "the command's own hold, not a writer's"
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert writer_alive(store.root) is False, "nothing of the backend's holds it"
    time.sleep(0.45)
    assert line.emit("turn_started") is not None and line.flush(timeout_s=5)
    assert count_events(store.timeline_path(session)) == 1 and writer_alive(store.root) is True


# ------------------------------------------------------------------ R9-A3b-F-04-STARTUP


def _boot_with_reports(monkeypatch, reports: Path) -> list[bool]:
    from app import main as main_module
    from config.settings import get_settings

    _no_provider(monkeypatch)
    monkeypatch.setattr(main_module, "REPORT_CHECK_DELAY_S", 0.01)
    monkeypatch.setenv("CROOKS_REPORTS_DIR", str(reports))
    get_settings.cache_clear()
    served: list[bool] = []

    async def boot():
        async with main_module.app.router.lifespan_context(main_module.app):
            served.append(True)

    with pytest.raises(RuntimeError, match="will not start with reports it cannot keep private"):
        asyncio.run(boot())
    return served


def test_start_up_refuses_with_a_link_among_the_reports(tmp_path, monkeypatch):
    """A report that is a link to a file readable elsewhere: its own mode says nothing of that, so
    privacy cannot be established, and the real start-up refuses before it answers anything. The
    link is neither followed nor moved."""
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    elsewhere = tmp_path / "web" / "exposed.md"
    elsewhere.parent.mkdir()
    elsewhere.write_text("the owner's words, readable from the web folder")
    os.chmod(elsewhere, 0o644)
    os.symlink(elsewhere, reports / "ts-20260927-000000-walk.md")
    assert _boot_with_reports(monkeypatch, reports) == [], "it never answered anything"
    assert (reports / "ts-20260927-000000-walk.md").is_symlink() and elsewhere.stat().st_mode & 0o777 == 0o644


def test_start_up_refuses_with_a_reports_folder_that_is_a_link(tmp_path, monkeypatch):
    real = tmp_path / "real-reports"
    real.mkdir(mode=0o700)
    linked = tmp_path / "reports"
    os.symlink(real, linked)
    assert _boot_with_reports(monkeypatch, linked) == []


def test_start_up_refuses_with_a_reports_folder_another_user_owns(tmp_path, monkeypatch):
    """A 0700 folder another user owns is theirs to open (and to chmod): not private to the
    service, whatever its mode, and the real start-up refuses."""
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    write_private_text(reports / "ts-20260927-000000-walk.md", "the owner's words")
    real = os.lstat

    class Theirs:
        def __init__(self, st):
            self._st = st

        def __getattr__(self, name):
            return os.geteuid() + 1 if name == "st_uid" else getattr(self._st, name)

    def lstat(path, *args, **kwargs):
        answer = real(path, *args, **kwargs)
        return Theirs(answer) if Path(path) == reports else answer

    monkeypatch.setattr(session_module.os, "lstat", lstat)
    assert _boot_with_reports(monkeypatch, reports) == []


# ------------------------------------------------------------------ R9-A3a-A3a-LIVE-CLEAN


def test_the_live_gap_records_shape_comes_through_the_real_start_up_byte_for_byte(tmp_path, monkeypatch):
    """The shape the deploy's own check read on the live record (round 10, Termius 1.6/1.6b):
    version 1, ten gap rows under cleaned keys — two with names — no builds, no misjudged rows,
    seeded, and exactly one copy already kept beside it from round 9's first clean. Through the
    real start-up (the runtime's install and seed, then shutdown): the file is the same bytes,
    every row and field is there, and there is still exactly one copy."""
    from app import main as main_module
    from app.objectives import gaps as gaps_module
    from config.settings import get_settings
    from tests.rollback import gaps_3e77f215 as rollback

    keys = ["concept multiple users member accounts invite", "custom line name on an order",
            "display tool project expanded view onto", "log manual physically done state task",
            "mac read only shopify gmail writes", "order name lookup on order open order add name",
            "tool exposes draft order's invoice checkout", "tool set custom line name price",
            "visibility into how machine's access networking", "web research tool look up trend"]
    gaps = {}
    for i, key in enumerate(keys):
        at = f"2026-09-2{6 + i % 2}T1{i}:00:00+00:00"
        row = {"label": f"Stand-in label {i}", "hits": 1 + i, "sources": {"blocker": 1 + i},
               "objectives": [f"obj_{i:08x}"], "requests": [], "seen": [at], "first_seen": at, "last_seen": at}
        if i in (1, 7):
            row["name"] = f"Stand-in name {i}"
        gaps[key] = row
    record = {"version": 1, "gaps": gaps, "builds": {}, "misjudged": {}, "seeded": "2026-09-27T01:07:06+00:00"}
    objectives = tmp_path / "objectives"
    objectives.mkdir(mode=0o700)
    path = objectives / "gaps.json"
    raw = json.dumps(record, indent=2, ensure_ascii=False).encode()
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    kept = objectives / "gaps.json.20260927T211850Z.before-clean"
    kept.write_bytes(b'{"version": 1, "gaps": {}}')
    os.chmod(kept, 0o600)
    stamp = path.stat().st_mtime_ns

    _no_provider(monkeypatch)
    monkeypatch.setenv("CROOKS_OBJECTIVES_DIR", str(objectives))
    get_settings.cache_clear()
    monkeypatch.setattr(gaps_module, "_LEDGER", None)

    async def boot():
        async with main_module.app.router.lifespan_context(main_module.app):
            pass

    asyncio.run(boot())
    assert path.read_bytes() == raw and path.stat().st_mtime_ns == stamp, "not rewritten"
    assert sorted(p.name for p in objectives.glob("gaps.json.*")) == [kept.name], "no second copy"
    assert gaps_module.GapLedger(path).load() == record, "every row and every field, as it was"
    assert len(rollback.GapLedger(path).load()["gaps"]) == 10, "and the rollback code reads all ten"


# ------------------------------------------------------------------ R9-E-families1-E-05

# Modules deleted with the fast lane and the word-matching families (commit 4411adde, 28 September
# 2026). Nothing may import them, name them in code, or load them.
DELETED = (
    "app.fastpath", "app.capabilities.ask", "app.capabilities.screen", "app.capabilities.ui_intent",
    "app.families.navigation_extras", "app.families.order_email", "app.families.owner_feedback",
    "app.families.query_language", "app.families.self_knowledge", "app.families.ui_intent",
    "app.speech.normalise", "scripts.bench_lanes",
)
OURS = ("app", "scripts", "config", "experience")


def _modules() -> list[tuple[str, Path]]:
    out = []
    for base in ("app", "scripts", "config"):
        for path in sorted((ROOT / base).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            parts = path.relative_to(ROOT).with_suffix("").parts
            name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            out.append((name, path))
    return out


def _deleted(name: str) -> bool:
    return any(name == gone or name.startswith(gone + ".") for gone in DELETED)


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def import_check() -> dict:
    """The check itself, run by the test below in an interpreter of its own (importing every script
    changes sys.path and the like for whatever runs after it, so it never runs in the test's)."""
    failed, dangling, named = [], [], []
    modules = _modules()
    for name, _path in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - collected and said below
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
    for name, path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        package = name.split(".") if path.name == "__init__.py" else name.split(".")[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] not in OURS:
                        continue
                    if _deleted(alias.name):
                        named.append(f"{path.name}:{node.lineno} imports {alias.name}")
                    elif importlib.util.find_spec(alias.name) is None:
                        dangling.append(f"{path.name}:{node.lineno} {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                base = package[: len(package) - (node.level - 1)] if node.level else []
                module = ".".join([*base, *([node.module] if node.module else [])]) if node.level else (node.module or "")
                if module.split(".")[0] not in OURS:
                    continue
                if _deleted(module):
                    named.append(f"{path.name}:{node.lineno} imports from {module}")
                    continue
                try:
                    loaded = importlib.import_module(module)
                except Exception as exc:  # noqa: BLE001
                    dangling.append(f"{path.name}:{node.lineno} {module} ({type(exc).__name__})")
                    continue
                for alias in node.names:
                    target = f"{module}.{alias.name}"
                    if alias.name == "*":
                        continue
                    if _deleted(target):
                        named.append(f"{path.name}:{node.lineno} imports {target}")
                    elif not hasattr(loaded, alias.name) and importlib.util.find_spec(target) is None:
                        dangling.append(f"{path.name}:{node.lineno} {target}")
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                for gone in DELETED:
                    if re.search(rf"(?<![\w.]){re.escape(gone)}(?![\w])|(?<![\w/]){re.escape(gone.replace('.', '/'))}\b",
                                 node.value):
                        named.append(f"{path.name}:{node.lineno} names {gone}")
    from app import families

    listed = sorted(m.name for m in pkgutil.iter_modules(families.__path__) if not m.name.startswith("_"))
    return {"modules": len(modules), "failed": failed, "dangling": dangling, "named": named,
            "families_listed": listed, "families_loaded": families.load_all()}


def test_every_module_imports_and_every_import_in_them_resolves_and_nothing_names_a_deleted_one():
    """R9-E-families1-E-05, executable over the whole tree under the test configuration, in a fresh
    interpreter: every module under app/, scripts/ and config/ is imported; every `import` and
    `from … import` in them — the lazy ones inside functions, which importing a module never runs,
    included — names a module that exists and a name it has; no import, and no string in the code
    (docstrings and comments are history, not references), names a module deleted with the fast
    lane; and every family module loads (load_all logs a family that fails and carries on, so
    only this comparison would show one missing)."""
    import subprocess
    import sys

    ran = subprocess.run(
        [sys.executable, "-c", "import json, sys; sys.path.insert(0, '.'); "
                               "from tests.test_r11_records import import_check; print(json.dumps(import_check()))"],
        cwd=ROOT, env=dict(os.environ), capture_output=True, text=True, timeout=600)
    assert ran.returncode == 0, ran.stderr[-2000:]
    found = json.loads(ran.stdout.strip().splitlines()[-1])
    assert found["failed"] == [], found["failed"]
    assert found["dangling"] == [], found["dangling"]
    assert found["named"] == [], found["named"]
    assert found["modules"] > 200, "the whole tree was walked"
    assert found["families_loaded"] == found["families_listed"], "every family module loaded"
    assert not [m for m in found["families_listed"] if _deleted(f"app.families.{m}")]


def test_every_capability_and_every_change_the_report_names_is_one_this_build_has():
    """The symbol half of E-05 beyond imports: the capability table names only tools the registry
    has, and every change the report sets against a family (semantics.CHANGES) names a family the
    table has — so no family the fast lane took with it is still reported as live."""
    from app.capabilities import families as capability_families
    from app.families import load_all
    from app.observability import semantics
    from app.tools import (  # noqa: F401 - imported for the tools they register
        analytics_tools,
        batch_tools,
        gmail_tools,
        gmail_writes,
        shopify_tools,
        shopify_writes,
    )
    from app.tools.registry import all_specs

    load_all()
    tools = {spec.name for spec in all_specs()}
    missing = {family.key: [t for t in family.tools if t not in tools]
               for family in capability_families.all_families() if any(t not in tools for t in family.tools)}
    assert missing == {}, missing
    unknown = [c.key for c in semantics.CHANGES if c.capability and capability_families.get(c.capability) is None]
    assert unknown == [], unknown
