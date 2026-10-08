"""The team's public door: team.crooksldn.com, through the host's Caddy, to the team's own page and the
routes it calls, and nothing else (ruling 35 of DEC-071, built as DEC-075; docs/STAFF_LINKS.md).

app/main.py asks came_through() before any other rule. A request is this door's when Caddy marked it
(X-Clive-Door) or it is addressed to the team's host (CROOKS_TEAM_HOST). Either is enough, and neither
can widen anything, because from then on only this module judges it:

  1. Identity claims are taken off it (Tailscale's headers, the server's local command key) and it is
     marked TEAM_DOOR (app/routes/actions.py proxy_state), which the owner rule, the write boundary
     and session binding never take for the owner or for the server itself.
  2. It may reach exactly ROUTES. Anything else is a plain 404, signed in or not.
  3. A POST must come from a page on this door's own host (its Origin), never from another site.
  4. Without a signed-in phone (app/people/links.py check) only the page shells, their files and the
     join answer, under no authority. With one, the request carries the team's own authority for that
     person (app/tools/authority.py for_staff, unchanged), revoked once the answer has been sent, as
     the main door does for the team on Tailscale.

Nothing a request carries is logged here: not the cookie, not a body, not an address.
"""

from __future__ import annotations

import logging
import re

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

log = logging.getLogger("crooks.team")

HEADER = "x-clive-door"
_SCOPE_KEY = "crooks.team"

# The page shells and the join, answered with no phone signed in. The files are exactly those
# web/today.html and web/join.html load (tests/test_staff_links.py reads the pages to hold it so).
OPEN = frozenset({("GET", "/"), ("GET", "/join"), ("POST", "/join"), ("GET", "/today")})
STATIC = frozenset(f"/static/{name}" for name in (
    "today.css", "orb.js", "objective-touch.js", "today-say.js", "today-voice.js", "today.js", "today-owner.js",
    "icon-192.png", "join.css", "join.js",
))
# What the team's page calls, and only with a phone signed in: its work list, its own CLIVE, and the
# cards that CLIVE stages for them. The owner's steps on /today (hand out, people, access) are not here.
SIGNED_IN = frozenset({
    ("GET", "/today/state"), ("POST", "/today/claim"), ("POST", "/today/release"), ("POST", "/today/packed"),
    ("POST", "/today/counts"), ("POST", "/today/done"), ("POST", "/today/undo"), ("POST", "/today/flag"),
    ("POST", "/turn"),
})
# The one answer a phone's sign-in is renewed with: the page's own read, quick and every 30 seconds.
RENEWS = "/today/state"
# A card: read it, arm it, confirm it (web/today.js). The id is the engine's (app/actions/models.py).
CARD_READ = re.compile(r"^/actions/prop_[0-9a-f]{12}$")
CARD_STEP = re.compile(r"^/actions/prop_[0-9a-f]{12}/(?:arm|commit)$")

STRIPPED = (b"tailscale-", b"x-crooks-local-key")
SIGNED_OUT = "This phone isn't signed in to CLIVE. Open the staff link George sent you."


def configured_host(value: str) -> str:
    """CROOKS_TEAM_HOST as it may be written ("team.crooksldn.com", "https://team.crooksldn.com/"),
    as a host and port only."""
    return str(value or "").strip().lower().split("://", 1)[-1].split("/", 1)[0]


def _hostname(value: str) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _team_host(request: Request) -> str:
    runtime = getattr(request.app.state, "runtime", None)
    return _hostname(configured_host(getattr(getattr(runtime, "settings", None), "team_host", "") or ""))


def came_through(request: Request) -> bool:
    """Whether this request is the team door's: marked by Caddy, or addressed to the team's host."""
    scope = request.scope
    if scope.get(_SCOPE_KEY) is not None:
        return True
    headers = scope.get("headers") or []
    if any(name.lower() == HEADER.encode() for name, _ in headers):
        return True
    team = _team_host(request)
    if not team:
        return False
    for name, value in headers:
        if name.lower() in (b"host", b"x-forwarded-host"):
            if _hostname(value.decode("latin-1")) == team:
                return True
    return False


def member(request: Request) -> str:
    """The identity of the signed-in phone's person on this request (links.identity), or ""."""
    held = request.scope.get(_SCOPE_KEY) or {}
    return str(held.get("identity") or "") if isinstance(held, dict) else ""


def address(request: Request) -> str:
    """Where the request came from, as Caddy says (the last X-Forwarded-For entry, which it writes
    itself): used to count failed joins in memory, and nowhere else."""
    held = request.scope.get(_SCOPE_KEY) or {}
    return str(held.get("address") or "unknown") if isinstance(held, dict) else "unknown"


