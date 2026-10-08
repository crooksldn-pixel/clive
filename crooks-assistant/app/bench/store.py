"""Where the bench keeps what it makes: the data directory's bench/, never the repository.

The data directory is the one CLIVE keeps its people cards and work list in, the parent of the
objectives folder (`/var/lib/crooks-assistant` on the server, `.state` in a checkout, which git
ignores). Under bench/:

    questions/<set id>.json        a fixed, versioned question set (generate)
    runs/<run id>/run.json         what a run was: the set, the caps, the versions, how it ended
    runs/<run id>/results.jsonl    one line per question, as the recorder wrote it
    runs/<run id>/judged.jsonl     one line per judged result, with the judge's version
    runs/<run id>/report.json      the report, and report.md beside it for reading on the server
    ratings.jsonl                  George's own ratings, one line each, the latest per result wins

What it promises:
- Ids are checked before they become paths: a set or run id is a fixed shape, and a result id is
  the question id the set gave it. Nothing a request sends is joined to a path unchecked.
- Every bench folder is 0700, bench/ itself, questions/, runs/ and each run's, and every file 0600, as
  the objectives are: the fake shop holds no customer, but a model's answer is still not for anyone
  else on the machine. Each folder is set on every write, whatever the umask, and whoever made it.
- A line that is not JSON is skipped and counted, never fatal: one bad line does not hide a run.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SET_ID = re.compile(r"^qs-\d{8}-\d{4}-[0-9a-f]{6}$")
RUN_ID = re.compile(r"^run-\d{8}-\d{4}-[0-9a-f]{4}$")
RESULT_ID = re.compile(r"^q\d{3,4}$")
MAX_NOTE = 500


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def root_for(settings: Any) -> Path:
    """The bench folder for these settings: beside the objectives' folder, in the data directory."""
    return Path(settings.objectives_dir).parent / "bench"


def _private_dir(path: Path) -> Path:
    """`path` made if it is missing, and 0700. mkdir's own mode reaches only the last folder it makes,
    cut by the umask, so the mode is set after; a bench folder's parents are made 0700 one by one
    (Bench.folder)."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _write(path: Path, text: str) -> None:
    _private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def write_json(path: Path, value: Any) -> None:
    _write(path, json.dumps(value, indent=1, ensure_ascii=False, sort_keys=False) + "\n")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    _private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M")


def new_set_id(digest: str) -> str:
    return f"qs-{_stamp()}-{digest[:6]}"


def new_run_id() -> str:
    return f"run-{_stamp()}-{secrets.token_hex(2)}"


class Bench:
    """One bench folder."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def folder(self, path: Path) -> Path:
        """Every folder from the bench's own down to `path`, made if missing and each 0700."""
        path = Path(path)
        current = _private_dir(self.root)
        for part in path.relative_to(self.root).parts:
            current = _private_dir(current / part)
        return path

    # ---------------------------------------------------------------- question sets

    def set_path(self, set_id: str) -> Path:
        if not SET_ID.fullmatch(str(set_id or "")):
            raise ValueError(f"{set_id!r} is not a question set id")
        return self.root / "questions" / f"{set_id}.json"

    def save_set(self, question_set: dict[str, Any]) -> Path:
        path = self.set_path(question_set["set_id"])
        write_json(self.folder(path.parent) / path.name, question_set)
        return path

    def sets(self) -> list[str]:
        folder = self.root / "questions"
        return sorted(p.stem for p in folder.glob("qs-*.json") if SET_ID.fullmatch(p.stem)) if folder.is_dir() else []

    def load_set(self, set_id: str) -> dict[str, Any]:
        if set_id == "latest":
            found = self.sets()
            if not found:
                raise FileNotFoundError("no question set yet: run `python -m app.bench generate` first")
            set_id = found[-1]
        value = read_json(self.set_path(set_id))
        if value is None:
            raise FileNotFoundError(f"no question set {set_id}")
        return value

    # ---------------------------------------------------------------- runs

    def run_dir(self, run_id: str) -> Path:
        if not RUN_ID.fullmatch(str(run_id or "")):
            raise ValueError(f"{run_id!r} is not a run id")
        return self.root / "runs" / run_id

    def runs(self) -> list[str]:
        folder = self.root / "runs"
        if not folder.is_dir():
            return []
        return sorted((p.name for p in folder.iterdir() if p.is_dir() and RUN_ID.fullmatch(p.name)), reverse=True)

    def latest_run(self) -> str:
        found = self.runs()
        if not found:
            raise FileNotFoundError("no run yet: run `python -m app.bench run` first")
        return found[0]

    def manifest(self, run_id: str) -> dict[str, Any] | None:
        return read_json(self.run_dir(run_id) / "run.json")

    def save_manifest(self, run_id: str, manifest: dict[str, Any]) -> None:
        write_json(self.folder(self.run_dir(run_id)) / "run.json", manifest)

    def results(self, run_id: str) -> list[dict[str, Any]]:
        """In the set's order: questions in flight together finish, and are written, in any order."""
        rows = read_jsonl(self.run_dir(run_id) / "results.jsonl")
        return sorted(rows, key=lambda r: (len(str(r.get("result_id") or "")), str(r.get("result_id") or "")))

    def add_result(self, run_id: str, row: dict[str, Any]) -> None:
        append_jsonl(self.folder(self.run_dir(run_id)) / "results.jsonl", [row])

    def judged(self, run_id: str) -> dict[str, dict[str, Any]]:
        """The latest verdict per result."""
        out: dict[str, dict[str, Any]] = {}
        for row in read_jsonl(self.run_dir(run_id) / "judged.jsonl"):
            if RESULT_ID.fullmatch(str(row.get("result_id") or "")):
                out[row["result_id"]] = row
        return out

    def add_verdict(self, run_id: str, row: dict[str, Any]) -> None:
        append_jsonl(self.folder(self.run_dir(run_id)) / "judged.jsonl", [row])

    # ---------------------------------------------------------------- ratings

    @property
    def ratings_path(self) -> Path:
        return self.root / "ratings.jsonl"

    def ratings(self) -> dict[tuple[str, str], dict[str, Any]]:
        """George's latest rating of each result he has rated."""
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for row in read_jsonl(self.ratings_path):
            run_id, result_id = str(row.get("run_id") or ""), str(row.get("result_id") or "")
            if RUN_ID.fullmatch(run_id) and RESULT_ID.fullmatch(result_id) and _score(row.get("score")):
                out[(run_id, result_id)] = row
        return out

    def rate(self, run_id: str, result_id: str, score: int, note: str, *, by: str, judge: dict[str, Any] | None) -> dict[str, Any]:
        """George's rating of one result, kept with what the judge said of it at that moment."""
        if not RESULT_ID.fullmatch(str(result_id or "")):
            raise ValueError("not a result id")
        if not (self.run_dir(run_id) / "results.jsonl").is_file():
            raise FileNotFoundError("no such run")
        if not _score(score):
            raise ValueError("a rating is a whole number from 1 to 5")
        row = {
            "run_id": run_id, "result_id": result_id, "score": int(score),
            "note": " ".join(str(note or "").split())[:MAX_NOTE], "by": str(by or "")[:120], "at": now(),
            "judge_overall": (judge or {}).get("overall"), "judge_version": (judge or {}).get("judge_version"),
        }
        append_jsonl(self.folder(self.root) / self.ratings_path.name, [row])
        return row


def _score(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5
