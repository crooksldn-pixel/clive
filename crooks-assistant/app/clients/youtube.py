"""YouTube, for the owner's screens: find a video from what he asked for, or read one he linked.

The screens play YouTube in YouTube's own embedded player (web/display.js). This module only
chooses what to play, and it only ever reads:

- With the key the owner stored as `youtube_api_key` (scripts/provision_secrets.py), the YouTube
  Data API v3 searches ("the Heat trailer", "lofi girl") and reads a linked video's details.
  The key travels in the X-Goog-Api-Key header and never in an address, so no log line or
  exception that carries a URL can carry the key; and no answer or refusal here ever quotes
  what YouTube sent back.
- With no key, a link or an id still works: YouTube's public oEmbed endpoint says the video's
  title and channel, and whether its owner lets it be played outside YouTube. Only search
  needs the key, and says so plainly when there is none.

Only what can actually play on a screen is offered: videos their owners let other sites embed,
public or unlisted, not age-restricted, not blocked in the UK, and not a stream still to come.
Nothing here is kept between calls, and every failure is one named YouTubeUnavailable with a
`kind` and words the owner can be told.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from app.secrets import keychain

log = logging.getLogger("crooks.youtube")

API = "https://www.googleapis.com/youtube/v3"
OEMBED = "https://www.youtube.com/oembed"
KEY_NAME = "youtube_api_key"
TIMEOUT_S = 6.0
# Where the owner watches: a video blocked here is not offered.
REGION = "GB"
# What one search offers: the one played and a few to choose from instead.
MAX_RESULTS = 5
MAX_QUERY = 200
MAX_TITLE = 120
MAX_CHANNEL = 80
# A start point in a link (?t=) is at most this far in.
MAX_START_S = 12 * 3600

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
    "youtube-nocookie.com", "www.youtube-nocookie.com",
})
_PATH_KINDS = frozenset({"shorts", "embed", "live", "v", "e"})
_DURATION = re.compile(r"^P(?:(\d{1,4})D)?(?:T(?:(\d{1,4})H)?(?:(\d{1,4})M)?(?:(\d{1,6})S)?)?$")
_START = re.compile(r"^(?:(\d{1,3})h)?(?:(\d{1,4})m)?(?:(\d{1,6})s?)?$")


class YouTubeUnavailable(RuntimeError):
    """YouTube could not answer this, said as the owner can be told it. `kind` is one of:
    no_key, timeout, unreachable, rejected (the key), quota, not_found, not_playable, refused."""

    def __init__(self, said: str, *, kind: str) -> None:
        super().__init__(said)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class Video:
    id: str
    title: str
    channel: str
    duration_s: int | None
    live: bool = False
    start: int = 0

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    def said(self) -> dict[str, Any]:
        """What CLIVE is told about it: enough to say what is playing and to choose another."""
        out: dict[str, Any] = {"video": self.id, "title": self.title, "channel": self.channel, "url": self.url}
        if self.live:
            out["live"] = True
        elif self.duration_s is not None:
            out["duration"] = clock(self.duration_s)
        return out


def clock(seconds: int) -> str:
    """1:02:03, 4:05, 0:09."""
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _text(value: Any, limit: int) -> str:
    # YouTube's titles arrive HTML-escaped ("Don&#39;t"). Cut before anything else is done.
    return " ".join(html.unescape(str(value or "")[: limit * 4]).split())[:limit]


def _start(values: list[str] | None) -> int:
    """A link's start point: ?t=90, ?t=90s, ?t=1m30s, ?start=90."""
    raw = str((values or [""])[0] or "").strip().lower()[:20]
    found = _START.fullmatch(raw) if raw else None
    if not found:
        return 0
    h, m, s = (int(x) if x else 0 for x in found.groups())
    return max(0, min(MAX_START_S, h * 3600 + m * 60 + s))


