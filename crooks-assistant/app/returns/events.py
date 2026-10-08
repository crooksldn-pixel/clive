"""CROOKS Returns' doorbell: the events the returns service posts to /hooks/returns, checked, and
what CLIVE does with each (DEC-077, the owner's ruling 20 of 8 October, DEC-071).

Why it exists: CLIVE used to learn that a return changed only when something it was showing asked
the service (at most once a minute, app/clients/crooks_returns.py OpenReturns). Now the service
rings as soon as it records an event, through the public hooks door. The ring is a doorbell, never
the record: CLIVE reads the return through the service's API with its own key, and what it shows
comes from that read alone.

What it promises:

- **The door's checks** (`verify`), in this order, for a body already capped at MAX_BODY: a secret is
  stored (Connections, CROOKS Returns, "Events secret"); the X-Crooks-Returns-Signature header is
  "sha256=" and the HMAC-SHA256 of the raw body under it, compared in constant time
  (app/messaging/meta.py `signed`), before the body is decoded; the body is strict UTF-8 JSON, one
  object with exactly the five fields the service sends (id, type, return id, when, sent_at) and
  nothing of a customer's; `sent_at` within five minutes of this server's clock. Anything else is
  Refused, and the route answers an empty 403.
- **Once each:** an event id seen before is answered and dropped (`Door.first_time`), for the last
  MAX_SEEN events whatever their age, so the service's retries of one CLIVE took change nothing.
- **What an event does** (`Door.ring`), never waiting on the service: it marks the open returns
  stale, so the home's row and the next returns card read afresh; then, on its own task, CLIVE
  reads the open returns again and, for an event that can make a return need George (one to
  approve, a label that failed, money that did not move: NEEDS_HIM), reads that return itself. A
  notice is made only when that read says the return needs him for that reason now.
- **Notices** are held in memory, newest per return, for NOTICE_KEEP_S, and handed to the home
  only while the open returns still say that return needs him for that reason (`Door.notices`):
  resolved, it goes. Their words are the return's order number and what happened, never the
  customer's name.
- Nothing an event carries is logged: refusals are counted by kind (app/messaging/guard.py), and a
  failed read is logged by its kind alone.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.clients import crooks_returns
from app.messaging.meta import signed
from app.returns import views
from app.secrets import keychain

log = logging.getLogger("crooks.hooks")

SECRET_KEY = "crooks_returns_hook_secret"
SIGNATURE_HEADER = "x-crooks-returns-signature"
MAX_BODY = 4096               # the service's posts are about 200 bytes
WINDOW_S = 300.0
MAX_SEEN = 10_000
MAX_PENDING = 200             # returns waiting to be read again; past this, only the open list is read
NOTICE_KEEP_S = 12 * 3600.0
MAX_NOTICES = 30
FIELDS = frozenset({"id", "type", "return_id", "at", "sent_at"})
EVENT_ID = re.compile(r"^evt_[0-9a-f]{16,40}$")
EVENT_TYPE = re.compile(r"^[a-z][a-z_]{0,39}$")

# The events that can make a return need George, what each needs to be true of the return as CLIVE
# reads it afterwards (its attention, as the service derives it), the notice's code and tone (web/
# notify.js), and what happened in his words. Every other event only wakes the returns view.
NEEDS_HIM: dict[str, tuple[str, str, str]] = {
    "requested": ("needs_approval", "return_to_approve", "waiting for your approval"),
    "delivered_to_us": ("delivered_unchecked", "return_needs_you", "delivered back to us, not checked yet"),
    "received": ("needs_decision", "return_needs_you", "back with us and needs your decision"),
    "label_overdue": ("awaiting_label_overdue", "return_needs_you", "the label is overdue"),
    "awaiting_label": ("error", "return_problem", "the label wasn't made"),
    "label_payment_not_taken": ("error", "return_problem", "Parcel2Go didn't take the label payment"),
    "label_paid_not_collected": ("error", "return_problem", "the label is paid for but not collected"),
    "shipping_attach_failed": ("error", "return_problem", "Shopify didn't take the tracking"),
    "shipping_attach_unknown": ("error", "return_problem", "Shopify didn't answer about the tracking"),
    "approve_failed": ("error", "return_problem", "the approval failed"),
    "approve_unknown": ("error", "return_problem", "Shopify didn't answer the approval"),
    "process_failed": ("error", "return_problem", "Shopify didn't move the money"),
    "bonus_failed": ("error", "return_problem", "the store credit bonus failed"),
    "cancel_failed": ("error", "return_problem", "the cancel failed"),
    "cancel_unknown": ("error", "return_problem", "Shopify didn't answer the cancel"),
    "action_interrupted": ("error", "return_problem", "an action was interrupted"),
}
TONE = {"return_to_approve": "info", "return_needs_you": "warn", "return_problem": "bad"}
# Which reason a notice gives when one read answers several events: the broken first.
ORDER = ("return_problem", "return_needs_you", "return_to_approve")


class Refused(Exception):
    """The door says no: `why` is the kind counted (never anything the request carried)."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    return_id: str
    at: str


