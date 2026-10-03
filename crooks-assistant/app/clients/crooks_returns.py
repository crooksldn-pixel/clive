"""CROOKS Returns, the owner's own returns service, as CLIVE reads it and acts through it.

The service is George's: built and deployed by him on 3 October 2026, outside CLIVE's engineering
kernel, in its own container on the production host (https://returns.crooksldn.com; its code is on
branch claude/compassionate-dirac-44hnee, crooks-returns/). Shopify stays the record of every
return; the service adds the request before Shopify knows of it, the customer's choices, the label,
the timeline and what needs attention. Its contract is its own `returns/api.py`, `/api/v1`.

What this client promises:

- The key travels in the Authorization header as `Bearer <key>`, never in an address, and
  redirects are never followed, so a key never reaches another host. Reads carry the read key
  (or the write key when only that is stored: a write key can read); only an action George has
  approved carries the write key. Both are read from the secret store at each call, so a key
  stored on the Connections screen works at once.
- Every call has a timeout, and every failure is one ReturnsUnavailable with a `kind` and words
  George can be told. What the service says back is put in words here; a detail it gives is
  bounded, and anything in it shaped like an email address, a phone number or a postcode is
  taken out before it goes anywhere. Nothing here logs a key, a return or a customer's detail:
  the one log line names a kind and a status code.
- Money is integer pence everywhere, as the service gives it; `pounds()` is the one place it
  becomes "£12.50".
- Only the service's own actions change anything: preview first (it changes nothing), and an
  execute with a fresh idempotency key that the service scopes to that return and action, so a
  retried request never repeats a refund or a label. Never the customers' portal (/proxy/api/*),
  never the service's database, never Shopify's return mutations.
- The open returns are asked for at most once a minute and only when something CLIVE is showing
  needs them (no timer runs); after the first whole read, `?since=` asks only for what changed.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from app.secrets import keychain

log = logging.getLogger("crooks.returns")

DEFAULT_BASE_URL = "https://returns.crooksldn.com"
READ_KEY = "crooks_returns_read_key"
WRITE_KEY = "crooks_returns_write_key"
NAME = "CROOKS Returns"
NOT_CONNECTED = "not connected — add the CROOKS Returns keys on the Connections screen"

READ_TIMEOUT_S = 8.0
# A preview of a label prices it at Parcel2Go; an action may buy one and then wait on Shopify.
PREVIEW_TIMEOUT_S = 20.0
EXECUTE_TIMEOUT_S = 60.0
MAX_DETAIL = 200
OPEN_CACHE_S = 60.0          # the open returns are asked for at most once a minute
FULL_READ_EVERY_S = 600.0    # and read whole again every ten, with ?since= between
MAX_LIST = 500

RETURN_ID = re.compile(r"^ret_[0-9a-f]{6,40}$")
ACTIONS = ("approve", "decline", "label", "tracking", "receive", "complete", "cancel", "note")
# The person an action is taken for, as the service writes it on the return's timeline.
ACTOR = "clive for George"

_SETTINGS = {"base_url": DEFAULT_BASE_URL}


class ReturnsUnavailable(RuntimeError):
    """The returns service could not do this, said as George can be told it. `kind`: no_key,
    rejected (a key refused), not_found, refused (the service said no, and why), rate_limited,
    trouble (it is failing), timeout, unreachable, invalid. `refused` is True when the service
    answered and nothing was changed, which the action engine reads to say so. `key` names the
    stored key that was refused, when one was."""

    # Its words are written to be said as they are (app/actions/engine.py `_refusal_words`).
    plain_words = True

    def __init__(self, said: str, *, kind: str, status: int = 0, key: str = "") -> None:
        super().__init__(said)
        self.kind = kind
        self.status = status
        self.key = key
        # The service answered (or CLIVE could not ask it at all) and nothing was changed.
        self.refused = kind in ("refused", "rejected", "not_found", "invalid", "no_key")


# ------------------------------------------------------------------ where, and with which key


def configure(*, base_url: str) -> None:
    """Called by the runtime with the setting (CROOKS_RETURNS_BASE_URL)."""
    _SETTINGS["base_url"] = clean_base(base_url)


def clean_base(value: Any) -> str:
    """The address to reach the service at: https only, since every request carries a key. Anything
    else (plain http, no scheme) is not used, and the service's own address is, with a warning."""
    text = str(value or "").strip().rstrip("/")
    if text.lower().startswith("https://") and len(text) > len("https://"):
        return text
    if text and text != DEFAULT_BASE_URL:
        log.warning("returns: CROOKS_RETURNS_BASE_URL is not an https:// address, so %s is used", DEFAULT_BASE_URL)
    return DEFAULT_BASE_URL


def base_url() -> str:
    return _SETTINGS["base_url"]


