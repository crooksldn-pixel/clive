"""FastAPI application.

Bound to loopback and served to the tablet by `tailscale serve`, which supplies the trusted
HTTPS origin that getUserMedia and speechSynthesis both require. Binding 0.0.0.0 and using the
LAN IP looks like it works and then fails on the browser API that actually matters.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import mimetypes
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from app import runtime as runtime_module
from app.logging.quiet import quieten
from app.logging.turnlog import RedactingFilter
from app.observability.session import HOUSEKEEPING_STOP
from app.providers.max_agent_sdk import BillingGuardError, assert_no_payg_credentials
from app.routes import (
    actions,
    admin,
    batches,
    branches,
    command,
    connections,
    context,
    displays,
    environment,
    health,
    media,
    objectives,
    observe,
    speak,
    support,
    today,
    turn,
    voice,
)
from app.routes import bench as bench_route  # [bench] the test bench's screen (owner only)
from app.routes import hooks as hooks_route
from app.routes import returns as returns_route
from config.settings import get_settings

log = logging.getLogger("crooks")


def configure_logging(log_dir: Path) -> None:
    """Every log line — stdout and file — passes through the redaction filter, and the file
    rotates. Under a supervisor stdout goes to a file that would otherwise grow forever."""
    from logging.handlers import RotatingFileHandler

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-22s %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if getattr(root, "_crooks_configured", False):
        return
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    stream.addFilter(RedactingFilter())
    root.addHandler(stream)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(log_dir / "assistant.log", maxBytes=5_000_000, backupCount=5)
        rotating.setFormatter(fmt)
        rotating.addFilter(RedactingFilter())
        root.addHandler(rotating)
    except OSError as exc:
        log.warning("file logging disabled: %s", exc)
    quieten()
    root._crooks_configured = True  # type: ignore[attr-defined]

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The billing guard is the one startup failure that must stop the process outright. A
    # missing token can be fixed while the backend keeps serving /health; a present API key
    # cannot be allowed to serve a single turn.
    assert_no_payg_credentials()
    # This process is the service: the one that may let a key stored at the server prompt take over
    # from the app tier, once it has loaded it (app/secrets/vault.py, before any secret is read).
    from app.secrets import vault

    vault.serving()
    settings = get_settings()
    configure_logging(settings.log_dir)
    app.state.runtime = runtime_module.build(settings)
    app.state.health_cache = None   # /health answers from a recent result; none yet
    app.state.health_lock = None
    # The same list the write boundary reads, so the two can never disagree.
    app.state.allowed_logins = app.state.runtime.allowed_logins
    try:
        await app.state.runtime.provider.start()
    except BillingGuardError:
        raise
    except Exception as exc:  # noqa: BLE001
        # A missing Claude token must not stop the backend booting: /health then names the
        # problem, and each /turn retries start() so fixing it needs no restart.
        log.error("Claude provider did not start: %s", exc)
    app.state.runtime.warm_orders_soon()
    # The key the server's own `make test-session-*` commands carry (app/local_cli.py): made once
    # and kept, so they work with the production switches without widening anything else.
    from app import local_cli

    await asyncio.to_thread(local_cli.ensure_key)
    # One pass before the first request is answered (the 2026-09-27 deploy review, F-04): a
    # restart never leaves the day's roll, the ages, the report permissions or a screen's old
    # slip waiting for the timer, and then the timer keeps them. What that pass could not put
    # right is logged as an error and shown on /health (checks.housekeeping).
    keeper = app.state.housekeeper = Housekeeper(app.state.runtime)
    await keeper.first_pass()
    # Fail closed (round 7, F-04-STARTUP): a report left readable by others, or one that could
    # not even be checked, stops the service here, before it answers anything. Nothing is
    # deleted to get past it; the owner puts the permissions right and starts it again. Only a
    # check that ran to its end and found everything private lets it start (round 8): one that
    # never ran is run here, and one that failed is tried again a few times first, so a passing
    # hiccup does not keep the service down.
    tests = getattr(app.state.runtime, "tests", None)
    if tests is not None and not await _reports_contained(tests):
        problem = getattr(tests, "tidy_problem", "") or "the reports could not be confirmed private"
        log.error("refusing to start: %s", problem)
        await app.state.runtime.aclose()
        await drain_timelines(app.state.runtime, timeout_s=SHUTDOWN_FLUSH_S)
        raise RuntimeError(f"CROOKS will not start with reports it cannot keep private: {problem}")
    keeper.start()
    log.info("CROOKS Assistant ready (bind address is whatever uvicorn was started with)")
    yield
    # Reached once uvicorn's graceful drain has ended, SHUTDOWN_GRACEFUL_S at the most (the budget
    # is set out above SHUTDOWN_WAIT_S). Nothing new is scheduled, a pass already running is asked
    # to stop — and ends at the next file it comes to, not only at its next step (round 11) — and
    # it finishes before the runtime it works on is closed (round 6, F-04; round 8,
    # F-04-SHUTDOWN). The wait is SHUTDOWN_WAIT_S, then on to SHUTDOWN_DEADLINE_S: a pass that
    # ends by then has the runtime closed after it. One still running at the deadline — only a
    # single filesystem call that has not returned can be, now — keeps its runtime open (round 7:
    # never closed under it), and the process exits without waiting on it, because the pass runs
    # in a daemon thread of its own.
    #
    # Either way, and last, what the timeline has accepted is written before the process exits
    # (round 9, F-04-SHUTDOWN): its writer is a daemon thread too, and neither the runtime's close
    # nor a pass left running flushed it, so events it had taken were lost with the process. The
    # timeline writes on a thread and a file of its own and shares nothing with a pass, so it is
    # drained even when the runtime is left open; bounded by what is left of the unit's time.
    import time

    began = time.monotonic()
    if await keeper.stop(timeout_s=SHUTDOWN_WAIT_S, deadline_s=SHUTDOWN_DEADLINE_S):
        # A pass that ended just before the deadline leaves the close what is left before the
        # unit's own: given up there and said, rather than cut off by SIGKILL mid-close.
        left = max(1.0, SHUTDOWN_CLOSE_BY_S - (time.monotonic() - began))
        try:
            await asyncio.wait_for(app.state.runtime.aclose(), timeout=left)
        except TimeoutError:
            log.error("shutdown: closing the runtime did not finish in %.1fs; exiting with it part-closed", left)
    else:
        log.error("shutdown: a housekeeping pass was still running at the %ss deadline; the runtime is left "
                  "open rather than closed under it", SHUTDOWN_DEADLINE_S)
    left = min(SHUTDOWN_FLUSH_S, max(SHUTDOWN_FLUSH_MIN_S, SHUTDOWN_EXIT_BY_S - (time.monotonic() - began)))
    await drain_timelines(app.state.runtime, timeout_s=left)


async def drain_timelines(runtime, *, timeout_s: float) -> bool:
    """Wait, at most `timeout_s` in all, until every event the process's timelines have accepted
    is on disk or counted dropped: the runtime's own, the one installed for the process, and the
    recording each carries as its mirror (round 9, F-04-SHUTDOWN). True when all of them settled;
    when not, says so, with the count still pending, since that count is then lost with the
    process. Never raises."""
    import time

    from app.observability import timeline as timeline_module

    found: list = []
    for start in (getattr(runtime, "timeline", None), timeline_module.current()):
        held = start
        while held is not None and all(held is not other for other in found):
            found.append(held)
            held = getattr(held, "mirror", None)
    deadline = time.monotonic() + max(0.0, timeout_s)
    settled = True
    for held in found:
        flush = getattr(held, "flush", None)
        if flush is None:
            continue
        left = max(0.0, deadline - time.monotonic())
        try:
            ok = bool(await _in_own_thread(lambda flush=flush, left=left: flush(timeout_s=left)))
        except Exception:  # noqa: BLE001 - shutting down: said, never raised
            ok = False
        if not ok:
            settled = False
            pending = getattr(held, "_pending", "?")
            log.error("shutdown: %s timeline event(s) were still being written when the process exited", pending)
    return settled


# How often test mode's records are aged and tightened with nobody using the service (the
# 2026-09-26 deploy review, F-04): the day's roll, the sessions past their keep and the reports
# drawn from them happen on a clock, not only when the next event asks.
HOUSEKEEPING_S = 15 * 60
# The whole stop, planned inside systemd's TimeoutStopSec (round 11, R9-A3b-F-04-SHUTDOWN and
# CFG-02). deploy/systemd/crooks-assistant.service sends SIGINT and gives UNIT_STOP_S before SIGKILL
# — the 30 s it has always given, which `make restart`'s stop (scripts/service_linux.py) waits
# on too:
#
#   uvicorn notices the signal   at its next tick and pauses once before the drain,
#                                SHUTDOWN_UVICORN_TICKS_S together (0.1 s each, uvicorn/server.py)
#   uvicorn's graceful drain     SHUTDOWN_GRACEFUL_S (--timeout-graceful-shutdown in ExecStart). A
#                                connection held open used to keep the lifespan's shutdown from
#                                starting at all until SIGKILL; now requests still running then are
#                                cancelled, and the lifespan below starts.
#   then the lifespan, timed from its own start:
#     housekeeping stops         asked at once, and ended within one filesystem call of it (the
#                                walks read the stop before each entry); waited for
#                                SHUTDOWN_WAIT_S, then on to SHUTDOWN_DEADLINE_S
#     the runtime closes         until SHUTDOWN_CLOSE_BY_S at the latest (given 1 s at least)
#     the timeline drains        until SHUTDOWN_EXIT_BY_S (at most SHUTDOWN_FLUSH_S, at least
#                                SHUTDOWN_FLUSH_MIN_S), on the normal path and the timed-out one alike
#
# The lifespan therefore ends by SHUTDOWN_EXIT_BY_S at the latest, and the whole stop by
# 0.2 + 10 + 13 = 23.2 s, leaving SHUTDOWN_EXIT_MARGIN_S and more (6.8 s) of the unit's 30 for the
# interpreter to exit. tests/test_r11_records.py holds the unit's two lines to these numbers and
# the sum to the margin.
UNIT_STOP_S = 30
SHUTDOWN_UVICORN_TICKS_S = 0.2
SHUTDOWN_GRACEFUL_S = 10
SHUTDOWN_WAIT_S = 2.0
SHUTDOWN_DEADLINE_S = 5.0
SHUTDOWN_CLOSE_BY_S = 9.0
SHUTDOWN_FLUSH_S = 4.0
SHUTDOWN_FLUSH_MIN_S = 0.5
SHUTDOWN_EXIT_BY_S = 13.0
# What the interpreter is left, at least, between the lifespan's end and SIGKILL.
SHUTDOWN_EXIT_MARGIN_S = 5.0
# How many times start-up checks the reports before it refuses, and how far apart (round 8,
# F-04-STARTUP): the first pass is the first of them.
REPORT_CHECK_ATTEMPTS = 3
REPORT_CHECK_DELAY_S = 0.5

# The stop asked of the housekeeping pass running in this thread (Housekeeper.run_pass sets it),
# read by housekeep_once between its steps and, being the session module's own, by every walk
# inside them (round 11). A context variable, so a pass called directly (a test, a script) has
# none and is never stopped.
_PASS_STOP = HOUSEKEEPING_STOP


async def _reports_contained(tests) -> bool:
    """Whether a check of the reports ran to its end and found them private, trying up to
    REPORT_CHECK_ATTEMPTS in all, REPORT_CHECK_DELAY_S apart (round 8, F-04-STARTUP)."""
    if getattr(tests, "tidy_contained", None) is None:
        await asyncio.to_thread(tests.tidy_reports)   # the first pass did not get to it
    for attempt in range(2, REPORT_CHECK_ATTEMPTS + 1):
        if getattr(tests, "tidy_contained", None) is True:
            return True
        log.warning("reports not confirmed private (%s); checking again, %d of %d",
                    getattr(tests, "tidy_problem", "") or "no answer", attempt, REPORT_CHECK_ATTEMPTS)
        await asyncio.sleep(REPORT_CHECK_DELAY_S)
        await asyncio.to_thread(tests.tidy_reports)
    return getattr(tests, "tidy_contained", None) is True


def housekeep_once(runtime, *, stop: threading.Event | None = None) -> str:
    """One pass: let the always-on session roll if the day has turned, age the sessions and the
    reports and make the reports private, and take down whatever a screen has shown too long.
    Never raises: what it could not do is returned, in words that name no file ('' when it did
    everything).

    Each step is tried on its own (round 8, F-04-STARTUP): the report check used to share one
    `try` with the roll and the ages, so an active session record that would not parse skipped
    it, and start-up read the unchecked reports as private. Now it runs whatever happened before
    it, and a check that raises is not a contained one.

    Asked to stop — shutdown — the pass ends and says so (round 8, F-04-SHUTDOWN). Not only
    between steps now but inside them (round 11, R9-A3b-F-04-SHUTDOWN): the stop is set for the
    whole pass in session.HOUSEKEEPING_STOP, which every walk over the sessions and the reports
    reads before each entry, so one step over a big folder ends within a single filesystem call
    rather than running on past the unit's deadline. The screens' sweep is one lock and one small
    file, and is not begun once a stop is asked."""
    stop = stop if stop is not None else _PASS_STOP.get()
    token = _PASS_STOP.set(stop)
    try:
        return _housekeep(runtime, stop)
    finally:
        _PASS_STOP.reset(token)


def _housekeep(runtime, stop: threading.Event | None) -> str:
    from app.observability.session import Interrupted

    problems: list[str] = []
    stopped = "housekeeping stopped early for shutdown"

    def stopping() -> bool:
        if stop is not None and stop.is_set():
            problems.append(stopped)
            return True
        return False

    tests = getattr(runtime, "tests", None)
    if tests is not None:
        for what, step in (("the day's roll", "active"), ("the session ages", "prune")):
            try:
                getattr(tests, step)()
            except Interrupted:
                problems.append(stopped)
                return "; ".join(problems)
            except Exception as exc:  # noqa: BLE001 - housekeeping never takes the service down
                log.warning("test-mode housekeeping: %s did not complete", what, exc_info=True)
                problems.append(f"{what} did not complete ({type(exc).__name__})")
            if stopping():
                return "; ".join(problems)
        try:
            tests.tidy_reports()
            if getattr(tests, "tidy_problem", ""):
                problems.append(tests.tidy_problem)
        except Interrupted:
            try:
                tests.tidy_contained = False   # a check stopped part way is not a clean one
            except Exception:  # noqa: BLE001
                pass
            problems.append(stopped)
            return "; ".join(problems)
        except Exception as exc:  # noqa: BLE001
            try:
                tests.tidy_contained = False   # a check that raised is not a clean one
            except Exception:  # noqa: BLE001
                pass
            log.warning("the report check did not complete", exc_info=True)
            problems.append(f"the report check did not complete ({type(exc).__name__})")
        if stopping():
            return "; ".join(problems)
    try:
        from app.displays.store import store as displays

        left = displays().sweep()
        if left:
            problems.append(left)
    except Exception as exc:  # noqa: BLE001
        log.warning("screens housekeeping did not complete", exc_info=True)
        problems.append(f"screens housekeeping did not complete ({type(exc).__name__})")
    return "; ".join(problems)


async def _in_own_thread(fn):
    """fn() in a daemon thread of its own, awaited (round 8, F-04-SHUTDOWN). asyncio.to_thread
    would use the loop's default executor, whose threads the process waits for as it exits (the
    event loop's close waits up to five minutes, the interpreter's exit for ever): a pass stuck
    past the shutdown deadline would then hold the process until systemd killed it anyway.
    Cancelling the await does not stop the thread; Housekeeper holds a lock for its length."""
    loop = asyncio.get_running_loop()
    done = loop.create_future()
    context = contextvars.copy_context()

    def settle(ok: bool, value) -> None:
        if not done.done():
            if ok:
                done.set_result(value)
            else:
                done.set_exception(value)

    def target() -> None:
        try:
            value, ok = context.run(fn), True
        except BaseException as exc:  # noqa: BLE001 - handed to whoever awaits it
            value, ok = exc, False
        try:
            loop.call_soon_threadsafe(settle, ok, value)
        except RuntimeError:
            pass   # the loop has closed: nobody is waiting any more

    threading.Thread(target=target, name="crooks-housekeeping", daemon=True).start()
    return await done


class Housekeeper:
    """The housekeeping timer, supervised (the 2026-09-27 deploy review, round 6, F-04).

    One pass runs before the service answers anything, then one every HOUSEKEEPING_S. If the
    timer ends for any reason but a shutdown — a pass that raised, a cancellation nobody asked
    for — it is started again, and the restart is counted and shown. A pass runs in a thread
    holding `_running` for its whole length, so shutdown can stop scheduling and then wait for a
    pass already under way to finish before the runtime is closed under it. Shutdown also sets
    `_stop`, which the pass reads between its steps (round 8, F-04-SHUTDOWN), so a long pass ends
    at its next step rather than running on to the unit's kill. /health reads check(): whether a
    pass has run lately and whether the last one left anything undone. Since round 11 the same
    stop is read inside the steps too, before each entry of every walk over the sessions and the
    reports (session.HOUSEKEEPING_STOP), so a pass asked to stop ends within one filesystem call."""

    def __init__(self, runtime, *, interval_s: float | None = None, pass_fn=None) -> None:
        self.runtime = runtime
        self.interval_s = float(HOUSEKEEPING_S if interval_s is None else interval_s)
        self._fn = pass_fn
        self._running = threading.Lock()
        self._stopping = False
        self._stop = threading.Event()
        self._task: asyncio.Task | None = None
        self.passes = 0
        self.restarts = 0
        self.last_at: float | None = None
        self.last_problem = ""
        self.last_stop = ""

    def run_pass(self) -> str:
        """One pass, in the calling thread. Nothing once shutdown has begun, and a pass under way
        is asked to stop, and ends at the next entry it comes to (housekeep_once reads `_stop`,
        and every walk inside it reads session.HOUSEKEEPING_STOP)."""
        import time

        with self._running:
            if self._stopping or self._stop.is_set():
                return ""
            fn = self._fn if self._fn is not None else housekeep_once
            token = _PASS_STOP.set(self._stop)
            try:
                problem = fn(self.runtime) or ""
            finally:
                _PASS_STOP.reset(token)
            self.passes += 1
            self.last_at = time.time()
            self.last_problem = str(problem)
            if problem:
                log.error("housekeeping left something undone: %s", problem)
            return self.last_problem

    async def first_pass(self) -> str:
        return await _in_own_thread(self.run_pass)

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop(), name="housekeeping")
        self._task.add_done_callback(self._ended)

    async def _loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(self.interval_s)
            if self._stopping:
                return
            await _in_own_thread(self.run_pass)

    def _ended(self, task: asyncio.Task) -> None:
        if self._stopping:
            return
        why = "cancelled" if task.cancelled() else type(task.exception()).__name__ if task.exception() else "returned"
        self.restarts += 1
        self.last_stop = why
        log.error("housekeeping timer stopped (%s); starting it again", why)
        try:
            self.start()
        except RuntimeError:   # the event loop itself is closing: nothing to restart on
            log.warning("housekeeping timer not restarted: no running event loop")

    async def stop(self, timeout_s: float = 60.0, deadline_s: float | None = None) -> bool:
        """Stop scheduling, ask a pass already running to stop at its next step, and wait for it:
        `timeout_s`, then, if it is still running, on to `deadline_s` from the start of the stop
        (round 8, F-04-SHUTDOWN: a pass that ended a moment after the first wait used to be
        treated as one that never would). True when none is left running."""
        import time

        began = time.monotonic()
        self._stopping = True
        self._stop.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - its own cancellation, or whatever ended it
                pass
        finished = await asyncio.to_thread(self._running.acquire, True, max(0.0, timeout_s - (time.monotonic() - began)))
        if not finished and deadline_s is not None and deadline_s > timeout_s:
            log.warning("a housekeeping pass was still running after %ss at shutdown; asked to stop, waiting "
                        "until %ss", timeout_s, deadline_s)
            left = max(0.0, deadline_s - (time.monotonic() - began))
            finished = await asyncio.to_thread(self._running.acquire, True, left)
        if finished:
            self._running.release()
        else:
            log.error("a housekeeping pass was still running after %ss at shutdown",
                      deadline_s if deadline_s is not None else timeout_s)
        return finished

    def check(self) -> dict:
        import time

        if self.last_at is None:
            return {"ok": False, "detail": "no housekeeping pass has completed"}
        age = time.time() - self.last_at
        late = age > 2 * self.interval_s + 60
        ok = not self.last_problem and not late
        if self.last_problem:
            detail = self.last_problem
        elif late:
            detail = f"no housekeeping pass for {int(age // 60)} minutes"
        else:
            detail = f"last pass {int(age)}s ago"
        detail += f" · {self.passes} pass(es)"
        if self.restarts:
            detail += f" · timer restarted {self.restarts} time(s), last because it was {self.last_stop}"
        return {"ok": ok, "detail": detail}


app = FastAPI(title="CROOKS Assistant", version="0.1.0", lifespan=lifespan)


def _wants_page(request: Request) -> bool:
    """A person opening a page in a browser, as against the app's own calls, which keep their JSON."""
    return request.method == "GET" and "text/html" in request.headers.get("accept", "")


