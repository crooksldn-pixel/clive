"""[returns-events] CROOKS Returns rings CLIVE's door, in Chromium at the tablet's and a phone's size
(scripts/browser/returns_events.js; app/routes/returns_hook.py, app/returns/events.py, DEC-077).

The backend is the real one on loopback, on the golden world (experience/browser.py), with the
stand-in returns service of tests/returns_stub.py behind CLIVE's real client. Mid-run the test changes
that service as a customer and a failed refund would, and posts the two events to /hooks/returns from
outside, signed over the raw body exactly as the service's own doorbell (crooks-returns/returns/
doorbell.py) signs them, with no Tailscale headers. The page is left alone: what it shows comes from
its own next look. Every name and number is invented.

Set RETURNS_EVENTS_SHOTS to a folder to keep the screenshots. Skipped, loudly, when node,
playwright-core or Chromium are missing, never quietly passed.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import httpx
import pytest

from app.clients import crooks_returns as rc
from app.returns import events
from app.secrets import keychain
from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available, serve_fixture_world
from tests.returns_stub import READ, WRITE, StubReturns, ret

SCRIPT = ROOT / "scripts" / "browser" / "returns_events.js"
EXPECTED_CHECKS = 2 * 10
SECRET = hashlib.sha256(b"returns-events-browser-secret").hexdigest()
APPROVE, REFUND = "ret_0a1b2c3d4e", "ret_0a1b2c3d4f"


def _world() -> list[dict]:
    """Nothing needs him: one return approved and waiting to be posted, one on its way back."""
    return [ret(APPROVE, 2131, status="awaiting_shipment", attention=[], customer="Ana Fixture"),
            ret(REFUND, 2132, status="in_transit", attention=[], customer="Ben Fixture")]


def _reset(service: StubReturns) -> None:
    service.returns = {r["id"]: r for r in copy.deepcopy(_world())}
    rc.forget()
    events.DOOR.forget()


async def _ring(service: StubReturns, port: int) -> None:
    """A customer asks to return #2131 and #2132's refund fails at Shopify; the service rings twice."""
    now = "2026-10-08T12:00:00+00:00"
    service.returns[APPROVE].update(status="requested", attention=["needs_approval"], updated_at=now)
    service.returns[REFUND].update(attention=["error"], last_error="Shopify did not process the return: refused",
                                   updated_at=now)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as outside:
        for n, (kind, rid) in enumerate((("requested", APPROVE), ("process_failed", REFUND)), start=1):
            raw = json.dumps({"id": f"evt_{n:024x}", "type": kind, "return_id": rid,
                              "at": now, "sent_at": int(time.time())}, separators=(",", ":")).encode()
            sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
            answer = await outside.post("/hooks/returns", content=raw,
                                        headers={"Content-Type": "application/json", "X-Crooks-Returns-Signature": sig})
            assert (answer.status_code, answer.content) == (200, b""), answer.status_code
    await events.DOOR.settle()


async def test_the_doorbell_in_a_real_browser(monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    service = StubReturns(copy.deepcopy(_world()))
    transport = service.transport()
    keys = {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE, events.SECRET_KEY: SECRET}
    monkeypatch.setattr(keychain, "get_optional", lambda key: keys.get(key))
    monkeypatch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(transport=transport))
    rc.configure(base_url="https://returns.example.com")
    port = _free_port()
    server, task, _shop = await serve_fixture_world(port)
    shots = os.environ.get("RETURNS_EVENTS_SHOTS", "")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
    said: list[str] = []
    try:
        node = await asyncio.create_subprocess_exec(
            "node", str(SCRIPT), f"http://127.0.0.1:{port}", shots, cwd=ROOT,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM})
        while True:
            line = await asyncio.wait_for(node.stdout.readline(), 300)
            if not line:
                break
            text = line.decode("utf-8", "replace").strip()
            said.append(text)
            if text.startswith("phase:"):
                if text.endswith(":fresh"):
                    _reset(service)
                elif text.endswith(":loaded"):
                    await _ring(service, port)
                node.stdin.write(b"go\n")
                await node.stdin.drain()
        errors = (await node.stderr.read()).decode("utf-8", "replace")
        await node.wait()
    finally:
        await _stop(server, task)
        rc.configure(base_url=rc.DEFAULT_BASE_URL)
        rc.forget()
        events.DOOR.forget()
    payload = None
    for text in reversed(said):
        try:
            payload = json.loads(text)
            break
        except ValueError:
            continue
    assert payload is not None, ("\n".join(said) + errors)[-2000:]
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("ok"), "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert len(payload["checks"]) == EXPECTED_CHECKS, [c["name"] for c in payload["checks"]]
