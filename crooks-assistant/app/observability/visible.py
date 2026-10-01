"""The other outcome: what the owner could see (§17).

The report of the live hour said **11 of 14 turns successful**. During that hour the owner
said out loud that the split was broken, that the applying button was broken, and that Back,
Back-to-assistant and Next had regressed. A report can be internally consistent and still be
wrong about the only thing that matters.

The gap has one cause. **The analyser scored the backend and the owner lives in the UI.** A
send that Gmail confirmed is VERIFIED whatever the glass says, and the glass said "Applying…"
for the rest of the session. So every turn now carries two outcomes and their disagreement is
itself the defect:

    gmail_send_reply:  backend = VERIFIED   visible = APPLYING_STUCK   experience = FAILED

This module is the second reading. It processes what the tablet already writes down and the
old classifier never looked at — the reconciles, the branch moves, the renders and their
surface states, the navigation commands, the refusals, the scroll depths, the multitouches,
the prediction and anticipation records, and the owner's own feedback — and files fifteen
classes that describe the SCREEN rather than the server.

Every rule is a count or a match over ids, and each one names the evidence it read. Nothing
here is scored by a model, nothing here executes anything, and nothing here can authorise a
write: it is a function from a timeline to a list of findings.

The rules, and the evidence each needs:

    ACTION_UI_STUCK            the Mac settled a surface and the tablet submitted it again at
                               the next reconcile. `tablet_reconcile.kept` is the tablet's own
                               count of surfaces it was told were finished; two consecutive
                               reconciles that keep something mean the settle did not stick.
    SPLIT_NO_REDRAW            a half was forked and a focus change drew nothing.
    SPLIT_DUPLICATE_SURFACE    two halves whose cards are the same cards.
    WRONG_BRANCH_SURFACE       a control acted on a half that was not the focused one.
    DUPLICATE_RENDER           the same cards drawn twice inside seconds.
    PROGRESSIVE_RENDER_MISSING nothing at all on screen until everything was ready.
    NAV_SEMANTIC_MISMATCH      accepted navigation that took the owner nowhere: a burst of
                               Home and Back inside half a minute, every one ok, or a Home
                               that replayed the last record instead of reaching a landing.
    DEAD_CONTROL               a control accepted and nothing redrawn.
    FAKE_CONTROL               a control offered with nothing behind it: refused not_held,
                               landing_unavailable, dead_chip, or tapped while disabled.
    STALE_PENDING_ACTION       a change left PENDING for the rest of the session, and the
                               "changes still waiting" that counts one.
    FOREGROUND_STARVED         the owner's own read refused because the turn had already read
                               too much.
    SELF_UI_KNOWLEDGE_ERROR    a question the UI manifest answers, disclaimed instead.
    OWNER_FEEDBACK_IGNORED     feedback said out loud with no `owner_feedback` event for it.
    COLLISION                  two fingers on one control, or two controls in one place.
    FOCUS_LOST                 a render took away the owner's place: the keyboard's focus, a
                               field's contents, or the scroll position.
    SUMMARY_ANSWERED_WITH_PROFILES
                               a counting or summary question answered with one full entity
                               profile per record read. §6/§13: seven different customers is
                               not a duplicate render, it is the wrong surface for the
                               question.
    EMPTY_NOTIFICATION         a notification with no words in it. Eleven of the sixteen the
                               11 September session raised carried no text at all, and a
                               notification with nothing to say should be a finding rather
                               than silence.
    WRONG_ENTITY_ANSWERED      the request named an entity and the answer was about a
                               different one. §21's sharpest case: every gate the programme
                               has was satisfied by a turn that told the owner a false thing
                               about his own business.

And the four touch classes, which live in `app/observability/touch.py` because the heuristic
that separates them needs its own page of reasoning:

    CONTROL_TAP_MISROUTED_TO_VOICE  a short pointer interaction that began on or over an
                                    interactive control and became a recording.
    GESTURE_COLLISION               a second finger, a split or a fork ended the recording.
    REAL_SHORT_VOICE_RECORDING      a genuine attempt to speak that was too short.
    PRECISION_INPUT_REQUIRED        real evidence the owner was attempting exact entry.
"""

from __future__ import annotations

import difflib
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.observability import touch
from app.observability.screens import PAGE_IDENTIFIER, WITHHELD, page_identifier

log = logging.getLogger("crooks.observe")

# The classes this module files, in the order they are tested. Ordered so that the cause comes
# before the consequence: a surface stuck after a verified change explains the reconciles that
# follow it, and a half that redrew nothing explains the taps that hunted for it.
CLASSES: tuple[str, ...] = (
    "ACTION_UI_STUCK", "SPLIT_NO_REDRAW", "SPLIT_DUPLICATE_SURFACE", "WRONG_BRANCH_SURFACE",
    "STALE_PENDING_ACTION", "FOREGROUND_STARVED", "PROGRESSIVE_RENDER_MISSING",
    "DUPLICATE_RENDER", "NAV_SEMANTIC_MISMATCH", "FAKE_CONTROL", "DEAD_CONTROL",
    "SELF_UI_KNOWLEDGE_ERROR", "OWNER_FEEDBACK_IGNORED", "COLLISION", "FOCUS_LOST",
    # §6 and §13: the class the 11 September report did not have, and filed as a duplicate
    # render instead. Tested before DUPLICATE_RENDER's consequence and after its cause.
    "WRONG_ENTITY_ANSWERED", "SUMMARY_ANSWERED_WITH_PROFILES", "EMPTY_NOTIFICATION",
    # §21: what a finger actually did, four ways (app/observability/touch.py).
    *touch.CLASSES,
)
SEVERITY: dict[str, int] = {
    "ACTION_UI_STUCK": 6, "OWNER_FEEDBACK_IGNORED": 6, "SELF_UI_KNOWLEDGE_ERROR": 5,
    "SPLIT_NO_REDRAW": 5, "SPLIT_DUPLICATE_SURFACE": 5, "WRONG_BRANCH_SURFACE": 5,
    "FOREGROUND_STARVED": 5, "NAV_SEMANTIC_MISMATCH": 4, "STALE_PENDING_ACTION": 4,
    "FAKE_CONTROL": 4, "DEAD_CONTROL": 4, "PROGRESSIVE_RENDER_MISSING": 3,
    "FOCUS_LOST": 3, "DUPLICATE_RENDER": 2, "COLLISION": 2,
    # The worst class in the file: a confident wrong answer about the owner's own business.
    # A UI that fights him is visibly broken; this is not.
    "WRONG_ENTITY_ANSWERED": 6,
    "SUMMARY_ANSWERED_WITH_PROFILES": 3, "EMPTY_NOTIFICATION": 1,
    **touch.SEVERITY,
}
COMPONENT: dict[str, str] = {
    "ACTION_UI_STUCK": "the action surface (web/app.js::settleProposals, web/ui.js): the server's terminal status must settle a card from ANY non-terminal state, `committing` included",
    "SPLIT_NO_REDRAW": "the halves (web/app.js, app/routes/branches.py): focus must redraw the half it moves to",
    "SPLIT_DUPLICATE_SURFACE": "the fork (app/session/branch.py): a forked half needs its own navigation state, or it draws its parent's screen",
    "WRONG_BRANCH_SURFACE": "the halves: a control carried a branch that was not the focused one",
    "STALE_PENDING_ACTION": "the proposal store (app/actions): an undo offer is a property of a finished change, not a queued one",
    "FOREGROUND_STARVED": "the read budget (app/reads/scheduler.py): speculation and the owner's own request share one budget",
    "PROGRESSIVE_RENDER_MISSING": "the workspace (app/presentation.py, app/routes/turn.py): a shell, then facts patched in place",
    "DUPLICATE_RENDER": "the renderer (web/app.js): the same cards drawn again instead of left alone",
    "NAV_SEMANTIC_MISMATCH": "navigation (app/commands.py, web/app.js): Home is a landing and Back is a workspace, and ok=true is not the same as arriving",
    "FAKE_CONTROL": "the surface vocabulary (app/presentation.py, web/ui.js): a control offered with nothing behind it",
    "DEAD_CONTROL": "the command layer (app/commands.py, app/routes/command.py): a tap accepted that changed nothing on screen",
    "SELF_UI_KNOWLEDGE_ERROR": "the UI semantics manifest (app/observability/ui_semantics.py): the model was not given what the manifest says",
    "OWNER_FEEDBACK_IGNORED": "owner feedback (app/observability/feedback.py)",
    "COLLISION": "the tablet's touch targets (web/style.css, web/app.js): two fingers on one control, or two controls in one place",
    "FOCUS_LOST": "the renderer's patching (web/app.js): a background render must not take the keyboard or the scroll position",
    "WRONG_ENTITY_ANSWERED": "entity resolution (app/context, app/routes/turn.py): a name in the request must outrank the record in focus",
    "SUMMARY_ANSWERED_WITH_PROFILES": "the summary surfaces (app/analytics, app/reads, app/presentation.py): a counting question wants one answer surface, not one profile per record read",
    "EMPTY_NOTIFICATION": "the notifications (web/app.js, app/presentation.py): a notification with no words should not be raised",
    **touch.COMPONENT,
}
TASKS: dict[str, str] = {
    "ACTION_UI_STUCK": "the worst class on the screen: the change was made and the card never said so. One state machine with terminal states, the server authoritative, and a watchdog that asserts no surface stays EXECUTING after its proposal is terminal.",
    "SPLIT_NO_REDRAW": "give each half its own navigation state and redraw on focus; a fork that draws its parent's screen is not a split.",
    "SPLIT_DUPLICATE_SURFACE": "the two halves drew the same cards. Per-half header, per-half entity and cursor, and a forked half that says plainly when it holds nothing.",
    "WRONG_BRANCH_SURFACE": "read the focused half from one place; a control that names a backgrounded half is either refused or redirected, never served quietly.",
    "STALE_PENDING_ACTION": "separate `pending` from `undoable`, give undo its own TTL, and take it out of every \"still waiting\" count.",
    "FOREGROUND_STARVED": "separate the budgets with strict priority — foreground read first, speculation last — and make speculation yield at once.",
    "PROGRESSIVE_RENDER_MISSING": "draw the shell, then patch the facts in as each read lands; instrument time_to_shell and time_to_first_fact and hold them.",
    "DUPLICATE_RENDER": "patch the surface that changed rather than redrawing the same cards; each redraw costs the owner his scroll position.",
    "NAV_SEMANTIC_MISMATCH": "Home reaches the branch's landing, Back restores the exact prior workspace, Next moves the set's cursor with a visible \"3 of 10\". Assert the restored workspace, never the HTTP code.",
    "FAKE_CONTROL": "either the control holds what it offers, or it is not drawn; a refusal under a finger is a control that should not have been there.",
    "DEAD_CONTROL": "a tap that changes nothing must say so; find what the owner expected and either do it or disable the control with a reason.",
    "SELF_UI_KNOWLEDGE_ERROR": "the manifest answers this. Check the question reaches the read family rather than the model.",
    "OWNER_FEEDBACK_IGNORED": "the owner narrated a defect and nothing recorded it. A test session must take it as an `owner_feedback` event and the report must print it verbatim.",
    "COLLISION": "separate the targets, or make the second touch a no-op rather than a different gesture.",
    "FOCUS_LOST": "patch in place; keep the field's focus, its contents and the scroll position across a background render.",
    "WRONG_ENTITY_ANSWERED": "entity resolution precedes context: a named entity in the request outranks the entity in focus, the workspace is composed for the entity the words RESOLVE TO, and when the two disagree the answer says which it used. A turn that names one entity and answers about another is a failure whatever the tools returned.",
    "SUMMARY_ANSWERED_WITH_PROFILES": "answer the question that was asked: a count, a comparison or a \"has anyone\" wants one summary surface naming the records behind it. Workstream D owns the fix; this class owns the finding.",
    "EMPTY_NOTIFICATION": "a state change updates the place the state lives. If there is nothing to say, say nothing — do not raise a wordless notification.",
    **touch.TASKS,
}

