"""Round 12's order, built by voice, in Chromium, at the tablet's, a phone's and a TV's size.

The page used to take a turn whose only card was the order being built for a turn with nothing
to show, and go back to the orb: the change made, the screen gone. That is a property of the
PAGE (web/ui.js CONTEXT_TYPES), so it is held here in a real browser against the real backend
on the golden world — not in the ASGI tests, which see only what the backend sent.

Claude is scripted for the four sentences `scripts/browser/orders.js` types; the cards are the
real presenters' and the taps are real clicks. Skipped, loudly, where there is no browser.

The golden world never completes a draft (experience/fixtures/shopify.py refuses every mutation
but `draftOrderCreate`). Here, and only here, it does — as Shopify would, naming the order it
made — because what the owner sees after the hold is the point: the card he held it from turns
into that order, and nothing on it can make it again (round 12's independent check, A1).
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess

import pytest

from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available, serve_fixture_world
from experience.fixtures import shopify as golden

SCRIPT = ROOT / "scripts" / "browser" / "orders.js"


HEADERS = {"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.9"}


class Completions:
    """`draftOrderComplete`, as Shopify answers it: the draft completed, with the order it made —
    and every call counted, by the draft it was for. It used to answer #1999 to every call and
    count none, so a second completion of one draft, which is one order made twice, would have
    gone unseen (round-12 deploy review, T7-02). A second call for a draft is answered as Shopify
    answers a draft already completed, with nothing made, and the count fails the test."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, store, variables: dict) -> dict:
        draft_id = str(variables["id"])
        self.calls.append(draft_id)
        node = store.drafts_by_id[draft_id]
        if self.calls.count(draft_id) > 1:
            return {"data": {"draftOrderComplete": {"draftOrder": None, "userErrors": [
                {"field": ["id"], "message": "This draft order has already been completed."}]}}}
        node["status"], node["order"] = "COMPLETED", {"id": "gid://shopify/Order/1999", "name": "#1999"}
        return {"data": {"draftOrderComplete": {"draftOrder": copy.deepcopy(node), "userErrors": []}}}


async def _repeat_every_hold(port: int, runtime, sessions: list[str]) -> None:
    """Each card that made its order, made again as the tablet could ask: Prepare tapped once
    more, and the hold card it was held from armed and committed a second time."""
    import httpx

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=HEADERS, timeout=30) as client:
        for session_id in dict.fromkeys(sessions):
            session = runtime.sessions.peek(session_id)
            for proposal in [p for p in session.proposals if p.operation == "draft_order_complete"]:
                again = await client.post("/command", data={"session_id": session_id, "command": "order.stage",
                                                            "workspace_id": str(proposal.execution["workspace_id"])})
                assert again.status_code == 200 and again.json()["ok"] is False, again.text
                armed = await client.post(f"/actions/{proposal.proposal_id}/arm", data={"session_id": session_id})
                nonce = armed.json().get("nonce", "") if armed.status_code == 200 else ""
                await client.post(f"/actions/{proposal.proposal_id}/commit", data={"session_id": session_id},
                                  headers={"X-Crooks-Arm": nonce})


def _opened(calls):
    """Claude reading the found order off the search: its id, and the matching line's variant."""
    order = calls[0].result["orders"][0]
    return {"order_id": order["order_id"], "variant_id": order["matched_items"][0]["variant_id"], "size_step": 1}


async def test_an_order_built_by_voice_stays_on_the_screen_at_every_size(monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    from app.main import app
    from app.tools import shopify_tools

    completions = Completions()
    monkeypatch.setitem(golden._DRAFTS, "draft_order_complete", completions)
    port = _free_port()
    server, task, _store = await serve_fixture_world(port)
    bound = shopify_tools._client, shopify_tools._hydrator
    try:
        provider = app.state.runtime.provider
        provider.runtime = app.state.runtime
        # The conversations the page spoke in, so each hold can be tried again after the script.
        sessions: list[str] = []
        spoken = provider.turn

        async def turn(session_id: str, text: str):
            sessions.append(session_id)
            return await spoken(session_id, text)

        provider.turn = turn
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
        # One hold at each of the four sizes, each its own conversation and its own draft: exactly
        # one completion for each, and none for any of them when it is tried again.
        held = list(completions.calls)
        assert len(held) == 4 and len(set(held)) == 4, (held, (result.stdout + result.stderr)[-800:])
        await _repeat_every_hold(port, app.state.runtime, sessions)
        assert completions.calls == held, f"a draft was completed again: {completions.calls}"
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
    assert len(payload["checks"]) == 40, "ten checks at each of four sizes"
