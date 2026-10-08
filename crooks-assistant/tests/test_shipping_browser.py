"""CLIVE Shipping, in Chromium, at the tablet's and a phone's size: what the owner actually sees.

The backend is the real one on loopback, with Claude scripted for the sentences
scripts/browser/shipping.js types. The orders are the shipping service's own (tests/shipping_service.py
runs its code at the pinned commit, its fake Shopify and its fake courier), reached by CLIVE's real
client through an ASGI transport under /shipping, as Caddy serves it. The cards are the real
presenters', the hold is a real press, and nothing reaches a network.

    #2148  Guernsey  a hoodie, three details missing (weight, HS code, origin)   needs attention
    #2146  US        a tee, payment pending in Shopify                          needs attention
    #2145  Germany   two tees, every detail answered, paid                       ready to ship
    #2140  Germany   a tee, its label bought by the service's own buy            label bought, not printed
                     (the service's PrintNode is off, as it is until George sets it up: a print is refused)

Skipped, loudly, where there is no browser, the service's code is not in this checkout's history, or
its PDF libraries are not installed. Set CLIVE_SHIPPING_SHOTS to a folder to keep the screenshots.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime

import httpx
import pytest

from app.clients import crooks_shipping as sc
from app.secrets import keychain
from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available
from tests import shipping_service
from tests.customers_world import CustomersShop, inbox, outbox
from tests.fake_credentials import bearer_token

SCRIPT = ROOT / "scripts" / "browser" / "shipping.js"
READ = bearer_token("browser-shipping-read", length=32)
WRITE = bearer_token("browser-shipping-write", length=32)


def _orders(loaded, w) -> None:
    fake = loaded.fake_shopify
    w.clock.now = datetime.now(UTC).replace(microsecond=0)
    shipping_service.ready_order(loaded, w, 2145)
    w.shopify.add(fake.fo(2140, [fake.tee_line(qty=1)]))
    pending = fake.fo(2146, [fake.tee_line(qty=1)], country="US")
    pending.financial_status = "PENDING"
    w.shopify.add(pending)
    w.shopify.add(fake.fo(2148, [fake.hoodie_line(qty=1)], country="GG"))
    w.svc.sync(w.shop)
    bought = next(s for s in w.store.shipments(w.shop) if s.order_name == "CROOKS-2140")
    w.svc.buy(w.shop, bought.id, w.svc.preview(w.shop, bought.id)["basis"], "George", "world-setup-2140")


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


def _script(provider) -> None:
    provider.will("Which international orders need me?", ("shipments_open", {}),
                  reply="Four need you: two are missing something, one is ready to buy, one label is waiting to print.")
    provider.will("show me the shipping for 2145", ("shipment_find", {"order": "2145"}),
                  reply="2145 is paid and ready: £10.69 to Germany.")
    provider.will("buy the label for 2145", ("shipment_find", {"order": "2145"}),
                  ("shipping_label_buy", lambda calls: {"shipment_id": calls[0].result["shipments"][0]["shipment_id"]}),
                  reply="The label for 2145 is £10.69. Hold the card, then tap.")
    provider.will("print the label for 2140", ("shipment_find", {"order": "2140"}),
                  ("shipping_label_print", lambda calls: {"shipment_id": calls[0].result["shipments"][0]["shipment_id"]}),
                  reply="2140's label is bought and not printed yet. Swipe the card to send it to the printer.")


async def test_shipping_in_a_real_browser(monkeypatch, tmp_path):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    missing = shipping_service.missing_libraries()
    if missing:
        shipping_service.not_here(missing)
    loaded = shipping_service.load(tmp_path / "service")
    if loaded is None:
        shipping_service.not_here(shipping_service.WHY_NOT)
    from app.tools import shopify_tools

    try:
        w = shipping_service.world(loaded, tmp_path, read_key=READ, write_key=WRITE)
        _orders(loaded, w)
        charges = len(w.provider.charges)
        held = {sc.READ_KEY: READ, sc.WRITE_KEY: WRITE}
        monkeypatch.setattr(keychain, "get_optional", lambda key: held.get(key))
        monkeypatch.setattr(sc, "http_client", lambda timeout_s: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=w.reached), timeout=timeout_s))
        sc.configure(base_url="https://returns.example.com/shipping")
        bound = shopify_tools._client, shopify_tools._hydrator
        port = _free_port()
        server, task, provider = await _serve(port)
        out = os.environ.get("CLIVE_SHIPPING_SHOTS", "")
        try:
            _script(provider)
            result = await asyncio.to_thread(
                subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", out],
                cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
            )
        finally:
            await _stop(server, task)
            shopify_tools._client, shopify_tools._hydrator = bound
            sc.configure(base_url=sc.DEFAULT_BASE_URL)
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
        assert len(payload["checks"]) == 2 * 14, [c["name"] for c in payload["checks"]]
        # The owner's hold bought the label for 2145 once, recorded as his through CLIVE.
        bought = next(s for s in w.store.shipments(w.shop) if s.order_name == "CROOKS-2145")
        assert bought.label is not None and len(w.provider.charges) == charges + 1
        assert [e.actor for e in bought.timeline if e.type == "purchase_authorised"] == ["George (CLIVE)"]
        # His swipe on 2140's print reached the service, which refused it (its PrintNode is off here):
        # nothing was sent to a printer and nothing was bought.
        printed = next(s for s in w.store.shipments(w.shop) if s.order_name == "CROOKS-2140")
        assert not [e for e in printed.timeline if e.type.startswith("label_print")]
        assert not w.store.print_intents_for(w.shop, printed.id)
    finally:
        shipping_service.unload(loaded)
