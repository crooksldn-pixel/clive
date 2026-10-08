"""WeChat through WeCom, in Chromium, at the tablet's and a phone's size: what the owner actually sees.

The backend is the real one on loopback. The messages come in through the real public door: a
callback sealed exactly as WeCom seals one (tests/wecom_world.py, WeCom's published example key) is
posted to /hooks/wecom, and the real adapter reads the messages from a stand-in qyapi.weixin.qq.com
with kf/sync_msg. Translation is a stand-in for the model that knows two sentences and fails on the
third, so the screen has to say so. Claude is scripted for the sentences scripts/browser/messages.js
types. The cards are the real presenters', the hold is a real press, and the send is proved by the
stand-in WeCom's msgid. Nothing reaches a network; every name and id is made up.

Skipped, loudly, where there is no browser. Set CLIVE_MESSAGES_SHOTS to a folder to keep the
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
from tests import wecom_world

SCRIPT = ROOT / "scripts" / "browser" / "messages.js"

SAID = {
    "recent": "What has the factory sent on WeChat?",
    "link": "That's Jessica, our manufacturer",
    "thread": "Show me Jessica's conversation",
    "reply": "Tell her Monday is fine and to send photos of the sample",
}
# What they wrote, and the English the stand-in model gives (none for the third: it fails).
WROTE = (
    ("样衣下周一寄出，大货面料已经到了。", "The sample ships next Monday; the bulk fabric has arrived."),
    ("请确认尺码表。", "Please confirm the size chart."),
    ("大货什么时候出？", None),
)
REPLY_EN = "Monday is fine. Please send photos of the sample before it ships."
REPLY_ZH = "周一可以。寄出前请发样衣照片。"


async def _serve(port: int):
    import uvicorn

    from app.main import app
    from app.session.manager import SessionManager
    from experience.harness import RecordingProvider

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        await asyncio.sleep(0.05)
        if server.started:
            break
    runtime = app.state.runtime
    runtime.provider = RecordingProvider()
    runtime.provider.runtime = runtime
    runtime.settings = runtime.settings.model_copy(update={
        "writes_enabled": True, "allowed_logins": "owner@example.com", "writes_local_owner": False, "tailscale_verify": False,
    })
    runtime.sessions = SessionManager()
    app.state.allowed_logins = runtime.allowed_logins
    return server, task, runtime


async def _model(system: str, text: str, **_kw) -> str:
    """The stand-in for Claude's translation: two sentences it knows; anything else fails."""
    for chinese, english in WROTE:
        if chinese in text and english:
            return english
    raise RuntimeError("the stand-in model has no translation for this")


def _script(provider) -> None:
    first = lambda calls: calls[0].result["threads"][0]["chat_id"]  # noqa: E731 - read from the turn's own search
    provider.will(SAID["recent"], ("messages_recent", {}),
                  reply="Jessica Factory wrote three times today: the sample ships Monday and the fabric is in.")
    provider.will(SAID["link"], ("messages_recent", {}),
                  ("message_contact", lambda calls: {"chat_id": first(calls), "person": "Jessica"}),
                  reply="Noted: that WeChat conversation is Jessica's.")
    provider.will(SAID["thread"], ("messages_recent", {"person": "Jessica"}),
                  ("message_thread", lambda calls: {"chat_id": first(calls)}),
                  reply="Here's Jessica's conversation. WeChat will take a reply for another two days.")
    provider.will(SAID["reply"], ("messages_recent", {"person": "Jessica"}),
                  ("message_reply", lambda calls: {"chat_id": first(calls), "english": REPLY_EN, "chinese": REPLY_ZH}),
                  reply="Here it is in Chinese and English. Hold the card to send it.")


async def _arrive(port: int, fake) -> None:
    """Three messages from Jessica, the way WeCom delivers them: a sealed callback at the public
    door, then kf/sync_msg. The door answers at once; the store and the translations follow."""
    fake.inbox = [wecom_world.kf_text(chinese, msgid=f"wxmsg{n}") for n, (chinese, _en) in enumerate(WROTE)]
    query, body = wecom_world.kf_event()
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        answered = await client.post("/hooks/wecom", params=query, content=body)
        assert (answered.status_code, answered.content) == (200, b"")
        unsigned = await client.post("/hooks/wecom", content=body)
        assert (unsigned.status_code, unsigned.content) == (403, b"")
    for _ in range(100):
        await ingest.settle()
        threads = store.threads()
        if threads and len(store.messages(threads[0].chat_id)) == len(WROTE):
            break
        await asyncio.sleep(0.05)


async def test_wechat_messages_in_a_real_browser(monkeypatch, tmp_path):
    ok, why = available()
    if not ok:
        pytest.skip(f"browser checks need a browser: {why}")
    fake = wecom_world.install(monkeypatch)
    port = _free_port()
    server, task, runtime = await _serve(port)
    out = os.environ.get("CLIVE_MESSAGES_SHOTS", "")
    store.configure(tmp_path / "messaging")
    people.configure(tmp_path / "people.json")
    try:
        people.note({"name": "Jessica", "kind": "contact", "role": "Manufacturer"})
        translate.bind(_model)
        await _arrive(port, fake)
        _script(runtime.provider)
        result = await asyncio.to_thread(
            subprocess.run, ["node", str(SCRIPT), f"http://127.0.0.1:{port}", out],
            cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
        )
        threads = store.threads()
        mine = [m for m in store.messages(threads[0].chat_id) if m.origin == "clive"] if threads else []
    finally:
        await _stop(server, task)
        translate.bind(None)
        store.configure(None)
        people.configure(None)
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
    # Nine checks at each size (the ninth since 8 Oct: WeChat's name for her beside his card's on the
    # reply card), and the phone's tenth: the conversation after its send.
    assert len(payload["checks"]) == 9 + 10, [c["name"] for c in payload["checks"]]
    # Only the phone's hold sent anything: one message, Chinese first, through customer service.
    sends = [body for path, _params, body in fake.calls if path == "/kf/send_msg"]
    assert len(sends) == 1 and sends[0]["text"]["content"] == f"{REPLY_ZH}\n\n{REPLY_EN}", sends
    assert len(mine) == 1 and mine[0].status == "sent" and mine[0].remote_id == sends[0]["msgid"]
