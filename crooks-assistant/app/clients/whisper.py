"""HTTP client for whisper.cpp's `whisper-server`.

The server runs as a separate long-lived process (launchd, M13) so the model stays resident.
Loading a model per request costs seconds and would make the whole product feel broken.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("crooks.whisper")

# Whisper's decoder emits these on silence — artefacts of its training data, not speech. They
# are the single most common way a voice assistant answers a question nobody asked.
HALLUCINATION_BLOCKLIST = frozenset(
    {
        "thank you.", "thank you", "thanks for watching!", "thanks for watching.",
        "you", "you.", "bye.", "bye", ".", "...", "[blank_audio]", "[music]",
        "subtitles by the amara.org community", "subs by www.zberg.net",
        "please subscribe to my channel.", "transcription by castingwords",
        "amara.org", "♪", "[silence]", "(silence)", "so.", "so",
    }
)


def _silence_wav(seconds: float) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return buf.getvalue()


class WhisperUnavailable(RuntimeError):
    """whisper-server is not reachable. A named failure, not a generic 500.

    `spoken` is what the tablet says; `str(exc)` is the developer detail for the log."""

    spoken = "My speech recognition is not running, so I cannot hear you right now."


@dataclass(slots=True)
class Transcript:
    text: str
    ms: float
    model: str = ""

    @property
    def is_hallucination(self) -> bool:
        stripped = self.text.strip().lower()
        return not stripped or stripped in HALLUCINATION_BLOCKLIST


class WhisperClient:
    def __init__(self, base_url: str, *, model: str = "", timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout_s
        # Set to False the first time the server rejects per-request VAD (started without a
        # Silero model). We then rely on our own level gate and hallucination blocklist.
        self._server_vad = True
        # One connection, reused: whisper-server is on this Mac, but a fresh TCP handshake per
        # question is still a round trip the owner waits for.
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    async def transcribe(self, wav: bytes) -> Transcript:
        """POST a 16 kHz mono WAV to /inference and return the transcript.

        No initial prompt is sent. A prompt is a list of words for the decoder to expect, and
        it finds them whether or not they were said (app/speech/transcribe.py)."""
        started = time.perf_counter()
        response = await self._post(wav, vad=self._server_vad)
        if response.status_code == 500 and self._server_vad:
            # A server started without a Silero model answers every VAD request with a bare
            # {"error":"failed to process audio"} — the body never says "vad" (measured). So
            # any 500 while VAD is on gets one retry without it; if that works, remember.
            retry = await self._post(wav, vad=False)
            if retry.status_code == 200:
                log.warning(
                    "whisper-server cannot do per-request VAD (no Silero model?). Continuing "
                    "without it — silence will rely on our level gate and blocklist. Start the "
                    "server with a VAD model to fix this."
                )
                self._server_vad = False
                response = retry

        if response.status_code != 200:
            raise WhisperUnavailable(
                f"whisper-server returned {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise WhisperUnavailable("whisper-server returned something that was not JSON.") from exc
        text = (payload.get("text") or "").strip()
        ms = (time.perf_counter() - started) * 1000
        return Transcript(text=text, ms=ms, model=self.model)

    async def _post(self, wav: bytes, *, vad: bool) -> httpx.Response:
        files = {"file": ("audio.wav", wav, "audio/wav")}
        data = {
            "temperature": "0.0",
            "temperature_inc": "0.2",
            "response_format": "json",
            "no_timestamps": "true",
            # Suppress non-speech tokens ("[MUSIC]", "♪") at the decoder, not just in our blocklist.
            "suppress_nst": "true",
        }
        if vad:
            # VAD is what stops silence becoming "Thank you." The server is started with --vad
            # too; asking per request as well means a mis-started server still filters.
            # Field name verified against examples/server/server.cpp: it is `vad`.
            data["vad"] = "true"
        try:
            return await self._client().post(f"{self.base_url}/inference", files=files, data=data)
        except httpx.ConnectError as exc:
            raise WhisperUnavailable(
                f"whisper-server is not running at {self.base_url}. Start it with "
                "`make whisper-server`."
            ) from exc
        except httpx.TimeoutException as exc:
            raise WhisperUnavailable("whisper-server did not respond in time.") from exc
        except httpx.HTTPError as exc:
            # Includes a server that died mid-request (RemoteProtocolError) — still our problem
            # to name, not a 500 to raise.
            raise WhisperUnavailable(f"whisper-server request failed: {type(exc).__name__}") from exc

    async def health(self) -> tuple[bool, str]:
        """Transcribe half a second of silence. "The port answers" is not health; "a request
        goes through the whole inference path" is."""
        try:
            response = await self._client().get(f"{self.base_url}/", timeout=3.0)
            if response.status_code >= 500:
                return False, f"whisper-server at {self.base_url} answered {response.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"whisper-server unreachable at {self.base_url}: {exc}"
        try:
            await self.transcribe(_silence_wav(0.5))
        except WhisperUnavailable as exc:
            return False, f"whisper-server is up but inference fails: {exc}"
        vad = "server VAD" if self._server_vad else "NO server VAD (start it with a Silero model)"
        return True, f"whisper-server at {self.base_url}, inference ok, {vad}"
