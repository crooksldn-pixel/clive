"""Repository-only owner judgment primitives.

Human judgment is deliberately separate from ActionStatus. These records do not
execute, approve, or mutate an ActionProposal; they only describe a bounded,
redacted decision that a higher layer may append to the Judgment Ledger.

Every invariant is checked at construction. A ``JudgmentRecord`` that exists is
a valid one: there is no window in which a malformed judgment can be passed
around, compared or appended before somebody remembers to validate it.
``validate_judgment`` stays public for a caller that wants to re-check a record
it did not build; on a constructed record it is idempotent.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OwnerDecision(StrEnum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    EDITED = "EDITED"
    DEFERRED = "DEFERRED"


class ReasonCode(StrEnum):
    """The V1 bounded reason vocabulary. Additions require review."""

    ACCEPTED_AS_PROPOSED = "ACCEPTED_AS_PROPOSED"
    WRONG_SCOPE = "WRONG_SCOPE"
    WRONG_CONTENT = "WRONG_CONTENT"
    NEEDS_CHANGES = "NEEDS_CHANGES"
    NOT_NOW = "NOT_NOW"
    RISK_TOO_HIGH = "RISK_TOO_HIGH"
    OTHER_BOUNDED = "OTHER_BOUNDED"


class JudgmentValidationError(ValueError):
    """A judgment failed a fail-closed invariant."""


REASON_CODES_V1 = frozenset(ReasonCode)
SUPPORTED_REDACTION_VERSIONS = frozenset({1})
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

MAX_REDACTED_EXPLANATION_CHARS = 500

# Labels whose presence means the text was not redacted before it got here.
# Matching is a case-insensitive substring test: the ledger accepts bounded,
# already-redacted prose only, so a false positive costs a rewording and a
# false negative costs a leak.
_FORBIDDEN_EXPLANATION_TERMS = (
    "password",
    "secret",
    "credential",
    "api_key",
    "api key",
    "apikey",
    "private key",
    "bearer ",
    "hidden prompt",
    "hidden-prompt",
    "chain-of-thought",
    "chain of thought",
)

_SHA256_HEX_LEN = 64


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JudgmentValidationError(f"{name} is required and must be non-blank text")
    return value


def _require_version(name: str, value: object, supported: frozenset[int]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in supported:
        raise JudgmentValidationError(f"unsupported {name}")
    return value


def _require_sha256(name: str, value: object) -> str:
    # Full SHA-256 only: a truncated or ambiguous digest is not a binding.
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LEN:
        raise JudgmentValidationError(f"{name} must be a full SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise JudgmentValidationError(f"{name} must be hexadecimal") from exc
    return value.lower()


@dataclass(frozen=True, slots=True)
class OwnerProvenance:
    """Who made the decision and in which session; never how they authenticated."""

    principal_id: str
    session_id: str
    source: str | None = None

    def __post_init__(self) -> None:
        _require_text("principal_id", self.principal_id)
        _require_text("session_id", self.session_id)
        if self.source is not None:
            _require_text("source", self.source)


def proposal_fingerprint(payload: bytes | Mapping[str, object]) -> str:
    """Bind a judgment to an immutable proposal without retaining its content.

    Bytes are digested as given. A mapping is digested through one canonical
    JSON encoding, so the same proposal always yields the same fingerprint. A
    bare ``str`` is refused: its byte encoding is the caller's decision to make
    explicitly, not this function's to guess.
    """

    if isinstance(payload, (bytes, bytearray, memoryview)):
        return hashlib.sha256(bytes(payload)).hexdigest()
    if isinstance(payload, Mapping):
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    raise TypeError(f"proposal_fingerprint takes bytes or a mapping, not {type(payload).__name__}")


@dataclass(frozen=True, slots=True)
class JudgmentRecord:
    judgment_id: str
    task_id: str
    action_id: str
    proposal_id: str
    proposal_fingerprint: str
    decision: OwnerDecision
    reason_code: ReasonCode
    provenance: OwnerProvenance
    decided_at: datetime
    redaction_version: int = 1
    schema_version: int = 1
    task_revision: int | None = None
    attempt_id: str | None = None
    # EDITED only: the distinct identity of the new proposal that replaces this
    # one, and the digest of that replacement. The original is never rewritten.
    superseding_proposal_id: str | None = None
    replacement_fingerprint: str | None = None
    redacted_explanation: str | None = None

    def __post_init__(self) -> None:
        # Coerce the two vocabularies so a record rebuilt from storage carries
        # enum members, and an unknown value fails here rather than downstream.
        try:
            object.__setattr__(self, "decision", OwnerDecision(self.decision))
        except ValueError as exc:
            raise JudgmentValidationError("decision is not a V1 OwnerDecision") from exc
        try:
            object.__setattr__(self, "reason_code", ReasonCode(self.reason_code))
        except ValueError as exc:
            raise JudgmentValidationError(
                "reason_code is outside the V1 bounded vocabulary"
            ) from exc
        object.__setattr__(
            self,
            "proposal_fingerprint",
            _require_sha256("proposal_fingerprint", self.proposal_fingerprint),
        )
        if self.replacement_fingerprint is not None:
            object.__setattr__(
                self,
                "replacement_fingerprint",
                _require_sha256("replacement_fingerprint", self.replacement_fingerprint),
            )
        validate_judgment(self)


def validate_judgment(record: JudgmentRecord) -> None:
    """Every fail-closed invariant in one place, raising on the first breach."""

    if not isinstance(record, JudgmentRecord):
        raise JudgmentValidationError("not a JudgmentRecord")

    for name in ("judgment_id", "task_id", "action_id", "proposal_id"):
        _require_text(name, getattr(record, name))
    if record.task_revision is not None and (
        isinstance(record.task_revision, bool)
        or not isinstance(record.task_revision, int)
        or record.task_revision < 1
    ):
        raise JudgmentValidationError("task_revision, when given, must be a positive integer")
    if record.attempt_id is not None:
        _require_text("attempt_id", record.attempt_id)

    if not isinstance(record.provenance, OwnerProvenance):
        raise JudgmentValidationError("provenance must be an OwnerProvenance")
    _require_text("provenance.principal_id", record.provenance.principal_id)
    _require_text("provenance.session_id", record.provenance.session_id)

    if not isinstance(record.decided_at, datetime):
        raise JudgmentValidationError("decided_at must be a datetime")
    if record.decided_at.tzinfo is None or record.decided_at.utcoffset() is None:
        raise JudgmentValidationError("decided_at must be timezone-aware")

    if not isinstance(record.decision, OwnerDecision):
        raise JudgmentValidationError("decision is not a V1 OwnerDecision")
    if not isinstance(record.reason_code, ReasonCode) or record.reason_code not in REASON_CODES_V1:
        raise JudgmentValidationError("reason_code is outside the V1 bounded vocabulary")
    _require_version("redaction_version", record.redaction_version, SUPPORTED_REDACTION_VERSIONS)
    _require_version("schema_version", record.schema_version, SUPPORTED_SCHEMA_VERSIONS)

    _require_sha256("proposal_fingerprint", record.proposal_fingerprint)

    if record.decision is OwnerDecision.EDITED:
        if not record.superseding_proposal_id or not record.replacement_fingerprint:
            raise JudgmentValidationError(
                "EDITED requires a superseding proposal id and a replacement fingerprint"
            )
        _require_text("superseding_proposal_id", record.superseding_proposal_id)
        _require_sha256("replacement_fingerprint", record.replacement_fingerprint)
        if record.superseding_proposal_id == record.proposal_id:
            raise JudgmentValidationError(
                "EDITED must create a new proposal, not overwrite the original"
            )
        if record.replacement_fingerprint == record.proposal_fingerprint:
            raise JudgmentValidationError("EDITED replacement must differ from the original proposal")
    elif record.superseding_proposal_id is not None or record.replacement_fingerprint is not None:
        raise JudgmentValidationError("supersession fields are valid only for EDITED")

    # The ledger accepts already-redacted bounded text only. Obvious credential
    # and prompt labels fail closed; raw payloads belong nowhere in this record.
    if record.redacted_explanation is not None:
        if not isinstance(record.redacted_explanation, str):
            raise JudgmentValidationError("redacted_explanation must be text")
        if len(record.redacted_explanation) > MAX_REDACTED_EXPLANATION_CHARS:
            raise JudgmentValidationError("redacted_explanation exceeds bounded length")
        lowered = record.redacted_explanation.lower()
        if any(term in lowered for term in _FORBIDDEN_EXPLANATION_TERMS):
            raise JudgmentValidationError(
                "redacted_explanation contains forbidden sensitive material"
            )
