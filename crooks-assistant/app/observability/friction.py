"""Where an interaction fought the owner, found mechanically from the interaction record.

George, 2 October 2026: "If something isn't working, e.g. a bulk archive of spam with friction
like screens changing randomly, archive buttons not working, Clive should understand that was
friction and that there could have been an easier way. I just need to say 'look at our
interaction and see how that happened'." And: "When I was doing refunds I had to spell names
out letter by letter."

So this module reads what the record holds (app/observability/interactions.py) and files what
fought him, each finding a count or a match over ids and clocks that names the events it read:

    REPEATED_TAP          the same control tapped again and again inside seconds
    SCREEN_CHANGED_UNASKED the cards on the glass were replaced with no tap and no question
                          in flight to ask for it
    ACTION_FAILED         a tap, a hold or a tool that was refused, failed or never answered;
                          RETRIED when the same thing was tried again after it
    SPELLED_OUT           a name spelled letter by letter, or a correction ("no, I said…"),
                          or the same thing said again
    LONG_WAIT             a turn, a tool or a tap that kept him waiting
    UNRELATED_SCENE       a request answered with a scene that is not what it asked for ("who
                          needs a reply" answered with a plain list of emails)
    MISSING_CAPABILITY    something asked for that CLIVE cannot do, or said it could not do

Each finding ends with what would have been easier, built from what CLIVE has: a row action
tapped eight times names the bulk tool that does the same change to the whole set under one
hold, when there is one.

What was SAID is read once, at the moment it was said (`speech_signals`, `expectations`), and
only the numbers and the fixed words those return reach the record: how many letters were
spelled, whether it was a correction, which of a small vocabulary of requests it was. So a
record that keeps the owner's words by their shape still knows that a name was spelled.

Nothing here executes, stages or authorises anything. It is a function from events to findings.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------------ what was said, read once

# Words, numbers, and the punctuation a recogniser puts between two spelled names ("Z O E, Q U I
# L L"), which ends a run; a hyphen joins letters ("Z-O-E") and does not; and "it's" is one word, not
# "it" and a letter.
_TOKEN = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)?|\d+|[,.;:?!]")
# Letters as they are said aloud. Counted as letters only inside a run that already has single
# letters in it ("zed oh ee" alone is three words): "see", "you" and "why" are words first.
LETTER_WORDS = {
    "ay": "a", "bee": "b", "cee": "c", "see": "c", "dee": "d", "ee": "e", "eff": "f", "ef": "f",
    "gee": "g", "aitch": "h", "haitch": "h", "jay": "j", "kay": "k", "el": "l", "ell": "l",
    "em": "m", "en": "n", "oh": "o", "pee": "p", "cue": "q", "queue": "q", "ar": "r",
    "ess": "s", "tee": "t", "you": "u", "vee": "v", "ex": "x", "wye": "y", "zed": "z", "zee": "z",
}
# "Q as in queen", "M for mother": a letter given by a word.
_AS_IN = re.compile(r"\b[A-Za-z]\s+(?:as\s+in|for)\s+[A-Za-z]{3,}", re.I)
_SPELL_WORD = re.compile(r"\bspel(?:l|t|led|ling|ls)\b", re.I)
_CORRECTION = re.compile(
    r"\b(?:no|nope|not\s+that|wrong)\b[\s,.!-]*(?:i\s+said|it'?s|i\s+mean|i\s+meant|that'?s|its)\b"
    r"|\bi\s+(?:said|meant)\b|\bi\s+didn'?t\s+say\b"
    r"|\bthat'?s\s+(?:wrong|not\s+(?:it|right|what\s+i\s+said))\b"
    r"|\bwrong\s+(?:name|one|person|order|customer|email|thread)\b"
    r"|\bnot\s+(?:that|him|her|them)\s+one\b",
    re.I,
)
# The same thing said again inside this long is a repeat, and this much alike is the same thing.
REPEAT_WITHIN_S = 120.0
REPEAT_RATIO = 0.75
MIN_SPELLED_LETTERS = 3


def spelled(text: str) -> tuple[int, int]:
    """(runs, letters): the names spelled out letter by letter in what was said.

    A run is three or more letters in a row — "Z O E", "Z-O-E", "zed O E" — with at least two
    of them single letters, so "I see you" is not one; "double L" counts two. "Q as in queen"
    counts a letter each, and two of them make a run."""
    tokens = _TOKEN.findall(text or "")
    runs = letters = 0
    run_letters = run_singles = 0
    i = 0

    def close() -> None:
        nonlocal runs, letters, run_letters, run_singles
        if run_letters >= MIN_SPELLED_LETTERS and run_singles >= 2:
            runs += 1
            letters += run_letters
        run_letters = run_singles = 0

    while i < len(tokens):
        word = tokens[i].lower()
        if word in ",.;:?!":
            close()
        elif len(word) == 1 and word.isalpha():
            run_letters += 1
            run_singles += 1
        elif word == "double" and i + 1 < len(tokens) and len(tokens[i + 1]) == 1 and tokens[i + 1].isalpha():
            run_letters += 2
            run_singles += 1
            i += 1
        elif word in LETTER_WORDS and (run_letters or _single(tokens, i + 1)):
            run_letters += 1
        else:
            close()
        i += 1
    close()
    given = len(_AS_IN.findall(text or ""))
    if given >= 2:
        runs += 1
        letters += given
    return runs, letters


def _single(tokens: list[str], i: int) -> bool:
    """Whether the token at `i` is a single letter: what lets "zed" begin a run ("zed O E")."""
    return i < len(tokens) and len(tokens[i]) == 1 and tokens[i].isalpha()


def similarity(a: str, b: str) -> float:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)


def speech_signals(heard: str, used: str, *, previous: tuple[str, str, float] | None = None,
                   now: float = 0.0) -> dict[str, Any]:
    """What a sentence says about how hard it was to say, in numbers and flags only.

    `heard` is the recogniser's own text (raw), `used` what the turn went on with. `previous`
    is (turn_id, words, when) for the last sentence in the same conversation."""
    said = used or heard or ""
    runs, letters = max(spelled(heard or ""), spelled(used or ""))
    out: dict[str, Any] = {
        "heard_chars": len(heard or ""), "used_chars": len(used or ""),
        "changed": bool(heard and used and heard.strip() != used.strip()),
        "spelled_runs": runs, "spelled_letters": letters,
        "said_spell": bool(_SPELL_WORD.search(said)),
        "correction": bool(_CORRECTION.search(said)),
    }
    if out["changed"]:
        out["similarity"] = similarity(heard, used)
    if previous is not None and said:
        turn, words, when = previous
        ratio = similarity(words, said)
        if now - when <= REPEAT_WITHIN_S and ratio >= REPEAT_RATIO:
            out["repeat_of"], out["repeat_ratio"] = turn, ratio
    return out


# A small vocabulary of requests whose right answer has a known shape, read from the words once.
# Only the key reaches the record.
EXPECT: tuple[tuple[str, re.Pattern], ...] = (
    ("needs_reply", re.compile(
        r"\b(?:need|needs|needing|waiting\s+(?:on|for)|owed?)\b[^.?!]{0,30}\b(?:repl(?:y|ies|ying)|answer(?:s|ing)?|response)\b"
        r"|\b(?:who|what|which)\b[^.?!]{0,25}\b(?:hasn'?t|haven'?t|not)\s+(?:been\s+)?(?:replied|answered)\b"
        r"|\bunanswered\b|\bwaiting\s+on\s+(?:us|me|a\s+reply)\b", re.I)),
    ("bulk", re.compile(
        r"\bbulk\b|\bin\s+one\s+go\b|\ball\s+(?:of\s+)?(?:them|these|those|the\s+\w+)\b|\bevery\s+(?:one|email|order|thread)\b"
        r"|\b(?:select|tick)\s+(?:them\s+)?all\b", re.I)),
    ("close", re.compile(
        r"\b(?:close|clear|dismiss)\b[^.?!]{0,20}\b(?:that|it|this|screen|card)\b|\bput\s+(?:that|it|this)\s+away\b", re.I)),
    ("show_again", re.compile(
        r"\b(?:pull|bring|show|put)\b[^.?!]{0,25}\b(?:up|back)\b[^.?!]{0,10}\bagain\b|\bshow\s+(?:me\s+)?(?:that|it)\s+again\b"
        r"|\bbring\s+(?:it|that)\s+back\b", re.I)),
    ("review", re.compile(
        r"\bwhat(?:'?s|\s+is)\s+on\s+(?:my\s+|the\s+|your\s+)?screen\b"
        r"|\bwhy\s+(?:are|aren'?t|is|isn'?t|did|didn'?t|do|don'?t)\s+(?:you|it|clive)\b[^.?!]{0,25}\bshow"
        r"|\blook\s+at\s+(?:our|the|this)\s+interaction\b|\bwhat\s+(?:are|were)\s+you\s+showing\b", re.I)),
)
# An order number only in the two forms that say it is one: "#1940" and "order 1940" (or "order
# number 1940", "orders 1938 and 1940"). A bare four digits is as often a house number, a year or
# the last four of a card, and none of those is an id the record may hold.
_ORDER_NUMBER = re.compile(r"(?:#\s*|\borders?\s+(?:number\s+|no\.?\s*)?)(\d{3,7})\b(?:\s+and\s+(\d{3,7})\b)?", re.I)


def expectations(question: str) -> list[str]:
    """Which of the known request shapes the words are (zero or more keys)."""
    return [key for key, pattern in EXPECT if pattern.search(question or "")]


def named_orders(question: str) -> list[str]:
    """The order numbers the words name. An order number is an id, which the record may hold."""
    out: list[str] = []
    for match in _ORDER_NUMBER.finditer(question or ""):
        for number in match.groups():
            if number and number not in out:
                out.append(number)
    return out[:6]


# -------------------------------------------------------------------------- the findings

KINDS = ("REPEATED_TAP", "SCREEN_CHANGED_UNASKED", "ACTION_FAILED", "SPELLED_OUT", "LONG_WAIT",
         "UNRELATED_SCENE", "MISSING_CAPABILITY")
SEVERITY = {"ACTION_FAILED": 5, "REPEATED_TAP": 4, "UNRELATED_SCENE": 4, "MISSING_CAPABILITY": 4,
            "SCREEN_CHANGED_UNASKED": 3, "SPELLED_OUT": 3, "LONG_WAIT": 2}

# The owner's own hands on the glass, as the page records them (web/app.js), and the field that
# says which control: the same control is the same kind with the same value.
TAPS: dict[str, tuple[str, ...]] = {
    "tablet_rail_tap": ("action",), "tablet_row_action": ("action",), "tablet_command_tap": ("command",),
    "tablet_action_arm": ("proposal_id",), "tablet_action_commit": ("proposal_id",),
    "tablet_alpha_tap": ("target",), "tablet_tab": ("label", "name"), "tablet_chip_ask": ("name",),
    "tablet_gesture": ("gesture", "proposal_id"), "tablet_action_primed": ("action",),
    "tablet_navigate": ("nav", "name"), "tablet_branch_command": ("action",),
}
# Navigations that are the owner's own taps, as opposed to the page drawing an answer.
OWNER_NAVS = frozenset({"back", "home", "dock", "recent", "set_chip", "stack_chip", "attention_open",
                        "split", "merge", "open_entity", "next", "previous", "restore"})
# The server's own record of the same taps, used only when the page sent none.
SERVER_TAPS: dict[str, tuple[str, ...]] = {"command": ("command",), "row_action": ("action", "operation")}
# Anything that means he asked for what came next: a tap, a hold, a sentence.
ASKING = frozenset({*TAPS, "tablet_turn_submitted", "tablet_hold", "tablet_ask_bar", "tablet_compose_field",
                    "tablet_scroll", "command", "row_action", "turn_started"})
REPEAT_GAP_S = 8.0          # one tap after another this close is the same attempt
REPEAT_MIN = 3              # three of them is a fight
QUICK_REPEAT_S = 2.5        # twice this fast after a refusal is a fight too
ASKED_WINDOW_S = 4.0        # a screen change this soon after a tap was asked for
TURN_SETTLE_S = 4.0         # and this long after a turn's answer arrived
IDLE_CLEAR_S = 25 * 60      # a deck emptied after this long untouched is web/app.js clearing it
RETRY_WITHIN_S = 90.0
LONG_TURN_MS = 8_000
LONG_TOOL_MS = 6_000
LONG_TAP_MS = 4_000
# What counts as a refusal or a failure, by event.
_FAILED_CODES = frozenset({"failed", "refused", "stale", "unverified", "service_unavailable", "expired",
                           "not_held", "error", "denied", "timeout", "unknown"})


@dataclass
class Finding:
    kind: str
    at: float
    what: str
    easier: str
    turn_id: str = ""
    count: int = 1
    evidence: list[dict[str, Any]] = field(default_factory=list)
    # Its own weight, when it is not its kind's (SEVERITY): a request the page made in the
    # background that failed on every turn — the voice with no credit — is said once, lower down.
    weight: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "at": round(self.at, 3), "turn_id": self.turn_id or None, "count": self.count,
                "what": self.what, "easier": self.easier, "evidence": self.evidence[:8]}


def _ts(event: dict[str, Any]) -> float:
    """When it happened. The page posts its account in batches every couple of seconds, so a
    page event's own clock (`t`, milliseconds) says when the finger moved; the Mac's `ts` says
    only when the batch arrived."""
    t = event.get("t")
    if event.get("source") == "tablet" and isinstance(t, (int, float)) and not isinstance(t, bool) and t > 1e12:
        return float(t) / 1000.0
    try:
        return float(event.get("ts") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ref(event: dict[str, Any]) -> dict[str, Any]:
    """An event, as evidence: its kind, its time and its ids. Never a word of what it carried."""
    out: dict[str, Any] = {"kind": str(event.get("kind") or ""), "at": round(_ts(event), 3)}
    for key in ("turn_id", "proposal_id", "batch_id", "action", "command", "operation", "tool", "code",
                "outcome", "status", "nav", "target", "gesture"):
        value = event.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            out[key] = value if not isinstance(value, str) else value[:60]
    return out


def _turn_at(turns: list[dict[str, Any]], at: float) -> str:
    """The turn whose answer last arrived at or before `at` (or the first, before any)."""
    best = ""
    for turn in turns:
        if _ts(turn) <= at + 0.5:
            best = str(turn.get("turn_id") or "")
    return best


def find(events: list[dict[str, Any]]) -> list[Finding]:
    """Every finding over these events, most severe first and, within a kind, in time order."""
    events = sorted((e for e in events if isinstance(e, dict)), key=_ts)
    turns = [e for e in events if e.get("kind") == "interaction_turn"]
    found: list[Finding] = []
    for rule in (_repeated_taps, _unasked_changes, _failures, _spelling, _waits, _scenes, _missing):
        try:
            found.extend(rule(events, turns))
        except Exception:  # noqa: BLE001 — one rule that cannot read the record never hides the rest
            continue
    for finding in found:
        if not finding.turn_id:
            finding.turn_id = _turn_at(turns, finding.at)
    found.sort(key=lambda f: (-(f.weight or SEVERITY.get(f.kind, 1)), f.at))
    return found


# ---- the rules


def _tap_key(event: dict[str, Any], fields: tuple[str, ...]) -> str:
    kind = str(event.get("kind") or "")
    if kind == "tablet_navigate" and str(event.get("nav") or "") not in OWNER_NAVS:
        return ""
    parts = [str(event.get(f) or "") for f in fields]
    return f"{kind}:{'/'.join(parts)}" if any(parts) else ""


# One tap the page writes down twice — a tab is recorded by the card's own handler and by the
# deck's (web/app.js `noteTab` and the delegated click) — lands inside this: one tap.
SAME_TAP_S = 0.15


def _taps(events: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    page: list[tuple[str, dict[str, Any]]] = []
    last: dict[str, float] = {}
    for event in events:
        key = _tap_key(event, TAPS.get(str(event.get("kind") or ""), ()))
        if not key:
            continue
        kind = str(event.get("kind") or "")
        if kind in last and 0 <= _ts(event) - last[kind] <= SAME_TAP_S:
            continue
        last[kind] = _ts(event)
        page.append((key, event))
    if page:
        return page
    return [(k, e) for e in events if (k := _tap_key(e, SERVER_TAPS.get(str(e.get("kind") or ""), ())))]


def owner_taps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """His own taps, each once: the page's account when it sent one, else the Mac's."""
    return [event for _key, event in _taps(sorted((e for e in events if isinstance(e, dict)), key=_ts))]


def _refused(event: dict[str, Any]) -> bool:
    outcome = str(event.get("outcome") or "").lower()
    code = str(event.get("code") or "").lower()
    status = event.get("status")
    return (outcome in ("refused", "unreachable", "blocked_busy", "blocked_by_live_card", "no_token")
            or code in _FAILED_CODES or event.get("ok") is False
            or (isinstance(status, int) and status >= 400) or str(event.get("state") or "") == "disabled")


def _repeated_taps(events, _turns) -> list[Finding]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, event in _taps(events):
        by_key[key].append(event)
    out: list[Finding] = []
    for key, taps in by_key.items():
        run: list[dict[str, Any]] = []
        for tap in taps + [None]:
            if tap is not None and run and _ts(tap) - _ts(run[-1]) <= REPEAT_GAP_S:
                run.append(tap)
                continue
            quick = len(run) == 2 and _refused(run[0]) and _ts(run[1]) - _ts(run[0]) <= QUICK_REPEAT_S
            if len(run) >= REPEAT_MIN or quick:
                out.append(_tap_finding(key, run))
            run = [tap] if tap is not None else []
    return out


def _tap_finding(key: str, run: list[dict[str, Any]]) -> Finding:
    kind, _, control = key.partition(":")
    refused = sum(1 for e in run if _refused(e))
    seconds = _ts(run[-1]) - _ts(run[0])
    label = control.split("/")[0] or kind.removeprefix("tablet_")
    if kind == "tablet_tab":
        # A tab's label is the page's own words, kept by its shape: it is named by its card.
        label = f"a tab on the {str(run[0].get('name') or 'card').replace('_', ' ')} card"
    what = (f"{label} was tapped {len(run)} times in {seconds:.1f} s"
            + (f"; {refused} of them were refused or did nothing" if refused else ""))
    return Finding("REPEATED_TAP", _ts(run[0]), what, _easier_for_taps(label, len(run), refused),
                   turn_id=str(run[0].get("turn_id") or ""), count=len(run), evidence=[_ref(e) for e in run])


def _bulk_for(action_id: str) -> list[dict[str, str]]:
    """The bulk tools that make the same change as one row's action, from the registries."""
    try:
        from app.actions.rows import ROW_ACTIONS
        from app.tools import registry

        row = ROW_ACTIONS.get(action_id)
        child = row.tool if row is not None else action_id
        return [{"tool": s.name, "operation": s.batch.operation, "needs": "a working set of " + "/".join(s.batch.set_kinds)}
                for s in registry.all_specs() if s.batch is not None and s.batch.child_tool == child]
    except Exception:  # noqa: BLE001 — no registry to read: no bulk tool to name
        return []


