"""From the question to the action, in a real browser at a phone's and the tablet's sizes (DEC-069).

`scripts/browser/flow.js` drives the page against the real backend on the golden world and checks
what George sees when he asks for a reply: words saying what CLIVE is doing while it works and no
card of any search, then the reply and nothing else; and the reply as one card whose words he edits
with real keystrokes and sends with one hold. And a list he asks for out loud has Next beside it,
as the Orders icon's list does. And [focus, DEC-073] what he asks for always shows ("show me today's
orders and open 1940" is both), and what CLIVE adds unasked is about the same customer: David's
email with his order, its tracking and his Instagram message, and nobody else's. This file starts that backend, scripts the model for
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
# Part d of the walk: a list asked for out loud, then Next.
LIST_QUESTION = "show me today's orders"
# [focus, DEC-073] Parts e and f: the model names what he asked for (`asked_for`).
TWO_PART_QUESTION = "show me today's orders and open 1940"
HIS_EMAIL_QUESTION = "show me david's email"
DAVIDS_THREAD = "58361c4d87dfeee5"      # "Where is 1939?"
MIAS_THREAD = "aa70d3f83dbef06e"        # somebody else's email today


def _the_reply_turn() -> tuple:
    return (
        ("shopify_find_customer", {"query": "Priya Raman"}),
        ("gmail_search", {"query": "cap"}),
        ("gmail_search", {"query": "newer_than:1d"}),
        ("shopify_list_orders", {"days": 1}),
        ("gmail_send_reply", {"thread_id": PRIYAS_THREAD, "body": REPLY}),
    )


def _instagram(who: str, text: str) -> str:
    """[focus] A conversation on Instagram, kept as the webhook keeps one: invented, in the golden world."""
    import time

    from app.messaging import instagram as channel
    from app.messaging.models import Message
    from app.messaging.store import store

    thread = channel.dm_thread(f"ig-fixture-{who}", "ig-account-fixture")
    thread.who = who
    store.upsert(thread)
    store.add(thread, Message(message_id=f"m_{time.time_ns()}", chat_id=thread.chat_id, direction="in", origin="contact",
                              text=text, at=time.time() - 600, language="en", english=text,
                              translation_state="not_needed", remote_id=f"igmid.fixture{time.time_ns()}"))
    return thread.chat_id


def _his_email_turn(chat_id: str) -> tuple:
    """[focus] Everyone's email today, today's orders, his email (what he asked for), Mia's email, his
    order with its tracking, the Instagram conversations, and his."""
    from experience.fixtures import data

    return (
        ("gmail_search", {"query": "newer_than:1d"}),
        ("shopify_list_orders", {"days": 1}),
        ("gmail_read_thread", {"thread_id": DAVIDS_THREAD}),
        ("gmail_read_thread", {"thread_id": MIAS_THREAD}),
        ("shopify_order_detail", {"order_id": data.BY_NAME["#1939"].order_id}),
        ("messages_recent", {}),
        ("message_thread", {"chat_id": chat_id}),
        ("asked_for", {"records": [DAVIDS_THREAD]}),
    )


def _slow_provider(runtime, davids_chat: str = ""):
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
    provider.will(LIST_QUESTION, ("shopify_list_orders", {"days": 1}), reply="Today's orders.")
    from experience.fixtures import data

    provider.will(TWO_PART_QUESTION, ("shopify_list_orders", {"days": 1}),
                  ("shopify_order_detail", {"order_id": data.BY_NAME["#1940"].order_id}),
                  ("asked_for", {"records": ["1940"], "lists": ["orders"]}), reply="Three today, and 1940 is open.")
    provider.will(HIS_EMAIL_QUESTION, *_his_email_turn(davids_chat), reply="He asked where 1939 is. It went Royal Mail.")
    return provider


async def _run(out: str, messages_dir: Path) -> tuple[dict, list[str]]:
    from app.messaging.store import store as messages
    from experience.fixtures import data

    port = browser._free_port()
    server, task, _store = await browser.serve_fixture_world(port)
    from app.main import app

    runtime = app.state.runtime
    # [focus] His Instagram message, and somebody else's, in a store of the walk's own.
    messages.configure(messages_dir)
    davids_chat = _instagram("@david.replica", "Did my parcel go out? Order 1939")
    _instagram("@someone.else", "Do you ship to Spain?")
    runtime.provider = _slow_provider(runtime, davids_chat)
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
        messages.configure(None)
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            return json.loads(line), sent
        except ValueError:
            continue
    return {"ok": False, "checks": [{"name": "flow.js ran", "ok": False, "detail": (result.stdout + result.stderr)[-600:]}]}, sent


async def test_a_question_shows_words_then_only_the_reply_and_one_hold_sends_it_in_a_real_browser(tmp_path):
    ok, why = browser.available()
    if not ok:
        pytest.skip(f"no browser here: {why}")
    out = os.environ.get("FLOW_SHOTS_DIR", "")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
    payload, sent = await _run(out, tmp_path / "messaging")
    print(json.dumps({"shots": payload.get("shots"), "out": out}))
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("checks"), payload
    assert not failed, json.dumps(failed, indent=1)
    # What left is exactly what was on the card: his words, as edited there, signed off.
    assert len(sent) == 2 and all(REPLY in body and "It fits every size." in body for body in sent), sent
