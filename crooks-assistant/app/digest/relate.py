"""Relate what was read out of an artifact to what CLIVE already is.

One Relation per Unit, against the self-model (app/digest/selfmodel.py):

    overlap     CLIVE already has it: an entry CLIVE has now (a tool, an intent family, a
                scene primitive, a builder skill, a shipped or testing feature) scores at or
                above OVERLAP_THRESHOLD
    extends     it adds to something CLIVE has, plans or has thought of: the best entry scores
                at or above EXTENDS_THRESHOLD (or an idea or planned feature scores above the
                overlap threshold, which is an idea getting closer, not something CLIVE has)
    gap         nothing in CLIVE is close: CLIVE lacks it
    reference   nothing in CLIVE is close and the unit is knowledge, a claim or an example —
                something to point at rather than something CLIVE lacks — and a script, which
                is only ever pointed at

The similarity is deterministic and explainable, and no model is asked: names, titles and
bodies are tokenised (lowercased, split on anything not a letter or digit and at camelCase and
snake_case joins, a small stopword list dropped, a light suffix stemmer), weighted by TF-IDF
over the self-model's own entries, and compared by cosine similarity. Each match carries the
terms that made it, so the reason for a relation can be read off it. Work is bounded: each
text is cut to MAX_TEXT_CHARS before it is tokenised and to MAX_TOKENS after."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from app.digest.model import CONTENT_DIGEST_PATTERN, UNIT_ID_PATTERN, UNIT_KINDS, Unit
from app.digest.selfmodel import SelfEntry, SelfModel

RELATIONS = ("overlap", "extends", "gap", "reference")

OVERLAP_THRESHOLD = 0.45   # an entry CLIVE has scores this or more: CLIVE already has it
EXTENDS_THRESHOLD = 0.18   # the best entry scores this or more: it adds to that entry
MIN_SHARED_TERMS = 2       # one word in common is a coincidence, not a relation
TOP_MATCHES = 3
TOP_TERMS = 5              # the shared terms kept to explain a match
MAX_TEXT_CHARS = 8_000     # of a unit's title and body, or an entry's name and description
MAX_TOKENS = 256           # tokens kept from one text, the title's first
MIN_TOKEN = 2
MAX_TOKEN = 40
REFERENCE_WHEN_UNMATCHED = frozenset({"knowledge", "claim", "example"})
ALWAYS_REFERENCE = frozenset({"script"})

STOPWORDS = frozenset("""
a about after all also always an and any are as at be been before being but by can could do
does done each every for from get had has have how if in into is it its itself may more most
must never no not of on one only or other our out over own per same should so some such than
that the their them then there these they this those through to too under up upon use used
using via was we were what when where which while who will with would you your
""".split())

_CAMEL_LOWER_UPPER = re.compile(r"([a-z0-9])([A-Z])")
_CAMEL_ACRONYM = re.compile(r"([A-Z]+)([A-Z][a-z])")
_WORD = re.compile(r"[a-z0-9]+")
_DOUBLED = re.compile(r"([b-df-hj-np-tv-z])\1$")


def _stem(word: str) -> str:
    """A light suffix stemmer: consistent rather than correct, since both sides of every
    comparison pass through it. orders, ordered, ordering -> order; queries -> query."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix, keep in (("ing", 3), ("ed", 3)):
        if word.endswith(suffix) and len(word) - len(suffix) >= keep:
            stem = word[: -len(suffix)]
            doubled = _DOUBLED.search(stem)
            if doubled and doubled.group(1) not in "lsz":
                stem = stem[:-1]
            return stem
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenise(text: str, limit: int = MAX_TOKENS) -> list[str]:
    """Words of text, in order, as the relation compares them. Bounded in both the characters
    looked at and the tokens returned."""
    text = text[:MAX_TEXT_CHARS]
    text = _CAMEL_ACRONYM.sub(r"\1 \2", _CAMEL_LOWER_UPPER.sub(r"\1 \2", text)).lower()
    out: list[str] = []
    for word in _WORD.findall(text):
        if len(word) < MIN_TOKEN or len(word) > MAX_TOKEN or word.isdigit() or word in STOPWORDS:
            continue
        stem = _stem(word)
        if stem in STOPWORDS or len(stem) < MIN_TOKEN:
            continue
        out.append(stem)
        if len(out) >= limit:
            break
    return out


def _terms(name: str, text: str) -> list[str]:
    """A name or title counts twice: it is what the thing is called."""
    head = tokenise(name, MAX_TOKENS // 4)
    return head + head + tokenise(text, MAX_TOKENS - 2 * len(head))


def _unit_terms(unit: Unit) -> list[str]:
    return _terms(unit.title, unit.body)


def _entry_terms(entry: SelfEntry) -> list[str]:
    return _terms(entry.name, entry.description)


def _weights(terms: Iterable[str], idf: dict[str, float], unseen: float) -> dict[str, float]:
    counts = Counter(terms)
    return {term: (1.0 + math.log(n)) * idf.get(term, unseen) for term, n in sorted(counts.items())}


def _norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(weight * weight for weight in vector.values()))


@dataclass(frozen=True)
class Match:
    """One self-model entry a unit resembles, how much, and the shared terms that weigh most."""

    key: str
    kind: str
    name: str
    score: float
    present: bool
    terms: tuple[str, ...] = ()
    shared: int = 0          # how many distinct terms the unit and the entry share

    @property
    def counts(self) -> bool:
        """Whether this match may carry a relation: it shares enough terms to be more than a
        coincidence of one word."""
        return self.shared >= MIN_SHARED_TERMS

    def to_dict(self) -> dict:
        return {"key": self.key, "kind": self.kind, "name": self.name, "score": self.score,
                "present": self.present, "terms": list(self.terms), "shared": self.shared}


