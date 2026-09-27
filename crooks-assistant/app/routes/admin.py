"""Small operational endpoints: voice list metadata and knowledge-base reload."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/voices")
async def voices() -> dict:
    """The voice list itself comes from the browser — only the browser knows what is installed.
    This endpoint carries the guidance the picker shows alongside it."""
    return {
        "preferred_langs": ["en-GB", "en"],
        "guidance": (
            "Prefer a voice whose lang is en-GB and whose localService is true — a local voice "
            "keeps working when the network does not. If every voice shows localService false, "
            "install the en-GB voice data on this device, in its text-to-speech or spoken "
            "content settings."
        ),
    }


@router.post("/reload-kb")
async def reload_kb(request: Request) -> dict:
    from app.kb.loader import build_system_prompt

    runtime = request.app.state.runtime
    kb = runtime.reload_kb()
    await runtime.provider.set_system_prompt(build_system_prompt(kb, writes_enabled=runtime.settings.writes_enabled))
    return {
        "reloaded": True,
        "files": kb.files,
        "chars": kb.chars,
        "note": "Open conversations were reset so the new knowledge base takes effect.",
    }


@router.get("/tools")
async def tools() -> dict:
    """What the assistant can do, and at what tier. Useful when a refusal is surprising."""
    from app.tools.registry import all_specs

    return {
        "tools": [
            {"name": s.name, "tier": s.tier.value, "description": s.description}
            for s in all_specs()
        ]
    }


@router.get("/whoami")
async def whoami(request: Request) -> dict:
    """Who Tailscale says is asking. Open this on the device to see the exact login to put in
    CROOKS_ALLOWED_LOGINS; nothing is guessed. A request made on the server itself has no login."""
    from app.routes.actions import TAILSCALE, proxy_state

    login = request.headers.get("tailscale-user-login", "")
    route, why = proxy_state(request)
    return {
        "login": login or None,
        "proxied": route == TAILSCALE,
        # How the request reached the app: direct, tailscale, this_host (the server through its
        # own `tailscale serve`) — the answer every gate reads, shown so it can be checked.
        "through": route,
        "why": why or None,
        "note": (
            "This is the login to put in CROOKS_ALLOWED_LOGINS."
            if login and route == TAILSCALE else "No Tailscale device on this request: it was made on the server itself."
        ),
    }
