"""What a finger actually did (§21). Four classes where the report had one.

The 11 September report said **"A value had to be exact and a voice could not make it so —
62 occurrences"** and made the precision-input path its number one improvement candidate and
speech its number two. Both were wrong, and wrong for the same reason: the analyser had a
single bucket, `tablet_recording_too_short`, and poured every short touch into it.

What the timeline actually holds for that evening:

    132 hold-starts. 131 report target "dock", one "orb", and NO OTHER TARGET EXISTS
    IN THE FILE — the tablet has no record of a touch ever reaching anything else.
    123 of them paired with a release: 76 under 200 ms, 63 of those accepted and sent
    to the recogniser, which is exactly the count of `recording_too_short` events.
    Seventeen bursts, the two largest being 8 taps in 2 s (eleven seconds before the
    owner said "wherever I press just leads to you listening") and 26 taps in 10 s.
    ZERO commands were posted anywhere inside that 26-tap window.

Twenty-six attempts to press something in ten seconds, every one delivered to the speech
recogniser, none of them reaching a control. That is a CSS stacking context (the branch bar
sits inside `.orb-zone`, a positioned element at `z-index: 1`, and the voice target is a
sibling at 3 with `inset: 0` in orb mode) — not a speech-quality problem, and not a request
for a keyboard. One interaction defect produced two false engineering priorities.

So this module reads each touch and files one of four things:

    CONTROL_TAP_MISROUTED_TO_VOICE  a short pointer interaction that began on or over an
                                    interactive control and became a recording.
    REAL_SHORT_VOICE_RECORDING      a genuine attempt to speak that was too short.
    GESTURE_COLLISION               a second finger, a split or a fork ended the recording.
    PRECISION_INPUT_REQUIRED        real evidence the owner was attempting exact entry.

THE HEURISTIC, and what it costs.

Workstream A is adding an explicit touch-ownership state machine which records the real
pointer OWNER and TARGET per touch. Where those exist this is not a heuristic at all: a touch
whose owner is not the voice layer, or whose target is an interactive control, is a misrouted
control tap and nothing else needs reading. That is the `direct` basis below, and it is the
only one that cannot be argued with.

On an older timeline — the 11 September file, where every touch says `target: "dock"` — the
class is inferred from four signals the brief names, in this order:

 1. **multitouch** · a `hold` with `phase: "multitouch"` within 250 ms of the release, or a
    split / merge / fork inside the hold's window. In the real file every one of the eighteen
    multitouch events lands 2–3 ms AFTER a release: the second finger ENDED the hold. That is
    GESTURE_COLLISION and it is tested first, because a recording ended by a gesture tells you
    nothing about either speech or targeting.
 2. **duration** · under `TAP_MS` (200 ms) a touch is a tap. Nobody presses and speaks in
    under a fifth of a second; the tablet's own "too short" message exists because there is no
    speech down there.
 3. **burst shape** · `BURST_MIN` (3) or more taps inside `BURST_S` (12 s). A person does not
    make three separate attempts to speak in twelve seconds in sub-200 ms flickers. He is
    pressing something that is not answering.
 4. **what followed** · no accepted `command` anywhere in the burst's window, and no turn
    submitted by any tap in it. This is the load-bearing one: if the controls were reachable a
    tap would have posted a command. A burst of taps with no command in it is proof that
    nothing on the screen received a touch.

A burst that also sits within 30 s of the owner saying out loud that pressing leads to
listening is reported as `corroborated` rather than `inferred`, because it is.

**False-positive risk, stated plainly.** The `inferred` basis can be wrong in one shape: a man
repeatedly stabbing the voice target itself — genuinely trying to talk and failing to hold —
looks identical to a man stabbing a control behind it, because the old timeline records the
same `target: "dock"` for both. Three things bound that risk and none of them removes it: a
burst needs three taps, it needs zero commands, and a single isolated short touch is never
called a misrouted tap (it is left as `REAL_SHORT_VOICE_RECORDING`, the weaker reading, and
its signal says the duration is below the tap threshold and no owner was recorded). The
consequence is the one worth having: on an old timeline this class can over-count real speech
attempts as control taps inside a burst, and it will never invent a precision-input failure
out of a 70 ms dock tap, which is the error that actually happened. Every inferred finding
names its basis so a reader can disagree with it, and workstream A's owner/target retires the
inference entirely.

And PRECISION_INPUT_REQUIRED is now what its name says. It is filed on evidence of exact
entry — a value typed into a composer field, a transcript the normaliser had to correct before
it was usable, a query naming a dimension the language does not have — and never on a short
recording, which is what produced 61 of the old report's 62 rows.

Nothing here executes anything, reads a tool or scores with a model: it is a function from a
list of events to a list of touches, each carrying the evidence that named it.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# The four classes, in the order they are tested.
CLASSES: tuple[str, ...] = (
    "CONTROL_TAP_MISROUTED_TO_VOICE", "GESTURE_COLLISION", "REAL_SHORT_VOICE_RECORDING",
    "PRECISION_INPUT_REQUIRED",
)
SEVERITY: dict[str, int] = {
    # The worst interaction defect the session has: the owner could not operate the interface
    # at all, said so twice, and hammered it twenty-six times.
    "CONTROL_TAP_MISROUTED_TO_VOICE": 6,
    "GESTURE_COLLISION": 4,
    # He meant to speak and was too quick. Cheap, and nothing like a P0.
    "REAL_SHORT_VOICE_RECORDING": 2,
    "PRECISION_INPUT_REQUIRED": 2,
}
COMPONENT: dict[str, str] = {
    "CONTROL_TAP_MISROUTED_TO_VOICE": "the tablet's touch ownership (web/style.css stacking contexts, web/app.js): the voice target is painted and hit-tested over interactive controls",
    "GESTURE_COLLISION": "the tablet's touch handling (web/app.js): a second finger ended the recording before the recogniser saw any speech",
    "REAL_SHORT_VOICE_RECORDING": "the hold gesture (web/app.js) and what it tells the owner: a hold too short to carry speech should say so where his finger is",
    "PRECISION_INPUT_REQUIRED": "the precision-input path (the composer's fields, app/routes/command.py)",
}
TASKS: dict[str, str] = {
    "CONTROL_TAP_MISROUTED_TO_VOICE": "fix touch ownership FIRST: voice activates only from a deliberate voice target that is never an ancestor of, and never painted over, an interactive control. Not a bigger hit region with more exceptions. Until this is done every speech measurement in the session is contaminated.",
    "GESTURE_COLLISION": "the tablet's touch handling ended the recording. Cover it with a two-finger gesture in the tablet gate and assert ZERO turns posted; nothing here is speech's to fix.",
    "REAL_SHORT_VOICE_RECORDING": "tell him at the finger, not after the fact: the hold target itself should show that it is listening and that nothing was captured. Do not tune the recogniser for this — no audio reached it.",
    "PRECISION_INPUT_REQUIRED": "give the field a keyboard on the card rather than another attempt at saying it.",
}
VISIBLE_WORD: dict[str, str] = {
    "CONTROL_TAP_MISROUTED_TO_VOICE": "TAP_SWALLOWED",
    "GESTURE_COLLISION": "GESTURE_ENDED_IT",
    "REAL_SHORT_VOICE_RECORDING": "TOO_SHORT",
    "PRECISION_INPUT_REQUIRED": "COULD_NOT_SAY_IT",
}

# ------------------------------------------------------------------------ the thresholds

# Under this, a pointer interaction is a tap and not a hold-to-speak.
TAP_MS = 200.0
# Taps this many inside this window are somebody pressing, not somebody speaking.
BURST_MIN = 3
BURST_S = 12.0
# How close to a release a second finger still counts as having ended the hold. The real
# file's multitouch events land 2–3 ms after the release they ended.
MULTITOUCH_NEAR_MS = 250.0
# How long after a burst the owner saying "wherever I press just leads to you listening"
# still corroborates it. His was eleven seconds after an eight-tap burst.
OWNER_WINDOW_S = 30.0
# A touch shorter than this never reached the recogniser and is not a recording at all.
FLICK_MS = 5.0
# How much of the owner's sentence travels with a corroborated finding.
OWNER_QUOTE_CHARS = 220

# The voice target, by every name the tablet has used for it. Anything else named as a
# pointer target or owner is an interactive control, and a touch that began there and became
# a recording is misrouted whatever its duration.
VOICE_TARGETS = frozenset({"", "dock", "orb", "talk", "voice", "hold", "mic", "orb-zone", "ask_bar"})
# What the owner says when the voice layer is eating his taps. Matched against `owner_feedback`
# text only — his own words, never the assistant's.
PRESS_LEADS_TO_LISTENING = re.compile(
    r"(?:press|pressing|click|clicking|tap|tapping|touch)\b[^.]{0,60}"
    r"(?:listen|listening|record|recording|hold to speak|you listening)"
    r"|cannot (?:click|press|tap)|can'?t (?:click|press|tap)"
    r"|no (?:actual )?way to (?:click|press|tap)"
    r"|rendering over", re.I)


# --------------------------------------------------------------------------- the records


@dataclass(frozen=True)
class Touch:
    """One pointer interaction, and what it turned out to be."""

    name: str                  # one of CLASSES
    at: float                  # the session clock, seconds
    turn_id: str = ""
    ms: float | None = None
    target: str = ""
    owner: str = ""
    basis: str = "inferred"    # direct | corroborated | inferred
    signal: str = ""
    taps: int = 1              # how many touches this finding stands for (a burst is one)

    def as_dict(self) -> dict[str, Any]:
        return {"class": self.name, "at": self.at, "turn_id": self.turn_id, "ms": self.ms,
                "target": self.target or None, "owner": self.owner or None,
                "basis": self.basis, "signal": self.signal, "taps": self.taps}


@dataclass
class Hold:
    """A hold-start joined to its release, with whatever ended it."""

    start: dict[str, Any]
    release: dict[str, Any] | None = None
    multitouch: list[dict[str, Any]] = field(default_factory=list)

    @property
    def at(self) -> float:
        return float(self.start.get("ts") or 0.0)

    @property
    def clock_ms(self) -> float:
        """The tablet's own millisecond clock where it has one, else the session clock. The
        `ts` of a batch of tablet events is when the Mac received the batch, so several
        hundred events can share one; `t` is when the finger moved."""
        t = self.start.get("t")
        return float(t) if isinstance(t, (int, float)) else self.at * 1000.0

    @property
    def ms(self) -> float | None:
        value = (self.release or {}).get("ms")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def outcome(self) -> str:
        return str((self.release or {}).get("outcome") or "")

    @property
    def target(self) -> str:
        return str(self.start.get("target") or "")

    @property
    def owner(self) -> str:
        """Workstream A's pointer owner, where the timeline has one."""
        for key in ("owner", "pointer_owner", "captured_by"):
            value = self.start.get(key) or (self.release or {}).get(key)
            if value:
                return str(value)
        return ""

    @property
    def turn_id(self) -> str:
        return str(self.start.get("turn_id") or (self.release or {}).get("turn_id") or "")

    @property
    def on_a_control(self) -> bool:
        """Whether the timeline says outright that this touch began on a control.

        True only on a richer timeline: an owner that is not the voice layer, a target that is
        not one of the voice target's names, or an explicit flag. On the 11 September file it
        is false for all 132 holds, because the only targets it holds are `dock` and `orb`.
        """
        if self.start.get("over_control") or self.start.get("on_control"):
            return True
        owner = self.owner.lower()
        if owner and owner not in VOICE_TARGETS:
            return True
        return self.target.lower() not in VOICE_TARGETS