def parse(text: str) -> tuple[str, int] | None:
    """(video id, start in seconds) from a YouTube link or a bare id, or None when it is
    neither. Only YouTube's own addresses are read; anything else is not a YouTube video."""
    raw = str(text or "").strip()[:500]
    if VIDEO_ID.fullmatch(raw):
        return raw, 0
    if not raw or any(c.isspace() for c in raw):
        return None
    try:
        parts = urlsplit(raw if "://" in raw else "https://" + raw)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or host not in _HOSTS:
        return None
    query = parse_qs(parts.query)
    segments = [s for s in parts.path.split("/") if s]
    video = ""
    if host == "youtu.be":
        video = segments[0] if segments else ""
    elif parts.path.rstrip("/") == "/watch":
        video = (query.get("v") or [""])[0]
    elif len(segments) >= 2 and segments[0] in _PATH_KINDS:
        video = segments[1]
    if not VIDEO_ID.fullmatch(video or ""):
        return None
    return video, _start(query.get("t") or query.get("start"))


def _duration(value: Any) -> int | None:
    found = _DURATION.fullmatch(str(value or ""))
    if not found:
        return None
    d, h, m, s = (int(x) if x else 0 for x in found.groups())
    total = d * 86400 + h * 3600 + m * 60 + s
    return total or None


def api_key() -> str:
    """The stored key, read each time (a key stored later works without a restart), or ""."""
    try:
        return (keychain.get_optional(KEY_NAME) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has no key to give
        return ""


def http_client() -> httpx.AsyncClient:
    """A client for one lookup. Looked up per call, so a test can put a mocked transport in its
    place. Redirects are not followed: every address here is answered where it is."""
    return httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S), follow_redirects=False)


def _reason(response: httpx.Response) -> str:
    """The reason Google gives for an API error ("quotaExceeded", "keyInvalid"), or ""."""
    try:
        body = response.json()
        errors = (body.get("error") or {}).get("errors") or []
        return str((errors[0] or {}).get("reason") or "")[:60] if errors else str((body.get("error") or {}).get("status") or "")[:60]
    except (ValueError, AttributeError, TypeError, IndexError):
        return ""


async def _get(url: str, params: dict[str, str], *, key: str = "") -> httpx.Response:
    headers = {"Accept": "application/json"}
    if key:
        headers["X-Goog-Api-Key"] = key
    try:
        async with http_client() as client:
            return await asyncio.wait_for(client.get(url, params=params, headers=headers), TIMEOUT_S)
    except (TimeoutError, httpx.TimeoutException):
        raise YouTubeUnavailable("YouTube did not answer in time.", kind="timeout") from None
    except httpx.HTTPError:
        raise YouTubeUnavailable("YouTube could not be reached.", kind="unreachable") from None


def _refused(response: httpx.Response) -> YouTubeUnavailable:
    reason = _reason(response)
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"):
        return YouTubeUnavailable("The YouTube key's allowance for today is used up; it resets overnight.", kind="quota")
    if response.status_code in (400, 401, 403) and reason in ("keyInvalid", "keyExpired", "accessNotConfigured",
                                                                "forbidden", "ipRefererBlocked", "PERMISSION_DENIED",
                                                                "API_KEY_INVALID", "INVALID_ARGUMENT"):
        return YouTubeUnavailable("YouTube refused the server's key: it may be wrong, or the YouTube Data API is not "
                                  "switched on for it.", kind="rejected")
    return YouTubeUnavailable(f"YouTube said no ({response.status_code}).", kind="refused")


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise YouTubeUnavailable("YouTube answered with something that was not a list of videos.", kind="refused") from None
    return body if isinstance(body, dict) else {}


def _playable(item: dict[str, Any]) -> bool:
    """Whether a video from the videos list can play on one of the owner's screens."""
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    details = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
    if status.get("embeddable") is not True or status.get("privacyStatus") not in ("public", "unlisted"):
        return False
    rating = details.get("contentRating") if isinstance(details.get("contentRating"), dict) else {}
    if rating.get("ytRating") == "ytAgeRestricted":
        return False
    region = details.get("regionRestriction") if isinstance(details.get("regionRestriction"), dict) else {}
    allowed, blocked = region.get("allowed"), region.get("blocked")
    if isinstance(allowed, list) and REGION not in allowed:
        return False
    return not (isinstance(blocked, list) and REGION in blocked)