# What the SCREEN did, as one word per class. The vocabulary of the `visible` column.
VISIBLE_WORD: dict[str, str] = {
    "ACTION_UI_STUCK": "APPLYING_STUCK", "SPLIT_NO_REDRAW": "NOT_REDRAWN",
    "SPLIT_DUPLICATE_SURFACE": "TWO_OF_THE_SAME", "WRONG_BRANCH_SURFACE": "WRONG_HALF",
    "STALE_PENDING_ACTION": "STILL_WAITING", "FOREGROUND_STARVED": "STARVED",
    "PROGRESSIVE_RENDER_MISSING": "LATE", "DUPLICATE_RENDER": "REDRAWN",
    "NAV_SEMANTIC_MISMATCH": "WENT_NOWHERE", "FAKE_CONTROL": "NOTHING_BEHIND_IT",
    "DEAD_CONTROL": "NO_RESPONSE", "SELF_UI_KNOWLEDGE_ERROR": "DISCLAIMED",
    "OWNER_FEEDBACK_IGNORED": "DISCARDED", "COLLISION": "COLLIDED", "FOCUS_LOST": "PLACE_LOST",
    "WRONG_ENTITY_ANSWERED": "ABOUT_SOMEBODY_ELSE",
    "SUMMARY_ANSWERED_WITH_PROFILES": "SEVEN_PROFILES_FOR_ONE_ANSWER",
    "EMPTY_NOTIFICATION": "WORDLESS",
    **touch.VISIBLE_WORD,
}

# ------------------------------------------------------------------------ the thresholds

# Two reconciles that keep something are a settle that did not stick; one is a correction.
STUCK_RECONCILES = 2
# How long after a focus change a redraw still counts as that focus change's.
REDRAW_S = 5.0
# The same cards, again, inside this many seconds of the last time they were drawn.
DUPLICATE_S = 5.0
# Two render frames closer together than this are ONE paint reported twice, not a redraw the
# owner saw happen. The 11 September file has the seven-customer deck arriving as two frames
# 41 ms apart and an email list as two frames 11 ms apart; the redraw storm it also has runs
# 131–982 ms between frames. A hundred milliseconds is about six display frames — below what a
# person perceives as a second paint, and below the gap at which a redraw costs a visible
# scroll jump. Under it there is nothing for the owner to have seen twice.
FRAME_MS = 100.0
# A summary or counting question answered with this many full entity profiles is answering a
# different question. One profile is an answer; two is a comparison; seven is a deck.
PROFILES_FOR_A_SUMMARY = 3
# Two requests this alike are the same request said twice. The same number the report uses for
# its own "said again" rule, held here so this module needs nothing from it.
SAME_REQUEST_RATIO = 0.62
# The reads that resolve a NAME into an id. A turn that ran one of these asked the store who
# the owner meant; a turn that ran none took whoever it already had.
RESOLVING_READS = ("find_customer", "find_order", "search", "lookup_customer", "customer_search")
# What the redactor leaves behind where a customer's name or address was. Their presence in a
# request is proof the request named somebody, on a timeline where the name itself is gone.
REDACTED_MARK_RE = re.compile(r"\[(?:name|email|address|phone|postcode)\]")
# Nothing on screen for this long, with no shell before it, is not progressive rendering.
PROGRESSIVE_MS = 3_000.0
# A burst of navigation this size inside this window is hunting, not moving.
NAV_WINDOW_S = 30.0
NAV_BURST = 4
# A control accepted and nothing redrawn within this is a control that did nothing.
DEAD_S = 3.0
# A place lost this soon after something redrew is that redraw's doing.
FOCUS_S = 5.0

# The refusal codes that mean the control had nothing behind it. Every one is a code the Mac
# itself writes (app/commands.py, app/families/landings.py).
NOTHING_BEHIND = frozenset({
    "not_held", "landing_unavailable", "no_entity", "no_set", "unknown_command", "unknown_kind",
    "unknown_area", "unknown_tab", "no_tabs", "no_ref", "unknown_control", "no_target",
    "unknown_branch", "branch_closed", "empty_set", "dead_chip",
})
# A read refused because the turn had already read too much (app/reads/scheduler.py). The
# owner's own request, refused by work nobody asked for.
STARVED_RE = re.compile(
    r"reading for too long|answer from what has been read|read budget|budget (?:spent|exhausted)"
    r"|too many reads|read cap", re.I)
# The navigation commands, and the ones that are a move through a set rather than a trail.
NAV_COMMANDS = frozenset({"navigation.home", "navigation.back", "navigation.forward"})
SET_COMMANDS = frozenset({"workflow.next", "workflow.previous"})
# The states a card can be in while it says "Applying…" (web/ui.js). A render carrying one of
# these for a proposal the Mac has already settled is the stuck surface itself, photographed.
APPLYING_STATES = frozenset({"committing", "executing", "verifying"})
TERMINAL_STATUS = frozenset({"VERIFIED", "UNVERIFIED", "FAILED", "STALE", "EXPIRED", "REVOKED"})

# The answers that disclaim the product's own interface, or its own ability to write something
# down. Held here because they are the sentences the live session actually produced.
DISCLAIMS_RE = re.compile(
    r"i (?:do not|don'?t) know what that (?:button|control|thing|is)"
    r"|not something i control"
    r"|check with whoever"
    r"|whoever (?:built|builds|made|makes|handles|handles the)"
    r"|that'?s just the tablet'?s (?:own )?screen"
    r"|i(?:'ve| have) no (?:tool|way)\b"
    r"|i still have no tool"
    r"|nothing here reaches whoever"
    r"|you'?d need to raise it with", re.I)


# ---------------------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    """One thing the owner could see going wrong, and what was read to say so."""

    name: str
    turn_id: str
    signal: str
    subject: str = ""          # the proposal's operation or the control's name, where there is one
    # How the rule knows. `direct` — the timeline records the thing itself (a refusal code, a
    # settled proposal, a pointer owner). `corroborated` — a reading of shape that the owner's
    # own words confirm. `inferred` — a reading of shape and nothing else. The improvement
    # ranking discounts an inference so it can never outrank a certainty of the same severity,
    # which is how sixty-two inferred rows came to be the 11 September report's first priority.
    basis: str = "direct"

    def as_dict(self) -> dict[str, Any]:
        return {"class": self.name, "turn_id": self.turn_id, "signal": self.signal,
                "subject": self.subject or None, "basis": self.basis}


@dataclass
class Row:
    """A turn's two outcomes, and the verdict they produce together."""

    turn_id: str
    subject: str
    backend: str
    visible: str
    experience: str
    why: str = ""

    def line(self) -> str:
        """The line §17 asks for, padded so a column of them reads as a column."""
        return (f"{self.subject}:  backend = {self.backend}   visible = {self.visible}   "
                f"experience = {self.experience}")


