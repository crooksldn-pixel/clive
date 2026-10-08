"""Research given, weighed and answered, in Chromium on the real backend (scripts/browser/research.js).

The page is the real one, served by the real backend on the golden world, with the build loop behind a
fake GitHub (tests/builds_fixture.py), an empty research store, and the model's one answer scripted for
the test document (tests/fixtures/research/test-research-note.md, a test on its face, never George's
research). The browser gives the file through the Builds screen's own way in, watches it read and
weighed, parks one recommendation, rejects one and adopts one. Afterwards:

- the judgment ledger holds his three answers, by his login, as the kernel's own reader accepts them;
- the adopted one's build request was prepared on his conversation and is waiting for his hold;
- nothing was filed: GitHub saw no write.

Set RESEARCH_SHOTS to a directory to keep the screenshots. Skipped, loudly, when node, playwright-core
or Chromium are missing, never quietly passed.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from app.builds import decisions
from app.objectives import store as store_module
from app.research import model as model_module
from app.research import store as research_store
from app.research.model import ScriptedModel
from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available, serve_fixture_world
from tests import builds_fixture
from tests.test_research import API, CHECKED, FIXTURE, REFUNDS, WHATSAPP, answer

SCRIPT = ROOT / "scripts" / "browser" / "research.js"
EXPECTED_CHECKS = 22


class WatchedLoop(builds_fixture.FakeLoop):
    """The loop as the Builds tests have it, with every method GitHub was asked kept: a write is a filing."""

    def __init__(self) -> None:
        super().__init__()
        self.methods: list[str] = []

    def handle(self, request):
        self.methods.append(request.method)
        return super().handle(request)


async def test_research_given_weighed_and_answered_in_a_real_browser(tmp_path, monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")

    previous = store_module._STORE
    port = _free_port()
    server, task, _shop = await serve_fixture_world(port)
    replaced = model_module.install(ScriptedModel(lambda system, prompt: answer(CHECKED, WHATSAPP, API, REFUNDS)))
    try:
        objectives = store_module.install(tmp_path / "objectives")
        monkeypatch.setattr(decisions, "_LEDGER", None)
        research = research_store.install(tmp_path / "research")
        loop = WatchedLoop()
        builds_fixture.bind(monkeypatch, loop)
        shots = os.environ.get("RESEARCH_SHOTS", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", str(FIXTURE), shots],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
        ledger_path = objectives.root / decisions.LEDGER_NAME
        (record,) = research.documents()
    finally:
        await _stop(server, task)
        store_module._STORE = previous
        model_module.install(replaced)
        research_store.install(None)
    payload = None
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    assert payload is not None, (result.stdout + result.stderr)[-2000:]
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    detail = "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    assert payload.get("ok"), f"{len(failed)} research browser check(s) failed:\n{detail}"
    assert len(payload.get("checks") or []) == EXPECTED_CHECKS, (
        f"the run made {len(payload.get('checks') or [])} checks, expected {EXPECTED_CHECKS}")

    from app.orchestrator.lifecycle import load_judgment_ledger

    ledger, _digest = load_judgment_ledger(ledger_path)
    assert [(r.decision.value, decisions.answer_of(r).key) for r in ledger.records] == [
        ("DEFERRED", "park"), ("DECLINED", "reject"), ("APPROVED", "adopt")]
    assert {r.provenance.principal_id for r in ledger.records} == {"owner@example.com"}
    adopted = record["proposals"][0]
    assert record["prepared"][adopted["id"]]["request_id"]
    assert set(loop.methods) == {"GET"}, f"GitHub was asked to write: {loop.methods}"
