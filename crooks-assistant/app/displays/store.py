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
kept. The key travels as a cookie the page's own script cannot read (round 9, B2-01,
app/routes/displays.py); how it travels is the routes' business, and this store sees only the
key. A new name is not a screen yet: it is waiting for approval, and the device shows a
six-digit code (only its hash is kept here, for PAIR_CODE_S). The owner reads the code off the
device he means and tells CLIVE, which approves it (`approve`, the screen_pair tool). Until then
nothing is ever put on it. PAIR_TRIES wrong codes cancel the request, and so does the code
running out; either frees the name, and neither screen ever showed anything. So the name is
bound to the physical device the owner read the code from, not to whichever admitted device
asked first. A screen written down before approval existed counts as approved.

An approved name is never handed to another device — not when the screen is quiet, not after a
restart, not when there are many screens (at MAX_SCREENS a new name is refused; nothing is
removed to make room, round 8, NEW-B-CAP). The device holding the key may name it again (and
gets a new key, and stays approved) — which is also how a screen paired before the key became a
cookie moves over, once, with the key it kept (round 9, B2-01). Otherwise the owner removes the
old screen first, explicitly (`forget`), which clears whatever it was showing and its key.

What "done" rests on (rounds 7 to 9, B-04). A screen's "Mark packed" is that screen's own word
and nothing more: the server cannot tell a packer's tap, or a page drawn on a screen, from
anything else the device holding the key sends. What the server does hold is its own plan of a
pane's pages (`_Acks`). The first page a screen acknowledges for a pane sets the plan's page
size, at most MAX_ACK; from then the server issues the plan — every page that size but the
last, each starting where the one before ended — and takes only the plan's next page, at least
ACK_GAP_S after the one before (a first page of another size is a new plan, counted from
nothing: the screen laid its pages out again). An order or a list is marked done from its screen
only once every page of the plan has been acknowledged for the version showing now, at least
ACK_GAP_S after the last, and only when the page says its button was tapped (`confirmed`). That
makes a screen's "done" slow to fake and impossible to hurry, not proven, and the done record
says so: each row keeps how it was marked (`how`) — "screen", the screen's own button and so its
word, or "remote", the owner ticking every item and marking it from one of his own devices
(below) — and CLIVE says which (app/tools/display_tools.py). A screen is one of the owner's
devices by its login, so it can reach the remote's routes too (its page ticks items through
them); a done marked there from a device that is a screen — one carrying a screen's key, or
asking from the tailnet address a screen's key-holder asks from (`screen_device`) — is
"screen_remote", a screen's word, never "remote" (round 11, B-04). Whether a screen's word is
to count as packed is the owner's ruling, not this code's. A slip cut at views.MAX_ITEMS is
never marked done here. Acknowledgements are held in memory: after a restart the screen shows
its pages again before it can say done.

What is kept, and for how long (rounds 6 to 9, B-03 and B-NEW-DONE-LOSS). An order's slip
carries the customer's name, address, phone and note, and the moment it is marked done the slip
is cut down to what the done record needs — a kind, a reference and a title that cannot be
anyone's words ("Order #2048", "Objective", "List"). Anything left up longer than SHOWING_KEEP_S
is taken down by itself. Done rows are kept DONE_KEEP_S and MAX_DONE at most, every field
bounded, and nothing else ever removes one. One view is at most views.MAX_VIEW_BYTES and the
whole record at most MAX_FILE_BYTES, which holds every screen showing two of the largest views
beside a full done record; a change that would take the record past it is refused (Full) with
nothing changed, and nothing is dropped to make room.

Writes are atomic and durable (the temporary file and then the folder are flushed). A deletion —
a slip cut down when it is marked done, a slip replaced or cleared, a screen removed — is written
first to a small purge journal beside the record (displays.purge.json), flushed with its folder,
and only then to the record. If the journal is durable and the record then cannot be made so, the
deletion stands in memory, the journal keeps it across a restart (it is applied before anything
else when the record is next read) and the caller is told it is not saved yet (NotDurable), never
that it is done. If the journal's folder could not be flushed either, nothing on disk is known to
hold the deletion, so it does not stand: the record in memory is put back as it was and the caller
is told nothing was changed (NotSaved, round 9, B-03). What comes down by its time — a slip past
SHOWING_KEEP_S, a request for approval that ran out — stands whatever the disk says: it comes
down in memory at once, and again by itself at the next start. The journal goes once a write of
the record is durable.

Two things at once (round 9). A screen shows up to MAX_PANES views side by side — two columns on
a landscape screen, one above the other on a portrait one (web/display.js). The first is kept as
`showing`, as it always was, and the second as `beside`; there is never a second without a
first, and a record written before panes existed is read as a screen with one. Each pane is its
own thing: it carries `v`, the screen's version when it was put up or marked done, and every
page acknowledgement, "done", tick and page turn names the pane and that `v`, so a change to one
pane never makes the other's acknowledgements stale. Everything above holds for each pane: it
comes down by itself after SHOWING_KEEP_S, it is cut to its done summary when marked done, and
taking it down, or putting something in its place, is a deletion journaled first.

The owner's remote (round 9, app/routes/displays.py and web/remote.js). The owner's own app can
be the remote for a screen: tick each item as it goes in the box (the screen shows the tick at
once), turn its pages, take a pane off, turn the screen off, and mark an order packed or a list
done. Every one of them names what it was made for — the pane and its version, or for the whole
screen the screen's version — so a tap made on an older view changes nothing that went up since
(round 9, B-REMOTE-OFF). Ticks are the owner's explicit word from his own device, item by item,
so "done" from the remote needs every item to send ticked, for the pane's current version, and
no page acknowledgements; the screen's own button keeps its rule above. A tick is an item's
place in the view and nothing else, kept in the pane (`ticked`), so it goes when the pane goes
and expires with it; so does the page the remote turned to (`page`).

A video (YouTube, app/clients/youtube.py and web/display.js). A pane can play a video the owner
asked for, kept as its id, title and channel and nothing else. What he asks of it — play, pause,
mute, a volume, a skip, a jump — is kept in the pane as `player`: every command counted, skips
added up and the last jump noted, so the screen applies each command exactly once however many
arrive between two of its asks. How it is actually playing is the screen's own word, told at
most every PLAYING_GAP_S and held in memory only (`report_playing`), for the remote and for
CLIVE. A video is never marked done, ticked or paged: it is taken off like anything else.

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

from app.displays.views import MAX_ITEMS, MAX_LINES, MAX_VIEW_BYTES

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
# The whole record, written down (round 9, B-NEW-DONE-LOSS). Every one of MAX_SCREENS screens
# showing MAX_PANES of the largest views a screen takes (views.MAX_VIEW_BYTES each, a little more
# once indented on disk), every item ticked, beside a full done record, comes to about 3.1 MB
# (tests/test_screens_r10.py builds it), so this is reached only if something above is broken.
# A change that would take the record past it is refused, with nothing changed; nothing is ever
# dropped to make it fit. The purge journal is held to the same bound.
MAX_FILE_BYTES = 4_000_000
# What a screen shows at once (round 9), and where each pane is kept in the record: the first
# where a screen has always kept what it shows, so a record from before panes reads as one.
MAX_PANES = 2
PANES = ("showing", "beside")
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


def how_marked(row: dict[str, Any]) -> str:
    """How a done row was marked, in words CLIVE can say as they are (round 9, B-04): the
    screen's own button is that screen's word, not a check; the remote is the owner marking it
    from one of his own devices that is not a screen, once every item was ticked (a packing
    tablet ticks items too, so where each tick was made is not said); and the remote's controls
    used from a device that is itself one of the screens are that screen's word as well
    (round 11, B-04)."""
    did = "packed" if row.get("kind") == "order" else "done"
    where = str(row.get("screen") or "") or "screen"
    if row.get("how") == "remote":
        return f"marked {did} from the owner's remote for the {where}, with every item ticked"
    if row.get("how") == "screen":
        return f"marked {did} with the {where}'s own button: that screen's word, not a check"
    if row.get("how") == "screen_remote":
        return (f"marked {did} for the {where} with the remote's controls on a device that is itself one of the "
                "screens, not the owner's own remote: a screen's word, not a check")
    return f"marked {did} on the {where}"


def _done_showing(showing: Any) -> dict[str, Any] | None:
    """What a screen may show once its slip is done: the summary, its times and the pane's
    version (a number), nothing else. Anything that is not a done summary is nothing at all
    (used for what the journal restores, so even a journal that was tampered with cannot put a
    customer's details back)."""
    if not isinstance(showing, dict) or not showing.get("done_at"):
        return None
    return {**done_summary(showing), "at": str(showing.get("at") or "")[:40], "by": str(showing.get("by") or "")[:80],
            "done_at": str(showing.get("done_at") or "")[:40], "v": max(-1, min(_whole(showing.get("v"), -1), 2**53))}


