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
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from app.orchestrator.contracts import StrictRecord
from app.orchestrator.store import JsonRecordStore

from .errors import InboxError

RECEIPT_SCHEMA = "clive.remote_engineering_receipt.v1"
CLAIM_SCHEMA = "clive.remote_engineering_claim.v1"

# Fixed text: the paths are host configuration, and this reaches a long-lived process log.
ADAPTER_ROOT_NOT_IGNORED = (
    "the remote-engineering adapter directory is inside the journalled store's git work tree and is "
    "not ignored there: its claims and receipts would be untracked store state, and the kernel refuses "
    "every verb while any exists. Pass --adapter-root outside the store's work tree; nothing was started"
)


def _work_tree(path: Path) -> Path | None:
    """The git work tree ``path`` is (or, not yet created, would be) inside, if any."""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(probe), capture_output=True, text=True)
    top = proc.stdout.strip()
    return Path(top).resolve() if proc.returncode == 0 and top else None


def adapter_root_preconditions(store_root: Path, adapter_root: Path) -> None:
    """Refuse to start while claims and receipts would be untracked files in the journalled work tree.

    The kernel's journal refuses every verb while the store holds untracked files, and intake
    writes its claim before the canonical door, so an unignored adapter directory beneath the
    store would have every request refused after its id was already claimed. A store outside
    any checkout has no journal, and an adapter root outside the store's work tree cannot be
    swept into one; otherwise both record directories must be ignored by the work tree's own
    rules, or nothing starts.

    The directories themselves are what is checked, never a sample file inside them: git
    cannot re-include anything beneath an ignored directory, so that is the one answer that
    covers every request id and every temporary file. A rule matching only some file names
    is refused, however many of the real records it would happen to cover.
    """
    work_tree = _work_tree(Path(store_root).resolve())
    if work_tree is None:
        return
    adapter = Path(adapter_root).resolve()
    if not adapter.is_relative_to(work_tree):
        return
    relative = adapter.relative_to(work_tree)
    for directory in ("claims", "receipts"):
        probe = (relative / directory).as_posix()
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--", probe], cwd=str(work_tree), capture_output=True, text=True
        )
        if ignored.returncode != 0:
            raise InboxError(ADAPTER_ROOT_NOT_IGNORED)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _durable_mkdir(path: Path) -> None:
    """Create every missing level, flushing the parent that made each one reachable.

    ``mkdir(parents=True)`` leaves the new directory entries in their parents' unflushed
    metadata. On the very first intake both ``remote_engineering/`` and ``claims/`` are new,
    so a crash could lose the claims directory outright while the lifecycle writes beneath
    the store survive -- reopening exactly the missing-digest window the claim exists to
    close. Each level is therefore created and its parent flushed, deepest last.
    """
    missing = []
    probe = path
    while not probe.exists():
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _fsync_dir(directory.parent)


def _write_once(path: Path, payload: bytes) -> None:
    """Create ``path`` with exactly ``payload``, atomically, only if it does not exist yet.

    ``os.link`` is the atomic create-if-absent this needs: it either publishes a complete,
    already-fsynced file under the final name or fails with ``FileExistsError``, with no
    window in which a concurrent reader can see a partial record and no check-then-write
    race between two processes that both found the name free. The containing directory is
    flushed afterwards so the name survives a crash, not only the bytes.
    """
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError:
            return
        _fsync_dir(path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()


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
    """Append-only, keyed by request id, under its own directory of the adapter root.

    The adapter root must not be unignored journalled store state; see ``adapter_root_preconditions``.
    """

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
        _durable_mkdir(self.dir)
        _write_once(path, payload)
        if path.read_bytes() != payload:
            raise InboxError(
                f"receipt for request {receipt.request_id} is already recorded differently; "
                "a request id is immutable once decided"
            )
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
    """Write-once, keyed by request id, beside the receipts under the adapter root."""

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
        """Claim the id atomically, and return whichever claim is actually on disk.

        Two processes can both find the id unclaimed, so the create itself decides: the
        loser reads back the winner's record and continues under it. Returning the winner
        rather than the caller's own claim is what makes a concurrent admission converge on
        one ``claimed_at``, and therefore on one byte-identical objective. A winner holding
        a different digest is refused here, before any lifecycle write.
        """
        payload = JsonRecordStore._canonical_bytes(claim)
        path = self._path(claim.request_id)
        _durable_mkdir(self.dir)
        _write_once(path, payload)
        winner = self.get(claim.request_id)
        if winner is None:  # pragma: no cover -- the create above either published or lost
            raise InboxError(f"request {claim.request_id} could not be claimed")
        if winner.request_sha256 != claim.request_sha256:
            raise InboxError(
                f"request {claim.request_id} is already claimed for different content; "
                "a request id is immutable once claimed"
            )
        return winner
