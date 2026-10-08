"""What a request was FOR, and whether the turn did it.

The September session scored a turn "successful" that asked to add two items to David
Replica's order, called no tool, staged nothing, and answered as though it had. Nothing in
the report caught it, because the report asked "did anything fail" rather than "was the
request contract met".

This module supplies the contract:

    READ_INTENT             look something up
    WRITE_INTENT            change something
    UI_INTENT               change what is on the screen
    NAVIGATION_INTENT       move around what is already there
    WORKFLOW_CONTINUATION   carry on with the thing in hand
    META_CAPABILITY_INTENT  a question about the assistant itself

and the failure classes that only make sense once a request has one. Words only: the question
as transcribed and the answer as spoken, never any model reasoning.
"""

from __future__ import annotations

import re
from typing import Any

READ_INTENT = "READ_INTENT"
WRITE_INTENT = "WRITE_INTENT"
UI_INTENT = "UI_INTENT"
NAVIGATION_INTENT = "NAVIGATION_INTENT"
WORKFLOW_CONTINUATION = "WORKFLOW_CONTINUATION"
META_CAPABILITY_INTENT = "META_CAPABILITY_INTENT"

CONTRACTS = (READ_INTENT, WRITE_INTENT, UI_INTENT, NAVIGATION_INTENT, WORKFLOW_CONTINUATION, META_CAPABILITY_INTENT)

# Asking for something on the screen to change: a button, a column, a card, a list.
# A gift card is not a card on the screen (round 11): "issue her a £20 gift card" is a grant.
_UI = re.compile(
    r"\b(?:button|buttons|tab|tabs|column|columns|(?<!gift )cards?|screen|list view|checkbox|"
    r"tick box|next to (?:them|it|each)|on the card|show me a|put a|give me a way to)\b", re.I,
)
_NAV = re.compile(r"^\s*(?:go |take me )?(?:back|home|up|forward)\b|^\s*(?:next|previous|the one before)\b", re.I)
_WORKFLOW = re.compile(r"^\s*(?:next|carry on|keep going|go on|and the next|the one after)\b", re.I)
_META = re.compile(r"\b(?:what (?:can|else can) you|your capabilities|what more can you|can you now|are you able to)\b", re.I)

# An answer that reports the change as made. Deliberately narrow: "I've added", "done",
# "that's updated". A card WAITING to be tapped is not one of these.
_SUCCESS = re.compile(
    r"\b(?:i(?:'ve| have) (?:added|updated|changed|set|sent|cancelled|refunded|removed|archived|tagged|saved)"
    r"|(?:that|it|the order|the note|the address|the email)(?:'s| is| has been) (?:done|added|updated|changed|set|sent|saved|cancelled|refunded|archived)"
    r"|^done\b|\ball set\b|\bsorted\b|\bthat's done\b)", re.I,
)
# An answer that says a card is waiting. This is the honest shape of a staged change.
_WAITING = re.compile(r"\b(?:tap|swipe|hold|drag|press)\b.{0,40}\b(?:card|to apply|to confirm|it)\b|\bwaiting for you\b|\bon the card\b", re.I)
# An answer that says plainly it did not do it.
_DECLINED = re.compile(r"\b(?:can'?t|cannot|couldn'?t|could not|unable to|not able to|there(?:'s| is) no way|i don'?t have)\b", re.I)

