"""The Connections screen and its routes: the owner adds, tests and removes CLIVE's keys and sign-ins
from the app (app/connections; the owner's decision of 1 October 2026).

Behind the door (app/main.py): every route here is the owner's (principal_verdict), and a POST from
another site is refused before it arrives. On top of that every change needs a passkey approval
made for exactly that change, at that moment (app/connections/passkeys.py); a POST without this
CLIVE's own address as its Origin is refused, because a passkey is bound to it.

Nothing here returns a stored secret, and nothing puts one in a log line. Bodies are read by hand,
not by a model class, so a refused value is never echoed back in a validation error.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.connections import catalog, instagram, ledger, passkeys, service
from app.secrets import vault

log = logging.getLogger("crooks.connections")
router = APIRouter()

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
MAX_BODY = 64 * 1024
CREDENTIAL_ID = re.compile(r"^[A-Za-z0-9_-]{16,1400}$")
NAME = re.compile(r"^[a-z]{2,20}$")


class _Refused(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _refusal(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "code": code, "detail": detail},
                        headers={"Cache-Control": "no-store"})


def _answer(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(content={"ok": True, **payload}, headers={"Cache-Control": "no-store"})


def _who(request: Request) -> str:
    from app.routes.actions import principal_check

    who, why = principal_check(request)
    if not who:
        raise _Refused(403, "not_the_owner", why or "This is the owner's.")
    return who


def _settings(request: Request) -> Any:
    runtime = getattr(request.app.state, "runtime", None)
    return getattr(runtime, "settings", None)


def _hosts(request: Request) -> set[str]:
    hosts = set()
    for header in ("host", "x-forwarded-host"):
        value = request.headers.get(header, "").strip().lower()
        if value:
            hosts.add(value.split(",")[0].strip().rsplit(":", 1)[0] if not value.startswith("[") else value)
    return hosts


def _origin(request: Request) -> tuple[str, str]:
    """This CLIVE's own address, from the request's Origin, and the passkey site it implies.

    The Origin must be the configured address (CROOKS_PUBLIC_ORIGIN) when one is set, and otherwise
    an https *.ts.net address that is the very host the request came to: what `tailscale serve`
    gives. Anything else is refused, since a passkey made for it would not be this CLIVE's."""
    origin = request.headers.get("origin", "").strip().rstrip("/")
    configured = str(getattr(_settings(request), "public_origin", "") or "").strip().rstrip("/")
    parts = urlsplit(origin)
    host = (parts.hostname or "").lower()
    if configured:
        if origin.lower() != configured.lower() or not host:
            raise _Refused(403, "wrong_origin", "Open the Connections screen at CLIVE's own address.")
        return origin, host
    if (parts.scheme != "https" or not host.endswith(".ts.net") or parts.port not in (None, 443)
            or parts.path or host not in _hosts(request)):
        raise _Refused(403, "wrong_origin", "Open the Connections screen in CLIVE itself, at its https "
                                            "Tailscale address: a passkey only works there.")
    return f"https://{host}", host


def _shown_origin(request: Request) -> str:
    """The address to show for the sign-in's redirect: what the owner registers with Meta."""
    configured = str(getattr(_settings(request), "public_origin", "") or "").strip().rstrip("/")
    if configured:
        return configured
    hosts = sorted(h for h in _hosts(request) if h.endswith(".ts.net"))
    return f"https://{hosts[0]}" if hosts else "https://<this CLIVE's Tailscale address>"


def _device(request: Request) -> str:
    agent = request.headers.get("user-agent", "")
    for marker, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Macintosh", "Mac"), ("Windows", "Windows PC")):
        if marker in agent:
            return name
    if "Android" in agent:
        return "Android phone" if "Mobile" in agent else "Android tablet"
    return "Linux computer" if "Linux" in agent else "a device"


async def _body(request: Request) -> dict[str, Any]:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:
        raise _Refused(413, "too_large", "That is more than any key.")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise _Refused(413, "too_large", "That is more than any key.")
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise _Refused(400, "bad_request", "The screen sent something unreadable. Reload it.") from None
    if not isinstance(body, dict):
        raise _Refused(400, "bad_request", "The screen sent something unreadable. Reload it.")
    return body


def _approve(body: dict[str, Any], action: str, *, who: str, origin: str, device: str) -> dict[str, Any]:
    try:
        return passkeys.verify_approval(body.get("approval"), action, login=who, origin=origin)
    except passkeys.PasskeyRefused as exc:
        ledger.record("approval_refused", connection=action, who=who, device=device, ok=False, detail=str(exc))
        log.warning("connections: an approval for %s was refused (%s)", action, exc.code)
        raise _Refused(403, exc.code, str(exc)) from None