def _whole(value: Any, default: int = 0) -> int:
    """A whole number from the record, or `default` for anything that is not one."""
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _pane_v(view: Any) -> int:
    """The screen's version when this pane was put up or marked done; -1 for none."""
    return _whole(view.get("v"), -1) if isinstance(view, dict) else -1


def _is_done(view: Any) -> bool:
    return isinstance(view, dict) and bool(view.get("done_at"))


def _private(view: Any) -> bool:
    """Whether taking this pane down deletes anything private: anything but a done summary,
    which is a kind, a reference and a number, never anyone's words."""
    return view is not None and not (isinstance(view, dict) and _done_showing(view) == view)


def _to_send(item: Any) -> int:
    """How many of one line of a slip still go in the box (as web/display.js toSendOf reads it)."""
    if not isinstance(item, dict):
        return 0
    for key in ("to_send", "quantity"):
        value = item.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, value)
    return 0


def _tickable(view: dict[str, Any]) -> list[int]:
    """What the owner ticks before the remote may mark a pane done: an order's items still to
    send, or every line of a list, by their place in the view (round 9)."""
    if view.get("kind") == "order":
        items = (view.get("order") or {}).get("items") or []
        return [n for n, item in enumerate(items) if _to_send(item) > 0]
    if view.get("kind") == "list":
        return list(range(len((view.get("list") or {}).get("lines") or [])))
    return []


def _ticked(view: dict[str, Any]) -> list[int]:
    """The items the owner has ticked on this pane: only places that can be ticked, whatever the
    record says."""
    raw = view.get("ticked")
    if not isinstance(raw, list):
        return []
    can = set(_tickable(view))
    return sorted({n for n in raw[:500] if isinstance(n, int) and not isinstance(n, bool) and n in can})


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
    """A page acknowledgement that is not the next page of the server's plan: it does not start
    where the last one ended, or is not the plan's size (round 9, B-04: `next_page` is the page
    the plan takes next)."""

    def __init__(self, message: str, *, covered: int, size: int, next_page: tuple[int, int] | None = None) -> None:
        super().__init__(message)
        self.covered = covered
        self.size = size
        self.next_page = next_page


class TooSoon(DisplayError):
    """An acknowledgement, or done, sooner than ACK_GAP_S after the page before it."""

    def __init__(self, message: str, *, retry_after_ms: int) -> None:
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class NoSuchScreen(DisplayError):
    """No screen has that id (any more)."""


class Stale(DisplayError):
    """The pane asked about is not the one showing at that version any more: nothing was done."""


class PanesFull(DisplayError):
    """Something was to go beside what is up, and the screen already shows MAX_PANES things."""


class NotTicked(DisplayError):
    """Done was asked for from the remote before every item to send was ticked."""


class Full(DisplayError):
    """The change would take the record past MAX_FILE_BYTES: refused, with nothing changed and
    nothing dropped to make room (round 9, B-NEW-DONE-LOSS)."""


class NotSaved(DisplayError):
    """The record could not be written; nothing was changed."""


class NotDurable(NotSaved):
    """The change was made and is in the record, but the record could not be made durable yet:
    it is not reported as done. A deletion is kept in the purge journal meanwhile."""


class NotFlushed(OSError):
    """The file was put in place but its folder could not be flushed."""


@dataclass(slots=True)
class _Acks:
    """The server's plan of one pane's pages, for the version it went up at, and how far through
    it the screen has acknowledged (round 9, B-04). The first page sets `size`; from then the
    plan is fixed by the server: page n is items [n * size, min(count, (n + 1) * size)), and the
    only page it takes next is the one starting at `covered`."""

    version: int
    covered: int = 0                  # items [0, covered) acknowledged, in order
    size: int = 0                     # the page size every page but the last must have
    last: float = float("-inf")       # when the last new page was acknowledged (monotonic)

    def next(self, count: int) -> tuple[int, int] | None:
        """The page the plan takes next, or None once every page has been acknowledged (or
        before the first page has set the plan)."""
        if not self.size or self.covered >= count:
            return None
        return self.covered, min(count, self.covered + self.size)

    def issued(self, count: int) -> dict[str, Any]:
        """The plan as the server holds it, said back to the screen with every answer."""
        page = self.next(count)
        return {"size": self.size, "pages": max(1, math.ceil(count / self.size)) if self.size else 0,
                "covered": self.covered, "next": list(page) if page else None}


# What the store sets on a view itself, never taken from what it is given to show (round 9;
# `player`, a video's playing state as the owner last set it).
_STAMPED = frozenset({"at", "by", "v", "done_at", "ticked", "page", "player"})

# A video on a screen (YouTube, web/display.js). What the owner can ask of it, from his remote or
# through CLIVE; `volume` and `jump` take a value, `skip` a number of seconds either way.
VIDEO_ACTIONS = ("play", "pause", "mute", "unmute", "volume", "louder", "quieter", "skip", "jump")
# How far one skip goes, either way, and how far in a jump may land.
MAX_SKIP_S = 3600
MAX_JUMP_S = 12 * 3600
# What a louder or quieter moves the volume by when no step is said.
VOLUME_STEP = 10
# What the screen says of the player it runs: its state, and why it stopped if it did.
PLAYER_STATES = ("unstarted", "cued", "buffering", "playing", "paused", "ended")
PLAYER_ERRORS = frozenset({2, 5, 100, 101, 150, 153})
# A screen tells CLIVE how a video is playing at most this often; anything sooner is dropped.
PLAYING_GAP_S = 0.5

_NOT_SAVED = "That could not be saved just now; nothing was changed. Try again."
_NOT_DURABLE = "That was done, but CLIVE could not make sure it is saved yet. It keeps trying; check again in a moment."
_FULL = ("CLIVE's record of its screens is full, so that was not done and nothing was changed. Take something off a "
         "screen, or remove a screen you no longer use, and try again.")

# How a done row was marked (round 9, B-04): with the screen's own button, which is that screen's
# word; from the owner's remote on one of his devices that is not a screen, every item ticked; or
# (round 11) with the remote's controls on a device that is itself one of the screens, which is
# that screen's word too — a screen never makes a row that says it was the owner's remote.
DONE_HOW = ("screen", "remote", "screen_remote")

# What a screen is given of each thing it shows (round 11, F-A3B-SCREEN-EVIDENCE): what
# app/displays/views.py builds for that kind, and what the store sets on a pane that the page
# reads (web/display.js) — and nothing else, whatever a record read from disk holds. `by` is who
# put the pane up ("clive"), never who marked anything done: that login is in the done record only.
_SCREEN_PANE = ("kind", "ref", "title", "at", "by")
_SCREEN_ORDER = frozenset({"number", "placed_at", "customer", "company", "address", "phone", "items", "note", "tags",
                           "fulfillment", "payment", "shipping_method", "partial", "total_items"})
_SCREEN_ORDER_ITEM = frozenset({"title", "variant", "sku", "quantity", "to_send", "image"})
_SCREEN_OBJECTIVE = frozenset({"deadline", "days_left", "doing", "next", "needs_you", "blocked_by", "items"})
_SCREEN_OBJECTIVE_ITEM = frozenset({"text", "state"})
_SCREEN_VIDEO = frozenset({"id", "channel", "duration_s", "live", "start"})
# A tailnet address as a screen's key-holder asked from it (app/routes/displays.py): at most this long.
MAX_ADDRESS = 64


def _only(value: Any, keys: frozenset[str]) -> dict[str, Any]:
    """The fields of a record named in `keys`, and no others; {} for anything not a record."""
    return {k: v for k, v in value.items() if k in keys} if isinstance(value, dict) else {}


def _rows(value: Any, keys: frozenset[str]) -> list[dict[str, Any]]:
    """A list of records, each cut to `keys`; anything in it that is not a record is dropped."""
    return [_only(row, keys) for row in value if isinstance(row, dict)] if isinstance(value, list) else []