# ----------------------------------------------------------------------------- reading


def holds(events: list[dict[str, Any]]) -> list[Hold]:
    """Every hold-start joined to the release that closed it, with the multitouches around it.

    A multitouch phase is attached to the hold whose release it is within `MULTITOUCH_NEAR_MS`
    of, in either direction: the tablet reports the second finger a couple of milliseconds
    AFTER the release it caused, so a rule that only looked inside the hold would find none of
    the eighteen in the real session.
    """
    ordered = sorted((e for e in events if str(e.get("kind") or "") == "tablet_hold"),
                     key=lambda e: (float(e.get("ts") or 0.0), int(e.get("seq") or 0)))
    out: list[Hold] = []
    open_hold: Hold | None = None
    seconds: list[dict[str, Any]] = []
    for event in ordered:
        phase = str(event.get("phase") or "")
        if phase == "start":
            if open_hold is not None:
                out.append(open_hold)          # a start with no release: still a touch
            open_hold = Hold(start=event)
        elif phase == "multitouch":
            seconds.append(event)
            if open_hold is not None:
                open_hold.multitouch.append(event)
        elif phase == "release" and open_hold is not None:
            open_hold.release = event
            out.append(open_hold)
            open_hold = None
    if open_hold is not None:
        out.append(open_hold)
    # The second fingers that landed just after the release they ended.
    for extra in seconds:
        when = extra.get("t")
        when = float(when) if isinstance(when, (int, float)) else float(extra.get("ts") or 0.0) * 1000.0
        for hold in out:
            if extra in hold.multitouch or hold.release is None:
                continue
            closed = hold.release.get("t")
            closed = float(closed) if isinstance(closed, (int, float)) else hold.at * 1000.0
            if abs(when - closed) <= MULTITOUCH_NEAR_MS:
                hold.multitouch.append(extra)
                break
    return out


