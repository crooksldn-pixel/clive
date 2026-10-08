"""Per-subsystem health, so the tablet can name what is broken rather than saying "error"."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Query, Request

from app.speech.voice_reasons import listening_reason, voice_reason

router = APIRouter()

VERSION = "0.1.0"

# The checks are real work: a Shopify query, a Gmail profile, a Scribe probe. The tablet polls;
# the settings sheet, the launcher and `make status` all ask. Answering from a recent result for
# this long keeps that from becoming a constant hum on the server and on the Shopify rate budget.
# `?fresh=1` skips it, for when someone is looking.
CACHE_TTL_S = 90.0


@router.get("/ping")
async def ping(request: Request) -> dict:
    """Is the server there at all? No external call and no cache: the installed app asks this on
    boot and every few seconds while the assistant is unreachable, and the answer must cost
    nothing and never be stale."""
    runtime = request.app.state.runtime
    return {"ok": True, "build": runtime.build, "uptime_s": round(runtime.uptime_s, 1)}


@router.get("/health")
async def health(request: Request, fresh: int = Query(default=0)) -> dict:
    runtime = request.app.state.runtime
    state = request.app.state
    cached = getattr(state, "health_cache", None)
    if not fresh and cached and time.time() - cached[0] < CACHE_TTL_S:
        return _guarded(request, {**_live(runtime, cached[1]), "observability": _observability(runtime, request), "cached": True, "age_s": round(time.time() - cached[0], 1)})
    lock = getattr(state, "health_lock", None)
    if lock is None:
        lock = state.health_lock = asyncio.Lock()
    async with lock:
        # A second poll arriving while the first is running waits for its answer rather than
        # doubling the work.
        cached = getattr(state, "health_cache", None)
        if not fresh and cached and time.time() - cached[0] < CACHE_TTL_S:
            return _guarded(request, {**_live(runtime, cached[1]), "observability": _observability(runtime, request), "cached": True, "age_s": round(time.time() - cached[0], 1)})
        result = await _health(runtime)
        state.health_cache = (time.time(), result)
        return _guarded(request, {**result, "observability": _observability(runtime, request), "cached": False, "age_s": 0.0})


# What /health says to a caller the owner rule refuses (the 2026-09-27 deploy review, round 8,
# F-NEW-PAD). /health is public — anything that can reach the port can ask, a device on the
# tailnet that is not the owner's among them — so such a caller gets liveness and nothing else:
# whether the server is well overall, which build, how long it has been up, and the two checks
# that say whether its own guards are working (_liveness says what each keeps). Built from an
# allow-list, not by taking the owner's blocks out, so that a block added later is the owner's by
# default. Sessions, write state, capabilities, families, the orders cache, the manifest, the
# voice, every other check and every check's detail (which can carry an exception's text) stay
# the owner's — and the server's own status readers', which carry its local key
# (app/local_cli.py).


def _guarded(request: Request, result: dict) -> dict:
    """The answer as this caller may see it: all of _checked for the owner and for the server's
    own status readers with their key, liveness alone for anyone else. Decided per request from
    the shared result, and never cached, so neither caller's answer is ever served to the other."""
    from app import local_cli
    from app.routes.actions import principal_verdict

    out = _checked(request.app.state, result)
    if local_cli.admits(request):
        return out
    _who, code, _detail = principal_verdict(request)
    return out if not code else _liveness(out)


def _the_owners(request: Request | None) -> bool:
    """Whether this request is the owner's (the owner rule) or the server's own status reader."""
    if request is None:
        return False
    from app import local_cli
    from app.routes.actions import principal_check

    return local_cli.admits(request) or not principal_check(request)[1]


