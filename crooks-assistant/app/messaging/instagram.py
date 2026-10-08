"""Instagram direct messages as a messaging channel: what Instagram sends to /hooks/instagram, the
conversations CLIVE can read from Instagram, and a reply the owner held, on the same core as WeChat
and WhatsApp.

Why it exists: George approved Instagram replies (7 October), ready when its keys are stored. CLIVE
already reads the account with its stored token (app/clients/instagram.py, Instagram API with
Instagram Login); this adapter reuses that client and that token, and docs/INSTAGRAM_DMS.md says
what he switches on at Meta and what he must decide.

What it promises:
- verify_inbound: Meta's GET check is answered only for the stored webhook verify token; a POST is
  read only when its X-Hub-Signature-256 is the signature of the body under the Instagram app's
  secret, and no other: WhatsApp's app secret never signs for Instagram.
- carried: each message in the request is stored at the door, once, by Instagram's own id. One the
  account sent (Instagram's echo) is kept as sent from the Instagram app, and becomes CLIVE's own
  record when it is the reply CLIVE sent (app/messaging/store.py `claim`). "Seen" marks what CLIVE
  sent as read.
- sync: the conversations Instagram's API returns, read on request, and stored the same way. What
  the API returned is said exactly, including nothing: Meta returns other people's messages only to
  an app with Advanced Access, and George's has returned none so far (docs/INSTAGRAM_DMS.md).
- A reply goes only within 24 hours of their last message. Instagram's human-agent tag (seven days)
  needs Meta's App Review and is for a person typing the answer; CLIVE does not use it, and refuses
  with plain words instead.
- send returns only Instagram's message id; anything else raises in plain words.
- Nothing here logs a handle, an id or a word.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.clients import instagram
from app.messaging import meta
from app.messaging.adapter import Delivery, Failure, Inbound, Received, Refused, Route, register
from app.messaging.models import Message, Thread, chat_id_for, new_message_id
from app.secrets import keychain

log = logging.getLogger("crooks.messaging")

CHANNEL = "instagram"
ROUTE = "dm"
KIND = "instagram"
WINDOW_S = 24 * 3600
VERIFY_TOKEN = "instagram_webhook_verify_token"
SYNC_CONVERSATIONS = 10
# [channels] How many conversations a read asks Instagram for at once.
SYNC_AT_ONCE = 4
NAMES_AT_ONCE = 10
# An attachment's type as the store keeps it; only text carries words.
KINDS = {"image": "image", "video": "video", "audio": "voice", "file": "file", "share": "share",
         "story_mention": "story_mention", "ig_reel": "reel", "reel": "reel", "ig_post": "share"}


def dm_thread(igsid: str, account: str = "") -> Thread:
    """One thread per person: keyed by their Instagram-scoped id alone, so a message Instagram's
    webhook brought and one its conversations API returned are the same conversation."""
    return Thread(chat_id=chat_id_for(CHANNEL, ROUTE, "", str(igsid)), channel=CHANNEL, route=ROUTE,
                  account=str(account or ""), contact=str(igsid))


def _stored(name: str) -> str:
    try:
        return (keychain.get_optional(name) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has nothing to give
        return ""


def _what(message: dict[str, Any]) -> tuple[str, str]:
    """(kind, words) of one Instagram message: its text, or the kind of thing it carried."""
    words = meta.text(message.get("text"), 2000)
    if words:
        return "text", words
    if message.get("is_unsupported"):
        return "unsupported", ""
    for attachment in meta.items(message.get("attachments")):
        kind = str(attachment.get("type") or "")
        return KINDS.get(kind, kind or "unknown"), ""
    return "unknown", ""


def _seconds(value: Any) -> float:
    """Instagram's webhook times are milliseconds; its API's are ISO dates."""
    if isinstance(value, (int, float)) or str(value or "").isdigit():
        number = float(value)
        return number / 1000.0 if number > 1e11 else number
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        return time.time()


async def _read_threads(ids: list[str]) -> list[dict[str, Any]]:
    """[channels] Each conversation's messages, SYNC_AT_ONCE read at a time and given back in the order
    asked: ten read one after another could outlast the tool's own time (review note 4). The first
    failure stops the rest and is raised as it is."""
    gate = asyncio.Semaphore(SYNC_AT_ONCE)

    async def one(conversation_id: str) -> dict[str, Any]:
        async with gate:
            return await instagram.thread(conversation_id)

    tasks = [asyncio.ensure_future(one(i)) for i in ids]
    try:
        return list(await asyncio.gather(*tasks))
    finally:
        for task in tasks:
            task.cancel()


class InstagramAdapter:
    channel = CHANNEL
    label = "Instagram"
    max_body = meta.MAX_BODY_BYTES

    def configured(self) -> bool:
        return bool(instagram.token())

    # ------------------------------------------------------------------ the door

    def verify_inbound(self, method: str, query: Mapping[str, str], body: bytes,
                       headers: Mapping[str, str] | None = None) -> Inbound:
        verify_token = _stored(VERIFY_TOKEN)
        # [channels] The Instagram app's secret alone: Instagram Login's webhooks are signed with it.
        # WhatsApp lives on another Meta app, whose secret never speaks for Instagram (review note 3).
        secrets = [_stored(instagram.APP_SECRET_KEY)]
        if not (verify_token and any(secrets) and instagram.token()):
            raise Refused("unconfigured")
        return meta.check(CHANNEL, method, query, body, headers, verify_token=verify_token, secrets=secrets, kind=KIND)

    def carried(self, inbound: Inbound) -> list[Received | Failure | Delivery]:
        out: list[Received | Failure | Delivery] = []
        data = inbound.payload if isinstance(inbound.payload, dict) else {}
        for entry in meta.items(data.get("entry")):
            account = str(entry.get("id") or "")
            for event in meta.items(entry.get("messaging")):
                item = self._event(account, event)
                if item is not None:
                    out.append(item)
        return out

    def _event(self, account: str, event: dict[str, Any]) -> Received | Delivery | None:
        sender = str((event.get("sender") or {}).get("id") or "") if isinstance(event.get("sender"), dict) else ""
        recipient = str((event.get("recipient") or {}).get("id") or "") if isinstance(event.get("recipient"), dict) else ""
        message = event.get("message") if isinstance(event.get("message"), dict) else None
        if message is not None:
            remote = str(message.get("mid") or "")
            if not remote or message.get("is_deleted"):
                return None
            echo = bool(message.get("is_echo")) or (bool(account) and sender == account)
            contact = recipient if echo else sender
            if not instagram.ID.fullmatch(contact or ""):
                return None
            kind, words = _what(message)
            thread = dm_thread(contact, account)
            return Received(thread, Message(
                message_id=new_message_id(), chat_id=thread.chat_id, direction="out" if echo else "in",
                origin="person" if echo else "contact", text=words, at=_seconds(event.get("timestamp")), kind=kind,
                status="sent" if echo else "received", remote_id=remote))
        read = event.get("read") if isinstance(event.get("read"), dict) else None
        if read is not None and read.get("mid") and instagram.ID.fullmatch(sender or ""):
            return Delivery(dm_thread(sender, account), str(read["mid"]), "read", and_before=True)
        return None                                  # reactions, postbacks, referrals: not messages

    async def receive(self, inbound: Inbound) -> list[Received | Failure]:
        return []                                    # everything came in the request itself

    async def names(self, threads: list[Thread]) -> dict[str, str]:
        """Each new person's @handle (or name), asked of Instagram once, for threads with none."""
        out: dict[str, str] = {}
        for thread in [t for t in threads if not t.who][:NAMES_AT_ONCE]:
            try:
                found = await instagram.person(thread.contact)
            except instagram.InstagramUnavailable as exc:
                log.info("messaging: an Instagram name was not read (%s)", exc.kind)
                continue
            said = f"@{found['username']}" if found["username"] else found["name"]
            if said:
                out[thread.contact] = said[:60]
        return out

    # ------------------------------------------------------------------ reading from Instagram

    async def sync(self, limit: int = SYNC_CONVERSATIONS) -> tuple[list[Received], int]:
        """The recent conversations as Instagram's API returns them, as messages to store, and how
        many conversations it returned (said to the owner exactly, nought included). Raises
        InstagramUnavailable when Instagram would not answer."""
        await instagram.maybe_refresh()
        account = await instagram.account()
        found = await instagram.conversations(limit=limit)
        wanted = [c for c in found if c.get("user_id")]
        reads = await _read_threads([c["conversation_id"] for c in wanted])
        out: list[Received] = []
        for conversation, read in zip(wanted, reads, strict=True):
            contact = str(read.get("user_id") or conversation["user_id"])
            thread = dm_thread(contact, account.get("user_id") or account.get("id") or "")
            thread.who = f"@{read['username']}" if read.get("username") else ""
            for item in read.get("messages") or []:
                if not item.get("message_id"):
                    continue
                ours = instagram.is_ours(item.get("from"), account)
                words = str(item.get("text") or "")
                kind = "text" if words else ("file" if item.get("attachments") else "unknown")
                out.append(Received(thread, Message(
                    message_id=new_message_id(), chat_id=thread.chat_id, direction="out" if ours else "in",
                    origin="person" if ours else "contact", text=words, at=_seconds(item.get("created_time")),
                    kind=kind, status="sent" if ours else "received", remote_id=str(item["message_id"]))))
        return out, len(found)

    # ------------------------------------------------------------------ sending

    def reply_window(self, thread: Thread, now: float | None = None) -> str:
        moment = time.time() if now is None else now
        if not thread.last_in_at:
            return "closed: they haven't written yet"
        left = thread.last_in_at + WINDOW_S - moment
        if left <= 0:
            return "closed: their last message was over 24 hours ago"
        return f"open {int(left // 3600)}h more"

    async def why_not(self, thread: Thread, *, now: float | None = None) -> str:
        moment = time.time() if now is None else now
        if thread.route != ROUTE:
            return "CLIVE can't send in that kind of conversation."
        if not thread.last_in_at:
            return "They haven't written to CROOKS on Instagram, so Instagram won't take a message from CLIVE."
        if moment - thread.last_in_at > WINDOW_S:
            return instagram.WINDOW_WORDS
        return ""

    def too_long(self, text: str) -> str:
        if len(str(text).encode("utf-8")) > instagram.TEXT_MAX_BYTES:
            return "Together the words are longer than Instagram takes (1,000 bytes); shorten them."
        return ""

    async def send(self, thread: Thread, text: str, *, client_id: str) -> str:
        if thread.route != ROUTE:
            raise instagram.InstagramUnavailable("CLIVE can't send in that kind of conversation.", kind="refused",
                                                 refused=True)
        return await instagram.send_text(thread.contact, text)

    # ------------------------------------------------------------------ what the account can do

    async def probe(self) -> list[Route]:
        return await probe_routes()


