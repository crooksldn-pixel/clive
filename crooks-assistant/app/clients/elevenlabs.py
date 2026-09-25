"""HTTP client for ElevenLabs Scribe — the primary speech recogniser.

Scribe v2 hears this business better than a local model does, and it is the only part of the
speech path that leaves the Mac. Two consequences shape this module:

- Nothing here may leak the credential. The key is read through the Keychain wrapper, held in
  memory only, and every message this module produces — log line, exception, health detail —
  goes through _scrub() so an accidental echo of the key becomes "[redacted]".
- Nothing here may leave the tablet without an answer. Every failure is raised as one named
  ScribeUnavailable with a `kind`, and app/speech/transcribe.py turns that into a whisper.cpp
  fallback rather than an error on the screen.

`keyterms` are product words, never customer names — see Catalogue.external_terms().
"""

from __future__ import annotations

import logging
import time

import httpx

from app.clients.whisper import Transcript
from app.secrets import keychain
from app.speech.voice_reasons import listening_reason

log = logging.getLogger("crooks.scribe")

API_BASE = "https://api.elevenlabs.io/v1"

# ElevenLabs' documented keyterm rules: at most 1000 terms, under 50 characters each, at most
# five words each. A request with 100 or more keyterms is billed at a 20-second minimum, so the
# default cap sits just under that line — see Settings.scribe_max_keyterms.
KEYTERM_MAX_CHARS = 49
KEYTERM_MAX_WORDS = 5

# Failures that will not fix themselves within a turn or two: a missing or rejected key, an
# account with no credit. Retrying those on every sentence buys nothing and costs the speaker a
# round trip before the fallback starts, so they open a short cooldown instead.
STICKY_KINDS = frozenset({"no_key", "rejected", "forbidden", "credit"})


def _says_no_credit(lowered_body: str) -> bool:
    """An ElevenLabs error body about an empty account (quota_exceeded, "0 credits remaining")."""
    return "quota" in lowered_body or "credit" in lowered_body


class ScribeUnavailable(RuntimeError):
    """Scribe cannot transcribe this recording. The caller falls back to whisper.cpp.

    `kind` is the machine-readable shape of the failure (timeout, rejected, credit, …) and is
    what gets logged and reported; str(exc) is the human detail, already scrubbed."""

    # Only used if the fallback is also down; the whisper message is the one normally spoken.
    spoken = "My speech recognition is not available right now."

    def __init__(self, detail: str, *, kind: str) -> None:
        super().__init__(detail)
        self.kind = kind