def _easier_for_taps(label: str, taps: int, refused: int) -> str:
    bulk = _bulk_for(label)
    if bulk:
        tool = bulk[0]
        return (f"One {tool['tool']} on the whole list ({tool['needs']}) would have been one hold instead of "
                f"{taps} taps on {label}: ask for them all at once and CLIVE stages the bulk card.")
    if refused:
        return f"The {label} control should have said why it would not work on the first tap, or not been offered."
    return f"One tap on {label} should have been enough: it needs to show at once that it heard the tap and what it is doing."


def _cards_of(event: dict[str, Any]) -> tuple[str, ...]:
    cards = event.get("cards") if isinstance(event.get("cards"), list) else []
    out = []
    for card in cards:
        if isinstance(card, dict):
            out.append(f"{card.get('type') or ''}:{card.get('ref') or card.get('proposal_id') or ''}")
    return tuple(out)


def _unasked_changes(events, _turns) -> list[Finding]:
    """A render whose cards differ from the render before it, with nothing asked for it: no tap
    or hold just before, and no turn in flight (submitted and not yet answered, or answered
    moments ago)."""
    out: list[Finding] = []
    last_cards: tuple[str, ...] | None = None
    last_ask = -1e18
    in_flight = 0
    answered_at = -1e18
    for event in events:
        kind = str(event.get("kind") or "")
        at = _ts(event)
        if kind == "tablet_turn_submitted":
            in_flight += 1
        elif kind in ("tablet_turn_response", "tablet_turn_failed", "tablet_turn_cancelled"):
            in_flight = max(0, in_flight - 1)
            answered_at = at
        if kind in ASKING and (kind != "tablet_navigate" or str(event.get("nav") or "") in OWNER_NAVS):
            last_ask = at
            continue
        if kind != "tablet_render" or not isinstance(event.get("cards"), list):
            continue
        cards = _cards_of(event)
        idle_clear = not cards and at - last_ask >= IDLE_CLEAR_S   # the deck's own half-hour clear
        if last_cards is not None and cards != last_cards and not in_flight and not idle_clear \
                and at - last_ask > ASKED_WINDOW_S and at - answered_at > TURN_SETTLE_S:
            gone = [c for c in last_cards if c not in cards]
            came = [c for c in cards if c not in last_cards]
            what = (f"the screen changed with nothing asked: {len(gone)} card(s) went"
                    f"{' (' + ', '.join(c.split(':')[0] for c in gone[:3]) + ')' if gone else ''} and {len(came)} came"
                    f"{' (' + ', '.join(c.split(':')[0] for c in came[:3]) + ')' if came else ''}")
            out.append(Finding("SCREEN_CHANGED_UNASKED", at, what,
                               "The screen should have stayed as it was until he asked: a background update "
                               "should patch the card in place, never replace what he is looking at.",
                               evidence=[_ref(event)]))
        last_cards = cards
    return out


