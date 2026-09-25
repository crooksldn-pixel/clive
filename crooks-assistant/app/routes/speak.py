"""POST /speak — the answer, in the assistant's voice.

Deliberately a second request rather than part of /turn. The answer text has to be on the
tablet's screen the moment the agent finishes; making /turn wait for an MP3 would delay the
thing that matters for the sake of the thing that does not.

Nothing about ElevenLabs reaches the tablet: it sends text and receives audio/mpeg. The
credential stays on the Mac. Every failure is a 503 with a short, safe reason, which the tablet
reads as "use the Android voice" — never as "say nothing".
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.clients.elevenlabs_tts import VoiceUnavailable
from app.observability import timeline
from app.speech.speakable import to_speakable
from app.speech.voice_reasons import VOICE, voice_reason

log = logging.getLogger("crooks.speak")

router = APIRouter()

MAX_TEXT_CHARS = 4_000

# A prefetch that failed for one of these reasons is worth one fresh request: the failure was
# a moment's, not the account's. Anything sticky (a rejected key, no credit) is not retried,
# and neither is a timeout — ElevenLabs being slow is not cured by waiting for it twice; the
# tablet's own voice takes that sentence.
RETRY_ONCE_KINDS = frozenset({"server_error", "rate", "network", "prefetch", "empty", "truncated"})

# What the tablet is told. The kind is a shape, never an account detail or an API message —
# those are in the log, where they belong. The words are in app/speech/voice_reasons.py.
REASONS = VOICE


def _reason(kind: str, voice) -> str:
    """The plain reason for this refusal. A cooldown is worded as the failure that opened it:
    five minutes of "unavailable at the moment" is how an empty account went unexplained."""
    if kind == "cooldown":
        cause = getattr(voice, "last_error_kind", "") or ""
        if cause in REASONS and cause != "cooldown":
            return voice_reason(cause)
    return voice_reason(kind)


@router.post("/speak")
async def speak(request: Request) -> Response:
    """Text in, MP3 out. 204 when there is nothing worth saying, 503 when the voice cannot."""
    runtime = request.app.state.runtime
    voice = runtime.voice
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    raw = str(body.get("text") or "")[:MAX_TEXT_CHARS]
    started = time.perf_counter()
    trace = {
        "session_id": str(body.get("session_id") or "")[:64] or None, "turn_id": str(body.get("turn_id") or "")[:40] or None,
        "chars": len(raw), "text": raw,
    }

    spoken = to_speakable(raw, max_chars=voice.max_chars)
    if not spoken:
        # An answer made only of punctuation, or an empty one. Silence is the right output and
        # a paid request is not; 204 tells the tablet so without looking like a failure.
        timeline.emit("tts", ok=True, silent=True, ms=_ms(started), **trace)
        return Response(status_code=204)
    trace["spoken_chars"] = len(spoken)

    headers = {
        # Diagnostics the tablet can show without a second request, and nothing secret.
        "X-Crooks-Voice": voice.voice_name,
        "X-Crooks-Model": voice.model,
        "Cache-Control": "no-store",
    }
    try:
        # /turn started synthesising this answer the moment it knew it (VoiceClient.prefetch).
        # What has arrived goes out now and the rest follows as ElevenLabs produces it — the
        # tablet starts playing the opening while the ending is still being generated.
        try:
            ready = await voice.take_ready(spoken)
        except VoiceUnavailable as exc:
            if exc.kind in RETRY_ONCE_KINDS and not voice.cooling_down:
                # The prefetch hit a blip a round trip ago; the network may well answer now.
                # One fresh request, the same one the tablet would otherwise have made.
                log.info("prefetch failed (%s); trying the request once more", exc.kind)
                ready = None
            else:
                raise
        if ready is not None:
            return StreamingResponse(
                _observed(ready, trace, started, prefetched=True), media_type="audio/mpeg", headers={**headers, "X-Crooks-Prefetched": "1"}
            )
        stream = await voice.open_stream(spoken)
    except VoiceUnavailable as exc:
        if exc.kind == "cancelled":
            # §24: an EXPECTED interruption, not a provider failure. The owner said stop (or
            # held the orb again), the prefetch was dropped on purpose, and there is nothing
            # left to say. Filed as `ok` with `interrupted` set, so the report counts it as an
            # interruption rather than as ElevenLabs failing — it was counted as a provider
            # error before this, which put the owner's own Stop in the voice-failure column.
            timeline.emit("tts", ok=True, interrupted=True, silent=True, ms=_ms(started), **trace)
            return Response(status_code=204)
        # The text is not logged; its length is what makes a latency or truncation report
        # readable, and an answer read out in the office does not need repeating to disk.
        log.info("tts declined (%s) for %d chars — tablet falls back", exc.kind, len(spoken))
        timeline.emit("tts", ok=False, failure=exc.kind, ms=_ms(started), **trace)
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "kind": exc.kind,
                "reason": _reason(exc.kind, voice),
            },
        )

    return StreamingResponse(_observed(stream.chunks(), trace, started, prefetched=False), media_type="audio/mpeg", headers=headers)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


async def _observed(chunks: AsyncIterator[bytes], trace: dict, started: float, *, prefetched: bool) -> AsyncIterator[bytes]:
    """The stream as it is, with one `tts` event once it ends: when its first byte left, how
    long the whole took, how many bytes. Off the tablet's path — the bytes go out first."""
    if timeline.current().active is None:
        async for chunk in chunks:
            yield chunk
        return
    first_ms: float | None = None
    total = 0
    try:
        async for chunk in chunks:
            if first_ms is None:
                first_ms = _ms(started)
            total += len(chunk)
            yield chunk
    except BaseException as exc:
        timeline.emit("tts", ok=False, failure="stream_error", error=f"{type(exc).__name__}"[:80], prefetched=prefetched, ms_first_byte=first_ms, ms=_ms(started), bytes=total, **trace)
        raise
    timeline.emit("tts", ok=True, prefetched=prefetched, ms_first_byte=first_ms, ms=_ms(started), bytes=total, **trace)
