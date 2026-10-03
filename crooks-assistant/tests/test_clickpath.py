"""§33 — the real click-path matrix, judged on the visible semantic destination.

The rule, and the reason for it: the live session recorded eight `navigation.home` commands
posted and eight accepted, zero refused, while the owner pressed Home four times in three
seconds because nothing he could see had happened (D-7). A 200 is not an arrival. So no check
in `scripts/browser/clickpath.js` reads a status code, and this file asserts that it does not:
the only thing any hop is allowed to look at is the deck, the trail and the tabs.

Two tests. The first needs no browser and holds the shape of the matrix: the four paths the
brief names, each with the hops it names, and the discipline that keeps them honest. The
second walks them in Chromium.

No failure is expected on this tree. The two this file once named walk now: Order → Customer
(path 1, step 4) and Cancel on the composer (path 3, step 7). The design pass of 3 October put the
dock under a finger on the 601 px Tab A, where the first hop of every path used to find no icon,
and retired path 4's Split hops with Split (DEC-050).
"""

from __future__ import annotations

import pytest

from experience.browser import CLICKPATH_SCRIPT, available, run_checks

#: The four paths §33 lists, by the id `clickpath.js` gives each, and the hops that make them
#: those paths rather than four walks that happen to pass.
REQUIRED_PATHS = {
    "1-orders-customer-prior-order-back": (
        "Idle → Orders → Order → Customer → Orders tab → prior order → Back → customer "
        "→ Back → original order", 8,
    ),
    "2-inbox-thread-customer-order-back": ("Inbox → Thread → Customer → Order → Back", 5),
    "3-customer-inbox-compose-cancel": ("Customer → Inbox → Compose → Cancel", 7),
    # Retired under DEC-050: George retired user-facing Split on 20 Sep 2026, and DEC-050 with
    # DEC-037/038 says Split-specific UI and tests are migration evidence, not permanent
    # requirements. Its eight Split hops (Split → select left → open order → switch right → open
    # inbox → switch left → Back → switch right) and their whole-path check are retired; its first
    # hop, a finger on the Orders icon at the Tab A's size, is the dock's and is still walked.
    "4-split-two-halves-independent": ("Orders (the Split hops are retired: DEC-050)", 1),
}


def test_the_matrix_is_the_four_paths_and_reads_no_status_code():
    source = CLICKPATH_SCRIPT.read_text(encoding="utf-8")
    for path_id in REQUIRED_PATHS:
        assert f"'{path_id}'" in source, f"§33's path `{path_id}` is not in the matrix"
    # The discipline, asserted on the source because it is the whole point of the file. The
    # destination comes from `glass()` — the deck, the trail, the tabs — and `judge()` is
    # handed nothing else.
    assert "const glass = (page) => page.evaluate" in source
    assert "function judge(want, g, memory)" in source
    for forbidden in ("res.status() ===", "status === 200", "r.ok &&", "response.ok"):
        assert forbidden not in source, (
            f"a hop is being judged on `{forbidden}`. §33: never an HTTP code — the live "
            "session had eight accepted Home commands and no arrival"
        )
    # `ref_is` is the strongest form of a destination and the one a card-type check cannot
    # express: the record the control NAMED must be the record now on screen.
    assert "ref_is" in source, "nothing checks that Back returns to the record it came from"


async def test_every_click_path_walks():
    ok, why = available()
    if not ok:
        pytest.skip(f"the click-path matrix needs a browser: {why}")
    result = await run_checks(scripts=(CLICKPATH_SCRIPT,))
    if result.get("skipped"):
        pytest.skip(result.get("why", "no browser"))
    checks = result.get("checks") or []
    names = [str(c.get("name") or "") for c in checks]

    # Each path was attempted, and each said whether the WHOLE path walks — a per-hop green
    # with no summary would let a path that stops half way look like a set of passes.
    for path_id, (words, least) in REQUIRED_PATHS.items():
        assert any(f"PATH {path_id} ·" in n for n in names), f"{path_id} was never walked"
        assert any(f"PATH {path_id} · the whole path is walkable" in n for n in names), (
            f"{path_id} never reported whether the whole path walks"
        )
        hops = [n for n in names if f"PATH {path_id} · step " in n]
        assert len(hops) >= least, (
            f"{path_id} ({words}) has {len(hops)} hops; §33 names {least}"
        )

    failed = [c for c in checks if not c.get("ok")]
    detail = "\n".join(f"  - {c['name']}\n      {c.get('detail', '')}" for c in failed)
    assert not failed, f"{len(failed)} of {len(checks)} click-path checks failed:\n{detail}"