@dataclass(frozen=True)
class Relation:
    """How one Unit relates to CLIVE. `score` is the score of the entry the relation rests on
    (`basis`), or, when it rests on none, of the closest entry sharing at least
    MIN_SHARED_TERMS terms (0 when there is none); `matches` are the best three by score, with
    the basis always among them."""

    unit_id: str
    unit_kind: str
    relation: str
    score: float
    matches: tuple[Match, ...]
    basis: str | None
    self_model: str          # the digest of the self-model it was made against

    def __post_init__(self) -> None:
        if not isinstance(self.unit_id, str) or not re.fullmatch(UNIT_ID_PATTERN, self.unit_id):
            raise ValueError(f"not a unit id: {self.unit_id!r}")
        if self.unit_kind not in UNIT_KINDS:
            raise ValueError(f"unit kind must be one of {UNIT_KINDS}, not {self.unit_kind!r}")
        if self.relation not in RELATIONS:
            raise ValueError(f"relation must be one of {RELATIONS}, not {self.relation!r}")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")
        if not isinstance(self.self_model, str) or not re.fullmatch(CONTENT_DIGEST_PATTERN, self.self_model):
            raise ValueError(f"a relation cites its self-model's digest, not {self.self_model!r}")
        object.__setattr__(self, "matches", tuple(self.matches))
        if len(self.matches) > TOP_MATCHES:
            raise ValueError(f"at most {TOP_MATCHES} matches")
        if (self.relation in ("overlap", "extends")) != (self.basis is not None):
            raise ValueError("an overlap or an extension rests on an entry; nothing else does")
        if self.basis is not None and self.basis not in {m.key for m in self.matches}:
            raise ValueError("the basis of a relation must be one of its matches")

    @property
    def best(self) -> Match | None:
        return self.matches[0] if self.matches else None

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "unit_kind": self.unit_kind,
            "relation": self.relation,
            "score": self.score,
            "matches": [match.to_dict() for match in self.matches],
            "basis": self.basis,
            "self_model": self.self_model,
        }


class _Index:
    """TF-IDF vectors of the self-model's entries, with an inverted index to score against."""

    def __init__(self, model: SelfModel) -> None:
        self.entries = model.entries
        self.digest = model.digest
        terms = [_entry_terms(entry) for entry in self.entries]
        total = len(self.entries)
        frequency: Counter[str] = Counter()
        for entry_terms in terms:
            frequency.update(set(entry_terms))
        self.idf = {t: math.log((1 + total) / (1 + n)) + 1.0 for t, n in sorted(frequency.items())}
        self.unseen = math.log(1 + total) + 1.0
        self.vectors = [_weights(entry_terms, self.idf, self.unseen) for entry_terms in terms]
        self.norms = [_norm(vector) for vector in self.vectors]
        self.postings: dict[str, list[int]] = {}
        for index, vector in enumerate(self.vectors):
            for term in vector:
                self.postings.setdefault(term, []).append(index)

    def matches(self, unit: Unit) -> list[Match]:
        vector = _weights(_unit_terms(unit), self.idf, self.unseen)
        norm = _norm(vector)
        if not norm:
            return []
        dots: dict[int, float] = {}
        shared: dict[int, list[tuple[float, str]]] = {}
        for term, weight in vector.items():
            for index in self.postings.get(term, ()):
                part = weight * self.vectors[index][term]
                dots[index] = dots.get(index, 0.0) + part
                shared.setdefault(index, []).append((part, term))
        scored = []
        for index, dot in dots.items():
            if not self.norms[index]:
                continue
            score = round(min(1.0, dot / (norm * self.norms[index])), 4)
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], self.entries[item[1]].key))
        out = []
        for score, index in scored:
            entry = self.entries[index]
            terms = sorted(shared[index], key=lambda item: (-item[0], item[1]))[:TOP_TERMS]
            out.append(Match(entry.key, entry.kind, entry.name, score, entry.present,
                             tuple(term for _part, term in terms), len(shared[index])))
        return out


def _relation(unit: Unit, ranked: list[Match], digest: str) -> Relation:
    top = tuple(ranked[:TOP_MATCHES])
    counted = [match for match in ranked if match.counts]
    nearest = counted[0].score if counted else 0.0
    if unit.kind in ALWAYS_REFERENCE:
        return Relation(unit.id, unit.kind, "reference", nearest, top, None, digest)
    have = next((match for match in counted if match.present), None)
    if have is not None and have.score >= OVERLAP_THRESHOLD:
        return Relation(unit.id, unit.kind, "overlap", have.score, _showing(top, have),
                        have.key, digest)
    best = counted[0] if counted else None
    if best is not None and best.score >= EXTENDS_THRESHOLD:
        return Relation(unit.id, unit.kind, "extends", best.score, _showing(top, best),
                        best.key, digest)
    kind = "reference" if unit.kind in REFERENCE_WHEN_UNMATCHED else "gap"
    return Relation(unit.id, unit.kind, kind, nearest, top, None, digest)


def _showing(top: tuple[Match, ...], basis: Match) -> tuple[Match, ...]:
    """The best matches, with the one a relation rests on always among them — last, when a
    closer match was set aside for sharing only one term."""
    return top if basis in top else (*top[: TOP_MATCHES - 1], basis)


def relate(units: Iterable[Unit], self_model: SelfModel) -> list[Relation]:
    """One Relation per Unit, in the order given."""
    if not isinstance(self_model, SelfModel):
        raise ValueError("relate needs CLIVE's self-model")
    index = _Index(self_model)
    out = []
    for unit in units:
        if not isinstance(unit, Unit):
            raise ValueError("relate takes Unit records")
        out.append(_relation(unit, index.matches(unit), index.digest))
    return out
