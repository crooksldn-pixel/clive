"""Deploy now: the owner's routes behind the Builds screen's "Deploy now" card (DEC-072; the owner's
rulings 6, 7 and 8 of 8 October 2026).

    GET  /release/deploy             what the card shows: the version waiting to go live (offer), whether
                                     his hold can deploy it now, and the deploy he approved, stage by stage
                                     (progress). ?progress=1 reads only this server's files, never GitHub:
                                     what the page asks every few seconds while a deploy runs.
    POST /release/deploy/challenge   his hold: a passkey prompt for exactly that SHA, with a challenge this
                                     server issues, good once, expiring in minutes (app/release/approve.py)
    POST /release/deploy             his passkey's answer: checked, and the approval written where the
                                     release service is started from at once (clive-release-now.path)
    POST /release/kept               after the deploy, his phone's own /whoami token: the deploy is kept
                                     once that line is in this service's journal, on the new build

Every route is the owner's alone: the door (app/main.py) refuses anyone else, the team included (their
routes are named in app/people/staff.py and these are not), and `require_principal` says so again. The
changes need his own device through Tailscale, never the server itself, and this CLIVE's own address
as the page's origin, because his passkey is bound to it (app/routes/connections.py, reused). No route
here runs a deploy or starts a unit, and none needs root (CLIVE's process runs as root today,
temporarily; nothing here relies on it): the release service, a separate program, checks his approval
and everything else itself. Nothing here is reachable by the model: no tool calls these.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.release import approve
from app.release import offer as offer_module
from app.release import status as release_status
from app.release.settings import ReleaseSettings
from app.routes import connections as conn
from app.routes.actions import require_principal
from app.tools import engineering_tools

log = logging.getLogger("crooks.release")
router = APIRouter(prefix="/release", dependencies=[Depends(require_principal)])

# The commit this process started on (its checkout's git files, read as the app is put together): a
# deploy is kept only by the build that was deployed, never by the one it replaced.
PROCESS_SHA = engineering_tools.running_sha()


def _settings(request: Request) -> Any:
    return getattr(getattr(request.app.state, "runtime", None), "settings", None)


def _folders(request: Request) -> tuple[Path, Path]:
    """Where CLIVE writes his approvals (the folder the release service reads and its trigger watches)
    and its record of the deploys he kept: beside his other records, in the objectives folder."""
    settings = _settings(request)
    root = Path(getattr(settings, "objectives_dir", "") or ".state/objectives")
    return root / approve.WAIVERS, root / approve.KEPT


def _refused(exc: approve.Refused) -> JSONResponse:
    return conn._refusal(exc.status, exc.code, exc.detail)


def _who_and_origin(request: Request) -> tuple[str, str, str]:
    """His login, this CLIVE's address and its passkey site: from his own device, at CLIVE's address."""
    who = conn._who(request)
    try:
        origin, rp_id = conn._origin(request)
    except conn._Refused as exc:
        if exc.code != "wrong_origin":
            raise
        raise conn._Refused(403, "wrong_origin", "Open CLIVE at its own address to approve a deploy: your "
                                                 "passkey only works there.") from None
    return who, origin, rp_id


def _state(request: Request, release: dict[str, Any]) -> dict[str, Any]:
    waivers, kept_dir = _folders(request)
    approval = approve.latest(waivers)
    kept = approve.kept_record(kept_dir, approval["sha"]) if approval else None
    shown = offer_module.progress(approval, release, kept=kept, process_sha=PROCESS_SHA, now=time.time())
    return {"progress": shown}


@router.get("/deploy")
@conn._guarded
async def deploy_state(request: Request, progress: int = 0) -> JSONResponse:
    """The card: the offer (unless ?progress=1), the progress of the deploy he approved, and the release
    service's own line. Changes nothing."""
    release = release_status.read()
    out: dict[str, Any] = {"release": release, "offer": None, "problems": [], **_state(request, release)}
    if not progress:
        live = engineering_tools.running_sha()
        if not live:
            out["problems"].append("CLIVE can't tell which version it runs, so it can't offer a deploy.")
        else:
            found = await offer_module.trunk(live, ReleaseSettings().repository)
            if found.problem:
                out["problems"].append(f"What's on the trunk couldn't be read: {found.problem}.")
            elif found.ahead and found.acceptance is not None and found.acceptance.state.value == "unavailable":
                out["problems"].append("GitHub acceptance on the trunk's head couldn't be read "
                                       f"({found.acceptance.detail}), so CLIVE can't offer a deploy.")
            out["offer"] = offer_module.offer(found, live=live, release=release)
            # The progress card says what happened to his approval. The same version's offer stays away
            # while that deploy runs, and after it unless his hold could start it again.
            shown = out["progress"]
            if shown and out["offer"] and shown["sha"] == out["offer"]["sha"] \
                    and (not shown["final"] or not out["offer"]["hold"]["can"]):
                out["offer"] = None
    return conn._answer(out)