@dataclass
class Reading:
    """Everything this module found, for the report and for the tests."""

    findings: list[Finding] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    feedback: list[dict[str, Any]] = field(default_factory=list)
    ignored_feedback: list[dict[str, Any]] = field(default_factory=list)
    # A rule that could not read this timeline, by name. Kept rather than swallowed: a
    # detection that silently stops detecting is how the live hour came to be scored 11 of 14,
    # so the report prints these and a test asserts the list is empty.
    errors: list[str] = field(default_factory=list)

    @property
    def counts(self) -> Counter:
        return Counter(f.name for f in self.findings)

    def by_turn(self, turn_id: str) -> list[Finding]:
        return [f for f in self.findings if f.turn_id == turn_id]

    def of(self, name: str) -> list[Finding]:
        return [f for f in self.findings if f.name == name]


# ------------------------------------------------------------------------- small readers


def _events(rec: Any, kind: str) -> list[dict[str, Any]]:
    return [e for e in rec.events if str(e.get("kind") or "") == kind]


def _renders(rec: Any) -> list[dict[str, Any]]:
    return _events(rec, "tablet_render")


def _signature(render: dict[str, Any]) -> tuple:
    """What was on screen, as a comparable shape: the card types, their refs and the tab that
    was open. Never their contents."""
    return tuple(
        (str(c.get("type") or ""), str(c.get("ref") or ""), str(c.get("tab_active") or ""))
        for c in (render.get("cards") or []) if isinstance(c, dict)
    )


def identity(card: dict[str, Any]) -> str:
    """The canonical IDENTITY of what a card draws: the record, not the kind of record.

    §6. `gid://shopify/Customer/11410640896343` is an identity; `customer` is a type. The 11
    September report compared types, found seven `customer` cards in one deck and reported
    "the same customer card drawn 7 times" — for seven different people. A card with no ref
    has no identity, and a rule that needs one is silent about it rather than guessing.
    """
    ref = str(card.get("ref") or card.get("id") or card.get("entity_id") or "")
    if not ref:
        return ""
    kind = str(card.get("entity") or card.get("kind") or card.get("type") or "")
    # A Shopify GID already names its own kind, so it is its own canonical form.
    return ref if ref.startswith("gid://") else f"{kind}:{ref}"


def _identities(render: dict[str, Any]) -> list[str]:
    """Every identity this frame drew, in order, repeats included."""
    return [i for i in (identity(c) for c in (render.get("cards") or []) if isinstance(c, dict)) if i]


def _clock_ms(event: dict[str, Any]) -> float:
    """The tablet's own millisecond clock for an event, else the session clock."""
    t = event.get("t")
    if isinstance(t, (int, float)):
        return float(t)
    return float(event.get("ts") or 0.0) * 1000.0


def _frame_ms(render: dict[str, Any]) -> float:
    """When the tablet painted, in milliseconds. `t` is the tablet's own clock; `ts` is when
    the Mac received the batch and several hundred events can share one."""
    t = render.get("t")
    if isinstance(t, (int, float)):
        return float(t)
    return float(render.get("ts") or 0.0) * 1000.0


# A question that wants a count, a comparison or a yes/no about a set — not a profile each.
SUMMARY_QUESTION_RE = re.compile(
    r"\bhas (?:anyone|anybody|any (?:one|customer|body))\b|\bhow many\b|\bhow much\b"
    r"|\bwho (?:has|have|is|are|bought|ordered|spent)\b|\banyone (?:who|that)\b"
    r"|\bwhich (?:of them|ones?|customers?|orders?)\b|\bcount\b|\btotal\b"
    r"|\bany (?:returning|repeat)\b|\breturning customer\b|\bcompare\b|\baverage\b"
    r"|\bbest (?:seller|selling)\b|\bmost\b", re.I)


def _turn_at(rec: Any, ts: float) -> str:
    """The turn running at that moment, else the one most recently started. A tap between two
    questions belongs to the one before it, which is the turn the owner was looking at."""
    best = ""
    for turn in rec.turns:
        if turn.started_at <= ts:
            best = turn.turn_id
    return best


def _terminal_by(rec: Any, ts: float) -> list[Any]:
    """The proposals the Mac had already settled by that moment."""
    out = []
    for proposal in rec.proposals.values():
        final = proposal.final
        if final is not None and float(final.get("ts") or 0.0) <= ts:
            out.append(proposal)
    return out


# ------------------------------------------------------------------------------- rules


def _action_ui_stuck(rec: Any) -> list[Finding]:
    """A surface the Mac settled and the tablet kept.

    `tablet_reconcile` carries the tablet's own three numbers: `count`, how many live
    proposals it submitted; `kept`, how many of them the Mac said were finished and it
    therefore called settle on; `cancelled`, how many the Mac had never heard of. A card that
    is settled leaves the live list, so it cannot be submitted again. Two reconciles in a row
    that KEEP something mean the settle did nothing — and the live session has six in a row
    reading `count=2 kept=2`, one per turn, for six turns.
    """
    events = sorted(_events(rec, "tablet_reconcile"), key=lambda e: float(e.get("ts") or 0.0))
    out: list[Finding] = []
    run: list[dict[str, Any]] = []

    def close(run: list[dict[str, Any]]) -> None:
        if len(run) < STUCK_RECONCILES:
            return
        pairs = Counter((int(e.get("count") or 0), int(e.get("kept") or 0)) for e in run)
        (count, kept), repeats = pairs.most_common(1)[0]
        for event in run[1:]:
            ts = float(event.get("ts") or 0.0)
            settled = _terminal_by(rec, ts)
            if not settled:
                continue
            operations = sorted({p.operation for p in settled if p.operation and not p.undo_of})
            out.append(Finding(
                "ACTION_UI_STUCK",
                str(event.get("turn_id") or _turn_at(rec, ts)),
                f"the Mac had settled {len(settled)} change(s) and the tablet submitted "
                f"{event.get('count')} again, keeping {event.get('kept')}: "
                f"{len(run)} consecutive reconciles, {repeats} of them count={count} kept={kept}"
                + (f"; settled: {', '.join(operations)}" if operations else ""),
                subject=operations[0] if operations else "",
            ))

    for event in events:
        if int(event.get("kept") or 0) >= 1:
            run.append(event)
            continue
        close(run)
        run = []
    close(run)

    # The same fault, photographed: a card drawn still saying "Applying…" for a proposal the
    # Mac had already settled. Stronger evidence than the reconciles when the tablet reports
    # its surface states, and silent when it does not.
    for render in _renders(rec):
        ts = float(render.get("ts") or 0.0)
        settled = {p.proposal_id for p in _terminal_by(rec, ts)}
        for card in render.get("cards") or []:
            if not isinstance(card, dict):
                continue
            state = str((card.get("surface") or {}).get("state") or "")
            pid = str(card.get("proposal_id") or "")
            if state in APPLYING_STATES and pid in settled:
                proposal = rec.proposals.get(pid)
                out.append(Finding(
                    "ACTION_UI_STUCK", str(render.get("turn_id") or _turn_at(rec, ts)),
                    f"the card for {pid} was drawn in state {state!r} after the Mac settled it "
                    f"as {proposal.status if proposal else 'terminal'}",
                    subject=(proposal.operation if proposal else ""),
                ))
    return out


def _split_findings(rec: Any) -> list[Finding]:
    """What the two halves cost the owner: a focus that drew nothing, and two halves showing
    the same cards."""
    out: list[Finding] = []
    forks = [e for e in rec.events if str(e.get("kind") or "") == "branch_forked"]
    if not forks:
        return out
    first_fork = min(float(e.get("ts") or 0.0) for e in forks)
    renders = sorted(((float(r.get("ts") or 0.0), r) for r in _renders(rec) if r.get("cards")),
                     key=lambda pair: pair[0])
    focuses = sorted((e for e in rec.events if str(e.get("kind") or "") == "branch_focused"),
                     key=lambda e: float(e.get("ts") or 0.0))
    for event in focuses:
        ts = float(event.get("ts") or 0.0)
        if ts < first_fork:
            continue
        after = [r for at, r in renders if ts <= at <= ts + REDRAW_S]
        if not after:
            out.append(Finding(
                "SPLIT_NO_REDRAW", _turn_at(rec, ts),
                f"the half {event.get('branch_id') or '?'} was focused and nothing was drawn "
                f"within {REDRAW_S:.0f} s of it",
                subject=str(event.get("branch_id") or ""),
            ))
            continue
        # What the half drew, held against what the previous half drew. Two halves whose cards
        # are the same cards is the owner's "it just shows two of the same thing".
        signature = _signature(after[0])
        previous = [(at, r) for at, r in renders if at < ts]
        if previous and _signature(previous[-1][1]) == signature and signature:
            out.append(Finding(
                "SPLIT_DUPLICATE_SURFACE", _turn_at(rec, ts),
                f"the half {event.get('branch_id') or '?'} drew the same cards as the half "
                f"before it: {', '.join(sorted({t for t, _r, _tab in signature}))}",
                subject=str(event.get("branch_id") or ""),
            ))
    return out


