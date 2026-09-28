"""What a sentence asked for, held against what this Mac can actually do.

The report used to read the owner's words with rules of its own, and so it disagreed with
the router about what had been asked for. "Which customers need replying to?" was filed as a
change nobody made; "What is the refund status on 1938?" the same. A noun is not an
instruction, and a report that says otherwise sends an engineer to fix a write path that was
never wanted.

Three sources decide, in this order, and the report says which one spoke:

    the ROUTER's own verdict          `lane.signals.mutation` and `lane.family`, on a
                                      timeline recorded before 28 September 2026, when a
                                      word-matching router still wrote a `lane` event at turn
                                      time. Where it is on the timeline it is the answer.
    the report's own rule             every turn since, and any turn with no `lane` event.
                                      `contract.mutating` reads the words; there is no
                                      family, because nothing routes by words any more, and
                                      the verdict is marked `report`.
    ONE narrowing rule on top         a mutation word standing as a noun or a state —
                                      "the refund status", "a draft", "the reply" — which
                                      only ever turns a WRITE reading into a READ one, never
                                      the reverse, and is reported as a disagreement
                                      whenever it fires.

And once a change HAS been asked for, `app/capabilities/families.py` says what to do about
it: a change with no family is a capability that does not exist (a candidate new action
family); a change whose family is MISSING_SCOPE is a grant the owner has not made, with the
scope named. That difference is the whole of "do not report a fixed failure as still open".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Words that turn a mutation verb into a thing or a state. "Refund status" is a question
# about an order; "refund" alone, with a person after it, is an instruction.
STATE_NOUNS = frozenset({
    "status", "state", "policy", "window", "deadline", "amount", "total", "request",
    "reason", "history", "date", "eligibility", "folder", "queue", "option", "options",
    "rate", "value", "balance", "period", "rules", "limit", "code", "number", "email",
    "address", "note", "notes", "tag", "tags", "label", "labels", "confirmation",
})
# A determiner in front of a mutation word makes it the head of a noun phrase: "the reply",
# "any refund", "his draft". On its own that is not enough — "give them the refund" is an
# instruction — so it counts only in a sentence that is opened as an actual QUESTION.
#
# "Opened as a question" here is NARROWER than `contract.OPENERS`, and deliberately: that set
# counts "show", "list", "give", "find" among the words that open a question, because "show me
# the sales" is a read. Here the cost of being wrong runs the other way — a change wrongly read
# as a question is an unfulfilled action that goes unreported — so the fetching verbs are taken
# back out. The set is the contract's own, minus a named few.
DETERMINERS = frozenset({
    "the", "a", "an", "any", "that", "this", "these", "those", "his", "her", "their",
    "my", "our", "its", "some", "no", "which", "what", "whats", "another", "each",
})
# Words the contract counts as opening a question that are really instructions to fetch. A
# sentence that begins with one of them is not interrogative enough for a determiner alone to
# make a mutation word into a noun.
FETCHING = frozenset({"show", "list", "tell", "give", "find", "check", "read", "look"})
_WORD = re.compile(r"[a-z0-9£$%'#]+")
_POSSESSIVE = re.compile(r"'s$")


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_POSSESSIVE.sub("", w) or w for w in _WORD.findall((text or "").lower()))


# --------------------------------------------------------------------- the changes


@dataclass(frozen=True)
class Change:
    """A change a sentence can name, and the capability family that would serve it.

    `capability` is a key in app/capabilities/families.py. Empty means nothing on this Mac
    claims the change at all, which is what makes the request a candidate new action family
    rather than a permission problem.
    """

    key: str
    what: str
    capability: str
    asks: Any                    # compiled pattern; matched against the request as said
    limitation: str = ""         # the stated limitation in app/observability/contract.py, if any


CHANGES: tuple[Change, ...] = (
    # ------------------------------------------------- asked for in §27C, and built since
    # Each names the family that now serves it (round 9, F-03): with no family named, a request for
    # store credit — a live, money-moving write — was reported as a capability nothing claims, and
    # the report proposed building it. The family's own state (READY, MISSING_SCOPE, …) decides.
    Change("order_create", "create an order from nothing", "order_create",
           re.compile(r"\b(?:create|make|raise|start|open|place|put in|set up)\b[^.?!]{0,30}\b(?:a |an |the )?(?:new )?(?:draft )?order\b", re.I)),
    Change("discount_code", "create a discount code", "discount_create",
           re.compile(r"\b(?:discount|promo(?:tion)?|voucher|coupon)\s*code\b|\b(?:create|make|set up|add|generate)\b[^.?!]{0,30}\b(?:discount|promo(?:tion)?|voucher|coupon)\b|\b\d{1,3}\s?%\s*(?:off|discount)\b", re.I)),
    Change("store_credit", "put store credit on a customer", "store_credit",
           re.compile(r"\bstore credit\b|\bgift card\b|\bcredit (?:on|to) (?:the |their |his |her )?(?:account|customer)\b", re.I)),
    Change("abandoned_checkout", "recover an abandoned checkout", "abandoned_checkouts",
           re.compile(r"\babandoned (?:checkout|cart|basket)s?\b", re.I)),
    # ------------------------------------------------- asked for and not built
    Change("price_change", "change a price", "",
           re.compile(r"\b(?:change|set|update|drop|raise|cut)\b[^.?!]{0,20}\bprice\b", re.I),
           limitation="price_change"),
    Change("thread_merge", "merge two email threads", "",
           re.compile(r"\bmerge\b[^.?!]{0,30}\b(?:threads?|emails?|conversations?)\b", re.I),
           limitation="gmail_thread_merge"),
    # ------------------------------------------------- asked for and built (§27, "not fixed" ≠ "still open")
    Change("order_add_item", "add, remove or swap a line on an order", "order_edit",
           re.compile(r"\b(?:add|put|swap|replace|remove|take off|take out)\b[^.?!]{0,60}\b(?:to|from|on|off)\b[^.?!]{0,30}\border\b|\border edit\b|\badd (?:a|an|another|one)\b[^.?!]{0,40}\b(?:to (?:it|this|that|his|her|their))\b", re.I),
           limitation="order_edit"),
    Change("refund", "refund an order", "order_refund",
           re.compile(r"\brefund(?:ed|ing)?\b", re.I)),
    Change("cancel", "cancel an order", "order_cancel",
           re.compile(r"\bcancel(?:led|ling)?\b", re.I)),
    Change("fulfil", "mark an order fulfilled, or set its tracking", "order_fulfil",
           re.compile(r"\b(?:fulfil|fulfill|dispatch|ship it|ship them|ship this|tracking number)\b", re.I)),
    Change("address", "correct a shipping address", "order_address",
           re.compile(r"\b(?:change|correct|fix|update|set)\b[^.?!]{0,30}\baddress\b", re.I)),
    Change("note", "put a note or a tag on an order", "order_notes",
           re.compile(r"\b(?:add|put|leave|write)\b[^.?!]{0,20}\b(?:note|tag)\b|\btag (?:it|this|that|the order)\b", re.I)),
    Change("stock", "set the stock of a variant", "inventory_set",
           re.compile(r"\b(?:set|adjust|correct|change)\b[^.?!]{0,30}\b(?:stock|inventory)\b", re.I)),
    Change("draft", "draft a reply or a new message", "email_drafts",
           re.compile(r"\b(?:draft|write)\b[^.?!]{0,30}\b(?:reply|response|email|message|back)\b|\breply to\b|\bdraft it\b|\bdraft one\b", re.I)),
    Change("send", "send an email", "email_sends",
           re.compile(r"\bsend (?:it|that|the (?:reply|email|draft)|them)\b|\bsend it instead\b|\bactually send\b", re.I)),
    Change("archive", "archive a thread", "email_archive",
           re.compile(r"\barchive\b", re.I)),
)

# What a capability state means for a request that named it. `NO_FAMILY` is this module's
# own: it is what the capability table says by saying nothing.
NO_FAMILY = "NO_FAMILY"


def change_named(text: str) -> Change | None:
    """The change this request names, if it names one. First match wins, and the table is
    ordered so that a change nothing serves is tested before the ones that are built: "create
    a discount code for the refund" is a discount request, not a refund one."""
    said = (text or "").strip()
    if not said:
        return None
    for change in CHANGES:
        if change.asks.search(said):
            return change
    return None


