"""Who on the team may get in: a staff member's login, and whether the owner has let it in.

A grant is "pending" when CLIVE has been told someone's login, "active" once the owner has
approved it with his passkey on the Today screen (app/routes/today.py), and "suspended" when he
takes it away. Only an active grant opens the door (app/main.py), and only for that login.

Kept in access.json beside the owner's passkeys, in the root-only directory (0600), not with
CLIVE's ordinary records: a line added here would let someone in, which makes it the same kind of
thing as a passkey. The door asks on every request; the file is read again only when it changes.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FILE_NAME = "access.json"
STATES = ("pending", "active", "suspended")

_LOCK = threading.RLock()
_CONFIG: dict[str, Any] = {"state_dir": None}
_CACHE: dict[str, Any] = {"signature": None, "grants": {}}


class AccessError(ValueError):
    pass


def configure(*, state_dir: Path | None) -> None:
    with _LOCK:
        _CONFIG["state_dir"] = Path(state_dir) if state_dir else None
        _CACHE.update(signature=None, grants={})


def _path() -> Path | None:
    folder = _CONFIG["state_dir"]
    return Path(folder) / FILE_NAME if folder else None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _grants() -> dict[str, dict[str, Any]]:
    path = _path()
    if path is None:
        return {}
    try:
        info = path.stat()
    except OSError:
        _CACHE.update(signature=None, grants={})
        return {}
    signature = (info.st_ino, info.st_size, info.st_mtime_ns)
    if _CACHE["signature"] == signature:
        return _CACHE["grants"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}                       # unreadable lets nobody in; the screen says so
    grants = {str(k): v for k, v in (data.get("grants") or {}).items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    _CACHE.update(signature=signature, grants=grants)
    return grants


def _save(grants: dict[str, dict[str, Any]]) -> None:
    path = _path()
    if path is None:
        raise AccessError("staff access is not set up on this server")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".access.", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "grants": grants}, stream, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    _CACHE.update(signature=None)


def all_grants() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return {k: dict(v) for k, v in _grants().items()}


def state(person_id: str) -> str:
    with _LOCK:
        return str((_grants().get(str(person_id)) or {}).get("status") or "")


def ask(person_id: str, login: str) -> str:
    """CLIVE has been told this person's login: their access waits for the owner. A changed login
    is asked again, even if the old one was active, because the owner approved that one."""
    with _LOCK:
        grants = dict(_grants())
        current = grants.get(person_id) or {}
        if current.get("login") == login and current.get("status") in ("pending", "active"):
            return str(current["status"])
        grants[person_id] = {"login": login, "status": "pending", "asked_at": _now()}
        _save(grants)
        return "pending"


def approve(person_id: str, *, by: str, passkey: str) -> dict[str, Any]:
    """Only the Today screen's route calls this, after the owner's passkey approved exactly this."""
    with _LOCK:
        grants = dict(_grants())
        current = grants.get(person_id)
        if not current or not current.get("login"):
            raise AccessError("there is no login to let in for that person")
        grants[person_id] = {**current, "status": "active", "approved_at": _now(), "approved_by": by,
                             "passkey": passkey}
        _save(grants)
        return dict(grants[person_id])


def suspend(person_id: str, *, by: str) -> None:
    with _LOCK:
        grants = dict(_grants())
        current = grants.get(person_id)
        if not current:
            return
        grants[person_id] = {**current, "status": "suspended", "suspended_at": _now(), "suspended_by": by}
        _save(grants)


def person_for_login(login: str) -> str:
    """The person an active grant lets in with this login, or "". What the door asks."""
    wanted = str(login or "").strip().lower()
    if not wanted:
        return ""
    with _LOCK:
        for person_id, grant in _grants().items():
            if grant.get("status") == "active" and str(grant.get("login") or "").lower() == wanted:
                return person_id
    return ""