def _bursts(taps: list[Hold]) -> list[list[Hold]]:
    """Runs of taps no more than `BURST_S` apart, by the tablet's own clock."""
    if not taps:
        return []
    ordered = sorted(taps, key=lambda h: h.clock_ms)
    runs: list[list[Hold]] = [[ordered[0]]]
    for hold in ordered[1:]:
        if hold.clock_ms - runs[-1][-1].clock_ms <= BURST_S * 1000.0:
            runs[-1].append(hold)
        else:
            runs.append([hold])
    return runs


def _gestures(events: list[dict[str, Any]]) -> list[tuple[float, str]]:
    """The moments a gesture forked or merged the conversation, by session clock."""
    out: list[tuple[float, str]] = []
    for event in events:
        kind = str(event.get("kind") or "")
        ts = float(event.get("ts") or 0.0)
        if kind == "tablet_navigate" and str(event.get("nav") or "") in ("split", "merge"):
            out.append((ts, str(event["nav"])))
        elif kind == "branch_forked":
            out.append((ts, "a fork"))
    return out


def _commands_between(events: list[dict[str, Any]], start: float, end: float) -> list[str]:
    """The accepted commands posted inside a window. A tap that reaches a control posts one of
    these; a window with none in it is a window in which nothing was reached."""
    out: list[str] = []
    for event in events:
        if str(event.get("kind") or "") not in ("command", "command_stage", "row_action"):
            continue
        if event.get("ok") is False:
            continue
        ts = float(event.get("ts") or 0.0)
        if start <= ts <= end:
            out.append(str(event.get("command") or event.get("action") or "a control"))
    return out


