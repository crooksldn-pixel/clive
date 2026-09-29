"""The timeline: one JSON line per event, from the Mac and from the tablet, into the active
test session's file. Nothing here is on a turn's path: `emit` puts the line on a queue and a
thread writes it. Off — no session active — `emit` is a cached stat and a return.

Every event carries the time, a sequence number, the test session, its source and its kind,
and whatever correlation ids the caller has (session_id, turn_id, tool_call_id, proposal_id,
context_request_id). Never a credential: keys that name one are withheld and strings that
look like one are scrubbed, whatever the caller passed.

And never a customer's contact details, for the same reason and by the same seam. D-15,
measured over all 1,365 events of the 11 September session:

    turn_finished.question   redacted — 8 events carry `[name]`
    turn_finished.answer     redacted — 7 events carry `[name]`
    tts.text                 NOT redacted — raw name and raw email address
    model.answer             NOT redacted — raw email address
    prediction.key           NOT redacted — raw email address

Three real customer email addresses sat in that file, in fields the redactor did not cover,
because redaction was applied at ONE CALL SITE (`app/routes/turn.py::_written`, on the turn
record) and not at the seam. The same sentence was scrubbed where it was written down as an
ANSWER and intact where it was written down as something SPOKEN. `logs/test-sessions/` is
gitignored so nothing reached the repository — but a timeline is exported, read, pasted into
reports and handed to engineering agents, and this pass received three real addresses exactly
that way.

So `scrub` — which every event passes through on its way to the queue, and which is the only
path there is — now redacts by SHAPE as well: email addresses, card numbers, postcodes and
telephone numbers, using the same rule the turn log has always used
(`app/logging/turnlog.py::redact_text`). A new event kind cannot arrive unredacted, because
there is nowhere for it to arrive from that does not go through here.

A name cannot be found by shape. It can be found because we know exactly which names a turn's
tools returned, so `note_names` takes them and every event written afterwards has them
replaced too — one call, at the one place that already computes the set, rather than a rule
per field."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import unicodedata
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any

from app.observability.session import TestSession, TestSessions

log = logging.getLogger("crooks.observe")

MAX_STRING = 6_000
# What may wait for the writer at once: past either, an event is dropped as it arrives.
MAX_PENDING_EVENTS = 5_000
MAX_PENDING_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 6
MAX_LIST = 400
# How many recent correlation ids are kept in memory for `recent()`, and which kinds count as
# one. A tap, a change and a branch move are what somebody is doing when he says something
# went wrong; a render or a scroll is not, and a hundred of them would push the taps out.
RECENT_EVENTS = 64
RECENT_KINDS = ("command", "command_stage", "row_action", "action_", "batch_", "branch_",
                "tablet_navigate", "tablet_action_commit", "tablet_reconcile", "tool_finished")

# Keys whose values are never written, whatever they hold.
WITHHELD_KEYS = frozenset({
    "authorization", "cookie", "cookies", "set-cookie", "x-api-key", "xi-api-key", "api_key", "apikey",
    "token", "access_token", "refresh_token", "id_token", "oauth_token", "client_secret", "secret",
    "password", "nonce", "arm_nonce", "x-crooks-arm", "headers", "raw_headers", "credentials", "credential",
})
# How many of the names this process has been told about are kept: every customer a busy season's
# conversations read, and still bounded, because this is a process-lifetime set. It was 256, fed
# every turn from a conversation's whole unordered `pii_seen`: past 256 which names survived was
# the set's iteration order, and the customer on screen could be one that did not (round 13's
# second independent check). Names are found through a tree of their words, so a string costs
# the same to redact however many are kept (under a millisecond for six thousand characters
# against fifty thousand names); the least recently told go first.
MAX_NAMES = 50_000
# The names to replace wherever they appear in a written event: each as the words it is written
# with, least recently told first, and a tree of their words to find them by, so a string costs
# the same to redact whether ten names are known or fifty thousand. Fed by `note_names` from the
# place that already knows them (a turn's own tool results); empty until something tells it, and
# shape redaction runs whether or not anything has.
_names: OrderedDict[str, tuple[str, ...]] = OrderedDict()
_tree: dict[str, Any] = {}
_END = "\x00end"
_names_lock = threading.Lock()
_NAME_WORD = re.compile(r"\w+")


def _name_words(text: str) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFKC", w).casefold() for w in _NAME_WORD.findall(text))

# Strings shaped like a credential, scrubbed wherever they appear.
_SECRET = re.compile(
    r"(shpat_[A-Za-z0-9]{8,}|shpca_[A-Za-z0-9]{8,}|shpss_[A-Za-z0-9]{8,}|sk-ant-[A-Za-z0-9_\-]{8,}|sk_[A-Za-z0-9]{20,}"
    r"|ya29\.[A-Za-z0-9_\-]{8,}|1//[A-Za-z0-9_\-]{20,}|xoxb-[A-Za-z0-9\-]{8,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_\-]{20,}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
    r"|(?i:bearer)\s+[A-Za-z0-9._\-]{16,})"
)


def scrub(value: Any, depth: int = 0) -> Any:
    """A copy safe to write: withheld keys gone, credential-shaped strings replaced, sizes
    bounded, anything unserialisable rendered as text."""
    if depth > MAX_DEPTH:
        return "[deep]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name.lower().replace("_", "-") in WITHHELD_KEYS or name.lower() in WITHHELD_KEYS:
                out[name[:80]] = "[withheld]"
            else:
                out[name[:80]] = scrub(item, depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)[:MAX_LIST]
        return [scrub(v, depth + 1) for v in items]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    text = value if isinstance(value, str) else str(value)
    # Cut near the length that is kept before redacting: a megabyte of text is not searched for
    # names to be thrown away after. The margin keeps what straddles the final cut out of it.
    text = text[:MAX_STRING + 400]
    text = _SECRET.sub("[secret]", text)
    text = _redact(text)
    return text if len(text) <= MAX_STRING else text[:MAX_STRING] + "…"


def note_names(names: Any) -> None:
    """The customer names this process has been shown, so written events can lose them.

    A name is not a shape, so it cannot be found by pattern; it can be found because the turn
    that is about to be written down knows exactly which names its own tools returned. One call
    from there covers every event of that turn and every event after it — `tts.text`,
    `model.answer`, `prediction.key` and any kind added later — rather than a redaction rule
    per field, which is what left three real addresses in the 11 September file.
    """
    for name in names or ():
        text = str(name or "").strip()
        if len(text) < 3 or not any(ch.isalpha() for ch in text):
            # A postcode's digits, a house number, an order number: not a name, and taken for one
            # they turned the event's own time and ids into "[name]".
            continue
        words = _name_words(text)
        if not words:
            continue
        with _names_lock:
            if text in _names:
                _names.move_to_end(text)
                continue
            _names[text] = words
            node = _tree
            for word in words:
                node = node.setdefault(word, {})
            node.setdefault(_END, set()).add(text)
            while len(_names) > MAX_NAMES:
                _forget_one(*_names.popitem(last=False))


def _forget_one(name: str, words: tuple[str, ...]) -> None:
    path = [_tree]
    for word in words:
        nxt = path[-1].get(word)
        if nxt is None:
            return
        path.append(nxt)
    ends = path[-1].get(_END)
    if ends is not None:
        ends.discard(name)
        if not ends:
            del path[-1][_END]
    for depth in range(len(words), 0, -1):
        if path[depth]:
            break
        del path[depth - 1][words[depth - 1]]


def forget_names() -> None:
    """Empty the name set. For tests, and for a process handed to a different shop."""
    with _names_lock:
        _names.clear()
        _tree.clear()


def _names_out(text: str) -> str:
    """Every name this process has been told, taken out of one string: found by its words, in
    order, whatever their case or width and whatever stands between them — "Mia Kowalski's" and
    "MIA  KOWALSKI" are both her name — the longest where two names start at the same word."""
    found = [(unicodedata.normalize("NFKC", m.group(0)).casefold(), m.start(), m.end()) for m in _NAME_WORD.finditer(text)]
    if not found:
        return text
    spans: list[tuple[int, int]] = []
    with _names_lock:
        i = 0
        while i < len(found):
            node, longest, j = _tree, 0, i
            while j < len(found):
                node = node.get(found[j][0])
                if node is None:
                    break
                j += 1
                if _END in node:
                    longest = j - i
            if longest:
                spans.append((found[i][1], found[i + longest - 1][2]))
                i += longest
            else:
                i += 1
    if not spans:
        return text
    out: list[str] = []
    at = 0
    for start, end in spans:
        out.append(text[at:start])
        out.append("[name]")
        at = end
    out.append(text[at:])
    return "".join(out)


def _redact(text: str) -> str:
    """Contact details out of one string, by shape and by the names we have been told.

    The rule is `app/logging/turnlog.py`'s, which is the one the M13 check is written against —
    "open a real log file and confirm there are none" — so the timeline and the turn log cannot
    disagree about what counts as personal data. Never raises: an event that cannot be redacted
    is not an event that gets written unredacted, it is an event that gets written as nothing.
    """
    if not text:
        return text
    try:
        from app.logging.turnlog import redact_text

        # Shapes first — an address is "[email]" whole, not a name and a domain — then names.
        return _names_out(redact_text(text))
    except Exception:  # noqa: BLE001 — observability never takes a turn down
        # Belt and braces: the one shape that actually leaked, with no import behind it.
        return _EMAIL_FALLBACK.sub("[email]", text)


_EMAIL_FALLBACK = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


# The owner's words, and the answers to them, by the event that carries them: what was heard,
# the model's answer, the question and the answer the turn finished with, and what was spoken
# back. A name he says that no read returns is never known to `note_names`, so nothing can
# redact it from these ("what did Zoe Quill order", answered from nothing, put her name in the
# always-on timeline three times: the round-12 deploy review, R9-D1-D1-01 and S1-NEW-02). In
# the day's automatic session they are written by their shape; a session he started by name —
# his walkthrough — keeps them. A defect he asks to be logged (`owner_feedback`) is kept word for
# word in his walkthrough and, like everything else he says, by its shape in the day's session:
# the recogniser reads his words by pattern, and every pattern that filed a defect also filed, in
# the round-13 second check, a note he was asking for on an order with a customer's name in it.
#
# The round-13 independent check found his words in more places, each written from inside a tool
# or a route before any read had told this timeline a name: a working set's label (the title the
# model gives a listing "in the owner's words", "Cy Cole's orders"), the half that shows it (its
# headline), a query the language refused (its reason quotes what was asked, and `unknown` names
# it), and the line spoken when a change is applied ("Reply sent to David.").
WORDS: dict[str, tuple[str, ...]] = {
    "stt": ("text", "raw_text"),
    "model": ("answer",),
    "turn_finished": ("question", "answer"),
    "tts": ("text",),
    "working_set": ("label",),
    "query_rejected": ("reason", "unknown"),
    "branch_forked": ("headline", "parent_headline"),
    "branch_focused": ("headline",),
    "action_commit": ("spoken",),
    "owner_feedback": ("text",),
    # What the turn began on: an email's subject is its label, and a subject can carry a name.
    "turn_started": ("focus.label",),
    # A refusal a tap or a row met, as the tool gave it: it can quote what was typed or said.
    "command_stage": ("detail",),
    "row_action": ("detail",),
}
# What the tablet sends about itself (POST /telemetry, `tablet_<kind>`) that echoes what the Mac
# drew or what he said: a listing's label (his words), a half's label and the headlines of the
# halves on a switch (a customer's name, a listing), and any question. Only these: the rest of a
# tablet event's `name`, `label` and `detail` are the page's own vocabulary — "same_screen", a
# tab's name — which the report reads (round 13's second and third checks).
TABLET_WORDS: dict[str, tuple[str, ...]] = {
    "tablet_working_set": ("label", "question"),
    "tablet_branch": ("label", "question"),
    "tablet_branch_switch": ("detail", "question"),
}


def _words_for(kind: str) -> tuple[str, ...]:
    if kind in WORDS:
        return WORDS[kind]
    return TABLET_WORDS.get(kind, ("question",)) if kind.startswith("tablet_") else ()


def keeps_words(session: TestSession | None) -> bool:
    """Whether this session keeps the owner's words: one he started by name. The owner can have
    the automatic session keep them too; that is his decision, and this is the line to change."""
    # The same test housekeeping and the day's roll use (session.is_automatic): a session the
    # owner himself named "always-on" is his, and keeps his words like any other he named.
    from app.observability.session import is_automatic

    return session is not None and not is_automatic(session)


def _words_by_shape(event: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """The event with each of these fields written as its length and a digest — the same digest
    for the same words for the life of the process, and nothing of what they were. Only this
    timeline's own file: a recording mirror was handed the fields before this, and keeps or drops
    words by its own rule (app/observability/recorder.py, CROOKS_RECORD_TRANSCRIPTS)."""
    from app.tools.dispatch import _spoken_shape

    def shaped(value: Any) -> Any:
        if isinstance(value, str):
            return _spoken_shape(value) if value else value
        if isinstance(value, (list, tuple)):
            return [shaped(v) for v in value]
        return value

    out = {key: (shaped(value) if key in keys else value) for key, value in event.items()}
    for key in keys:
        # "focus.label": a field inside a field, the rest of it kept.
        outer, _, inner = key.partition(".")
        if inner and isinstance(out.get(outer), dict) and inner in out[outer]:
            out[outer] = {**out[outer], inner: shaped(out[outer][inner])}
    return out


def scrub_text(text: str) -> str:
    """One string made safe to write, by the same rules as every event: credential shapes out,
    then contact details and the customer names this process has been shown."""
    return _redact(_SECRET.sub("[secret]", text or ""))


# Held, shared, by every process with a timeline writer on a session folder, for as long as the
# process lives: the kernel lets go of it when the process ends, however it ends. The command line
# asks for it exclusively to learn whether any writer is still alive when nothing answers on the
# port (round 8, F-10): a backend stops listening before its lifespan closes, and a refused
# connection alone is not proof that nothing is still writing.
WRITER_LOCK = ".timeline-writer.lock"


def writer_alive(root: Path) -> bool | None:
    """Whether any process holds the timeline writer for the session folder `root`: True, False,
    or None when that could not be found out (no flock here, the lock file cannot be opened).
    None is never taken for False by anything that decides a count is final."""
    try:
        import fcntl
    except ImportError:
        return None
    try:
        fd = os.open(Path(root) / WRITER_LOCK, os.O_RDONLY | os.O_CREAT, 0o600)
    except FileNotFoundError:
        return False     # no session folder: no timeline has been written here, nor can be held
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return None
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


_LOCK_HELD, _LOCK_BUSY, _LOCK_FAILED = "held", "busy", "failed"
# How long an event may wait, at most, for the writer lock a command is holding for a moment
# (round 11, O1 F-01): a command holds it exclusively only for the instant of writer_alive's
# look, so the wait is milliseconds in practice, and it can happen only before this process's
# first hold, which is kept for the life of the process. One that is still held after this is
# not waited for again for WRITER_LOCK_BACKOFF_S, so a command stuck with it cannot slow every
# event on a turn's path.
WRITER_LOCK_WAIT_S = 0.25
WRITER_LOCK_POLL_S = 0.005
WRITER_LOCK_BACKOFF_S = 5.0


def _write_all(fd: int, data: bytes) -> tuple[int, OSError | None]:
    """Every byte of `data` onto `fd`, however many writes that takes (round 9,
    F-A3B-SHORT-WRITE: one os.write can take fewer bytes than it is given, and the rest were
    lost while every line was counted written). (bytes written, None), or (bytes written before
    it stopped, why it stopped)."""
    view = memoryview(data)
    done = 0
    while done < len(data):
        try:
            n = os.write(fd, view[done:])
        except OSError as exc:
            return done, exc
        if n <= 0:
            return done, OSError("the file took none of what was left")
        done += n
    return done, None


def _hold_file(fd: int) -> bool:
    """This append's own hold on the timeline file: exclusive, for as long as the fd is open
    (closing it lets go). Another writer on the same file waits for it rather than landing its
    line between this append's part-line and the take-back of it (round 13, O1-01). False when
    it cannot be taken; then nothing is written, as with no hold on the writer lock."""
    try:
        import fcntl
    except ImportError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError as exc:
        log.debug("timeline file could not be held for an append: %s", exc)
        return False
    return True


def _take_back(fd: int, keep_to: int, wrote_to: int) -> bool:
    """The part of a line that did not finish, off again: the file cut back to `keep_to`, the end
    of the last whole line this append wrote, from where this append began (round 13, O1-01). The
    file's size at the time is not used: it is where the file ends, not where this append's own
    bytes end, and a line another writer added after them is theirs, counted written. The append
    holds the file alone (`_hold_file`), so nothing is after `wrote_to` but what it wrote.

    If the file cannot be cut, the part-line is ended, so the next line starts whole. True when
    the file now ends at the end of a line; False when neither worked, and the file ends in a
    part-line anything written next would be glued to (`Timeline._broken`)."""
    if wrote_to <= keep_to:
        return True
    try:
        os.ftruncate(fd, keep_to)
        return True
    except OSError:
        pass
    done, error = _write_all(fd, b"\n")
    return error is None and done == 1


class Timeline:
    # The shared hold on WRITER_LOCK, once taken (an fd kept for the life of the process).
    _writer_lock: int | None = None

    def __init__(self, sessions: TestSessions, *, clock=time.time) -> None:
        self.sessions = sessions
        self.clock = clock
        # A second sink, given every event before this one decides whether it has anywhere to
        # put it. The production experience recorder is installed here (app/observability/
        # recorder.py) so that recording needs nothing from the turn's path: everything the
        # test session already writes reaches the recorder too, minimised on the way in. A
        # mirror never has a mirror of its own.
        self.mirror: Timeline | None = None
        # Bounded where events come in, not only where they go out (the 2026-09-26 deploy
        # review, F-09): a writer that stalls must not let memory grow without end. Past either
        # bound an event is dropped at once and counted.
        self._queue: queue.Queue = queue.Queue(maxsize=MAX_PENDING_EVENTS)
        self._pending_bytes = 0
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # One count of what is not settled yet (the 2026-09-27 deploy review, F-10): an event
        # is pending from the moment it is queued until the writer has put it on disk or
        # counted it dropped, and it moves only under the lock, in the same step as the
        # written and dropped counts. There is no moment, between the queue and the file, when
        # an event is in nobody's count. `_settled` wakes flush when it reaches nothing.
        self._pending = 0
        self._batches = 0
        self._settled = threading.Condition(self._lock)
        self._seq = 0
        self._written = 0
        self._dropped = 0
        self.stop_settled: bool | None = None   # whether the last stop saw every event settle
        # Until when a writer lock found held by a command is not waited for (see _take_writer_lock),
        # and the guard that makes the hold one per process however many threads ask at once.
        self._lock_busy_until = 0.0
        self._lock_guard = threading.Lock()
        self._full: set[Path] = set()
        # Files that end in a part-line that could be neither cut off nor ended: nothing more is
        # written to one, and what would have been is counted dropped (round 13, O1-01).
        self._broken: set[Path] = set()
        # The last few CORRELATION ids to go past, so something being written down now can say
        # what was happening around it without reading the file back. Owner feedback is the
        # caller (app/observability/feedback.py): "log that the split is broken" is worth far
        # more with the ids of the taps and the changes either side of it. Ids, kinds and
        # clocks only — a bounded deque, and appending to one is atomic.
        self._recent: deque[tuple[float, str, str, str]] = deque(maxlen=RECENT_EVENTS)

    # ----------------------------------------------------------------- state

    @property
    def own(self) -> TestSession | None:
        """The TEST session this timeline writes, and only that."""
        return self.sessions.active()

    @property
    def active(self) -> TestSession | None:
        """Whether anything is being written down — this timeline's own test session, or the
        mirror's recording.

        Callers ask this to decide whether to compose an event at all: `/turn`, the ledger
        observer and the read scheduler all guard their emissions with it, so that a process
        with nothing recording does no work per turn beyond one cached boolean. If it answered
        only for the test session, a production recording would receive nothing from any of
        those guarded call sites — which is most of the interesting ones. So it answers for
        either, and `emit` looks up `own` when it comes to deciding where a line goes.
        """
        session = self.sessions.active()
        if session is not None:
            return session
        mirror = self.mirror
        return mirror.active if mirror is not None else None

    @property
    def active_id(self) -> str | None:
        session = self.own
        return session.test_session_id if session is not None else None

    def start(self, name: str) -> TestSession:
        session = self.sessions.start(name)
        self.emit("session_started", name=session.name, started_at=session.started_at)
        self.flush()
        return session

    def stop(self) -> TestSession | None:
        current = self.own
        if current is None:
            return None
        self.emit("session_stopped", name=current.name, duration_s=round(self.clock() - current.started_at, 3))
        # Whether everything reached the file is kept and said, never assumed (the 2026-09-27
        # deploy review, round 6, F-10): `counts` after this reports what is still pending, and a
        # stop that could not settle in time is logged as such.
        self.stop_settled = self.flush() and self.sessions.timeline_path(current) not in self._broken
        if not self.stop_settled:
            log.warning("test session %s stopped with events still being written; its count is not final",
                        current.test_session_id)
        return self.sessions.stop()

    # ------------------------------------------------------------------ emit

    def emit(self, kind: str, *, source: str = "mac", ts: float | None = None, **fields: Any) -> dict[str, Any] | None:
        """One event, if a session is active. Returns what was queued (for tests), else None.
        Never raises: an event that cannot be written is a dropped event, counted."""
        mirror = self.mirror
        if mirror is not None:
            # First, and whatever this timeline does with it: a production recording runs when
            # no test session does, which is the whole point of it.
            mirror.emit(kind, source=source, ts=ts, **fields)
        try:
            # This timeline's OWN session: `active` is true while a recording runs, and a
            # recording's line is the mirror's to write, not this one's.
            if self.own is None:
                return None
            # No event is accepted without this process's hold on the writer lock (round 8,
            # F-10; round 11, O1 F-01 and R9-A3b-F-10). It is taken before anything is pending, and
            # kept for the life of the process, so a command that finds no writer holding the lock
            # knows no process has an event waiting to be written. An event used to be accepted
            # while a command held the lock for its look, to be written once the writer took the
            # hold: the command, letting go and finding no writer, called a count final that the
            # event then landed in. Now the event waits (briefly) for the hold, or is not accepted.
            if not self._take_writer_lock():
                with self._lock:
                    self._dropped += 1
                return None
            # And the session is looked up again now the hold is taken. A command stops a session on
            # disk and looks for a writer only once RECHECK_S has passed, so a look made after the
            # hold began sees that stop: an event taken now is never one for a session a command has
            # already called final.
            session = self.own
            if session is None:
                return None
            now = self.clock()
            with self._lock:
                self._seq += 1
                seq = self._seq
            event: dict[str, Any] = {
                "ts": round(float(ts) if ts is not None else now, 3),
                "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                "seq": seq,
                "test_session_id": session.test_session_id,
                "source": source,
                "kind": str(kind)[:40],
            }
            for key, value in fields.items():
                if value is None or key in event:
                    continue
                event[key] = value
            words = _words_for(str(kind))
            if words and not keeps_words(session):
                event = _words_by_shape(event, words)
            # The envelope — its time, sequence, session and kind — is the timeline's own, and is
            # never redacted: a customer's postcode digits once turned `iso` into "[name]-09-29".
            envelope = {key: event[key] for key in ("ts", "iso", "seq", "test_session_id", "source", "kind")}
            event = {**envelope, **scrub({k: v for k, v in event.items() if k not in envelope})}
            self._note(event)
            line = json.dumps(event, ensure_ascii=False, default=str)
            size = len(line.encode("utf-8"))
            path = self.sessions.timeline_path(session)
            queued = False
            with self._lock:
                if self._pending_bytes + size <= MAX_PENDING_BYTES:
                    try:
                        self._queue.put_nowait((path, line, size))
                        self._pending_bytes += size
                        self._pending += 1
                        queued = True
                    except queue.Full:
                        pass
                if not queued:
                    self._dropped += 1
            self._ensure_writer()
            return event if queued else None
        except Exception as exc:  # noqa: BLE001 — observability never takes a turn down
            with self._lock:
                self._dropped += 1
            log.debug("timeline event dropped: %s", exc)
            return None

    # ------------------------------------------------------------ what just happened

    def _note(self, event: dict[str, Any]) -> None:
        """Keep this event's id, if it has one worth keeping. Ids, kinds and clocks."""
        kind = str(event.get("kind") or "")
        if not any(kind.startswith(prefix) or kind == prefix for prefix in RECENT_KINDS):
            return
        ident = str(event.get("proposal_id") or event.get("batch_id") or event.get("command")
                    or event.get("branch_id") or event.get("action") or event.get("tool")
                    or event.get("nav") or "")
        self._recent.append((float(event.get("ts") or 0.0), kind, ident[:60],
                             str(event.get("turn_id") or "")[:60]))

    def recent(self, *, within_s: float = 90.0, limit: int = 8, now: float | None = None) -> list[dict[str, Any]]:
        """What went past in the last little while: the taps, the changes and the branch moves,
        most recent last. Read by owner feedback, so a defect narrated out loud carries the ids
        of what the owner was doing when he narrated it."""
        at = float(now if now is not None else self.clock())
        rows = [row for row in list(self._recent) if at - row[0] <= within_s]
        return [{"at": round(ts, 3), "kind": kind, "id": ident or None, "turn_id": turn or None}
                for ts, kind, ident, turn in rows[-limit:]]

    # ----------------------------------------------------------------- writer

    def _ensure_writer(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="crooks-timeline", daemon=True)
            self._thread.start()

    def _take_writer_lock(self) -> bool:
        """Whether this process holds the writer lock now, taking it if it does not yet (round 11,
        O1 F-01). A command holding it exclusively — writer_alive's look, an instant — is waited
        for, a few milliseconds at a time, for at most WRITER_LOCK_WAIT_S; a lock still held after
        that, or one that cannot be taken at all, is False, and the caller accepts nothing. Once
        taken the hold is kept, so this is one attribute read on every event after the first."""
        if self._writer_lock is not None:
            return True
        state = self._hold_writer_lock(blocking=False)
        if state != _LOCK_BUSY:
            return state == _LOCK_HELD
        if time.monotonic() < self._lock_busy_until:
            return False      # found held a moment ago and not let go: not waited for again yet
        deadline = time.monotonic() + WRITER_LOCK_WAIT_S
        while time.monotonic() < deadline:
            time.sleep(WRITER_LOCK_POLL_S)
            state = self._hold_writer_lock(blocking=False)
            if state != _LOCK_BUSY:
                return state == _LOCK_HELD
        self._lock_busy_until = time.monotonic() + WRITER_LOCK_BACKOFF_S
        log.warning("timeline: the writer lock stayed held by another process for %.2f s; events are "
                    "not accepted until it is let go", WRITER_LOCK_WAIT_S)
        return False

    def _hold_writer_lock(self, *, blocking: bool) -> str:
        """Take the shared hold on this session folder's WRITER_LOCK, once: _LOCK_HELD, or
        _LOCK_BUSY when a non-blocking try met a command holding it for a moment, or _LOCK_FAILED
        when it could not be taken at all. Never raises, because observability never takes a turn
        down. One hold per process however many threads ask at once."""
        if self._writer_lock is not None:
            return _LOCK_HELD
        with self._lock_guard:
            if self._writer_lock is not None:
                return _LOCK_HELD
            try:
                import fcntl

                root = self.sessions.root
                root.mkdir(parents=True, exist_ok=True)
                fd = os.open(root / WRITER_LOCK, os.O_RDONLY | os.O_CREAT, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH | (0 if blocking else fcntl.LOCK_NB))
                except BaseException:
                    os.close(fd)
                    raise
                self._writer_lock = fd
                return _LOCK_HELD
            except BlockingIOError:
                return _LOCK_BUSY
            except Exception as exc:  # noqa: BLE001 - observability never takes a turn down
                log.debug("timeline writer lock could not be taken: %s", exc)
                return _LOCK_FAILED

    def _run(self) -> None:
        while True:
            batch = [self._queue.get()]
            held = self._hold_writer_lock(blocking=True)
            # Whatever else is waiting goes out in the same write.
            while True:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            by_path: dict[Path, list[str]] = {}
            for path, line, _size in batch:
                by_path.setdefault(path, []).append(line)
            written = dropped = 0
            try:
                if held != _LOCK_HELD:
                    # Never written unprotected (round 9, F-10): with no hold on the writer lock a
                    # command sees no writer here, and may already have called the file's count
                    # final. Counted as dropped, and said.
                    log.error("timeline: %d event(s) not written, the writer lock could not be held", len(batch))
                    dropped = len(batch)
                    by_path = {}
                for target, lines in by_path.items():
                    kept, lost = self._append(target, lines)
                    written += kept
                    dropped += lost
            except Exception:  # noqa: BLE001 — the writer never dies; what it held is dropped
                log.warning("timeline writer failed on a batch", exc_info=True)
                dropped = len(batch) - written
            finally:
                # Settled in one step: the events leave `pending` as they are counted written
                # or dropped, never before.
                with self._lock:
                    self._written += written
                    self._dropped += dropped
                    self._pending_bytes = max(0, self._pending_bytes - sum(size for _p, _l, size in batch))
                    self._pending = max(0, self._pending - len(batch))
                    self._batches += 1
                    if self._pending == 0:
                        self._settled.notify_all()

    def _append(self, path: Path, lines: list[str]) -> tuple[int, int]:
        """Lines onto a timeline, up to MAX_TIMELINE_BYTES a file, as (written, dropped). Past
        that, what follows is counted as dropped and one line says the file is full: test mode
        is always on, and a day's timeline must not be able to fill the disk."""
        from app.observability.session import MAX_TIMELINE_BYTES

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                if path in self._full or path in self._broken:
                    return 0, len(lines)
                if not _hold_file(fd):
                    log.error("timeline: %d event(s) not written, the file could not be held for the append", len(lines))
                    return 0, len(lines)
                # Where this append begins, under its hold: every byte from here to the end is
                # this append's, which is what lets a failed write take back exactly its own.
                start = os.lseek(fd, 0, os.SEEK_END)
                room = MAX_TIMELINE_BYTES - start
                keep: list[bytes] = []
                for line in lines:
                    data = (line + "\n").encode("utf-8")
                    if len(data) > room:
                        break
                    keep.append(data)
                    room -= len(data)
                if keep:
                    done, error = _write_all(fd, b"".join(keep))
                    if error is not None:
                        # Only the lines whose every byte went down are written (round 9,
                        # F-A3B-SHORT-WRITE); the part of one that did not finish is taken back
                        # off, so it is neither counted from the file nor glued to the next.
                        whole = used = 0
                        for data in keep:
                            if used + len(data) > done:
                                break
                            used += len(data)
                            whole += 1
                        if not _take_back(fd, start + used, start + done):
                            # A part-line is at the end and stays: the next line would be glued to
                            # it and counted, so there is no next line in this file.
                            self._broken.add(path)
                            log.error("timeline %s ends in a part-line that could not be taken back; "
                                      "nothing more is written to it", path.name)
                        log.warning("could not write the timeline whole: %s", error)
                        return whole, len(lines) - whole
                if len(keep) < len(lines):
                    # Full: one line says so, and nothing more is written to this file.
                    self._full.add(path)
                    _write_all(fd, (json.dumps({"kind": "timeline_full", "ts": self.clock(),
                                                "max_bytes": MAX_TIMELINE_BYTES}) + "\n").encode("utf-8"))
            finally:
                os.close(fd)
            return len(keep), len(lines) - len(keep)
        except OSError as exc:
            log.warning("could not write the timeline: %s", exc)
            return 0, len(lines)

    def flush(self, timeout_s: float = 2.0) -> bool:
        """Wait, briefly, until nothing is pending: every queued event on disk or counted
        dropped. For stop, and for tests. True when that happened inside the time."""
        deadline = time.monotonic() + timeout_s
        with self._lock:
            while self._pending:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._settled.wait(left)
            return True

    @property
    def counts(self) -> dict[str, Any]:
        """How many events this session actually holds.

        `written` is counted from the FILE, not from a counter in memory. The counters are
        per-process and a restart zeroes them, which is how `make test-session-status`
        reported "events written=0" against a session that already held a thousand — the
        supervisor had restarted the backend mid-session and the timeline kept growing
        underneath it. The file is the session; the counters describe this process's part
        in it, and are reported as such.
        """
        # The session this is about: the one running, or — just after `stop`, which is when
        # the count is most often asked for — the one that has just ended.
        session = self.own or self.sessions.last()
        path = self.sessions.timeline_path(session) if session is not None else None
        # `written` is only what is on disk (the 2026-09-26 deploy review, F-10): an event still
        # waiting may yet be dropped at the file's cap or by a failed write, so it is counted
        # apart, as pending, and the figure is final only when nothing is. The counters are read
        # together under the writer's lock, and on either side of reading the file: `settled`
        # is claimed only when nothing was pending and no batch landed while the file was read,
        # so the file's count is the whole of it (the 2026-09-27 review, F-10 again).
        for _attempt in range(3):
            before = self._snapshot()
            on_disk = count_events(path) if path is not None else 0
            after = self._snapshot()
            if before == after:
                break
        pending, queued, dropped, written, _batches = after
        return {
            "written": on_disk,
            "on_disk": on_disk,
            "pending": pending,
            "queued": queued,
            "settled": pending == 0 and before == after,
            "dropped": dropped,
            "this_process": written,
            "test_session_id": session.test_session_id if session is not None else "",
        }

    def _snapshot(self) -> tuple[int, int, int, int, int]:
        with self._lock:
            return self._pending, self._queue.qsize(), self._dropped, self._written, self._batches


