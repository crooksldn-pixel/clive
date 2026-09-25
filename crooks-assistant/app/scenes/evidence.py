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
# A record's key within its evidence: "r1", "r2", … in the order the read returned them. Never
# the connector's own id, which can be an email address or a name.
RECORD_KEY = re.compile(r"^r[1-9][0-9]{0,3}$")
# What a read is called, as its connector registered it: words, no digits, no marks.
_LABEL = re.compile(r"^[A-Z][A-Za-z' ]{0,59}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
MAX_TEXT = 300
MAX_SHORT = 120
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
    """One row of evidence: its key within the evidence ("r1", "r2", …) and a value (or None,
    unknown) for every described field. The key is opaque: whatever the connector identifies
    the row by is a field like any other, shown only as its descriptor allows."""

    id: str
    values: Mapping[str, Any]


def record_key(index: int) -> str:
    """The key of the row at `index` (from nought) in the order its read returned them."""
    return f"r{index + 1}"


@dataclass(frozen=True, slots=True)
class Evidence:
    """What one read found. `records` are its rows, described by `fields`; `facts` are about
    the result as a whole (a total, a count, a series), described by `fact_fields`. The handle
    is what a scene plan cites; `label` is what was read and `asked` the names of the
    arguments it was given, both as its connector registered them; `query` is the short
    summary a drill-down shows, made from those two alone — a summary given in words is not
    kept, since its words are what was asked about and can be anyone's name or address;
    `session_id` is the session whose read produced it, without which nothing in it may be
    shown."""

    handle: str
    tool: str
    observed_at: datetime
    query: str
    fields: tuple[FieldDescriptor, ...] = ()
    records: tuple[Record, ...] = ()
    fact_fields: tuple[FieldDescriptor, ...] = ()
    facts: Mapping[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    label: str = ""
    asked: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.handle, str) or not HANDLE.match(self.handle):
            raise ValueError(f"{self.handle!r} is not an evidence handle.")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None:
            raise ValueError("observed_at is a timezone-aware datetime.")
        if not isinstance(self.query, str) or not isinstance(self.label, str):
            raise ValueError("A query summary and a label are text.")
        object.__setattr__(self, "asked", tuple(self.asked))
        if (self.label or self.asked) and not registered(self.tool, self.label, self.asked):
            raise ValueError(f"{self.handle}: its label and arguments are not ones its tool registered.")
        # However it was made, the summary is stored as a drill-down may show it.
        object.__setattr__(self, "query", summary(self.label, self.asked, self.query))
        for described in (self.fields, self.fact_fields):
            names = [d.name for d in described]
            if len(names) != len(set(names)):
                raise ValueError(f"{self.handle}: a field is described twice.")
        names = {d.name for d in self.fields}
        ids: set[str] = set()
        for record in self.records:
            if not isinstance(record.id, str) or not RECORD_KEY.fullmatch(record.id):
                raise ValueError(f"{self.handle}: a record is keyed r1, r2, … and never by the connector's own id.")
            if record.id in ids:
                raise ValueError(f"{self.handle}: record {record.id} appears twice.")
            ids.add(record.id)
            if not set(record.values) <= names:
                raise ValueError(f"{self.handle}: record {record.id} carries an undescribed field.")
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


# What a summary says in place of anything that was asked in words.
VALUE = "[value]"


def summary(label: str, asked: Iterable[str] = (), given: Any = "") -> str:
    """A query summary as a drill-down may show it, made only of what a connector registered:
    the read's label and the names of the arguments it was given ("Inbox by query, days"),
    never their values. A summary given in words is not read word by word — any word, even
    one the store uses, can be a customer's or a business's name — so unless it says exactly
    what the registration says, all of it is `[value]`."""
    base = " by ".join(part for part in (label, ", ".join(asked)) if part)
    told = " ".join(str(given or "").split())
    if told in ("", base):
        return base
    return f"{base}: {VALUE}" if base else VALUE


# ------------------------------------------------------------------- registration

Extract = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolDescriptors:
    """What a connector registers for one read tool. `label` says what the read is, in words;
    `arguments` are the names of the arguments it takes, the only words besides the label a
    query summary is made of. `records` is the path of the list of rows in the result ("."
    when the result is itself the one row); `record_id` the path of each row's own id, used
    only to know a row read twice, never to key or show it. `extract`, when a result is
    awkwardly shaped, reshapes it into plain data first; it describes nothing and draws
    nothing."""

    tool: str
    label: str
    fields: tuple[FieldDescriptor, ...] = ()
    facts: tuple[FieldDescriptor, ...] = ()
    records: str | None = None
    record_id: str | None = None
    extract: Extract | None = None
    arguments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.tool, str) or not _TOOL.match(self.tool):
            raise ValueError(f"{self.tool!r} is not a tool name.")
        if not isinstance(self.label, str) or not _LABEL.fullmatch(self.label):
            raise ValueError(f"{self.tool}: a label is words, capitalised, with no digits or marks.")
        object.__setattr__(self, "arguments", tuple(self.arguments))
        if not all(isinstance(a, str) and _NAME.fullmatch(a) for a in self.arguments) or len(set(self.arguments)) != len(self.arguments):
            raise ValueError(f"{self.tool}: arguments are distinct names (lower case, digits, underscores).")
        if self.fields and self.records is None:
            raise ValueError(f"{self.tool}: record fields need the path of the records.")
        for described in (self.fields, self.facts):
            names = [d.name for d in described]
            if len(names) != len(set(names)):
                raise ValueError(f"{self.tool}: a field is described twice.")