def _said_so(events: list[dict[str, Any]], start: float, end: float) -> str:
    """The owner's own words, inside the window, saying that pressing leads to listening."""
    for event in events:
        if str(event.get("kind") or "") != "owner_feedback":
            continue
        ts = float(event.get("ts") or 0.0)
        if not (start <= ts <= end):
            continue
        said = " ".join(str(event.get("text") or "").split())
        if PRESS_LEADS_TO_LISTENING.search(said):
            # Enough of it to carry the sentence that corroborates the class. His own words
            # are the evidence, and a quote cut off before "listening" is not evidence.
            return said[:OWNER_QUOTE_CHARS]
    return ""


def _too_short(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if str(e.get("kind") or "") == "tablet_recording_too_short"]


def _turn_at(turn_starts: list[tuple[float, str]], ts: float) -> str:
    best = ""
    for at, turn_id in turn_starts:
        if at <= ts:
            best = turn_id
    return best


def classify(events: list[dict[str, Any]]) -> list[Touch]:
    """Every touch that became a recording it should not have been, in one timeline.

    One finding per BURST rather than per tap: twenty-six taps in ten seconds are one defect
    pressed twenty-six times, and a report that files twenty-six rows for it buries the other
    nine. The tap count travels in the finding.
    """
    every = sorted(events, key=lambda e: (float(e.get("ts") or 0.0), int(e.get("seq") or 0)))
    turn_starts = [(float(e.get("ts") or 0.0), str(e.get("turn_id") or ""))
                   for e in every if str(e.get("kind") or "") == "turn_started" and e.get("turn_id")]
    gestures = _gestures(every)
    discarded = _too_short(every)
    out: list[Touch] = []

    all_holds = holds(every)
    # A recording the tablet threw away: `outcome: "sent"` means it reached the recogniser,
    # and a `recording_too_short` beside it means the recogniser was handed nothing usable.
    # Both are read, because an older tablet reports only one of them.
    short_times = sorted(float(e.get("t") or (float(e.get("ts") or 0.0) * 1000.0)) for e in discarded)

    def was_discarded(hold: Hold) -> bool:
        if hold.release is None:
            return False
        if hold.outcome == "discarded":
            return True
        closed = hold.release.get("t")
        closed = float(closed) if isinstance(closed, (int, float)) else hold.at * 1000.0
        return any(abs(at - closed) <= 2_000.0 for at in short_times)

    gesture_ended: list[Hold] = []
    control_taps: list[Hold] = []
    real_short: list[Hold] = []
    for hold in all_holds:
        ms = hold.ms
        if ms is not None and ms < FLICK_MS and not hold.multitouch:
            continue                     # a brush, not a recording: the tablet never armed one
        near = [g for _at, g in gestures if abs(_at - hold.at) <= MULTITOUCH_NEAR_MS / 1000.0]
        if hold.multitouch or near:
            gesture_ended.append(hold)
            continue
        if not was_discarded(hold):
            continue                     # a recording that worked is not this module's business
        if hold.on_a_control:
            control_taps.append(hold)
            continue
        if ms is not None and ms < TAP_MS:
            real_short.append(hold)      # a candidate: the burst test below decides
        elif ms is not None:
            real_short.append(hold)

    # GESTURE_COLLISION, one per hold: the second finger is the whole story.
    for hold in gesture_ended:
        fingers = next((e.get("fingers") for e in hold.multitouch
                        if isinstance(e.get("fingers"), int)), 2)
        why = ("a second finger" if hold.multitouch
               else next((g for at, g in gestures if abs(at - hold.at) <= MULTITOUCH_NEAR_MS / 1000.0), "a gesture"))
        out.append(Touch(
            "GESTURE_COLLISION", hold.at, _turn_at(turn_starts, hold.at) or hold.turn_id,
            ms=hold.ms, target=hold.target, owner=hold.owner, basis="direct",
            signal=(f"{fingers} fingers on the {hold.target or 'orb'}: {why} ended a "
                    f"{hold.ms or 0:.0f} ms recording"),
        ))

    # The ones the timeline names outright (workstream A's owner and target).
    for hold in control_taps:
        out.append(Touch(
            "CONTROL_TAP_MISROUTED_TO_VOICE", hold.at,
            _turn_at(turn_starts, hold.at) or hold.turn_id, ms=hold.ms, target=hold.target,
            owner=hold.owner, basis="direct",
            signal=(f"a {hold.ms or 0:.0f} ms touch owned by {hold.owner or 'the voice layer'} "
                    f"on {hold.target or 'a control'} became a recording: the pointer began on "
                    f"an interactive control and the voice layer took it"),
        ))

    # And the ones an older timeline can only infer, by burst shape and by what did not follow.
    taps = [h for h in real_short if h.ms is not None and h.ms < TAP_MS]
    singles = [h for h in real_short if h not in taps]
    for run in _bursts(taps):
        first, last = run[0], run[-1]
        span = (last.clock_ms - first.clock_ms) / 1000.0
        window = (first.at - 0.5, last.at + BURST_S)
        commands = _commands_between(every, *window)
        if len(run) < BURST_MIN or commands:
            singles.extend(run)
            continue
        said = _said_so(every, last.at - OWNER_WINDOW_S, last.at + OWNER_WINDOW_S)
        lengths = ", ".join(f"{h.ms:.0f}" for h in run[:8]) + ("…" if len(run) > 8 else "")
        out.append(Touch(
            "CONTROL_TAP_MISROUTED_TO_VOICE", first.at,
            _turn_at(turn_starts, first.at) or first.turn_id, ms=first.ms,
            target=first.target, owner=first.owner,
            basis="corroborated" if said else "inferred",
            taps=len(run),
            signal=(f"{len(run)} taps in {span:.0f} s, {lengths} ms, every one sent to the "
                    f"recogniser; no control posted a command in the window, and no turn came "
                    f"of any of them"
                    + (f" — and the owner said: “{said}”" if said else "")
                    + f" (target recorded as {first.target or 'nothing'}, so the class is "
                    f"{'corroborated' if said else 'inferred'} from duration, burst shape and "
                    f"the absence of any command)"),
        ))
    for hold in singles:
        out.append(Touch(
            "REAL_SHORT_VOICE_RECORDING", hold.at,
            _turn_at(turn_starts, hold.at) or hold.turn_id, ms=hold.ms, target=hold.target,
            owner=hold.owner, basis="direct" if (hold.ms or 0) >= TAP_MS else "inferred",
            signal=(f"a {hold.ms or 0:.0f} ms hold reached the recogniser with nothing in it"
                    + ("" if (hold.ms or 0) >= TAP_MS else
                       f"; under the {TAP_MS:.0f} ms tap threshold and not part of a burst, and "
                       f"no pointer owner was recorded, so this is the weaker reading of a "
                       f"touch that may have been meant for a control")),
        ))
    return sorted(out, key=lambda t: (t.at, CLASSES.index(t.name)))


