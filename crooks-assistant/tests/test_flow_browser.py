"""From the question to the action, in a real browser at a phone's and the tablet's sizes (DEC-067).

`scripts/browser/flow.js` drives the page against the real backend on the golden world and checks
what George sees when he asks for a reply: words saying what CLIVE is doing while it works and no
card of any search, then the reply and nothing else; and the reply as one card whose words he edits
with real keystrokes and sends with one hold. This file starts that backend, scripts the model for
his turn — read for read the turn he described, through the real gate, and SLOWLY, a little under
a second a call, saying which tool is running as the real provider does
(`app/providers/max_agent_sdk.py` `_on_tool_event`) — and lets the fixture inbox take the one send
the walk makes, so the proof reads the sent message back from the thread as Gmail's would. A second
reply is refused by "Gmail", as a real send can be, to see what he is told and what he can do next.

    FLOW_SHOTS_DIR=/path/to/shots pytest tests/test_flow_browser.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import subprocess
from email import message_from_bytes, policy
from pathlib import Path

import pytest

from experience import browser

SCRIPT = browser.ROOT / "scripts" / "browser" / "flow.js"
PRIYAS_THREAD = "c28cf65d31fe6cbb"
REPLY = "Hi Priya, yes: the black cap is the adjustable one."
QUESTIONS = ("show me the email reply to priya", "the email reply to priya please")
# The reply Gmail refuses (part c of the walk): the words that come back on "Try again".
REFUSED = "Hi Priya, one more thing: it comes in black only."
REFUSED_QUESTION = "and tell her it only comes in black"


def _the_reply_turn() -> tuple:
    return (
        ("shopify_find_customer", {"query": "Priya Raman"}),
        ("gmail_search", {"query": "cap"}),
        ("gmail_search", {"query": "newer_than:1d"}),
        ("shopify_list_orders", {"days": 1}),
        ("gmail_send_reply", {"thread_id": PRIYAS_THREAD, "body": REPLY}),
    )


def _slow_provider(runtime):
    """The scripted model, taking its time between calls and saying which one is running."""
    from experience.harness import RecordingProvider, _key, said_in

    class Slow(RecordingProvider):
        async def turn(self, session_id, text):
            from app.providers.base import TurnResult
            from app.tools.dispatch import dispatch

            self.calls.append(text)
            script = self._scripts.get(_key(said_in(text)))
            if script is None:
                return TurnResult(text=self.reply, session_id=session_id)
            tools, reply = script
            session = self.runtime.sessions.get_or_create(session_id)
            calls: list = []
            for name, args in tools:
                session.set_state("CHECKING EMAIL" if name.startswith("gmail_") else "CHECKING SHOPIFY", name)
                await asyncio.sleep(0.9)
                await dispatch(name, dict(args), session=session, timeout_s=10, calls=calls)
            session.set_state("THINKING", "")
            return TurnResult(text=reply, tool_calls=calls, session_id=session_id)

    provider = Slow(reply="Done.")
    provider.runtime = runtime
    for question in QUESTIONS:
        provider.will(question, *_the_reply_turn(), reply="The reply to Priya is ready: hold it to send.")
    provider.will(REFUSED_QUESTION, ("gmail_send_reply", {"thread_id": PRIYAS_THREAD, "body": REFUSED}),
                  reply="Ready: hold it to send.")
    return provider


async def _run(out: str) -> tuple[dict, list[str]]:
    from experience.fixtures import data

    port = browser._free_port()
    server, task, _store = await browser.serve_fixture_world(port)
    from app.main import app

    runtime = app.state.runtime
    runtime.provider = _slow_provider(runtime)
    gmail = runtime.gmail
    thread = data.BY_THREAD[PRIYAS_THREAD]
    kept = list(thread.messages)
    sent: list[str] = []

    def send_message(raw: str, thread_id: str | None) -> dict:
        """The one send the walk makes, taken as Gmail takes it: into the thread, labelled SENT —
        and the refused one refused, as Gmail answers a 4xx with a reason."""
        from app.clients.gmail import GmailRefused

        parsed = message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)
        if REFUSED in parsed.get_content():
            raise GmailRefused("Recipient address rejected")
        message_id = secrets.token_hex(8)
        sent.append(parsed.get_content())
        target = data.BY_THREAD[str(thread_id)]
        target.messages.append(data.Message(message_id, str(thread_id), str(parsed["From"]), str(parsed["To"]),
                                            str(parsed["Subject"]), parsed.get_content(), 0, 12, ["SENT"]))
        return {"message_id": message_id, "thread_id": str(thread_id)}

    gmail.send_message = send_message
    try:
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", out],
            cwd=browser.ROOT, capture_output=True, text=True, timeout=420,
            env={**os.environ, "CROOKS_CHROMIUM": browser.CHROMIUM},
        )
    finally:
        thread.messages[:] = kept
        del gmail.send_message
        await browser._stop(server, task)
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            return json.loads(line), sent
        except ValueError:
            continue
    return {"ok": False, "checks": [{"name": "flow.js ran", "ok": False, "detail": (result.stdout + result.stderr)[-600:]}]}, sent


async def test_a_question_shows_words_then_only_the_reply_and_one_hold_sends_it_in_a_real_browser():
    ok, why = browser.available()
    if not ok:
        pytest.skip(f"no browser here: {why}")
    out = os.environ.get("FLOW_SHOTS_DIR", "")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
    payload, sent = await _run(out)
    print(json.dumps({"shots": payload.get("shots"), "out": out}))
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("checks"), payload
    assert not failed, json.dumps(failed, indent=1)
    # What left is exactly what was on the card: his words, as edited there, signed off.
    assert len(sent) == 2 and all(REPLY in body and "It fits every size." in body for body in sent), sent
