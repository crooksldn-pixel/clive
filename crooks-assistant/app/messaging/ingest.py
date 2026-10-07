"""What happens to a verified callback after the door has answered it: the channel's adapter says
which messages it stands for, each is stored once, the contact gets a name, and anything not in
English is translated.

Why it exists: WeCom wants an answer within five seconds and retries otherwise (90930), and a
translation takes longer than that. So the door answers at once and this runs after it, on its
own, with no tool authority and no turn: it can store and translate, and nothing else.

What it promises:
- A message is stored before anything slow is tried, so a translation that fails or a nickname
  WeCom will not give never loses the message itself.
- A message is translated once, when it arrives; failing that it says its translation is missing.
- Failures are logged by kind and count only: no words, no names, no ids.
- The tasks it starts are kept until they end, and at most MAX_RUNNING run at once; past that a
  callback is still stored by the next one that reads the channel (WeCom's cursor), so nothing is
  lost by being turned away here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.messaging import translate
from app.messaging.adapter import Adapter, Failure, Inbound, Received
from app.messaging.models import Message, Thread
from app.messaging.store import store

log = logging.getLogger("crooks.messaging")

MAX_RUNNING = 4
_RUNNING: set[asyncio.Task] = set()
COUNTS: dict[str, int] = {"stored": 0, "repeats": 0, "translated": 0, "untranslated": 0, "failed_sends": 0, "errors": 0}


def start(adapter: Adapter, inbound: Inbound) -> bool:
    """Run `process` after the door has answered. False when too many are already running."""
    if len([t for t in _RUNNING if not t.done()]) >= MAX_RUNNING:
        log.info("messaging: a %s callback was left for the next read (busy)", adapter.channel)
        return False
    task = asyncio.get_running_loop().create_task(process(adapter, inbound), name=f"messaging-{adapter.channel}")
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    return True


async def settle() -> None:
    """Wait for every callback being processed (the tests, and shutdown)."""
    while _RUNNING:
        await asyncio.gather(*list(_RUNNING), return_exceptions=True)


async def process(adapter: Adapter, inbound: Inbound) -> dict[str, Any]:
    """Store, name and translate what one callback stands for. Never raises."""
    try:
        items = await adapter.receive(inbound)
    except Exception as exc:  # noqa: BLE001 - said by kind, and the next callback reads on from the cursor
        COUNTS["errors"] += 1
        log.info("messaging: a %s callback could not be read (%s)", adapter.channel, getattr(exc, "kind", type(exc).__name__))
        return {"stored": 0, "error": True}
    fresh: list[tuple[Thread, Message]] = []
    for item in items:
        if isinstance(item, Failure):
            if store.mark_failed(item.thread.chat_id, item.remote_id, item.reason):
                COUNTS["failed_sends"] += 1
            continue
        if isinstance(item, Received) and _keep(item):
            fresh.append((item.thread, item.message))
    await _name(adapter, [t for t, _ in fresh])
    for thread, message in fresh:
        if message.translation_state == "pending":
            english, state, label = await translate.to_english(message.text)
            store.update_translation(thread.chat_id, message.message_id, english=english, state=state, label=label)
            COUNTS["translated" if state == "done" else "untranslated"] += 1
    return {"stored": len(fresh)}


def _keep(item: Received) -> bool:
    message = item.message
    message.language = translate.language_of(message.text)
    if translate.needs_translation(message.language):
        message.translation_state, message.english = "pending", ""
    else:
        message.translation_state, message.english = "not_needed", message.text
    store.upsert(item.thread)
    if store.add(item.thread, message):
        COUNTS["stored"] += 1
        return True
    COUNTS["repeats"] += 1
    return False


async def _name(adapter: Adapter, threads: list[Thread]) -> None:
    unnamed = {t.chat_id: t for t in threads if not t.who and not (store.thread(t.chat_id) or t).who}
    if not unnamed:
        return
    try:
        names = await adapter.names(list(unnamed.values()))
    except Exception:  # noqa: BLE001 - a thread without a name still has its messages
        return
    for thread in unnamed.values():
        if names.get(thread.contact):
            thread.who = names[thread.contact]
            store.upsert(thread)