def secret() -> str:
    try:
        return (keychain.get_optional(SECRET_KEY) or "").strip()
    except Exception:  # noqa: BLE001 - a store that cannot be read has no secret to give
        return ""


def verify(raw: bytes, given: str, *, key: str, now: float) -> Event:
    """The event, or Refused. The signature is checked before the body is decoded at all."""
    if not key:
        raise Refused("unset")
    if not signed(given, raw, (key,)):
        raise Refused("signature")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Refused("unreadable") from None
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise Refused("shape")
    sent_at = data["sent_at"]
    if isinstance(sent_at, bool) or not isinstance(sent_at, int | float):
        raise Refused("shape")
    if abs(now - float(sent_at)) > WINDOW_S:
        raise Refused("stale")
    event = Event(*(str(data[k]) if isinstance(data[k], str) else "" for k in ("id", "type", "return_id", "at")))
    if not (EVENT_ID.fullmatch(event.id) and EVENT_TYPE.fullmatch(event.type)
            and crooks_returns.RETURN_ID.fullmatch(event.return_id) and _moment(event.at)):
        raise Refused("shape")
    return event


def _moment(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass
class Notice:
    id: str              # the page shows each once (rn_ and 24 hex; nothing of the return)
    return_id: str
    reason: str          # the attention it stands for (NEEDS_HIM)
    code: str
    words: str
    at: float

    def shown(self) -> dict[str, Any]:
        when = datetime.fromtimestamp(self.at, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        return {"id": self.id, "code": self.code, "tone": TONE[self.code], "words": self.words, "at": when}


class Door:
    """What the door remembers between events: the ids it took, the returns to read again, the
    notices, and counts by kind. One event loop serves every request, so nothing here locks."""

    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._pending: dict[str, set[str]] = {}
        self._task: asyncio.Task | None = None
        self._notices: dict[str, Notice] = {}
        self.counts: Counter[str] = Counter()
        self.last_at = 0.0

    def forget(self) -> None:
        self._seen.clear()
        self._pending.clear()
        self._notices.clear()
        self.counts.clear()
        self.last_at = 0.0

    def first_time(self, event_id: str) -> bool:
        if event_id in self._seen:
            return False
        self._seen[event_id] = None
        while len(self._seen) > MAX_SEEN:
            self._seen.popitem(last=False)
        return True

    def ring(self, event: Event) -> None:
        """Wake the returns view and start the reads; returns at once."""
        self.counts["accepted"] += 1
        self.last_at = self.clock()
        crooks_returns.OPEN.touch()
        if event.type in NEEDS_HIM and (event.return_id in self._pending or len(self._pending) < MAX_PENDING):
            self._pending.setdefault(event.return_id, set()).add(event.type)
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._work())

    async def settle(self) -> None:
        """For tests and shutdown: wait for the reads an event started."""
        while self._task is not None and not self._task.done():
            await asyncio.shield(self._task)

    async def _work(self) -> None:
        while self._pending:
            return_id = next(iter(self._pending))
            types = self._pending.pop(return_id)
            try:
                ret = await crooks_returns.get_return(return_id)
            except crooks_returns.ReturnsUnavailable as exc:
                self.counts[f"read_{exc.kind}"] += 1
                log.info("returns hook: a return could not be read again (%s)", exc.kind)
                continue
            self._consider(return_id, types, ret)
        try:
            await crooks_returns.OPEN.get()
        except crooks_returns.ReturnsUnavailable as exc:
            log.info("returns hook: the open returns could not be read again (%s)", exc.kind)

    def _consider(self, return_id: str, types: set[str], ret: dict[str, Any]) -> None:
        """A notice, if the return as read needs him for a reason one of these events gives."""
        needs = set(views.attention(ret))
        reasons = [(NEEDS_HIM[t], t) for t in types if NEEDS_HIM[t][0] in needs]
        if not reasons:
            return
        (reason, code, what), _ = min(reasons, key=lambda r: ORDER.index(r[0][1]))
        number = views.order_number(ret)
        words = f"Return on {number}: {what}." if number else f"A return: {what}."
        self.counts["notices"] += 1
        self._notices[return_id] = Notice(_notice_id(return_id, code, self.clock()), return_id, reason, code,
                                          words, self.clock())
        while len(self._notices) > MAX_NOTICES:
            oldest = min(self._notices, key=lambda k: self._notices[k].at)
            self._notices.pop(oldest)

    def notices(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The notices still true of the open returns as last read, newest first."""
        now = self.clock()
        open_needs = {str(r.get("id") or ""): set(views.attention(r)) for r in rows}
        for return_id, notice in list(self._notices.items()):
            if now - notice.at > NOTICE_KEEP_S or notice.reason not in open_needs.get(return_id, set()):
                self._notices.pop(return_id)
        return [n.shown() for n in sorted(self._notices.values(), key=lambda n: n.at, reverse=True)]


def _notice_id(return_id: str, code: str, at: float) -> str:
    """The page's handle for one notice: new for each one, nothing of the return in it."""
    return "rn_" + hashlib.sha256(f"{return_id}|{code}|{at}".encode()).hexdigest()[:24]


DOOR = Door()
