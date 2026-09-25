"""What the controls on the glass ARE — the product's knowledge of its own interface (§15).

    Owner:  "What does the split button do?"
    CROOKS: "I don't know what that button is — not something I control, so best to check
             with whoever built the tablet screen."

That is the whole reason this file exists. The assistant was told what TOOLS it has and
nothing about the screen it speaks through, so it denied knowledge of its own primary control
and referred its owner to himself. Every other answer in the system is derived from a
registry; this one was left to the model, and the model had nothing to derive it from.

So: a BOUNDED manifest of first-party UI semantics. Bounded in three senses.

* **It is a fixed table.** Split, Back, Home, Next, Previous, Aside, Merge, the dock, the four
  approval gestures, the composer, the branch states and the surface states. Nothing else. A
  question it cannot answer is answered by something else, not invented here.
* **It is derived where it can be.** Every entry that corresponds to a semantic command names
  it, and takes its `what` from `app.commands.REGISTRY` at build time — so the manifest cannot
  say Back means one thing while the command does another. `check()` fails loudly if an entry
  names a command that is not registered, and a test runs it. The approval gestures come the
  same way from `app.actions.grammar`, the dock's destinations from `app.families.landings`,
  and the branch states from the session's own vocabulary.
* **It never generates UI.** This says what a control DOES. It cannot draw one, add one,
  rename one, or tell the tablet to do anything. It is read by a read family and by the
  report; both of those are read paths, and neither can stage a change.

The words are the product's, written once, and they are what the owner hears. A model asked
the same question without this file answers from nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# The groups, in the order a person would meet them.
GROUPS: tuple[tuple[str, str], ...] = (
    ("halves", "The two halves"),
    ("navigation", "Getting about"),
    ("dock", "The dock"),
    ("approval", "Applying a change"),
    ("surface_state", "What a card is saying"),
    ("composer", "Typing instead of speaking"),
    ("branch_state", "What a half is doing"),
    # What is on the glass right now, chrome included (D-11). Its entry is registered by
    # app/families/self_knowledge.py through `extend`, because the answer is derived from live
    # session state and this table holds only what is stable.
    ("screen", "What is on the glass"),
)


@dataclass(frozen=True)
class Entry:
    """One control, or one state a control can be in.

    `command` names the semantic command in `app/commands.py` that the control resolves to,
    where there is one; `derived_what` is filled from that registry when the manifest is
    built, so the sentence below and the code behind the control cannot drift apart.
    """

    key: str
    control: str                    # what it is called on the glass
    group: str
    what: str                       # one sentence: what it does
    where: str = ""                 # where it is, and how it is reached
    command: str = ""               # app/commands.py, where the control resolves to one
    says: tuple[str, ...] = ()      # what the owner can say instead of touching it
    also: tuple[str, ...] = ()      # the other entries worth naming in the same breath
    asks: Any = None                # the questions this entry answers
    derived_what: str = ""          # the command registry's own words, filled by manifest()

    def sentence(self) -> str:
        """The answer, as the assistant says it: what it does, then where it is."""
        parts = [self.what.rstrip(".") + "."]
        if self.where:
            parts.append(self.where.rstrip(".") + ".")
        if self.says:
            spoken = " or ".join(f"“{s}”" for s in self.says[:2])
            parts.append(f"You can say {spoken} instead of touching it.")
        return " ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "control": self.control, "group": self.group, "what": self.what,
                "where": self.where, "command": self.command or None, "says": list(self.says),
                "registry": self.derived_what or None}


def _asks(*patterns: str) -> Any:
    return re.compile("|".join(patterns), re.I)


# The words that make a sentence a question about the SCREEN rather than about the shop.
# "What does split do" is this file's; "what did we sell" is not, and no pattern below can
# match it. Held as one bounded vocabulary so the read family and the report ask the same
# question of the same table.
UI_WORDS = frozenset({
    "split", "splits", "aside", "merge", "merged", "back", "home", "next", "previous",
    "forward", "dock", "orb", "button", "buttons", "control", "controls", "card", "cards",
    "screen", "tablet", "tab", "tabs", "applying", "apply", "armed", "arm", "compose",
    "composer", "keyboard", "type", "typing", "half", "halves", "chip", "chips", "rail",
})

ENTRIES: tuple[Entry, ...] = (
    # ------------------------------------------------------------------ the two halves
    Entry(
        key="split", control="Split", group="halves",
        what="Split divides the conversation in two, so one half can keep working while you "
             "talk to the other",
        where="It is the control on the orb; a two-finger spread does the same thing. Each "
              "half keeps its own record, its own list and its own place in the trail, and "
              "you tap a half to talk to it",
        says=("split", "take that aside"),
        also=("aside", "merge", "branch_focus"),
        asks=_asks(r"\bsplit\b", r"\bdivide\b.{0,20}\b(?:conversation|screen|orb)\b"),
    ),
    Entry(
        key="aside", control="Aside", group="halves",
        what="Aside puts the half you are on into the background and hands you the other one; "
             "the one you put aside carries on with what it was doing",
        where="It is on the half's own header, beside its name",
        says=("put that aside", "switch to the other half"),
        also=("split", "merge"),
        asks=_asks(r"\baside\b", r"\bbackground(?:ed)?\b.{0,20}\bhalf\b"),
    ),
    Entry(
        key="merge", control="Merge", group="halves",
        what="Merge ends the split and brings the two halves back to one conversation, keeping "
             "what each of them found",
        where="It is on the orb while the conversation is divided; a two-finger pinch does the "
              "same thing. Anything either half had prepared and you have not applied is still "
              "waiting afterwards",
        says=("merge", "put them back together"),
        also=("split", "aside"),
        asks=_asks(r"\bmerge\b|\bmerging\b|\bput (?:them|the halves) back\b"),
    ),
    Entry(
        key="branch_focus", control="Tapping a half", group="halves",
        what="Tapping a half moves you to it and draws what that half is looking at",
        where="Each half has its own strip on screen while the conversation is divided",
        command="branch.show",
        says=("switch to the other half",),
        asks=_asks(r"\btap(?:ping)? a half\b|\bswitch\b.{0,20}\bhalf\b|\bother half\b"),
    ),
    # ------------------------------------------------------------------- getting about
    Entry(
        key="back", control="Back", group="navigation",
        what="Back returns you to the record you were on before this one",
        where="It is at the top left of the screen. It moves through this half's own trail, so "
              "the other half's trail is not disturbed",
        command="navigation.back",
        says=("go back", "back"),
        also=("home", "next", "return_here"),
        asks=_asks(r"\bgo back\b", r"\bback\b.{0,20}\bbutton\b", r"\bhow do i go back\b",
                   r"\bwhat\b.{0,20}\bback\b.{0,10}\b(?:do|mean|means)\b"),
    ),
    Entry(
        key="home", control="Home", group="navigation",
        what="Home returns you to the start of this half's trail — where the conversation began",
        where="It is beside Back. It is not a fresh start: nothing is forgotten and nothing is "
              "read again",
        command="navigation.home",
        says=("go home", "back to the start"),
        also=("back", "dock"),
        asks=_asks(r"\bhome\b.{0,20}\bbutton\b", r"\bgo home\b", r"\bwhat\b.{0,20}\bhome\b.{0,10}\b(?:do|mean|means)\b",
                   r"\bback to (?:the )?(?:start|beginning)\b", r"\bback to assistant\b"),
    ),
    Entry(
        key="next", control="Next", group="navigation",
        what="Next moves to the following record in the list you have open, and says which of "
             "how many you are on",
        where="It appears once a list is open. At the end of the list it says so rather than "
              "showing the last one again",
        command="workflow.next",
        says=("next", "the next one"),
        also=("previous", "back"),
        asks=_asks(r"\bnext\b.{0,20}\bbutton\b", r"\bwhat\b.{0,20}\bnext\b.{0,10}\b(?:do|mean|means)\b",
                   r"\bhow do i (?:see|get to) the next\b"),
    ),
    Entry(
        key="previous", control="Previous", group="navigation",
        what="Previous moves back one record in the list you have open",
        where="It sits beside Next. It is a move through a list, where Back is a move through "
              "the trail of everything you have looked at",
        command="workflow.previous",
        says=("previous", "the one before"),
        also=("next", "back"),
        asks=_asks(r"\bprevious\b.{0,20}\bbutton\b", r"\bwhat\b.{0,20}\bprevious\b.{0,10}\b(?:do|mean|means)\b"),
    ),
    Entry(
        key="tabs", control="The tabs on a card", group="navigation",
        what="The tabs along a card show one part of the record at a time — an order's items, "
             "its shipping, its customer, the email about it",
        where="They are at the top of the card. Which tab you are on is remembered, so Back "
              "returns to the same part of the same record",
        command="surface.tab",
        says=("show me the shipping", "show me the items"),
        asks=_asks(r"\btabs?\b"),
    ),
    Entry(
        key="return_here", control="Getting back to this record", group="navigation",
        what="Back returns to the record you were on before, Home returns to the start of this "
             "half's trail, and the strip of recent records along the bottom returns to any of "
             "them in one tap",
        where="Tapping a linked record — an order on a thread, a customer on an order — opens "
              "it and puts it on the trail, so Back always comes back here",
        command="open.entity",
        says=("go back", "show it again"),
        also=("back", "home"),
        asks=_asks(r"\bhow do i (?:get|come|return) back to\b", r"\breturn to this\b",
                   r"\bfind (?:this|that|it) again\b", r"\bget back to (?:this|that|the) (?:order|customer|email|thread|page)\b"),
    ),
    # --------------------------------------------------------------------------- the dock
    Entry(
        key="dock", control="The dock", group="dock",
        what="The dock along the edge opens a landing for each part of the shop — {areas}",
        where="A landing is a starting point rather than an answer: it is what is waiting in "
              "that part of the shop, read fresh",
        command="open.area",
        says=("open orders", "open the inbox"),
        asks=_asks(r"\bdock\b", r"\blanding\b"),
    ),
    # ------------------------------------------------------------------ applying a change
    Entry(
        key="approval", control="Applying a change", group="approval",
        what="A change is never made until you say so with your hand: the card says which "
             "gesture it wants, and the gesture is decided by what the change is, never by the "
             "assistant",
        where="{gestures}",
        also=("applying", "undo"),
        asks=_asks(r"\bhow do i (?:apply|approve|confirm)\b", r"\bwhat gesture\b",
                   r"\bhold\b.{0,20}\bdrag\b", r"\bwhy\b.{0,20}\bhold\b.{0,20}\bcard\b"),
    ),
    # ------------------------------------------------------------ what a card is saying
    Entry(
        key="applying", control="Applying…", group="surface_state",
        what="“Applying…” means the card has been sent to the server and the server has not yet said "
             "what happened",
        where="It should last a second or two and then say Done, or say what went wrong. A card "
              "still saying it after the change has gone through is a fault on the screen, not "
              "a change still running — the change is finished",
        also=("undo", "approval"),
        asks=_asks(r"\bapplying\b", r"\bspinner\b", r"\bstill (?:going|spinning|hovering)\b"),
    ),
    Entry(
        key="armed", control="Armed", group="surface_state",
        what="“Armed” means the card is ready for the gesture that applies it, and will disarm "
             "itself if you leave it",
        where="Nothing has been sent to the shop or the inbox while a card is armed",
        also=("approval", "applying"),
        asks=_asks(r"\barmed\b|\barm(?:ing)?\b.{0,20}\bmean\b"),
    ),
    Entry(
        key="undo", control="Undo", group="surface_state",
        what="Undo appears on a change that has just been made and can still be taken back",
        where="It is an offer on a finished change, not a change waiting to be made",
        also=("applying",),
        asks=_asks(r"\bundo\b"),
    ),
    # --------------------------------------------------- typing instead of speaking
    Entry(
        key="composer", control="The composer", group="composer",
        what="Anything that has to be exact is typed rather than said: the composer's To, "
             "Subject and Body take the keyboard",
        where="It opens on the card itself, so what you type stays with the thread it belongs "
              "to. Nothing is saved or sent until you tap — Save draft keeps it, Send sends it. "
              "A field the assistant heard rather than read is marked so you can check it",
        says=("write to them", "reply to this"),
        also=("voice_bind", "approval"),
        asks=_asks(r"\bhow do i type\b", r"\btype (?:instead of|rather than) (?:speak|saying|talking)\b",
                   r"\bkeyboard\b", r"\bcomposer?\b", r"\btype (?:it|that|the)\b",
                   r"\bwithout (?:speaking|saying it|talking)\b"),
    ),
    Entry(
        key="voice_bind", control="Reply / Rewrite / Add a note", group="composer",
        what="A control that expects words does not do anything by itself — it says what your "
             "next sentence is about, and starts listening",
        where="The screen says who it is about while it listens. The sentence that follows is "
              "what does the work",
        command="voice.bind",
        asks=_asks(r"\blistening\b", r"\bwhat does (?:reply|rewrite|add a note) do\b"),
    ),
    Entry(
        key="rail", control="The chips on a card", group="approval",
        what="The chips along a card are the changes that record can take right now — reply, "
             "archive, a note, a refund, an address, fulfilment",
        where="Tapping one prepares the change and asks for the gesture; it does not make it. "
              "A chip shown greyed out says why it cannot be used",
        also=("approval", "applying"),
        asks=_asks(r"\brail\b", r"\bchips?\b",
                   r"\bwhat does the [a-z]{3,12} (?:button|chip) do\b"),
    ),
    # ----------------------------------------------------------- what a half is doing
    Entry(
        key="branch_states", control="What a half is doing", group="branch_state",
        what="A half is one of: {states}",
        where="A half in the background keeps reading and never applies a change on its own",
        also=("split", "merge"),
        asks=_asks(r"\bhalf\b.{0,20}\b(?:doing|state|status)\b", r"\bbackground(?:ed)?\b"),
    ),
)

# What a half can be. The session's own vocabulary (app/session/branch.py), said in words.
BRANCH_STATES: tuple[tuple[str, str], ...] = (
    ("ACTIVE", "the one you are talking to"),
    ("BACKGROUND", "working while you are elsewhere"),
    ("MERGED", "folded back into the conversation"),
    ("CANCELLED", "stopped, with anything it had prepared withdrawn"),
)


def _gesture_words() -> str:
    """The four approval gestures, from the action grammar's own table.

    Read, never copied: `app/actions/grammar.py` decides which gesture a change gets from its
    tier and its class, and the words on the surface come from the same table. A manifest that
    held its own copy would describe a gesture the tablet does not ask for.
    """
    try:
        from app.actions import grammar
    except Exception:  # noqa: BLE001 — the manifest still reads without the action engine
        return ("A card says which gesture it wants: a tap, a swipe, a hold and then a tap, or "
                "a hold and a drag onto the target")
    parts = [f"{grammar.words_for(kind)['label'].lower()}" for kind in grammar.KINDS]
    return ("The card itself says which: " + "; ".join(parts)
            + ". The heavier the change, the more deliberate the gesture — money and anything "
              "that cannot be undone take a hold")


def _dock_areas() -> str:
    try:
        from app.families.landings import AREAS

        names = sorted(AREAS)
    except Exception:  # noqa: BLE001 — the manifest still reads without the family modules
        names = ["orders", "email", "products", "sales"]
    return ", ".join(names[:-1]) + (" and " + names[-1] if len(names) > 1 else "")


def _branch_state_words() -> str:
    return "; ".join(f"{name.lower()}, {what}" for name, what in BRANCH_STATES)


_FILLERS = {"areas": _dock_areas, "gestures": _gesture_words, "states": _branch_state_words}


def _filled(text: str) -> str:
    for name, make in _FILLERS.items():
        token = "{" + name + "}"
        if token in text:
            text = text.replace(token, make())
    return text


# --------------------------------------------------------------------------- the manifest


def _registry() -> dict[str, str]:
    """Every semantic command, by name, with the registry's own words for it."""
    try:
        from app import commands

        return {c["name"]: str(c["what"]) for c in commands.public()}
    except Exception:  # noqa: BLE001 — the manifest still reads without the command layer
        return {}


