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
- what the Dispatcher reports about each build (``Dispatcher.status``: attempts, repairs, generated
  files, landing) is read after the tick for the projection only; a Dispatcher that cannot answer
  publishes none of it and the cycle goes on, unless what it raised is an authoritative-state failure;
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

from app.orchestrator.lifecycle import JournalError, LifecycleError, LifecycleStore
from app.orchestrator.store import RecordConflictError, StateConflictError

from .controller import RemoteController
from .errors import InboxBoundExceeded, InboxError, RequestContentChanged
from .receipts import ReceiptLog
from .status import build_status

INTAKE_UNAVAILABLE = "inbox could not be fetched or read this cycle; nothing new was admitted"
PUBLISH_UNAVAILABLE = "status projection could not be published this cycle; it will be retried"
INTAKE_OVER_BOUND = "inbox snapshot exceeded a work bound; nothing new was admitted this cycle"
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
        except InboxBoundExceeded:
            outcomes, intake_error = [], INTAKE_OVER_BOUND
        except TRANSPORT_ERRORS:
            outcomes, intake_error = [], INTAKE_UNAVAILABLE
        except (JournalError, LifecycleError, RecordConflictError, StateConflictError):
            raise  # authoritative-state failures stop the loop: fail closed
        except Exception:  # noqa: BLE001 -- untrusted inbox content must never end supervision
            outcomes, intake_error = [], INTAKE_UNAVAILABLE
        else:
            # A schema-invalid record earns no receipt -- nothing was decided about an id --
            # so the controller keys its refusal by source and digest instead, and that key
            # is what marks the outcomes this cycle has to project itself.
            refusals = tuple(item for item in outcomes if "refusal_id" in item)

        dispatcher_events = list(self.dispatcher.tick())

        status = build_status(store=self.store, receipts=self.receipts, now=self.clock(), refusals=refusals,
                              gates=self._acceptance_gates(), progress=self._build_progress())
        status["adapter"] = {"intake_error": intake_error}
        # Published only when this cycle needed the trunk for a missing base and could not fetch it:
        # fixed words (controller.TRUNK_UNAVAILABLE), never git's.
        trunk_error = getattr(self.controller, "trunk_fetch_error", None)
        if intake_error is None and isinstance(trunk_error, str) and trunk_error:
            status["adapter"]["trunk_fetch_error"] = trunk_error
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

    def _build_progress(self) -> dict[str, dict]:
        """What the Dispatcher says each build went through (``Dispatcher.status``), by objective id,
        for the projection only. A dispatcher that has no such view, or one that fails to answer,
        publishes none of it -- the fields are then simply absent, meaning unknown -- and does not
        stop the cycle: supervision matters more than this report. The kernel's and the store's own
        failures still stop it, exactly as they do from the tick."""
        read = getattr(self.dispatcher, "status", None)
        if not callable(read):
            return {}
        try:
            entries = read()
        except (JournalError, LifecycleError, RecordConflictError, StateConflictError):
            raise  # authoritative-state failures stop the loop, wherever they surface: fail closed
        except Exception:  # noqa: BLE001 -- anything else in a projection read must never end supervision
            return {}
        if not isinstance(entries, (list, tuple)):
            return {}
        return {
            entry["objective_id"]: entry
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("objective_id"), str)
        }

    def _acceptance_gates(self) -> dict[str, dict]:
        """The dispatcher's recorded GitHub acceptance answers, for the projection only: a dispatcher that
        keeps none, or notes that cannot be read, publish none, and never stop the cycle."""
        read = getattr(self.dispatcher, "acceptance_gates", None)
        if not callable(read):
            return {}
        try:
            gates = read()
        except (OSError, ValueError):
            return {}
        return gates if isinstance(gates, dict) else {}