def _wrong_branch(rec: Any) -> list[Finding]:
    """A control that acted on a half which was not the one the owner was talking to."""
    out: list[Finding] = []
    focused = ""
    for event in sorted(rec.events, key=lambda e: (float(e.get("ts") or 0.0), int(e.get("seq") or 0))):
        kind = str(event.get("kind") or "")
        branch = str(event.get("branch_id") or "")
        if kind == "branch_focused":
            # Only a FOCUS moves who the owner is talking to. A fork does not: "Divided. Tap a
            # half to talk to it" is what the tablet says, and treating the fork as a focus
            # reported every command on the parent half as being on the wrong one.
            focused = branch
            continue
        if kind in ("branch_merged", "branch_cancelled"):
            # The surviving half is not named by the event, so the tracking stops rather than
            # reporting every command afterwards as being on the wrong half.
            focused = ""
            continue
        if kind not in ("command", "command_stage", "row_action") or not focused or not branch:
            continue
        if branch != focused and event.get("ok") is not False:
            ts = float(event.get("ts") or 0.0)
            out.append(Finding(
                "WRONG_BRANCH_SURFACE", str(event.get("turn_id") or _turn_at(rec, ts)),
                f"{event.get('command') or event.get('action') or kind} was served on {branch} "
                f"while {focused} was the focused half",
                subject=str(event.get("command") or event.get("action") or ""),
            ))
    return out


def _duplicate_renders(rec: Any) -> list[Finding]:
    """The same thing, drawn again within seconds. Every redraw costs the owner his place.

    §6 — **identity, not type.** The 11 September report filed `DUPLICATE_RENDER` against
    `turn_be1b384ca420` and described it as "the same customer card drawn 7 times". The seven
    ids were all different (…6343, …4807, …5015, …4055, …7975, …2855, …8887): seven people,
    one card each, in answer to "has anyone bought today that has bought before". Nothing was
    drawn twice. The rule compared card TYPES and the signal it wrote enumerated them, so
    seven profiles of seven customers read as one profile drawn seven times, and the fix it
    proposed was to de-duplicate a renderer that was not duplicating.

    So two rules, both over canonical identity:

    * **the same record twice in ONE frame** — customer X drawn at index 0 and again at index
      4 is a duplicate render, whatever else is in the deck. This is what the class is for.
    * **the same record set painted again** — a later frame repeating the identities the last
      one had, more than `FRAME_MS` after it, inside `DUPLICATE_S`. Two frames closer together
      than `FRAME_MS` are one paint reported twice and the owner saw nothing happen twice.

    A deck with no identities in it at all (an `order_list`, a `working_set`) still has a
    comparable shape, so a redraw storm of surfaces that carry no ref is still caught — the 11
    September file has one turn drawing `order_list + working_set + folded` seven times, 131 to
    982 ms apart, and that is a real defect. What the class can no longer do is call seven
    different people the same person.
    """
    out: list[Finding] = []
    seen: dict[tuple, tuple[float, float, int]] = {}
    for render in sorted(_renders(rec), key=lambda r: (float(r.get("ts") or 0.0), _frame_ms(r))):
        cards = [c for c in (render.get("cards") or []) if isinstance(c, dict)]
        if not cards:
            continue
        ts = float(render.get("ts") or 0.0)
        painted = _frame_ms(render)
        turn_id = str(render.get("turn_id") or _turn_at(rec, ts))

        # One frame, one record, twice.
        repeats = Counter(_identities(render))
        for ref, n in repeats.items():
            if n < 2:
                continue
            out.append(Finding(
                "DUPLICATE_RENDER", turn_id,
                f"{ref} was drawn {n} times in one render of {len(cards)} card(s): the same "
                f"record, not the same kind of record",
                subject=ref,
            ))

        # The same identities again, in a later paint.
        identities = sorted(repeats)
        key = tuple(identities) if identities else tuple(
            (str(c.get("type") or ""), str(c.get("tab_active") or "")) for c in cards)
        last = seen.get(key)
        if last is not None and ts - last[0] <= DUPLICATE_S and painted - last[1] > FRAME_MS:
            n = last[2] + 1
            seen[key] = (ts, painted, n)
            what = (", ".join(identities[:3]) + (f" and {len(identities) - 3} more"
                                                 if len(identities) > 3 else "")
                    if identities else
                    ", ".join(dict.fromkeys(str(c.get("type") or "") for c in cards)))
            out.append(Finding(
                "DUPLICATE_RENDER", turn_id,
                f"the same {what} painted again {(painted - last[1]) / 1000:.1f} s later "
                f"(#{n} of this shape)"
                + ("" if identities else " — surfaces with no record id of their own"),
                subject=identities[0] if identities else "",
            ))
        elif last is None or ts - last[0] > DUPLICATE_S:
            seen[key] = (ts, painted, 1)
    return out


def _summary_answered_with_profiles(rec: Any) -> list[Finding]:
    """A counting question answered with one full profile per record read (§6, §13).

    This is what `turn_be1b384ca420` actually was. "Has anyone bought today that has bought
    before, a returning customer?" — answered correctly, out loud, with **one**; and drawn as
    **seven** full customer cards, 265 px each, 1,949 px of deck, one per customer the turn had
    read. Seven `shopify_customer_history` calls to answer a one-line question.

    The evidence is three counts and nothing else: the request is a summary question, the deck
    holds `PROFILES_FOR_A_SUMMARY` or more entity profiles of one type with DIFFERENT
    identities, and the spoken answer names fewer than it drew. Workstream D owns the fix; this
    owns the class.
    """
    out: list[Finding] = []
    for turn in rec.turns:
        said = turn.question or turn.raw_text
        if not said or not SUMMARY_QUESTION_RE.search(said):
            continue
        for render in turn.tablet_events("render"):
            cards = [c for c in (render.get("cards") or []) if isinstance(c, dict)]
            profiles: dict[str, set[str]] = {}
            for card in cards:
                ref = identity(card)
                if ref:
                    profiles.setdefault(str(card.get("type") or ""), set()).add(ref)
            for kind, refs in profiles.items():
                if len(refs) < PROFILES_FOR_A_SUMMARY:
                    continue
                height = sum(int(c.get("height") or 0) for c in cards
                             if isinstance(c.get("height"), (int, float)))
                out.append(Finding(
                    "SUMMARY_ANSWERED_WITH_PROFILES", turn.turn_id,
                    f"a summary question drew {len(refs)} different {kind} profiles"
                    + (f", {height:,} px of deck" if height else "")
                    + f" — the ids are all different ({', '.join(sorted(r[-4:] for r in refs))}), "
                    f"so this is one profile each for every record read, not one answer to the "
                    f"question asked",
                    subject=kind,
                ))
                break
            else:
                continue
            break
    return out


def _empty_notifications(rec: Any) -> list[Finding]:
    """A notification with no words in it.

    Sixteen `tablet_notify` events in the 11 September session; **eleven carry no text at
    all**, and the five that do are `divided`, `merged`, `divided`, `merged`, `divided` — state
    changes the screen itself shows. A notification is an interruption, and an interruption
    with nothing to say is a defect rather than silence, which is how eleven of them went
    unreported.
    """
    out: list[Finding] = []
    for event in _events(rec, "tablet_notify"):
        words = " ".join(str(event.get("text") or event.get("message") or event.get("code") or "").split())
        if words:
            continue
        ts = float(event.get("ts") or 0.0)
        out.append(Finding(
            "EMPTY_NOTIFICATION", str(event.get("turn_id") or _turn_at(rec, ts)),
            f"a {event.get('name') or 'notification'} was raised with no text, no code and "
            f"nothing to read (seq {event.get('seq') or '?'})",
            subject=str(event.get("name") or "notification"),
        ))
    return out


def _resolved_entity(turn: Any) -> tuple[str, str]:
    """The canonical identity the turn ANSWERED about, and how it got it.

    The identity is read off what the turn put on the glass (`ui_entities`, then the render's
    cards), because that is the record the owner was told about. The "how" is `by_name` when a
    resolving read ran, `from_hand` when the first read was handed an id the session already
    held, and `""` when neither can be said.
    """
    ref = ""
    for entity in turn.ui_entities:
        ref = identity({"ref": entity.get("ref"), "type": entity.get("type")})
        if ref:
            break
    if not ref:
        for render in turn.tablet_events("render"):
            refs = _identities(render)
            if refs:
                ref = refs[0]
                break
    how = ""
    if any(any(mark in record.tool for mark in RESOLVING_READS) for record in turn.tools):
        how = "by_name"
    elif turn.tools:
        first = turn.tools[0]
        ids = [str(v) for v in (first.args or {}).values() if str(v).startswith("gid://")]
        if ids:
            how = "from_hand"
    return ref, how


def _kind_of(ref: str) -> str:
    """The kind of record an identity names: `Customer`, `Order`, else its own prefix."""
    if ref.startswith("gid://"):
        parts = ref.split("/")
        return parts[3] if len(parts) > 4 else ref
    return ref.split(":", 1)[0] if ":" in ref else ""


def _named_queries(rec: Any) -> dict[str, str]:
    """Every name the session resolved, and the identity it resolved to.

    Read off the resolving reads themselves: `shopify_find_customer {query: "…"}` followed by
    the customer the turn then drew. This is the only place a NAME is joined to an ID, and it
    is what makes "he asked about A and was told about B" provable rather than suspected.

    A search the dispatcher wrote down by its shape (`<9 chars ~…>`, app/tools/dispatch.py
    loggable_args, round 9) holds no name to find in a request, and is passed over: the pair,
    which compares ids, is what proves it then.
    """
    out: dict[str, str] = {}
    for turn in rec.turns:
        ref, how = _resolved_entity(turn)
        if not ref or how != "by_name":
            continue
        for record in turn.tools:
            if not any(mark in record.tool for mark in RESOLVING_READS):
                continue
            asked = str((record.args or {}).get("query") or (record.args or {}).get("name") or "").strip()
            if len(asked) >= 3 and not asked.startswith("<"):
                out.setdefault(asked.lower(), ref)
    return out


