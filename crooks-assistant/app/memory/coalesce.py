"""In-flight coalescing: the same read, asked twice, is made once.

Two things ask for order 1938 within the same second — a tapped control's read and, a moment
later, a tool call the model made. One request goes to Shopify; both callers get its result. The
second caller is not "cached": it is awaiting the same future, so it cannot be served
something older than what the first caller gets.

Reads only. A mutation is never coalesced: two commits of the same change are two commits,
and the engine's arm-once rule is what stops the second — not this.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("crooks.memory")

# A flight that has been running longer than this is not joined by a new caller: something is
# wrong with it, and a second caller inheriting its stall is worse than a second request.
MAX_JOIN_AGE_S = 12.0


class Coalescer:
    def __init__(self, *, clock=time.monotonic) -> None:
        self.clock = clock
        self._flights: dict[str, tuple[asyncio.Future, float]] = {}
        self.joined = 0
        self.started = 0

    def in_flight(self, key: str) -> bool:
        found = self._flights.get(key)
        return found is not None and not found[0].done()

    async def run(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        """The result of `factory()`, run once per key while it is in flight."""
        existing = self._flights.get(key)
        if existing is not None:
            future, started = existing
            if not future.done() and self.clock() - started < MAX_JOIN_AGE_S:
                self.joined += 1
                # A shielded await: this caller being cancelled must not cancel the flight
                # the other caller is still waiting on.
                return await asyncio.shield(future)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._flights[key] = (future, self.clock())
        self.started += 1
        try:
            value = await factory()
        except BaseException as exc:  # noqa: BLE001 — the joiners must learn what happened
            if not future.done():
                future.set_exception(exc)
            self._forget(key, future)
            raise
        if not future.done():
            future.set_result(value)
        self._forget(key, future)
        return value

    def _forget(self, key: str, future: asyncio.Future) -> None:
        found = self._flights.get(key)
        if found is not None and found[0] is future:
            del self._flights[key]
        # A future nobody awaited would log "exception was never retrieved" at exit.
        if future.done() and not future.cancelled() and future.exception() is not None:
            future.exception()

    def counts(self) -> dict[str, int]:
        return {"started": self.started, "joined": self.joined, "in_flight": sum(1 for f, _ in self._flights.values() if not f.done())}


_current: Coalescer | None = None


def current() -> Coalescer:
    global _current
    if _current is None:
        _current = Coalescer()
    return _current


def install(coalescer: Coalescer) -> Coalescer:
    global _current
    _current = coalescer
    return coalescer
