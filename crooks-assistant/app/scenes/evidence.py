"""The evidence model: what a connector read, typed, with nothing decided about how — or
whether — it is shown.

A connector's only job is to describe its output: the fields it carries, their kind, whether
one is personal, and the unit or currency a number is in. It registers descriptors
(FieldDescriptor) and wraps a tool result as Evidence; it writes no UI code, and nothing here
imports anything that renders. What is drawn from this, and what is left out, is decided later
by app/scenes/scene.py and app/scenes/validate.py — never by the connector.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


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


def _shape_error(descriptor: FieldDescriptor, value: Any) -> str | None:
    """None when `value` is a well-formed value of `descriptor.kind` (or absent, which is
    always allowed — a field a connector did not have for this record). Otherwise the reason
    it is not, so a malformed record is refused rather than shown as if it were typed."""

    if value is None:
        return None
    kind = descriptor.kind
    if kind is FieldKind.MONEY:
        if not isinstance(value, dict):
            return "money value must be an amount/currency mapping"
        amount = value.get("amount")
        currency = value.get("currency")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return "money value must carry a numeric amount"
        if not isinstance(currency, str) or not _ISO_CURRENCY_RE.match(currency):
            return "money value must carry an ISO currency code"
        return None
    if kind in (FieldKind.COUNT, FieldKind.RATIO, FieldKind.DURATION):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{kind.value} value must be numeric"
        return None
    if kind is FieldKind.DATETIME:
        if isinstance(value, (datetime, date)):
            return None
        if isinstance(value, str) and value.strip():
            return None
        return "datetime value must be a non-empty timestamp"
    if kind is FieldKind.STATUS:
        if isinstance(value, (str, bool)):
            return None
        return "status value must be text or a boolean"
    if kind is FieldKind.PERSON:
        if isinstance(value, str):
            return None
        return "person value must be text"
    if kind is FieldKind.TEXT:
        if isinstance(value, str):
            return None
        return "text value must be text"
    if kind is FieldKind.LINK:
        if isinstance(value, dict) and isinstance(value.get("label"), str):
            return None
        return "link value must be a mapping with a label"
    if kind is FieldKind.SERIES:
        if not isinstance(value, list):
            return "series value must be a list of points"
        for point in value:
            if not isinstance(point, dict) or "at" not in point or "value" not in point:
                return "series value must be a list of at/value points"
        return None
    return None


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

    @model_validator(mode="after")
    def _records_match_descriptors(self) -> Evidence:
        names = self.field_names()
        for index, record in enumerate(self.records):
            for key in record:
                if key not in names:
                    raise ValueError(f"record {index} has field {key!r} not described by this evidence")
            for descriptor in self.fields:
                reason = _shape_error(descriptor, record.get(descriptor.name))
                if reason is not None:
                    raise ValueError(f"record {index} field {descriptor.name!r}: {reason}")
        return self

    def field(self, name: str) -> FieldDescriptor | None:
        return next((f for f in self.fields if f.name == name), None)

    def field_names(self) -> frozenset[str]:
        return frozenset(f.name for f in self.fields)

    def value(self, record_index: int, name: str) -> Any:
        return self.records[record_index].get(name)

    def has_value(self, name: str) -> bool:
        """Whether at least one record carries an actual value for this field — a descriptor
        naming a field nobody ever filled in grounds nothing."""
        return any(record.get(name) is not None for record in self.records)


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
    if not isinstance(currency, str) or not _ISO_CURRENCY_RE.match(currency):
        raise ValueError(f"not an ISO currency code: {currency!r}")
    return {"amount": round(float(amount), 2), "currency": currency}


def series_point(at: str, value: float) -> dict[str, Any]:
    """One point in a `series` field: an ISO-8601 timestamp and a value."""
    return {"at": at, "value": value}
