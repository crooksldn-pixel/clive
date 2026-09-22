"""decode → recognise → filter hallucinations → normalise CROOKS terminology.

The pipeline's contract is that it never returns text it does not believe. Silence, a decode
failure and a blocklisted artefact all come back as "no speech", because an assistant that
answers a question nobody asked is worse than one that says it did not hear.

Recognition has two engines and one rule: the tablet gets an answer. ElevenLabs Scribe runs
first because it hears this business better; whisper.cpp on this Mac catches every way Scribe
can fail — no key, no credit, no network, no response in time — and the speaker never hears
about it. Everything after recognition (hallucination blocklist, CROOKS normalisation, order
numbers, ambiguity) is engine-independent and runs exactly as it did before.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.clients.elevenlabs import ScribeClient, ScribeUnavailable
from app.clients.whisper import Transcript, WhisperClient, WhisperUnavailable
from app.speech.decode import AudioStats, DecodeError, decode
from app.speech.normalise import Normalised, Normaliser

log = logging.getLogger("crooks.transcribe")

# Whisper accepts an initial prompt to bias decoding. It is truncated from the FRONT at 224
# tokens, so the most important terms go LAST. It must be a bare comma-separated list — prose
# here bleeds into the transcript, which looks like a hallucination and is not one.
# Whisper keeps roughly the last 224 tokens of the prompt; ~900 characters of short product
# names lands under that. Counting characters rather than terms keeps a long live catalogue from
# pushing the hand-written aliases out.
PROMPT_MAX_CHARS = 900


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
    normalised: Normalised | None = None
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
            "matches": [
                {"heard": m.heard, "became": m.replaced_with, "score": m.score, "via": m.via}
                for m in (self.normalised.matches if self.normalised else [])
            ],
            "order_numbers": self.normalised.order_numbers if self.normalised else [],
            "engine": self.engine,
            "fallback": self.fallback,
            "engine_detail": self.engine_detail,
            "timings_ms": {k: round(v, 1) for k, v in self.timings_ms.items()},
        }


def build_prompt(terms: list[str]) -> str:
    """A comma-separated term list ending in a full stop, most important LAST because
    truncation eats the front.

    Whisper imitates the prompt's style. A bare lower-case list produced transcripts with no
    capitals and no punctuation; the same list in display case ending with a period restored
    both. Symbols are dropped because '★' teaches the model nothing about how a word sounds."""
    cleaned = [re.sub(r"[^A-Za-z0-9' ]+", " ", t).strip() for t in terms]
    cleaned = [" ".join(t.split()) for t in cleaned if t and t.strip()]
    cleaned = list(dict.fromkeys(cleaned))
    if not cleaned:
        return ""
    kept: list[str] = []
    length = 0
    for term in reversed(cleaned):  # last terms are the most important; keep from the end
        if length + len(term) + 2 > PROMPT_MAX_CHARS:
            break
        kept.append(term)
        length += len(term) + 2
    return ", ".join(reversed(kept)) + "."


class Transcriber:
    def __init__(
        self,
        client: WhisperClient,
        normaliser: Normaliser,
        *,
        scribe: ScribeClient | None = None,
        primary: str = "whisper",
        whisper_enabled: bool = True,
        keyterms: bool = True,
        save_dir: Path | None = None,
        max_saved: int = 200,
    ) -> None:
        self._client = client
        self._normaliser = normaliser
        # No Scribe client, or primary set to "whisper", means the local path exactly as it was.
        self._scribe = scribe
        self._primary = "scribe" if (primary == "scribe" and scribe is not None) else "whisper"
        # False on a host where whisper.cpp was never deployed. Rather than let every Scribe
        # failure spend a connect-and-timeout on a port with nothing behind it, the fallback
        # refuses immediately and says why — the caller sees WhisperUnavailable either way,
        # so nothing downstream learns a new shape, it just stops waiting to be told.
        self._whisper_enabled = whisper_enabled
        self._keyterms = keyterms
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
        return await self._client.transcribe(
            wav, prompt=build_prompt(self._normaliser.catalogue.prompt_terms())
        )

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
            # external_terms(), not prompt_terms(): customer names bias Whisper on this Mac but
            # are never sent to ElevenLabs.
            terms = self._normaliser.catalogue.external_terms() if self._keyterms else []
            transcript = await self._scribe.transcribe(wav, keyterms=terms)
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
                reason=exc.spoken,
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

        t2 = time.perf_counter()
        normalised = self._normaliser.normalise(transcript.text)
        timings["normalise"] = _ms(t2)
        if normalised.changed:
            # Counts, not words: what the owner says about customers is not for the log.
            log.info("normalised the transcript (%d chars -> %d)", len(normalised.raw), len(normalised.text))

        return SpeechResult(
            ok=True,
            text=normalised.text,
            raw_text=transcript.text,
            stats=audio.stats,
            normalised=normalised,
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
