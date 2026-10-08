"""CLIVE Shipping, the owner's international shipping service, as CLIVE reads it and acts through it.

The service is George's: built by him beside CROOKS Returns and deployed by him in its own container
on the production host, outside CLIVE's engineering kernel (DEC-066). It finds Shopify's open
international orders, prices them at Parcel2Go and Easyship, buys a label only for a paid order the
server has authorised, prints it through its own PrintNode connection, and reads the carrier's
tracking from Shopify. Its code is on branch claude/compassionate-dirac-44hnee (clive-shipping/), and
its contract with CLIVE is that branch's docs/sister-apps/CLIVE_OPERATIONS.md and
clive-shipping/shipping/api.py: `/api/v1` behind https://returns.crooksldn.com/shipping.

What this client promises:

- The key travels in the Authorization header as `Bearer <key>`, never in an address, and redirects
  are never followed, so a key never reaches another host. Reads, prices and tracking carry the
  read key alone; the write key is sent with nothing but a buy or a print George approved on its
  card. Both are read from the secret store at each call, so a key stored on Connections works at
  once.
- Every call has a timeout, and every failure is one ShippingUnavailable with a `kind` and words
  George can be told: the service's own sentence when it gave one (`{"detail": {"message",
  "code"}}`), bounded, with anything shaped like an email address, a phone number or a UK postcode
  taken out. Nothing here logs a key, an address or a customer's detail: a log line names a kind,
  a status code and the service's error code, and nothing else.
- Only the service's own operations change anything. A label is bought only with the `basis` its
  preview returned and an idempotency key made for that one card; a request that never got its
  answer is asked once more with the SAME key, which the service answers with the first outcome,
  never a second purchase or print. A new key is never used to "try again" after an unknown
  outcome (CLIVE_OPERATIONS.md, "Unknown is not failed").
- Printing goes through the service's PrintNode connection. CLIVE holds no PrintNode key: the
  service's PRINTNODE_API_KEY and PRINTNODE_PRINTER_ID are the only ones, on its server.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.secrets import keychain

log = logging.getLogger("crooks.shipping")

DEFAULT_BASE_URL = "https://returns.crooksldn.com/shipping"
READ_KEY = "crooks_shipping_read_key"
WRITE_KEY = "crooks_shipping_write_key"
NAME = "CLIVE Shipping"
NOT_CONNECTED = "not connected — add the CLIVE Shipping keys on the Connections screen"
# The server settings the keys are copied from (clive-shipping/.env on the production host).
READ_ENV = "SHIPPING_CLIVE_READ_KEYS"
WRITE_ENV = "SHIPPING_CLIVE_WRITE_KEYS"
ENV_FILE = "/opt/clive/clive-shipping/.env"

READ_TIMEOUT_S = 8.0
# A preview re-reads the order in Shopify and asks the provider for the exact price now; a tracking
# read asks Shopify for the carrier's view.
PREVIEW_TIMEOUT_S = 25.0
TRACKING_TIMEOUT_S = 15.0
# A buy re-reads Shopify, books and pays at the provider, fetches the documents and fulfils the order.
BUY_TIMEOUT_S = 90.0
PRINT_TIMEOUT_S = 30.0
MAX_DETAIL = 200
MAX_LIST = 500

STAGES = ("attention", "ready", "bought", "printed", "in_transit", "delivered")
SHIPMENT_ID = re.compile(r"^shp_[0-9a-f]{6,40}$")
# Who an action is taken for. The service records it on the order's history as "George (CLIVE)".
ACTOR = "George"

_SETTINGS = {"base_url": DEFAULT_BASE_URL}


class ShippingUnavailable(RuntimeError):
    """CLIVE Shipping could not do this, said as George can be told it. `kind`: no_key, rejected (a
    key refused), not_found, refused (the service said no, and why), rate_limited, trouble (it is
    failing, or a buy's outcome is unknown), timeout, unreachable, invalid. `code` is the service's
    own (payment, stale, not_authorised, busy, printing_disabled, confirm_required...). `refused` is
    True when the service answered and nothing was changed, which the action engine reads to say so.
    `key` names the stored key that was refused, when one was."""

    # Its words are written to be said as they are (app/actions/engine.py `_refusal_words`).
    plain_words = True

    def __init__(self, said: str, *, kind: str, status: int = 0, code: str = "", key: str = "") -> None:
        super().__init__(said)
        self.kind = kind
        self.status = status
        self.code = code
        self.key = key
        self.refused = kind in ("refused", "rejected", "not_found", "invalid", "no_key")


# ------------------------------------------------------------------ where, and with which key


def configure(*, base_url: str) -> None:
    """Called by the runtime with the setting (CROOKS_SHIPPING_BASE_URL)."""
    _SETTINGS["base_url"] = clean_base(base_url)


def clean_base(value: Any) -> str:
    """The address to reach the service at: https only, since every request carries a key. Anything
    else is not used, and the service's own address is, with a warning. The contract names the
    API's base with its /api/v1 (CLIVE_OPERATIONS.md); given that way, it is the same service."""
    text = str(value or "").strip().rstrip("/").removesuffix("/api/v1")
    if text.lower().startswith("https://") and len(text) > len("https://"):
        return text
    if text and text != DEFAULT_BASE_URL:
        log.warning("shipping: CROOKS_SHIPPING_BASE_URL is not an https:// address, so %s is used", DEFAULT_BASE_URL)
    return DEFAULT_BASE_URL


def base_url() -> str:
    return _SETTINGS["base_url"]


def _stored(name: str) -> str:
    try:
        return (keychain.get_optional(name) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has no key to give
        return ""


def read_key() -> str:
    """The key reads, prices and tracking carry. Only the read key: the service lets a write key
    read too, but the key that can buy is sent with nothing but an action the owner approved."""
    return _stored(READ_KEY)


def write_key() -> str:
    return _stored(WRITE_KEY)


def http_client(timeout_s: float) -> httpx.AsyncClient:
    """A client for one call; looked up per call so a test can put a transport in its place."""
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False)


# ------------------------------------------------------------------ words


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\d[\d ()-]{8,}\d")
_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)


