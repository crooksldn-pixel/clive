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

A request whose base commit the engineering repo does not have yet is not refused: the trunk
is fetched once per poll (time-bounded, the configured remote and trunk branch only), and if the
commit is still absent the request waits, with nothing claimed or receipted, and is asked again
on the next poll (waits.py). It is refused, exactly as before, only when its ref resolves to a
different commit, or when its base is still missing past the bound recorded at first sight.
"""

from __future__ import annotations

import subprocess
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

from .errors import (
    InboxError,
    RequestContentChanged,
    RequestSchemaError,
    redact_refusal,
    redact_validation_error,
    supplied_strings,
)
from .inbox import (
    DEFAULT_INBOX_BRANCH,
    DEFAULT_INBOX_DIRECTORY,
    DEFAULT_TRUNK_BRANCH,
    _validate_name,
    bounded_source,
    discover_requests,
    fetch_inbox,
    fetch_trunk,
    validate_inbox_directory,
)
from .publisher import validate_seconds
from .receipts import Claim, ClaimLog, Receipt, ReceiptLog
from .requests import RemoteObjectiveRequest, parse_request
from .waits import DEFAULT_BASE_WAIT_S, MAX_BASE_WAIT_S, MIN_BASE_WAIT_S, BaseWait, WaitLog

# A build's repair rounds when its request names none, and the most any objective may have (objectives.py).
DEFAULT_REPAIR_ROUNDS = 2
MAX_REPAIR_ROUNDS = 5

# Every field label this host itself defined; see ``redact_validation_error``.
OBJECTIVE_LABELS = frozenset(Objective.model_fields) | frozenset(Check.model_fields)

# Fixed words for the host log and the projection: git's own output never travels (TransportError).
TRUNK_UNAVAILABLE = (
    "the trunk could not be fetched this cycle; a request whose base commit is missing stays waiting"
)

__all__ = [
    "DEFAULT_REPAIR_ROUNDS",
    "MAX_REPAIR_ROUNDS",
    "OBJECTIVE_LABELS",
    "TRUNK_UNAVAILABLE",
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
    # Where a request's base is normally found, and how long a request whose base commit the
    # engineering repo still lacks waits for it before it is refused (waits.py).
    trunk_branch: str = DEFAULT_TRUNK_BRANCH
    base_wait_s: float = DEFAULT_BASE_WAIT_S
    # How many repair rounds a build gets when its request names none (the owner's loop upgrade of 7 October 2026,
    # "more repair rounds"): the convergence doctrine's 2 unless the owner raises it on this host. A request that
    # names its own limit keeps it.
    default_repair_rounds: int = DEFAULT_REPAIR_ROUNDS

    def __post_init__(self) -> None:
        # One plain path component, refused without echo; and whatever it is, it is never
        # serialized: receipts and the projection name records by a fixed label (inbox.py).
        validate_inbox_directory(self.inbox_directory)
        _validate_name(self.trunk_branch, what="trunk branch")
        validate_seconds(self.base_wait_s, what="base wait", minimum=MIN_BASE_WAIT_S, maximum=MAX_BASE_WAIT_S)
        if isinstance(self.default_repair_rounds, bool) or not isinstance(self.default_repair_rounds, int) \
                or not 0 <= self.default_repair_rounds <= MAX_REPAIR_ROUNDS:
            raise ValueError(f"the default repair rounds are a whole number from 0 to {MAX_REPAIR_ROUNDS}")


def objective_from_request(
    request: RemoteObjectiveRequest,
    *,
    config: RemoteControllerConfig,
    git: GitFacts,
    created_at: datetime,
    admitted: Objective | None = None,
) -> Objective:
    """The one Objective this request authorises, validated only by ``Objective`` itself.

    ``admitted`` is the objective an interrupted admission of this same claimed request already
    recorded. Its base and product-memory commits were resolved then; the loop's own fetches
    move the trunk ref since (landing, a base fetch), so a replay rebuilds from those commits
    rather than resolving the refs again, and stays byte-identical (the #70 pre-review)."""
    if admitted is None or admitted.base_sha != request.base_sha:
        resolved = git.rev_parse(request.base_ref)
        if resolved is None or resolved != request.base_sha:
            # Never echo base_ref: it is requester-supplied and this reason is persisted in a
            # receipt and published. The request id and the declared sha are both bounded.
            raise InboxError(
                f"request {request.request_id}: base ref does not resolve to the "
                f"declared base sha {request.base_sha}"
            )
    memory_sha = admitted.product_memory_sha if admitted is not None else git.rev_parse(config.product_memory_ref)
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
            max_repair_rounds=_repair_rounds(request, config=config, admitted=admitted),
            owner=owner_entry_from_host(),
            created_at=created_at,
        )
    except ValidationError as exc:
        raise InboxError(
            f"request {request.request_id} cannot become an objective: "
            f"{redact_validation_error(exc, known=OBJECTIVE_LABELS)}"
        ) from exc


