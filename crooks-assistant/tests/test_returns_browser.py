"""CROOKS Returns, in Chromium, at the tablet's and a phone's size: what the owner actually sees.

The backend is the real one on loopback, bound to the customers' fixture shop (tests/customers_world.py),
with Claude scripted for the sentences scripts/browser/returns.js types. The returns are the returns
service's own (tests/returns_world.py runs its code, its fake Shopify and its simulated Parcel2Go),
reached by CLIVE's real client through an ASGI transport. The cards are the real presenters', the hold
is a real press, and nothing reaches a network.

Skipped, loudly, where there is no browser or the service's code is not in this checkout's history.
Set CLIVE_RETURNS_SHOTS to a folder to keep the screenshots.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess

import httpx
import pytest

from app.clients import crooks_returns as rc
from app.secrets import keychain
from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available
from tests import customers_world, returns_service, returns_world
from tests.customers_world import ALICIA, OURS, CustomersShop, inbox, outbox
from tests.fake_credentials import bearer_token

SCRIPT = ROOT / "scripts" / "browser" / "returns.js"
READ = bearer_token("browser-returns-read", length=32)
WRITE = bearer_token("browser-returns-write", length=32)


async def _serve(port: int):
    import uvicorn

    from app.main import app
    from app.session.manager import SessionManager
    from app.tools import gmail_writes, shopify_tools
    from experience.harness import RecordingProvider

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        await asyncio.sleep(0.05)
        if server.started:
            break
    runtime = app.state.runtime
    runtime.provider = RecordingProvider()
    runtime.provider.runtime = runtime
    store = CustomersShop()
    runtime.shopify = store
    shopify_tools.bind(store, threads_for=inbox())
    gmail = outbox()
    runtime.gmail = gmail
    runtime.settings = runtime.settings.model_copy(update={
        "writes_enabled": True, "allowed_logins": "owner@example.com", "writes_local_owner": False, "tailscale_verify": False,
    })
    gmail_writes.bind(gmail, policy=lambda: runtime.settings)
    runtime.sessions = SessionManager()
    app.state.allowed_logins = runtime.allowed_logins
    return server, task, runtime.provider


def _script(provider, ids: dict[str, str]) -> None:
    provider.will("Which returns need me?", ("returns_open", {}),
                  reply="Three returns need you, and one label was never posted.")
    provider.will("approve Mia's swap and send her a label", ("returns_open", {}),
                  ("return_action", {"return_id": ids["mia"], "action": "approve", "postage_mode": "label_now"}),
                  reply="Approve Mia's swap to a medium, with an Evri label bought now. Hold the card, then tap.")
    provider.will("where is Alicia's return", ("return_find", {"order": "2201"}),
                  reply="Delivered back to us today; it hasn't been checked yet.")
    provider.will("how did returns do this month", ("returns_stats", {"days": 30}),
                  reply="Most of what came back stayed as credit or a swap. The Convict T-Shirt keeps coming back too small.")
    provider.will("show me order 2202", ("shopify_find_order", {"query": "2202"}),
                  ("shopify_order_detail", lambda calls: {"order_id": calls[0].result["orders"][0]["order_id"]}),
                  reply="Order 2202: Alison's return came back damaged and needs your decision.")
    provider.will("show me Alicia Grant's history", ("shopify_find_customer", {"query": "Alicia Grant"}),
                  ("shopify_customer_history", {"customer_id": ALICIA}), reply="Here's Alicia's story.")


async def test_returns_in_a_real_browser(monkeypatch, tmp_path):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    loaded = returns_service.load(tmp_path / "service")
    if loaded is None:
        pytest.skip(returns_service.WHY_NOT)
    from app.tools import shopify_tools

    async def ours() -> str:
        return OURS

    shipped = returns_world.ship_the_orders()
    try:
        world = returns_world.build(loaded, tmp_path, read_key=READ, write_key=WRITE)
        held = {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE}
        monkeypatch.setattr(keychain, "get_optional", lambda key: held.get(key))
        monkeypatch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=world.app), timeout=timeout_s))
        rc.configure(base_url="https://returns.example.com")
        rc.forget()
        monkeypatch.setattr(shopify_tools, "_our_address", ours)
        bound = shopify_tools._client, shopify_tools._hydrator
        port = _free_port()
        server, task, provider = await _serve(port)
        out = os.environ.get("CLIVE_RETURNS_SHOTS", "")
        try:
            _script(provider, world.ids)
            result = await asyncio.to_thread(
                subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", out],
                cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
            )
        finally:
            await _stop(server, task)
            shopify_tools._client, shopify_tools._hydrator = bound
            rc.configure(base_url=rc.DEFAULT_BASE_URL)
            rc.forget()
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
        assert len(payload["checks"]) == 2 * 10, [c["name"] for c in payload["checks"]]
        # The owner's hold approved Mia's swap once: one label bought for her, one Shopify return.
        mia = world.svc.store.get(world.ids["mia"])
        assert mia.status.value == "awaiting_shipment" and [e.actor for e in mia.timeline if e.type == "approved"] == ["clive for George"]
        assert len(world.shop.called("returnCreate")) == 5, "four from the world's own history, one from the hold"
    finally:
        customers_world.ORDERS[:] = shipped
        returns_service.unload(loaded)