def _liveness(out: dict) -> dict:
    """What a caller the owner rule refuses may read. proxy_identity keeps its detail because that
    string is only ever one of identity.served_without_proxy_headers's own fixed sentences (never an
    exception's text; tests/test_health_liveness.py holds it to them); housekeeping's detail can name a problem
    a pass met, so it goes as a verdict only."""
    checks = out.get("checks") if isinstance(out.get("checks"), dict) else {}
    shown: dict[str, dict] = {}
    proxy = checks.get("proxy_identity")
    if isinstance(proxy, dict):
        shown["proxy_identity"] = {"ok": proxy.get("ok") is True, "detail": str(proxy.get("detail") or "")}
    keeper = checks.get("housekeeping")
    if isinstance(keeper, dict):
        shown["housekeeping"] = {"ok": keeper.get("ok") is True}
    return {
        "status": "ok" if out.get("status") == "ok" else "degraded",
        "build": out.get("build"),
        "uptime_s": out.get("uptime_s"),
        "checks": shown,
        # So a reader can tell this answer from the whole one and never takes an absent check for
        # a working one (scripts/healthcheck.py, scripts/status.py).
        "limited": True,
    }


def _checked(state, result: dict) -> dict:
    """Two checks read at answer time, never cached, that say whether the server's own guards are
    working (the 2026-09-27 deploy review, round 6):

    proxy_identity — the server was started so it can tell who opened each connection (uvicorn
    with --no-proxy-headers, F-05B-AVAIL). Without it every request from the owner's devices is
    refused, so a deploy that did not update the service file shows here at once.
    housekeeping — the pass that ages the records and keeps the reports private ran, and the last
    one found nothing it could not put right (F-04). Neither carries anything but a verdict."""
    if "checks" not in result:
        return result
    from app import identity

    checks = dict(result["checks"])
    ok, detail = identity.served_without_proxy_headers()
    checks["proxy_identity"] = {"ok": ok, "detail": detail}
    keeper = getattr(state, "housekeeper", None)
    if keeper is not None:
        checks["housekeeping"] = keeper.check()
    return {**result, "checks": checks, "status": "ok" if all(c.get("ok") for c in checks.values()) else "degraded"}


def _live(runtime, result: dict) -> dict:
    """A cached result with the voice and Scribe's latest attempt read again at ANSWER time.

    Neither costs a request (the voice name is remembered for an hour, Scribe's probe is the
    one the cache was filled with), and a voice or a recogniser that failed a minute into the
    cache — or worked again after failing — must not be reported as it was when the cache was
    filled. The speech verdict and the status follow. The cached dict itself is not changed."""
    if "voice" not in result or "checks" not in result:
        return result
    ok, detail = runtime.voice.health()
    checks = {**result["checks"], "tts": {"ok": ok, "detail": detail}}
    speech = result.get("speech")
    probe = getattr(runtime.scribe, "last_probe", None)
    if speech is not None and probe is not None:
        scribe_ok, scribe_detail = runtime.scribe.judged(probe)
        checks["scribe"] = {"ok": scribe_ok, "detail": scribe_detail}
        checks["speech"], effective = _speech_verdict(checks, runtime.settings, failing=_scribe_failing(runtime))
        speech = {
            **speech,
            **_scribe_state(runtime),
            "scribe_ok": scribe_ok,
            "effective": effective,
        }
    return {
        **result,
        "status": "ok" if all(c["ok"] for c in checks.values()) else "degraded",
        "voice": _voice_block(runtime, ok),
        **({"speech": speech} if speech is not None else {}),
        "checks": checks,
    }


def _speech_verdict(checks: dict, settings, *, failing: str = "") -> tuple[dict, str]:
    """checks["speech"] and the engine actually hearing, from Scribe's check.

    Scribe is the only recogniser (DEC-022; the local fallback was deleted on 8 October,
    DEC-071 ruling 39), so Scribe down is a deaf assistant and `speech` says UNHEALTHY.
    `redundancy` publishes that there is nothing behind it, so the absence of a fallback is a
    visible fact rather than something you have to already know.

    `failing` is the kind of Scribe's current failure; while it is set, the verdict says in
    plain words what happened and what brings it back."""
    why = f" ({listening_reason(failing)})" if failing else ""
    if checks["scribe"]["ok"]:
        speech_ok, speech_effective = True, settings.scribe_model
        speech_detail = f"{settings.scribe_model} · no local fallback on this host (by design)"
    else:
        speech_ok, speech_effective = False, "none"
        speech_detail = f"NOT working: scribe is down{why} and there is no local fallback"
    return {"ok": speech_ok, "detail": speech_detail, "redundancy": "none"}, speech_effective


