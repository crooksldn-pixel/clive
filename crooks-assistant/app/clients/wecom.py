"""WeCom (企业微信), as CLIVE reaches WeChat through George's own self-built WeCom app.

Why it exists: CROOKS talks to its manufacturer and its freight forwarder on WeChat, and WeCom
is the official API onto WeChat. George built his own WeCom app; this is CLIVE's side of it,
written from WeCom's own documentation so his app's six values plug straight in (CorpID,
AgentID, the app's Secret, a customer-service Secret if he has a separate one, and the callback
Token and EncodingAESKey). docs/WECOM.md names every doc page relied on.

What it promises:

- The callback crypto is WeCom's own scheme (developer.work.weixin.qq.com/document/path/90968,
  "加解密方案说明"), proved against its published vectors in tests/test_wecom_crypto.py:
  signature = SHA-1 of the sorted [token, timestamp, nonce, encrypt], compared in constant
  time; AES-256-CBC with key = base64(EncodingAESKey + "="), IV = the key's first 16 bytes,
  PKCS#7 padding to a 32-byte block; plaintext = 16 random bytes + a 4-byte big-endian length +
  the message + the receive id, which must be this company's CorpID or nothing is accepted.
- Access tokens come from `gettoken`, are held in memory only (never on disk, never logged),
  refreshed early, and on 40014 / 42001 / 42009 refreshed once and the call tried once more.
- Every errcode becomes plain English (`words_for`), and a refusal says what to switch on.
  WeCom's own errmsg is never repeated, except the server address a 60020 names, which is the
  thing George has to add to the app's trusted IPs.
- Nothing is called sent unless WeCom answered errcode 0 with a message id (`send_kf_text`,
  `send_member_text` return it, and raise otherwise).
- Nothing here logs a secret, a token, a message, a person or an id: the log lines name a kind
  and an errcode. The access token travels in the query string because WeCom accepts it nowhere
  else; httpx's request lines are kept out of the log (app/logging/quiet.py).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import struct
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.secrets import keychain

log = logging.getLogger("crooks.wecom")

NAME = "WeCom"
API = "https://qyapi.weixin.qq.com/cgi-bin"
TIMEOUT_S = 10.0

# The six values from George's WeCom admin console, as the secret store names them.
CORP_ID = "wecom_corp_id"
AGENT_ID = "wecom_agent_id"
APP_SECRET = "wecom_app_secret"
KF_SECRET = "wecom_kf_secret"            # optional: only when 微信客服 has a Secret of its own
CALLBACK_TOKEN = "wecom_callback_token"
AES_KEY = "wecom_encoding_aes_key"
KEYS = (CORP_ID, AGENT_ID, APP_SECRET, KF_SECRET, CALLBACK_TOKEN, AES_KEY)
REQUIRED = (CORP_ID, AGENT_ID, APP_SECRET, CALLBACK_TOKEN, AES_KEY)
NOT_CONNECTED = "WeCom is not connected — add its keys on the Connections screen"

# Token errors that mean "get a new token and ask again, once" (the brief; 90313 says what they are).
TOKEN_ERRCODES = frozenset({40014, 42001, 42009})
TOKEN_EARLY_S = 300.0            # refresh this long before WeCom's expires_in runs out
KF_TEXT_MAX_BYTES = 2048         # 94677: text.content is cut beyond 2048 bytes; CLIVE refuses instead
APP_TEXT_MAX_BYTES = 2048        # 90236: the same for an app message

_SETTINGS = {"api": API}


class _NoQueryInTheLog(logging.Filter):
    """httpx logs each request's address at INFO, and WeCom takes the Secret (gettoken) and the
    access token in the address. app/logging/quiet.py keeps httpx at WARNING in the service; this
    takes the query off any WeCom address httpx logs, whatever level anyone sets."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and any("qyapi.weixin.qq.com" in str(a) for a in args):
            record.args = tuple(str(a).split("?", 1)[0] if "qyapi.weixin.qq.com" in str(a) else a for a in args)
        return True


