"""Shopify admin session tokens (App Bridge), checked on every admin API call.

The same check CROOKS Returns uses (returns/admin.py): HS256 with the app secret, for this
app (aud), for this shop (dest), inside its validity window. Sister apps share the pattern,
not the code.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlparse

LEEWAY_S = 10


class BadToken(Exception):
    pass


def _b64(part: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    except (binascii.Error, ValueError) as exc:
        raise BadToken("not base64") from exc


def verify_session_token(
    token: str, *, client_id: str, secret: str, shop_domain: str, now: float | None = None
) -> dict[str, Any]:
    """Check a Shopify admin session token: HS256 with the app secret, for this app, for this
    shop, inside its validity window. Returns its claims."""
    parts = token.split(".")
    if len(parts) != 3 or not secret:
        raise BadToken("malformed")
    try:
        header = json.loads(_b64(parts[0]))
        claims = json.loads(_b64(parts[1]))
    except ValueError as exc:
        raise BadToken("malformed") from exc
    if header.get("alg") != "HS256":
        raise BadToken("wrong algorithm")
    want = hmac.new(secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(want, _b64(parts[2])):
        raise BadToken("bad signature")
    now = time.time() if now is None else now
    if float(claims.get("exp", 0)) < now - LEEWAY_S:
        raise BadToken("expired")
    if float(claims.get("nbf", 0)) > now + LEEWAY_S:
        raise BadToken("not yet valid")
    aud = claims.get("aud")
    if client_id not in (aud if isinstance(aud, list) else [aud]):
        raise BadToken("for another app")
    if urlparse(str(claims.get("dest", ""))).hostname != shop_domain:
        raise BadToken("for another shop")
    return claims
