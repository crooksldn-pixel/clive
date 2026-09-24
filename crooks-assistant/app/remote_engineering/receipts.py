"""Durable provenance of every inbox request CLIVE has seen. Never lifecycle truth.

Two write-once records per request id, neither of them authority:

- a **claim**, written *before* the first lifecycle write, binding the id to the exact
  bytes about to be admitted under it and to the instant they were claimed;
- a **receipt**, written *after* the decision, recording what was decided.

The claim exists because the lifecycle write and the receipt cannot be one atomic act. A
crash between them would otherwise leave an admitted objective with no durable record of
which bytes produced it, and a replay could then bind that objective to different bytes
that happen to parse to the same request. The claim closes that window from the front: it
is always the first thing on disk, so after any interruption the id is already bound, the
original bytes replay into byte-identical records (the claim also pins ``created_at``, so
the rebuilt objective is identical rather than merely equivalent), and every other byte
sequence for that id is refused. Neither record can create or advance a task: the kernel's
own records remain the one lifecycle authority.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from app.orchestrator.contracts import StrictRecord
from app.orchestrator.store import JsonRecordStore

from .errors import InboxError

RECEIPT_SCHEMA = "clive.remote_engineering_receipt.v1"
CLAIM_SCHEMA = "clive.remote_engineering_claim.v1"


def _durable_write(path: Path, payload: bytes) -> None:
    """Write once, and make the name itself survive a crash, not only the bytes.

    ``JsonRecordStore._atomic_write`` fsyncs the file before renaming it, which is what
    these records need for their contents. It does not fsync the containing directory, so
    on a crash the rename can still be lost even though the data reached the disk. These
    records exist precisely to survive that crash, so the directory entry is flushed too.
    """
    JsonRecordStore._atomic_write(path, payload)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Receipt(StrictRecord):
    schema_version: Literal["clive.remote_engineering_receipt.v1"] = RECEIPT_SCHEMA
    request_id: str = Field(min_length=1, max_length=120)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["accepted", "refused"]
    reason: str | None = Field(default=None, max_length=2000)
    objective_id: str | None = Field(default=None, max_length=120)
    task_id: str | None = Field(default=None, max_length=120)
    source: str = Field(min_length=1, max_length=500)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class ReceiptLog:
    """Append-only, keyed by request id, under its own directory of the engineering store."""

    def __init__(self, root: Path) -> None:
        self.dir = Path(root) / "receipts"

    def _path(self, request_id: str) -> Path:
        return self.dir / f"{request_id}.json"

    def get(self, request_id: str) -> Receipt | None:
        path = self._path(request_id)
        if not path.exists():
            return None
        return Receipt.model_validate_json(path.read_text(encoding="utf-8"))

    def read_all(self) -> tuple[Receipt, ...]:
        if not self.dir.exists():
            return ()
        return tuple(
            Receipt.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.dir.glob("*.json"))
        )

    def put(self, receipt: Receipt) -> Receipt:
        """Write once. Identical bytes are idempotent; a changed receipt for the same id is refused."""
        payload = JsonRecordStore._canonical_bytes(receipt)
        path = self._path(receipt.request_id)
        if path.exists():
            if path.read_bytes() == payload:
                return receipt
            raise InboxError(
                f"receipt for request {receipt.request_id} is already recorded differently; "
                "a request id is immutable once decided"
            )
        self.dir.mkdir(parents=True, exist_ok=True)
        _durable_write(path, payload)
        return receipt


class Claim(StrictRecord):
    """The id-to-bytes binding written before anything authoritative. Pointers only."""

    schema_version: Literal["clive.remote_engineering_claim.v1"] = CLAIM_SCHEMA
    request_id: str = Field(min_length=1, max_length=120)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claimed_at: datetime

    @field_validator("claimed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class ClaimLog:
    """Write-once, keyed by request id, beside the receipts in the engineering store."""

    def __init__(self, root: Path) -> None:
        self.dir = Path(root) / "claims"

    def _path(self, request_id: str) -> Path:
        return self.dir / f"{request_id}.json"

    def get(self, request_id: str) -> Claim | None:
        path = self._path(request_id)
        if not path.exists():
            return None
        return Claim.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, claim: Claim) -> Claim:
        """Write once. Identical bytes are idempotent; a different claim for the id is refused."""
        payload = JsonRecordStore._canonical_bytes(claim)
        path = self._path(claim.request_id)
        if path.exists():
            if path.read_bytes() == payload:
                return claim
            raise InboxError(
                f"request {claim.request_id} is already claimed for different content; "
                "a request id is immutable once claimed"
            )
        self.dir.mkdir(parents=True, exist_ok=True)
        _durable_write(path, payload)
        return claim
