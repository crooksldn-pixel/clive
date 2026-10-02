"""The team's own CLIVE in Chromium, at a phone's size and the shared tablet's, and George's side.

`scripts/browser/team.js` works the real page, served by the real backend and its door, as Mia on a
phone, Kit on the tablet and George: claiming by tap, Undo, a typed sentence, hold to speak with a
scripted recogniser standing in for the phone's (the browser here cannot hear), holding the job in
hand, and a refund asked for both on the page and of their CLIVE, which the gate refuses and notes
for George. The members' assistant is the harness's script (scripts/browser/team_server.py): its
tool calls go through the real gate under the member's own authority.

Set TEAM_SHOTS to a directory to keep the screenshots. Skipped, loudly, when node, playwright-core or
Chromium are missing — never quietly passed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available, serve_fixture_world

SCRIPT = ROOT / "scripts" / "browser" / "team.js"
# Every check the script makes must be made: a run that stopped early is not a pass.
EXPECTED_CHECKS = 26


def _harness():
    spec = importlib.util.spec_from_file_location("team_server", ROOT / "scripts" / "browser" / "team_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_teams_own_clive_in_a_real_browser(tmp_path, monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    from app.main import app
    from app.people import access
    from app.people.store import people
    from app.work.store import work

    port = _free_port()
    server, task, _shop = await serve_fixture_world(port)
    try:
        _harness().seed(app.state.runtime, tmp_path / "team", patch=monkeypatch.setattr)
        shots = os.environ.get("TEAM_SHOTS", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", shots],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
    finally:
        await _stop(server, task)
        people.configure(None)
        access.configure(state_dir=None)
        work.configure(None)
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
    assert payload.get("ok"), f"{len(failed)} team browser check(s) failed:\n{detail}"
    assert len(payload.get("checks") or []) == EXPECTED_CHECKS, (
        f"the run made {len(payload.get('checks') or [])} checks, expected {EXPECTED_CHECKS}")
