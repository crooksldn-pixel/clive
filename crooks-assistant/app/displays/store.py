"""Screens CLIVE can put things on, and what was marked done on them.

Any of the owner's devices becomes a screen by opening `/display` and giving itself a name —
"office mac", "bedroom screen", "packing tablet". From then on the owner can say "put order
2048 on the office mac" and it appears there, large: a fulfilment slip, an objective, or a
checklist. A screen asks every couple of seconds whether it has something new, so nothing has
to reach into it.

A screen can mark what it shows as done ("Mark packed"). That is CLIVE's own record that the
work was physically done, which screen it was done on and when — separate from Shopify, which
can only say a label was created. CLIVE reads it back ("has 2048 been packed?").

Who a screen is (the 2026-09-27 deploy reviews, rounds 6 and 7, B-02). Only the owner can name
one: every route here is his (app/routes/displays.py), so pairing a screen is his verified
device asking. Naming hands that device a key, once, and every later ask, page acknowledgement
and "done" must carry it; only the key's hash is kept. A name already in use is never handed to
another device — not when the screen is quiet, not after a restart. The device holding the key
may name it again (and gets a new key). Otherwise the old screen must first be removed, by the
owner, explicitly (`forget`), which clears whatever it was showing and its key: a new device
named the same gets a new screen, with nothing on it.

What "done" rests on (round 7, B-04). The server keeps, for what a screen is showing now, which
of its items the screen has acknowledged putting up, a page at a time (`acknowledge`, at most
MAX_ACK items each). An order or a list is marked done only once every item has been
acknowledged for the version showing now; a count the page asserts is not evidence. A slip cut
at views.MAX_ITEMS is never marked done here. Acknowledgements are held in memory: after a
restart the screen shows its pages again before it can say done.

What is kept, and for how long (rounds 6 and 7, B-03). An order's slip carries the customer's
name, address, phone and note, and the moment it is marked done the slip is cut down to what
the done record needs — a kind, a reference and a title that cannot be anyone's words ("Order
#2048", "Objective", "List"; a list's own title is the owner's text and may name a customer, so
it is not kept). Anything left up longer than SHOWING_KEEP_S is taken down by itself — when a
screen asks, when CLIVE lists the screens, on the backend's housekeeping timer and when the
record is first read after a start. Done rows are kept DONE_KEEP_S and MAX_DONE at most, every
field bounded; one view is at most views.MAX_VIEW_BYTES, and the file is checked against
MAX_FILE_BYTES before it is written.

Writes are atomic and durable (the temporary file and then the folder are flushed), and a write
that fails is never taken for one that succeeded: a change is undone in memory and refused, and a
slip taken down in memory whose removal from disk failed stays down (it is not shown again) while
the store says so — `sweep` returns it as a problem for /health — and tries again on every pass.

One JSON file beside the objectives, 0600 in a 0700 folder. Nothing here is sent anywhere.
"""

from __future__ import annotations

import copy
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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.displays.views import MAX_VIEW_BYTES

log = logging.getLogger("crooks.displays")

# A screen that has asked within this long is on.
ONLINE_S = 30.0
# How often a screen's "last seen" is written down; in memory it is exact.
SEEN_WRITE_S = 60.0
MAX_SCREENS = 20
MAX_DONE = 500
MAX_NAME = 40
# The most items one acknowledgement may cover: the largest page a screen puts up
# (web/display.js: twelve lines of a list on a wide screen).
MAX_ACK = 12
# What a screen shows is taken down after this long, whatever it is.
SHOWING_KEEP_S = 12 * 3600
# How long a done row is kept ("has 2048 been packed?" is asked within days, not seasons).
DONE_KEEP_S = 90 * 86_400
# The whole record, written down: 20 screens at the largest view each and the done record full
# come to about 1.4 MB, so this is never reached unless something above is broken.
MAX_FILE_BYTES = 2_000_000
_ID = re.compile(r"^scr_[0-9a-f]{12}$")
_ORDER_TITLE = re.compile(r"^Order #?[0-9]{1,12}$")
_ORDER_REF = re.compile(r"^gid://shopify/Order/[0-9]{1,20}$")
_OBJECTIVE_REF = re.compile(r"^obj_[0-9a-f]{8}$")