def _wrong_entity(rec: Any) -> list[Finding]:
    """The request named one entity and the answer was about a different one (§3, §6, §21).

    The 11 September session, sixty-six seconds apart:

        20:15:26  "what has [A] ordered in his lifetime?"
                  shopify_order_detail(order already in focus) → shopify_customer_history
                  → spoke customer B's history, as fact.  answered about …6343
        20:16:32  "Show me [A]'s orders in his lifetime"
                  shopify_find_customer("[A]") → shopify_customer_history
                  → spoke A's history.                     answered about …5015

    The report scored the first `backend = READ_OK / visible = DRAWN / experience =
    SUCCESSFUL`, because both tools returned 200 and a card was drawn. Every gate the
    programme has was satisfied by a turn that told the owner a false thing about his own
    business, and the only reason anybody knows is that he asked again.

    Two ways to prove it, and both need a second reading of the same request:

    * **the pair** · two requests alike enough to be the same request, answering about
      different identities of the same kind, where one turn resolved a NAME and the other took
      the record it already held. The one that took what it held is the failure. This works on
      a redacted timeline, because it compares ids and similarity, never names.
    * **the name** · the session resolved a name to an id somewhere, that name is in this
      turn's own words, and this turn answered about a different id. Available only while the
      names are still in the file.

    It also re-reads a row the report files as a curiosity. Wherever a request was said again,
    the first question is whether the first ANSWER was wrong rather than unheard.
    """
    out: list[Finding] = []
    resolved: dict[str, tuple[str, str, str]] = {}
    for turn in rec.turns:
        said = " ".join((turn.question or turn.raw_text or "").split()).lower()
        ref, how = _resolved_entity(turn)
        if said and ref:
            resolved[turn.turn_id] = (said, ref, how)

    by_name = _named_queries(rec)
    filed: set[str] = set()
    for turn in rec.turns:
        row = resolved.get(turn.turn_id)
        if row is None:
            continue
        said, ref, how = row
        if how == "by_name":
            continue                      # it asked the store who was meant
        # The pair: the same request, later, answered about somebody else.
        for other in rec.turns:
            if other.turn_id == turn.turn_id or other.started_at <= turn.started_at:
                continue
            theirs = resolved.get(other.turn_id)
            if theirs is None:
                continue
            said_again, their_ref, their_how = theirs
            if their_how != "by_name" or their_ref == ref:
                continue
            if _kind_of(their_ref) != _kind_of(ref):
                continue
            ratio = difflib.SequenceMatcher(None, said, said_again).ratio()
            if ratio < SAME_REQUEST_RATIO:
                continue
            filed.add(turn.turn_id)
            out.append(Finding(
                "WRONG_ENTITY_ANSWERED", turn.turn_id,
                f"answered about {ref}; the same request in {other.turn_id} "
                f"({ratio:.0%} the same words) resolved the name the owner said and answered "
                f"about {their_ref} instead. This turn ran no resolving read — "
                + (", ".join(record.tool for record in turn.tools[:3]) or "no tool at all")
                + " — so the record already in hand won over the one he named",
                subject=ref,
            ))
            break
        if turn.turn_id in filed:
            continue
        # The name: still in the file, and it points somewhere else.
        for asked, their_ref in by_name.items():
            if asked not in said or their_ref == ref or _kind_of(their_ref) != _kind_of(ref):
                continue
            out.append(Finding(
                "WRONG_ENTITY_ANSWERED", turn.turn_id,
                f"the request names somebody this session resolved to {their_ref}, and the "
                f"turn answered about {ref}",
                subject=ref,
            ))
            break
    return out


def _touches(rec: Any) -> list[Finding]:
    """What every finger actually did (§21, app/observability/touch.py).

    The single "recording too short" bucket became four classes, and this turns each touch the
    classifier names into a finding on the turn it happened during. A burst arrives as ONE
    touch record carrying its tap count, so twenty-six taps in ten seconds are one row.
    """
    out: list[Finding] = []
    for found in touch.classify(rec.events):
        out.append(Finding(
            found.name, found.turn_id or _turn_at(rec, found.at), found.signal,
            subject=found.target or found.owner or "", basis=found.basis,
        ))
    for turn in rec.turns:
        for what, detail in touch.precision_evidence(turn):
            out.append(Finding(
                "PRECISION_INPUT_REQUIRED", turn.turn_id, f"{what}: {detail}",
                subject="precision input",
            ))
    return out


def _progressive(rec: Any) -> list[Finding]:
    """Nothing on screen until everything was ready.

    `workspace_ms` is the Mac's own measurement of when the cards existed
    (app/routes/turn.py::_performance); with no shell drawn before it, that number is how long
    the owner looked at the previous screen.
    """
    out: list[Finding] = []
    for turn in rec.turns:
        drew = sorted(((float(r.get("ts") or 0.0), r) for r in turn.tablet_events("render")),
                      key=lambda pair: pair[0])
        with_cards = [at for at, r in drew if r.get("cards")]
        if not with_cards:
            continue
        shells = [at for at, r in drew if not r.get("cards") and at < with_cards[0]]
        workspace = (turn.performance or {}).get("workspace_ms")
        waited = float(workspace) if isinstance(workspace, (int, float)) else (with_cards[0] - turn.started_at) * 1000
        if waited >= PROGRESSIVE_MS and not shells and len(with_cards) == 1:
            out.append(Finding(
                "PROGRESSIVE_RENDER_MISSING", turn.turn_id,
                f"the first and only cards arrived after {waited:,.0f} ms with nothing drawn "
                f"before them",
            ))
    return out


def _navigation(rec: Any) -> list[Finding]:
    """Navigation that was accepted and took the owner nowhere.

    Two rules. A BURST — four or more accepted Home / Back / Forward inside half a minute — is
    somebody hunting for a landing he never reaches; the live hour has eight Homes and four
    Backs in twenty-two seconds, every one `ok=true`, and the old report called that "100 %
    accepted". And a HOME that replays the record already in hand instead of reaching the
    branch's landing, which is what made the hunt necessary.
    """
    out: list[Finding] = []
    commands = sorted((e for e in rec.controls if str(e.get("kind") or "") == "command"
                       and str(e.get("command") or "") in NAV_COMMANDS and e.get("ok") is not False),
                      key=lambda e: float(e.get("ts") or 0.0))
    used: set[int] = set()
    for i, first in enumerate(commands):
        if i in used:
            continue
        start = float(first.get("ts") or 0.0)
        window = [(j, e) for j, e in enumerate(commands[i:], start=i)
                  if float(e.get("ts") or 0.0) - start <= NAV_WINDOW_S]
        if len(window) < NAV_BURST:
            continue
        used.update(j for j, _e in window)
        counts = Counter(str(e.get("command") or "") for _j, e in window)
        span = float(window[-1][1].get("ts") or 0.0) - start
        out.append(Finding(
            "NAV_SEMANTIC_MISMATCH", _turn_at(rec, start),
            ", ".join(f"{n} × {name.split('.')[-1]}" for name, n in counts.most_common())
            + f" accepted in {span:.0f} s, every one ok=true — accepted is not arrived",
            subject="navigation",
        ))
    for event in rec.controls:
        if str(event.get("command") or "") != "navigation.home" or event.get("ok") is False:
            continue
        if event.get("replayed") and event.get("entity"):
            ts = float(event.get("ts") or 0.0)
            out.append(Finding(
                "NAV_SEMANTIC_MISMATCH", str(event.get("turn_id") or _turn_at(rec, ts)),
                f"Home replayed the {event.get('entity')} already in hand instead of reaching "
                f"the half's landing",
                subject="navigation.home",
            ))
    return out


def _controls(rec: Any) -> list[Finding]:
    """Controls with nothing behind them, and controls that did nothing."""
    out: list[Finding] = []
    renders = sorted(float(r.get("ts") or 0.0) for r in _renders(rec) if r.get("cards"))
    for event in rec.controls:
        kind = str(event.get("kind") or "")
        if kind not in ("command", "command_stage", "row_action"):
            continue
        ts = float(event.get("ts") or 0.0)
        name = str(event.get("command") or event.get("action") or kind)
        turn_id = str(event.get("turn_id") or _turn_at(rec, ts))
        code = str(event.get("code") or "")
        if event.get("ok") is False and code in NOTHING_BEHIND:
            out.append(Finding(
                "FAKE_CONTROL", turn_id,
                f"{name} was on screen and the Mac refused it {code}: the control was offered "
                f"with nothing behind it",
                subject=name,
            ))
            continue
        if event.get("ok") is False:
            continue
        if str(event.get("command") or "") in NAV_COMMANDS | SET_COMMANDS and not any(
                ts <= at <= ts + DEAD_S for at in renders):
            out.append(Finding(
                "DEAD_CONTROL", turn_id,
                f"{name} was accepted and nothing was drawn within {DEAD_S:.0f} s of it",
                subject=name,
            ))
    for turn in rec.turns:
        for tap in turn.tablet_events("rail_tap"):
            if str(tap.get("state") or "") == "disabled":
                out.append(Finding(
                    "FAKE_CONTROL", turn.turn_id,
                    f"the {tap.get('action')} chip was tapped while it was disabled",
                    subject=str(tap.get("action") or ""),
                ))
        for nav in turn.tablet_events("navigate"):
            if str(nav.get("nav") or "") == "dead_chip":
                out.append(Finding(
                    "FAKE_CONTROL", turn.turn_id,
                    "a context chip was tapped that the tablet no longer held",
                    subject="context chip",
                ))
    return out


