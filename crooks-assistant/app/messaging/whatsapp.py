"""WhatsApp as a messaging channel: the adapter that turns what Meta sends to /hooks/whatsapp into
threads and messages, sends a reply the owner held, and says what George's WhatsApp number can do.

Why it exists: George approved WhatsApp (7 October) without saying who it is for. It is built so
either works: a supplier who writes from WhatsApp, or a customer. Who a conversation is with is said
on that person's card (app/messaging/contacts.py), and one card can hold WeChat and WhatsApp both.
app/clients/whatsapp.py makes every call; docs/WHATSAPP.md says what he sets up and decides.

What it promises:
- verify_inbound: Meta's GET check is answered only for the stored verify token; a POST is read only
  when its X-Hub-Signature-256 is the Meta app secret's signature of the body (app/messaging/meta.py).
  Anything else is Refused, which the door answers with an empty 403.
- carried: everything Meta sends arrives in the request itself, so it is stored at the door before
  Meta is answered: each message once (by WhatsApp's own id, so Meta's retries change nothing), the
  name WhatsApp gives the person, and what became of each message CLIVE sent: delivered, read, or
  failed with WhatsApp's reason in plain words. Changes for any other phone number are left alone.
- A reply is taken only within 24 hours of their last message (WhatsApp's customer service window).
  Outside it WhatsApp takes only an approved template, which Meta charges for; CLIVE refuses and
  says so, before the card is made (why_not) and again if WhatsApp says so at send (131047).
- send returns only WhatsApp's own message id; anything else raises WhatsAppError in plain words.
- Nothing here logs a number, a name or a word.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

from app.clients import whatsapp
from app.messaging import meta
from app.messaging.adapter import Delivery, Failure, Inbound, Received, Refused, Route, register
from app.messaging.models import Message, Thread, keyed_chat_id, new_message_id
from app.messaging.store import store

log = logging.getLogger("crooks.messaging")

CHANNEL = "whatsapp"
ROUTE = "wa"
KIND = "whatsapp_business_account"
WINDOW_S = 24 * 3600         # Meta's customer service window: 24 hours from their last message

# A message's type as the store keeps it (only text carries words; a caption is kept as words).
KINDS = {"text": "text", "image": "image", "video": "video", "audio": "voice", "document": "file",
         "sticker": "sticker", "location": "location", "contacts": "business_card", "button": "text",
         "interactive": "text", "order": "order", "unsupported": "unsupported"}


def wa_thread(phone_number_id: str, wa_id: str) -> Thread:
    """[channels] The conversation with one WhatsApp number, its id keyed with the server's own key: a
    WhatsApp id is a phone number (review note 7)."""
    chat_id = keyed_chat_id(store.chat_key(), CHANNEL, ROUTE, str(phone_number_id), str(wa_id))
    return Thread(chat_id=chat_id, channel=CHANNEL, route=ROUTE, account=str(phone_number_id), contact=str(wa_id))


def _words(message: dict[str, Any]) -> tuple[str, str]:
    """(kind, words) of one incoming WhatsApp message."""
    kind = str(message.get("type") or "")
    part = message.get(kind) if isinstance(message.get(kind), dict) else {}
    if kind == "text":
        return "text", meta.text(part.get("body"))
    if kind == "button":
        return "text", meta.text(part.get("text"))
    if kind == "interactive":
        reply = part.get("button_reply") or part.get("list_reply") or {}
        return "text", meta.text(reply.get("title") if isinstance(reply, dict) else "")
    if kind == "location":
        return "location", " ".join(x for x in (meta.text(part.get("name"), 200), meta.text(part.get("address"), 300)) if x)
    if kind in ("image", "video", "document"):
        return KINDS[kind], meta.text(part.get("caption"), 1024)
    return KINDS.get(kind, kind or "unknown"), ""


def _when(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return time.time()


def _failed_words(status: dict[str, Any]) -> str:
    for error in meta.items(status.get("errors")):
        try:
            return whatsapp.words_for(int(error.get("code") or 0)).rstrip(".")
        except (TypeError, ValueError):
            break
    return "WhatsApp didn't say why"


class WhatsAppAdapter:
    channel = CHANNEL
    label = "WhatsApp"
    max_body = meta.MAX_BODY_BYTES

    def configured(self) -> bool:
        return whatsapp.configured()

    # ------------------------------------------------------------------ the door

    def verify_inbound(self, method: str, query: Mapping[str, str], body: bytes,
                       headers: Mapping[str, str] | None = None) -> Inbound:
        verify_token = whatsapp.value(whatsapp.VERIFY_TOKEN)
        secret = whatsapp.value(whatsapp.APP_SECRET)
        if not (verify_token and secret):
            raise Refused("unconfigured")
        return meta.check(CHANNEL, method, query, body, headers, verify_token=verify_token, secrets=[secret], kind=KIND)

    def carried(self, inbound: Inbound) -> list[Received | Failure | Delivery]:
        """Every message and status in Meta's request, for this phone number only."""
        ours = whatsapp.value(whatsapp.PHONE_NUMBER_ID)
        out: list[Received | Failure | Delivery] = []
        data = inbound.payload if isinstance(inbound.payload, dict) else {}
        for entry in meta.items(data.get("entry")):
            for change in meta.items(entry.get("changes")):
                value = change.get("value") if isinstance(change.get("value"), dict) else {}
                metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
                number = str(metadata.get("phone_number_id") or "")
                if not number or number != ours:
                    continue
                field = str(change.get("field") or "")
                if field == "messages":
                    out.extend(self._messages(number, value))
                    out.extend(self._statuses(number, value))
                elif field == "smb_message_echoes":
                    out.extend(self._echoes(number, value))
        return out

    def _messages(self, number: str, value: dict[str, Any]) -> list[Received]:
        contacts = meta.items(value.get("contacts"))
        names = {str(c.get("wa_id") or ""): meta.text((c.get("profile") or {}).get("name"), 60)
                 for c in contacts if isinstance(c.get("profile"), dict)}
        out = []
        for message in meta.items(value.get("messages")):
            sender = str(message.get("from") or "").lstrip("+")
            wa_id = sender if sender in names or len(contacts) != 1 else str(contacts[0].get("wa_id") or sender)
            kind, words = _words(message)
            if not wa_id or kind == "reaction" or not str(message.get("id") or ""):
                continue
            thread = wa_thread(number, wa_id)
            thread.who = " ".join(str(names.get(wa_id) or names.get(sender) or "").split())[:60]
            out.append(Received(thread, Message(
                message_id=new_message_id(), chat_id=thread.chat_id, direction="in", origin="contact", text=words,
                at=_when(message.get("timestamp")), kind=kind, remote_id=str(message["id"]))))
        return out

    def _statuses(self, number: str, value: dict[str, Any]) -> list[Failure | Delivery]:
        out: list[Failure | Delivery] = []
        for status in meta.items(value.get("statuses")):
            remote_id, recipient = str(status.get("id") or ""), str(status.get("recipient_id") or "").lstrip("+")
            if not remote_id or not recipient or status.get("recipient_type") == "group":
                continue
            thread = wa_thread(number, recipient)
            state = str(status.get("status") or "")
            if state == "failed":
                out.append(Failure(thread, remote_id, _failed_words(status)))
            elif state in ("delivered", "read"):
                out.append(Delivery(thread, remote_id, state))
        return out

    def _echoes(self, number: str, value: dict[str, Any]) -> list[Received]:
        """A message someone sent from the WhatsApp Business app on the same number (coexistence):
        CLIVE did not send it, and keeps it so the conversation reads as it happened."""
        out = []
        for echo in meta.items(value.get("message_echoes")):
            to = str(echo.get("to") or "").lstrip("+")
            kind, words = _words(echo)
            if not to or not str(echo.get("id") or ""):
                continue
            thread = wa_thread(number, to)
            out.append(Received(thread, Message(
                message_id=new_message_id(), chat_id=thread.chat_id, direction="out", origin="person", text=words,
                at=_when(echo.get("timestamp")), kind=kind, status="sent", remote_id=str(echo["id"]))))
        return out

    async def receive(self, inbound: Inbound) -> list[Received | Failure]:
        return []                                   # everything came in the request itself

    async def names(self, threads: list[Thread]) -> dict[str, str]:
        return {}                                   # WhatsApp gives the name with each message

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
        """Why WhatsApp would not take a reply in this thread now, in plain words; "" when it would."""
        moment = time.time() if now is None else now
        if thread.route != ROUTE:
            return "CLIVE can't send in that kind of conversation."
        if thread.account != whatsapp.value(whatsapp.PHONE_NUMBER_ID):
            return "That conversation is on a WhatsApp number CLIVE no longer sends from."
        if not thread.last_in_at:
            return ("They haven't written to your WhatsApp number yet. WhatsApp lets a business start a "
                    "conversation only with an approved template message, which CLIVE doesn't send.")
        if moment - thread.last_in_at > WINDOW_S:
            return whatsapp.WINDOW_WORDS
        return ""

    def too_long(self, text: str) -> str:
        if len(str(text)) > whatsapp.TEXT_MAX_CHARS:
            return "Together the words are longer than WhatsApp takes (4,096 characters); shorten them."
        return ""

    async def send(self, thread: Thread, text: str, *, client_id: str) -> str:
        if thread.route != ROUTE:
            raise whatsapp.WhatsAppError("CLIVE can't send in that kind of conversation.", kind="refused")
        return await whatsapp.send_text(thread.contact, text)

    # ------------------------------------------------------------------ what the number can do

    async def probe(self) -> list[Route]:
        return await probe_routes()


