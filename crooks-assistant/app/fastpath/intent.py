"""What was asked, as structure.

Not a phrase table. The resolver extracts SIGNALS from the request and from the branch state
— a mutation verb, an order number, a direction, a period, a metric, a meta-question, a name
the branch has already resolved, a working set under a cursor — and each intent family
declares which signals it requires, which it forbids, and what it needs to resolve before it
can act. A family wins only when it beats the runner-up by a margin and clears a floor.

The point of the structure is that "go on then" and "next one" and "and the one after that"
all reduce to the same signal (DIRECTION_NEXT) without any of them being written down as a
sentence, and that "cancel the next one" reduces to a mutation and never reaches the lane at
all.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from app.fastpath import correction

# ------------------------------------------------------------------ signals

# A verb that changes something. Any of these and the request leaves the fast lane: the fast
# lane cannot write, and a request it cannot serve must not be scored as if it could.
# A verb that changes something. Split in two, because English does not agree with itself:
#
#   STRONG   only ever an instruction. "Cancel", "refund", "archive".
#   SOFT     an instruction at the head of one, a noun or a description anywhere else.
#            "Email" in "email them" is a change; in "any email from her?" it is the inbox.
#            "Replying" in "who needs replying to" describes a state, not an order given.
#
# A SOFT verb counts as a mutation only when the request is NOT opened as a question. The
# cost of being wrong in the cautious direction is one model call; the cost of being wrong in
# the other direction is the fast lane trying to serve a change, which it cannot do.
MUTATION_STRONG = frozenset({
    "cancel", "cancelled", "refund", "refunded", "delete", "archive", "unarchive", "fulfil",
    "fulfill", "dispatch", "restock", "untag", "revoke", "amend", "replace",
    "resend", "forward", "edit", "editing",
})
MUTATION_SOFT = frozenset({
    # "fulfilled" was STRONG, and so "find an order that hasn't been fulfilled" — asked in
    # those words on the tablet — was read as an instruction to ship something and left the
    # fast lane before any family could see it. As a past participle it describes a state;
    # "fulfil" and "fulfill", the imperatives, are still STRONG. SOFT means it counts as a
    # change only when the sentence is not opened as a question, which is exactly the
    # distinction between "mark it fulfilled" and "has it been fulfilled".
    "fulfilled",
    "add", "adding", "remove", "removing", "send", "sending", "sent", "reply", "replying",
    "draft", "drafting", "write", "writing", "email", "emailing", "note", "tag", "tagging",
    "mark", "marking", "set", "setting", "put", "make", "create", "creating", "change",
    "changing", "update", "updating", "ship", "shipping", "adjust", "adjusting", "apply",
    "move", "moving",
})
MUTATION = MUTATION_STRONG | MUTATION_SOFT
# A request that opens with one of these is asking, whatever verbs come later in it.
_OPENERS = frozenset({
    "what", "whats", "which", "who", "whose", "how", "when", "where", "why", "is", "are",
    "was", "were", "do", "does", "did", "has", "have", "had", "any", "anyone", "anybody",
    "show", "list", "tell", "give", "find", "check", "read", "look", "whos",
})
# A SOFT verb straight after a determiner is a noun, wherever the sentence starts. "Customers
# who need a reply?" asks about a state of the inbox, and was refused as "asks for a change"
# because it opens with no question word and "reply" was read as an order to send one. "Reply
# to Mia" has no determiner in front of it, and "send a reply to order 2044" still carries
# "send", so neither instruction is lost.
_DETERMINER = frozenset({"a", "an", "the", "any", "no", "our", "my", "your", "their"})
_NOUN_READING = frozenset({"reply"})


def _as_a_noun(words: tuple[str, ...], index: int) -> bool:
    return words[index] in _NOUN_READING and index > 0 and words[index - 1] in _DETERMINER


def mutating(words: tuple[str, ...]) -> bool:
    """Whether this request asks for a change."""
    have = set(words)
    if have & MUTATION_STRONG:
        return True
    if not any(w in MUTATION_SOFT and not _as_a_noun(words, i) for i, w in enumerate(words)):
        return False
    return not (words and words[0] in _OPENERS)


# Verbs that only ever ask. Present with a mutation verb, the mutation still wins.
_QUESTION = frozenset({"what", "which", "who", "how", "when", "where", "show", "tell", "list", "find", "check", "look", "read", "give"})

_WORD = re.compile(r"[a-z0-9£$%'#]+")
# A possessive or a contraction is the same word wearing a suffix. Keeping the apostrophe made
# "today's" a token of its own, so it matched no period word and "show me today's orders" — the
# ordinary way to ask — resolved to no family at all while "orders today" resolved to a sales
# metric. Every closed set in this file is written without apostrophes, so stripping the tail
# can only help a word find its set.
_POSSESSIVE = re.compile(r"'s$")
# Somebody's something. The time words take a possessive too ("today's orders"), and those are
# not people, so they are excluded by name. What is left is almost always a person: "Millie's
# emails" is a question about one customer's correspondence, and answering it with the whole
# inbox — which is what happened — is a confident answer to a different question. The fast
# lane has no way to resolve a name it has never seen, so it declines and Claude, which can
# search for the customer, takes the turn.
_TIME_POSSESSIVE = frozenset({
    "today", "yesterday", "tomorrow", "week", "weeks", "month", "months", "year", "years",
    "day", "days", "morning", "afternoon", "evening", "tonight", "weekend", "quarter",
    "this", "last", "next", "it", "that", "there", "who", "what", "let",
    "customer", "order", "buyer", "client", "shopper", "recipient", "company",
})
_OWNER_OF = re.compile(r"\b([a-z]+)'s\b")


def _tokens(lowered: str) -> tuple[str, ...]:
    return tuple(_POSSESSIVE.sub("", w) or w for w in _WORD.findall(lowered))

# Direction: moving through a set that is already open.
_NEXT = frozenset({"next", "onwards", "forward", "another", "following"})
_PREV = frozenset({"previous", "prior", "before", "last"})
_BACK = frozenset({"back", "return"})
# Where the assistant's own landing is. "Assistant" is one of these because the chip on the
# glass says Assistant and the owner says "back to the assistant" — four words with "back" in
# them, which was read as one step back along the trail.
_HOME = frozenset({"home", "start", "top", "beginning", "assistant"})

# Meta: questions about the assistant rather than the shop.
_SELF = frozenset({"you", "your", "yourself"})
# A question about what it CAN do. "You" alone is not one: "what did you do" and "what have
# you done" are questions about the last turn, and were being answered with a capability
# blurb.
_ABLE = frozenset({"can", "could", "capable", "capabilities", "capability", "abilities", "ability", "able", "handle", "manage", "know"})
_MORE = frozenset({"more", "new", "newly", "extra", "now", "changed", "gained", "added", "since", "update", "updated", "upgrade", "upgraded"})

_PERIOD = frozenset({
    "today", "yesterday", "week", "weeks", "month", "months", "year", "day", "days",
    "morning", "afternoon", "tonight", "weekend", "quarter", "recently", "lately",
})
# A quantity is being asked for. "Orders" is deliberately NOT here: "how many orders today" is
# a number and "show me today's orders" is a list, and the word they share cannot decide which.
# What decides is whether a quantity was asked for ("how much", "how many") or a look was
# ("show", "list") — so the quantity words carry the metric reading and _LISTING carries the
# other. Before this split, "show me today's orders" was answered with a revenue figure.
_METRIC = frozenset({
    "sales", "selling", "sold", "revenue", "takings", "turnover", "units",
    "average", "aov", "spend", "spent", "breakdown", "split", "compare", "comparison",
    "versus", "vs", "against", "made", "money", "much", "many",
})
# Asking to be shown something, rather than told a figure about it.
_LISTING = frozenset({"show", "list", "see", "display", "view", "pull", "bring", "open", "give"})
# Asking for the same thing again. The order is already the branch's entity; this is a
# re-render, not a new lookup.
# "Back" is deliberately absent: it is a direction, not a repetition. While it was here,
# "is the black tee back in stock" scored as "show that order again" and answered a stock
# question with the order card that happened to be open — and "go back" never needed it,
# because that is navigation_back's word.
_AGAIN = frozenset({"again", "re-open", "reopen", "once more", "one more time"})
# Asking for an order of merit rather than a total: a different question and a different card.
_RANKING = frozenset({"best", "bestseller", "bestsellers", "top", "worst", "most", "least", "highest", "lowest", "popular", "biggest"})
_STOCK = frozenset({"stock", "inventory", "left", "remaining", "sizes"})
# Running out is a different question from how much is on the shelf. "What is running out"
# is a ranking by cover across the catalogue; "how much stock of the yard jeans" is one
# product, and belongs to the model, which can find the product.
_RUNNING_OUT = frozenset({"cover", "running", "low", "reorder", "restock", "restocking", "short", "soon", "empty"})
_EMAIL = frozenset({"email", "emails", "emailed", "inbox", "mail", "mailed", "message", "messages", "thread", "threads", "unread", "unanswered", "replied", "reply", "replies", "replying", "heard", "wrote", "written", "correspondence"})
# Someone is owed an answer. The question "who needs replying to" is this signal, not a
# request to reply: it asks about a state of the inbox.
_WAITING = frozenset({"waiting", "unanswered", "unreplied", "outstanding", "owed", "chase", "chasing", "needs", "need", "back", "ignored", "hanging"})
# "Any emails I haven't replied to" names the same state with no word of waiting in it: a
# negation beside a word of answering. Only when the owner is the one who has not answered —
# a first-person subject, or the passive "hasn't been answered" — because "did Mia not reply"
# is about Mia, and "everyone who has not replied" is about the customers.
_NEGATION = frozenset({"not", "never", "havent", "haven't", "hasnt", "hasn't", "didnt", "didn't"})
_ANSWERED = frozenset({"replied", "answered", "responded", "reply", "answer"})
_OWNER_SUBJECT = frozenset({"i", "we", "ive", "i've", "weve", "we've", "been"})
# Owed an answer, asked without a word for email: "does anyone need an ANSWER from us".
_ANSWER = frozenset({"answer", "answers", "answered", "response", "responses", "responded"})
# "Is anyone waiting on ME" — the person waited on is the owner. With no order named, what the
# owner is being waited on for is an answer.
_WAITED_ON = frozenset({"me", "us"})
_DELAY = frozenset({"late", "delayed", "overdue", "waiting", "stuck", "unfulfilled", "unshipped", "slow"})
# The orders that have not gone out, named as a STATE: "unfulfilled", "undelivered",
# "unshipped" — and "waiting longest", which names the same set by its worst member. The words
# of lateness ("late", "overdue") are deliberately absent: those belong to delayed_orders,
# which answers a narrower question (unfulfilled past five days), and a signal that took its
# sentences would take its family with them.
_UNFULFILLED = frozenset({"unfulfilled", "undelivered", "unshipped", "undispatched", "unposted", "unsent", "outstanding"})
# Where it is going. "Undelivered" is in _UNFULFILLED and NOT here on purpose: the destination
# and the delivery are different questions, and only one of them can be answered.
_INTERNATIONAL = frozenset({"international", "overseas", "abroad", "export", "exports", "foreign", "worldwide", "eu", "europe"})
_ORDER = frozenset({"order", "orders", "invoice", "purchase"})
_CUSTOMER = frozenset({"customer", "customers", "buyer", "buyers", "client", "clients", "people", "person", "someone"})
_STATUS = frozenset({"status", "where", "shipped", "dispatched", "tracking", "delivered", "arrived", "fulfilled"})
# "Number" is deliberately absent. It made "what's the order number" a request for the postal
# address, answered confidently and read aloud. "House number" and "door number" still reach
# this through "house" and "door", which mean nothing else.
_ADDRESS = frozenset({"address", "street", "addresses", "postcode", "house", "door", "line"})
# "Before" is deliberately absent: "has she bought before" already carries "bought", and
# "the one before" is a direction. A word that means two things belongs to the reading that
# needs it, not to both.
_BOUGHT = frozenset({"bought", "buy", "buys", "ordered", "purchased", "spent", "spend", "history", "previously"})

# Complexity markers: a request with two clauses is not a fast path, whatever its words say.
_JOIN = frozenset({"and", "then", "also", "plus", "after", "afterwards", "but", "however", "while", "whilst", "if", "unless", "because"})

# ------------------------------------------------------------------ the whole vocabulary
#
# Every word above, in one set. Not used to route anything: used to recognise a word that is
# NOT one of these, which is how a NAME is found in a sentence the branch has never resolved
# (D-14). "What has David Randall ordered in his lifetime" carries two tokens this router has
# no meaning for at all, and those two tokens are the person the owner named — the person the
# turn answered about somebody else instead.
#
# Built from the sets rather than written out, so a word added to `_EMAIL` or `_BOUGHT` stops
# being mistaken for a name the moment it is added.
VOCABULARY: frozenset[str] = frozenset(
    MUTATION | _OPENERS | _QUESTION | _NEXT | _PREV | _BACK | _HOME | _SELF | _ABLE | _MORE
    | _PERIOD | _METRIC | _LISTING | _AGAIN | _RANKING | _STOCK | _RUNNING_OUT | _EMAIL
    | _WAITING | _DELAY | _UNFULFILLED | _INTERNATIONAL | _ORDER | _CUSTOMER | _STATUS
    | _ADDRESS | _BOUGHT | _JOIN | _TIME_POSSESSIVE
    | _NEGATION | _ANSWERED | _OWNER_SUBJECT | _ANSWER | _WAITED_ON
)

# ------------------------------------------------- appended for app/families/compose.py
#
# Four signals no family above reads, and each of them exists because the composer cannot be
# told apart from something else without it.
#
# `has_address` — the words carry an email address. It is the ONLY thing separating "write an
# email to 1232candlestickhorse@gmail.com" (a recipient the shop has never heard of, which is
# what the composer is for) from "email them all" (which is about the open set and belongs to
# the model). Dictated forms count, because that is how an address arrives through a
# microphone: "1232 candlestick horse at gmail dot com".
#
# `send_instead` — the sentence corrects a draft into a send. Deliberately narrow: a send verb
# AND a correction word, or a refusal of the draft, or "wanted it sent". Without the narrowness
# "cancel it" would reach the composer, since it too is a mutation with a pointer in it — and
# `tests/test_fastpath.py::test_a_mutation_verb_leaves_the_lane_whatever_else_it_says` says
# exactly why that must not happen.
#
# `has_compose` / `rewrite` — a rewriting instruction, and a composer open on THIS half to
# apply it to. Both are required together: "make it shorter" means nothing with no composer,
# and "archive them" said over an open composer is not a rewrite.
_ADDRESS_LITERAL = re.compile(r"[a-z0-9][a-z0-9._%+-]*@[a-z0-9][a-z0-9.-]*\.[a-z]{2,24}")
# The local part is a run of at most seven words with NO full stop in it, and the domain is
# labels joined by the word "dot". Both bounds are what stops the span swallowing the prose in
# front of it: without them, "…free for a shoot next Sunday. Their email is 1232 candlestick
# horse at gmail dot com" matched from "free", and the normaliser was handed a sentence.
_ADDRESS_DICTATED = re.compile(
    r"(?:[a-z0-9][a-z0-9_%+-]*\s+){0,6}[a-z0-9][a-z0-9_%+-]*"
    r"\s+(?:at|@)\s+"
    r"(?:[a-z0-9][a-z0-9-]*\s+(?:dot|\.)\s+){1,3}[a-z]{2,24}\b"
)
_SEND = frozenset({"send", "sent", "sending"})
_INSTEAD = frozenset({"instead", "actually", "rather"})
_REFUSAL = frozenset({"no", "nope", "dont", "don't", "doesnt", "doesn't", "not", "never"})
_DRAFT_WORD = frozenset({"draft", "drafts", "drafted", "save", "saving", "saved"})
_WANTED = frozenset({"want", "wanted", "wants", "meant"})
_REWRITE = frozenset({
    "shorter", "longer", "briefer", "warmer", "friendlier", "apologetic", "apologise",
    "polite", "politer", "firmer", "softer", "blunter", "reword", "rewrite", "redo",
    "rephrase", "shorten", "tighten", "lengthen", "subject", "tone", "wording", "sign",
})


def _address_span(lowered: str) -> str:
    """The address in the words, as said. Literal first, then the dictated form."""
    found = _ADDRESS_LITERAL.search(lowered)
    if found:
        return found.group(0)
    found = _ADDRESS_DICTATED.search(lowered)
    return found.group(0) if found else ""


def _send_instead(words: tuple[str, ...]) -> bool:
    have = set(words)
    if not (have & _SEND):
        return False
    if have & _INSTEAD:
        return True                                    # "send it instead", "actually send that"
    if (have & _REFUSAL) and (words[0] in _REFUSAL or (have & _DRAFT_WORD)):
        return True                                    # "no, send it", "don't save a draft, send it"
    return "sent" in have and bool(have & _WANTED)     # "we want this sent"


@dataclass(slots=True)
class Signals:
    words: tuple[str, ...] = ()
    # The request as it was said, case and all. Held because CASE is evidence: a capitalised
    # word the router has no meaning for is a person's name, and that is how a sentence that
    # NAMES somebody is told from one that points at the record in focus (D-14). PRIVATE — it
    # is the owner's own sentence, and telemetry carries ids, counts and controlled words.
    raw: str = ""
    mutation: bool = False
    question: bool = False
    joins: int = 0
    order_numbers: tuple[str, ...] = ()
    direction: str = ""             # next | previous | back | home
    meta_self: bool = False
    meta_more: bool = False
    period: bool = False
    metric: bool = False
    ranking: bool = False
    stock: bool = False
    running_out: bool = False
    email: bool = False
    waiting: bool = False
    # Somebody is owed an answer by the owner: the inbox and a word of waiting, or an answer
    # and a word of waiting, or somebody waiting on "me" with no order named. What needs_reply
    # needs, so the family is not bound to the one word "email" being said.
    owed_reply: bool = False
    delayed: bool = False
    order: bool = False
    customer: bool = False
    unfulfilled: bool = False       # named as a state: "unfulfilled", "undelivered", "waiting longest"
    international: bool = False     # named a destination outside the shop's country
    status: bool = False
    address: bool = False
    listing: bool = False
    again: bool = False
    possessive_name: bool = False
    bought: bool = False
    deixis: bool = False            # "that", "this", "it", "them", "these"
    # Branch state, folded in: what the conversation already has open.
    has_entity: bool = False
    # Whether a customer has been open on this half at any point. "Bring up a UI for the
    # customer's page" names a person without naming one, and the person it names is the one
    # this conversation has been looking at — which is not always the record in focus, because
    # a read of the inbox moves the focus off it (D-3). Without this the third of D-5's three
    # attempts had nothing to resolve and fell to the model, which spoke.
    has_recent_customer: bool = False
    has_set: bool = False
    has_workflow: bool = False
    known_name: str = ""
    # app/families/compose.py. `address_words` is the span as it was said, kept so the recipe
    # normalises the same characters the router matched rather than searching again with a
    # second regex that could disagree with this one.
    has_address: bool = False
    address_words: str = ""
    send_instead: bool = False
    has_compose: bool = False
    rewrite: bool = False
    # What the owner took back mid-sentence (app/fastpath/correction.py): "today's, uh,
    # yesterday's orders" names two periods and asks about one. Held as structure so every
    # family reads one answer rather than each re-parsing the words.
    corrections: tuple[Any, ...] = ()

    # Never written to the timeline, whatever it holds. `known_name` is a customer's name as
    # the owner said it; the observability rule is that telemetry carries ids, counts and
    # controlled words, and this is none of those. The router still uses it; the record says
    # only that a name was recognised. `address_words` is an email address, which is the same
    # kind of thing: `has_address` says one was found and the span never leaves the Mac.
    # `corrections` carries the values themselves, so the record says which FAMILIES were
    # corrected and not to what.
    PRIVATE = ("words", "raw", "known_name", "address_words", "corrections")

    def as_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in ((f, getattr(self, f)) for f in self.__slots__) if v and k not in self.PRIVATE}
        if self.known_name:
            out["known_name"] = True
        if self.corrections:
            out["corrected"] = [c.family for c in self.corrections]
        return out

    def correction(self, family: str) -> str:
        for found in self.corrections:
            if found.family == family:
                return found.value
        return ""


# Pointing at what is already on screen. "She" and "he" belong here for the same reason "her"
# and "him" do: they refer to the record in front of the owner, not to a person named in the
# sentence.
_DEIXIS = frozenset({"that", "this", "it", "them", "those", "these", "they", "him", "her",
                     "their", "she", "he", "his", "hers"})


def signals_for(text: str, *, branch: Any = None) -> Signals:
    """Everything the router looks at, extracted once."""
    from app.routes.turn import spoken_order_numbers

    lowered = (text or "").lower()
    words = _tokens(lowered)
    have = set(words)
    sig = Signals(
        words=words,
        raw=" ".join((text or "").split()),
        mutation=mutating(words),
        question=bool(have & _QUESTION) or lowered.strip().endswith("?"),
        joins=sum(1 for w in words if w in _JOIN),
        order_numbers=tuple(spoken_order_numbers(text or "")),
        meta_self=bool(have & _SELF) and bool(have & _ABLE),
        meta_more=bool(have & _MORE),
        period=bool(have & _PERIOD),
        metric=bool(have & _METRIC),
        ranking=bool(have & _RANKING),
        stock=bool(have & _STOCK),
        running_out=bool(have & _RUNNING_OUT) or ({"out", "of"} <= have and not (have & _STOCK)) or ("out" in have and "running" in have),
        email=bool(have & _EMAIL),
        listing=bool(have & _LISTING),
        again=bool(have & _AGAIN),
        possessive_name=any(w not in _TIME_POSSESSIVE for w in _OWNER_OF.findall(lowered)),
        waiting=bool(have & _WAITING) or bool(have & _NEGATION and have & _ANSWERED and have & _OWNER_SUBJECT),
        delayed=bool(have & _DELAY),
        order=bool(have & _ORDER),
        customer=bool(have & _CUSTOMER),
        # "Orders waiting longest" carries no state word at all, and it is the same request:
        # the superlative on a word of delay is the set of things still to go out.
        unfulfilled=bool(have & _UNFULFILLED) or ("longest" in have and bool(have & _DELAY)),
        international=bool(have & _INTERNATIONAL),
        status=bool(have & _STATUS),
        address=bool(have & _ADDRESS),
        bought=bool(have & _BOUGHT),
        deixis=bool(have & _DEIXIS),
        address_words=_address_span(lowered),
        send_instead=_send_instead(words),
        rewrite=bool(have & _REWRITE),
    )
    sig.has_address = bool(sig.address_words)
    sig.owed_reply = sig.waiting and (
        sig.email or bool(have & _ANSWER)
        or ("waiting" in have and bool(have & _WAITED_ON) and not sig.order)
    )
    # What was taken back mid-sentence, before any family reads the values (D-8). An order
    # number the owner corrected is NOT a second order: "1956, I mean 1957" named one record,
    # and leaving both in `order_numbers` made every family that needs exactly one defer.
    sig.corrections = tuple(correction.corrections(words))
    sig.order_numbers = _corrected_orders(sig)
    # A direction is a direction only when the request names NOTHING ELSE. "Next" is a
    # direction; "next week's sales" is a question about sales, "what's the last order" is a
    # question about an order, and "has she bought before" is a question about a customer.
    # Every one of those was routed to the set-walker before this check existed, and the
    # walker would have answered a question about an order with a customer.
    bare = not (sig.order or sig.customer or sig.email or sig.metric or sig.ranking
                or sig.stock or sig.running_out or sig.period or sig.status or sig.address
                or sig.bought or sig.delayed or sig.meta_self or sig.order_numbers)
    if bare and len(words) <= 5:
        if have & _NEXT:
            sig.direction = "next"
        # Home before back, because the words overlap and the phrase that names a PLACE is the
        # specific one: "back to the start" and "back to the assistant" are both a landing, and
        # both were read as one step along the trail because "back" was tested first.
        elif have & _HOME and len(words) <= 4:
            sig.direction = "home"
        elif have & _BACK:
            sig.direction = "back"
        elif have & _PREV:
            sig.direction = "previous"
    if branch is not None:
        sig.has_entity = bool(getattr(branch, "entity", None))
        entity = getattr(branch, "entity", None) or {}
        sig.has_recent_customer = entity.get("kind") == "customer" or any(
            e.get("kind") == "customer" for e in (getattr(branch, "recent_entities", None) or [])
        )
        sig.has_set = bool(getattr(branch, "set_id", ""))
        sig.has_workflow = getattr(branch, "workflow", None) is not None
        sig.known_name = _known_name(text or "", branch)
        sig.has_compose = bool(getattr(branch, "compose", None))
    return sig


def _corrected_orders(sig: Signals) -> tuple[str, ...]:
    """The order numbers the request named, with a correction applied.

    "Order 1936, I mean 1938" names ONE record. `spoken_order_numbers` extracts only 1936 —
    the second number has no "order" in front of it — so the correction replaces the number
    it superseded rather than being required to appear in the list itself.

    A bare year is still refused. `spoken_order_numbers` will not read "2025" as an order
    without "order number" or a hash in front of it, and a correction must not be the way
    round that: the corrected value is accepted only when it is outside the year range, or
    when the extractor already found it.
    """
    numbers = tuple(sig.order_numbers)
    fixed = sig.correction(correction.ORDER_NUMBER)
    if not fixed:
        return numbers
    if fixed in numbers:
        return (fixed,)
    if 2000 <= int(fixed) <= 2099:
        return numbers
    superseded = next((c.superseded for c in sig.corrections if c.family == correction.ORDER_NUMBER), "")
    return (fixed,) if superseded in numbers else numbers


def _known_name(text: str, branch: Any) -> str:
    """A name this branch has already resolved to a record, if the request says it. Longest
    match wins, so "Millie Rogers" beats "Millie"."""
    lowered = " ".join((text or "").lower().split())
    best = ""
    for key in getattr(branch, "resolutions", {}) or {}:
        if key and key in lowered and len(key) > len(best):
            best = key
    return best


# ------------------------------------------------------------------ families


# What a family is FOR, which is what settles a request that asks for two things at once
# (§14, D-14). Turn 1 of the live session asked "are you okay now?" and "pull up the today's
# emails" and got the capability delta and no emails. The order is not a preference:
#
#     WORK        explicit requested work — a read of the shop or the inbox, a move
#     STATUS      contextual status — how the assistant itself is
#     CAPABILITY  an explanation of what it can do
#
# Work outranks status outranks capability, always. A status answer may be given; it may not
# take the turn.
WORK = "work"
STATUS = "status"
CAPABILITY = "capability"
KIND_RANK: dict[str, int] = {WORK: 0, STATUS: 1, CAPABILITY: 2}


@dataclass(frozen=True, slots=True)
class Family:
    """One intent family and the signals that identify it.

    `needs` are required (all of them); `boosts` add confidence; `blocks` rule it out. `floor`
    is the confidence a match must reach; `entities` are what the runner must resolve before
    the family may run at all.
    """

    name: str
    needs: tuple[str, ...] = ()
    boosts: tuple[str, ...] = ()
    blocks: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    base: float = 0.55
    floor: float = 0.7
    # A request longer than this many words is not this family, however it scores: a short
    # instruction is what the fast lane is for.
    max_words: int = 14
    # Appended for app/families/compose.py, both defaulting to the behaviour every family
    # above already has.
    #
    # `serves_mutation_words`: this family's sentence carries a mutation verb and is still a
    # READ. "Write an email to <address>" and "send it instead" are instructions, and the
    # fast lane must not try to SERVE a change — but drawing the composer, with the address
    # the owner dictated resolved and the words printed, changes nothing and stages nothing.
    # The exception withdraws only the refusal to SCORE the sentence: a recipe still names
    # read tools alone (recipes.assert_read_only) and the read scheduler still refuses a plan
    # with a write in it (reads/scheduler.assert_reads_only), so a family that declares this
    # is no more able to write than any other. Every family that does not declare it keeps
    # the blanket refusal, which is why "cancel it" still leaves the lane unscored.
    serves_mutation_words: bool = False
    # `many_clauses`: the joins penalty below says two clauses are two requests, and drops
    # 0.25 per clause. A dictated email is ONE request with as many clauses as the owner
    # cares to speak — "asking if they're free for a shoot next Sunday and whether they can
    # bring boots" is not two questions — so the composer opts out of the penalty rather than
    # the scorer growing a special case for long sentences generally.
    many_clauses: bool = False
    # WORK, STATUS or CAPABILITY. Defaults to WORK, which every family that reads the shop or
    # the inbox is, so a family added later is ranked as work unless it says otherwise.
    kind: str = WORK


FAMILIES: tuple[Family, ...] = (
    Family("working_set_next", needs=("direction_next",), boosts=("has_workflow", "has_set"), blocks=("mutation",), entities=("workflow",), base=0.8, max_words=6),
    Family("working_set_previous", needs=("direction_previous",), boosts=("has_workflow", "has_set"), blocks=("mutation",), entities=("workflow",), base=0.8, max_words=6),
    Family("navigation_back", needs=("direction_back",), blocks=("mutation",), base=0.85, max_words=5),
    Family("navigation_home", needs=("direction_home",), blocks=("mutation",), base=0.8, max_words=4),
    Family("capability_delta", needs=("meta_self", "meta_more"), blocks=("mutation",), base=0.75, max_words=16, kind=CAPABILITY),
    # §5. `capability_question` is the whole of the fix for D-5: "can you" and "you" beside a
    # word of ability were the only requirement, so every politely-phrased instruction — "can
    # you expand his customer page", "can you open David Harding", "can you pull up his order
    # history" — scored as a question about the assistant and was answered with a 1,014-pixel
    # list of what the product can do. The two signals it had are KEPT and one is ADDED: this
    # can only narrow what reaches the family, never widen it.
    Family("capability_summary", needs=("meta_self", "question", "capability_question"), blocks=("mutation", "meta_more"), base=0.7, max_words=12, kind=CAPABILITY),
    Family("order_lookup", needs=("order_number",), boosts=("order", "question"), blocks=("mutation", "metric", "email", "status", "address"), entities=("order",), base=0.8, max_words=12),
    # "Show me today's orders" — a list, not a total. It needs an explicit ask to be shown,
    # so "how many orders today" stays a number and this stays a list.
    Family("order_list_period", needs=("order", "period"), boosts=("listing", "question"),
           blocks=("mutation", "metric", "order_number", "ranking", "running_out", "stock", "email", "delayed", "status", "address"),
           entities=("order",), base=0.74, max_words=12),
    # "Show it again" / "1938 again" — the order is already the branch's entity, so this is a
    # re-render of what is open, not a fresh lookup. Requires an entity: with nothing open
    # there is nothing to show again, and guessing would re-open the wrong record.
    Family("order_reopen", needs=("again", "has_entity"), boosts=("listing", "order", "question"),
           blocks=("mutation", "metric", "email", "ranking", "period", "direction_back",
                   "stock", "running_out", "status", "address"),
           entities=("order",), base=0.76, max_words=8),
    # "What else has this customer ordered?" — the person is whoever the open record belongs
    # to, so no name has to be resolved.
    # "What else has THIS customer ordered?" — the person is whoever the open record belongs
    # to. Blocked by a name, because a name means a different question: "has Daniel bought
    # from us before" is about Daniel whatever is on screen, and answering it from the open
    # order would report on whoever that order belongs to. customer_purchase_lookup takes
    # the named case; this one takes the pronoun.
    # D-14: `names_a_person` replaces the pair `known_name`/`possessive_name` it contains.
    # Those two blocked a name the branch had ALREADY resolved and a possessive — and so the
    # live session's "what has [customer A] ordered in his lifetime", which named a person
    # this conversation had never resolved, reached this family, read the ORDER in focus, and
    # spoke a different customer's order history as a statement of fact. A named person
    # outranks the record in focus, always; this family is the pronoun case only.
    Family("customer_history_lookup", needs=("bought", "has_entity", "deixis"), boosts=("customer", "question"),
           blocks=("mutation", "order_number", "metric", "email", "ranking", "period",
                   "names_a_person"),
           entities=("customer", "order"), base=0.74, max_words=12),
    Family("order_status_lookup", needs=("status",), boosts=("order_number", "order", "has_entity", "deixis"), blocks=("mutation", "metric", "address", "possessive_name"), entities=("order",), base=0.72, max_words=14),
    Family("order_address_lookup", needs=("address",), boosts=("order_number", "has_entity", "deixis"), blocks=("mutation", "metric", "email", "possessive_name"), entities=("order",), base=0.72, max_words=14),
    # D-14: `names_a_person`, not `known_name`. "What has [customer A] ordered in his
    # lifetime" names the person plainly and the branch had not resolved him, so this family
    # — the one that resolves a name against the shop before it reads anything — could not
    # take the turn, and the one that answers from the record in focus did.
    Family("customer_purchase_lookup", needs=("names_a_person", "bought"), boosts=("customer", "question"), blocks=("mutation",), entities=("customer",), base=0.72, max_words=14),
    Family("best_sellers_period", needs=("ranking",), boosts=("period", "question", "metric"), blocks=("mutation", "email", "stock", "running_out", "order_number", "customer"), base=0.65, floor=0.72, max_words=14),
    # Blocks "customer" because "how many" is in _METRIC: without it "how many customers do we
    # have today" scored as the sales card and was answered "Today: £162.00, 3 orders" — a
    # confident figure that is not what was asked for. The model can count customers.
    Family("sales_breakdown_period", needs=("metric", "period"), boosts=("question",), blocks=("mutation", "email", "stock", "running_out", "order_number", "ranking", "customer"), base=0.66, floor=0.72, max_words=16),
    Family("delayed_orders", needs=("delayed", "order"), boosts=("question", "period"), blocks=("mutation", "order_number"), base=0.72, max_words=14),
    Family("stock_cover_analysis", needs=("running_out",), boosts=("question", "period", "metric", "stock"), blocks=("mutation", "email", "order_number"), base=0.7, floor=0.72, max_words=12),
    # `owed_reply` rather than `email` and `waiting`, which it contains: "is anyone waiting on
    # me" and "does anyone need an answer from us" say no word for email. `opens_asking`,
    # because "anyone waiting on a reply" and "any emails I haven't replied to" are asked with
    # "any" and "anyone", which carry no question word and left the family under its floor.
    Family("needs_reply", needs=("owed_reply",), boosts=("customer", "question", "opens_asking"), blocks=("mutation", "metric", "order_number", "ranking"), base=0.7, floor=0.74, max_words=14),
    # "The inbox, in one line." Blocked by anything that narrows it to a person or a field:
    # "what's her email address" is about one customer's address and was being answered with a
    # summary of the whole week's threads.
    # `asked`, not `question`: "can you pull up the today's emails" is a request even though
    # it opens with an auxiliary and carries none of the question words. It was scoring zero,
    # so the emails half of turn 1 could not win however the turn was split (D-14).
    Family("inbox_state", needs=("email", "asked"), boosts=("period",), blocks=("mutation", "metric", "customer", "waiting", "ranking", "order_number", "possessive_name", "deixis", "address"), base=0.7, floor=0.74, max_words=12),
)

# Families a Phase 3 capability module adds from its own file (app/families/*), so two
# families never edit this tuple's same line. Read wherever FAMILIES is read.
EXTRA_FAMILIES: list[Family] = []


def extend(families: list[Family] | tuple[Family, ...]) -> None:
    known = {f.name for f in FAMILIES} | {f.name for f in EXTRA_FAMILIES}
    for family in families:
        if family.name in known:
            raise ValueError(f"intent family {family.name!r} is already registered")
        EXTRA_FAMILIES.append(family)
        known.add(family.name)


def all_families() -> tuple[Family, ...]:
    return FAMILIES + tuple(EXTRA_FAMILIES)


# Signal names as the families spell them, mapped to how they are read off Signals.
_LOOKUP = {
    "mutation": lambda s: s.mutation,
    "question": lambda s: s.question,
    "order_number": lambda s: bool(s.order_numbers),
    "direction_next": lambda s: s.direction == "next",
    "direction_previous": lambda s: s.direction == "previous",
    "direction_back": lambda s: s.direction == "back",
    "direction_home": lambda s: s.direction == "home",
    "meta_self": lambda s: s.meta_self,
    "meta_more": lambda s: s.meta_more,
    "period": lambda s: s.period,
    "metric": lambda s: s.metric,
    "ranking": lambda s: s.ranking,
    "stock": lambda s: s.stock,
    "running_out": lambda s: s.running_out,
    "email": lambda s: s.email,
    "listing": lambda s: s.listing,
    # Asked for, one way or the other: a question word, a question mark, or an instruction to
    # be shown something. "Show me the emails" and "can you pull up the emails" are one
    # request, and only the first of them carries a question word.
    "asked": lambda s: s.question or s.listing,
    "again": lambda s: s.again,
    "possessive_name": lambda s: s.possessive_name,
    "waiting": lambda s: s.waiting,
    "owed_reply": lambda s: s.owed_reply,
    # Opened the way a question is opened — "any", "anyone", "is", "does" — whether or not a
    # question word follows.
    "opens_asking": lambda s: bool(s.words) and s.words[0] in _OPENERS,
    "delayed": lambda s: s.delayed,
    "order": lambda s: s.order,
    "customer": lambda s: s.customer,
    "unfulfilled": lambda s: s.unfulfilled,
    "international": lambda s: s.international,
    "status": lambda s: s.status,
    "address": lambda s: s.address,
    "bought": lambda s: s.bought,
    "deixis": lambda s: s.deixis,
    "has_entity": lambda s: s.has_entity,
    "has_recent_customer": lambda s: s.has_recent_customer,
    "has_set": lambda s: s.has_set,
    "has_workflow": lambda s: s.has_workflow,
    "known_name": lambda s: bool(s.known_name),
    # app/families/compose.py
    "has_address": lambda s: s.has_address,
    "send_instead": lambda s: s.send_instead,
    "has_compose": lambda s: s.has_compose,
    "rewrite": lambda s: s.rewrite,
    # §5, §4 and D-14 (app/capabilities/ask.py). Core signals, not family-registered ones,
    # because `capability_summary` is in the table above and must read them, and because a
    # family cannot narrow a family it does not own.
    #
    #   capability_question  "can you" means a question about the assistant ONLY when the
    #                        sentence names nothing to do. The operation, the entity or the
    #                        task that follows dominates the opener, always (§5).
    #   ui_demand            the words oblige a visible workspace: show, show me, open, pull
    #                        up, bring up, expand, take me to, go to, view (§4).
    #   goes_to              the two demand phrases the landings do not already own.
    #   names_a_person       the sentence says WHO it is about, including a name this
    #                        conversation has never resolved. A family that answers from the
    #                        record in focus blocks on this (D-14).
    "capability_question": lambda s: _ask().is_a_capability_question(s),
    "ui_demand": lambda s: bool(_ask().demand_phrase(s.words)),
    "goes_to": lambda s: _ask().goes_to(s.words),
    "names_a_person": lambda s: _ask().names_a_person(s),
}


def _ask():
    """app/capabilities/ask.py, imported on use. The module reads this one's VOCABULARY, so
    importing it at the top of this file would be a cycle."""
    from app.capabilities import ask

    return ask


@dataclass(frozen=True, slots=True)
class Intent:
    family: str
    confidence: float
    signals: Signals
    slots: dict[str, Any] = field(default_factory=dict)
    runner_up: str = ""
    reason: str = ""
    # The other thing the request asked for, when it asked for two (§14). The turn is
    # answered as `family`; `secondary` is what the answer should also acknowledge, in a
    # clause. "Are you okay now? Can you pull up the today's emails" is the emails, with the
    # health question kept here rather than thrown away.
    secondary: str = ""

    @property
    def certain(self) -> bool:
        return self.family != "" and self.confidence > 0

    def public(self) -> dict[str, Any]:
        return {"family": self.family or None, "confidence": round(self.confidence, 3),
                "runner_up": self.runner_up or None, "reason": self.reason or None,
                "secondary": self.secondary or None,
                "signals": self.signals.as_dict()}


# How far the winner must be clear of the runner-up. Two families within this of each other
# is an ambiguous request, and an ambiguous request belongs to the model.
MARGIN = 0.08


def signal(name: str, predicate: Callable[[Signals], bool]) -> str:
    """A family brings its own word to the router.

    The signal table is fixed vocabulary — order, period, metric, address — and a Phase 3
    family that needs a word of its own ("show me the SHIPPING", "the LATEST order", "the
    other HALF") had no way to ask for one without editing the `Signals` dataclass, which is
    the file every family would then be editing at once. So a name and a predicate over the
    words already extracted; `score` looks the name up here like any other.

    A core signal is never redefined: shadowing `order` or `mutation` from a family module
    would change how every other family routes, which is exactly the drift this seam exists to
    avoid. Registering the same name twice with the same predicate is a no-op, so a module
    that is imported twice is harmless.
    """
    if name in _CORE_SIGNALS:
        raise ValueError(f"{name!r} is a core signal and cannot be redefined by a family")
    existing = _LOOKUP.get(name)
    if existing is not None and existing is not predicate:
        raise ValueError(f"the signal {name!r} is already registered by another family")
    _LOOKUP[name] = predicate
    return name


def score(family: Family, sig: Signals) -> float:
    """Zero when the family is ruled out; otherwise base plus what the boosts add."""
    if len(sig.words) > family.max_words:
        return 0.0
    for name in family.blocks:
        if _LOOKUP[name](sig):
            return 0.0
    for name in family.needs:
        if not _LOOKUP[name](sig):
            return 0.0
    value = family.base
    for name in family.boosts:
        if _LOOKUP[name](sig):
            value += 0.07
    # Two clauses is two requests. The second one would be dropped silently, so decline both.
    if not family.many_clauses:
        value -= 0.25 * max(0, sig.joins)
    # A short instruction is the fast lane's home ground; a long one is probably nuanced.
    if len(sig.words) <= 4:
        value += 0.06
    return max(0.0, min(0.99, value))


# Everything in the table as this module defines it. A family may add to the table; it may
# never replace one of these.
_CORE_SIGNALS = frozenset(_LOOKUP)


# Where one request ends and the next begins. SENTENCES only — a full stop, a question mark
# or an exclamation — and deliberately NOT "and" or "then". "Look up today's orders and
# today's emails and see if anything correlates" is ONE request for a synthesis, and
# splitting it here would answer a third of it and call that a win (D-5 is a different
# defect with a different fix). Two sentences, though, are two things said.
_SENTENCE = re.compile(r"[.!?]+")


def sentences(text: str) -> list[str]:
    """The request as the separate things it said. One sentence in, one sentence out."""
    return [part for part in (p.strip() for p in _SENTENCE.split(text or "")) if _tokens(part.lower())]


def kind_of(family_name: str) -> str:
    found = family(family_name) if family_name else None
    return found.kind if found is not None else WORK


def _rank(intent: Intent) -> int:
    return KIND_RANK.get(kind_of(intent.family), 0)


def resolve(text: str, *, branch: Any = None) -> Intent:
    """The request as an intent, with the priority order applied when it asked for two things.

    `family` empty means "this is the model's". `secondary` names the other thing the request
    asked for, when explicit work had to outrank it.
    """
    whole = _resolve_one(text, branch=branch)
    if whole.certain and _rank(whole) == KIND_RANK[WORK]:
        # The request as a whole asked for work. There is nothing to arbitrate, and the whole
        # sentence's slots are better than any one clause's.
        return whole
    said = sentences(text)
    if len(said) < 2:
        return whole
    apart = [_resolve_one(part, branch=branch) for part in said]
    work = [i for i in apart if i.certain and _rank(i) == KIND_RANK[WORK]]
    if not work:
        return whole
    # The highest-confidence piece of actual work wins the turn; the best-ranked of what is
    # left is acknowledged rather than dropped.
    best = max(work, key=lambda i: i.confidence)
    rest = [i for i in apart if i.certain and i is not best] + ([whole] if whole.certain else [])
    secondary = next((i.family for i in sorted(rest, key=_rank) if _rank(i) > KIND_RANK[WORK]), "")
    return replace(
        best, secondary=secondary,
        reason=f"the request also asked something {kind_of(secondary)}; the work outranks it" if secondary
        else "the request said more than one thing; the work outranks the rest",
    )


def _resolve_one(text: str, *, branch: Any = None) -> Intent:
    """One request, scored against the families. The whole of the router before §14."""
    sig = signals_for(text, branch=branch)
    candidates = all_families()
    if sig.mutation:
        # A change was asked for. Only the families that have declared they answer such a
        # sentence with a READ are eligible; if none of them fits, the turn goes to Claude
        # exactly as it always has, with the same reason on the timeline. Narrowing the
        # candidate set rather than lifting the guard is what keeps this scoped: a family
        # that has not opted in cannot be reached by a mutation sentence at all, however
        # well its signals happen to match.
        candidates = tuple(f for f in candidates if f.serves_mutation_words)
    scored = sorted(((score(f, sig), f) for f in candidates), key=lambda pair: (-pair[0], pair[1].name)) or [(0.0, None)]
    best_value, best = scored[0]
    second_value, second = (scored[1] if len(scored) > 1 else (0.0, None))
    if best_value <= 0 or best is None:
        return Intent(family="", confidence=0.0, signals=sig,
                      reason="asks for a change" if sig.mutation else "no family matched")
    if best_value < best.floor:
        return Intent(family="", confidence=round(best_value, 3), signals=sig, runner_up=best.name, reason="below the family's confidence floor")
    if second is not None and second_value > 0 and best_value - second_value < MARGIN:
        return Intent(family="", confidence=round(best_value, 3), signals=sig, runner_up=second.name, reason=f"too close to {second.name}")
    return Intent(family=best.name, confidence=round(best_value, 3), signals=sig, runner_up=(second.name if second_value > 0 and second else ""),
                  slots=_slots(sig))


def _slots(sig: Signals) -> dict[str, Any]:
    """The parameters a recipe reads, from one place whether they were said or tapped.

    `corrected` is every value the owner took back mid-sentence, by family, so a recipe reads
    the resolved value rather than re-parsing the words with a second rule that could
    disagree with the first. `size` is lifted out of it because the variant picker already
    reads a `size` slot (app/families/order_edit.py) and "a medium, no, a large" should
    narrow it.
    """
    fixed = {c.family: c.value for c in sig.corrections}
    # `name` is the person the request is ABOUT, and a name this conversation has never
    # resolved is still the person it is about (D-14). Before this, the slot held only a name
    # the branch had already learnt, so a recipe with a name in front of it had nothing to
    # search for and fell back to the record in focus — which is how one customer's question
    # was answered with another customer's history. The branch's own resolution is preferred
    # when it has one, because it carries an id and the span carries only words.
    slots: dict[str, Any] = {
        "order_numbers": list(sig.order_numbers),
        "name": _ask().person_for(sig),
    }
    if fixed:
        slots["corrected"] = fixed
    if fixed.get(correction.SIZE):
        slots["size"] = fixed[correction.SIZE]
    return slots


def family(name: str) -> Family | None:
    for candidate in all_families():
        if candidate.name == name:
            return candidate
    return None
