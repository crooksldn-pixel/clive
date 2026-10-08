"""WeCom as a messaging channel: the adapter that turns WeCom's callbacks into threads and
messages, sends a reply the owner held, and says what George's WeCom app can do.

Why it exists: the manufacturer and the freight forwarder are on WeChat. WeCom reaches them in
exactly one way an app can both read and answer, 微信客服 (WeChat customer service): they message
CROOKS's customer-service account from their own WeChat, WeCom tells CLIVE a message is waiting,
CLIVE reads it with kf/sync_msg, and may answer within 48 hours of their last message, five times
at most, while the conversation is with the app rather than a person in WeCom. People inside the
company are reached as app messages (message/send), and their messages to the app arrive in the
callback itself. app/clients/wecom.py makes every call; docs/WECOM.md says what each route can do.

What it promises:
- verify_inbound: the signature is checked before anything else is done with a request; then its
  timestamp (five minutes) and that it is new (app/messaging/guard.py); then it is decrypted, and
  it must be for this company's CorpID. Anything else, a body that cannot be read at all included,
  is Refused, which the door answers with an empty 403, never an error.
- carried: a team member's message to the app is in the callback itself, so the door stores it
  before it answers (app/messaging/ingest.py), however busy the server is.
- receive: each WeChat message is stored once (by WeCom's msgid), with the read position kept
  after every page, so a restart reads on from where it was. A message WeCom later says did not
  arrive (msg_send_fail) is marked failed, with WeCom's reason in plain words.
- send returns only when WeCom answered errcode 0 with a msgid; otherwise it raises WeComError,
  which says why in plain words and whether nothing was sent.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

from app.clients import wecom
from app.messaging.adapter import Failure, Inbound, Received, Refused, Route, register
from app.messaging.guard import GUARD
from app.messaging.models import Message, Thread, chat_id_for, new_message_id
from app.messaging.store import store

log = logging.getLogger("crooks.messaging")

CHANNEL = "wecom"
KF_WINDOW_S = 48 * 3600          # 94677: a reply only within 48 hours of their last message
KF_MAX_REPLIES = 5               # ... and at most five of them
KF_SENDABLE_STATES = (0, 1)      # 94677/94669: new, or with the app ("智能助手")
MAX_PAGES = 10                   # sync_msg pages read for one callback, at most
MEMBER_KINDS = ("text", "image", "voice", "video", "file", "location", "link")

# 94670: why WeCom says a message it accepted did not arrive (event msg_send_fail, fail_type).
FAIL_WORDS = {
    0: "WeCom didn't say why", 1: "the customer-service account was deleted", 2: "the app was closed",
    4: "it was more than 48 hours after their last message", 5: "the conversation was closed",
    6: "it was over WeChat's five-reply limit", 8: "the company isn't verified", 10: "they refused the message",
    11: "nobody in the company has signed in to the WeCom app", 12: "customer service doesn't allow that kind of message",
    13: "a WeCom security limit",
}
STATE_WORDS = {
    2: "That conversation is waiting for a person in WeCom to pick it up, so CLIVE can't answer it.",
    3: "A person in WeCom is answering that conversation, so CLIVE can't send in it. Answer it in WeCom.",
    4: "That conversation has ended. CLIVE can answer once they write again.",
}


def kf_thread(open_kfid: str, external_userid: str) -> Thread:
    return Thread(chat_id=chat_id_for(CHANNEL, "kf", open_kfid, external_userid), channel=CHANNEL, route="kf",
                  account=str(open_kfid), contact=str(external_userid))


def member_thread(agent_id: str, userid: str) -> Thread:
    return Thread(chat_id=chat_id_for(CHANNEL, "member", agent_id, userid), channel=CHANNEL, route="member",
                  account=str(agent_id), contact=str(userid), who=str(userid))


def _words_of(msg: dict[str, Any]) -> tuple[str, str]:
    """(kind, words) of one kf message: the text's content, or the kind alone for a photo, a file."""
    kind = str(msg.get("msgtype") or "")
    if kind == "text":
        return "text", str((msg.get("text") or {}).get("content") or "")
    if kind == "link":
        link = msg.get("link") or {}
        return "link", " ".join(x for x in (str(link.get("title") or ""), str(link.get("url") or "")) if x)
    if kind == "location":
        place = msg.get("location") or {}
        return "location", " ".join(x for x in (str(place.get("name") or ""), str(place.get("address") or "")) if x)
    return kind or "unknown", ""


