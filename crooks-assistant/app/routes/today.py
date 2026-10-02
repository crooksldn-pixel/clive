"""The Today screen: the team's work list on their phones, and the owner's board of everyone's.

A member of the team sees their own jobs, what is up for grabs (jobs for anyone and what CLIVE
found: orders to pack, emails and Instagram messages waiting), and what they have done today; they
claim, mark packed, enter counts and finish with a note, and ask CLIVE (POST /turn) for the rest.
The owner sees everyone's, hands out jobs and routines, reads the record of who did what, and lets
a new member of the team in: their access waits for his passkey (app/people/access.py).

Behind the door like every route (app/main.py): the owner by his rule, the team by theirs
(app/people/door.py), and the owner-only steps here refuse anyone else.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.people import access
from app.people.store import PeopleError, people
from app.tools import authority as tool_authority
from app.work import found as live
from app.work import view
from app.work.store import WorkError, work

log = logging.getLogger("crooks.today")
router = APIRouter()

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
MAX_BODY = 64 * 1024
OWNER_NAME = "George"   # as the team's prompt names him (app/people/prompt.py)


class _Refused(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def _answer(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(content={"ok": True, **payload}, headers={"Cache-Control": "no-store"})


def _refusal(exc: _Refused | WorkError | PeopleError) -> JSONResponse:
    if isinstance(exc, _Refused):
        status, code, detail = exc.status, exc.code, exc.detail
    else:
        status, code, detail = 409, "not_now", str(exc)
    return JSONResponse(status_code=status, content={"ok": False, "code": code, "detail": detail},
                        headers={"Cache-Control": "no-store"})


def _who() -> tuple[str, bool, str]:
    """(who the record names, is the owner, the name to show)."""
    held = tool_authority.current()
    if held is None:
        raise _Refused(403, "not_allowed", "Open this from your own phone, signed in to Tailscale.")
    if held.kind == tool_authority.OWNER:
        return "owner", True, OWNER_NAME
    if held.kind == tool_authority.STAFF:
        person = people.get(held.who)
        return held.who, False, person.name if person else held.who
    raise _Refused(403, "not_allowed", "This is for the team.")


def _owner_only() -> str:
    who, owner, _ = _who()
    if not owner:
        raise _Refused(403, "owners", f"That is {OWNER_NAME}'s to do.")
    return who


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise _Refused(413, "too_large", "That is more than a job needs.")
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise _Refused(400, "bad_request", "The screen sent something unreadable. Reload it.") from None
    if not isinstance(body, dict):
        raise _Refused(400, "bad_request", "The screen sent something unreadable. Reload it.")
    return body


def _name_of(person_id: str) -> str:
    if not person_id:
        return ""
    if person_id == "owner":
        return OWNER_NAME
    person = people.get(person_id)
    return person.name if person else person_id


def _named(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each row with the names of the people on it, as the screen shows them."""
    out = []
    for row in rows:
        named = dict(row)
        for key in ("assignee", "claimed_by", "done_by", "who", "packed_by"):
            if named.get(key):
                named[f"{key}_name"] = _name_of(str(named[key]))
        out.append(named)
    return out


def _guarded(handler):
    import functools

    @functools.wraps(handler)
    async def run(*args: Any, **kwargs: Any):
        try:
            return await handler(*args, **kwargs)
        except (_Refused, WorkError, PeopleError, access.AccessError) as exc:
            if isinstance(exc, access.AccessError):
                exc = _Refused(409, "not_now", str(exc))
            return _refusal(exc)
    return run


# ------------------------------------------------------------------ the page and its state

@router.get("/today")
async def today_page(request: Request) -> Response:
    from app.routes.connections import PAGE_HEADERS

    source = (WEB_DIR / "today.html").read_text(encoding="utf-8")
    build = getattr(getattr(request.app.state, "runtime", None), "build", "unknown")
    return Response(source.replace("__BUILD__", str(build)), media_type="text/html; charset=utf-8", headers=PAGE_HEADERS)


@router.get("/today/state")
@_guarded
async def today_state(request: Request, fresh: bool = False) -> JSONResponse:
    who, owner, name = _who()
    runtime = getattr(request.app.state, "runtime", None)
    board = await view.today_for(runtime, who=who, owner=owner, fresh=bool(fresh))
    for key in ("mine", "mine_found", "up_for_grabs", "found", "in_hand", "team", "done"):
        board[key] = _named(board.get(key) or [])
    out: dict[str, Any] = {"me": {"id": who, "owner": owner, "name": name}, "work": board}
    if owner:
        grants = access.all_grants()
        out["people"] = [{**p.public(), "access": (grants.get(p.person_id) or {}).get("status") or ""}
                         for p in people.all(include_inactive=True)]
        out["record"] = _named(work.history(limit=40))
        out["routines"] = [{**r.__dict__, "assignee_name": _name_of(r.assignee)} for r in work.routines() if r.active]
    else:
        out["people"] = [p.public(for_staff=True) for p in people.all() if p.kind == "staff"]
        out["record"] = _named(work.history(who=who, limit=20))
    return _answer(out)


