"""The adapter: discovers inbox requests and pushes each one through the existing
Objective intake, exactly once. It is not a second lifecycle engine.

Every request becomes an ``Objective`` only by way of ``app.orchestrator.objectives.
Objective`` and ``intake``: the same canonical door, the same PROTECTED_PATHS, the same
default prohibited actions, the same repository-only authority class. This module adds
nothing to what an objective may authorise; it only decides, deterministically and
idempotently, which request bytes become which one objective.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.orchestrator.lifecycle import GitFacts, Kernel, LifecycleError, sha256_of
from app.orchestrator.objectives import Objective, ObjectiveStore, intake, owner_entry_from_host
from app.orchestrator.store import RecordConflictError

from .errors import InboxError, RequestContentChanged, RequestSchemaError, redact_validation_error
from .inbox import DEFAULT_INBOX_BRANCH, DEFAULT_INBOX_DIRECTORY, discover_requests, fetch_inbox
from .receipts import Receipt, ReceiptLog
from .requests import RemoteObjectiveRequest, parse_request

__all__ = [
    "RemoteController",
    "RemoteControllerConfig",
    "objective_from_request",
]


@dataclass(frozen=True)
class RemoteControllerConfig:
    """Everything the adapter needs that a remote request must never be able to supply itself."""

    repo: Path
    repository: str
    product_memory_ref: str
    remote: str = "origin"
    inbox_branch: str = DEFAULT_INBOX_BRANCH
    inbox_directory: str = DEFAULT_INBOX_DIRECTORY


def objective_from_request(
    request: RemoteObjectiveRequest,
    *,
    config: RemoteControllerConfig,
    git: GitFacts,
    created_at: datetime,
) -> Objective:
    """The one Objective this request authorises, validated only by ``Objective`` itself."""
    resolved = git.rev_parse(request.base_ref)
    if resolved is None or resolved != request.base_sha:
        raise InboxError(
            f"request {request.request_id}: base ref {request.base_ref!r} does not resolve to the "
            f"declared base sha {request.base_sha}"
        )
    memory_sha = git.rev_parse(config.product_memory_ref)
    if memory_sha is None:
        raise InboxError(f"product-memory ref {config.product_memory_ref!r} does not resolve in {config.repo}")
    try:
        return Objective(
            objective_id=request.request_id,
            title=request.title,
            requested_outcome=request.requested_outcome,
            acceptance_criteria=request.acceptance_criteria,
            checks=request.checks,
            repository=config.repository,
            base_ref=request.base_ref,
            base_sha=request.base_sha,
            target_branch=request.target_branch,
            product_memory_sha=memory_sha,
            allowed_paths=request.allowed_paths,
            max_repair_rounds=request.max_repair_rounds,
            owner=owner_entry_from_host(),
            created_at=created_at,
        )
    except ValidationError as exc:
        raise InboxError(
            f"request {request.request_id} cannot become an objective: {redact_validation_error(exc)}"
        ) from exc


@dataclass
class RemoteController:
    """Fetch, discover, validate, intake. Nothing here assigns, reviews, accepts or integrates."""

    kernel: Kernel
    objectives: ObjectiveStore
    config: RemoteControllerConfig
    receipts: ReceiptLog
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def poll_once(self) -> list[dict]:
        """One bounded fetch, then one pass over every request file found. Safe to repeat."""
        ref_sha = fetch_inbox(self.config.repo, remote=self.config.remote, branch=self.config.inbox_branch)
        return [
            self.process(raw, source=name)
            for name, raw in discover_requests(self.config.repo, ref_sha, self.config.inbox_directory)
        ]

    def process(self, raw: bytes, *, source: str) -> dict:
        """Decide one request's exact bytes, once. Replay of the same bytes repeats the decision."""
        digest = sha256_of(raw)
        try:
            request = parse_request(raw)
        except RequestSchemaError as exc:
            return {"source": source, "request_sha256": digest, "outcome": "refused", "reason": str(exc)}

        existing = self.receipts.get(request.request_id)
        if existing is not None:
            if existing.request_sha256 == digest:
                return existing.model_dump(mode="json")
            raise RequestContentChanged(
                f"request {request.request_id} is already recorded with different content; "
                "a request id is immutable: submit a new request id"
            )

        now = self.clock()
        try:
            objective = objective_from_request(request, config=self.config, git=self.kernel.git, created_at=now)
            outcome = intake(objective, kernel=self.kernel, objectives=self.objectives)
        except (LifecycleError, RecordConflictError, InboxError, ValidationError) as exc:
            refusal = Receipt(
                request_id=request.request_id,
                request_sha256=digest,
                outcome="refused",
                reason=str(exc)[:2000],
                source=source,
                recorded_at=now,
            )
            return self.receipts.put(refusal).model_dump(mode="json")

        acceptance = Receipt(
            request_id=request.request_id,
            request_sha256=digest,
            outcome="accepted",
            objective_id=outcome["objective_id"],
            task_id=outcome["task_id"],
            source=source,
            recorded_at=now,
        )
        return self.receipts.put(acceptance).model_dump(mode="json")