@router.post("/deploy/challenge")
@conn._guarded
async def deploy_challenge(request: Request) -> JSONResponse:
    """His hold on the card: a passkey prompt for exactly the version it showed, if his hold can still
    deploy it (read again from GitHub now, not from the minute-old copy)."""
    who, origin, rp_id = _who_and_origin(request)
    body = await conn._body(request)
    sha = str(body.get("sha") or "")
    live = engineering_tools.running_sha()
    release = release_status.read()
    found = await offer_module.trunk(live, ReleaseSettings().repository, fresh=True) if live else None
    card = offer_module.offer(found, live=live, release=release) if found is not None else None
    if card is None or card["sha"] != sha:
        raise conn._Refused(409, "moved_on", "That version isn't the one waiting to go live any more. Nothing was "
                                             "deployed. The Builds screen shows what is.")
    if not card["hold"]["can"]:
        raise conn._Refused(409, "cannot_deploy", card["hold"]["why_not"])
    try:
        # Signed into the challenge: a hold shown as "Hold to try it (dry run)" can never deploy for real.
        asked = approve.begin(sha, card["title"], repository=ReleaseSettings().repository, login=who, origin=origin,
                              rp_id=rp_id, now=time.time(), mode="dry_run" if card["hold"]["dry_run"] else "live")
    except approve.Refused as exc:
        return _refused(exc)
    return conn._answer(asked)


@router.post("/deploy")
@conn._guarded
async def deploy_approve(request: Request) -> JSONResponse:
    """His passkey's answer: the approval for exactly that SHA, written for the release service, which
    its trigger starts at once. Answers with the progress the card then follows."""
    who, origin, _rp_id = _who_and_origin(request)
    body = await conn._body(request)
    waivers, _kept = _folders(request)
    try:
        approved = approve.finish(str(body.get("sha") or ""), str(body.get("ticket") or ""), body.get("approval"),
                                  repository=ReleaseSettings().repository, login=who, origin=origin, folder=waivers,
                                  now=time.time())
    except approve.Refused as exc:
        return _refused(exc)
    log.info("release: the owner approved a deploy of %s (%s)", approved["sha"][:8], conn._device(request))
    return conn._answer({"approved": approved, **_state(request, release_status.read())})


@router.post("/kept")
@conn._guarded
async def deploy_kept(request: Request) -> JSONResponse:
    """His phone's /whoami token, after the deploy: kept once its line is in the journal, on the new build."""
    conn._who(request)
    body = await conn._body(request)
    _waivers, kept_dir = _folders(request)
    release = release_status.read()
    try:
        record = approve.keep(str(body.get("sha") or ""), str(body.get("check") or ""), process_sha=PROCESS_SHA,
                              release=release, folder=kept_dir, now=time.time())
    except approve.Refused as exc:
        return _refused(exc)
    log.info("release: the deploy of %s was kept (his phone got through)", record["sha"][:8])
    return conn._answer({"kept": record, **_state(request, release)})
