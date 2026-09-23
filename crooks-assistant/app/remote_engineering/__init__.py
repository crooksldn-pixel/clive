"""The bounded GitHub-backed remote engineering inbox and controller adapter.

GitHub is transport only, never lifecycle truth. Every accepted request becomes
exactly one objective through the existing canonical intake
(``app.orchestrator.objectives.intake``); this package reuses that door, the
existing ``Kernel``/``LifecycleStore`` records and the existing dispatcher. It
creates no second source of truth: its own receipts are provenance for GitHub
visibility only, never lifecycle authority.
"""

from __future__ import annotations

from .controller import RemoteController, RemoteControllerConfig, objective_from_request
from .errors import InboxError, RequestSchemaError
from .inbox import DEFAULT_INBOX_BRANCH, DEFAULT_INBOX_DIRECTORY, discover_requests, fetch_inbox
from .receipts import Receipt, ReceiptLog
from .requests import REQUEST_SCHEMA, RemoteObjectiveRequest, parse_request
from .status import STATUS_SCHEMA, build_status

__all__ = [
    "DEFAULT_INBOX_BRANCH",
    "DEFAULT_INBOX_DIRECTORY",
    "REQUEST_SCHEMA",
    "STATUS_SCHEMA",
    "InboxError",
    "Receipt",
    "ReceiptLog",
    "RemoteController",
    "RemoteControllerConfig",
    "RemoteObjectiveRequest",
    "RequestSchemaError",
    "build_status",
    "discover_requests",
    "fetch_inbox",
    "objective_from_request",
    "parse_request",
]
