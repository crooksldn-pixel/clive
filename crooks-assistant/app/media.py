"""Product images for the tablet, by way of the Mac.

The tablet never loads a Shopify CDN URL itself. The Mac chooses which image a card shows,
signs that choice, and serves the bytes from a same-origin path. The path names the image
and the size; the signature is over both, with a key this process made up at boot, so the
route can only ever fetch what a card was built with. There is no general proxy here: a
URL that is not on Shopify's CDN is refused before it is signed, and a signature that does
not verify is a 404 before any request leaves the Mac.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

# Shopify serves product images from here and nowhere else. The check is on the host as
# parsed, never on a substring: "cdn.shopify.com.evil.example" is not on the list.
ALLOWED_HOSTS = frozenset({"cdn.shopify.com"})
ALLOWED_SUFFIXES = (".shopifycdn.com",)
# The sizes a card may ask for. The Tab A shows a thumbnail at 64 px on a 1.5x screen; the
# largest is for a product card, and is still a fraction of the original.
WIDTHS = frozenset({160, 320, 640})
DEFAULT_WIDTH = 160
MAX_URL_CHARS = 600
PATH_PREFIX = "/media/shopify/"



def _load_key() -> bytes:
    """The signing key: stored so image paths stay valid across a restart and the tablet's own
    image cache keeps its thumbnails. The Mac keeps it in the login Keychain, the server in its
    root-only secret directory; both persist it, so a restart no longer silently invalidates
    every thumbnail the tablet holds.

    Where there is no store at all — the test suite, or a process outside the login session —
    this falls back to a key for this process only. That is still safe: the paths it signs are
    valid while it runs, and a restart simply means fresh ones."""
    try:
        from app.secrets import keychain

        stored = keychain.get_optional("media_signing_key")
        if stored and len(stored) >= 32:
            return stored.encode("utf-8")
        fresh = secrets.token_hex(32)
        keychain.set_secret("media_signing_key", fresh)
        return fresh.encode("utf-8")
    except Exception:  # noqa: BLE001 — no keychain here
        return secrets.token_bytes(32)


_KEY = _load_key()


def allowed_url(url: object) -> str | None:
    """The URL as a string, if and only if it is an https image location on Shopify's CDN."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    host = parts.hostname.lower().rstrip(".")
    if host not in ALLOWED_HOSTS and not any(host.endswith(suffix) for suffix in ALLOWED_SUFFIXES):
        return None
    if parts.hostname.endswith(".") or host.startswith("."):
        return None   # "cdn.shopify.com." resolves the same but is not the name on the list
    if parts.username or parts.password or parts.port not in (None, 443):
        return None
    return url


def signature(url: str, width: int) -> str:
    return hmac.new(_KEY, f"{width}\n{url}".encode(), hashlib.sha256).hexdigest()[:32]


def signed_path(url: object, width: int = DEFAULT_WIDTH) -> str | None:
    """The same-origin path a card carries for an image, or None when the URL is not one
    the Mac will serve. Width is one of a few; anything else is the default."""
    allowed = allowed_url(url)
    if allowed is None:
        return None
    width = width if width in WIDTHS else DEFAULT_WIDTH
    return f"{PATH_PREFIX}{signature(allowed, width)}/{width}?u={quote(allowed, safe='')}"


def verify(sig: str, width: int, url: str) -> bool:
    """Constant-time: a wrong signature costs the same as a right one to check."""
    if not isinstance(sig, str) or width not in WIDTHS or allowed_url(url) is None:
        return False
    return hmac.compare_digest(sig, signature(url, width))


def sized(url: str, width: int) -> str:
    """Shopify's CDN resizes on request: `width=` on the query string. The original is never
    fetched at full size for a 64-pixel thumbnail. A width already on the URL is replaced,
    not doubled."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in ("width", "height")]
    query.append(("width", str(int(width))))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
