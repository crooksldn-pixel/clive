"""HTTP client for ElevenLabs text-to-speech — the assistant's voice.

The sibling module (elevenlabs.py) turns the owner's speech into text; this one turns the
answer back into speech. Same account, same credential, same two rules:

- Nothing here may leak the credential. The key is read through the Keychain wrapper, held in
  memory only, sent in one header, and every message this module produces goes through
  _scrub(). It is never handed to the tablet, so web/app.js has no way to leak it either.
- Nothing here may cost the owner an answer. Speech is an output layer: every failure is one
  named VoiceUnavailable, /speak turns that into a 503, and the tablet falls back to the
  Android voice it used before. A silent tablet is a bug; a broken turn is a worse one.

The MP3 is streamed out of ElevenLabs and through FastAPI as it arrives rather than being
buffered here, so the first bytes leave the Mac before the last ones have been generated.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.clients.elevenlabs_account import AccountCredit
from app.secrets import keychain
from app.speech.voice_reasons import voice_reason

log = logging.getLogger("crooks.voice")

API_BASE = "https://api.elevenlabs.io/v1"

# The same shapes of failure that make Scribe stand down: a key that will not be accepted and
# an account with nothing left in it do not recover between two sentences, and retrying them
# on every answer costs the owner a pause before the Android voice starts.
STICKY_KINDS = frozenset({"no_key", "rejected", "forbidden", "credit"})


class VoiceUnavailable(RuntimeError):
    """ElevenLabs cannot speak this answer. The tablet falls back to its own voice.

    `kind` is the machine-readable shape of the failure (timeout, rejected, credit, …); it is
    what gets logged and reported. str(exc) is the human detail, already scrubbed."""

    def __init__(self, detail: str, *, kind: str) -> None:
        super().__init__(detail)
        self.kind = kind


class VoiceStream:
    """An MP3 arriving from ElevenLabs, forwarded chunk by chunk.

    Constructed only after the response headers have come back 200, so the caller already knows
    the request succeeded before it commits to an audio/mpeg response with no way back."""

    def __init__(self, client: VoiceClient, response: httpx.Response, started: float) -> None:
        self._client = client
        self._response = response
        self._started = started
        self.bytes_out = 0
        self.truncated = False

    async def chunks(self) -> AsyncIterator[bytes]:
        truncated = ""
        try:
            async for chunk in self._response.aiter_bytes():
                if chunk:
                    self.bytes_out += len(chunk)
                    yield chunk
        except httpx.HTTPError as exc:
            # The tablet already has the opening of the sentence and is playing it; there is
            # no status code left to change. Say so in the log, which is where it is findable.
            truncated = f" TRUNCATED after {type(exc).__name__}"
            self.truncated = True
        finally:
            await self.aclose()
            self._client._finish(self, truncated)

    async def aclose(self) -> None:
        # The response only: the connection belongs to the client and is reused.
        await self._response.aclose()

    @property
    def ms(self) -> float:
        return (time.perf_counter() - self._started) * 1000


class Prefetched:
    """An answer being synthesised ahead of the request for it.

    Holds every chunk received so far and wakes anyone following it when the next arrives, so
    /speak can start sending the opening of the sentence while ElevenLabs is still generating
    the end of it — the point of prefetching is to move the start earlier, not to wait for the
    whole file. Handed out once, unless pinned: a fixed line ("I did not catch that") is kept
    for the life of the process and costs nothing the second time."""

    def __init__(self, *, pinned: bool = False) -> None:
        self.chunks: list[bytes] = []
        self.done = False
        self.error: VoiceUnavailable | None = None
        self.pinned = pinned
        self.at = time.time()
        self._cond = asyncio.Condition()

    async def push(self, chunk: bytes) -> None:
        async with self._cond:
            self.chunks.append(chunk)
            self._cond.notify_all()

    async def finish(self, error: VoiceUnavailable | None = None) -> None:
        async with self._cond:
            self.done = True
            self.error = error
            self._cond.notify_all()

    async def wait_first(self) -> None:
        """Until the first chunk exists or the stream has ended — so a caller can tell an
        answer that is coming from one that failed before it started."""
        async with self._cond:
            while not self.chunks and not self.done:
                await self._cond.wait()

    async def follow(self) -> AsyncIterator[bytes]:
        """Everything received so far, then the rest as it arrives."""
        index = 0
        while True:
            async with self._cond:
                while index >= len(self.chunks) and not self.done:
                    await self._cond.wait()
                if index >= len(self.chunks):
                    return
                chunk = self.chunks[index]
                index += 1
            yield chunk

    @property
    def size(self) -> int:
        return sum(len(c) for c in self.chunks)


class VoiceClient:
    def __init__(
        self,
        *,
        voice_id: str,
        voice_name: str = "",
        model: str = "eleven_flash_v2_5",
        output_format: str = "mp3_44100_128",
        timeout_s: float = 20.0,
        base_url: str = API_BASE,
        max_chars: int = 1200,
        cooldown_s: float = 300.0,
        enabled: bool = True,
        max_per_minute: int = 30,
        account: AccountCredit | None = None,
    ) -> None:
        self.voice_id = voice_id
        self.voice_name = voice_name or voice_id
        # What the owner asked the voice to sound like (app/speech/voice_prefs.py). Empty means
        # "say nothing and let ElevenLabs apply the voice's own defaults", which is what this
        # client always did and what a fresh install still does.
        self.voice_settings: dict[str, Any] = {}
        self.model = model
        self.output_format = output_format
        self.base_url = base_url.rstrip("/")
        self.max_chars = max_chars
        self.enabled = enabled
        self._timeout = timeout_s
        self._cooldown_s = cooldown_s
        self._key: str | None = None
        self._cooldown_until = 0.0
        # A ceiling on requests per minute. One conversation makes a handful; a loop against
        # the port — or a bug — would otherwise spend the account's credit in minutes.
        self.max_per_minute = max_per_minute
        self._recent: list[float] = []
        # One HTTPS connection, reused: the handshake is a good part of the wait before an
        # answer is heard, and it was being paid on every sentence.
        self._http: httpx.AsyncClient | None = None
        self._voice_checked_at: float = 0.0
        self._voice_actual_name: str | None = None
        # What the account last said about its own credit. Shared with Scribe when the runtime
        # builds both: Scribe is the one that probes the account, and this client will not —
        # a health check that synthesises a sentence on every poll is a bill, not a check.
        self.account = account or AccountCredit()
        # Answers synthesised ahead of the tablet asking for them — see prefetch(). Keyed by
        # the spoken text; a handful of entries, a couple of minutes, in memory only.
        self._ready: dict[str, Prefetched] = {}
        self._inflight: dict[str, asyncio.Task] = {}
        self.prefetch_enabled = True
        self.prefetches = 0
        self.prefetch_hits = 0
        # Non-sensitive diagnostics for /health. Never the text that was spoken.
        self.attempts = 0
        self.successes = 0
        self.failures = 0
        self.last_error: str = ""
        self.last_error_kind: str = ""
        self.last_ms: float = 0.0
        self.last_bytes: int = 0
        # The latest attempt failed and nothing has succeeded since. Health reads this, not
        # the cooldown alone: a voice that failed its last sentence is not "ok".
        self.failing = False

    # ------------------------------------------------------------------ connection

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        for task in list(self._inflight.values()):
            task.cancel()
        self._inflight.clear()
        self._ready.clear()
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    # ------------------------------------------------------------------ credential

    def _api_key(self) -> str:
        """The key, from the Keychain, cached in memory once found. A *missing* key is not
        cached, so storing it later starts working without a restart."""
        if not self._key:
            self._key = keychain.get_optional("elevenlabs_api_key") or ""
        if not self._key:
            raise VoiceUnavailable(
                "no elevenlabs_api_key in the Keychain "
                "(store it with: python scripts/set_secrets.py elevenlabs_api_key)",
                kind="no_key",
            )
        return self._key

    def _scrub(self, text: str) -> str:
        """Last line of defence: no message this module emits may contain the credential."""
        key = self._key
        if key and len(key) >= 8 and key in text:
            text = text.replace(key, "[redacted]")
        return text

    def forget_key(self) -> None:
        self._key = None

    # ------------------------------------------------------------------ cooldown

    @property
    def cooling_down(self) -> bool:
        return time.time() < self._cooldown_until

    @property
    def cooldown_remaining_s(self) -> float:
        return max(0.0, self._cooldown_until - time.time())

    def clear_cooldown(self) -> None:
        self._cooldown_until = 0.0

    def _record_failure(self, exc: VoiceUnavailable) -> VoiceUnavailable:
        self.failures += 1
        self.failing = True
        self.last_error_kind = exc.kind
        self.last_error = self._scrub(str(exc))[:200]
        if exc.kind == "credit":
            # The account, not the product: Scribe is on the same plan and the same key.
            self.account.observe(exhausted=True, source="an answer was refused for credit")
        if exc.kind in STICKY_KINDS and self._cooldown_s > 0:
            self._cooldown_until = time.time() + self._cooldown_s
            if exc.kind in {"rejected", "forbidden"}:
                self.forget_key()  # the stored key may have been replaced since we read it
        log.warning(
            "tts unavailable (%s): %s — the tablet will use its own voice", exc.kind,
            self.last_error,
        )
        return exc

    def _finish(self, stream: VoiceStream, truncated: str) -> None:
        self.last_ms = stream.ms
        self.last_bytes = stream.bytes_out
        if truncated or not stream.bytes_out:
            self.failures += 1
            self.failing = True
            self.last_error_kind = "truncated" if truncated else "empty"
            self.last_error = (truncated or "ElevenLabs sent no audio").strip()
            log.warning(
                "tts %s · %s · %s · %.0fms · %d bytes%s", self.last_error_kind, self.voice_name,
                self.model, stream.ms, stream.bytes_out, truncated,
            )
            return
        self.successes += 1
        self.failing = False
        self.clear_cooldown()
        # It spoke, so the account has credit: newer evidence than any earlier emptiness.
        self.account.observe(exhausted=False, source="an answer was spoken")
        log.info(
            "tts ok · %s · %s · %s · %.0fms · %d bytes", self.voice_name, self.model,
            self.output_format, stream.ms, stream.bytes_out,
        )

    # ------------------------------------------------------------------ request

    def _payload(self, text: str) -> dict:
        """The request body. Voice settings are sent only when the owner has set some: saying
        nothing is how ElevenLabs is asked for the voice's own defaults, and that is still what
        an untouched install does (app/speech/voice_prefs.py)."""
        body: dict[str, Any] = {"text": text, "model_id": self.model}
        if self.voice_settings:
            body["voice_settings"] = dict(self.voice_settings)
        return body

    def apply(self, *, voice_id: str = "", voice_name: str = "", model: str = "",
              voice_settings: dict[str, Any] | None = None) -> None:
        """Speak as this voice from the next answer on, with no restart. Changing the voice clears
        the remembered name ElevenLabs gave for the old id, so /health verifies the new one at its
        next look rather than reporting a mismatch against the voice that is gone."""
        changed_voice = bool(voice_id) and voice_id != self.voice_id
        if voice_id:
            self.voice_id = voice_id
        if voice_name:
            self.voice_name = voice_name
        elif changed_voice:
            self.voice_name = voice_id
        if model:
            self.model = model
        if voice_settings is not None:
            self.voice_settings = dict(voice_settings)
        if changed_voice:
            self._voice_checked_at = 0.0
            self._voice_actual_name = None

    def _url(self, *, stream: bool) -> str:
        path = f"/text-to-speech/{self.voice_id}" + ("/stream" if stream else "")
        return f"{self.base_url}{path}?output_format={self.output_format}"

    def _guard(self, text: str) -> str:
        if not self.enabled:
            raise VoiceUnavailable("ElevenLabs speech is switched off in settings", kind="off")
        text = (text or "").strip()
        if not text:
            raise VoiceUnavailable("nothing to say", kind="empty_text")
        if self.cooling_down:
            raise VoiceUnavailable(
                f"skipped: cooling down for {self.cooldown_remaining_s:.0f}s after "
                f"{self.last_error_kind or 'a failure'}",
                kind="cooldown",
            )
        now = time.time()
        self._recent = [t for t in self._recent if now - t < 60.0]
        if self.max_per_minute and len(self._recent) >= self.max_per_minute:
            raise VoiceUnavailable(
                f"more than {self.max_per_minute} requests in a minute; refusing to spend more",
                kind="rate",
            )
        self._recent.append(now)
        return text[: self.max_chars]

    async def open_stream(self, text: str) -> VoiceStream:
        """Start the request and return once the headers say it worked.

        Splitting the handshake from the body is the whole point: a 401 or an exhausted account
        is discovered here, while a JSON error response is still possible, rather than halfway
        through an audio/mpeg body the tablet is already playing."""
        text = self._guard(text)
        key = self._api_key()
        self.attempts += 1
        started = time.perf_counter()
        http = self._client()
        request = http.build_request(
            "POST",
            self._url(stream=True),
            headers={"xi-api-key": key, "accept": "audio/mpeg"},
            json=self._payload(text),
        )
        try:
            response = await http.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise self._record_failure(
                VoiceUnavailable(f"no response in {self._timeout:.0f}s", kind="timeout")
            ) from exc
        except httpx.HTTPError as exc:
            raise self._record_failure(
                VoiceUnavailable(f"request failed: {type(exc).__name__}", kind="network")
            ) from exc

        if response.status_code != 200:
            body = ""
            try:
                body = (await response.aread()).decode("utf-8", "replace")
            except httpx.HTTPError:
                pass
            finally:
                await response.aclose()
            raise self._record_failure(self._http_failure(response.status_code, body))
        return VoiceStream(self, response, started)

    # ------------------------------------------------------------------ prefetch

    # How long a synthesised answer waits to be asked for. The tablet asks within a second;
    # anything older is an answer that was interrupted, and is dropped rather than kept.
    READY_TTL_S = 120.0
    READY_MAX = 4
    PINNED_MAX = 24
    FIRST_BYTE_S = 4.0   # how long /speak waits for a prefetch's first byte

    def prefetch(self, text: str, *, pin: bool = False) -> bool:
        """Start synthesising an answer now, before the tablet asks for it.

        /turn knows the answer a round trip before /speak arrives; starting ElevenLabs on it
        then means the audio is generating while the JSON crosses the tailnet and the tablet
        renders. The tablet only says `speak` when it will actually ask, so this is the same
        single request, earlier — never an extra one. `pin` keeps a fixed line for good.
        Returns True when the answer is, or is about to be, ready."""
        if not self.enabled or not self.prefetch_enabled or self.cooling_down or not text:
            return False
        if self.max_chars and len(text) > self.max_chars:
            text = text[: self.max_chars]
        existing = self._ready.get(text)
        if existing is not None and (not existing.done or existing.error is None):
            return True   # in flight, or ready (pinned or not); nothing to do
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        self._expire_ready()
        entry = Prefetched(pinned=pin)
        self._ready[text] = entry
        self.prefetches += 1
        task = loop.create_task(self._fetch_into(text, entry))
        # A task cancelled before it ever ran executes none of its own cleanup; this does it.
        task.add_done_callback(lambda done, e=entry, t=text: self._settle(e, t))
        self._inflight[text] = task
        return True

    def _settle(self, entry: Prefetched, text: str) -> None:
        self._inflight.pop(text, None)
        if not entry.done:
            entry.pinned = False
            try:
                asyncio.get_running_loop().create_task(
                    entry.finish(VoiceUnavailable("cancelled", kind="cancelled"))
                )
            except RuntimeError:
                pass

    async def _fetch_into(self, text: str, entry: Prefetched) -> None:
        # However this ends — audio, a named failure, a cancellation that lands before the
        # request has even been sent — the entry is finished and the in-flight record dropped.
        # An entry left waiting forever is a /speak that hangs forever.
        stream = None
        try:
            stream = await self.open_stream(text)
            async for chunk in stream.chunks():
                await entry.push(chunk)
            if getattr(stream, "truncated", False):
                # Half a sentence is not a line worth keeping; a pinned line that was cut
                # would otherwise be replayed cut for the life of the process.
                entry.pinned = False
        except VoiceUnavailable as exc:
            # Remembered, so /speak reports the shape of the failure at once rather than
            # paying the same timeout a second time. A failed line is never kept: the next
            # time it is needed it is tried again, whether or not it was meant to be pinned.
            entry.pinned = False
            await entry.finish(exc)
        except asyncio.CancelledError:
            entry.pinned = False
            if stream is not None:
                await stream.aclose()
            await entry.finish(VoiceUnavailable("cancelled", kind="cancelled"))
            raise
        except Exception:  # noqa: BLE001 — a prefetch must never take the loop down
            log.exception("tts prefetch failed unexpectedly")
            entry.pinned = False
            await entry.finish(VoiceUnavailable("prefetch failed", kind="prefetch"))
        finally:
            self._inflight.pop(text, None)
            if not entry.chunks:
                entry.pinned = False   # nothing worth keeping
            if not entry.done:
                await entry.finish()

    def _expire_ready(self) -> None:
        now = time.time()
        unpinned = [k for k, e in self._ready.items() if not e.pinned]
        for key in unpinned:
            entry = self._ready[key]
            if entry.done and (now - entry.at > self.READY_TTL_S or entry.error is not None):
                del self._ready[key]
        unpinned = [k for k, e in self._ready.items() if not e.pinned and e.done]
        while len(unpinned) > self.READY_MAX:
            del self._ready[unpinned.pop(0)]
        pinned = [k for k, e in self._ready.items() if e.pinned]
        while len(pinned) > self.PINNED_MAX:
            del self._ready[pinned.pop(0)]

    async def take_ready(self, text: str) -> AsyncIterator[bytes] | None:
        """The prefetched answer for this text, as chunks — the ones already here, then the
        rest as they arrive. None when nothing was prefetched, in which case the caller
        streams as before. Raises the VoiceUnavailable a prefetch ended with before producing
        any audio, so the caller reports it without a second request."""
        entry = self._ready.get(text)
        if entry is None:
            return None
        if not entry.pinned:
            del self._ready[text]   # handed out once
        try:
            # Bounded, and tightly: the first byte normally arrives within a second. A voice
            # that has not started after this is not coming soon, and the tablet's own voice
            # should take the sentence rather than the screen saying Speaking over silence.
            await asyncio.wait_for(entry.wait_first(), timeout=min(self.FIRST_BYTE_S, self._timeout + 1.0))
        except TimeoutError:
            self._ready.pop(text, None)
            raise VoiceUnavailable("prefetch never started", kind="timeout") from None
        if entry.error is not None and not entry.chunks:
            self._ready.pop(text, None)   # a failed line is never kept, pinned or not
            raise entry.error
        self.prefetch_hits += 1
        return entry.follow()

    def cancel_prefetches(self) -> int:
        """Stop synthesising anything not yet handed out: the owner has moved on."""
        cancelled = 0
        for text, task in list(self._inflight.items()):
            entry = self._ready.get(text)
            if entry is not None and not entry.pinned and not task.done():
                task.cancel()
                # Gone from the shelf at once: a later /speak for this text streams afresh
                # rather than waiting on, or inheriting, a request that was stopped.
                self._ready.pop(text, None)
                cancelled += 1
        return cancelled

    async def synthesise(self, text: str) -> bytes:
        """The whole MP3, for scripts and tests. The tablet uses open_stream()."""
        stream = await self.open_stream(text)
        audio = b"".join([chunk async for chunk in stream.chunks()])
        if not audio:
            raise self._record_failure(
                VoiceUnavailable("ElevenLabs returned no audio", kind="empty_audio")
            )
        return audio

    async def voices(self) -> tuple[list[dict[str, Any]] | None, str]:
        """Every voice this account can speak with: (list, "") or (None, why). Free — no synthesis.
        Only the id, the name and a word on what it is: nothing else is the screen's business, and
        the key never leaves this method."""
        if not self.enabled:
            return None, "ElevenLabs speech is switched off in settings"
        try:
            key = self._api_key()
        except VoiceUnavailable as exc:
            return None, exc.detail
        try:
            response = await self._client().get(
                f"{self.base_url}/voices", headers={"xi-api-key": key}, timeout=10.0,
            )
        except httpx.HTTPError as exc:
            return None, f"ElevenLabs could not be reached: {self._scrub(str(exc))[:120]}"
        if response.status_code != 200:
            return None, self._http_failure(response.status_code, response.text[:400]).detail
        try:
            listed = response.json().get("voices") or []
        except ValueError:
            return None, "ElevenLabs answered something unreadable"
        found = []
        for item in listed:
            if not isinstance(item, dict):
                continue
            voice_id = str(item.get("voice_id") or "")
            name = str(item.get("name") or "")
            if not voice_id or not name:
                continue
            found.append({"voice_id": voice_id, "name": name[:60],
                          "kind": str(item.get("category") or "")[:30]})
        found.sort(key=lambda v: v["name"].lower())
        return found, ""

    async def voice_details(self, voice_id: str) -> tuple[dict[str, Any] | None, str]:
        """One voice as ElevenLabs describes it (GET /voices/{id}): ({"voice_id", "name",
        "settings"}, "") or (None, why). Free, no synthesis. `settings` is what ElevenLabs reports
        as the voice's own, as it reported it, and empty when it reports none: nothing is filled
        in here. The caller has checked the id's shape; the key never leaves this method."""
        if not self.enabled:
            return None, "ElevenLabs speech is switched off in settings"
        try:
            key = self._api_key()
        except VoiceUnavailable as exc:
            return None, self._scrub(str(exc))
        try:
            response = await self._client().get(
                f"{self.base_url}/voices/{voice_id}", headers={"xi-api-key": key}, timeout=10.0,
            )
        except httpx.HTTPError as exc:
            return None, f"ElevenLabs could not be reached ({type(exc).__name__})"
        if response.status_code != 200:
            return None, str(self._http_failure(response.status_code, response.text[:400]))
        try:
            body = response.json()
        except ValueError:
            return None, "ElevenLabs answered something unreadable"
        name = " ".join(str((body or {}).get("name") or "").split())[:60] if isinstance(body, dict) else ""
        if not name:
            return None, "ElevenLabs did not say what that voice is called"
        settings = body.get("settings")
        return {"voice_id": voice_id, "name": name, "settings": settings if isinstance(settings, dict) else {}}, ""

    async def say_once(self, text: str, *, voice_id: str = "", model: str = "",
                       voice_settings: dict[str, Any] | None = None) -> bytes:
        """One sentence in settings that are not this client's, for a preview. Nothing here changes
        what the next answer sounds like: the overrides are used for this request only, and a
        failure is not recorded against the voice in use, so auditioning a voice that cannot speak
        never puts the working one into its cooldown."""
        self._guard(text)
        key = self._api_key()
        body: dict[str, Any] = {"text": text, "model_id": model or self.model}
        if voice_settings:
            body["voice_settings"] = dict(voice_settings)
        url = f"{self.base_url}/text-to-speech/{voice_id or self.voice_id}?output_format={self.output_format}"
        response = await self._client().post(
            url, headers={"xi-api-key": key, "accept": "audio/mpeg"}, json=body, timeout=self._timeout,
        )
        if response.status_code != 200:
            raise self._http_failure(response.status_code, response.text[:400])
        audio = response.content
        if not audio:
            raise VoiceUnavailable("ElevenLabs returned no audio", kind="empty_audio")
        return audio

    def why_not(self, exc: BaseException) -> str:
        """A reason the owner can read, for a preview that did not speak. Never a traceback."""
        if isinstance(exc, VoiceUnavailable):
            return exc.detail
        return f"ElevenLabs could not speak that: {self._scrub(str(exc))[:160]}"

    def _http_failure(self, code: int, body: str) -> VoiceUnavailable:
        """Name the failure by its shape. The body is included because it is what makes an
        account problem diagnosable — scrubbed, and truncated, because it is not ours."""
        # Classified on the whole body — the quota detail can sit past any cut — and only the
        # text that is shown is truncated.
        lowered = self._scrub(body).lower()
        body = self._scrub(body[:200])
        if code == 402 or "quota" in lowered or "credit" in lowered:
            # First, whatever the status: ElevenLabs answers an empty account with a 401
            # quota_exceeded, and that is a plan to top up, not a key to replace.
            kind = "credit"
        elif code in (401, 403) or "invalid_api_key" in lowered:
            kind = "rejected" if code == 401 else "forbidden"
        elif code == 429 and ("concurrent" in lowered or "rate" in lowered or "busy" in lowered):
            # Too many requests at once, not an empty account: the next one may well work.
            kind = "rate"
        elif code == 429:
            kind = "credit"
        elif code == 404 or "voice_not_found" in lowered:
            kind = "no_voice"
        elif code >= 500:
            kind = "server_error"
        else:
            kind = f"http_{code}"
        return VoiceUnavailable(f"ElevenLabs returned {code}: {body}", kind=kind)

    # ------------------------------------------------------------------ health

    VOICE_NAME_TTL_S = 3600.0

    async def verify_voice(self) -> str | None:
        """What ElevenLabs calls the configured voice id — asked once an hour, free (no
        synthesis), and remembered. The configured name is only a label; a .env that still
        carries an old id would otherwise name the configured voice on the health page
        while another spoke on the tablet. Returns the name, or None when it cannot be asked."""
        if not self.enabled:
            return None
        now = time.time()
        if self._voice_checked_at and now - self._voice_checked_at < self.VOICE_NAME_TTL_S:
            return self._voice_actual_name
        try:
            key = self._api_key()
        except VoiceUnavailable:
            return None
        self._voice_checked_at = now
        try:
            response = await self._client().get(
                f"{self.base_url}/voices/{self.voice_id}", headers={"xi-api-key": key}, timeout=5.0,
            )
            if response.status_code != 200:
                self._voice_actual_name = None
                return None
            name = response.json().get("name")
            self._voice_actual_name = str(name)[:60] if name else None
        except Exception as exc:  # noqa: BLE001 — a name check must never take health down
            log.info("could not verify the voice id with ElevenLabs: %s", self._scrub(str(exc))[:120])
            self._voice_actual_name = None
        return self._voice_actual_name

    @property
    def voice_mismatch(self) -> str | None:
        """Set when ElevenLabs names the configured id differently from the configured name."""
        actual = self._voice_actual_name
        if not actual:
            return None
        # ElevenLabs library voices carry a description after the name — a voice returned as
        # "Vikram - AI Productivity Assistant" is the one configured as "Vikram". The name is
        # what must match; a different voice entirely is what this is for.
        theirs, ours = actual.strip().lower(), self.voice_name.strip().lower()
        if theirs == ours or theirs.split(" - ")[0].strip() == ours or theirs.startswith(f"{ours} "):
            return None
        return actual

    def health(self) -> tuple[bool, str]:
        """Is the voice usable? Answered from configuration, the Keychain and what the account
        has already said about itself, with no request of its own: a health check that
        synthesises a sentence on every poll is a bill, not a check.

        Three kinds of evidence, strongest first. The latest real attempt is the best: it tried
        to speak and either did or did not. Under it sits the account, probed once per check by
        Scribe on the same credential — one plan pays for both, so an empty account is as true
        of speaking as of listening. Only when neither has anything to say is configuration on
        its own enough to answer "key ok".

        That last clause is the whole of the repair. Until it existed, a process that had not
        yet tried to speak reported the voice healthy no matter what the account had told
        Scribe a moment earlier, and every restart put that answer back."""
        note = f"ElevenLabs {self.voice_name} · {self.model} · {self.output_format}"
        if not self.enabled:
            return True, f"not in use (CROOKS_TTS_ENABLED=false) · {note}"
        try:
            self._api_key()
        except VoiceUnavailable as exc:
            return False, f"{self._scrub(str(exc))} · {note}"
        if self.voice_mismatch:
            return False, (
                f"CROOKS_TTS_VOICE_ID {self.voice_id} is the voice ElevenLabs calls "
                f"'{self.voice_mismatch}', not {self.voice_name}: fix or remove the "
                f"CROOKS_TTS_VOICE_ID and CROOKS_TTS_VOICE_NAME lines in .env · {note}"
            )
        if self.attempts:
            note += (
                f" · {self.successes}/{self.attempts} ok, last {self.last_ms:.0f}ms, "
                f"{self.last_bytes} bytes"
            )
        if self.prefetches:
            note += f" · {self.prefetch_hits}/{self.prefetches} answers ready before asked"
        if self.failing_kind:
            # The latest attempt failed and nothing has worked since: not ok, in plain words
            # first, then the kind and ElevenLabs' own detail. The next success clears it.
            detail = f"{voice_reason(self.failing_kind)} ({self.failing_kind}) · {note}"
            if self.cooling_down:
                detail += f" · SKIPPING ElevenLabs for {self.cooldown_remaining_s:.0f}s"
            return False, f"{detail} · last error: {self.last_error}"
        if self.account.exhausted:
            # Nothing has been tried in this process — a restart, or a quiet morning — but the
            # account has already answered, and it said there is nothing left to spend.
            return False, f"{voice_reason('credit')} (credit) · {self.account.detail} · {note}"
        return True, f"key ok · {note}"

    @property
    def failing_kind(self) -> str:
        """The kind of the latest failure while nothing has succeeded since; "" when well."""
        if self.failing or self.cooling_down:
            return self.last_error_kind or "failure"
        return ""

    @property
    def blocking_kind(self) -> str:
        """Why the voice cannot speak, from the strongest evidence there is; "" when it can.

        `failing_kind` answers only for what this process has tried. This answers for the
        account as well, so /health can name the reason on a page whose process has made no
        attempt at all — which is every page served in the first minutes after a deploy."""
        return self.failing_kind or ("credit" if self.account.exhausted else "")
