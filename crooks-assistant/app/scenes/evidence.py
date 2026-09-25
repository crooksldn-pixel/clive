"""Evidence: what a read found, described field by field, with nothing about how to draw it.

Connectors describe data, CLIVE decides what to show, the screen shows findings not sources.
A connector registers a `ToolDescriptors` for each of its read tools — the kind, label and pii
flag of every field the tool returns — and `Registry.to_evidence` turns a result into typed
`Evidence` through those descriptors alone. There is no screen code per connector here or
anywhere else in app/scenes: what may be shown is decided in app/scenes/validate.py, from the
kinds, never from which connector a value came from.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any


class Kind(StrEnum):
    """The closed set of field kinds. A value's kind, not its source, decides how it is shown."""

    MONEY = "money"
    COUNT = "count"
    RATIO = "ratio"
    DATETIME = "datetime"
    DURATION = "duration"
    STATUS = "status"
    PERSON = "person"
    LINK = "link"
    TEXT = "text"
    SERIES = "series"


# The kinds a Measure or a Comparison can carry: a quantity, not a word.
QUANTITIES = frozenset({Kind.MONEY, Kind.COUNT, Kind.RATIO, Kind.DURATION})

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_TOOL = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
HANDLE = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
MAX_TEXT = 300
MAX_SHORT = 120
MAX_QUERY = 160
MAX_RECORDS = 200


# ------------------------------------------------------------------------ values


@dataclass(frozen=True, slots=True)
class Money:
    """An amount and its ISO 4217 currency. A Decimal, never a float: money is counted."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise ValueError("Money needs a finite Decimal amount.")
        if not isinstance(self.currency, str) or not _CURRENCY.match(self.currency):
            raise ValueError(f"{self.currency!r} is not an ISO 4217 currency code.")

    def text(self) -> str:
        return f"{self.amount:.2f} {self.currency}"


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    at: str       # an ISO date or datetime, or the bucket's own label ("2026-W38")
    value: float


@dataclass(frozen=True, slots=True)
class Series:
    """Points in order. The currency or unit belongs to every point."""

    points: tuple[SeriesPoint, ...]
    currency: str | None = None
    unit: str | None = None


# ------------------------------------------------------------------ descriptors


@dataclass(frozen=True, slots=True)
class FieldDescriptor:
    """One field a read returns: its name, kind, label, whether it is personal (pii), and the
    unit or currency where the kind has one. `path` is where the value sits in a raw record
    (dotted, the name when absent); `points` names the x and y keys of a series' points."""

    name: str
    kind: Kind
    label: str
    pii: bool = False
    unit: str | None = None
    currency: str | None = None
    path: str | None = None
    points: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME.match(self.name):
            raise ValueError(f"{self.name!r} is not a field name (lower case, digits, underscores).")
        object.__setattr__(self, "kind", Kind(self.kind))
        if not isinstance(self.label, str) or not self.label.strip() or len(self.label) > 60:
            raise ValueError(f"{self.name}: a label is one to sixty characters.")
        if self.currency is not None and (self.kind not in (Kind.MONEY, Kind.SERIES) or not _CURRENCY.match(self.currency)):
            raise ValueError(f"{self.name}: a currency is an ISO code on a money or series field.")
        if self.unit is not None and self.kind not in (Kind.COUNT, Kind.RATIO, Kind.DURATION, Kind.SERIES):
            raise ValueError(f"{self.name}: a {self.kind} field has no unit.")
        if self.points is not None and (self.kind is not Kind.SERIES or len(self.points) != 2):
            raise ValueError(f"{self.name}: points name the x and y keys of a series.")


@dataclass(frozen=True, slots=True)
class Record:
    """One row of evidence: an id and a value (or None, unknown) for every described field."""

    id: str
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Evidence:
    """What one read found. `records` are its rows, described by `fields`; `facts` are about
    the result as a whole (a total, a count, a series), described by `fact_fields`. The handle
    is what a scene plan cites; `query` is a short, redacted summary of what was asked."""

    handle: str
    tool: str
    observed_at: datetime
    query: str
    fields: tuple[FieldDescriptor, ...] = ()
    records: tuple[Record, ...] = ()
    fact_fields: tuple[FieldDescriptor, ...] = ()
    facts: Mapping[str, Any] = field(default_factory=dict)
    session_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.handle, str) or not HANDLE.match(self.handle):
            raise ValueError(f"{self.handle!r} is not an evidence handle.")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None:
            raise ValueError("observed_at is a timezone-aware datetime.")
        if len(self.query) > MAX_QUERY:
            raise ValueError("The query summary is short: at most 160 characters.")
        for described in (self.fields, self.fact_fields):
            names = [d.name for d in described]
            if len(names) != len(set(names)):
                raise ValueError(f"{self.handle}: a field is described twice.")
        names = {d.name for d in self.fields}
        ids: set[str] = set()
        for record in self.records:
            if record.id in ids:
                raise ValueError(f"{self.handle}: record {record.id!r} appears twice.")
            ids.add(record.id)
            if not set(record.values) <= names:
                raise ValueError(f"{self.handle}: record {record.id!r} carries an undescribed field.")
        if not set(self.facts) <= {d.name for d in self.fact_fields}:
            raise ValueError(f"{self.handle}: a fact is not described.")

    def descriptor(self, name: str, *, fact: bool = False) -> FieldDescriptor | None:
        return next((d for d in (self.fact_fields if fact else self.fields) if d.name == name), None)

    def record(self, record_id: str) -> Record | None:
        return next((r for r in self.records if r.id == record_id), None)


