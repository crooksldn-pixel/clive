"""Staff links: joining CLIVE by a link and a code, and the owner's side of making them (ruling 35 of
DEC-071, built as DEC-075; docs/STAFF_LINKS.md).

  GET  /join                                  the join page: a box for the code, nothing else
  POST /join                                  the link's token and the code: this phone is signed in
  POST /staff-links/add                       George adds someone to the team, no Tailscale login needed
  POST /staff-links/{person}/make             George makes their link, with his passkey: shown once
  POST /staff-links/{person}/cancel           the link waiting for them stops working
  POST /staff-links/phones/{phone}/sign-out   that phone is signed out

Joining is answered only through the team's door (app/people/team_door.py): the cookie it hands
out means something there and nowhere else. The owner's steps are behind the main door like every
route of his, and refuse anyone else here too. No token, code or cookie is ever logged or recorded:
the link and code go to his screen once, in the answer to his passkey, and are kept only as hashes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.people import links
from app.people.store import PeopleError, people
from app.routes.today import _answer, _body, _guarded, _login, _name_of, _owner_only, _Refused
from app.work.store import work

log = logging.getLogger("crooks.team")
router = APIRouter()

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
MAX_JOIN_BODY = 2048


def _through_team_door(request: Request) -> bool:
    from app.routes.actions import TEAM_DOOR, proxy_state

    return proxy_state(request)[0] == TEAM_DOOR


# ------------------------------------------------------------------ joining, on the team's door

@router.get("/join")
async def join_page(request: Request) -> Response:
    from app.routes.connections import PAGE_HEADERS

    source = (WEB_DIR / "join.html").read_text(encoding="utf-8")
    build = getattr(getattr(request.app.state, "runtime", None), "build", "unknown")
    return Response(source.replace("__BUILD__", str(build)), media_type="text/html; charset=utf-8", headers=PAGE_HEADERS)


@router.post("/join")
async def join(request: Request) -> JSONResponse:
    """The token from the link's #fragment and the code George said. Every refusal of a link that is
    not open is the same; a wrong code says how many tries are left, which only a real link reaches."""
    from app.people import team_door
    from app.routes.connections import _device

    if not _through_team_door(request):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    # The one POST anyone on the internet can make: read no more than a link and a code need, never
    # the whole of whatever was sent.
    declared = request.headers.get("content-length", "")
    if declared and (not declared.isdigit() or int(declared) > MAX_JOIN_BODY):
        return _refused(413, "too_large", "That is more than a link and a code.")
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_JOIN_BODY:
            return _refused(413, "too_large", "That is more than a link and a code.")
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        body = None
    if not isinstance(body, dict):
        return _refused(400, "bad_request", "The page sent something unreadable. Open the link again.")
    try:
        joined = links.redeem(str(body.get("token") or ""), str(body.get("code") or ""),
                              address=team_door.address(request), kind=_device(request))
    except links.JoinRefused as refused:
        log.warning("team door: a join was refused (%s)", refused.code)
        status = 429 if refused.code == "too_many" else 403
        return _refused(status, refused.code, refused.detail, tries_left=refused.tries_left)
    except (links.LinkError, PeopleError):
        log.error("team door: a join could not be recorded")
        return _refused(503, "not_now", "CLIVE couldn't sign this phone in just now. Try again in a minute.")
    log.info("team door: a phone joined")
    work.record({"who": joined.person_id, "what": "phone_joined", "item_id": joined.person_id,
                 "detail": joined.name})
    _ledger("staff_phone_joined", who=links.identity(joined.person_id), device=_device(request), detail=joined.name)
    answer = JSONResponse(content={"ok": True, "name": joined.name.split(" ")[0]}, headers={"Cache-Control": "no-store"})
    answer.headers.append("set-cookie", joined.cookie)
    return answer


def _refused(status: int, code: str, detail: str, **extra) -> JSONResponse:
    content = {"ok": False, "code": code, "detail": detail}
    content.update({k: v for k, v in extra.items() if v is not None})
    return JSONResponse(status_code=status, content=content, headers={"Cache-Control": "no-store"})


def _ledger(action: str, *, who: str, device: str = "", detail: str = "") -> None:
    from app.connections import ledger

    ledger.record(action, connection="team", who=who, device=device, detail=detail)


# ------------------------------------------------------------------ the owner's

def _team_host(request: Request) -> str:
    from app.people import team_door

    runtime = getattr(request.app.state, "runtime", None)
    return team_door.configured_host(getattr(getattr(runtime, "settings", None), "team_host", "") or "")


def _member(person_id: str):
    person = people.get(person_id)
    if person is None or person.kind != "staff" or not person.active:
        raise _Refused(404, "unknown_person", "There is no such member of the team.")
    return person


@router.post("/staff-links/add")
@_guarded
async def staff_links_add(request: Request) -> JSONResponse:
    """Someone new on the team, by their name and what they do. Nothing opens for them until George
    makes their link with his passkey."""
    by = _owner_only()
    body = await _body(request)
    name = str(body.get("name") or "").strip()
    if not name:
        raise _Refused(400, "missing", "Give their name.")
    person, created = people.note({"name": name, "kind": "staff", "role": str(body.get("role") or ""), "active": True})
    work.record({"who": by, "what": "person_added", "item_id": person.person_id, "detail": person.name})
    return _answer({"person": {"person_id": person.person_id, "name": person.name}, "created": created})


@router.post("/staff-links/{person_id}/make")
@_guarded
async def staff_links_make(request: Request, person_id: str) -> JSONResponse:
    """Their link and its code, after George's passkey approved exactly this (staff-link:make:<person>).
    Shown to him once, in this answer: the server keeps neither."""
    from app.connections import ledger as connections_ledger
    from app.connections import passkeys
    from app.routes.connections import _device, _origin

    by = _owner_only()
    person = _member(person_id)
    host = _team_host(request)
    if not host:
        raise _Refused(409, "no_team_host", "The team's address is not set on the server yet (CROOKS_TEAM_HOST), "
                                            "so a link would lead nowhere. See docs/STAFF_LINKS.md.")
    body = await _body(request)
    try:
        origin, _ = _origin(request)
    except Exception as exc:  # noqa: BLE001 - the connections route's own refusal, said here
        raise _Refused(403, "wrong_origin", getattr(exc, "detail", "Open this in CLIVE itself.")) from None
    who = _login(request)
    try:
        used = passkeys.verify_approval(body.get("approval"), f"staff-link:make:{person.person_id}", login=who,
                                        origin=origin)
    except passkeys.PasskeyRefused as exc:
        connections_ledger.record("approval_refused", connection="staff-link:make", who=by, device=_device(request),
                                  ok=False, detail=str(exc))
        raise _Refused(403, exc.code, str(exc)) from None
    try:
        token, code, expires_at = links.make(person.person_id, by=by, passkey=str(used.get("id") or ""))
    except links.LinkError as exc:
        raise _Refused(409, "not_now", str(exc)) from None
    work.record({"who": by, "what": "link_made", "item_id": person.person_id, "detail": person.name})
    _ledger("staff_link_made", who=who, device=_device(request), detail=person.name)
    return _answer({"link": f"https://{host}/join#{token}", "code": code, "expires_at": links._iso(expires_at),
                    "name": person.name})


@router.post("/staff-links/{person_id}/cancel")
@_guarded
async def staff_links_cancel(request: Request, person_id: str) -> JSONResponse:
    by = _owner_only()
    person = people.get(person_id)
    if person is None:
        raise _Refused(404, "unknown_person", "There is no such person on the list.")
    if not links.cancel(person.person_id):
        raise _Refused(404, "no_link", f"There is no link waiting for {person.name}.")
    work.record({"who": by, "what": "link_cancelled", "item_id": person.person_id, "detail": person.name})
    return _answer({})


@router.post("/staff-links/phones/{phone_id}/sign-out")
@_guarded
async def staff_links_sign_out(request: Request, phone_id: str) -> JSONResponse:
    """Taking access away needs no passkey: it only ever narrows who is let in, and must be quick."""
    by = _owner_only()
    owner_of = next((pid for pid, entry in links.summary().items()
                     if any(p["phone_id"] == phone_id and p["state"] == "active" for p in entry["phones"])), "")
    if not owner_of or not links.sign_out(phone_id, by=by):
        raise _Refused(404, "no_phone", "That phone is not signed in.")
    work.record({"who": by, "what": "phone_signed_out", "item_id": owner_of, "detail": _name_of(owner_of)})
    return _answer({})
