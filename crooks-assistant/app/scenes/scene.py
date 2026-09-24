"""The scene-plan schema: a closed set of primitives over evidence, and nothing else.

Every value-bearing element points at an evidence handle and a field name; none of them carries
a free-standing number or markup of its own. Every element carries a one-line justification —
whether that justification survives review is for app/scenes/validate.py, not for this module,
which only fixes the shape a plan is allowed to take. Extra fields are forbidden throughout, so
a plan cannot smuggle in anything outside this set.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Significance(StrEnum):
    """Why a Finding is on the screen at all."""

    ACTION_REQUIRED = "ACTION_REQUIRED"
    DECISION_REQUIRED = "DECISION_REQUIRED"
    RISK = "RISK"
    UNCERTAINTY = "UNCERTAINTY"
    LIMITATION = "LIMITATION"
    CONTEXT = "CONTEXT"


class EvidenceRef(BaseModel):
    """A pointer at one field of one piece of evidence from this session. Nowhere in a scene
    plan does a value appear except behind a pointer shaped like this one."""

    model_config = ConfigDict(extra="forbid")

    handle: str
    field: str


class MeasureRef(BaseModel):
    """One evidence field, over one period — what a Measure holds, and what each side of a
    Comparison is."""

    model_config = ConfigDict(extra="forbid")

    evidence: EvidenceRef
    period: str


class Answer(BaseModel):
    """One or two lines, always on the screen. The only element the validator never drops."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["answer"] = "answer"
    lines: list[str] = Field(min_length=1, max_length=2)
    evidence: list[EvidenceRef] = []
    justification: str = ""


class Finding(BaseModel):
    """One thing worth the owner's attention, with why it matters and what backs it."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["finding"] = "finding"
    significance: Significance
    text: str
    evidence: list[EvidenceRef] = []
    justification: str = ""


class Entity(BaseModel):
    """One evidence record, and the fields of it chosen to show — an order, a customer, a
    thread, never the raw record."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["entity"] = "entity"
    handle: str
    record: int = Field(ge=0)
    fields: list[str] = Field(min_length=1)
    label: str | None = None
    justification: str = ""


class Collection(BaseModel):
    """Several records from one piece of evidence, as columns, bounded to a row limit."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["collection"] = "collection"
    handle: str
    columns: list[str] = Field(min_length=1)
    limit: int = Field(default=8, ge=1)
    title: str | None = None
    justification: str = ""


class Measure(BaseModel):
    """One evidence field, over one period, shown as a figure."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["measure"] = "measure"
    ref: MeasureRef
    label: str | None = None
    justification: str = ""


class Comparison(BaseModel):
    """Two measures set against each other — this period against the one before, and the like."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["comparison"] = "comparison"
    baseline: MeasureRef
    current: MeasureRef
    label: str | None = None
    justification: str = ""


class Trend(BaseModel):
    """A `series` evidence field, shown as a trend."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["trend"] = "trend"
    evidence: EvidenceRef
    label: str | None = None
    justification: str = ""


class Timeline(BaseModel):
    """Several records from one piece of evidence, ordered by a `datetime` field."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["timeline"] = "timeline"
    handle: str
    at_field: str
    label_field: str | None = None
    limit: int = Field(default=8, ge=1)
    justification: str = ""


class Proposal(BaseModel):
    """A reference to an action that already exists (app/actions) — a scene plan never mints
    a new one; it only points at one the action engine already knows how to run."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["proposal"] = "proposal"
    action_ref: str
    label: str | None = None
    justification: str = ""


class Question(BaseModel):
    """Something to ask the owner, optionally grounded in evidence."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["question"] = "question"
    text: str
    evidence: list[EvidenceRef] = []
    justification: str = ""


Element = Annotated[
    Finding | Entity | Collection | Measure | Comparison | Trend | Timeline | Proposal | Question,
    Field(discriminator="kind"),
]


class ScenePlan(BaseModel):
    """A proposed scene: one Answer, and the further elements a planner would like to show —
    subject to the budget app/scenes/validate.py enforces before anything is drawn."""

    model_config = ConfigDict(extra="forbid")

    answer: Answer
    elements: list[Element] = []


class AcceptedScene(BaseModel):
    """What survived validation: the Answer, the elements kept within budget, and — when
    nothing else survived — a drill-down back to the evidence the Answer checked."""

    model_config = ConfigDict(extra="forbid")

    answer: Answer
    elements: list[Element] = []
    drilldown: list[EvidenceRef] = []
