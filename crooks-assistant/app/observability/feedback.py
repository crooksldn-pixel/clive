"""What the owner says about the product while he is testing it (§16).

    "please log that your split function is broken. It just shows two of the same thing,
     and the applying button is also broken"
    "I've no tool for logging a product bug like that."

    …four turns later…

    "Log — a lot of your functions are broken… especially with the back button, back to
     assistant button and the next button"
    "I still have no tool that logs product feedback."

He did the most valuable thing a tester can do — narrate defects as they happen — and the
machine discarded all of it, twice, and then produced a report that did not mention them.

So a sentence of that shape is recognised as local development feedback, and `record` appends
it to the timeline as an `owner_feedback` event while a TEST SESSION is running. Nothing calls
`record` at turn time any more: the word-matching lane that did so answered the sentence
itself instead of letting the model hear it, and it was removed on 28 September 2026. A
spoken report now reaches the model like every other sentence, and the report finds it in the
transcript with `recognise` (OWNER_FEEDBACK_IGNORED). What an event is, and what it is not:

* It is **observability metadata**, written to the same append-only timeline as everything
  else, and it is what `app/observability/report.py` reads to print OWNER-REPORTED DEFECTS
  verbatim. The owner never has to repeat himself after the session.
* It is **local**. Nothing here reaches Shopify or Gmail; this module imports neither, nor
  the action engine, nor any tool. There is no proposal, no arming, no gesture and no
  approval, because nothing is being changed — writing down what somebody said is not a
  change to the shop.
* It is **test mode only**. `record` writes nothing when no test session is active, so a
  sentence like this on an ordinary day is answered by the assistant as it always was.

D-12, found in the 11 September evening: **a complaint only counted if he said the word
"log".** Sixteen seconds apart —

    20:16:48  "Logical error here. You just pulled up two [name] screens for no reason"
                  → NOT captured. Filed as an unrouted 'orders' request.
    20:17:04  "Log your error there. You just pulled up two in the same UI"
                  → captured.

He stated the defect plainly, was not recorded, and had to repeat it with the magic word in
front. There is a louder instance in the same session that was never captured at all —
*"why is there bullshit on the screen right now?"*, the strongest negative signal of the
evening, which exists in the report only as an unrouted "other" request with an STT_ERROR
beside it.

So a defect report is now recognised by its SHAPE as well as by an imperative to record one: a
statement that the system did something wrong. "That's wrong." "Logical error here." "You just
pulled up two of these." "Why is there X on the screen." "That's not what I asked for."

And the shape rules are deliberately conservative, because the cost of over-reading is worse
than the cost of under-reading: a tester whose approval is filed as a defect stops trusting the
record. The same session's *"Is that not nice? It's actually like"* and *"I actually like"* are
approval; *"Hi"*, *"Crooks OS"* and *"Are you working right now?"* are neither. Each of those
is a NEGATIVE in `tests/test_owner_feedback.py`, and the rules are written to fail them.

On what it holds. The rule for the timeline is ids, counts, tool names and milliseconds, and
the one exception is what the OWNER said — the timeline already carries his question and the
answer on every turn, because a session you cannot read back is not a record. His feedback is
his own words about his own product; it is kept as he said it, bounded, and everything
AROUND it is ids: the branch, the card types on screen, the entity kind and ref, and the ids
of the commands and proposals nearby. No customer's name, no address, no label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.observability import timeline

MAX_FEEDBACK_CHARS = 600
# How far back a command or an action still counts as "what he was doing when he said it".
NEARBY_S = 90.0
MAX_NEARBY = 8

# The shapes the owner actually used, and the ones a tester reaches for. Each is anchored on
# an instruction to RECORD something, or on a plain statement that something is broken — a
# sentence that merely contains the word "log" ("the log says") is not one of these.
KINDS: tuple[tuple[str, Any], ...] = (
    ("log", re.compile(r"\b(?:please )?log(?: that| this| it)?\b(?!\s*(?:says?|file|in\b|out\b|ical\b))", re.I)),
    ("note", re.compile(r"\b(?:note|make a note of|take a note of)\s+(?:that|this|the)\b|\bnote this bug\b", re.I)),
    ("record", re.compile(r"\brecord (?:that|this|it)\b|\bwrite (?:that|this) down\b|\bmake a note\b", re.I)),
    ("save_as_test", re.compile(r"\bsave (?:this|that|it) as a (?:test|case|regression)\b|\bturn (?:this|that) into a test\b", re.I)),
    ("broken", re.compile(r"\b(?:is|are|isn'?t|aren'?t|was|were)\s+(?:completely |totally |still |also |a bit |quite )?"
                          r"(?:broken|not working|buggy|stuck|frozen|dead|wrong|regressed)\b"
                          r"|\bdoes(?:n'?t| not) work(?: at all)?\b"
                          r"|\bthis is (?:a )?bug\b|\bthat'?s (?:a )?bug\b", re.I)),
    # D-12. A defect stated plainly, with no instruction to write it down. Each of these is a
    # sentence that asserts the SYSTEM did something wrong, and each is anchored tightly enough
    # that ordinary conversation does not trip it.
    ("wrong", re.compile(
        # "that's wrong", "this is wrong", "that's not right" — about the thing on the glass.
        r"\b(?:that'?s|thats|this is|it'?s|that is)\s+(?:just |completely |totally |all |quite |a bit )?"
        r"(?:wrong|incorrect|not right|the wrong \w+|rubbish|nonsense|useless|broken)\b"
        # "logical error", "that's an error", "your error there"
        r"|\blogic(?:al)? error\b|\b(?:that'?s|this is) an error\b|\byour error\b"
        # "that's not what I asked for" / "that's not what I wanted" / "I didn't ask for that"
        r"|\bnot what i (?:asked|wanted|meant|said)\b|\bi did ?n'?t ask for\b"
        r"|\bthat'?s not what i\b", re.I)),
    ("did_the_wrong_thing", re.compile(
        # "you just pulled up two screens", "you've opened the wrong one", "it showed me
        # somebody else". A second person or the product itself, plus a mistake.
        r"\b(?:you|it|you'?ve|you have|it'?s|it has)\s+(?:just |already )?"
        r"(?:pulled up|opened|shown|showed|drew|drawn|gave|given|brought up|put up)\s+(?:me |us )?"
        r"(?:the wrong|two|2|the same|somebody else|someone else|another)\b"
        r"|\btwo of the same\b|\btwo (?:\w+ )?screens? for no reason\b"
        r"|\bsame (?:thing|screen|card) twice\b", re.I)),
    ("why_is_it", re.compile(
        # "why is there X on the screen", "why can't I press anything", "why is nothing
        # happening". A question in form and a complaint in substance.
        r"\bwhy (?:is|are) there\b[^?]{0,60}\b(?:on (?:the|my) screen|here|up)\b"
        r"|\bwhy (?:can'?t|cannot|won'?t) i\b"
        r"|\bwhy (?:is|are)(?: there)? (?:nothing|no \w+|it) (?:happening|showing|working|there)\b"
        r"|\bwhy (?:did|does) (?:it|you) (?:do|show|open|pull up) that\b", re.I)),
    # `\bwhat is (?:it|this) doing\b` was the sixth alternative here and had to come out.
    #
    # It is the only one in a "why" shape that is not a why, and it collided head-on with
    # D-11. "What is it doing?" is step 7 of docs/phase5/PHYSICAL_SAMSUNG_ACCEPTANCE.md, a
    # question about what is on the glass. When recognised feedback took a turn before
    # anything else got it, the shape won and the owner asked what the screen was doing and
    # was told his complaint had been recorded.
    #
    # The tie-break is not in the words — both readings of that sentence are fair — it is
    # that ONE OF THEM CAN BE ANSWERED. A product able to say what is in front of him should
    # say it; filing the question as a defect gives him neither an answer nor a reason. And
    # nothing is lost from D-12: every complaint here is a judgement or an impossibility
    # ("why can't I press anything", "why is nothing happening", and the owner's own "why is
    # there bullshit on the screen right now?", which the first alternative still takes), and
    # a sentence carrying an actual judgement is caught by `broken`, `wrong` or
    # `did_the_wrong_thing` whatever question word it opens with.

)
# The shapes that are a statement about the product rather than an instruction to record one.
# Held by name so `recognise` can hold them to the extra tests below and the imperatives are
# untouched — a man who says "log that" has already told us what he wants.
_BY_SHAPE = frozenset({"broken", "wrong", "did_the_wrong_thing", "why_is_it"})
# Approval, agreement and small talk. A defect report has to get past all of this, because a
# tester whose compliments are filed as defects stops trusting the record. Every phrase here
# is from the 11 September session.
_NOT_A_COMPLAINT = re.compile(
    r"\b(?:i (?:actually )?like|i like (?:that|this|it)|that'?s (?:quite )?(?:good|nice|great|better|lovely|class)"
    r"|is that not (?:nice|good)|not bad|well done|perfect|brilliant|love (?:that|it|this)"
    r"|that'?s (?:it|right|correct)|exactly|yes(?:,| )?(?:that|thank)|thank you|thanks"
    r"|much better|spot on)\b", re.I)
# Sentences that are not about the product at all: a greeting, its own name, a wake check.
_NOT_ABOUT_THE_PRODUCT = re.compile(
    r"^(?:hi|hey|hello|yo|morning|good morning|crooks(?: os)?|jarvis|are you (?:working|there|awake|on)"
    r"|you there|can you hear me|test|testing)\b[\s,.!?]*$", re.I)
# Words that make a "broken" sentence about the SHOP rather than about the product. "The
# order is wrong" is a complaint about an order; "the back button is broken" is a defect.
_ABOUT_THE_SHOP = re.compile(
    r"\b(?:order|orders|customer|customers|refund|invoice|address|delivery|parcel|tracking|"
    r"stock|price|product|discount|payment)\b", re.I)


@dataclass(frozen=True)
class Recognition:
    """A sentence read as feedback about the product, and which rule read it that way."""

    kind: str                # log | note | record | save_as_test | broken
    text: str                # what he said, as he said it

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text}


def recognise(text: str) -> Recognition | None:
    """The sentence as local development feedback, or None.

    An instruction to log, note, record or save is feedback whatever else is in it: "log that
    the split is broken" and "log that the refund did not go through" are both things the
    owner wants written down.

    A sentence that only STATES a defect — D-12's shapes — has three more tests to pass, and
    all three exist to stop ordinary conversation being filed as a bug report:

    * it must not be about the SHOP. "The order is wrong" is a job, not a defect; "the back
      button is wrong" is a defect.
    * it must not be approval. "That's quite good actually" contains no complaint, and the
      acceptance script says so out loud in step 9.
    * it must not be a greeting, the product's own name, or a check that it is awake.

    An imperative skips all three, because a man who says "log that" has already said what he
    wants done with it.
    """
    said = " ".join(str(text or "").split())
    if not said:
        return None
    for kind, pattern in KINDS:
        if not pattern.search(said):
            continue
        if kind not in _BY_SHAPE:
            return Recognition(kind=kind, text=said[:MAX_FEEDBACK_CHARS])
        if _ABOUT_THE_SHOP.search(said) or _NOT_A_COMPLAINT.search(said):
            return None
        if _NOT_ABOUT_THE_PRODUCT.match(said):
            return None
        return Recognition(kind=kind, text=said[:MAX_FEEDBACK_CHARS])
    return None


# ------------------------------------------------------------------- what was on screen


def _screen(branch: Any) -> list[str]:
    """The card types this half last put on the glass. Types, never their contents."""
    ui = getattr(branch, "last_ui", None) or []
    return [str(u.get("type") or "") for u in ui if isinstance(u, dict) and u.get("type")][:6]


def _entities(branch: Any) -> list[dict[str, str]]:
    """What the half is on, and what it has been on. Kind and ref — never the label, which is
    a customer's name."""
    out: list[dict[str, str]] = []
    entity = getattr(branch, "entity", None) or {}
    if entity.get("kind") and entity.get("ref"):
        out.append({"kind": str(entity["kind"]), "ref": str(entity["ref"])})
    for recent in (getattr(branch, "recent_entities", None) or [])[:4]:
        if not isinstance(recent, dict) or not recent.get("ref"):
            continue
        row = {"kind": str(recent.get("kind") or ""), "ref": str(recent["ref"])}
        if row not in out:
            out.append(row)
    return out[:5]