def _failure_key(event: dict[str, Any]) -> str:
    for key in ("proposal_id", "action", "command", "operation", "tool", "path"):
        value = event.get(key)
        if value:
            return f"{key}:{value}"
    return str(event.get("kind") or "")


def _is_failure(event: dict[str, Any]) -> bool:
    kind = str(event.get("kind") or "")
    if kind in ("action_arm_refused", "action_commit_refused", "batch_arm_refused", "batch_commit_refused",
                "tablet_turn_failed", "tablet_http_error", "tablet_context_failed", "tablet_action_stale_affordance",
                "tablet_action_watchdog", "tablet_exception"):
        return True
    if kind in ("tablet_row_action", "tablet_action_arm", "tablet_action_commit", "tablet_command_tap",
                "command", "row_action", "action_commit", "tablet_compose_field"):
        return _refused(event)
    if kind.startswith("action_") or kind.startswith("batch_"):
        return str(event.get("code") or "").lower() in _FAILED_CODES or str(event.get("status") or "").upper() in ("FAILED", "REFUSED")
    if kind == "tool_finished":
        return event.get("ok") is False and str(event.get("outcome") or "") not in ("staged",)
    return False


# The page's account of a refusal and the Mac's own arrive this close together: one refusal. Two
# from the same side are two attempts, however close.
ECHO_S = 3.0


