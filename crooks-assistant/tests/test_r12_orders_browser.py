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


class _Completions:
    """`draftOrderComplete`, as Shopify answers it: the draft completed, with the order it made —
    and every call counted, by the draft it was for. It answers "#1999" every time, so the page
    alone could not tell one completion from two (round 13, T7-02); the count can, and a second
    call for a draft already completed is refused here as well as counted."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def __call__(self, store, variables: dict) -> dict:
        draft_id = str(variables["id"])
        self.calls[draft_id] = self.calls.get(draft_id, 0) + 1
        node = store.drafts_by_id[draft_id]
        assert self.calls[draft_id] == 1 and not node.get("order"), f"{draft_id} was completed a second time"
        node["status"], node["order"] = "COMPLETED", {"id": "gid://shopify/Order/1999", "name": "#1999"}
        return {"data": {"draftOrderComplete": {"draftOrder": copy.deepcopy(node), "userErrors": []}}}


async def _complete_again(runtime) -> list[str]:
    """Every completion the page's holds made, asked for once more the way a second gesture
    would — armed, then committed with whatever the arming handed back. Returns how each
    attempt was answered; none may reach the shop."""
    from app.actions.models import ActionStatus
    from app.tools import registry

    answered = []
    for session in list(runtime.sessions._sessions.values()):
        for proposal in list(session.proposals):
            if proposal.operation != "draft_order_complete" or proposal.status is not ActionStatus.VERIFIED:
                continue
            _armed, refused = runtime.actions.arm(proposal.proposal_id, session.session_id)
            result = await runtime.actions.commit(proposal.proposal_id, session.session_id, caller="test",
                                                  spec_lookup=registry.get, nonce=proposal.arm_nonce or "")
            answered.append(f"{refused or 'armed'}/{result.code}")
    return answered


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

    completions = _Completions()
    monkeypatch.setitem(golden._DRAFTS, "draft_order_complete", completions)
    port = _free_port()
    server, task, store = await serve_fixture_world(port)
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
        # One hold at each of the four sizes, one draft each, and each completed exactly once.
        held = dict(completions.calls)
        repeated = await _complete_again(app.state.runtime)
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
    assert len(held) == 4 and set(held) == set(store.drafts_by_id), f"one draft completed at each size: {held}"
    assert all(count == 1 for count in held.values()), f"each draft completed exactly once by its hold: {held}"
    assert len(repeated) == 4, f"each completed order was asked for again: {repeated}"
    assert completions.calls == held, f"a repeat reached the shop: {repeated} {completions.calls}"