class NullTimeline(Timeline):
    """Nothing active, ever: what a process without a log directory uses."""

    def __init__(self) -> None:  # noqa: D107 — no sessions, no thread
        self._seq = 0
        self._written = 0
        self._dropped = 0
        self.mirror: Timeline | None = None
        self._recent: deque[tuple[float, str, str, str]] = deque(maxlen=RECENT_EVENTS)

    @property
    def own(self) -> TestSession | None:
        return None

    @property
    def active(self) -> TestSession | None:
        mirror = self.mirror
        return mirror.active if mirror is not None else None

    def emit(self, kind: str, **fields: Any) -> dict[str, Any] | None:
        # Silent for itself, and still a carrier: a process with no log directory may still
        # have been told to record.
        if self.mirror is not None:
            self.mirror.emit(kind, **fields)
        return None

    def flush(self, timeout_s: float = 0.0) -> bool:  # noqa: ARG002
        return True

    def recent(self, *, within_s: float = 90.0, limit: int = 8, now: float | None = None) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    @property
    def counts(self) -> dict[str, Any]:
        return {"written": 0, "on_disk": 0, "pending": 0, "queued": 0, "settled": True, "dropped": 0, "this_process": 0,
                "test_session_id": ""}


def stop_is_final(answer: dict[str, Any]) -> bool:
    """Whether a stop's answer (the /test-session/stop route's) makes its count the session's
    total: the stop's own flush settled, the counts read afterwards settled, and nothing was still
    pending (the 2026-09-27 deploy review, round 7, F-10). Anything missing — an older backend's
    answer — is not final. Every owner-facing stop reads this one rule."""
    counts = answer.get("events") if isinstance(answer.get("events"), dict) else {}
    pending = counts.get("pending")
    # Nought as a number, not text or a bool that happens to convert to it (round 8, F-10).
    nothing_pending = isinstance(pending, int) and not isinstance(pending, bool) and pending == 0
    return answer.get("stop_settled") is True and counts.get("settled") is True and nothing_pending