def _source(event: dict[str, Any]) -> str:
    return "tablet" if str(event.get("kind") or "").startswith("tablet_") else "mac"


def _failures(events, _turns) -> list[Finding]:
    """Each failure once (the page's and the Mac's account of it folded together), with what
    came after it: the same thing tried again and refused again is RETRIED; tried again and
    gone through says so."""
    out: list[Finding] = []
    open_: dict[str, Finding] = {}
    last_at: dict[str, float] = {}
    last_from: dict[str, str] = {}
    background: dict[str, Finding] = {}
    for event in events:
        key = _failure_key(event)
        at = _ts(event)
        if str(event.get("kind") or "") == "tablet_http_error" and _is_failure(event):
            # A request the page makes by itself (the voice, a poll): one finding for the window,
            # however many turns it failed on, so it never buries what he did.
            held = background.get(key)
            if held is None:
                what, easier = _failure_words(event)
                held = background[key] = Finding("ACTION_FAILED", at, what, easier, turn_id=str(event.get("turn_id") or ""),
                                                 evidence=[_ref(event)], weight=2)
                out.append(held)
            else:
                held.count += 1
                held.evidence.append(_ref(event))
                held.what = f"{_failure_words(event)[0]}, {held.count} times in this window"
            continue
        finding = open_.get(key)
        if not _is_failure(event):
            if finding is not None and str(event.get("kind") or "") in TAPS and at - last_at[key] > ECHO_S \
                    and at - finding.at <= RETRY_WITHIN_S:
                finding.count += 1
                finding.evidence.append(_ref(event))
                finding.what += "; tried again, and that time it went through"
                open_.pop(key, None)
            continue
        if finding is not None and at - last_at[key] <= ECHO_S and last_from[key] not in ("", _source(event)):
            finding.evidence.append(_ref(event))
            last_at[key], last_from[key] = at, ""      # paired: the next one is a new attempt
            continue
        if finding is not None and at - finding.at <= RETRY_WITHIN_S:
            finding.count += 1
            finding.evidence.append(_ref(event))
            last_at[key], last_from[key] = at, _source(event)
            if "retried" not in finding.what:
                finding.what += "; tried again and refused again (retried)"
            continue
        what, easier = _failure_words(event)
        finding = Finding("ACTION_FAILED", at, what, easier, turn_id=str(event.get("turn_id") or ""),
                          evidence=[_ref(event)])
        open_[key] = finding
        last_at[key], last_from[key] = at, _source(event)
        out.append(finding)
    return out


