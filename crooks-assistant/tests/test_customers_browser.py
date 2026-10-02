"""Customers, in Chromium, at the tablet's and a phone's size: what the owner actually sees.

The backend is the real one on loopback, bound to the customers' fixture shop
(tests/customers_world.py), with Claude scripted for the sentences `scripts/browser/customers.js`
types. The cards are the real presenters' and the tap is a real click. Skipped, loudly, where there
is no browser. Set CLIVE_CUSTOMERS_SHOTS to a folder to keep the screenshots.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess

import pytest

from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available
from tests.customers_world import ALICIA, MIA, OURS, CustomersShop, inbox, outbox

SCRIPT = ROOT / "scripts" / "browser" / "customers.js"


async def _serve(port: int):
    """A real uvicorn on loopback with this world bound — the same order serve_fixture_world keeps:
    the lifespan builds the runtime, and the swap happens after start-up."""
    import uvicorn

    from app.families import checkout_link
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
    checkout_link._made.clear()
    return server, task, store, gmail, runtime.provider


def _script(provider) -> None:
    provider.will("look up Alysa who ordered the grey hoodie last week",
                  ("shopify_find_order", {"name": "Alysa", "item": "grey hoodie", "when": "last week"}),
                  reply="Alicia Grant's grey Loopback Hoodie, ordered last week. I heard the name as Alysa.")
    provider.will("Alysa who ordered a hoodie last week",
                  ("shopify_find_order", {"name": "Alysa", "item": "hoodie", "when": "last week"}),
                  reply="Two fit. Alicia Grant's or Alison Grey's?")
    provider.will("show me Alicia Grant's history", ("shopify_find_customer", {"query": "Alicia Grant"}),
                  ("shopify_customer_history", {"customer_id": ALICIA}), reply="Here's Alicia's story.")
    provider.will("send Mia a checkout link for the black tee, size M", ("shopify_find_customer", {"query": "Mia Jones"}),
                  ("shopify_checkout_link_send", {"customer_id": MIA, "items": [{"item": "black tee", "size": "M"}],
                                                  "message": "Hi Mia, here's the link for the black tee in a medium you asked about."}),
                  reply="The checkout link for Mia is ready. Hold the card to send it.")
    provider.will("has the refund on 2201 landed", ("shopify_find_order", {"query": "2201"}),
                  ("shopify_order_detail", lambda calls: {"order_id": calls[0].result["orders"][0]["order_id"]}),
                  reply="Yes: forty-five pounds went back to her Visa.")


async def test_the_customers_screens_in_a_real_browser(monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    from app.tools import shopify_tools

    async def ours() -> str:
        return OURS

    monkeypatch.setattr(shopify_tools, "_our_address", ours)
    bound = shopify_tools._client, shopify_tools._hydrator
    port = _free_port()
    server, task, _store, gmail, provider = await _serve(port)
    out = os.environ.get("CLIVE_CUSTOMERS_SHOTS", "")
    try:
        _script(provider)
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", out],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
    finally:
        await _stop(server, task)
        shopify_tools._client, shopify_tools._hydrator = bound
    payload = None
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    assert payload is not None, (result.stdout + result.stderr)[-800:]
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("ok"), "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert len(payload["checks"]) == 2 * 10, [c["name"] for c in payload["checks"]]
    # Nothing was sent: the checkout link waited for a hold nobody gave.
    assert not [c for c in gmail.calls if c[0] in ("send", "send_draft")]