# --------------------------------------------------------------------- coercion


def coerce(descriptor: FieldDescriptor, raw: Any) -> Any:
    """The raw value as its kind says it is, or None when it is absent or is not of that kind.
    Unknown is said as unknown: a value that will not parse is never guessed at."""
    if raw is None:
        return None
    try:
        return _COERCE[descriptor.kind](descriptor, raw)
    except (TypeError, ValueError, ArithmeticError, OSError):
        return None


def _number(raw: Any) -> float:
    if isinstance(raw, bool):
        raise TypeError("a flag is not a number")
    if isinstance(raw, (int, float, Decimal)):
        value = float(raw)
    elif isinstance(raw, str):
        value = float(raw.strip())
    else:
        raise TypeError("not a number")
    if not math.isfinite(value):
        raise ValueError("not a finite number")
    return value


def _money(d: FieldDescriptor, raw: Any) -> Money:
    if isinstance(raw, Money):
        return raw
    currency: Any = d.currency
    if isinstance(raw, Mapping):
        amount = raw.get("amount")
        currency = raw.get("currency") or currency
    elif isinstance(raw, str):
        parts = raw.split()
        if not parts or len(parts) > 2:
            raise ValueError("not an amount")
        amount = parts[0]
        currency = parts[1] if len(parts) == 2 else currency
    else:
        amount = _number(raw)
    if amount is None or not currency:
        raise ValueError("an amount needs its currency")
    return Money(Decimal(str(amount)), str(currency).upper())


def _count(_d: FieldDescriptor, raw: Any) -> int:
    if isinstance(raw, (list, tuple)):
        return len(raw)
    value = _number(raw)
    if value != int(value):
        raise ValueError("a count is whole")
    return int(value)


def _quantity(_d: FieldDescriptor, raw: Any) -> float:
    return _number(raw)


def _datetime(_d: FieldDescriptor, raw: Any) -> datetime:
    if isinstance(raw, datetime):
        value = raw
    elif isinstance(raw, date):
        value = datetime(raw.year, raw.month, raw.day)
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # Epoch seconds, or milliseconds when it is too large to be seconds.
        value = datetime.fromtimestamp(raw / 1000 if abs(raw) > 1e11 else raw, UTC)
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip()
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            value = parsedate_to_datetime(text)   # a mail Date header
    else:
        raise TypeError("not a time")
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _status(_d: FieldDescriptor, raw: Any) -> str:
    if isinstance(raw, bool):
        return "yes" if raw else "no"
    if isinstance(raw, (str, int)):
        text = " ".join(str(raw).split())[:40]
        if text:
            return text
    raise ValueError("not a status")


def _flat(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bool):
        raise TypeError("a flag is not text")
    if isinstance(raw, (int, float)):
        return str(raw)
    if isinstance(raw, Mapping):
        raw = list(raw.values())
    if isinstance(raw, (list, tuple)):
        return ", ".join(part for part in (_flat(v) for v in raw if v is not None and v != "") if part)
    raise TypeError("not text")


def _text(limit: int) -> Callable[[FieldDescriptor, Any], str]:
    def shorten(_d: FieldDescriptor, raw: Any) -> str:
        text = " ".join(_flat(raw).split())
        if not text:
            raise ValueError("empty")
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    return shorten


def _series(d: FieldDescriptor, raw: Any) -> Series:
    if isinstance(raw, Series):
        return raw
    currency: Any = d.currency
    if isinstance(raw, Mapping):
        currency = raw.get("currency") or currency
        raw = raw.get("points")
    if not isinstance(raw, (list, tuple)):
        raise TypeError("not a series")
    x, y = d.points or ("at", "value")
    points: list[SeriesPoint] = []
    for point in raw:
        if isinstance(point, Mapping):
            at, value = point.get(x), point.get(y)
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            at, value = point
        else:
            continue
        try:
            number = _number(value)
        except (TypeError, ValueError):
            continue
        if at is not None and str(at).strip():
            points.append(SeriesPoint(str(at).strip()[:40], number))
    code = str(currency).upper() if currency else None
    return Series(tuple(points), code if code and _CURRENCY.match(code) else None, d.unit)


_COERCE: dict[Kind, Callable[[FieldDescriptor, Any], Any]] = {
    Kind.MONEY: _money,
    Kind.COUNT: _count,
    Kind.RATIO: _quantity,
    Kind.DURATION: _quantity,
    Kind.DATETIME: _datetime,
    Kind.STATUS: _status,
    Kind.PERSON: _text(MAX_SHORT),
    Kind.LINK: _text(MAX_SHORT),
    Kind.TEXT: _text(MAX_TEXT),
    Kind.SERIES: _series,
}


