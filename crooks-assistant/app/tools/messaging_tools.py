"""Messaging in the conversation, whichever app it is on (WeChat through WeCom, WhatsApp, Instagram's
direct messages): what people sent, who a conversation is with, and a reply the owner holds before
it goes. app/messaging is the core, app/messaging/<channel>.py each channel, app/clients the calls.
The same four tools serve every channel; nothing here is written twice for a second app.

The approved rules (7 October), and where each is kept:
- Every outgoing message needs his hold. message_reply is a write registered at RED, so the action
  engine makes its card hold-to-arm (app/actions/grammar.py), and it never sends when called: it
  prepares the exact text, and only the owner's hold on the card sends it.
- Inbound words not in English are shown in English, with the original one tap away: the reads
  return both, labelled machine translation, and the "messages" card draws the original behind a tap.
- Outbound messages to someone who doesn't write English are drafted in both English and their
  language (on WeChat always Chinese): message_reply takes both, the card prints both, and both are
  sent, theirs first, as one message. To someone who writes English, the English alone.
- Each channel's own limit is checked before the card is made: WeChat 48 hours and five replies,
  WhatsApp and Instagram 24 hours from their last message. Outside it CLIVE refuses and says why;
  it never sends a paid template or uses a tag to get round it.
- Nothing is called sent unless the channel's API answered with its own message id; that send is
  then recorded in the thread and on the action ledger, and the card says Sent only once the
  record shows it. Delivered and read follow from the channel, where it reports them.

Reads, the link and the reply are the owner's alone: no staff set names them (app/people/staff.py).
The two reads are AMBER, because they surface people's names and what they wrote; the link is
GREEN, changing only CLIVE's own card; the reply is RED.
Following the email writes (app/tools/gmail_writes.py) until the generic one-hold message card
lands; docs/WECOM.md says what to switch then.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from typing import Any

from app.actions.engine import SENT_THROUGH
from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily, register
from app.clients import wecom as wecom_client
from app.messaging import adapter as adapters
from app.messaging import contacts, ingest, views
from app.messaging import instagram as _ig  # noqa: F401 - registers the Instagram adapter
from app.messaging import wecom as _wecom_channel  # noqa: F401 - registers the WeCom adapter
from app.messaging import whatsapp as _wa  # noqa: F401 - registers the WhatsApp adapter
from app.messaging.models import Message
from app.messaging.store import store
from app.messaging.translate import language_of
from app.people.store import PeopleError, people
from app.tools import authority
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool

READS = ("messages_recent", "message_thread")
LINK = "message_contact"
WRITE = "message_reply"
TOOLS = (*READS, LINK, WRITE)
# The operations that send a message, by name: tests/test_messaging_tools.py holds this list exact.
SEND_OPERATIONS = (WRITE,)

MAX_ENGLISH = 600
MAX_CHINESE = 400
MAX_TRANSLATED = 600
MAX_THREADS = 12
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# The apps as the owner names them, and the channel each is (`messages_recent` `channel`).
CHANNELS = {"wechat": "wecom", "whatsapp": "whatsapp", "instagram": "instagram"}
# Reading Instagram's conversations on request: at most this long, so a slow Instagram never holds the turn.
# [channels] Inside messages_recent's own time (RECENT_TIMEOUT_S), with room left to show what CLIVE
# already had: 20 seconds under the turn's 8-second tool time failed the whole tool (review note 4).
SYNC_TIMEOUT_S = 6.0
RECENT_TIMEOUT_S = SYNC_TIMEOUT_S + 4.0
LANGUAGE_WORDS = {"zh": "Chinese", "other": "a language other than English"}
APP_WORDS = {"wecom": "WeChat", "whatsapp": "WhatsApp", "instagram": "Instagram"}


# Said on every model turn while no messaging app is connected (the families' standing line), so short.
NO_KEYS = "no WeCom, WhatsApp or Instagram keys stored"


async def _probe(_runtime: Any) -> dict[str, str]:
    """No channel's keys stored: DISCONNECTED, so the tools are not offered and the model is told why."""
    if not adapters.any_configured():
        return {"state": "DISCONNECTED", "detail": NO_KEYS}
    named = ", ".join(a.label for a in adapters.ADAPTERS.values() if a.configured())
    return {"state": "READY", "detail": f"connected: {named}"}


async def _probe_replies(_runtime: Any) -> dict[str, str]:
    if not adapters.any_configured():
        return {"state": "DISCONNECTED", "detail": NO_KEYS}
    return {}


