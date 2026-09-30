"""Requests waiting for their base commit to reach the engineering repo. Never lifecycle truth.

A request names its base by an exact commit. The filing tool on production names the trunk head
it reads at filing time, so a request filed minutes after a merge can name a commit the
engineering repo has not fetched yet (30 Sep 2026: one did, and was refused, its id burned). Such
a request is not refused: the trunk is fetched once, and if the commit is still absent the
request is *deferred* -- no claim, no receipt, nothing burned -- and asked again on the next poll.

The deferral has a bound, counted from the first poll that saw these exact bytes and recorded
here, under the adapter root beside the claims and receipts, so a restart keeps counting from
the same instant instead of starting over. Past it the request is refused exactly as an
unresolvable base always was. One small record per waiting request id:

- the id, the digest of the exact bytes that are waiting, and their bounded inbox locator;
- when they were first seen, and the instant after which they are refused.

The declared base SHA is deliberately not kept here and not published: it is requester-supplied,
and nothing a requester supplied is echoed into a host log or the projection (the echo bounds).

Unlike a claim or a receipt this record binds nothing and decides nothing. Different bytes under
the same id simply start their own wait; a record that cannot be read is treated as absent and
replaced (the wait restarts, which only delays a refusal); and a poll leaves records only for the
requests that are still waiting in its snapshot.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from app.orchestrator.contracts import StrictRecord
from app.orchestrator.store import JsonRecordStore

from .receipts import _durable_mkdir, _fsync_dir

WAIT_SCHEMA = "clive.remote_engineering_base_wait.v1"
DEFAULT_BASE_WAIT_S = 3600.0
MIN_BASE_WAIT_S = 60.0
MAX_BASE_WAIT_S = 86_400.0
# Fixed words: nothing here is chosen by the requester, so nothing needs redacting.
BASE_WAIT_REASON = "waiting for the engineering repo to fetch the base commit it names"


class BaseWait(StrictRecord):
    schema_version: Literal["clive.remote_engineering_base_wait.v1"] = WAIT_SCHEMA
    request_id: str = Field(min_length=1, max_length=120)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1, max_length=500)
    first_seen_at: datetime
    refuse_after: datetime

    @field_validator("first_seen_at", "refuse_after")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    def outcome(self) -> dict:
        """What the loop reports for a waiting request: pointers and fixed words only."""
        return {
            "request_id": self.request_id,
            "source": self.source,
            "request_sha256": self.request_sha256,
            "outcome": "waiting",
            "reason": BASE_WAIT_REASON,
            "waiting_since": self.first_seen_at.isoformat(),
            "refuse_after": self.refuse_after.isoformat(),
        }


class WaitLog:
    """One replaceable record per waiting request id, under ``<adapter root>/waits``."""

    def __init__(self, root: Path) -> None:
        self.dir = Path(root) / "waits"

    def _path(self, request_id: str) -> Path:
        return self.dir / f"{request_id}.json"

    def get(self, request_id: str) -> BaseWait | None:
        try:
            return BaseWait.model_validate_json(self._path(request_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def read_all(self) -> tuple[BaseWait, ...]:
        if not self.dir.exists():
            return ()
        out = []
        for path in sorted(self.dir.glob("*.json")):
            wait = self.get(path.stem)
            if wait is not None:
                out.append(wait)
        return tuple(out)

    def note(self, *, request_id: str, request_sha256: str, source: str, now: datetime, bound_s: float) -> BaseWait:
        """The wait these exact bytes are in, starting it at ``now`` if they are not waiting yet."""
        existing = self.get(request_id)
        if existing is not None and existing.request_sha256 == request_sha256:
            return existing
        wait = BaseWait(
            request_id=request_id,
            request_sha256=request_sha256,
            source=source,
            first_seen_at=now,
            refuse_after=now + timedelta(seconds=bound_s),
        )
        _durable_mkdir(self.dir)
        _replace(self._path(request_id), JsonRecordStore._canonical_bytes(wait))
        return wait

    def clear(self, request_id: str) -> None:
        path = self._path(request_id)
        if path.exists():
            path.unlink(missing_ok=True)
            _fsync_dir(self.dir)

    def retain(self, request_ids: set[str]) -> None:
        """Keep only the records of the requests a poll found still waiting."""
        if not self.dir.exists():
            return
        for path in sorted(self.dir.glob("*.json")):
            if path.stem not in request_ids:
                self.clear(path.stem)


def _replace(path: Path, payload: bytes) -> None:
    """Write ``path`` atomically: a complete, fsynced file under the final name, or the old one."""
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_dir(path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()
