"""Research read as ideas, end to end, in Chromium on the real backend (scripts/browser/research-ideas.js; DEC-078).

Why this exists: George's words (9 Oct 2026), "George should not need to review 113 recommendations".
The screen's own test draws ideas from a payload, and the synthesis tests call the code; this proves the
two together, the way he will meet them: a generation synthesised and applied by the same functions
`scripts/research.py --synthesise` and `--apply` call, then the Builds screen opened and three ideas
answered on the glass.

The page is the real one, served by the real backend on the golden world, with the build loop behind a
fake GitHub (tests/builds_fixture.py), an empty research store and owner's ledger, and the model scripted
from the invented notes of tests/research_synthesis_fixture.py (tests/fixtures/research/synthesis/,
tests on their face, never George's research). Three notes are read the old way, synthesised, a fourth
is read before the generation is applied, and applying takes it in. In the browser he answers one idea
Not now, one Not for CLIVE and one Approve the work, each in two steps. Afterwards:

- the judgment ledger holds his three answers, by his login, as the kernel's own reader accepts them,
  each bound to the idea exactly as he was shown it;
- the approved idea's build request was prepared on his conversation and waits for his hold;
- that request carries no quote, document name or section title from the notes;
- nothing was filed: GitHub saw no write;
- the old proposals' answer and prepare routes refuse with 409 "superseded", and record nothing.

Set RESEARCH_SHOTS to a directory to keep the screenshots (390 px and 1024 px). Skipped, loudly, when
node, playwright-core or Chromium are missing, never quietly passed.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest

from app.actions.models import ActionStatus
from app.builds import decisions, research_ideas
from app.objectives import store as store_module
from app.research import model as model_module
from app.research import store as research_store
from app.research.rules import read_map
from app.research.synthesis import answers as idea_answers
from app.research.synthesis import run as run_module
from app.research.synthesis.apply import apply
from app.research.synthesis.store import synthesis_store
from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available, serve_fixture_world
from tests import builds_fixture
from tests import research_synthesis_fixture as fx
from tests.test_research_browser import WatchedLoop
from tests.test_research_synthesis import _never_the_research

SCRIPT = ROOT / "scripts" / "browser" / "research-ideas.js"
EXPECTED_CHECKS = 30
OWNER = {"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.9"}
ANSWERED = {"Adopt a workflow engine for it": ("DEFERRED", "later"), "Send small refunds without a hold": ("DECLINED", "no"),
            "Work survives a restart": ("APPROVED", "go")}


async def synthesised_and_applied(store) -> str:
    """The invented notes, read and made live by the code the server's script runs."""
    model = model_module.current()
    await fx.read_old_way(store, model, "test-note-alpha.md", "test-note-beta.md", "test-note-gamma.md")
    gen = await run_module.synthesise(store, model=model_module.current(), the_map=read_map())
    await fx.read_old_way(store, model, "test-note-delta.md")
    done = await apply(store, gen, model=model_module.current(), the_map=read_map())
    assert done["taken_in"] == ["test-note-delta.md"] and synthesis_store(store).live() == gen
    return gen


def staged_requests(app) -> list:
    """Every build request staged on any conversation the backend holds."""
    sessions = app.state.runtime.sessions
    return [(sid, p) for sid, s in list(sessions._sessions.items()) for p in s.proposals
            if p.tool_name == "submit_engineering_request"]


async def test_research_ideas_answered_in_a_real_browser(tmp_path, monkeypatch):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")

    from app.main import app

    previous = store_module._STORE
    port = _free_port()
    server, task, _shop = await serve_fixture_world(port)
    replaced = model_module.install(fx.Scripted())
    try:
        objectives = store_module.install(tmp_path / "objectives")
        monkeypatch.setattr(decisions, "_LEDGER", None)
        research = research_store.install(tmp_path / "research")
        loop = WatchedLoop()
        builds_fixture.bind(monkeypatch, loop)
        gen = await synthesised_and_applied(research)
        expected = await research_ideas.current(research, decisions.ledger())
        (tmp_path / "expected.json").write_text(json.dumps(expected), encoding="utf-8")
        shots = os.environ.get("RESEARCH_SHOTS", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", str(tmp_path / "expected.json"), shots],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
        staged = staged_requests(app)
        old = next(r for r in research.documents() if r["name"] == "test-note-alpha.md")["proposals"][0]
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=OWNER, timeout=30) as client:
            refused = [await client.post("/objectives/research/answer", json={
                "proposal_id": old["id"], "fingerprint": old["fingerprint"], "answer": "adopt", "session_id": "research-ideas"}),
                await client.post("/objectives/research/prepare", json={"proposal_id": old["id"], "session_id": "research-ideas"})]
        ledger_path = objectives.root / decisions.LEDGER_NAME
        ideas = {i["name"]: i for i in synthesis_store(research).ideas(gen).values() if i.get("status") == "active"}
        prepared = synthesis_store(research).prepared()
        world = {"store": research}
        records = research.documents()
    finally:
        await _stop(server, task)
        store_module._STORE = previous
        model_module.install(replaced)
        research_store.install(None)
        fx._open_up(tmp_path)
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
    assert payload.get("ok"), f"{len(failed)} research ideas browser check(s) failed:\n{detail}"
    assert len(payload.get("checks") or []) == EXPECTED_CHECKS, (
        f"the run made {len(payload.get('checks') or [])} checks, expected {EXPECTED_CHECKS}")

    from app.orchestrator.lifecycle import load_judgment_ledger

    # His three answers, by his login, each to the idea exactly as he was shown it.
    ledger, _digest = load_judgment_ledger(ledger_path)
    said = [(idea_answers.idea_of(r.proposal_id), r.decision.value, decisions.answer_of(r).key, r.proposal_fingerprint)
            for r in ledger.records]
    assert said == [(ideas[name]["id"], decision, key, ideas[name]["fingerprint"]) for name, (decision, key) in ANSWERED.items()]
    assert {r.provenance.principal_id for r in ledger.records} == {"owner@example.com"}
    assert all(r.action_id.startswith(decisions.RESEARCH_IDEA_PREFIX) for r in ledger.records)

    # Approving prepared one build request, on his conversation, waiting for his hold.
    approved = ideas["Work survives a restart"]
    request_id = prepared[approved["id"]]["request_id"]
    assert list(prepared) == [approved["id"]], "only the approved idea has a build request"
    ((session_id, proposal),) = staged
    assert session_id == payload["session"] and proposal.session_id == payload["session"], "on the page's own conversation"
    assert proposal.status == ActionStatus.PENDING and proposal.executed_at is None, "waiting for his hold"
    assert proposal.execution["request_id"] == request_id

    # In CLIVE's words only: none of the notes' quotes, names or section titles.
    request = json.loads(proposal.execution["content"])
    assert request["title"] == "Work survives a restart" and f"idea {approved['id']}, {gen}" in request["requested_outcome"]
    _never_the_research({"request": request, "args": dict(proposal.model_args)}, world)
    assert {r["name"] for r in records} >= {"test-note-alpha.md", "test-note-delta.md"}
    assert set(loop.methods) == {"GET"}, f"GitHub was asked to write: {loop.methods}"

    # The old screen's answers are over once ideas are live: refused in words, nothing recorded.
    for response in refused:
        assert response.status_code == 409 and response.json()["code"] == "superseded", response.text
    assert len(ledger.records) == 3
