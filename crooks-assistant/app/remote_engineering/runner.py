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

What this cycle reports is bounded, and identically so on the public projection and in the
value the host prints to its own log. Only two things ever travel: the fixed sentence for a
transport failure, and, for a re-presented request id, a message built solely from that
schema-validated id. Git's own output never travels, in either direction: it names the
remote it was talking to, and an authenticated remote URL carries a credential in its
userinfo. The operator diagnoses a transport failure from git's stderr at the console, not
from this loop's log, which is why the exception itself is dropped rather than recorded.
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

INTAKE_UNAVAILABLE = "inbox could not be fetched or read this cycle; nothing new was admitted"
PUBLISH_UNAVAILABLE = "status projection could not be published this cycle; it will be retried"
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
        refusals: tuple[dict, ...] = ()
        try:
            outcomes = self.controller.poll_once()
        except RequestContentChanged as exc:
            outcomes, intake_error = [], str(exc)
        except TRANSPORT_ERRORS:
            outcomes, intake_error = [], INTAKE_UNAVAILABLE
        else:
            # A schema-invalid record earns no receipt -- nothing was decided about an id --
            # so the controller keys its refusal by source and digest instead, and that key
            # is what marks the outcomes this cycle has to project itself.
            refusals = tuple(item for item in outcomes if "refusal_id" in item)

        dispatcher_events = list(self.dispatcher.tick())

        status = build_status(store=self.store, receipts=self.receipts, now=self.clock(), refusals=refusals)
        status["adapter"] = {"intake_error": intake_error}
        publish_error: str | None = None
        try:
            projection_commit: str | None = self.publish(status)
        except TRANSPORT_ERRORS:
            projection_commit, publish_error = None, PUBLISH_UNAVAILABLE

        return {
            "outcomes": outcomes,
            "dispatcher_events": dispatcher_events,
            "status": status,
            "projection_commit": projection_commit,
            "intake_error": intake_error,
            "publish_error": publish_error,
        }
