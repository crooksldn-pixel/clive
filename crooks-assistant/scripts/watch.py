#!/usr/bin/env python3
"""crooks-watch — what CROOKS OS is doing, live, in one line per thing (§35).

    make watch                 follow the active test session
    make watch SESSION=ts-…    follow (or replay) a named one
    crooks-watch --once        print what has happened and stop
    crooks-watch -v            everything: the lanes, the plans, the renders, the taps

Reads the test session's timeline as it grows and prints the SEMANTIC state, in the shape of
one job going through the machine:

    VOICE "reply to anna"
    LANE  NORMAL
    READ  Gmail thread 312ms  (gmail_read_thread ok)
    STAGE gmail_send_reply RED
    ARM   owner
    WRITE Gmail 452ms
    VERIFY Gmail ✓
    UI    confirmation → VERIFIED 31ms

and, when the two halves disagree, the disagreement — which is the defect the live hour spent
ten minutes on and nobody read:

    UI action prop_037e20c6ea04 stuck EXECUTING after server VERIFIED
    ERROR ACTION_UI_STUCK

What it will never print, whatever is on the timeline:

  * model reasoning of any kind — the timeline does not carry it and this does not ask for it
  * secrets, tokens or headers — the writer withholds them; this also refuses them by key
  * an email body, a subject, a customer's name, an address or an order's contents

What it does print, and did not before, is the OWNER's own sentence — `VOICE "…"`, which is
what makes a live watch legible at all: without it every line is an id and there is no telling
which question they belong to. It is his speech, on his Mac, in a session he started, and it
is scrubbed on the way out: an email address, a street, a postcode, a telephone number and any
long run of digits are replaced before the line is printed, whoever said them. Everything else
below is an id, a count, a millisecond or a controlled word.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

POLL_S = 0.25
# Fields that may be printed. An event field not named here is not shown, so a field added
# to the timeline later cannot start leaking into a terminal on somebody's bench.
SAFE = frozenset({
    "kind", "turn_id", "session_id", "branch_id", "parent_branch_id", "lane", "why", "family",
    "confidence", "recipe_id", "hit", "defer", "ms", "target_ms", "partial", "tool", "ok",
    "outcome", "error", "tool_call_id", "proposal_id", "batch_id", "operation", "risk",
    "interaction", "status", "code", "count", "set_id", "set_kind", "label", "engine",
    "fallback", "audio_s", "steps", "error_kind", "stopped_early", "ui", "model_calls",
    "fast_path_hit", "cache", "coalesced", "prefetch", "critical_path_ms", "serial_ms",
    "saved_ms", "groups", "fanout", "spent", "skipped", "state", "nav", "depth", "index",
    "chars", "via", "source", "input", "turns_before", "epoch", "missing_capability",
    "model_input_chars", "tool_schema_bytes", "turn_total_ms", "stt_ms", "model_ms",
    "source_ms", "tool_calls", "backgrounded", "cancelled", "threads_checked", "threads_found",
    # §35: the job going through the machine, and the two halves disagreeing about it.
    "verified", "caller_present", "kept", "reason", "command", "replayed", "entity", "cards",
    "shape", "text", "screen", "fingers", "target", "phase", "undo_of", "event",
})
# Fields that may be printed only as one of their own values (round 12, SC1-02). `claim` says
# which claim an `unsupported_claim` is (app/observability/claims.py screen_claim), and `drew`
# what the Mac drew to make a screen claim true (app/routes/turn.py _hold_to_the_screen): an
# order's number, or the kind of record it drew. Anything else it may hold — a record's label in
# words, which can be a customer's name — is printed as "a record".
CLAIMS = frozenset({"on_screen"})
DREW_KINDS = frozenset({"order", "customer", "email_thread"})
_ORDER_NUMBER = re.compile(r"#?[0-9]{1,12}")


def _drew(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, str) and (value in DREW_KINDS or _ORDER_NUMBER.fullmatch(value)):
        return value
    return "a record"


CONTROLLED = {
    "claim": lambda value: value if isinstance(value, str) and value in CLAIMS else None,
    "drew": _drew,
}

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
COLOUR = {"FAST": "\033[32m", "NORMAL": "\033[36m", "DEEP": "\033[35m",
          "error": "\033[31m", "warn": "\033[33m", "ok": "\033[32m"}

# What the owner said, with the shapes that are somebody's data taken out of it first. The
# same patterns the production recorder uses (app/observability/recorder.py), so the one rule
# is written once and this cannot be looser than that.
_REDACT: tuple[tuple[Any, str], ...] = (
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b\d{1,5}[a-z]?[\s,]+(?:[A-Za-z'\-]+\s+){0,3}"
                r"(?:road|street|lane|avenue|close|drive|way|court|place|terrace|gardens?|"
                r"crescent|row|hill|park|square|grove|mews|walk|rise|rd|st|ln|ave)\b", re.I), "[street]"),
    (re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I), "[postcode]"),
    (re.compile(r"\b\d{9,}\b"), "[digits]"),
    (re.compile(r"(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{3,5}\)?[\s\-]?){2,4}\d{2,4}"), "[phone]"),
)
SAID_CHARS = 60

# What a tool is READING, said as a person would. Anything not here is derived from its name,
# so a tool added tomorrow still prints a sentence rather than nothing.
SOURCES = {"shopify": "Shopify", "gmail": "Gmail", "commerce": "Shopify", "inventory": "Shopify",
           "email": "Gmail", "batch": "both"}
# Which service a change is made in, from the operation's own name.
WRITE_SERVICE = (("gmail_", "Gmail"), ("order_", "Shopify"), ("refund_", "Shopify"),
                 ("fulfillment_", "Shopify"), ("inventory_", "Shopify"), ("discount_", "Shopify"),
                 ("store_credit", "Shopify"), ("draft_order", "Shopify"))
# The states a card is in while it says "Applying…" (web/ui.js).
APPLYING = frozenset({"committing", "executing", "verifying"})
TERMINAL = frozenset({"VERIFIED", "UNVERIFIED", "FAILED", "STALE", "EXPIRED", "REVOKED"})
# A burst of navigation this size inside this window is somebody hunting rather than moving.
# The same numbers the analyser uses (app/observability/visible.py); imported there so the
# terminal and the report cannot disagree about what a burst is.
try:
    from app.observability.visible import NAV_BURST, NAV_WINDOW_S
except Exception:      # noqa: BLE001 — the watch runs from a checkout without the app importable
    NAV_BURST, NAV_WINDOW_S = 4, 30.0
# And the same for what makes a touch a TAP rather than a hold to speak. §21: 63 of the 11
# September session's taps became recordings and nobody saw it happen — the report found it
# twelve hours later and called it a precision-input failure. The bar the acceptance script
# sets for this is ZERO, so the terminal has to say it at the moment the finger lifts.
try:
    from app.observability.touch import BURST_MIN, BURST_S, TAP_MS
except Exception:      # noqa: BLE001 — same reason
    TAP_MS, BURST_MIN, BURST_S = 200.0, 3, 12.0
NAV_COMMANDS = {"navigation.home": "Home", "navigation.back": "Back", "navigation.forward": "Forward",
                "workflow.next": "Next", "workflow.previous": "Previous"}


def _tint(text: str, key: str, colour: bool) -> str:
    return f"{COLOUR.get(key, '')}{text}{RESET}" if colour and COLOUR.get(key) else text


def _ms(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{value / 1000:.1f}s" if value >= 1000 else f"{value:.0f}ms"


def said(text: str) -> str:
    """The owner's sentence, scrubbed and clipped."""
    words = " ".join(str(text or "").split())
    for pattern, replacement in _REDACT:
        words = pattern.sub(replacement, words)
    return words if len(words) <= SAID_CHARS else words[: SAID_CHARS - 1] + "…"


