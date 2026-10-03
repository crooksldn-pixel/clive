"""A live test of a key before it replaces the one in use: the service is asked, with the new key,
the smallest question that only a working key can answer. A key that fails is never stored.

What each asks (read-only, and spending nothing):
  ElevenLabs   GET /models, as the voice's own health probe does (app/clients/elevenlabs.py)
  YouTube      GET /videos for one public video, the key in the X-Goog-Api-Key header
  Shopify      the client-credentials token request for this shop; the token minted is dropped
  GitHub       GET /repos/<the clive repository>, which says whether the token may write there
  Instagram    GET /me with the token, which names the account it reads
  Ship24       GET /trackers?limit=1, which lists trackers and creates none, so it spends none of
               a per-shipment plan's shipments; per-call plans count only /tracking/search, which
               this never calls (app/clients/ship24.py has the docs relied on)

The key goes in a header or a request body, never in an address. What comes back is described
in our own words; nothing a service wrote is quoted, and no key appears in any detail.

A failed test also says what would put it right (`fix`), so the screen offers that one thing and
no other: "key" (the service refused the key itself: paste a new one), "service" (the key is
good, something is to be changed at the service: then check again) or "retry" (the service did
not answer, or is limiting requests: nothing is wrong with the key, check again).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

TIMEOUT_S = 10.0
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_PROBE_VIDEO = "jNQXAC9IVRw"     # "Me at the zoo": public since 2005
GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class Outcome:
    ok: bool
    detail: str
    who: str = ""            # the account the key belongs to, when the service says
    checked: bool = True     # False: nothing to ask until the owner signs in
    fix: str = ""            # a failure's remedy: "key", "service" or "retry" (empty: "key")

    def as_dict(self) -> dict[str, Any]:
        out = {"ok": self.ok, "detail": self.detail, "who": self.who, "checked": self.checked}
        if not self.ok:
            out["fix"] = self.fix or "key"
        return out


def http_client() -> httpx.AsyncClient:
    """Patched in tests; no redirects followed, so a key is never carried to another host."""
    return httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False)


def _scrub(text: str, values: dict[str, str]) -> str:
    for value in values.values():
        if value and len(value) >= 6:
            text = text.replace(value, "[the key]")
    return text


async def _elevenlabs(values: dict[str, str], settings: Any) -> Outcome:
    base = str(getattr(settings, "elevenlabs_base_url", "") or "https://api.elevenlabs.io/v1").rstrip("/")
    async with http_client() as client:
        response = await client.get(f"{base}/models", headers={"xi-api-key": values["elevenlabs_api_key"]})
    body = (response.text or "").lower()
    if response.status_code == 200:
        return Outcome(True, "ElevenLabs accepted the key.")
    if "missing_permissions" in body or response.status_code == 403:
        return Outcome(True, "ElevenLabs accepted the key. It is limited to some products, which is fine "
                             "if it covers speech-to-text and text-to-speech.")
    if response.status_code == 401:
        return Outcome(False, "ElevenLabs refused that key. Check you copied all of it.")
    return Outcome(False, f"ElevenLabs answered {response.status_code}; nothing was changed.", fix="retry")


async def _youtube(values: dict[str, str], settings: Any) -> Outcome:
    async with http_client() as client:
        response = await client.get(f"{YOUTUBE_API}/videos", params={"part": "id", "id": YOUTUBE_PROBE_VIDEO},
                                    headers={"X-Goog-Api-Key": values["youtube_api_key"]})
    body = (response.text or "").lower()
    if response.status_code == 200:
        return Outcome(True, "Google accepted the key for YouTube.")
    if "api key not valid" in body or "api_key_invalid" in body:
        return Outcome(False, "Google says that is not a valid API key.")
    if "accessnotconfigured" in body or "has not been used" in body or "service_disabled" in body:
        return Outcome(False, "The key works, but the YouTube Data API is not switched on in its Google "
                              "Cloud project. Enable it there, then try again.", fix="service")
    if response.status_code == 403:
        return Outcome(False, "Google refused the key for YouTube: it may be restricted to other APIs or "
                              "to other addresses.", fix="service")
    return Outcome(False, f"Google answered {response.status_code}; nothing was changed.", fix="retry")


async def _shopify(values: dict[str, str], settings: Any) -> Outcome:
    shop = str(getattr(settings, "shopify_shop_domain", "") or "").strip()
    if not shop.endswith(".myshopify.com"):
        return Outcome(False, "No shop is set on the server (CROOKS_SHOPIFY_SHOP_DOMAIN).", fix="service")
    async with http_client() as client:
        response = await client.post(f"https://{shop}/admin/oauth/access_token", json={
            "client_id": values["shopify_client_id"], "client_secret": values["shopify_client_secret"],
            "grant_type": "client_credentials"})
    body = (response.text or "").lower()
    if response.status_code == 200 and "access_token" in body:
        return Outcome(True, f"Shopify accepted the app's ID and secret for {shop}.", who=shop)
    if "shop_not_permitted" in body:
        return Outcome(False, "Shopify says this app belongs to another organisation than the shop. "
                              "Make the app in the shop's own organisation.", fix="service")
    if response.status_code in (400, 401, 403):
        return Outcome(False, f"Shopify refused that ID and secret for {shop}. Check the app is "
                              "released and installed on the shop.")
    return Outcome(False, f"Shopify answered {response.status_code}; nothing was changed.", fix="retry")


async def _github(values: dict[str, str], settings: Any) -> Outcome:
    from app.engineering_bridge.github import DEFAULT_REPOSITORY

    repository = DEFAULT_REPOSITORY
    async with http_client() as client:
        response = await client.get(f"{GITHUB_API}/repos/{repository}", headers={
            "Authorization": f"Bearer {values['github_engineering_inbox_token']}",
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    if response.status_code == 401:
        return Outcome(False, "GitHub refused that token. It may have expired or been copied short.")
    if response.status_code == 404:
        return Outcome(False, f"That token cannot see {repository}. Give it that repository.", fix="service")
    if response.status_code != 200:
        return Outcome(False, f"GitHub answered {response.status_code}; nothing was changed.", fix="retry")
    try:
        allowed = response.json().get("permissions") or {}
    except (ValueError, AttributeError):
        allowed = {}
    if not allowed.get("push"):
        return Outcome(False, f"That token can read {repository} but not write to it. Give it Contents: "
                              "read and write.", fix="service")
    return Outcome(True, f"GitHub accepted the token for {repository}.", who=repository)


async def _instagram(values: dict[str, str], settings: Any, changed: frozenset[str] = frozenset()) -> Outcome:
    from app.clients import instagram

    # The app's ID and secret cannot be asked about on their own; they are proved at sign-in. Only
    # a token that is being stored, or tested, is asked about here.
    token = values.get("instagram_access_token") or ""
    if not token or (changed and "instagram_access_token" not in changed):
        return Outcome(True, "Kept. They are checked when you sign in with Instagram.", checked=False)
    version = str(getattr(settings, "instagram_api_version", "") or instagram.DEFAULT_VERSION)
    url, params = f"{instagram.HOST}/{version}/me", {"fields": "user_id,username"}
    async with http_client() as client:
        response = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        if response.status_code != 200 and instagram._header_not_accepted(response):
            # As the client itself does (app/clients/instagram.py get): an API that will not read
            # the header is asked once with the token as a parameter, never logged.
            response = await client.get(url, params={**params, "access_token": token})
    if response.status_code == 200:
        try:
            name = str(response.json().get("username") or "").strip()
        except (ValueError, AttributeError):
            name = ""
        who = f"@{name}" if name else ""
        return Outcome(True, f"Instagram accepted the token{f' for {who}' if who else ''}.", who=who)
    refused = instagram._refusal(response)
    reasons = {
        "token": "Instagram refused that token: it has expired, or it was copied short.",
        "permission": "Instagram accepted the token but it lacks a permission CLIVE needs.",
        "rate_limited": "Instagram is limiting requests just now. Try again in a few minutes.",
    }
    fixes = {"permission": "service", "rate_limited": "retry"}
    return Outcome(False, reasons.get(refused.kind, "Instagram refused that token; nothing was changed."),
                   fix=fixes.get(refused.kind, "key"))


async def _ship24(values: dict[str, str], settings: Any) -> Outcome:
    from app.clients import ship24

    async with http_client() as client:
        response = await client.get(f"{ship24.API}/trackers", params={"limit": "1"}, headers={
            "Authorization": f"Bearer {values['ship24_api_key']}", "Accept": "application/json"})
    if response.status_code == 200:
        return Outcome(True, "Ship24 accepted the key.")
    if response.status_code == 401:
        return Outcome(False, "Ship24 refused that key. Check you copied all of it (Ship24's keys start apik_).")
    if ship24.refusal(response).kind == "no_plan":
        # The key is genuine (a bad one is a 401); it is only not on a per-shipment plan. Whether it
        # is on a per-call one could be learned only by spending a call, so it is not asked here.
        return Outcome(True, "Ship24 accepted the key, but says it has no per-shipment plan. If it is on a "
                             "per-call plan, CLIVE uses that and each look-up counts as one call; if it has no "
                             "plan, choose one at dashboard.ship24.com → Subscriptions.")
    if response.status_code == 429:
        return Outcome(False, "Ship24 is limiting requests just now. Try again in a minute.", fix="retry")
    return Outcome(False, f"Ship24 answered {response.status_code}; nothing was changed.", fix="retry")


TESTERS = {
    "elevenlabs": _elevenlabs,
    "youtube": _youtube,
    "shopify": _shopify,
    "github": _github,
    "instagram": _instagram,
    "ship24": _ship24,
}


async def run(name: str, values: dict[str, str], settings: Any, *, changed: frozenset[str] = frozenset()) -> Outcome:
    """Ask the service with `values` (`changed`: the keys being stored now; empty when testing what is
    stored). Never raises: an unreachable service is a failed test, so a key that could not be
    checked is not stored."""
    tester = TESTERS.get(name)
    if tester is None:
        return Outcome(False, "This connection cannot be set from the app yet.")
    try:
        outcome = await (tester(values, settings, changed) if name == "instagram" else tester(values, settings))
    except httpx.TimeoutException:
        return Outcome(False, "The service did not answer in time; nothing was changed. Try again.", fix="retry")
    except httpx.HTTPError:
        return Outcome(False, "The service could not be reached from the server; nothing was changed.", fix="retry")
    except KeyError:
        return Outcome(False, "Fill in every field for this connection.")
    return Outcome(outcome.ok, _scrub(outcome.detail, values), _scrub(outcome.who, values), outcome.checked,
                   outcome.fix)