def _stale_pending(rec: Any) -> list[Finding]:
    """A change left PENDING for the rest of the session, and the count that reported one.

    The two "changes still waiting" the live session warned about at merge were the two UNDO
    offers for changes that had already succeeded. Availability of an undo is not unfinished
    work.
    """
    out: list[Finding] = []
    stopped = rec.session.get("stopped_at")
    end = float(stopped) if isinstance(stopped, (int, float)) else max(
        [float(e.get("ts") or 0.0) for e in rec.events] or [0.0])
    for proposal in sorted(rec.proposals.values(), key=lambda p: p.staged_at or 0.0):
        if proposal.status != "PENDING" or proposal.staged_at is None:
            continue
        out.append(Finding(
            "STALE_PENDING_ACTION", proposal.turn_id or _turn_at(rec, proposal.staged_at),
            f"{proposal.proposal_id} ({proposal.operation or 'a change'}"
            + (" — an undo offer" if proposal.undo_of else "")
            + f") stayed PENDING for {end - proposal.staged_at:.0f} s, to the end of the session",
            subject=proposal.operation or proposal.proposal_id,
        ))
    for turn in rec.turns:
        for toast in turn.tablet_events("toast"):
            words = str(toast.get("message") or "")
            if not re.search(r"\bstill waiting\b|\bchanges waiting\b", words, re.I):
                continue
            undone = [p for p in rec.proposals.values() if p.status == "PENDING" and p.undo_of]
            if undone:
                out.append(Finding(
                    "STALE_PENDING_ACTION", turn.turn_id,
                    f"the tablet said changes were still waiting; {len(undone)} of the pending "
                    f"proposal(s) are undo offers for changes already made",
                    subject="undo",
                ))
    return out


def _starved(rec: Any) -> list[Finding]:
    """The owner's own read, refused because the turn had already read too much."""
    out: list[Finding] = []
    for turn in rec.turns:
        refusals = [t for t in turn.tools if t.outcome == "refused" and STARVED_RE.search(t.error or "")]
        if refusals:
            names = Counter(t.tool for t in refusals)
            out.append(Finding(
                "FOREGROUND_STARVED", turn.turn_id,
                f"{len(refusals)} read(s) the owner asked for were refused for having read too "
                f"long: " + ", ".join(f"{name} × {n}" for name, n in names.most_common()),
                subject=next(iter(names)),
            ))
        for event in turn.commands:
            if event.get("ok") is False and str(event.get("code") or "") == "landing_unavailable":
                out.append(Finding(
                    "FOREGROUND_STARVED", turn.turn_id,
                    f"a dock landing was refused {event.get('code')} while the turn was reading",
                    subject=str(event.get("command") or "open.area"),
                ))
    return out


def _self_knowledge(rec: Any) -> list[Finding]:
    """A question the manifest answers, disclaimed instead.

    The manifest is asked whether it has an entry for the question. If it has, and the answer
    disclaimed the interface or referred the owner to whoever built it, the product did not
    know itself. A sentence that is feedback rather than a question is not this: that is
    OWNER_FEEDBACK_IGNORED, and the two are kept apart here.
    """
    from app.observability import feedback as feedback_mod
    from app.observability import ui_semantics

    out: list[Finding] = []
    for turn in rec.turns:
        question, answer = turn.question or turn.raw_text, turn.answer
        if not question or not answer:
            continue
        if feedback_mod.recognise(question) is not None:
            continue
        known = ui_semantics.lookup(question)
        if known is None or not DISCLAIMS_RE.search(answer):
            continue
        out.append(Finding(
            "SELF_UI_KNOWLEDGE_ERROR", turn.turn_id,
            f"asked about {known.entry.control} and disclaimed it; the manifest has the answer"
            + (f" (the {known.entry.command} command)" if known.entry.command else ""),
            subject=known.entry.key,
        ))
    return out


# What leaves this module of an owner_feedback event (round 9, F-OBS2-01): the fields the report
# and the proposals print, each passed through the timeline's own scrub again, and nothing else of
# the raw event. Where the report goes is the owner's alone (see read()).
_FEEDBACK_FIELDS = ("ts", "session_id", "turn_id", "branch_id", "shape", "text", "screen", "entities", "tab",
                    "branch_status", "nearby")
# How much of an answer an ignored feedback row carries: the report prints 160 characters of it.
_ANSWER_CHARS = 200


def _kept_feedback(event: dict[str, Any]) -> dict[str, Any]:
    from app.observability.timeline import scrub

    return scrub({name: event[name] for name in _FEEDBACK_FIELDS if name in event})


def _said(text: Any, limit: int) -> str:
    """Owner or assistant words as they may leave this module: credential shapes, contact details
    and the customer names the process knows taken out by the timeline's own rule, and bounded."""
    from app.observability.timeline import scrub_text

    return scrub_text(" ".join(str(text or "").split()))[:limit]


def _feedback(rec: Any) -> tuple[list[Finding], list[dict[str, Any]], list[dict[str, Any]]]:
    """What the owner said about the product, and whether anything wrote it down."""
    from app.observability import feedback as feedback_mod

    recorded = [_kept_feedback(e) for e in _events(rec, "owner_feedback")]
    by_turn = {str(e.get("turn_id") or ""): e for e in recorded}
    out: list[Finding] = []
    ignored: list[dict[str, Any]] = []
    for turn in rec.turns:
        said = turn.question or turn.raw_text
        recognition = feedback_mod.recognise(said)
        if recognition is None:
            continue
        if turn.turn_id in by_turn:
            continue
        answer = _said(turn.answer, _ANSWER_CHARS)
        ignored.append({"turn_id": turn.turn_id, "shape": recognition.kind, "text": _said(recognition.text, 2000),
                        "answer": answer, "at": turn.started_at,
                        # The card types a page said it drew: as identifiers, or withheld (round 11, F-OBS2-01).
                        "screen": [as_identifier(c.get("type")) for r in turn.tablet_events("render")
                                   for c in (r.get("cards") or []) if isinstance(c, dict)][:6]})
        out.append(Finding(
            "OWNER_FEEDBACK_IGNORED", turn.turn_id,
            f"the owner asked for this to be recorded ({recognition.kind}) and no owner_feedback "
            f"event exists for the turn; the answer was: " + (answer[:120] or "nothing"),
            subject="owner_feedback",
        ))
    return out, recorded, ignored


def _collisions(rec: Any) -> list[Finding]:
    """Two fingers on one control, or two controls in one place.

    The tablet reports the first itself (`tablet_hold` with `phase: "multitouch"` and the
    finger count) and would report the second as `tablet_collision`. A collision that ended a
    recording is GESTURE_COLLISION's — the narrower class, already filed by the classifier —
    so a turn that carries that one is left alone here.
    """
    out: list[Finding] = []
    gesture_turns = {t.turn_id for t in rec.turns if "GESTURE_COLLISION" in t.classes}
    # The second fingers that ENDED a recording belong to GESTURE_COLLISION, which now files
    # one per hold (app/observability/touch.py) and says how long the recording it killed was.
    # A second finger that landed without ending anything is still this class's.
    closed = [_clock_ms(e) for e in rec.events
              if str(e.get("kind") or "") == "tablet_hold"
              and str(e.get("phase") or "") == "release"]
    ended_a_hold = {
        id(event) for event in rec.events
        if str(event.get("kind") or "") == "tablet_hold"
        and str(event.get("phase") or "") == "multitouch"
        and any(abs(at - _clock_ms(event)) <= touch.MULTITOUCH_NEAR_MS for at in closed)
    }
    for event in rec.events:
        kind = str(event.get("kind") or "")
        ts = float(event.get("ts") or 0.0)
        turn_id = str(event.get("turn_id") or _turn_at(rec, ts))
        if kind == "tablet_hold" and str(event.get("phase") or "") == "multitouch":
            if turn_id in gesture_turns or id(event) in ended_a_hold:
                continue
            fingers = event.get("fingers") if isinstance(event.get("fingers"), int) else 2
            out.append(Finding(
                "COLLISION", turn_id,
                f"{fingers} fingers landed on the {event.get('target') or 'orb'} at once",
                subject=str(event.get("target") or ""),
            ))
        elif kind == "tablet_collision":
            out.append(Finding(
                "COLLISION", turn_id,
                f"{event.get('a') or 'a control'} and {event.get('b') or 'another'} overlap by "
                f"{event.get('overlap') or '?'} px",
                subject=str(event.get("a") or ""),
            ))
    return out


