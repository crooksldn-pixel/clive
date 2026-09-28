"""decode → recognise → filter hallucinations → trim.

The pipeline's contract is that it never returns text it does not believe. Silence, a decode
failure and a blocklisted artefact all come back as "no speech", because an assistant that
answers a question nobody asked is worse than one that says it did not hear.

And it returns what was SAID. Nothing tells a recogniser which words to expect and nothing
rewrites the words it heard: no keyterms to Scribe, no prompt to Whisper, no fuzzy match onto
the catalogue afterwards. All three were here, and between them "Clive" came out as "Plaid" —
Scribe was handed the catalogue as keyterms and found one of them. Understanding the words is
the model's job, with the tools that can look a product up (the owner's decision of 28
September 2026). What is left after recognition is the one change that alters no word:
surrounding whitespace is trimmed.

Recognition has two engines and one rule: the tablet gets an answer. ElevenLabs Scribe runs
first; whisper.cpp on this Mac catches every way Scribe can fail — no key, no credit, no
network, no response in time — and the speaker never hears about it. The hallucination
blocklist after recognition is engine-independent.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.clients.elevenlabs import ScribeClient, ScribeUnavailable
from app.clients.whisper import Transcript, WhisperClient, WhisperUnavailable
from app.speech.decode import AudioStats, DecodeError, decode
from app.speech.voice_reasons import LISTENING_CREDIT_SPOKEN

log = logging.getLogger("crooks.transcribe")

# Said aloud when the upload could not be turned into audio at all. Fixed, so the voice
# synthesises it once and keeps it.
DECODE_FAILED_REASON = "I could not make out that recording. Try once more."


@dataclass(slots=True)
class SpeechResult:
    ok: bool
    text: str = ""
    raw_text: str = ""
    reason: str = ""  # populated when ok is False
    stats: AudioStats | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    # Which recogniser produced this text: "scribe_v2", "whisper_fallback" or "whisper".
    engine: str = ""
    fallback: bool = False
    engine_detail: str = ""  # why the fallback happened; never contains a credential

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
        client: WhisperClient,
        *,
        scribe: ScribeClient | None = None,
        primary: str = "whisper",
        whisper_enabled: bool = True,
        save_dir: Path | None = None,
        max_saved: int = 200,
    ) -> None:
        self._client = client
        # No Scribe client, or primary set to "whisper", means the local path exactly as it was.
        self._scribe = scribe
        self._primary = "scribe" if (primary == "scribe" and scribe is not None) else "whisper"
        # False on a host where whisper.cpp was never deployed. Rather than let every Scribe
        # failure spend a connect-and-timeout on a port with nothing behind it, the fallback
        # refuses immediately and says why — the caller sees WhisperUnavailable either way,
        # so nothing downstream learns a new shape, it just stops waiting to be told.
        self._whisper_enabled = whisper_enabled
        self._save_dir = save_dir
        self._max_saved = max_saved

    @property
    def primary(self) -> str:
        return self._primary

    async def _whisper(self, wav: bytes) -> Transcript:
        if not self._whisper_enabled:
            raise WhisperUnavailable(
                "local speech recognition is not deployed on this host "
                "(CROOKS_WHISPER_ENABLED=false); there is no fallback behind Scribe here."
            )
        # No initial prompt: a prompt of product names is a list of words to expect, and
        # Whisper finds them whether or not they were said.
        return await self._client.transcribe(wav)

    def _unheard_reason(self, exc: WhisperUnavailable) -> str:
        """What the owner hears when nothing could transcribe. An empty ElevenLabs account is
        said as what it is — and what brings it back — rather than as a broken recogniser."""
        if self._primary == "scribe" and getattr(self._scribe, "failing_kind", "") == "credit":
            return LISTENING_CREDIT_SPOKEN
        return exc.spoken

    async def _recognise(self, wav: bytes, timings: dict[str, float]) -> tuple[Transcript, str, bool, str]:
        """(transcript, engine, fell_back, why). Raises WhisperUnavailable only when the
        fallback is down too — at which point there is genuinely nothing to say."""
        if self._primary == "whisper":
            t = time.perf_counter()
            transcript = await self._whisper(wav)
            timings["whisper"] = _ms(t)
            return transcript, "whisper", False, ""

        t = time.perf_counter()
        try:
            transcript = await self._scribe.transcribe(wav)
            timings["scribe"] = _ms(t)
            return transcript, self._scribe.model, False, ""
        except ScribeUnavailable as exc:
            timings["scribe"] = _ms(t)
            # The kind and the detail are both already scrubbed of the credential.
            log.warning("scribe unavailable (%s), falling back to whisper: %s", exc.kind, exc)
            why = f"{exc.kind}: {exc}"[:200]
        except Exception as exc:  # noqa: BLE001
            # A bug in the Scribe path is still not a reason for the tablet to get an error.
            # Only the type is reported: an unexpected exception's message is not ours to trust.
            timings["scribe"] = _ms(t)
            log.exception("unexpected error from scribe, falling back to whisper")
            why = f"unexpected: {type(exc).__name__}"

        t = time.perf_counter()
        transcript = await self._whisper(wav)
        timings["whisper"] = _ms(t)
        return transcript, "whisper_fallback", True, why

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
        try:
            transcript, engine, fell_back, why = await self._recognise(audio.as_wav(), timings)
        except WhisperUnavailable as exc:
            # Both engines are down. Spoken line for the tablet; the developer detail goes to
            # the log, not the speaker.
            log.error("no recogniser available: %s", exc)
            return SpeechResult(
                ok=False,
                reason=self._unheard_reason(exc),
                stats=audio.stats,
                timings_ms=timings,
                engine="none",
                fallback=self._primary == "scribe",
                engine_detail=str(exc)[:200],
            )
        timings["transcribe"] = _ms(t1)
        log.info(
            "recognised via %s in %.0fms%s", engine, timings["transcribe"],
            " (fallback)" if fell_back else "",
        )

        if transcript.is_hallucination:
            log.info("filtered hallucination (%d chars)", len(transcript.text))
            return SpeechResult(
                ok=False,
                raw_text=transcript.text,
                reason="I did not catch any speech there.",
                stats=audio.stats,
                timings_ms=timings,
                engine=engine,
                fallback=fell_back,
                engine_detail=why,
            )

        # Trimmed and nothing else: every word is the recogniser's, as it heard it.
        return SpeechResult(
            ok=True,
            text=transcript.text.strip(),
            raw_text=transcript.text,
            stats=audio.stats,
            timings_ms=timings,
            engine=engine,
            fallback=fell_back,
            engine_detail=why,
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
