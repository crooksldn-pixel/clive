"""The interaction record: CLIVE always writing down what it did with the owner, so it can look.

George, 2 October 2026: "Clive needs to actually look at how it responds to my queries … so it
can be used as part of building itself better. Right now I don't know if tests are running or
how much Clive actually knows about what he's putting on screen." And: "It should know exactly
what it's giving you on screen, how it's interacting, … what text it's showing, what screens
it's showing, so you can challenge it and it can challenge itself as to why it's showing those
screens."

What it is
----------
A test session is something somebody starts. This is not: it runs whenever the service runs
(CROOKS_INTERACTION_RECORD, on unless it is set false), one file a day in logs/interactions/,
and it holds every event a test session would hold — what was heard, which tools ran, what the
tablet drew and what was tapped, held, refused and how long each took — plus one line per turn
of its own (`interaction_turn`): what was asked and heard, what each card on the screen was and
which tool drew it, WHY the screen was chosen (which rule of app/screen.py, which tool result,
which change, which failure), the speech signals (a name spelled, a correction) and the request
shape the words had. `app/observability/friction.py` reads it for friction, and the
`interaction_review` tool (app/tools/interaction_tools.py) lets CLIVE read it.

What it promises
----------------
* Bounded by days and by size: a day is kept CROOKS_INTERACTION_RECORD_KEEP_DAYS (seven) and
  stops growing at CROOKS_INTERACTION_RECORD_DAY_MB (sixteen), so the folder never holds more
  than one day more than that.
* Redacted exactly as a test session is, by the same code: every line passes the timeline's
  `scrub` (credentials, email addresses, card numbers, postcodes, telephone numbers, and the
  customer names this process has been told), and the owner's words and the cards' titles are
  written by their shape — a length and a digest — as the day's automatic test session writes
  them (app/observability/timeline.py `WORDS`). CROOKS_INTERACTION_RECORD_WORDS keeps them as
  said, still scrubbed; it is the owner's decision and never a default.
* It stays on this server: files 0600 in a 0700 folder, read by nothing but this process.
* It changes nothing about a turn. It hangs off the timeline as its mirror; off, it is not
  installed and nothing here runs.

The words, while the process lives
----------------------------------
"What is on screen now" is answered from the Mac's own copy of each half's screen
(`Branch.last_ui`, app/screen.py), word for word, never from a model's memory. And the last few
turns of each conversation are held in memory (`Recent`) with their words — what was asked, what
the recogniser heard, the cards' titles and lines — so "why did you show me that" can be
answered in his words. Memory only, bounded, gone at a restart: the same words the conversation
itself already holds in memory, and never written anywhere by this module.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any

from app.observability import friction
from app.observability.session import TestSession, TestSessions
from app.observability.timeline import Timeline, read_events

log = logging.getLogger("crooks.observe")

DIR_NAME = "interactions"
# The kinds only this record writes. They never reach the experience recorder behind it, which
# minimises by its own rules and was not written for card titles.
OWN_KINDS = frozenset({"interaction_turn"})
# What one look at the record reads from the end of a day's file. A busy hour is well under it.
TAIL_BYTES = 6 * 1024 * 1024
MAX_CARDS = 8
MAX_LINES = 12
MAX_LINE_CHARS = 160


# ------------------------------------------------------------------------- where it is kept


class InteractionDays(TestSessions):
    """The days on disk: today's always running, yesterday's closed at midnight, anything older
    than `keep_days` deleted when the next day starts. The test-session machinery in its own
    folder, so `make test-session-report` never mistakes a day of this for a session."""

    __test__ = False

    def __init__(self, log_dir: Path, *, keep_days: int = 7, clock=time.time) -> None:
        keep = max(1, int(keep_days or 7))
        super().__init__(log_dir, clock=clock, dir_name=DIR_NAME, always=True, keep_days=keep,
                         keep_named_days=keep)

    def start(self, name: str) -> TestSession:  # noqa: ARG002 — nothing starts a day by name
        raise RuntimeError("the interaction record keeps itself; nothing is started in it by name")

    def days(self) -> list[Path]:
        """Every day's file, oldest first."""
        try:
            return sorted(p for p in self.root.glob("ts-*.jsonl") if p.is_file())
        except OSError:
            return []