def _whole(value: Any) -> int | None:
    """A count or a size the tablet sent, as a whole number; None when it sent none, or sent
    something that is not one. A value a page sent that is not a number is not a reason for the
    rule reading it to fail (round 9, F-OBS2-02), and it is not nought either: it says nothing
    about what was there (round 12, O1-02), so a rule given one has no measurement to compare.
    A float is one only when it is whole (874.0): 12.7 is not a count of characters or of pixels,
    and cutting it to 12 would make up a measurement the page never sent."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    if isinstance(value, str) and _WHOLE.fullmatch(value.strip()):
        return int(value.strip())
    return None


_WHOLE = re.compile(r"-?[0-9]{1,15}")


def _focus_lost(rec: Any) -> list[Finding]:
    """The owner's place, taken away by something that redrew.

    Two shapes. The tablet says so — `tablet_focus` with a lost state, or a composer field
    whose contents went from something to nothing across a render. Or the scroll position did:
    a deep scroll, then a redraw, then the top of the same document, with no navigation
    between to explain it.

    Only between two measurements that can both be read (round 12, O1-02): a count that is not
    a number is not an empty field, and a depth that is not one is not the top of the page, so
    neither is a place lost, and neither is the place he was in when the next one comes.
    """
    out: list[Finding] = []
    ordered = sorted(rec.events, key=lambda e: (float(e.get("ts") or 0.0), int(e.get("seq") or 0)))
    typed: int | None = None
    for i, event in enumerate(ordered):
        kind = str(event.get("kind") or "")
        ts = float(event.get("ts") or 0.0)
        turn_id = str(event.get("turn_id") or _turn_at(rec, ts))
        if kind == "tablet_focus" and str(event.get("state") or "") in ("lost", "blur"):
            out.append(Finding(
                "FOCUS_LOST", turn_id,
                f"the keyboard left {event.get('name') or 'a field'}"
                + (f" when {event.get('cause')}" if event.get("cause") else ""),
                subject=str(event.get("name") or ""),
            ))
        elif kind == "tablet_compose_field":
            chars = _whole(event.get("chars"))
            if typed is not None and typed > 0 and chars == 0:
                out.append(Finding(
                    "FOCUS_LOST", turn_id,
                    f"the composer's {event.get('name') or 'field'} held {typed} character(s) "
                    f"and then held none",
                    subject=str(event.get("name") or ""),
                ))
            typed = chars
        elif kind == "tablet_scroll" and _whole(event.get("depth")) == 0:
            deep, at = None, i
            for j in range(i - 1, -1, -1):
                earlier = ordered[j]
                earlier_kind = str(earlier.get("kind") or "")
                if ts - float(earlier.get("ts") or 0.0) > FOCUS_S:
                    break
                if earlier_kind in ("command", "tablet_navigate", "tablet_tab"):
                    break     # he moved: the top of a new screen is where he asked to be
                if earlier_kind == "tablet_scroll":
                    depth = _whole(earlier.get("depth"))
                    if depth is None:
                        break     # where he was then cannot be read
                    if depth > 0:
                        deep, at = earlier, j
                        break
            if deep is None:
                continue
            before, after = _whole(deep.get("height")), _whole(event.get("height"))
            if before is None or after is None or before != after:
                continue      # a different document, or one that cannot be told: the place could not be kept
            between = [e for e in ordered[at:i]
                       if str(e.get("kind") or "") in ("tablet_render", "branch_focused")]
            if not between:
                continue
            out.append(Finding(
                "FOCUS_LOST", turn_id,
                f"the scroll was {deep.get('depth')} px down the same {event.get('height')} px "
                f"document and returned to the top after {len(between)} redraw(s), with no "
                f"navigation between",
                subject="scroll",
            ))
    return out


RULES = (_action_ui_stuck, _split_findings, _wrong_branch, _wrong_entity, _duplicate_renders,
         _summary_answered_with_profiles, _empty_notifications, _touches, _progressive,
         _navigation, _controls, _stale_pending, _starved, _self_knowledge, _collisions,
         _focus_lost)


# --------------------------------------------------------------------- the two outcomes


def backend_outcome(turn: Any) -> str:
    """What the SERVER did. The old report's only column."""
    proposals = [p for p in turn.proposals if p.proposal_id and not p.undo_of]
    if any(p.status == "VERIFIED" for p in proposals):
        return "VERIFIED"
    if any(p.status == "UNVERIFIED" for p in proposals):
        return "UNVERIFIED"
    if any(p.status in ("FAILED", "STALE", "EXPIRED", "REVOKED") for p in proposals):
        return next(p.status for p in proposals if p.status in ("FAILED", "STALE", "EXPIRED", "REVOKED"))
    if any(p.committed for p in proposals):
        return "EXECUTING"
    if proposals:
        return "STAGED"
    if any(t.outcome in ("error", "exception", "unprepared") for t in turn.tools):
        return "TOOL_ERROR"
    if any(t.outcome == "refused" for t in turn.tools):
        return "REFUSED"
    if any(t.outcome in ("ok", "staged") for t in turn.tools):
        return "READ_OK"
    if turn.error_kind:
        return "ERROR"
    if turn.answer:
        return "ANSWERED"
    return "NOTHING"


def visible_outcome(turn: Any, found: list[Finding]) -> str:
    """What the OWNER could see. The column the report did not have.

    The worst of what went wrong, not the first: a turn whose feedback was discarded AND whose
    cards were late is a turn whose feedback was discarded.
    """
    names = {f.name for f in found}
    for name in sorted(names, key=lambda n: (-SEVERITY[n], CLASSES.index(n))):
        return VISIBLE_WORD[name]
    cards = [c for r in turn.tablet_events("render") for c in (r.get("cards") or []) if isinstance(c, dict)]
    if turn.error_kind:
        return "NOTHING"
    if cards:
        return "DRAWN"
    if turn.answer:
        return "SPOKEN"
    return "NOTHING"


# What a class does to the verdict. At this severity or above the owner could not do or see
# the thing at all — a change that never said it was made, feedback thrown away, a half that
# drew nothing, his own read refused — and the turn is a failure whatever the backend managed.
# Below it the turn happened and cost him something: a redraw, a dead tap, a late card.
FAILS_THE_TURN = 5
# Backend states that are a failure on their own, whatever the screen did.
BACKEND_FAILED = frozenset({"UNVERIFIED", "FAILED", "STALE", "EXPIRED", "REVOKED", "TOOL_ERROR", "ERROR"})


def experience_outcome(turn: Any, found: list[Finding]) -> str:
    """The verdict the owner would give.

    A turn is NOT successful because the backend verified. It is successful when the backend
    did its part AND nothing the owner could see went wrong.
    """
    worst = max((SEVERITY[f.name] for f in found), default=0)
    if worst >= FAILS_THE_TURN or backend_outcome(turn) in BACKEND_FAILED:
        return "FAILED"
    if worst:
        return "PARTIAL"
    if turn.outcome == "successful":
        return "SUCCESSFUL"
    return "FAILED" if turn.outcome == "failed" else "PARTIAL"


def _subjects(turn: Any, found: list[Finding]) -> list[str]:
    """What each row of a turn is ABOUT: the changes it staged, else what it did."""
    operations = [p.operation for p in turn.proposals if p.operation and not p.undo_of]
    if operations:
        return sorted(set(operations))
    worst = sorted(found, key=lambda f: (-SEVERITY[f.name], CLASSES.index(f.name)))
    subject = next((f.subject for f in worst if f.subject), "")
    if subject:
        return [subject]
    tools = [t.tool for t in turn.tools if t.outcome in ("ok", "staged")]
    if tools:
        return [tools[0]]
    return [str((turn.lane or {}).get("family") or turn.cluster or "the turn")]


# What a finding may carry of what a page sent (round 11, R9-F-observability2-F-OBS2-01). The
# rules above write a page's own values into their signals and subjects — the field the keyboard
# left (`tablet_focus.name`), why (`cause`), the control two fingers landed on, a card's state —
# and a page is not trusted to have put an identifier there: /telemetry keeps whatever words it
# sent (bounded, and scrubbed only of the shapes and the names the process has been told), and a
# customer's name is neither. So every string a page sent in a field that names a thing, and that
# is not an identifier, is withheld from every finding, wherever a rule put it, before anything
# leaves this module; then the whole signal passes the timeline's own rule (which is all a page's
# free text — an exception's message — gets, see _PAGE_TEXT). An identifier is what CLIVE's pages
# put in these fields:
# lower-case letters and digits joined by . _ : / # or - (`composer-subject`, `ask_bar`,
# `order.add_note`, `br_left`, `1938`), or a Shopify id.
_IDENTIFIER = PAGE_IDENTIFIER
_WITHHELD = WITHHELD
# The frame every event carries, written by the Mac whoever sent the event; and the fields that are
# a page's free text by what they are for — an exception's message, its detail, words on the glass
# — which the report quotes as text (scrubbed by the timeline's rule, and bounded) because a
# frontend exception is read by its words. Every other field names a thing: a field, a control, a
# card, a state, a cause.
_FRAME = frozenset({"ts", "iso", "seq", "test_session_id", "source", "kind"})
_PAGE_TEXT = frozenset({"message", "detail", "text", "question"})
# How deep page_words looks into what a page sent: deeper than /telemetry keeps anything
# (app/routes/observe.py MAX_DEPTH, 6), so every string a page could have sent is found.
_PAGE_DEPTH = 8


WITHHELD_MARK = WITHHELD


def _a_told_name(text: str) -> bool:
    """Whether a customer name this process has been told stands in `text`, its words joined by any
    of an identifier's separators ('zoe_quill', 'zoe.quill', 'zoe-quill' for Zoe Quill): a page
    can send a name in an identifier's shape, and the shape does not make it one (round 9,
    R9-F-observability2-F-OBS2-01, ruled still present at round 12)."""
    from app.observability.timeline import holds_a_told_name

    return holds_a_told_name(text)