logging.getLogger("httpx").addFilter(_NoQueryInTheLog())


# ------------------------------------------------------------------ the keys


def _stored(name: str) -> str:
    try:
        return (keychain.get_optional(name) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has nothing to give
        return ""


# Values being tested on the Connections screen before they are stored: set by `trying`, read by
# `value`, and given their own tokens, so a test never touches what is in use.
_TRYING: contextvars.ContextVar[tuple[dict[str, str], Tokens] | None] = contextvars.ContextVar("wecom_trying", default=None)


def value(name: str) -> str:
    """One of the six values, read from the secret store at each call so a key stored on the
    Connections screen works at once (or, inside `trying`, the value being tested)."""
    held = _TRYING.get()
    if held is not None:
        return str(held[0].get(name) or "").strip()
    return _stored(name)


@contextlib.contextmanager
def trying(values: dict[str, str]):
    """Run calls with these values and tokens of their own, as the Connections test does, without
    storing them or touching the tokens CLIVE is using."""
    token = _TRYING.set(({str(k): str(v or "") for k, v in values.items()}, Tokens()))
    try:
        yield
    finally:
        _TRYING.reset(token)


def _tokens() -> Tokens:
    held = _TRYING.get()
    return held[1] if held is not None else TOKENS


def configured() -> bool:
    return all(value(k) for k in REQUIRED)


def missing() -> list[str]:
    return [k for k in REQUIRED if not value(k)]


# ------------------------------------------------------------------ plain words for errcodes

ERRCODE_WORDS: dict[int, str] = {
    -1: "WeCom is busy just now; try again in a moment.",
    40001: "WeCom refused the app's Secret. Copy it again from the app's page in the WeCom admin console.",
    40003: "WeCom has no member with that UserID.",
    40013: "WeCom doesn't recognise that CorpID. It is at the bottom of My Company (我的企业) in the admin console.",
    40014: "WeCom said CLIVE's access token was not valid.",
    40031: "Those members aren't in this app's visible range (可见范围).",
    40056: "That AgentID isn't this app's. It is on the app's own page, beside its Secret.",
    40096: "That WeChat contact's id isn't valid for this company.",
    41001: "WeCom was sent no access token.",
    41002: "WeCom was sent no CorpID.",
    41004: "WeCom was sent no Secret.",
    42001: "CLIVE's WeCom access token had expired.",
    42009: "CLIVE's WeCom access token had expired.",
    44004: "The message was empty.",
    45009: "WeCom is limiting CLIVE's requests just now; try again in a minute.",
    45033: "WeCom is limiting CLIVE's requests just now; try again in a minute.",
    48001: "This app hasn't been given that API in the WeCom admin console.",
    48002: ("This app isn't allowed to call that API. In the WeCom admin console, add the app under that "
            "feature's API settings (可调用接口的应用)."),
    60011: "That person isn't in this app's visible range (可见范围). Add them on the app's page.",
    60020: "WeCom refused this server's address. Add it to the app's Trusted IPs (企业可信IP).",
    60111: "WeCom has no member with that UserID.",
    81013: "Nobody this was for can get messages from this app: check the app's visible range (可见范围).",
    84061: "That person isn't one of your WeCom contacts.",
    95000: "That customer-service account isn't valid.",
    95001: "WeChat allows only five replies after a contact's last message. Wait for them to write again.",
    95002: ("It is more than 48 hours since they last wrote, so WeChat won't take a reply through customer "
            "service. Ask them to message the CROOKS customer-service account first."),
    95003: "WeCom limits customer-service conversations until the company is verified (企业认证).",
    95004: "That customer-service account isn't this company's, or it was deleted.",
    95007: "The message token from WeCom had expired.",
    95011: "WeChat customer service is run inside WeCom, and this Secret is the standalone one.",
    95012: "WeChat customer service is run standalone, and this Secret is WeCom's.",
    95013: "That conversation has ended.",
    95014: "The person set to answer isn't an active customer-service agent.",
    95016: "WeCom doesn't allow that change to the conversation.",
    95017: "The customer-service API switch is off in the WeCom admin console (微信客服 → API).",
    95018: ("That conversation is with a person in WeCom, or more than 48 hours old, so CLIVE can't send in it. "
            "Answer it in WeCom, or wait for them to write again."),
    95019: "The customer-service agent has stopped receiving or is paused.",
    301002: "The AgentID and the Secret belong to different apps.",
}

# The errcodes WeCom gives for "this app may not do that": the probe says to switch something on.
PERMISSION_ERRCODES = frozenset({48001, 48002, 60011, 95017, 301002, 60020})
_FROM_IP = re.compile(r"from ip:\s*([0-9a-fA-F:.]{3,45})")


def server_address(errmsg: Any) -> str:
    """The address WeCom says a refused call came from (its errmsg carries "from ip: …")."""
    found = _FROM_IP.search(str(errmsg or ""))
    return found.group(1) if found else ""


def words_for(errcode: int, errmsg: Any = "") -> str:
    """An errcode as George can be told it. Only the server address of a 60020 is taken from
    WeCom's own text; nothing else it said is repeated."""
    said = ERRCODE_WORDS.get(int(errcode))
    if said is None:
        return f"WeCom said no (error {int(errcode)})."
    if int(errcode) == 60020:
        address = server_address(errmsg)
        if address:
            return (f"WeCom refused this server's address {address}. Add {address} to the app's Trusted IPs "
                    "(企业可信IP) in the WeCom admin console.")
    return said


class WeComError(RuntimeError):
    """WeCom could not do this, in words George can be told. `kind`: no_key, refused (WeCom
    answered with an errcode), timeout, unreachable, unreadable. `refused` is True when WeCom
    answered and so nothing was done, which the action engine reads to say so."""

    plain_words = True   # its words are written to be said (app/actions/engine.py `_refusal_words`)

    def __init__(self, said: str, *, kind: str, errcode: int = 0) -> None:
        super().__init__(said)
        self.kind = kind
        self.errcode = errcode
        self.refused = kind in ("refused", "no_key")


# ------------------------------------------------------------------ the callback crypto


class CryptoError(ValueError):
    """A callback that is not WeCom's, or not this company's. `code` is the sample library's own
    (ierror.py): -40001 signature, -40002 parse, -40004 key, -40005 receive id, -40007 decrypt."""

    def __init__(self, code: int, why: str) -> None:
        super().__init__(why)
        self.code = code


BLOCK = 32
_KEY_CHARS = re.compile(r"^[A-Za-z0-9]{43}$")


def aes_key(encoding_aes_key: str) -> bytes:
    """AESKey = Base64_Decode(EncodingAESKey + "="): 43 characters in, 32 bytes out, or refused."""
    text = str(encoding_aes_key or "").strip()
    if not _KEY_CHARS.match(text):
        raise CryptoError(-40004, "the EncodingAESKey is not 43 letters and digits")
    try:
        key = base64.b64decode(text + "=", validate=True)
    except ValueError:
        raise CryptoError(-40004, "the EncodingAESKey does not decode") from None
    if len(key) != 32:
        raise CryptoError(-40004, "the EncodingAESKey does not decode to 32 bytes")
    return key


def signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """dev_msg_signature = sha1(sort(token, timestamp, nonce, msg_encrypt)), lower-case hex."""
    parts = sorted([str(token), str(timestamp), str(nonce), str(encrypt)])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def _pad(data: bytes) -> bytes:
    amount = BLOCK - (len(data) % BLOCK)
    return data + bytes([amount]) * amount


def _unpad(data: bytes) -> bytes:
    if not data:
        raise CryptoError(-40007, "nothing to decrypt")
    amount = data[-1]
    if amount < 1 or amount > BLOCK or len(data) < amount or data[-amount:] != bytes([amount]) * amount:
        raise CryptoError(-40007, "the padding is wrong")
    return data[:-amount]


class CallbackCrypto:
    """WXBizMsgCrypt, as WeCom's sample libraries define it, for one company's callback."""

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str) -> None:
        self.token = str(token or "")
        self.key = aes_key(encoding_aes_key)
        self.receive_id = str(receive_id or "")
        if not self.token or not self.receive_id:
            raise CryptoError(-40004, "the callback Token or the CorpID is missing")

    def signed(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str) -> bool:
        expected = signature(self.token, timestamp, nonce, encrypt)
        return hmac.compare_digest(expected.encode("ascii"), str(msg_signature or "").lower().encode("utf-8", "replace"))

    def decrypt(self, encrypt: str) -> str:
        try:
            raw = base64.b64decode(str(encrypt or ""), validate=True)
        except ValueError:
            raise CryptoError(-40010, "the ciphertext is not base64") from None
        if not raw or len(raw) % 16:
            raise CryptoError(-40007, "the ciphertext is not whole AES blocks")
        decryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16])).decryptor()
        plain = _unpad(decryptor.update(raw) + decryptor.finalize())
        if len(plain) < 20:
            raise CryptoError(-40008, "the plaintext is too short")
        (length,) = struct.unpack(">I", plain[16:20])
        if 20 + length > len(plain):
            raise CryptoError(-40008, "the plaintext's length is wrong")
        message, receive_id = plain[20:20 + length], plain[20 + length:]
        if not hmac.compare_digest(receive_id, self.receive_id.encode("utf-8")):
            raise CryptoError(-40005, "the message is for another company")
        try:
            return message.decode("utf-8")
        except UnicodeDecodeError:
            raise CryptoError(-40008, "the message is not UTF-8") from None

    def encrypt(self, text: str, *, random16: bytes | None = None) -> str:
        """For a passive reply, and for the tests: the same scheme the other way round."""
        body = str(text).encode("utf-8")
        head = random16 if random16 is not None else os.urandom(16)
        if len(head) != 16:
            raise CryptoError(-40006, "the random prefix must be 16 bytes")
        plain = _pad(head + struct.pack(">I", len(body)) + body + self.receive_id.encode("utf-8"))
        encryptor = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16])).encryptor()
        return base64.b64encode(encryptor.update(plain) + encryptor.finalize()).decode("ascii")

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        """The GET WeCom sends when the URL is saved: signature first, then the echo's plaintext."""
        if not self.signed(msg_signature, timestamp, nonce, echostr):
            raise CryptoError(-40001, "the signature does not match")
        return self.decrypt(echostr)

    def decrypt_message(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str) -> str:
        if not self.signed(msg_signature, timestamp, nonce, encrypt):
            raise CryptoError(-40001, "the signature does not match")
        return self.decrypt(encrypt)


