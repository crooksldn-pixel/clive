"""CLIVE recording what it does, and saying what is on the screen, in a real browser (2 October 2026).

`scripts/browser/recording.js` drives the real page against the real backend on the golden world,
with the interaction record on and no test session running: an order asked for, a chip on it
tapped four times, "who needs a reply" answered with the plain inbox, then "what's on my screen?".
This file starts that backend, puts the record in a folder of its own, scripts the model — the last
sentence calls interaction_review through the real gate, exactly as Claude would — and holds CLIVE's
answer to what the glass showed at that moment, word for word.

Set RECORDING_SHOTS_DIR to a directory to keep the screenshots and the review, drawn. Skipped,
loudly, when node, playwright-core or Chromium are missing — never quietly passed.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from experience import browser

SCRIPT = browser.ROOT / "scripts" / "browser" / "recording.js"


async def _run(out: str) -> tuple[dict, dict]:
    from app.main import app
    from app.observability import interactions
    from experience.harness import RecordingProvider, order_reads

    class Watching(RecordingProvider):
        """The harness's model, keeping what each tool returned so the review can be read back."""

        def __init__(self, reply: str) -> None:
            super().__init__(reply=reply)
            self.results: dict[str, dict] = {}

        async def turn(self, session_id, text):
            result = await super().turn(session_id, text)
            for call in result.tool_calls or []:
                if isinstance(getattr(call, "result", None), dict):
                    self.results[call.name] = call.result
            return result

    port = browser._free_port()
    server, task, _store = await browser.serve_fixture_world(port)
    runtime = app.state.runtime
    scratch = tempfile.mkdtemp(prefix="crooks-recording-")
    held = runtime.timeline.mirror
    runtime.timeline.mirror = interactions.install(
        interactions.InteractionRecord(interactions.InteractionDays(Path(scratch)), behind=held))
    provider = Watching(reply="Done.")
    provider.runtime = runtime
    runtime.provider = provider
    provider.will("show me order 1938", *order_reads("1938"), reply="Order 1938. Paid, not shipped.")
    provider.will("who needs a reply", ("gmail_search", {"query": "in:inbox", "days": 14}), reply="Here's the inbox.")
    provider.will("what's on my screen?", ("interaction_review", {"minutes": 30}),
                  reply="The inbox, as a plain list of threads. You asked who needs a reply and got the inbox instead.")
    try:
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", out],
            cwd=browser.ROOT, capture_output=True, text=True, timeout=300,
            env={**os.environ, "CROOKS_CHROMIUM": browser.CHROMIUM},
        )
    finally:
        runtime.timeline.mirror = held
        interactions.install(None)
        await browser._stop(server, task)
        shutil.rmtree(scratch, ignore_errors=True)
    payload: dict = {"ok": False, "checks": [{"name": "recording.js ran", "ok": False, "detail": (result.stdout + result.stderr)[-600:]}]}
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    return payload, provider.results.get("interaction_review") or {}