register(CapabilityFamily(
    key="messaging_reads", label="Messages", area="messages",
    what="what people sent on WeChat, WhatsApp and Instagram, in English with the original kept",
    tools=(*READS, LINK), state="READY", detail="ready", probe=_probe,
))
register(CapabilityFamily(
    key="messaging_replies", label="Message replies", area="messages",
    what="a reply in English and, for someone who writes another language, theirs too, sent on your hold",
    operations=(WRITE,), tools=(WRITE,), state="READY", detail="ready", probe=_probe_replies,
))


def _owner_only() -> None:
    held = authority.current()
    if held is None or held.kind != authority.OWNER:
        raise ToolError("Only the owner reads and answers CROOKS's messages.")


def _thread(chat_id: str):
    thread = store.thread(str(chat_id or ""))
    if thread is None:
        raise ToolError("There is no such conversation in CLIVE's messages.")
    return thread


# ------------------------------------------------------------------ reads


@tool(
    name="messages_recent",
    description=("Conversations (WeChat, WhatsApp, Instagram DMs), newest first, in English, originals kept. "
                 "`person`: one person's; `channel`: one app's."),
    input_schema={"type": "object", "properties": {
        "person": {"type": "string", "maxLength": 80},
        "channel": {"type": "string", "enum": list(CHANNELS)},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_THREADS}}},
    # AMBER, like every read that surfaces people's names and words (instagram_inbox, returns_open,
    # people_list): the model is told to read the detail back (review note 3, 8 Oct).
    tier=Tier.AMBER,
    # Its own time, deliberately longer than the Instagram read it may make, so a slow Instagram is
    # said in the note beside the conversations CLIVE already had, never a failed tool.
    timeout_s=RECENT_TIMEOUT_S,
)
async def messages_recent(person: str = "", limit: int = 6, channel: str = "") -> dict[str, Any]:
    _owner_only()
    wanted = CHANNELS.get(str(channel or "").strip().lower(), "")
    if str(channel or "").strip() and not wanted:
        raise ToolError("That isn't one of CLIVE's messaging apps: wechat, whatsapp or instagram.")
    read_note = await _read_instagram() if wanted == "instagram" else ""
    threads = [t for t in store.threads() if not wanted or t.channel == wanted]
    title = "Messages"
    note = ""
    if str(person or "").strip():
        try:
            card = people.find(person)
        except PeopleError as exc:
            raise ToolError(str(exc)) from None
        if card is None:
            return {"threads": [], "shown": 0, "note": f"No one called {str(person)[:40]} is on CLIVE's list."}
        threads = [t for t in threads if t.channel_key in card.channels]
        title = f"Messages with {card.name}"
        if not threads:
            note = (f"No conversation is linked to {card.name} yet. When they write in, say which "
                    "conversation is theirs.")
    elif not threads:
        connected = [words for channel, words in APP_WORDS.items()
                     if adapters.get(channel) is not None and adapters.get(channel).configured()]
        apps = [APP_WORDS[wanted]] if wanted else connected
        named = f"{', '.join(apps[:-1])} or {apps[-1]}" if len(apps) > 1 else "".join(apps)
        note = f"No messages have come in on {named or 'any messaging app'} yet."
    if wanted:
        title = f"{title} on {APP_WORDS[wanted]}"
    note = " ".join(x for x in (read_note, note) if x)
    shown = threads[: max(1, min(int(limit or 6), MAX_THREADS))]
    out: dict[str, Any] = {
        "frame": views.FRAME, "title": title,
        "threads": [views.thread_view(t, store.messages(t.chat_id, limit=3), limit=3) for t in shown],
        "shown": len(shown), "of": len(threads),
    }
    if note:
        out["note"] = note
    if wanted:
        out["app"] = APP_WORDS[wanted]
    return out