def crypto() -> CallbackCrypto:
    """The callback crypto for the values stored now. Raises CryptoError when any is missing."""
    return CallbackCrypto(value(CALLBACK_TOKEN), value(AES_KEY), value(CORP_ID))


# ------------------------------------------------------------------ the envelope and the message

_FORBIDDEN_XML = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.I)


def _xml(raw: bytes | str) -> ET.Element:
    """XML from WeCom, refused if it declares a document type or an entity (nothing WeCom sends
    does), so no entity can expand however the parser is built."""
    data = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
    if _FORBIDDEN_XML.search(data):
        raise CryptoError(-40002, "the XML declares a document type")
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise CryptoError(-40002, "the XML does not parse") from None


def envelope(body: bytes) -> dict[str, str]:
    """The outer callback (xml or json, 90238): ToUserName, AgentID and the Encrypt field."""
    text = bytes(body or b"").strip()
    if text.startswith(b"{"):
        try:
            data = json.loads(text.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            # RecursionError: JSON nested thousands deep fits under the body cap and would otherwise
            # end the request in a 500 (review note 1, 8 Oct).
            raise CryptoError(-40002, "the JSON does not parse") from None
        if not isinstance(data, dict):
            raise CryptoError(-40002, "the JSON is not an object")
        lower = {str(k).lower(): v for k, v in data.items()}
        found = {"ToUserName": lower.get("tousername"), "AgentID": lower.get("agentid"), "Encrypt": lower.get("encrypt")}
    else:
        root = _xml(text)
        found = {name: (root.findtext(name) or "") for name in ("ToUserName", "AgentID", "Encrypt")}
    out = {k: str(v or "").strip() for k, v in found.items()}
    if not out["Encrypt"]:
        raise CryptoError(-40002, "there is no Encrypt field")
    return out


def message_fields(plaintext: str) -> dict[str, str]:
    """A decrypted message or event (90239, 90240, 94670), one level deep: tag → text."""
    stripped = plaintext.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except (ValueError, RecursionError):
            raise CryptoError(-40002, "the message JSON does not parse") from None
        return {str(k): str(v) for k, v in data.items() if not isinstance(v, (dict, list))} if isinstance(data, dict) else {}
    root = _xml(stripped)
    return {child.tag: (child.text or "").strip() for child in root}


# ------------------------------------------------------------------ access tokens


@dataclass
class _Held:
    token: str = ""
    expires_at: float = 0.0


class Tokens:
    """One access token per Secret (the app's, and customer service's when it has its own), in
    memory only, asked for again TOKEN_EARLY_S before it runs out, one request at a time."""

    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        self._held: dict[str, _Held] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.minted = 0          # gettoken calls made, for the tests

    def forget(self, kind: str | None = None) -> None:
        if kind is None:
            self._held.clear()
        else:
            self._held.pop(kind, None)

    def _fresh(self, kind: str) -> str:
        held = self._held.get(kind)
        if held and held.token and self.clock() < held.expires_at - TOKEN_EARLY_S:
            return held.token
        return ""

    async def get(self, kind: str = "app") -> str:
        token = self._fresh(kind)
        if token:
            return token
        lock = self._locks.setdefault(kind, asyncio.Lock())
        async with lock:
            token = self._fresh(kind)
            if token:
                return token
            secret = secret_for(kind)
            corp = value(CORP_ID)
            if not corp or not secret:
                raise WeComError(f"{NOT_CONNECTED}.", kind="no_key")
            answer = await _request("GET", "/gettoken", params={"corpid": corp, "corpsecret": secret})
            self.minted += 1
            code = _errcode(answer)
            if code != 0:
                log.info("wecom: gettoken refused (errcode %s)", code)
                raise WeComError(words_for(code, answer.get("errmsg")), kind="refused", errcode=code)
            token = str(answer.get("access_token") or "")
            try:
                life = float(answer.get("expires_in") or 7200)
            except (TypeError, ValueError):
                life = 7200.0
            if not token:
                raise WeComError("WeCom answered without a token.", kind="unreadable")
            self._held[kind] = _Held(token, self.clock() + life)
            return token


TOKENS = Tokens()


async def token_check() -> None:
    """Mint an access token with the values in use (or being tried): proves the CorpID and the
    app's Secret belong together. Raises WeComError in plain words when they do not."""
    await _tokens().get("app")


def secret_for(kind: str) -> str:
    """Customer-service calls use their own Secret when George stored one; otherwise the app's,
    which is the rule since 1 December 2023 (94670: the system app's Secret is no longer taken)."""
    if kind == "kf":
        return value(KF_SECRET) or value(APP_SECRET)
    return value(APP_SECRET)


def forget() -> None:
    """A key was stored or taken away: every token goes, and the next call asks again."""
    TOKENS.forget()


# ------------------------------------------------------------------ requests


def http_client(timeout_s: float) -> httpx.AsyncClient:
    """A client for one call; looked up per call so a test can put a transport in its place.
    Redirects are never followed, so a token never reaches another host."""
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False)


