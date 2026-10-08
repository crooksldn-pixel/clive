"""Named routines, in Chromium, at the tablet's and a phone's size: what the owner actually sees (DEC-074).

The backend is the real one on loopback, bound to the golden world (experience/browser.py
`serve_fixture_world`), with Claude scripted for the sentences scripts/browser/routines.js types.
The routines are kept by the real store, in a folder of this test's own; the cards are the real
presenters', and the change in the routine is staged by the real gate and action engine. Nothing is
applied: the card waits for a gesture nobody gives, and the fixture shop counts every mutation.

Skipped, loudly, where there is no browser. Set CLIVE_ROUTINES_SHOTS to a folder to keep the
screenshots.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess

import pytest

from experience.browser import (
    CHROMIUM,
    ROOT,
    _free_port,
    _names_left_as_found,
    _stop,
    available,
    serve_fixture_world,
)

SCRIPT = ROOT / "scripts" / "browser" / "routines.js"
ORDER = "gid://shopify/Order/1940"
STEPS = [
    {"tool": "shopify_list_orders", "args": {"days": 1}, "say": "Today's orders"},
    {"tool": "gmail_search", "args": {"query": "newer_than:1d"}, "say": "Who wrote today"},
    {"tool": "shopify_order_note_append", "args": {"order_id": ORDER, "note": "Friday drop: pack first"},
     "say": "Note on 1940: pack it first"},
]


def _script(provider) -> None:
    """What Claude calls for each sentence: the steps it just took, kept; the steps, run, each through
    the gate, with the order its own lookup this run found; a step taken out; the routine forgotten."""
    provider.will("save this as my friday drop routine",
                  ("routine_note", {"action": "save", "name": "Friday drop", "steps": STEPS}),
                  reply="Saved as Friday drop: three steps, one of them a change.")
    provider.will("show my routines", ("routine_list", {}), reply="One routine: Friday drop.")
    provider.will("run my friday drop routine", ("routine_run", {"name": "friday drop"}),
                  ("shopify_list_orders", {"days": 1}), ("gmail_search", {"query": "newer_than:1d"}),
                  ("shopify_find_order", {"query": "1940"}),
                  ("shopify_order_note_append", lambda calls: {"order_id": calls[3].result["orders"][0]["order_id"],
                                                               "note": "Friday drop: pack first"}),
                  reply="Friday drop ran. The note on 1940 is waiting on its card.")
    provider.will("take step 2 out of my friday drop routine",
                  ("routine_note", {"action": "drop", "name": "friday drop", "at": 2}), reply="Took out step two.")
    provider.will("forget my friday drop routine", ("routine_note", {"action": "forget", "name": "friday drop"}),
                  reply="Forgotten.")


async def test_routines_in_a_real_browser(tmp_path):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    from app.main import app
    from app.work.store import work

    port = _free_port()
    with _names_left_as_found():
        server, task, store = await serve_fixture_world(port)
        folder = work._folder
        work.configure(tmp_path / "work")
        runtime = app.state.runtime
        runtime.provider.runtime = runtime
        out = os.environ.get("CLIVE_ROUTINES_SHOTS", "")
        try:
            _script(runtime.provider)
            result = await asyncio.to_thread(
                subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", out],
                cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
            )
            pending = [(p.operation, p.status.value) for s in list(runtime.sessions._sessions.values()) for p in s.proposals]
        finally:
            work.configure(folder)
            await _stop(server, task)
    payload = None
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    assert payload is not None, (result.stdout + result.stderr)[-1500:]
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("ok"), "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert len(payload["checks"]) == 2 * 12, [c["name"] for c in payload["checks"]]
    # One note staged per size, waiting for a gesture nobody gave until his next sentence moved on from
    # it (REVOKED, as every waiting card is): never executed, and the shop was not asked to change.
    assert pending == [("order_note_append", "REVOKED")] * 2, pending
    assert store.mutations_sent == 0
