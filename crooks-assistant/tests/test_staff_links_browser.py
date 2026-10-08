"""Staff links in Chromium at a phone's size (DEC-075): `scripts/browser/staff_links.js` joins CLIVE through
the team's door as someone with no Tailscale at all, works their list, and is signed out by George.

The real backend and its door serve the page (experience.browser serve_fixture_world, the team's world of
scripts/browser/team_server.py), the team's address is set, and the two links are made here as George's
passkey would have had them made (app/people/links.py make); the passkey check itself is tested in
tests/test_staff_links.py. Set STAFF_LINK_SHOTS to a directory to keep the screenshots. Skipped, loudly,
when node, playwright-core or Chromium are missing — never quietly passed.
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

SCRIPT = ROOT / "scripts" / "browser" / "staff_links.js"
# Every check the script makes must be made: a run that stopped early is not a pass.
EXPECTED_CHECKS = 25


def _harness():
    spec = importlib.util.spec_from_file_location("team_server", ROOT / "scripts" / "browser" / "team_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_joining_by_staff_link_on_a_phone_in_a_real_browser(tmp_path, monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    from app.main import app
    from app.people import access, links
    from app.people.store import people
    from app.work.store import work

    port = _free_port()
    server, task, _shop = await serve_fixture_world(port)
    try:
        runtime = app.state.runtime
        _harness().seed(runtime, tmp_path / "team", patch=monkeypatch.setattr)
        runtime.settings = runtime.settings.model_copy(update={"team_host": "team.example.test"})
        links.configure(state_dir=tmp_path / "team" / "secret")
        people.note({"name": "Ana Fixture", "kind": "staff", "role": "packing"})
        token, code, _ = links.make("ana-fixture", by="owner")
        other, other_code, _ = links.make("kit", by="owner")
        shots = os.environ.get("STAFF_LINK_SHOTS", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CROOKS_CHROMIUM": CHROMIUM, "STAFF_LINK_TOKEN": token, "STAFF_LINK_CODE": code,
               "STAFF_LINK_OTHER": other, "STAFF_LINK_OTHER_CODE": other_code}
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", shots],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env=env,
        )
    finally:
        await _stop(server, task)
        people.configure(None)
        access.configure(state_dir=None)
        links.configure(state_dir=None)
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
    assert payload.get("ok"), f"{len(failed)} staff link browser check(s) failed:\n{detail}"
    assert len(payload.get("checks") or []) == EXPECTED_CHECKS, (
        f"the run made {len(payload.get('checks') or [])} checks, expected {EXPECTED_CHECKS}")
