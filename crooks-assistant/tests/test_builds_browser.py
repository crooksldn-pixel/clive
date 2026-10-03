"""The Builds screen in Chromium, on the real build loop as it stood on 2 Oct 2026.

`scripts/browser/builds.js` opens the real page, served by the real backend on the golden world,
with the worker-01 loop's own published status, request files and trunk facts behind a fake GitHub
(tests/builds_fixture.py), and judges what is on the glass: the home's Builds rows, the screen's
groups in George's order with no SHA on any build's face, the question a build puts to him and his
answer recorded, the technical details, asking CLIVE "What's being built?", and the phone's and the
tablet's widths. Afterwards the answer he gave is read back from the judgment ledger, by the kernel's
own reader, as the one valid judgment it holds.

Set BUILDS_SHOTS to a directory to keep the screenshots. Skipped, loudly, when node, playwright-core
or Chromium are missing, never quietly passed.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from app.objectives import store as store_module
from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available, serve_fixture_world
from experience.harness import model_could_make
from tests import builds_fixture

SCRIPT = ROOT / "scripts" / "browser" / "builds.js"
EXPECTED_CHECKS = 27


async def test_the_builds_screen_in_a_real_browser(tmp_path, monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    from app.main import app

    previous = store_module._STORE
    port = _free_port()
    server, task, _shop = await serve_fixture_world(port)
    try:
        runtime = app.state.runtime
        runtime.provider.runtime = runtime
        objectives = store_module.install(tmp_path / "objectives")
        builds_fixture.bind(monkeypatch, builds_fixture.FakeLoop())
        runtime.provider.will("What's being built?", ("engineering_status", {}),
                              reply="Two builds are waiting on your answer; the rest of what was built is live.")
        shots = os.environ.get("BUILDS_SHOTS", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", shots],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
        made = list(runtime.provider.made)
        ledger_path = objectives.root / "owner-judgments.jsonl"
        lines = ledger_path.read_text(encoding="utf-8").splitlines() if ledger_path.exists() else []
    finally:
        await _stop(server, task)
        store_module._STORE = previous
    payload = None
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    assert payload is not None, (result.stdout + result.stderr)[-2000:]
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    detail = "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert payload.get("ok"), f"{len(failed)} builds browser check(s) failed:\n{detail}"
    assert len(payload.get("checks") or []) == EXPECTED_CHECKS, (
        f"the run made {len(payload.get('checks') or [])} checks, expected {EXPECTED_CHECKS}")
    assert made and all(model_could_make(runtime, name, args) == "" for name, args in made), made

    # His one answer, read back by the kernel's own reader: one valid judgment, by the owner's login.
    from app.orchestrator.lifecycle import load_judgment_ledger

    assert len(lines) == 1, lines
    ledger, _digest = load_judgment_ledger(ledger_path)
    (record,) = ledger.records
    assert record.provenance.principal_id == "owner@example.com"
    assert record.action_id.startswith("build-decision:") and record.decision.value == "APPROVED"