def allowed(method: str, path: str) -> str:
    """"open", "signed_in" or "" for this method and routed path."""
    method = str(method or "").upper()
    if (method, path) in OPEN or (method == "GET" and path in STATIC):
        return "open"
    if (method, path) in SIGNED_IN:
        return "signed_in"
    if (method == "GET" and CARD_READ.fullmatch(path)) or (method == "POST" and CARD_STEP.fullmatch(path)):
        return "signed_in"
    return ""


def _from_this_host(request: Request) -> bool:
    """A POST from a page on this door's own host: an Origin naming it, and no Sec-Fetch-Site saying
    otherwise. No Origin at all is refused here: every browser sends one on a POST."""
    site = request.headers.get("sec-fetch-site", "").strip().lower()
    if site and site != "same-origin":
        return False
    origin = request.headers.get("origin", "").strip().lower()
    if not origin or origin == "null" or "://" not in origin:
        return False
    host = origin.split("://", 1)[1].split("/", 1)[0]
    return host in {request.headers.get("host", "").strip().lower(),
                    request.headers.get("x-forwarded-host", "").strip().lower()} - {""}


def _strip(request: Request) -> None:
    scope = request.scope
    scope["headers"] = [(name, value) for name, value in scope.get("headers") or []
                        if not name.lower().startswith(STRIPPED)]
    if hasattr(request, "_headers"):
        del request._headers


def _forwarded_for(request: Request) -> str:
    entries = [e.strip() for e in request.headers.get("x-forwarded-for", "").split(",") if e.strip()]
    return entries[-1][:64] if entries else "unknown"


def _hardened(response: Response, *, api: bool) -> Response:
    for name, value in (("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
                        ("X-Frame-Options", "DENY")):
        if name not in response.headers:
            response.headers[name] = value
    if api:
        response.headers["Cache-Control"] = "no-store"
    elif "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-cache"
    return response


def _not_found() -> Response:
    return _hardened(JSONResponse(status_code=404, content={"detail": "Not Found"}), api=True)


async def through(request: Request, call_next) -> Response:
    """Judge a request that came through the team's door, start to finish."""
    from app.people import links
    from app.routes.actions import _PROXY_KEY, TEAM_DOOR
    from app.tools import authority as tool_authority

    _strip(request)
    request.scope[_PROXY_KEY] = (TEAM_DOOR, "")
    request.scope[_SCOPE_KEY] = {"identity": "", "person_id": "", "address": _forwarded_for(request)}
    path = str(request.scope.get("path") or "")
    kind = allowed(request.method, path)
    if not kind:
        return _not_found()
    if request.method == "POST" and not _from_this_host(request):
        log.warning("team door: refused a POST that did not come from the team's own page (path=%s)", path)
        return _hardened(JSONResponse(status_code=403, content={"ok": False, "code": "cross_site",
                                                                "detail": "Open CLIVE's own page to do that."}), api=True)
    if path == "/":
        return _hardened(RedirectResponse("/today", status_code=303), api=False)
    nobody = tool_authority.TOOL_AUTHORITY.set(None)
    if kind == "open":
        try:
            response = await call_next(request)
        finally:
            tool_authority.TOOL_AUTHORITY.reset(nobody)
        return _hardened(response, api=request.method == "POST")
    tool_authority.TOOL_AUTHORITY.reset(nobody)
    presented = request.cookies.get(links.COOKIE, "")
    # A new sign-in goes out only with Today's own quick read: a turn's answer can take minutes and
    # could land after a newer cookie (app/people/links.py check).
    seen = links.check(presented, renew=(request.method == "GET" and path == RENEWS))
    if seen.refused:
        refused = JSONResponse(status_code=401, content={"ok": False, "code": "signed_out", "detail": SIGNED_OUT})
        if presented:
            refused.headers.append("set-cookie", links.clear_cookie_header())
        return _hardened(refused, api=True)
    identity = links.identity(seen.person_id)
    request.scope[_SCOPE_KEY].update(identity=identity, person_id=seen.person_id)
    granted = tool_authority.for_staff(seen.person_id, identity)
    stamped = tool_authority.TOOL_AUTHORITY.set(granted)
    try:
        response = await call_next(request)
    except BaseException:
        granted.revoke()
        raise
    finally:
        tool_authority.TOOL_AUTHORITY.reset(stamped)
    response.body_iterator = _revoking(response.body_iterator, granted)
    if seen.set_cookie:
        response.headers.append("set-cookie", seen.set_cookie)
    return _hardened(response, api=True)


async def _revoking(body, granted):
    try:
        async for chunk in body:
            yield chunk
    finally:
        granted.revoke()
