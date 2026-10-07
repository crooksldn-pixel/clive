"""The public door's three limits that no signature can give: how big a request may be, how old
it may be, and that it may come only once.

Why it exists: a signed request copied off the wire is still signed. The signature says who made
it; this says it is new. Shared by every channel's hook (app/routes/hooks.py).

What it promises:
- MAX_BODY_BYTES: a body larger than this is refused before it is read whole.
- WINDOW_S: a timestamp more than five minutes from this server's clock, either way, is refused.
- A request seen once (its channel, timestamp, nonce and signature) is never processed again: a
  repeat inside the window is answered and dropped, and it is remembered until its timestamp has
  left the window, unless more than MAX_SEEN signed requests come within it (only WeCom can sign
  one). Even then a message is stored once, by WeCom's own msgid (app/messaging/store.py).
- Refusals are counted by kind, and the log gets one line per kind a minute at most, naming the
  kind and nothing the request carried.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

log = logging.getLogger("crooks.hooks")

MAX_BODY_BYTES = 64 * 1024
WINDOW_S = 300.0
MAX_SEEN = 20_000
LOG_EVERY_S = 60.0


class Guard:
    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()
        self.refused: dict[str, int] = {}
        self._logged: dict[str, float] = {}

    def fresh(self, timestamp: str | float) -> bool:
        """Whether the request's own timestamp is within WINDOW_S of now."""
        try:
            moment = float(timestamp)
        except (TypeError, ValueError):
            return False
        return abs(self.clock() - moment) <= WINDOW_S

    def first_time(self, key: str, timestamp: float) -> bool:
        """True the first time `key` is seen; False for a repeat. Keys are kept until their
        timestamp has left the window, so a repeat is never mistaken for a first."""
        now = self.clock()
        with self._lock:
            while self._seen:
                oldest_key, oldest_at = next(iter(self._seen.items()))
                if now - oldest_at > 2 * WINDOW_S or len(self._seen) > MAX_SEEN:
                    self._seen.popitem(last=False)
                else:
                    break
            if key in self._seen:
                return False
            self._seen[key] = float(timestamp)
            return True

    def refuse(self, channel: str, why: str) -> None:
        """Count a refusal, and say so in the log at most once a minute per kind."""
        kind = f"{channel}:{why}"
        self.refused[kind] = self.refused.get(kind, 0) + 1
        now = self.clock()
        if now - self._logged.get(kind, 0.0) >= LOG_EVERY_S:
            self._logged[kind] = now
            log.info("hooks: refused a %s request (%s); %d so far", channel, why, self.refused[kind])


GUARD = Guard()
