"""The test bench's screen in Chromium, at a phone's size and the tablet's.

`scripts/browser/bench.js` works the real page, served by the real backend and its door on the fake
shop, over a bench run whose every model is scripted (tests/bench_world.py): the run list, a run's
safety, ratings queue, scores, worst, gaps and tools never used, a result with its cards drawn by
CLIVE's own renderer in their frame and the bad actor's refund waiting for the hold, and a rating
saved and counted against the judge.

Set BENCH_SHOTS to a directory to keep the screenshots. Skipped, loudly, when node, playwright-core or
Chromium are missing — never quietly passed.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.bench.store import Bench
from experience.browser import _free_port, _stop, available
from tests import bench_world

# Every check the script makes must be made: a run that stopped early is not a pass.
EXPECTED_CHECKS = 38


async def test_the_bench_screen_in_a_real_browser(tmp_path, monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    from config.settings import get_settings

    for name, sub in (("CROOKS_OBJECTIVES_DIR", "objectives"), ("CROOKS_SECRET_DIR", "secrets"), ("CROOKS_LOG_DIR", "logs")):
        monkeypatch.setenv(name, str(tmp_path / sub))
    get_settings.cache_clear()
    await bench_world.furnish(Bench(tmp_path / "bench"), tmp_path)
    shots = os.environ.get("BENCH_SHOTS", "")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
    port = _free_port()
    server, task = await bench_world.serve(port, tmp_path / "objectives")
    try:
        payload = await asyncio.to_thread(bench_world.run_script, port, shots)
    finally:
        await _stop(server, task)
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    detail = "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert payload.get("ok"), f"{len(failed)} bench browser check(s) failed:\n{detail}"
    assert len(payload.get("checks") or []) == EXPECTED_CHECKS, (
        f"the run made {len(payload.get('checks') or [])} checks, expected {EXPECTED_CHECKS}")
