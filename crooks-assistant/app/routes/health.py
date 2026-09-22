"""Per-subsystem health, so the tablet can name what is broken rather than saying "error"."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Query, Request

router = APIRouter()

VERSION = "0.1.0"

# The checks are real work: a Shopify query, a Gmail profile, half a second of whisper
# inference. The tablet polls; the settings sheet, the launcher and `make status` all ask.
# Answering from a recent result for this long keeps that from becoming a constant hum on the
# Mac and on the Shopify rate budget. `?fresh=1` skips it, for when someone is looking.
CACHE_TTL_S = 90.0


@router.get("/ping")
async def ping(request: Request) -> dict:
    """Is the Mac there at all? No external call and no cache: the installed app asks this on
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
        return {**cached[1], "observability": _observability(runtime), "cached": True, "age_s": round(time.time() - cached[0], 1)}
    lock = getattr(state, "health_lock", None)
    if lock is None:
        lock = state.health_lock = asyncio.Lock()
    async with lock:
        # A second poll arriving while the first is running waits for its answer rather than
        # doubling the work.
        cached = getattr(state, "health_cache", None)
        if not fresh and cached and time.time() - cached[0] < CACHE_TTL_S:
            return {**cached[1], "observability": _observability(runtime), "cached": True, "age_s": round(time.time() - cached[0], 1)}
        result = await _health(runtime)
        state.health_cache = (time.time(), result)
        return {**result, "observability": _observability(runtime), "cached": False, "age_s": 0.0}


