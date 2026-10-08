"""decode → recognise → filter hallucinations → trim.

The pipeline's contract is that it never returns text it does not believe. Silence, a decode
failure and a blocklisted artefact all come back as "no speech", because an assistant that
answers a question nobody asked is worse than one that says it did not hear.

And it returns what was SAID. Nothing tells the recogniser which words to expect and nothing
rewrites the words it heard: no keyterms to Scribe, no prompt to a local model, no fuzzy match
onto the catalogue afterwards. All three were here, and between them "Clive" came out as "Plaid" —
Scribe was handed the catalogue as keyterms and found one of them. Understanding the words is
the model's job, with the tools that can look a product up (the owner's decision of 28
September 2026). What is left after recognition is the one change that alters no word:
surrounding whitespace is trimmed.

Recognition is ElevenLabs Scribe and nothing else (DEC-022: no local speech fallback on the
server). The local whisper.cpp fallback the Mac had was deleted on the owner's ruling of 8
October (DEC-071, ruling 39). Every way Scribe can fail — no key, no credit, no network, no
response in time — ends in one spoken sentence saying the owner cannot be heard, or, for an
empty account, what brings it back; the reason goes to the log and the turn's record, never to
the speaker. The hallucination blocklist after recognition (app/speech/heard.py) stays.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.clients.elevenlabs import ScribeClient, ScribeUnavailable
from app.speech.decode import AudioStats, DecodeError, decode
from app.speech.heard import Transcript
from app.speech.voice_reasons import LISTENING_CREDIT_SPOKEN

log = logging.getLogger("crooks.transcribe")

# Said aloud when the upload could not be turned into audio at all. Fixed, so the voice
# synthesises it once and keeps it.
DECODE_FAILED_REASON = "I could not make out that recording. Try once more."
# Said aloud when Scribe could not hear the recording for any reason but an empty account. The
# words production has always spoken in that case, unchanged by the fallback's going.
UNHEARD_REASON = "My speech recognition is not running, so I cannot hear you right now."


@dataclass(slots=True)
class SpeechResult:
    ok: bool
    text: str = ""
    raw_text: str = ""
    reason: str = ""  # populated when ok is False
    stats: AudioStats | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    # Which recogniser produced this text: Scribe's model ("scribe_v2"), or "none" when it
    # could not hear the recording.
    engine: str = ""
    # Whether another engine took the turn. There is no other engine since the local fallback
    # was deleted (DEC-071, ruling 39), so it is always False; it stays because the turn's
    # record carries it (app/routes/turn.py) and readers of older records find it there.
    fallback: bool = False
    engine_detail: str = ""  # why Scribe could not hear; never contains a credential

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "text": self.text,
            "raw_text": self.raw_text,
            "reason": self.reason,
            "stats": self.stats.as_dict() if self.stats else None,
            "engine": self.engine,
            "fallback": self.fallback,
            "engine_detail": self.engine_detail,
            "timings_ms": {k: round(v, 1) for k, v in self.timings_ms.items()},
        }


class Transcriber:
    def __init__(
        self,
        scribe: ScribeClient,
        *,
        save_dir: Path | None = None,
        max_saved: int = 200,
    ) -> None:
        self._scribe = scribe
        self._save_dir = save_dir
        self._max_saved = max_saved

    def _unheard_reason(self) -> str:
        """What the owner hears when Scribe could not transcribe. An empty ElevenLabs account is
        said as what it is — and what brings it back — rather than as a broken recogniser."""
        if getattr(self._scribe, "failing_kind", "") == "credit":
            return LISTENING_CREDIT_SPOKEN
        return UNHEARD_REASON

    async def _recognise(self, wav: bytes, timings: dict[str, float]) -> tuple[Transcript | None, str]:
        """(transcript, why). The transcript is None when Scribe could not hear the recording,
        and `why` then says what went wrong, already scrubbed of the credential."""
        t = time.perf_counter()
        try:
            transcript = await self._scribe.transcribe(wav)
            timings["scribe"] = _ms(t)
            return transcript, ""
        except ScribeUnavailable as exc:
            timings["scribe"] = _ms(t)
            # The kind and the detail are both already scrubbed of the credential.
            log.warning("scribe unavailable (%s): %s", exc.kind, exc)
            return None, f"{exc.kind}: {exc}"[:200]
        except Exception as exc:  # noqa: BLE001
            # A bug in the Scribe path is still not a reason for the tablet to get an error.
            # Only the type is reported: an unexpected exception's message is not ours to trust.
            timings["scribe"] = _ms(t)
            log.exception("unexpected error from scribe")
            return None, f"unexpected: {type(exc).__name__}"

    async def from_blob(self, blob: bytes, *, filename_hint: str = "") -> SpeechResult:
        timings: dict[str, float] = {}

        save_to = None
        if self._save_dir is not None:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            suffix = Path(filename_hint).suffix or ".webm"
            save_to = self._save_dir / f"{stamp}{suffix}"

        t0 = time.perf_counter()
        try:
            # PyAV decoding is CPU work; off the event loop so the tablet's /state polls and
            # the health check keep answering while a long recording is unpacked.
            audio = await asyncio.to_thread(decode, blob, save_to=save_to)
        except DecodeError as exc:
            # The owner hears one fixed sentence; the decoder's own words go to the log,
            # where they are useful and where they cost nothing to keep.
            log.warning("could not decode the recording: %s", exc)
            return SpeechResult(
                ok=False, reason=DECODE_FAILED_REASON, engine_detail=str(exc)[:200],
                timings_ms={"decode": _ms(t0)},
            )
        timings["decode"] = _ms(t0)
        if save_to is not None:
            prune_captures(self._save_dir, self._max_saved)

        if not audio.stats.usable:
            if audio.stats.duration_s < 0.3:
                reason = "That was too short — hold the button while you speak."
            elif audio.stats.clipped:
                # Sustained clipping, not a single full-scale sample: a peak is a knock on the
                # desk, and refusing to transcribe those threw away good recordings.
                reason = "That came through distorted — a bit further from the microphone."
            else:
                reason = "I could not hear that clearly — a bit closer to the microphone."
            log.info(
                "rejected audio: %s (%.2fs, %.1f dBFS RMS, %.2f%% clipped)",
                reason, audio.stats.duration_s, audio.stats.rms_dbfs,
                100 * audio.stats.clipped_ratio,
            )
            return SpeechResult(ok=False, reason=reason, stats=audio.stats, timings_ms=timings)

        t1 = time.perf_counter()
        transcript, why = await self._recognise(audio.as_wav(), timings)
        if transcript is None:
            # Nothing heard it. Spoken line for the tablet; the developer detail goes to the
            # log and the record, not the speaker.
            log.error("no recogniser available: %s", why)
            return SpeechResult(
                ok=False,
                reason=self._unheard_reason(),
                stats=audio.stats,
                timings_ms=timings,
                engine="none",
                engine_detail=why,
            )
        engine = self._scribe.model
        timings["transcribe"] = _ms(t1)
        log.info("recognised via %s in %.0fms", engine, timings["transcribe"])

        if transcript.is_hallucination:
            log.info("filtered hallucination (%d chars)", len(transcript.text))
            return SpeechResult(
                ok=False,
                raw_text=transcript.text,
                reason="I did not catch any speech there.",
                stats=audio.stats,
                timings_ms=timings,
                engine=engine,
            )

        # Trimmed and nothing else: every word is the recogniser's, as it heard it.
        return SpeechResult(
            ok=True,
            text=transcript.text.strip(),
            raw_text=transcript.text,
            stats=audio.stats,
            timings_ms=timings,
            engine=engine,
        )


def prune_captures(directory: Path | None, keep: int) -> int:
    """Keep the newest `keep` recordings. These are recordings of an office; the benchmark
    corpus needs a few dozen, not a year of them. Returns how many were removed."""
    if directory is None or keep <= 0 or not directory.exists():
        return 0
    files = sorted(
        (p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
    )
    removed = 0
    for path in files[: max(0, len(files) - keep)]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _ms(since: float) -> float:
    return (time.perf_counter() - since) * 1000