class ScribeClient:
    def __init__(
        self,
        *,
        model: str = "scribe_v2",
        language: str = "eng",
        timeout_s: float = 20.0,
        base_url: str = API_BASE,
        max_keyterms: int = 99,
        cooldown_s: float = 300.0,
    ) -> None:
        self.model = model
        self.language = language
        self.base_url = base_url.rstrip("/")
        self.max_keyterms = max_keyterms
        self._timeout = timeout_s
        self._cooldown_s = cooldown_s
        self._key: str | None = None
        self._cooldown_until = 0.0
        # One HTTPS connection to ElevenLabs, kept open between questions: the TLS handshake
        # is a few hundred milliseconds the owner would otherwise wait for on every sentence.
        self._http: httpx.AsyncClient | None = None
        # Non-sensitive diagnostics for /health and the turn log.
        self.attempts = 0
        self.successes = 0
        self.failures = 0
        self.last_error: str = ""
        self.last_error_kind: str = ""
        self.last_ms: float = 0.0
        # The latest attempt failed and nothing has succeeded since. A key that still lists
        # models is not a recogniser that works: health reads this as well as the probe.
        self.failing = False
        # What the key and the account said at the last health probe, before the latest attempt
        # is laid over it: a cached /health reads the attempt again through judged().
        self.last_probe: tuple[bool, str] | None = None
        # How many transcriptions had succeeded when that probe answered. A success after it
        # is newer evidence than a failed probe; a probe after the success is newer still.
        self._probe_successes = 0
        # The kind of what that probe found wrong ("credit", "rejected"), "" when it was well.
        self._probe_kind = ""

    # ------------------------------------------------------------------ connection

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            # A route to ElevenLabs that does not even connect is known in five seconds; the
            # read bound is the recogniser's, and whisper is waiting behind it.
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=min(5.0, self._timeout)))
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None

    # ------------------------------------------------------------------ credential

    def _api_key(self) -> str:
        """The key, from the Keychain, cached in memory once it is found.

        A *missing* key is deliberately not cached: storing it with
        `python scripts/set_secrets.py elevenlabs_api_key` then starts working without a
        restart."""
        if not self._key:
            self._key = keychain.get_optional("elevenlabs_api_key") or ""
        if not self._key:
            raise ScribeUnavailable(
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
        """Drop the cached key so the next call re-reads the Keychain (used after a 401)."""
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

    def _record_failure(self, exc: ScribeUnavailable) -> ScribeUnavailable:
        self.failures += 1
        self.failing = True
        self.last_error_kind = exc.kind
        self.last_error = self._scrub(str(exc))[:200]
        if exc.kind in STICKY_KINDS and self._cooldown_s > 0:
            self._cooldown_until = time.time() + self._cooldown_s
            if exc.kind in {"rejected", "forbidden"}:
                self.forget_key()  # the stored key may have been replaced since we read it
        return exc

    # ------------------------------------------------------------------ transcription

    def keyterms(self, terms: list[str]) -> list[str]:
        """The terms ElevenLabs will actually accept: short, few-worded, deduplicated, capped.

        Most important LAST in, most important KEPT — the catalogue puts the hand-written
        spoken forms at the end, so the cap trims from the front like Whisper's prompt does."""
        cleaned: list[str] = []
        for term in terms:
            term = " ".join(str(term).split())
            if not term or len(term) > KEYTERM_MAX_CHARS or len(term.split()) > KEYTERM_MAX_WORDS:
                continue
            cleaned.append(term)
        deduped = list(dict.fromkeys(cleaned))
        return deduped[-self.max_keyterms :] if self.max_keyterms > 0 else []

    async def transcribe(self, wav: bytes, *, keyterms: list[str] | None = None) -> Transcript:
        """POST a 16 kHz mono WAV to /v1/speech-to-text. Raises ScribeUnavailable on anything
        that is not a usable transcript, so the caller can fall back."""
        if self.cooling_down:
            raise ScribeUnavailable(
                f"skipped: cooling down for {self.cooldown_remaining_s:.0f}s after "
                f"{self.last_error_kind or 'a failure'}",
                kind="cooldown",
            )
        key = self._api_key()
        self.attempts += 1
        started = time.perf_counter()

        data: dict[str, str | list[str]] = {
            "model_id": self.model,
            "language_code": self.language,
            # "(laughter)" and friends are not what was said; they would reach the normaliser
            # and then the agent as if they were words.
            "tag_audio_events": "false",
            "diarize": "false",
        }
        terms = self.keyterms(keyterms or [])
        if terms:
            data["keyterms"] = terms  # httpx repeats the field once per term, as the API wants

        try:
            response = await self._client().post(
                f"{self.base_url}/speech-to-text",
                headers={"xi-api-key": key},
                files={"file": ("audio.wav", wav, "audio/wav")},
                data=data,
            )
        except httpx.TimeoutException as exc:
            raise self._record_failure(
                ScribeUnavailable(f"no response in {self._timeout:.0f}s", kind="timeout")
            ) from exc
        except httpx.HTTPError as exc:
            raise self._record_failure(
                ScribeUnavailable(f"request failed: {type(exc).__name__}", kind="network")
            ) from exc

        if response.status_code != 200:
            raise self._record_failure(self._http_failure(response))

        try:
            payload = response.json()
        except ValueError as exc:
            raise self._record_failure(
                ScribeUnavailable("response was not JSON", kind="bad_response")
            ) from exc
        if not isinstance(payload, dict) or "text" not in payload:
            raise self._record_failure(
                ScribeUnavailable("response had no transcript in it", kind="bad_response")
            )

        ms = (time.perf_counter() - started) * 1000
        self.successes += 1
        self.failing = False
        self.last_ms = ms
        self.clear_cooldown()
        return Transcript(text=(payload.get("text") or "").strip(), ms=ms, model=self.model)

    def _http_failure(self, response: httpx.Response) -> ScribeUnavailable:
        """Name the failure by its shape. The body is included because it is what makes an
        account problem diagnosable — scrubbed, and truncated, because it is not ours."""
        code = response.status_code
        # Classified on the whole body — the quota detail can sit past any cut — and only the
        # text that is shown is truncated.
        lowered = self._scrub(response.text or "").lower()
        body = self._scrub((response.text or "")[:200])
        if code == 402 or _says_no_credit(lowered):
            # First, whatever the status: ElevenLabs answers an empty account with a 401
            # quota_exceeded, and that is a plan to top up, not a key to replace.
            kind = "credit"
        elif code in (401, 403) or "invalid_api_key" in lowered or "api key" in lowered:
            kind = "rejected" if code == 401 else "forbidden"
        elif code == 429 and ("concurrent" in lowered or "rate" in lowered or "busy" in lowered):
            # A burst, not an empty account: whisper takes this one, Scribe the next.
            kind = "rate"
        elif code == 429:
            kind = "credit"
        elif code >= 500:
            kind = "server_error"
        else:
            kind = f"http_{code}"
        return ScribeUnavailable(f"ElevenLabs returned {code}: {body}", kind=kind)

    # ------------------------------------------------------------------ health

    async def health(self) -> tuple[bool, str]:
        """Is Scribe usable right now? Checked without transcribing anything, because a health
        check that spends credit on every /health poll is a bill, not a check.

        The probe is GET /models: it needs a valid key (a bad one is a 401 invalid_api_key) and,
        unlike the account endpoints, it does not need the `user_read` permission — which a key
        scoped to speech-to-text does not have. Quota is read afterwards, best effort, because
        a restricted key cannot see it and that is not a fault."""
        # Forgotten first: a probe that times out must not leave an older answer behind it.
        self.last_probe = None
        self._probe_kind = ""
        probe = await self._probe()
        self.last_probe, self._probe_successes = probe, self.successes
        return self.judged(probe)

    async def _probe(self) -> tuple[bool, str]:
        """What the key and the account say, without the latest attempt."""
        try:
            key = self._api_key()
        except ScribeUnavailable as exc:
            return False, self._scrub(str(exc))

        try:
            client = self._client()
            headers = {"xi-api-key": key}
            probe = await client.get(f"{self.base_url}/models", headers=headers, timeout=5.0)
            quota = await self._quota(client, headers) if probe.status_code == 200 else ""
        except httpx.HTTPError as exc:
            return False, f"ElevenLabs unreachable: {type(exc).__name__}"

        body = self._scrub(probe.text or "").lower()
        if probe.status_code == 200:
            return True, f"key ok{quota}"
        elif "missing_permissions" in body or probe.status_code == 403:
            # A key scoped to one product. It cannot list models; it can still transcribe.
            return True, "key ok (restricted, unlisted quota)"
        elif probe.status_code in (401, 402, 429) and _says_no_credit(body):
            self._probe_kind = "credit"
            return False, f"{listening_reason('credit')} (credit)"
        elif probe.status_code == 401:
            self._probe_kind = "rejected"
            return False, "API key rejected (401)"
        else:
            return False, f"ElevenLabs returned {probe.status_code}"

    def judged(self, probe: tuple[bool, str]) -> tuple[bool, str]:
        """A probe's answer with the attempts read NOW, so a cached /health that passes its
        probe back through here shows a failure, or a recovery, since the probe at once."""
        ok, detail = probe
        if not ok and probe is self.last_probe and self.successes > self._probe_successes:
            # Transcribed since this probe failed: the key and the account answered after it.
            ok, detail = True, "key ok (a transcription has succeeded since the last probe)"
        note = f"model {self.model}, language {self.language}"
        if self.attempts:
            note += f" · {self.successes}/{self.attempts} ok, last {self.last_ms:.0f}ms"
        failing = self.failing_kind
        if self.cooling_down:
            note += (
                f" · SKIPPING Scribe for {self.cooldown_remaining_s:.0f}s after "
                f"{self.last_error_kind}: {self.last_error}"
            )
        elif failing:
            note += f" · last error: {self.last_error}"
        detail = f"{detail} · {note}"
        # The key answers; whether transcription itself works is what the last attempt said.
        # Not ok, in plain words, until the next success.
        if ok and failing:
            return False, f"{listening_reason(failing)} ({failing}) · {detail}"
        return ok, detail

    @property
    def failing_kind(self) -> str:
        """The kind of the latest failure while nothing has succeeded since; "" when well."""
        if self.failing or self.cooling_down:
            return self.last_error_kind or "failure"
        return ""

    @property
    def unwell_kind(self) -> str:
        """failing_kind, or else what the last probe found wrong while no transcription has
        succeeded since it — an account the probe already saw empty is not a recogniser that
        works just because nobody has spoken yet. "" when well."""
        if self.failing_kind:
            return self.failing_kind
        probe = self.last_probe
        if self._probe_kind and probe is not None and not probe[0] and self.successes <= self._probe_successes:
            return self._probe_kind
        return ""

    # A key that may not read the account says so with a 401 every time it is asked. Ask once
    # an hour, not on every poll: the answer does not change and the log should not be a column
    # of refusals.
    QUOTA_RECHECK_S = 3600.0

    async def _quota(self, client: httpx.AsyncClient, headers: dict[str, str]) -> str:
        """Characters used, when the key is allowed to see them. Never a failure on its own."""
        remembered = getattr(self, "_quota_memo", None)
        if remembered is not None and time.monotonic() < remembered[0]:
            return remembered[1]
        try:
            response = await client.get(
                f"{self.base_url}/user/subscription", headers=headers, timeout=5.0
            )
            if response.status_code != 200:
                note = ", quota unreadable (restricted key)"
                self._quota_memo = (time.monotonic() + self.QUOTA_RECHECK_S, note)
                return note
            sub = response.json()
        except (httpx.HTTPError, ValueError):
            return ""
        if not isinstance(sub, dict):
            return ""
        used, limit = sub.get("character_count"), sub.get("character_limit")
        tier = sub.get("tier") or "unknown tier"
        return f", {tier}, {used}/{limit} characters used" if limit is not None else f", {tier}"