# Whether a request asks for a change, read after the turn for the report. It decides nothing
# about the turn itself — every sentence is a model turn — and it lives here, beside the
# contract it grades, since the word-matching lane it was written for was removed (28
# September 2026). "Any email from him about 1938" is a noun; "email him about 1938" is an
# instruction.
#
# A verb that changes something. Split in two, because English does not agree with itself:
#
#   STRONG   only ever an instruction. "Cancel", "refund", "archive".
#   SOFT     an instruction at the head of one, a noun or a description anywhere else.
#            "Email" in "email them" is a change; in "any email from her?" it is the inbox.
#            "Replying" in "who needs replying to" describes a state, not an order given.
#
# A SOFT verb counts as a change only when the request is NOT opened as a question.
MUTATION_STRONG = frozenset({
    "cancel", "cancelled", "refund", "refunded", "delete", "archive", "unarchive", "fulfil",
    "fulfill", "dispatch", "restock", "untag", "revoke", "amend", "replace",
    "resend", "forward", "edit", "editing",
})
MUTATION_SOFT = frozenset({
    # "fulfilled" as a past participle describes a state: "has it been fulfilled" is a
    # question, "mark it fulfilled" an instruction. "fulfil" and "fulfill" are STRONG.
    "fulfilled",
    "add", "adding", "remove", "removing", "send", "sending", "sent", "reply", "replying",
    "draft", "drafting", "write", "writing", "email", "emailing", "note", "tag", "tagging",
    "mark", "marking", "set", "setting", "put", "make", "create", "creating", "change",
    "changing", "update", "updating", "ship", "shipping", "adjust", "adjusting", "apply",
    "move", "moving",
})
MUTATION = MUTATION_STRONG | MUTATION_SOFT
# A request that opens with one of these is asking, whatever verbs come later in it.
OPENERS = frozenset({
    "what", "whats", "which", "who", "whose", "how", "when", "where", "why", "is", "are",
    "was", "were", "do", "does", "did", "has", "have", "had", "any", "anyone", "anybody",
    "show", "list", "tell", "give", "find", "check", "read", "look", "whos",
})
# A SOFT verb straight after a determiner is a noun, wherever the sentence starts. "Customers
# who need a reply?" asks about a state of the inbox; "reply to Mia" has no determiner in
# front of it, and "send a reply to order 2044" still carries "send".
_DETERMINER = frozenset({"a", "an", "the", "any", "no", "our", "my", "your", "their"})
_NOUN_READING = frozenset({"reply"})

_ASKING_ABOUT = re.compile(r"^\s*(?:can|could|will|would|is it possible|are you able|do you|how (?:do|would) (?:i|you|we))\b", re.I)
_WORD = re.compile(r"[a-z0-9'#]+")


def _as_a_noun(words: tuple[str, ...], index: int) -> bool:
    return words[index] in _NOUN_READING and index > 0 and words[index - 1] in _DETERMINER


# Store credit is GIVEN, and "give" is not a mutation verb: "give me the sales" is a read, so
# "Give Alice £15 of store credit" found no change word and was graded a read, and the store
# credit it asked for — a live write — was never set against the family that serves it (round 11,
# R9-F-observability1-F-03, O2-F-02). A grant is recognised by its shape instead: the sentence
# opens (after an optional "please") with a verb that grants — give, issue, grant, award, credit,
# top up, load — and what it grants is credit or a gift card. "Give me …" / "give us …" fetch, and
# the credit's balance, history or what is left of it is a question about it, not a grant.
_GRANTS = frozenset({"give", "issue", "grant", "award", "credit", "load", "top"})
_TO_THE_ASKER = frozenset({"me", "us"})
_CREDIT_STATE = frozenset({"balance", "balances", "history", "left", "remaining", "total", "limit", "status",
                           "used", "value", "amount", "card", "cards", "note", "notes", "policy"})
_CARD_STATE = frozenset({"balance", "balances", "history", "left", "remaining", "value", "code", "codes", "number",
                         "status", "used"})


def grants_credit(words: tuple[str, ...]) -> bool:
    """Whether this request grants store credit (or a gift card) to someone."""
    at = 1 if words[:1] == ("please",) else 0
    verb = words[at] if len(words) > at else ""
    if verb not in _GRANTS:
        return False
    rest = words[at + 1:]
    if verb == "top":
        if rest[:1] != ("up",):
            return False
        rest = rest[1:]
    if verb == "give" and rest[:1] and rest[0] in _TO_THE_ASKER:
        return False
    if verb == "credit":
        # The verb itself grants: "credit Alice's account with £15", "credit her £10". "Credit card
        # payments today?" and "credit note for 1938" are nouns.
        return bool(rest) and rest[0] not in _CREDIT_STATE
    for i, word in enumerate(rest):
        after = rest[i + 1] if i + 1 < len(rest) else ""
        if word == "credit" and after not in _CREDIT_STATE:
            return True
        if word == "card" and i and rest[i - 1] == "gift" and after not in _CARD_STATE:
            return True
    return False