def _read_phrase(tool: str) -> str:
    """"Gmail thread" from `gmail_read_thread`. Derived, never a table that can fall behind."""
    parts = [p for p in str(tool or "").split("_") if p]
    if not parts:
        return "something"
    source = SOURCES.get(parts[0], parts[0].title())
    rest = [p for p in parts[1:] if p not in ("read", "get", "find", "list", "query", "detail", "info")]
    # A tool whose whole name is its verb ("commerce_query") keeps its last word, so the line
    # says which read it was rather than only which service.
    return f"{source} {' '.join(rest or parts[-1:])}".strip()


def _write_service(operation: str) -> str:
    for prefix, service in WRITE_SERVICE:
        if str(operation or "").startswith(prefix):
            return service
    return "the shop"


class Watch:
    """One line per thing, and the state needed to notice when two things disagree.

    The disagreement is the point (§17): the server settles a change and the surface goes on
    saying "Applying…". Neither event says so on its own — the Mac's says the change is
    finished, the tablet's says it is still holding it — so the watch keeps what the server
    last said about each proposal and reports the moment the tablet contradicts it.
    """

    def __init__(self, *, colour: bool = True, verbose: bool = False) -> None:
        self.colour = colour
        self.verbose = verbose
        self.status: dict[str, str] = {}          # proposal -> what the SERVER last said
        self.operation: dict[str, str] = {}       # proposal -> what it is
        self.told: set[str] = set()               # proposals already reported as stuck
        self.nav: deque[tuple[float, str]] = deque(maxlen=32)
        self.said_burst = 0.0
        # The touches too short to carry speech, so a burst of them can be said once rather
        # than twenty-six times (§21).
        self.taps: deque[float] = deque(maxlen=64)
        self.said_taps = 0.0

    # ------------------------------------------------------------------ helpers

    def head(self, event: dict[str, Any]) -> str:
        when = str(event.get("iso") or "")[11:19]
        turn = str(event.get("turn_id") or "")[-6:]
        return f"{when} {DIM if self.colour else ''}{turn or '······'}{RESET if self.colour else ''}"

    def tint(self, text: str, key: str) -> str:
        return _tint(text, key, self.colour)

    def bold(self, text: str) -> str:
        return f"{BOLD}{text}{RESET}" if self.colour else text

    def dim(self, text: str) -> str:
        return f"{DIM}{text}{RESET}" if self.colour else text

    # ------------------------------------------------------------------- the lines

    def lines(self, event: dict[str, Any]) -> list[str]:
        """Everything this event is worth saying, in order. Usually one line; two when the
        tablet and the Mac have just been caught disagreeing."""
        controlled = {k: CONTROLLED[k](v) for k, v in event.items() if k in CONTROLLED}
        event = {k: v for k, v in event.items() if k in SAFE or k in ("ts", "iso")}
        event.update({k: v for k, v in controlled.items() if v is not None})
        kind = str(event.get("kind") or "")
        head = self.head(event)
        out: list[str] = []

        if kind == "session_started":
            return [f"{head} {self.bold('session started')}"]
        if kind == "session_stopped":
            return [f"{head} {self.bold('session stopped')}"]
        if kind == "stt":
            if event.get("ok") is False:
                return [f"{head} {self.tint('VOICE  no speech', 'warn')}"
                        + self.dim(f"  {event.get('engine') or '?'}")]
            words = said(event.get("text") or event.get("raw_text") or "")
            engine = str(event.get("engine") or "?") + (" (fallback)" if event.get("fallback") else "")
            return [f"{head} VOICE  “{words}”" + self.dim(f"  {engine}")] if words else \
                   [f"{head} VOICE  heard" + self.dim(f"  {engine}")]
        if kind == "lane":
            lane = str(event.get("lane") or "")
            recipe = f" {event.get('recipe_id') or event.get('family') or ''}".rstrip()
            why = str(event.get("why") or "")
            return [f"{head} LANE   {self.tint(lane, lane)}{recipe}" + (self.dim(f"  {why}") if why else "")]
        if kind == "fast_path":
            state = "hit" if event.get("hit") else f"deferred: {event.get('defer')}"
            late = "  ⟵ over target" if _over(event) else ""
            return [f"{head} RECIPE {event.get('recipe_id')} {state} in {_ms(event.get('ms'))}{late}"]
        if kind == "tool_finished":
            outcome = str(event.get("outcome") or "")
            if outcome == "staged" and not self.verbose:
                # The change itself says this, better, on the next line: `STAGE <operation>
                # <risk>` comes off the proposal. Two lines for one staging is noise.
                return []
            key = "ok" if outcome == "ok" else ("warn" if outcome in ("not_yet", "staged") else "error")
            tool = str(event.get("tool") or "")
            verb = "STAGE" if outcome == "staged" else "READ "
            tail = f"  {event.get('error')}" if outcome not in ("ok", "staged") and event.get("error") else ""
            return [f"{head} {verb}  {_read_phrase(tool)} {_ms(event.get('ms'))}"
                    + self.dim(f"  ({tool} {self.tint(outcome, key)})") + str(tail)[:90]]
        if kind == "owner_feedback":
            return [f"{head} {self.tint('NOTE', 'warn')}   logged “{said(event.get('text') or '')}”"
                    + self.dim(f"  {event.get('shape') or ''}")]
        if kind.startswith("action_") or kind.startswith("batch_"):
            out.extend(self._action(head, kind, event))
            return out
        if kind.startswith("tablet_"):
            return self._tablet(head, kind[len("tablet_"):], event)
        if kind in ("command", "row_action"):
            return self._control(head, kind, event)
        if kind == "turn_finished":
            cards = ",".join(str(u) for u in (event.get("ui") or [])) or "no card"
            bad = event.get("error_kind")
            return [f"{head} ══ {_ms(event.get('ms'))}  {cards}"
                    + (f"  {self.tint(str(bad), 'error')}" if bad else "")]
        if not self.verbose:
            return []
        return self._verbose(head, kind, event)

    def _action(self, head: str, kind: str, event: dict[str, Any]) -> list[str]:
        pid = str(event.get("proposal_id") or "")
        operation = str(event.get("operation") or self.operation.get(pid) or "")
        if operation and pid:
            self.operation[pid] = operation
        what = kind.removeprefix("action_").removeprefix("batch_")
        if what == "proposed":
            risk = str(event.get("risk") or "")
            undo = " (undo)" if event.get("undo_of") else ""
            return [f"{head} STAGE  {operation} {self.tint(risk, 'warn' if risk == 'RED' else 'ok')}{undo}"]
        if what == "armed":
            # Always the owner: nothing else can arm a change. `app/actions/engine.py` refuses
            # a commit whose gesture it did not see, and the ledger's `caller` is about which
            # identity was recorded, not about whose hand it was.
            return [f"{head} ARM    owner"]
        if what == "executed":
            return [f"{head} WRITE  {_write_service(operation)} {_ms(event.get('ms'))}"]
        if what == "verified":
            proved = event.get("verified")
            self.status[pid] = "VERIFIED"
            mark = "✓" if proved is not False else "✗"
            return [f"{head} VERIFY {_write_service(operation)} {self.tint(mark, 'ok' if proved is not False else 'error')}"]
        status = str(event.get("status") or "").upper()
        if status in TERMINAL:
            self.status[pid] = status
            if what != "commit":
                return [f"{head} {self.tint(status, 'error')}  {operation}"
                        + self.dim(f"  {event.get('code') or ''}")]
        return self._verbose(head, kind, event) if self.verbose else []

    def _tablet(self, head: str, what: str, event: dict[str, Any]) -> list[str]:
        if what == "action_commit":
            status = str(event.get("status") or event.get("code") or "").upper()
            key = "ok" if status in ("VERIFIED", "EXECUTED") else "error"
            return [f"{head} UI     confirmation → {self.tint(status or '?', key)} {_ms(event.get('ms'))}"]
        if what == "reconcile":
            return self._stuck(head, event, f"the tablet resubmitted {event.get('count')} "
                                            f"proposal(s) and kept {event.get('kept')}")
        if what == "render":
            lines = self._stuck_cards(head, event)
            if lines:
                return lines
            if not self.verbose:
                return []
            return [f"{head} UI     drew {len(event.get('cards') or [])} card(s)"]
        if what == "exception":
            return [f"{head} {self.tint('ERROR  tablet exception', 'error')}"]
        if what == "navigate":
            # The tablet's own record of a tap the Mac also wrote down as a `command`. The
            # Mac's is the one printed, because it carries whether the move was ACCEPTED and
            # what it landed on; printing both gave every Back and Home twice.
            return [f"{head} UI     {event.get('nav')}"] if self.verbose else []
        if what == "toast":
            return [f"{head} UI     toast"] if self.verbose else []
        if what == "hold" and str(event.get("phase") or "") == "multitouch":
            return [f"{head} {self.tint('WARN', 'warn')}   {event.get('fingers') or 2} fingers on the "
                    f"{event.get('target') or 'orb'} at once"]
        if what == "hold" and str(event.get("phase") or "") == "release":
            return self._short_hold(head, event)
        if what == "recording_too_short":
            return []      # the release beside it already said it, with the target
        return self._verbose(head, f"tablet_{what}", event) if self.verbose else []

    def _short_hold(self, head: str, event: dict[str, Any]) -> list[str]:
        """A touch too short to carry speech, said at the moment the finger lifts.

        §21 and §39 step 1. The bar is ZERO ordinary control taps becoming recordings, and a
        bar nobody can see being crossed is a bar nobody holds. A tap on its own is a warning;
        three inside twelve seconds is the burst the 11 September evening had seventeen of, and
        that gets said once, loudly, rather than once per tap.
        """
        ms = event.get("ms")
        try:
            ms = float(ms)
        except (TypeError, ValueError):
            return []
        if ms >= TAP_MS or str(event.get("outcome") or "") != "sent":
            return []
        ts = float(event.get("ts") or 0.0)
        self.taps.append(ts)
        recent = [at for at in self.taps if ts - at <= BURST_S]
        out = [f"{head} {self.tint('TAP→MIC', 'warn')} a {ms:.0f} ms touch became a recording"
               + self.dim(f"  under {TAP_MS:.0f} ms, so no speech was in it")]
        if len(recent) >= BURST_MIN and ts - self.said_taps > BURST_S:
            self.said_taps = ts
            out.append(f"{head} {self.tint('SWALLOWED', 'error')} {len(recent)} taps in "
                       f"{ts - recent[0]:.0f}s, every one sent to the recogniser — the voice "
                       f"layer is over a control (web/style.css stacking context)")
        return out

    def _control(self, head: str, kind: str, event: dict[str, Any]) -> list[str]:
        name = str(event.get("command") or event.get("action") or kind)
        if event.get("ok") is False:
            return [f"{head} {self.tint('DEAD', 'error')}   {name} refused {event.get('code') or '?'}"]
        if name in NAV_COMMANDS:
            return self._navigation(head, event, NAV_COMMANDS[name])
        return [f"{head} TAP    {name}" + self.dim(f"  {_ms(event.get('ms'))}")] if self.verbose else []

    def _navigation(self, head: str, event: dict[str, Any], where: str) -> list[str]:
        """Back and Home, and the moment a burst of them stops being navigation."""
        ts = float(event.get("ts") or 0.0)
        self.nav.append((ts, where))
        landed = str(event.get("entity") or "")
        replayed = " (replayed what was already in hand)" if event.get("replayed") else ""
        out = [f"{head} NAV    {where}" + (f" → {landed}" if landed else "") + self.dim(replayed)]
        recent = [(at, w) for at, w in self.nav if ts - at <= NAV_WINDOW_S]
        if len(recent) >= NAV_BURST and ts - self.said_burst > NAV_WINDOW_S:
            self.said_burst = ts
            counts: dict[str, int] = {}
            for _at, name in recent:
                counts[name] = counts.get(name, 0) + 1
            span = ts - recent[0][0]
            out.append(f"{head} {self.tint('WARN', 'warn')}   "
                       + ", ".join(f"{n} × {name}" for name, n in sorted(counts.items()))
                       + f" in {span:.0f} s, every one accepted")
        return out

    # ------------------------------------------- the two halves, caught disagreeing

    def _settled(self) -> list[str]:
        return [pid for pid, status in self.status.items() if status in TERMINAL and pid not in self.told]

    def _stuck(self, head: str, event: dict[str, Any], detail: str) -> list[str]:
        """A reconcile that kept something the server had already settled."""
        if int(event.get("kept") or 0) < 1:
            return []
        settled = self._settled()
        if not settled:
            return []
        out: list[str] = []
        for pid in settled:
            self.told.add(pid)
            out.append(f"{head} {self.tint('UI', 'error')}     action {pid} stuck EXECUTING after "
                       f"server {self.status[pid]}")
            out.append(f"{head} {self.tint('ERROR  ACTION_UI_STUCK', 'error')}"
                       + self.dim(f"  {detail}"))
        return out

    def _stuck_cards(self, head: str, event: dict[str, Any]) -> list[str]:
        """A card drawn still saying "Applying…" for a change the server has finished."""
        out: list[str] = []
        for card in event.get("cards") or []:
            if not isinstance(card, dict):
                continue
            pid = str(card.get("proposal_id") or "")
            state = str((card.get("surface") or {}).get("state") or "")
            if not pid or state not in APPLYING or pid in self.told:
                continue
            if self.status.get(pid) not in TERMINAL:
                continue
            self.told.add(pid)
            out.append(f"{head} {self.tint('UI', 'error')}     action {pid} stuck EXECUTING after "
                       f"server {self.status[pid]}")
            out.append(f"{head} {self.tint('ERROR  ACTION_UI_STUCK', 'error')}"
                       + self.dim(f"  the card is drawn in {state!r}"))
        return out

    # --------------------------------------------------------------------- verbose

    def _verbose(self, head: str, kind: str, event: dict[str, Any]) -> list[str]:
        """Everything else, for somebody who asked to see everything else."""
        if kind == "turn_started":
            return [f"{head} ── heard ({event.get('input')})"]
        if kind == "read_plan":
            groups = event.get("groups") or []
            saved = _ms(event.get("saved_ms"))
            return [f"{head}    reads {' | '.join(','.join(g) for g in groups)}  "
                    f"{_ms(event.get('critical_path_ms'))}" + (f" (saved {saved})" if saved else "")]
        if kind == "prefetch" and event.get("hit"):
            return [f"{head}    looked the order up ahead of the model in {_ms(event.get('ms'))}"]
        if kind == "model":
            steps = len(event.get("steps") or [])
            calls = len(event.get("tool_calls") or [])
            return [f"{head}    claude {_ms(event.get('ms'))}  {steps} step(s), {calls} tool call(s)"]
        if kind == "working_set":
            return [f"{head}    set {event.get('set_id')} {event.get('count')} {event.get('set_kind')}"]
        if kind == "unsupported_claim" and event.get("claim") == "on_screen":
            done = f"drew {event.get('drew')}" if event.get("drew") else "corrected the answer"
            return [f"{head}    {self.tint(f'said it was on screen when nothing was; {done}', 'warn')}"]
        if kind == "unsupported_claim":
            return [f"{head}    {self.tint('said it cannot, though it can', 'warn')}"]
        if kind in ("prediction", "anticipation"):
            return [f"{head}    {kind} {event.get('state') or event.get('event') or ''}"]
        if kind.startswith("branch_"):
            return [f"{head}    {kind.removeprefix('branch_')} {event.get('branch_id') or ''}"]
        if kind == "turn_performance":
            bits = [f"lane={event.get('lane')}", f"model={event.get('model_calls')}"]
            if event.get("model_ms"):
                bits.append(f"claude={_ms(event.get('model_ms'))}")
            cache = event.get("cache") or {}
            if isinstance(cache, dict) and (cache.get("hits") or cache.get("misses")):
                bits.append(f"cache={cache.get('hits')}/{cache.get('hits', 0) + cache.get('misses', 0)}")
            if event.get("model_input_chars"):
                bits.append(f"prompt={event['model_input_chars']}c")
            return [f"{head}    {self.dim('  '.join(bits))}"]
        if kind.startswith("tablet_"):
            what = kind[len("tablet_"):]
            if what in ("tab", "scroll", "gesture"):
                # `depth` is a number and a scroll back to the top is 0, which is the
                # interesting one: a falsy test printed the line with nothing on it.
                detail = event.get("label") or event.get("gesture") or ""
                if what == "scroll":
                    detail = f"{event.get('depth', 0)} px of {event.get('height', 0)}"
                return [f"{head}    tablet {what} {detail}".rstrip()]
        return []


