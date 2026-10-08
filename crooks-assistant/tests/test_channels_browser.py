"""WhatsApp and Instagram direct messages, in Chromium, at the tablet's and a phone's size: what the
owner actually sees.

The backend is the real one on loopback. The messages come in through the real public doors: a
WhatsApp message from a supplier who writes Portuguese, and an Instagram message from a customer,
each signed exactly as Meta signs one (tests/meta_world.py) and posted to /hooks/whatsapp and
/hooks/instagram. The stand-in Meta answers the calls CLIVE makes (Instagram's @handle, its empty
conversations API, the send), and translation is a stand-in for the model that knows the one
Portuguese sentence. Claude is scripted for the sentences scripts/browser/channels.js types. The
cards are the real presenters', the hold is a real press, the send is proved by the stand-in's
message id, and WhatsApp's "read" arrives at the door, signed, as Meta would send it. Nothing reaches
a network; every name, number and id is made up.

Skipped, loudly, where there is no browser. Set CLIVE_CHANNELS_SHOTS to a folder to keep the
screenshots.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess

import httpx
import pytest

from app.messaging import ingest, translate
from app.messaging.store import store
from app.people.store import people
from experience.browser import CHROMIUM, ROOT, _free_port, _stop, available
from tests import meta_world
from tests.test_messages_browser import _serve

SCRIPT = ROOT / "scripts" / "browser" / "channels.js"

SAID = {
    "whatsapp": "Any WhatsApp messages?",
    "link": "That's Ana, our knitwear supplier",
    "reply": "Tell Ana thank you, and to send it on Friday",
    "thread": "Show me Ana's conversation",
    "instagram": "Anything on Instagram?",
}
WROTE_PT = "Olá, a amostra está pronta para envio amanhã."
WROTE_EN = "Hello, the sample is ready to ship tomorrow."
REPLY_EN = "Thank you. Please send it on Friday."
REPLY_PT = "Obrigado. Por favor, envie na sexta-feira."
DM = "Is the black hoodie back in stock in medium?"


async def _model(system: str, text: str, **_kw) -> str:
    """The stand-in for Claude's translation: the one Portuguese sentence it knows."""
    if WROTE_PT in text:
        return WROTE_EN
    raise RuntimeError("the stand-in model has no translation for this")


def _script(provider) -> None:
    first = lambda calls: calls[0].result["threads"][0]["chat_id"]  # noqa: E731 - read from the turn's own search
    provider.will(SAID["whatsapp"], ("messages_recent", {"channel": "whatsapp"}),
                  reply="Ana Fixture wrote on WhatsApp: the sample is ready to ship tomorrow.")
    provider.will(SAID["link"], ("messages_recent", {"channel": "whatsapp"}),
                  ("message_contact", lambda calls: {"chat_id": first(calls), "person": "Ana"}),
                  reply="Noted: that WhatsApp conversation is Ana's.")
    provider.will(SAID["reply"], ("messages_recent", {"person": "Ana"}),
                  ("message_reply", lambda calls: {"chat_id": first(calls), "english": REPLY_EN, "translated": REPLY_PT}),
                  reply="Here it is in Portuguese and English. Hold the card to send it.")
    provider.will(SAID["thread"], ("messages_recent", {"person": "Ana"}),
                  ("message_thread", lambda calls: {"chat_id": first(calls)}),
                  reply="Here's Ana's conversation.")
    provider.will(SAID["instagram"], ("messages_recent", {"channel": "instagram"}),
                  reply="One customer asked about the black hoodie in medium.")


async def _arrive(port: int) -> None:
    """One WhatsApp message and one Instagram message, each at its own door, signed as Meta signs."""
    whatsapp_body = meta_world.raw(meta_world.wa_text(WROTE_PT, msg_id="wamid.BROWSER1"))
    instagram_body = meta_world.raw(meta_world.ig_text(DM, mid="igmid.BROWSER1"))
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        answered = await client.post("/hooks/whatsapp", content=whatsapp_body, headers=meta_world.sign(whatsapp_body))
        assert (answered.status_code, answered.content) == (200, b"")
        unsigned = await client.post("/hooks/whatsapp", content=whatsapp_body)
        assert (unsigned.status_code, unsigned.content) == (403, b"")
        answered = await client.post("/hooks/instagram", content=instagram_body,
                                     headers=meta_world.sign(instagram_body, meta_world.IG_SECRET))
        assert (answered.status_code, answered.content) == (200, b"")
    for _ in range(100):
        await ingest.settle()
        threads = store.threads()
        named = all(t.who for t in threads)
        done = all(m.translation_now() != "pending" for t in threads for m in store.messages(t.chat_id))
        if len(threads) == 2 and named and done:
            break
        await asyncio.sleep(0.05)


async def test_whatsapp_and_instagram_messages_in_a_real_browser(monkeypatch, tmp_path):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    fake = meta_world.install(monkeypatch)
    port = _free_port()
    server, task, runtime = await _serve(port)
    out = os.environ.get("CLIVE_CHANNELS_SHOTS", "")
    from app.clients import instagram

    instagram.configure(state_path=tmp_path / "instagram.json")
    store.configure(tmp_path / "messaging")
    people.configure(tmp_path / "people.json")
    try:
        people.note({"name": "Ana", "kind": "contact", "role": "Knitwear supplier"})
        translate.bind(_model)
        await _arrive(port)
        _script(runtime.provider)
        env = {**os.environ, "CROOKS_CHROMIUM": CHROMIUM, "CLIVE_TEST_META_SECRET": meta_world.APP_SECRET,
               "CLIVE_TEST_WA": json.dumps({"phone": meta_world.PHONE_ID, "waba": meta_world.WABA_ID,
                                            "to": meta_world.SUPPLIER})}
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", out],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env=env,
        )
        await ingest.settle()
        mine = [m for t in store.threads() if t.channel == "whatsapp" for m in store.messages(t.chat_id) if m.origin == "clive"]
    finally:
        await _stop(server, task)
        translate.bind(None)
        store.configure(None)
        people.configure(None)
        instagram.reset()
    payload = None
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    assert payload is not None, (result.stdout + result.stderr)[-1500:]
    failed = [c for c in payload.get("checks") or [] if not c.get("ok")]
    assert payload.get("ok"), "\n".join(f"  - {c['name']} :: {c.get('detail', '')}" for c in failed)
    # Seven checks at each size; the tablet's eighth (nothing sent while the card waits), and the phone's
    # three more (Sent, then read, then its Portuguese a tap away).
    assert len(payload["checks"]) == 8 + 10, [c["name"] for c in payload["checks"]]
    # Only the phone's hold sent anything: one WhatsApp text, Portuguese first, to her number.
    assert [s["text"]["body"] for s in fake.sent] == [f"{REPLY_PT}\n\n{REPLY_EN}"] and fake.sent[0]["to"] == meta_world.SUPPLIER
    assert len(mine) == 1 and mine[0].remote_id == "wamid.SENT1" and mine[0].delivery == "read"