def _stored(name: str) -> str:
    try:
        return (keychain.get_optional(name) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has no key to give
        return ""


def read_key() -> str:
    """The key reads (and previews, which change nothing) carry. Only the read key: the service
    would let the write key read too, but the key that can act is sent with nothing but an action
    the owner approved, so with only that stored, returns read as not connected."""
    return _stored(READ_KEY)


def write_key() -> str:
    return _stored(WRITE_KEY)


def http_client(timeout_s: float) -> httpx.AsyncClient:
    """A client for one call; looked up per call so a test can put a transport in its place."""
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False)


# ------------------------------------------------------------------ money and words


def pence(value: Any) -> int | None:
    """Integer pence, as the service gives money; anything else is None, never a guess."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def pounds(value: Any) -> str:
    """12550 -> "£125.50"; -300 -> "-£3.00"; not integer pence -> ""."""
    amount = pence(value)
    if amount is None:
        return ""
    sign = "-" if amount < 0 else ""
    whole, part = divmod(abs(amount), 100)
    return f"{sign}£{whole:,}.{part:02d}"


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d ()-]{8,}\d")
_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)


def scrub(text: Any, limit: int = MAX_DETAIL) -> str:
    """A detail the service wrote, fit to be said: one line, bounded, and without anything shaped
    like an email address, a phone number or a UK postcode (a courier's refusal can echo the
    address it was given)."""
    words = " ".join(str(text or "").split())
    words = _EMAIL.sub("[email]", words)
    words = _POSTCODE.sub("[postcode]", words)
    words = _PHONE.sub("[number]", words)
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def _detail(response: httpx.Response) -> str:
    """The service's own sentence for a refusal (FastAPI's `detail`), in plain words."""
    try:
        body = response.json()
    except ValueError:
        return ""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list):
        # A request the service could not read: the first thing it said was wrong.
        first = detail[0] if detail and isinstance(detail[0], dict) else {}
        where = ".".join(str(p) for p in (first.get("loc") or [])[1:])
        return scrub(f"{where}: {first.get('msg')}" if where else first.get("msg") or "")
    return scrub(detail) if isinstance(detail, str) else ""


def refusal(response: httpx.Response, *, key_name: str = READ_KEY) -> ReturnsUnavailable:
    """What a refused request means, in our words. Shared with the key's test on the Connections
    screen (app/connections/testers.py), so the two never describe one answer differently."""
    status = response.status_code
    said = _detail(response)
    if status == 401:
        return ReturnsUnavailable(f"{NAME} wants a key and was sent none it could read. Add the keys again on the "
                                  "Connections screen.", kind="rejected", status=status, key=key_name)
    if status == 403:
        if key_name == WRITE_KEY:
            return ReturnsUnavailable(f"{NAME} refused CLIVE's write key: it may read returns but not act on them. "
                                      "Paste the value of RETURNS_CLIVE_WRITE_KEYS on the Connections screen.",
                                      kind="rejected", status=status, key=WRITE_KEY)
        return ReturnsUnavailable(f"{NAME} refused CLIVE's key. Paste the value of RETURNS_CLIVE_READ_KEYS on the "
                                  "Connections screen.", kind="rejected", status=status, key=key_name)
    if status == 404:
        return ReturnsUnavailable(said or f"{NAME} has no such return.", kind="not_found", status=status)
    if status in (409, 422):
        return ReturnsUnavailable(said or f"{NAME} would not do that.", kind="refused", status=status)
    if status == 429:
        return ReturnsUnavailable(f"{NAME} asked CLIVE to slow down; try again in a moment.", kind="rate_limited",
                                  status=status)
    if status == 503:
        return ReturnsUnavailable(f"{NAME} couldn't reach Shopify just now; try again in a minute.", kind="trouble",
                                  status=status)
    if status >= 500:
        return ReturnsUnavailable(f"{NAME} is having trouble just now ({status}); try again shortly.", kind="trouble",
                                  status=status)
    return ReturnsUnavailable(f"{NAME} said no ({status}).", kind="refused", status=status)


# ------------------------------------------------------------------ the requests


async def _send(method: str, path: str, *, key: str, key_name: str, params: dict[str, Any] | None = None,
                body: dict[str, Any] | None = None, timeout_s: float = READ_TIMEOUT_S) -> httpx.Response:
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with http_client(timeout_s) as client:
            return await asyncio.wait_for(
                client.request(method, f"{base_url()}{path}", params=params, json=body, headers=headers), timeout_s)
    except (TimeoutError, httpx.TimeoutException):
        raise ReturnsUnavailable(f"{NAME} did not answer in time.", kind="timeout") from None
    except httpx.HTTPError:
        raise ReturnsUnavailable(f"{NAME} could not be reached.", kind="unreachable") from None


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise ReturnsUnavailable(f"{NAME} answered with something unreadable.", kind="trouble") from None
    if not isinstance(body, dict):
        raise ReturnsUnavailable(f"{NAME} answered with something unreadable.", kind="trouble")
    return body


async def _read(path: str, params: dict[str, Any] | None = None, *, timeout_s: float = READ_TIMEOUT_S) -> dict[str, Any]:
    key = read_key()
    if not key:
        raise ReturnsUnavailable(f"Returns are {NOT_CONNECTED}.", kind="no_key")
    response = await _send("GET", f"/api/v1{path}", key=key, key_name=READ_KEY, params=params, timeout_s=timeout_s)
    if response.status_code != 200:
        problem = refusal(response, key_name=READ_KEY)
        log.info("returns: a read was refused (%s, %s)", problem.kind, response.status_code)
        _note_refused_key(problem)
        raise problem
    return _json(response)


def return_id(value: Any) -> str:
    text = str(value or "").strip()
    if not RETURN_ID.fullmatch(text):
        raise ReturnsUnavailable("That isn't a CROOKS Returns id (they look like ret_ and ten letters and digits).",
                                 kind="invalid")
    return text


def order_digits(value: Any) -> str:
    """"2131", "#2131", "CROOKS-2131" and "crooks 2131" are one order: its number."""
    digits = re.sub(r"\D", "", str(value or ""))
    if not 1 <= len(digits) <= 10:
        raise ReturnsUnavailable("Give the order's number, like 2131.", kind="invalid")
    return digits


async def health() -> dict[str, Any]:
    """GET /health: no key. The service's policy and whether CLIVE's keys are set there."""
    response = await _send("GET", "/health", key="", key_name="", timeout_s=READ_TIMEOUT_S)
    if response.status_code != 200:
        raise refusal(response)
    return _json(response)


async def list_returns(*, open_only: bool = False, status: str = "", since: str = "", limit: int = 100) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": max(1, min(int(limit), MAX_LIST))}
    if open_only:
        params["open"] = "true"
    if status:
        params["status"] = status
    if since:
        params["since"] = since
    found = (await _read("/returns", params)).get("returns")
    return [r for r in found if isinstance(r, dict)] if isinstance(found, list) else []


async def get_return(value: Any) -> dict[str, Any]:
    return await _read(f"/returns/{return_id(value)}")


async def order_returns(order: Any) -> list[dict[str, Any]]:
    """The returns on one order. Asked by its name as the shop writes it (CROOKS-2131), which the
    service matches directly; it matches the bare number too."""
    digits = order_digits(order)
    found = (await _read(f"/orders/{quote('CROOKS-' + digits, safe='')}/returns")).get("returns")
    return [r for r in found if isinstance(r, dict)] if isinstance(found, list) else []


async def stats(since: str = "") -> dict[str, Any]:
    return await _read("/stats", {"since": since} if since else None)


async def preview(value: Any, action: str, params: dict[str, Any]) -> dict[str, Any]:
    """What an action would do, in the service's own words and pence. Changes nothing; a refusal
    here is a refusal of the action itself (the service checks the same rules)."""
    if action not in ACTIONS:
        raise ReturnsUnavailable(f"{NAME} has no action called that.", kind="invalid")
    key = read_key()
    if not key:
        raise ReturnsUnavailable(f"Returns are {NOT_CONNECTED}.", kind="no_key")
    response = await _send("POST", f"/api/v1/returns/{return_id(value)}/actions/{action}/preview", key=key,
                           key_name=READ_KEY, body={"params": dict(params)}, timeout_s=PREVIEW_TIMEOUT_S)
    if response.status_code != 200:
        problem = refusal(response, key_name=READ_KEY)
        _note_refused_key(problem)
        raise problem
    return _json(response)


async def execute(value: Any, action: str, params: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
    """Do it: only ever after George's approval (app/tools/returns_tools.py, through the action
    engine). A request that never got its answer is asked once more with the SAME key, which the
    service answers with the first outcome (`replayed`) rather than doing it twice."""
    if action not in ACTIONS:
        raise ReturnsUnavailable(f"{NAME} has no action called that.", kind="invalid")
    key = write_key()
    if not key:
        raise ReturnsUnavailable(f"{NAME} has no write key on this server, so CLIVE can only read returns. Add it on "
                                 "the Connections screen.", kind="no_key", key=WRITE_KEY)
    if not idempotency_key:
        raise ReturnsUnavailable("An action needs its own idempotency key.", kind="invalid")
    body = {"params": dict(params), "actor": ACTOR, "idempotency_key": idempotency_key}
    path = f"/api/v1/returns/{return_id(value)}/actions/{action}"
    try:
        response = await _send("POST", path, key=key, key_name=WRITE_KEY, body=body, timeout_s=EXECUTE_TIMEOUT_S)
    except ReturnsUnavailable as first:
        if first.kind not in ("timeout", "unreachable"):
            raise
        log.info("returns: an action got no answer (%s); asking once more with the same key", first.kind)
        response = await _send("POST", path, key=key, key_name=WRITE_KEY, body=body, timeout_s=EXECUTE_TIMEOUT_S)
    if response.status_code != 200:
        problem = refusal(response, key_name=WRITE_KEY)
        log.info("returns: an action was refused (%s, %s)", problem.kind, response.status_code)
        _note_refused_key(problem)
        raise problem
    return _json(response)


def _note_refused_key(problem: ReturnsUnavailable) -> None:
    """A key the service refused is the Connections screen's to show, with a box for that key: the
    same record a failed test leaves (app/connections/ledger.py). Never in the way of the answer."""
    if problem.kind != "rejected" or not problem.key:
        return
    try:
        from app.connections import ledger, testers

        ledger.tested("returns", testers.Outcome(False, str(problem), fix="key", refused=(problem.key,)).as_dict())
    except Exception:  # noqa: BLE001 - the refusal is said either way
        log.debug("returns: the refused key was not recorded for the Connections screen", exc_info=True)


# ------------------------------------------------------------------ the open returns, polled


@dataclass
class OpenReturns:
    """The open returns, kept for a minute. Asked for only when something needs them (the home's
    Needs you row, the returns_open tool), so nothing is polled while nobody is using CLIVE. The
    first read is whole; after it, `?since=` the newest change seen asks only for what changed,
    and a return that is no longer open leaves. Read whole again every ten minutes regardless.

    One read at a time (the callers that arrive while it is out wait for it and share its answer),
    and a read that failed is kept for the minute as an answer would be: the service is asked at
    most once a minute whatever it said, and a home drawn ten times while it is down asks once."""

    clock: Any = time.time
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    read_at: float = 0.0
    whole_at: float = 0.0
    watermark: str = ""
    failed: ReturnsUnavailable | None = None
    failed_at: float = 0.0
    _lock: asyncio.Lock | None = None

    def forget(self) -> None:
        self.rows, self.read_at, self.whole_at, self.watermark = {}, 0.0, 0.0, ""
        self.failed, self.failed_at = None, 0.0

    def _held(self, max_age_s: float) -> tuple[list[dict[str, Any]], float] | None:
        """What the last read left, while it is under a minute old: its rows, or its failure raised
        again (a copy, so each caller's traceback is its own)."""
        now = self.clock()
        if self.failed is not None and now - self.failed_at < max_age_s:
            f = self.failed
            raise ReturnsUnavailable(str(f), kind=f.kind, status=f.status, key=f.key)
        if self.read_at and now - self.read_at < max_age_s:
            return self._sorted(), self.read_at
        return None

    async def get(self, *, max_age_s: float = OPEN_CACHE_S) -> tuple[list[dict[str, Any]], float]:
        held = self._held(max_age_s)
        if held is not None:
            return held
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            held = self._held(max_age_s)
            if held is not None:
                return held
            now = self.clock()
            try:
                if not self.whole_at or now - self.whole_at >= FULL_READ_EVERY_S or not self.watermark:
                    found = await list_returns(open_only=True, limit=MAX_LIST)
                    self.rows = {str(r.get("id")): r for r in found if r.get("id")}
                    self.whole_at = now
                    self.watermark = max((str(r.get("updated_at") or "") for r in found), default="") or self.watermark
                else:
                    changed = await list_returns(since=self.watermark, limit=MAX_LIST)
                    for row in changed:
                        rid = str(row.get("id") or "")
                        if not rid:
                            continue
                        if str(row.get("status") or "") in OPEN_STATUSES:
                            self.rows[rid] = row
                        else:
                            self.rows.pop(rid, None)
                        self.watermark = max(self.watermark, str(row.get("updated_at") or ""))
            except ReturnsUnavailable as exc:
                # No key is not an answer from the service (nothing was asked): never kept.
                if exc.kind != "no_key":
                    self.failed, self.failed_at = exc, now
                raise
            self.failed, self.failed_at = None, 0.0
            self.read_at = now
            return self._sorted(), self.read_at

    def _sorted(self) -> list[dict[str, Any]]:
        return sorted(self.rows.values(), key=lambda r: str(r.get("updated_at") or ""), reverse=True)


OPEN_STATUSES = frozenset({"requested", "awaiting_label", "awaiting_shipment", "in_transit", "received"})
OPEN = OpenReturns()


def forget() -> None:
    """A key was stored or taken away, or an action changed a return: read whole next time."""
    OPEN.forget()