class DisplayStore:
    def __init__(self, path: Path, *, clock=time.time, mono=time.monotonic) -> None:
        self.path = Path(path)
        self.journal_path = self.path.with_name(f"{self.path.stem}.purge.json")
        self.clock = clock
        self.mono = mono
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}
        self._seen_written: dict[str, float] = {}
        # Page acknowledgements, per pane: (screen id, the pane's version) -> how far (round 9).
        self._acks: dict[tuple[str, int], _Acks] = {}
        # How each video is actually playing, as its screen last said: (screen id, the pane's
        # version) -> state, position and when it was said. Held in memory only, like the
        # acknowledgements: nothing about it is worth keeping across a restart.
        self._playing: dict[tuple[str, int], dict[str, Any]] = {}
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
        for screen in data["screens"].values():
            self._migrate(screen)
        if not isinstance(data.get("done"), list):
            data["done"] = []
        # Done rows written before round 7 are cut to the same policy as new ones.
        data["done"] = [self._done_row(row) for row in data["done"] if isinstance(row, dict)]
        self._replay(data)
        return data

    @classmethod
    def _migrate(cls, screen: dict[str, Any]) -> None:
        """A screen written before panes (round 9): what it shows is its one pane, put up at the
        screen's own version, and it has no second. A second with no first becomes the first."""
        version = _whole(screen.get("version"))
        panes = cls._panes(screen)
        for view in panes:
            if isinstance(view, dict) and _pane_v(view) < 0:
                view["v"] = version
        cls._lay(screen, panes)

    @staticmethod
    def _panes(screen: dict[str, Any] | None) -> list[Any]:
        """What a screen shows, pane by pane, first first: none, one or two."""
        if not screen:
            return []
        return [screen.get(key) for key in PANES if screen.get(key) is not None]

    @staticmethod
    def _lay(screen: dict[str, Any], panes: list[Any]) -> None:
        """Lay these panes on the screen, first first; there is never a second without a first."""
        panes = [view for view in panes if view is not None][:MAX_PANES]
        for n, key in enumerate(PANES):
            screen[key] = panes[n] if n < len(panes) else None

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
                if self._panes(screen):
                    self._lay(screen, [])
                    screen["version"] = _whole(screen.get("version")) + 1
                    self._purges[sid] = {"version": screen["version"], "showing": None, "beside": None}
            return
        screens = data["screens"]
        added = False
        for sid, entry in entries.items():
            # Only what a journal entry can say is kept of it: that the screen is gone, or the
            # version it must be at and, pane by pane, the done summary it shows or the version
            # of a pane that was not deleted; and the done rows owed.
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
            owed = [self._owed_pane(entry.get(key), max(want, 0)) for key in PANES]
            self._purges[sid] = {"version": max(want, 0), "showing": owed[0], "beside": owed[1], **({"done": rows} if rows else {})}
            if screen is None or _whole(screen.get("version")) >= want:
                continue
            # Round 9: a pane the deletion did not touch stays if the record holds it, found by
            # the version it went up at; anything else that was up comes down. Nothing a journal
            # says can put a view up that the record does not already hold, done summaries apart.
            had = [p for p in self._panes(screen) if isinstance(p, dict) and not p.get("done_at")]
            now: list[dict[str, Any]] = []
            for pane in owed:
                if pane is None:
                    continue
                if "keep" in pane:
                    kept = next((p for p in had if _pane_v(p) == pane["keep"]), None)
                    if kept is not None and kept not in now:
                        now.append(kept)
                else:
                    now.append(pane)
            self._lay(screen, now)
            screen["version"] = want
        if added:
            data["done"] = sorted(data["done"], key=lambda d: d.get("at") or "")[-MAX_DONE:]

    @staticmethod
    def _owed_pane(value: Any, version: int) -> dict[str, Any] | None:
        """What a purge journal may say of one pane (round 9): nothing there; a done summary
        (a journal from before panes gave it no version of its own: it is the entry's); or
        {"keep": N}, the pane put up at version N, which was not deleted and may stay if the
        record holds it. Anything else is nothing at all."""
        if isinstance(value, dict) and set(value) == {"keep"}:
            kept = _whole(value.get("keep"), -1)
            return {"keep": kept} if kept >= 0 else None
        done = _done_showing(value)
        if done is not None and done["v"] < 0:
            done["v"] = version
        return done

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
                # The later entry says what every pane must be (it was taken after the earlier
                # deletion, so it never keeps what that one deleted).
                merged = {"version": entry["version"], "showing": entry.get("showing"), "beside": entry.get("beside")}
            if done:
                merged["done"] = done
            out[sid] = merged
        return out

    @staticmethod
    def _done_row(row: dict[str, Any]) -> dict[str, Any]:
        """A done row as it is kept. `how` it was marked is "screen" or "remote" (round 9, B-04),
        or None for a row written before that was kept, which may have been either."""
        how = row.get("how")
        return {**done_summary(row), "at": str(row.get("at") or "")[:40], "screen": str(row.get("screen") or "")[:MAX_NAME],
                "screen_id": str(row.get("screen_id") or "")[:20], "by": (str(row.get("by") or "")[:80] or None),
                "how": how if how in DONE_HOW else None}

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
        folder are flushed; False when it is in place but the folder could not be flushed, so it
        is not durable and a new deletion may not rest on it (_commit, round 9, B-03). Raises if
        it could not be put in place: then nothing on disk changed."""
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

    @staticmethod
    def _text(data: dict[str, Any]) -> str:
        """The record as it is written down."""
        return json.dumps(data, indent=2, ensure_ascii=False)

    def _write(self, text: str | None = None) -> None:
        """Write the record: a 0600 temporary file, flushed, renamed into place, and the folder
        flushed after. Raises OSError if the record could not be put in place (nothing changed
        on disk). Raises NotFlushed if it was put in place but the folder could not be flushed:
        the new record IS the file, but may not survive a power cut, so that is kept as
        `unsaved` (said by sweep() on /health and written again on the next pass), and what it
        deleted stays in the purge journal. Only a durable write empties the journal.

        Its size is not judged here (round 9, B-NEW-DONE-LOSS): every change that could make the
        record larger is refused before it is written if it would take it past MAX_FILE_BYTES
        (_commit), and nothing here drops a done row, or anything else, to make it fit. What is
        written without that check only ever makes the record smaller or keeps it the same — a
        deletion, a slip past its time, a "last seen" — and must never be refused for size."""
        folder = self._folder()
        if text is None:
            text = self._text(self._data)
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

        A change that would take the record past MAX_FILE_BYTES is refused before anything is
        written (Full), unless it makes the record no larger (round 9, B-NEW-DONE-LOSS).

        A deletion (`owes` says what it deleted) is written to the purge journal first, and
        once the journal is durable the deletion is never put back: if the record then cannot
        be made durable the caller is told NotDurable — not saved yet — and never that it is
        done (round 8, B-03). The same holds for any change written while an earlier deletion is
        still owed, since that write carries it. A journal put in place whose folder could not
        be flushed is not durable: unless the record itself then is, the deletion does not
        stand — it is put back, the journal is put back as it was, and the caller is told
        nothing was changed (round 9, B-03)."""
        before = copy.deepcopy(self._data)
        carries = bool(self._purges)
        result = change()
        text = self._text(self._data)
        size = len(text.encode("utf-8"))
        if size > MAX_FILE_BYTES and size > len(self._text(before).encode("utf-8")):
            self._data = before
            log.error("screens record would be %d bytes, over %d; the change was refused", size, MAX_FILE_BYTES)
            raise Full(_FULL)
        journaled = True       # a deletion's obligation is durably on disk (or there is none)
        if owes is not None:
            owed = self._merge(self._purges, owes())
            try:
                journaled = self._journal(owed)
            except OSError as exc:
                self._data = before
                log.error("screens purge journal not written; the change was not made: %s", exc)
                raise NotSaved(_NOT_SAVED) from exc
            if journaled:
                self._purges = owed
        try:
            self._write(text)
        except OSError as exc:
            if not journaled:
                # Neither the journal nor the record is known to be on disk: after a power cut the
                # old record could come back with nothing owed against it, so the deletion is not
                # made at all, and is not said to be.
                self._data = before
                self._restore_journal()
                log.error("screens deletion not made: neither its journal nor the record is durable: %s", exc)
                raise NotSaved(_NOT_SAVED) from exc
            if isinstance(exc, NotFlushed):
                if owes is not None or carries:
                    raise NotDurable(_NOT_DURABLE) from exc
                # Not a deletion: the change is the file, and that it may not survive a power cut
                # is said by sweep() and put right on the next pass.
                return result
            if owes is not None:
                self.unsaved = True
                log.error("screens record not written; the deletion stands and is owed: %s", exc)
                raise NotDurable(_NOT_DURABLE) from exc
            self._data = before
            log.error("screens record not written; the change was not made: %s", exc)
            raise NotSaved(_NOT_SAVED) from exc
        return result

    def _restore_journal(self) -> None:
        """The purge journal put back to what is still owed (nothing at all: no journal), after
        a deletion that did not stand. At best effort: a journal that still names the refused
        deletion only ever takes a slip down, never puts one up (_replay)."""
        try:
            if self._purges:
                self._put(self.journal_path, json.dumps({"screens": self._purges}, ensure_ascii=False))
            else:
                self.journal_path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("screens purge journal not put back after a deletion that did not stand: %s", exc)

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

    def register(self, name: str, *, screen_key: str = "", old_key: str = "", device: str = "") -> dict[str, Any]:
        """The owner's device names itself a screen, and is given that screen's key and, for a
        new name, the code the owner approves it by (in the answer, once). A new screen waits for
        approval (`approve`) and shows nothing until then. A name already in use is refused
        unless the device holds that screen's key (then it gets a new key, and a waiting screen a
        new code; an approved one stays approved): it never passes to another device by name
        (round 7, B-02). To give the name to a new device, the owner removes the old screen
        first (`forget`). At MAX_SCREENS a new name is refused; nothing is removed to make room
        (round 8, NEW-B-CAP).

        `screen_key` is the key the device holds now; `old_key` is one a page kept from before
        the key moved into a cookie (round 9, B2-01), offered only when naming itself, and
        treated exactly as holding the key: the holder naming itself again. Either way the key it
        held is spent: the screen keeps only the new key's hash, so the old key opens nothing
        from then on. `device` is the tailnet address the device asks from, when the request came
        through Tailscale (screen_device, round 11, B-04)."""
        shown = clean_name(name)
        key = name_key(shown)
        if not key:
            raise DisplayError("Give the screen a name, like office screen.")
        secret = secrets.token_urlsafe(24)
        code = f"{secrets.randbelow(1_000_000):06d}"
        device = str(device or "")[:MAX_ADDRESS]
        with self._lock:
            if self._expire_locked() or self.unsaved:
                # A request that ran out frees its name (and its place) before either is asked for.
                self._settle_expiry()
            for screen in self._data["screens"].values():
                if screen.get("key") != key:
                    continue
                if not (self._holds(screen, screen_key) or self._holds(screen, old_key)):
                    if self._pending(screen):
                        raise NameTaken(f"A screen called {screen['name']} is waiting to be approved. If it is not this one, "
                                        "remove it and name this one: it has never shown anything.")
                    raise NameTaken(f"There is already a screen called {screen['name']}. If this is that screen and "
                                    "it has lost its key, remove the old one first: that clears what it was showing.")

                if self._pending(screen):
                    def renew(screen=screen) -> dict[str, Any]:
                        screen["secret"] = _key_hash(secret)
                        screen["pairing"] = self._pairing(code)
                        if device:
                            screen["asked_from"] = device
                        return self._answer(screen, secret, code)

                    out = self._keyed(renew)
                else:
                    def rotate(screen=screen) -> dict[str, Any]:
                        screen["secret"] = _key_hash(secret)
                        if device:
                            screen["asked_from"] = device
                        return self._answer(screen, secret, None)

                    out = self._keyed(rotate)
                self._touch(screen["id"])
                return out

            if len(self._data["screens"]) >= MAX_SCREENS:
                raise TooMany(f"CLIVE already has {MAX_SCREENS} screens, the most it keeps. Remove one you no longer use "
                              "first: type its name here and tap Remove that screen.")

            def create() -> dict[str, Any]:
                ident = "scr_" + secrets.token_hex(6)
                screen = {"id": ident, "name": shown, "key": key, "secret": _key_hash(secret), "created_at": _now_iso(),
                          "last_seen": _now_iso(), "version": 0, "showing": None, "beside": None, "paired": False,
                          "pairing": self._pairing(code)}
                if device:
                    screen["asked_from"] = device
                self._data["screens"][ident] = screen
                return self._answer(screen, secret, code)

            out = self._keyed(create)
            self._touch(out["id"])
            return out

    def _keyed(self, change: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """A change that hands a device its key — a new screen, a new code, a new key for the
        screen it holds — written as every change is (_commit). It deletes nothing, so _commit
        says NotDurable of it only when the record holding it was put in place but its folder
        could not be flushed while an earlier deletion is still owed: the change stands, in
        memory and in the file on disk, and so the device is handed its key (round 11, B2-01).
        Refusing it then would leave the screen with the hash of a key no device holds: the old
        key no longer its, and the new one never given. A change not made at all (NotSaved)
        hands nothing, and the key the device held still works."""
        made: dict[str, Any] = {}

        def run() -> dict[str, Any]:
            made["answer"] = change()
            return made["answer"]

        try:
            return self._commit(run)
        except NotDurable:
            log.error("a screen was handed its key; the record holding it is in place but not yet durable")
            return made["answer"]

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
        return {k: v for k, v in screen.items() if k not in ("secret", "pairing", "asked_from")}

    def screen_device(self, screen_key: str, device: str) -> str | None:
        """Whether a request to one of the owner's routes comes from one of the screens, and
        which (round 11, B-04). A screen is one of the owner's devices by its Tailscale login,
        so it is let into his routes like any other — its own page ticks items and turns pages
        through the remote's routes (web/display.js) — and from there it could also mark a pane
        done as the remote does. What it says there is still a screen's word, never the owner's
        own remote, so the done row must say so (done_from_remote). A request is a screen's when
        it carries a key some screen holds (its cookie, sent by its browser on every /displays
        route), or when it comes from the tailnet address a screen's key-holder asks from — which
        a page leaving its cookie out cannot change. The screen's id, or None for any other of
        the owner's devices."""
        device = str(device or "")[:MAX_ADDRESS]
        with self._lock:
            for screen in self._data["screens"].values():
                if self._holds(screen, screen_key) or (device and screen.get("asked_from") == device):
                    return str(screen["id"])
        return None

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

    def _touch(self, screen_id: str, *, device: str = "") -> None:
        """Seen now. "Last seen" is written down now and then, and a failure to write it down
        costs nothing but its accuracy. `device`, the tailnet address the screen's key-holder
        asked from (round 11, B-04), is written down at once when it is new, so that it is known
        across a restart (screen_device)."""
        now = self.clock()
        self._seen[screen_id] = now
        screen = self._data["screens"].get(screen_id)
        device = str(device or "")[:MAX_ADDRESS]
        moved = screen is not None and bool(device) and screen.get("asked_from") != device
        if moved:
            screen["asked_from"] = device
        if screen is not None and (moved or now - self._seen_written.get(screen_id, 0.0) >= SEEN_WRITE_S):
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
                self._prune_acks(screen["id"])
                self._purges = self._merge(self._purges, {screen["id"]: {"forget": True}})
                changed = True
                continue
            # Each pane by its own time (round 9): the one left, if any, fills the screen.
            panes = self._panes(screen)
            kept = [p for p in panes if isinstance(p, dict) and str(p.get("at") or "") >= cutoff]
            if len(kept) != len(panes):
                self._lay(screen, kept)
                screen["version"] = _whole(screen.get("version")) + 1
                self._prune_acks(screen["id"])
                self._purges = self._merge(self._purges, {screen["id"]: self._owed(screen)})
                changed = True
        kept = [d for d in self._data["done"] if isinstance(d, dict) and str(d.get("at") or "") >= done_cutoff]
        if len(kept) != len(self._data["done"]):
            self._data["done"] = kept
            changed = True
        return changed

    def _sweep_locked(self) -> None:
        """What is past its time comes down before anything is done to a screen."""
        if self._expire_locked() or self.unsaved:
            self._settle_expiry()

    def screens(self) -> list[dict[str, Any]]:
        with self._lock:
            self._sweep_locked()
        out = []
        for screen in sorted(self._data["screens"].values(), key=lambda s: s.get("name", "")):
            panes = [p for p in self._panes(screen) if isinstance(p, dict)]
            showing = panes[0] if panes else {}
            out.append({"id": screen["id"], "name": screen["name"], "online": self.online(screen["id"]),
                        "showing": showing.get("title") or None, "since": showing.get("at"),
                        # Round 9: what is up beside it, if anything.
                        "beside": (panes[1].get("title") or None) if len(panes) > 1 else None,
                        "pending": self._pending(screen)})
        return out

    # ---- what a screen shows ---------------------------------------------------------------
    def poll(self, screen_id: str, screen_key: str, *, device: str = "") -> dict[str, Any] | None:
        """What the screen should show now, and its version, for the device holding its key.
        The screen is seen (and `device`, the tailnet address it asked from, noted: round 11,
        B-04). A screen waiting for approval is never given anything to show, in either pane,
        and one whose request ran out is gone (None).

        This is everything a screen is given from its own record (round 11,
        F-A3B-SCREEN-EVIDENCE): its id, name, version and whether it waits for approval (and
        then how long its code has), the time, the title and time of the last thing marked done
        on it, and each pane as _for_screen cuts it — never another screen's, never a key, a
        hash, an approval code or the login that marked anything done."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                return None
            self._holder(screen, screen_key)
            self._sweep_locked()
            if screen_id not in self._data["screens"]:
                return None
            self._touch(screen_id, device=device)
            pending = self._pending(screen)
            last = None if pending else next((d for d in reversed(self._data["done"]) if d.get("screen_id") == screen_id), None)
            out = {"id": screen_id, "name": screen["name"], "version": _whole(screen.get("version")),
                   "showing": None if pending else self._for_screen(screen.get("showing")),
                   "beside": None if pending else self._for_screen(screen.get("beside")), "pending": pending, "now": _now_iso(),
                   "last_done": {"title": str(last.get("title") or ""), "at": str(last.get("at") or "")} if last else None}
            if pending:
                out["code_expires_in"] = max(0, math.ceil(float(screen["pairing"]["until"]) - self.clock()))
            return out

    @classmethod
    def _for_screen(cls, view: Any) -> dict[str, Any] | None:
        """One pane as its screen is given it (round 11, F-A3B-SCREEN-EVIDENCE): the fields
        views.py builds for its kind and those the store sets that the page reads (_SCREEN_*),
        each nested record cut to its own list, and nothing else whatever the record holds. A
        pane marked done is its done summary, its times, who put it up and its version."""
        if not isinstance(view, dict):
            return None
        if view.get("done_at"):
            return _done_showing(view)
        kind = view.get("kind")
        out: dict[str, Any] = {k: view[k] for k in _SCREEN_PANE if k in view}
        out["v"] = _pane_v(view)
        if kind == "order":
            slip = _only(view.get("order"), _SCREEN_ORDER)
            if "items" in slip:
                slip["items"] = _rows(slip["items"], _SCREEN_ORDER_ITEM)
            out["order"] = slip
        elif kind == "list":
            lines = (view.get("list") or {}).get("lines") if isinstance(view.get("list"), dict) else None
            out["list"] = {"lines": [line for line in lines if isinstance(line, str)] if isinstance(lines, list) else []}
        elif kind == "objective":
            goal = _only(view.get("objective"), _SCREEN_OBJECTIVE)
            if "items" in goal:
                goal["items"] = _rows(goal["items"], _SCREEN_OBJECTIVE_ITEM)
            out["objective"] = goal
        elif kind == "video":
            out["video"] = _only(view.get("video"), _SCREEN_VIDEO)
            if "player" in view:
                out["player"] = cls._player(view)
        if kind in ("order", "list"):
            if "ticked" in view:
                out["ticked"] = _ticked(view)
            if "page" in view:
                out["page"] = max(0, _whole(view.get("page")))
        return out

    def show(self, screen_id: str, showing: dict[str, Any] | None, *, by: str = "clive", beside: bool = False,
             replace: int | None = None, expect: int | None = None) -> dict[str, Any]:
        """Put a view on a screen, or clear it (`showing` None: every pane comes off). Refused for
        a screen still waiting for approval (round 8, B-02).

        Two at once (round 9). With `beside` the view goes next to what is up, and a third is
        refused (PanesFull, naming both, so the owner can say which to replace); with `replace`
        (0 or 1) it goes in place of that pane — and with `expect` too, only while that pane is
        still the one put up at that version (Stale otherwise); with neither it replaces
        everything, as it always has. A done summary is resting and makes way. Taking down
        anything but a done summary is a deletion, journaled first (B-03)."""
        if showing is not None and len(json.dumps(showing, ensure_ascii=False).encode("utf-8")) > MAX_VIEW_BYTES:
            raise DisplayError("That is more than one screen can show.")
        if replace is not None and replace not in range(MAX_PANES):
            raise DisplayError("A screen shows two things at most: say the first or the second.")
        with self._lock:
            self._sweep_locked()
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise NoSuchScreen("That screen is not there any more.")
            if self._pending(screen):
                raise NotPaired("That screen hasn't been approved yet. It shows a six-digit code: it is approved only "
                                "with the code the owner reads from it.")
            panes = self._panes(screen)
            if expect is not None and (replace is None or replace >= len(panes) or _pane_v(panes[replace]) != int(expect)):
                raise Stale("That changed on the screen before this, so nothing was changed.")
            new = object()
            if showing is None:
                after: list[Any] = []
            elif replace is not None and replace < len(panes):
                after = [new if n == replace else p for n, p in enumerate(panes) if n == replace or not _is_done(p)]
            elif beside or replace is not None:
                after = [p for p in panes if not _is_done(p)]
                if len(after) >= MAX_PANES:
                    raise PanesFull(self._full(screen, after))
                after.append(new)
            else:
                after = [new]
            removed = [p for p in panes if not any(p is q for q in after)]

            def put() -> dict[str, Any]:
                version = _whole(screen.get("version")) + 1
                screen["version"] = version
                view = None if showing is None else {
                    **{k: v for k, v in showing.items() if k not in _STAMPED},
                    "at": _now_iso(), "by": str(by or "")[:80], "v": version}
                self._lay(screen, [view if p is new else p for p in after])
                return self._public(screen)

            # What was up is owed gone; what goes up is not copied into the journal, only the
            # version of a pane that stays (a restart before the record is durable shows nothing
            # new, and never the old slip).
            owes = (lambda: {screen_id: self._owed(screen)}) if any(_private(p) for p in removed) else None
            return self._stood(screen_id, lambda: self._commit(put, owes=owes))

    @staticmethod
    def _full(screen: dict[str, Any], live: list[Any]) -> str:
        names = [str(p.get("title") or "something") if isinstance(p, dict) else "something" for p in live]
        return (f"The {screen['name']} already shows two things: first {names[0]}, and second {names[1]}. "
                "Say which one to replace, or take one off first.")

    def take_off(self, screen_id: str, pane: int | None = None, *, expect: int | None = None,
                 screen_version: int | None = None) -> dict[str, Any]:
        """Everything off a screen, back to its clock (`pane` None), or one pane of it, and the
        other then fills the screen (round 9: "turn the screen off", "take that off"). With
        `expect`, only while that pane is still the one put up at that version (Stale
        otherwise). With `screen_version`, everything comes off only while the screen is still
        at that version — the remote's whole-screen off names the view it was tapped on, so a
        tap made for an older view never takes down what went up since (round 9, B-REMOTE-OFF):
        Stale, with nothing taken off; a screen that shows nothing by then is simply off.
        Without it, everything that is up comes off: that is CLIVE's own "turn the screen off",
        the owner's request as he makes it (app/tools/display_tools.py screen_off). Taking a
        view down is a deletion, journaled first (B-03). Asked while there is nothing to take
        down and an earlier deletion on this screen is still owed, that one is made durable or
        refused, so the screen is said to be off only once it is. Returns the screen, how many
        panes came off and what they were (`removed`, their titles)."""
        with self._lock:
            self._sweep_locked()
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise NoSuchScreen("That screen is not there any more.")
            if self._pending(screen):
                raise NotPaired("That screen hasn't been approved yet: it shows only its code.")
            panes = self._panes(screen)
            if pane is None:
                if screen_version is not None and panes and (
                        isinstance(screen_version, bool) or _whole(screen.get("version")) != _whole(screen_version, -2)):
                    raise Stale("The screen changed before this, so nothing was taken off.")
                gone = list(range(len(panes)))
            elif isinstance(pane, int) and 0 <= pane < len(panes):
                if expect is not None and _pane_v(panes[pane]) != int(expect):
                    raise Stale("That changed on the screen before this, so nothing was taken off.")
                gone = [pane]
            elif expect is not None:
                raise Stale("That changed on the screen before this, so nothing was taken off.")
            elif panes:
                raise DisplayError(f"The {screen['name']} shows only one thing.")
            else:
                gone = []
            if not gone:
                if screen_id in self._purges:
                    self._make_durable()
                return {**self._public(screen), "taken_off": 0, "removed": []}
            removed = [panes[n] for n in gone]
            after = [p for n, p in enumerate(panes) if n not in gone]
            titles = [str(p.get("title") or "") if isinstance(p, dict) else "" for p in removed]

            def off() -> dict[str, Any]:
                screen["version"] = _whole(screen.get("version")) + 1
                self._lay(screen, after)
                return {**self._public(screen), "taken_off": len(gone), "removed": titles}

            owes = (lambda: {screen_id: self._owed(screen)}) if any(_private(p) for p in removed) else None
            return self._stood(screen_id, lambda: self._commit(off, owes=owes))

    @classmethod
    def _pane(cls, screen: dict[str, Any], pane: Any) -> dict[str, Any] | None:
        """One pane of a screen by its place (0 the first), or None."""
        panes = cls._panes(screen)
        if isinstance(pane, bool) or not isinstance(pane, int) or not 0 <= pane < len(panes):
            return None
        view = panes[pane]
        return view if isinstance(view, dict) else None

    def acknowledge(self, screen_id: str, version: int, *, screen_key: str, start: int, end: int, pane: int = 0) -> int:
        """The screen holding this key says items [start, end) of one pane are up on it now
        (round 8, B-04; round 9: `pane`, and `version` is that pane's own). It is the screen's
        word; what the server decides is the plan it is held to (_Acks, round 9, B-04). The
        first page starts at item 0 and sets the plan's page size, at most MAX_ACK; after that
        only the plan's next page is taken — starting where the last ended, the plan's size, or
        shorter only as the last (OutOfOrder otherwise, naming the page the plan takes next) —
        and each at least ACK_GAP_S after the one before (TooSoon, with how long to wait). A
        page inside what is already acknowledged changes nothing. A first page of another size
        is a new plan, counted from nothing (the screen laid its pages out again). Returns how
        many items, from the first, are acknowledged for this pane's version; `page_plan` says
        the plan itself."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise NoSuchScreen("That screen is not there any more.")
            self._holder(screen, screen_key)
            if self._pending(screen):
                raise NotPaired("That screen hasn't been approved yet.")
            showing = self._pane(screen, pane)
            if not showing or int(version) != _pane_v(showing) or showing.get("done_at"):
                raise DisplayError("The screen changed before that; show the page again.")
            count = _shown_count(showing)
            if count is None:
                raise DisplayError("Nothing on this screen is marked item by item.")
            start, end = int(start), int(end)
            if not (0 <= start < end <= count) or end - start > MAX_ACK:
                raise DisplayError(f"A page is at most {MAX_ACK} items of the {count} on the screen.")
            key = (screen_id, int(version))
            held = self._acks.get(key)
            state = held if held is not None else _Acks(int(version))
            size = end - start
            # A new plan: the first page, or a first page of another size (laid out again).
            fresh = start == 0 and (state.covered == 0 or size != state.size)
            if not fresh:
                if end <= state.covered:
                    return state.covered
                want = state.next(count)
                if (start, end) != want:
                    said = (f"Pages are told in order: the next one starts at item {state.covered + 1}."
                            if start != state.covered else f"Every page but the last is {state.size} items.")
                    raise OutOfOrder(said, covered=state.covered, size=state.size, next_page=want)
            now = self.mono()
            wait = ACK_GAP_S - (now - state.last)
            if wait > 0:
                raise TooSoon("That page came too soon after the last one.", retry_after_ms=max(1, math.ceil(wait * 1000)))
            if fresh:
                state.size = size
            state.covered = end
            state.last = now
            self._acks[key] = state
            return state.covered

    def page_plan(self, screen_id: str, version: int, pane: int = 0) -> dict[str, Any] | None:
        """The server's plan of one pane's pages as it stands (round 9, B-04): its page size, how
        many pages, how far the screen has acknowledged and the page it takes next. None before
        the screen's first page has set it, or for a pane that is not marked item by item."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            showing = self._pane(screen, pane) if screen is not None else None
            if not showing or isinstance(version, bool) or _pane_v(showing) != _whole(version, -2):
                return None
            count = _shown_count(showing)
            state = self._acks.get((screen_id, _pane_v(showing)))
            if not count or state is None or not state.size:
                return None
            return state.issued(count)

    def mark_done(self, screen_id: str, version: int, *, screen_key: str, confirmed: bool, by: str = "", pane: int = 0) -> dict[str, Any]:
        """The screen holding this key says what one pane shows was done — its Mark packed button
        (round 9: `pane`, and `version` is that pane's own). That is the screen's own word, and
        the done row says so (`how` "screen", round 9, B-04): the server cannot tell the tap from
        anything else the key-holder sends, and `confirmed` is only the page saying the button
        was pressed. Refused without it (round 8); if the pane has moved on since it was drawn,
        so a late tap never marks the wrong thing; for an order or a list, unless every page of
        the server's plan was acknowledged for the pane's version (round 7), and until
        ACK_GAP_S after the last page; and for a slip cut at the screen's limit. The slip is then
        cut down to what the done record needs, journaled first (B-03)."""
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise NoSuchScreen("That screen is not there any more.")
            self._holder(screen, screen_key)
            if self._pending(screen):
                raise NotPaired("That screen hasn't been approved yet.")
            if confirmed is not True:
                raise NotConfirmed("Nothing was marked: it is marked with the button on the screen.")
            showing = self._pane(screen, pane)
            if not showing or int(version) != _pane_v(showing):
                raise DisplayError("The screen changed before that tap; nothing was marked.")
            if showing.get("done_at"):
                if screen_id in self._purges or self.unsaved:
                    # Asked again while the first answer was "not saved yet": said done only once it is.
                    self._make_durable()
                return self._public(screen)
            if showing.get("kind") == "video":
                raise DisplayError("A video is not marked done; take it off the screen instead.")
            if showing.get("kind") not in ("order", "list"):
                # The screen's page has no button for anything else (web/display.js): an
                # objective marked done from here could only be a request the page never makes
                # (round 11, B-04). The remote refuses it the same way.
                raise DisplayError("Only an order or a list is marked done.")
            if showing.get("kind") == "order" and (showing.get("order") or {}).get("partial"):
                # A slip cut at views.MAX_ITEMS: the rest of the order was never on any screen.
                raise DisplayError("This order has more items than a screen shows, so it cannot be marked packed here.")
            count = _shown_count(showing)
            if count:
                state = self._acks.get((screen_id, int(version)))
                if state is None or state.version != int(version) or state.covered < count:
                    what = "item on the order" if showing.get("kind") == "order" else "line of the list"
                    raise NotSeen(f"Not every {what} has been on the screen yet, so nothing was marked.")
                wait = ACK_GAP_S - (self.mono() - state.last)
                if wait > 0:
                    raise TooSoon("That came too soon after the last page.", retry_after_ms=max(1, math.ceil(wait * 1000)))
            return self._finish(screen_id, screen, pane, showing, by, how="screen")

    def _finish(self, screen_id: str, screen: dict[str, Any], pane: int, showing: dict[str, Any], by: str, *,
                how: str) -> dict[str, Any]:
        """One pane marked done: its slip cut to the done summary at a new version, and a done row
        written saying how it was marked (DONE_HOW) — the purge journal first (B-03). The other
        pane is not touched."""
        when = _now_iso()

        def done() -> dict[str, Any]:
            summary = done_summary(showing)
            version = _whole(screen.get("version")) + 1
            screen["version"] = version
            panes = self._panes(screen)
            panes[pane] = {**summary, "at": showing.get("at"), "by": showing.get("by"), "done_at": when, "v": version}
            self._lay(screen, panes)
            self._data["done"].append(self._done_row({**summary, "at": when, "screen": screen["name"],
                                                      "screen_id": screen_id, "by": by, "how": how}))
            self._data["done"] = self._data["done"][-MAX_DONE:]
            return self._public(screen)

        def owed() -> dict[str, dict[str, Any]]:
            return {screen_id: {**self._owed(screen), "done": [self._data["done"][-1]]}}

        return self._stood(screen_id, lambda: self._commit(done, owes=owed))

    # ---- the owner's remote (round 9) ------------------------------------------------------
    def _remote_pane(self, screen_id: str, pane: Any, version: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        """The screen and the pane the remote means: approved, and still the pane put up at
        `version`. Anything else is said plainly and nothing is done."""
        screen = self._data["screens"].get(str(screen_id)) if _ID.fullmatch(str(screen_id or "")) else None
        if screen is None:
            raise NoSuchScreen("That screen is not there any more.")
        if self._pending(screen):
            raise NotPaired("That screen hasn't been approved yet: it shows only its code.")
        showing = self._pane(screen, pane)
        if showing is None or isinstance(version, bool) or _pane_v(showing) != _whole(version, -2):
            raise Stale("That changed on the screen before this, so nothing was done.")
        return screen, showing

    def _pages(self, screen_id: str, showing: dict[str, Any]) -> int | None:
        """How many pages the screen lays this pane out in, once it has told any (its first page's
        size, B-04), or None while it has not."""
        state = self._acks.get((screen_id, _pane_v(showing)))
        count = _shown_count(showing) or 0
        if state is None or not state.size or not count:
            return None
        return max(1, math.ceil(count / state.size))

    @staticmethod
    def _remote_state(screen: dict[str, Any], showing: dict[str, Any]) -> dict[str, Any]:
        return {"version": _whole(screen.get("version")), "v": _pane_v(showing), "ticked": _ticked(showing),
                "page": max(0, _whole(showing.get("page")))}

    def tick(self, screen_id: str, pane: int, item: int, packed: bool, version: int) -> dict[str, Any]:
        """The owner ticks one item still to send (a line of a list) on his remote, or unticks
        it. The screen shows the tick on its next ask. A tick is the item's place in the view and
        nothing more, kept in the pane, so it goes when the pane goes."""
        with self._lock:
            self._sweep_locked()
            screen, showing = self._remote_pane(screen_id, pane, version)
            if showing.get("done_at"):
                raise Stale("That is marked done already.")
            if showing.get("kind") not in ("order", "list"):
                raise DisplayError("Nothing on this is ticked off item by item.")
            if isinstance(item, bool) or not isinstance(item, int) or item not in _tickable(showing):
                sent = isinstance(item, int) and not isinstance(item, bool) and 0 <= item < (_shown_count(showing) or 0)
                raise DisplayError("That item was sent already." if sent else "There is no such item.")
            ticked = set(_ticked(showing))
            want = ticked | {item} if packed is True else ticked - {item}
            if want == ticked:
                return self._remote_state(screen, showing)

            def change() -> dict[str, Any]:
                showing["ticked"] = sorted(want)
                screen["version"] = _whole(screen.get("version")) + 1
                return self._remote_state(screen, showing)

            return self._commit(change)

    def turn_page(self, screen_id: str, pane: int, delta: int, version: int) -> dict[str, Any]:
        """The remote turns a pane's page on the screen, one at a time (the screen puts it up and
        acknowledges it as its own button does, B-04). Past the last page is the first again once
        the screen has said how it lays the pane out; before that it stops at the last item."""
        with self._lock:
            self._sweep_locked()
            screen, showing = self._remote_pane(screen_id, pane, version)
            if showing.get("done_at") or showing.get("kind") not in ("order", "list"):
                raise DisplayError("Nothing on this has pages.")
            if delta not in (-1, 1) or isinstance(delta, bool):
                raise DisplayError("Pages turn one at a time.")
            count = _shown_count(showing) or 0
            pages = self._pages(screen_id, showing)
            now = max(0, _whole(showing.get("page")))
            turned = (now + delta) % pages if pages else max(0, min(max(0, count - 1), now + delta))
            if turned == now:
                return self._remote_state(screen, showing)

            def change() -> dict[str, Any]:
                showing["page"] = turned
                screen["version"] = _whole(screen.get("version")) + 1
                return self._remote_state(screen, showing)

            return self._commit(change)

    def done_from_remote(self, screen_id: str, pane: int, version: int, *, by: str = "",
                         from_screen: bool = False) -> dict[str, Any]:
        """The owner marks a pane done from his remote: an order packed, a list done — as the
        screen's own button does it, the same done row (but for `how`, "remote") and the slip
        cut to its summary, journaled first (B-03) — once every item to send (every line of a
        list) is ticked for the pane's current version. The ticks are his own word, item by
        item, from his own devices, so no page acknowledgement is asked for; the screen's button
        keeps its rule. A slip cut at the screen's limit is never marked packed here either.

        `from_screen`: the request came from a device that is itself one of the screens
        (screen_device, round 11, B-04). It is let do this — it is one of the owner's devices —
        but what it says is a screen's word, and the row says so ("screen_remote"): a screen
        never makes a row that says the owner's own remote marked it."""
        with self._lock:
            self._sweep_locked()
            screen, showing = self._remote_pane(screen_id, pane, version)
            if showing.get("done_at"):
                if screen_id in self._purges or self.unsaved:
                    self._make_durable()
                return self._public(screen)
            kind = showing.get("kind")
            if kind not in ("order", "list"):
                raise DisplayError("Only an order or a list is marked done.")
            if kind == "order" and (showing.get("order") or {}).get("partial"):
                raise DisplayError("This order has more items than a screen shows, so it cannot be marked packed here.")
            need = _tickable(showing)
            if not need:
                raise DisplayError("There is nothing on this left to pack." if kind == "order" else "There is nothing on this list.")
            if not set(need) <= set(_ticked(showing)):
                what = "item to send" if kind == "order" else "line"
                raise NotTicked(f"Tick every {what} first; nothing was marked.")
            return self._finish(screen_id, screen, int(pane), showing, by, how="screen_remote" if from_screen else "remote")

    def pane_ref(self, screen_id: str, pane: int, version: int) -> tuple[str, str]:
        """What kind of thing one pane shows, and its reference (an objective's id), so the remote
        can put it up again from CLIVE's own record."""
        with self._lock:
            _screen, showing = self._remote_pane(screen_id, pane, version)
            return str(showing.get("kind") or ""), str(showing.get("ref") or "")

    # ---- a video on a screen ---------------------------------------------------------------
    @staticmethod
    def _player(view: dict[str, Any]) -> dict[str, Any]:
        """A video's playing state as the owner last set it, whatever the record holds: `n`
        counts his commands, so the screen applies each one once; `skip` is every skip added
        up, and `jump` the last jump (where to, its command, and the skips before it), so
        commands that arrive together between two of the screen's asks are all applied."""
        raw = view.get("player") if isinstance(view.get("player"), dict) else {}
        volume = raw.get("volume")
        jump = raw.get("jump") if isinstance(raw.get("jump"), dict) else None
        return {
            "n": max(0, _whole(raw.get("n"))),
            "paused": raw.get("paused") is True,
            "muted": raw.get("muted") is True,
            "volume": max(0, min(100, volume)) if isinstance(volume, int) and not isinstance(volume, bool) else None,
            "skip": max(-(2**40), min(2**40, _whole(raw.get("skip")))),
            "jump": {"n": max(0, _whole(jump.get("n"))), "to": max(0, min(MAX_JUMP_S, _whole(jump.get("to")))),
                     "skip": max(-(2**40), min(2**40, _whole(jump.get("skip"))))} if jump else None,
        }

    def _heard(self, screen_id: str, view: dict[str, Any]) -> dict[str, Any] | None:
        """How the screen last said this video was playing, brought up to now: the position
        moves on by the time since, while it was playing, and never past the end."""
        heard = self._playing.get((screen_id, _pane_v(view)))
        if heard is None:
            return None
        out = {k: v for k, v in heard.items() if k != "mono"}
        age = max(0.0, self.mono() - float(heard["mono"]))
        if heard["state"] == "playing":
            at = float(heard["at"]) + age
            out["at"] = round(min(at, float(heard["duration"])) if heard.get("duration") else at, 1)
        out["age_s"] = round(age, 1)
        return out

    def _video_state(self, screen_id: str, screen: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
        return {"version": _whole(screen.get("version")), "v": _pane_v(view), "player": self._player(view),
                "playing": self._heard(screen_id, view)}

    def player(self, screen_id: str, pane: int, version: int, action: str, value: int | None = None) -> dict[str, Any]:
        """The owner plays, pauses, mutes, sets the volume of, skips through or jumps within the
        video on one pane — from his remote, the screen's own buttons or through CLIVE. It is
        kept in the pane (it goes when the pane goes) and the screen applies it on its next ask.
        Nothing here is anyone's words: a state, a number or two."""
        if action not in VIDEO_ACTIONS:
            raise DisplayError("Say play, pause, mute, unmute, volume, louder, quieter, skip or jump.")
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise DisplayError("That needs a whole number.")
        with self._lock:
            self._sweep_locked()
            screen, showing = self._remote_pane(screen_id, pane, version)
            if showing.get("kind") != "video":
                raise DisplayError("Nothing on this plays.")
            was = self._player(showing)
            now = dict(was)
            heard = self._playing.get((screen_id, _pane_v(showing))) or {}
            if action in ("play", "pause"):
                now["paused"] = action == "pause"
            elif action in ("mute", "unmute"):
                now["muted"] = action == "mute"
            elif action == "volume":
                if value is None or not 0 <= value <= 100:
                    raise DisplayError("The volume is 0 to 100.")
                now["volume"], now["muted"] = value, value == 0 and now["muted"]
            elif action in ("louder", "quieter"):
                step = VOLUME_STEP if value is None else value
                if not 1 <= step <= 100:
                    raise DisplayError("Louder or quieter by 1 to 100.")
                base = now["volume"] if now["volume"] is not None else heard.get("volume")
                base = base if isinstance(base, int) else 100
                now["volume"] = max(0, min(100, base + (step if action == "louder" else -step)))
                now["muted"] = False if action == "louder" else now["muted"]
            elif action == "skip":
                if value is None or value == 0 or abs(value) > MAX_SKIP_S:
                    raise DisplayError(f"Skip by 1 to {MAX_SKIP_S} seconds, forward or back.")
                now["skip"] = was["skip"] + value
            else:
                if value is None or not 0 <= value <= MAX_JUMP_S:
                    raise DisplayError("Jump to a point from the start, in seconds.")
                now["jump"] = {"n": was["n"] + 1, "to": value, "skip": was["skip"]}
            now["n"] = was["n"] + 1

            def change() -> dict[str, Any]:
                showing["player"] = now
                screen["version"] = _whole(screen.get("version")) + 1
                return self._video_state(screen_id, screen, showing)

            return self._commit(change)

    def report_playing(self, screen_id: str, pane: int, version: int, *, screen_key: str, state: str, at: float,
                       duration: float | None, volume: int | None, muted: bool, blocked: bool, error: int | None) -> bool:
        """The screen holding this key says how the video on one pane is actually playing: kept
        in memory for the owner's remote and for CLIVE ("is it still playing?"), never written
        down. At most one every PLAYING_GAP_S; one sooner is dropped (False), not refused."""
        if state not in PLAYER_STATES:
            raise DisplayError("That is not a player's state.")
        if error is not None and error not in PLAYER_ERRORS:
            error = 5
        with self._lock:
            screen = self._data["screens"].get(screen_id)
            if screen is None:
                raise NoSuchScreen("That screen is not there any more.")
            self._holder(screen, screen_key)
            if self._pending(screen):
                raise NotPaired("That screen hasn't been approved yet.")
            showing = self._pane(screen, pane)
            if not showing or showing.get("kind") != "video" or isinstance(version, bool) or _pane_v(showing) != int(version):
                raise Stale("The screen changed before that; nothing was noted.")
            key = (screen_id, _pane_v(showing))
            now = self.mono()
            last = self._playing.get(key)
            if last is not None and now - float(last["mono"]) < PLAYING_GAP_S:
                return False
            self._touch(screen_id)
            self._playing[key] = {
                "state": state,
                "at": round(max(0.0, min(float(at), float(MAX_JUMP_S * 2))), 1),
                "duration": round(max(0.0, min(float(duration), float(MAX_JUMP_S * 2))), 1) if duration else None,
                "volume": max(0, min(100, int(volume))) if isinstance(volume, int) and not isinstance(volume, bool) else None,
                "muted": muted is True, "blocked": blocked is True, "error": error, "mono": now,
            }
            return True

    def playing(self, screen_id: str) -> list[dict[str, Any]]:
        """Each video on a screen, pane by pane: its title, as the owner last set it, and as
        the screen last said it was playing (for CLIVE: "is it still playing?")."""
        with self._lock:
            screen = self._data["screens"].get(str(screen_id)) if _ID.fullmatch(str(screen_id or "")) else None
            if screen is None:
                return []
            out = []
            for n, view in enumerate(self._panes(screen)):
                if isinstance(view, dict) and view.get("kind") == "video" and not view.get("done_at"):
                    out.append({"pane": n, "v": _pane_v(view), "title": str(view.get("title") or "")[:120],
                                "player": self._player(view), "playing": self._heard(str(screen_id), view)})
            return out

    def remote(self, screen_id: str) -> dict[str, Any]:
        """The owner's view of a screen, for his remote: its name, whether it is on, and pane by
        pane what it shows — as much as the remote needs to work it and nothing more. An order's
        items (title, variant, how many, the image) and never who it goes to, where, their phone
        or their note; a done pane is its title alone."""
        with self._lock:
            self._sweep_locked()
            screen = self._data["screens"].get(str(screen_id)) if _ID.fullmatch(str(screen_id or "")) else None
            if screen is None:
                raise NoSuchScreen("That screen is not there any more.")
            if self._pending(screen):
                raise NotPaired("That screen hasn't been approved yet: it shows only its code.")
            panes = [self._remote_view(screen_id, n, view) for n, view in enumerate(self._panes(screen)) if isinstance(view, dict)]
            return {"id": screen_id, "name": screen["name"], "online": self.online(screen_id),
                    "version": _whole(screen.get("version")), "now": _now_iso(), "panes": panes}

    def _remote_view(self, screen_id: str, n: int, view: dict[str, Any]) -> dict[str, Any]:
        kind = str(view.get("kind") or "")
        out: dict[str, Any] = {"pane": n, "v": _pane_v(view), "kind": kind, "title": str(view.get("title") or "")[:120],
                               "at": str(view.get("at") or "")[:40], "done_at": str(view.get("done_at") or "")[:40] or None}
        if view.get("done_at"):
            return out
        ticked = set(_ticked(view))
        if kind == "order":
            slip = view.get("order") if isinstance(view.get("order"), dict) else {}
            items = slip.get("items") if isinstance(slip.get("items"), list) else []
            out["items"] = []
            for i, item in enumerate(items[:MAX_ITEMS]):
                if not isinstance(item, dict):
                    continue
                left = _to_send(item)
                image = item.get("image")
                out["items"].append({
                    "i": i, "title": str(item.get("title") or "")[:120], "variant": str(item.get("variant") or "")[:80],
                    "quantity": left if left > 0 else max(0, _whole(item.get("quantity"))), "sent": left <= 0,
                    "image": image if isinstance(image, str) and image.startswith("https://") and len(image) <= 500 else None,
                    "ticked": i in ticked,
                })
            out["partial"] = bool(slip.get("partial"))
        elif kind == "list":
            lines = (view.get("list") or {}).get("lines") if isinstance(view.get("list"), dict) else []
            out["lines"] = [{"i": i, "text": str(line)[:200], "ticked": i in ticked}
                            for i, line in enumerate((lines if isinstance(lines, list) else [])[:MAX_LINES])]
        elif kind == "objective":
            goal = view.get("objective") if isinstance(view.get("objective"), dict) else {}

            def few(key: str, most: int) -> list[str]:
                value = goal.get(key)
                return [str(x)[:200] for x in value[:most]] if isinstance(value, list) else []

            days = goal.get("days_left")
            out["objective"] = {
                "doing": str(goal.get("doing") or "")[:200] or None,
                "needs_you": (few("needs_you", 4) + [f"Blocked: {x}" for x in few("blocked_by", 4)])[:4],
                "next": few("next", 5),
                "deadline": str(goal.get("deadline") or "")[:40] or None,
                "days_left": days if isinstance(days, int) and not isinstance(days, bool) else None,
            }
        elif kind == "video":
            clip = view.get("video") if isinstance(view.get("video"), dict) else {}
            ident = str(clip.get("id") or "")
            duration = clip.get("duration_s")
            out["video"] = {
                "id": ident if len(ident) == 11 else "",
                "channel": str(clip.get("channel") or "")[:80] or None,
                "duration_s": duration if isinstance(duration, int) and not isinstance(duration, bool) else None,
                "live": clip.get("live") is True,
            }
            out["player"] = self._player(view)
            out["playing"] = self._heard(screen_id, view)
        if kind in ("order", "list"):
            out["page"] = max(0, _whole(view.get("page")))
            out["pages"] = self._pages(screen_id, view)
        return out

    def _owed(self, screen: dict[str, Any]) -> dict[str, Any]:
        """What a deletion owes the purge journal for this screen (B-03), pane by pane (round
        9): a done summary as it is; nothing for no pane; and for a pane still up only the
        version it went up at — never what it shows — so that a restart before the record is
        durable keeps a pane that was not deleted, if the record holds it, and never brings back
        one that was."""
        def one(view: Any) -> dict[str, Any] | None:
            if view is None:
                return None
            if _is_done(view):
                return _done_showing(view)
            kept = _pane_v(view)
            return {"keep": kept} if kept >= 0 else None

        panes = self._panes(screen)
        return {"version": _whole(screen.get("version")),
                "showing": one(panes[0]) if panes else None,
                "beside": one(panes[1]) if len(panes) > 1 else None}

    def _prune_acks(self, screen_id: str) -> None:
        """Acknowledgements for panes a screen no longer shows go (and every one of a screen
        that is gone)."""
        live = {_pane_v(p) for p in self._panes(self._data["screens"].get(screen_id))}
        for key in [k for k in self._acks if k[0] == screen_id and k[1] not in live]:
            del self._acks[key]
        for key in [k for k in self._playing if k[0] == screen_id and k[1] not in live]:
            del self._playing[key]

    def _stood(self, screen_id: str, commit: Callable[[], Any]) -> Any:
        """Run a commit that moves a screen past what it showed. The acknowledgements of what it
        no longer shows go once the change stands (made, or made and not yet durable); a change
        refused outright leaves them as they were, for the panes still showing."""
        try:
            out = commit()
        except NotDurable:
            self._prune_acks(screen_id)
            raise
        self._prune_acks(screen_id)
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