def _shown_count(showing: dict[str, Any]) -> int | None:
    """How many things a slip or list asks to be seen before it is marked done; None for a view
    that is not marked item by item."""
    if showing.get("kind") == "order":
        return len((showing.get("order") or {}).get("items") or [])
    if showing.get("kind") == "list":
        return len((showing.get("list") or {}).get("lines") or [])
    return None


def done_summary(showing: dict[str, Any]) -> dict[str, str]:
    """What the done record keeps of a view: its kind, a reference, and a title that cannot be
    anyone's words — an order's number, or just the kind (round 7, B-03)."""
    kind = showing.get("kind")
    ref = str(showing.get("ref") or "")
    if kind == "order":
        title = str(showing.get("title") or "")
        return {"kind": "order", "ref": ref if _ORDER_REF.fullmatch(ref) else "",
                "title": title if _ORDER_TITLE.fullmatch(title) else "Order"}
    if kind == "objective":
        return {"kind": "objective", "ref": ref if _OBJECTIVE_REF.fullmatch(ref) else "", "title": "Objective"}
    return {"kind": "list", "ref": "", "title": "List"}


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


def _fsync_dir(folder: Path) -> None:
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class DisplayError(ValueError):
    """Said to the owner as it is."""


class NotThisScreen(DisplayError):
    """The device asking does not hold this screen's key."""


class NameTaken(DisplayError):
    """A screen already has this name, and the device asking does not hold its key."""


class NotSeen(DisplayError):
    """Done was asked for before every item was acknowledged on the screen."""


class NotSaved(DisplayError):
    """The record could not be written; nothing was changed."""