def _errcode(answer: dict[str, Any]) -> int:
    try:
        return int(answer.get("errcode") or 0)
    except (TypeError, ValueError):
        return -1


async def _request(method: str, path: str, *, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
                   timeout_s: float = TIMEOUT_S) -> dict[str, Any]:
    url = f"{_SETTINGS['api']}{path}"
    try:
        async with http_client(timeout_s) as client:
            if method == "GET":
                response = await asyncio.wait_for(client.get(url, params=params), timeout_s)
            else:
                payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
                response = await asyncio.wait_for(
                    client.post(url, params=params, content=payload, headers={"Content-Type": "application/json"}), timeout_s)
    except (TimeoutError, httpx.TimeoutException):
        raise WeComError("WeCom did not answer in time.", kind="timeout") from None
    except httpx.HTTPError:
        raise WeComError("WeCom could not be reached from this server.", kind="unreachable") from None
    if response.status_code != 200:
        log.info("wecom: %s answered HTTP %s", path, response.status_code)
        raise WeComError(f"WeCom answered {response.status_code}; try again shortly.", kind="unreachable")
    try:
        answer = response.json()
    except ValueError:
        raise WeComError("WeCom answered with something unreadable.", kind="unreadable") from None
    if not isinstance(answer, dict):
        raise WeComError("WeCom answered with something unreadable.", kind="unreadable")
    return answer


