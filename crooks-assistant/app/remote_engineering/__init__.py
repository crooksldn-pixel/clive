"""The bounded GitHub-backed remote engineering inbox and controller adapter.

GitHub is transport only, never lifecycle truth. Every accepted request becomes
exactly one objective through the existing canonical intake
(``app.orchestrator.objectives.intake``); this package reuses that door, the
existing ``Kernel``/``LifecycleStore`` records and the existing dispatcher. It
creates no second source of truth: its own receipts are provenance for GitHub
visibility only, never lifecycle authority.
"""

from __future__ import annotations

from .controller import (
    TRUNK_UNAVAILABLE,
    RemoteController,
    RemoteControllerConfig,
    objective_from_request,
)
from .errors import InboxError, RequestContentChanged, RequestSchemaError, TransportError
from .inbox import (
    DEFAULT_INBOX_BRANCH,
    DEFAULT_INBOX_DIRECTORY,
    DEFAULT_TRUNK_BRANCH,
    discover_requests,
    fetch_inbox,
    fetch_trunk,
)
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
from .status import STATUS_SCHEMA, build_history, build_status, loop_fields
from .waits import BASE_WAIT_REASON, DEFAULT_BASE_WAIT_S, WAIT_SCHEMA, BaseWait, WaitLog

__all__ = [
    "ADAPTER_ROOT_NOT_IGNORED",
    "BASE_WAIT_REASON",
    "CLAIM_SCHEMA",
    "DEFAULT_BASE_WAIT_S",
    "DEFAULT_INBOX_BRANCH",
    "DEFAULT_INBOX_DIRECTORY",
    "DEFAULT_TRUNK_BRANCH",
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
    "TRUNK_UNAVAILABLE",
    "WAIT_SCHEMA",
    "BaseWait",
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
    "WaitLog",
    "adapter_root_preconditions",
    "build_history",
    "build_status",
    "discover_requests",
    "fetch_inbox",
    "fetch_trunk",
    "loop_fields",
    "objective_from_request",
    "parse_request",
    "publish_status",
    "validate_seconds",
]