# ------------------------------------------------------------------ the ladder

@router.post("/today/claim")
@_guarded
async def today_claim(request: Request) -> JSONResponse:
    who, owner, _ = _who()
    body = await _body(request)
    if body.get("item_id"):
        item = work.claim(str(body["item_id"]), who=who, owner=owner)
    else:
        sources = await live.found(getattr(request.app.state, "runtime", None))
        row = view.found_row(sources, str(body.get("ref") or ""))
        if row is None:
            raise _Refused(409, "gone", "That is not on today's list any more. Pull to refresh.")
        item = work.claim_found(ref=row["ref"], kind=row["kind"], title=row["title"], details=row.get("details") or "", who=who)
    return _answer({"job": _named([item.summary()])[0]})


@router.post("/today/release")
@_guarded
async def today_release(request: Request) -> JSONResponse:
    who, owner, _ = _who()
    item = work.release(str((await _body(request)).get("item_id") or ""), who=who, owner=owner)
    return _answer({"job": _named([item.summary()])[0]})


@router.post("/today/packed")
@_guarded
async def today_packed(request: Request) -> JSONResponse:
    who, owner, _ = _who()
    item = work.packed(str((await _body(request)).get("item_id") or ""), who=who, owner=owner)
    return _answer({"job": _named([item.summary()])[0]})


@router.post("/today/counts")
@_guarded
async def today_counts(request: Request) -> JSONResponse:
    who, owner, _ = _who()
    body = await _body(request)
    counts = body.get("counts")
    if not isinstance(counts, list):
        raise _Refused(400, "bad_request", "Enter the counts as lines.")
    item = work.counted(str(body.get("item_id") or ""), counts, who=who, owner=owner)
    return _answer({"job": _named([item.summary()])[0]})


@router.post("/today/done")
@_guarded
async def today_done(request: Request) -> JSONResponse:
    who, owner, _ = _who()
    body = await _body(request)
    item = work.done(str(body.get("item_id") or ""), who=who, note=str(body.get("note") or ""), owner=owner)
    return _answer({"job": _named([item.summary()])[0]})


# ------------------------------------------------------------------ the owner's

@router.post("/today/assign")
@_guarded
async def today_assign(request: Request) -> JSONResponse:
    by = _owner_only()
    body = await _body(request)
    to = str(body.get("to") or "")
    if to and people.get(to) is None:
        raise _Refused(404, "unknown_person", "There is no such person on the list.")
    item = work.assign(title=str(body.get("title") or ""), details=str(body.get("details") or ""), assignee=to,
                       due=str(body.get("due") or ""), kind=str(body.get("kind") or "job"), by=by)
    return _answer({"job": _named([item.summary()])[0]})


@router.post("/today/cancel")
@_guarded
async def today_cancel(request: Request) -> JSONResponse:
    by = _owner_only()
    item = work.cancel(str((await _body(request)).get("item_id") or ""), by=by)
    return _answer({"job": _named([item.summary()])[0]})


@router.post("/today/routine")
@_guarded
async def today_routine(request: Request) -> JSONResponse:
    by = _owner_only()
    body = await _body(request)
    to = str(body.get("to") or "")
    if to and people.get(to) is None:
        raise _Refused(404, "unknown_person", "There is no such person on the list.")
    routine = work.add_routine(title=str(body.get("title") or ""), cadence=str(body.get("cadence") or ""),
                               details=str(body.get("details") or ""), assignee=to, kind=str(body.get("kind") or "job"), by=by)
    work.materialise()
    return _answer({"routine": routine.__dict__})


@router.post("/today/routine/stop")
@_guarded
async def today_routine_stop(request: Request) -> JSONResponse:
    by = _owner_only()
    if not work.stop_routine(str((await _body(request)).get("routine_id") or ""), by=by):
        raise _Refused(404, "unknown_routine", "There is no such routine running.")
    return _answer({})