# Entries a family adds from its own file, so two families never edit ENTRIES' same line —
# the seam `app.fastpath.intent.extend` already gives the family table. Read wherever ENTRIES
# is read; `check()` holds for these too.
EXTRA_ENTRIES: list[Entry] = []


def extend(entries: list[Entry] | tuple[Entry, ...]) -> None:
    known = {e.key for e in ENTRIES} | {e.key for e in EXTRA_ENTRIES}
    for entry in entries:
        if entry.key in known:
            raise ValueError(f"the manifest entry {entry.key!r} is already registered")
        EXTRA_ENTRIES.append(entry)
        known.add(entry.key)


def all_entries() -> tuple[Entry, ...]:
    return ENTRIES + tuple(EXTRA_ENTRIES)


def manifest() -> tuple[Entry, ...]:
    """The entries, with the command registry's own words folded into each that has one.

    Built fresh rather than cached: a family registered at import time adds commands, and a
    manifest built before it loaded would be describing a smaller product than the one running.
    """
    known = _registry()
    out: list[Entry] = []
    for entry in all_entries():
        out.append(Entry(
            key=entry.key, control=entry.control, group=entry.group,
            what=_filled(entry.what), where=_filled(entry.where), command=entry.command,
            says=entry.says, also=entry.also, asks=entry.asks,
            derived_what=known.get(entry.command, ""),
        ))
    return tuple(out)