class WeComAdapter:
    channel = CHANNEL
    label = "WeCom"

    def configured(self) -> bool:
        return wecom.configured()

    # ------------------------------------------------------------------ the door

    def verify_inbound(self, method: str, query: Mapping[str, str], body: bytes) -> Inbound:
        if not self.configured():
            raise Refused("unconfigured")
        signature = str(query.get("msg_signature") or "")
        timestamp = str(query.get("timestamp") or "")
        nonce = str(query.get("nonce") or "")
        if not (signature and timestamp and nonce):
            raise Refused("unsigned")
        try:
            crypto = wecom.crypto()
        except wecom.CryptoError:
            raise Refused("unconfigured") from None
        if method == "GET":
            # A base64 echo has no spaces: a "+" the query parser read as a space is put back.
            sealed = str(query.get("echostr") or "").replace(" ", "+")
            if not sealed:
                raise Refused("unsigned")
        else:
            # Any failure to read the envelope is a refusal, never a 500: anyone on the internet can
            # post here, and nothing they send may end the request any other way (review note 1).
            try:
                outer = wecom.envelope(body)
            except Exception:  # noqa: BLE001 - CryptoError, RecursionError, anything: an empty 403
                raise Refused("unreadable") from None
            sealed = outer["Encrypt"]
        if not crypto.signed(signature, timestamp, nonce, sealed):
            raise Refused("signature")
        if not GUARD.fresh(timestamp):
            raise Refused("stale")
        # Opened and checked before it is counted as seen, so a signed request that is not for this
        # company is refused every time it comes, never waved through as a repeat.
        try:
            plain = crypto.decrypt(sealed)
            fields = {} if method == "GET" else wecom.message_fields(plain)
        except Exception:  # noqa: BLE001 - CryptoError or anything else opening it: an empty 403
            raise Refused("crypto") from None
        corp = wecom.value(wecom.CORP_ID)
        if fields.get("ToUserName") and fields["ToUserName"] != corp:
            raise Refused("crypto")
        key = f"{CHANNEL}|{method}|{timestamp}|{nonce}|{signature.lower()}"
        if not GUARD.first_time(key, float(timestamp)):
            if method == "GET":
                raise Refused("repeat")
            return Inbound(channel=CHANNEL, key=key, timestamp=float(timestamp), fields={"_repeat": "1"})
        if method == "GET":
            return Inbound(channel=CHANNEL, echo=plain, key=key, timestamp=float(timestamp))
        return Inbound(channel=CHANNEL, fields=fields, key=key, timestamp=float(timestamp))

    # ------------------------------------------------------------------ what a callback stands for

    def carried(self, inbound: Inbound) -> list[Received]:
        """A team member's message to the app, which the callback carries itself: no call to make."""
        fields = inbound.fields
        if fields.get("MsgType", "") in MEMBER_KINDS and fields.get("FromUserName"):
            return [self._member(fields)]
        return []

    async def receive(self, inbound: Inbound) -> list[Received | Failure]:
        """What WeCom said is waiting in customer service, read with kf/sync_msg."""
        fields = inbound.fields
        if fields.get("MsgType", "") == "event" and fields.get("Event") == "kf_msg_or_event":
            return await self._kf(fields.get("OpenKfId", ""), fields.get("Token", ""))
        return []

    def _member(self, fields: dict[str, str]) -> Received:
        thread = member_thread(fields.get("AgentID") or wecom.value(wecom.AGENT_ID), fields["FromUserName"])
        kind = fields.get("MsgType", "text")
        words = fields.get("Content", "") if kind == "text" else ""
        try:
            at = float(fields.get("CreateTime") or time.time())
        except ValueError:
            at = time.time()
        message = Message(message_id=new_message_id(), chat_id=thread.chat_id, direction="in", origin="contact",
                          text=words, at=at, kind=kind, remote_id=str(fields.get("MsgId") or ""))
        return Received(thread, message)

    async def _kf(self, open_kfid: str, token: str) -> list[Received | Failure]:
        if not open_kfid:
            return []
        out: list[Received | Failure] = []
        cursor_key = f"{CHANNEL}:kf:{open_kfid}"
        cursor = store.cursor(cursor_key)
        for _page in range(MAX_PAGES):
            answer = await wecom.kf_sync(open_kfid, cursor=cursor, token=token)
            for msg in answer.get("msg_list") or []:
                if isinstance(msg, dict):
                    item = self._kf_item(open_kfid, msg)
                    if item is not None:
                        out.append(item)
            following = str(answer.get("next_cursor") or "")
            if following:
                cursor = following
                store.set_cursor(cursor_key, cursor)
            if not answer.get("has_more"):
                break
        return out

    def _kf_item(self, open_kfid: str, msg: dict[str, Any]) -> Received | Failure | None:
        origin = int(msg.get("origin") or 0)
        if msg.get("msgtype") == "event":
            event = msg.get("event") or {}
            if event.get("event_type") == "msg_send_fail" and event.get("external_userid"):
                thread = kf_thread(str(event.get("open_kfid") or open_kfid), str(event["external_userid"]))
                reason = FAIL_WORDS.get(int(event.get("fail_type") or 0), FAIL_WORDS[0])
                return Failure(thread, str(event.get("fail_msgid") or ""), reason)
            return None
        contact = str(msg.get("external_userid") or "")
        if origin not in (3, 5) or not contact:
            return None
        thread = kf_thread(str(msg.get("open_kfid") or open_kfid), contact)
        kind, words = _words_of(msg)
        try:
            at = float(msg.get("send_time") or time.time())
        except (TypeError, ValueError):
            at = time.time()
        if origin == 3:
            message = Message(message_id=new_message_id(), chat_id=thread.chat_id, direction="in", origin="contact",
                              text=words, at=at, kind=kind, remote_id=str(msg.get("msgid") or ""))
        else:
            # Typed by a customer-service agent in the WeCom app: CLIVE did not send it, and keeps it so
            # the thread reads as it happened.
            message = Message(message_id=new_message_id(), chat_id=thread.chat_id, direction="out", origin="person",
                              text=words, at=at, kind=kind, status="sent", remote_id=str(msg.get("msgid") or ""))
        return Received(thread, message)

    async def names(self, threads: list[Thread]) -> dict[str, str]:
        """WeChat nicknames for customer-service contacts, for threads that have none yet."""
        wanted = [t.contact for t in threads if t.route == "kf" and not t.who]
        if not wanted:
            return {}
        try:
            return await wecom.kf_customers(wanted)
        except wecom.WeComError as exc:
            log.info("messaging: WeCom nicknames not read (%s)", exc.kind)
            return {}

    # ------------------------------------------------------------------ sending

    async def why_not(self, thread: Thread, *, now: float | None = None) -> str:
        """Why a reply in this thread would not be taken by WeCom now, in plain words; "" when it
        would. Checked when the card is prepared; WeCom still decides when it is sent."""
        if thread.route == "member":
            return ""
        if thread.route != "kf":
            return "CLIVE can't send in that kind of conversation."
        moment = time.time() if now is None else now
        if not thread.last_in_at:
            return "They haven't written to the CROOKS customer-service account yet, so WeChat won't take a message to them."
        if moment - thread.last_in_at > KF_WINDOW_S:
            return wecom.ERRCODE_WORDS[95002]
        if thread.sends_since_in >= KF_MAX_REPLIES:
            return wecom.ERRCODE_WORDS[95001]
        state = await wecom.kf_state(thread.account, thread.contact)
        if state not in KF_SENDABLE_STATES:
            return STATE_WORDS.get(state, "WeCom didn't say the conversation can take a message from CLIVE.")
        return ""

    async def send(self, thread: Thread, text: str, *, client_id: str) -> str:
        """Send, and return WeCom's msgid. Raises WeComError (with `refused` when WeCom answered
        and nothing went) on anything but errcode 0 with a msgid."""
        if thread.route == "kf":
            return await wecom.send_kf_text(thread.account, thread.contact, text, msgid=client_id)
        if thread.route == "member":
            return await wecom.send_member_text(thread.contact, text)
        raise wecom.WeComError("CLIVE can't send in that kind of conversation.", kind="refused")

    # ------------------------------------------------------------------ what the app can do

    async def probe(self) -> list[Route]:
        return await probe_routes()


