"""Objectives in the shape of their kind, in Chromium at the tablet's size and a phone's (round 12).

`scripts/browser/objectives.js` types the owner's sentences into the bar of the real page, served
by the real backend on the golden world, and judges what is on the glass: the samples sentence
draws a project on its stages, the delegation sentence draws tasks by person, a tick on either the
card or the sheet changes the Mac's record, the home rows carry each kind's shape, an objective
written before round 12 reads as it did, and the current stage holds still under reduced motion
and on the weak device. The model is scripted here, as everywhere offline: its calls are the ones
Claude would make, and every one is checked to be a call Claude could make.

Set OBJECTIVE_SHOTS to a directory to keep the screenshots. Skipped, loudly, when node,
playwright-core or Chromium are missing — never quietly passed.
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

SCRIPT = ROOT / "scripts" / "browser" / "objectives.js"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "objectives"
STAGES = ["Sampling", "Approval", "Production", "Delivery"]
# Every check the script makes must be made: a run that stopped early is not a pass.
EXPECTED_CHECKS = 41


def _by_kind(kind: str):
    """The objective of this kind the conversation opened, found as the model finds it."""
    def args(_calls):
        return {"objective_id": next(o.id for o in store_module.store().live() if o.kind == kind)}
    return args


def _script(provider) -> None:
    """The calls Claude makes for each sentence the browser types."""
    provider.will(
        "Samples have started for the AW drop with Northfield",
        ("objective_list", {}),
        ("objective_open", {"title": "AW drop", "request": "Samples have started for the AW drop with Northfield",
                            "kind": "project", "stages": STAGES, "stage": "Sampling", "waiting_on": "Northfield",
                            "people": ["Northfield (factory)"]}),
        reply="The AW drop is in sampling with Northfield. When does it need to land?")
    delegate = ("Give Rosa and Kit these tasks to do later: Rosa, steam the AW samples and photograph the "
                "swatches; Kit, update the size chart")
    provider.will(
        delegate,
        ("objective_list", {}),
        ("objective_open", {"title": "Rosa and Kit's tasks", "request": delegate, "kind": "tasks", "tasks": [
            {"who": "Rosa", "text": "Steam the AW samples"},
            {"who": "Rosa", "text": "Photograph the swatches"},
            {"who": "Kit", "text": "Update the size chart"}]}),
        reply="Two for Rosa and one for Kit, for later.")
    provider.will(
        "Move the AW drop on to approval",
        ("objective_list", {}),
        ("objective_note", lambda calls: {**_by_kind("project")(calls), "action": "stage", "stage": "Approval"}),
        reply="The AW drop is at approval now.")
    provider.will(
        "The samples are approved, production's started",
        ("objective_list", {}),
        ("objective_note", lambda calls: {**_by_kind("project")(calls), "action": "stage", "stage": "Production"}),
        reply="The AW drop is in production.")
    provider.will("Show me the AW drop", ("objective_list", {}), ("objective_show", _by_kind("project")),
                  reply="It is in production.")
    provider.will("Show me Rosa and Kit's tasks", ("objective_list", {}), ("objective_show", _by_kind("tasks")),
                  reply="Rosa has one left, Kit has one.")


async def test_objectives_are_drawn_in_their_own_shape_in_a_real_browser(tmp_path):
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
        # An objective as the store wrote it before round 12, with an open question on it.
        older = json.loads((FIXTURES / "business_v1.json").read_text(encoding="utf-8"))
        objectives.root.mkdir(parents=True, exist_ok=True)
        (objectives.root / f"{older['id']}.json").write_text(json.dumps(older), encoding="utf-8")
        _script(runtime.provider)
        shots = os.environ.get("OBJECTIVE_SHOTS", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", shots],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
        made = list(runtime.provider.made)
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
    assert payload.get("ok"), f"{len(failed)} objective browser check(s) failed:\n{detail}"
    assert len(payload.get("checks") or []) == EXPECTED_CHECKS, (
        f"the run made {len(payload.get('checks') or [])} checks, expected at least {EXPECTED_CHECKS}")
    # Every call the script stood in for Claude with is one Claude can make on this runtime.
    assert made, "the model was never asked"
    for name, args in made:
        assert model_could_make(runtime, name, args) == "", (name, args, model_could_make(runtime, name, args))