def scrub(text: Any, limit: int = MAX_DETAIL) -> str:
    """Something the service wrote, fit to be said: one line, bounded, and without anything shaped
    like an email address, a phone number or a UK postcode (a refusal can echo an address)."""
    words = " ".join(str(text or "").split())
    words = _EMAIL.sub("[email]", words)
    words = _POSTCODE.sub("[postcode]", words)
    words = _PHONE.sub("[number]", words)
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def _said(response: httpx.Response) -> tuple[str, str]:
    """(message, code) from the service's refusal: `{"detail": {"message", "code"}}`, or FastAPI's
    list of what was wrong with the request."""
    try:
        body = response.json()
    except ValueError:
        return "", ""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return scrub(detail.get("message")), str(detail.get("code") or "")[:40]
    if isinstance(detail, list):
        first = detail[0] if detail and isinstance(detail[0], dict) else {}
        where = ".".join(str(p) for p in (first.get("loc") or [])[1:])
        return scrub(f"{where}: {first.get('msg')}" if where else first.get("msg") or ""), "invalid"
    return (scrub(detail), "") if isinstance(detail, str) else ("", "")


def refusal(response: httpx.Response, *, key_name: str = READ_KEY) -> ShippingUnavailable:
    """What a refused request means, in our words. Shared with the key's test on the Connections
    screen (app/connections/testers.py), so the two never describe one answer differently."""
    status = response.status_code
    said, code = _said(response)
    if status == 401:
        return ShippingUnavailable(f"{NAME} wants a key and was sent none it could read. Add the keys again on the "
                                   "Connections screen.", kind="rejected", status=status, code=code, key=key_name)
    if status == 403 and code != "not_authorised":
        # Kept under the 140 characters a refusal is said in (app/actions/engine.py `_refusal_words`).
        said = (f"{NAME} took CLIVE's key to read but not to act. Paste {WRITE_ENV} again on Connections"
                if key_name == WRITE_KEY else f"{NAME} refused CLIVE's read key. Paste {READ_ENV} again on Connections")
        return ShippingUnavailable(said, kind="rejected", status=status, code=code, key=key_name)
    if status == 404:
        return ShippingUnavailable(said or f"{NAME} has no such order.", kind="not_found", status=status, code=code)
    if status in (403, 409, 422):
        # 403 not_authorised is the server's buying authorisation, not CLIVE's key.
        if code == "printing_disabled":
            # The service's PrintNode is set up on its server, never in CLIVE: say where.
            said = f"{said or 'Label printing (PrintNode) is not switched on.'} Set PRINTNODE_* in clive-shipping/.env on the server."
        return ShippingUnavailable(said or f"{NAME} would not do that.", kind="refused", status=status, code=code)
    if status == 429:
        return ShippingUnavailable(f"{NAME} asked CLIVE to slow down; try again in a moment.", kind="rate_limited",
                                   status=status, code=code)
    if status == 503:
        return ShippingUnavailable(said or f"{NAME} couldn't reach Shopify or the courier just now; try again in a "
                                   "minute.", kind="trouble", status=status, code=code)
    if status >= 500:
        return ShippingUnavailable(f"{NAME} is having trouble just now ({status}); try again shortly.", kind="trouble",
                                   status=status, code=code)
    return ShippingUnavailable(f"{NAME} said no ({status}).", kind="refused", status=status, code=code)