def _repair_rounds(request: RemoteObjectiveRequest, *, config: RemoteControllerConfig,
                   admitted: Objective | None) -> int:
    """The request's own limit; else the one its interrupted admission already recorded (so a replay stays
    byte-identical when the host default changed in between); else this host's default."""
    if request.max_repair_rounds is not None:
        return request.max_repair_rounds
    if admitted is not None:
        return admitted.max_repair_rounds
    return config.default_repair_rounds


@dataclass
class RemoteController:
    """Fetch, discover, validate, intake. Nothing here assigns, reviews, accepts or integrates."""

    kernel: Kernel
    objectives: ObjectiveStore
    config: RemoteControllerConfig
    receipts: ReceiptLog
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    claims: ClaimLog | None = None
    waits: WaitLog | None = None
    # TRUNK_UNAVAILABLE when this poll needed the trunk and could not fetch it, else None.
    trunk_fetch_error: str | None = field(default=None, init=False)
    # Within a poll: whether the trunk was fetched yet (at most once per poll). None outside one.
    _trunk_fetched: bool | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # Claims live beside the receipts, under the same adapter root, so every existing
        # caller gets one without being changed. So do the waits.
        if self.claims is None:
            self.claims = ClaimLog(self.receipts.dir.parent)
        if self.waits is None:
            self.waits = WaitLog(self.receipts.dir.parent)

    def poll_once(self) -> list[dict]:
        """One bounded fetch, one preflight of the whole snapshot, then one pass over it.

        Safe to repeat. Nothing is written unless every applicable request in the snapshot
        agrees with what is already recorded under its id. A request whose base commit the
        engineering repo lacks, even after one bounded fetch of the trunk, is deferred to the
        next poll with nothing written but its wait; the waits kept are exactly this poll's.
        """
        self.trunk_fetch_error = None
        ref_sha = fetch_inbox(self.config.repo, remote=self.config.remote, branch=self.config.inbox_branch)
        discovered = discover_requests(self.config.repo, ref_sha, self.config.inbox_directory)
        self._preflight(discovered)
        self._trunk_fetched = False
        try:
            outcomes = [self.process(raw, source=name) for name, raw in discovered]
        finally:
            self._trunk_fetched = None
        self.waits.retain({item["request_id"] for item in outcomes if item.get("outcome") == "waiting"})
        return outcomes

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
            # An id claimed but not yet receipted was interrupted mid-admission. It is bound
            # to its claimed bytes just as firmly, so the whole snapshot is refused here too.
            claimed = self.claims.get(request.request_id)
            if claimed is not None and claimed.request_sha256 != digest:
                raise RequestContentChanged(
                    f"request {request.request_id} is already claimed for different content; "
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

        claimed = self.claims.get(request.request_id)
        if claimed is not None and claimed.request_sha256 != digest:
            raise RequestContentChanged(
                f"request {request.request_id} is already claimed for different content; "
                "a request id is immutable: submit a new request id"
            )

        # A base commit the engineering repo has not fetched yet defers the request rather than
        # refusing it: nothing is claimed or receipted, so nothing is burned, and the next poll
        # asks again. Only a base still missing past the recorded bound goes on to be refused.
        waiting, overdue = self._await_base(request, digest=digest, source=source)
        if waiting is not None:
            return waiting

        # Bind this id to these exact bytes before the first lifecycle write. A crash
        # between intake and the receipt would otherwise leave an admitted objective with
        # no durable digest, and a later replay could bind it to different bytes that
        # happen to parse to the same request. The claim is provenance, never authority:
        # it admits nothing and advances nothing on its own.
        admitted = None
        if claimed is None:
            claimed = self.claims.put(
                Claim(request_id=request.request_id, request_sha256=digest, claimed_at=self.clock())
            )
        else:
            # A replay of this claimed request: whatever its interrupted admission recorded is
            # rebuilt from, never re-resolved from refs that have moved since.
            admitted = self.objectives.read(request.request_id)

        # The claimed instant, not the current one, so a resumed admission rebuilds the
        # byte-identical objective rather than a merely equivalent one.
        now = claimed.claimed_at
        try:
            if overdue is not None:
                raise InboxError(overdue)
            objective = objective_from_request(request, config=self.config, git=self.kernel.git, created_at=now,
                                               admitted=admitted)
            outcome = intake(objective, kernel=self.kernel, objectives=self.objectives)
        except (LifecycleError, RecordConflictError, InboxError, ValidationError) as exc:
            # A ValidationError reaching here unwrapped (from intake, not from the objective
            # builder above) still stringifies its rejected input, so it is redacted too.
            reason = (
                redact_validation_error(exc, known=OBJECTIVE_LABELS)
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            # Validators downstream (the Objective door, the kernel) quote what they reject,
            # sometimes normalised; no supplied value may reach a receipt or the projection.
            reason = redact_refusal(
                reason, supplied_strings(request.model_dump(mode="json")), keep=(request.request_id,)
            )
            refusal = Receipt(
                request_id=request.request_id,
                request_sha256=digest,
                outcome="refused",
                reason=reason[:2000],
                source=source,
                recorded_at=now,
            )
            return self._decided(self.receipts.put(refusal))

        acceptance = Receipt(
            request_id=request.request_id,
            request_sha256=digest,
            outcome="accepted",
            objective_id=outcome["objective_id"],
            task_id=outcome["task_id"],
            source=source,
            recorded_at=now,
        )
        return self._decided(self.receipts.put(acceptance))

    def _decided(self, receipt: Receipt) -> dict:
        """A decided id waits for nothing any more."""
        self.waits.clear(receipt.request_id)
        return receipt.model_dump(mode="json")

    def _await_base(
        self, request: RemoteObjectiveRequest, *, digest: str, source: str
    ) -> tuple[dict | None, str | None]:
        """``(waiting outcome, None)`` to defer; ``(None, reason)`` to refuse a base past its bound;
        ``(None, None)`` to go on to admission, which refuses a ref naming another commit as before.

        The clock is read only when the base is missing, so an admission's claimed instant is the
        first reading of it exactly as before this deferral existed.
        """
        git = self.kernel.git
        if git.rev_parse(request.base_ref) == request.base_sha:
            return None, None
        # The ref names another commit, or none: the trunk may simply not have been fetched since
        # the commit the request names was merged. Fetch it once (per poll), then look again.
        self._fetch_trunk_once()
        if git.commit_exists(request.base_sha):
            return None, None
        now = self.clock()
        wait = self.waits.note(request_id=request.request_id, request_sha256=digest, source=source,
                               now=now, bound_s=self.config.base_wait_s)
        if now < wait.refuse_after:
            return wait.outcome() | {"durable": False}, None
        # Today's wording first (it is redacted like every refusal, so the declared sha never
        # travels), then why it was refused only now.
        return None, (
            f"request {request.request_id}: base ref does not resolve to the declared base sha "
            f"{request.base_sha}; the engineering repo still did not have that commit "
            f"{_span(wait)} after the loop first saw the request"
        )

    def _fetch_trunk_once(self) -> None:
        """One time-bounded fetch of the configured trunk: once per poll, or once per direct call.

        A failure is not a refusal: the base is then still missing and the request waits, and the
        cycle says so in fixed words (``TRUNK_UNAVAILABLE``), never in git's."""
        if self._trunk_fetched:
            return
        if self._trunk_fetched is not None:
            self._trunk_fetched = True
        try:
            fetch_trunk(self.config.repo, remote=self.config.remote, branch=self.config.trunk_branch)
        except (InboxError, subprocess.TimeoutExpired, OSError):
            self.trunk_fetch_error = TRUNK_UNAVAILABLE


def _span(wait: BaseWait) -> str:
    """The recorded bound in words: "1 hour", "90 minutes"."""
    seconds = int(round((wait.refuse_after - wait.first_seen_at).total_seconds()))
    for size, unit in ((3600, "hour"), (60, "minute")):
        if seconds % size == 0:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''}"
    return f"{seconds} seconds"