def context(branch: Any, *, now: float | None = None) -> dict[str, Any]:
    """Everything the event carries about WHERE the owner was when he said it: the half, the
    screen, the records in hand, and the ids of what happened around him."""
    return {
        "branch_id": str(getattr(branch, "branch_id", "") or ""),
        "branch_status": str(getattr(branch, "status", "") or ""),
        "screen": _screen(branch),
        "entities": _entities(branch),
        "tab": str(getattr(branch, "tab", "") or ""),
        "nearby": timeline.current().recent(within_s=NEARBY_S, limit=MAX_NEARBY, now=now),
    }


# -------------------------------------------------------------------------- recording


def record(recognition: Recognition, *, branch: Any = None, session_id: str = "",
           turn_id: str = "", now: float | None = None) -> dict[str, Any] | None:
    """Append the feedback to the timeline. Returns the event, or None when nothing is
    recording.

    Nothing here can fail a turn: `timeline.emit` is a queue put that never raises, and with
    no test session active this is one cached stat and a return.
    """
    if timeline.current().own is None:
        return None
    where = context(branch, now=now)
    return timeline.emit(
        "owner_feedback",
        session_id=session_id or None,
        turn_id=turn_id or None,
        branch_id=where["branch_id"] or None,
        # `shape`, not `kind`: every timeline event's `kind` is the event's own name, and this
        # event's name is `owner_feedback`. What KIND of feedback it is goes beside it.
        shape=recognition.kind,
        text=recognition.text,
        screen=where["screen"] or None,
        entities=where["entities"] or None,
        tab=where["tab"] or None,
        branch_status=where["branch_status"] or None,
        nearby=where["nearby"] or None,
    )


def active() -> bool:
    """Whether a test session is running, so feedback has somewhere to go."""
    return timeline.current().own is not None
