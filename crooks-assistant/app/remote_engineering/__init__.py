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
from .errors import InboxError, RequestContentChanged, RequestSchemaError, TransportError
from .inbox import DEFAULT_INBOX_BRANCH, DEFAULT_INBOX_DIRECTORY, discover_requests, fetch_inbox
from .publisher import (
    DEFAULT_STATUS_BRANCH,
    DEFAULT_STATUS_HEARTBEAT_S,
    DEFAULT_STATUS_PATH,
    MAX_HEARTBEAT_S,
    MIN_HEARTBEAT_S,
    publish_status,
    validate_seconds,
)
from .receipts import (
    ADAPTER_ROOT_NOT_IGNORED,
    CLAIM_SCHEMA,
    Claim,
    ClaimLog,
    Receipt,
    ReceiptLog,
    adapter_root_preconditions,
)
from .requests import REQUEST_ID_MAX_LENGTH, REQUEST_SCHEMA, RemoteObjectiveRequest, parse_request
from .runner import INTAKE_UNAVAILABLE, PUBLISH_UNAVAILABLE, RemoteEngineeringLoop
from .status import STATUS_SCHEMA, build_status

__all__ = [
    "ADAPTER_ROOT_NOT_IGNORED",
    "CLAIM_SCHEMA",
    "DEFAULT_INBOX_BRANCH",
    "DEFAULT_INBOX_DIRECTORY",
    "DEFAULT_STATUS_BRANCH",
    "DEFAULT_STATUS_HEARTBEAT_S",
    "DEFAULT_STATUS_PATH",
    "INTAKE_UNAVAILABLE",
    "MAX_HEARTBEAT_S",
    "MIN_HEARTBEAT_S",
    "PUBLISH_UNAVAILABLE",
    "REQUEST_ID_MAX_LENGTH",
    "REQUEST_SCHEMA",
    "STATUS_SCHEMA",
    "Claim",
    "ClaimLog",
    "InboxError",
    "Receipt",
    "ReceiptLog",
    "RemoteController",
    "RemoteControllerConfig",
    "RemoteEngineeringLoop",
    "RemoteObjectiveRequest",
    "RequestContentChanged",
    "RequestSchemaError",
    "TransportError",
    "adapter_root_preconditions",
    "build_status",
    "discover_requests",
    "fetch_inbox",
    "objective_from_request",
    "parse_request",
    "publish_status",
    "validate_seconds",
]
