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
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_SOFT_BREAK = re.compile(r"(?<!\n)[ \t]*\n(?!\n)")
# Where the customer's own words stop and quoted or forwarded mail begins.
_QUOTE_START = re.compile(r"^On .{0,300}?wrote:|^>|^-{2,}\s*(?:Original Message|Forwarded message)|^From: ", re.M | re.S)
_QUOTE_PREFIX = re.compile(r"^>[ \t]?", re.M)
_GREETING = re.compile(r"^(hi|hello|hey|dear|good (morning|afternoon|evening)|thanks|thank you|many thanks|cheers|kind regards|regards|best|sent from my)\b", re.I)
_ASK_CUES = ("could you", "can you", "please", "let me know", "when ", "where ", "why ", "how ", "what ", "any update", "wondering if")
MIN_ASK = 12
# An order-shaped number is only an order number when the text treats it as one: a phone
# number's groups and a year are the same shape, and were read as orders in a real case.
_ORDER_CUE = re.compile(r"(?:order|#|crooks[\s-]*|\bno\.?|\bnumber|\bref)\s*[:#]?\s*$", re.I)
_PHONE_BEFORE = re.compile(r"(?:\+\d{1,3}|\d{3,})[ .-]$|(?:tel|phone|call|mobile|mob)\b[^\n]{0,12}$", re.I)
_PHONE_AFTER = re.compile(r"^[ .-]\d{3,}")
_YEAR = re.compile(r"^(?:19|20)\d\d$")
# A year is only a year in a date: "19 Sep 2026", "Sep 2026", "2026-09-11". The store's order
# numbers run through the same range, so a bare four-digit number stays an order number.
_DATE_BEFORE = re.compile(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?$", re.I)
_DATE_AFTER = re.compile(r"^[-/]\d{1,2}[-/]\d{1,2}")


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


def unquoted(text: str) -> str:
    """The customer's own words: everything above the first quoted reply or forwarded mail."""
    found = _QUOTE_START.search(text)
    return text[:found.start()].strip() if found else text.strip()


def _quoted_by_sender(text: str, sender: str) -> str:
    """What the customer quoted of their own earlier message, when the quote header names
    their address; anything they quoted of ours is not their ask."""
    if not sender:
        return ""
    header = re.search(rf"On .{{0,300}}?{re.escape(sender)}.{{0,60}}?wrote:", text, re.S | re.I)
    if not header:
        return ""
    quoted = _QUOTE_PREFIX.sub("", text[header.end():])
    return unquoted(quoted)


def _sentences(text: str) -> list[str]:
    joined = _SOFT_BREAK.sub(" ", text)
    out = []
    for s in _SENTENCE.split(joined):
        s = (s or "").strip()
        if len(s) < MIN_ASK or _GREETING.match(s):
            continue
        letters = sum(c.isalpha() for c in s)
        digits = sum(c.isdigit() for c in s)
        if digits > letters:
            continue
        out.append(s)
    return out


def _ranked(sentences: list[str]) -> list[str]:
    questions = [s for s in sentences if s.endswith("?")]
    cued = [s for s in sentences if s not in questions and any(c in s.lower() for c in _ASK_CUES)]
    rest = [s for s in sentences if s not in questions and s not in cued]
    return questions + cued + rest


def _asks(text: str, sender: str = "") -> tuple[str, ...]:
    """The sentences that ask something: questions, then sentences with an asking cue, then
    the rest; from the customer's own words first, then what they quoted of themselves."""
    own = _sentences(unquoted(text) or text)
    if len(own) < 2:
        own += [s for s in _sentences(_quoted_by_sender(text, sender)) if s not in own]
    return tuple(_ranked(own)[:MAX_ASKS])


def _order_numbers(combined: str) -> tuple[str, ...]:
    """The order-shaped numbers the text treats as order numbers: cued ones first; a
    phone-number group or a bare year is not one."""
    cued: list[str] = []
    plain: list[str] = []
    for number in order_numbers_in(combined):
        occurrences = [m for m in re.finditer(rf"(?<!\d){re.escape(number)}(?!\d)", combined)]
        before = [combined[max(0, m.start() - 16):m.start()] for m in occurrences]
        after = [combined[m.end():m.end() + 8] for m in occurrences]
        if any(_ORDER_CUE.search(b) for b in before):
            cued.append(number)
        elif any(_PHONE_BEFORE.search(b) or _PHONE_AFTER.match(a) for b, a in zip(before, after, strict=True)):
            continue
        elif _YEAR.match(number) and any(_DATE_BEFORE.search(b) or _DATE_AFTER.match(a) for b, a in zip(before, after, strict=True)):
            continue
        else:
            plain.append(number)
    return tuple(dict.fromkeys(cued + plain))


def parse_enquiry(text: str, *, subject: str = "", sender_email: str = "") -> Enquiry:
    text = str(text or "").strip()[:MAX_TEXT]
    subject = str(subject or "").strip()[:300]
    sender = str(sender_email or "").strip().lower()
    combined = f"{subject}\n{text}"
    mentioned = tuple(dict.fromkeys(m.lower() for m in _EMAIL.findall(combined) if m.lower() != sender))
    return Enquiry(
        text=text,
        subject=subject,
        sender_email=sender,
        kind=classify(combined),
        order_numbers=_order_numbers(combined),
        emails_mentioned=mentioned,
        asks=_asks(text, sender),
    )