def line(event: dict, *, colour: bool = True, verbose: bool = False) -> str | None:
    """One event as one line, or None for an event with nothing to say.

    The stateless door, kept because most events need no state and every caller had it. A
    watch that must notice the tablet contradicting the Mac keeps a `Watch` instead.
    """
    rendered = Watch(colour=colour, verbose=verbose).lines(event)
    return "\n".join(rendered) if rendered else None


def _over(event: dict) -> bool:
    try:
        return float(event.get("ms") or 0) > float(event.get("target_ms") or 0) > 0
    except (TypeError, ValueError):
        return False


def follow(path: Path, *, once: bool, colour: bool, out=None, verbose: bool = False) -> int:
    """Print what is there, then what arrives. Ends on Ctrl-C, or at once with --once."""
    out = out if out is not None else sys.stdout
    watch = Watch(colour=colour, verbose=verbose)
    offset = 0
    seen_stop = False
    while True:
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                for raw in handle:
                    if not raw.endswith("\n"):
                        break        # a partial line: leave the offset before it
                    offset += len(raw.encode("utf-8"))
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    for rendered in watch.lines(event):
                        print(rendered, file=out, flush=True)
                    seen_stop = seen_stop or event.get("kind") == "session_stopped"
        except OSError:
            pass
        if once or seen_stop:
            return 0
        try:
            time.sleep(POLL_S)
        except KeyboardInterrupt:
            return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session", nargs="?", default="", help="a session id or its prefix; default: the one running")
    parser.add_argument("--once", action="store_true", help="print what has happened and stop")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="every event that has a line: the plans, the renders, the taps, the branches")
    parser.add_argument("--no-colour", action="store_true")
    args = parser.parse_args(argv)

    from app.observability.session import TestSessions
    from config.settings import get_settings

    store = TestSessions(get_settings().log_dir)
    path = store.find(args.session)
    if path is None:
        active = store.active()
        if active is not None:
            path = store.timeline_path(active)     # started, nothing written yet
        else:
            print("No test session is running. Start one: make test-session-start NAME=\"an hour\"", file=sys.stderr)
            return 1
    print(f"watching {path.name} — Ctrl-C to stop\n", file=sys.stderr)
    return follow(path, once=args.once, colour=not args.no_colour and sys.stdout.isatty(),
                  verbose=args.verbose)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