async def probe_routes() -> list[Route]:
    """Each way WhatsApp could carry messages, as George's number stands now (read-only calls,
    nothing sent), with exactly what Meta answered and what to do where something is off."""
    routes: list[Route] = []
    try:
        number = await whatsapp.phone_number()
    except whatsapp.WhatsAppError as exc:
        state = "off" if exc.kind in ("refused", "no_key") else "unknown"
        routes.append(Route("number", "Your WhatsApp number", state, "The number CLIVE sends from.", str(exc)))
        return [*routes, await _callback_route(), *_unused()]
    shown = " ".join(x for x in (number["display_phone_number"], f"({number['verified_name']})" if number["verified_name"] else "") if x)
    status = number["status"] or "not given"
    quality = number["quality_rating"] or "not given"
    if number["status"] == "CONNECTED":
        routes.append(Route("number", "Your WhatsApp number", "ready",
                            f"{shown or 'The number'}: Meta says its status is CONNECTED, quality {quality}."))
    else:
        routes.append(Route("number", "Your WhatsApp number", "off",
                            f"{shown or 'The number'}: Meta says its status is {status}.",
                            "It must be CONNECTED to send and receive: register it for the Cloud API "
                            "(docs/WHATSAPP.md, registering the number), then press Test again."))
    try:
        await whatsapp.business_account()
        account_ok, account_words = True, ""
    except whatsapp.WhatsAppError as exc:
        account_ok, account_words = False, str(exc)
    can = "Answering people within 24 hours of their last message, on your hold. Free: Meta charges only for templates."
    if number["status"] == "CONNECTED" and account_ok:
        routes.append(Route("replies", "Replies", "ready", can))
    else:
        routes.append(Route("replies", "Replies", "off", can, account_words or "Fix the number above first."))
    return [*routes, await _callback_route(), *_unused()]


