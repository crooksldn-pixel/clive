"""The page in Chromium, as part of the suite.

Skipped, loudly, when node/playwright-core/Chromium are not on this machine — never quietly
passed. A browser check that cannot run has proved nothing, and saying so is the difference
between a suite that is green and a suite that is honest.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from experience.browser import (
    ACCEPT_SCRIPT,
    ACTION_SCRIPT,
    CLICKPATH_SCRIPT,
    COLLISION_SCRIPT,
    DENSITY_SCRIPT,
    EMAIL_SCRIPT,
    REPLAY_SCRIPT,
    SCREENS_SCRIPT,
    SCRIPT,
    SPLIT_SCRIPT,
    TABLET_SCRIPT,
    available,
    run_checks,
)


def test_the_gate_runs_every_browser_script():
    """The gate is eleven scripts, not one, and none of them is optional.

    `experience.js` proves the backend's cards can be drawn and touched at 800 x 1280.
    `tablet.js` proves the same at the size the tablet physically is. `collision.js` reads
    every rectangle on screen against the stress fixtures at both sizes, because the live
    session of 11 September recorded `clipped=0` on every render while the owner was looking
    at overlapping text and controls. A file that is not in this tuple is a check nobody runs,
    which is how that session came to be green.

    Phase 5 added four and removed none. `density.js` was declared and screenshotted but had
    never been in the default sweep, so between releases it proved exactly as much as
    `accept.js` did before Phase 4 put it here — nothing. `replay.js` (§30) puts the states the
    owner physically held back on a screen; `clickpath.js` (§33) walks the four real click
    paths judged on the visible destination; `screens.js` (§32) asks of each of the thirty-four
    named surfaces whether it exists, and with no output directory writes no files while doing
    it. The tuple is checked here by NAME because that is the failure mode: not a script that
    breaks, a script that quietly stops being called.
    """
    from experience import browser

    every = (SCRIPT, TABLET_SCRIPT, ACTION_SCRIPT, ACCEPT_SCRIPT, COLLISION_SCRIPT,
             SPLIT_SCRIPT, EMAIL_SCRIPT, DENSITY_SCRIPT, REPLAY_SCRIPT, CLICKPATH_SCRIPT,
             SCREENS_SCRIPT)
    for script in every:
        assert script.exists(), f"{script.name} is missing"
    source = (browser.ROOT / "experience" / "browser.py").read_text(encoding="utf-8")
    assert "COLLISION_SCRIPT" in source
    assert source.count("COLLISION_SCRIPT") >= 3, "declared, screenshotted and checked"
    # The default tuple itself, read out of the source: every script named above has to be in
    # the call that `run_checks` makes when nobody passes `scripts=`.
    default = source.split("scripts if scripts is not None else", 1)[1].split("):", 1)[0]
    for script in every:
        name = {
            "experience.js": "SCRIPT", "tablet.js": "TABLET_SCRIPT",
            "action_state.js": "ACTION_SCRIPT", "accept.js": "ACCEPT_SCRIPT",
            "collision.js": "COLLISION_SCRIPT", "split.js": "SPLIT_SCRIPT",
            "email.js": "EMAIL_SCRIPT", "density.js": "DENSITY_SCRIPT",
            "replay.js": "REPLAY_SCRIPT", "clickpath.js": "CLICKPATH_SCRIPT",
            "screens.js": "SCREENS_SCRIPT",
        }[script.name]
        assert name in default, f"{script.name} is not in run_checks's default sweep"


async def test_the_page_works_in_a_real_browser():
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    result = await run_checks()
    if result.get("skipped"):
        pytest.skip(result.get("why", "no browser"))
    failed = [c for c in result.get("checks") or [] if not c.get("ok")]
    detail = "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert result.get("ok"), f"{len(failed)} browser check(s) failed:\n{detail}"
    assert len(result.get("checks") or []) >= 12, "the browser run did fewer checks than expected"
    # The collision suite's own names, so a run that quietly stopped measuring geometry is a
    # failure rather than a smaller green number.
    names = " | ".join(str(c.get("name") or "") for c in result.get("checks") or [])
    for size in ("601x889@1.33", "800x1280@1"):
        assert size in names, f"nothing was measured at {size}"
    for rule in ("no interactive control overlaps another", "no text overlaps an action control",
                 "no notification overlaps the dock", "nothing essential is hidden under the fixed furniture",
                 "every control a finger uses is about 44px"):
        assert rule in names, f"the collision suite did not run: {rule}"
    # And the touch gate's own, for the same reason (Phase 5, D-1): it presses controls with
    # real CDP touch events at measured pixels, which is the only kind of check that could ever
    # have seen a transparent voice target owning every tap on the idle screen.
    for pressed in ("tap Split", "tap Merge", "tap Close", "tap Back", "tap Home",
                    "the layer ladder holds on the idle screen",
                    "ZERO recordings were too short across the whole run"):
        assert pressed in names, f"the touch gate did not run: {pressed}"
    # [checker, 8 Oct 2026, review note N2] The walk on a list asked for out loud, by API, by
    # thumb and by finger. Its Next and Back are strict expected failures until flow's fix lands
    # (KNOWN DEFECT spoken-list-walk); these names stay when they are made plain checks.
    for walked in ("Next moves the cursor on a list asked for out loud",
                   "Next on a list asked for out loud opens ITS first order",
                   "tap Back on an order opened from a list asked for out loud",
                   "tap Next on an order opened from a list asked for out loud",
                   "tap Home on an order opened from a list asked for out loud"):
        assert walked in names, f"the spoken-list walk did not run: {walked}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed here")
def test_only_the_by_design_503_from_voice_live_is_forgiven():
    """Review note N4 (8 October 2026). The fixture world's /voice/live answers 503 by design (no
    ElevenLabs key, app/routes/voice.py), and the gates skipped every console error from that URL,
    so a 500 from it passed them silently. Each gate's own predicate is run here under Node: the
    503 is skipped; a 500, or a 503 from anywhere else, still counts."""
    from experience import browser

    cases = [["http://127.0.0.1:1/voice/live", "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"],
             ["http://127.0.0.1:1/voice/live", "Failed to load resource: the server responded with a status of 500 (Internal Server Error)"],
             ["http://127.0.0.1:1/turn", "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"]]
    for name in ("screens.js", "tablet.js", "touch.js", "walk.js"):
        source = (browser.ROOT / "scripts" / "browser" / name).read_text(encoding="utf-8")
        line = next((ln for ln in source.splitlines() if ln.startswith("const voiceLiveByDesign = ")), None)
        assert line, f"{name} has no voiceLiveByDesign"
        assert "from.includes('/voice/live')) return" not in source, f"{name} still skips all of /voice/live"
        assert "voiceLiveByDesign(from, m.text())) return;" in source, f"{name} does not use it"
        run = subprocess.run(["node", "-e", f"{line}\nconsole.log(JSON.stringify({json.dumps(cases)}.map(([f, t]) => voiceLiveByDesign(f, t))))"],
                             capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
        assert json.loads(run.stdout) == [True, False, False], (name, run.stdout)
