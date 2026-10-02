"""Ship24, for "where is order 2106?": a parcel's own carrier scans, found by its tracking number.

Read-only towards the shop, and only ever asked about one parcel at a time:

- The key the owner stored as `ship24_api_key` (the Connections screen, or
  scripts/provision_secrets.py) travels in the Authorization header as `Bearer <key>` and never in
  an address, so no log line or exception that carries a URL can carry it. It is read from the
  secret store at every call, so a key stored later works without a restart. No answer, refusal
  or log line here quotes what Ship24 sent back: its error text can echo the request.
- Nothing here touches Shopify. The one thing a look-up can change is on Ship24's side: on a
  per-shipment plan, the first look-up of a number Ship24 is not tracking yet creates a tracker
  for it, which is one shipment of the plan (that is how that plan tracks anything at all).
- Every failure is one Ship24Unavailable with a `kind` and words the owner can be told.

Two plans, two ways to ask (https://docs.ship24.com/trackers, https://docs.ship24.com/per-call-api):

  per-shipment  GET  /trackers/search/{trackingNumber}/results  the results of a tracker that
                                                                 already exists; creates nothing
                POST /trackers/track                           creates the tracker if there is
                                                                 none (idempotent for the same
                                                                 payload) and returns its results
  per-call      POST /tracking/search                          one synchronous look-up, counted
                                                                 as one call of the plan

A key on the wrong plan for an endpoint is refused with the error code `no_active_subscription`.
So the per-shipment pair is asked first (the existing tracker is looked for before one is made, so
asking twice never spends a second shipment), and on that refusal the per-call endpoint; which
plan answered is remembered for this process, and forgotten when a new key is stored. When
neither answers, the owner is told the key has no active plan.

Docs relied on (read 2 October 2026):
  https://docs.ship24.com/getting-started          the Bearer header; keys in the dashboard
  https://docs.ship24.com/trackers                 which endpoints create a tracker and which read
  https://docs.ship24.com/per-call-api             POST /tracking/search, per-call plans only
  https://docs.ship24.com/errors                   {"errors": [{"code", "message"}]} and the codes
  https://docs.ship24.com/rate-limiter             10 requests a second an endpoint; Retry-After
  https://docs.ship24.com/status                   statusMilestone and its meanings
  https://docs.ship24.com/data-format              tracking numbers; the carriers' local times
  https://docs.ship24.com/tracking-api-reference   the request and response shapes (its OpenAPI:
                                                   https://docs.ship24.com/assets/openapi/ship24-tracking-api.yaml)
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.secrets import keychain

log = logging.getLogger("crooks.ship24")

API = "https://api.ship24.com/public/v1"
KEY_NAME = "ship24_api_key"
# A read of an existing tracker answers at once. Creating one, or a per-call look-up, fetches from
# the carrier while we wait: Ship24 says up to a minute for the first call.
READ_TIMEOUT_S = 10.0
LOOKUP_TIMEOUT_S = 45.0

MAX_EVENTS = 15
MAX_STATUS = 160
MAX_LOCATION = 80
MAX_COURIERS = 3

PER_SHIPMENT = "per-shipment"
PER_CALL = "per-call"
NOT_CONNECTED = "not connected — add the Ship24 key on the Connections screen"

# 5 to 50 of these (https://docs.ship24.com/data-format#tracking-number).
TRACKING_NUMBER = re.compile(r"^[A-Za-z0-9_/.-]{5,50}$")
# A Ship24 courier code ("us-post", "palletways"); anything else said is a carrier's name.
COURIER_CODE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")

# statusMilestone, in the words the owner would use (https://docs.ship24.com/status).
MILESTONES = {
    "info_received": "Label created, not yet scanned by the carrier",
    "in_transit": "In transit",
    "out_for_delivery": "Out for delivery",
    "failed_attempt": "Delivery attempted, not delivered",
    "available_for_pickup": "Waiting to be picked up",
    "delivered": "Delivered",
    "exception": "Problem: returning, returned, lost or destroyed",
    "pending": "No carrier scans yet",
}

_PLAN = {"plan": ""}


class Ship24Unavailable(RuntimeError):
    """Ship24 could not answer this, said as the owner can be told it. `kind` is one of:
    no_key, rejected (the key), no_plan, quota, rate_limited, invalid (the number or courier),
    not_found, slow (a first look-up still running), timeout, unreachable, refused."""

    def __init__(self, said: str, *, kind: str) -> None:
        super().__init__(said)
        self.kind = kind


def api_key() -> str:
    """The stored key, read each time (a key stored later works without a restart), or ""."""
    try:
        return (keychain.get_optional(KEY_NAME) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has no key to give
        return ""


def plan() -> str:
    """The plan the stored key was last seen answering on: PER_SHIPMENT, PER_CALL or ""."""
    return _PLAN["plan"]


def forget_plan() -> None:
    """A new key was stored (or the old one taken away): which plan it is on is asked again."""
    _PLAN["plan"] = ""


def http_client(timeout_s: float) -> httpx.AsyncClient:
    """A client for one call. Looked up per call, so a test can put a mocked transport in its
    place. Redirects are not followed, so the key is never carried to another host."""
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), follow_redirects=False)


def tracking_number(text: Any) -> str:
    """The number as Ship24 takes it: spaces gone, upper case (it answers in upper case anyway, and
    the same payload every time is what keeps a tracker from being made twice)."""
    number = "".join(str(text or "").split())[:60].upper()
    if not TRACKING_NUMBER.fullmatch(number):
        raise Ship24Unavailable("That isn't a tracking number Ship24 can look up: it should be 5 to 50 letters "
                                "and digits, as on the order's fulfilment.", kind="invalid")
    return number


def _courier(text: Any) -> tuple[str, str]:
    """(courier code, courier name) from what was said: a code is sent as one; a carrier's name
    ("Royal Mail", as a fulfilment names it) only labels a new tracker, since Ship24 finds the
    carrier from the number itself."""
    said = " ".join(str(text or "").split())[:60]
    if not said:
        return "", ""
    return (said, "") if COURIER_CODE.fullmatch(said) else ("", said)


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "")[: limit * 4].split())[:limit]


def _codes(response: httpx.Response) -> set[str]:
    """The error codes Ship24 gives ("no_active_subscription", "quota_limit_reached"). Read to
    decide what to say; the message beside each is never read, kept or said."""
    try:
        body = response.json()
    except ValueError:
        return set()
    errors = body.get("errors") if isinstance(body, dict) else None
    out = {str(e.get("code") or "")[:60] for e in errors if isinstance(e, dict)} if isinstance(errors, list) else set()
    single = body.get("error") if isinstance(body, dict) else None      # the bulk endpoint's shape
    if isinstance(single, dict) and single.get("code"):
        out.add(str(single["code"])[:60])
    return out - {""}


def _retry_after(response: httpx.Response) -> int:
    try:
        return max(0, min(3600, int(str(response.headers.get("retry-after") or "0").strip())))
    except ValueError:
        return 0


def refusal(response: httpx.Response) -> Ship24Unavailable:
    """What a refused request means, in our words. Shared with the key's test on the Connections
    screen (app/connections/testers.py), so the two can never describe one answer differently."""
    codes = _codes(response)
    status = response.status_code
    if status == 401:
        return Ship24Unavailable("Ship24 refused CLIVE's key: it may have been deleted in the Ship24 dashboard, or "
                                 "copied short. Add it again on the Connections screen.", kind="rejected")
    if "no_active_subscription" in codes:
        return Ship24Unavailable("Ship24 says this key's account has no active plan for that.", kind="no_plan")
    if "quota_limit_reached" in codes:
        return Ship24Unavailable("The Ship24 plan's allowance for this billing period is used up. A bigger plan, "
                                 "or the next period, brings it back (dashboard.ship24.com → Subscriptions).",
                                 kind="quota")
    if status == 429:
        wait = _retry_after(response)
        when = f"in {wait} second{'' if wait == 1 else 's'}" if 0 < wait <= 120 else "in a moment"
        return Ship24Unavailable(f"Ship24 asked CLIVE to slow down; try again {when}.", kind="rate_limited")
    if "parcel_not_found" in codes or "tracker_not_found" in codes or status == 404:
        return Ship24Unavailable("Ship24 can't find that parcel yet. It usually means the carrier hasn't scanned it "
                                 "yet; a parcel handed over today often has no scans until tomorrow.", kind="not_found")
    if "validation_error" in codes or status in (400, 422):
        return Ship24Unavailable("Ship24 didn't accept that tracking number. Check it against the order's "
                                 "fulfilment.", kind="invalid")
    if status == 403:
        return Ship24Unavailable("Ship24 refused that for this key.", kind="rejected")
    if status >= 500:
        return Ship24Unavailable(f"Ship24 is having trouble just now ({status}); try again shortly.", kind="refused")
    return Ship24Unavailable(f"Ship24 said no ({status}).", kind="refused")


async def _send(method: str, path: str, key: str, *, payload: dict[str, Any] | None = None,
                timeout_s: float = READ_TIMEOUT_S, slow: str = "") -> httpx.Response:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {key}"}
    try:
        async with http_client(timeout_s) as client:
            return await asyncio.wait_for(client.request(method, f"{API}{path}", json=payload, headers=headers),
                                          timeout_s)
    except (TimeoutError, httpx.TimeoutException):
        if slow:
            raise Ship24Unavailable(slow, kind="slow") from None
        raise Ship24Unavailable("Ship24 did not answer in time.", kind="timeout") from None
    except httpx.HTTPError:
        raise Ship24Unavailable("Ship24 could not be reached.", kind="unreachable") from None


def _body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise Ship24Unavailable("Ship24 answered with something unreadable.", kind="refused") from None
    return body if isinstance(body, dict) else {}


def trackings(body: dict[str, Any]) -> list[dict[str, Any]]:
    """`data.trackings`, as every tracking endpoint returns it."""
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    found = data.get("trackings")
    return [t for t in found if isinstance(t, dict)] if isinstance(found, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _events(tracking: dict[str, Any]) -> list[dict[str, Any]]:
    events = tracking.get("events")
    return [e for e in events if isinstance(e, dict)] if isinstance(events, list) else []


def _couriers(tracking: dict[str, Any]) -> list[str]:
    """The carriers that scanned it, latest first, then any the tracker was made with."""
    out: list[str] = []
    named = _dict(tracking.get("tracker")).get("courierCode")
    for code in [e.get("courierCode") for e in _events(tracking)] + (named if isinstance(named, list) else [named]):
        code = _text(code, 40)
        if code and code not in out:
            out.append(code)
    return out


def _pick(found: list[dict[str, Any]], courier_code: str) -> dict[str, Any]:
    """One parcel among the trackers on this number (a number is not unique across carriers): the
    one on the courier asked about, else the one with the latest scan, else the newest tracker."""
    if courier_code:
        for tracking in found:
            if courier_code in _couriers(tracking):
                return tracking

    def recency(tracking: dict[str, Any]) -> tuple[str, str]:
        events = _events(tracking)
        return (str(events[0].get("occurrenceDatetime") or "") if events else "",
                str(_dict(tracking.get("tracker")).get("createdAt") or ""))

    return max(found, key=recency)


def _window(value: Any, source: str) -> dict[str, str] | None:
    window = _dict(value)
    earliest, latest = _text(window.get("from"), 40), _text(window.get("to"), 40)
    if not (earliest or latest):
        return None
    return {"earliest": earliest or latest, "latest": latest or earliest, "source": source}


def _estimate(delivery: dict[str, Any]) -> dict[str, str] | None:
    """The carrier's own estimate first, then the date it gave alone, then Ship24's prediction
    (an add-on: absent when the plan does not have it)."""
    window = _window(delivery.get("courierEstimatedDeliveryDate"), "the carrier")
    if window:
        return window
    date = _text(delivery.get("estimatedDeliveryDate"), 40)
    if date:
        return {"earliest": date, "latest": date, "source": "the carrier"}
    return _window(delivery.get("aiPredictiveDeliveryDate"), "Ship24's prediction")


def summary(tracking: dict[str, Any], *, number: str, plan_: str) -> dict[str, Any]:
    """One tracking result as CLIVE is told it: the carrier, where it is, when it should arrive,
    and its latest scans, newest first (as Ship24 orders them). Bounded: at most MAX_EVENTS scans,
    each line cut short. The recipient Ship24 may hold is never read."""
    shipment = _dict(tracking.get("shipment"))
    events = _events(tracking)
    milestone = _text(shipment.get("statusMilestone") or (events[0].get("statusMilestone") if events else ""), 40)
    milestone = milestone or "pending"
    stamps = _dict(_dict(tracking.get("statistics")).get("timestamps"))
    return {
        "tracking_number": _text(_dict(tracking.get("tracker")).get("trackingNumber"), 50) or number,
        "courier": ", ".join(_couriers(tracking)[:MAX_COURIERS]),
        "status": MILESTONES.get(milestone, milestone.replace("_", " ")),
        "milestone": milestone,
        "estimated_delivery": _estimate(_dict(shipment.get("delivery"))),
        "delivered_at": _text(stamps.get("deliveredDatetime"), 40),
        "origin": _text(shipment.get("originCountryCode"), 3),
        "destination": _text(shipment.get("destinationCountryCode"), 3),
        "events": [
            {"at": _text(e.get("occurrenceDatetime"), 40), "location": _text(e.get("location"), MAX_LOCATION),
             "status": _text(e.get("status"), MAX_STATUS)}
            for e in events[:MAX_EVENTS]
        ],
        "events_total": len(events),
        "plan": plan_,
    }


async def _post_lookup(path: str, key: str, payload: dict[str, Any], *, slow: str) -> httpx.Response:
    """A POST that fetches from the carrier. A courier code Ship24 does not know is a validation
    error before anything is created or counted, so it is asked once more without the code."""
    response = await _send("POST", path, key, payload=payload, timeout_s=LOOKUP_TIMEOUT_S, slow=slow)
    if response.status_code in (400, 422) and "courierCode" in payload and "validation_error" in _codes(response):
        payload = {k: v for k, v in payload.items() if k != "courierCode"}
        response = await _send("POST", path, key, payload=payload, timeout_s=LOOKUP_TIMEOUT_S, slow=slow)
    return response


async def _per_shipment(number: str, code: str, name: str, key: str) -> dict[str, Any]:
    response = await _send("GET", f"/trackers/search/{quote(number, safe='')}/results", key)
    if response.status_code == 200:
        found = trackings(_body(response))
        if found:
            out = summary(_pick(found, code), number=number, plan_=PER_SHIPMENT)
            return {**out, "new_tracker": False, "trackers": len(found)}
    elif not (response.status_code == 404 or "tracker_not_found" in _codes(response)):
        raise refusal(response)
    # Not tracked yet: track it now, which is one shipment of the plan.
    payload: dict[str, Any] = {"trackingNumber": number}
    if code:
        payload["courierCode"] = [code]
    elif name:
        payload["courierName"] = name[:200]
    response = await _post_lookup("/trackers/track", key, payload, slow=(
        "Ship24 has started tracking that parcel and is still fetching it from the carrier (the first look-up can "
        "take up to a minute). Ask again shortly: it answers at once from then on."))
    if response.status_code not in (200, 201):
        raise refusal(response)
    found = trackings(_body(response))
    if not found:
        raise Ship24Unavailable("Ship24 started tracking that parcel but has nothing for it yet. Ask again in a "
                                "few minutes.", kind="not_found")
    return {**summary(_pick(found, code), number=number, plan_=PER_SHIPMENT), "new_tracker": True,
            "trackers": len(found)}


async def _per_call(number: str, code: str, key: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"trackingNumber": number}
    if code:
        payload["courierCode"] = [code]
    response = await _post_lookup("/tracking/search", key, payload, slow="")
    if response.status_code not in (200, 201):
        raise refusal(response)
    found = trackings(_body(response))
    if not found:
        raise Ship24Unavailable("Ship24 has nothing for that number yet: the carrier may not have scanned it.",
                                kind="not_found")
    return {**summary(_pick(found, code), number=number, plan_=PER_CALL), "new_tracker": False, "trackers": len(found)}


async def track(number: Any, courier: Any = "") -> dict[str, Any]:
    """Where one parcel is. Asks on the plan the key was last seen on, or per-shipment first; a
    refusal for want of that plan moves to the other, and only both refusing is said as no plan."""
    wanted = tracking_number(number)
    code, name = _courier(courier)
    key = api_key()
    if not key:
        raise Ship24Unavailable(f"Parcel tracking is {NOT_CONNECTED}.", kind="no_key")
    order = (PER_CALL, PER_SHIPMENT) if _PLAN["plan"] == PER_CALL else (PER_SHIPMENT, PER_CALL)
    for which in order:
        try:
            found = await (_per_shipment(wanted, code, name, key) if which == PER_SHIPMENT
                           else _per_call(wanted, code, key))
        except Ship24Unavailable as exc:
            if exc.kind == "no_plan":
                continue
            log.info("ship24: %s look-up refused (%s)", which, exc.kind)
            raise
        _PLAN["plan"] = which
        return found
    _PLAN["plan"] = ""
    raise Ship24Unavailable("Ship24 accepted the key, but its account has no active plan: neither per-shipment nor "
                            "per-call. Choose one at dashboard.ship24.com → Subscriptions (there is a free one).",
                            kind="no_plan")
