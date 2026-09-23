"""POST /support/investigate — one customer enquiry, investigated read-only.

The body carries the customer's message (and, when known, its subject and sender). The
route reads the store, the inbox and the knowledge base through the application's own
read-only tools, and answers with the identification, the what-happened summary in its three
kinds of statement, every piece of evidence used, the questions only the owner can decide,
and a reply draft that requires the owner's approval. Nothing is sent, saved or changed by
this route: it holds no write tool and calls none.

Given an evidence bundle instead of a message, it investigates that bundle without reading
anything, which is how a captured case is replayed.

Access is the application's: the tailnet allow-list middleware in `app/main.py` has already
refused any caller who is not one of the owner's logins.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.support import EvidenceBundle, investigate_bundle, parse_enquiry
from app.support.enquiry import MAX_TEXT
from app.support.evidence import gather

log = logging.getLogger("crooks.support")

router = APIRouter(prefix="/support")


class InvestigateBody(BaseModel):
    text: str = Field(default="", max_length=MAX_TEXT)
    subject: str = Field(default="", max_length=300)
    sender_email: str = Field(default="", max_length=254)
    bundle: dict[str, Any] | None = None
    include_bundle: bool = False


def live_readers() -> dict[str, Any]:
    """The live readers, looked up per request so a test can bind fakes in their place."""
    from app.support.live import readers

    return readers()


@router.post("/investigate", response_model=None)
async def investigate(request: Request, body: InvestigateBody) -> JSONResponse | dict[str, Any]:
    signature = _signature(request)
    if body.bundle is not None:
        try:
            bundle = EvidenceBundle.from_dict(body.bundle)
        except (ValueError, TypeError) as exc:
            return JSONResponse(status_code=400, content={"code": "bad_bundle", "detail": str(exc)[:160]})
        result = investigate_bundle(bundle, signature=signature)
        result["mode"] = "replay"
    else:
        if not body.text.strip():
            return JSONResponse(status_code=400, content={"code": "empty", "detail": "The customer's message is required."})
        enquiry = parse_enquiry(body.text, subject=body.subject, sender_email=body.sender_email)
        try:
            bundle = await gather(enquiry, **live_readers())
        except Exception as exc:  # noqa: BLE001 — the readers name their own failures; this is the last resort
            log.warning("support investigation could not gather evidence: %s", type(exc).__name__)
            return JSONResponse(status_code=503, content={"code": "unavailable", "detail": f"Could not gather the evidence: {type(exc).__name__}."})
        result = investigate_bundle(bundle, signature=signature)
        result["mode"] = "live"
    if body.include_bundle:
        result["bundle"] = bundle.to_dict()
    result["read_only"] = True
    return result


def _signature(request: Request) -> str:
    runtime = getattr(request.app.state, "runtime", None)
    settings = getattr(runtime, "settings", None)
    return str(getattr(settings, "gmail_signature", "") or "CROOKS")
