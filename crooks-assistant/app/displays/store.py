"""Screens CLIVE can put things on, and what was marked done on them.

Any of the owner's devices becomes a screen by opening `/display` and giving itself a name —
"office mac", "bedroom screen", "packing tablet". From then on the owner can say "put order
2048 on the office mac" and it appears there, large: a fulfilment slip, an objective, or a
checklist. A screen asks every couple of seconds whether it has something new, so nothing has
to reach into it.

A screen can mark what it shows as done ("Mark packed"). That is CLIVE's own record that the
work was physically done, which screen it was done on and when — separate from Shopify, which
can only say a label was created. CLIVE reads it back ("has 2048 been packed?").

One JSON file beside the objectives, 0600 in a 0700 folder, written atomically. It holds the
screens' names, what each is showing (an order's slip carries its address: the owner's own
screens, reached only from his own verified devices, app/routes/displays.py), and the done
record, bounded. Nothing here is sent anywhere.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("crooks.displays")

# A screen that has asked within this long is on.
ONLINE_S = 30.0
# How often a screen's "last seen" is written down; in memory it is exact.
SEEN_WRITE_S = 60.0
MAX_SCREENS = 20
MAX_DONE = 500
MAX_NAME = 40
_ID = re.compile(r"^scr_[0-9a-f]{12}$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def name_key(name: str) -> str:
    """How a screen's name is matched: lowercase words, whatever the spacing or punctuation."""
    return " ".join(re.findall(r"[a-z0-9]+", str(name or "").lower()))[:MAX_NAME]


def clean_name(name: str) -> str:
    words = " ".join(str(name or "").split())
    return re.sub(r"[^\w\s'’&-]", "", words)[:MAX_NAME].strip()


class DisplayError(ValueError):
    """Said to the owner as it is."""