def _drawn(review: dict, out: str) -> None:
    """The review as a page George can look at, beside the screenshots of the glass: the cards
    as CLIVE says they are drawn, each turn and why, the friction and the easier way."""
    e = html.escape

    def card(c: dict) -> str:
        lines = [*c.get("attention", []), *c.get("facts", []), *(c.get("rows") or {}).get("shows", [])]
        for name, section in (c.get("sections") or {}).items():
            lines += [f"{name}: {line}" for line in section.get("shows", [])[:3]]
        controls = ", ".join(f"{a.get('label') or a.get('control')}{'' if a.get('enabled', True) else ' (off)'}" for a in c.get("actions", []))
        return (f"<div class=card><span class=pill>{e(c['type'])}</span><b>{e(c.get('title') or '')}</b>"
                + "".join(f"<div class=line>{e(line)}</div>" for line in lines[:10])
                + (f"<div class=dim>controls: {e(controls)}</div>" if controls else "") + "</div>")

    def turn(t: dict) -> str:
        cards = "; ".join(f"{c['type']} by {'+'.join(c.get('drawn_by') or ['?'])}" for c in t.get("cards", []))
        return (f"<div class=card><span class=pill>{e(t['at'])}</span><b>{e(t.get('asked') or '')}</b>"
                f"<div class=line>tools: {e(', '.join(t.get('tools') or []) or 'none')}</div>"
                f"<div class=line>drew: {e(cards or 'nothing')}</div>"
                f"<div class=line>screen {e(str(t.get('screen')))}: {e(t.get('why') or '')}</div>"
                + (f"<div class=line>workspace: {e(t['why_workspace'])}</div>" if t.get("why_workspace") else "") + "</div>")

    def finding(f: dict) -> str:
        return (f"<div class=card><span class='pill warn'>{e(f['kind'])}</span><b>{e(f['what'])}</b>"
                f"<div class=line>Easier: {e(f['easier'])}</div></div>")

    halves = [h for h in review.get("on_screen") or [] if isinstance(h, dict)]
    page = ("<!doctype html><meta charset=utf-8><title>interaction_review</title><style>"
            "body{background:#000;color:#f2f2f7;font:15px -apple-system,'SF Pro Text','Helvetica Neue',sans-serif;margin:24px}"
            "h1{font-size:24px;margin:0 0 4px}p{color:#8e8e93;margin:0 0 18px}h2{font-size:13px;letter-spacing:.06em;"
            "text-transform:uppercase;color:#8e8e93;margin:22px 0 8px}.card{background:#1c1c1e;border-radius:14px;padding:12px 14px;"
            "margin:0 0 8px}.card b{display:block;margin:6px 0 4px}.line{color:#d1d1d6;font-size:13px;margin:2px 0}"
            ".dim{color:#8e8e93;font-size:12px;margin-top:6px}.pill{font-size:11px;letter-spacing:.04em;color:#0a84ff;"
            "text-transform:uppercase}.pill.warn{color:#ff9f0a}pre{background:#1c1c1e;border-radius:14px;padding:12px;"
            "white-space:pre-wrap;font:12px ui-monospace,Menlo,monospace;color:#d1d1d6;margin:0}</style>"
            "<h1>What CLIVE says is on the screen</h1><p>interaction_review, called by CLIVE for \"what's on my screen?\": "
            "from what was drawn and the interaction record, not from memory.</p>"
            "<h2>On the screen now</h2>" + "".join(card(c) for h in halves for c in h.get("cards", []))
            + "<h2>Each turn, and why its screen</h2>" + "".join(turn(t) for t in review.get("turns") or [])
            + "<h2>Friction, and the easier way</h2>" + "".join(finding(f) for f in review.get("friction") or [] if isinstance(f, dict))
            + "<h2>Excerpt for a build: no words said, no names</h2><pre>" + e(review.get("excerpt") or "") + "</pre>")
    Path(out, "recording-4-review.html").write_text(page, encoding="utf-8")
    Path(out, "recording-review.json").write_text(json.dumps(review, indent=1, ensure_ascii=False), encoding="utf-8")
    subprocess.run(["node", str(SCRIPT), "--render", str(Path(out, "recording-4-review.html")), str(Path(out, "recording-4-review.png"))],
                   cwd=browser.ROOT, capture_output=True, text=True, timeout=120, env={**os.environ, "CROOKS_CHROMIUM": browser.CHROMIUM})


async def test_clive_records_with_no_test_running_and_says_what_is_on_the_glass_word_for_word():
    ok, why = browser.available()
    if not ok:
        pytest.skip(f"no browser here: {why}")
    out = os.environ.get("RECORDING_SHOTS_DIR", "")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
    payload, review = await _run(out)
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("checks") and not failed, json.dumps(failed or payload, indent=1)
    assert review, "the model's call to interaction_review came back with nothing"
    if out:
        _drawn(review, out)

    # What CLIVE says is up is what the glass showed when he asked, word for word.
    glass = payload["glass"]
    focused = next(h for h in review["on_screen"] if h.get("focused"))
    said = focused["cards"]
    assert [c["type"] for c in said] == [c["type"] for c in glass], (said, glass)
    for card, seen in zip(said, glass, strict=True):
        if card.get("title"):
            assert card["title"] in seen["text"], (card["title"], seen["text"][:200])
        for line in (card.get("rows") or {}).get("shows") or []:
            assert line.split(" · ")[0] in seen["text"], (line, seen["text"][:300])

    # And why: each turn, what drew its cards and which rule chose the screen.
    turns = {t["asked"]: t for t in review["turns"]}
    order, inbox = turns["show me order 1938"], turns["who needs a reply"]
    assert order["tools"] == ["shopify_find_order", "shopify_order_detail"] and order["screen"] == "new"
    assert any("1938" in (c.get("numbers") or []) for c in order["cards"])
    assert inbox["asked_for"] == ["needs_reply"] and "new subject" in inbox["why"]
    assert any(c["type"] == "email_list" and c["drawn_by"] == ["gmail_search"] for c in inbox["cards"])
    # The order's workspace came up for "who needs a reply": the record says which rule drew it.
    composed = next(c for c in inbox["cards"] if c["type"] == "order_workspace")
    assert composed["drawn_by"] == ["(composed from what the conversation already read)"]
    assert "naming its" in inbox["why_workspace"] and "order" in inbox["why_workspace"]
    kinds = {f["kind"]: f for f in review["friction"]}
    assert "UNRELATED_SCENE" in kinds and "no reply state" in kinds["UNRELATED_SCENE"]["what"]
    assert "REPEATED_TAP" in kinds and "4 times" in kinds["REPEATED_TAP"]["what"]
    assert review["tablet_last_drew"]["cards"], "the tablet's own account reached the record"
    # The excerpt a build request may carry: none of his sentences, and nobody the inbox named.
    for said in ("show me order 1938", "who needs a reply", "what's on my screen", "Priya", "Raman"):
        assert said not in review["excerpt"], said
    assert "UNRELATED_SCENE" in review["excerpt"] and "REPEATED_TAP" in review["excerpt"]
