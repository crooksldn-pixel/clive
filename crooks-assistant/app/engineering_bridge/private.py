"""CLIVE's read of the build server's private channel: why each stopped build stopped, in full.

The repository is public (since 7 October 2026), so the loop publishes counts and states on GitHub and
keeps the reviewer's findings, the failing output and the builder's own report back. It serves them
from the build server itself, over the tailnet, to the machines its operator names
(app/remote_engineering/private.py, ``GET /v1/stops``). This module is the reading end, for the owner's
Builds screen (app/builds/read.py):

- **Off unless named.** ``CROOKS_ENGINEERING_PRIVATE_URL`` (config/settings.py) is the server's address,
  ``http://<tailnet address>:<port>``. Unset, "off", or anything but a plain http address on the tailnet
  (100.64.0.0/10, fd7a:115c:a1e0::/48) or loopback is off: nothing is asked, and the screen says the
  findings are kept on the build server, as before. Nothing goes over the public internet: Tailscale
  carries it, encrypted, and the server answers only the machines it was told to.
- **Read sparingly, kept, never guessed.** At most once a minute, like the loop's status; a failed read
  keeps the last answer and says why, in a fixed sentence (no URL, no body, no server text).
- **Bounded and checked.** The answer is one JSON document of the server's schema, at most 2 MB; each stop is
  keyed by its request id. Its text was redacted by the server (credentials, customer shapes); the screen's
  own translators (app/builds/plain.py) bound and redact it again before it is drawn, with textContent.
- **Read-only.** One GET; nothing is sent but the request line, and nothing is logged of what came back.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import time
from typing import Any

import httpx

log = logging.getLogger("crooks.engineering")

SCHEMA = "clive.remote_engineering_private.v1"
PATH = "/v1/stops"
OFF = "off"
TTL_S = 60.0
TIMEOUT_S = 5.0
MAX_BYTES = 2 * 1024 * 1024
MAX_STOPS = 200

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
_URL = re.compile(r"^http://(?:(?P<v4>[0-9.]{7,15})|\[(?P<v6>[0-9a-fA-F:.]{2,45})\]):(?P<port>\d{1,5})/?$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")

UNREADABLE = "The build server's private findings could not be read just now, so the reviewer's words may be missing."
NOT_ITS_SCHEMA = "The build server's private findings were not in the shape CLIVE reads, so they are not shown."

# The server's address (None: off) and the last answer, changed in place (a test harness puts it back whole).
_STATE: dict[str, Any] = {"base": None}


def parse_url(value: object) -> str | None:
    """The base address the setting names, or None when it is off or not a tailnet (or loopback) http address."""
    text = str(value or "").strip()
    if not text or text.lower() == OFF:
        return None
    match = _URL.fullmatch(text)
    if match is None:
        return None
    try:
        ip = ipaddress.ip_address(match.group("v4") or match.group("v6"))
    except ValueError:
        return None
    port = int(match.group("port"))
    if not (ip in TAILNET_V4 or ip in TAILNET_V6 or ip.is_loopback) or not 1 <= port <= 65535:
        return None
    return text.rstrip("/")


def configure(url: object) -> None:
    """Bind the reader to CROOKS_ENGINEERING_PRIVATE_URL. A value that is set but refused is said in the log by
    what it is not, never echoed; the reader stays off."""
    _STATE.clear()
    _STATE["base"] = parse_url(url)
    if _STATE["base"] is None and str(url or "").strip().lower() not in ("", OFF):
        log.warning("CROOKS_ENGINEERING_PRIVATE_URL is not http://<tailnet or loopback address>:<port>; "
                    "the build server's private findings stay off")


def configured() -> bool:
    return _STATE.get("base") is not None


def _stops_of(document: object) -> dict[str, dict[str, Any]] | None:
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA:
        return None
    listed = document.get("stops")
    if not isinstance(listed, list):
        return None
    out: dict[str, dict[str, Any]] = {}
    for stop in listed[:MAX_STOPS]:
        rid = stop.get("request_id") if isinstance(stop, dict) else None
        if isinstance(rid, str) and _ID.fullmatch(rid):
            out[rid] = stop
    return out


async def _get(transport: httpx.AsyncBaseTransport | None) -> tuple[dict[str, dict[str, Any]] | None, str]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False, transport=transport,
                                     trust_env=False) as client:
            async with client.stream("GET", f"{_STATE['base']}{PATH}") as response:
                if response.status_code != 200:
                    return None, UNREADABLE
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        return None, NOT_ITS_SCHEMA
    except (httpx.HTTPError, OSError):
        return None, UNREADABLE
    try:
        stops = _stops_of(json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, ValueError, RecursionError):
        stops = None
    return (stops, "") if stops is not None else (None, NOT_ITS_SCHEMA)


async def stops(*, transport: httpx.AsyncBaseTransport | None = None) -> tuple[dict[str, dict[str, Any]] | None, str]:
    """(each stopped build's full record by request id, a problem sentence or ""). (None, "") when the reader is
    off. Asked at most once a minute; a failed read keeps the last answer it had, with the sentence saying so."""
    if _STATE.get("base") is None:
        return None, ""
    now = time.monotonic()
    if _STATE.get("at") is not None and now - _STATE["at"] < TTL_S:
        return _STATE.get("stops"), _STATE.get("problem", "")
    found, problem = await _get(transport)
    _STATE["at"] = now
    if found is not None:
        _STATE.update(stops=found, problem="")
    else:
        log.info("the build server's private channel did not answer usably")
        _STATE["problem"] = problem
    return _STATE.get("stops"), _STATE["problem"]


def reset() -> None:
    """Forget what was read (a test, or a different server bound); the address stays."""
    base = _STATE.get("base")
    _STATE.clear()
    _STATE["base"] = base