async def probe_routes() -> list[Route]:
    """What Instagram's API says the account can do now, read-only, with exactly what it returned."""
    try:
        account = await instagram.account()
    except instagram.InstagramUnavailable as exc:
        return [Route("replies", "Replies to direct messages", "off" if exc.kind != "timeout" else "unknown",
                      "Answering people within 24 hours of their last message, on your hold.", str(exc)),
                _callback_route(None), *_unused()]
    who = f"@{account['username']}" if account.get("username") else "the account"
    routes = [Route("replies", "Replies to direct messages", "ready",
                    f"Answering people who wrote to {who} within 24 hours of their last message, on your hold.")]
    try:
        found = await instagram.conversations(limit=SYNC_CONVERSATIONS)
        count = len(found)
        routes.append(Route("conversations", "Reading conversations", "ready" if count else "unknown",
                            f"Instagram's API returned {count} conversation{'' if count == 1 else 's'}.",
                            "" if count else ("Meta returns other people's messages only to an app with Advanced "
                                              "Access for instagram_business_manage_messages (App Review). Until "
                                              "then only the webhook brings them (docs/INSTAGRAM_DMS.md).")))
    except instagram.InstagramUnavailable as exc:
        routes.append(Route("conversations", "Reading conversations", "off", "Reading the account's conversations.",
                            str(exc)))
    try:
        fields = await instagram.subscribed_fields()
    except instagram.InstagramUnavailable as exc:
        fields = None
        log.info("messaging: Instagram's subscription was not read (%s)", exc.kind)
    return [*routes, _callback_route(fields), *_unused()]


def _callback_route(fields: list[str] | None) -> Route:
    label, can = "Messages arriving", "Instagram telling CLIVE a message came in, at this server's /hooks/instagram."
    if not (_stored(VERIFY_TOKEN) and _stored(instagram.APP_SECRET_KEY)):
        return Route("callback", label, "off", can, "Store the app secret and the webhook verify token on this card.")
    if fields is None:
        return Route("callback", label, "unknown", can, "Instagram didn't say which events it sends for the account.")
    if "messages" not in fields:
        listed = ", ".join(fields) if fields else "none"
        return Route("callback", label, "off", can,
                     f"Instagram sends this account's events for: {listed}. Switch on messages "
                     "(docs/INSTAGRAM_DMS.md, the account's subscription), then press Test again.")
    return Route("callback", label, "ready", f"{can} Instagram sends: {', '.join(fields)}.")


def _unused() -> list[Route]:
    return [Route("human_agent", "After 24 hours", "not_used",
                  "Instagram's human-agent tag allows seven days, but only with Meta's App Review and for a person "
                  "typing the answer; CLIVE doesn't use it. Ask them to message CROOKS again.")]


ADAPTER = register(InstagramAdapter())
