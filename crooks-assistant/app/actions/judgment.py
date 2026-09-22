"""Repository-only owner judgment primitives.

Human judgment is deliberately separate from ActionStatus.  These records do not
execute, approve, or mutate an ActionProposal; they only describe a bounded,
redacted decision that a higher layer may append to the Judgment Ledger.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class OwnerDecision(StrEnum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    EDITED = "EDITED"
    DEFERRED = "DEFERRED"


class JudgmentValidationError(ValueError):
    """A judgment failed a fail-closed invariant."""


# V1 vocabulary is intentionally small and versioned. Additions require review.
REASON_CODES_V1 = frozenset(
    {
        "ACCEPT_AS_PROPOSED",
        "WRONG_SCOPE",
        "WRONG_CONTENT",
        "NEEDS_CHANGES",
        "NOT_NOW",
        "RISK_TOO_HIGH",
        "OTHER_BOUNDED",
    }
)

SUPPORTED_REDACTION_VERSIONS = frozenset({1})
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


@dataclass(frozen=True, slots=True)
class OwnerProvenance:
    principal_id: str
    source: str


@dataclass(frozen=True, slots=True)
class JudgmentRecord:
    judgment_id: str
    task_id: str
    action_id: str
    proposal_id: str
    proposal_fingerprint: str
    decision: OwnerDecision
    reason_code: str
    provenance: OwnerProvenance
    decided_at: str
    redaction_version: int = 1
    schema_version: int = 1
    task_revision: int | None = None
    attempt_id: str | None = None
    supersedes_proposal_id: str | None = None
    replacement_fingerprint: str | None = None
    redacted_explanation: str | None = None


def proposal_fingerprint(payload: Mapping[str, object]) -> str:
    """Bind judgment to an immutable proposal without retaining proposal content."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_judgment(record: JudgmentRecord) -> None:
    required = {
        "judgment_id": record.judgment_id,
        "task_id": record.task_id,
        "action_id": record.action_id,
        "proposal_id": record.proposal_id,
        "proposal_fingerprint": record.proposal_fingerprint,
        "principal_id": record.provenance.principal_id,
        "provenance_source": record.provenance.source,
        "decided_at": record.decided_at,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        raise JudgmentValidationError(f"missing required judgment fields: {', '.join(sorted(missing))}")

    if record.reason_code not in REASON_CODES_V1:
        raise JudgmentValidationError("reason_code is outside the V1 bounded vocabulary")
    if record.redaction_version not in SUPPORTED_REDACTION_VERSIONS:
        raise JudgmentValidationError("unsupported redaction_version")
    if record.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise JudgmentValidationError("unsupported schema_version")

    # Full SHA-256 avoids weak or ambiguous proposal binding.
    if len(record.proposal_fingerprint) != 64:
        raise JudgmentValidationError("proposal_fingerprint must be a full SHA-256 digest")
    try:
        int(record.proposal_fingerprint, 16)
    except ValueError as exc:
        raise JudgmentValidationError("proposal_fingerprint must be hexadecimal") from exc

    if record.decision is OwnerDecision.EDITED:
        if not record.supersedes_proposal_id or not record.replacement_fingerprint:
            raise JudgmentValidationError("EDITED requires superseding proposal identity and fingerprint")
        if record.supersedes_proposal_id != record.proposal_id:
            raise JudgmentValidationError("EDITED must identify the original proposal it supersedes")
        if record.replacement_fingerprint == record.proposal_fingerprint:
            raise JudgmentValidationError("EDITED replacement must differ from the original proposal")
    elif record.supersedes_proposal_id or record.replacement_fingerprint:
        raise JudgmentValidationError("supersession fields are valid only for EDITED")

    # The ledger accepts already-redacted bounded text only. Obvious credential/prompt
    # labels fail closed; raw payloads belong nowhere in this record.
    if record.redacted_explanation:
        lowered = record.redacted_explanation.lower()
        forbidden = ("password", "secret", "credential", "api_key", "api key", "hidden prompt", "chain-of-thought")
        if any(term in lowered for term in forbidden):
            raise JudgmentValidationError("redacted_explanation contains forbidden sensitive material")
        if len(record.redacted_explanation) > 500:
            raise JudgmentValidationError("redacted_explanation exceeds bounded length")
