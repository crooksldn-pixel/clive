"""Sign in with Instagram: the owner taps, Instagram's own page asks him to approve, and CLIVE keeps
a long-lived token it renews itself (the Instagram API with Instagram Login).

1. start(): needs the Meta app's ID and secret, stored on the Connections screen first, and the
   owner's passkey (the route asks for it). Makes a `state` good once, for ten minutes, bound to
   this owner and this CLIVE's address, and returns Instagram's authorize address.
2. Instagram sends the browser back to <this CLIVE>/connections/instagram/callback with a code.
   The browser carries it: Instagram never has to reach the server, which is why this works on a
   private, Tailscale-only CLIVE (only webhooks would need a public address).
3. finish(): the state must be one issued here, unexpired, unused, to the same owner. The code is
   swapped for a short-lived token (a POST with the app secret in its body, never in an address),
   the short-lived token for a long-lived one (app/clients/instagram.py exchange), which is stored
   in the app tier and tested before the owner is told it worked.

The address to register in the Meta app (Instagram → API setup with Instagram login → Business
login settings → OAuth redirect URIs) is <this CLIVE>/connections/instagram/callback, exactly; the
screen shows it with a copy button. Nothing Instagram writes is quoted back.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connections import testers
from app.secrets import keychain

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
SCOPES = ("instagram_business_basic", "instagram_business_manage_messages", "instagram_business_manage_comments")
CALLBACK_PATH = "/connections/instagram/callback"
STATE_S = 600.0
MAX_PENDING = 16
CODE = re.compile(r"^[A-Za-z0-9_.\-]{8,2048}$")


class SignInFailed(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class _Pending:
    login: str
    origin: str
    expires: float


_LOCK = threading.Lock()
_PENDING: dict[str, _Pending] = {}


def reset() -> None:
    with _LOCK:
        _PENDING.clear()


def redirect_uri(origin: str) -> str:
    return origin.rstrip("/") + CALLBACK_PATH


def _app() -> tuple[str, str]:
    app_id = (keychain.get_optional("instagram_app_id") or "").strip()
    secret = (keychain.get_optional("instagram_app_secret") or "").strip()
    if not app_id or not secret:
        raise SignInFailed("needs_app", "Store the Instagram app ID and app secret on this card first.")
    return app_id, secret


def start(*, login: str, origin: str) -> str:
    """Instagram's authorize address for this owner, with a fresh single-use state."""
    app_id, _ = _app()
    state = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _LOCK:
        for stale in [k for k, p in _PENDING.items() if p.expires <= now]:
            _PENDING.pop(stale, None)
        while len(_PENDING) >= MAX_PENDING:
            _PENDING.pop(min(_PENDING, key=lambda k: _PENDING[k].expires), None)
        _PENDING[state] = _Pending(login, origin, now + STATE_S)
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": app_id, "redirect_uri": redirect_uri(origin), "response_type": "code",
        "scope": ",".join(SCOPES), "state": state, "enable_fb_login": "0", "force_reauth": "true",
    })


def _claim(state: str, login: str) -> _Pending:
    with _LOCK:
        pending = _PENDING.pop(str(state or ""), None)
    if pending is None or pending.expires <= time.monotonic():
        raise SignInFailed("stale", "That sign-in was not started here, or took longer than ten minutes. "
                                    "Start it again from Connections.")
    if pending.login != login:
        raise SignInFailed("not_yours", "That sign-in was started by someone else.")
    return pending


def cancelled(state: str, login: str) -> None:
    """Instagram came back with an error (the owner pressed Cancel): spend the state."""
    try:
        _claim(state, login)
    except SignInFailed:
        pass


def _granted(body: dict[str, Any]) -> tuple[str, set[str]]:
    item = body
    data = body.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        item = data[0]
    short = str(item.get("access_token") or "").strip()
    permissions = item.get("permissions") or ""
    if isinstance(permissions, str):
        granted = {p.strip() for p in permissions.split(",") if p.strip()}
    elif isinstance(permissions, list):
        granted = {str(p).strip() for p in permissions}
    else:
        granted = set()
    return short, granted


async def finish(*, code: str, state: str, login: str,
                 store: Callable[[str, str], None]) -> testers.Outcome:
    """Turn Instagram's code into a stored, tested long-lived token. Raises SignInFailed."""
    from app.clients import instagram as client

    pending = _claim(state, login)
    code = str(code or "").strip().removesuffix("#_")
    if not CODE.fullmatch(code):
        raise SignInFailed("bad_code", "Instagram's answer did not carry a sign-in code. Start again.")
    app_id, secret = _app()
    try:
        async with testers.http_client() as http:
            response = await http.post(TOKEN_URL, data={
                "client_id": app_id, "client_secret": secret, "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(pending.origin), "code": code,
            })
    except httpx.HTTPError:
        raise SignInFailed("unreachable", "Instagram could not be reached from the server. Try again.") from None
    if response.status_code != 200:
        raise SignInFailed("refused", "Instagram did not accept the sign-in. Check the redirect address on "
                                      "this card is in the Meta app exactly, then start again.")
    try:
        short, granted = _granted(response.json())
    except (ValueError, AttributeError):
        short, granted = "", set()
    if not short:
        raise SignInFailed("refused", "Instagram's answer carried no token. Start again.")

    kept: dict[str, str] = {}

    def keep(key: str, value: str) -> None:
        store(key, value)
        kept[key] = value

    try:
        await client.exchange(short, store=keep)
    except client.InstagramUnavailable as exc:
        raise SignInFailed("exchange", {
            "token": "Instagram would not turn the sign-in into a lasting token. Check the app secret.",
            "timeout": "Instagram did not answer in time. Start again.",
            "unreachable": "Instagram could not be reached from the server. Try again.",
        }.get(exc.kind, "Instagram would not turn the sign-in into a lasting token.")) from None
    outcome = await testers.run("instagram", {"instagram_access_token": kept.get(client.TOKEN_KEY, "")},
                                _Settings())
    missing = [p for p in SCOPES[1:] if granted and p not in granted]
    if outcome.ok and missing:
        what = " and ".join("messages" if "messages" in p else "comments" for p in missing)
        return testers.Outcome(True, f"{outcome.detail} Instagram did not allow {what}: sign in again and "
                                     "leave every permission ticked.", outcome.who)
    return outcome


class _Settings:
    """The one setting the token test reads, from the live configuration."""

    @property
    def instagram_api_version(self) -> str:
        from app.clients import instagram as client

        return str(client._CONFIG.get("version") or client.DEFAULT_VERSION)
