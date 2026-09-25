"""The scene plan: what CLIVE proposes to show for one answer, over a closed set of primitives.

A plan never carries a value of its own. Every value-bearing element points at an evidence
handle and a field name; prose places bound values through numbered slots ("{0} customers are
waiting"), and a digit, a currency sign, a number in words ("forty", "half", "double"), an
email or web address or markup anywhere else in prose is refused by app/scenes/validate.py.
The schema is strict — an unknown element or an extra field is an error — so a plan is one of
these shapes or it is not a plan. Every element carries a one-line justification of plain
words under the same rule; one without is dropped by the validator, which also decides
everything else about what may be shown. The accepted scene it returns is described at the foot of this file.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.scenes.evidence import Kind, Money, Series

# A numbered slot in prose, filled with a bound value when the scene is drawn.
SLOT = re.compile(r"\{(\d)\}")

Handle = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,40}$")]
FieldName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
RecordId = Annotated[str, Field(min_length=1, max_length=200)]
Justification = Annotated[str, Field(max_length=160)]
Significance = Literal["ACTION_REQUIRED", "DECISION_REQUIRED", "RISK", "UNCERTAINTY", "LIMITATION", "CONTEXT"]
# A closed vocabulary, not a value: "as_observed" is the window the evidence itself covers.
Period = Literal[
    "as_observed", "today", "yesterday", "this_week", "last_week", "this_month", "last_month",
    "last_7_days", "last_30_days", "last_90_days", "since_launch",
]
Rows = Annotated[int, Field(ge=1, le=50, strict=True)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _lines(text: str, most: int) -> str:
    """Prose that has words once trimmed, in at most `most` lines by every line boundary
    (a carriage return ends a line as a newline does)."""
    text = text.strip()
    if not text:
        raise ValueError("no words, only whitespace")
    if len(text.splitlines()) > most:
        raise ValueError(f"at most {most} line(s)")
    return text


class FieldRef(_Strict):
    """A value in evidence: a field of one record, or a fact about the whole result when no
    record is named."""

    evidence: Handle
    field: FieldName
    record: RecordId | None = None


class Answer(_Strict):
    """One or two lines that answer the question. Always shown."""

    type: Literal["answer"] = "answer"
    text: Annotated[str, Field(min_length=1, max_length=280)]
    values: list[FieldRef] = Field(default_factory=list, max_length=4)
    justification: Justification = ""

    @field_validator("text")
    @classmethod
    def _two_lines(cls, text: str) -> str:
        return _lines(text, 2)


class Finding(_Strict):
    """Something the evidence shows that matters, with how much it matters."""

    type: Literal["finding"] = "finding"
    significance: Significance
    text: Annotated[str, Field(min_length=1, max_length=200)]
    values: list[FieldRef] = Field(default_factory=list, max_length=4)
    evidence: list[Handle] = Field(default_factory=list, max_length=6)
    justification: Justification = ""

    @field_validator("text")
    @classmethod
    def _one_line(cls, text: str) -> str:
        return _lines(text, 1)


class Entity(_Strict):
    """One evidence record, with the fields chosen for it."""

    type: Literal["entity"] = "entity"
    evidence: Handle
    record: RecordId
    fields: list[FieldName] = Field(min_length=1, max_length=8)
    justification: Justification = ""


class Collection(_Strict):
    """Rows of one evidence, with the columns chosen and a row limit."""

    type: Literal["collection"] = "collection"
    evidence: Handle
    columns: list[FieldName] = Field(min_length=1, max_length=8)
    limit: Rows
    justification: Justification = ""


class Measure(_Strict):
    """One quantity, and the period it covers."""

    type: Literal["measure"] = "measure"
    value: FieldRef
    period: Period = "as_observed"
    justification: Justification = ""


class Comparison(_Strict):
    """Two quantities of the same kind, side by side."""

    type: Literal["comparison"] = "comparison"
    current: FieldRef
    previous: FieldRef
    justification: Justification = ""


class Trend(_Strict):
    """A series, drawn as a line."""

    type: Literal["trend"] = "trend"
    series: FieldRef
    justification: Justification = ""


class Timeline(_Strict):
    """Records of one evidence in time order: a datetime field and a label field."""

    type: Literal["timeline"] = "timeline"
    evidence: Handle
    at: FieldName
    label: FieldName
    limit: Rows
    justification: Justification = ""


class Proposal(_Strict):
    """An action that already exists, by its id. A plan cannot describe a new one."""

    type: Literal["proposal"] = "proposal"
    action: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")]
    justification: Justification = ""


class Question(_Strict):
    """What CLIVE needs the owner to say before it can go on."""

    type: Literal["question"] = "question"
    text: Annotated[str, Field(min_length=1, max_length=200)]
    options: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default_factory=list, max_length=4)
    justification: Justification = ""

    @field_validator("text")
    @classmethod
    def _one_line(cls, text: str) -> str:
        return _lines(text, 1)

    @field_validator("options")
    @classmethod
    def _one_line_each(cls, options: list[str]) -> list[str]:
        return [_lines(option, 1) for option in options]


Element = Annotated[
    Finding | Entity | Collection | Measure | Comparison | Trend | Timeline | Proposal | Question,
    Field(discriminator="type"),
]


class ScenePlan(_Strict):
    """One Answer, and the further elements proposed beside it."""

    answer: Answer
    elements: list[Element] = Field(default_factory=list, max_length=12)


# ------------------------------------------------------------------ the accepted scene


@dataclass(frozen=True, slots=True)
class Bound:
    """A value taken from evidence: where it came from, what kind it is, and the value."""

    evidence: str
    record: str | None
    field: str
    kind: Kind
    label: str
    value: Any
    pii: bool = False
    unit: str | None = None

    def text(self) -> str:
        return _plain(self.value, self.unit)

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence, "record": self.record, "field": self.field, "kind": str(self.kind),
            "label": self.label, "value": _jsonable(self.value), "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class Shown:
    """An element that may be shown, with the values bound to it: `values` fill its slots or
    are its quantities; `rows` are an Entity's, a Collection's or a Timeline's."""

    element: Any
    values: tuple[Bound, ...] = ()
    rows: tuple[tuple[Bound, ...], ...] = ()

    def text(self) -> str:
        """The element's prose with its slots filled; empty for an element without prose."""
        text = getattr(self.element, "text", "")
        return SLOT.sub(lambda m: self.values[int(m.group(1))].text(), text)

    def bound(self) -> Iterator[Bound]:
        yield from self.values
        for row in self.rows:
            yield from row

    def as_dict(self) -> dict[str, Any]:
        return {
            "element": self.element.model_dump(), "values": [b.as_dict() for b in self.values],
            "rows": [[b.as_dict() for b in row] for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class Source:
    """One evidence a drill-down refers to: what was read, when, and how many rows it found."""

    handle: str
    tool: str
    query: str
    observed_at: datetime
    records: int

    def as_dict(self) -> dict[str, Any]:
        return {"handle": self.handle, "tool": self.tool, "query": self.query, "observed_at": self.observed_at.isoformat(), "records": self.records}


@dataclass(frozen=True, slots=True)
class DrillDown:
    """A reference to the evidence an answer checked, opened on request. Not the evidence."""

    sources: tuple[Source, ...]

    @property
    def handles(self) -> tuple[str, ...]:
        return tuple(s.handle for s in self.sources)

    def as_dict(self) -> dict[str, Any]:
        return {"sources": [s.as_dict() for s in self.sources]}


@dataclass(frozen=True, slots=True)
class Scene:
    """What may be shown: the Answer, at most a budget of further elements, and — when only
    the Answer survived — a drill-down reference to what it checked."""

    answer: Shown
    elements: tuple[Shown, ...] = ()
    drilldown: DrillDown | None = None

    def bound(self) -> Iterator[Bound]:
        yield from self.answer.bound()
        for shown in self.elements:
            yield from shown.bound()

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": {**self.answer.as_dict(), "text": self.answer.text()},
            "elements": [{**s.as_dict(), "text": s.text()} for s in self.elements],
            "drilldown": self.drilldown.as_dict() if self.drilldown is not None else None,
        }


Decision = Literal["kept", "dropped", "reduced", "replaced", "ignored"]


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """One decision: what it was about, what was decided, and why."""

    target: str
    decision: Decision
    reason: str


def _plain(value: Any, unit: str | None) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, Money):
        return value.text()
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    if isinstance(value, Series):
        return f"{len(value.points)} points"
    if isinstance(value, float):
        return f"{value:g}" + (f" {unit}" if unit else "")
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value) + (f" {unit}" if unit else "")
    return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Money):
        return {"amount": str(value.amount), "currency": value.currency}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Series):
        return {"points": [[p.at, p.value] for p in value.points], "currency": value.currency, "unit": value.unit}
    return value