# ------------------------------------------------------------------ the requests


async def _send(method: str, path: str, *, key: str, params: dict[str, Any] | None = None,
                body: dict[str, Any] | None = None, timeout_s: float = READ_TIMEOUT_S) -> httpx.Response:
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with http_client(timeout_s) as client:
            return await asyncio.wait_for(
                client.request(method, f"{base_url()}{path}", params=params, json=body, headers=headers), timeout_s)
    except (TimeoutError, httpx.TimeoutException):
        raise ShippingUnavailable(f"{NAME} did not answer in time.", kind="timeout") from None
    except httpx.HTTPError:
        raise ShippingUnavailable(f"{NAME} could not be reached.", kind="unreachable") from None


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise ShippingUnavailable(f"{NAME} answered with something unreadable.", kind="trouble") from None
    if not isinstance(body, dict):
        raise ShippingUnavailable(f"{NAME} answered with something unreadable.", kind="trouble")
    return body


def _refused(response: httpx.Response, key_name: str, what: str) -> ShippingUnavailable:
    problem = refusal(response, key_name=key_name)
    log.info("shipping: %s was refused (%s, %s, %s)", what, problem.kind, response.status_code, problem.code or "-")
    _note_refused_key(problem)
    return problem


async def _read(method: str, path: str, params: dict[str, Any] | None = None, *,
                timeout_s: float = READ_TIMEOUT_S) -> dict[str, Any]:
    key = read_key()
    if not key:
        raise ShippingUnavailable(f"Shipping is {NOT_CONNECTED}.", kind="no_key")
    response = await _send(method, f"/api/v1{path}", key=key, params=params, timeout_s=timeout_s)
    if response.status_code != 200:
        raise _refused(response, READ_KEY, "a read")
    return _json(response)


def shipment_id(value: Any) -> str:
    text = str(value or "").strip()
    if not SHIPMENT_ID.fullmatch(text):
        raise ShippingUnavailable("That isn't a CLIVE Shipping id (they look like shp_ and twelve letters and digits).",
                                  kind="invalid")
    return text


def order_digits(value: Any) -> str:
    """"2142", "#2142", "CROOKS-2142" and "crooks 2142" are one order: its number."""
    digits = re.sub(r"\D", "", str(value or ""))
    if not 1 <= len(digits) <= 10:
        raise ShippingUnavailable("Give the order's number, like 2142.", kind="invalid")
    return digits


async def health() -> dict[str, Any]:
    """GET /health: no key. {"ok": true} when the service is up."""
    response = await _send("GET", "/health", key="", timeout_s=READ_TIMEOUT_S)
    if response.status_code != 200:
        raise refusal(response)
    return _json(response)


async def capabilities() -> dict[str, Any]:
    return await _read("GET", "/capabilities")


async def list_shipments(*, stage: str = "all", q: str = "", limit: int = MAX_LIST) -> list[dict[str, Any]]:
    """The orders in one lifecycle stage (or all), newest first, as the service sums each up."""
    if stage not in (*STAGES, "all"):
        raise ShippingUnavailable(f"stage is one of {', '.join((*STAGES, 'all'))}.", kind="invalid")
    params: dict[str, Any] = {"stage": stage, "limit": max(1, min(int(limit), MAX_LIST))}
    if q:
        params["q"] = q
    found = (await _read("GET", "/shipments", params)).get("shipments")
    return [s for s in found if isinstance(s, dict)] if isinstance(found, list) else []


async def get_shipment(value: Any) -> dict[str, Any]:
    return await _read("GET", f"/shipments/{quote(shipment_id(value), safe='')}")


