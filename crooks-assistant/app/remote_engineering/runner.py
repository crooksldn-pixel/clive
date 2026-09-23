"""One deterministic remote-engineering cycle: intake, dispatcher advance, projection.

This is deliberately orchestration glue only. The existing RemoteController performs
bounded inbox intake, the existing Dispatcher advances authoritative lifecycle records,
and the status publisher emits a disposable projection. Nothing here owns task state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.orchestrator.lifecycle import LifecycleStore

from .controller import RemoteController
from .receipts import ReceiptLog
from .status import build_status


@dataclass
class RemoteEngineeringLoop:
    controller: RemoteController
    dispatcher: object
    store: LifecycleStore
    receipts: ReceiptLog
    publish: Callable[[dict], str]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def cycle(self) -> dict:
        """Process inbox, advance the existing dispatcher once, then publish projection."""
        outcomes = self.controller.poll_once()
        dispatcher_events = list(self.dispatcher.tick())
        status = build_status(store=self.store, receipts=self.receipts, now=self.clock())
        projection_commit = self.publish(status)
        return {
            "outcomes": outcomes,
            "dispatcher_events": dispatcher_events,
            "status": status,
            "projection_commit": projection_commit,
        }