class InteractionRecord(Timeline):
    """The record's writer: a timeline over `InteractionDays`, installed as the process
    timeline's mirror, with its own day size and its own rule for the owner's words. Whatever
    mirror it was given (the experience recorder, when that is on too) still gets every event."""

    def __init__(self, days: InteractionDays, *, keep_words: bool = False, day_bytes: int = 16 * 1024 * 1024,
                 clock=time.time, behind: Timeline | None = None) -> None:
        super().__init__(days, clock=clock)
        self.keep_words = bool(keep_words)
        self.max_file_bytes = max(64 * 1024, int(day_bytes))
        self.mirror = behind
        self.recent = Recent()

    @classmethod
    def from_settings(cls, settings: Any, *, behind: Timeline | None = None) -> InteractionRecord:
        days = InteractionDays(Path(settings.log_dir), keep_days=int(getattr(settings, "interaction_record_keep_days", 7) or 7))
        return cls(days, keep_words=bool(getattr(settings, "interaction_record_words", False)),
                   day_bytes=int(getattr(settings, "interaction_record_day_mb", 16) or 16) * 1024 * 1024, behind=behind)

    def _keeps_words(self, session: TestSession | None) -> bool:
        return self.keep_words

    def emit(self, kind: str, *, source: str = "mac", ts: float | None = None, **fields: Any) -> dict[str, Any] | None:
        if kind in OWN_KINDS:
            return self._write(kind, source=source, ts=ts, **fields)
        return super().emit(kind, source=source, ts=ts, **fields)

    @property
    def bounds(self) -> dict[str, Any]:
        days: InteractionDays = self.sessions  # type: ignore[assignment]
        return {"keep_days": days.keep_days, "day_mb": round(self.max_file_bytes / 1024 / 1024, 1),
                "words": "kept as said, scrubbed" if self.keep_words else "by their shape",
                "folder": str(days.root)}

    def window(self, *, minutes: float = 15.0, now: float | None = None) -> list[dict[str, Any]]:
        """The record's events from the last `minutes`, oldest first: the end of today's file,
        and of yesterday's when the window reaches back past midnight."""
        self.flush(timeout_s=1.0)
        at = float(now if now is not None else self.clock())
        since = at - max(0.5, float(minutes)) * 60.0
        days: InteractionDays = self.sessions  # type: ignore[assignment]
        out: list[dict[str, Any]] = []
        for path in days.days()[-2:]:
            out.extend(e for e in _tail_events(path) if since <= float(e.get("ts") or 0.0) <= at + 1.0)
        out.sort(key=lambda e: (float(e.get("ts") or 0.0), int(e.get("seq") or 0)))
        return out