def counts(touches: list[Touch]) -> Counter:
    return Counter(t.name for t in touches)


def taps_in(touches: list[Touch], name: str) -> int:
    """How many individual touches a class stands for, as against how many findings."""
    return sum(t.taps for t in touches if t.name == name)


# ------------------------------------------------------------------- precision input


# Evidence that a value had to be got exactly right. Each is a positive record of exact entry;
# none of them is a short recording, which is the whole point of this module.
def precision_evidence(turn: Any) -> list[tuple[str, str]]:
    """What this turn shows about a value that had to be exact, as (what, detail) pairs."""
    out: list[tuple[str, str]] = []
    for event in turn.tablet_events("compose_field"):
        out.append((f"a value was typed into the composer ({event.get('name') or event.get('label') or 'a field'})",
                    f"{event.get('chars') or '?'} character(s)"))
    for event in turn.tablet_events("keyboard"):
        if str(event.get("state") or "") in ("shown", "open"):
            out.append((f"the keyboard was opened on {event.get('name') or 'a field'}",
                        str(event.get("reason") or "typing")))
    stt = turn.stt or {}
    raw, text = str(stt.get("raw_text") or ""), str(stt.get("text") or "")
    # Only a timeline recorded while a normaliser rewrote transcripts can show this: the
    # recogniser's words are now passed on as heard, trimmed and nothing more.
    if raw and text and raw.strip() != text.strip():
        out.append(("the normaliser had to correct the transcript before it was usable",
                    f"{len(raw)} → {len(text)} characters"))
    for event in turn.rejected:
        if event.get("unknown"):
            out.append(("a query named a dimension the language does not have",
                        ", ".join(str(x) for x in event["unknown"])))
    return out
