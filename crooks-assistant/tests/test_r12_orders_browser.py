"""Round 12's order, built by voice, in Chromium, at the tablet's, a phone's and a TV's size.

The page used to take a turn whose only card was the order being built for a turn with nothing
to show, and go back to the orb: the change made, the screen gone. That is a property of the
PAGE (web/ui.js CONTEXT_TYPES), so it is held here in a real browser against the real backend
on the golden world — not in the ASGI tests, which see only what the backend sent.

Claude is scripted for the four sentences `scripts/browser/orders.js` types; the cards are the
real presenters' and the taps are real clicks. Skipped, loudly, where there is no browser.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess

import pytest

from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available, serve_fixture_world

SCRIPT = ROOT / "scripts" / "browser" / "orders.js"


def _opened(calls):
    """Claude reading the found order off the search: its id, and the matching line's variant."""
    order = calls[0].result["orders"][0]
    return {"order_id": order["order_id"], "variant_id": order["matched_items"][0]["variant_id"], "size_step": 1}


async def test_an_order_built_by_voice_stays_on_the_screen_at_every_size():
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    from app.main import app
    from app.tools import shopify_tools

    port = _free_port()
    server, task, _store = await serve_fixture_world(port)
    bound = shopify_tools._client, shopify_tools._hydrator
    try:
        provider = app.state.runtime.provider
        provider.runtime = app.state.runtime
        said = [
            "find the customer who ordered the black medium hoodie to SL4 1QN and make a new order for them in the next size up",
            "add a custom back print at twelve pounds, two of them, and take ten percent off the hoodie",
            "five pounds off the order and four pounds postage",
            "and add a black hoodie",
        ]
        provider.will(said[0], ("shopify_find_order", {"item": "black medium hoodie", "address": "SL4 1QN"}),
                      ("shopify_order_open", _opened), reply="Mia Jones, order 1938. A new order in the large is on screen.")
        provider.will(said[1], ("shopify_order_build", {"add": [{"title": "Custom back print", "price": 12, "quantity": 2}],
                                                        "lines": [{"line": 1, "percent_off": 10}]}), reply="Added.")
        provider.will(said[2], ("shopify_order_build", {"amount_off": 5, "postage": 4}), reply="Done.")
        provider.will(said[3], ("shopify_order_build", {"add": [{"item": "black hoodie"}]}), reply="Three match. Which one?")
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", ""],
            cwd=ROOT, capture_output=True, text=True, timeout=600,
            env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
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
    assert payload.get("ok"), "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed) or payload.get("error")
    names = " | ".join(c["name"] for c in payload["checks"])
    for size in ("tablet:", "phone:", "tv:", "tablet-weak:"):
        assert size in names, f"nothing was checked at {size}"
    assert len(payload["checks"]) == 32, "eight checks at each of four sizes"