def unsettled_reasons(answer: dict[str, Any]) -> list[str]:
    """Why a stop's answer does not make its count final, one reason for each thing stop_is_final
    needs that the answer did not give (round 8, F-10): a flush that did not settle is said as
    that, even when the pending count read afterwards has reached nought, and never as "0 still
    being written". Empty only when stop_is_final(answer) is True."""
    counts = answer.get("events") if isinstance(answer.get("events"), dict) else {}
    reasons: list[str] = []
    settled = answer.get("stop_settled")
    if settled is False:
        reasons.append("the stop's own flush did not settle")
    elif settled is not True:
        reasons.append("the backend did not say whether the stop's own flush settled")
    pending = counts.get("pending")
    counted = isinstance(pending, int) and not isinstance(pending, bool)
    if counted and pending > 0:
        reasons.append(f"{pending} were still being written")
    elif not counted:
        reasons.append("the backend did not say how many were still being written")
    # A pending count above nought already says the counts had not settled; said once.
    if counts.get("settled") is False and not (counted and pending > 0):
        reasons.append("the counts were still moving when they were read")
    elif counts.get("settled") is not True and counts.get("settled") is not False:
        reasons.append("the backend did not say whether its counts had settled")
    if not reasons and not stop_is_final(answer):
        reasons.append("the backend's answer did not say the stop had settled")
    return reasons


_current: Timeline = NullTimeline()


def install(timeline: Timeline) -> Timeline:
    global _current
    _current = timeline
    return timeline


def current() -> Timeline:
    return _current


def emit(kind: str, **fields: Any) -> dict[str, Any] | None:
    """The process's timeline, for code that has no runtime in hand (the dispatcher, the
    engine, the hydrator)."""
    return _current.emit(kind, **fields)


def new_id(prefix: str) -> str:
    return f"{prefix}_{os.urandom(6).hex()}"


def count_events(path: Path) -> int:
    """The number of events in a timeline, counted from the file. Cheap: lines, not JSON.
    Zero for a file that is not there yet, which is what an unwritten session looks like."""
    try:
        with Path(path).open("rb") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def read_events(path: Path) -> list[dict[str, Any]]:
    """Every event in a timeline, in the order written."""
    events: list[dict[str, Any]] = []
    try:
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
    except OSError:
        return []
    events.sort(key=lambda e: (float(e.get("ts") or 0), int(e.get("seq") or 0)))
    return events
