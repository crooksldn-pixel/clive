"""Opus/WebM from the tablet's MediaRecorder to 16 kHz mono PCM for the recogniser.

Chrome on Android picks its own container, so nothing here assumes what arrived — PyAV probes
the actual bytes. The stats returned are the M2 success test: if RMS sits on the noise floor,
that is a hardware finding about the tablet, not a bug to code around.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from dataclasses import dataclass, field
from pathlib import Path

TARGET_RATE = 16_000
TARGET_CHANNELS = 1

# A sample this close to full scale is sitting on the rail. Not 1.0: Opus is lossy, so a
# clipped signal comes back oscillating around the limit rather than exactly at it.
CLIP_LEVEL = 0.99
# Reject only when the rail is where the recording LIVES. Measured over 98 real tablet
# captures: 34 of them touched full scale — a third of everything the tablet ever recorded —
# and the very worst spent 0.27% of its samples there, about six milliseconds. All were
# perfectly intelligible. Deliberately clipped audio measures 20–50% by the same count, so
# 2% sits an order of magnitude clear of real speech and well below real distortion. A peak
# is a moment; distortion is a proportion.
CLIPPED_RATIO_LIMIT = 0.02


class DecodeError(RuntimeError):
    """The uploaded blob could not be decoded to audio."""


@dataclass(slots=True)
class AudioStats:
    duration_s: float
    sample_rate: int
    channels: int
    peak: float  # 0.0–1.0
    rms: float  # 0.0–1.0
    bytes_in: int
    samples: int
    container: str = ""
    codec: str = ""
    clipped_samples: int = 0  # samples at or above CLIP_LEVEL of full scale

    @property
    def clipped_ratio(self) -> float:
        """The share of the recording spent on the rail. This, not `peak`, is distortion."""
        return self.clipped_samples / self.samples if self.samples else 0.0

    @property
    def clipped_ms(self) -> float:
        return 1000 * self.clipped_samples / self.sample_rate if self.sample_rate else 0.0

    @property
    def clipped(self) -> bool:
        """Distorted enough that transcribing it is not worth attempting."""
        return self.clipped_ratio >= CLIPPED_RATIO_LIMIT

    @property
    def peak_dbfs(self) -> float:
        return 20 * math.log10(self.peak) if self.peak > 0 else -120.0

    @property
    def rms_dbfs(self) -> float:
        return 20 * math.log10(self.rms) if self.rms > 0 else -120.0

    @property
    def usable(self) -> bool:
        """A rough gate for "did the microphone actually hear a person".

        `peak` is deliberately not part of this. One transient at full scale — a knock on the
        desk, a plosive, a chair — says nothing about whether the speech is intelligible, and
        rejecting on it threw away a third of all real recordings. A mildly clipped recording
        is sent to the recogniser; a recording that is mostly rail is not."""
        return self.duration_s >= 0.3 and self.rms_dbfs > -50 and not self.clipped

    def as_dict(self) -> dict:
        return {
            "duration_s": round(self.duration_s, 3),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "peak": round(self.peak, 4),
            "rms": round(self.rms, 4),
            "peak_dbfs": round(self.peak_dbfs, 1),
            "rms_dbfs": round(self.rms_dbfs, 1),
            # Why a recording was called distorted, in a form that can be argued with.
            "clipped_samples": self.clipped_samples,
            "clipped_ratio": round(self.clipped_ratio, 5),
            "clipped_ms": round(self.clipped_ms, 1),
            "bytes_in": self.bytes_in,
            "samples": self.samples,
            "container": self.container,
            "codec": self.codec,
            "usable": self.usable,
        }


@dataclass(slots=True)
class Decoded:
    pcm: bytes  # 16-bit signed little-endian mono @ 16 kHz
    stats: AudioStats
    saved_to: Path | None = field(default=None)

    def as_wav(self) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(TARGET_CHANNELS)
            w.setsampwidth(2)
            w.setframerate(TARGET_RATE)
            w.writeframes(self.pcm)
        return buf.getvalue()

    def samples_f32(self) -> list[float]:
        count = len(self.pcm) // 2
        return [s / 32768.0 for s in struct.unpack(f"<{count}h", self.pcm[: count * 2])]


def decode(blob: bytes, *, save_to: Path | None = None) -> Decoded:
    """Decode an uploaded recording to 16 kHz mono PCM. Raises DecodeError on anything unusable."""
    if not blob:
        raise DecodeError("Empty upload — the recorder produced no audio.")

    if save_to is not None:
        save_to.parent.mkdir(parents=True, exist_ok=True)
        save_to.write_bytes(blob)

    try:
        import av
    except ImportError as exc:  # pragma: no cover - environment problem, not a runtime one
        raise DecodeError("PyAV is not installed; cannot decode audio.") from exc

    try:
        container = av.open(io.BytesIO(blob))
    except Exception as exc:
        raise DecodeError(
            f"Could not open the recording ({exc}). Log the MediaRecorder mimeType — Chrome may "
            "have chosen a container we are not handling."
        ) from exc

    try:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise DecodeError("The upload contains no audio stream.")
        codec_name = getattr(stream.codec_context, "name", "") or ""
        format_name = getattr(container.format, "name", "") or ""

        resampler = av.audio.resampler.AudioResampler(
            format="s16", layout="mono", rate=TARGET_RATE
        )
        chunks: list[bytes] = []
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                chunks.append(bytes(resampled.planes[0])[: resampled.samples * 2])
        for resampled in resampler.resample(None):  # flush
            chunks.append(bytes(resampled.planes[0])[: resampled.samples * 2])
    finally:
        container.close()

    pcm = b"".join(chunks)
    if not pcm:
        raise DecodeError("Decoded to zero samples — the recording is empty.")

    stats = _stats(pcm, bytes_in=len(blob), container=format_name, codec=codec_name)
    return Decoded(pcm=pcm, stats=stats, saved_to=save_to)


def _stats(pcm: bytes, *, bytes_in: int, container: str = "", codec: str = "") -> AudioStats:
    count = len(pcm) // 2
    samples = struct.unpack(f"<{count}h", pcm[: count * 2])
    peak = max((abs(s) for s in samples), default=0) / 32768.0
    rms = math.sqrt(sum(s * s for s in samples) / count) / 32768.0 if count else 0.0
    rail = int(32767 * CLIP_LEVEL)
    clipped = sum(1 for s in samples if s >= rail or s <= -rail)
    return AudioStats(
        duration_s=count / TARGET_RATE,
        sample_rate=TARGET_RATE,
        channels=TARGET_CHANNELS,
        peak=peak,
        rms=rms,
        bytes_in=bytes_in,
        samples=count,
        container=container,
        codec=codec,
        clipped_samples=clipped,
    )


def read_wav(path: Path) -> Decoded:
    """Load an already-decoded 16 kHz mono WAV. Used by the benchmark harness."""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != TARGET_CHANNELS or w.getframerate() != TARGET_RATE:
            raise DecodeError(f"{path} is not 16 kHz mono.")
        pcm = w.readframes(w.getnframes())
    return Decoded(pcm=pcm, stats=_stats(pcm, bytes_in=path.stat().st_size, container="wav"))
