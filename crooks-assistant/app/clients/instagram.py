"""Instagram, for the owner's inbox: the CROOKS account's direct messages and the comments on
its posts. Read-only.

- Every call goes to graph.instagram.com, the Instagram API with Instagram Login, with the
  account's long-lived Instagram User access token stored as `instagram_access_token`
  (scripts/provision_secrets.py). It is read from the secret store at every call, so a token
  stored later works without a restart.
- The token travels in the Authorization header, never in an address, so no log line or
  exception that carries a URL can carry it. The one exception is the refresh call, which Meta
  defines with the token as a query parameter; that address is built, sent and dropped here and
  never logged or quoted. If the API does not accept the header, the first call learns that and
  this process sends the token as a parameter from then on (`_auth_mode`), again never logged.
- Nothing here sends, replies, likes, hides or deletes anything: every request is a GET, and no
  write the API offers is wired to anything.
- Every failure is one InstagramUnavailable with a `kind` and words the owner can be told. No
  answer or refusal quotes what Meta sent back, because Meta's error text can echo the request.
- A long-lived token lasts 60 days, and Meta renews one only once it is at least a day old
  (`refresh_access_token`, grant_type=ig_refresh_token). `maybe_refresh` renews it on use: a day
  after it was first seen here, then weekly. The expiry Meta returns is kept in a small state
  file beside CLIVE's other records, so /health can say how long is left before it runs out.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from app.secrets import keychain

log = logging.getLogger("crooks.instagram")

HOST = "https://graph.instagram.com"
DEFAULT_VERSION = "v25.0"
TOKEN_KEY = "instagram_access_token"
APP_ID_KEY = "instagram_app_id"
APP_SECRET_KEY = "instagram_app_secret"

TIMEOUT_S = 8.0
MAX_TEXT = 600
MAX_CAPTION = 120
MAX_USERNAME = 60
# The API returns at most the 20 most recent messages of a conversation.
THREAD_MESSAGES = 20
MAX_PAGE = 50
# How often the account's own id and handle are read again (they tell "us" from "them").
ACCOUNT_TTL_S = 3600

# Token lifetime (Meta): 60 days from issue or refresh; a refresh needs a token a day old.
TOKEN_LIFETIME_S = 60 * 86400
MIN_TOKEN_AGE_S = 86400
REFRESH_AFTER_S = 7 * 86400
REFRESH_RETRY_S = 12 * 3600

_VERSION = re.compile(r"^v\d{1,3}\.\d$")
# Instagram's ids: digits for media and comments, a base64url string for a conversation.
ID = re.compile(r"^[A-Za-z0-9_=-]{1,200}$")

_CONFIG: dict[str, Any] = {"version": DEFAULT_VERSION, "state_path": None}
_STATE: dict[str, Any] = {}
_ACCOUNT: dict[str, Any] = {}
_AUTH_MODE = ["header"]


class InstagramUnavailable(RuntimeError):
    """Instagram could not answer this, said as the owner can be told it. `kind` is one of:
    no_token, token (expired or revoked), permission, rate_limited, timeout, unreachable,
    not_found, refused, refresh_blocked."""

    def __init__(self, said: str, *, kind: str) -> None:
        super().__init__(said)
        self.kind = kind


def configure(*, api_version: str | None = None, state_path: Path | None = None) -> None:
    """Called once by the runtime. A version that is not shaped like one keeps the default."""
    if api_version and _VERSION.fullmatch(api_version.strip()):
        _CONFIG["version"] = api_version.strip()
    if state_path is not None:
        _CONFIG["state_path"] = Path(state_path)
        _STATE.clear()
        _STATE.update(_read_state(Path(state_path)))


def reset() -> None:
    """Test helper: forget everything held in this process."""
    _CONFIG.update({"version": DEFAULT_VERSION, "state_path": None})
    _STATE.clear()
    _ACCOUNT.clear()
    _AUTH_MODE[0] = "header"


def auth_mode() -> str:
    """How the token is being sent: "header" (Authorization) or "query" (learned, see `get`)."""
    return _AUTH_MODE[0]


def token() -> str:
    """The stored token, read each time, or ""."""
    try:
        return (keychain.get_optional(TOKEN_KEY) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has no token to give
        return ""


def http_client() -> httpx.AsyncClient:
    """A client for one call. Looked up per call, so a test can put a mocked transport in its
    place. Redirects are not followed: every address here is answered where it is."""
    return httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S), follow_redirects=False)


# --- state: what this machine knows about the token, never the token itself -----------------

def _read_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state() -> None:
    path = _CONFIG.get("state_path")
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".instagram.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_STATE, handle, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        log.warning("instagram state could not be written")


def state() -> dict[str, Any]:
    """A copy of what is known about the token and the last call: timestamps and kinds only."""
    return dict(_STATE)


def _note(**values: Any) -> None:
    _STATE.update(values)
    _save_state()


def _noted_error(exc: InstagramUnavailable) -> InstagramUnavailable:
    _note(last_error_kind=exc.kind, last_error_at=time.time())
    return exc


def _noted_ok() -> None:
    """A call answered. Written to disk when that changes what /health says, and otherwise at
    most every five minutes: a listing of twelve posts is thirteen calls, not thirteen writes."""
    now = time.time()
    recovered = bool(_STATE.get("last_error_kind"))
    _STATE.update(last_ok_at=now, last_error_kind="")
    if recovered or now - float(_STATE.get("saved_at") or 0) > 300:
        _STATE["saved_at"] = now
        _save_state()


# --- the one way a request is made -----------------------------------------------------------

def _error_fields(response: httpx.Response) -> tuple[int, int, str]:
    """(code, subcode, message) from a Graph API error. The message is read only to decide how
    to retry, and is never returned, logged or said."""
    try:
        error = (response.json() or {}).get("error") or {}
        return int(error.get("code") or 0), int(error.get("error_subcode") or 0), str(error.get("message") or "")[:300]
    except (ValueError, AttributeError, TypeError):
        return 0, 0, ""


def _refusal(response: httpx.Response) -> InstagramUnavailable:
    code, _subcode, _message = _error_fields(response)
    status = response.status_code
    if code == 190 or status == 401:
        return InstagramUnavailable(
            "Instagram refused CLIVE's token: it has expired or been revoked. Store a new one with "
            "scripts/provision_secrets.py instagram_access_token.", kind="token")
    if code in (4, 17, 32, 613, 80002) or status == 429:
        return InstagramUnavailable("Instagram has asked CLIVE to slow down; try again in a few minutes.",
                                    kind="rate_limited")
    if code == 10 or code == 3 or 200 <= code <= 299 or status == 403:
        return InstagramUnavailable(
            "Instagram says CLIVE isn't allowed to read that. The token may be missing a permission "
            "(messages need instagram_business_manage_messages, comments "
            "instagram_business_manage_comments), or 'Allow access to messages' is off in the "
            "Instagram app's message settings.", kind="permission")
    if code in (100, 803) or status == 404:
        return InstagramUnavailable("Instagram has nothing at that id.", kind="not_found")
    return InstagramUnavailable(f"Instagram said no ({status}).", kind="refused")


def _header_not_accepted(response: httpx.Response) -> bool:
    """Whether a refusal reads as "no token was sent", which is what an API that does not read
    the Authorization header says. An expired token says so differently and is not retried."""
    code, _subcode, message = _error_fields(response)
    text = message.lower()
    return code == 2500 or (code == 190 and "active access token" in text and "expired" not in text)


async def _send(url: str, params: dict[str, str], access: str, mode: str) -> httpx.Response:
    headers = {"Accept": "application/json"}
    query = dict(params)
    if mode == "header":
        headers["Authorization"] = f"Bearer {access}"
    else:
        query["access_token"] = access
    try:
        async with http_client() as client:
            return await asyncio.wait_for(client.get(url, params=query, headers=headers), TIMEOUT_S)
    except (TimeoutError, httpx.TimeoutException):
        raise InstagramUnavailable("Instagram did not answer in time.", kind="timeout") from None
    except httpx.HTTPError:
        raise InstagramUnavailable("Instagram could not be reached.", kind="unreachable") from None


async def get(path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """GET one Graph API object or edge (`me/conversations`, an id) and return its JSON."""
    access = token()
    if not access:
        raise InstagramUnavailable(
            "Instagram isn't connected: there is no Instagram token on the server yet.", kind="no_token")
    url = f"{HOST}/{_CONFIG['version']}/{path.lstrip('/')}"
    mode = _AUTH_MODE[0]
    response = await _send(url, params or {}, access, mode)
    if response.status_code != 200 and mode == "header" and _header_not_accepted(response):
        response = await _send(url, params or {}, access, "query")
        if response.status_code == 200:
            _AUTH_MODE[0] = "query"
    if response.status_code != 200:
        raise _noted_error(_refusal(response))
    try:
        body = response.json()
    except ValueError:
        raise _noted_error(InstagramUnavailable("Instagram answered with something unreadable.", kind="refused")) from None
    if not isinstance(body, dict):
        raise _noted_error(InstagramUnavailable("Instagram answered with something unreadable.", kind="refused"))
    _noted_ok()
    return body


def _data(body: dict[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data")
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def text(value: Any, limit: int = MAX_TEXT) -> str:
    """Instagram text as one line, cut to `limit`."""
    return " ".join(str(value or "")[: limit * 4].split())[:limit]


def _handle(value: Any) -> str:
    return text(value, MAX_USERNAME).lstrip("@")


# --- reads -----------------------------------------------------------------------------------

async def account() -> dict[str, str]:
    """The connected account: its ids and handle. Held for an hour."""
    if _ACCOUNT and time.time() - float(_ACCOUNT.get("_read_at") or 0) < ACCOUNT_TTL_S:
        return {k: v for k, v in _ACCOUNT.items() if not k.startswith("_")}
    body = await get("me", {"fields": "id,user_id,username,name,account_type"})
    out = {
        "id": str(body.get("id") or ""),
        "user_id": str(body.get("user_id") or ""),
        "username": _handle(body.get("username")),
        "name": text(body.get("name"), 80),
        "account_type": text(body.get("account_type"), 40),
    }
    _ACCOUNT.clear()
    _ACCOUNT.update(out, _read_at=time.time())
    if out["username"] and _STATE.get("username") != out["username"]:
        _note(username=out["username"])
    return out


def _ours(account_: dict[str, str]) -> tuple[set[str], str]:
    ids = {i for i in (account_.get("id"), account_.get("user_id")) if i}
    return ids, (account_.get("username") or "").lower()


def is_ours(sender: dict[str, Any] | None, account_: dict[str, str]) -> bool:
    """Whether a message's or comment's author is the connected account itself."""
    if not isinstance(sender, dict):
        return False
    ids, handle = _ours(account_)
    who = str(sender.get("id") or "")
    name = _handle(sender.get("username")).lower()
    return bool((who and who in ids) or (handle and name == handle))


def _message(item: dict[str, Any]) -> dict[str, Any]:
    sender = item.get("from") if isinstance(item.get("from"), dict) else {}
    attachments = item.get("attachments")
    count = len(attachments.get("data") or []) if isinstance(attachments, dict) else 0
    return {
        "message_id": str(item.get("id") or ""),
        "created_time": str(item.get("created_time") or ""),
        "from": {"id": str(sender.get("id") or ""), "username": _handle(sender.get("username"))},
        "text": text(item.get("message")),
        "attachments": count,
    }


def _participant(conversation: dict[str, Any], account_: dict[str, str]) -> str:
    people = conversation.get("participants")
    for person in _data(people) if isinstance(people, dict) else []:
        if not is_ours(person, account_):
            return _handle(person.get("username"))
    return ""


async def conversations(limit: int = 10) -> list[dict[str, Any]]:
    """Recent direct-message conversations, newest first: each with the other person's handle
    and its latest message."""
    account_ = await account()
    body = await get("me/conversations", {
        "platform": "instagram",
        "limit": str(max(1, min(MAX_PAGE, int(limit)))),
        "fields": "id,updated_time,participants,messages.limit(1){id,created_time,from,to,message}",
    })
    out = []
    for item in _data(body):
        ident = str(item.get("id") or "")
        if not ID.fullmatch(ident):
            continue
        messages = item.get("messages")
        latest = [_message(m) for m in _data(messages)] if isinstance(messages, dict) else []
        if latest and not latest[0]["text"] and not latest[0]["from"]["id"] and latest[0]["message_id"]:
            latest = [await _message_by_id(latest[0]["message_id"])]
        out.append({
            "conversation_id": ident,
            "updated_time": str(item.get("updated_time") or ""),
            "username": _participant(item, account_),
            "latest": latest[0] if latest else None,
        })
    return out


async def _message_by_id(message_id: str) -> dict[str, Any]:
    if not ID.fullmatch(message_id):
        return _message({})
    return _message(await get(message_id, {"fields": "id,created_time,from,to,message,attachments"}))


async def thread(conversation_id: str) -> dict[str, Any]:
    """One conversation: the other person and its most recent messages, oldest first."""
    if not ID.fullmatch(str(conversation_id or "")):
        raise InstagramUnavailable("That is not an Instagram conversation.", kind="not_found")
    account_ = await account()
    body = await get(conversation_id, {
        "fields": f"id,updated_time,participants,messages.limit({THREAD_MESSAGES})"
                  "{id,created_time,from,to,message,attachments}",
    })
    messages = body.get("messages")
    items = [_message(m) for m in _data(messages)] if isinstance(messages, dict) else []
    # Some API versions give only ids and times in a conversation: read each message then.
    if items and all(not m["text"] and not m["from"]["id"] for m in items):
        items = [await _message_by_id(m["message_id"]) for m in items[:THREAD_MESSAGES]]
    items.sort(key=lambda m: m["created_time"])
    return {
        "conversation_id": conversation_id,
        "username": _participant(body, account_),
        "messages": items[-THREAD_MESSAGES:],
        "account": account_,
    }


async def media(limit: int = 12) -> list[dict[str, Any]]:
    """The account's most recent posts, newest first."""
    body = await get("me/media", {
        "limit": str(max(1, min(MAX_PAGE, int(limit)))),
        "fields": "id,caption,media_type,permalink,timestamp,comments_count",
    })
    out = []
    for item in _data(body):
        ident = str(item.get("id") or "")
        if not ID.fullmatch(ident):
            continue
        out.append({
            "media_id": ident,
            "caption": text(item.get("caption"), MAX_CAPTION),
            "media_type": text(item.get("media_type"), 30),
            "permalink": str(item.get("permalink") or "")[:300],
            "timestamp": str(item.get("timestamp") or ""),
            "comments_count": int(item.get("comments_count") or 0),
        })
    return out


