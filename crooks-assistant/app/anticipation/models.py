"""What a signal is, what a prediction is, and the two words that keep them apart.

One vocabulary, used by the rules (level 1), the learner (level 2) and the engine:

    Signal      something the OWNER did — an order opened, an inbox read, a cursor moved
    Prediction  one read the Mac believes is worth making before it is asked for

The distinction that matters everywhere downstream is `origin`. A read the model asked for or
the owner tapped for is REQUESTED; a read this layer decided to make is PREDICTED. It is not a
second record: it travels on the `ReadPlan` the scheduler already runs (`origin` on the
`read_plan` timeline event) and on the memory entry's provenance, which `Entry.public()`
already hands out. So "why is this on screen" is answerable from the record that was already
there rather than from a parallel one kept by this package.

A signal's STATE — what the learner records — carries no identifiers at all: an event name and
a handful of allow-listed feature words. The ids a prediction needs in order to actually read
something live on the signal, in memory, for the length of one turn, and are never learned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The two tiers of anticipation, in the brief's own words (§18).
P1 = "p1"          # safe background: what the record on screen is about
P2 = "p2"          # speculative: where the owner is likely to go next
TIERS = (P1, P2)

# The two origins a read can have. The word the timeline and the memory provenance carry.
REQUESTED = "requested"
PREDICTED = "predicted"

# The three levels (§18). A prediction says which one it came from so the debug view can too.
LEVEL_RULE = 1        # deterministic
LEVEL_LEARNED = 2     # a transition probability from real use
LEVEL_SUGGESTION = 3  # high confidence, offered to the owner, never acted on as a write

# The only feature words a signal's state may carry. An allow-list rather than a filter: what
# is learned is a shape of order, not an order — "unfulfilled and three weeks old and going
# abroad", never which one. Anything else a caller passes is dropped before it is recorded.
FEATURES = frozenset({
    "unfulfilled", "fulfilled", "partial", "cancelled", "refunded",
    "international", "domestic", "old", "recent", "high_value",
    "inbound_unanswered", "has_email", "no_email", "in_set", "tracked", "untracked",
})

# The events this layer knows how to record and predict from. A vocabulary, so a caller cannot
# grow the learned table one typo at a time.
EVENTS = frozenset({
    "order_opened", "customer_opened", "email_checked", "tracking_checked",
    "history_checked", "reply_drafted", "next_record", "previous_record", "tab_opened",
})


def clean_state(event: str, features: tuple[str, ...] | list[str] = ()) -> str:
    """The learnable state of a signal: an event and its allow-listed features, sorted.

    This is the privacy boundary of §19 and it is enforced here rather than trusted: an event
    outside `EVENTS` is refused, a feature outside `FEATURES` is dropped, and anything with a
    digit, an at-sign or a slash in it cannot survive either check. So an id, an address or a
    customer's name has no path into the learned table even from a careless caller.
    """
    name = str(event or "").strip().lower()
    if name not in EVENTS:
        raise ValueError(f"{event!r} is not one of the events this layer records")
    tags = sorted({str(f).strip().lower() for f in features} & FEATURES)
    return f"{name}[{','.join(tags)}]" if tags else name


@dataclass(frozen=True)
class Signal:
    """Something the owner did, as this layer sees it."""

    event: str
    session_id: str
    branch_id: str = ""
    # Who: the login the request came from. Part of the isolation key, never learned.
    login: str = ""
    kind: str = ""                                  # "order" | "customer" | "email_thread"
    ref: str = ""                                   # that record's id
    features: tuple[str, ...] = ()
    # The ids a prediction needs to read something. In memory for the length of a turn; not
    # written to the learned table, and on the timeline only as ids (which it already carries).
    ids: dict[str, str] = field(default_factory=dict)
    # The neighbours of the record on screen, when a working set is open.
    neighbours: tuple[str, ...] = ()

    @property
    def scope(self) -> str:
        """The isolation key. Two logins, or two conversations, never share anticipated work
        or a cancellation — one owner's speculative read must not be cancelled by another's
        question, and must never be served to them."""
        return f"{self.login or 'owner'}|{self.session_id}"

    @property
    def state(self) -> str:
        return clean_state(self.event, self.features)


@dataclass(frozen=True)
class Prediction:
    """One read worth making before it is asked for."""

    key: str                                        # the identity of the read, for dedupe
    tier: str                                       # P1 | P2
    tool: str = ""                                  # a registered READ tool, or ""
    args: dict[str, Any] = field(default_factory=dict)
    source: str = "shopify"                         # shopify | gmail | mac
    why: str = ""                                   # the rule id, or "learned:<state>-><event>"
    level: int = LEVEL_RULE
    confidence: float = 1.0
    observations: int = 0
    # An internal read that is not a model-facing tool, resolved by app/anticipation/internal.py,
    # which is read-only by construction (and empty since the shipping boundary went, DEC-071).
    internal: str = ""
    # (tier, key) in the tiered cache. A prediction whose answer is already fresh there does
    # not run, and its result is put back there for the requested read to find.
    memory: tuple[str, str] | None = None

    @property
    def speculative(self) -> bool:
        return self.tier == P2
