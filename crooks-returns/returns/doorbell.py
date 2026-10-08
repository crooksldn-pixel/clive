"""The doorbell: every event a return records is posted to CLIVE's door (RETURNS_CLIVE_WEBHOOK_URL,
https://hooks.crooksldn.com/hooks/returns), so CLIVE knows at once instead of asking every minute.

Why it exists: the owner's ruling of 8 October (CLIVE's DEC-071, ruling 20) has CROOKS Returns post
its events to CLIVE through the public hooks door. The post is a doorbell, not the record: it says
which return changed and how, and CLIVE then reads the return through /api/v1 with its own key.

What it promises:

- **What goes out:** the event's id, its type, the return's id and when it happened, and the moment
  it was sent. Never a customer's name, email, address, order or anything else of the return
  (`body`). Signed: `X-Crooks-Returns-Signature: sha256=<hex HMAC-SHA256 of the raw body>` with
  RETURNS_CLIVE_WEBHOOK_SECRET. `sent_at` is inside the signed body, so a copied request is too
  old for CLIVE's door after five minutes.
- **Every recorded event, once each:** the store writes one outbox row per new timeline event in
  the same transaction as the return itself (`Store.save`), so an event is never recorded without
  its row, and a crash after the save still delivers it. The row's id is the event's id, made from
  the return and the event's place in its timeline, so saving again never makes a second.
- **Never in the way of the user:** saving a return only writes the row. Posting is done here, on
  its own thread, never under the store's lock, with a five-second timeout, so a slow or absent
  CLIVE never slows or fails an action.
- **Retries with backoff:** anything but a 2xx is tried again after 30 s, 1 min, 2 min ... up to an
  hour between tries, each try signed afresh; after a day the event is given up (CLIVE still sees
  the change the next time it reads). A delivered event is never sent again. A post that could
  not be made at all (an address httpx refuses) is a try like any other: it never stops the pass,
  so the rest of the batch still goes. The address posted to is the one `on` checked, stripped.
- **Off when unset:** without RETURNS_CLIVE_WEBHOOK_URL no row is written and no thread starts.
  Without RETURNS_CLIVE_WEBHOOK_SECRET nothing is sent unsigned: the rows wait (and are given up
  after a day), and the log says so once.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from returns.settings import Settings
from returns.store import Store, event_id  # noqa: F401 - event_id: the id CLIVE de-dupes by

log = logging.getLogger("returns.doorbell")

SIGNATURE_HEADER = "X-Crooks-Returns-Signature"
TIMEOUT_S = 5.0
POLL_S = 15.0  # rows another process wrote (returns-ctl) are found within this
BATCH = 20  # at most this many posts per pass
FIRST_RETRY_S = 30.0
MAX_RETRY_S = 3600.0
GIVE_UP_AFTER = timedelta(days=1)
KEEP_DONE = timedelta(days=7)  # delivered and given-up rows are kept this long, for returns-ctl


def body(row: dict[str, Any], sent_at: float) -> bytes:
    """What CLIVE is sent for one event: no more than this."""
    return json.dumps(
        {
            "id": row["id"],
            "type": row["type"],
            "return_id": row["return_id"],
            "at": row["at"],
            "sent_at": int(sent_at),
        },
        separators=(",", ":"),
    ).encode()


def signature(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def backoff(attempts: int) -> float:
    """Seconds before the next try, after `attempts` tries: 30 s, 1 min, 2 min ... at most an hour."""
    return min(FIRST_RETRY_S * 2 ** max(0, attempts - 1), MAX_RETRY_S)


class Doorbell:
    """Posts the outbox to CLIVE. One thread; `wake()` makes it look now rather than at the next poll."""

    def __init__(
        self,
        settings: Settings,
        store: Store,
        *,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.s = settings
        self.store = store
        self.clock = clock
        self._http = http
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._said_unsigned = False

    @property
    def url(self) -> str:
        """CLIVE's door as configured, without the stray whitespace (a CRLF .env's `\\r`) that `on`
        ignores: the address posted to is the one `on` checked."""
        return self.s.clive_webhook_url.strip()

    @property
    def on(self) -> bool:
        return bool(self.url)

    def wake(self) -> None:
        if self.on:
            self._wake.set()

    # ------------------------------------------------------------------ one pass

    def deliver_due(self) -> int:
        """Post every event that is due, once each; returns how many CLIVE accepted."""
        if not self.on:
            return 0
        now = self.clock()
        self.store.outbox_prune(_iso(now - KEEP_DONE.total_seconds()))
        secret = self.s.clive_webhook_secret
        delivered = 0
        for row in self.store.outbox_due(_iso(now), BATCH):
            if self._stop.is_set():
                break
            if not secret:
                self._unsigned(row, now)
                continue
            answer = self._post(row, secret)
            if answer.startswith("2"):
                self.store.outbox_done(row["id"], "delivered", answer, _iso(self.clock()))
                delivered += 1
            else:
                self._later(row, answer, now)
        return delivered

    def _post(self, row: dict[str, Any], secret: str) -> str:
        """One try. The answer as a word: the status code, "timeout", "unreachable", or "error" for
        a post that could not be made at all (an address httpx refuses, say). Every one of them is a
        try like any other, so the row is retried and given up on schedule and the rest of the
        batch still goes."""
        raw = body(row, self.clock())
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: signature(secret, raw),
            "User-Agent": "crooks-returns-doorbell",
        }
        try:
            response = self._client().post(self.url, content=raw, headers=headers)
        except httpx.TimeoutException:
            return "timeout"
        except httpx.HTTPError:
            return "unreachable"
        except Exception as exc:  # noqa: BLE001 - recorded as the row's answer, never lost
            # Its kind only: the message can repeat the address, and the address is the owner's.
            log.warning("doorbell: the post to CLIVE could not be made (%s)", type(exc).__name__)
            return "error"
        return str(response.status_code)

    def _later(self, row: dict[str, Any], answer: str, now: float) -> None:
        attempts = int(row["attempts"]) + 1
        if _age(row, now) >= GIVE_UP_AFTER:
            self.store.outbox_done(row["id"], "given_up", answer, _iso(now), attempts=attempts)
            log.warning(
                "doorbell: gave up on %s (%s) after %d tries; last answer %s",
                row["id"],
                row["type"],
                attempts,
                answer,
            )
            return
        self.store.outbox_retry(
            row["id"], attempts, _iso(now + backoff(attempts)), answer, _iso(now)
        )
        log.info(
            "doorbell: %s (%s) not delivered (%s); try %d again later",
            row["id"],
            row["type"],
            answer,
            attempts + 1,
        )

    def _unsigned(self, row: dict[str, Any], now: float) -> None:
        """No secret: nothing goes unsigned. The row waits, as if CLIVE had not answered."""
        if not self._said_unsigned:
            self._said_unsigned = True
            log.warning(
                "doorbell: RETURNS_CLIVE_WEBHOOK_SECRET is not set, so no event is sent to CLIVE"
            )
        self._later(row, "no secret", now)

    def _client(self) -> httpx.Client:
        if self._http is None:
            # Never follows a redirect: the signed post goes to the address configured, nowhere else.
            self._http = httpx.Client(timeout=TIMEOUT_S, follow_redirects=False)
        return self._http

    # ------------------------------------------------------------------ the thread

    def start(self) -> bool:
        """Start posting in the background; off when RETURNS_CLIVE_WEBHOOK_URL is unset."""
        if not self.on or self._thread is not None:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="returns-doorbell", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout_s: float = TIMEOUT_S + 1) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout_s)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.deliver_due()
            except Exception:  # one bad pass must not stop the next
                log.exception("doorbell: a delivery pass failed")
            self._wake.wait(POLL_S)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="microseconds")


def _age(row: dict[str, Any], now: float) -> timedelta:
    try:
        queued = datetime.fromisoformat(str(row["queued_at"]))
    except ValueError:
        return GIVE_UP_AFTER
    return datetime.fromtimestamp(now, UTC) - queued