async def probe_routes() -> list[Route]:
    """Each way WeCom could reach people, as George's app stands now (read-only calls, nothing
    sent): ready, off with what to switch on, or not used by CLIVE and why."""
    routes: list[Route] = []
    callback = _callback_route()
    try:
        app = await wecom.agent()
    except wecom.WeComError as exc:
        why = str(exc)
        routes.append(Route("member", "Your team, as messages from the app", "off" if exc.kind == "refused" else "unknown",
                            "Messages from CLIVE's WeCom app to people in your company.", why))
        routes.append(Route("kf", "WeChat contacts, through customer service", "unknown",
                            "Reading and answering people who message your customer-service account on WeChat.",
                            "Fix the line above first."))
        return [callback, *routes, *_unused()]
    name = " ".join(str(app.get("name") or "").split())[:40] or "the app"
    if int(app.get("close") or 0):
        routes.append(Route("member", "Your team, as messages from the app", "off",
                            "Messages from CLIVE's WeCom app to people in your company.",
                            f"{name} is switched off (停用) in the WeCom admin console: switch it on."))
    else:
        routes.append(Route("member", "Your team, as messages from the app", "ready",
                            f"Messages from {name} to people in your company who can see the app, and theirs back to it.",
                            "Add anyone CLIVE should message to the app's visible range (可见范围)."))
    routes.append(await _kf_route())
    return [callback, *routes, *_unused()]