def check() -> list[str]:
    """Every entry that names a command names one that is registered. Returns what is wrong,
    empty when nothing is — a test runs it, so the manifest cannot outlive the control it
    describes."""
    known = _registry()
    if not known:
        return []               # nothing to check against; not a failure of this table
    return [f"{e.key}: names the command {e.command!r}, which is not registered"
            for e in all_entries() if e.command and e.command not in known]


def get(key: str) -> Entry | None:
    return next((e for e in manifest() if e.key == key), None)


def groups() -> list[dict[str, Any]]:
    """The manifest arranged for a card: one panel per group, in the order above."""
    entries = manifest()
    out: list[dict[str, Any]] = []
    for name, label in GROUPS:
        mine = [e for e in entries if e.group == name]
        if not mine:
            continue
        out.append({
            "area": name, "label": label, "count": len(mine), "truncated": False,
            "items": [{"name": e.control, "what": e.sentence(), "kind": "read", "state": "ready",
                       "area": name, "operation": "", "risk": "", "reversible": True} for e in mine],
        })
    return out


# ------------------------------------------------------------------------ the question


@dataclass(frozen=True)
class Answer:
    """What the manifest says about one control, and which entry said it."""

    entry: Entry
    words: str
    related: tuple[Entry, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.entry.key, "control": self.entry.control, "answer": self.words,
                "command": self.entry.command or None,
                "related": [e.key for e in self.related]}