class DisplayStore:
    def __init__(self, path: Path, *, clock=time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()
        self._data = self._load()
        self._seen: dict[str, float] = {}
        self._seen_written: dict[str, float] = {}

    # ---- the file ------------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError):
            log.warning("screens record unreadable at %s; starting afresh", self.path)
            data = {}
        if not isinstance(data, dict):
            data = {}
        if not isinstance(data.get("screens"), dict):
            data["screens"] = {}
        if not isinstance(data.get("done"), list):
            data["done"] = []
        return data

    def _save(self) -> None:
        try:
            folder = self.path.parent
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                if folder.stat().st_mode & 0o077:
                    folder.chmod(0o700)
            except OSError:
                pass
            tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex[:8]}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(self._data, indent=2, ensure_ascii=False))
            os.replace(tmp, self.path)
        except OSError:
            log.warning("screens record not written", exc_info=True)

    # ---- screens ---------------------------------------------------------------------------
    def register(self, name: str) -> dict[str, Any]:
        """A screen names itself. The same name again is the same screen (a browser that lost
        its storage comes back as itself)."""
        shown = clean_name(name)
        key = name_key(shown)
        if not key:
            raise DisplayError("Give the screen a name, like office screen.")
        with self._lock:
            for screen in self._data["screens"].values():
                if screen.get("key") == key:
                    self._touch(screen["id"])
                    return dict(screen)
            if len(self._data["screens"]) >= MAX_SCREENS:
                oldest = min(self._data["screens"].values(), key=lambda s: s.get("last_seen") or "")
                del self._data["screens"][oldest["id"]]
            ident = "scr_" + secrets.token_hex(6)
            screen = {"id": ident, "name": shown, "key": key, "created_at": _now_iso(), "last_seen": _now_iso(),
                      "version": 0, "showing": None}
            self._data["screens"][ident] = screen
            self._touch(ident)
            self._save()
            return dict(screen)

    def forget(self, screen_id: str) -> bool:
        with self._lock:
            gone = self._data["screens"].pop(str(screen_id), None)
            if gone is not None:
                self._save()
            return gone is not None

    def get(self, screen_id: str) -> dict[str, Any] | None:
        if not _ID.fullmatch(str(screen_id or "")):
            return None
        screen = self._data["screens"].get(screen_id)
        return dict(screen) if screen else None

    def find(self, name: str) -> dict[str, Any]:
        """The screen a spoken name means: exactly, else the one screen whose name contains
        every word said ("office" finds "office mac"). Anything else is said plainly."""
        key = name_key(name)
        screens = list(self._data["screens"].values())
        if not screens:
            raise DisplayError("No screens yet. Open CLIVE's address with /display on the screen and give it a name.")
        exact = [s for s in screens if s.get("key") == key]
        if exact:
            return dict(exact[0])
        words = key.split()
        near = [s for s in screens if words and all(w in s.get("key", "").split() for w in words)]
        if len(near) == 1:
            return dict(near[0])
        names = ", ".join(sorted(s["name"] for s in screens))
        if len(near) > 1:
            raise DisplayError(f"More than one screen fits {name!r}: {names}. Say which.")
        raise DisplayError(f"There is no screen called {name!r}. The screens are: {names}.")

    def _touch(self, screen_id: str) -> None:
        now = self.clock()
        self._seen[screen_id] = now
        screen = self._data["screens"].get(screen_id)
        if screen is not None and now - self._seen_written.get(screen_id, 0.0) >= SEEN_WRITE_S:
            screen["last_seen"] = _now_iso()
            self._seen_written[screen_id] = now
            self._save()

    def online(self, screen_id: str) -> bool:
        return self.clock() - self._seen.get(screen_id, -1e9) <= ONLINE_S

    def screens(self) -> list[dict[str, Any]]:
        out = []
        for screen in sorted(self._data["screens"].values(), key=lambda s: s.get("name", "")):
            showing = screen.get("showing") or {}
            out.append({"id": screen["id"], "name": screen["name"], "online": self.online(screen["id"]),
                        "showing": showing.get("title") or None, "since": showing.get("at")})
        return out

    # ---- what a screen shows ---------------------------------------------------------------
    def poll(self, screen_id: str) -> dict[str, Any] | None:
        """What the screen should show now, and its version. The screen is seen."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                return None
            self._touch(screen_id)
            last = next((d for d in reversed(self._data["done"]) if d.get("screen_id") == screen_id), None)
            return {"id": screen_id, "name": screen["name"], "version": screen.get("version", 0),
                    "showing": screen.get("showing"),
                    "last_done": {"title": last.get("title"), "at": last.get("at")} if last else None}

    def show(self, screen_id: str, showing: dict[str, Any] | None, *, by: str = "clive") -> dict[str, Any]:
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise DisplayError("That screen is not there any more.")
            if showing is not None:
                showing = {**showing, "at": _now_iso(), "by": by}
            screen["showing"] = showing
            screen["version"] = int(screen.get("version", 0)) + 1
            self._save()
            return dict(screen)

    def mark_done(self, screen_id: str, version: int, *, by: str = "") -> dict[str, Any]:
        """What the screen is showing was physically done. Refused if the screen has moved on
        since it was drawn, so a late tap never marks the wrong thing."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise DisplayError("That screen is not there any more.")
            showing = screen.get("showing")
            if not showing or int(version) != int(screen.get("version", 0)):
                raise DisplayError("The screen changed before that tap; nothing was marked.")
            if showing.get("done_at"):
                return dict(screen)
            when = _now_iso()
            showing["done_at"] = when
            screen["version"] = int(screen.get("version", 0)) + 1
            self._data["done"].append({
                "at": when, "screen": screen["name"], "screen_id": screen_id, "kind": showing.get("kind"), "ref": showing.get("ref"),
                "title": showing.get("title"), "by": str(by or "")[:80] or None,
            })
            self._data["done"] = self._data["done"][-MAX_DONE:]
            self._save()
            return dict(screen)

    def done(self, *, ref: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        rows = [d for d in self._data["done"] if ref is None or d.get("ref") == ref]
        return list(reversed(rows[-limit:]))


_STORE: DisplayStore | None = None


def install(path: Path) -> DisplayStore:
    global _STORE
    _STORE = DisplayStore(path)
    return _STORE


def store() -> DisplayStore:
    if _STORE is None:
        from config.settings import get_settings

        return install(get_settings().objectives_dir / "displays.json")
    return _STORE
