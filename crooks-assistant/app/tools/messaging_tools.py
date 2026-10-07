"""Messaging in the conversation: what people sent on WeChat and WeCom, who a conversation is with,
and a reply the owner holds before it goes (app/messaging is the core, app/messaging/wecom.py the
channel, app/clients/wecom.py the calls).

The approved rules (7 October), and where each is kept:
- Every outgoing message needs his hold. message_reply is a write registered at RED, so the action
  engine makes its card hold-to-arm (app/actions/grammar.py), and it never sends when called: it
  prepares the exact text, and only the owner's hold on the card sends it.
- Inbound Chinese is shown in English, with the original one tap away: the reads return both,
  labelled machine translation, and the "messages" card draws the original behind a tap.
- Outbound messages are drafted in both English and Chinese: message_reply takes both, the card
  prints both, and both are sent, Chinese first, as one message.
- Nothing is called sent unless WeCom answered errcode 0 with a msgid; that send is then recorded
  in the thread and on the action ledger, and the card says Sent only once the record shows it.

Reads, the link and the reply are the owner's alone: no staff set names them (app/people/staff.py).
Following the email writes (app/tools/gmail_writes.py) until the generic one-hold message card
lands; docs/WECOM.md says what to switch then.
"""

from __future__ import annotations

import re
import secrets
import time
from typing import Any

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily, register
from app.clients import wecom as wecom_client
from app.messaging import adapter as adapters
from app.messaging import contacts, views
from app.messaging import wecom as _wecom_channel  # noqa: F401 - registers the WeCom adapter
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
MAX_THREADS = 12
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# Said on every model turn while WeCom is not connected (the families' standing line), so short.
NO_KEYS = "no WeCom keys stored"


async def _probe(_runtime: Any) -> dict[str, str]:
    """No WeCom keys stored: DISCONNECTED, so the tools are not offered and the model is told why."""
    if not wecom_client.configured():
        return {"state": "DISCONNECTED", "detail": NO_KEYS}
    return {"state": "READY", "detail": "WeCom is connected"}


async def _probe_replies(_runtime: Any) -> dict[str, str]:
    if not wecom_client.configured():
        return {"state": "DISCONNECTED", "detail": NO_KEYS}
    return {}


register(CapabilityFamily(
    key="messaging_reads", label="WeChat messages", area="messages",
    what="what the manufacturer, the forwarder and the team sent on WeChat or WeCom, in English with the original kept",
    tools=(*READS, LINK), state="READY", detail="ready", probe=_probe,
))
register(CapabilityFamily(
    key="messaging_replies", label="WeChat replies", area="messages",
    what="a reply drafted in English and Chinese, sent on your hold",
    operations=(WRITE,), tools=(WRITE,), state="READY", detail="ready", probe=_probe_replies,
))


def _owner_only() -> None:
    held = authority.current()
    if held is None or held.kind != authority.OWNER:
        raise ToolError("Only the owner reads and answers CROOKS's WeChat messages.")


def _thread(chat_id: str):
    thread = store.thread(str(chat_id or ""))
    if thread is None:
        raise ToolError("There is no such conversation in CLIVE's messages.")
    return thread


# ------------------------------------------------------------------ reads


@tool(
    name="messages_recent",
    description="WeChat/WeCom conversations, newest first, in English (originals kept). `person`: one person's.",
    input_schema={"type": "object", "properties": {
        "person": {"type": "string", "maxLength": 80},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_THREADS}}},
    tier=Tier.GREEN,
)
async def messages_recent(person: str = "", limit: int = 6) -> dict[str, Any]:
    _owner_only()
    threads = store.threads()
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
            note = (f"No WeChat conversation is linked to {card.name} yet. When they message the CROOKS "
                    "customer-service account, say which conversation is theirs.")
    elif not threads:
        note = "No messages have come in on WeCom yet."
    shown = threads[: max(1, min(int(limit or 6), MAX_THREADS))]
    out: dict[str, Any] = {
        "frame": views.FRAME, "title": title,
        "threads": [views.thread_view(t, store.messages(t.chat_id, limit=3), limit=3) for t in shown],
        "shown": len(shown), "of": len(threads),
    }
    if note:
        out["note"] = note
    return out