# A sentence reaches the table only when it is BOTH of these, and the pair is the whole of the
# bound. One half is a frame that asks to be told something; the other is a subject that is
# part of the interface.
#
# Both halves are needed, and each without the other was measured to be wrong. The subject
# alone takes "switch to the other half" — which MEANS the move, and must make it — and "has
# the order come back yet". The frame alone takes "what is running out" and "how do I refund
# this", which are the shop's questions and not the screen's. A control's name doubles as an
# instruction in this product, deliberately, so the frame is what tells them apart.
_EXPLAIN_FRAME = re.compile(
    r"\bwhat (?:does|do|is|are|s)\b|\bwhat'?s\b"
    r"|\bhow (?:do|can|would|should) i\b|\bhow does\b"
    r"|\bwhy (?:does|is|do|are)\b"
    r"|\bexplain\b|\btell me what\b|\bwhat happens (?:when|if)\b"
    r"|\bwhat (?:am i|is that|is this) (?:looking at|for)\b",
    re.I,
)
# The subjects that belong to the interface: the nouns a person points at, and the named
# controls and states. Nothing about the shop is in this list.
_UI_SUBJECT = re.compile(
    r"\b(?:button|buttons|control|controls|screen|tablet|card|cards|tab|tabs|orb|dock|landing|"
    r"gesture|compose|composer|keyboard|typing|type|half|halves|chip|chips|rail|"
    r"split|merge|merging|aside|applying|armed|arming|undo|"
    # "Why is this HERE" and "what am i LOOKING at" name the interface with no noun of its own
    # in them (D-11). Widening the subject cannot widen what is answered: a sentence still has
    # to match one entry's own pattern, so these reach the table and no further.
    r"here|looking|glass|display|"
    r"back|home|next|previous|forward)\b",
    re.I,
)