def mutating(words: tuple[str, ...]) -> bool:
    """Whether this request asks for a change."""
    have = set(words)
    if have & MUTATION_STRONG:
        return True
    if grants_credit(words):
        return True
    if not any(w in MUTATION_SOFT and not _as_a_noun(words, i) for i, w in enumerate(words)):
        return False
    return not (words and words[0] in OPENERS)


def _is_change(text: str) -> bool:
    return mutating(tuple(_WORD.findall((text or "").lower())))


def contract_of(question: str, *, ui_asked: bool = False) -> str:
    """What this request was for. One contract per turn: the most specific that fits."""
    text = (question or "").strip()
    if not text:
        return READ_INTENT
    if _META.search(text):
        return META_CAPABILITY_INTENT
    if _WORKFLOW.match(text):
        return WORKFLOW_CONTINUATION
    if _NAV.match(text):
        return NAVIGATION_INTENT
    if ui_asked or _UI.search(text):
        return UI_INTENT
    if _is_change(text) and not _ASKING_ABOUT.match(text):
        return WRITE_INTENT
    return READ_INTENT


def reports_success(answer: str) -> bool:
    """Whether the answer claims the change was made. A card offered for a gesture does not."""
    text = answer or ""
    return bool(_SUCCESS.search(text)) and not _WAITING.search(text)


def declines(answer: str) -> bool:
    return bool(_DECLINED.search(answer or ""))


def waiting_for_a_gesture(answer: str) -> bool:
    return bool(_WAITING.search(answer or ""))


# What CROOKS OS knowingly cannot do, so that a request for one is a limitation stated
# rather than a silence or an invention. Each entry names the thing, the words that ask for
# it, and the nearest thing that IS possible. Generated answers are checked against this in
# app/observability/report.py; the model is told the honest sentence at turn time
# (app/routes/turn.py).
LIMITATIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "order_edit",
        "what": "change what is ON an order — add, remove or swap a line item",
        "asks": re.compile(r"\b(?:add|put|swap|change|replace|remove|take off)\b.{0,60}\b(?:to|from|on|off)\b.{0,30}\b(?:order|his order|her order|their order|the order)\b|\border edit\b", re.I),
        "instead": (
            "Shopify's order editing changes what the customer owes, so it is not one of the "
            "reviewed changes the Mac can make. What I can do: put a note on the order saying "
            "exactly what to add, tag it, or cancel and refund it."
        ),
    },
    {
        "name": "gmail_thread_merge",
        "what": "merge two Gmail threads into one",
        "asks": re.compile(r"\bmerge\b.{0,30}\b(?:threads?|emails?|conversations?)\b", re.I),
        "instead": "I can reply in either thread, and quote the other, but Gmail has no way to join two threads.",
    },
    {
        "name": "price_change",
        "what": "change a price on a product or an order",
        "asks": re.compile(r"\b(?:change|set|update|drop|raise|discount)\b.{0,30}\bprice\b", re.I),
        "instead": "I can tell you what a thing costs and what it sold for; changing a price is done in Shopify.",
    },
)


def limitation_for(question: str) -> dict[str, Any] | None:
    """The known limitation this request runs into, if it runs into one."""
    text = (question or "").strip()
    if not text:
        return None
    for entry in LIMITATIONS:
        if entry["asks"].search(text):
            return entry
    return None


def limitation_line(question: str) -> str:
    """The one line the model is given so a limitation is stated rather than papered over."""
    found = limitation_for(question)
    if found is None:
        return ""
    return (
        f"[The Mac cannot {found['what']}. Say so plainly and say what it can do instead: "
        f"{found['instead']} Never answer as though the change has been made.]"
    )
