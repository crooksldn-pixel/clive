"""One deterministic remote-engineering cycle: intake, dispatcher advance, projection.

This is deliberately orchestration glue only. The existing RemoteController performs
bounded inbox intake, the existing Dispatcher advances authoritative lifecycle records,
and the status publisher emits a disposable projection. Nothing here owns task state.

Failure isolation, all fail-closed:

- a transport failure or a refused inbox (a request id re-presented with different bytes)
  admits nothing new, but never stops the Dispatcher from supervising objectives that are
  already recorded: their leases, heartbeats and reviews keep advancing;
- a projection that cannot be published is reported and retried next cycle; it is never
  authority, so losing one changes nothing;
- anything the kernel, the store or the Dispatcher raises propagates and stops the loop.

What reaches the public projection is bounded: an inbox refusal names only the
schema-validated request id; any other intake failure is a fixed sentence, never raw git
or transport output (which could carry a remote URL).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.orchestrator.lifecycle import LifecycleStore

from .controller import RemoteController
from .errors import InboxError, RequestContentChanged
from .receipts import ReceiptLog
from .status import build_status

INTAKE_UNAVAILABLE = "inbox could not be fetched or read this cycle; nothing new was admitted (see host log)"
TRANSPORT_ERRORS = (InboxError, subprocess.TimeoutExpired)


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
        intake_error: str | None = None
        intake_detail: str | None = None
        try:
            outcomes = self.controller.poll_once()
        except RequestContentChanged as exc:
            outcomes, intake_error, intake_detail = [], str(exc), str(exc)
        except TRANSPORT_ERRORS as exc:
            outcomes, intake_error, intake_detail = [], INTAKE_UNAVAILABLE, f"{type(exc).__name__}: {exc}"

        dispatcher_events = list(self.dispatcher.tick())

        status = build_status(store=self.store, receipts=self.receipts, now=self.clock())
        status["adapter"] = {"intake_error": intake_error}
        publish_error: str | None = None
        try:
            projection_commit: str | None = self.publish(status)
        except TRANSPORT_ERRORS as exc:
            projection_commit, publish_error = None, f"{type(exc).__name__}: {exc}"

        return {
            "outcomes": outcomes,
            "dispatcher_events": dispatcher_events,
            "status": status,
            "projection_commit": projection_commit,
            "intake_error": intake_detail,
            "publish_error": publish_error,
        }
