"""What WhatsApp's and Instagram's webhooks have in common: both are Meta's, and Meta checks and signs
them the same way (developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/
create-webhook-endpoint; /documentation/instagram-platform/webhooks).

Why it exists: the public door (app/routes/hooks.py) lets Meta's servers reach CLIVE, so anything
claiming to be Meta must prove it before CLIVE reads a word of it. One place does that for both
channels, so they cannot drift apart.

What it promises:
- GET (Meta's check when the callback URL is saved): answered with hub.challenge only when
  hub.mode is "subscribe" and hub.verify_token equals the stored verify token, compared in
  constant time, and only when the challenge is short and plain (it is echoed as text).
- POST: the X-Hub-Signature-256 header must be "sha256=" and the HMAC-SHA256 of the raw body under
  the app's secret, compared in constant time, before the body is decoded or parsed at all.
- The body must then be strict UTF-8 JSON, one object, for the right kind of object; anything else,
  JSON nested past what the parser takes included, is refused, never an error.
- Meta signs the body only, with no timestamp, and retries a delivery that was not answered with a
  200 for up to seven days (WhatsApp) or 36 hours (Instagram). So an old request is not refused:
  the same body seen again within the guard's memory is answered and dropped, and each message is
  stored once by its own id (app/messaging/store.py), so a replay changes nothing.
- Nothing a request carried is logged; a refusal is counted by kind (app/messaging/guard.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Iterable, Mapping
from typing import Any

from app.messaging.adapter import Inbound, Refused
from app.messaging.guard import GUARD

# Meta: "Webhook payloads can be up to 3 MB" (they batch up to 1,000 updates). A smaller cap would
# refuse a real batch, which Meta would then retry for days and never deliver.
MAX_BODY_BYTES = 3 * 1024 * 1024
SIGNATURE_HEADER = "x-hub-signature-256"
_SIGNATURE = re.compile(r"^sha256=([0-9a-fA-F]{64})$")
# Meta's challenge is a number ("1158201444"); anything longer or stranger is not echoed.
_CHALLENGE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def signature(secret: str, body: bytes) -> str:
    """The header Meta sends with `body` when `secret` is the app's secret."""
    return "sha256=" + hmac.new(str(secret).encode("utf-8"), bytes(body), hashlib.sha256).hexdigest()


def header(headers: Mapping[str, str] | None, name: str) -> str:
    """One header, whatever its case, or ""."""
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == wanted:
            return str(value or "")
    return ""


def signed(given: str, body: bytes, secrets: Iterable[str]) -> bool:
    """Whether `given` is "sha256=<hex>" of `body` under one of `secrets`. Every secret is tried, so
    the time taken never says which one matched or how far a guess got."""
    found = _SIGNATURE.match(str(given or "").strip())
    if not found:
        return False
    claimed = found.group(1).lower().encode("ascii")
    ok = False
    for secret in secrets:
        if secret:
            expected = hmac.new(str(secret).encode("utf-8"), bytes(body), hashlib.sha256).hexdigest().encode("ascii")
            ok = hmac.compare_digest(expected, claimed) or ok
    return ok


def challenge(query: Mapping[str, str], verify_token: str) -> str:
    """Meta's GET check: the challenge to echo, or Refused."""
    mode = str(query.get("hub.mode") or "")
    given = str(query.get("hub.verify_token") or "")
    asked = str(query.get("hub.challenge") or "")
    if mode != "subscribe" or not given or not asked:
        raise Refused("unsigned")
    if not verify_token or not hmac.compare_digest(given.encode("utf-8"), str(verify_token).encode("utf-8")):
        raise Refused("verify_token")
    if not _CHALLENGE.match(asked):
        raise Refused("unreadable")
    return asked


def payload(body: bytes, kind: str) -> dict[str, Any]:
    """The signed body as Meta's JSON object for `kind` ("whatsapp_business_account", "instagram"),
    or Refused. Strict UTF-8, one object, a bounded parse."""
    try:
        text = bytes(body or b"").decode("utf-8").strip()
    except UnicodeDecodeError:
        raise Refused("unreadable") from None
    if not text.startswith("{"):
        raise Refused("unreadable")
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        raise Refused("unreadable") from None
    if not isinstance(data, dict) or data.get("object") != kind or not isinstance(data.get("entry"), list):
        raise Refused("unreadable")
    return data


def check(channel: str, method: str, query: Mapping[str, str], body: bytes, headers: Mapping[str, str] | None, *,
          verify_token: str, secrets: Iterable[str], kind: str) -> Inbound:
    """A request at a Meta channel's door, verified in this order: the verify token (GET) or the
    signature (POST) first, then the body, then whether it was seen already. Raises Refused."""
    if method == "GET":
        return Inbound(channel=channel, echo=challenge(query, verify_token))
    given = header(headers, SIGNATURE_HEADER)
    if not given:
        raise Refused("unsigned")
    if not signed(given, body, secrets):
        raise Refused("signature")
    data = payload(body, kind)
    now = time.time()
    key = f"{channel}|{hashlib.sha256(bytes(body)).hexdigest()}"
    if not GUARD.first_time(key, now):
        return Inbound(channel=channel, key=key, timestamp=now, fields={"_repeat": "1"})
    return Inbound(channel=channel, key=key, timestamp=now, payload=data)


def items(value: Any) -> list[dict[str, Any]]:
    """The objects in a JSON list, or none: Meta's payloads are read defensively, field by field."""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def text(value: Any, limit: int = 4096) -> str:
    return str(value or "")[:limit]
