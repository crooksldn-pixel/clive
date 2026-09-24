"""The evidence model: what a connector read, typed, with nothing decided about how — or
whether — it is shown.

A connector's only job is to describe its output: the fields it carries, their kind, whether
one is personal, and the unit or currency a number is in. It registers descriptors
(FieldDescriptor) and wraps a tool result as Evidence; it writes no UI code, and nothing here
imports anything that renders. What is drawn from this, and what is left out, is decided later
by app/scenes/scene.py and app/scenes/validate.py — never by the connector.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class FieldKind(StrEnum):
    """The closed set of value shapes a piece of evidence can carry."""

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


class FieldDescriptor(BaseModel):
    """One field a connector's records carry: its name, kind, a human label, whether it is
    personal data, and — for money or a unit-bearing number — what unit it is in."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: FieldKind
    label: str
    pii: bool = False
    unit: str | None = None
    currency: str | None = None


class Evidence(BaseModel):
    """One connector's read, held as a handle, the described fields, and the records they
    describe. A scene plan never carries a number or a name outside of this: it points at a
    handle and a field name, and this is what that pointer resolves to."""

    model_config = ConfigDict(extra="forbid")

    handle: str
    source_tool: str
    observed_at: datetime
    query_summary: str
    fields: list[FieldDescriptor]
    records: list[dict[str, Any]] = []

    @field_validator("fields")
    @classmethod
    def _unique_field_names(cls, fields: list[FieldDescriptor]) -> list[FieldDescriptor]:
        names = [f.name for f in fields]
        if len(names) != len(set(names)):
            raise ValueError("field names must be unique within one piece of evidence")
        return fields

    def field(self, name: str) -> FieldDescriptor | None:
        return next((f for f in self.fields if f.name == name), None)

    def field_names(self) -> frozenset[str]:
        return frozenset(f.name for f in self.fields)

    def value(self, record_index: int, name: str) -> Any:
        return self.records[record_index].get(name)


def evidence_map(evidence: list[Evidence] | tuple[Evidence, ...]) -> dict[str, Evidence]:
    """Evidence by handle. Raises on a duplicate handle: two pieces of evidence claiming the
    same handle in one session is a connector bug, not something to shadow silently."""
    out: dict[str, Evidence] = {}
    for item in evidence:
        if item.handle in out:
            raise ValueError(f"duplicate evidence handle: {item.handle}")
        out[item.handle] = item
    return out


def money(amount: float, currency: str) -> dict[str, Any]:
    """The value shape a `money` field carries: the amount and its ISO currency together, so
    a figure is never shown without knowing what it is a figure of."""
    return {"amount": round(float(amount), 2), "currency": currency}


def series_point(at: str, value: float) -> dict[str, Any]:
    """One point in a `series` field: an ISO-8601 timestamp and a value."""
    return {"at": at, "value": value}
