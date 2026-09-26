"""Relate what was read out of an artifact to what CLIVE already is.

One Relation per Unit, against the self-model (app/digest/selfmodel.py):

    overlap     CLIVE already has it: the unit names an entry CLIVE has (see below), or an
                entry CLIVE has now (a tool, an intent family, a scene primitive, a builder
                skill, a shipped or testing feature) scores at or above OVERLAP_THRESHOLD
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
text is cut to MAX_TEXT_CHARS before it is tokenised and to MAX_TOKENS after. The units of one
artifact are related together, and a term in more than COMMON_SHARE of them (in an artifact of
at least COMMON_MIN_UNITS) is the artifact's own vocabulary and not evidence of anything.

Similar words are not the only evidence. A unit that names something CLIVE has, exactly,
overlaps it whatever the words around the name score: its title holds the name of a tool, an
intent family, a scene primitive or a builder skill as a whole identifier — a compound name,
like shopify_find_order or web-design-guidelines, never a single word like "answer" — or it
was read out of a builder skill of that name (the skills adapter tags it skill:<name>, and
any adapter's unit from <name>/SKILL.md is in that skill's folder). Without this,
the function shopify_find_order scored a whisker closer to the tool shopify_find_customer, whose
description shares more of its words, than to the tool it is.

The artifact as a whole is evidence too. Its own vocabulary is left out of each unit's
comparison, but that vocabulary is what the artifact is about: when it matches something
CLIVE has strongly (at least OVERLAP_THRESHOLD, on enough shared terms), a rule, check,
procedure or other actionable unit with no evidence of its own extends that entry, and its
match says it rests on the artifact (`context`). Vercel's interface guidelines are about
exactly what CLIVE's web-design-guidelines skill reviews against; each guideline extends it.

Pointed at CLIVE itself, relate_self also traces every unit to the feature, idea or decision
it serves (the why-index of CLIVE_SELF_KNOWLEDGE.md) and says where code and product memory
have drifted apart: code that traces to nothing in memory, shipped features no code traces
to, plans that already have code, and the strongest links from a decision to the code that
carries it out."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.digest.model import CONTENT_DIGEST_PATTERN, UNIT_ID_PATTERN, UNIT_KINDS, Unit
from app.digest.selfmodel import MEMORY_KINDS, SelfEntry, SelfModel

RELATIONS = ("overlap", "extends", "gap", "reference")

OVERLAP_THRESHOLD = 0.45   # an entry CLIVE has scores this or more: CLIVE already has it
EXTENDS_THRESHOLD = 0.25   # the best entry scores this or more: it adds to that entry
# Evidence: the unit names the entry, or shares at least MIN_SHARED_TERMS distinct terms with
# it, or exactly PAIR_SHARED_TERMS with a score of at least PAIR_THRESHOLD. Tuned on five real
# artifacts (DIGESTIONS_2026-09-26.md): two shared words below that score were coincidences
# nine times in ten ("keep" and "app" extending a decision on objective ids).
MIN_SHARED_TERMS = 3
PAIR_SHARED_TERMS = 2
PAIR_THRESHOLD = 0.35
COMMON_SHARE = 0.2         # a term in more than this share of an artifact's own units ...
COMMON_MIN_UNITS = 50      # ... of at least this many is the artifact's vocabulary, not evidence
TOP_MATCHES = 3
TOP_TERMS = 5              # the shared terms kept to explain a match
MAX_TEXT_CHARS = 8_000     # of a unit's title and body, or an entry's name and description
MAX_TOKENS = 256           # tokens kept from one text, the title's first
MIN_TOKEN = 2
MAX_TOKEN = 40
REFERENCE_WHEN_UNMATCHED = frozenset({"knowledge", "claim", "example"})
ALWAYS_REFERENCE = frozenset({"script"})
NAMED_KINDS = frozenset({"tool", "intent_family", "scene_primitive", "builder_skill", "review_check"})
# The artifact's vocabulary, matched as a whole: the terms of it kept, and the kinds of unit
# that may rest on it when they have no evidence of their own.
CONTEXT_TERMS = 12
CONTEXT_KINDS = frozenset({"procedure", "rule", "check", "capability", "interface", "pattern",
                           "design_token"})
# Units that are code (read from source, not from prose), for the drift of self mode.
CODE_KINDS = frozenset({"capability", "pattern", "check", "interface", "design_token", "script"})
PROSE_SUFFIXES = (".md", ".mdx", ".markdown", ".rst", ".txt", ".adoc", ".html", ".htm")
MAX_DRIFT = 15              # rows in each list of drift and links
SKILL_TAG = "skill:"       # the skills adapter's tag for the skill a unit was read from
SKILL_FILE = "SKILL.md"    # a skill's file, in a folder named for the skill

STOPWORDS = frozenset("""
a about after all also always an and any are as at be been before being but by can could do
does done each every for from get had has have how if in into is it its itself may more most
must never no not of on one only or other our out over own per same should so some such than
that the their them then there these they this those through to too under up upon use used
using via was we were what when where which while who will with would you your
""".split()) | frozenset("""
able above across actually again against ago ahead almost along already although among
another anyone anything anyway around away became because become becomes behind below best
better between beyond both bring came certain clear clearly come comes consider day days
different don doesn isn aren won ll ve re me my us easy either else enough especially even ever
everything exactly far few fine first following follow found full fully give given go goes
going gone good great half hard help here high however important instead just keep kind know
large last later least left less let like likely little long look lot lots low made main make
makes making many matter maybe mean means might much need needed needs next nothing now often
ok okay once others otherwise part particular perhaps place plain point possible pre probably
put quite rather really right said say see seem seems set several side simple since small
something sometimes soon start still sure take takes taken tell thing things think though thus
together took toward try trying two three unless until usually various very want wants way ways
well whatever whether whole why within without yes yet
""".split())
# Generic English words: rare in CLIVE's own entries, so the entries' IDF would weigh them as
# if they said something, and they matched units to entries by coincidence ("just", "unless",
# "still", "don't"). Words that name something in CLIVE (order, run, open, find, new, back,
# number, check, test) are not among them.

# A compound name — words joined by "_" or "-" — and every whole identifier in a title, each
# run as long as it goes, so shopify_find_order_extra does not name shopify_find_order.
_COMPOUND = re.compile(r"[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)+")
_IDENTIFIER = re.compile(r"[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)*")
_CAMEL_LOWER_UPPER = re.compile(r"([a-z0-9])([A-Z])")
# Between the last capital of an acronym and the word after it: HTTPServer -> HTTP Server.
# Zero-width and looking one character each way, so a run of capitals costs one pass; the
# ([A-Z]+)([A-Z][a-z]) it replaces backtracked over the whole run from every capital in it.
_CAMEL_ACRONYM = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_RUN = re.compile(r"[A-Za-z0-9]+")
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


def tokenise(text: str, limit: int = MAX_TOKENS,
             joins: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """Words of text, in order, as the relation compares them. Bounded in both the characters
    looked at and the tokens returned. A word in mixed case is kept whole as well as split at
    its joins, so GitHub is "github" as a path spells it, and "git" and "hub" as an identifier
    GitHubBridge does; `joins`, when given, records each such whole term's parts, so that one
    word is counted once as evidence (see _words)."""
    out: list[str] = []
    for run in _RUN.findall(text[:MAX_TEXT_CHARS]):
        whole = _keep(run.lower())
        parts: list[str] = []
        if run != run.lower() and not run.isupper() and len(run) <= 3 * MAX_TOKEN:
            split = _CAMEL_ACRONYM.sub(" ", _CAMEL_LOWER_UPPER.sub(r"\1 \2", run)).lower().split()
            if len(split) > 1:
                parts = [term for term in map(_keep, split) if term and term != whole]
        if whole and parts and joins is not None:
            joins.setdefault(whole, tuple(parts))
        for term in ([whole] if whole else []) + parts:
            out.append(term)
            if len(out) >= limit:
                return out
    return out


def _keep(word: str) -> str:
    """The word's stem, or "" when it is too short, too long, a number or a stopword."""
    if len(word) < MIN_TOKEN or len(word) > MAX_TOKEN or word.isdigit() or word in STOPWORDS:
        return ""
    stem = _stem(word)
    return "" if stem in STOPWORDS or len(stem) < MIN_TOKEN else stem


