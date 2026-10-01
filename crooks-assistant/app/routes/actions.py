"""POST /actions/{proposal_id}/commit — the owner tapped.

The only route from the tablet to a mutation, and it carries no arguments: a proposal id and
the session it belongs to. Everything else — what to send, to which order, checked against
what — was decided on the Mac when the proposal was staged. Claude is not in this loop.

Refusals are controlled codes the tablet turns into calm states. Nothing here leaks a GraphQL
document, a token, a variable, or a stack trace.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from app import readonly, screen
from app.actions import grammar
from app.observability import timeline
from app.presentation import present, present_action, present_proposal_state
from app.speech.speakable import to_speakable

log = logging.getLogger("crooks.actions")

router = APIRouter(prefix="/actions")


# What the tablet says, out loud, when a change cannot be applied from where it is. Fixed
# lines: nothing from the request and nothing from Shopify reaches the voice.
SPOKEN_REFUSALS = {
    "writes_disabled": "Changes are switched off on the server, so I can't apply that.",
    "allow_list_missing": "Nobody is allowed to apply changes yet: the allowed logins aren't set on the server.",
    "not_authorised": "This device isn't allowed to apply changes.",
    "not_authorised_local": "Requests from the server itself aren't allowed to apply changes.",
    "scope_missing": "The store hasn't granted the permission this change needs; the card says which.",
    "gmail_scope_missing": "The Gmail credential can't make that change yet; the card says what it needs.",
    "identity_unverified": "I couldn't confirm which device this is with Tailscale, so I can't apply that.",
}


def _refuse(status: int, code: str, detail: str, spoken_key: str | None = None) -> JSONResponse:
    content = {"code": code, "detail": detail, "spoken": SPOKEN_REFUSALS.get(spoken_key or code, "")}
    response = JSONResponse(status_code=status, content=content)
    response.crooks_code = code  # type: ignore[attr-defined] — for the timeline, never the wire
    return response


def _code_of(response: JSONResponse) -> str:
    return str(getattr(response, "crooks_code", "") or "")


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def caller_check(request: Request) -> tuple[str, str, str, str]:
    """Who is asking, and whether they may apply a change: (caller, code, detail, spoken_key).
    The code is empty when they may. The write boundary, independent of the general
    middleware: writes need the allow-list to exist, the caller to be on it, and a request made
    on the Mac itself to be deliberately permitted. Used by the commit route to refuse, and by
    /turn to tell the tablet — before anyone taps — whether a tap could work from here."""
    runtime = request.app.state.runtime
    settings = runtime.settings
    if not settings.writes_enabled:
        return "", "writes_disabled", "Writes are switched off on the server (CROOKS_WRITES_ENABLED).", "writes_disabled"
    allowed = runtime.allowed_logins
    if not allowed:
        return "", "allow_list_missing", "No allowed Tailscale logins are configured (CROOKS_ALLOWED_LOGINS).", "allow_list_missing"
    login = request.headers.get("tailscale-user-login", "").strip()
    # Only `tailscale serve` stamps an identity. A login header on a request that did not come
    # through it is a claim made by something on the server itself, and is worth nothing: that
    # request is judged as what it is, a local one. One that claims to have come through it and
    # did not is refused outright (proxy_state).
    route, why = proxy_state(request)
    if route == FORGED:
        return "", "identity_unverified", f"This request did not come through Tailscale: {why}.", "identity_unverified"
    if route == TAILSCALE:
        if login and login.lower() in allowed:
            if settings.tailscale_verify:
                # The header is a claim; Tailscale is asked who holds the forwarded address.
                from app import identity

                ok, why = identity.verify(request.headers.get("x-forwarded-for", ""), login, cli=identity.cli_path(settings.tailscale_cli))
                if not ok:
                    return "", "identity_unverified", f"Tailscale could not confirm this device's identity: {why}.", "identity_unverified"
            return login.lower(), "", "", ""
        if login and staff_caller() == login.lower():
            # A member of the team the door let in for this request, its identity confirmed there
            # (app/people/door.py): they may confirm a change, and only the ones the owner allowed
            # them, which staff_refusal() holds at each route that applies one.
            return login.lower(), "", "", ""
        return "", "not_authorised", "This login may not apply changes.", "not_authorised"
    # Not proxied: a request made on the Mac itself, whatever headers it carries.
    if settings.writes_local_owner:
        return "local", "", "", ""
    return "", "not_authorised_local", "Requests made on the server itself may not apply changes (CROOKS_WRITES_LOCAL_OWNER).", "not_authorised_local"


def staff_caller() -> str:
    """The login of the team member this request is from, when the door made it a staff request."""
    from app.tools import authority as tool_authority

    held = tool_authority.current()
    if held is None or held.kind != tool_authority.STAFF:
        return ""
    return str(held.purpose or "").lower()


def staff_refusal(operation: str | None) -> JSONResponse | None:
    """A team member may confirm only the changes the owner allowed them without his OK (fulfil, its
    tracking, an email reply, a stock adjustment, and the undo of each): any other is refused here,
    whatever card they hold (app/people/staff.py)."""
    if not staff_caller():
        return None
    from app.people import staff as staff_rules

    if operation and staff_rules.may_commit(operation):
        return None
    return _refuse(403, "not_yours_to_make", "That change is George's to make; ask him, or note it on the work list for him.")


def principal_check(request: Request) -> tuple[str, str]:
    """(who, why refused): principal_verdict without its code."""
    who, _code, why = principal_verdict(request)
    return who, why


def principal_verdict(request: Request) -> tuple[str, str, str]:
    """Who may read or change the owner's own records — objectives, builds, the gap record, his
    screens, the test session and its telemetry, the anticipation table — as (who, why refused).
    The write boundary's rule without the writes switch, failing the same way it does (the
    2026-09-26 and 2026-09-27 deploy reviews, F-05): no allow-list, nobody; a request that
    came through `tailscale serve` must carry a login on the list and, when
    CROOKS_TAILSCALE_VERIFY is on, Tailscale must confirm the device is theirs; one that claims
    to have come through it and did not is refused; a request made on the server itself is
    refused unless CROOKS_WRITES_LOCAL_OWNER says the server is the owner. Other processes run
    on that host."""
    runtime = getattr(request.app.state, "runtime", None)
    allowed = getattr(runtime, "allowed_logins", ()) if runtime is not None else ()
    if not allowed:
        # As caller_check: an empty list is a server nobody has said is anyone's.
        return "", "allow_list_missing", "No allowed logins are set on the server (CROOKS_ALLOWED_LOGINS)."
    settings = runtime.settings
    login = request.headers.get("tailscale-user-login", "").strip()
    route, why = proxy_state(request)
    if route == FORGED:
        return "", "identity_unverified", f"This request did not come through Tailscale: {why}."
    if route == TAILSCALE:
        if not login or login.lower() not in allowed:
            return "", "not_authorised", "This login may not use this."
        if settings.tailscale_verify:
            from app import identity

            ok, why = identity.verify(request.headers.get("x-forwarded-for", ""), login, cli=identity.cli_path(settings.tailscale_cli))
            if not ok:
                return "", "identity_unverified", f"Tailscale could not confirm this device's identity: {why}."
        return login.lower(), "", ""
    if settings.writes_local_owner or getattr(settings, "local_owner", False):
        return "local", "", ""
    return "", "not_authorised_local", ("Requests made on the server itself may not use this "
                                        "(CROOKS_LOCAL_OWNER or CROOKS_WRITES_LOCAL_OWNER).")


async def require_principal(request: Request) -> None:
    """A route dependency: principal_check, refused as 403 with its reason."""
    from fastapi import HTTPException

    who, why = principal_check(request)
    if why:
        raise HTTPException(status_code=403, detail=why)


# How a request reached the app. One answer, used by the middleware, the write boundary and the
# owner-only rule alike, so that the three can never disagree about it.
DIRECT = "direct"          # made on this server: no forwarding header
TAILSCALE = "tailscale"    # came through `tailscale serve` from one of the tailnet's devices
THIS_HOST = "this_host"    # came through `tailscale serve`, sent by this server to itself
FORGED = "forged"          # carries forwarding headers and did not come through tailscaled
_PROXY_KEY = "crooks.proxy_state"


def proxy_state(request: Request) -> tuple[str, str]:
    """(route, why) for this request; worked out once and kept on the request.

    `tailscale serve` stamps X-Forwarded-For on everything it proxies, but so can any process
    on the server (the 2026-09-27 deploy review, F-05B). With CROOKS_TAILSCALE_VERIFY on (the
    default, and production), a forwarded request counts as proxied only when the kernel says
    tailscaled opened the connection it arrived on (app/identity.py), and not when the address
    it was forwarded for is this server's own. With the check off (a development machine, the
    offline tests) the header is taken as it always was."""
    cached = request.scope.get(_PROXY_KEY)
    if cached is not None:
        return cached
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        result = (DIRECT, "")
    else:
        runtime = getattr(request.app.state, "runtime", None)
        settings = getattr(runtime, "settings", None)
        if not bool(getattr(settings, "tailscale_verify", True)):
            result = (TAILSCALE, "")
        else:
            from app import identity

            ok, why = identity.peer_is_tailscaled(request.scope.get("client"), request.scope.get("server"))
            mine, mine_why = identity.this_host(forwarded) if ok else (False, "")
            if not ok:
                result = (FORGED, why)
            elif mine is None:
                # Which addresses are this server's own could not be read whole, so a request it
                # sent itself could not be told from one of the owner's devices: refused, not
                # guessed, and the reason says which table and why (round 8, F-05B-AVAIL).
                result = (FORGED, mine_why)
            elif mine:
                result = (THIS_HOST, "sent through tailscale serve by this server itself")
            else:
                result = (TAILSCALE, "")
    request.scope[_PROXY_KEY] = result
    return result


def made_on_this_server(request: Request) -> bool:
    """A request made on the server itself: no forwarding header, or sent by the server to
    itself through `tailscale serve`. Never one that only claims a forwarding header."""
    return proxy_state(request)[0] in (DIRECT, THIS_HOST)


def caller_identity(request: Request) -> str:
    """Who is asking, for binding a conversation to them: the proxied login, or "local" for
    a request made on the server itself. The middleware has already refused a proxied request
    with no login, and one that only claims to be proxied, so this is never empty."""
    login = request.headers.get("tailscale-user-login", "").strip().lower()
    return login if proxy_state(request)[0] == TAILSCALE and login else "local"


def session_matches(session, request: Request) -> bool:
    """Whether this request may use this session. A session binds to the tailnet login that
    first used it; every later proxied request must carry the same one. A request made on
    the Mac itself is the owner at the keyboard — it may look at any conversation (and is
    still held to CROOKS_WRITES_LOCAL_OWNER before it can apply anything) and binds none."""
    identity = caller_identity(request)
    if identity == "local":
        return True
    if not session.login:
        session.login = identity
        return True
    return session.login == identity


def _authorise(request: Request) -> tuple[str, JSONResponse | None]:
    caller, code, detail, spoken_key = caller_check(request)
    if code:
        # Findable in one grep: the next "it said not allowed" is answered from this line.
        log.warning(
            "commit refused: %s — %s (login=%s proxied=%s path=%s)",
            code, detail, request.headers.get("tailscale-user-login", "") or "-",
            bool(request.headers.get("x-forwarded-for")), request.url.path,
        )
        return "", _refuse(403, code, detail, spoken_key)
    return caller, None


# The tablet is told whether a tap could work while the owner waits for the answer's voice.
# A Shopify scope check that is slow must not become the answer's latency: past this, the
# card is shown as it would be if the scopes were fine, and the tap itself decides.
WRITE_STATUS_TIMEOUT_S = 1.5


# When the preflight has just timed out, this is how long before it is tried again. Without
# it a Shopify that hangs costs the bound on the answer AND again on the tap.
PREFLIGHT_QUIET_S = 30.0
_preflight_timed_out_at = 0.0
_SLOW = "ready, unverified — the Shopify scope check was slow"


async def _write_status_soon(runtime, operation: str | None = None):
    """The preflight, bounded. It runs before the answer's voice and before a tap; neither may
    wait on a slow Shopify. Past the bound the change is treated as applicable — Shopify has
    the last word on the mutation itself, and refuses it there if the scope is really missing."""
    global _preflight_timed_out_at
    from app.runtime import WriteStatus

    if time.time() - _preflight_timed_out_at < PREFLIGHT_QUIET_S:
        return WriteStatus("unknown", _SLOW)
    try:
        return await asyncio.wait_for(runtime.write_status(operation), timeout=WRITE_STATUS_TIMEOUT_S)
    except TimeoutError:
        _preflight_timed_out_at = time.time()
        log.warning("the write preflight took longer than %.1fs; treated as ready", WRITE_STATUS_TIMEOUT_S)
        return WriteStatus("unknown", _SLOW)


def _unknown_capabilities(runtime) -> dict:
    return {op: {"state": "unknown", "detail": _SLOW, "scope": scope} for op, scope in runtime._write_scopes().items()}


async def _preflight_soon(runtime, operation: str | None = None):
    """The status and the per-change table together, under ONE bound: the two read the same
    cached scope answer, and a Shopify that hangs costs the turn the bound once, not twice.
    Past it every built change is "unknown": offered, with Shopify deciding the tap."""
    global _preflight_timed_out_at
    from app.runtime import WriteStatus

    if time.time() - _preflight_timed_out_at < PREFLIGHT_QUIET_S:
        return WriteStatus("unknown", _SLOW), _unknown_capabilities(runtime)
    try:
        status, capabilities = await asyncio.wait_for(
            asyncio.gather(runtime.write_status(operation), runtime.capabilities()), timeout=WRITE_STATUS_TIMEOUT_S,
        )
    except TimeoutError:
        _preflight_timed_out_at = time.time()
        log.warning("the write preflight took longer than %.1fs; treated as ready", WRITE_STATUS_TIMEOUT_S)
        return WriteStatus("unknown", _SLOW), _unknown_capabilities(runtime)
    return status, capabilities


async def writes_context(request: Request, operation: str | None = None) -> dict:
    """What the tablet needs to know about applying changes from this request's identity:
    whether writes are ready on the Mac, whether this caller may tap, and which changes the
    Mac could make right now (for the order card's rail). Sent with every turn that proposes
    something, so the card can say up front when a tap would be refused."""
    runtime = request.app.state.runtime
    caller, code, detail, spoken_key = caller_check(request)
    status, capabilities = await _preflight_soon(runtime, operation)
    if not code and not status.ready:
        code, detail, spoken_key = status.code, status.detail, status.code
    if code:
        # The turn-time refusal, in the log as plainly as a refused tap: the owner hears one
        # sentence, and this line says which and why. The card names the local case as the
        # Mac's own doing, never as the tablet's login.
        log.warning(
            "change proposed but a tap would be refused: %s — %s (login=%s proxied=%s writes=%s)",
            spoken_key or code, detail, request.headers.get("tailscale-user-login", "") or "-",
            bool(request.headers.get("x-forwarded-for")), status.state,
        )
    offered = capabilities if not code or code == status.code else {}
    if staff_caller() and isinstance(offered, dict):
        # A team member is offered only the changes the owner allowed them (app/people/staff.py).
        from app.people import staff as staff_rules

        offered = {op: v for op, v in offered.items() if staff_rules.may_commit(op)}
    return {
        "state": status.state,
        "allowed": not code,
        "code": (spoken_key or code) if code else "",
        "detail": detail,
        "spoken": SPOKEN_REFUSALS.get(spoken_key, "") if code else "",
        "caller": caller or None,
        # The rail's source: which changes this Mac could make now, by operation. Empty when
        # the caller may not tap at all, so no chip is offered to a login that cannot use it.
        "capabilities": offered,
    }


@router.post("/row", response_model=None)
async def row(request: Request, session_id: str = Form(default=""), action: str = Form(default=""), ref: str = Form(default=""), branch_id: str = Form(default="")) -> JSONResponse | dict:
    """A button beside a row on a card was tapped.

    The page posts WHICH action and WHICH row, and nothing else. The server looks the action
    up in its own table (app/actions/rows.py), builds the arguments from a fresh read through
    the write tool's own prepare step, and stages a proposal — the same path a change the
    model proposed takes, through the same gate. Nothing is applied here: the card that comes
    back still waits for the owner's gesture.
    """
    runtime = request.app.state.runtime
    caller, refusal = _authorise(request)
    if refusal is not None:
        return refusal
    session_id = session_id.strip()
    if not session_id:
        return _refuse(400, "wrong_session", "The session is missing.")
    try:
        owner_session = runtime.sessions.get(session_id)
    except KeyError:
        return _refuse(409, "no_session", "That conversation has gone; ask again.")
    if not session_matches(owner_session, request):
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")

    from app.actions import rows as row_actions

    # The change belongs to the half of the orb the row was on, not to whichever half happens
    # to be focused when the finger lands — nor to whichever half last spoke. Focusing the half
    # was not enough: the engine stamps a proposal with the request's own half first and the
    # session's `acting_branch` after it, and that field holds the half that last had a
    # sentence or a tap, so Archive on a row in the left half, after a question to the right,
    # was filed against the right. The right half's next question then withdrew it and the left
    # half's did not (the 2026-09-28 deploy review, round 9, D2-03). The row's half is held on
    # this request's own task, as /turn and /command hold theirs.
    if branch_id.strip():
        owner_session.focus_branch(branch_id.strip())
    row_half = owner_session.branch(branch_id.strip()).branch_id
    try:
        spec, args = row_actions.resolve(action, ref)
    except row_actions.UnknownRowAction:
        # Fail closed: an action this build does not offer is not attempted, whatever the
        # tablet believes it saw.
        log.warning("row action refused: %r is not offered", action)
        return _refuse(400, "unknown_action", "That button is not one this build offers.")
    if staff_caller():
        from app.people import staff as staff_rules

        if spec.tool not in staff_rules.WRITES:
            return _refuse(403, "not_yours_to_make", "That change is George's to make.")
    status = await _write_status_soon(runtime, spec.tool)
    if not status.ready:
        return _refuse(403, status.code, status.detail, status.code)

    from app.tools.context import CURRENT_BRANCH
    from app.tools.dispatch import dispatch

    calls: list = []
    owner_session.acting_branch = row_half
    token = CURRENT_BRANCH.set(row_half)
    try:
        await dispatch(spec.tool, args, session=owner_session, timeout_s=runtime.settings.tool_timeout_s, calls=calls)
    finally:
        CURRENT_BRANCH.reset(token)
    proposal_id = next((c.proposal_id for c in calls if getattr(c, "proposal_id", None)), "")
    if not proposal_id:
        detail = next((str(c.error) for c in calls if not c.ok and c.error), "That change could not be prepared.")
        timeline.emit("row_action", session_id=session_id, action=str(action)[:40], ok=False, detail=detail[:200])
        return _refuse(409, "not_prepared", detail[:200])
    runtime.actions.deliver(proposal_id)
    timeline.emit("row_action", session_id=session_id, turn_id=getattr(owner_session, "turn_id", "") or None, action=str(action)[:40], ok=True, proposal_id=proposal_id)
    ui = present(calls, session=owner_session, writes=await writes_context(request))
    # The list the row was on stays, with the card beside it (app/screen.py); and it is what
    # this half now shows, so a reload or a switch of halves draws the same.
    half = owner_session.branch(row_half)
    ui = screen.carry(ui, branch=half, session=owner_session)
    ui = screen.listening_on_cursor(ui, getattr(half, "entity", None))
    half.shown(ui, half.last_answer, half.last_question)
    return {"staged": True, "proposal_id": proposal_id, "ui": ui}


@router.post("/{proposal_id}/arm", response_model=None)
async def arm(request: Request, proposal_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    """The owner's hold began on a card whose gesture is a hold. The server notes when, and
    answers with a single-use token the commit must carry. Same refusals as a commit: a login
    that may not apply changes may not arm one either."""
    runtime = request.app.state.runtime
    caller, refusal = _authorise(request)
    if refusal is not None:
        return refusal
    if not session_id.strip():
        return _refuse(400, "wrong_session", "The session is missing.")
    try:
        owner_session = runtime.sessions.peek(session_id.strip())
    except KeyError:
        owner_session = None
    if owner_session is not None and not session_matches(owner_session, request):
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")
    # A hold is refused where the tap would be: a change the store has not granted is never
    # armed, so the tablet never says "armed" about a tap the Mac already knows it will refuse.
    pending = runtime.actions.state(proposal_id, session_id.strip())
    # And the same branch refusal, so the tablet is never told "armed" about a card the
    # commit will refuse a moment later. The docstring promised this; now it is true.
    if pending is not None:
        elsewhere = _branch_may_commit(owner_session, pending)
        if elsewhere:
            timeline.emit("action_arm_refused", session_id=session_id.strip(), proposal_id=proposal_id, code="branch_not_focused", detail=elsewhere)
            return _refuse(409, "branch_not_focused", elsewhere)
    if pending is not None and (refused := staff_refusal(pending.operation)) is not None:
        return refused
    status = await _write_status_soon(runtime, pending.operation if pending is not None else None)
    if not status.ready:
        log.warning("arm refused: %s — %s (caller=%s)", status.code, status.detail, caller)
        timeline.emit("action_arm_refused", session_id=session_id.strip(), proposal_id=proposal_id, code=status.code, detail=status.detail)
        return _refuse(403, status.code, status.detail, status.code)
    proposal, code = runtime.actions.arm(proposal_id, session_id.strip())
    if proposal is None:
        timeline.emit("action_arm_refused", session_id=session_id.strip(), proposal_id=proposal_id, code=code, detail="no such proposal")
        return _refuse(404 if code == "unknown" else 403, code, "No such proposal for this session.")
    if code:
        timeline.emit("action_arm_refused", session_id=session_id.strip(), proposal_id=proposal_id, code=code, detail="no longer waiting")
        return _refuse(409, code, "That change is no longer waiting.")
    log.info("action %s armed by %s", proposal.proposal_id, caller)
    return {"proposal_id": proposal.proposal_id, "nonce": proposal.arm_nonce, "hold_ms": grammar.HOLD_MS, "armed_for_s": grammar.ARMED_FOR_S}


def _branch_may_commit(session, proposal) -> str:
    """Why this branch may not apply this change, if it may not.

    A change belongs to the half of the orb it was asked for in. A half the owner has put to
    one side is not where his hands are: it goes on reading, and it can never commit. This is
    the route's part of "background execution must never silently commit a write"; the other
    part is that nothing in the background calls this route at all.
    """
    branch_id = str(getattr(proposal, "branch_id", "") or "")
    if session is None:
        return ""
    live = [b for b in getattr(session, "branches", {}).values() if b.status in ("ACTIVE", "BACKGROUND")]
    if not branch_id:
        # A change with no half named belongs to an undivided conversation. Once the orb has
        # divided there is no such thing, and a card that cannot say where it came from is
        # not one a gesture may apply.
        return "" if len(live) <= 1 else "That change was made before the orb divided. Ask again in the half you want it in."
    branch = getattr(session, "branches", {}).get(branch_id)
    if branch is None:
        return "That change belongs to a half of the conversation that is gone."
    if branch.status == "BACKGROUND":
        return "That change belongs to the half you put aside. Tap it to come back to it first."
    if branch.status in ("CANCELLED", "MERGED"):
        return "That change belongs to a half of the conversation that is closed."
    return ""


@router.post("/{proposal_id}/commit", response_model=None)
async def commit(request: Request, proposal_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    started = time.perf_counter()
    runtime = request.app.state.runtime
    caller, refusal = _authorise(request)
    if refusal is not None:
        timeline.emit("action_commit_refused", session_id=session_id.strip(), proposal_id=proposal_id, code=_code_of(refusal), ms=_elapsed(started))
        return refusal
    if not session_id.strip():
        return _refuse(400, "wrong_session", "The session is missing.")
    try:
        owner_session = runtime.sessions.peek(session_id.strip())
    except KeyError:
        owner_session = None
    if owner_session is not None and not session_matches(owner_session, request):
        log.warning("commit refused: wrong_session — another login's conversation (caller=%s)", caller)
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")
    # The preflight is for THIS change's scope: a fulfilment scope the store has not granted
    # does not stop a note. The proposal is looked at, not claimed; the engine claims it.
    pending = runtime.actions.state(proposal_id, session_id.strip())
    if pending is not None:
        elsewhere = _branch_may_commit(owner_session, pending)
        if elsewhere:
            log.warning("commit refused: branch %s is not where the owner is (caller=%s)", getattr(pending, "branch_id", ""), caller)
            timeline.emit("action_commit_refused", session_id=session_id.strip(), proposal_id=proposal_id, code="branch_not_focused", detail=elsewhere, ms=_elapsed(started))
            return _refuse(409, "branch_not_focused", elsewhere)
    if staff_caller() and (refused := staff_refusal(pending.operation if pending is not None else None)) is not None:
        timeline.emit("action_commit_refused", session_id=session_id.strip(), proposal_id=proposal_id, code="not_yours_to_make", ms=_elapsed(started))
        return refused
    status = await _write_status_soon(runtime, pending.operation if pending is not None else None)
    if not status.ready:
        log.warning("commit refused: %s — %s (caller=%s)", status.code, status.detail, caller)
        timeline.emit("action_commit_refused", session_id=session_id.strip(), proposal_id=proposal_id, code=status.code, detail=status.detail, ms=_elapsed(started))
        return _refuse(403, status.code, status.detail, status.code)

    from app.tools import registry

    def spec_lookup(name: str):
        try:
            return registry.get(name)
        except KeyError:
            return None

    # The arming token travels as a header: the body carries the session and nothing else,
    # and the token is an authorisation, not an argument.
    nonce = request.headers.get("x-crooks-arm", "").strip()[:64]
    # A change prepared from a workspace (an order, a code, a credit): a card that has already
    # made its one thing — or is making it now — makes nothing more, whichever hold card is
    # held; and while this one is being applied the card is finished, so a second Prepare
    # meanwhile cannot make a second (app/families/_workspace.py "made once").
    from app.families import _workspace as workspaces

    if pending is not None:
        already = workspaces.commit_refused(pending)
        if already:
            runtime.actions.revoke_ids([pending.proposal_id], "its card has already made what it was for")
            timeline.emit("action_commit_refused", session_id=session_id.strip(), proposal_id=proposal_id,
                          code="already_made", ms=_elapsed(started))
            return _refuse(409, "already_made", already)
        workspaces.before_commit(pending)
    result = await runtime.actions.commit(proposal_id, session_id.strip(), caller=caller, spec_lookup=spec_lookup, nonce=nonce)
    if result.proposal is not None:
        workspaces.after_commit(result.proposal, session=owner_session)
    if result.proposal is None:
        timeline.emit("action_commit_refused", session_id=session_id.strip(), proposal_id=proposal_id, code=result.code, detail="no such proposal", ms=_elapsed(started))
        return _refuse(404 if result.code == "unknown" else 403, result.code, "No such proposal for this session.")
    if result.code == "read_only":
        # A backend latched read-only for an acceptance run. The card is untouched and still
        # says PENDING: nothing was claimed, so nothing has to be un-claimed.
        log.warning("commit refused: read_only — %s", readonly.reason())
        timeline.emit("action_commit_refused", session_id=session_id.strip(), proposal_id=proposal_id,
                      turn_id=result.proposal.turn_id or None, code="read_only", ms=_elapsed(started))
        return _refuse(403, "read_only", "This backend is in read-only test mode and cannot apply changes.")
    if result.code == "not_armed":
        log.warning("commit refused: not_armed — a hold gesture without its hold (caller=%s)", caller)
        timeline.emit("action_commit_refused", session_id=session_id.strip(), proposal_id=proposal_id, turn_id=result.proposal.turn_id or None, code="not_armed", nonce_present=bool(nonce), ms=_elapsed(started))
        return _refuse(409, "not_armed", "Hold the card first.")

    proposal = result.proposal
    # The work list (app/work/hooks.py): a claimed job this change was for is done, in the name of
    # whoever confirmed it, and the record says who made the change. Never in the way of the change.
    from app.work import hooks as work_hooks

    work_hooks.after_commit(proposal)
    # A change that left for Shopify from a workspace and was not proven made is sent, not
    # confirmed, on every surface — the response the hold card settles from, the voice, the
    # result card — and never "not applied" (app/families/_workspace.py `sent_not_confirmed`).
    unconfirmed = workspaces.sent_not_confirmed(proposal)
    code = "unverified" if unconfirmed else result.code
    spoken = workspaces.SENT_NOT_CONFIRMED if unconfirmed else result.spoken
    log.info("action %s %s → %s (%s)", proposal.proposal_id, proposal.operation, proposal.status.value, result.code)
    timeline.emit(
        "action_commit", session_id=session_id.strip(), proposal_id=proposal.proposal_id, turn_id=proposal.turn_id or None,
        operation=proposal.operation, code=result.code, status=proposal.status.value, verified=proposal.verified,
        spoken=result.spoken, detail=getattr(result, "detail", "") or None, nonce_present=bool(nonce), undo_id=proposal.undo_id, ms=_elapsed(started),
    )
    if spoken and not staff_caller():
        # A fixed line, synthesised once and kept: the tablet asks /speak for it next.
        # Pinned only when fixed: a success line names the order and is not worth a slot.
        # The team's page reads the line rather than playing it, so nothing is synthesised for it.
        runtime.voice.prefetch(to_speakable(spoken, max_chars=runtime.voice.max_chars), pin=code != "verified")
    try:
        session = runtime.sessions.peek(session_id.strip())
    except KeyError:
        session = None
    if session is not None and spoken and code in ("verified", "stale", "unverified", "failed", "refused", "service_unavailable"):
        session.last_outcome = spoken
    undo = None
    if proposal.undo_id and session is not None:
        undo_proposal = session.proposal(proposal.undo_id)
        if undo_proposal is not None:
            undo = undo_proposal.public()
    writes = await writes_context(request, proposal.operation)
    # The record the change was about stays where the owner left it, redrawn with its new
    # state — as the workspace it was shown as, with what can be done with it now — and the
    # half's own copy of its screen is settled to match what the tablet draws (app/screen.py).
    ui = screen.after_gesture(
        present_action(result, session=session, writes=writes), session=session, proposal_id=proposal.proposal_id,
        undo_of=proposal.undo_of or "", entity=proposal.entity, entity_kind=proposal.entity_kind, writes=writes,
    )
    return {
        **proposal.public(),
        **({"status": "unverified"} if unconfirmed else {}),
        "code": code,
        "spoken": spoken,
        "ui": ui,
        "undo": undo,
    }


# How many live surfaces one reconciliation may ask about. A screen shows a handful; a
# request naming fifty is not the tablet this was built for.
MAX_RECONCILE = 60


@router.get("/states", response_model=None)
async def states(request: Request, session_id: str = "", ids: str = "") -> JSONResponse | dict:
    """Where every card on the screen actually stands, in one request.

    The September session ended with two batches the page reported committed that the server
    never claimed. A gesture is a request, not an outcome: the page renders lifecycle from
    THIS — PROPOSED, ARMED, COMMITTING, VERIFIED, UNVERIFIED, FAILED, STALE, EXPIRED,
    REVOKED — and never from the fact that a finger moved. It reconciles after every gesture
    and on every wake, so a card cannot go on saying something the server disagrees with.
    """
    runtime = request.app.state.runtime
    session_id = session_id.strip()
    if not session_id:
        return _refuse(400, "wrong_session", "The session is missing.")
    try:
        session = runtime.sessions.peek(session_id)
    except KeyError:
        session = None
    if session is not None and not session_matches(session, request):
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")
    wanted = [i.strip() for i in (ids or "").split(",") if i.strip()][:MAX_RECONCILE]
    found: dict[str, dict] = {}
    unknown: list[str] = []
    for proposal_id in wanted:
        if proposal_id.startswith("batch_"):
            batch = runtime.batches.state(proposal_id, session_id)
            if batch is not None:
                found[proposal_id] = {**batch.public(), "kind": "batch"}
                continue
        else:
            proposal = runtime.actions.state(proposal_id, session_id)
            if proposal is not None:
                # Sent, not confirmed stays that on every wake, as the commit answered it.
                from app.families import _workspace as workspaces

                unconfirmed = {"status": "unverified", "code": "unverified"} if workspaces.sent_not_confirmed(proposal) else {}
                found[proposal_id] = {**proposal.public(), **unconfirmed, "kind": "action"}
                continue
        # The Mac has never heard of it, or it belonged to a conversation that has gone.
        # Either way the tablet must stop showing it as live.
        unknown.append(proposal_id)
    # What is WAITING, and what is merely on OFFER. Two lists, because they are two kinds of
    # thing and only one of them is counted: a change waiting is work the owner has not
    # decided about, and an undo is a way back from work that is finished. The live session's
    # merge toast counted two undo offers as "2 changes still waiting over there".
    pending = [pid for pid, state in found.items() if state.get("status") == "pending" and not state.get("undo_of")]
    undoable = [pid for pid, state in found.items() if state.get("status") == "pending" and state.get("undo_of")]
    # Whether the Mac is holding this conversation at all. When it is not — it restarted, or
    # the conversation idled out — the answer is not authoritative about which proposals
    # exist, and the tablet must not settle a card on the strength of it.
    return {"session_id": session_id, "session_known": session is not None, "states": found,
            "unknown": unknown, "pending": pending, "undoable": undoable,
            "epoch": getattr(session, "epoch", 0)}


@router.post("/{proposal_id}/dismiss", response_model=None)
async def dismiss(request: Request, proposal_id: str, session_id: str = Form(default="")) -> JSONResponse | dict:
    """Let an undo OFFER go.

    The page posts this when an undo's own clock runs out on the glass, so that the server's
    copy stops being something the owner could still be waiting on. It applies nothing,
    reverses nothing and withdraws nothing else — and a proposal that is not an undo is
    refused here, whatever the page believes: a change waiting for a gesture is let go by
    moving on from it, never by this door.
    """
    runtime = request.app.state.runtime
    if not session_id.strip():
        return _refuse(400, "wrong_session", "The session is missing.")
    try:
        owner_session = runtime.sessions.peek(session_id.strip())
    except KeyError:
        owner_session = None
    if owner_session is not None and not session_matches(owner_session, request):
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")
    proposal = runtime.actions.state(proposal_id, session_id.strip())
    if proposal is None:
        return _refuse(404, "unknown", "No such proposal for this session.")
    if proposal.undo_of is None:
        return _refuse(409, "not_an_undo", "That is a change waiting for you, not an offer to undo one.")
    dismissed = runtime.actions.dismiss_undo(proposal_id)
    timeline.emit("undo_dismissed", session_id=session_id.strip(), proposal_id=proposal_id,
                  turn_id=proposal.turn_id or None, ok=dismissed, status=proposal.status.value)
    return {"proposal_id": proposal.proposal_id, "status": proposal.status.value.lower(), "dismissed": dismissed}


@router.get("/{proposal_id}", response_model=None)
async def state(request: Request, proposal_id: str, session_id: str = "") -> JSONResponse | dict:
    """Where a proposal stands, for a device that lost the connection mid-tap: it asks what
    happened rather than sending the tap again. Public fields only."""
    runtime = request.app.state.runtime
    proposal = runtime.actions.state(proposal_id, session_id.strip())
    if proposal is None:
        return _refuse(404, "unknown", "No such proposal for this session.")
    try:
        session = runtime.sessions.peek(session_id.strip())
    except KeyError:
        session = None
    if session is not None and not session_matches(session, request):
        return _refuse(403, "wrong_session", "That conversation belongs to another login.")
    # The same preflight the commit route runs: a card recovered after a lost connection is
    # only shown as tappable when a tap from this request could actually work.
    writes = await writes_context(request, proposal.operation)
    return {**proposal.public(), "ui": present_proposal_state(proposal, session=session, writes=writes)}