async def _details(ids: list[str], key: str, *, snippet: bool) -> dict[str, dict[str, Any]]:
    parts = "contentDetails,status" + (",snippet" if snippet else "")
    response = await _get(f"{API}/videos", {"part": parts, "id": ",".join(ids[:50]), "maxResults": "50"}, key=key)
    if response.status_code != 200:
        raise _refused(response)
    items = _json(response).get("items")
    out: dict[str, dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and VIDEO_ID.fullmatch(str(item.get("id") or "")):
            out[str(item["id"])] = item
    return out


async def search(query: str) -> list[Video]:
    """What YouTube finds for these words, best first, and only what can play on a screen: at
    most MAX_RESULTS. Needs the stored key."""
    words = " ".join(str(query or "").split())[:MAX_QUERY]
    if not words:
        raise YouTubeUnavailable("Say what to look for on YouTube.", kind="not_found")
    key = api_key()
    if not key:
        raise YouTubeUnavailable("Searching YouTube needs a YouTube key on the server, and there isn't one yet. "
                                 "A YouTube link plays without one.", kind="no_key")
    response = await _get(f"{API}/search", {
        "part": "snippet", "type": "video", "q": words, "maxResults": "12", "videoEmbeddable": "true",
        "videoSyndicated": "true", "regionCode": REGION, "relevanceLanguage": "en",
    }, key=key)
    if response.status_code != 200:
        raise _refused(response)
    found: list[tuple[str, str, str, bool]] = []
    items = _json(response).get("items")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ident = item.get("id") if isinstance(item.get("id"), dict) else {}
        snip = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        video = str(ident.get("videoId") or "")
        state = str(snip.get("liveBroadcastContent") or "none")
        if not VIDEO_ID.fullmatch(video) or state == "upcoming" or any(f[0] == video for f in found):
            continue
        found.append((video, _text(snip.get("title"), MAX_TITLE), _text(snip.get("channelTitle"), MAX_CHANNEL), state == "live"))
    if not found:
        return []
    details = await _details([f[0] for f in found], key, snippet=False)
    out: list[Video] = []
    for video, title, channel, live in found:
        item = details.get(video)
        if item is None or not _playable(item):
            continue
        duration = None if live else _duration((item.get("contentDetails") or {}).get("duration"))
        out.append(Video(id=video, title=title or "YouTube video", channel=channel, duration_s=duration, live=live))
        if len(out) == MAX_RESULTS:
            break
    return out


async def video(video_id: str, *, start: int = 0) -> Video:
    """One video by its id: its title and channel, and whether it can play on a screen. With
    the key, the Data API says; without it, YouTube's public oEmbed endpoint does."""
    if not VIDEO_ID.fullmatch(str(video_id or "")):
        raise YouTubeUnavailable("That is not a YouTube video.", kind="not_found")
    start = max(0, min(MAX_START_S, int(start or 0)))
    key = api_key()
    if key:
        item = (await _details([video_id], key, snippet=True)).get(video_id)
        if item is None:
            raise YouTubeUnavailable("YouTube has no public video at that link.", kind="not_found")
        if not _playable(item):
            raise YouTubeUnavailable("That video's owner doesn't let it play outside YouTube (or it's age-restricted "
                                     "or blocked in the UK), so it can't go on a screen.", kind="not_playable")
        snip = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        live = str(snip.get("liveBroadcastContent") or "none") == "live"
        return Video(id=video_id, title=_text(snip.get("title"), MAX_TITLE) or "YouTube video",
                     channel=_text(snip.get("channelTitle"), MAX_CHANNEL), live=live, start=start,
                     duration_s=None if live else _duration((item.get("contentDetails") or {}).get("duration")))
    response = await _get(OEMBED, {"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"})
    if response.status_code in (401, 403):
        raise YouTubeUnavailable("That video's owner doesn't let it play outside YouTube, so it can't go on a screen.",
                                 kind="not_playable")
    if response.status_code in (400, 404):
        raise YouTubeUnavailable("YouTube has no public video at that link.", kind="not_found")
    if response.status_code != 200:
        raise YouTubeUnavailable(f"YouTube said no ({response.status_code}).", kind="refused")
    body = _json(response)
    return Video(id=video_id, title=_text(body.get("title"), MAX_TITLE) or "YouTube video",
                 channel=_text(body.get("author_name"), MAX_CHANNEL), duration_s=None, start=start)