def _callback_route() -> Route:
    try:
        wecom.crypto()
    except wecom.CryptoError as exc:
        return Route("callback", "Messages arriving", "off", "WeCom telling CLIVE a message has come in.",
                     f"The callback values are not right: {exc}. Copy the Token and EncodingAESKey from the app's "
                     "Receive Messages (接收消息) settings again.")
    return Route("callback", "Messages arriving", "ready",
                 "WeCom tells CLIVE when a message comes in, at this server's /hooks/wecom, signed with your Token.",
                 "")


async def _kf_route() -> Route:
    label = "WeChat contacts, through customer service"
    can = ("Reading what people send your customer-service account from WeChat, and answering within 48 hours of "
           "their last message, five replies at most, while the conversation is with the app.")
    switch = ("In the WeCom admin console, open 微信客服 (WeChat Customer Service) → API: add this app under "
              "可调用接口的应用 (apps that can call the API), then under 通过API管理微信客服账号 choose the CROOKS "
              "account, so the app (not a person) receives its conversations. Its agents (接待人员) must be in this "
              "app's visible range (可见范围).")
    try:
        accounts = await wecom.kf_accounts()
    except wecom.WeComError as exc:
        if exc.errcode in wecom.PERMISSION_ERRCODES or exc.errcode in (95011, 95012):
            return Route("kf", label, "off", can, f"{exc} {switch}")
        return Route("kf", label, "unknown", can, str(exc))
    managed = [a for a in accounts if a.get("manage_privilege") is True]
    if not accounts:
        return Route("kf", label, "off", can, "There is no customer-service account yet. Make one in 微信客服, then: " + switch)
    if not managed:
        return Route("kf", label, "off", can, "This app manages none of your customer-service accounts. " + switch)
    names = ", ".join(" ".join(str(a.get("name") or "").split())[:30] for a in managed[:3])
    # Neutral words: who should write in is on his people's cards, never in code (review note 7, 8 Oct).
    return Route("kf", label, "ready", f"{can} Account{'s' if len(managed) > 1 else ''}: {names}.",
                 "Send the account's link (微信客服 → the account → 客服链接) to each supplier who should reach "
                 "CROOKS here, so they message it from WeChat.")


def _unused() -> list[Route]:
    return [
        Route("external_contact", "Your own WeChat contacts (客户联系)", "not_used",
              "WeCom lets an app only queue a message to a contact that you then confirm and send yourself in the "
              "WeCom app (externalcontact/add_msg_template), so CLIVE doesn't send this way."),
        Route("archive", "Reading your own WeCom chats (会话内容存档)", "not_used",
              "The conversation archive is a paid WeCom add-on that needs Tencent's own C library on the server, an "
              "RSA key and each contact's consent; CLIVE doesn't use it."),
        Route("appchat", "Group chats made by the app", "not_used",
              "They hold people in your company only, and WeCom confirms a group message with no message id, so "
              "CLIVE couldn't prove one was sent; it doesn't send there."),
    ]


ADAPTER = register(WeComAdapter())