def lookup(data: Any, path: str) -> Any:
    """The value at a dotted path, or None. "." is the data itself."""
    if path == ".":
        return data
    for part in path.split("."):
        if not isinstance(data, Mapping):
            return None
        data = data.get(part)
    return data


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w-])(?:\+|0)\d[\d ()-]{8,}\d")


def summarise(text: Any) -> str:
    """A query summary as a drill-down may show it: one line, short, with no address or phone
    number in it — what was asked is described, never who it was asked about."""
    line = " ".join(str(text or "").split())
    line = _PHONE.sub("[phone]", _EMAIL.sub("[email]", line))
    return line if len(line) <= MAX_QUERY else line[: MAX_QUERY - 1].rstrip() + "…"


# ------------------------------------------------------------------- registration

Extract = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolDescriptors:
    """What a connector registers for one read tool. `records` is the path of the list of rows
    in the result ("." when the result is itself the one row); `record_id` the path of each
    row's id. `extract`, when a result is awkwardly shaped, reshapes it into plain data first;
    it describes nothing and draws nothing."""

    tool: str
    label: str
    fields: tuple[FieldDescriptor, ...] = ()
    facts: tuple[FieldDescriptor, ...] = ()
    records: str | None = None
    record_id: str | None = None
    extract: Extract | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tool, str) or not _TOOL.match(self.tool):
            raise ValueError(f"{self.tool!r} is not a tool name.")
        if self.fields and self.records is None:
            raise ValueError(f"{self.tool}: record fields need the path of the records.")
        for described in (self.fields, self.facts):
            names = [d.name for d in described]
            if len(names) != len(set(names)):
                raise ValueError(f"{self.tool}: a field is described twice.")


class Registry:
    """The descriptors every connector has registered, by tool name."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolDescriptors] = {}

    def register(self, spec: ToolDescriptors) -> ToolDescriptors:
        if spec.tool in self._specs:
            raise ValueError(f"Descriptors for {spec.tool!r} are already registered.")
        self._specs[spec.tool] = spec
        return spec

    def get(self, tool: str) -> ToolDescriptors | None:
        return self._specs.get(tool)

    def tools(self) -> list[str]:
        return sorted(self._specs)

    def to_evidence(
        self, tool: str, result: Mapping[str, Any], *, handle: str, query: str | None = None,
        args: Mapping[str, Any] | None = None, observed_at: datetime | None = None, session_id: str | None = None,
    ) -> Evidence:
        """One tool result as Evidence, through its registered descriptors and nothing else."""
        spec = self._specs.get(tool)
        if spec is None:
            raise KeyError(f"No descriptors are registered for {tool!r}.")
        if not isinstance(result, Mapping):
            raise TypeError("A tool result is described from a mapping.")
        data = spec.extract(result) if spec.extract is not None else result
        records: list[Record] = []
        seen: set[str] = set()
        for index, raw in enumerate(_raw_records(data, spec.records)):
            ident = lookup(raw, spec.record_id) if spec.record_id else None
            key = str(ident).strip() if ident is not None else ""
            if not key or key in seen:
                key = f"#{index}"
            seen.add(key)
            records.append(Record(key, {d.name: coerce(d, lookup(raw, d.path or d.name)) for d in spec.fields}))
        facts = {d.name: coerce(d, lookup(data, d.path or d.name)) for d in spec.facts}
        return Evidence(
            handle=handle, tool=tool, observed_at=observed_at or datetime.now(UTC),
            query=summarise(query if query is not None else _describe(spec, args)),
            fields=spec.fields, records=tuple(records), fact_fields=spec.facts, facts=facts,
            session_id=session_id,
        )


def _raw_records(data: Mapping[str, Any], path: str | None) -> Iterable[Mapping[str, Any]]:
    if path is None:
        return []
    found = lookup(data, path)
    if isinstance(found, Mapping):
        return [found]
    if isinstance(found, (list, tuple)):
        return [r for r in found if isinstance(r, Mapping)][:MAX_RECORDS]
    return []


def _describe(spec: ToolDescriptors, args: Mapping[str, Any] | None) -> str:
    asked = [f"{k} {v}" for k, v in (args or {}).items() if v not in (None, "", False) and v != [] and v != {}]
    return spec.label + (": " + ", ".join(str(a)[:40] for a in asked) if asked else "")


DEFAULT = Registry()


def register(spec: ToolDescriptors) -> ToolDescriptors:
    return DEFAULT.register(spec)


def to_evidence(
    tool: str, result: Mapping[str, Any], *, handle: str, query: str | None = None,
    args: Mapping[str, Any] | None = None, observed_at: datetime | None = None, session_id: str | None = None,
) -> Evidence:
    return DEFAULT.to_evidence(tool, result, handle=handle, query=query, args=args, observed_at=observed_at, session_id=session_id)