def _failure_words(event: dict[str, Any]) -> tuple[str, str]:
    kind = str(event.get("kind") or "")
    name = str(event.get("action") or event.get("operation") or event.get("command") or event.get("tool")
               or event.get("path") or kind.removeprefix("tablet_"))
    code = str(event.get("code") or event.get("outcome") or event.get("status") or "").strip()
    what = f"{name} {'was refused' if 'refused' in kind or 'refused' in code else 'failed'}" + (f" ({code})" if code else "")
    if kind == "tool_finished":
        return what, "Say once, in a few words, what failed and offer the way that works; never leave a blank screen."
    if kind == "tablet_turn_failed":
        return what, "The page lost the answer: it should say so where he is looking and keep the question to send again."
    if kind == "tablet_http_error":
        return what, "A request the page made failed: it should say so once where he is looking, not leave him waiting."
    return what, "Say why at the control, once, and offer what would work instead of letting the same tap fail again."


def _spelling(_events, turns) -> list[Finding]:
    out: list[Finding] = []
    for turn in turns:
        speech = turn.get("speech") if isinstance(turn.get("speech"), dict) else {}
        runs, letters = int(speech.get("spelled_runs") or 0), int(speech.get("spelled_letters") or 0)
        parts = []
        if runs:
            parts.append(f"{runs} name(s) spelled out, {letters} letters")
        if speech.get("correction"):
            parts.append("a correction (\"no, I said…\")")
        if speech.get("repeat_of"):
            parts.append(f"said again after {speech.get('repeat_of')} ({float(speech.get('repeat_ratio') or 0):.0%} the same)")
        if not parts:
            continue
        out.append(Finding(
            "SPELLED_OUT", _ts(turn), "; ".join(parts),
            "Offer the names already in play (this order's customer, the customers just read) to tap, and "
            "look a spoken name up by how it sounds, so a name never has to be spelled letter by letter.",
            turn_id=str(turn.get("turn_id") or ""), count=max(1, runs), evidence=[_ref(turn)]))
    return out


