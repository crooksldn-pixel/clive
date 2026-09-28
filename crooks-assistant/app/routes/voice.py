"""POST /voice/live — a single-use key for the live words under the owner's thumb.

While the owner holds the ask bar, the phone shows what ElevenLabs hears as he speaks
(web/live-voice.js). The phone opens ElevenLabs' realtime speech-to-text socket itself, so the
words reach the screen without a hop through this server, and it opens it with a key that is
good for one session and fifteen minutes. This route mints that key with the server's own
ElevenLabs key, which never leaves the server.

What it answers
---------------
200 {"token", "url", "params"}, with Cache-Control: no-store: the key, the socket's address and
the query it takes, so the page carries no address of its own. The params never carry keyterms:
the owner had them removed because they rewrote his words.

503 {"live": false, "why": "<plain reason>"} when there are no live words to be had: the setting
is off (CROOKS_LIVE_TRANSCRIPT), no key is stored, or ElevenLabs did not give a key within five
seconds. 429 when keys are asked for faster than a person can hold: at most one per 1.5 s and
forty in ten minutes, in this process. The page treats all of them alike: no live words, and the
hold goes on exactly as before. The words are display only; the recording sent on release is
still the one CLIVE answers.

What it never does
------------------
Return or log the server's key, or log the key it minted. Its log lines name the refusal in its
own fixed words, never ElevenLabs' answer. It is the owner's: the door in app/main.py refuses
anyone else before it runs, and it checks again itself, as the pad's routes do.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.secrets import keychain

log = logging.getLogger("crooks.voice")

router = APIRouter(prefix="/voice")

# ElevenLabs' realtime speech-to-text, as documented: the path the single-use key is minted at,
# the socket it opens, and the query the socket takes. 16 kHz PCM is what the page sends; the
# commit is the page's, on the release.
TOKEN_PATH = "/single-use-token/realtime_scribe"
SOCKET_PATH = "/speech-to-text/realtime"
PARAMS = {
    "model_id": "scribe_v2_realtime",
    "audio_format": "pcm_16000",
    "language_code": "en",
    "commit_strategy": "manual",
}
TIMEOUT_S = 5.0
NO_STORE = {"Cache-Control": "no-store"}


class Pace:
    """How often a key may be minted, in this process: at most one per `gap_s`, and `limit` in
    any `window_s`. A hold is a person's thumb; faster than this is a page gone wrong, and every
    key is ElevenLabs' to count. `take()` answers 0 and counts the key when one may be minted,
    and otherwise the seconds until one may."""

    def __init__(self, *, gap_s: float = 1.5, limit: int = 40, window_s: float = 600.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.gap_s = gap_s
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self._taken: deque[float] = deque()
        self._lock = threading.Lock()

    def take(self) -> float:
        with self._lock:
            now = self.clock()
            while self._taken and now - self._taken[0] >= self.window_s:
                self._taken.popleft()
            if self._taken and now - self._taken[-1] < self.gap_s:
                return self.gap_s - (now - self._taken[-1])
            if len(self._taken) >= self.limit:
                return self.window_s - (now - self._taken[0])
            self._taken.append(now)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._taken.clear()


PACE = Pace()


def http_client() -> httpx.AsyncClient:
    """A client for one mint. Looked up per request, so a test can put a mocked transport in
    its place; a key is asked for once per hold, so there is no connection worth keeping."""
    return httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S))


def _refused(request: Request) -> JSONResponse | None:
    """The owner rule, as a 403 with its code; None when the caller is the owner. The same rule
    the door applies, kept here as well so this route does not rest on the door's list."""
    from app.routes.actions import principal_verdict

    _who, code, why = principal_verdict(request)
    if code:
        log.warning("live words refused: %s (path=%s)", code, request.url.path)
        return JSONResponse(status_code=403, content={"code": code, "detail": why}, headers=NO_STORE)
    return None


def _unavailable(why: str) -> JSONResponse:
    return JSONResponse(status_code=503, content={"live": False, "why": why}, headers=NO_STORE)


def _api_key() -> str:
    """The server's ElevenLabs key, read as the recogniser and the voice read it
    (app/clients/elevenlabs.py, app/clients/elevenlabs_tts.py): through the secret store's
    get_optional, and not cached here, so a key stored later works without a restart."""
    try:
        return (keychain.get_optional("elevenlabs_api_key") or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has no key to give
        return ""


def socket_url(base_url: str) -> str:
    """The realtime socket beside the REST base the server is configured with
    (CROOKS_ELEVENLABS_BASE_URL): https becomes wss, so a region's base moves both together."""
    base = (base_url or "").rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    return base + SOCKET_PATH


def _refusal(response: httpx.Response) -> str:
    """ElevenLabs said no: why, in fixed words. Its body decides the words, and goes nowhere."""
    code = response.status_code
    body = (response.text or "").lower()
    if code == 402 or "quota" in body or "credit" in body:
        return "The ElevenLabs account has no credit left."
    if code in (401, 403):
        return "ElevenLabs refused the server's key."
    if code == 429:
        return "ElevenLabs is busy; the next hold tries again."
    if code >= 500:
        return "ElevenLabs had a problem of its own."
    return f"ElevenLabs would not start live words ({code})."


async def _mint(key: str, base_url: str) -> tuple[str, str]:
    """(token, "") or ("", why). Five seconds in all, however the time is spent."""
    url = (base_url or "").rstrip("/") + TOKEN_PATH
    try:
        async with http_client() as client:
            response = await asyncio.wait_for(client.post(url, headers={"xi-api-key": key}), TIMEOUT_S)
    except (TimeoutError, httpx.TimeoutException):
        return "", "ElevenLabs did not answer in time."
    except httpx.HTTPError:
        return "", "ElevenLabs could not be reached."
    if response.status_code != 200:
        return "", _refusal(response)
    try:
        token = response.json().get("token")
    except (ValueError, AttributeError):
        token = None
    if not isinstance(token, str) or not token.strip():
        return "", "ElevenLabs answered without a key."
    return token.strip(), ""


@router.post("/live", response_model=None)
async def live(request: Request) -> JSONResponse:
    """A single-use key for one hold's live words, or the plain reason there is none."""
    if (refused := _refused(request)) is not None:
        return refused
    settings = request.app.state.runtime.settings
    if not getattr(settings, "live_transcript", True):
        return _unavailable("Live words are switched off on the server (CROOKS_LIVE_TRANSCRIPT).")
    key = _api_key()
    if not key:
        return _unavailable("No ElevenLabs key is stored on the server.")
    wait = PACE.take()
    if wait:
        log.info("live words: a key was asked for too soon; refused for %.1fs", wait)
        return JSONResponse(
            status_code=429,
            content={"live": False, "why": "Live words were asked for too often; the next hold tries again."},
            headers={**NO_STORE, "Retry-After": str(max(1, math.ceil(wait)))},
        )
    base_url = getattr(settings, "elevenlabs_base_url", "") or "https://api.elevenlabs.io/v1"
    token, why = await _mint(key, base_url)
    if not token:
        log.warning("live words unavailable: %s", why)
        return _unavailable(why)
    return JSONResponse(content={"token": token, "url": socket_url(base_url), "params": dict(PARAMS)}, headers=NO_STORE)
