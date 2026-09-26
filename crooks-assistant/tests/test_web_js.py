"""The JavaScript, checked by Node: syntax for every file, and the renderer's behaviour.

Node is not a dependency of the assistant; it is a development tool. When it is absent these
tests skip rather than fail, so `make test` on a Mac without Node still proves everything
else. When it is present (it is on the build Mac), the renderer is run against a small DOM
stand-in and its two rules — vocabulary only, text only — are checked for real.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
NODE = shutil.which("node")

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed here")


@needs_node
@pytest.mark.parametrize("name", sorted(p.name for p in WEB.glob("*.js")))
def test_javascript_parses(name):
    result = subprocess.run([NODE, "--check", str(WEB / name)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@needs_node
def test_the_renderer_under_node():
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "ui.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_composed_workspaces_under_node():
    """The surfaces of §3/§12: a section drawn from its own state, and a row that is a control
    only where the Mac said it can be opened (tests/web/workspaces.test.js)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "workspaces.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_progressive_disclosure_under_node():
    """The fold that keeps a compound answer on one screen (brief section 22)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "fold.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_collision_rules_under_node():
    """The geometry that answers the question `clipped=0` could not (web/collide.js)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "collide.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_notification_architecture_under_node():
    """Three classes, one home each, and no message over the furniture (web/notify.js)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "notify.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_telemetry_under_node():
    """What a test session records of the screen, including the collision counts."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "telemetry.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_service_worker_under_node():
    """The worker keeps the shell and nothing else — proved by running it, not by reading it."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "sw.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_only_the_hold_asks_for_the_microphone_under_node():
    """On the owner's iPhone every opening of the microphone can be another permission prompt:
    a tap elsewhere, a return to the app and a reconnect never call getUserMedia, and two
    presses share one stream (tests/web/mic.test.js, running web/app.js's own text)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "mic.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_owners_settings_and_contextual_chrome_under_node():
    """GENERATIVE_UI_V1 §4, objective 2b: the Settings sheet in the owner's order with empty
    sections left out, diagnostics and fixtures behind an off-by-default Developer view switch,
    a header that speaks only while something relevant is wrong, and Back, Previous and Next
    only inside a list or a drill-down (tests/web/settings.test.js, running web/app.js's own
    text)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "settings.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_one_interaction_state_under_node():
    """V0.5 invariant 2: IDLE → LISTENING → HEARING → UNDERSTOOD → THINKING → WORKING →
    RESPONDING → IDLE, with error, interruption and recovery explicit — and the four
    latencies the evidence gate asks for, measured from pointer-down and from release
    (web/live-state.js)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "live-state.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_work_in_flight_under_node():
    """V0.5 slice C: independent jobs inside one session — out-of-order completion, one job
    failing while the others carry on, a retry only where re-running is safe, and a strip
    that disappears rather than becoming a dashboard (web/jobs.js)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "jobs.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_v05_acceptance_scenario_under_node():
    """§E of the V0.5 contract, driven end to end against an honestly-labelled fixture: the
    acknowledgement on the touch, the words settling before reasoning, two jobs progressing
    independently, the first useful result before the slowest job, speech beginning while
    work continues, a barge-in that keeps the work in flight, a second question that adds a
    background job rather than a Split, and one job failing while the others carry on.

    The timings in it are invented by the harness and prove nothing about how fast the Mac
    is; real device numbers come from the live_marks the page posts."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "acceptance-v05.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


@needs_node
def test_the_scene_renderer_under_node():
    """Generative UI V1 (2a of 4): every primitive renders, all text is text, row limits and
    drill-downs hold, a control dispatches its event and nothing else, and the gallery's cases
    draw as asked (web/scenes.js, web/scene-fixtures.js)."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "scenes.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
