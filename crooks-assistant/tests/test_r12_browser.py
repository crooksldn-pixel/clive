"""The screen that stays, in a real browser at the owner's sizes (round 12).

`scripts/browser/keep.js` drives the page against the real backend on the golden world and
checks what the owner sees: the order he is working on stays on the glass for every frame of an
edit, the card to tap arrives on top of it and in view, the proven change redraws the order in
its own place, and "pull that up again" brings back the order he moved away from. This file
starts that backend, scripts the model for the sentences the walk says — each one makes the tool
calls Claude makes for it, through the real gate — and lets the fixture shop take the one change
the walk applies, an order's note, so the gesture can be followed to what the shop holds.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from experience import browser

SCRIPT = browser.ROOT / "scripts" / "browser" / "keep.js"


def _order_reads(number: str):
    from experience.harness import order_reads

    return order_reads(number)


async def _run(out: str) -> dict:
    from experience.fixtures import data
    from experience.harness import RecordingProvider

    port = browser._free_port()
    server, task, store = await browser.serve_fixture_world(port)
    from app.main import app

    runtime = app.state.runtime
    provider = RecordingProvider(reply="Done.")
    provider.runtime = runtime
    runtime.provider = provider
    spec = data.BY_NAME["#1938"]
    order_1938 = spec.order_id
    provider.will("show me order 1938", *_order_reads("1938"), reply="Order 1938. Paid, not shipped.")
    provider.will("what's the note on it?", reply="There's no note on it yet.")
    provider.will("add a note saying gift wrap it",
                  ("shopify_order_note_append", {"order_id": order_1938, "note": "Gift wrap it"}),
                  reply="The note is ready on the card; tap to apply.")
    provider.will("has 1940 shipped?", reply="Yes, it went out yesterday.")
    provider.will("show me order 1940", *_order_reads("1940"), reply="Order 1940.")
    provider.will("pull that up again", ("show_again", {}), reply="Order 1938 is back.")
    provider.will("put 1938 and 1940 side by side", *_order_reads("1938"), *_order_reads("1940"), reply="Both are up.")
    provider.will("add a note to 1940 saying fragile",
                  ("shopify_order_note_append", {"order_id": data.BY_NAME["#1940"].order_id, "note": "Fragile"}),
                  reply="The note is ready on #1940's card; tap to apply.")

    # The one change the walk applies. The golden world refuses every mutation; for this run
    # it takes an order's note, as Shopify would, so the proof re-reads what was written.
    notes = {name: data.BY_NAME[name].note for name in ("#1938", "#1940")}
    refuse = store.mutate

    async def mutate(name: str, variables: dict) -> dict:
        if name != "order_note_set":
            return await refuse(name, variables)
        found = next(s for s in data.BY_NAME.values() if s.order_id == variables["id"])
        found.note = str(variables["note"])
        return {"data": {"orderUpdate": {"order": {"id": variables["id"], "name": f"#{found.number}", "note": found.note},
                                         "userErrors": []}}}

    store.mutate = mutate
    try:
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", out],
            cwd=browser.ROOT, capture_output=True, text=True, timeout=300,
            env={**os.environ, "CROOKS_CHROMIUM": browser.CHROMIUM},
        )
    finally:
        for name, note in notes.items():
            data.BY_NAME[name].note = note
        store.mutate = refuse
        await browser._stop(server, task)
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {"ok": False, "checks": [{"name": "keep.js ran", "ok": False, "detail": (result.stdout + result.stderr)[-600:]}]}


async def test_the_order_stays_through_an_edit_and_comes_back_when_asked_in_a_real_browser():
    ok, why = browser.available()
    if not ok:
        pytest.skip(f"no browser here: {why}")
    out = os.environ.get("KEEP_SHOTS_DIR", "")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
    payload = await _run(out)
    print(json.dumps({"shots": payload.get("shots"), "out": out}))
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("checks"), payload
    assert not failed, json.dumps(failed, indent=1)