def _not_let_in_page(login: str) -> HTMLResponse:
    """What someone sees on their phone when their login is not let in: who Tailscale says they are,
    and the one thing to do about it. It used to be a line of raw JSON (2 October)."""
    import html

    who = html.escape(login)
    body = f"""<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>CLIVE</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0b0d;color:#f2f2f5;
font:17px/1.45 -apple-system,BlinkMacSystemFont,system-ui,sans-serif;padding:24px}}main{{max-width:420px}}
h1{{font-size:24px;font-weight:600;margin:0 0 12px}}p{{margin:0 0 12px;color:#b8b8c0}}
code{{display:block;margin:4px 0 16px;padding:12px 14px;border-radius:12px;background:#1c1c21;color:#fff;
font:16px ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all;user-select:all}}</style></head>
<body><main><h1>You're not let in yet</h1>
<p>Tailscale says you are signed in as:</p><code>{who}</code>
<p>Ask George to add you on CLIVE's Team screen with exactly that login, then tap <b>Let them in</b>.
If he already has, he still needs to let you in.</p>
<p>Then come back to this page.</p></main></body></html>"""
    return HTMLResponse(content=body, status_code=403, headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def guard_and_freshness(request: Request, call_next):
    """Two small things every request passes through.

    Who may ask: `tailscale serve` tags every proxied request with the caller's login, and when
    CROOKS_ALLOWED_LOGINS names logins only those callers are answered at all. Beyond the public
    paths (liveness, /whoami, the page shells), every route is the owner's by the one rule
    (principal_verdict): his device, or the server itself only when CROOKS_LOCAL_OWNER says the
    server speaks for him. A request made on the server with that switch off gets the public
    paths and nothing else.

    What the tablet keeps: the page and its scripts are served with no-cache, so a page open
    for a week picks up a new build on its next load rather than in a fortnight.
    """
    # [messaging] The public doors for messages coming in, one per channel (app/routes/hooks.py
    # HOOK_PATHS, exact paths only): they skip everything below, because WeCom's and Meta's servers
    # are not on the tailnet, and they carry no authority of any kind, so no tool can run from them. The route checks the channel's
    # signature before anything else and answers anything unsigned or invalid with an empty 403.
    # Every other path is judged exactly as before (tests/test_hooks_door.py). The routed path, from
    # the ASGI scope, never request.url, which an older Starlette built from the Host header, so a
    # Host of "x/hooks/wecom#" could have made any route look like this one (review note 8, 8 Oct).
    if hooks_route.is_hook(hooks_route.routed_path(request)) and request.method in ("GET", "POST"):
        from app.tools import authority as hook_authority

        nobody = hook_authority.TOOL_AUTHORITY.set(None)
        try:
            return await call_next(request)
        finally:
            hook_authority.TOOL_AUTHORITY.reset(nobody)
    # A page from another site — another tailnet host, or anything the tablet's browser was
    # pointed at — must not be able to POST here with the tablet's own Tailscale identity.
    # Chrome names the relationship in Sec-Fetch-Site; an Origin that is neither this host nor
    # the forwarded one is refused too. Requests without either header (curl, scripts) pass.
    if request.method in _STATE_CHANGING and _cross_site(request):
        return JSONResponse(status_code=403, content={"error": "cross-site request refused"})
    allowed = getattr(request.app.state, "allowed_logins", ())
    login = request.headers.get("tailscale-user-login", "")
    # `tailscale serve` adds X-Forwarded-For to everything it proxies and a login only for
    # tailnet users: a proxied request with no login is Funnel or a tagged node, and is
    # refused whether or not an allow-list is set — nobody anonymous asks this assistant.
    # A request that carries the header and did not come through tailscaled is something on
    # the server pretending, and is refused before any route sees it (F-05B; the same decision
    # the write boundary and the owner-only rule read, app/routes/actions.py proxy_state).
    # A request with neither header was made on the server itself.
    from app.routes.actions import FORGED, TAILSCALE, proxy_state

    route, why = proxy_state(request)
    if route == FORGED:
        log.warning("refused a request that claimed to come through Tailscale and did not: %s (path=%s)",
                    why, request.url.path)
        return JSONResponse(status_code=403, content={"error": "not allowed", "who": "unverified proxy"})
    if route == TAILSCALE and not login:
        return JSONResponse(status_code=403, content={"error": "not allowed", "who": "unknown"})
    if allowed and login and login.lower() not in allowed:
        # A member of the team whose login the owner let in with his passkey is looked at further
        # below; any other login is turned away here, as before (app/people/door.py).
        from app.people import door as staff_door

        if not staff_door.staff_login(login):
            log.warning("refused a login that is neither the owner's nor let in for the team (path=%s)",
                        request.url.path)
            if _wants_page(request):
                return _not_let_in_page(login)
            return JSONResponse(status_code=403, content={"error": "not allowed", "who": login})
    # Everything that is not public is the owner's, by the one rule (principal_check): a turn and
    # every tool the model reaches through it, every command, record and card, the pad's heartbeat
    # and whatever route is added next (the 2026-09-27 deploy review, round 6: gating routers one
    # by one had left /turn, and so the model's whole tool surface, open to any caller on the
    # server). tests/test_proxy_identity.py walks every route the app serves to keep it so.
    # The one exception, and not an owner: the server's own test-session commands with their key
    # (app/local_cli.py, round 6 F-05A), on its own routes only (local_cli.ROUTES), straight to the
    # port. The key anywhere else — through the proxy, on another route — is refused outright
    # (round 7), even from a device that would pass the owner rule without it; and carrying the
    # header at all is carrying the key, an empty value included (round 8, F-05A).
    from app import local_cli
    from app.tools import authority as tool_authority

    if local_cli.presented(request) and not local_cli.admits(request):
        log.warning("refused a request carrying the local command key where it does not apply (path=%s)", request.url.path)
        return JSONResponse(status_code=403, content={
            "error": "not allowed", "who": "not the owner", "code": "local_key_misused",
            "detail": "The server's command key opens its own test-session commands, on the server, and nothing else."})
    granted = None
    if not is_public(request.url.path) and not local_cli.admits(request):
        from app.routes.actions import SPOKEN_REFUSALS, principal_verdict

        who, code, why = principal_verdict(request)
        staff_person, staff_login = "", ""
        if code == "not_authorised":
            # Not the owner: perhaps a member of the team, on their own phone, let in by the owner's
            # passkey, asking for one of the routes the team may use (app/people/door.py, staff.py).
            from app.people import door as staff_door
            from app.people import staff as staff_rules

            staff_person, staff_login, staff_why = staff_door.verdict(request)
            if staff_person and not staff_rules.route_allowed(request.method, request.url.path):
                staff_person, staff_why = "", "that is the owner's"
            if not staff_person and staff_why and staff_door.staff_login(request.headers.get("tailscale-user-login", "")):
                why = f"{why} ({staff_why})"
        if code and not staff_person:
            log.warning("refused a request that is not the owner's: %s — %s (path=%s)", code, why, request.url.path)
            # The write boundary's own codes and spoken lines, so the tablet says the same thing
            # whichever door refused it.
            return JSONResponse(status_code=403, content={
                "error": "not allowed", "who": "not the owner", "code": code, "detail": why,
                "spoken": SPOKEN_REFUSALS.get(code, "")})
        # The only places an authority is made for a request (app/tools/authority.py). Without one
        # no tool runs: public paths, the local command key and anything else get none.
        granted = tool_authority.for_staff(staff_person, staff_login) if staff_person else tool_authority.for_owner(who)
    stamped = tool_authority.TOOL_AUTHORITY.set(granted)
    try:
        response = await call_next(request)
    except BaseException:
        if granted is not None:
            granted.revoke()
        raise
    finally:
        tool_authority.TOOL_AUTHORITY.reset(stamped)
    if granted is not None:
        # Revoked once the answer has been sent, on the object itself, so a task this request
        # left running (a copy of this context) holds nothing from then on.
        response.body_iterator = _revoking(response.body_iterator, granted)
    path = request.url.path
    if path in ("/", "/sw.js", "/manifest.webmanifest") or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


async def _revoking(body, granted):
    try:
        async for chunk in body:
            yield chunk
    finally:
        granted.revoke()


_STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Answered for anyone who can reach the port, and nothing else is: liveness (the service manager,
# the watchdog and `make status` read /health on the server), "who am I" (what a device shows to
# be put on the allow-list), and the page shells and their static files (code, never data). The
# pad's routes are the owner's like everything else (the 2026-09-27 review, F-NEW-PAD).
PUBLIC_PATHS = frozenset({"/health", "/ping", "/whoami", "/", "/display", "/sw.js", "/manifest.webmanifest",
                          "/favicon.ico"})
PUBLIC_PREFIXES = ("/static/",)


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def _cross_site(request: Request) -> bool:
    site = request.headers.get("sec-fetch-site", "").strip().lower()
    if site in ("cross-site", "same-site"):
        return True
    origin = request.headers.get("origin", "").strip().lower()
    if not origin or origin == "null":
        return bool(origin)   # "null" is an opaque origin: a sandboxed or file: page. Refuse.
    origin_host = origin.split("://", 1)[-1].split("/", 1)[0]
    hosts = {
        request.headers.get("host", "").strip().lower(),
        request.headers.get("x-forwarded-host", "").strip().lower(),
    }
    return origin_host not in hosts


# The page files travel compressed: 140 KB of script and style is 40 KB over the tailnet.
# Audio is excluded by default (an MP3 does not shrink) and the shell's cache keeps whatever
# encoding it received. Never a secret in a compressed body, so no compression-oracle concern.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.include_router(health.router)
app.include_router(environment.router)
app.include_router(turn.router)
app.include_router(speak.router)
app.include_router(admin.router)
app.include_router(actions.router)
app.include_router(batches.router)
app.include_router(branches.router)
app.include_router(command.router)
app.include_router(context.router)
app.include_router(media.router)
app.include_router(observe.router)
app.include_router(support.router)
app.include_router(objectives.router)
app.include_router(displays.router)
app.include_router(voice.router)   # POST /voice/live: the live words' single-use key (owner only)
app.include_router(connections.router)   # the Connections screen: keys and sign-ins, each change with a passkey
app.include_router(today.router)   # the Today screen: the team's work list, and the owner's board
app.include_router(returns_route.router)   # CROOKS Returns: the home's count of returns that need the owner
app.include_router(bench_route.router)   # [bench] the test bench: runs, results and his ratings (owner only)
app.include_router(hooks_route.router)   # [messaging] the public doors for messages coming in (/hooks/wecom, whatsapp, instagram)

if WEB_DIR.exists():
    mimetypes.add_type("application/manifest+json", ".webmanifest")
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    async def index(request: Request) -> Response:
        # A member of the team works from the Today screen, not the owner's own (app/people): sent
        # there. Nothing is granted by this; the door judges /today as it judges every route.
        from app.people import door as staff_door

        if staff_door.staff_login(request.headers.get("tailscale-user-login", "")):
            return RedirectResponse("/today", status_code=303)
        # The page carries the build it was made for, so a shell opened from the worker's
        # cache can tell at its first health poll that the Mac has moved on.
        source = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        build = getattr(request.app.state.runtime, "build", "unknown")
        return Response(source.replace("__BUILD__", build), media_type="text/html; charset=utf-8")

    @app.get("/display", include_in_schema=False)
    async def display_page(request: Request) -> Response:
        # A screen of the owner's: it names itself and shows what CLIVE puts on it
        # (app/routes/displays.py). The page holds no data; everything it draws is asked for.
        # The build id tells the screen when CLIVE has been updated (it plays its whole start-up then).
        source = (WEB_DIR / "display.html").read_text(encoding="utf-8")
        build = getattr(request.app.state.runtime, "build", "unknown")
        return Response(source.replace("__BUILD__", build), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest() -> FileResponse:
        # At the root, like the worker, so the installed app's scope is the whole site.
        return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker(request: Request) -> Response:
        # Served from the root so its scope is the whole app, with the build id written in so
        # the file changes — and Chrome installs the new worker — whenever a page file does.
        source = (WEB_DIR / "sw.js").read_text(encoding="utf-8")
        build = getattr(request.app.state.runtime, "build", "unknown")
        return Response(
            source.replace("__BUILD__", build),
            media_type="text/javascript; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> FileResponse:
        # Desktop Chrome asks for this on every visit; the page's own icon answers it rather
        # than a 404 in the log each time.
        return FileResponse(WEB_DIR / "icon-192.png", media_type="image/png")
