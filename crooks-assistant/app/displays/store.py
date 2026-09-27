"""Screens CLIVE can put things on, and what was marked done on them.

Any of the owner's devices becomes a screen by opening `/display` and giving itself a name —
"office mac", "bedroom screen", "packing tablet". From then on the owner can say "put order
2048 on the office mac" and it appears there, large: a fulfilment slip, an objective, or a
checklist. A screen asks every couple of seconds whether it has something new, so nothing has
to reach into it.

A screen can mark what it shows as done ("Mark packed"). That is CLIVE's own record that the
work was physically done, which screen it was done on and when — separate from Shopify, which
can only say a label was created. CLIVE reads it back ("has 2048 been packed?").

A screen is the device that named it, not anything that knows its name (the 2026-09-27 deploy
review, round 6, B-02): naming a screen hands that device a key, once, and every later ask and
every "done" must carry it. Only the key's hash is kept. A name already in use is refused while
its screen is on; a screen that has gone quiet (a browser that lost its storage) can be named
again, and the new device gets a new key that the old one no longer matches.

What a screen shows is kept only while it is up (round 6, B-03). An order's slip carries the
customer's name, address, phone and note, and the moment it is marked done the slip is cut down
to what the done record needs: kind, reference, title and times. Anything left up longer than
SHOWING_KEEP_S is taken down by itself — when a screen asks, when CLIVE lists the screens, on
the backend's housekeeping timer and when the record is first read after a start, so nothing
waits on a browser being open. The done record keeps DONE_KEEP_S and MAX_DONE rows at most, each
field of each row bounded, and one view is at most views.MAX_VIEW_BYTES written down, so the
whole file stays under MAX_FILE_BYTES by construction (and is checked before it is written).
The page keeps its own copy for the minute it shows "Packed".

One JSON file beside the objectives, 0600 in a 0700 folder, written atomically. It holds the
screens' names and key hashes, what each is showing now, and the done record, bounded. Nothing
here is sent anywhere.
"""

from __future__ import annotations

import hashlib
import hmac
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

from app.displays.views import MAX_ID, MAX_TITLE, MAX_VIEW_BYTES

log = logging.getLogger("crooks.displays")

# A screen that has asked within this long is on.
ONLINE_S = 30.0
# How often a screen's "last seen" is written down; in memory it is exact.
SEEN_WRITE_S = 60.0
MAX_SCREENS = 20
MAX_DONE = 500
MAX_NAME = 40
# What a screen shows is taken down after this long, whatever it is.
SHOWING_KEEP_S = 12 * 3600
# How long a done row is kept ("has 2048 been packed?" is asked within days, not seasons).
DONE_KEEP_S = 90 * 86_400
# The whole record, written down: 20 screens at the largest view each and the done record full
# come to about 1.4 MB, so this is never reached unless something above is broken.
MAX_FILE_BYTES = 2_000_000
# What survives of a slip once it is done: enough to say what was done, nothing about whom.
DONE_FIELDS = ("kind", "ref", "title", "at", "by", "done_at")
_ID = re.compile(r"^scr_[0-9a-f]{12}$")


def _shown_count(showing: dict[str, Any]) -> int | None:
    """How many things a slip or list asks to be seen before it is marked done; None for a view
    that is not marked item by item."""
    if showing.get("kind") == "order":
        return len((showing.get("order") or {}).get("items") or [])
    if showing.get("kind") == "list":
        return len((showing.get("list") or {}).get("lines") or [])
    return None


def _key_hash(key: str) -> str:
    return hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()


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