def _observability(runtime) -> dict:
    """Whether a test session is on, read at answer time rather than from the cached checks:
    the tablet turns its own telemetry on and off from this, within one poll."""
    timeline = getattr(runtime, "timeline", None)
    session = timeline.active if timeline is not None else None
    return {"test_session": session.test_session_id if session is not None else None, "name": session.name if session is not None else None}


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

    primary = runtime.transcriber.primary
    whisper_enabled = runtime.settings.whisper_enabled
    running = [
        check("claude", runtime.provider.health()),
        check("shopify", runtime.shopify.health()),
        check("gmail", asyncio.to_thread(runtime.gmail.health)),
    ]
    if whisper_enabled:
        running.append(check("whisper", runtime.whisper.health()))
    else:
        # Not deployed here, and that is a decision rather than a failure. ok=True, so an
        # absence nobody intends to fix cannot make the whole host read as degraded — a check
        # that is permanently red is a check people stop reading, and then they stop reading
        # the one beside it too. `disabled` is what anything branching on this should use.
        # Nothing is being hidden: checks["speech"] below goes UNHEALTHY the moment the one
        # remaining recogniser stops answering, which on this host is the whole of speech.
        checks["whisper"] = {
            "ok": True,
            "disabled": True,
            "detail": "disabled (CROOKS_WHISPER_ENABLED=false) — no local recogniser on this host",
        }
    if primary == "scribe":
        running.append(check("scribe", runtime.scribe.health()))
    else:
        # Configured off. Don't call ElevenLabs, and don't report a subsystem nobody is using
        # as broken — that is how a health page trains people to ignore it.
        checks["scribe"] = {"ok": True, "detail": "not in use (CROOKS_STT_PRIMARY=whisper)"}

    await asyncio.gather(*running)

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

    # The plan's M3 failure check: Core ML build succeeds but the .mlmodelc is missing, and
    # everything runs twice as slowly with no error. Say so here so it cannot go unnoticed.
    if whisper_enabled and checks["whisper"]["ok"]:
        bin_dir = settings.whisper_bin_dir
        coreml = bin_dir / "models" / f"ggml-{settings.whisper_model}-encoder.mlmodelc"
        checks["whisper"]["detail"] += (
            " · Core ML encoder present" if coreml.exists()
            else " · no Core ML encoder (fine for a Metal-only build; ~2x slower if built with Core ML)"
        )

    # Speech recognition is two engines behind one job, so it gets a verdict of its own:
    # Scribe down while Whisper is up is a slower assistant, not a deaf one, and the tablet's
    # page should not read "degraded" as "cannot hear you".
    #
    # Where there is no second engine, that reasoning inverts and this is the one place that
    # matters. On the Mac, Scribe going down is a slower assistant. On a host with whisper
    # disabled it is a deaf one, and `speech` says UNHEALTHY rather than borrowing the Mac's
    # answer. `redundancy` publishes which of the two worlds the reader is in, so the absence
    # of a fallback is a visible fact rather than something you have to already know.
    primary_check = "scribe" if primary == "scribe" else "whisper"
    # Whether whisper could actually take a turn: deployed here AND answering. On the Mac this
    # is exactly checks["whisper"]["ok"], which is why nothing there changes.
    whisper_usable = whisper_enabled and checks["whisper"]["ok"]
    redundancy = "whisper" if whisper_enabled else "none"

    if primary == "whisper" and not whisper_enabled:
        # Configured to hear through an engine this host was never given. Neither setting is
        # wrong by itself, so neither check catches it alone; the pair is the fault, and it is
        # named rather than left to look like an ordinary whisper outage.
        speech_ok, speech_effective = False, "none"
        speech_detail = (
            "MISCONFIGURED — CROOKS_STT_PRIMARY=whisper but CROOKS_WHISPER_ENABLED=false: "
            "this host has no recogniser at all"
        )
    elif checks[primary_check]["ok"]:
        expect = settings.scribe_model if primary == "scribe" else "whisper"
        speech_ok, speech_effective = True, expect
        speech_detail = f"{expect} (primary)"
        if not whisper_enabled:
            speech_detail += " · no local fallback on this host (by design)"
    elif whisper_usable:
        speech_ok, speech_effective = True, "whisper_fallback"
        speech_detail = f"whisper_fallback — {primary_check} is unavailable, answers still work"
    else:
        speech_ok, speech_effective = False, "none"
        speech_detail = (
            "NO recogniser available — the tablet cannot be heard"
            if whisper_enabled
            else f"NOT working: {primary_check} is down and this host has no local fallback"
        )
    checks["speech"] = {"ok": speech_ok, "detail": speech_detail, "redundancy": redundancy}

    checks["knowledge_base"] = {
        "ok": not runtime.kb.empty,
        "detail": f"{len(runtime.kb.files)} file(s), {runtime.kb.chars} chars",
    }
    checks["terminology"] = {
        "ok": len(runtime.normaliser.catalogue) > 0,
        "detail": f"{len(runtime.normaliser.catalogue)} term(s)",
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
        # backend is offline, because Gmail and the knowledge base still work. Nor should
        # ElevenLabs — speech falls back to the Mac and the answer still arrives.
        "status": "ok" if all(c["ok"] for c in checks.values()) else "degraded",
        "version": VERSION,
        # Changes whenever the tablet page's files change on the Mac; the tablet reloads
        # itself, when idle, on seeing a new one. A page can otherwise stay open for weeks.
        "build": runtime.build,
        "uptime_s": round(runtime.uptime_s, 1),
        "sessions": runtime.sessions.count(),
        # One line for "who is listening", so a spoken problem can be diagnosed at a glance.
        "speech": {
            "primary": primary,
            "scribe_model": settings.scribe_model,
            "scribe_ok": checks["scribe"]["ok"],
            # Usable, not merely "the probe passed": a disabled whisper reports its check as
            # ok so the host is not degraded, and reporting that as whisper_ok here would be
            # the one place that turns into a lie about what can hear you.
            "whisper_ok": whisper_usable,
            "whisper_enabled": whisper_enabled,
            "redundancy": redundancy,
            "effective": speech_effective,
            "scribe_attempts": runtime.scribe.attempts,
            "scribe_successes": runtime.scribe.successes,
            "scribe_failures": runtime.scribe.failures,
            "scribe_last_error_kind": runtime.scribe.last_error_kind,
        },
        # And one line for "who is speaking". The tablet decides nothing from this — it asks
        # /speak and falls back if that fails — but it is what makes a silent tablet or an
        # Android-sounding one diagnosable without reading the log.
        "voice": {
            "provider": "elevenlabs" if runtime.voice.enabled else "browser",
            "voice": runtime.voice.voice_name,
            "model": runtime.voice.model,
            "output_format": runtime.voice.output_format,
            "enabled": runtime.voice.enabled,
            "ok": ok,
            "attempts": runtime.voice.attempts,
            "successes": runtime.voice.successes,
            "failures": runtime.voice.failures,
            "last_ms": round(runtime.voice.last_ms, 1),
            "last_bytes": runtime.voice.last_bytes,
            "last_error_kind": runtime.voice.last_error_kind,
            "prefetches": runtime.voice.prefetches,
            "prefetch_hits": runtime.voice.prefetch_hits,
        },
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