def _scribe_failing(runtime) -> str:
    """The kind of Scribe's failure while nothing has succeeded since — its latest attempt, or
    else a probe that found the key or the account wrong; "" when well."""
    scribe = runtime.scribe
    return getattr(scribe, "unwell_kind", "") or getattr(scribe, "failing_kind", "") or ""


def _scribe_state(runtime) -> dict:
    """Scribe's counters and, while it is failing with no success since, what happened in
    plain words."""
    scribe = runtime.scribe
    failing = _scribe_failing(runtime)
    return {
        "scribe_attempts": scribe.attempts,
        "scribe_successes": scribe.successes,
        "scribe_failures": scribe.failures,
        "scribe_last_error_kind": scribe.last_error_kind,
        "scribe_failure_kind": failing or None,
        "scribe_reason": listening_reason(failing) if failing else None,
    }


def _voice_block(runtime, ok: bool) -> dict:
    """One line for "who is speaking". The tablet decides nothing from this — it asks /speak
    and falls back if that fails — but it is what makes a silent tablet or an Android-sounding
    one diagnosable without reading the log."""
    voice = runtime.voice
    # Not `failing_kind`: with an empty account and no attempt yet there is no failure to name
    # and there is still a reason, and a block that says `ok: false` beside `reason: null` tells
    # the owner nothing. `blocking_kind` falls back to what the account said.
    failing = getattr(voice, "blocking_kind", "") or ""
    return {
        "provider": "elevenlabs" if voice.enabled else "browser",
        "voice": voice.voice_name,
        "model": voice.model,
        "output_format": voice.output_format,
        "enabled": voice.enabled,
        "ok": ok,
        "attempts": voice.attempts,
        "successes": voice.successes,
        "failures": voice.failures,
        "last_ms": round(voice.last_ms, 1),
        "last_bytes": voice.last_bytes,
        "last_error_kind": voice.last_error_kind,
        # Set while the latest attempt failed with no success since: what happened and what
        # brings it back. None once the voice has spoken again.
        "failure_kind": failing or None,
        "reason": voice_reason(failing) if failing else None,
        "prefetches": voice.prefetches,
        "prefetch_hits": voice.prefetch_hits,
    }


def _observability(runtime, request: Request | None = None) -> dict:
    """Whether a test session is on, read at answer time rather than from the cached checks:
    the tablet turns its own telemetry on and off from this, within one poll."""
    timeline = getattr(runtime, "timeline", None)
    # [recording] What is said to be running is a test session or the experience recording, never
    # the interaction record's own day: "is a test running?" stays a question about tests
    # (app/observability/interactions.py `reported`). The page turns its telemetry on for the
    # record too (web/telemetry.js `configure`), so `recording` names the day it is writing into —
    # to the owner's own devices only, whose telemetry the record keeps: a team member's phone
    # posting its account would only be refused at the door.
    from app.observability import interactions

    session = interactions.reported(timeline)
    out = {"test_session": session.test_session_id if session is not None else None, "name": session.name if session is not None else None}
    recording = interactions.current()
    if recording is not None and recording.active_id and _the_owners(request):
        out["recording"] = recording.active_id
    # Whether the page should send a copy of its screen too (CROOKS_SCREEN_SNAPSHOTS): only for a
    # test session of this timeline's own, never for a production recording. Said only when it
    # is so; the route refuses copies whenever it is not, whatever a page still believes.
    own = timeline.own if timeline is not None else None
    if own is not None and getattr(getattr(runtime, "settings", None), "screen_snapshots", False):
        out["screens"] = True
    return out


