"""Where a quote the model gave sits in the research, as the research itself wrote it.

Why this exists: every claim CLIVE keeps from research must be something the research says (DEC-078).
The model copies a passage; PDFs, lists and typography make an honest copy differ from the document
in ways that are not the model's fault. `find_quote` looks harder than an exact match, in order, and
says how it found the passage, or why it could not:

  1. the two texts as review.normalise makes them (case, marks, list markers, broken words aside);
  2. letters and digits only, first with list markers taken out of both, then as written;
  3. a near match: the quote's start, then its end, in order, the whole within 1.3 times its length.

What it promises:
- The span is a (start, end) in the document's own text, so what is kept is the document's words,
  never the model's copy of them.
- A quote too short to mean anything is never found.
"""

from __future__ import annotations

import re

from app.research.review import MIN_QUOTE, normalise

NEAR_STRETCH = 1.3
NEAR_SHRINK = 0.7
_MARKERS = (re.compile(r"(?m)^[ \t]*(?:[-+•]|\d{1,3}[.)])[ \t]+"),
            re.compile(r"(?<=[.!?:;])\s+\d{1,3}[.)]\s+"))
_CLOSERS = ".,;:!?)\"'’”"

FOUND = "found as written"
FOUND_LETTERS = "found by its letters and digits"
FOUND_NEAR = "found by its start and end"
NOTHING = "it quoted nothing from the research"
MISSING = "its quote isn't in the research"


class _Projection:
    """The document's letters and digits, lower case, each with where it sits in the document."""

    def __init__(self, text: str, *, strip: bool) -> None:
        skip = _marker_positions(text) if strip else set()
        letters, positions = [], []
        for i, ch in enumerate(text):
            if i in skip or not ch.isalnum():
                continue
            letters.append(ch.lower()[:1])
            positions.append(i)
        self.letters = "".join(letters)
        self.positions = positions

    def span(self, start: int, length: int) -> tuple[int, int]:
        return self.positions[start], self.positions[start + length - 1] + 1


def _marker_positions(text: str) -> set[int]:
    out: set[int] = set()
    for pattern in _MARKERS:
        for match in pattern.finditer(text):
            out.update(range(match.start(), match.end()))
    return out


def _letters(text: str, *, strip: bool) -> str:
    return _Projection(text, strip=strip).letters


def _extend(document: str, span: tuple[int, int]) -> tuple[int, int]:
    """Take in the closing punctuation right after the passage, as a reader would quote it."""
    start, end = span
    while end < len(document) and end - span[1] < 2 and document[end] in _CLOSERS:
        end += 1
    return start, end


def _locate(projection: _Projection, key: str) -> tuple[int, int] | None:
    if not key:
        return None
    at = projection.letters.find(key)
    return projection.span(at, len(key)) if at >= 0 else None


def _near(projection: _Projection, key: str) -> tuple[int, int] | None:
    n = len(key)
    if n < 24:
        return None
    k = max(12, min(40, n // 4))
    head, tail = key[:k], key[-k:]
    letters = projection.letters
    at = letters.find(head)
    while at >= 0:
        end = letters.find(tail, at + k, at + int(n * NEAR_STRETCH) + 1)
        if end >= 0 and (end + k - at) >= n * NEAR_SHRINK:
            return projection.span(at, end + k - at)
        at = letters.find(head, at + 1)
    return None


def find_quote(document: str, quote: str) -> tuple[tuple[int, int] | None, str]:
    """(span in `document`, how it was found), or (None, why not)."""
    document, quote = str(document or ""), str(quote or "").strip()
    if len(normalise(quote)) < MIN_QUOTE:
        return None, NOTHING
    stripped, as_written = _Projection(document, strip=True), _Projection(document, strip=False)
    key_stripped, key_written = _letters(quote, strip=True), _letters(quote, strip=False)
    if normalise(quote) in normalise(document):
        span = _locate(stripped, key_stripped) or _locate(as_written, key_written)
        if span:
            return _extend(document, span), FOUND
    for projection, key in ((stripped, key_stripped), (as_written, key_written)):
        span = _locate(projection, key)
        if span:
            return _extend(document, span), FOUND_LETTERS
    span = _near(as_written, key_written) or _near(stripped, key_stripped)
    if span:
        return _extend(document, span), FOUND_NEAR
    return None, MISSING


def passage(document: str, span: tuple[int, int], limit: int = 400) -> str:
    """The document's own words for a span, spacing made plain, at most `limit` characters."""
    text = re.sub(r"\s+", " ", document[span[0]:span[1]]).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
