"""What the customer is asking, and what they gave us to find them by.

Deterministic and bounded: a handful of phrases decide the kind of enquiry, and the identifiers
are the ones the rest of the application already trusts (an order-shaped number, an email
address). Nothing here calls a model; a reading a person cannot check is not an investigation.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.context.graph import order_numbers_in

MAX_TEXT = 4000
MAX_ASKS = 4

KINDS = (
    "cancel",
    "change_address",
    "damaged",
    "wrong_item",
    "missing_item",
    "return_exchange",
    "delivery",
    "other",
)

# Checked in this order: the first kind whose phrases appear wins, so a message about a
# damaged item that also asks where the replacement is reads as "damaged".
_PHRASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cancel", ("cancel",)),
    ("change_address", ("change my address", "change the address", "wrong address", "update my address",
                        "update the address", "different address", "new address", "moved house", "address is wrong")),
    ("damaged", ("damaged", "faulty", "ripped", "torn", "broken", "hole in", "stain", "defect")),
    ("wrong_item", ("wrong item", "wrong size", "wrong colour", "wrong color", "sent me the wrong", "not what i ordered",
                    "received the wrong", "got the wrong", "instead of the")),
    ("missing_item", ("missing", "only received", "only got", "wasn't in the parcel", "was not in the parcel",
                      "short of", "one item short", "didn't include", "did not include")),
    ("return_exchange", ("return", "exchange", "refund", "swap", "send it back", "too big", "too small", "doesn't fit",
                         "does not fit", "changed my mind")),
    ("delivery", ("where is my order", "where's my order", "wheres my order", "where is it", "where's it", "where is my parcel",
                  "where's my parcel", "where is the parcel", "not turned up", "hasn't turned up", "no sign of", "not arrived", "hasn't arrived",
                  "has not arrived", "haven't received", "have not received", "not received", "still waiting",
                  "tracking", "dispatched", "shipped", "delivery", "deliver", "when will", "eta", "on its way",
                  "any update", "arrive")),
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Enquiry:
    text: str
    subject: str
    sender_email: str
    kind: str
    order_numbers: tuple[str, ...]
    emails_mentioned: tuple[str, ...]
    asks: tuple[str, ...]

    def as_dict(self) -> dict:
        # JSON-native (lists, not tuples), so a bundle read back from a file is equal to the
        # one that was gathered and the investigation cannot tell the two apart.
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict) -> Enquiry:
        return cls(
            text=str(data.get("text") or ""),
            subject=str(data.get("subject") or ""),
            sender_email=str(data.get("sender_email") or ""),
            kind=str(data.get("kind") or "other"),
            order_numbers=tuple(str(n) for n in data.get("order_numbers") or ()),
            emails_mentioned=tuple(str(e) for e in data.get("emails_mentioned") or ()),
            asks=tuple(str(a) for a in data.get("asks") or ()),
        )


def classify(text: str) -> str:
    lowered = f" {text.lower()} "
    for kind, phrases in _PHRASES:
        if any(phrase in lowered for phrase in phrases):
            return kind
    return "other"


def _asks(text: str) -> tuple[str, ...]:
    """The sentences that ask something, questions first; bounded."""
    sentences = [s.strip() for s in _SENTENCE.split(text) if s and s.strip()]
    questions = [s for s in sentences if s.endswith("?")]
    others = [s for s in sentences if not s.endswith("?")]
    return tuple((questions + others)[:MAX_ASKS])


def parse_enquiry(text: str, *, subject: str = "", sender_email: str = "") -> Enquiry:
    text = str(text or "").strip()[:MAX_TEXT]
    subject = str(subject or "").strip()[:300]
    sender = str(sender_email or "").strip().lower()
    combined = f"{subject}\n{text}"
    numbers = tuple(order_numbers_in(combined))
    mentioned = tuple(dict.fromkeys(m.lower() for m in _EMAIL.findall(combined) if m.lower() != sender))
    return Enquiry(
        text=text,
        subject=subject,
        sender_email=sender,
        kind=classify(combined),
        order_numbers=numbers,
        emails_mentioned=mentioned,
        asks=_asks(text),
    )