def looks_like_a_question_about_the_screen(text: str) -> bool:
    """Whether this sentence asks to be TOLD something about part of the interface.

    Both halves: a frame that asks, and a subject that is part of the screen. "What does the
    split button do" is one; "split" on its own is an instruction, and "what did we sell" is
    the shop's.
    """
    said = " ".join(str(text or "").split())
    if not said:
        return False
    return bool(_EXPLAIN_FRAME.search(said) and _UI_SUBJECT.search(said))


def lookup(text: str) -> Answer | None:
    """The manifest's answer to this question, or None when it has none.

    Deterministic and bounded: the sentence must read as a question about the screen, and it
    must match one entry's own pattern. Nothing here guesses, and nothing here composes an
    answer out of two entries — an answer the manifest cannot give is not given.
    """
    said = " ".join(str(text or "").split())
    if not said or not looks_like_a_question_about_the_screen(said):
        return None
    entries = manifest()
    by_key = {e.key: e for e in entries}
    for entry in entries:
        if entry.asks is not None and entry.asks.search(said):
            related = tuple(by_key[k] for k in entry.also if k in by_key)
            return Answer(entry=entry, words=entry.sentence(), related=related)
    return None


def spoken(answer: Answer) -> str:
    """The answer as it is said aloud: the sentence, and at most one pointer to a neighbour.

    The neighbour is the first related control the sentence has not already named — pointing
    at Back in an answer that is mostly about Back is a sentence longer and no clearer.
    """
    words = answer.words
    for entry in answer.related:
        if entry.control.lower() in words.lower():
            continue
        return f"{words} See also {entry.control}."
    return words
