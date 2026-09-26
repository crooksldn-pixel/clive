"""The digester's file store: one directory per artifact under a root it is given.

    <root>/<artifact id>/source.json         where it came from
                         artifact.json       its id, kinds and the ids of its units, in order
                         units.jsonl         one unit per line
                         findings.jsonl      appended to by the scanner
                         absorptions.jsonl   the absorption ledger: appended to, never rewritten

An artifact is written once, into a staging directory that is then renamed into place, so a
reader never sees half of one. Writing the same artifact again changes nothing; writing a
different one under an id already taken is refused. Findings and absorptions are only ever
appended, and a record already in the file is not appended twice."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from app.digest.model import ARTIFACT_ID_PATTERN, Absorption, Artifact, Finding, Source, Unit

SOURCE_FILE = "source.json"
ARTIFACT_FILE = "artifact.json"
UNITS_FILE = "units.jsonl"
FINDINGS_FILE = "findings.jsonl"
ABSORPTIONS_FILE = "absorptions.jsonl"


class ArtifactConflict(Exception):
    """A different artifact is already stored under this id."""


def _record(artifact: Artifact) -> dict:
    return {
        "id": artifact.id,
        "content_digest": artifact.source.content_digest,
        "kinds": list(artifact.kinds),
        "unit_ids": [unit.id for unit in artifact.units],
    }


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def _line(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_lines(path: Path) -> list[Any]:
    # split on "\n" only: str.splitlines would also break inside a body holding U+2028.
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split("\n") if line.strip()]


class DigestStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def path_for(self, artifact_id: str) -> Path:
        if not isinstance(artifact_id, str) or not re.fullmatch(ARTIFACT_ID_PATTERN, artifact_id):
            raise ValueError(f"not an artifact id: {artifact_id!r}")
        return self.root / artifact_id

    def has(self, artifact_id: str) -> bool:
        return (self.path_for(artifact_id) / ARTIFACT_FILE).is_file()

    def ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name for entry in self.root.iterdir()
            if re.fullmatch(ARTIFACT_ID_PATTERN, entry.name) and (entry / ARTIFACT_FILE).is_file()
        )

    # --- artifacts ---------------------------------------------------------------------------

    def put(self, artifact: Artifact) -> bool:
        """Store an artifact: True when written, False when this exact artifact was already
        there. A different artifact under the same id raises ArtifactConflict."""
        if not isinstance(artifact, Artifact):
            raise ValueError("only an Artifact can be stored")
        with self._lock:
            final = self.path_for(artifact.id)
            if final.exists():
                return self._already_there(artifact)
            self.root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{artifact.id}-", dir=self.root))
            try:
                _write_json(staging / SOURCE_FILE, artifact.source.to_dict())
                _write_json(staging / ARTIFACT_FILE, _record(artifact))
                (staging / UNITS_FILE).write_text(
                    "".join(_line(unit.to_dict()) for unit in artifact.units), encoding="utf-8"
                )
                (staging / FINDINGS_FILE).write_text("", encoding="utf-8")
                (staging / ABSORPTIONS_FILE).write_text("", encoding="utf-8")
                try:
                    os.rename(staging, final)
                except OSError:
                    # another writer got there first: the same artifact is fine, any other is not
                    if not final.exists():
                        raise
                    return self._already_there(artifact)
                return True
            finally:
                if staging.exists():
                    shutil.rmtree(staging)

    def _already_there(self, artifact: Artifact) -> bool:
        existing = self.load(artifact.id)
        if existing != artifact:
            raise ArtifactConflict(
                f"{artifact.id} is already stored in {self.root} as a different artifact; "
                "it is not overwritten"
            )
        return False

    def load(self, artifact_id: str) -> Artifact:
        folder = self._existing(artifact_id)
        record = _read_json(folder / ARTIFACT_FILE)
        if not isinstance(record, dict) or "kinds" not in record:
            raise ValueError(f"{folder / ARTIFACT_FILE} is not an artifact record")
        artifact = Artifact(
            source=Source.from_dict(_read_json(folder / SOURCE_FILE)),
            kinds=record["kinds"],
            units=tuple(Unit.from_dict(unit) for unit in _read_lines(folder / UNITS_FILE)),
        )
        if _record(artifact) != record or artifact.id != artifact_id:
            raise ValueError(f"{folder} is inconsistent: {ARTIFACT_FILE} does not match its source and units")
        return artifact

    def _existing(self, artifact_id: str) -> Path:
        folder = self.path_for(artifact_id)
        if not (folder / ARTIFACT_FILE).is_file():
            raise FileNotFoundError(f"no artifact {artifact_id} in {self.root}")
        return folder

    # --- findings and the absorption ledger --------------------------------------------------

    def add_finding(self, finding: Finding) -> bool:
        """Append a finding: True when appended, False when it was already recorded."""
        if not isinstance(finding, Finding):
            raise ValueError("only a Finding can be added")
        with self._lock:
            artifact = self.load(finding.artifact_id)
            if finding.unit_id is not None and finding.unit_id not in {u.id for u in artifact.units}:
                raise ValueError(f"finding names unit {finding.unit_id}, which {artifact.id} does not have")
            return self._append(artifact.id, FINDINGS_FILE, finding, Finding)

    def findings(self, artifact_id: str) -> tuple[Finding, ...]:
        folder = self._existing(artifact_id)
        return tuple(Finding.from_dict(item) for item in _read_lines(folder / FINDINGS_FILE))

    def add_absorption(self, absorption: Absorption) -> bool:
        """Append to the ledger: True when appended, False when it was already recorded. What
        is in the ledger is never rewritten; a decision is a new record after its proposal."""
        if not isinstance(absorption, Absorption):
            raise ValueError("only an Absorption can be added")
        with self._lock:
            artifact = self.load(absorption.artifact_id)
            if absorption.unit_id not in {unit.id for unit in artifact.units}:
                raise ValueError(f"absorption names unit {absorption.unit_id}, which {artifact.id} does not have")
            return self._append(artifact.id, ABSORPTIONS_FILE, absorption, Absorption)

    def absorptions(self, artifact_id: str) -> tuple[Absorption, ...]:
        folder = self._existing(artifact_id)
        return tuple(Absorption.from_dict(item) for item in _read_lines(folder / ABSORPTIONS_FILE))

    def _append(self, artifact_id: str, name: str, record: Finding | Absorption, kind: type) -> bool:
        path = self.path_for(artifact_id) / name
        # read back through from_dict, so a damaged ledger is found before it is added to
        if any(kind.from_dict(item).id == record.id for item in _read_lines(path)):
            return False
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_line(record.to_dict()))
            handle.flush()
            os.fsync(handle.fileno())
        return True
