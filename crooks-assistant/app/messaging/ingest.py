"""What happens to a verified callback: what it carries itself is stored before the door answers,
and after the door has answered the channel's adapter reads whatever else it stands for, each
message is stored once, the contact gets a name, and anything not in English is translated.

Why it exists: WeCom wants an answer within five seconds and retries otherwise (90930), Meta wants
a 200 or it retries for days, and a translation takes longer than that. So the door answers at once and the slow part runs after it,
on its own, with no tool authority and no turn: it can store and translate, and nothing else.

What it promises:
- A message is stored before anything slow is tried, so a translation that fails or a nickname
  WeCom will not give never loses the message itself.
- What a callback carries itself (a team member's message to the app; everything WhatsApp and
  Instagram send: no call to make, so it is cheap) is stored at the door, before the channel is
  answered, however busy the server is; only its translation, and asking the channel what a new
  contact is called, wait (review note 5, 8 Oct).
- A message is translated once, when it arrives or as soon as a run is free; failing that it says
  its translation is missing. Nothing waits for a translation at shutdown: one a restart cuts off
  is left "pending", which reads as missing once PENDING_LIMIT_S has passed and is kept so at the
  next start (app/messaging/models.py, store.py `expire_pending`).
- Failures are logged by kind and count only: no words, no names, no ids.
- The tasks it starts are kept until they end, and at most MAX_RUNNING run at once. Past that, a
  WeChat callback's messages are read by the next callback that reads the channel (WeCom's
  cursor), and the translations of what a callback carried are made by a run already going: each
  run, before it ends, translates every one left waiting. Nothing is lost by being turned away.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections import OrderedDict
from typing import Any

from app.messaging import translate
from app.messaging.adapter import Adapter, Delivery, Failure, Inbound, Received
from app.messaging.models import Message, Thread
from app.messaging.store import store

log = logging.getLogger("crooks.messaging")

MAX_RUNNING = 4
# Translations waiting for a run, oldest first (message id → chat id). Past this many the oldest
# are let go: they read as missing once PENDING_LIMIT_S has passed, like any that is not made.
MAX_WAITING = 200
_RUNNING: set[asyncio.Task] = set()
_WAITING: OrderedDict[str, str] = OrderedDict()
# Set on the Inbound a run is handed when the door has already stored what the callback carried,
# with the conversations it stored into (so the run can ask the channel what they are called).
CARRIED_STORED = "_carried_stored"
CARRIED_CHATS = "_carried_chats"
COUNTS: dict[str, int] = {"stored": 0, "repeats": 0, "translated": 0, "untranslated": 0, "failed_sends": 0, "errors": 0}


def start(adapter: Adapter, inbound: Inbound) -> bool:
    """At the door: store what the callback carries now, then run the rest (`process`) after the
    door has answered. False when too many runs are already going; what it carried is stored all
    the same, and its translation is made by one of them."""
    carried = _take_carried(adapter, inbound)
    _wait_for_translation(carried)
    if len([t for t in _RUNNING if not t.done()]) >= MAX_RUNNING:
        log.info("messaging: a %s callback was left for the next read (busy); %d stored at the door",
                 adapter.channel, len(carried))
        return False
    chats = ",".join(dict.fromkeys(thread.chat_id for thread, _ in carried))
    handed = dataclasses.replace(inbound, fields={**inbound.fields, CARRIED_STORED: "1", CARRIED_CHATS: chats})
    task = asyncio.get_running_loop().create_task(process(adapter, handed), name=f"messaging-{adapter.channel}")
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    return True


def take(adapter: Adapter, items: list[Received]) -> int:
    """Keep messages a read brought (Instagram's conversations, read when the owner asked), as the
    door keeps what a callback carried: each once, by the channel's own id, with its translation
    made after, by a run of its own. Returns how many were new. Never raises."""
    kept: list[tuple[Thread, Message]] = []
    for item in items:
        try:
            if isinstance(item, Received) and _keep(item):
                kept.append((item.thread, item.message))
        except Exception as exc:  # noqa: BLE001 - one message; the rest are still kept
            COUNTS["errors"] += 1
            log.info("messaging: a message a %s read brought could not be kept (%s)", adapter.channel, type(exc).__name__)
    _wait_for_translation(kept)
    if _WAITING and len([t for t in _RUNNING if not t.done()]) < MAX_RUNNING:
        task = asyncio.get_running_loop().create_task(_translate_waiting(), name=f"messaging-{adapter.channel}-read")
        _RUNNING.add(task)
        task.add_done_callback(_RUNNING.discard)
    return len(kept)


async def settle() -> None:
    """Wait for every callback being processed. For the tests: nothing calls it at shutdown (see
    the header on what a restart leaves)."""
    while _RUNNING:
        await asyncio.gather(*list(_RUNNING), return_exceptions=True)


async def process(adapter: Adapter, inbound: Inbound) -> dict[str, Any]:
    """Store, name and translate what one callback stands for, then every translation still
    waiting. Never raises."""
    fresh = [] if inbound.fields.get(CARRIED_STORED) else _take_carried(adapter, inbound)
    error = False
    try:
        items = await adapter.receive(inbound)
    except Exception as exc:  # noqa: BLE001 - said by kind, and the next callback reads on from the cursor
        COUNTS["errors"] += 1
        error = True
        items = []
        log.info("messaging: a %s callback could not be read (%s)", adapter.channel, getattr(exc, "kind", type(exc).__name__))
    for item in items:
        if isinstance(item, Failure):
            if store.mark_failed(item.thread.chat_id, item.remote_id, item.reason):
                COUNTS["failed_sends"] += 1
            continue
        if isinstance(item, Received) and _keep(item):
            fresh.append((item.thread, item.message))
    named = [t for t, _ in fresh]
    for chat_id in filter(None, inbound.fields.get(CARRIED_CHATS, "").split(",")):
        held = store.thread(chat_id)
        if held is not None:
            named.append(held)
    await _name(adapter, named)
    _wait_for_translation(fresh)
    await _translate_waiting()
    out: dict[str, Any] = {"stored": len(fresh)}
    if error:
        out["error"] = True
    return out


def _take_carried(adapter: Adapter, inbound: Inbound) -> list[tuple[Thread, Message]]:
    """Store what the callback itself carries: messages, and what became of the ones CLIVE sent
    (failed, delivered, read). Never raises: the door answers whatever happens."""
    try:
        items = adapter.carried(inbound)
    except Exception as exc:  # noqa: BLE001 - said by kind; the door still answers
        COUNTS["errors"] += 1
        log.info("messaging: what a %s callback carried could not be read (%s)", adapter.channel, type(exc).__name__)
        return []
    kept: list[tuple[Thread, Message]] = []
    for item in items:
        try:
            if isinstance(item, Received):
                if _keep(item):
                    kept.append((item.thread, item.message))
            elif isinstance(item, Failure):
                if store.mark_failed(item.thread.chat_id, item.remote_id, item.reason):
                    COUNTS["failed_sends"] += 1
            elif isinstance(item, Delivery):
                store.mark_delivery(item.thread.chat_id, item.remote_id, item.state, and_before=item.and_before)
        except Exception as exc:  # noqa: BLE001 - one item; the rest are still kept
            COUNTS["errors"] += 1
            log.info("messaging: one thing a %s callback carried could not be stored (%s)", adapter.channel,
                     type(exc).__name__)
    return kept


def _wait_for_translation(stored: list[tuple[Thread, Message]]) -> None:
    for thread, message in stored:
        if message.translation_state == "pending":
            _WAITING[message.message_id] = thread.chat_id
    while len(_WAITING) > MAX_WAITING:
        _WAITING.popitem(last=False)


async def _translate_waiting() -> None:
    """Translate every message waiting, oldest first, including those another callback stored
    while every run was busy. The last thing a run does: a run not yet finished always looks again,
    so nothing the door stored while it was going is left behind."""
    while _WAITING:
        message_id, chat_id = _WAITING.popitem(last=False)
        try:
            message = store.message(chat_id, message_id)
            if message is None or message.translation_now() != "pending":
                continue
            english, state, label = await translate.to_english(message.text)
            # [channels] Handed back unchanged: English after all, so an English reply is the right one.
            language = "en" if translate.english_after_all(message.text, state) else ""
            store.update_translation(chat_id, message_id, english=english, state=state, label=label, language=language)
            COUNTS["translated" if state == "done" else "untranslated"] += 1
        except Exception as exc:  # noqa: BLE001 - one message's translation; the rest still go
            COUNTS["errors"] += 1
            log.info("messaging: a translation could not be kept (%s)", type(exc).__name__)


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