def _tail_events(path: Path, limit: int = TAIL_BYTES) -> list[dict[str, Any]]:
    """The events at the end of one day's file: at most `limit` bytes of it, from a line start."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size <= limit:
        return read_events(path)
    out: list[dict[str, Any]] = []
    try:
        with path.open("rb") as handle:
            handle.seek(size - limit)
            handle.readline()   # the part-line the cut began in
            for raw in handle:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    out.append(event)
    except OSError:
        return []
    return out


# ---------------------------------------------------------------------------- the process's

_current: InteractionRecord | None = None


def install(record: InteractionRecord | None) -> InteractionRecord | None:
    global _current
    _current = record
    return record


def current() -> InteractionRecord | None:
    return _current


def on(timeline: Any) -> bool:
    """Whether `timeline`'s active session is this record's day rather than a test session or
    a recording somebody started: what /health and /test-session/status say apart."""
    record = _current
    if record is None or timeline is None:
        return False
    session = getattr(timeline, "active", None)
    own = record.active_id
    return session is not None and own is not None and getattr(session, "test_session_id", None) == own


# ---------------------------------------------------------------- the words, in memory only


class Recent:
    """The last turns of each conversation with their words, in memory: never written down.
    Bounded by turns per conversation, conversations, and age."""

    PER_CONVERSATION = 40
    CONVERSATIONS = 12
    MAX_AGE_S = 2 * 3600

    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        self._by: OrderedDict[str, deque] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, session_id: str, entry: dict[str, Any]) -> None:
        with self._lock:
            turns = self._by.pop(session_id, None) or deque(maxlen=self.PER_CONVERSATION)
            turns.append(entry)
            self._by[session_id] = turns
            while len(self._by) > self.CONVERSATIONS:
                self._by.popitem(last=False)

    def turns(self, session_id: str, *, now: float | None = None) -> list[dict[str, Any]]:
        at = float(now if now is not None else self.clock())
        with self._lock:
            held = list(self._by.get(session_id) or ())
        return [t for t in held if at - float(t.get("at") or 0.0) <= self.MAX_AGE_S]

    def last(self, session_id: str) -> dict[str, Any] | None:
        turns = self.turns(session_id)
        return turns[-1] if turns else None

    def find(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            for turns in self._by.values():
                for entry in turns:
                    if entry.get("turn_id") == turn_id:
                        return entry
        return None


# ------------------------------------------------------------------ what a card IS, in words

# The fields a card's data shows as text, in the order a line is read; and the lists it shows
# rows from. Read generically, so a card type added later is still described.
_TITLE_KEYS = ("title", "headline", "order_number", "subject", "name", "label", "customer_name")
_TEXT_KEYS = ("title", "headline", "order_number", "label", "name", "customer_name", "customer", "subject",
              "from", "sender", "status", "payment", "fulfillment", "financial_status", "fulfillment_status",
              "total", "value", "amount", "count", "when", "placed_at", "waiting", "detail", "summary", "note",
              "snippet", "recovery", "target", "message", "ships_to", "variant", "quantity", "stage", "who", "text",
              "service")
_LIST_KEYS = ("orders", "threads", "rows", "customers", "products", "items", "messages", "metrics", "facts",
              "fields", "lines", "entries", "members", "stages", "tasks", "variants")


def _text(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return " ".join(value.split())[:MAX_LINE_CHARS]
    return ""


def card_title(item: dict[str, Any]) -> str:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    for key in _TITLE_KEYS:
        said = _text(data.get(key))
        if said:
            return said
    return ""


def _row_line(row: Any) -> str:
    if not isinstance(row, dict):
        return _text(row)
    if "key" in row and "value" in row:          # a fact, as a workspace draws one: "Payment: Paid"
        return f"{_text(row.get('key'))}: {_text(row.get('value'))}"[:MAX_LINE_CHARS]
    parts = []
    for key in _TEXT_KEYS:
        said = _text(row.get(key))
        if said and said not in parts:
            parts.append(said)
    return " · ".join(parts)[:MAX_LINE_CHARS]


def _rows_of(data: dict[str, Any]) -> tuple[str, list[Any]]:
    for key in _LIST_KEYS:
        rows = data.get(key)
        if isinstance(rows, list) and rows:
            return key, rows
    return "", []


def card_words(item: dict[str, Any]) -> dict[str, Any]:
    """One card as the owner sees it: its title, its lines (a list's first rows, a record's
    facts), each section of a workspace with its state, and the controls on it with whether
    each is enabled and why not. From the card data the tablet renders, word for word."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    out: dict[str, Any] = {"type": str(item.get("type") or ""), "title": card_title(item)}
    if item.get("kept"):
        out["kept"] = True
    if item.get("refreshed"):
        out["refreshed"] = True
    facts = []
    for key in _TEXT_KEYS:
        said = _text(data.get(key))
        if said and said != out["title"]:
            facts.append(f"{key}: {said}")
    if facts:
        out["facts"] = facts[:MAX_LINES]
    key, rows = _rows_of(data)
    if rows:
        out["rows"] = {"of": key, "count": len(rows), "shows": [line for line in (_row_line(r) for r in rows[:MAX_LINES]) if line]}
        if isinstance(data.get("count"), int):
            out["rows"]["count"] = data["count"]
    attention = [_text(a.get("title")) for a in (data.get("attention_top") or []) if isinstance(a, dict) and a.get("title")]
    if attention:
        out["attention"] = attention[:4]
    sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    if sections:
        out["sections"] = {str(name): _section_words(section) for name, section in list(sections.items())[:8]
                           if isinstance(section, dict)}
        if data.get("tab"):
            out["tab"] = _text(data.get("tab"))
    actions = _actions_of(data, rows)
    if actions:
        out["actions"] = actions
    return out