async def call(method: str, path: str, *, kind: str = "app", params: dict[str, Any] | None = None,
               body: dict[str, Any] | None = None, timeout_s: float = TIMEOUT_S) -> dict[str, Any]:
    """One API call with a token. A token WeCom calls invalid or expired is replaced once and the
    call asked once more; any other errcode is a WeComError in plain words."""
    for attempt in (1, 2):
        token = await _tokens().get(kind)
        answer = await _request(method, path, params={**(params or {}), "access_token": token}, body=body,
                                timeout_s=timeout_s)
        code = _errcode(answer)
        if code in TOKEN_ERRCODES and attempt == 1:
            log.info("wecom: token refused on %s (errcode %s); asking for a new one once", path, code)
            _tokens().forget(kind)
            continue
        if code != 0:
            log.info("wecom: %s refused (errcode %s)", path, code)
            raise WeComError(words_for(code, answer.get("errmsg")), kind="refused", errcode=code)
        return answer
    raise WeComError("WeCom kept refusing CLIVE's access token.", kind="refused")   # pragma: no cover


# ------------------------------------------------------------------ the calls CLIVE makes


async def agent() -> dict[str, Any]:
    """agent/get: the app the AgentID names, read with its Secret (both must be the same app's)."""
    return await call("GET", "/agent/get", params={"agentid": value(AGENT_ID)})


