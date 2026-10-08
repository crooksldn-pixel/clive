"""The private store of threads and messages, beside CLIVE's other records.

Why it exists: a message from the manufacturer arrives at the public door while nobody is asking
anything; it has to be kept somewhere only CLIVE reads, until the owner asks or CLIVE needs it.

What it promises:
- One folder (`messaging/`, mode 0700) holding one file per thread (`threads/<chat_id>.json`) and
  the channels' read positions (`cursors.json`), every file 0600 and written whole, atomically.
- Messages are kept RETENTION_DAYS (90) and at most MAX_PER_THREAD per thread; older ones are
  pruned on each write and when CLIVE starts, and a thread with nothing left goes too.
- A message is stored once: the channel's own id (or CLIVE's id for one it sent) is its key. A
  message CLIVE sent that the channel echoed to the door first becomes CLIVE's own record (`claim`).
- What a channel says later about a message CLIVE's account sent is kept on it: failed, with the
  channel's reason; delivered; read (`mark_failed`, `mark_delivery`).
- A translation left "pending" past PENDING_LIMIT_S (a restart cut it off) is kept as missing
  when CLIVE starts, so the message never says "still being made" for good.
- Nothing here logs a word, a name or an id.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from app.messaging.models import Message, Thread

log = logging.getLogger("crooks.messaging")

RETENTION_DAYS = 90
MAX_PER_THREAD = 400
_CHAT_ID = re.compile(r"^chat_[0-9a-f]{12,40}$")


class MessageStore:
    def __init__(self, root: Path | None = None, *, clock=time.time) -> None:
        self._root = Path(root) if root else None
        self._lock = threading.RLock()
        self.clock = clock

    def configure(self, root: Path | None) -> None:
        with self._lock:
            self._root = Path(root) if root else None
            if self._root is not None:
                self._ensure()
                self.prune()
                self.expire_pending()

    @property
    def root(self) -> Path | None:
        return self._root

    # ------------------------------------------------------------------ files

    def _ensure(self) -> Path:
        if self._root is None:
            raise RuntimeError("messaging is not set up on this server")
        (self._root / "threads").mkdir(parents=True, exist_ok=True)
        for folder in (self._root, self._root / "threads"):
            try:
                os.chmod(folder, 0o700)
            except OSError:
                log.warning("messaging: could not make its folder private")
        return self._root

    def _write(self, path: Path, data: Any) -> None:
        handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".msg.", suffix=".tmp")
        temporary_path = Path(temporary)
        try:
            os.fchmod(handle, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    def _thread_path(self, chat_id: str) -> Path:
        if not _CHAT_ID.match(str(chat_id or "")):
            raise ValueError("not a thread id")
        return self._ensure() / "threads" / f"{chat_id}.json"

    def _load(self, chat_id: str) -> tuple[Thread, list[Message]] | None:
        path = self._thread_path(chat_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            log.warning("messaging: a thread file could not be read")
            return None
        thread = Thread.from_dict(data.get("thread") or {})
        messages = [Message.from_dict(m) for m in data.get("messages") or [] if isinstance(m, dict)]
        return thread, messages

    def _save(self, thread: Thread, messages: list[Message]) -> None:
        cutoff = self.clock() - RETENTION_DAYS * 86400
        kept = [m for m in messages if m.at >= cutoff][-MAX_PER_THREAD:]
        path = self._thread_path(thread.chat_id)
        if not kept and thread.last_at and thread.last_at < cutoff:
            path.unlink(missing_ok=True)
            return
        self._write(path, {"version": 1, "thread": thread.to_dict(), "messages": [m.to_dict() for m in kept]})

    # ------------------------------------------------------------------ threads

    def thread(self, chat_id: str) -> Thread | None:
        with self._lock:
            try:
                held = self._load(chat_id)
            except ValueError:
                return None
            return held[0] if held else None

    def threads(self) -> list[Thread]:
        """Every thread, the most recent first."""
        with self._lock:
            if self._root is None:
                return []
            out = []
            for path in sorted((self._ensure() / "threads").glob("chat_*.json")):
                held = self._load(path.stem)
                if held:
                    out.append(held[0])
        return sorted(out, key=lambda t: t.last_at, reverse=True)

    def upsert(self, thread: Thread) -> Thread:
        """Keep this thread, with the name and contact as the channel gave them now; its
        messages are untouched."""
        with self._lock:
            held = self._load(thread.chat_id)
            if held is None:
                self._save(thread, [])
                return thread
            current, messages = held
            if thread.who:
                current.who = thread.who
            self._save(current, messages)
            return current

    # ------------------------------------------------------------------ messages

    def messages(self, chat_id: str, *, limit: int = 50) -> list[Message]:
        with self._lock:
            try:
                held = self._load(chat_id)
            except ValueError:
                return []
        if not held:
            return []
        return held[1][-max(1, int(limit)):]

    def add(self, thread: Thread, message: Message) -> bool:
        """Store one message in its thread (made if new). False, and nothing written, when the
        channel's id or CLIVE's id for it is already held: a callback WeCom sent twice is one
        message."""
        with self._lock:
            held = self._load(thread.chat_id)
            current, messages = held if held else (thread, [])
            for existing in messages:
                if (message.remote_id and existing.remote_id == message.remote_id) or (
                        message.client_id and existing.client_id == message.client_id):
                    return False
            messages.append(message)
            messages.sort(key=lambda m: (m.at, m.stored_at))
            current.last_at = max(current.last_at, message.at)
            if message.direction == "in":
                if message.at >= current.last_in_at:
                    current.last_in_at, current.last_in_id = message.at, message.message_id
                    current.sends_since_in = 0
                    if message.language:
                        current.last_in_language = message.language
            elif message.origin == "clive" and message.status == "sent" and message.at >= current.last_in_at:
                current.sends_since_in += 1
            self._save(current, messages)
            return True

    def claim(self, thread: Thread, message: Message) -> bool:
        """Record a message CLIVE sent. The channel may have told the door about it first, as an echo
        of what the account sent (Instagram's is_echo), under the same channel id: that record
        becomes CLIVE's own, so the send is proved by its client id whichever arrived first. False
        when CLIVE's own record of it is already held."""
        with self._lock:
            held = self._load(thread.chat_id)
            if held is not None and message.remote_id:
                current, messages = held
                for index, existing in enumerate(messages):
                    if existing.remote_id == message.remote_id and existing.direction == "out":
                        if existing.origin == "clive":
                            return False
                        message.delivery = existing.delivery
                        messages[index] = message
                        self._save(current, messages)
                        return True
        return self.add(thread, message)

    def mark_delivery(self, chat_id: str, remote_id: str, state: str, *, and_before: bool = False) -> bool:
        """The channel said a message CLIVE's account sent was delivered or read (WhatsApp's statuses,
        Instagram's messaging_seen, which names the newest message read: `and_before` marks the
        ones sent before it too). Never moves backwards; a message it does not know is left alone."""
        rank = {"": 0, "delivered": 1, "read": 2}
        if state not in rank or not remote_id:
            return False
        with self._lock:
            held = self._load(chat_id)
            if not held:
                return False
            thread, messages = held
            target = next((m for m in messages if m.direction == "out" and m.remote_id == remote_id), None)
            if target is None:
                return False
            changed = False
            for message in messages:
                hit = message is target or (and_before and message.direction == "out" and message.at <= target.at)
                if hit and message.status == "sent" and rank.get(message.delivery, 0) < rank[state]:
                    message.delivery = state
                    changed = True
            if changed:
                self._save(thread, messages)
            return changed

    def message(self, chat_id: str, message_id: str) -> Message | None:
        """One message, by CLIVE's own id for it."""
        for message in self.messages(chat_id, limit=MAX_PER_THREAD):
            if message.message_id == message_id:
                return message
        return None

    def outgoing(self, chat_id: str, client_id: str) -> Message | None:
        """CLIVE's own outgoing message, by the id CLIVE gave it when the card was prepared."""
        for message in self.messages(chat_id, limit=MAX_PER_THREAD):
            if message.direction == "out" and message.client_id == client_id:
                return message
        return None

    def mark_failed(self, chat_id: str, remote_id: str, reason: str) -> bool:
        """The channel said later that a message it accepted did not arrive (WeCom's
        msg_send_fail, WhatsApp's "failed" status): it stays in the thread, marked failed, with the
        channel's reason."""
        with self._lock:
            held = self._load(chat_id)
            if not held:
                return False
            thread, messages = held
            for message in messages:
                if message.direction == "out" and remote_id and message.remote_id == remote_id:
                    message.status, message.fail_reason = "failed", str(reason)[:200]
                    self._save(thread, messages)
                    return True
        return False

    def update_translation(self, chat_id: str, message_id: str, *, english: str, state: str, label: str) -> bool:
        with self._lock:
            held = self._load(chat_id)
            if not held:
                return False
            thread, messages = held
            for message in messages:
                if message.message_id == message_id:
                    message.english, message.translation_state, message.translation = english, state, label
                    self._save(thread, messages)
                    return True
        return False

    def expire_pending(self) -> int:
        """Keep as missing every translation still "pending" past PENDING_LIMIT_S: nothing is making
        it any more. Run when CLIVE starts. Returns how many it marked."""
        marked = 0
        with self._lock:
            if self._root is None:
                return 0
            now = self.clock()
            for path in (self._ensure() / "threads").glob("chat_*.json"):
                held = self._load(path.stem)
                if not held:
                    continue
                thread, messages = held
                stuck = [m for m in messages if m.translation_state == "pending" and m.translation_now(now) == "missing"]
                for message in stuck:
                    message.translation_state, message.english, message.translation = "missing", "", ""
                if stuck:
                    marked += len(stuck)
                    self._save(thread, messages)
        if marked:
            log.info("messaging: %d translation(s) a restart cut off are now marked missing", marked)
        return marked

    # ------------------------------------------------------------------ cursors

    def cursor(self, key: str) -> str:
        with self._lock:
            return str(self._cursors().get(str(key)) or "")

    def set_cursor(self, key: str, value: str) -> None:
        with self._lock:
            cursors = self._cursors()
            cursors[str(key)] = str(value)
            self._write(self._ensure() / "cursors.json", cursors)

    def _cursors(self) -> dict[str, str]:
        if self._root is None:
            return {}
        try:
            data = json.loads((self._ensure() / "cursors.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ retention

    def prune(self) -> int:
        """Drop what is past RETENTION_DAYS everywhere. Returns how many messages went."""
        dropped = 0
        with self._lock:
            if self._root is None:
                return 0
            cutoff = self.clock() - RETENTION_DAYS * 86400
            for path in (self._ensure() / "threads").glob("chat_*.json"):
                held = self._load(path.stem)
                if not held:
                    continue
                thread, messages = held
                old = [m for m in messages if m.at < cutoff]
                if old or (not messages and thread.last_at and thread.last_at < cutoff):
                    dropped += len(old)
                    self._save(thread, messages)
        return dropped


store = MessageStore()
