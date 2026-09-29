"""The screen page's visual flow, in a real Chromium at 1920 x 1080 (round 12).

The owner, 29 September: "i can ask to put xyz on screen, if i ask for something new, it reverts
to home screen for a second then reverts to the new screen. why is the home animation happening
it just adds delays and makes things clunky." A claim about pixels and time, so this runs the page
the way a TV does — the real backend, a real browser naming the screen and being approved with
the code it shows — and puts on it, one after another, what the owner asks for through CLIVE's own
display store (experience/tv_flow.py, scripts/browser/tv_flow.js). Every frame the browser paints
across each change is looked at.

On the page as it was, every replacement here failed: 40 to 80 frames of the clock between the
old and the new, and seven seconds from the answer arriving to the new thing being readable.

Skipped, loudly, when there is no browser on this machine: a check that cannot run has proved
nothing.
"""

from __future__ import annotations

import asyncio

import pytest

from experience import tv_flow
from experience.browser import available

# From the answer arriving to the new thing being readable. About one second on an idle machine;
# the bound leaves room for a busy one (the suite shares its machine), and is still a third of
# the seven seconds the page took before.
READY_MS = 2500


@pytest.fixture(scope="module")
def walked():
    """The whole walk, once for the module, in its own event loop (it serves a backend)."""
    ok, why = available()
    if not ok:
        pytest.skip(f"the screen's flow needs a browser: {why}")
    result = asyncio.run(tv_flow.run(modes="full,weak,calm"))
    if result.get("skipped"):
        pytest.skip(result.get("why", "no browser"))
    assert result.get("ok"), result.get("errors") or result.get("error")
    assert not result.get("errors"), result["errors"]
    return result["results"]


def _steps(results, mode):
    return {r["step"]: r for r in results if r["mode"] == mode}


@pytest.mark.parametrize("mode", ["full", "weak", "calm"])
def test_something_new_goes_straight_there_never_home_first(walked, mode):
    """Every replacement, in every mode: no frame of the clock, no frame with nothing on the
    screen, no frame with the old and the new drawn over each other, a pane that stays never
    hidden, and the new thing readable within READY_MS of its answer arriving."""
    changes = [r for r in walked if r["mode"] == mode and r["replace"]]
    assert len(changes) >= (7 if mode == "full" else 3), [r["step"] for r in changes]
    for r in changes:
        assert r["clock_frames"] == 0, f"{mode} {r['step']}: {r['clock_frames']} frames of the clock"
        assert r["empty_frames"] == 0, f"{mode} {r['step']}: {r['empty_frames']} frames with nothing up"
        assert r["kept_hidden_frames"] == 0, f"{mode} {r['step']}: the pane that stays was hidden"
        assert r["collide_frames"] == 0, f"{mode} {r['step']}: {r['collide_frames']} frames with the old and the new drawn over each other"
        assert r["ready_ms"] is not None and r["ready_ms"] <= READY_MS, f"{mode} {r['step']}: readable after {r['ready_ms']} ms"


def test_a_video_is_never_reloaded_or_paused_by_a_pane_beside_it_and_goes_quiet_when_replaced(walked):
    steps = _steps(walked, "full")
    beside = steps["beside-the-video"]["video"]
    assert beside["loads"] == 0, "the player was loaded again"
    assert beside["commands"] and "pauseVideo" not in beside["commands"][0], beside
    for mode in ("full", "weak", "calm"):
        gone = _steps(walked, mode)["video-to-order"]["video"]
        assert gone["commands"] and gone["commands"][0][-1] == "pauseVideo", (mode, gone)
        assert gone["loads"] == 0 and gone["left_on_board"] == 0, (mode, gone)


def test_the_clock_comes_back_only_when_nothing_is_left(walked):
    for mode in ("full", "weak", "calm"):
        off = _steps(walked, mode)["off"]
        assert off["ready_ms"] is not None, f"{mode}: turned off, the screen never went home to its clock"
