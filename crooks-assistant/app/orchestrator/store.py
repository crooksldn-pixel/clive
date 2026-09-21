"""Filesystem-backed repository-only record store for Phase 1 simulation.

The store is intentionally simple:
- immutable task revisions and attempts are addressed by identity;
- publishing the same bytes twice is idempotent;
- publishing different bytes to an existing identity fails closed;
- writes are atomic on a single filesystem via os.replace;
- no watcher, service, deployment or external side effects are included.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, TypeVar

from pydantic import BaseModel

from .contracts import ActiveState, EngineeringResult, EngineeringTask


ModelT = TypeVar("ModelT", bound=BaseModel)


class RecordConflictError(RuntimeError):
    """Raised when an immutable record identity is reused with different content."""


class JsonRecordStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.tasks_dir = self.root / "tasks"
        self.results_dir = self.root / "results"
        self.state_path = self.root / "ACTIVE_STATE.json"

    def ensure_layout(self) -> None:
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def put_task(self, task: EngineeringTask) -> Path:
        path = self.tasks_dir / f"{task.task_id}.r{task.revision}.json"
        self._put_immutable(path, task)
        return path

    def put_result(self, result: EngineeringResult) -> Path:
        path = self.results_dir / result.task_id / f"{result.attempt_id}.json"
        self._put_immutable(path, result)
        return path

    def write_active_state(self, state: ActiveState) -> Path:
        self.ensure_layout()
        self._atomic_write(self.state_path, self._canonical_bytes(state))
        return self.state_path

    def read_tasks(self) -> tuple[EngineeringTask, ...]:
        if not self.tasks_dir.exists():
            return ()
        records = [
            EngineeringTask.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.tasks_dir.glob("*.json"))
        ]
        return tuple(records)

    def read_results(self) -> tuple[EngineeringResult, ...]:
        if not self.results_dir.exists():
            return ()
        records = [
            EngineeringResult.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.results_dir.glob("*/*.json"))
        ]
        return tuple(records)

    def read_active_state(self) -> ActiveState | None:
        if not self.state_path.exists():
            return None
        return ActiveState.model_validate_json(self.state_path.read_text(encoding="utf-8"))

    def _put_immutable(self, path: Path, model: BaseModel) -> None:
        self.ensure_layout()
        payload = self._canonical_bytes(model)
        if path.exists():
            existing = path.read_bytes()
            if existing == payload:
                return
            raise RecordConflictError(f"immutable record identity already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, payload)

    @staticmethod
    def _canonical_bytes(model: BaseModel) -> bytes:
        data = model.model_dump(mode="json")
        text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        return text.encode("utf-8")

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()


def latest_result_by_task(
    results: Iterable[EngineeringResult],
) -> dict[str, EngineeringResult]:
    """Return latest completed result per task using timestamp then attempt ID as tie-break."""

    latest: dict[str, EngineeringResult] = {}
    for result in results:
        current = latest.get(result.task_id)
        if current is None or (result.completed_at, result.attempt_id) > (
            current.completed_at,
            current.attempt_id,
        ):
            latest[result.task_id] = result
    return latest
