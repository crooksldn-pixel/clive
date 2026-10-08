"""Where George's research is kept on the server, and the record of each document given.

Why this exists: research comes in two ways — a file given on the Builds screen, or a file put in a
folder on the server — and each becomes one record that says where it is (waiting, being read,
read, stopped by the safety scan, or failed, with why) and, once read, the proposals made from it.

    <research dir>/inbox/            the server folder: put research files here
    <research dir>/inbox/taken/      what was in it, moved here once taken in
    <research dir>/received/         each file as given, until it has been read
    <research dir>/quarantine/       the digester's read-only copies (app/digest/intake.py)
    <research dir>/digests/          the digester's store (app/digest/store.py)
    <research dir>/documents/        one JSON record per document: research.json files

What it promises:
- Folders are 0700 and files 0600; a record is written whole (written beside, then renamed).
- A record's proposals, once written, are never rewritten: George's answers live in the owner's
  judgment ledger (app/builds/decisions.py), not here.
- The server path is never shown or stored in a record: a document is its own file name.
- A long file name is cut in its stem, never its suffix, which is what says what kind of file it
  is (review note 4, 8 Oct).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

DOCUMENT_SUFFIX = ".research.json"
STATES = ("queued", "reading", "done", "stopped", "failed")
_ID = re.compile(r"^doc-[0-9a-f]{20}$")
_lock = threading.Lock()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ResearchStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- folders

    def folder(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    @property
    def inbox(self) -> Path:
        return self.folder("inbox")

    @property
    def quarantine(self) -> Path:
        return self.folder("quarantine")

    @property
    def digests(self) -> Path:
        return self.folder("digests")

    # -- records

    def new_document(self, name: str, data: bytes, *, via: str) -> dict[str, Any]:
        """Keep the file as given and open its record, queued to be read."""
        doc_id = f"doc-{uuid.uuid4().hex[:20]}"
        safe = safe_name(name)
        received = self.folder("received") / doc_id
        received.mkdir(mode=0o700)
        _write_bytes(received / safe, data)
        record = {"id": doc_id, "name": fit(Path(str(name)).name, 200) or "research", "via": via, "received_at": now(),
                  "state": "queued", "why": "", "file": safe, "bytes": len(data), "artifact_id": "",
                  "notes": [], "proposals": [], "dropped": [], "model": "", "map_digest": "", "finished_at": "",
                  "repeat_of": ""}
        self.save(record)
        return record

    def refused_document(self, name: str, why: str, *, via: str) -> dict[str, Any]:
        """A file that could not be taken in at all: its record says why, and nothing is kept."""
        record = {"id": f"doc-{uuid.uuid4().hex[:20]}", "name": fit(Path(str(name)).name, 200) or "research", "via": via,
                  "received_at": now(), "state": "failed", "why": why[:400], "file": "", "bytes": 0,
                  "artifact_id": "", "notes": [], "proposals": [], "dropped": [], "model": "", "map_digest": "",
                  "finished_at": now(), "repeat_of": ""}
        self.save(record)
        return record

    def received_file(self, record: dict[str, Any]) -> Path:
        return self.root / "received" / record["id"] / record["file"]

    def forget_received(self, record: dict[str, Any]) -> None:
        """The quarantine holds what was read; the file as given is no longer needed."""
        folder = self.root / "received" / record["id"]
        for child in folder.glob("*"):
            try:
                child.unlink()
            except OSError:
                pass
        try:
            folder.rmdir()
        except OSError:
            pass

    def save(self, record: dict[str, Any]) -> None:
        if not _ID.match(str(record.get("id") or "")) or record.get("state") not in STATES:
            raise ValueError("not a research record")
        folder = self.folder("documents")
        with _lock:
            fd, tmp = tempfile.mkstemp(prefix=".rec-", dir=folder)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    json.dump(record, out, ensure_ascii=False, sort_keys=True, indent=1)
                os.chmod(tmp, 0o600)
                os.replace(tmp, folder / f"{record['id']}{DOCUMENT_SUFFIX}")
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)

    def get(self, doc_id: str) -> dict[str, Any] | None:
        if not _ID.match(str(doc_id or "")):
            return None
        path = self.root / "documents" / f"{doc_id}{DOCUMENT_SUFFIX}"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def documents(self) -> list[dict[str, Any]]:
        """Every record, newest first. A record that cannot be read is said, not skipped."""
        folder = self.root / "documents"
        if not folder.is_dir():
            return []
        out = []
        for path in folder.glob(f"doc-*{DOCUMENT_SUFFIX}"):
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                out.append({"id": path.name[: -len(DOCUMENT_SUFFIX)], "name": path.name, "state": "failed",
                            "why": "This record couldn't be read.", "received_at": "", "proposals": []})
        return sorted(out, key=lambda r: str(r.get("received_at") or ""), reverse=True)

    def proposal(self, proposal_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """(record, proposal) for a proposal id, or None."""
        for record in self.documents():
            for proposal in record.get("proposals") or []:
                if proposal.get("id") == proposal_id:
                    return record, proposal
        return None

    def note_prepared(self, doc_id: str, proposal_id: str, request_id: str) -> None:
        """Which build request an adopted proposal was prepared as (beside the proposal, never in it)."""
        record = self.get(doc_id)
        if record is None:
            return
        prepared = dict(record.get("prepared") or {})
        prepared[proposal_id] = {"request_id": request_id, "at": now()}
        record["prepared"] = prepared
        self.save(record)


def safe_name(name: str) -> str:
    """A file name as kept on the server: letters, digits, dots, dashes and underscores, at most 120."""
    return fit(re.sub(r"[^A-Za-z0-9._-]+", "-", Path(str(name)).name).strip("-."), 120) or "research"


def fit(name: str, limit: int) -> str:
    """`name` cut to `limit` characters in its stem, keeping its suffix (".md", ".docx"), which is what
    says what kind of file it is."""
    if len(name) <= limit:
        return name
    path = PurePosixPath(name)
    suffix = path.suffix if 1 < len(path.suffix) <= 16 else ""
    return path.stem[: limit - len(suffix)].rstrip(" .-") + suffix


def _write_bytes(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)


_STORE: ResearchStore | None = None


def store() -> ResearchStore:
    """The research store at the configured folder (CROOKS_RESEARCH_DIR), or one a test installed."""
    global _STORE
    if _STORE is None:
        from config.settings import get_settings

        _STORE = ResearchStore(get_settings().research_dir)
    return _STORE


def install(root: Path | str | None) -> ResearchStore | None:
    """Use the store at `root` from now on (tests); None forgets it."""
    global _STORE
    _STORE = ResearchStore(root) if root is not None else None
    return _STORE