def _load_families() -> Any:
    """The capability table, with every family module imported. A report can be written on a
    machine where a family module will not import; the table is then whatever did."""
    from app.capabilities import families as capability_families

    try:
        from app.families import load_all

        load_all()
    except Exception:  # noqa: BLE001 — a family that will not import is a smaller table, not a crash
        pass
    return capability_families


def capability_state(change: Change, states: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """What this Mac can do about the change, now.

    `states` is `app.capabilities.families.states(runtime)` when the caller has a runtime — the
    live answer, with the store's own scopes in it. Without one the family's declared state is
    used and `probed` says that a probe would have had the last word, so a report never claims
    a scope is granted that it did not check.
    """
    key = change.capability
    if not key:
        return {"family": "", "label": "", "state": NO_FAMILY, "scope": "", "probed": False}
    if states and key in states:
        row = states[key]
        return {"family": key, "label": str(row.get("label") or key), "state": str(row.get("state") or ""),
                "scope": str(row.get("scope") or ""), "probed": True}
    families = _load_families()
    family = families.get(key)
    if family is None:
        return {"family": "", "label": "", "state": NO_FAMILY, "scope": "", "probed": False}
    scope = family.scopes[0] if family.scopes else ""
    return {"family": key, "label": family.label, "state": family.state,
            "scope": scope.rsplit("/", 1)[-1] if "://" in scope else scope, "probed": family.probe is not None}


# --------------------------------------------------------- the noun-versus-verb rule


def nominal_only(text: str) -> str:
    """Every mutation word in this sentence stands as a noun or a state.

    Returns the phrase that decided it, or "" when at least one mutation word is an
    instruction. The words come from the contract's own sets (app/observability/contract.py) —
    imported, never copied — so this rule can only ever say "that word is a noun here"; it can
    never invent a mutation word the contract does not know.
    """
    from app.observability.contract import MUTATION, OPENERS

    asking = OPENERS - FETCHING
    words = _tokens(text)
    if not words:
        return ""
    found = [(i, w) for i, w in enumerate(words) if w in MUTATION]
    if not found:
        return ""
    asked = words[0] in asking
    phrases: list[str] = []
    for i, word in found:
        after = words[i + 1] if i + 1 < len(words) else ""
        before = words[i - 1] if i else ""
        if after in STATE_NOUNS:
            phrases.append(f"{word} {after}")
            continue
        if asked and before in DETERMINERS:
            phrases.append(f"{before} {word}")
            continue
        return ""            # an instruction: the sentence asks for a change after all
    return "; ".join(phrases)


# ------------------------------------------------------------------- the verdict


@dataclass(frozen=True)
class Verdict:
    """What the request was for, and who said so."""

    text: str
    mutation: bool
    mutation_source: str          # "router" | "report"
    family: str                   # the intent family an older router gave it, "" for none
    family_source: str            # "router" | "none"
    reason: str                   # the router's own words, where it left any
    change: Change | None = None
    disagreement: str = ""        # non-empty when this module narrowed the router's reading

    @property
    def unplaced(self) -> bool:
        """No intent family took this request — always so since the word-matching router was
        removed. Kept so a verdict read from an older timeline still says what it said."""
        return not self.family

    def as_dict(self) -> dict[str, Any]:
        return {"mutation": self.mutation, "mutation_source": self.mutation_source,
                "family": self.family or None, "family_source": self.family_source,
                "reason": self.reason or None, "change": self.change.key if self.change else None,
                "disagreement": self.disagreement or None}


def read_request(text: str, *, lane: dict[str, Any] | None = None) -> Verdict:
    """The request, read the way the turn's own router read it when there was one.

    `lane` is the turn's `lane` timeline event, which only a timeline recorded before the
    router was removed has. With one, the mutation verdict and the family are the router's;
    without one the mutation is this report's reading and there is no family.
    """
    said = (text or "").strip()
    signals = (lane or {}).get("signals") if isinstance((lane or {}).get("signals"), dict) else {}
    if lane:
        mutation = bool((signals or {}).get("mutation"))
        mutation_source = "router"
        family = str(lane.get("family") or "")
        family_source = "router" if family else "none"
        reason = str(lane.get("reason") or "")
    else:
        from app.observability.contract import mutating

        mutation = bool(said) and mutating(_tokens(said))
        mutation_source = "report"
        family, family_source, reason = "", "none", ""
    disagreement = ""
    if mutation:
        phrase = nominal_only(said)
        if phrase:
            mutation = False
            disagreement = f"{phrase!r} reads as a change word; here it is a noun, so the turn is graded as a read"
    change = change_named(said) if mutation else None
    return Verdict(text=said, mutation=mutation, mutation_source=mutation_source, family=family,
                   family_source=family_source, reason=reason, change=change, disagreement=disagreement)
