"""The record of every change to a connection: what, when, by whom and from which device, and
whether it worked. Never a value. The Connections screen shows the latest first, so a change the
owner did not make is the first thing he sees there.

changes.jsonl (append-only, 0600) and tests.json (each connection's latest test) live beside the
app tier's keys in the root-only directory. The record is trimmed to its newest 500 lines once it
passes 1 MB.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CHANGES = "changes.jsonl"
TESTS = "tests.json"
MAX_BYTES = 1_000_000
KEEP_LINES = 500

_LOCK = threading.RLock()
_CONFIG: dict[str, Any] = {"state_dir": None}


def configure(*, state_dir: Path | None) -> None:
    with _LOCK:
        _CONFIG["state_dir"] = Path(state_dir) if state_dir else None


def _folder() -> Path | None:
    folder = _CONFIG["state_dir"]
    if folder is None:
        return None
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record(action: str, *, connection: str = "", keys: tuple[str, ...] | list[str] = (), who: str = "",
           device: str = "", ok: bool = True, detail: str = "") -> dict[str, Any]:
    """Append one change. `keys` are names (instagram_access_token), never values."""
    entry = {"at": now(), "action": action, "connection": connection, "keys": list(keys), "who": who,
             "device": device, "ok": bool(ok), "detail": str(detail)[:300]}
    with _LOCK:
        folder = _folder()
        if folder is None:
            return entry
        path = folder / CHANGES
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if path.stat().st_size > MAX_BYTES:
            lines = path.read_text(encoding="utf-8").splitlines()[-KEEP_LINES:]
            _replace(path, "\n".join(lines) + "\n")
    return entry


def recent(limit: int = 20) -> list[dict[str, Any]]:
    """The newest changes first."""
    with _LOCK:
        folder = _folder()
        if folder is None:
            return []
        try:
            lines = (folder / CHANGES).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _replace(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def tested(name: str, outcome: dict[str, Any]) -> None:
    """Keep a connection's latest test, for its card."""
    with _LOCK:
        folder = _folder()
        if folder is None:
            return
        table = last_tests()
        table[name] = {**outcome, "at": now()}
        _replace(folder / TESTS, json.dumps(table, ensure_ascii=False, indent=1))


def forget_test(name: str) -> None:
    with _LOCK:
        folder = _folder()
        if folder is None:
            return
        table = last_tests()
        if table.pop(name, None) is not None:
            _replace(folder / TESTS, json.dumps(table, ensure_ascii=False, indent=1))


def last_tests() -> dict[str, dict[str, Any]]:
    with _LOCK:
        folder = _folder()
        if folder is None:
            return {}
        try:
            data = json.loads((folder / TESTS).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