def _guarded(handler):
    """Every route's refusals as one JSON shape; never a traceback, never a value. functools.wraps
    keeps the handler's own signature, which is what FastAPI reads its path parameters from."""
    @functools.wraps(handler)
    async def run(*args: Any, **kwargs: Any):
        try:
            return await handler(*args, **kwargs)
        except _Refused as exc:
            return _refusal(exc.status, exc.code, exc.detail)
        except service.ConnectionsError as exc:
            return _refusal(400, exc.code, exc.detail)
        except passkeys.PasskeyRefused as exc:
            return _refusal(403, exc.code, str(exc))
        except instagram.SignInFailed as exc:
            return _refusal(400, exc.code, exc.detail)
    return run


# ------------------------------------------------------------------ the page and its state

# The page runs only its own script and style, cannot be framed by another page, and sends no
# referrer when it opens Instagram's sign-in: a screen that takes keys gets the strictest policy.
PAGE_HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
                                "frame-ancestors 'none'"),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/connections", include_in_schema=True)
async def connections_page(request: Request) -> Response:
    """The screen itself. It holds no data; it asks /connections/state."""
    source = (WEB_DIR / "connections.html").read_text(encoding="utf-8")
    build = getattr(getattr(request.app.state, "runtime", None), "build", "unknown")
    return Response(source.replace("__BUILD__", str(build)), media_type="text/html; charset=utf-8",
                    headers=PAGE_HEADERS)


@router.get("/connections/state")
async def connections_state(request: Request) -> JSONResponse:
    """Every card, the passkeys (which device, when), the latest changes, and whether this server
    can keep keys for the app. Never a secret. Read off the event loop: deciding whether this server
    can keep keys runs systemd-creds once."""
    runtime = getattr(request.app.state, "runtime", None)
    return _answer(await asyncio.to_thread(service.state, runtime, origin=_shown_origin(request)))


# ------------------------------------------------------------------ passkeys

def _known_action(action: str) -> bool:
    kind, _, rest = action.partition(":")
    if kind in ("save", "disconnect"):
        connection = catalog.get(rest)
        return connection is not None and bool(connection.fields)
    if kind == "signin":
        return rest == "instagram"
    if kind == "passkey":
        verb, _, identity = rest.partition(":")
        return (verb == "add" and not identity) or (verb == "remove" and bool(CREDENTIAL_ID.fullmatch(identity)))
    return False


@router.post("/connections/approve")
@_guarded
async def connections_approve(request: Request) -> JSONResponse:
    """A passkey prompt for exactly one change: the options navigator.credentials.get() takes."""
    who = _who(request)
    origin, rp_id = _origin(request)
    action = str((await _body(request)).get("action") or "")
    if len(action) > 1500 or not _known_action(action):
        raise _Refused(400, "unknown_action", "That is not a change this screen makes.")
    return _answer({"publicKey": passkeys.begin_approval(action, login=who, origin=origin, rp_id=rp_id)})


@router.post("/connections/passkeys/begin")
@_guarded
async def connections_passkey_begin(request: Request) -> JSONResponse:
    """A prompt to make a passkey: open for the first one, from the owner's own device; every later
    one needs a passkey he already has to approve it."""
    who = _who(request)
    origin, rp_id = _origin(request)
    body = await _body(request)
    approved = False
    if passkeys.count():
        _approve(body, "passkey:add", who=who, origin=origin, device=_device(request))
        approved = True
    return _answer({"publicKey": passkeys.begin_registration(login=who, origin=origin, rp_id=rp_id,
                                                             approved=approved)})


@router.post("/connections/passkeys")
@_guarded
async def connections_passkey_finish(request: Request) -> JSONResponse:
    """The new passkey, verified and kept (its public key only)."""
    who = _who(request)
    origin, _ = _origin(request)
    device = _device(request)
    body = await _body(request)
    shown = passkeys.finish_registration(body.get("credential"), login=who, origin=origin, label=device)
    ledger.record("passkey_added", who=who, device=device, detail=f"a passkey on {shown['label']}")
    log.info("connections: a passkey was added (%s)", shown["label"])
    return _answer({"passkey": shown})