def _access_step(request: Request, person_id: str, action: str, body: dict[str, Any]) -> tuple[str, Any, str]:
    """The owner's passkey, for exactly this step for exactly this person (app/connections/passkeys.py).
    Letting someone in also names the login the owner saw, and the passkey signs it: an approval is
    for that person with that login, never for whatever login the card holds by the time it lands."""
    from app.connections import ledger as connections_ledger
    from app.connections import passkeys
    from app.routes.connections import _device, _origin

    by = _owner_only()
    person = people.get(person_id)
    if person is None or person.kind != "staff":
        raise _Refused(404, "unknown_person", "There is no such member of the team.")
    login = str(body.get("login") or "").strip().lower() if action == "approve" else ""
    signed = f"access:{action}:{person_id}" + (f":{login}" if action == "approve" else "")
    try:
        origin, _ = _origin(request)
    except Exception as exc:  # noqa: BLE001 - the connections route's own refusal, said here
        raise _Refused(403, "wrong_origin", getattr(exc, "detail", "Open this in CLIVE itself.")) from None
    try:
        used = passkeys.verify_approval(body.get("approval"), signed, login=_login(request), origin=origin)
    except passkeys.PasskeyRefused as exc:
        connections_ledger.record("approval_refused", connection=f"access:{action}", who=by, device=_device(request),
                                  ok=False, detail=str(exc))
        raise _Refused(403, exc.code, str(exc)) from None
    if action == "approve":
        # What the passkey signed must still be what is waiting: the login on the card, and not one
        # of the owner's own (a staff login that is also his would make his changes theirs).
        if not login or login != person.login:
            raise _Refused(409, "login_changed", f"{person.name}'s login is not the one this screen showed. Reload "
                                                 "and look again before letting them in.")
        owners = {str(x).lower() for x in (getattr(getattr(request.app.state, "runtime", None), "allowed_logins", ())
                                           or ())}
        if login in owners:
            raise _Refused(409, "owner_login", "That login is the owner's own: a member of the team signs in with "
                                               "their own.")
    connections_ledger.record(f"access_{action}d" if action == "approve" else "access_suspended",
                              connection="team", who=_login(request), device=_device(request), detail=person.name)
    return by, used, login


def _login(request: Request) -> str:
    from app.routes.connections import _Refused as ConnectionsRefused
    from app.routes.connections import _who as connections_who

    try:
        return connections_who(request)
    except ConnectionsRefused as exc:       # the server itself, or no owner: said in this route's shape
        raise _Refused(exc.status, exc.code, exc.detail) from None


def _owner_logins(request: Request) -> set[str]:
    return {str(x).lower() for x in (getattr(getattr(request.app.state, "runtime", None), "allowed_logins", ()) or ())}


@router.post("/today/people")
@_guarded
async def today_people_add(request: Request) -> JSONResponse:
    """The owner adds someone to the team from the People tab: their name and the login they sign in
    to Tailscale with. It writes their card and a waiting grant, nothing more: letting them in is
    still the owner's passkey, on "Let them in". Before this, the only way was telling CLIVE, which
    had to get the kind and the login exactly right (2 October)."""
    by = _owner_only()
    body = await _body(request)
    name, login = str(body.get("name") or "").strip(), str(body.get("login") or "").strip().lower()
    if not name or not login:
        raise _Refused(400, "missing", "Give their name and the login they sign in to Tailscale with.")
    if login in _owner_logins(request):
        raise _Refused(409, "owner_login", "That login is the owner's own: a member of the team signs in with "
                                           "their own.")
    person, created = people.note({"name": name, "kind": "staff", "login": login,
                                   "role": str(body.get("role") or "")})
    state = access.ask(person.person_id, person.login)
    work.record({"who": by, "what": "person_added", "item_id": person.person_id, "detail": person.name})
    return _answer({"person": {"person_id": person.person_id, "name": person.name, "login": person.login},
                    "access": state, "created": created})


@router.post("/today/access/{person_id}/approve")
@_guarded
async def today_access_approve(request: Request, person_id: str) -> JSONResponse:
    body = await _body(request)
    by, used, login = _access_step(request, person_id, "approve", body)
    if not access.state(person_id):
        # A staff card with a login but no grant behind it (made before grants were asked, or by hand):
        # the passkey just approved this person with this login, so ask and let in together.
        person = people.get(person_id)
        if person is None or person.kind != "staff":
            raise _Refused(409, "not_staff", "Only a member of the team can be let in.")
        access.ask(person_id, login)
    try:
        access.approve(person_id, login=login, by=by, passkey=used.get("id", ""))
    except access.AccessError as exc:
        raise _Refused(409, "login_changed", str(exc).capitalize() + ".") from None
    work.record({"who": by, "what": "access_approved", "item_id": person_id, "detail": _name_of(person_id)})
    return _answer({"access": "active"})


@router.post("/today/access/{person_id}/suspend")
@_guarded
async def today_access_suspend(request: Request, person_id: str) -> JSONResponse:
    body = await _body(request)
    by, _, _ = _access_step(request, person_id, "suspend", body)
    access.suspend(person_id, by=by)
    work.record({"who": by, "what": "access_suspended", "item_id": person_id, "detail": _name_of(person_id)})
    return _answer({"access": "suspended"})