def _comment(item: dict[str, Any]) -> dict[str, Any]:
    sender = item.get("from") if isinstance(item.get("from"), dict) else {}
    return {
        "comment_id": str(item.get("id") or ""),
        "timestamp": str(item.get("timestamp") or ""),
        "username": _handle(item.get("username") or sender.get("username")),
        "from_id": str(sender.get("id") or ""),
        "text": text(item.get("text")),
        "like_count": int(item.get("like_count") or 0),
        "hidden": bool(item.get("hidden")),
    }


async def comments(media_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """The top-level comments on one post, each with its replies."""
    if not ID.fullmatch(str(media_id or "")):
        raise InstagramUnavailable("That is not an Instagram post.", kind="not_found")
    body = await get(f"{media_id}/comments", {
        "limit": str(max(1, min(MAX_PAGE, int(limit)))),
        "fields": "id,text,timestamp,username,from,like_count,hidden,replies{id,text,timestamp,username,from}",
    })
    out = []
    for item in _data(body):
        if not ID.fullmatch(str(item.get("id") or "")):
            continue
        entry = _comment(item)
        replies = item.get("replies")
        entry["replies"] = [_comment(r) for r in _data(replies)] if isinstance(replies, dict) else []
        out.append(entry)
    return out


# --- the token's life ------------------------------------------------------------------------

async def refresh() -> int:
    """Renew the long-lived token and store the new one. Returns the seconds it now lasts."""
    access = token()
    if not access:
        raise InstagramUnavailable("There is no Instagram token to renew.", kind="no_token")
    _note(refresh_attempt_at=time.time())
    try:
        async with http_client() as client:
            response = await asyncio.wait_for(client.get(
                f"{HOST}/refresh_access_token",
                params={"grant_type": "ig_refresh_token", "access_token": access},
                headers={"Accept": "application/json"},
            ), TIMEOUT_S)
    except (TimeoutError, httpx.TimeoutException):
        raise _noted_error(InstagramUnavailable("Instagram did not answer in time.", kind="timeout")) from None
    except httpx.HTTPError:
        raise _noted_error(InstagramUnavailable("Instagram could not be reached.", kind="unreachable")) from None
    if response.status_code != 200:
        raise _noted_error(_refusal(response))
    try:
        body = response.json()
        renewed = str(body.get("access_token") or "").strip()
        lasts = int(body.get("expires_in") or 0)
    except (ValueError, AttributeError, TypeError):
        renewed, lasts = "", 0
    if not renewed:
        raise _noted_error(InstagramUnavailable("Instagram's renewal came back without a token.", kind="refused"))
    try:
        keychain.set_secret(TOKEN_KEY, renewed)
    except keychain.SecretShadowed:
        raise _noted_error(InstagramUnavailable(
            "The Instagram token is provisioned read-only, so its renewal could not be stored. "
            "Re-provision it with scripts/provision_secrets.py instagram_access_token.",
            kind="refresh_blocked")) from None
    now = time.time()
    lasts = lasts if lasts > 0 else TOKEN_LIFETIME_S
    _note(refreshed_at=now, expires_at=now + lasts, last_error_kind="")
    return lasts


async def exchange(short_lived: str, *, store: Callable[[str, str], None] | None = None) -> int:
    """Swap a short-lived token (one hour) for a long-lived one (60 days) and store it. The only
    call that reads the app secret. Run by hand (scripts/instagram.py exchange), and by "Sign in
    with Instagram" once the owner has approved it with a passkey (app/connections/instagram.py),
    which passes `store` so the token goes to the app tier (app/secrets/vault.py)."""
    short = str(short_lived or "").strip()
    if not short:
        raise InstagramUnavailable("Paste the short-lived token to exchange.", kind="no_token")
    try:
        secret = (keychain.get_optional(APP_SECRET_KEY) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has no secret to give
        secret = ""
    if not secret:
        raise InstagramUnavailable(
            "Exchanging a token needs the app secret: store it with "
            "scripts/provision_secrets.py instagram_app_secret.", kind="no_token")
    try:
        async with http_client() as client:
            response = await asyncio.wait_for(client.get(
                f"{HOST}/access_token",
                params={"grant_type": "ig_exchange_token", "client_secret": secret, "access_token": short},
                headers={"Accept": "application/json"},
            ), TIMEOUT_S)
    except (TimeoutError, httpx.TimeoutException):
        raise InstagramUnavailable("Instagram did not answer in time.", kind="timeout") from None
    except httpx.HTTPError:
        raise InstagramUnavailable("Instagram could not be reached.", kind="unreachable") from None
    if response.status_code != 200:
        raise _refusal(response)
    try:
        body = response.json()
        renewed = str(body.get("access_token") or "").strip()
        lasts = int(body.get("expires_in") or 0)
    except (ValueError, AttributeError, TypeError):
        renewed, lasts = "", 0
    if not renewed:
        raise InstagramUnavailable("Instagram's exchange came back without a token.", kind="refused")
    try:
        (store or keychain.set_secret)(TOKEN_KEY, renewed)
    except keychain.SecretShadowed:
        raise InstagramUnavailable(
            "The Instagram token is provisioned read-only, so the new one could not be stored. "
            "Re-provision it with scripts/provision_secrets.py instagram_access_token.",
            kind="refresh_blocked") from None
    now = time.time()
    lasts = lasts if lasts > 0 else TOKEN_LIFETIME_S
    _ACCOUNT.clear()            # a sign-in may be another account
    _AUTH_MODE[0] = "header"
    _note(refreshed_at=now, expires_at=now + lasts, first_seen_at=now, last_error_kind="")
    return lasts


def adopt_new_token() -> None:
    """A token was just stored from the app (pasted on the Connections screen): what this process
    learned about the old one no longer holds. Its age is unknown, so renewal starts a day from
    now, as for a token stored by hand; the account it reads is asked again."""
    _ACCOUNT.clear()
    _AUTH_MODE[0] = "header"
    for name in ("refreshed_at", "expires_at", "refresh_attempt_at", "last_error_kind", "last_error_at"):
        _STATE.pop(name, None)
    _note(first_seen_at=time.time())


async def maybe_refresh(now: float | None = None) -> None:
    """Renew the token when it is due, and never let a renewal stop a read.

    Due means: a day after the token was first seen here (Meta renews only tokens at least a
    day old, and the age of a token stored by hand is unknown), then a week after each renewal.
    A failed attempt waits twelve hours before the next; /health says why meanwhile."""
    if not token():
        return
    now = time.time() if now is None else now
    if now - float(_STATE.get("refresh_attempt_at") or 0) < REFRESH_RETRY_S:
        return
    refreshed = _STATE.get("refreshed_at")
    if refreshed is None:
        first_seen = _STATE.get("first_seen_at")
        if first_seen is None:
            _note(first_seen_at=now)
            return
        due = now - float(first_seen) >= MIN_TOKEN_AGE_S
    else:
        due = now - float(refreshed) >= REFRESH_AFTER_S
    if not due:
        return
    try:
        await refresh()
    except InstagramUnavailable as exc:
        log.warning("instagram token renewal failed: %s", exc.kind)


def health(now: float | None = None) -> tuple[bool, str]:
    """Configuration and what the last calls learned. No network: /health is polled."""
    if not token():
        return True, "not connected (no instagram_access_token stored)"
    now = time.time() if now is None else now
    who = f"@{_STATE['username']}" if _STATE.get("username") else "the stored token"
    expires = _STATE.get("expires_at")
    if expires is not None:
        days = int((float(expires) - now) // 86400)
        if days < 0:
            return False, f"{who}: the token has expired; store a new one"
        if days < 7:
            kind = _STATE.get("last_error_kind")
            why = f" (the last renewal failed: {kind})" if kind else ""
            return False, f"{who}: the token expires in {days} day(s); run scripts/instagram.py refresh{why}"
    kind = _STATE.get("last_error_kind")
    if kind in ("token", "permission", "refresh_blocked"):
        return False, f"{who}: the last call was refused ({kind})"
    left = f", token good for {int((float(expires) - now) // 86400)} more days" if expires is not None else ""
    return True, f"connected as {who}{left}"