async def kf_accounts() -> list[dict[str, Any]]:
    """kf/account/list (94661): the customer-service accounts, and whether this app manages each."""
    answer = await call("POST", "/kf/account/list", kind="kf", body={"offset": 0, "limit": 100})
    found = answer.get("account_list")
    return [a for a in found if isinstance(a, dict)] if isinstance(found, list) else []


async def kf_sync(open_kfid: str, *, cursor: str = "", token: str = "", limit: int = 1000) -> dict[str, Any]:
    """kf/sync_msg (94670): messages since `cursor` for one account, with the callback's token."""
    body: dict[str, Any] = {"open_kfid": str(open_kfid), "limit": max(1, min(int(limit), 1000)), "voice_format": 0}
    if cursor:
        body["cursor"] = str(cursor)
    if token:
        body["token"] = str(token)
    return await call("POST", "/kf/sync_msg", kind="kf", body=body)


async def kf_state(open_kfid: str, external_userid: str) -> int:
    """kf/service_state/get (94669): 0 new, 1 the assistant (the API), 2 queued, 3 a person, 4 ended."""
    answer = await call("POST", "/kf/service_state/get", kind="kf",
                        body={"open_kfid": str(open_kfid), "external_userid": str(external_userid)})
    try:
        return int(answer.get("service_state"))
    except (TypeError, ValueError):
        return -1