async def _callback_route() -> Route:
    label, can = "Messages arriving", "Meta telling CLIVE a message came in, at this server's /hooks/whatsapp."
    if not (whatsapp.value(whatsapp.APP_SECRET) and whatsapp.value(whatsapp.VERIFY_TOKEN)):
        return Route("callback", label, "off", can, "Store the app secret and the verify token on this card.")
    try:
        apps = await whatsapp.subscribed_apps()
    except whatsapp.WhatsAppError as exc:
        return Route("callback", label, "unknown", can, str(exc))
    if not apps:
        return Route("callback", label, "off", can,
                     "Meta says no app is subscribed to this WhatsApp account's webhooks, so no message reaches "
                     "CLIVE. Subscribe the app (docs/WHATSAPP.md, webhooks), then press Test again.")
    names = ", ".join(a for a in apps[:3] if a)
    return Route("callback", label, "ready",
                 f"{can} Meta sends this account's webhooks to: {names or 'an app it gave no name'}.",
                 "In the Meta app: WhatsApp → Configuration → Callback URL is this server's /hooks/whatsapp, "
                 "with the same verify token, and the messages field is subscribed.")


def _unused() -> list[Route]:
    return [Route("templates", "Starting a conversation, or after 24 hours", "not_used",
                  "WhatsApp takes only an approved template message then, and Meta charges for each one, so "
                  "CLIVE doesn't send them. Ask the person to message the number first.")]


ADAPTER = register(WhatsAppAdapter())
