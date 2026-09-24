"""The adapter: discovers inbox requests and pushes each one through the existing
Objective intake, exactly once. It is not a second lifecycle engine.

Every request becomes an ``Objective`` only by way of ``app.orchestrator.objectives.
Objective`` and ``intake``: the same canonical door, the same PROTECTED_PATHS, the same
default prohibited actions, the same repository-only authority class. This module adds
nothing to what an objective may authorise; it only decides, deterministically and
idempotently, which request bytes become which one objective.

Admission is atomic per poll. The whole discovered snapshot is preflighted before the
first write, so a snapshot that re-presents an already-decided request id with different
bytes admits nothing at all -- not even the requests that happen to sort before it. The
alternative, refusing partway through a sequence of writes, would make "a changed request
id is refused" depend on filename order and would leave the cycle half-applied.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.orchestrator.lifecycle import GitFacts, Kernel, LifecycleError, sha256_of
from app.orchestrator.objectives import (
    Check,
    Objective,
    ObjectiveStore,
    intake,
    owner_entry_from_host,
)
from app.orchestrator.store import RecordConflictError

from .errors import InboxError, RequestContentChanged, RequestSchemaError, redact_validation_error
from .inbox import (
    DEFAULT_INBOX_BRANCH,
    DEFAULT_INBOX_DIRECTORY,
    bounded_source,
    discover_requests,
    fetch_inbox,
)
from .receipts import Receipt, ReceiptLog
from .requests import RemoteObjectiveRequest, parse_request

# Every field label this host itself defined; see ``redact_validation_error``.
OBJECTIVE_LABELS = frozenset(Objective.model_fields) | frozenset(Check.model_fields)

__all__ = [
    "OBJECTIVE_LABELS",
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
        # Never echo base_ref: it is requester-supplied and this reason is persisted in a
        # receipt and published. The request id and the declared sha are both bounded.
        raise InboxError(
            f"request {request.request_id}: base ref does not resolve to the "
            f"declared base sha {request.base_sha}"
        )
    memory_sha = git.rev_parse(config.product_memory_ref)
    if memory_sha is None:
        # The ref and the repo path are the operator's own configuration, and this reason is
        # published; the operator reads the ref back off the unit file, not off a public branch.
        raise InboxError("the host's configured product-memory ref does not resolve in the engineering repo")
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
            f"request {request.request_id} cannot become an objective: "
            f"{redact_validation_error(exc, known=OBJECTIVE_LABELS)}"
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
        """One bounded fetch, one preflight of the whole snapshot, then one pass over it.

        Safe to repeat. Nothing is written unless every applicable request in the snapshot
        agrees with what is already recorded under its id.
        """
        ref_sha = fetch_inbox(self.config.repo, remote=self.config.remote, branch=self.config.inbox_branch)
        discovered = discover_requests(self.config.repo, ref_sha, self.config.inbox_directory)
        self._preflight(discovered)
        return [self.process(raw, source=name) for name, raw in discovered]

    def _preflight(self, discovered: tuple[tuple[str, bytes], ...]) -> None:
        """Refuse the whole cycle, before any write, if an immutable id is re-presented changed.

        Schema-invalid records are skipped here: they are refused by ``process`` without
        writing anything, and they carry no id this adapter would trust as a key anyway.
        """
        digests: dict[str, str] = {}
        for _name, raw in discovered:
            digest = sha256_of(raw)
            try:
                request = parse_request(raw)
            except RequestSchemaError:
                continue
            earlier = digests.get(request.request_id)
            if earlier is not None and earlier != digest:
                raise RequestContentChanged(
                    f"request {request.request_id} appears twice in this inbox snapshot with "
                    "different content; a request id is immutable: submit a new request id"
                )
            digests[request.request_id] = digest
            existing = self.receipts.get(request.request_id)
            if existing is not None and existing.request_sha256 != digest:
                raise RequestContentChanged(
                    f"request {request.request_id} is already recorded with different content; "
                    "a request id is immutable: submit a new request id"
                )

    def process(self, raw: bytes, *, source: str) -> dict:
        """Decide one request's exact bytes, once. Replay of the same bytes repeats the decision."""
        digest = sha256_of(raw)
        directory = self.config.inbox_directory.strip("/")
        try:
            request = parse_request(raw)
        except RequestSchemaError as exc:
            source = bounded_source(directory, source, digest, None)
            # No trustworthy request id exists here, so nothing about this record's own
            # naming may be echoed: it is keyed by its bounded locator and the digest of its
            # exact bytes. It earns no receipt -- nothing was decided about an id -- but it
            # is still projected, so a Director polling GitHub can see that the record was
            # seen and refused. ``reason`` is a redacted schema diagnostic only; it never
            # carries the rejected content.
            return {
                "refusal_id": f"{source}@{digest}",
                "source": source,
                "request_sha256": digest,
                "outcome": "refused",
                "durable": False,
                "reason": str(exc),
            }

        source = bounded_source(directory, source, digest, request.request_id)
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
            # A ValidationError reaching here unwrapped (from intake, not from the objective
            # builder above) still stringifies its rejected input, so it is redacted too.
            reason = (
                redact_validation_error(exc, known=OBJECTIVE_LABELS)
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            refusal = Receipt(
                request_id=request.request_id,
                request_sha256=digest,
                outcome="refused",
                reason=reason[:2000],
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
