"""DEC-071's inbox rulings in a real browser (scripts/browser/inbox.js), against the real backend.

The backend is experience/browser.py's: uvicorn on loopback with the golden fixture world. What this
adds is a mailbox that can be changed — the in-memory Gmail of tests/test_gmail_writes.py, bound to
the email writes, so a junk and a send can really happen and be read back — with three emails a
morning brings (two promotions and a customer), two of George's own drafts written in Gmail, and
Mia let in to the team. The owner's model is scripted for two sentences and Mia's assistant for one;
everything the page then does — the cards, the holds, the commits through the engine, the count
after — is the real code. Skipped, and said so, where there is no browser.

Screenshots go to INBOX_SHOTS when it is set, and nowhere otherwise.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess

import pytest

from experience import browser

SCRIPT = browser.ROOT / "scripts" / "browser" / "inbox.js"
OWNER_SESSION = "a1b2c3d4e5f60718"
MIA = "mia@example.com"
PROMO, SEO, CUSTOMER = "18f00000000000b1", "18f00000000000b2", "18f00000000000b3"
LENA, ANA = "18f00000000000c1", "18f00000000000c2"


def _mailbox():
    """The morning's inbox and George's two drafts, in the in-memory Gmail the writes are proven on.
    Gmail refuses to relabel the SEO thread, so a junk of the set is a junk in part."""
    from app.clients.gmail import GmailRefused
    from app.tools import gmail_writes
    from experience.fixtures.data import MIA as MIA_JONES
    from tests.test_gmail_writes import msg
    from tests.test_staff_send_draft import Drafts

    box = Drafts()
    box.threads = {
        PROMO: [msg("p1", from_="Promo Bot <deals@example.net>", subject="WIN A PRIZE", mid="<p1@example.net>", labels=["INBOX", "UNREAD"])],
        SEO: [msg("p2", from_="SEO Expert <seo@example.org>", subject="Rank #1 on Google", mid="<p2@example.org>", labels=["INBOX"])],
        CUSTOMER: [msg("p3", from_=f"Mia Jones <{MIA_JONES.email}>", subject="Order 1938 — can I add to it?", mid="<p3@example.com>", labels=["INBOX"])],
        LENA: [msg("l1", from_="Lena Fixture <lena@example.com>", subject="Sizing question", mid="<l1@example.com>", labels=["INBOX"])],
        ANA: [msg("a1", from_="Ana Fixture <ana@example.com>", subject="Where is my order?", mid="<a1@example.com>", labels=["INBOX"])],
    }
    for thread, to, name, words, token in (
        (LENA, "lena@example.com", "Lena Fixture", "Hi Lena, George here. The medium fits true to size.", "<george-lena@crooksldn.com>"),
        (ANA, "ana@example.com", "Ana Fixture", "Hi Ana, George here. Yours goes out on Monday.", "<george-ana@crooksldn.com>"),
    ):
        subject = "Re: Sizing question" if thread == LENA else "Re: Where is my order?"
        raw = gmail_writes.build_raw(sender="team@crooksldn.com", sender_name="CROOKS", to=to, to_name=name, subject=subject, body=words, token=token)
        box.create_draft(raw, thread)
    real = box.modify_thread

    def modify(thread_id, *, add, remove):
        if thread_id == SEO and "SPAM" in add:
            box.calls.append(("modify", thread_id, tuple(add), tuple(remove)))
            raise GmailRefused("Could not change the thread's labels: refused")
        return real(thread_id, add=add, remove=remove)

    box.modify_thread = modify
    return box


def _mias_assistant(runtime):
    """Mia's CLIVE for the one sentence the browser says: the drafts waiting, then George's one to
    Ana, prepared as a card for her own hold — through the real gate, under her own authority."""
    from app.providers.base import TurnResult
    from app.tools.dispatch import dispatch

    class Scripted:
        async def start(self): pass
        async def stop(self): pass
        async def health(self): return True, "harness"
        async def reset_session(self, session_id): pass
        async def set_system_prompt(self, prompt): pass
        async def interrupt(self, session_id): return True

        async def turn(self, session_id, text):
            session = runtime.sessions.get_or_create(session_id)
            calls: list = []
            await dispatch("gmail_unsent", {}, session=session, timeout_s=10, calls=calls)
            drafts = (calls[-1].result or {}).get("drafts") if calls and calls[-1].ok else []
            thread = next((d["thread_id"] for d in drafts or [] if "ana@" in str(d.get("to") or "")), "")
            await dispatch("gmail_send_draft", {"thread_id": thread}, session=session, timeout_s=10, calls=calls)
            return TurnResult(text="Here is George's draft to Ana, as he wrote it.", tool_calls=calls, session_id=session_id)

    return Scripted()


async def _run(tmp_path) -> tuple[dict, list[dict], list[dict]]:
    from app.actions import engine as engine_module
    from app.analytics import sets
    from app.main import app
    from app.people import access
    from app.people.store import people
    from app.tools import gmail_drafts, gmail_writes
    from app.work.store import work

    port = browser._free_port()
    server, task, _shop = await browser.serve_fixture_world(port)
    try:
        runtime = app.state.runtime
        runtime.provider.runtime = runtime
        box = _mailbox()
        gmail_writes.bind(box, policy=lambda: runtime.settings)
        gmail_drafts.configure(tmp_path / "gmail-drafts.json")

        def the_set(calls):
            # What "the promo emails" are in this conversation: the three a search would have listed.
            session = runtime.sessions.get_or_create(OWNER_SESSION)
            labels = {PROMO: "WIN A PRIZE", SEO: "Rank #1 on Google", CUSTOMER: "Order 1938 — can I add to it?"}
            made = sets.create(session, kind="emails", members=list(labels), label="email: this morning", labels=labels)
            return {"set_id": made.set_id}

        runtime.provider.will("junk the promo emails", ("batch_email_junk", the_set),
                              reply="Two can go to Spam; the one from Mia is a customer's, so it stays.")
        runtime.provider.will("send the draft to lena", ("gmail_unsent", {}), ("gmail_send_draft", {"thread_id": LENA}),
                              reply="Here is your draft to Lena, as you wrote it.")
        people.configure(tmp_path / "people.json")
        access.configure(state_dir=tmp_path / "secret")
        work.configure(tmp_path / "work")
        person, _new = people.note({"name": "Mia", "kind": "staff", "role": "packing and emails", "login": MIA})
        access.ask(person.person_id, MIA)
        access.approve(person.person_id, login=MIA, by="owner", passkey="harness")
        runtime.staff_provider_factory = lambda person: _mias_assistant(runtime)
        runtime.staff_providers.clear()
        shots = os.environ.get("INBOX_SHOTS", "")
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", shots],
            cwd=browser.ROOT, capture_output=True, text=True, timeout=600,
            env={**os.environ, "CROOKS_CHROMIUM": browser.CHROMIUM,
                 "CROOKS_INBOX": json.dumps({"owner_session": OWNER_SESSION, "mia": MIA})},
        )
        ledger = engine_module.current().ledger.read()
        record = work.history()
    finally:
        await browser._stop(server, task)
        people.configure(None)
        work.configure(None)
        access.configure(state_dir=None)
        gmail_drafts.configure(None)
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            return json.loads(line), ledger, record
        except ValueError:
            continue
    return {"ok": False, "checks": [{"name": "the browser run", "ok": False, "detail": (result.stdout + result.stderr)[-800:]}]}, ledger, record


async def test_the_inbox_rulings_work_under_a_finger_on_his_tablet_and_on_mias_phone(tmp_path):
    """Ruling 27: one card, one hold, each thread named, a refusal said per thread. Ruling 34: his
    draft sent as he wrote it on his hold; George's other draft sent by Mia on her own hold, her card
    saying whose words and who sends, and the record saying it was her."""
    ok, why = browser.available()
    if not ok:
        pytest.skip(f"no browser here: {why}")
    payload, ledger, record = await _run(tmp_path)
    failed = [f"{c['name']}: {c.get('detail', '')}" for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("ok") and not failed, "\n".join(failed)
    assert len(payload.get("checks") or []) >= 18
    # Recorded with who held it: the engine's own record names Mia's login on her send.
    sends = [e for e in ledger if e.get("operation") == "gmail_send_draft" and e.get("event") == "EXECUTING"]
    assert sorted(e["caller"] for e in sends) == sorted(["owner@example.com", MIA]), sends
    assert any(r.get("who") == "mia" and r.get("what") == "draft_sent" for r in record), record
    assert "Hi Ana" not in json.dumps(ledger) and "ana@example.com" not in json.dumps(ledger), "nobody's words or address in the record"
