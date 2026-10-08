"""The page in a real browser, against a real backend serving the golden world.

Everything else in this package drives the application through ASGI, which is the right way to
assert on what the backend produced. It cannot tell you whether a finger can hit the thing, or
whether the card fits an eight-inch screen, or whether the page threw on the way to drawing it.
Those need a browser and a socket.

So this starts uvicorn on loopback with the fixture clients bound, hands the address to
`scripts/browser/experience.js`, and collects what it reports. The backend is the real one and
the fixture world is the same one the scenarios use, so a card in a screenshot is a card the
scenarios asserted on.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from experience import gate_model

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "browser" / "experience.js"
# The physical tablet's own viewport, 601 x 889 at DPR 1.33: the checks the Phase 2 live test
# found on the device and the 800 x 1280 gate could not see. Run after the gate, folded into
# the same result, so one green means both sizes.
TABLET_SCRIPT = ROOT / "scripts" / "browser" / "tablet.js"
# And the action surface, driven to the state the owner physically watched get stuck: a
# commit whose answer never came back, over a change the Mac had already proved (D-1).
ACTION_SCRIPT = ROOT / "scripts" / "browser" / "action_state.js"
# `make accept` has driven this one against a real server since Phase 1. It was never in
# the gate the suite runs, so its 23 checks proved nothing between releases — and it was
# the only check anywhere that caught the duplicate `replaceCard` (Phase 4, D-1's
# neighbour): the verified card was simply never drawn. It runs with the rest now.
ACCEPT_SCRIPT = ROOT / "scripts" / "browser" / "accept.js"
# And the geometry, at both sizes. The live session of 11 September recorded `clipped=0` on
# every render while the owner was looking at overlapping text and controls: the telemetry was
# answering a narrower question than the one he was asking. This script asks his question —
# every rectangle on screen, read with getBoundingClientRect, against nineteen stress fixtures
# — so an overlap fails a gate here instead of being discovered in his hand.
COLLISION_SCRIPT = ROOT / "scripts" / "browser" / "collision.js"
# What the first viewport says, measured at the same size (§8, D-12). Its own script and its
# own test (tests/test_density.py) rather than a third block in the two above: the question it
# asks is about PIXELS, and a failure in it should name density and nothing else.
DENSITY_SCRIPT = ROOT / "scripts" / "browser" / "density.js"
# D-3, at both sizes in one run: whether tapping a half changes the visible cards. The claim
# the owner made — "it just shows two of the same thing" — is about pixels, and the 800 x 1280
# gate and the physical 601 x 889 tablet disagree often enough that both have to be checked.
SPLIT_SCRIPT = ROOT / "scripts" / "browser" / "split.js"
# The email workspace, driven with a finger: the Reply path end to end, every enabled rail
# chip actually pressed, a precision field typed into through a redraw, and the archive
# proven out of the queue (§19, §20, §22). Its own file and its own run, because it walks one
# long path rather than sampling many screens, and a failure in it has to name the step.
EMAIL_SCRIPT = ROOT / "scripts" / "browser" / "email.js"
# §30. The states the owner physically held on 11 September, put back on a screen: seven
# customer profiles for a one-line answer, a customer card open on an empty Email tab, a
# thousand-pixel capability card, the branch chips under a full-viewport voice target, the
# twenty-six-tap burst with the durations the tablet recorded. Every one of them is DERIVED
# from `logs/test-sessions/ts-20260911-201129-phase-4-live-tablet-test.jsonl` by
# `experience/fixtures/live_states.py`; nothing in the committed fixture was invented and no
# customer name or address from that file is in it. Phase 4's nineteen fixtures were all
# invented and all green through that evening, which is the whole reason this file exists.
REPLAY_SCRIPT = ROOT / "scripts" / "browser" / "replay.js"
# §33. The four click paths, walked with a finger and judged on the VISIBLE destination. The
# live session recorded eight `navigation.home` commands posted and eight accepted while the
# owner pressed Home four times in three seconds: a 200 is not an arrival, and no check in
# this suite had ever said so.
CLICKPATH_SCRIPT = ROOT / "scripts" / "browser" / "clickpath.js"
# §32. The thirty-four named surfaces. Every shot declares what must be on the glass for the
# file to BE that shot, so a blank orb screen can never again be saved as a picture of the
# customer workspace. Run with no output directory it writes nothing and still checks every
# surface, which is why it belongs in the gate as well as in the capture.
SCREENS_SCRIPT = ROOT / "scripts" / "browser" / "screens.js"
#: Where §32's matrix is written. Its own directory, not the report gallery: these are named,
#: numbered, and compared release to release by eye.
SCREENS_OUT = ROOT / "docs" / "screens" / "phase5"
# And the P0 of Phase 5, with real fingers. Every other browser gate reaches into the DOM with
# `element.click()`, which dispatches straight at the node and cannot be swallowed by anything
# painted over it — so not one of them could see D-1, in which a transparent voice target the
# size of the stage owned every touch on the idle screen and 63 taps on Split, Merge and Close
# became recordings in one evening. This one dispatches CDP touch events at measured pixels and
# counts what the tablet would have done with them: /turn posts, `recording_too_short`, the
# voice layer's own hold-start, and the touch machine's submit count. All four must be ZERO for
# every ordinary control tap, at both viewports — and two genuine holds must still send.
TOUCH_SCRIPT = ROOT / "scripts" / "browser" / "touch.js"
# Where Playwright's Chromium lives in this environment. Overridable, because on the Mac it
# will be wherever `npx playwright install` put it.
CHROMIUM = os.environ.get("CROOKS_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

log = logging.getLogger("crooks.experience.browser")


class BrowserUnavailable(RuntimeError):
    """Node, playwright-core or a Chromium is missing. The suite says so and carries on: a
    browser check that cannot run is reported as skipped, never as passed."""


def available() -> tuple[bool, str]:
    if shutil.which("node") is None:
        return False, "node is not installed"
    if not SCRIPT.exists():
        return False, f"{SCRIPT.name} is missing"
    probe = subprocess.run(["node", "-e", "require.resolve('playwright-core')"],
                           cwd=ROOT, capture_output=True, text=True)
    if probe.returncode != 0:
        return False, "playwright-core is not installed (npm i playwright-core)"
    if not Path(CHROMIUM).exists():
        return False, f"no Chromium at {CHROMIUM}"
    return True, ""


@contextlib.contextmanager
def _names_left_as_found():
    """[checker, 8 Oct 2026] The browser run serves the fixture world inside this process, and every
    personal string its reads return is noted for redaction (app/observability/timeline.py
    `note_names`), for the rest of the process. Once the gates' model read for real, the replay gate
    read the shop's own replies and "CROOKS" was left noted as a name: a later test's record wrote
    "CROOKS-1938" as "[name]-1938". So a run puts the set back as it found it."""
    from app.observability import timeline

    with timeline._names_lock:
        before = list(timeline._names)
    try:
        yield
    finally:
        timeline.forget_names()
        timeline.note_names(before)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def serve_fixture_world(port: int):
    """A real uvicorn on loopback, with the golden world bound to it.

    The lifespan builds the runtime with whatever clients the settings describe, so the swap
    happens after start-up — the same order the harness uses, and for the same reason.
    """
    import uvicorn

    from app.main import app
    from app.runtime import _make_customer_lookup
    from app.session.manager import SessionManager
    from app.tools import gmail_tools, gmail_writes, shopify_tools
    from experience.fixtures import FixtureShopify, data, fixture_gmail
    from experience.harness import RecordingProvider, _warm

    original_lifespan = app.router.lifespan_context

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        await asyncio.sleep(0.05)
        if server.started:
            break
    if not server.started:
        task.cancel()
        raise BrowserUnavailable("the fixture backend did not start")

    runtime = app.state.runtime
    runtime.provider = RecordingProvider()
    # The world on the day the application is on, as the harness builds it (data.rebase).
    data.rebase()
    store, gmail = FixtureShopify(), fixture_gmail()
    runtime.shopify = store
    runtime.gmail = gmail
    shopify_tools.bind(store)
    # Both Gmail modules, and the real customer cross-reference — the same three the harness
    # binds, and for the same reasons: `runtime.customer_lookup` does not exist, and the write
    # module holds its own client which would otherwise still be the real one.
    gmail_tools.bind(gmail, customer_lookup=_make_customer_lookup(store))
    # No `customer=` — see experience/harness.py for what passing one did.
    gmail_writes.bind(gmail, policy=lambda: runtime.settings)
    runtime.sessions = SessionManager()
    runtime.settings = runtime.settings.model_copy(update={
        "writes_enabled": True, "allowed_logins": "owner@example.com",
        "writes_local_owner": False, "tailscale_verify": False,
    })
    app.state.allowed_logins = runtime.allowed_logins
    await _warm(runtime)
    _ = original_lifespan
    return server, task, store


async def capture_screens(_harness: Any, *, out: Path, only: str = "") -> list[Path]:
    """Drive the page and take the pictures. Returns the files written.

    The harness passed in is NOT used to serve: a browser needs a socket, so a second backend
    is started on loopback against the same fixture world. They do not share a session, which
    is deliberate — the browser run is its own conversation.
    """
    ok, why = available()
    if not ok:
        log.warning("browser checks skipped: %s", why)
        return []
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.png"):
        stale.unlink()

    port = _free_port()
    server, task, _store = await serve_fixture_world(port)
    _script_the_model()
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["node", str(SCRIPT), f"http://127.0.0.1:{port}", str(out)],
            cwd=ROOT, capture_output=True, text=True, timeout=300,
            env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
        # And the same again at the tablet's own size. The pictures that matter for an
        # eight-inch screen are the ones taken on an eight-inch screen: the Phase 2 live test
        # found clipping and a swallowed dock that the 800 x 1280 shots could not show.
        #
        # Every gate, into the one directory, because the index in the report is meant to be
        # the whole build and not the half of it that one file happens to take. Each script
        # prefixes its own names (accept-, action-, collide-, density-, split-, tab-, e0...),
        # so nothing here overwrites anything else.
        for extra in (TABLET_SCRIPT, ACTION_SCRIPT, ACCEPT_SCRIPT, COLLISION_SCRIPT,
                      SPLIT_SCRIPT, EMAIL_SCRIPT, TOUCH_SCRIPT, DENSITY_SCRIPT,
                      REPLAY_SCRIPT, CLICKPATH_SCRIPT):
            if not extra.exists():
                continue
            await asyncio.to_thread(
                subprocess.run,
                ["node", str(extra), f"http://127.0.0.1:{port}", str(out)],
                cwd=ROOT, capture_output=True, text=True, timeout=600,
                env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
            )
    finally:
        await _stop(server, task)

    payload: dict[str, Any] = {}
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    if not payload:
        log.warning("the browser run produced no result: %s", (result.stdout + result.stderr)[-400:])
        return []

    for entry in payload.get("checks") or []:
        mark = "ok  " if entry.get("ok") else "FAIL"
        print(f"    {mark} {entry.get('name')}"
              + (f"  — {entry.get('detail')}" if not entry.get("ok") and entry.get("detail") else ""),
              file=sys.stderr)
    if not payload.get("ok"):
        log.warning("browser checks failed")
    _ = only
    return sorted(out.glob("*.png"))


async def capture_matrix(*, out: Path | None = None) -> dict[str, Any]:
    """§32's thirty-four named surfaces, written where they can be compared by eye.

    Its own entry point, separate from `capture_screens`, for two reasons. The files are NAMED
    and NUMBERED — `10-full-customer-rich-workspace.png` — and a numbered set that shares a
    directory with a gallery of `collide-601-*.png` cannot be read as a matrix. And a shot
    whose surface does not exist is written as `…MISSING.png`, so a directory listing is
    itself the report; mixing that convention into the report gallery would make every other
    file there ambiguous.

    Returns the script's own payload: checks, the files written, and `missing` — the shots
    whose surface is not on the glass yet, each with the workstream that owns it.
    """
    ok, why = available()
    if not ok:
        return {"skipped": True, "why": why, "checks": [], "shots": [], "missing": []}
    where = out or SCREENS_OUT
    where.mkdir(parents=True, exist_ok=True)
    # Stale pictures are worse than none: a shot that stopped being captured would otherwise
    # keep its last good file and the matrix would claim a surface nobody had photographed.
    for stale in where.glob("*.png"):
        stale.unlink()
    port = _free_port()
    server, task, _store = await serve_fixture_world(port)
    _script_the_model()
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["node", str(SCREENS_SCRIPT), f"http://127.0.0.1:{port}", str(where)],
            cwd=ROOT, capture_output=True, text=True, timeout=1200,
            env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
    finally:
        await _stop(server, task)
    payload: dict[str, Any] = {}
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    if not payload:
        return {"skipped": False, "ok": False, "checks": [{
            "name": "the screenshot matrix ran", "ok": False,
            "detail": (result.stdout + result.stderr)[-400:],
        }], "shots": [], "missing": []}
    for entry in payload.get("checks") or []:
        mark = "ok  " if entry.get("ok") else "MISSING"
        print(f"    {mark} {entry.get('name')}"
              + (f"  — {entry.get('detail')}" if not entry.get("ok") else ""), file=sys.stderr)
    return payload


def _script_the_model() -> Any:
    """The fixture model taught the gates' sentences (experience/gate_model.py). Returns the
    runtime it is bound to."""
    from app.main import app

    runtime = app.state.runtime
    gate_model.script(runtime.provider, runtime)
    return runtime


def _start_gate_session(scratch: str):
    """Begin a test session for the browser run, writing nowhere near the owner's. Returns the
    function that ends it; both are no-ops if the runtime is not up or already recording."""
    from app.main import app
    from app.observability.session import TestSessions

    runtime = getattr(app.state, "runtime", None)
    if runtime is None:
        return lambda: None
    previous = runtime.tests
    runtime.tests = runtime.timeline.sessions = TestSessions(Path(scratch))
    try:
        runtime.timeline.start("browser gate")
    except Exception:  # noqa: BLE001 — an already-running session is not this gate's business
        runtime.tests = runtime.timeline.sessions = previous
        return lambda: None

    def stop() -> None:
        try:
            runtime.timeline.stop()
        except Exception:  # noqa: BLE001
            pass
        runtime.tests = runtime.timeline.sessions = previous

    return stop


async def run_checks(*, scripts: tuple[Path, ...] | None = None) -> dict[str, Any]:
    """The browser checks on their own, for a test to assert on.

    `scripts` names which runs to make; the default is every gate. A test that is about one
    thing — the density measurement, the email workspace — passes just its own file, so its
    failure names its own subject and it pays for one browser. The DEFAULT is the whole set on
    purpose: a gate left out of it is a gate that proves nothing between releases, which is
    exactly how accept.js came to be the only check that had ever seen the duplicate
    `replaceCard`. Keyword-only, so nobody narrows the default sweep by accident.

    Phase 5 widened it by four and narrowed it by nothing. `density.js` was declared and
    screenshotted but was not in this tuple, so between releases it proved nothing; the other
    three are §30's live replay, §33's click paths and §32's matrix. The matrix runs here with
    NO output directory, so it writes no files and still asks of every one of the thirty-four
    surfaces whether it exists — which is the half of §32 that belongs in a gate.
    """
    ok, why = available()
    if not ok:
        return {"skipped": True, "why": why, "checks": []}
    with _names_left_as_found():
        return await _run_checks(scripts)


async def _run_checks(scripts: tuple[Path, ...] | None) -> dict[str, Any]:
    port = _free_port()
    server, task, _store = await serve_fixture_world(port)
    # The model, for the sentences the gates type (experience/gate_model.py): every sentence
    # is a model turn since 28 September, and an unscripted one draws nothing.
    runtime = _script_the_model()
    # accept.js asserts that the page posts what it drew into a test session, which is the
    # only proof anywhere that the tablet's own telemetry is wired to the Mac at all. It needs
    # a session to be running. One is started here, into a throwaway directory — a gate must
    # never write into logs/test-sessions/, where `make test-session-report` looks for the
    # owner's real ones.
    scratch = tempfile.mkdtemp(prefix="crooks-browser-gate-")
    stop_session = _start_gate_session(scratch)
    try:
        results = []
        for script in (scripts if scripts is not None else
                       (SCRIPT, TABLET_SCRIPT, ACTION_SCRIPT, ACCEPT_SCRIPT, COLLISION_SCRIPT,
                        SPLIT_SCRIPT, EMAIL_SCRIPT, TOUCH_SCRIPT, DENSITY_SCRIPT,
                        REPLAY_SCRIPT, CLICKPATH_SCRIPT, SCREENS_SCRIPT)):
            if not script.exists():
                continue
            results.append(await asyncio.to_thread(
                subprocess.run,
                ["node", str(script), f"http://127.0.0.1:{port}", ""],
                cwd=ROOT, capture_output=True, text=True,
                # `screens.js` walks to thirty-four surfaces at one size and twelve at another,
                # through real reads on a real backend. It waits on the page rather than on the
                # clock, so it is minutes rather than tens of minutes — but a 600s ceiling is
                # close enough to its honest runtime that a slow machine would report a gate
                # TIMEOUT as a gate failure, which is the worst kind of red.
                timeout=1200 if script == SCREENS_SCRIPT else 600,
                env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
            ))
    finally:
        stop_session()
        shutil.rmtree(scratch, ignore_errors=True)
        await _stop(server, task)
    merged: dict[str, Any] = {"skipped": False, "ok": True, "checks": [], "shots": []}
    # A call the gates stood in for Claude with that Claude could not make is a failed check.
    stood_in = gate_model.unmakeable(runtime.provider, runtime)
    merged["checks"].extend(stood_in)
    merged["ok"] = not stood_in
    for result in results:
        payload = None
        for line in reversed((result.stdout or "").strip().splitlines()):
            try:
                payload = json.loads(line)
                break
            except ValueError:
                continue
        if payload is None:
            payload = {"ok": False, "checks": [{"name": "browser run", "ok": False, "detail": (result.stdout + result.stderr)[-400:]}]}
        merged["ok"] = bool(merged["ok"] and payload.get("ok"))
        merged["checks"].extend(payload.get("checks") or [])
        merged["shots"].extend(payload.get("shots") or [])
    return merged


async def _stop(server: Any, task: asyncio.Task) -> None:
    """Shut the fixture backend down without leaving a traceback in the suite's output.

    uvicorn's socket closes a beat after the serve task returns, and anything still finishing
    then raises "Event loop is closed" into stderr — noise that reads like a failure in a run
    that passed. A moment for the loop to drain removes it.
    """
    server.should_exit = True
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=10)
    except (TimeoutError, asyncio.CancelledError):
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
    # A beat for uvicorn's transports to finish closing before the loop goes.
    await asyncio.sleep(0.25)
