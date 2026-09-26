"""The Knowledge Digester's data model: where an artifact came from, what was read out of it,
what was noticed about it, and what CLIVE proposes — or the owner decides — to take from it.

Digesting is reading. Nothing here fetches, unpacks or runs anything: these are records of
what the digester found, frozen once made, serialised with to_dict and read back with
from_dict so that the one is exactly the other. Every id is derived from the content it names,
so the same artifact digested twice gives the same ids, and a record whose id does not match
its content is refused on the way in rather than trusted.

The vocabularies below are closed — a value not in them is refused — and extensible by adding
to the tuple here; schema.py reads them from this module so the two cannot drift apart."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

ORIGIN_KINDS = ("git", "archive", "file", "directory", "url", "upload")
ARTIFACT_KINDS = (
    "skill_collection", "python_package", "node_package", "source_code", "document",
    "api_spec", "tool_spec", "dataset", "web_app", "theme", "media", "application",
    "configuration", "other",
)
UNIT_KINDS = (
    "procedure",     # steps to do something
    "rule",          # a constraint or guideline
    "check",         # something testable
    "capability",    # something that can be called: a tool, endpoint or command
    "interface",     # a schema or contract
    "pattern",       # a reusable design or code shape
    "knowledge",     # a fact or explanation
    "data_schema",
    "design_token",
    "example",
    "dependency",
    "script",        # code that would run if executed — never run by the digester
    "claim",         # an assertion by the source that needs verifying
)
FINDING_CATEGORIES = ("safety", "quality")
SEVERITIES = ("info", "low", "medium", "high", "critical")
ABSORPTION_TARGETS = (
    "builder_skill", "review_check", "tool_connector", "product_memory", "native_objective",
    "design_system", "reference_only", "rejected",
)
# The targets that put something into CLIVE, and so must say exactly what; the other two add
# nothing, and their removal handle says so by being empty.
ADDING_TARGETS = frozenset(
    ("builder_skill", "review_check", "tool_connector", "product_memory", "native_objective",
     "design_system")
)
# token_set: a named block of design tokens in the Generative UI's token sheet; component: a
# component's folder beside the scene renderer. Both are what the design_system target adds.
ADDITION_KINDS = (
    "file", "skill", "check", "tool", "connector", "memory", "objective", "token_set",
    "component",
)
PROPOSER = "clive"   # CLIVE proposes
DECIDER = "owner"    # the owner decides

MAX_TITLE = 200
MAX_BODY = 16_000
MAX_LICENCE = 4_000
MAX_EXPLANATION = 4_000
MAX_REASONING = 4_000
MAX_TAG = 64

CONTENT_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
ARTIFACT_ID_PATTERN = r"^art-[0-9a-f]{24}$"
UNIT_ID_PATTERN = r"^unit-[0-9a-f]{24}$"
FINDING_ID_PATTERN = r"^find-[0-9a-f]{24}$"
ABSORPTION_ID_PATTERN = r"^abs-[0-9a-f]{24}$"


def content_digest(data: bytes) -> str:
    """The digest a Source records for its quarantined copy."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _derive(prefix: str, *parts: Any) -> str:
    canonical = json.dumps(
        [prefix, *parts], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"{prefix}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]}"


# --- validation ------------------------------------------------------------------------------


def _text(value: Any, name: str, *, limit: int | None = None, optional: bool = False,
          empty: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{name} must be a non-empty string")
    if limit is not None and len(value) > limit:
        raise ValueError(f"{name} is longer than {limit} characters")
    _utf8(value, name)


def _utf8(value: str, name: str) -> None:
    """Every stored string must be writable as UTF-8: ids are derived from it and the store
    writes it. A lone surrogate (from a JSON or Python escape, or a file name that is not
    UTF-8) is refused here with a ValueError, never a UnicodeEncodeError later."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{name} contains text that cannot be written as UTF-8") from None


def _choice(value: Any, name: str, vocabulary: tuple[str, ...] | frozenset[str]) -> None:
    if not isinstance(value, str) or value not in vocabulary:
        raise ValueError(f"{name} must be one of {sorted(vocabulary)}, not {value!r}")


def _match(value: Any, name: str, pattern: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"{name} does not match {pattern}: {value!r}")


def _timestamp(value: Any, name: str) -> None:
    _text(value, name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} is not an ISO 8601 timestamp: {value!r}") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must carry a timezone: {value!r}")


def _as_tuple(value: Any, name: str) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list")
    return tuple(value)


def _unique(values: tuple, name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{name} has duplicates")


def _fields(data: Any, name: str, keys: tuple[str, ...]) -> dict:
    """The serialised form, exactly: every key present and nothing else, so that what is read
    back is what was written."""
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be an object")
    missing = [key for key in keys if key not in data]
    unexpected = sorted(set(data) - set(keys))
    if missing or unexpected:
        raise ValueError(f"{name}: missing {missing}, unexpected {unexpected}")
    return data


def _same_id(data: dict, derived: str, name: str) -> None:
    if data["id"] != derived:
        raise ValueError(f"{name} id {data['id']!r} is not the id its content derives: {derived}")


# --- the records -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    """Where an artifact came from. An artifact never exists without one."""

    origin: str             # the URL or path, as given
    origin_kind: str        # ORIGIN_KINDS
    pinned_ref: str         # commit SHA, or the content digest where there is nothing to pin
    licence: str | None     # as found; None when none was found
    taken_at: str           # ISO 8601 with a timezone
    content_digest: str     # of the quarantined copy: "sha256:<hex>"

    def __post_init__(self) -> None:
        _text(self.origin, "origin")
        _choice(self.origin_kind, "origin_kind", ORIGIN_KINDS)
        _text(self.pinned_ref, "pinned_ref")
        _text(self.licence, "licence", limit=MAX_LICENCE, optional=True)
        _timestamp(self.taken_at, "taken_at")
        _match(self.content_digest, "content_digest", CONTENT_DIGEST_PATTERN)

    @property
    def artifact_id(self) -> str:
        """Derived from the content alone: the same bytes are the same artifact."""
        return _derive("art", self.content_digest)

    def to_dict(self) -> dict:
        return {
            "origin": self.origin,
            "origin_kind": self.origin_kind,
            "pinned_ref": self.pinned_ref,
            "licence": self.licence,
            "taken_at": self.taken_at,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Source:
        keys = ("origin", "origin_kind", "pinned_ref", "licence", "taken_at", "content_digest")
        data = _fields(data, "source", keys)
        return cls(**{key: data[key] for key in keys})


@dataclass(frozen=True)
class Location:
    """A place in the artifact: a relative path, and the 1-based inclusive line span when the
    thing is text. "." is the artifact as a whole."""

    path: str
    line_start: int | None = None
    line_end: int | None = None

    def __post_init__(self) -> None:
        _text(self.path, "location path")
        pure = PurePosixPath(self.path)
        if "\x00" in self.path or pure.is_absolute() or ".." in pure.parts or str(pure) != self.path:
            raise ValueError(f"location path must be relative, normalised and inside the artifact: {self.path!r}")
        if self.line_start is None and self.line_end is None:
            return
        for name, value in (("line_start", self.line_start), ("line_end", self.line_end)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a line number from 1, or both must be None")
        if self.line_start > self.line_end:
            raise ValueError("line_start is after line_end")

    def to_dict(self) -> dict:
        return {"path": self.path, "line_start": self.line_start, "line_end": self.line_end}

    @classmethod
    def from_dict(cls, data: Any) -> Location:
        data = _fields(data, "location", ("path", "line_start", "line_end"))
        return cls(data["path"], data["line_start"], data["line_end"])


@dataclass(frozen=True)
class Unit:
    """The smallest reusable piece read out of an artifact."""

    artifact_id: str
    kind: str               # UNIT_KINDS
    title: str
    body: str               # at most MAX_BODY characters
    location: Location
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _match(self.artifact_id, "artifact_id", ARTIFACT_ID_PATTERN)
        _choice(self.kind, "unit kind", UNIT_KINDS)
        _text(self.title, "title", limit=MAX_TITLE)
        _text(self.body, "body", limit=MAX_BODY, empty=True)
        if not isinstance(self.location, Location):
            raise ValueError("a unit needs its location in the artifact")
        object.__setattr__(self, "tags", _as_tuple(self.tags, "tags"))
        for tag in self.tags:
            _text(tag, "tag", limit=MAX_TAG)
        _unique(self.tags, "tags")

    @property
    def id(self) -> str:
        return _derive(
            "unit", self.artifact_id, self.kind, self.title, self.body,
            self.location.to_dict(), list(self.tags),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "location": self.location.to_dict(),
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Any) -> Unit:
        data = _fields(
            data, "unit", ("id", "artifact_id", "kind", "title", "body", "location", "tags")
        )
        unit = cls(
            artifact_id=data["artifact_id"], kind=data["kind"], title=data["title"],
            body=data["body"], location=Location.from_dict(data["location"]),
            tags=_as_tuple(data["tags"], "tags"),
        )
        _same_id(data, unit.id, "unit")
        return unit


@dataclass(frozen=True)
class Artifact:
    """One digested thing: its Source, what kinds of thing it was found to be — one repository
    can be a skill collection and a Python package at once — and its Units."""

    source: Source
    kinds: tuple[str, ...]
    units: tuple[Unit, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source, Source):
            raise ValueError("an artifact never exists without its Source")
        object.__setattr__(self, "kinds", _as_tuple(self.kinds, "kinds"))
        for kind in self.kinds:
            _choice(kind, "artifact kind", ARTIFACT_KINDS)
        _unique(self.kinds, "kinds")
        object.__setattr__(self, "units", _as_tuple(self.units, "units"))
        for unit in self.units:
            if not isinstance(unit, Unit):
                raise ValueError("units must be Unit records")
            if unit.artifact_id != self.id:
                raise ValueError(f"unit {unit.id} belongs to {unit.artifact_id}, not {self.id}")
        _unique(tuple(unit.id for unit in self.units), "unit ids")

    @property
    def id(self) -> str:
        return self.source.artifact_id

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source.to_dict(),
            "kinds": list(self.kinds),
            "units": [unit.to_dict() for unit in self.units],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Artifact:
        data = _fields(data, "artifact", ("id", "source", "kinds", "units"))
        artifact = cls(
            source=Source.from_dict(data["source"]),
            kinds=_as_tuple(data["kinds"], "kinds"),
            units=tuple(Unit.from_dict(unit) for unit in _as_tuple(data["units"], "units")),
        )
        _same_id(data, artifact.id, "artifact")
        return artifact


@dataclass(frozen=True)
class Finding:
    """Something the digester noticed about the artifact's safety or quality."""

    artifact_id: str
    category: str           # FINDING_CATEGORIES
    severity: str           # SEVERITIES
    location: Location
    explanation: str        # plain words
    unit_id: str | None = None

    def __post_init__(self) -> None:
        _match(self.artifact_id, "artifact_id", ARTIFACT_ID_PATTERN)
        _choice(self.category, "category", FINDING_CATEGORIES)
        _choice(self.severity, "severity", SEVERITIES)
        if not isinstance(self.location, Location):
            raise ValueError("a finding needs its location in the artifact")
        _text(self.explanation, "explanation", limit=MAX_EXPLANATION)
        _match(self.unit_id, "unit_id", UNIT_ID_PATTERN, optional=True)

    @property
    def id(self) -> str:
        return _derive(
            "find", self.artifact_id, self.category, self.severity, self.location.to_dict(),
            self.explanation, self.unit_id,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "artifact_id": self.artifact_id,
            "category": self.category,
            "severity": self.severity,
            "location": self.location.to_dict(),
            "explanation": self.explanation,
            "unit_id": self.unit_id,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Finding:
        data = _fields(
            data, "finding",
            ("id", "artifact_id", "category", "severity", "location", "explanation", "unit_id"),
        )
        finding = cls(
            artifact_id=data["artifact_id"], category=data["category"],
            severity=data["severity"], location=Location.from_dict(data["location"]),
            explanation=data["explanation"], unit_id=data["unit_id"],
        )
        _same_id(data, finding.id, "finding")
        return finding


@dataclass(frozen=True)
class Addition:
    """One thing an absorption put into CLIVE: what kind of thing, where it is (a repository
    path or a record id), and the digest of what was put there, so that removing it can
    confirm it is removing exactly that."""

    kind: str               # ADDITION_KINDS
    ref: str
    digest: str | None = None

    def __post_init__(self) -> None:
        _choice(self.kind, "addition kind", ADDITION_KINDS)
        _text(self.ref, "addition ref")
        _match(self.digest, "addition digest", CONTENT_DIGEST_PATTERN, optional=True)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "digest": self.digest}

    @classmethod
    def from_dict(cls, data: Any) -> Addition:
        data = _fields(data, "addition", ("kind", "ref", "digest"))
        return cls(data["kind"], data["ref"], data["digest"])


@dataclass(frozen=True)
class RemovalHandle:
    """Exactly what an absorption added, so it can be taken out again cleanly. Empty for the
    targets that add nothing — which is itself the record that there is nothing to remove."""

    additions: tuple[Addition, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "additions", _as_tuple(self.additions, "additions"))
        for addition in self.additions:
            if not isinstance(addition, Addition):
                raise ValueError("additions must be Addition records")
        _unique(self.additions, "additions")

    def to_dict(self) -> dict:
        return {"additions": [addition.to_dict() for addition in self.additions]}

    @classmethod
    def from_dict(cls, data: Any) -> RemovalHandle:
        data = _fields(data, "removal", ("additions",))
        return cls(tuple(Addition.from_dict(item) for item in _as_tuple(data["additions"], "additions")))


@dataclass(frozen=True)
class Absorption:
    """A proposal (decided_by None) or a decision (decided_by the owner) to use a Unit in CLIVE.
    Nothing is absorbed without a way back: the removal handle is required, and a target that
    adds something must say exactly what."""

    artifact_id: str
    unit_id: str
    target: str             # ABSORPTION_TARGETS
    reasoning: str
    removal: RemovalHandle
    recorded_at: str
    proposed_by: str = PROPOSER
    decided_by: str | None = None

    def __post_init__(self) -> None:
        _match(self.artifact_id, "artifact_id", ARTIFACT_ID_PATTERN)
        _match(self.unit_id, "unit_id", UNIT_ID_PATTERN)
        _choice(self.target, "target", ABSORPTION_TARGETS)
        _text(self.reasoning, "reasoning", limit=MAX_REASONING)
        if not isinstance(self.removal, RemovalHandle):
            raise ValueError("an absorption needs a removal handle: nothing is absorbed without a way back")
        if self.target in ADDING_TARGETS and not self.removal.additions:
            raise ValueError(f"a {self.target} absorption must record in its removal handle what it adds")
        if self.target not in ADDING_TARGETS and self.removal.additions:
            raise ValueError(f"a {self.target} absorption adds nothing, so its removal handle must be empty")
        _timestamp(self.recorded_at, "recorded_at")
        if self.proposed_by != PROPOSER:
            raise ValueError(f"absorptions are proposed by {PROPOSER}, not {self.proposed_by!r}")
        if self.decided_by is not None and self.decided_by != DECIDER:
            raise ValueError(f"absorptions are decided by the {DECIDER}, not {self.decided_by!r}")

    @property
    def is_decision(self) -> bool:
        return self.decided_by is not None

    @property
    def id(self) -> str:
        return _derive(
            "abs", self.artifact_id, self.unit_id, self.target, self.reasoning,
            self.removal.to_dict(), self.recorded_at, self.proposed_by, self.decided_by,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "artifact_id": self.artifact_id,
            "unit_id": self.unit_id,
            "target": self.target,
            "reasoning": self.reasoning,
            "removal": self.removal.to_dict(),
            "recorded_at": self.recorded_at,
            "proposed_by": self.proposed_by,
            "decided_by": self.decided_by,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Absorption:
        data = _fields(
            data, "absorption",
            ("id", "artifact_id", "unit_id", "target", "reasoning", "removal", "recorded_at",
             "proposed_by", "decided_by"),
        )
        if data["removal"] is None:
            raise ValueError("an absorption needs a removal handle: nothing is absorbed without a way back")
        absorption = cls(
            artifact_id=data["artifact_id"], unit_id=data["unit_id"], target=data["target"],
            reasoning=data["reasoning"], removal=RemovalHandle.from_dict(data["removal"]),
            recorded_at=data["recorded_at"], proposed_by=data["proposed_by"],
            decided_by=data["decided_by"],
        )
        _same_id(data, absorption.id, "absorption")
        return absorption
