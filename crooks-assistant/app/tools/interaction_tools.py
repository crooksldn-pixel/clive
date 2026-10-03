"""CLIVE looking at its own interaction: "what's on screen?", "why aren't you showing me bulk
actions?", "look at our interaction and see how that happened".

George, 2 October 2026: "I could ask him what's on screen, but his answer can vary." It varied
because the model answered from its memory of the conversation. This tool answers from what was
DRAWN: the Mac's own copy of each half's screen, word for word (app/screen.py), and the
interaction record (app/observability/interactions.py) — every recent turn's cards, which tool
drew each, the rule that chose the screen, the taps and holds, what failed, how long each step
took — with the friction in it found mechanically (app/observability/friction.py) and, for each,
what would have been easier.

`about` is what he is asking after, in his words ("bulk actions", "the archive button"): the
answer says whether it is on the screen now and where, which of CLIVE's tools do it and what
card each draws, whether any turn in the window called one, and so why it is not up.

`excerpt` is the same account with nothing a person said or is called in it — ids, kinds,
counts, clocks and the product's own words — for a build request. Filing stays where it is: the
model files with submit_engineering_request, and nothing is filed until the owner holds the card.

A read of CLIVE's own records on this machine: it reaches no store, inbox, screen or message and
stages nothing. Off (CROOKS_INTERACTION_RECORD=false), it still says what is on the screen now,
and says plainly that nothing before now was recorded.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from app.capabilities.families import CapabilityFamily, register
from app.observability import friction, interactions
from app.observability.timeline import scrub_text
from app.tools.context import current_session
from app.tools.gate import Tier
from app.tools.registry import tool

REVIEW_TOOL = "interaction_review"
DEFAULT_MINUTES = 15
MAX_MINUTES = 240
MAX_TURNS = 8
MAX_FINDINGS = 12
MAX_EXCERPT_CHARS = 6_000

# Named in the family table like every tool the model is offered (tests/test_families.py).
register(CapabilityFamily(
    key="self_review", label="Look at our interaction", area="system",
    what="say what is on your screen word for word, why each screen was shown, and where our interaction fought you",
    tools=(REVIEW_TOOL,),
    state="READY", detail="ready",
))


@tool(
    name=REVIEW_TOOL,
    description=(
        "What is on the owner's screen now, word for word as drawn; why each recent screen was shown; and "
        "the friction in the interaction (repeated taps, failures, unasked screen changes, spelling, waits, "
        "wrong scene, missing capability) with what would have been easier. For 'what's on screen', 'why "
        "aren't you showing me X' (about X), 'look at our interaction'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "minutes": {"type": "integer", "minimum": 1, "maximum": MAX_MINUTES},
            "about": {"type": "string", "maxLength": 120},
        },
    },
    tier=Tier.GREEN,
    timeout_s=10.0,
)
async def interaction_review(minutes: int = DEFAULT_MINUTES, about: str = "") -> dict[str, Any]:
    session = current_session()
    minutes = max(1, min(MAX_MINUTES, int(minutes or DEFAULT_MINUTES)))
    out: dict[str, Any] = {"on_screen": interactions.on_screen(session) or "no conversation is open, so nothing is drawn"}
    record = interactions.current()
    if record is None:
        out["record"] = ("off on this server (CROOKS_INTERACTION_RECORD=false): only what is on the screen now can "
                         "be said; nothing before it was recorded")
        if about:
            out["about"] = _about(about, out["on_screen"], [], [])
        return out
    session_id = str(getattr(session, "session_id", "") or "")
    said = {t.get("turn_id"): t for t in record.recent.turns(session_id)} if session_id else {}
    # Reading the files and finding the friction are the slow part of a busy day: off the loop.
    out.update(await asyncio.to_thread(_looked, record, session_id, said, minutes, about, out["on_screen"]))
    out["to_file"] = ("if he agrees it should be fixed: engineering_status with areas true, then "
                      "submit_engineering_request with this excerpt in requested_outcome; he holds the card to file it")
    return out


def _looked(record: Any, session_id: str, said: dict[str, Any], minutes: int, about: str,
            on_screen: Any) -> dict[str, Any]:
    """Everything the record says about this conversation's window, in one pass off the event
    loop: its turns, what the tablet drew, the friction, the speech, the excerpt."""
    events, cut = record.look(minutes=minutes)
    mine = [e for e in events if not e.get("session_id") or e.get("session_id") == session_id]
    turns = [e for e in mine if e.get("kind") == "interaction_turn"]
    found = friction.find(mine)
    out: dict[str, Any] = {"turns": [_turn(t, said.get(t.get("turn_id"))) for t in turns[-MAX_TURNS:]]}
    tablet = interactions.tablet_said(mine)
    if tablet is not None:
        out["tablet_last_drew"] = tablet
    out["friction"] = [_finding(f) for f in found[:MAX_FINDINGS]] or "none found in this window"
    speech = friction.speech_report(mine)
    if speech["turns"]:
        out["speech"] = speech
    if about:
        out["about"] = _about(about, on_screen, turns, mine)
    out["excerpt"] = excerpt(mine, found, minutes=minutes, cut=cut)
    out["record"] = {"on": True, "window_minutes": minutes, "events": len(mine), "turns": len(turns), **record.bounds}
    if cut is not None:
        # A busy day: the window reaches back further than one look reads, and that is said.
        out["record"]["cut_short"] = (f"a busy day: only what happened since {_clock(cut)} was read, not the whole "
                                      f"{minutes} minutes asked for")
    return out


# --------------------------------------------------------------------------- one turn, said


def _clock(ts: Any) -> str:
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OverflowError):
        return ""


def _turn(event: dict[str, Any], words: dict[str, Any] | None) -> dict[str, Any]:
    """One turn as the record holds it, with the words from memory where this process still has
    them (what was asked and heard, the cards' titles and what they showed)."""
    out: dict[str, Any] = {"turn_id": event.get("turn_id"), "at": _clock(event.get("ts")), "via": event.get("via")}
    if words:
        out["asked"] = words.get("question") or ""
        if words.get("heard") and words.get("heard") != words.get("question"):
            out["heard"] = words.get("heard")
    else:
        asked = event.get("asked") if isinstance(event.get("asked"), dict) else {}
        out["asked"] = f"({asked.get('words', 0)} words; the record keeps them by their shape)"
    if event.get("expect"):
        out["asked_for"] = event.get("expect")
    out["tools"] = [f"{t.get('tool')}{'' if t.get('ok') else ' (failed)'}{' (staged)' if t.get('staged') else ''}"
                    for t in (event.get("tools") or []) if isinstance(t, dict)]
    why = event.get("why") if isinstance(event.get("why"), dict) else {}
    out["screen"] = event.get("screen")
    out["why"] = why.get("says") or ""
    for key in ("read_for_words", "staged", "claim_repair", "withheld", "drew_nothing"):
        if why.get(key):
            out[key] = why[key]
    if isinstance(why.get("workspace"), dict) and why["workspace"].get("says"):
        out["why_workspace"] = why["workspace"]["says"]
    cards = [c for c in (event.get("cards") or []) if isinstance(c, dict)]
    drawn = (words or {}).get("cards") or []
    out["cards"] = []
    for index, card in enumerate(cards):
        said = drawn[index] if index < len(drawn) and isinstance(drawn[index], dict) else {}
        entry = {"type": card.get("type"), "drawn_by": card.get("drawn_by") or []}
        if said.get("title"):
            entry["title"] = said["title"]
        for key in ("rows", "numbers", "marks", "kept", "refreshed", "tab"):
            if card.get(key):
                entry[key] = card[key]
        if card.get("actions"):
            entry["controls"] = card["actions"]
        out["cards"].append(entry)
    speech = event.get("speech") if isinstance(event.get("speech"), dict) else {}
    flags = {k: speech[k] for k in ("spelled_runs", "spelled_letters", "correction", "repeat_of", "changed") if speech.get(k)}
    if flags:
        out["speech"] = flags
    ms = event.get("ms") if isinstance(event.get("ms"), dict) else {}
    if ms:
        out["ms"] = ms
    if event.get("error_kind"):
        out["error"] = event.get("error_kind")
    return out


def _finding(found: friction.Finding) -> dict[str, Any]:
    out = found.as_dict()
    out["at"] = _clock(found.at)
    out["evidence"] = [{k: v for k, v in e.items() if k != "at"} for e in out["evidence"][:4]]
    return out


# -------------------------------------------------------------- "why aren't you showing me X"

_STOP = frozenset({"the", "and", "you", "your", "me", "my", "aren", "isn", "not", "why", "show", "showing", "shown",
                   "what", "with", "for", "that", "this", "button", "buttons", "option", "options", "screen", "thing"})
# Words the owner uses for a kind of capability the registry names otherwise.
_BULK = frozenset({"bulk", "batch", "all", "everything", "mass", "multi", "multiple", "every", "select"})
# Words that name no capability by themselves: "bulk actions" is every bulk tool.
_GENERIC = frozenset({"action", "change", "edit", "control", "tool", "way", "feature", "function"})


def _terms(about: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z]+", (about or "").lower()) if len(w) >= 3 and w not in _STOP]
    return [w[:-1] if w.endswith("s") and len(w) > 4 else w for w in words][:8]


def _about(about: str, on_screen: Any, turns: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether what he asked after is on the screen, which tools do it and what each draws, and
    whether any turn in the window called one — so the answer to "why not" is read, not guessed."""
    from app.tools import registry

    terms = _terms(about)
    bulk = bool(set(terms) & _BULK)
    specific = [t for t in terms if t not in _BULK and t not in _GENERIC]
    out: dict[str, Any] = {"asked_after": about[:120]}
    offered = []
    for half in on_screen if isinstance(on_screen, list) else []:
        for card in half.get("cards") or []:
            if bulk and card.get("type") in ("batch_action", "batch_result"):
                offered.append({"half": half.get("half"), "card": card.get("type"), "title": card.get("title", "")})
            for action in card.get("actions") or []:
                text = f"{action.get('control', '')} {action.get('label', '')}".lower()
                if (not bulk and any(t in text for t in specific)) or (bulk and "batch" in text):
                    offered.append({"half": half.get("half"), "card": card.get("type"), **action})
    out["on_screen_now"] = offered or "not on the screen now"
    tools = []
    for spec in registry.all_specs():
        text = f"{spec.name} {spec.description}".lower()
        if bulk:
            matched = spec.batch is not None and (not specific or any(t in text for t in specific))
        else:
            matched = bool(specific) and any(t in text for t in specific)
        if not matched:
            continue
        entry: dict[str, Any] = {"tool": spec.name, "what": spec.description.split(". ")[0][:160]}
        if spec.batch is not None:
            entry["draws"] = "a batch_action card: one hold applies it to every member"
            entry["needs"] = "a working set of " + "/".join(spec.batch.set_kinds) + " (a listing read makes one)"
        elif spec.write is not None:
            entry["draws"] = "a confirmation card the owner holds to apply"
        tools.append(entry)
    out["tools_that_do_it"] = tools[:8] or "no tool CLIVE has does this: it is a gap, and a build to file"
    called = {str(t.get("tool") or "") for turn in turns for t in (turn.get("tools") or []) if isinstance(t, dict)}
    used = [t["tool"] for t in tools if t["tool"] in called]
    out["called_in_window"] = used or "no turn in this window called any of them, so none of their cards was drawn"
    rows = [c for half in (on_screen if isinstance(on_screen, list) else []) for c in half.get("cards") or []
            if any(a.get("on_rows") for a in c.get("actions") or [])]
    if bulk and rows:
        out["note"] = ("the list on the screen carries one-row actions only; a bulk change is its own card, drawn "
                       "when CLIVE stages it with a batch tool on a working set")
    return out


# --------------------------------------------------------------- the excerpt for a build


def excerpt(events: list[dict[str, Any]], found: list[friction.Finding], *, minutes: int, cut: float | None = None) -> str:
    """The window as a build request may carry it: turn by turn, the request shape, the tools,
    the cards drawn and why, the times; then each finding and the easier way. Ids, kinds,
    counts, clocks and the product's own words — never what was said or anyone's name — and
    scrubbed again by the timeline's rule on the way out. A window cut short says so."""
    turns = [e for e in events if e.get("kind") == "interaction_turn"]
    taps = len(friction.owner_taps(events))
    span = f"since {_clock(cut)} (a busy day: not the whole {minutes} minutes)" if cut is not None else f"the last {minutes} minutes"
    lines = [f"Interaction excerpt from CLIVE's interaction record: {span}, "
             f"{len(turns)} turn(s), {taps} tap(s). No words said and no names: ids, kinds, counts and times."]
    for turn in turns[-MAX_TURNS:]:
        why = turn.get("why") if isinstance(turn.get("why"), dict) else {}
        cards = [c for c in (turn.get("cards") or []) if isinstance(c, dict)]
        drew = "; ".join(_card_line(c) for c in cards) or "no card"
        tools = ", ".join(f"{t.get('tool')}{'' if t.get('ok') else ' FAILED'}" for t in (turn.get("tools") or []) if isinstance(t, dict)) or "none"
        total = (turn.get("ms") or {}).get("total") if isinstance(turn.get("ms"), dict) else None
        lines.append(
            f"- {turn.get('turn_id')} at {_clock(turn.get('ts'))} by {turn.get('via')}"
            + (f", asked for {'/'.join(turn.get('expect') or [])}" if turn.get("expect") else "")
            + f": tools {tools}; drew {drew}; screen {turn.get('screen')} ({why.get('says') or 'no rule recorded'})"
            + (f"; workspace: {why['workspace'].get('says')}" if isinstance(why.get("workspace"), dict) else "")
            + (f"; {_took(total)}" if isinstance(total, (int, float)) else ""))
    if found:
        lines.append("Friction:")
        for finding in found[:MAX_FINDINGS]:
            lines.append(f"- {finding.kind} at {_clock(finding.at)}{' in ' + finding.turn_id if finding.turn_id else ''}: "
                         f"{finding.what}. Easier: {finding.easier}")
    else:
        lines.append("Friction: none found mechanically in this window.")
    text = scrub_text("\n".join(lines))
    return text if len(text) <= MAX_EXCERPT_CHARS else text[:MAX_EXCERPT_CHARS] + "…"


def _took(ms: float) -> str:
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def _card_line(card: dict[str, Any]) -> str:
    parts = [str(card.get("type") or "card")]
    if card.get("rows"):
        parts.append(f"{card['rows']} rows")
    if card.get("numbers"):
        parts.append("#" + ",#".join(str(n) for n in card["numbers"][:3]))
    if card.get("drawn_by"):
        parts.append("by " + "+".join(str(t) for t in card["drawn_by"][:3]))
    controls = [str(a.get("control") or "") + ("" if a.get("enabled", True) else " (off)") for a in card.get("actions") or [] if isinstance(a, dict)]
    if controls:
        parts.append("controls " + ",".join(controls[:6]))
    if card.get("kept"):
        parts.append("kept")
    return " ".join(parts)