async def find_order(order: Any) -> list[dict[str, Any]]:
    """The shipments for one order number, whatever their stage. The service matches the number
    against each order's own name, so "2142" finds CROOKS-2142 and nothing else."""
    digits = order_digits(order)
    rows = await list_shipments(stage="all", q=digits, limit=20)
    return [r for r in rows if re.sub(r"\D", "", str(r.get("order") or "")) == digits]


async def preview(value: Any) -> dict[str, Any]:
    """The exact price now, and what a purchase would do, in the service's own words: `will`,
    `money`, `service`, `charged`, and the `basis` a buy needs. Changes nothing (read key)."""
    return await _read("POST", f"/shipments/{quote(shipment_id(value), safe='')}/preview",
                       timeout_s=PREVIEW_TIMEOUT_S)


async def refresh_tracking(value: Any) -> dict[str, Any]:
    """Shopify's carrier tracking for a bought label, read now (read key). Never buys or prints."""
    return await _read("POST", f"/shipments/{quote(shipment_id(value), safe='')}/tracking",
                       timeout_s=TRACKING_TIMEOUT_S)


async def events(*, since: str = "", limit: int = 200) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 1000))}
    if since:
        params["since"] = since
    return await _read("GET", "/events", params)


async def _act(path: str, body: dict[str, Any], *, timeout_s: float, what: str) -> dict[str, Any]:
    """An approved action, with the write key. Sent only by the action engine after the owner's
    gesture (app/tools/shipping_tools.py). No answer is not "nothing happened": it is asked once
    more with the SAME idempotency key, which the service answers from its record."""
    key = write_key()
    if not key:
        raise ShippingUnavailable(f"{NAME} has no write key on this server, so CLIVE can only read shipping. Add it on "
                                  "the Connections screen.", kind="no_key", key=WRITE_KEY)
    if len(str(body.get("idempotency_key") or "")) < 8:
        raise ShippingUnavailable("An action needs its own idempotency key.", kind="invalid")
    try:
        response = await _send("POST", f"/api/v1{path}", key=key, body=body, timeout_s=timeout_s)
    except ShippingUnavailable as first:
        if first.kind not in ("timeout", "unreachable"):
            raise
        log.info("shipping: %s got no answer (%s); asking once more with the same key", what, first.kind)
        response = await _send("POST", f"/api/v1{path}", key=key, body=body, timeout_s=timeout_s)
    if response.status_code != 200:
        raise _refused(response, WRITE_KEY, what)
    return _json(response)


async def buy(value: Any, *, basis: str, idempotency_key: str) -> dict[str, Any]:
    """Buy the label previewed: the preview's `basis`, this card's key. Refused (409 stale, payment)
    if anything changed since the preview; refused (403 not_authorised) unless the server
    authorises buying for this order."""
    if not basis:
        raise ShippingUnavailable("A label is bought only with the basis its preview gave.", kind="invalid")
    body = {"basis": str(basis), "idempotency_key": idempotency_key, "actor": ACTOR}
    return await _act(f"/shipments/{quote(shipment_id(value), safe='')}/buy", body, timeout_s=BUY_TIMEOUT_S,
                      what="a buy")


async def print_label(value: Any, *, idempotency_key: str) -> dict[str, Any]:
    """The label's first print, through the service's PrintNode. Never buys."""
    body = {"idempotency_key": idempotency_key, "actor": ACTOR}
    return await _act(f"/shipments/{quote(shipment_id(value), safe='')}/print", body, timeout_s=PRINT_TIMEOUT_S,
                      what="a print")


async def reprint(value: Any, *, idempotency_key: str) -> dict[str, Any]:
    """One extra copy, confirmed (the service refuses a reprint without `confirm: true`). Never buys."""
    body = {"idempotency_key": idempotency_key, "actor": ACTOR, "confirm": True}
    return await _act(f"/shipments/{quote(shipment_id(value), safe='')}/reprint", body, timeout_s=PRINT_TIMEOUT_S,
                      what="a reprint")


def _note_refused_key(problem: ShippingUnavailable) -> None:
    """A key the service refused is the Connections screen's to show, with a box for that key: the
    same record a failed test leaves (app/connections/ledger.py). Never in the way of the answer."""
    if problem.kind != "rejected" or not problem.key:
        return
    try:
        from app.connections import ledger, testers

        ledger.tested("shipping", testers.Outcome(False, str(problem), fix="key", refused=(problem.key,)).as_dict())
    except Exception:  # noqa: BLE001 - the refusal is said either way
        log.debug("shipping: the refused key was not recorded for the Connections screen", exc_info=True)
