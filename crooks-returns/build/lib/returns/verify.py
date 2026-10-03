"""Proving a customer owns an order, without accounts: the order number plus one thing only
the buyer knows (email, postcode or phone). Failures all read the same, attempts are limited
per order and per address, and a success returns a short-lived signed session."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import time
from collections import defaultdict, deque

from returns.models import Order

NOT_FOUND = "We couldn't find an order matching those details. Check them and try again."
LOCKED = "Too many attempts. Please wait a few minutes and try again."


def normalise_order_number(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    return digits or None


def normalise_email(raw: str | None) -> str:
    return (raw or "").strip().casefold()


def normalise_postcode(raw: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def normalise_phone(raw: str | None) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("44"):
        digits = "0" + digits[2:]
    # The last ten digits identify a UK number however it was written (+44, 0044, 07…).
    return digits[-10:]


def proof_matches(order: Order, proof: str) -> bool:
    proof = (proof or "").strip()
    if not proof:
        return False
    if "@" in proof:
        given = normalise_email(proof)
        return any(
            given and given == normalise_email(e) for e in (order.email, order.customer_email)
        )
    phone = normalise_phone(proof)
    if len(phone) >= 9 and any(
        phone == normalise_phone(p)
        for p in (order.phone, order.customer_phone, order.shipping_phone, order.billing_phone)
        if p
    ):
        return True
    postcode = normalise_postcode(proof)
    return bool(postcode) and any(
        postcode == normalise_postcode(z) for z in (order.shipping_zip, order.billing_zip) if z
    )


class RateLimiter:
    """Sliding-window attempt counter, in memory: one process serves the portal."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def blocked(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window_s:
                hits.popleft()
            return len(hits) >= self.limit

    def hit(self, key: str, now: float | None = None) -> None:
        with self._lock:
            self._hits[key].append(time.time() if now is None else now)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, secret: str) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def unsign(token: str, secret: str, now: float | None = None) -> dict | None:
    try:
        body, mac = token.split(".", 1)
        want = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(want, _unb64(mac)):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if payload.get("exp", 0) < (time.time() if now is None else now):
        return None
    return payload


def session_for(order_id: str, secret: str, ttl_s: int) -> str:
    return sign({"kind": "session", "order": order_id, "exp": int(time.time()) + ttl_s}, secret)


def order_from_session(token: str, secret: str) -> str | None:
    payload = unsign(token or "", secret)
    if not payload or payload.get("kind") != "session":
        return None
    return payload.get("order")