class DisplayStore:
    def __init__(self, path: Path, *, clock=time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()
        self._data = self._load()
        self._seen: dict[str, float] = {}
        self._seen_written: dict[str, float] = {}
        # screen id -> (version, the item indices acknowledged for that version)
        self._acks: dict[str, tuple[int, set[int]]] = {}
        # A slip taken down in memory whose removal could not yet be written (said by sweep()).
        self.unsaved = False

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
        # Done rows written before round 7 are cut to the same policy as new ones.
        data["done"] = [self._done_row(row) for row in data["done"] if isinstance(row, dict)]
        return data

    @staticmethod
    def _done_row(row: dict[str, Any]) -> dict[str, Any]:
        return {**done_summary(row), "at": str(row.get("at") or "")[:40], "screen": str(row.get("screen") or "")[:MAX_NAME],
                "screen_id": str(row.get("screen_id") or "")[:20], "by": (str(row.get("by") or "")[:80] or None)}

    def _write(self) -> None:
        """Write the record: a 0600 temporary file, flushed, renamed into place, and the folder
        flushed after. Raises if the record could not be put in place (nothing changed on disk).
        Once it is in place, a failure to flush the folder cannot be undone by raising: the new
        record IS the file. That is kept as `unsaved` — said by sweep() on /health and written
        again, durably, on the next pass — rather than passed over."""
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if folder.stat().st_mode & 0o077:
            folder.chmod(0o700)
        text = json.dumps(self._data, indent=2, ensure_ascii=False)
        while len(text.encode("utf-8")) > MAX_FILE_BYTES and self._data["done"]:
            # Never reached while the bounds hold; if it is, the oldest done rows go first.
            self._data["done"] = self._data["done"][len(self._data["done"]) // 2 + 1:]
            text = json.dumps(self._data, indent=2, ensure_ascii=False)
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise OSError(f"screens record over {MAX_FILE_BYTES} bytes")
        tmp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex[:8]}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        try:
            _fsync_dir(folder)
        except OSError as exc:
            self.unsaved = True
            log.error("screens record written but its folder could not be flushed: %s", exc)
            return
        self.unsaved = False

    def _commit(self, change: Callable[[], Any]) -> Any:
        """One change, written down or not made at all: on a failed write the record in memory
        is put back as it was and the change is refused."""
        before = copy.deepcopy(self._data)
        result = change()
        try:
            self._write()
        except OSError as exc:
            self._data = before
            log.error("screens record not written; the change was not made: %s", exc)
            raise NotSaved("That could not be saved just now; nothing was changed. Try again.") from exc
        return result

    def _settle_expiry(self) -> str:
        """After slips were taken down in memory (or after a write that was not made durable):
        write it, or say it could not be (and keep trying on every pass). Never puts a slip back
        up."""
        try:
            self._write()
        except OSError as exc:
            self.unsaved = True
            log.error("an expired slip was taken down but could not yet be removed from disk: %s", exc)
            return "a slip taken down on a screen could not yet be removed from disk"
        if self.unsaved:
            return "the screens record could not be made durable on disk yet"
        return ""

    def sweep(self) -> str:
        """Take down whatever has been up too long and age the done record, now, whoever is
        asking or not. Housekeeping calls this on its timer and once at start-up (app/main.py).
        Returns what it could not do ('' when nothing)."""
        with self._lock:
            if self._expire_locked() or self.unsaved:
                return self._settle_expiry()
            return ""

    # ---- screens ---------------------------------------------------------------------------
    def register(self, name: str, *, screen_key: str = "") -> dict[str, Any]:
        """The owner's device names itself a screen, and is given that screen's key (in the
        answer, once). A name already in use is refused unless the device holds that screen's
        key (then it gets a new one): it never passes to another device by name (round 7, B-02).
        To give the name to a new device, the owner removes the old screen first (`forget`)."""
        shown = clean_name(name)
        key = name_key(shown)
        if not key:
            raise DisplayError("Give the screen a name, like office screen.")
        secret = secrets.token_urlsafe(24)
        with self._lock:
            for screen in self._data["screens"].values():
                if screen.get("key") != key:
                    continue
                kept = screen.get("secret")
                if not (kept and screen_key and hmac.compare_digest(str(kept), _key_hash(screen_key))):
                    raise NameTaken(f"There is already a screen called {screen['name']}. If this is that screen and "
                                    "it has lost its key, remove the old one first: that clears what it was showing.")

                def rotate(screen=screen) -> dict[str, Any]:
                    screen["secret"] = _key_hash(secret)
                    return {**self._public(screen), "screen_key": secret}

                out = self._commit(rotate)
                self._touch(screen["id"])
                return out

            def create() -> dict[str, Any]:
                if len(self._data["screens"]) >= MAX_SCREENS:
                    oldest = min(self._data["screens"].values(), key=lambda s: s.get("last_seen") or "")
                    del self._data["screens"][oldest["id"]]
                    self._acks.pop(oldest["id"], None)
                ident = "scr_" + secrets.token_hex(6)
                screen = {"id": ident, "name": shown, "key": key, "secret": _key_hash(secret), "created_at": _now_iso(),
                          "last_seen": _now_iso(), "version": 0, "showing": None}
                self._data["screens"][ident] = screen
                return {**self._public(screen), "screen_key": secret}

            out = self._commit(create)
            self._touch(out["id"])
            return out

    @staticmethod
    def _public(screen: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in screen.items() if k != "secret"}

    def _holder(self, screen: dict[str, Any], screen_key: str) -> None:
        """Refused unless the device asking holds this screen's key."""
        kept = screen.get("secret")
        if not kept or not screen_key or not hmac.compare_digest(str(kept), _key_hash(screen_key)):
            raise NotThisScreen("This device is not that screen any more. Name it again.")

    def forget(self, screen_id: str) -> bool:
        """The owner removes a screen: its name, its key and whatever it was showing go at once."""
        with self._lock:
            if str(screen_id) not in self._data["screens"]:
                return False
            self._commit(lambda: self._data["screens"].pop(str(screen_id), None))
            self._acks.pop(str(screen_id), None)
            return True

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
        """Seen now. "Last seen" is written down now and then, and a failure to write it down
        costs nothing but its accuracy."""
        now = self.clock()
        self._seen[screen_id] = now
        screen = self._data["screens"].get(screen_id)
        if screen is not None and now - self._seen_written.get(screen_id, 0.0) >= SEEN_WRITE_S:
            screen["last_seen"] = _now_iso()
            self._seen_written[screen_id] = now
            try:
                self._write()
            except OSError:
                log.warning("screens record: last seen not written", exc_info=True)

    def online(self, screen_id: str) -> bool:
        return self.clock() - self._seen.get(screen_id, -1e9) <= ONLINE_S

    def _expire_locked(self) -> bool:
        """Whatever has been up for SHOWING_KEEP_S comes down, in memory now; done rows older
        than DONE_KEEP_S go. A slip whose time cannot be read is taken down too. True when
        anything changed; the caller writes it down (or says it could not)."""
        now = self.clock()
        cutoff = datetime.fromtimestamp(now - SHOWING_KEEP_S, UTC).isoformat(timespec="seconds")
        done_cutoff = datetime.fromtimestamp(now - DONE_KEEP_S, UTC).isoformat(timespec="seconds")
        changed = False
        for screen in self._data["screens"].values():
            showing = screen.get("showing")
            if showing is not None and (not isinstance(showing, dict) or str(showing.get("at") or "") < cutoff):
                screen["showing"] = None
                screen["version"] = int(screen.get("version", 0)) + 1
                self._acks.pop(screen["id"], None)
                changed = True
        kept = [d for d in self._data["done"] if isinstance(d, dict) and str(d.get("at") or "") >= done_cutoff]
        if len(kept) != len(self._data["done"]):
            self._data["done"] = kept
            changed = True
        return changed

    def screens(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._expire_locked() or self.unsaved:
                self._settle_expiry()
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
            if self._expire_locked() or self.unsaved:
                self._settle_expiry()
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

            def put() -> dict[str, Any]:
                screen["showing"] = None if showing is None else {**showing, "at": _now_iso(), "by": str(by or "")[:80]}
                screen["version"] = int(screen.get("version", 0)) + 1
                return self._public(screen)

            out = self._commit(put)
            self._acks.pop(screen_id, None)
            return out

    def acknowledge(self, screen_id: str, version: int, *, screen_key: str, start: int, end: int) -> int:
        """The screen holding this key says items [start, end) of what it shows are up on it now.
        At most MAX_ACK at a time — a page, never the whole order in one word. Returns how many
        items are acknowledged so far for this version."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise DisplayError("That screen is not there any more.")
            self._holder(screen, screen_key)
            showing = screen.get("showing")
            if not showing or int(version) != int(screen.get("version", 0)) or showing.get("done_at"):
                raise DisplayError("The screen changed before that; show the page again.")
            count = _shown_count(showing)
            if count is None:
                raise DisplayError("Nothing on this screen is marked item by item.")
            start, end = int(start), int(end)
            if not (0 <= start < end <= count) or end - start > MAX_ACK:
                raise DisplayError(f"A page is at most {MAX_ACK} items of the {count} on the screen.")
            held_version, seen = self._acks.get(screen_id, (int(version), set()))
            if held_version != int(version):
                seen = set()
            seen.update(range(start, end))
            self._acks[screen_id] = (int(version), seen)
            return len(seen)

    def mark_done(self, screen_id: str, version: int, *, screen_key: str, by: str = "") -> dict[str, Any]:
        """What the screen is showing was physically done, tapped on the screen holding its key.
        Refused if the screen has moved on since it was drawn, so a late tap never marks the wrong
        thing; for an order or a list, unless every item was acknowledged on the screen for the
        version showing now (round 7, B-04); and for a slip cut at the screen's limit. The slip
        is then cut down to what the done record needs (B-03)."""
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
            count = _shown_count(showing)
            if count:
                held_version, seen = self._acks.get(screen_id, (-1, set()))
                if held_version != int(version) or not set(range(count)) <= seen:
                    what = "item on the order" if showing.get("kind") == "order" else "line of the list"
                    raise NotSeen(f"Not every {what} has been on the screen yet, so nothing was marked.")
            when = _now_iso()

            def done() -> dict[str, Any]:
                summary = done_summary(showing)
                screen["showing"] = {**summary, "at": showing.get("at"), "by": showing.get("by"), "done_at": when}
                screen["version"] = int(screen.get("version", 0)) + 1
                self._data["done"].append(self._done_row({**summary, "at": when, "screen": screen["name"],
                                                          "screen_id": screen_id, "by": by}))
                self._data["done"] = self._data["done"][-MAX_DONE:]
                return self._public(screen)

            out = self._commit(done)
            self._acks.pop(screen_id, None)
            return out

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
