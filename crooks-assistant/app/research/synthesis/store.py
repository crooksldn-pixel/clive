"""Where CLIVE keeps what it learned from research: generations of ideas, on the server only.

Why this exists: DEC-078. George's research is evidence for CLIVE's understanding, not a pile of
separate roadmaps. Every synthesis run writes one generation; one generation is live at a time, named
by the LIVE file. It never lives in the repository (DEC-070): `<research dir>` is git-ignored.

    <research dir>/synthesis/LIVE                    one line: the live generation (absent until applied)
    <research dir>/synthesis/gen-<UTC>/claims/       <doc_id>.json: every recommendation read from it
    <research dir>/synthesis/gen-<UTC>/ideas/        idea-NNNN.json: each idea's current state
    <research dir>/synthesis/gen-<UTC>/events.jsonl  the history, append-only
    <research dir>/synthesis/gen-<UTC>/summary.json  the plain-English synthesis
    <research dir>/synthesis/gen-<UTC>/run.json      the run: stage, progress, calls, errors
    <research dir>/synthesis/cache/                  what each file said, by its digest (no model call twice)
    <research dir>/synthesis/prepared.jsonl          which build request each approved idea was prepared as

What it promises:
- Folders are 0700 and files 0600. A record is written whole: written beside, then renamed.
- events.jsonl is opened O_APPEND, one JSON line per event, and never rewritten or truncated; an
  idea's history is its events. prepared.jsonl is kept the same way.
- A read that fails is said (ReadProblem), never skipped silently, as in app/research/store.py.
- Idea ids are never handed out twice across generations on disk, so an answer George gave one idea
  can only ever follow it to a generation that kept its id on purpose (run.apply, by overlap).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GEN = re.compile(r"^gen-\d{8}T\d{6}(?:-\d{1,3})?$")
IDEA = re.compile(r"^idea-(\d{4,6})$")
DOC = re.compile(r"^doc-[0-9a-f]{20}$")
EVENTS = "events.jsonl"
PREPARED = "prepared.jsonl"
_lock = threading.Lock()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ReadProblem(Exception):
    """A record that is there but could not be read, said in words."""


class SynthesisStore:
    """The synthesis folder inside the research store's folder."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- folders and generations

    def _folder(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o700)
        return path

    def generations(self) -> list[str]:
        """Every generation on disk, oldest first."""
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and GEN.match(p.name))

    def exists(self, gen: str) -> bool:
        return bool(GEN.match(str(gen or ""))) and (self.root / gen).is_dir()

    def new_generation(self, at: datetime | None = None) -> str:
        stamp = (at or datetime.now(UTC)).strftime("gen-%Y%m%dT%H%M%S")
        name, n = stamp, 1
        while (self.root / name).exists():
            n += 1
            name = f"{stamp}-{n}"
        for sub in ("claims", "ideas"):
            self._folder(self.root / name / sub)
        return name

    def gen_dir(self, gen: str) -> Path:
        if not GEN.match(str(gen or "")):
            raise ValueError("not a generation")
        return self.root / gen

    def live(self) -> str:
        """The live generation's name, or "" before the first is applied."""
        try:
            name = (self.root / "LIVE").read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return name if self.exists(name) else ""

    def set_live(self, gen: str) -> None:
        if not self.exists(gen):
            raise ValueError(f"there is no generation {gen}")
        self._write_text(self.root / "LIVE", gen + "\n")

    # -- whole records

    def _write_text(self, path: Path, text: str) -> None:
        folder = self._folder(path.parent)
        with _lock:
            fd, tmp = tempfile.mkstemp(prefix=".w-", dir=folder)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    out.write(text)
                os.chmod(tmp, 0o600)
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)

    def write_json(self, path: Path, data: Any) -> None:
        self._write_text(path, json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1) + "\n")

    def read_json(self, path: Path, default: Any = None) -> Any:
        """The record, `default` when there is none; ReadProblem when it is there but unreadable."""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return default
        except OSError as exc:
            raise ReadProblem(f"{path.name} couldn't be read ({type(exc).__name__}).") from None
        try:
            return json.loads(text)
        except ValueError:
            raise ReadProblem(f"{path.name} isn't readable JSON.") from None

    # -- claims, ideas, summary, run

    def claims_path(self, gen: str, doc_id: str) -> Path:
        if not DOC.match(str(doc_id or "")):
            raise ValueError("not a document id")
        return self.gen_dir(gen) / "claims" / f"{doc_id}.json"

    def claims(self, gen: str) -> dict[str, dict[str, Any]]:
        """Every document's claims in a generation, by document id."""
        folder = self.gen_dir(gen) / "claims"
        out = {}
        for path in sorted(folder.glob("doc-*.json")) if folder.is_dir() else []:
            out[path.stem] = self.read_json(path, {})
        return out

    def idea_path(self, gen: str, idea_id: str) -> Path:
        if not IDEA.match(str(idea_id or "")):
            raise ValueError("not an idea id")
        return self.gen_dir(gen) / "ideas" / f"{idea_id}.json"

    def ideas(self, gen: str) -> dict[str, dict[str, Any]]:
        """Every idea in a generation (active and merged), by id, in id order."""
        folder = self.gen_dir(gen) / "ideas"
        out = {}
        for path in sorted(folder.glob("idea-*.json"), key=lambda p: _number(p.stem)) if folder.is_dir() else []:
            out[path.stem] = self.read_json(path, {})
        return out

    def save_idea(self, gen: str, idea: dict[str, Any]) -> None:
        self.write_json(self.idea_path(gen, idea["id"]), idea)

    def remove_idea(self, gen: str, idea_id: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.idea_path(gen, idea_id).unlink()

    def summary(self, gen: str) -> dict[str, Any] | None:
        return self.read_json(self.gen_dir(gen) / "summary.json", None)

    def save_summary(self, gen: str, summary: dict[str, Any]) -> None:
        self.write_json(self.gen_dir(gen) / "summary.json", summary)

    def run(self, gen: str) -> dict[str, Any] | None:
        return self.read_json(self.gen_dir(gen) / "run.json", None)

    def save_run(self, gen: str, run: dict[str, Any]) -> None:
        self.write_json(self.gen_dir(gen) / "run.json", run)

    def next_idea_id(self, gen: str) -> str:
        """The next id no generation on disk has used."""
        import fcntl

        self._folder(self.root)
        fd = os.open(self.root / ".highest-idea", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)     # the server and the script may both be handing out ids
            raw = os.read(fd, 64).decode("ascii", "replace").strip()
            # Every id is handed out here, so the counter is the highest once it exists; without it, ask the disk.
            highest = int(raw) if raw.isdigit() else max((_number(i) for i in self.used_ids()), default=0)
            highest += 1
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, f"{highest}\n".encode("ascii"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return f"idea-{highest:04d}"

    def used_ids(self, *, but: str = "") -> set[str]:
        """Every idea id in every generation on disk except `but`, and every id an idea there was before."""
        out: set[str] = set()
        for name in self.generations():
            if name == but:
                continue
            folder = self.root / name / "ideas"
            for path in folder.glob("idea-*.json") if folder.is_dir() else []:
                out.add(path.stem)
                with contextlib.suppress(ReadProblem, AttributeError, TypeError):
                    out.update(str(w) for w in (self.read_json(path, {}).get("was") or []))
        return out

    # -- the cache of what a file said

    def cached(self, key: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[0-9a-f]{64}", key or ""):
            return None
        return self.read_json(self._folder(self.root / "cache") / f"{key}.json", None)

    def cache(self, key: str, data: dict[str, Any]) -> None:
        self.write_json(self._folder(self.root / "cache") / f"{key}.json", data)

    # -- append-only lines

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        self._folder(path.parent)
        line = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
        with _lock:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                os.fchmod(fd, 0o600)
                os.write(fd, line.encode("ascii"))
                os.fsync(fd)
            finally:
                os.close(fd)

    def _lines(self, path: Path) -> list[dict[str, Any]]:
        """Every line; a line that cannot be read is said as an event of its own, never dropped."""
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise ReadProblem(f"{path.name} couldn't be read ({type(exc).__name__}).") from None
        out = []
        for n, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                item = None
            out.append(item if isinstance(item, dict) else {"type": "unreadable", "line": n,
                                                            "said": f"Line {n} of the history couldn't be read."})
        return out

    def event(self, gen: str, kind: str, *, idea: str | None = None, said: str, at: str = "", **fields: Any) -> dict[str, Any]:
        record = {"at": at or now(), "type": kind, "idea": idea, "said": said, **fields}
        self._append(self.gen_dir(gen) / EVENTS, record)
        return record

    def events(self, gen: str) -> list[dict[str, Any]]:
        return self._lines(self.gen_dir(gen) / EVENTS)

    def note_prepared(self, idea_id: str, request_id: str) -> None:
        self._append(self.root / PREPARED, {"at": now(), "idea": idea_id, "request_id": request_id})

    def prepared(self) -> dict[str, dict[str, Any]]:
        """The newest build request prepared for each idea, by idea id."""
        out: dict[str, dict[str, Any]] = {}
        for line in self._lines(self.root / PREPARED):
            if line.get("idea") and line.get("request_id"):
                out[str(line["idea"])] = line
        return out


def _number(idea_id: str) -> int:
    match = IDEA.match(str(idea_id or ""))
    return int(match.group(1)) if match else 0


def synthesis_store(research_store=None) -> SynthesisStore:
    """The synthesis folder of the research store (the configured one unless one is given)."""
    if research_store is None:
        from app.research.store import store

        research_store = store()
    return SynthesisStore(Path(research_store.root) / "synthesis")
