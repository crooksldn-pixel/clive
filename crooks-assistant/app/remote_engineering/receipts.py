"""Durable provenance of every inbox request CLIVE has seen. Never lifecycle truth.

One immutable file per request id, written the first time that id is decided. A
replay with identical bytes returns the stored receipt unchanged, whether it was
accepted or refused; a different request reusing the same id is refused before it
touches anything else. This is CLIVE's own bookkeeping for GitHub-visible status: the
kernel's own records (objectives, tasks, attempts, reviews, integrations) remain the
one lifecycle authority, and nothing here can create or advance any of them.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from app.orchestrator.contracts import StrictRecord
from app.orchestrator.store import JsonRecordStore

from .errors import InboxError

RECEIPT_SCHEMA = "clive.remote_engineering_receipt.v1"


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
        JsonRecordStore._atomic_write(path, payload)
        return receipt