def _words(terms: Iterable[str], *joins: dict[str, tuple[str, ...]]) -> int:
    """How many words the terms are: a mixed-case word's whole term and its parts are one."""
    found = set(terms)
    parts = set()
    for term in found:
        for join in joins:
            if term in join:
                parts.update(part for part in join[term] if part in found)
                break
    return max(len(found) - len(parts), 1 if found else 0)


def _terms(name: str, text: str, joins: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """A name or title counts twice: it is what the thing is called."""
    head = tokenise(name, MAX_TOKENS // 4, joins)
    return head + head + tokenise(text, MAX_TOKENS - 2 * len(head), joins)


def _unit_terms(unit: Unit, joins: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    return _terms(unit.title, unit.body, joins)


def _entry_terms(entry: SelfEntry, joins: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    return _terms(entry.name, entry.description, joins)


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
    shared: int = 0          # how many distinct words the unit and the entry share
    named: bool = False      # the unit names this entry exactly
    context: bool = False    # the match is the artifact's as a whole, not the unit's own

    @property
    def counts(self) -> bool:
        """Whether this match may carry a relation: the unit names the entry, or shares enough
        distinct words with it — or two, scoring high — to be more than a coincidence."""
        return (self.named or self.shared >= MIN_SHARED_TERMS
                or (self.shared >= PAIR_SHARED_TERMS and self.score >= PAIR_THRESHOLD))

    def to_dict(self) -> dict:
        return {"key": self.key, "kind": self.kind, "name": self.name, "score": self.score,
                "present": self.present, "terms": list(self.terms), "shared": self.shared,
                "named": self.named, "context": self.context}


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
        self.joins: list[dict[str, tuple[str, ...]]] = [{} for _entry in self.entries]
        terms = [_entry_terms(entry, joins) for entry, joins in zip(self.entries, self.joins,
                                                                     strict=True)]
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
        # entries a unit can name: present, and called by a compound identifier; and every
        # builder skill, by the name of the skill a unit was read from
        self.by_name: dict[str, list[int]] = {}
        self.skills: dict[str, list[int]] = {}
        for index, entry in enumerate(self.entries):
            if entry.kind in NAMED_KINDS and entry.present and _COMPOUND.fullmatch(entry.name):
                self.by_name.setdefault(entry.name, []).append(index)
            if entry.kind == "builder_skill":
                self.skills.setdefault(entry.name, []).append(index)

    def named(self, unit: Unit) -> set[int]:
        """The entries the unit names: by a whole identifier in its title, or as the skill it
        was read from — its skill:<name> tag, or the folder of the SKILL.md it is in."""
        found: set[int] = set()
        for identifier in _IDENTIFIER.findall(unit.title[:MAX_TEXT_CHARS]):
            found.update(self.by_name.get(identifier, ()))
        skills = {tag[len(SKILL_TAG):] for tag in unit.tags if tag.startswith(SKILL_TAG)}
        path = PurePosixPath(unit.location.path)
        if path.name == SKILL_FILE and path.parent.name:
            skills.add(path.parent.name)
        for skill in skills:
            found.update(self.skills.get(skill, ()))
        return found

    def matches(self, unit: Unit, terms: list[str] | None = None,
                ignore: frozenset[str] = frozenset(),
                joins: dict[str, tuple[str, ...]] | None = None) -> list[Match]:
        named = self.named(unit)
        if terms is None:
            joins = {}
            terms = _unit_terms(unit, joins)
        joins = joins or {}
        vector = _weights([term for term in terms if term not in ignore], self.idf, self.unseen)
        norm = _norm(vector)
        if not norm and not named:
            return []
        dots: dict[int, float] = {index: 0.0 for index in named}
        shared: dict[int, list[tuple[float, str]]] = {}
        for term, weight in vector.items():
            for index in self.postings.get(term, ()):
                part = weight * self.vectors[index][term]
                dots[index] = dots.get(index, 0.0) + part
                shared.setdefault(index, []).append((part, term))
        scored = []
        for index, dot in dots.items():
            score = (round(min(1.0, dot / (norm * self.norms[index])), 4)
                     if norm and self.norms[index] else 0.0)
            if score > 0 or index in named:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], self.entries[item[1]].key))
        out = []
        for score, index in scored:
            entry = self.entries[index]
            terms = sorted(shared.get(index, ()), key=lambda item: (-item[0], item[1]))[:TOP_TERMS]
            words = _words((term for _part, term in shared.get(index, ())), joins,
                           self.joins[index])
            out.append(Match(entry.key, entry.kind, entry.name, score, entry.present,
                             tuple(term for _part, term in terms), words, index in named))
        return out


def _relation(unit: Unit, ranked: list[Match], digest: str,
              context: Match | None = None) -> Relation:
    top = tuple(ranked[:TOP_MATCHES])
    counted = [match for match in ranked if match.counts]
    nearest = counted[0].score if counted else 0.0
    if unit.kind in ALWAYS_REFERENCE:
        return Relation(unit.id, unit.kind, "reference", nearest, top, None, digest)
    named = next((match for match in ranked if match.named and match.present), None)
    if named is not None:
        return Relation(unit.id, unit.kind, "overlap", named.score, _showing(top, named),
                        named.key, digest)
    have = next((match for match in counted if match.present), None)
    if have is not None and have.score >= OVERLAP_THRESHOLD:
        return Relation(unit.id, unit.kind, "overlap", have.score, _showing(top, have),
                        have.key, digest)
    best = counted[0] if counted else None
    if best is not None and best.score >= EXTENDS_THRESHOLD:
        return Relation(unit.id, unit.kind, "extends", best.score, _showing(top, best),
                        best.key, digest)
    if context is not None and unit.kind in CONTEXT_KINDS:
        own = tuple(match for match in top if match.key != context.key)
        return Relation(unit.id, unit.kind, "extends", context.score,
                        (*own[: TOP_MATCHES - 1], context), context.key, digest)
    kind = "reference" if unit.kind in REFERENCE_WHEN_UNMATCHED else "gap"
    return Relation(unit.id, unit.kind, kind, nearest, top, None, digest)


def _showing(top: tuple[Match, ...], basis: Match) -> tuple[Match, ...]:
    """The best matches, with the one a relation rests on always among them — last, when a
    closer match was set aside for sharing only one term."""
    return top if basis in top else (*top[: TOP_MATCHES - 1], basis)


def relate(units: Iterable[Unit], self_model: SelfModel) -> list[Relation]:
    """One Relation per Unit, in the order given. The units are related together: in an
    artifact of at least COMMON_MIN_UNITS units, a term found in more than COMMON_SHARE of them
    is the artifact's own vocabulary — its name, its package path, the word every page of it
    uses — and is left out of every comparison (see common_terms); and that vocabulary, matched
    as a whole, may be what an actionable unit with no evidence of its own extends."""
    return _relate(units, self_model)[0]


def relate_self(units: Iterable[Unit], self_model: SelfModel) -> tuple[list[Relation], SelfTrace]:
    """relate, for CLIVE digesting itself: the relations, and the trace of every unit to the
    product memory with the drift it shows (see SelfTrace). One pass over the units."""
    units = list(units)
    relations, own, terms, ignore = _relate(units, self_model, trace=True)
    return relations, _trace(units, own, terms, ignore, self_model)


def _relate(units: Iterable[Unit], self_model: SelfModel, trace: bool = False
            ) -> tuple[list[Relation], list[Trace], list[list[str]], frozenset[str]]:
    if not isinstance(self_model, SelfModel):
        raise ValueError("relate needs CLIVE's self-model")
    units = list(units)
    for unit in units:
        if not isinstance(unit, Unit):
            raise ValueError("relate takes Unit records")
    index = _Index(self_model)
    joins: list[dict[str, tuple[str, ...]]] = [{} for _unit in units]
    terms = [_unit_terms(unit, join) for unit, join in zip(units, joins, strict=True)]
    ignore = common_terms(terms)
    context = _context(index, terms, ignore, units)
    relations, own = [], []
    for unit, unit_terms, join in zip(units, terms, joins, strict=True):
        ranked = index.matches(unit, unit_terms, ignore, join)
        relations.append(_relation(unit, ranked, index.digest, context))
        if trace:
            own.append(_own_trace(unit, ranked, self_model))
    return relations, own, terms, ignore


def _context(index: _Index, terms: list[list[str]], ignore: frozenset[str],
             units: list[Unit]) -> Match | None:
    """The entry CLIVE has that the artifact's own vocabulary matches strongly, if any: its
    CONTEXT_TERMS most frequent common terms, compared as one text."""
    if not ignore:
        return None
    counts: Counter[str] = Counter()
    for unit_terms in terms:
        counts.update(term for term in set(unit_terms) if term in ignore)
    vocabulary = [term for term, _n in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
                  [:CONTEXT_TERMS]]
    probe = Unit(units[0].artifact_id, "knowledge", "the artifact as a whole", "",
                 units[0].location, ())
    for match in index.matches(probe, vocabulary):
        if match.present and match.counts and match.score >= OVERLAP_THRESHOLD:
            return Match(match.key, match.kind, match.name, match.score, match.present,
                         match.terms, match.shared, False, True)
        break
    return None


def common_terms(terms: list[list[str]]) -> frozenset[str]:
    """The terms in more than COMMON_SHARE of the units whose terms are given, when there are
    at least COMMON_MIN_UNITS units; none otherwise. Without this, every module of a package
    named crooks-assistant.app "extended" the feature 'CROOKS Control Mac app' on the two words
    its path shares with that feature's name."""
    if len(terms) < COMMON_MIN_UNITS:
        return frozenset()
    counts: Counter[str] = Counter()
    for unit_terms in terms:
        counts.update(set(unit_terms))
    return frozenset(term for term, n in counts.items() if n > COMMON_SHARE * len(terms))


# --- CLIVE itself: the why-index and drift ----------------------------------------------------


@dataclass(frozen=True)
class Trace:
    """The feature, idea or decision one unit serves, or None when nothing in the product
    memory accounts for it, and how that is known (`via`):

    cited   the unit cites the entry by its id (FEAT-nnn, IDEA-nnn, DEC-nnn)
    unit    the unit resembles the entry by the evidence a relation needs
    file    the unit is code in a file whose words carry the entry's name (see _file_traces)"""

    unit_id: str
    key: str | None
    score: float
    terms: tuple[str, ...] = ()
    via: str = ""


@dataclass(frozen=True)
class SelfTrace:
    """What digesting CLIVE shows about CLIVE: each unit's trace, and where code and product
    memory have drifted apart. Every list is bounded by MAX_DRIFT; the counts are whole.

    traced_entries        the why-index at a glance: the entries most code traces to,
                          (key, code files tracing to it)
    code_without_memory   folders of code units that trace to nothing, most first:
                          (folder, untraced code units, code units)
    shipped_without_code  shipped or testing features that no code carries: no code unit
                          traces to one, and no code file carries its name
    planned_with_code     features not shipped (planned, building, superseded ...) and ideas
                          that code already traces to: (key, code files tracing to it, status)
    decision_links        each decision's strongest link to code, strongest first:
                          (decision, unit id, score, via) — for a link via a file, the unit
                          is the file's first code unit
    """

    self_model: str
    traces: tuple[Trace, ...]
    names: tuple[tuple[str, str], ...]        # (key, name) of every entry the lists cite
    code_units: int
    traced_code_units: int
    code_files: int
    traced_code_files: int
    traced_entries: tuple[tuple[str, int], ...]
    code_without_memory: tuple[tuple[str, int, int], ...]
    shipped_without_code: tuple[str, ...]
    shipped_without_code_count: int
    planned_with_code: tuple[tuple[str, int, str], ...]
    decision_links: tuple[tuple[str, str, float, str], ...]

    def name(self, key: str) -> str:
        return dict(self.names).get(key, key)


# A citation of a product-memory entry by its id, and the kind each prefix names.
_CITATION = re.compile(r"\b(FEAT|IDEA|DEC)-(\d{3,4})\b")
CITED_KINDS = {"FEAT": "feature", "IDEA": "idea", "DEC": "decision"}
# A code file carries an entry's name when the terms of the name it holds weigh at least
# TRACE_COVERAGE of the name, weighed by how rare each is across the artifact's code files; at
# least one of them in no more than TRACE_DISTINCTIVE of those files; and at least TRACE_TERMS
# of them. Tuned on CLIVE itself (DIGESTIONS_2026-09-26.md): a single function rarely shares
# enough words with a one-line feature to count, but its file does; "app", in every file, is not
# evidence of the WhatsApp integration; and a name of one word ("What needs me today" is
# "today") is carried by every file that says it.
TRACE_COVERAGE = 0.75
TRACE_DISTINCTIVE = 0.1
TRACE_TERMS = 2


def is_code(unit: Unit) -> bool:
    """Whether a unit was read out of code rather than prose."""
    return unit.kind in CODE_KINDS and not unit.location.path.lower().endswith(PROSE_SUFFIXES)


def _folder(path: str) -> str:
    parts = path.split("/")[:-1]
    return "/".join(parts[:3]) or "."


def _own_trace(unit: Unit, ranked: list[Match], self_model: SelfModel) -> Trace:
    """What the unit itself says it serves: an entry it cites by id, or the closest memory
    entry by the evidence a relation needs."""
    for prefix, number in _CITATION.findall(f"{unit.title}\n{unit.body}"[:MAX_TEXT_CHARS]):
        key = f"{CITED_KINDS[prefix]}:{prefix}-{number}"
        if self_model.get(key) is not None:
            return Trace(unit.id, key, 1.0, (), "cited")
    best = next((m for m in ranked if m.kind in MEMORY_KINDS and m.counts
                 and m.score >= EXTENDS_THRESHOLD), None)
    if best is None:
        return Trace(unit.id, None, 0.0)
    return Trace(unit.id, best.key, best.score, best.terms, "unit")


def _file_traces(files: dict[str, set[str]], self_model: SelfModel, ignore: frozenset[str]
                 ) -> tuple[dict[str, tuple[str, float, tuple[str, ...]]], set[str]]:
    """Each code file's best memory entry by the words of the entry's name (see
    TRACE_COVERAGE), and every entry some file carries. A name is a query over the code:
    the whole file is compared, since one function rarely says what feature it is part of."""
    total = len(files)
    frequency: Counter[str] = Counter()
    postings: dict[str, list[str]] = {}
    for path in sorted(files):
        for term in files[path]:
            frequency[term] += 1
            postings.setdefault(term, []).append(path)
    distinctive = max(1, int(TRACE_DISTINCTIVE * total))
    best: dict[str, tuple[float, float, str, tuple[str, ...]]] = {}
    carried: set[str] = set()
    for kind in MEMORY_KINDS:
        for entry in self_model.of_kind(kind):
            joins: dict[str, tuple[str, ...]] = {}
            query = [term for term in dict.fromkeys(tokenise(entry.name, MAX_TOKENS // 4, joins))
                     if term not in ignore]
            weight = {term: math.log((total + 1) / (frequency[term] + 1)) for term in query}
            whole = sum(weight.values())
            if not query or whole <= 0:
                continue
            candidates = sorted({path for term in query if 0 < frequency[term] <= distinctive
                                 for path in postings[term]})
            for path in candidates:
                shared = tuple(term for term in query if term in files[path])
                coverage = sum(weight[term] for term in shared) / whole
                if coverage < TRACE_COVERAGE or _words(shared, joins) < TRACE_TERMS:
                    continue
                carried.add(entry.key)
                ranking = (round(coverage, 4), sum(weight[term] for term in shared))
                current = best.get(path)
                if current is None or ranking > current[:2] or (
                        ranking == current[:2] and entry.key < current[2]):
                    best[path] = (*ranking, entry.key, shared)
    return {path: (key, score, shared) for path, (score, _w, key, shared) in best.items()}, carried


def _trace(units: list[Unit], own: list[Trace], terms: list[list[str]], ignore: frozenset[str],
           self_model: SelfModel) -> SelfTrace:
    files: dict[str, set[str]] = {}
    first: dict[str, str] = {}
    for unit, unit_terms in zip(units, terms, strict=True):
        if is_code(unit):
            path = unit.location.path
            words = files.setdefault(path, set(tokenise(path.replace("/", " "), MAX_TOKENS // 4)))
            words.update(term for term in unit_terms if term not in ignore)
            first.setdefault(path, unit.id)
    by_file, carried = _file_traces(files, self_model, ignore)
    traces: list[Trace] = []
    for unit, trace in zip(units, own, strict=True):
        found = by_file.get(unit.location.path) if is_code(unit) else None
        if trace.key is None and found is not None:
            trace = Trace(unit.id, found[0], found[1], found[2], "file")
        traces.append(trace)
    folders: dict[str, list[int]] = {}
    tracing: dict[str, set[str]] = {}
    links: dict[str, tuple[float, str, str]] = {}
    for unit, trace in zip(units, traces, strict=True):
        if not is_code(unit):
            continue
        counts = folders.setdefault(_folder(unit.location.path), [0, 0])
        counts[1] += 1
        if trace.key is None:
            counts[0] += 1
            continue
        tracing.setdefault(trace.key, set()).add(unit.location.path)
        if trace.key.startswith("decision:"):
            unit_id = first[unit.location.path] if trace.via == "file" else unit.id
            current = links.get(trace.key)
            if current is None or (trace.score, unit_id) > current[:2]:
                links[trace.key] = (trace.score, unit_id, trace.via)
    code = [trace for unit, trace in zip(units, traces, strict=True) if is_code(unit)]
    untraced = sorted(((folder, n[0], n[1]) for folder, n in folders.items() if n[0]),
                      key=lambda row: (-row[1], row[0]))
    shipped = [entry.key for entry in self_model.of_kind("feature")
               if entry.present and entry.key not in tracing and entry.key not in carried]
    by_files = sorted(((key, len(paths)) for key, paths in tracing.items()),
                      key=lambda row: (-row[1], row[0]))
    planned = [(key, n, self_model.get(key).status or "") for key, n in by_files
               if key.startswith(("feature:", "idea:")) and self_model.get(key) is not None
               and not self_model.get(key).present]
    decisions = sorted(((key, unit_id, score, via) for key, (score, unit_id, via) in links.items()),
                       key=lambda row: (-row[2], row[0]))
    cited = ({key for key, _n in by_files[:MAX_DRIFT]} | set(shipped[:MAX_DRIFT])
             | {row[0] for row in planned[:MAX_DRIFT]} | {row[0] for row in decisions[:MAX_DRIFT]})
    names = tuple(sorted((key, self_model.get(key).name) for key in cited if self_model.get(key)))
    return SelfTrace(
        self_model=self_model.digest, traces=tuple(traces), names=names,
        code_units=len(code), traced_code_units=sum(1 for t in code if t.key is not None),
        code_files=len(files),
        traced_code_files=len({path for paths in tracing.values() for path in paths}),
        traced_entries=tuple(by_files[:MAX_DRIFT]),
        code_without_memory=tuple(untraced[:MAX_DRIFT]),
        shipped_without_code=tuple(shipped[:MAX_DRIFT]), shipped_without_code_count=len(shipped),
        planned_with_code=tuple(planned[:MAX_DRIFT]), decision_links=tuple(decisions[:MAX_DRIFT]),
    )