async def kf_customers(external_userids: list[str]) -> dict[str, str]:
    """kf/customer/batchget (95159): each contact's WeChat nickname, for the thread's name."""
    ids = [str(i) for i in external_userids if i][:100]
    if not ids:
        return {}
    answer = await call("POST", "/kf/customer/batchget", kind="kf", body={"external_userid_list": ids})
    out: dict[str, str] = {}
    for row in answer.get("customer_list") or []:
        if isinstance(row, dict) and row.get("external_userid"):
            out[str(row["external_userid"])] = " ".join(str(row.get("nickname") or "").split())[:60]
    return out


def utf8_bytes(text: str) -> int:
    return len(str(text).encode("utf-8"))


_MSGID = re.compile(r"^[0-9A-Za-z_-]{1,32}$")


async def send_kf_text(open_kfid: str, external_userid: str, text: str, *, msgid: str) -> str:
    """kf/send_msg (94677): one text to a WeChat contact through a customer-service account. The
    msgid is CLIVE's own, so the message is known by it. Returns WeCom's msgid; anything but
    errcode 0 with a msgid raises, and nothing is said to have gone."""
    if not _MSGID.match(str(msgid)):
        raise WeComError("That message id isn't one WeCom takes.", kind="refused")
    if not str(text).strip():
        raise WeComError(ERRCODE_WORDS[44004], kind="refused", errcode=44004)
    if utf8_bytes(text) > KF_TEXT_MAX_BYTES:
        raise WeComError("That message is longer than WeChat takes (2048 bytes); shorten it.", kind="refused")
    answer = await call("POST", "/kf/send_msg", kind="kf", body={
        "touser": str(external_userid), "open_kfid": str(open_kfid), "msgid": str(msgid),
        "msgtype": "text", "text": {"content": str(text)}})
    sent = str(answer.get("msgid") or "")
    if not sent:
        raise WeComError("WeCom accepted the message but gave no message id, so it isn't counted as sent.",
                         kind="unreadable")
    return sent


async def send_member_text(userid: str, text: str) -> str:
    """message/send (90236): one text from the app to one member of the company. Duplicate check
    on (1800 s), so a request repeated after a lost answer is not delivered twice. Returns WeCom's
    msgid; a member WeCom names invalid or unlicensed is a refusal, never a send."""
    if not str(text).strip():
        raise WeComError(ERRCODE_WORDS[44004], kind="refused", errcode=44004)
    if utf8_bytes(text) > APP_TEXT_MAX_BYTES:
        raise WeComError("That message is longer than WeCom takes (2048 bytes); shorten it.", kind="refused")
    try:
        agent_id = int(value(AGENT_ID))
    except ValueError:
        raise WeComError(ERRCODE_WORDS[40056], kind="no_key", errcode=40056) from None
    answer = await call("POST", "/message/send", body={
        "touser": str(userid), "msgtype": "text", "agentid": agent_id, "text": {"content": str(text)},
        "safe": 0, "enable_duplicate_check": 1, "duplicate_check_interval": 1800})
    wanted = str(userid).lower()
    for field_name in ("invaliduser", "unlicenseduser"):
        refused = {u.strip().lower() for u in str(answer.get(field_name) or "").split("|") if u.strip()}
        if wanted in refused:
            raise WeComError(ERRCODE_WORDS[60011] if field_name == "invaliduser"
                             else "That member has no WeCom licence for apps, so the message wasn't delivered.",
                             kind="refused", errcode=60011)
    sent = str(answer.get("msgid") or "")
    if not sent:
        raise WeComError("WeCom accepted the message but gave no message id, so it isn't counted as sent.",
                         kind="unreadable")
    return sent


async def follow_users() -> list[str]:
    """externalcontact/get_follow_user_list (92571): who may have customer contacts. Only asked
    by the probe, to learn whether 客户联系 is open to this app."""
    answer = await call("GET", "/externalcontact/get_follow_user_list")
    found = answer.get("follow_user")
    return [str(u) for u in found] if isinstance(found, list) else []