# The label and argument names of every read any registry has registered, by tool: what an
# Evidence's label and `asked` are checked against, so that a summary is registered words only.
_REGISTERED: set[tuple[str, str, tuple[str, ...]]] = set()


def registered(tool: str, label: str, asked: Iterable[str]) -> bool:
    """Whether a registration of `tool` has this label (or any, when none is given) and takes
    every argument named in `asked`."""
    names = set(asked)
    return any(t == tool and (not label or registered_label == label) and names <= set(arguments)
               for t, registered_label, arguments in _REGISTERED)


class Registry:
    """The descriptors every connector has registered, by tool name."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolDescriptors] = {}

    def register(self, spec: ToolDescriptors) -> ToolDescriptors:
        if spec.tool in self._specs:
            raise ValueError(f"Descriptors for {spec.tool!r} are already registered.")
        self._specs[spec.tool] = spec
        _REGISTERED.add((spec.tool, spec.label, spec.arguments))
        return spec

    def get(self, tool: str) -> ToolDescriptors | None:
        return self._specs.get(tool)

    def tools(self) -> list[str]:
        return sorted(self._specs)

    def to_evidence(
        self, tool: str, result: Mapping[str, Any], *, handle: str, query: str | None = None,
        args: Mapping[str, Any] | None = None, observed_at: datetime | None = None, session_id: str | None = None,
    ) -> Evidence:
        """One tool result as Evidence, through its registered descriptors and nothing else.
        Its rows are keyed r1, r2, … and its summary names the registered arguments in `args`
        that were given; a `query` given in words is kept only as `[value]`."""
        spec = self._specs.get(tool)
        if spec is None:
            raise KeyError(f"No descriptors are registered for {tool!r}.")
        if not isinstance(result, Mapping):
            raise TypeError("A tool result is described from a mapping.")
        data = spec.extract(result) if spec.extract is not None else result
        records: list[Record] = []
        seen: set[str] = set()
        for raw in _raw_records(data, spec.records):
            ident = lookup(raw, spec.record_id) if spec.record_id else None
            if ident is not None and str(ident).strip():
                if str(ident).strip() in seen:
                    continue   # the same row, read twice
                seen.add(str(ident).strip())
            values = {d.name: coerce(d, lookup(raw, d.path or d.name)) for d in spec.fields}
            records.append(Record(record_key(len(records)), values))
        facts = {d.name: coerce(d, lookup(data, d.path or d.name)) for d in spec.facts}
        given = args if isinstance(args, Mapping) else {}
        asked = tuple(name for name in spec.arguments if _given(given.get(name)))
        return Evidence(
            handle=handle, tool=tool, observed_at=observed_at or datetime.now(UTC), query=query or "",
            fields=spec.fields, records=tuple(records), fact_fields=spec.facts, facts=facts,
            session_id=session_id, label=spec.label, asked=asked,
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


def _given(value: Any) -> bool:
    """Whether an argument was given a value (whatever it is, it is not read)."""
    return value is not None and value is not False and value != "" and value != [] and value != {}


DEFAULT = Registry()


def register(spec: ToolDescriptors) -> ToolDescriptors:
    return DEFAULT.register(spec)


def to_evidence(
    tool: str, result: Mapping[str, Any], *, handle: str, query: str | None = None,
    args: Mapping[str, Any] | None = None, observed_at: datetime | None = None, session_id: str | None = None,
) -> Evidence:
    return DEFAULT.to_evidence(tool, result, handle=handle, query=query, args=args, observed_at=observed_at, session_id=session_id)