class NotThisScreen(DisplayError):
    """The device asking does not hold this screen's key."""


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

    def sweep(self) -> bool:
        """Take down whatever has been up too long and age the done record, now, whoever is
        asking or not. Housekeeping calls this on its timer and once at start-up (app/main.py);
        True when anything changed."""
        with self._lock:
            return self._expire_locked()

    def _save(self) -> None:
        try:
            folder = self.path.parent
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                if folder.stat().st_mode & 0o077:
                    folder.chmod(0o700)
            except OSError:
                pass
            text = json.dumps(self._data, indent=2, ensure_ascii=False)
            while len(text.encode("utf-8")) > MAX_FILE_BYTES and self._data["done"]:
                # Never reached while the bounds hold; if it is, the oldest done rows go first.
                self._data["done"] = self._data["done"][len(self._data["done"]) // 2 + 1:]
                text = json.dumps(self._data, indent=2, ensure_ascii=False)
            if len(text.encode("utf-8")) > MAX_FILE_BYTES:
                log.error("screens record over %d bytes; not written", MAX_FILE_BYTES)
                return
            tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex[:8]}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except OSError:
            log.warning("screens record not written", exc_info=True)

    # ---- screens ---------------------------------------------------------------------------
    def register(self, name: str) -> dict[str, Any]:
        """A device names itself a screen, and is given that screen's key (in the answer, once).
        A name in use by a screen that is on is refused; a screen that has gone quiet can be
        named again from another device, which gets a new key: the old device's no longer fits."""
        shown = clean_name(name)
        key = name_key(shown)
        if not key:
            raise DisplayError("Give the screen a name, like office screen.")
        secret = secrets.token_urlsafe(24)
        with self._lock:
            for screen in self._data["screens"].values():
                if screen.get("key") == key:
                    if self.online(screen["id"]):
                        raise DisplayError(f"A screen called {screen['name']} is on right now. Give this one another name.")
                    screen["secret"] = _key_hash(secret)
                    screen["version"] = int(screen.get("version", 0)) + 1
                    self._touch(screen["id"])
                    self._save()
                    return {**self._public(screen), "screen_key": secret}
            if len(self._data["screens"]) >= MAX_SCREENS:
                oldest = min(self._data["screens"].values(), key=lambda s: s.get("last_seen") or "")
                del self._data["screens"][oldest["id"]]
            ident = "scr_" + secrets.token_hex(6)
            screen = {"id": ident, "name": shown, "key": key, "secret": _key_hash(secret), "created_at": _now_iso(),
                      "last_seen": _now_iso(), "version": 0, "showing": None}
            self._data["screens"][ident] = screen
            self._touch(ident)
            self._save()
            return {**self._public(screen), "screen_key": secret}

    @staticmethod
    def _public(screen: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in screen.items() if k != "secret"}

    def _holder(self, screen: dict[str, Any], screen_key: str) -> None:
        """Refused unless the device asking holds this screen's key. A screen recorded before
        keys existed holds none, and is named again."""
        kept = screen.get("secret")
        if not kept or not screen_key or not hmac.compare_digest(str(kept), _key_hash(screen_key)):
            raise NotThisScreen("This device is not that screen any more. Name it again.")

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
        return self._public(screen) if screen else None

    def find(self, name: str, *, exact: bool = False) -> dict[str, Any]:
        """The screen a spoken name means: exactly, else the one screen whose name contains
        every word said ("office" finds "office mac"). With `exact`, only the screen's own name
        (however it is typed or spaced) will do: what goes on a screen can be a customer's
        name and address, and it goes where it was sent or nowhere (the 2026-09-27 deploy
        review, B-05). Anything else is said plainly."""
        key = name_key(name)
        screens = list(self._data["screens"].values())
        if not screens:
            raise DisplayError("No screens yet. Open CLIVE's address with /display on the screen and give it a name.")
        matches = [s for s in screens if s.get("key") == key]
        if matches:
            return self._public(matches[0])
        if exact:
            names = ", ".join(sorted(s["name"] for s in screens))
            raise DisplayError(f"There is no screen called exactly {name!r}. Say its full name: {names}.")
        words = key.split()
        near = [s for s in screens if words and all(w in s.get("key", "").split() for w in words)]
        if len(near) == 1:
            return self._public(near[0])
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

    def _expire_locked(self) -> bool:
        """Whatever has been up for SHOWING_KEEP_S comes down, and is not kept; done rows older
        than DONE_KEEP_S go. A slip whose time cannot be read is taken down too."""
        now = self.clock()
        cutoff = datetime.fromtimestamp(now - SHOWING_KEEP_S, UTC).isoformat(timespec="seconds")
        done_cutoff = datetime.fromtimestamp(now - DONE_KEEP_S, UTC).isoformat(timespec="seconds")
        changed = False
        for screen in self._data["screens"].values():
            showing = screen.get("showing")
            if showing is not None and (not isinstance(showing, dict) or str(showing.get("at") or "") < cutoff):
                screen["showing"] = None
                screen["version"] = int(screen.get("version", 0)) + 1
                changed = True
        kept = [d for d in self._data["done"] if isinstance(d, dict) and str(d.get("at") or "") >= done_cutoff]
        if len(kept) != len(self._data["done"]):
            self._data["done"] = kept
            changed = True
        if changed:
            self._save()
        return changed

    def screens(self) -> list[dict[str, Any]]:
        with self._lock:
            self._expire_locked()
        out = []
        for screen in sorted(self._data["screens"].values(), key=lambda s: s.get("name", "")):
            showing = screen.get("showing") or {}
            out.append({"id": screen["id"], "name": screen["name"], "online": self.online(screen["id"]),
                        "showing": showing.get("title") or None, "since": showing.get("at")})
        return out

    # ---- what a screen shows ---------------------------------------------------------------
    def poll(self, screen_id: str, screen_key: str) -> dict[str, Any] | None:
        """What the screen should show now, and its version, for the device holding its key.
        The screen is seen."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                return None
            self._holder(screen, screen_key)
            self._expire_locked()
            self._touch(screen_id)
            last = next((d for d in reversed(self._data["done"]) if d.get("screen_id") == screen_id), None)
            return {"id": screen_id, "name": screen["name"], "version": screen.get("version", 0),
                    "showing": screen.get("showing"),
                    "last_done": {"title": last.get("title"), "at": last.get("at")} if last else None}

    def show(self, screen_id: str, showing: dict[str, Any] | None, *, by: str = "clive") -> dict[str, Any]:
        if showing is not None and len(json.dumps(showing, ensure_ascii=False).encode("utf-8")) > MAX_VIEW_BYTES:
            raise DisplayError("That is more than one screen can show.")
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise DisplayError("That screen is not there any more.")
            if showing is not None:
                showing = {**showing, "at": _now_iso(), "by": str(by or "")[:80]}
            screen["showing"] = showing
            screen["version"] = int(screen.get("version", 0)) + 1
            self._save()
            return self._public(screen)

    def mark_done(self, screen_id: str, version: int, *, screen_key: str, items_seen: int | None = None,
                  by: str = "") -> dict[str, Any]:
        """What the screen is showing was physically done, tapped on the screen holding its key.
        Refused if the screen has moved on since it was drawn, so a late tap never marks the wrong
        thing; and for an order, unless every item on it was on the screen (round 6, B-04). The
        slip is then cut down to what the done record needs (B-03)."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise DisplayError("That screen is not there any more.")
            self._holder(screen, screen_key)
            showing = screen.get("showing")
            if not showing or int(version) != int(screen.get("version", 0)):
                raise DisplayError("The screen changed before that tap; nothing was marked.")
            if showing.get("done_at"):
                return self._public(screen)
            if showing.get("kind") == "order" and (showing.get("order") or {}).get("partial"):
                # A slip cut at views.MAX_ITEMS: the rest of the order was never on any screen.
                raise DisplayError("This order has more items than a screen shows, so it cannot be marked packed here.")
            shown = _shown_count(showing)
            if shown is not None and (items_seen is None or int(items_seen) < shown):
                what = "item on the order" if showing.get("kind") == "order" else "line of the list"
                raise DisplayError(f"Not every {what} was on the screen, so nothing was marked.")
            when = _now_iso()
            showing = {k: showing.get(k) for k in DONE_FIELDS if k in showing}
            showing["done_at"] = when
            screen["showing"] = showing
            screen["version"] = int(screen.get("version", 0)) + 1
            self._data["done"].append({
                "at": when, "screen": str(screen["name"])[:MAX_NAME], "screen_id": screen_id,
                "kind": str(showing.get("kind") or "")[:20], "ref": str(showing.get("ref") or "")[:MAX_ID],
                "title": str(showing.get("title") or "")[:MAX_TITLE], "by": str(by or "")[:80] or None,
            })
            self._data["done"] = self._data["done"][-MAX_DONE:]
            self._save()
            return self._public(screen)

    def done(self, *, ref: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        rows = [d for d in self._data["done"] if ref is None or d.get("ref") == ref]
        return list(reversed(rows[-limit:]))


_STORE: DisplayStore | None = None


def install(path: Path, *, clock=time.time) -> DisplayStore:
    """The record, read and swept at once: a start after a long stop does not keep a slip up, or
    a done row, a moment past its time."""
    global _STORE
    _STORE = DisplayStore(path, clock=clock)
    _STORE.sweep()
    return _STORE


def store() -> DisplayStore:
    if _STORE is None:
        from config.settings import get_settings

        return install(get_settings().objectives_dir / "displays.json")
    return _STORE