async def _health(runtime) -> dict:
    checks: dict[str, dict] = {}

    async def check(name: str, coro):
        try:
            ok, detail = await asyncio.wait_for(coro, timeout=6)
        except TimeoutError:
            ok, detail = False, "check timed out"
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        checks[name] = {"ok": ok, "detail": detail}

    running = [
        check("claude", runtime.provider.health()),
        check("shopify", runtime.shopify.health()),
        check("gmail", asyncio.to_thread(runtime.gmail.health)),
        check("scribe", runtime.scribe.health()),
    ]
    await asyncio.gather(*running)

    # Instagram, read-only: whether a token is stored, how long it has left and whether its last
    # call was refused. No network call: /health is polled, and the API has its own allowance.
    # Not connected is a configuration, not a fault, so it reads ok (app/clients/instagram.py).
    from app.clients import instagram as instagram_client

    ok, detail = instagram_client.health()
    checks["instagram"] = {"ok": ok, "detail": detail}

    # The voice is a configuration and credential check, never a synthesis: a health page that
    # spends ElevenLabs credit on every fifteen-second poll is a bill, not a check. Once an
    # hour it also asks ElevenLabs what it calls the configured id — free — so a .env still
    # naming an old voice cannot name the configured one here while another speaks on the tablet.
    try:
        await runtime.voice.verify_voice()
    except Exception:  # noqa: BLE001 — the name is a courtesy; the check below stands alone
        pass
    ok, detail = runtime.voice.health()
    checks["tts"] = {"ok": ok, "detail": detail}
    settings = runtime.settings

    # Speech recognition gets a verdict of its own — see _speech_verdict.
    checks["speech"], speech_effective = _speech_verdict(checks, settings, failing=_scribe_failing(runtime))

    checks["knowledge_base"] = {
        "ok": not runtime.kb.empty,
        "detail": f"{len(runtime.kb.files)} file(s), {runtime.kb.chars} chars",
    }

    # Whether a proposal could execute here. Off by configuration is the intended state and
    # not a fault; on but blocked (no allow-list, no scope) is a fault the owner should see.
    writes = await runtime.write_status()
    checks["writes"] = {"ok": writes.state != "blocked", "detail": writes.detail}
    # Every change the Mac knows how to make, and whether it could make it now. Off is the
    # intended state and not a fault; a scope the store has not granted is named here.
    capabilities = await runtime.capabilities()
    # The capability families (order editing, discount codes, store credit, abandoned
    # checkouts, shipping providers …) with the state a person can act on: READY,
    # MISSING_SCOPE (and which), NOT_SUPPORTED_BY_STORE, DISCONNECTED, NOT_IMPLEMENTED.
    try:
        families = await runtime.family_states()
    except Exception as exc:  # noqa: BLE001 — a probe must not take /health down
        families = {"_error": {"state": "TEMPORARILY_UNAVAILABLE", "detail": type(exc).__name__}}

    return {
        # Degraded, not down: Shopify being unreachable should not make the page say the
        # backend is offline, because Gmail and the knowledge base still work, and typing still
        # reaches CLIVE when ElevenLabs cannot hear.
        "status": "ok" if all(c["ok"] for c in checks.values()) else "degraded",
        "version": VERSION,
        # Changes whenever the tablet page's files change on the Mac; the tablet reloads
        # itself, when idle, on seeing a new one. A page can otherwise stay open for weeks.
        "build": runtime.build,
        "uptime_s": round(runtime.uptime_s, 1),
        "sessions": runtime.sessions.count(),
        # One line for "who is listening", so a spoken problem can be diagnosed at a glance.
        "speech": {
            "scribe_model": settings.scribe_model,
            "scribe_ok": checks["scribe"]["ok"],
            "redundancy": "none",
            "effective": speech_effective,
            # Set while Scribe's latest attempt failed with no success since, in plain words.
            **_scribe_state(runtime),
        },
        # And one line for "who is speaking" — see _voice_block.
        "voice": _voice_block(runtime, ok),
        "writes": {"state": writes.state, "detail": writes.detail},
        "capabilities": capabilities,
        "families": families,
        # What this build can do, from the generated manifest (app/capabilities): counts for
        # crooks-status, and the fingerprint so a build can be told apart from its neighbour.
        "manifest": (
            {**(runtime.manifest or {}).get("counts", {}), "fingerprint": (runtime.manifest or {}).get("fingerprint", "")}
            if getattr(runtime, "manifest", None) else None
        ),
        # The recent orders the read layer answers from: how many, how far back, how fresh.
        "orders_cache": runtime.order_cache.status() if getattr(runtime, "order_cache", None) is not None else None,
        "checks": checks,
    }