def _waits(events, turns) -> list[Finding]:
    out: list[Finding] = []
    for turn in turns:
        ms = turn.get("ms") if isinstance(turn.get("ms"), dict) else {}
        total = ms.get("total")
        if not isinstance(total, (int, float)) or total < LONG_TURN_MS:
            continue
        slowest = ms.get("slowest_tool") if isinstance(ms.get("slowest_tool"), dict) else {}
        read_ms = float(slowest.get("ms") or 0.0)
        parts = [(name, float(ms[key])) for key, name in (("agent", "the model and its reads"), ("transcribe", "hearing it"))
                 if isinstance(ms.get(key), (int, float))]
        what = f"he waited {total / 1000:.1f} s for the answer"
        if slowest.get("tool") and read_ms >= 0.4 * total:
            what += f"; most of it was the read {slowest['tool']} ({read_ms / 1000:.1f} s)"
        elif parts:
            name, part_ms = max(parts, key=lambda kv: kv[1])
            what += f"; most of it was {name} ({part_ms / 1000:.1f} s)"
            if slowest.get("tool"):
                what += f", the slowest read {slowest['tool']} at {read_ms / 1000:.1f} s"
        first = ms.get("first_card")
        easier = ("Put the first useful card up as soon as its read lands and fill the rest in place"
                  + (f" (the first card came at {first / 1000:.1f} s)." if isinstance(first, (int, float)) else "."))
        out.append(Finding("LONG_WAIT", _ts(turn), what, easier, turn_id=str(turn.get("turn_id") or ""), evidence=[_ref(turn)]))
    for event in events:
        kind = str(event.get("kind") or "")
        ms = event.get("ms")
        if not isinstance(ms, (int, float)):
            continue
        if kind == "tool_finished" and ms >= LONG_TOOL_MS and not any(f.turn_id and f.turn_id == event.get("turn_id") for f in out):
            out.append(Finding("LONG_WAIT", _ts(event), f"{event.get('tool')} took {ms / 1000:.1f} s",
                               "A read this slow should show its card shell at once and fill in when it lands.",
                               turn_id=str(event.get("turn_id") or ""), evidence=[_ref(event)]))
        elif kind in ("tablet_action_commit", "command", "tablet_compose_field") and ms >= LONG_TAP_MS:
            out.append(Finding("LONG_WAIT", _ts(event), f"a tap on {event.get('command') or kind.removeprefix('tablet_')} took {ms / 1000:.1f} s to answer",
                               "A tap should answer at once and show the work under way.", evidence=[_ref(event)]))
    return out


