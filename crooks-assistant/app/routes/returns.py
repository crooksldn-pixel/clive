"""CROOKS Returns on the owner's home: how many returns need him, and why, for its Needs you row.

GET /returns/brief reads the open returns through the same minute-long cache the returns_open
tool reads (app/clients/crooks_returns.py OpenReturns), so opening the home asks the service at
most once a minute, and only while someone has CLIVE open: nothing polls on a timer. It answers
counts and words, never a customer's name. Not connected, it says so and the home draws nothing.

The owner's alone: behind the door's owner rule like every route that is not the team's
(app/main.py, app/people/staff.py ROUTES), and asked for it again here (require_principal).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.clients import crooks_returns as client
from app.returns import views
from app.routes.actions import require_principal

router = APIRouter(prefix="/returns", dependencies=[Depends(require_principal)])


@router.get("/brief")
async def brief() -> JSONResponse:
    if not client.read_key():
        return _answer({"connected": False, "needs": 0, "words": "", "open": 0, "unused_labels": 0})
    try:
        rows, at = await client.OPEN.get()
    except client.ReturnsUnavailable as exc:
        return _answer({"connected": True, "available": False, "needs": 0, "open": 0, "unused_labels": 0,
                        "words": "", "problem": str(exc)})
    said = views.brief(rows, now=datetime.now(UTC))
    checked = datetime.fromtimestamp(at, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return _answer({"connected": True, "available": True, **said, "checked_at": checked})


def _answer(payload: dict) -> JSONResponse:
    return JSONResponse(content={"ok": True, **payload}, headers={"Cache-Control": "no-store"})
