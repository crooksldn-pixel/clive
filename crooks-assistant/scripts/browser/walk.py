#!/usr/bin/env python3
"""Serve the fixture worlds and walk every screen in a real browser (scripts/browser/walk.js).

    NODE_PATH=<playwright-core's node_modules> python scripts/browser/walk.py <folder for the pictures>

Why this exists. George asked on 7 October for everything built into CLIVE to be checked as he
uses it. The browser gates judge one subject each; this walks the whole app by touch at a phone and
both ways up a tablet, and leaves a picture of every stop for a person to look at.

Two worlds, one after the other, each a real backend on loopback with nothing reaching a network:

  main     the golden world the browser gates use (experience/browser.py `serve_fixture_world`),
           with the model scripted for the sentences the gates type (experience/gate_model.py),
           three objectives (a project, a delegation, a number to reach), the build loop's stand-in
           (tests/builds_fixture.py), the team let in (scripts/browser/team_server.py `seed`), and a
           screen record of its own for /display (approved, and an order put on it, as CLIVE's
           screen tools do: experience/tv_flow.py).
  returns  CROOKS Returns beside the customers' shop (tests/returns_world.py), as the returns gate
           serves it; skipped, and said so, where the returns service's code is not in this checkout.

Every objective, order, person and return is invented. Prints the walk's checks and exits 1 if any
failed. Writes only into the folder it is given and a temporary folder it removes.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SCRIPT = ROOT / "scripts" / "browser" / "walk.js"


def _seed_objectives(where: Path) -> None:
    """One objective of each shape the home draws: a project on its stages, tasks by person, and a
    number counted from the shop's own orders (the golden world sells the Convict Hoodie)."""
    from app.objectives import store as store_module

    s = store_module.install(where)
    today = date.today()
    s.create(title="AW drop", request="Samples have started for the AW drop with Northfield", kind="project",
             stages=["Sampling", "Approval", "Production", "Delivery"], stage="Sampling", waiting_on="Northfield",
             people=["Northfield (factory)"], deadline=(today + timedelta(days=24)).isoformat())
    s.create(title="Rosa and Kit's tasks", request="Rosa, steam the AW samples and photograph the swatches; "
             "Kit, update the size chart", kind="tasks", tasks=[
                 {"who": "Rosa", "text": "Steam the AW samples"}, {"who": "Rosa", "text": "Photograph the swatches"},
                 {"who": "Kit", "text": "Update the size chart"}])
    s.create(title="Shift the Convict Hoodies", request="Shift 40 Convict Hoodies by the end of the month",
             number={"of": "Convict Hoodie", "target": 40, "since": (today - timedelta(days=20)).isoformat(),
                     "unit": "hoodies"},
             deadline=(today + timedelta(days=18)).isoformat())


async def _drive(port: int, out: str, world: str) -> dict[str, Any]:
    """Run walk.js against the server on `port`, answering what it asks of the screen record."""
    from experience.browser import CHROMIUM
    from experience.tv_flow import _act, _views

    proc = await asyncio.create_subprocess_exec(
        "node", str(SCRIPT), f"http://127.0.0.1:{port}", out, world, cwd=ROOT,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM})
    views = _views() if world == "main" else {}
    payload: dict[str, Any] = {}
    while True:
        raw = await asyncio.wait_for(proc.stdout.readline(), timeout=600)
        if not raw:
            break
        try:
            msg = json.loads(raw.decode("utf-8"))
        except ValueError:
            continue
        if isinstance(msg, dict) and "do" in msg:
            try:
                answer = {"ok": True, **_act(msg, views)}
            except Exception as exc:  # noqa: BLE001 — the walk is told, and records it
                answer = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            proc.stdin.write((json.dumps(answer) + "\n").encode("utf-8"))
            await proc.stdin.drain()
        elif isinstance(msg, dict):
            payload = msg
    proc.stdin.close()
    _, err = await proc.communicate()
    return payload or {"ok": False, "checks": [{"name": f"{world} walk ran", "ok": False,
                                                 "detail": err.decode("utf-8", "replace")[-800:]}]}