def _types(turn: dict[str, Any]) -> list[str]:
    return [str(c.get("type") or "") for c in (turn.get("cards") or []) if isinstance(c, dict)]


def _scenes(_events, turns) -> list[Finding]:
    out: list[Finding] = []
    for turn in turns:
        expect = set(turn.get("expect") or [])
        cards = [c for c in (turn.get("cards") or []) if isinstance(c, dict) and not c.get("kept")]
        types = [str(c.get("type") or "") for c in cards]
        tools = {str(t.get("tool") or "") for t in (turn.get("tools") or []) if isinstance(t, dict)}
        at, ident = _ts(turn), str(turn.get("turn_id") or "")
        if "needs_reply" in expect and types:
            marked = any("reply_state" in (c.get("marks") or []) or c.get("type") in ("reply_state", "summary_list") for c in cards)
            if not marked:
                shown = ", ".join(sorted(set(types)))
                out.append(Finding("UNRELATED_SCENE", at, f"asked for the reply queue (needs_reply); shown {shown} with no reply state on it",
                                   "Answer from the inbox's reply state (email_query's needs-reply queue): who is waiting, "
                                   "longest first, not a plain list of emails.", turn_id=ident, evidence=[_ref(turn)]))
        if "close" in expect and turn.get("screen") != "cleared" and "close_screen" not in tools:
            out.append(Finding("UNRELATED_SCENE", at, "asked for the screen to close (close); it stayed up",
                               "close_screen takes it away; the answer should have called it.", turn_id=ident, evidence=[_ref(turn)]))
        if "review" in expect and "interaction_review" not in tools:
            out.append(Finding("UNRELATED_SCENE", at, "asked about the screen or the interaction (review) and answered without reading the record",
                               "interaction_review says what was drawn and why; an answer from memory can vary.",
                               turn_id=ident, evidence=[_ref(turn)]))
        named = set(turn.get("named_orders") or [])
        drawn = {str(n) for c in cards for n in (c.get("numbers") or [])}
        if named and drawn and not (named & drawn):
            out.append(Finding("UNRELATED_SCENE", at, f"asked about order {', '.join(sorted(named))}; shown {', '.join(sorted(drawn))}",
                               "Draw the order he named, or say plainly that it could not be found.", turn_id=ident, evidence=[_ref(turn)]))
    return out


