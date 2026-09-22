"""Tamper-evident serialization for the append-only Judgment Ledger.

This module adds deterministic entry hashing and predecessor binding without
turning the ledger into an execution or authorization mechanism.
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


def _record_payload(record: JudgmentRecord) -> dict[str, object]:
    payload = asdict(record)
    payload["decision"] = record.decision.value
    return payload


def judgment_entry_hash(record: JudgmentRecord, previous_hash: str) -> str:
    if len(previous_hash) != 64:
        raise JudgmentLedgerError("previous_hash must be a full SHA-256 digest")
    try:
        int(previous_hash, 16)
    except ValueError as exc:
        raise JudgmentLedgerError("previous_hash must be hexadecimal") from exc

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


def verify_chain(entries: tuple[ChainedJudgment, ...]) -> JudgmentLedger:
    """Rebuild and validate a ledger, failing closed on mutation/reordering/removal."""
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
    return JudgmentLedger.from_records(records)