async def _main_world(out: str, scratch: Path, patch) -> dict[str, Any]:
    from app.displays import store as displays_module
    from app.main import app
    from app.objectives import store as store_module
    from experience.browser import _free_port, _script_the_model, _stop, serve_fixture_world
    from tests import builds_fixture

    spec = importlib.util.spec_from_file_location("team_server", ROOT / "scripts" / "browser" / "team_server.py")
    team = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(team)

    previous = store_module._STORE
    port = _free_port()
    server, task, _shop = await serve_fixture_world(port)
    try:
        _script_the_model()
        _seed_objectives(scratch / "objectives")
        builds_fixture.bind(patch, builds_fixture.FakeLoop())
        team.seed(app.state.runtime, scratch / "team", patch=patch.setattr)
        displays_module.install(scratch / "displays.json")
        return await _drive(port, out, "main")
    finally:
        await _stop(server, task)
        store_module._STORE = previous


async def _returns_world(out: str, scratch: Path, patch) -> dict[str, Any]:
    import httpx

    from app.clients import crooks_returns as rc
    from app.secrets import keychain
    from app.tools import shopify_tools
    from experience.browser import _free_port, _stop
    from tests import customers_world, returns_service, returns_world
    from tests import test_returns_browser as gate

    loaded = returns_service.load(scratch / "service")
    if loaded is None:
        return {"ok": True, "skipped": returns_service.WHY_NOT, "checks": []}

    async def ours() -> str:
        return customers_world.OURS

    shipped = returns_world.ship_the_orders()
    try:
        world = returns_world.build(loaded, scratch, read_key=gate.READ, write_key=gate.WRITE)
        held = {rc.READ_KEY: gate.READ, rc.WRITE_KEY: gate.WRITE}
        patch.setattr(keychain, "get_optional", lambda key: held.get(key))
        patch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=world.app), timeout=timeout_s))
        rc.configure(base_url="https://returns.example.com")
        rc.forget()
        patch.setattr(shopify_tools, "_our_address", ours)
        bound = shopify_tools._client, shopify_tools._hydrator
        port = _free_port()
        server, task, provider = await gate._serve(port)
        try:
            gate._script(provider, world.ids)
            return await _drive(port, out, "returns")
        finally:
            await _stop(server, task)
            shopify_tools._client, shopify_tools._hydrator = bound
            rc.configure(base_url=rc.DEFAULT_BASE_URL)
            rc.forget()
    finally:
        customers_world.ORDERS[:] = shipped
        returns_service.unload(loaded)


async def walk(out: str) -> dict[str, Any]:
    import pytest

    from experience.browser import available

    ok, why = available()
    if not ok:
        return {"ok": False, "skipped": why, "checks": []}
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="crooks-walk-"))
    patch = pytest.MonkeyPatch()
    merged: dict[str, Any] = {"ok": True, "checks": [], "shots": []}
    try:
        for name, run in (("main", _main_world), ("returns", _returns_world)):
            result = await run(out, scratch / name, patch)
            merged["ok"] = merged["ok"] and bool(result.get("ok"))
            merged["checks"] += result.get("checks") or []
            merged["shots"] += result.get("shots") or []
            if result.get("skipped"):
                merged.setdefault("skipped", []).append(f"{name}: {result['skipped']}")
            patch.undo()
    finally:
        patch.undo()
        shutil.rmtree(scratch, ignore_errors=True)
    return merged


if __name__ == "__main__":
    result = asyncio.run(walk(sys.argv[1] if len(sys.argv) > 1 else ""))
    for c in result["checks"]:
        if not c.get("ok"):
            print(f"FAIL {c['name']} :: {c.get('detail', '')}")
    print(json.dumps({"ok": result["ok"], "checks": len(result["checks"]),
                      "failed": sum(1 for c in result["checks"] if not c.get("ok")),
                      "shots": len(result["shots"]), "skipped": result.get("skipped", [])}))
    raise SystemExit(0 if result["ok"] else 1)