def _section_words(section: dict[str, Any]) -> dict[str, Any]:
    """One section of a workspace: its state, and what it shows — its facts, then its rows."""
    lines = [_row_line(f) for f in (section.get("facts") or [])[:6]]
    lines += [_row_line(r) for r in (section.get("rows") or [])[:4]]
    return {"state": str(section.get("state") or ""), "shows": [line for line in lines if line]}


def _control(action: dict[str, Any]) -> str:
    """A control's name: its id or operation, or "open" for a link to another record."""
    named = action.get("id") or action.get("operation") or action.get("command")
    if named:
        return str(named)[:40]
    return "open" if action.get("ref") or action.get("kind") else ""


def _actions_of(data: dict[str, Any], rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for action in (data.get("actions") or [])[:12]:
        if isinstance(action, dict):
            entry = {"control": _control(action), "label": _text(action.get("label")),
                     "enabled": action.get("enabled") is not False}
            if not entry["enabled"] and action.get("reason"):
                entry["why_not"] = _text(action.get("reason"))
            out.append(entry)
    on_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        for action in (row.get("actions") or []) if isinstance(row, dict) else []:
            if isinstance(action, dict) and action.get("id"):
                held = on_rows.setdefault(str(action["id"]), {"control": str(action["id"]), "label": _text(action.get("label")),
                                                              "enabled": action.get("enabled") is not False, "on_rows": 0})
                held["on_rows"] += 1
    return out + list(on_rows.values())


# --------------------------------------------------------- what a card is, for the record


def card_shape(item: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    """One card as the record keeps it: what it is, how many rows, which controls (ids and
    whether enabled), which order numbers, which tools drew it. Ids and vocabulary only; its
    title travels apart, by the words rule."""
    from app import screen

    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    out: dict[str, Any] = {"type": str(item.get("type") or "")}
    if item.get("surface"):
        out["surface"] = str(item.get("surface"))[:40]
    for flag in ("kept", "refreshed"):
        if item.get(flag):
            out[flag] = True
    if sources:
        out["drawn_by"] = sources[:6]
    key, rows = _rows_of(data)
    if rows:
        out["rows"] = int(data["count"]) if isinstance(data.get("count"), int) else len(rows)
    # The reply queue (app/families/landings.py `_waiting_surface`, a work queue) and the read
    # layer's reply-state rows say who is waiting; a plain inbox list does not, however its rows
    # are flagged.
    if item.get("surface") == "work_queue" or any(isinstance(r, dict) and "waiting_since" in r for r in rows):
        out["marks"] = ["reply_state"]
    actions = _actions_of(data, rows)
    if actions:
        out["actions"] = [{k: v for k, v in a.items() if k in ("control", "enabled", "on_rows")} for a in actions]
    sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    if sections:
        out["sections"] = {str(n)[:24]: str((s or {}).get("state") or "")[:16] for n, s in list(sections.items())[:8] if isinstance(s, dict)}
    if data.get("tab"):
        out["tab"] = str(data.get("tab"))[:24]
    numbers = sorted(screen.numbers_on([item]))
    if numbers:
        out["numbers"] = numbers[:6]
    record = screen.record_of(item)
    if record:
        out["record"] = record[0]
    if data.get("proposal_id"):
        out["proposal_id"] = str(data.get("proposal_id"))[:40]
    if data.get("batch_id"):
        out["batch_id"] = str(data.get("batch_id"))[:40]
    return out


# --------------------------------------------------------------------- the decision trace


def _call_ids(call: Any) -> set[str]:
    result = getattr(call, "result", None)
    ids: set[str] = set()
    if not isinstance(result, dict):
        return ids
    for key in ("order_id", "customer_id", "thread_id", "ref", "set_id", "workspace_id", "objective_id", "compose_id"):
        value = result.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            ids.add(str(value).strip())
    return ids


def _types_from(call: Any) -> set[str]:
    """The card types this call's result is drawn as, by the presentation layer's own rule."""
    from app import presentation

    try:
        return {str(i.get("type") or "") for i in presentation._from_result(call.name, call.result)}
    except Exception:  # noqa: BLE001 — a result it cannot shape draws nothing by itself
        return set()


def sources(ui: list[dict[str, Any]], calls: list[Any] | None) -> list[list[str]]:
    """For each card, the tools whose results drew it: the proposal a change card waits on, the
    reads whose records it shows, the reads the presentation layer draws as its type."""
    from app import screen

    calls = [c for c in (calls or []) if getattr(c, "name", "")]
    by_proposal = {str(c.proposal_id): c.name for c in calls if getattr(c, "proposal_id", None)}
    reads = [c for c in calls if getattr(c, "ok", False) and not getattr(c, "proposal_id", None) and isinstance(getattr(c, "result", None), dict)]
    typed = {id(c): _types_from(c) for c in reads}
    ids = {id(c): _call_ids(c) for c in reads}
    failed = [c.name for c in calls if not getattr(c, "ok", True)]
    out: list[list[str]] = []
    for item in ui or []:
        kind = str(item.get("type") or "")
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        found: list[str] = []
        if item.get("kept"):
            found = ["(already on screen)"]
        elif kind in ("confirmation", "success") and data.get("proposal_id"):
            found = [by_proposal.get(str(data["proposal_id"]), "(a change)")]
        elif kind in ("batch_action", "batch_result") and data.get("batch_id"):
            found = [by_proposal.get(str(data["batch_id"]), "(a bulk change)")]
        elif kind == "error":
            found = failed or ["(the turn itself)"]
        elif kind == "context_stack":
            found = ["(the conversation)"]
        else:
            refs = screen.refs_on([item])
            for call in reads:
                if kind in typed[id(call)] or (refs and ids[id(call)] & refs):
                    found.append(call.name)
            if not found and kind in _COMPOSED:
                # A record's workspace is composed from everything the conversation holds of it
                # (app/presentation.py `_compose_workspace`), not from one read of this turn.
                found = ["(composed from what the conversation already read)"]
        out.append(list(dict.fromkeys(found)))
    return out


_COMPOSED = frozenset({"order_workspace", "customer_workspace", "workspace"})


def workspace_reason(question: str, session: Any) -> dict[str, Any] | None:
    """Why the words drew a record's workspace, by the rule that drew it (app/workspace.py
    `desired`): which record kind, which of its sections the words named, which tab. Section
    names and kinds only — the vocabulary of that file."""
    if session is None or not question:
        return None
    try:
        from app import entities, workspace

        plan = workspace.desired(question, graph=entities.graph_for(session))
    except Exception:  # noqa: BLE001 — no reason to give is no reason given
        return None
    if plan is None:
        return None
    out: dict[str, Any] = {"kind": plan.kind, "named": list(plan.wants), "tab": plan.tab, "whole": plan.whole}
    out["says"] = (f"the words were read as about the {plan.kind} the conversation already had"
                   + (f", naming its {' and '.join(plan.wants)}" if plan.wants else "")
                   + (" (the whole record)" if plan.whole else "")
                   + ", so it was composed as that record's workspace")
    return out


_CARRY_WORDS = {
    "nothing_up": "nothing was on the screen, so the answer's cards are the screen",
    "new_subject": "the answer brought a new subject (a record or list not on the screen), so it replaced the screen",
    "change_elsewhere": "the change card was about a record not on the screen, so it replaced the screen",
    "named_elsewhere": "he named an order the screen was not showing, so the screen did not stay under the answer",
    "read_elsewhere": "the answer read a record the screen was not showing, so the screen did not stay under it",
    "continued": "no new subject, so the screen he was working on stayed and the answer's cards went with it",
    "failed": "the screen could not be continued, so the answer was drawn alone",
}


def decision(*, ui: list[dict[str, Any]], screen_state: str, carry: list[str], calls: list[Any] | None,
             card_sources: list[list[str]], error_kind: str | None, abandoned: bool, claim: dict[str, Any] | None,
             withheld: int, scene: dict[str, Any] | None = None) -> dict[str, Any]:
    """Why the screen is what it is after this turn: the rule that decided, in words of the
    product's own vocabulary, and which tools drew which cards and which drew nothing."""
    reason = carry[-1] if carry else ""
    tools = [getattr(c, "name", "") for c in calls or []]
    drew = {name for names in card_sources for name in names}
    reads = [getattr(c, "name", "") for c in calls or [] if getattr(c, "ok", False) and not getattr(c, "proposal_id", None)]
    out: dict[str, Any] = {"screen": screen_state, "carry": reason or None}
    if abandoned:
        out["rule"], out["says"] = "abandoned", "a newer question or a cancel replaced this answer, so it drew nothing"
    elif error_kind:
        out["rule"], out["says"] = "error", f"the turn failed ({error_kind}), so an error card was drawn"
    elif screen_state == "cleared":
        if "close_screen" in tools:
            out["rule"], out["says"] = "closed", "he asked for it to be closed (close_screen)"
        elif reason in ("named_elsewhere", "read_elsewhere"):
            out["rule"], out["says"] = "cleared", _CARRY_WORDS[reason] + ", and the answer drew nothing of its own"
        else:
            out["rule"], out["says"] = "words_only", "the answer drew no card and there was nothing on the screen to keep"
    elif screen_state == "kept":
        out["rule"], out["says"] = "carried", _CARRY_WORDS.get(reason, _CARRY_WORDS["continued"])
    else:
        out["rule"], out["says"] = "new", _CARRY_WORDS.get(reason, _CARRY_WORDS["nothing_up"])
    staged = [getattr(c, "name", "") for c in calls or [] if getattr(c, "proposal_id", None)]
    if staged:
        out["staged"] = staged[:6]
    words_only = [name for name in dict.fromkeys(reads) if name not in drew]
    if words_only:
        out["read_for_words"] = words_only[:8]
    if claim:
        # The answer said something was on the screen that this turn had not put there
        # (app/routes/turn.py `_hold_to_the_screen`): the record it drew to make that true, or
        # that the sentence was taken out. Order numbers and a record's id only.
        repaired = {k: claim.get(k) for k in ("drew", "corrected", "named") if claim.get(k) not in (None, False, [])}
        out["claim_repair"] = repaired or {"corrected": False}
    if withheld:
        out["withheld"] = withheld
    if scene and isinstance(scene.get("trace"), list):
        out["scene"] = [{"target": str(t.get("target") or "")[:40], "decision": str(t.get("decision") or "")[:24]}
                        for t in scene["trace"][:8] if isinstance(t, dict)]
    if not ui and not abandoned:
        out["drew_nothing"] = True
    return out


# ------------------------------------------------------------------------ after each turn


def after_turn(*, session_id: str, turn_id: str, question: str, transcript: dict[str, Any] | None, answer: str,
               ui: list[dict[str, Any]], calls: list[Any] | None, screen_state: str, carry: list[str] | None,
               error_kind: str | None, abandoned: bool, timings: dict[str, float], branch: Any = None,
               claim: dict[str, Any] | None = None, withheld: int = 0, binding: Any = None,
               scene: dict[str, Any] | None = None, session: Any = None) -> None:
    """One turn, written down: called by /turn once its screen is decided. Never raises, and
    with no record installed it is one check."""
    record = _current
    if record is None:
        return
    try:
        _after_turn(record, session_id=session_id, turn_id=turn_id, question=question, transcript=transcript,
                    answer=answer, ui=ui, calls=calls, screen_state=screen_state, carry=list(carry or []),
                    error_kind=error_kind, abandoned=abandoned, timings=timings, branch=branch, claim=claim,
                    withheld=withheld, binding=binding, scene=scene, session=session)
    except Exception as exc:  # noqa: BLE001 — the record never takes a turn down
        log.warning("the interaction record missed a turn: %s", type(exc).__name__)


def _after_turn(record: InteractionRecord, *, session_id, turn_id, question, transcript, answer, ui, calls,
                screen_state, carry, error_kind, abandoned, timings, branch, claim, withheld, binding, scene,
                session) -> None:
    from app.observability import claims

    now = record.clock()
    transcript = transcript if isinstance(transcript, dict) else {}
    heard = str(transcript.get("raw_text") or transcript.get("text") or "")
    used = str(question or transcript.get("text") or "")
    previous = record.recent.last(session_id)
    speech = friction.speech_signals(
        heard, used, now=now,
        previous=(str(previous.get("turn_id") or ""), str(previous.get("question") or ""), float(previous.get("at") or 0.0))
        if previous else None)
    cards = [item for item in (ui or []) if isinstance(item, dict) and item.get("type") and item.get("type") != "context_stack"]
    drawn_by = sources(cards, calls)
    shapes = [card_shape(item, drawn_by[i]) for i, item in enumerate(cards[:MAX_CARDS])]
    titles = [card_title(item) for item in cards[:MAX_CARDS]]
    why = decision(ui=cards, screen_state=screen_state, carry=carry, calls=calls, card_sources=drawn_by,
                   error_kind=error_kind, abandoned=abandoned, claim=claim, withheld=withheld, scene=scene)
    if any(str(item.get("type") or "") in _COMPOSED and not item.get("kept") for item in cards):
        composed = workspace_reason(used, session)
        if composed is not None:
            why["workspace"] = composed
    tools = [_tool_shape(c) for c in (calls or [])][:16]
    expect = friction.expectations(used)
    ms = _times(timings, calls)
    declined = bool(answer and claims.CANNOT_RE.search(answer))
    bound = str((binding or {}).get("family") or "")[:40] if isinstance(binding, dict) else ""
    via = "audio" if transcript else ("text" if used else "none")
    record.emit(
        "interaction_turn", session_id=session_id or None, turn_id=turn_id or None,
        branch_id=str(getattr(branch, "branch_id", "") or "") or None, via=via,
        question=used or None, heard=(heard or None) if transcript else None, answer=answer or None,
        asked={"chars": len(used), "words": len(used.split())}, speech=speech, expect=expect or None,
        named_orders=friction.named_orders(used) or None, bound=bound or None, tools=tools or None,
        cards=shapes, titles=titles, screen=screen_state, why=why, declined=declined or None, ms=ms,
        error_kind=error_kind or None, abandoned=abandoned or None,
    )
    record.recent.add(session_id, {
        "turn_id": turn_id, "at": now, "branch_id": str(getattr(branch, "branch_id", "") or ""), "via": via,
        "question": used, "heard": heard if transcript else "", "answer": str(answer or "")[:600],
        "cards": [card_words(item) for item in cards[:MAX_CARDS]], "sources": drawn_by[:MAX_CARDS],
        "screen": screen_state, "why": why, "speech": speech, "expect": expect, "tools": tools, "ms": ms,
    })


def _tool_shape(call: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"tool": str(getattr(call, "name", "") or "")[:60], "ok": bool(getattr(call, "ok", False))}
    ms = getattr(call, "duration_ms", None)
    if isinstance(ms, (int, float)):
        out["ms"] = round(float(ms), 1)
    if getattr(call, "proposal_id", None):
        out["staged"] = True
    return out


def _times(timings: dict[str, float], calls: list[Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("total", "transcribe", "agent", "workspace"):
        value = (timings or {}).get(key)
        if isinstance(value, (int, float)):
            out[key] = round(float(value), 1)
    slowest = max(((getattr(c, "name", ""), getattr(c, "duration_ms", None)) for c in calls or []
                   if isinstance(getattr(c, "duration_ms", None), (int, float))), key=lambda kv: kv[1], default=None)
    if slowest is not None:
        out["slowest_tool"] = {"tool": slowest[0], "ms": round(float(slowest[1]), 1)}
    return out


# ---------------------------------------------------------------------- what is up now


def on_screen(session: Any, *, clock=time.time) -> list[dict[str, Any]]:
    """Each half's screen as the Mac last drew it, word for word, with when it was drawn and
    what the half is doing. Nothing on a half means nothing is drawn there (the tablet clears
    its cards after thirty minutes, and so does the Mac's copy)."""
    from app import screen

    if session is None:
        return []
    halves = []
    focused = str(getattr(session, "focused_branch", "") or "")
    for branch_id, branch in list((getattr(session, "branches", None) or {}).items()):
        if str(getattr(branch, "status", "")) not in ("ACTIVE", "BACKGROUND"):
            continue
        cards = screen.showing(branch, clock=clock)
        last_at = float(getattr(branch, "last_at", 0.0) or 0.0)
        half: dict[str, Any] = {
            "half": branch_id, "focused": branch_id == focused or len(session.branches) == 1,
            "headline": (branch.headline() or {}).get("words", "") if hasattr(branch, "headline") else "",
            "state": branch.state() if hasattr(branch, "state") else "",
            "drawn_s_ago": round(clock() - last_at, 1) if last_at else None,
            "cards": [card_words(item) for item in cards[:MAX_CARDS]],
        }
        if not cards:
            half["nothing"] = ("nothing is drawn on this half" if not last_at
                               else "nothing is drawn on this half now (closed, cleared or idle)")
        halves.append(half)
    # A conversation that has drawn nothing yet has no half to speak of: one, empty.
    return halves or [{"half": "", "focused": True, "cards": [], "nothing": "nothing is drawn on this half"}]


def tablet_said(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """What the tablet itself last reported drawing (its own `render` event): card types, which
    controls were enabled and why not, overlaps it measured — to hold against the Mac's copy."""
    renders = [e for e in events if e.get("kind") == "tablet_render" and isinstance(e.get("cards"), list)]
    if not renders:
        return None
    last = renders[-1]
    cards = []
    for card in last.get("cards") or []:
        if not isinstance(card, dict):
            continue
        entry: dict[str, Any] = {"type": str(card.get("type") or "")}
        actions = [a for a in (card.get("actions") or []) if isinstance(a, dict)]
        if actions:
            entry["controls"] = [{"control": a.get("id"), "enabled": a.get("enabled"), **({"why_not": a.get("reason")} if a.get("reason") else {})}
                                 for a in actions[:10]]
        if card.get("tab_active"):
            entry["tab"] = card.get("tab_active")
        cards.append(entry)
    overflow = last.get("overflow") if isinstance(last.get("overflow"), dict) else {}
    live = [e for e in events if e.get("kind") == "tablet_live_marks"]
    out: dict[str, Any] = {"at": last.get("ts"), "screen": last.get("screen"), "cards": cards,
                           "overlaps": overflow.get("collisions"), "long_scroll": overflow.get("long_scroll")}
    if live:
        marks = live[-1]
        out["last_turn_motion"] = {k: marks.get(k) for k in ("ack_ms", "transcript_ms", "progress_ms", "useful_ms", "responding_ms", "state")
                                   if marks.get(k) is not None}
    return out


def private(path: Path) -> bool:
    """Whether a day's file is this process's own and closed to everyone else."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return not info.st_mode & 0o077 and info.st_uid == os.geteuid()