def _missing(events, turns) -> list[Finding]:
    out: list[Finding] = []
    for turn in turns:
        expect = set(turn.get("expect") or [])
        tools = {str(t.get("tool") or "") for t in (turn.get("tools") or []) if isinstance(t, dict)}
        types = set(_types(turn))
        if "bulk" in expect and not (types & {"batch_action", "batch_result", "working_set"}) \
                and not any(t.startswith("batch_") for t in tools):
            out.append(Finding("MISSING_CAPABILITY", _ts(turn), "asked for a bulk change (bulk); no bulk card was drawn",
                               _bulk_words(), turn_id=str(turn.get("turn_id") or ""), evidence=[_ref(turn)]))
        elif turn.get("declined"):
            out.append(Finding("MISSING_CAPABILITY", _ts(turn), "CLIVE said it could not do what was asked",
                               "If a tool can do it, CLIVE should have used it; if none can, it is a build to file.",
                               turn_id=str(turn.get("turn_id") or ""), evidence=[_ref(turn)]))
    for event in events:
        if str(event.get("kind") or "") != "unsupported_claim":
            continue
        caps = [str(c) for c in (event.get("capabilities") or []) if c]
        if event.get("false_unsupported"):
            out.append(Finding("MISSING_CAPABILITY", _ts(event), f"CLIVE said it could not ({', '.join(caps) or 'a request'}), and it can",
                               "The tools exist: the answer should have used them rather than declining.",
                               turn_id=str(event.get("turn_id") or ""), evidence=[_ref(event)]))
    return _one_per_turn(out)


def _one_per_turn(found: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str]] = set()
    out = []
    for finding in found:
        key = (finding.turn_id, finding.what)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def _bulk_words() -> str:
    try:
        from app.tools import registry

        bulk = [s.name for s in registry.all_specs() if s.batch is not None]
    except Exception:  # noqa: BLE001
        bulk = []
    if not bulk:
        return "There is no bulk tool for this yet: it is a build to file."
    return ("A bulk change is drawn as one card under one hold when CLIVE stages it with a batch tool ("
            + ", ".join(bulk[:6]) + ") on a working set; a list's rows only carry one-row actions.")


# ----------------------------------------------------------------------- spelling, measured


def speech_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    """How often names were spelled out or corrected, from the record: what the speech fix is
    measured against. Counts only."""
    turns = [e for e in events if isinstance(e, dict) and e.get("kind") == "interaction_turn"]
    voice = [t for t in turns if t.get("via") == "audio"]
    spelled_turns = [t for t in turns if int(((t.get("speech") or {}).get("spelled_runs")) or 0) > 0]
    corrections = [t for t in turns if (t.get("speech") or {}).get("correction")]
    repeats = [t for t in turns if (t.get("speech") or {}).get("repeat_of")]
    changed = [t for t in voice if (t.get("speech") or {}).get("changed")]
    letters = sum(int(((t.get("speech") or {}).get("spelled_letters")) or 0) for t in turns)
    return {
        "turns": len(turns), "voice_turns": len(voice), "spelled_turns": len(spelled_turns),
        "letters_spelled": letters, "corrections": len(corrections), "said_again": len(repeats),
        "recogniser_rewrote": len(changed),
        "spelled_share": round(len(spelled_turns) / len(turns), 3) if turns else 0.0,
        "spelled_in": [str(t.get("turn_id") or "") for t in spelled_turns][:12],
    }