async def _read_instagram() -> str:
    """Read Instagram's conversations now and keep any new messages, as the webhook would have. Says
    exactly what Instagram returned, nought included, or why it could not be read: never a failure
    passed off as nothing new."""
    channel = adapters.get("instagram")
    if channel is None or not channel.configured():
        return "Instagram isn't connected, so it wasn't read."
    try:
        found, conversations = await asyncio.wait_for(channel.sync(), SYNC_TIMEOUT_S)
    except TimeoutError:
        return "Instagram didn't answer in time, so it wasn't read just now; this is what CLIVE had already."
    except Exception as exc:  # noqa: BLE001 - said in its own plain words when it has them
        words = str(exc) if getattr(exc, "plain_words", False) else "Instagram could not be read"
        return f"Instagram wasn't read just now ({words.rstrip('.')}); this is what CLIVE had already."
    new = ingest.take(channel, found)
    return (f"Instagram's API returned {conversations} conversation{'' if conversations == 1 else 's'} just now"
            f"{f', {new} new message' + ('' if new == 1 else 's') if new else ''}.")


@tool(
    name="message_thread",
    description="One conversation in full, by chat_id, in English with each original.",
    input_schema={"type": "object", "properties": {
        "chat_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}},
        "required": ["chat_id"]},
    tier=Tier.AMBER,   # a supplier's name and words, as messages_recent
    issued_id_args=("chat_id",),
)
async def message_thread(chat_id: str, limit: int = 20) -> dict[str, Any]:
    _owner_only()
    thread = _thread(chat_id)
    return {"frame": views.FRAME,
            "thread": views.thread_view(thread, store.messages(thread.chat_id, limit=int(limit or 20)), limit=int(limit or 20))}


@tool(
    name=LINK,
    description="Say who a conversation is with: links chat_id to a person on CLIVE's list.",
    input_schema={"type": "object", "properties": {
        "chat_id": {"type": "string"}, "person": {"type": "string", "maxLength": 80}},
        "required": ["chat_id", "person"]},
    tier=Tier.GREEN,
    issued_id_args=("chat_id",),
)
async def message_contact(chat_id: str, person: str) -> dict[str, Any]:
    _owner_only()
    thread = _thread(chat_id)
    try:
        card = contacts.link(thread, person)
    except PeopleError as exc:
        raise ToolError(str(exc)) from None
    return {"chat_id": thread.chat_id, "from": card.name, "linked": True,
            "said": f"That {contacts.channel_words(thread)} conversation is now {card.name}'s."}


# ------------------------------------------------------------------ the reply


def _clean(text: Any, limit: int, what: str) -> str:
    words = str(text or "").replace("\r\n", "\n").strip()
    words = re.sub(r"\n{3,}", "\n\n", words)
    if not words:
        raise ToolError(f"The {what} is empty.")
    if _CONTROL.search(words):
        raise ToolError(f"The {what} must be plain text.")
    if len(words) > limit:
        raise ToolError(f"The {what} is longer than {limit} characters; shorten it.")
    return words


def sent_text(english: str, theirs: str) -> str:
    """What the contact receives: their language (Chinese on WeChat) first, then the English the
    owner read; the English alone to someone who writes English."""
    return f"{theirs}\n\n{english}" if theirs else english


class NotConnected(RuntimeError):
    """The conversation's app has no keys on this server any more: nothing was sent."""

    plain_words = True
    refused = True


class NotSendable(RuntimeError):
    """[channels] Checked again at the hold, the app would not take this reply now (the 24 hours ran
    out between the card and the hold, review note 6): said in the channel's words, nothing sent."""

    plain_words = True
    refused = True


def _fingerprint(chat_id: str, client_id: str) -> dict[str, Any]:
    """The thread reduced to what the proof needs: their latest message (a new one since the card
    was prepared makes it stale) and whether OUR message is recorded as sent. No words, no names."""
    thread = store.thread(chat_id)
    mine = store.outgoing(chat_id, client_id)
    return {"last_in": thread.last_in_id if thread else "",
            "sent": 1 if mine is not None and mine.status == "sent" and mine.remote_id else 0}


async def _observe(execution: dict) -> Observed:
    return Observed(fingerprint=_fingerprint(str(execution["chat_id"]), str(execution["client_id"])), entity=None)


async def _execute(execution: dict) -> dict:
    """Sent only by the action engine, after the owner's hold on this card. The channel's own message
    id is the proof: it is recorded in the thread, and nothing is recorded when the channel did not
    confirm. A message the channel echoed to the door first becomes this record (store `claim`)."""
    thread = _thread(execution["chat_id"])
    channel = adapters.get(thread.channel)
    if channel is None or not channel.configured():
        raise NotConnected(f"{APP_WORDS.get(thread.channel, thread.channel)} is not connected on this server any more.")
    await _still_sendable(channel, thread)
    remote_id = await channel.send(thread, str(execution["text"]), client_id=str(execution["client_id"]))
    theirs = str(execution.get("translated", execution.get("chinese", "")) or "")
    language = str(execution.get("language") or ("zh" if theirs else "en"))
    store.claim(thread, Message(
        message_id=f"m_{secrets.token_hex(8)}", chat_id=thread.chat_id, direction="out", origin="clive",
        text=str(execution["text"]), at=time.time(), language=language, english=str(execution["english"]),
        chinese=theirs if language == "zh" else "", translated=theirs if language != "zh" else "",
        translation_state="not_needed", status="sent", remote_id=str(remote_id), client_id=str(execution["client_id"])))
    return {"msg_id": str(remote_id), "done": True}


async def _still_sendable(channel, thread) -> None:
    """[channels] The card's check made again at the hold, CLIVE's own and not only the app's: a card
    made at 23h50 and held at 24h10 is refused here, before anything goes. A check that can't be
    made is a refusal too: nothing has been sent yet."""
    try:
        why = await channel.why_not(thread)
    except Exception as exc:  # noqa: BLE001 - a channel's own refusal, in its words
        app = APP_WORDS.get(thread.channel, thread.channel)
        raise NotSendable(str(exc) if getattr(exc, "plain_words", False) else f"{app} could not be asked") from None
    if why:
        raise NotSendable(why)


async def _settle(_execution: dict, _sent: dict) -> None:
    """Nothing to wait for. Declared so a send whose answer never came back is never written off as
    "nothing was sent" on one look: the card says it could not confirm it, and to check the app."""
    return None


def _verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return observed.get("sent") == 1, ""


def to_line(thread, person, who: str) -> str:
    """Who the card says it goes to. Linked to a card, the channel's own name for the contact is
    printed beside it, so a conversation linked to the wrong person shows before the hold, not
    after the send (review note 6, 8 Oct): "Jessica (WeChat name: 李伟)". Drawn as text only."""
    if person is None:
        return who
    words = contacts.channel_words(thread)
    nick = " ".join(str(thread.who or "").split())[:60]
    return f"{person.name} ({words} name: {nick})" if nick else f"{person.name} ({words} gave no name)"


def _present(proposal) -> dict:
    s = proposal.summary
    app = str(s.get("app") or ("WeChat" if s.get("route") == "kf" else "WeCom"))
    theirs = str(s.get("theirs") or ("Chinese" if s.get("route") in ("kf", "member") else ""))
    facts = [{"label": "To", "value": str(s.get("to_line") or s.get("to") or "")},
             {"label": "On", "value": str(s.get("on") or "")}]
    if theirs:
        facts.append({"label": theirs if theirs == "Chinese" else "Their language",
                      "value": "CLIVE's translation of your English: a machine translation", "tone": "warn"})
    if s.get("window"):
        facts.append({"label": f"{app} allows", "value": str(s["window"])})
    if not s.get("linked"):
        facts.append({"label": "Who", "value": "not linked to anyone on your list yet", "tone": "warn"})
    first = {"Chinese": "Chinese first, then your English", "": ""}.get(theirs, "their language first, then your English")
    return {
        "title": f"Send on {app}",
        "summary": "",
        # The message exactly as it will be sent: their language first, then the English.
        "body": str(s.get("text") or ""),
        "facts": facts,
        "detail": f"Sends now{', ' + first if first else ''}. It cannot be unsent.",
        "done_title": "Sent",
    }


def _theirs(thread, translated: str) -> tuple[str, str]:
    """(their words, their language) for a reply in this thread: on WeChat the Chinese, always (the
    approved rule); elsewhere the same words in the language they write, when it isn't English, and
    nothing when it is. Raises ToolError, in plain words, when what was given doesn't fit."""
    if thread.channel == "wecom":
        words = _clean(translated, MAX_CHINESE, "Chinese")
        if language_of(words) != "zh":
            raise ToolError("The Chinese isn't in Chinese; write it in Chinese characters.")
        return words, "zh"
    theirs = thread.last_in_language
    if theirs in ("zh", "other"):
        if not str(translated or "").strip():
            raise ToolError(f"They write in {LANGUAGE_WORDS[theirs]}: give the same words in their language as "
                            "`translated`, as well as the English.")
        words = _clean(translated, MAX_TRANSLATED, "translation")
        found = language_of(words)
        if theirs == "zh" and found != "zh":
            raise ToolError("They write in Chinese; write the translation in Chinese characters.")
        if found == "en":
            raise ToolError("The translation reads as English; write it in the language they write in.")
        return words, found
    if str(translated or "").strip():
        raise ToolError("They write in English: send the English alone, with no translation.")
    return "", "en"


@tool(
    name=WRITE,
    description=("Stage a reply in a conversation for the owner's hold: `english`, and `translated`, the same in "
                 "their language unless they write English (WeChat: always Chinese). Both sent, theirs first."),
    input_schema={"type": "object", "properties": {
        "chat_id": {"type": "string"},
        "english": {"type": "string", "maxLength": MAX_ENGLISH},
        "translated": {"type": "string", "maxLength": MAX_TRANSLATED}},
        "required": ["chat_id", "english"]},
    tier=Tier.RED,
    issued_id_args=("chat_id",),
    # Preparing may mint a WeCom token and ask WeCom whether the conversation can take a message.
    timeout_s=2 * wecom_client.TIMEOUT_S + 2.0,
    write=WriteSpec(
        operation=WRITE, entity_kind="chat", entity_arg="chat_id", mutation="messages:send",
        observe=_observe, execute=_execute, present=_present, verify=_verify, settle=_settle,
        # His hold: RED and irreversible make it hold_to_arm at staging (app/actions/grammar.py).
        interaction="hold_to_arm", op_class="irreversible", reversible=False, precondition_keys=("last_in", "sent"),
        # WeCom's word for a WeChat reply; every proposal names its own app as `sent_through` in its
        # summary, which is what the owner is told (app/actions/engine.py `service_name`).
        service=wecom_client.NAME, says_failure=True,
        spoken_success="Sent to {to}.",
        spoken_failure="I couldn't confirm the message went. Check {service} before sending it again.",
        spoken_stale="A new message came in on that conversation since this was drafted. Nothing was sent.",
    ),
)
async def message_reply(chat_id: str, english: str, translated: str = "") -> Prepared:
    """Prepare, never send: the exact text, checked against what the channel will take now.
    `translated` was called `chinese` while WeChat was the only channel (7 October)."""
    _owner_only()
    thread = _thread(chat_id)
    channel = adapters.get(thread.channel)
    app = APP_WORDS.get(thread.channel, thread.channel)
    if channel is None or not channel.configured():
        raise ToolError(f"{app} is not connected — add its keys on the Connections screen.")
    english_words = _clean(english, MAX_ENGLISH, "English")
    theirs, language = _theirs(thread, translated)
    text = sent_text(english_words, theirs)
    too_long = channel.too_long(text)
    if too_long:
        raise ToolError(too_long)
    try:
        why = await channel.why_not(thread)
    except Exception as exc:  # noqa: BLE001 - a channel's own refusal, in its words
        raise ToolError(str(exc) if getattr(exc, "plain_words", False) else f"{app} could not be asked.") from None
    if why:
        raise ToolError(why)
    who = contacts.name_for(thread)
    person = contacts.person_for(thread)
    words = contacts.channel_words(thread)
    client_id = f"clive{secrets.token_hex(10)}"
    before = _fingerprint(thread.chat_id, client_id)
    on = {"kf": "WeChat, from the CROOKS customer-service account", "member": "WeCom, from CLIVE's app",
          "wa": "WhatsApp, from your business number", "dm": "Instagram, from the CROOKS account"}.get(thread.route, words)
    return Prepared(
        execution={"chat_id": thread.chat_id, "client_id": client_id, "text": text, "english": english_words,
                   "translated": theirs, "language": language},
        before=before,
        expected_after={**before, "sent": 1},
        entity_ref=thread.chat_id,
        # Never a name: the ledger and the log carry this label.
        entity_label=f"on {words}",
        summary={
            "to": who, "to_line": to_line(thread, person, who),
            "spoken_to": (who.split() or ["them"])[0], "on": on, "route": thread.route, "text": text,
            "app": words, SENT_THROUGH: "WeCom" if thread.channel == "wecom" else app,
            "theirs": LANGUAGE_WORDS.get(language, "") if theirs else "",
            "linked": person is not None, "window": views.reply_window(thread),
            "read_back": f"send {who} a message on {words}",
            # Kept out of the turn's record and the log: the name, and the channel's own name for them.
            "pii": [v for v in dict.fromkeys((who if person is not None or thread.who else "", thread.who)) if v],
            "ledger": {"channel": thread.channel, "route": thread.route, "chars": len(text)},
        },
    )