@tool(
    name="message_thread",
    description="One WeChat/WeCom conversation in full, by chat_id, in English with each original.",
    input_schema={"type": "object", "properties": {
        "chat_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}},
        "required": ["chat_id"]},
    tier=Tier.GREEN,
    issued_id_args=("chat_id",),
)
async def message_thread(chat_id: str, limit: int = 20) -> dict[str, Any]:
    _owner_only()
    thread = _thread(chat_id)
    return {"frame": views.FRAME,
            "thread": views.thread_view(thread, store.messages(thread.chat_id, limit=int(limit or 20)), limit=int(limit or 20))}


@tool(
    name=LINK,
    description="Say who a WeChat/WeCom conversation is with: links chat_id to a person on CLIVE's list.",
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


def sent_text(english: str, chinese: str) -> str:
    """What the contact receives: the Chinese, then the English the owner read."""
    return f"{chinese}\n\n{english}"


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
    """Sent only by the action engine, after the owner's hold on this card. WeCom's msgid is the
    proof: it is recorded in the thread, and nothing is recorded when WeCom did not confirm."""
    thread = _thread(execution["chat_id"])
    channel = adapters.get(thread.channel)
    if channel is None or not channel.configured():
        raise wecom_client.WeComError(f"{wecom_client.NOT_CONNECTED}.", kind="no_key")
    remote_id = await channel.send(thread, str(execution["text"]), client_id=str(execution["client_id"]))
    store.add(thread, Message(
        message_id=f"m_{secrets.token_hex(8)}", chat_id=thread.chat_id, direction="out", origin="clive",
        text=str(execution["text"]), at=time.time(), language="zh", english=str(execution["english"]),
        chinese=str(execution["chinese"]), translation_state="not_needed", status="sent", remote_id=str(remote_id),
        client_id=str(execution["client_id"])))
    return {"msg_id": str(remote_id), "done": True}


async def _settle(_execution: dict, _sent: dict) -> None:
    """Nothing to wait for. Declared so a send whose answer never came back is never written off as
    "nothing was sent" on one look: the card says it could not confirm it, and to check WeCom."""
    return None


def _verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return observed.get("sent") == 1, ""


def _present(proposal) -> dict:
    s = proposal.summary
    facts = [{"label": "To", "value": str(s.get("to") or "")},
             {"label": "On", "value": str(s.get("on") or "")},
             {"label": "Chinese", "value": "CLIVE's translation of your English: a machine translation", "tone": "warn"}]
    if s.get("window"):
        facts.append({"label": "WeChat allows", "value": str(s["window"])})
    if not s.get("linked"):
        facts.append({"label": "Who", "value": "not linked to anyone on your list yet", "tone": "warn"})
    return {
        "title": "Send on WeChat" if s.get("route") == "kf" else "Send on WeCom",
        "summary": "",
        # The message exactly as it will be sent: the Chinese, then the English.
        "body": str(s.get("text") or ""),
        "facts": facts,
        "detail": "Sends now, Chinese first, then your English. It cannot be unsent.",
        "done_title": "Sent",
    }


@tool(
    name=WRITE,
    description=("Stage a reply in a WeChat/WeCom conversation for the owner's hold. `english`, and `chinese` "
                 "saying the same; both are sent, Chinese first."),
    input_schema={"type": "object", "properties": {
        "chat_id": {"type": "string"},
        "english": {"type": "string", "maxLength": MAX_ENGLISH},
        "chinese": {"type": "string", "maxLength": MAX_CHINESE}},
        "required": ["chat_id", "english", "chinese"]},
    tier=Tier.RED,
    issued_id_args=("chat_id",),
    # Preparing may mint a token and asks WeCom whether the conversation can take a message.
    timeout_s=2 * wecom_client.TIMEOUT_S + 2.0,
    write=WriteSpec(
        operation=WRITE, entity_kind="chat", entity_arg="chat_id", mutation="messages:send",
        observe=_observe, execute=_execute, present=_present, verify=_verify, settle=_settle,
        # His hold: RED and irreversible make it hold_to_arm at staging (app/actions/grammar.py).
        interaction="hold_to_arm", op_class="irreversible", reversible=False, precondition_keys=("last_in", "sent"),
        service=wecom_client.NAME, says_failure=True,
        spoken_success="Sent to {to}.",
        spoken_failure="I couldn't confirm the message went. Check WeCom before sending it again.",
        spoken_stale="A new message came in on that conversation since this was drafted. Nothing was sent.",
    ),
)
async def message_reply(chat_id: str, english: str, chinese: str) -> Prepared:
    """Prepare, never send: the exact text, checked against what WeChat will take now."""
    _owner_only()
    thread = _thread(chat_id)
    channel = adapters.get(thread.channel)
    if channel is None or not channel.configured():
        raise ToolError(f"{wecom_client.NOT_CONNECTED}.")
    english_words = _clean(english, MAX_ENGLISH, "English")
    chinese_words = _clean(chinese, MAX_CHINESE, "Chinese")
    if language_of(chinese_words) != "zh":
        raise ToolError("The Chinese isn't in Chinese; write it in Chinese characters.")
    text = sent_text(english_words, chinese_words)
    if wecom_client.utf8_bytes(text) > wecom_client.KF_TEXT_MAX_BYTES:
        raise ToolError("Together the Chinese and the English are longer than WeChat takes; shorten them.")
    try:
        why = await channel.why_not(thread)
    except wecom_client.WeComError as exc:
        raise ToolError(str(exc)) from None
    if why:
        raise ToolError(why)
    who = contacts.name_for(thread)
    person = contacts.person_for(thread)
    client_id = f"clive{secrets.token_hex(10)}"
    before = _fingerprint(thread.chat_id, client_id)
    on = ("WeChat, from the CROOKS customer-service account" if thread.route == "kf" else "WeCom, from CLIVE's app")
    return Prepared(
        execution={"chat_id": thread.chat_id, "client_id": client_id, "text": text, "english": english_words,
                   "chinese": chinese_words},
        before=before,
        expected_after={**before, "sent": 1},
        entity_ref=thread.chat_id,
        # Never a name: the ledger and the log carry this label.
        entity_label=f"on {contacts.channel_words(thread)}",
        summary={
            "to": who, "spoken_to": (who.split() or ["them"])[0], "on": on, "route": thread.route, "text": text,
            "linked": person is not None, "window": views.reply_window(thread) if thread.route == "kf" else "",
            "read_back": f"send {who} a message on {contacts.channel_words(thread)}",
            "pii": [who] if person is not None or thread.who else [],
            "ledger": {"channel": thread.channel, "route": thread.route, "chars": len(text)},
        },
    )
