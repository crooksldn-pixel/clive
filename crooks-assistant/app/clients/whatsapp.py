"""WhatsApp, through Meta's own WhatsApp Business Cloud API (graph.facebook.com), as CLIVE reaches the
people CROOKS works with on WhatsApp: a supplier, or a customer, whichever George puts on the number.

Why it exists: George approved WhatsApp beside WeChat (7 October), ready to switch on when he stores
its keys. This is every call CLIVE makes to WhatsApp; app/messaging/whatsapp.py turns them into
conversations, and docs/WHATSAPP.md says what he sets up at Meta.

What it promises:
- Five values, read from the secret store at each call (so keys stored on the Connections screen work
  at once): the business phone number's id, the WhatsApp Business Account's id, a permanent access
  token (a system user's), the Meta app's secret (it signs what Meta sends to /hooks/whatsapp) and a
  verify token George chooses (Meta sends it back when the callback URL is saved).
- The token travels in the Authorization header, never in an address, so nothing that logs a URL
  can carry it. Redirects are never followed.
- One send, `send_text`, of one text to one person, only ever called by the action engine after the
  owner's hold (app/tools/messaging_tools.py). It returns WhatsApp's message id ("wamid.…") and
  nothing else counts as sent; an answer without one is an error. WhatsApp's own "sent, delivered,
  read, failed" arrive later at the door (app/messaging/whatsapp.py).
- Two calls change Meta's settings, never a message: `subscribe` (Meta sends this WhatsApp account's
  webhooks to the app) and `register` (the number joins the Cloud API, with its two-step PIN). Only
  scripts/whatsapp.py makes them, run by hand on the server; nothing in the running app does.
- No template message is ever sent: outside the 24 hours after a person's last message WhatsApp
  takes only an approved template, which Meta charges for, so CLIVE refuses instead (131047).
- Every refusal is one WhatsAppError in plain words George can be told, from Meta's error code;
  Meta's own message is never repeated (it can echo the request). Nothing here logs a token, a
  number, a name or a word anybody wrote: log lines name a kind and a code.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import re
from typing import Any

import httpx

from app.secrets import keychain

log = logging.getLogger("crooks.whatsapp")

NAME = "WhatsApp"
HOST = "https://graph.facebook.com"
VERSION = "v25.0"            # the version Meta's WhatsApp documentation uses throughout (October 2026)
TIMEOUT_S = 10.0
TEXT_MAX_CHARS = 4096        # a text message's body, at most (Meta: "Maximum 4096 characters")

PHONE_NUMBER_ID = "whatsapp_phone_number_id"
BUSINESS_ACCOUNT_ID = "whatsapp_business_account_id"
ACCESS_TOKEN = "whatsapp_access_token"
APP_SECRET = "whatsapp_app_secret"
VERIFY_TOKEN = "whatsapp_verify_token"
KEYS = (PHONE_NUMBER_ID, BUSINESS_ACCOUNT_ID, ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN)
REQUIRED = KEYS
NOT_CONNECTED = "WhatsApp is not connected — add its keys on the Connections screen"

# Meta's ids are digits; a token is long and has no spaces. Checked before a value is used in a path.
_ID = re.compile(r"^[0-9]{5,30}$")
_RECIPIENT = re.compile(r"^\+?[0-9]{6,20}$")

# Meta's error codes, as George can be told them (developers.facebook.com/documentation/
# business-messaging/whatsapp/support/error-codes).
TOKEN_WORDS = ("Meta refused CLIVE's WhatsApp access token: it has expired or been revoked. Make a permanent "
               "one (a system user's token, set to never expire) and store it on Connections → WhatsApp.")
PERMISSION_WORDS = ("Meta says the WhatsApp token isn't allowed to do that. It needs the permissions "
                    "whatsapp_business_messaging and whatsapp_business_management, and its system user needs "
                    "this WhatsApp account assigned to it in Business settings.")
SLOW_WORDS = "WhatsApp is limiting how fast CLIVE can send just now; try again in a few minutes."
BUSY_WORDS = "WhatsApp is having trouble just now; try again shortly."
WINDOW_WORDS = ("It is more than 24 hours since they last wrote, so WhatsApp takes only an approved template "
                "message, which CLIVE doesn't send. They need to message you first.")
ERROR_WORDS: dict[int, str] = {
    0: TOKEN_WORDS, 190: TOKEN_WORDS,
    3: PERMISSION_WORDS, 10: PERMISSION_WORDS, 131005: PERMISSION_WORDS,
    4: SLOW_WORDS, 80007: SLOW_WORDS, 130429: SLOW_WORDS,
    131056: "WhatsApp is limiting messages to this person just now; wait a little before sending them another.",
    1: BUSY_WORDS, 2: BUSY_WORDS, 131000: BUSY_WORDS, 131016: BUSY_WORDS, 133004: BUSY_WORDS,
    33: "Meta says that WhatsApp phone number was deleted. Check the phone number id on Connections → WhatsApp.",
    100: "WhatsApp said the request wasn't valid. Check the phone number id and account id on Connections → WhatsApp.",
    131008: "WhatsApp said the request wasn't valid. Check the phone number id on Connections → WhatsApp.",
    131009: "WhatsApp said a value in the request wasn't valid (often the phone number id, or their number).",
    131021: "That is the business's own number.",
    131026: ("WhatsApp couldn't deliver to that person: the number may not be on WhatsApp, or they haven't "
             "accepted WhatsApp's latest terms, or their app is out of date."),
    131031: "Meta has restricted this WhatsApp Business account. Check the account in WhatsApp Manager.",
    368: "Meta has restricted this WhatsApp Business account for a policy reason. Check WhatsApp Manager.",
    131042: "WhatsApp says there is a problem with the account's payment method. Check billing in WhatsApp Manager.",
    131045: "This phone number isn't registered for the WhatsApp Cloud API yet (docs/WHATSAPP.md, registering the number).",
    133010: "This phone number isn't registered for the WhatsApp Cloud API yet (docs/WHATSAPP.md, registering the number).",
    131047: WINDOW_WORDS,
    131048: ("WhatsApp is limiting this number because too many of its messages were blocked or reported. Check "
             "its quality in WhatsApp Manager."),
    131049: "WhatsApp held the message back to keep engagement healthy. That is Meta's choice, not a fault.",
    131050: "They have chosen to stop receiving marketing messages from CROOKS on WhatsApp.",
    131051: "WhatsApp doesn't take that kind of message.",
    131057: "The WhatsApp account is in maintenance mode; try again in a few minutes.",
    2494100: "The WhatsApp number is in maintenance mode; try again in a few minutes.",
    130403: "CROOKS has blocked this person on WhatsApp. Unblock them in WhatsApp Manager to message them.",
    130497: "WhatsApp doesn't let this account message people in their country.",
}
# The errors that mean the keys or Meta's settings, not this one message: the probe says what to do.
TOKEN_CODES = frozenset({0, 190})
PERMISSION_CODES = frozenset({3, 10, 131005}) | frozenset(range(200, 300))


def words_for(code: int) -> str:
    """A Meta error code as George can be told it. Nothing Meta wrote is repeated."""
    code = int(code or 0)
    if code in ERROR_WORDS:
        return ERROR_WORDS[code]
    if 200 <= code < 300:
        return PERMISSION_WORDS
    return f"WhatsApp said no (error {code})."


class WhatsAppError(RuntimeError):
    """WhatsApp could not do this, in words George can be told. `kind`: no_key, refused (Meta answered
    with an error, so nothing was done), timeout, unreachable, unreadable. `refused` is what the
    action engine reads to say nothing was sent (app/actions/engine.py)."""

    plain_words = True

    def __init__(self, said: str, *, kind: str, code: int = 0) -> None:
        super().__init__(said)
        self.kind = kind
        self.code = int(code or 0)

    @property
    def refused(self) -> bool:
        return self.kind in ("refused", "no_key")


# ------------------------------------------------------------------ the keys


def _stored(name: str) -> str:
    try:
        return (keychain.get_optional(name) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has nothing to give
        return ""


# Values being tested on the Connections screen before they are stored (as app/clients/wecom.py).
_TRYING: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("whatsapp_trying", default=None)


def value(name: str) -> str:
    held = _TRYING.get()
    if held is not None:
        return str(held.get(name) or "").strip()
    return _stored(name)


@contextlib.contextmanager
def trying(values: dict[str, str]):
    """Run calls with these values, as the Connections test does, without storing them."""
    token = _TRYING.set({str(k): str(v or "") for k, v in values.items()})
    try:
        yield
    finally:
        _TRYING.reset(token)


def configured() -> bool:
    return all(value(k) for k in REQUIRED)


def can_send() -> bool:
    """The two values a send needs: the number to send from and the token to send with."""
    return bool(value(PHONE_NUMBER_ID) and value(ACCESS_TOKEN))


def missing() -> list[str]:
    return [k for k in REQUIRED if not value(k)]


# ------------------------------------------------------------------ requests


def http_client(timeout_s: float) -> httpx.AsyncClient:
    """A client for one call; looked up per call so a test can put a transport in its place."""
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False)


def _error_code(response: httpx.Response) -> int:
    try:
        error = (response.json() or {}).get("error") or {}
        return int(error.get("code") or 0)
    except (ValueError, AttributeError, TypeError):
        return 0


def _path_id(name: str) -> str:
    found = value(name)
    if not _ID.match(found):
        label = "phone number id" if name == PHONE_NUMBER_ID else "WhatsApp Business Account id"
        raise WhatsAppError(f"The {label} on Connections → WhatsApp isn't one Meta gives (digits only).",
                            kind="no_key")
    return found


async def _request(method: str, path: str, *, params: dict[str, str] | None = None,
                   body: dict[str, Any] | None = None) -> dict[str, Any]:
    token = value(ACCESS_TOKEN)
    if not token:
        raise WhatsAppError(f"{NOT_CONNECTED}.", kind="no_key")
    url = f"{HOST}/{VERSION}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        async with http_client(TIMEOUT_S) as client:
            if method == "GET":
                response = await asyncio.wait_for(client.get(url, params=params, headers=headers), TIMEOUT_S)
            else:
                headers["Content-Type"] = "application/json"
                payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
                response = await asyncio.wait_for(client.post(url, params=params, content=payload, headers=headers),
                                                  TIMEOUT_S)
    except (TimeoutError, httpx.TimeoutException):
        raise WhatsAppError("WhatsApp did not answer in time.", kind="timeout") from None
    except httpx.HTTPError:
        raise WhatsAppError("WhatsApp could not be reached from this server.", kind="unreachable") from None
    if response.status_code != 200:
        code = _error_code(response)
        log.info("whatsapp: a %s answered HTTP %s (error %s)", method, response.status_code, code)
        if not code and response.status_code >= 500:
            raise WhatsAppError(BUSY_WORDS, kind="unreachable")
        raise WhatsAppError(words_for(code), kind="refused", code=code)
    try:
        answer = response.json()
    except ValueError:
        raise WhatsAppError("WhatsApp answered with something unreadable.", kind="unreadable") from None
    if not isinstance(answer, dict):
        raise WhatsAppError("WhatsApp answered with something unreadable.", kind="unreadable")
    return answer


# ------------------------------------------------------------------ the calls CLIVE makes


async def phone_number() -> dict[str, str]:
    """The business phone number as Meta holds it: its display number, the name it shows, its status
    (it must be CONNECTED to send and receive), its quality rating and verification."""
    answer = await _request("GET", _path_id(PHONE_NUMBER_ID), params={
        "fields": "display_phone_number,verified_name,status,quality_rating,code_verification_status"})
    return {k: " ".join(str(answer.get(k) or "").split())[:80] for k in (
        "display_phone_number", "verified_name", "status", "quality_rating", "code_verification_status")}


async def business_account() -> dict[str, str]:
    """The WhatsApp Business Account the id names: read to prove the token may see it."""
    answer = await _request("GET", _path_id(BUSINESS_ACCOUNT_ID), params={"fields": "id,name"})
    return {"id": str(answer.get("id") or ""), "name": " ".join(str(answer.get("name") or "").split())[:80]}


async def subscribed_apps() -> list[str]:
    """The apps Meta sends this WhatsApp account's webhooks to, by name, exactly as Meta lists them."""
    answer = await _request("GET", f"{_path_id(BUSINESS_ACCOUNT_ID)}/subscribed_apps")
    names = []
    for row in answer.get("data") or []:
        data = row.get("whatsapp_business_api_data") if isinstance(row, dict) else None
        if isinstance(data, dict):
            names.append(" ".join(str(data.get("name") or data.get("id") or "").split())[:60])
    return names


