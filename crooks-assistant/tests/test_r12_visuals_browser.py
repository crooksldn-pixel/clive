"""Round 12: the owner's three visual complaints, looked at in a real browser.

"the startup of clive is good except the start flash/star — that looks terrible"; "when text
scrolls out of view it should not be clipped but gradually blur, same as at the bottom row";
"the dots that currently make up the tv screen ... i want to see that used elsewhere such as on
clive as an active animation instead of boxes just appearing."

Chromium at the tablet's own size (601 x 889 at DPR 1.33) and a phone's (390 x 844 at DPR 3),
against the real backend on the fixture world, driving scripts/browser/visuals.js: the start-up's
light is read while it plays, the scroll edges at the top, scrolled and at the end of the home, an
objective's sheet and the deck, and a card forming out of dots frame by frame on a clock the test
holds, then at real speed, on the weak path, and under reduced motion. The objectives the home
lists are invented and served to the page by the script; nothing is written to the objective store.

Skipped, loudly, when there is no browser on this machine: a check that cannot run has proved
nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from experience.browser import available, run_checks

VISUALS_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "browser" / "visuals.js"


async def test_the_start_up_the_scroll_edges_and_the_dots_in_a_real_browser():
    ok, why = available()
    if not ok:
        pytest.skip(f"the visual checks need a browser: {why}")
    result = await run_checks(scripts=(VISUALS_SCRIPT,))
    if result.get("skipped"):
        pytest.skip(result.get("why", "no browser"))
    failed = [c for c in result.get("checks") or [] if not c.get("ok")]
    detail = "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert result.get("ok"), f"{len(failed)} visual check(s) failed:\n{detail}"
    names = [c["name"] for c in result.get("checks") or []]
    # Every part of the three complaints, at both sizes, was looked at.
    for size in ("tablet", "phone"):
        for part in ("start-up: the light never leaves", "home at the top", "home at the end",
                     "objective sheet scrolled", "the card forms out of dots", "leaves no dots of its words"):
            assert any(n.startswith(f"{size} · ") and part in n for n in names), f"{size}: {part} was not checked"
    for part in ("weak path: every frame of dots drawn in under 16ms", "reduced motion: no card forms from dots"):
        assert any(part in n for n in names), f"{part} was not checked"
