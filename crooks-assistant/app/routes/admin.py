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
    runtime = request.app.state.runtime
    kb = runtime.reload_kb()
    # The runtime's own prompt, so what it says beside the knowledge base (the installed skills'
    # names, app/runtime.py `system_prompt`) is not lost when the knowledge base is reloaded.
    await runtime.provider.set_system_prompt(runtime.system_prompt())
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
    import logging
    import secrets

    from app.routes.actions import TAILSCALE, principal_verdict, proxy_state

    login = request.headers.get("tailscale-user-login", "")
    route, why = proxy_state(request)
    _who, code, _detail = principal_verdict(request)
    # One line in the service's own log for every /whoami, without the login: the deploy reads it
    # to know that a real owner device got through end to end before it keeps a new build
    # (the 2026-09-27 deploy review, round 7, F-05B-AVAIL-PREFLIGHT). It carries a token made for
    # this request alone, which the answer carries too, so the line the deploy reads can be tied to
    # the phone that asked and not to any other request (round 8, F-05B-AVAIL-PREFLIGHT).
    check = secrets.token_hex(4)
    logging.getLogger("crooks.identity").info(
        "whoami: id=%s through=%s owner=%s refusal=%s", check, route, "true" if not code else "false", code or "none")
    return {
        "check": check,
        "login": login or None,
        "proxied": route == TAILSCALE,
        # Whether this request, as it arrived, is the owner's by the one rule every owner route
        # reads — so opening /whoami on his phone proves the whole path end to end (round 6,
        # F-05B-AVAIL). Only a yes or the refusal's code: never what the allow-list holds.
        "owner": not code,
        "owner_refusal": code or None,
        # How the request reached the app: direct, tailscale, this_host (the server through its
        # own `tailscale serve`) — the answer every gate reads, shown so it can be checked.
        "through": route,
        "why": why or None,
        "note": (
            "This is the login to put in CROOKS_ALLOWED_LOGINS."
            if login and route == TAILSCALE else "No Tailscale device on this request: it was made on the server itself."
        ),
    }
