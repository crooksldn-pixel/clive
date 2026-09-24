"""Tamper-evident serialization for the append-only Judgment Ledger.

This module adds deterministic entry hashing, predecessor binding, and optional
external head/count anchoring without turning the ledger into an execution or
authorization mechanism.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .judgment import JudgmentRecord
from .judgment_ledger import JudgmentLedger, JudgmentLedgerError

GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class ChainedJudgment:
    record: JudgmentRecord
    previous_hash: str
    entry_hash: str


@dataclass(frozen=True, slots=True)
class JudgmentChainAnchor:
    """Minimal external checkpoint needed to detect valid-prefix truncation."""

    entry_count: int
    head_hash: str


def _validate_digest(value: str, field: str) -> None:
    if len(value) != 64:
        raise JudgmentLedgerError(f"{field} must be a full SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise JudgmentLedgerError(f"{field} must be hexadecimal") from exc


def _record_payload(record: JudgmentRecord) -> dict[str, object]:
    payload = asdict(record)
    payload["decision"] = record.decision.value
    return payload


def judgment_entry_hash(record: JudgmentRecord, previous_hash: str) -> str:
    _validate_digest(previous_hash, "previous_hash")
    envelope = {"previous_hash": previous_hash, "record": _record_payload(record)}
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def chain_ledger(ledger: JudgmentLedger) -> tuple[ChainedJudgment, ...]:
    """Produce deterministic predecessor-bound entries for a validated ledger."""
    previous = GENESIS_HASH
    chained: list[ChainedJudgment] = []
    for record in ledger.records:
        entry_hash = judgment_entry_hash(record, previous)
        chained.append(ChainedJudgment(record=record, previous_hash=previous, entry_hash=entry_hash))
        previous = entry_hash
    return tuple(chained)


def chain_anchor(entries: tuple[ChainedJudgment, ...]) -> JudgmentChainAnchor:
    """Return a minimal checkpoint suitable for storage outside the ledger payload."""
    head_hash = entries[-1].entry_hash if entries else GENESIS_HASH
    _validate_digest(head_hash, "head_hash")
    return JudgmentChainAnchor(entry_count=len(entries), head_hash=head_hash)


def verify_chain(
    entries: tuple[ChainedJudgment, ...],
    *,
    expected_anchor: JudgmentChainAnchor | None = None,
) -> JudgmentLedger:
    """Rebuild and validate a ledger, failing closed on mutation/reordering/removal.

    Predecessor hashing detects internal mutation, insertion, reordering and middle
    removal. A caller that needs truncation detection must supply an independently
    retained ``expected_anchor``; without an external checkpoint, a valid prefix is
    cryptographically indistinguishable from the complete historical ledger.
    """
    if expected_anchor is not None:
        if expected_anchor.entry_count < 0:
            raise JudgmentLedgerError("anchor entry_count must be non-negative")
        _validate_digest(expected_anchor.head_hash, "anchor head_hash")

    previous = GENESIS_HASH
    records: list[JudgmentRecord] = []
    for entry in entries:
        if entry.previous_hash != previous:
            raise JudgmentLedgerError("judgment chain predecessor mismatch")
        expected = judgment_entry_hash(entry.record, previous)
        if entry.entry_hash != expected:
            raise JudgmentLedgerError("judgment chain entry hash mismatch")
        records.append(entry.record)
        previous = entry.entry_hash

    if expected_anchor is not None:
        if len(entries) != expected_anchor.entry_count:
            raise JudgmentLedgerError("judgment chain entry count does not match anchor")
        if previous != expected_anchor.head_hash:
            raise JudgmentLedgerError("judgment chain head does not match anchor")

    return JudgmentLedger.from_records(records)
