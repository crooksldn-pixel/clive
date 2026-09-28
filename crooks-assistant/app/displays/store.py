"""Screens CLIVE can put things on, and what was marked done on them.

Any of the owner's devices becomes a screen by opening `/display` and giving itself a name —
"office mac", "bedroom screen", "packing tablet". From then on the owner can say "put order
2048 on the office mac" and it appears there, large: a fulfilment slip, an objective, or a
checklist. A screen asks every couple of seconds whether it has something new, so nothing has
to reach into it.

A screen can mark what it shows as done ("Mark packed"). That is CLIVE's own record that the
work was physically done, which screen it was done on and when — separate from Shopify, which
can only say a label was created. CLIVE reads it back ("has 2048 been packed?").

Who a screen is (the 2026-09-27 deploy reviews, rounds 6 to 8, B-02 and B-05). Only the owner
can name one: every route here is his (app/routes/displays.py). Naming hands that device a key,
once, and every later ask, page acknowledgement and "done" must carry it; only the key's hash is
kept. A new name is not a screen yet: it is waiting for approval, and the device shows a
six-digit code (only its hash is kept here, for PAIR_CODE_S). The owner reads the code off the
device he means and tells CLIVE, which approves it (`approve`, the screen_pair tool). Until then
nothing is ever put on it. PAIR_TRIES wrong codes cancel the request, and so does the code
running out; either frees the name, and neither screen ever showed anything. So the name is
bound to the physical device the owner read the code from, not to whichever admitted device
asked first. A screen written down before approval existed counts as approved.

An approved name is never handed to another device — not when the screen is quiet, not after a
restart, not when there are many screens (at MAX_SCREENS a new name is refused; nothing is
removed to make room, round 8, NEW-B-CAP). The device holding the key may name it again (and
gets a new key). Otherwise the owner removes the old screen first, explicitly (`forget`), which
clears whatever it was showing and its key.

What "done" rests on (rounds 7 and 8, B-04). The server keeps, for what a screen is showing now,
how far through its items the screen has acknowledged putting them up: pages told in order from
the first item, each starting where the last ended, all the same size but the last and at most
MAX_ACK, each at least ACK_GAP_S after the one before. An order or a list is marked done only
once every item has been acknowledged for the version showing now, at least ACK_GAP_S after the
last page, and only when the tap says so (`confirmed`). This is still the key-holding screen's
own word: it is harder to fake and cannot be hurried, not proven. A slip cut at views.MAX_ITEMS
is never marked done here. Acknowledgements are held in memory: after a restart the screen shows
its pages again before it can say done.

What is kept, and for how long (rounds 6 to 8, B-03). An order's slip carries the customer's
name, address, phone and note, and the moment it is marked done the slip is cut down to what
the done record needs — a kind, a reference and a title that cannot be anyone's words ("Order
#2048", "Objective", "List"). Anything left up longer than SHOWING_KEEP_S is taken down by
itself. Done rows are kept DONE_KEEP_S and MAX_DONE at most, every field bounded; one view is at
most views.MAX_VIEW_BYTES, and the file is checked against MAX_FILE_BYTES before it is written.

Writes are atomic and durable (the temporary file and then the folder are flushed). A deletion —
a slip cut down when it is marked done, a slip replaced or cleared, a slip past its time, a
screen removed — is written first to a small purge journal beside the record
(displays.purge.json), flushed with its folder, and only then to the record. If the record then
cannot be made durable, the deletion stands in memory, the journal keeps it across a restart
(it is applied before anything else when the record is next read) and the caller is told it is
not saved yet, never that it is done. The journal goes once a write of the record is durable.

One JSON file beside the objectives, 0600 in a 0700 folder. Nothing here is sent anywhere.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
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
# A page acknowledgement, and "done", come at least this long after the page before it for the
# same version (server monotonic time; round 8, B-04).
ACK_GAP_S = 1.0
# What a screen shows is taken down after this long, whatever it is.
SHOWING_KEEP_S = 12 * 3600
# How long a done row is kept ("has 2048 been packed?" is asked within days, not seasons).
DONE_KEEP_S = 90 * 86_400
# A new screen's approval code works this long, and this many wrong codes cancel the request
# (round 8, B-02).
PAIR_CODE_S = 15 * 60
PAIR_TRIES = 5
# The whole record, written down: 20 screens at the largest view each and the done record full
# come to about 1.4 MB, so this is never reached unless something above is broken. The purge
# journal is held to the same bound.
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


def _done_showing(showing: Any) -> dict[str, Any] | None:
    """What a screen may show once its slip is done: the summary and its times, nothing else.
    Anything that is not a done summary is nothing at all (used for what the journal restores,
    so even a journal that was tampered with cannot put a customer's details back)."""
    if not isinstance(showing, dict) or not showing.get("done_at"):
        return None
    return {**done_summary(showing), "at": str(showing.get("at") or "")[:40], "by": str(showing.get("by") or "")[:80],
            "done_at": str(showing.get("done_at") or "")[:40]}


def _whole(value: Any, default: int = 0) -> int:
    """A whole number from the record, or `default` for anything that is not one."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _key_hash(key: str) -> str:
    return hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()


def _code_hash(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


def _same(kept: Any, given: str) -> bool:
    """A constant-time comparison of two digests, whatever the stored one turns out to hold."""
    return hmac.compare_digest(str(kept or "").encode("utf-8"), str(given or "").encode("utf-8"))


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


class TooMany(DisplayError):
    """There are MAX_SCREENS screens; one must be removed, by the owner, before another is named."""


class NotPaired(DisplayError):
    """The screen is waiting for the owner to approve it; nothing goes on it until then."""


class NotSeen(DisplayError):
    """Done was asked for before every item was acknowledged on the screen."""


class NotConfirmed(DisplayError):
    """Done was asked for without the tap that says so."""


class OutOfOrder(DisplayError):
    """A page acknowledgement that does not carry on from where the last one ended."""

    def __init__(self, message: str, *, covered: int, size: int) -> None:
        super().__init__(message)
        self.covered = covered
        self.size = size


class TooSoon(DisplayError):
    """An acknowledgement, or done, sooner than ACK_GAP_S after the page before it."""

    def __init__(self, message: str, *, retry_after_ms: int) -> None:
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class NotSaved(DisplayError):
    """The record could not be written; nothing was changed."""


class NotDurable(NotSaved):
    """The change was made and is in the record, but the record could not be made durable yet:
    it is not reported as done. A deletion is kept in the purge journal meanwhile."""


class NotFlushed(OSError):
    """The file was put in place but its folder could not be flushed."""


@dataclass(slots=True)
class _Acks:
    """How far through what it shows a screen has acknowledged, for one version."""

    version: int
    covered: int = 0                  # items [0, covered) acknowledged, in order
    size: int = 0                     # the page size every page but the last must have
    last: float = float("-inf")       # when the last new page was acknowledged (monotonic)


_NOT_SAVED = "That could not be saved just now; nothing was changed. Try again."
_NOT_DURABLE = "That was done, but CLIVE could not make sure it is saved yet. It keeps trying; check again in a moment."


class DisplayStore:
    def __init__(self, path: Path, *, clock=time.time, mono=time.monotonic) -> None:
        self.path = Path(path)
        self.journal_path = self.path.with_name(f"{self.path.stem}.purge.json")
        self.clock = clock
        self.mono = mono
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}
        self._seen_written: dict[str, float] = {}
        self._acks: dict[str, _Acks] = {}
        # The record in memory differs from what is durably on disk (said by sweep()).
        self.unsaved = False
        # Deletions made in memory that are not yet durably in the record: screen id -> what the
        # purge journal says of it (round 8, B-03). Emptied by the first durable write.
        self._purges: dict[str, dict[str, Any]] = {}
        self._data = self._load()
        if self._purges or self.journal_path.exists():
            # The journal was applied before anything else (_load); now the record says it too.
            try:
                self._write()
            except OSError as exc:
                self.unsaved = True
                log.error("screens record: owed deletions applied in memory but not yet written: %s", exc)

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
        data["screens"] = {k: v for k, v in data["screens"].items() if isinstance(v, dict)}
        if not isinstance(data.get("done"), list):
            data["done"] = []
        # Done rows written before round 7 are cut to the same policy as new ones.
        data["done"] = [self._done_row(row) for row in data["done"] if isinstance(row, dict)]
        self._replay(data)
        return data

    def _replay(self, data: dict[str, Any]) -> None:
        """A deletion owed when the service stopped (round 8, B-03): what the purge journal holds
        is applied before anything else reads the record. Applying it twice changes nothing — a
        screen already at or past the version a deletion made is left alone — so a journal that
        outlived its write is harmless. A journal that cannot be read means CLIVE cannot tell
        which slips it promised to take down, so every slip comes down."""
        try:
            raw = self.journal_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            raw = ""
        try:
            entries = json.loads(raw)["screens"]
            if not isinstance(entries, dict) or not all(_ID.fullmatch(str(k)) and isinstance(v, dict) for k, v in entries.items()):
                raise ValueError("not a purge journal")
        except (ValueError, KeyError, TypeError):
            log.error("screens purge journal unreadable at %s; every slip is taken down", self.journal_path)
            for sid, screen in data["screens"].items():
                if screen.get("showing") is not None:
                    screen["showing"] = None
                    screen["version"] = _whole(screen.get("version")) + 1
                    self._purges[sid] = {"version": screen["version"], "showing": None}
            return
        screens = data["screens"]
        added = False
        for sid, entry in entries.items():
            # Only what a journal entry can say is kept of it: that the screen is gone, or the
            # version it must be at and the done summary it shows; and the done rows owed.
            rows = [self._done_row(r) for r in entry.get("done") or [] if isinstance(r, dict)] if isinstance(entry.get("done"), list) else []
            for row in rows:
                if row not in data["done"]:
                    data["done"].append(row)
                    added = True
            if entry.get("forget"):
                self._purges[sid] = {"forget": True, **({"done": rows} if rows else {})}
                screens.pop(sid, None)
                continue
            screen = screens.get(sid)
            want = _whole(entry.get("version"), -1)
            if screen is not None and want < 0:
                want = _whole(screen.get("version")) + 1
            showing = _done_showing(entry.get("showing"))
            self._purges[sid] = {"version": max(want, 0), "showing": showing, **({"done": rows} if rows else {})}
            if screen is None or _whole(screen.get("version")) >= want:
                continue
            screen["showing"] = showing
            screen["version"] = want
        if added:
            data["done"] = sorted(data["done"], key=lambda d: d.get("at") or "")[-MAX_DONE:]

    @staticmethod
    def _merge(owed: dict[str, dict[str, Any]], more: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Deletions owed, with more added. One entry per screen: the latest version it must be
        at (or that it is gone), and every done row still owed for it, so a later deletion never
        drops an earlier one's record of what was packed."""
        out = dict(owed)
        for sid, entry in more.items():
            earlier = out.get(sid) or {}
            done = [*(earlier.get("done") or []), *(entry.get("done") or [])][-MAX_DONE:]
            if entry.get("forget") or earlier.get("forget"):
                merged: dict[str, Any] = {"forget": True}
            else:
                merged = {"version": entry["version"], "showing": entry.get("showing")}
            if done:
                merged["done"] = done
            out[sid] = merged
        return out

    @staticmethod
    def _done_row(row: dict[str, Any]) -> dict[str, Any]:
        return {**done_summary(row), "at": str(row.get("at") or "")[:40], "screen": str(row.get("screen") or "")[:MAX_NAME],
                "screen_id": str(row.get("screen_id") or "")[:20], "by": (str(row.get("by") or "")[:80] or None)}

    def _folder(self) -> Path:
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if folder.stat().st_mode & 0o077:
            folder.chmod(0o700)
        return folder

    def _put(self, target: Path, text: str) -> None:
        """A 0600 temporary file, flushed and renamed into place. Raises (leaving nothing behind)
        if it could not be put in place."""
        tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _journal(self, owed: dict[str, dict[str, Any]]) -> bool:
        """The purge journal, written before the record (round 8, B-03). True once it and its
        folder are flushed; False when it is in place but the folder could not be flushed.
        Raises if it could not be put in place: then nothing on disk changed."""
        folder = self._folder()
        text = json.dumps({"screens": owed}, ensure_ascii=False)
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise OSError(f"screens purge journal over {MAX_FILE_BYTES} bytes")
        self._put(self.journal_path, text)
        try:
            _fsync_dir(folder)
        except OSError as exc:
            log.error("screens purge journal written but its folder could not be flushed: %s", exc)
            return False
        return True

    def _drop_journal(self) -> None:
        """Nothing is owed once the record is durable, so the journal goes. Its removal need not
        be flushed, and one that cannot be removed is harmless: a journal that outlives its write
        changes nothing when it is replayed (_replay), and goes after the next durable write."""
        try:
            self.journal_path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            log.warning("screens purge journal not removed: %s", exc)

    def _write(self) -> None:
        """Write the record: a 0600 temporary file, flushed, renamed into place, and the folder
        flushed after. Raises OSError if the record could not be put in place (nothing changed
        on disk). Raises NotFlushed if it was put in place but the folder could not be flushed:
        the new record IS the file, but may not survive a power cut, so that is kept as
        `unsaved` (said by sweep() on /health and written again on the next pass), and what it
        deleted stays in the purge journal. Only a durable write empties the journal."""
        folder = self._folder()
        text = json.dumps(self._data, indent=2, ensure_ascii=False)
        while len(text.encode("utf-8")) > MAX_FILE_BYTES and self._data["done"]:
            # Never reached while the bounds hold; if it is, the oldest done rows go first.
            self._data["done"] = self._data["done"][len(self._data["done"]) // 2 + 1:]
            text = json.dumps(self._data, indent=2, ensure_ascii=False)
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise OSError(f"screens record over {MAX_FILE_BYTES} bytes")
        self._put(self.path, text)
        try:
            _fsync_dir(folder)
        except OSError as exc:
            self.unsaved = True
            log.error("screens record written but its folder could not be flushed: %s", exc)
            raise NotFlushed(str(exc)) from exc
        self.unsaved = False
        self._purges = {}
        self._drop_journal()

    def _commit(self, change: Callable[[], Any], *, owes: Callable[[], dict[str, dict[str, Any]]] | None = None) -> Any:
        """One change, written down or not made at all: on a failed write the record in memory
        is put back as it was and the change is refused.

        A deletion (`owes` says what it deleted) is written to the purge journal first, and
        once the journal is in place the deletion is never put back: if the record then cannot
        be made durable the caller is told NotDurable — not saved yet — and never that it is
        done (round 8, B-03). The same holds for any change written while an earlier deletion is
        still owed, since that write carries it."""
        before = copy.deepcopy(self._data)
        carries = bool(self._purges)
        result = change()
        if owes is not None:
            owed = self._merge(self._purges, owes())
            try:
                self._journal(owed)
            except OSError as exc:
                self._data = before
                log.error("screens purge journal not written; the change was not made: %s", exc)
                raise NotSaved(_NOT_SAVED) from exc
            self._purges = owed
        try:
            self._write()
        except NotFlushed as exc:
            if owes is not None or carries:
                raise NotDurable(_NOT_DURABLE) from exc
            # Not a deletion: the change is the file, and that it may not survive a power cut
            # is said by sweep() and put right on the next pass.
            return result
        except OSError as exc:
            if owes is not None:
                self.unsaved = True
                log.error("screens record not written; the deletion stands and is owed: %s", exc)
                raise NotDurable(_NOT_DURABLE) from exc
            self._data = before
            log.error("screens record not written; the change was not made: %s", exc)
            raise NotSaved(_NOT_SAVED) from exc
        return result

    def _make_durable(self) -> None:
        """Whatever is owed, written durably now, or NotDurable."""
        if self._purges:
            try:
                self._journal(self._purges)
            except OSError:
                log.error("screens purge journal could not be rewritten", exc_info=True)
        try:
            self._write()
        except OSError as exc:
            self.unsaved = True
            raise NotDurable(_NOT_DURABLE) from exc

    def _settle_expiry(self) -> str:
        """After slips were taken down in memory (or after a write that was not made durable):
        write it, or say it could not be (and keep trying on every pass). Never puts a slip back
        up. What was taken down is journaled first; a slip past its time also comes down again
        by itself at the next start."""
        if self._purges:
            try:
                self._journal(self._purges)
            except OSError:
                log.error("screens purge journal could not be written", exc_info=True)
        try:
            self._write()
        except NotFlushed:
            return "the screens record could not be made durable on disk yet"
        except OSError as exc:
            self.unsaved = True
            log.error("an expired slip was taken down but could not yet be removed from disk: %s", exc)
            return "a slip taken down on a screen could not yet be removed from disk"
        return ""

    def sweep(self) -> str:
        """Take down whatever has been up too long, cancel approval requests that ran out, and
        age the done record, now, whoever is asking or not. Housekeeping calls this on its timer
        and once at start-up (app/main.py). Returns what it could not do ('' when nothing)."""
        with self._lock:
            if self._expire_locked() or self.unsaved or self._purges:
                return self._settle_expiry()
            return ""

    # ---- screens ---------------------------------------------------------------------------
    @staticmethod
    def _pending(screen: dict[str, Any]) -> bool:
        """Waiting for the owner's approval (round 8, B-02). A screen written down before
        approval existed has no mark and counts as approved; anything else is waiting."""
        return screen.get("paired", True) is not True

    def _lapsed(self, screen: dict[str, Any], now: float) -> bool:
        """A request for approval whose code has run out (or cannot be read, or claims a time
        further ahead than a code is ever given — a clock put back)."""
        if not self._pending(screen):
            return False
        pairing = screen.get("pairing")
        try:
            until = float(pairing["until"])  # type: ignore[index]
        except (TypeError, KeyError, ValueError):
            return True
        return not (now < until <= now + PAIR_CODE_S + 300)

    def _pairing(self, code: str) -> dict[str, Any]:
        salt = secrets.token_hex(16)
        return {"salt": salt, "hash": _code_hash(salt, code), "until": self.clock() + PAIR_CODE_S, "tries": 0}

    def _answer(self, screen: dict[str, Any], secret: str, code: str | None) -> dict[str, Any]:
        """What naming a screen hands back, once: its key, and the code to approve it by."""
        out = {**self._public(screen), "screen_key": secret, "pending": self._pending(screen)}
        if code is not None:
            out["code"] = code
            out["code_expires_in"] = PAIR_CODE_S
        return out

    def register(self, name: str, *, screen_key: str = "") -> dict[str, Any]:
        """The owner's device names itself a screen, and is given that screen's key and, for a
        new name, the code the owner approves it by (in the answer, once). A new screen waits for
        approval (`approve`) and shows nothing until then. A name already in use is refused
        unless the device holds that screen's key (then it gets a new key, and a waiting screen a
        new code): it never passes to another device by name (round 7, B-02). To give the name to
        a new device, the owner removes the old screen first (`forget`). At MAX_SCREENS a new
        name is refused; nothing is removed to make room (round 8, NEW-B-CAP)."""
        shown = clean_name(name)
        key = name_key(shown)
        if not key:
            raise DisplayError("Give the screen a name, like office screen.")
        secret = secrets.token_urlsafe(24)
        code = f"{secrets.randbelow(1_000_000):06d}"
        with self._lock:
            if self._expire_locked() or self.unsaved:
                # A request that ran out frees its name (and its place) before either is asked for.
                self._settle_expiry()
            for screen in self._data["screens"].values():
                if screen.get("key") != key:
                    continue
                if not self._holds(screen, screen_key):
                    if self._pending(screen):
                        raise NameTaken(f"A screen called {screen['name']} is waiting to be approved. If it is not this one, "
                                        "remove it and name this one: it has never shown anything.")
                    raise NameTaken(f"There is already a screen called {screen['name']}. If this is that screen and "
                                    "it has lost its key, remove the old one first: that clears what it was showing.")

                if self._pending(screen):
                    def renew(screen=screen) -> dict[str, Any]:
                        screen["secret"] = _key_hash(secret)
                        screen["pairing"] = self._pairing(code)
                        return self._answer(screen, secret, code)

                    out = self._commit(renew)
                else:
                    def rotate(screen=screen) -> dict[str, Any]:
                        screen["secret"] = _key_hash(secret)
                        return self._answer(screen, secret, None)

                    out = self._commit(rotate)
                self._touch(screen["id"])
                return out

            if len(self._data["screens"]) >= MAX_SCREENS:
                raise TooMany(f"CLIVE already has {MAX_SCREENS} screens, the most it keeps. Remove one you no longer use "
                              "first: type its name here and tap Remove that screen.")

            def create() -> dict[str, Any]:
                ident = "scr_" + secrets.token_hex(6)
                screen = {"id": ident, "name": shown, "key": key, "secret": _key_hash(secret), "created_at": _now_iso(),
                          "last_seen": _now_iso(), "version": 0, "showing": None, "paired": False,
                          "pairing": self._pairing(code)}
                self._data["screens"][ident] = screen
                return self._answer(screen, secret, code)

            out = self._commit(create)
            self._touch(out["id"])
            return out

    def approve(self, name: str, code: str) -> dict[str, Any]:
        """The owner read the code off the screen he means and said it (the screen_pair tool;
        round 8, B-02): if it is that screen's code, the screen is approved and may be shown
        things from now on. A wrong code counts; PAIR_TRIES of them cancel the request, and so
        does the code running out — either frees the name, and nothing was ever shown."""
        digits = re.sub(r"\D", "", str(code or "")[:40])
        if len(digits) != 6:
            raise DisplayError("The code is the six digits on the screen, like 123 456.")
        key = name_key(name)
        # The screen's page says "approve the bedroom tv screen" for a screen called Bedroom TV:
        # the word "screen" said after a name that does not end in it is not part of the name.
        # (The code, not the name, is what binds the approval to a device.)
        keys = [key, key[: -len(" screen")]] if key.endswith(" screen") else [key]
        with self._lock:
            screen = next((s for k in keys for s in self._data["screens"].values() if s.get("key") == k), None)
            if screen is None:
                raise DisplayError(f"There is no screen called {name!r} waiting to be approved. Name it on the screen "
                                   "first: open CLIVE's address with /display there.")
            if not self._pending(screen):
                return {"screen": screen["name"], "approved": True, "note": "It was already approved."}
            sid = screen["id"]
            if self._lapsed(screen, self.clock()):
                self._void(sid)
                raise DisplayError(f"The code on the {screen['name']} ran out before it was approved. Name the screen again "
                                   "on it for a new code.")
            pairing = screen["pairing"]
            if _same(pairing.get("hash"), _code_hash(str(pairing.get("salt") or ""), digits)):
                def pair() -> None:
                    screen["paired"] = True
                    screen.pop("pairing", None)

                self._commit(pair)
                return {"screen": screen["name"], "approved": True}
            tries = _whole(pairing.get("tries")) + 1
            if tries >= PAIR_TRIES:
                self._void(sid)
                raise DisplayError(f"That was the {PAIR_TRIES}th wrong code, so the request for the {screen['name']} is "
                                   "cancelled and nothing was approved. Name the screen again on it for a new code.")

            def count() -> None:
                pairing["tries"] = tries

            self._commit(count)
            left = PAIR_TRIES - tries
            raise DisplayError(f"That is not the code on the {screen['name']}, so it was not approved. "
                               f"{left} {'try' if left == 1 else 'tries'} left.")

    def _void(self, screen_id: str) -> None:
        """A request for approval cancelled: the record, its key and its code go, journaled like
        a removal so it does not come back after a restart."""
        self._forget_locked(screen_id)

    @staticmethod
    def _public(screen: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in screen.items() if k not in ("secret", "pairing")}

    @staticmethod
    def _holds(screen: dict[str, Any], screen_key: str) -> bool:
        kept = screen.get("secret")
        return bool(kept and screen_key and _same(kept, _key_hash(screen_key)))

    def _holder(self, screen: dict[str, Any], screen_key: str) -> None:
        """Refused unless the device asking holds this screen's key."""
        if not self._holds(screen, screen_key):
            raise NotThisScreen("This device is not that screen any more. Name it again.")

    def forget(self, screen_id: str) -> bool:
        """The owner removes a screen: its name, its key and whatever it was showing go at once.
        A removal is journaled first (round 8, B-03); asked again while it is still owed, it is
        made durable or refused."""
        with self._lock:
            sid = str(screen_id)
            if sid not in self._data["screens"]:
                if sid in self._purges:
                    self._make_durable()
                    return True
                return False
            self._forget_locked(sid)
            return True

    def forget_named(self, name: str) -> str:
        """`forget`, for the screen of exactly this name. "No such screen" is said only once
        every removal already made is durable."""
        with self._lock:
            try:
                screen = self.find(name, exact=True)
            except DisplayError:
                if self._purges:
                    self._make_durable()
                raise
            self._forget_locked(screen["id"])
            return screen["name"]

    def _forget_locked(self, screen_id: str) -> None:
        self._stood(screen_id, lambda: self._commit(lambda: self._data["screens"].pop(screen_id, None),
                                                    owes=lambda: {screen_id: {"forget": True}}))

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
        """Whatever has been up for SHOWING_KEEP_S comes down, in memory now, and is owed to the
        journal; a request for approval that ran out is cancelled; done rows older than
        DONE_KEEP_S go. A slip whose time cannot be read is taken down too. True when anything
        changed; the caller writes it down (or says it could not)."""
        now = self.clock()
        cutoff = datetime.fromtimestamp(now - SHOWING_KEEP_S, UTC).isoformat(timespec="seconds")
        done_cutoff = datetime.fromtimestamp(now - DONE_KEEP_S, UTC).isoformat(timespec="seconds")
        changed = False
        for screen in list(self._data["screens"].values()):
            if self._lapsed(screen, now):
                del self._data["screens"][screen["id"]]
                self._acks.pop(screen["id"], None)
                self._purges = self._merge(self._purges, {screen["id"]: {"forget": True}})
                changed = True
                continue
            showing = screen.get("showing")
            if showing is not None and (not isinstance(showing, dict) or str(showing.get("at") or "") < cutoff):
                screen["showing"] = None
                screen["version"] = int(screen.get("version", 0)) + 1
                self._acks.pop(screen["id"], None)
                self._purges = self._merge(self._purges, {screen["id"]: {"version": screen["version"], "showing": None}})
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
                        "showing": showing.get("title") or None, "since": showing.get("at"),
                        "pending": self._pending(screen)})
        return out

    # ---- what a screen shows ---------------------------------------------------------------
    def poll(self, screen_id: str, screen_key: str) -> dict[str, Any] | None:
        """What the screen should show now, and its version, for the device holding its key.
        The screen is seen. A screen waiting for approval is never given anything to show, and
        one whose request ran out is gone (None)."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                return None
            self._holder(screen, screen_key)
            if self._expire_locked() or self.unsaved:
                self._settle_expiry()
            if screen_id not in self._data["screens"]:
                return None
            self._touch(screen_id)
            pending = self._pending(screen)
            last = None if pending else next((d for d in reversed(self._data["done"]) if d.get("screen_id") == screen_id), None)
            out = {"id": screen_id, "name": screen["name"], "version": screen.get("version", 0),
                   "showing": None if pending else screen.get("showing"), "pending": pending, "now": _now_iso(),
                   "last_done": {"title": last.get("title"), "at": last.get("at")} if last else None}
            if pending:
                out["code_expires_in"] = max(0, math.ceil(float(screen["pairing"]["until"]) - self.clock()))
            return out

    def show(self, screen_id: str, showing: dict[str, Any] | None, *, by: str = "clive") -> dict[str, Any]:
        """Put a view on a screen (or clear it). Refused for a screen still waiting for approval
        (round 8, B-02). Replacing or clearing what was up is a deletion, journaled first
        (B-03)."""
        if showing is not None and len(json.dumps(showing, ensure_ascii=False).encode("utf-8")) > MAX_VIEW_BYTES:
            raise DisplayError("That is more than one screen can show.")
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise DisplayError("That screen is not there any more.")
            if self._pending(screen):
                raise NotPaired("That screen hasn't been approved yet. It shows a six-digit code: it is approved only "
                                "with the code the owner reads from it.")
            # A done summary is a kind, a reference and a number, never anyone's words: replacing
            # one deletes nothing private. Anything else that was up is.
            was = screen.get("showing")
            replacing = was is not None and not (isinstance(was, dict) and _done_showing(was) == was)

            def put() -> dict[str, Any]:
                screen["showing"] = None if showing is None else {**showing, "at": _now_iso(), "by": str(by or "")[:80]}
                screen["version"] = int(screen.get("version", 0)) + 1
                return self._public(screen)

            # What was up is owed gone at the new version; what goes up is not copied into the
            # journal (a restart before the record is durable shows nothing, never the old slip).
            owes = (lambda: {screen_id: {"version": int(screen["version"]), "showing": None}}) if replacing else None
            return self._stood(screen_id, lambda: self._commit(put, owes=owes))

    def acknowledge(self, screen_id: str, version: int, *, screen_key: str, start: int, end: int) -> int:
        """The screen holding this key says items [start, end) of what it shows are up on it now
        (round 8, B-04). Pages are told in order: the first starts at item 0 and each new one
        where the last ended; every page but the last is the same size, at most MAX_ACK; each
        new page comes at least ACK_GAP_S after the one before (TooSoon, with how long to wait).
        A page inside what is already acknowledged changes nothing. A first page of another size
        starts the count again (the screen laid its pages out again). Returns how many items,
        from the first, are acknowledged for this version."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise DisplayError("That screen is not there any more.")
            self._holder(screen, screen_key)
            if self._pending(screen):
                raise NotPaired("That screen hasn't been approved yet.")
            showing = screen.get("showing")
            if not showing or int(version) != int(screen.get("version", 0)) or showing.get("done_at"):
                raise DisplayError("The screen changed before that; show the page again.")
            count = _shown_count(showing)
            if count is None:
                raise DisplayError("Nothing on this screen is marked item by item.")
            start, end = int(start), int(end)
            if not (0 <= start < end <= count) or end - start > MAX_ACK:
                raise DisplayError(f"A page is at most {MAX_ACK} items of the {count} on the screen.")
            held = self._acks.get(screen_id)
            state = held if held is not None and held.version == int(version) else _Acks(int(version))
            size = end - start
            fresh = start == 0 and (state.covered == 0 or size != state.size)
            if not fresh:
                if end <= state.covered:
                    return state.covered
                if start != state.covered:
                    raise OutOfOrder(f"Pages are told in order: the next one starts at item {state.covered + 1}.",
                                     covered=state.covered, size=state.size)
                if size != state.size and not (end == count and size < state.size):
                    raise OutOfOrder(f"Every page but the last is {state.size} items.", covered=state.covered, size=state.size)
            now = self.mono()
            wait = ACK_GAP_S - (now - state.last)
            if wait > 0:
                raise TooSoon("That page came too soon after the last one.", retry_after_ms=max(1, math.ceil(wait * 1000)))
            if fresh:
                state.size = size
            state.covered = end
            state.last = now
            self._acks[screen_id] = state
            return state.covered

    def mark_done(self, screen_id: str, version: int, *, screen_key: str, confirmed: bool, by: str = "") -> dict[str, Any]:
        """What the screen is showing was physically done, tapped on the screen holding its key.
        Refused without the tap saying so (`confirmed`, round 8, B-04); if the screen has moved on
        since it was drawn, so a late tap never marks the wrong thing; for an order or a list,
        unless every item was acknowledged on the screen for the version showing now (round 7),
        and until ACK_GAP_S after the last page; and for a slip cut at the screen's limit. The
        slip is then cut down to what the done record needs, journaled first (B-03)."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise DisplayError("That screen is not there any more.")
            self._holder(screen, screen_key)
            if self._pending(screen):
                raise NotPaired("That screen hasn't been approved yet.")
            if confirmed is not True:
                raise NotConfirmed("Nothing was marked: it is marked with the button on the screen.")
            showing = screen.get("showing")
            if not showing or int(version) != int(screen.get("version", 0)):
                raise DisplayError("The screen changed before that tap; nothing was marked.")
            if showing.get("done_at"):
                if screen_id in self._purges or self.unsaved:
                    # Asked again while the first answer was "not saved yet": said done only once it is.
                    self._make_durable()
                return self._public(screen)
            if showing.get("kind") == "order" and (showing.get("order") or {}).get("partial"):
                # A slip cut at views.MAX_ITEMS: the rest of the order was never on any screen.
                raise DisplayError("This order has more items than a screen shows, so it cannot be marked packed here.")
            count = _shown_count(showing)
            if count:
                state = self._acks.get(screen_id)
                if state is None or state.version != int(version) or state.covered < count:
                    what = "item on the order" if showing.get("kind") == "order" else "line of the list"
                    raise NotSeen(f"Not every {what} has been on the screen yet, so nothing was marked.")
                wait = ACK_GAP_S - (self.mono() - state.last)
                if wait > 0:
                    raise TooSoon("That came too soon after the last page.", retry_after_ms=max(1, math.ceil(wait * 1000)))
            when = _now_iso()

            def done() -> dict[str, Any]:
                summary = done_summary(showing)
                screen["showing"] = {**summary, "at": showing.get("at"), "by": showing.get("by"), "done_at": when}
                screen["version"] = int(screen.get("version", 0)) + 1
                self._data["done"].append(self._done_row({**summary, "at": when, "screen": screen["name"],
                                                          "screen_id": screen_id, "by": by}))
                self._data["done"] = self._data["done"][-MAX_DONE:]
                return self._public(screen)

            def owed() -> dict[str, dict[str, Any]]:
                return {screen_id: {"version": int(screen["version"]), "showing": screen["showing"], "done": [self._data["done"][-1]]}}

            return self._stood(screen_id, lambda: self._commit(done, owes=owed))

    def _stood(self, screen_id: str, commit: Callable[[], Any]) -> Any:
        """Run a commit that moves a screen past what it showed. Its acknowledgements go once the
        change stands (made, or made and not yet durable); a change refused outright leaves them
        as they were, for the version still showing."""
        try:
            out = commit()
        except NotDurable:
            self._acks.pop(screen_id, None)
            raise
        self._acks.pop(screen_id, None)
        return out

    def done(self, *, ref: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        rows = [d for d in self._data["done"] if ref is None or d.get("ref") == ref]
        return list(reversed(rows[-limit:]))


_STORE: DisplayStore | None = None


def install(path: Path, *, clock=time.time, mono=time.monotonic) -> DisplayStore:
    """The record, read and swept at once: a start after a long stop does not keep a slip up, or
    a done row, a moment past its time."""
    global _STORE
    _STORE = DisplayStore(path, clock=clock, mono=mono)
    _STORE.sweep()
    return _STORE


def store() -> DisplayStore:
    if _STORE is None:
        from config.settings import get_settings

        return install(get_settings().objectives_dir / "displays.json")
    return _STORE
