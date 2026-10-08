"""Round 12, in a real browser: hold an order or an objective and put it on a screen
(scripts/browser/lift.js), against the real backend on the golden fixture world.

The backend is experience/browser.py's: uvicorn on loopback with the fixture shop and inbox bound.
What this adds is what the owner has on the day: two approved screens and one still waiting for
its code (named and approved here as the owner does it, by the code the screen was given), two
objectives on his home, and a model scripted for the three sentences the script says. Everything
the page then does — the orders it is shown, the ids that issues, the drops, the TV page drawing
what was dropped — is the real code. Skipped, and said so, where there is no browser.

Screenshots go to R12_LIFT_SHOTS when it is set (the round-12 report's pictures), and nowhere
otherwise.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time

import pytest

from experience import browser

SCRIPT = browser.ROOT / "scripts" / "browser" / "lift.js"


def _thread_about_1939(calls):
    """The thread the inbox search in this turn found, as the next call's argument."""
    for call in calls:
        threads = (getattr(call, "result", None) or {}).get("threads") if call.name == "gmail_search" else None
        for thread in threads or []:
            if isinstance(thread, dict) and thread.get("thread_id"):
                return {"thread_id": thread["thread_id"]}
    return {"thread_id": ""}


def _autumn_drop(calls):
    """The objective the list in this turn found by its title, as the next call's argument."""
    for call in calls:
        found = (getattr(call, "result", None) or {}).get("objectives") if call.name == "objective_list" else None
        for goal in found or []:
            if isinstance(goal, dict) and goal.get("title") == "Autumn drop shoot":
                return {"objective_id": goal.get("id")}
    return {"objective_id": ""}


async def _run(tmp_path) -> dict:
    from app.displays import store as store_module
    from app.main import app
    from app.objectives import store as objectives_module
    from experience.harness import order_reads, todays_orders_reads

    port = browser._free_port()
    server, task, _shop = await browser.serve_fixture_world(port)
    try:
        runtime = app.state.runtime
        runtime.provider.runtime = runtime
        runtime.provider.will("show me today's orders", *todays_orders_reads(), reply="Today's orders.")
        runtime.provider.will("show me order 1938", *order_reads("1938"), reply="Order 1938.")
        runtime.provider.will("show me the email about 1939", ("gmail_search", {"query": "1939", "days": 30}),
                              ("gmail_read_thread", _thread_about_1939), reply="Here it is.")
        runtime.provider.will("show me the autumn drop shoot", ("objective_list", {}), ("objective_show", _autumn_drop),
                              reply="Here it is.")
        # Named a minute ago: a screen counts as on for ONLINE_S after it last asked, and naming it
        # is an ask. Named "now", the Packing screen was on for the first thirty seconds of the run
        # and off after, so the checks that drop on it while it is off passed or failed with the
        # machine's speed. Only the Office TV's own page, opened below, turns a screen on.
        minute_ago = [time.time() - 60.0]
        screens = store_module.install(tmp_path / "screens" / "displays.json", clock=lambda: minute_ago[0])
        named = {}
        for name in ("Office TV", "Packing screen"):
            made = screens.register(name)
            screens.approve(name, made["code"])
            named[name] = {"id": made["id"], "key": made["screen_key"]}
        screens.register("Bedroom TV")
        screens.clock = time.time
        goals = objectives_module.install(tmp_path / "goals")
        goals.create(title="Autumn drop shoot", request="Get the autumn drop shot by Friday", deadline="2026-10-03", by="owner")
        goals.create(title="Restock the black caps", request="Restock the black caps before the weekend", by="owner")
        shots = os.environ.get("R12_LIFT_SHOTS", "")
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", shots],
            cwd=browser.ROOT, capture_output=True, text=True, timeout=600,
            env={**os.environ, "CROOKS_CHROMIUM": browser.CHROMIUM, "CROOKS_LIFT_SCREENS": json.dumps(named)},
        )
    finally:
        await browser._stop(server, task)
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {"ok": False, "checks": [{"name": "the browser run", "ok": False, "detail": (result.stdout + result.stderr)[-800:]}]}


async def test_holding_a_record_and_dropping_it_on_a_screen_works_with_fingers_a_mouse_and_the_keyboard(tmp_path, monkeypatch):
    """George's request, walked the way he will walk it: on the tablet (601 x 889, DPR 1.33,
    touch) today's orders, a flick that scrolls, a hold that lifts a row, the Displays tray, a drop
    on the Office TV, the Office TV's own page at 1920 x 1080 drawing the order; putting it back;
    the tray kept open to tap; a refusal and a slow answer said in the tray; a tap that still opens
    the order; an order card dropped on the Packing screen; an email dropped on the Office TV and drawn there. On
    the phone (390 x 844), an objective from the home. With a mouse, and with the keyboard alone.
    And with reduced motion."""
    from app.displays import store as store_module
    from app.objectives import store as objectives_module

    ok, why = browser.available()
    if not ok:
        pytest.skip(f"no browser here: {why}")
    # This run's own records, and the process's put back afterwards.
    monkeypatch.setattr(store_module, "_STORE", None)
    monkeypatch.setattr(objectives_module, "_STORE", None)
    payload = await _run(tmp_path)
    failed = [f"{c['name']}: {c.get('detail', '')}" for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("ok") and not failed, "\n".join(failed)
    assert len(payload.get("checks") or []) >= 35