async def send_text(to: str, text: str) -> str:
    """POST /<phone number id>/messages: one text to one person (Meta's text message). Returns
    WhatsApp's message id; anything else raises, and nothing is said to have gone. Only the action
    engine calls this, after the owner's hold."""
    recipient = str(to or "").strip()
    if not _RECIPIENT.match(recipient):
        raise WhatsAppError("That isn't a WhatsApp number CLIVE can send to.", kind="refused")
    words = str(text or "")
    if not words.strip():
        raise WhatsAppError("The message is empty.", kind="refused")
    if len(words) > TEXT_MAX_CHARS:
        raise WhatsAppError("That message is longer than WhatsApp takes (4,096 characters); shorten it.", kind="refused")
    answer = await _request("POST", f"{_path_id(PHONE_NUMBER_ID)}/messages", body={
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": recipient, "type": "text",
        "text": {"preview_url": False, "body": words}})
    sent = ""
    for row in answer.get("messages") or []:
        if isinstance(row, dict) and str(row.get("id") or "").strip():
            sent = str(row["id"]).strip()
            break
    if not sent:
        raise WhatsAppError("WhatsApp accepted the message but gave no message id, so it isn't counted as sent.",
                            kind="unreadable")
    return sent


# ------------------------------------------------------------------ set-up, run by hand (scripts/whatsapp.py)


async def subscribe() -> bool:
    """POST /<WhatsApp Business Account id>/subscribed_apps: Meta sends this account's webhooks to the
    app whose token this is. Changes a Meta setting; sends no message."""
    answer = await _request("POST", f"{_path_id(BUSINESS_ACCOUNT_ID)}/subscribed_apps")
    return answer.get("success") is True


async def register(pin: str) -> bool:
    """POST /<phone number id>/register: the number joins the Cloud API, with its six-digit two-step
    PIN (the existing one, or the one it is set to now). Changes a Meta setting; sends no message."""
    if not (len(str(pin)) == 6 and str(pin).isdigit()):
        raise WhatsAppError("The two-step PIN is six digits.", kind="refused")
    answer = await _request("POST", f"{_path_id(PHONE_NUMBER_ID)}/register",
                            body={"messaging_product": "whatsapp", "pin": str(pin)})
    return answer.get("success") is True