def as_identifier(value: Any) -> str:
    """A value a page sent, as the report may count it: an identifier as it is
    (screens.page_identifier), and WITHHELD when it is not one or when a told name stands in it
    ('' stays '')."""
    shown = page_identifier(value)
    return WITHHELD if shown not in ("", WITHHELD) and _a_told_name(shown) else shown


def as_number(value: Any) -> Any:
    """A number a page sent, as the report may print it: a number as it is, None as None, and
    anything else — a page can put words in any field — WITHHELD."""
    if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return value
    return _WITHHELD


def as_path(value: Any) -> str:
    """A path a page sent (an image's src, which the page cuts to its path), as the report may print
    it: kept when what follows its leading slashes is an identifier ('/media/shopify/3fa2/240'),
    else WITHHELD ('' stays '')."""
    text = str(value if value is not None else "").strip()
    rest = text.lstrip("/")
    shown = as_identifier(rest)
    return shown if shown in ("", _WITHHELD) else text[: len(text) - len(rest)] + shown


def _from_a_page(event: dict[str, Any]) -> bool:
    return str(event.get("source") or "") == "tablet" or str(event.get("kind") or "").startswith("tablet_")


class PageWords:
    """The strings a page sent that are not identifiers (page_words), ready to be withheld from a
    signal. Each is filed under what it begins with — its first run of ASCII letters, digits and
    underscores when it begins with one, else its first character — and then by length, longest
    first. A string can stand whole in a signal only where the signal has such a start (at the
    beginning, or just after a character that is none of those), and there it begins with exactly
    the run or the character the signal has there, so withholding is one look at each start and a
    few set lookups, however many strings a session sent. The first round-11 rule searched each
    signal once per string: some ten seconds for 3,000 signals against the 20,000 strings it then
    stopped collecting at, and strings past that cap were not withheld at all. There is no cap now."""

    def __init__(self, words: set[str]) -> None:
        index: dict[str, dict[int, set[str]]] = {}
        for word in words:
            if word:
                index.setdefault(_lead(word), {}).setdefault(len(word), set()).add(word)
        self._index = {lead: sorted(by_length.items(), reverse=True) for lead, by_length in index.items()}
        self._count = sum(len(same) for by_length in index.values() for same in by_length.values())

    def __len__(self) -> int:
        return self._count

    def withhold(self, text: str) -> str:
        """`text` with every page string that stands whole in it (no ASCII letter, digit or
        underscore either side, the rule round 11 began with) replaced by WITHHELD — the longest
        where two begin at one place, and two that overlap as one — and then looked at again,
        between the marks, until none is left: withholding one can leave a neighbour standing whole
        that did not before ('-d' in 'abc-d' once 'abc' is withheld). Each look that finds one
        withholds at least one character that was not a mark, so this ends; what it returns has no
        page string standing whole outside a mark."""
        if not self._index or not text:
            return text
        out = self._once(text)
        while out != text:
            text = out
            out = _WITHHELD.join(self._once(part) for part in text.split(_WITHHELD))
        return out

    def _once(self, text: str) -> str:
        spans: list[list[int]] = []
        size = len(text)
        for start in _STARTS.finditer(text):
            lengths = self._index.get(start.group())
            if lengths is None:
                continue
            begin = start.start()
            for length, same in lengths:
                end = begin + length
                if end > size or (end < size and _word_char(text[end])) or text[begin:end] not in same:
                    continue
                if spans and begin < spans[-1][1]:
                    spans[-1][1] = max(spans[-1][1], end)     # overlaps the last: one mark for both
                else:
                    spans.append([begin, end])
                break
        if not spans:
            return text
        out: list[str] = []
        at = 0
        for begin, end in spans:
            out.append(text[at:begin])
            out.append(_WITHHELD)
            at = end
        out.append(text[at:])
        return "".join(out)


# Where a page string can begin in a signal, and what it must then begin with: a run of letters,
# digits and underscores, or one other character, either at the start or after one of those others.
_STARTS = re.compile(r"(?<![0-9A-Za-z_])(?:[0-9A-Za-z_]+|.)", re.S)
_RUN = re.compile(r"[0-9A-Za-z_]+")


def _lead(word: str) -> str:
    """What a page string is filed under: its first run of letters, digits and underscores when it
    begins with one, else its first character (see PageWords)."""
    run = _RUN.match(word)
    return run.group() if run else word[0]


def _word_char(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch == "_")


def page_words(events: list[dict[str, Any]]) -> PageWords:
    """Every string a page sent in these events that is not an identifier, or is one a told name
    stands in (as_identifier). The report's own classifier withholds them from its signals too
    (report.reconstruct)."""
    found: set[str] = set()

    def walk(value: Any, depth: int) -> None:
        if isinstance(value, str):
            text = value.strip()
            if text and not (len(text) <= 64 and _IDENTIFIER.fullmatch(text) and not _a_told_name(text)):
                found.add(text)
        elif depth < _PAGE_DEPTH and isinstance(value, dict):
            for key, item in value.items():
                walk(str(key), depth + 1)
                walk(item, depth + 1)
        elif depth < _PAGE_DEPTH and isinstance(value, (list, tuple)):
            for item in value:
                walk(item, depth + 1)

    for event in events:
        if isinstance(event, dict) and _from_a_page(event):
            for key, value in event.items():
                if key not in _FRAME and key not in _PAGE_TEXT:
                    walk(value, 0)
    return PageWords(found)


def withheld(text: str, words: PageWords) -> str:
    """`text` with every word a page sent withheld, each where it stands as a whole, and then
    passed through the timeline's own rule (credential shapes, contact details, known names)."""
    from app.observability.timeline import scrub_text

    return scrub_text(words.withhold(str(text or "")))


def _leaving(findings: list[Finding], rec: Any) -> list[Finding]:
    """The findings as they may leave this module (see _IDENTIFIER)."""
    words = page_words(rec.events)
    return [Finding(f.name, f.turn_id, withheld(f.signal, words), subject=withheld(f.subject, words), basis=f.basis)
            for f in findings]


def read(rec: Any) -> Reading:
    """Everything this module finds in one timeline, and the two outcomes per turn.

    Who sees it (round 9, F-OBS2-01): what this returns carries the owner's words and the
    assistant's answers, scrubbed by the timeline's own rule on the way out. It is read by
    app/observability/report.py (reconstruct) and nothing else, and the report goes only to the
    owner: into reports/, written 0600 in a 0700 folder under a checked session id
    (session.write_private_text, report_target), by the command line and the Control app on the
    server. No route answers with it and no screen is given it — tests/test_visible_privacy.py
    holds both. What a PAGE sent reaches a finding only as an identifier (round 11, F-OBS2-01:
    _leaving), so a customer's name a page put in a field's name or a cause is not carried into
    the report's tables."""
    findings: list[Finding] = []
    errors: list[str] = []
    recorded: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    for rule in RULES:
        try:
            findings.extend(rule(rec))
        except Exception as exc:  # noqa: BLE001 — one rule that cannot read a timeline is not a crash
            errors.append(f"{rule.__name__}: {type(exc).__name__}")
            # The rule and the kind of failure, never the exception's own words (round 9,
            # F-OBS2-02): those carry the value that could not be read — a telemetry field, which
            # can be anything a page sent, a credential included.
            log.warning("the experience rule %s could not read this timeline (%s)", rule.__name__, type(exc).__name__)
    try:
        extra, recorded, ignored = _feedback(rec)
        findings.extend(extra)
    except Exception as exc:  # noqa: BLE001 — the same rule for the same reason
        errors.append(f"_feedback: {type(exc).__name__}")
        log.warning("owner feedback could not be read from this timeline (%s)", type(exc).__name__)
    # What a page sent leaves only as an identifier (round 11, F-OBS2-01): every signal and subject,
    # whichever rule wrote it, before a row, a turn or the report is given it.
    findings = _leaving(findings, rec)
    # Exact repeats are one finding: eleven Homes that each replayed the record in hand are one
    # defect said eleven times, and a report that lists it eleven times buries the other ten.
    seen: set[tuple[str, str, str]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (finding.name, finding.turn_id, finding.signal)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    findings = sorted(unique, key=lambda f: (CLASSES.index(f.name), f.turn_id))
    reading = Reading(findings=findings, feedback=recorded, ignored_feedback=ignored, errors=errors)
    for turn in rec.turns:
        mine = reading.by_turn(turn.turn_id)
        backend = backend_outcome(turn)
        visible = visible_outcome(turn, mine)
        experience = experience_outcome(turn, mine)
        why = "; ".join(dict.fromkeys(f.signal for f in mine))
        for subject in _subjects(turn, mine):
            reading.rows.append(Row(turn_id=turn.turn_id, subject=subject, backend=backend,
                                    visible=visible, experience=experience, why=why))
    return reading


def apply(rec: Any) -> Reading:
    """Read the timeline and put what it says on the turns themselves.

    The classes join `turn.classes` so section 5, section 12 and the improvement candidates
    see them like any other; `turn.backend`, `turn.visible` and `turn.experience` are the two
    outcomes and the verdict.
    """
    reading = read(rec)
    for turn in rec.turns:
        mine = reading.by_turn(turn.turn_id)
        for finding in mine:
            if finding.name not in turn.classes:
                turn.classes.append(finding.name)
                turn.signals.append(finding.signal)
            elif finding.signal not in turn.signals:
                turn.signals.append(finding.signal)
        turn.backend = backend_outcome(turn)
        turn.visible = visible_outcome(turn, mine)
        turn.experience = experience_outcome(turn, mine)
    return reading
