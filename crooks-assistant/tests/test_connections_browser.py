"""The Connections screen in Chromium, at a phone, the Tab A and a laptop (2 October 2026).

George: "it asks for API keys when not needed and is clunky to use." `scripts/browser/connections.js`
opens the real page, served by the real backend with every connection in a state he meets
(tests/connections_world.py), and judges what is on the glass: what needs him first, then what
works, then what he could add; no key box on a working connection; exactly one where a key was
refused, and exactly one when he taps Connect on a service not yet added; details closed until
opened; the voice settings still behind ElevenLabs; nothing wider than the screen; every control
44 px; nothing moving under reduced motion; no secret on the page or in its answers; and a new
GitHub token saved in one step through the page's own passkey approval (Chromium's virtual
authenticator holding the owner's passkey), after which GitHub is Working.

Opening the screen asks each connected service again: the stand-ins count it here.

Set CONNECTIONS_SHOTS to a folder to keep the screenshots. Skipped, loudly, when node,
playwright-core or Chromium are missing, never quietly passed. Like every browser check here
(experience/browser.py `available`), it finds playwright-core through Node's own lookup, so on a
machine where it is installed outside the repository NODE_PATH must name that folder, as the
builders' machines do; the overnight machine's is /home/claude/night/node_modules:

    NODE_PATH=/home/claude/night/node_modules CONNECTIONS_SHOTS=<folder> \
        python -m pytest tests/test_connections_browser.py
"""

from __future__ import annotations

import asyncio
import os

import pytest

from experience.browser import _stop, available
from tests import connections_world

# Every check the script makes must be made: a run that stopped early is not a pass.
EXPECTED_CHECKS = 70   # 64, then CROOKS Returns as something to add, at each of the three sizes (+3), then WeCom (+3)


async def test_the_connections_screen_in_a_real_browser(tmp_path):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why} (playwright-core is found through NODE_PATH)")
    server, task, port, world = await connections_world.serve(tmp_path)
    try:
        before = {c.url.host for c in world.services.calls}
        asked_before = len(world.services.calls)
        payload = await asyncio.to_thread(connections_world.run_script, port,
                                          os.environ.get("CONNECTIONS_SHOTS", ""), "after", world)
        asked = world.services.calls[asked_before:]
    finally:
        await _stop(server, task)
        world.restore()
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    detail = "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert payload.get("ok"), f"{len(failed)} connections browser check(s) failed:\n{detail}"
    assert len(payload.get("checks") or []) == EXPECTED_CHECKS, (
        f"the run made {len(payload.get('checks') or [])} checks, expected {EXPECTED_CHECKS}")
    # The world tested each one as it was furnished and Shopify five minutes before: five openings
    # of the screen asked Shopify once and nothing tested within the minute, and never a service
    # that is not connected. GitHub was asked once more: the test of the token saved in one step.
    assert before, "the world was furnished by the services' own tests"
    hosts = [c.url.host for c in asked]
    assert sum(h.endswith(".myshopify.com") for h in hosts) == 1, hosts
    github = [c for c in asked if c.url.host == "api.github.com"]
    assert len(github) == 1 and github[0].headers["authorization"] == f"Bearer {connections_world.NEW_GITHUB}"
    assert not [h for h in hosts if not h.endswith(".myshopify.com") and h != "api.github.com"], hosts
    # The voice's own client only ever asked ElevenLabs what a voice is (its name and its own
    # settings): free, and never a sentence synthesised on the owner's credit.
    assert world.voice.calls, "the voice panel asked for the voice's own settings"
    assert all(c.method == "GET" and c.url.path.startswith("/v1/voices/") for c in world.voice.calls)