@router.post("/connections/passkeys/{credential_id}/remove")
@_guarded
async def connections_passkey_remove(request: Request, credential_id: str) -> JSONResponse:
    who = _who(request)
    origin, _ = _origin(request)
    device = _device(request)
    if not CREDENTIAL_ID.fullmatch(credential_id):
        raise _Refused(404, "unknown_passkey", "There is no such passkey.")
    _approve(await _body(request), f"passkey:remove:{credential_id}", who=who, origin=origin, device=device)
    if not passkeys.remove(credential_id):
        raise _Refused(404, "unknown_passkey", "There is no such passkey.")
    ledger.record("passkey_removed", who=who, device=device)
    return _answer({})


# ------------------------------------------------------------------ Sign in with Instagram

@router.post("/connections/instagram/sign-in")
@_guarded
async def connections_instagram_sign_in(request: Request) -> JSONResponse:
    """Instagram's own sign-in page, for a change the owner's passkey has just approved."""
    who = _who(request)
    origin, _ = _origin(request)
    device = _device(request)
    ok, why = await asyncio.to_thread(vault.check)
    if not ok:
        raise _Refused(503, "store_unavailable", f"This server cannot keep keys for the app yet: {why}.")
    _approve(await _body(request), "signin:instagram", who=who, origin=origin, device=device)
    url = instagram.start(login=who, origin=origin)
    ledger.record("sign_in_started", connection="instagram", who=who, device=device)
    return _answer({"url": url})


@router.get("/connections/instagram/callback")
async def connections_instagram_callback(request: Request) -> Response:
    """Where Instagram sends the browser back. The code and state are never logged (the access log
    drops this route's query, app/logging/quiet.py) and nothing Instagram wrote is shown."""
    try:
        who = _who(request)
    except _Refused as exc:
        return _refusal(exc.status, exc.code, exc.detail)
    device = _device(request)
    params = request.query_params
    state = params.get("state", "")
    if params.get("error"):
        instagram.cancelled(state, who)
        ledger.record("sign_in_cancelled", connection="instagram", who=who, device=device, ok=False)
        return RedirectResponse("/connections?error=cancelled#instagram", status_code=303)
    runtime = getattr(request.app.state, "runtime", None)
    try:
        outcome = await instagram.finish(code=params.get("code", ""), state=state, login=who, store=vault.store)
    except instagram.SignInFailed as exc:
        ledger.record("sign_in_failed", connection="instagram", who=who, device=device, ok=False, detail=exc.detail)
        return RedirectResponse(f"/connections?error={quote(exc.code)}#instagram", status_code=303)
    except vault.VaultUnavailable:
        ledger.record("sign_in_failed", connection="instagram", who=who, device=device, ok=False,
                      detail="the token could not be kept on this server")
        return RedirectResponse("/connections?error=store_unavailable#instagram", status_code=303)
    await service.signed_in(runtime, outcome, who=who, device=device)
    done = "signed_in" if outcome.ok else "signed_in_untested"
    return RedirectResponse(f"/connections?done={done}#instagram", status_code=303)


# ------------------------------------------------------------------ one connection

def _connection(name: str) -> str:
    if not NAME.fullmatch(name or "") or catalog.get(name) is None:
        raise _Refused(404, "unknown", "There is no such connection.")
    return name


@router.post("/connections/{name}/test")
@_guarded
async def connections_test(request: Request, name: str) -> JSONResponse:
    """Ask the service again with what is stored now. Changes nothing, so asks no passkey."""
    _who(request)
    outcome = await service.test(getattr(request.app.state, "runtime", None), _connection(name))
    return _answer({"result": outcome.as_dict()})


@router.post("/connections/{name}/disconnect")
@_guarded
async def connections_disconnect(request: Request, name: str) -> JSONResponse:
    who = _who(request)
    origin, _ = _origin(request)
    device = _device(request)
    name = _connection(name)
    _approve(await _body(request), f"disconnect:{name}", who=who, origin=origin, device=device)
    await service.disconnect(getattr(request.app.state, "runtime", None), name, who=who, device=device)
    return _answer({})


@router.post("/connections/{name}")
@_guarded
async def connections_save(request: Request, name: str) -> JSONResponse:
    """Test the new values with the service, and store them only if that worked."""
    who = _who(request)
    origin, _ = _origin(request)
    device = _device(request)
    name = _connection(name)
    body = await _body(request)
    _approve(body, f"save:{name}", who=who, origin=origin, device=device)
    outcome = await service.save(getattr(request.app.state, "runtime", None), name, body.get("values"),
                                 who=who, device=device)
    if not outcome.ok:
        return JSONResponse(status_code=422, content={"ok": False, "code": "test_failed", "detail": outcome.detail},
                            headers={"Cache-Control": "no-store"})
    return _answer({"result": outcome.as_dict()})
