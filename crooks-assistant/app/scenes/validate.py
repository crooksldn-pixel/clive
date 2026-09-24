"""The scene validator: pure functions, no I/O.

`validate_scene` takes a proposed plan, the evidence the session actually holds and a small
context, and returns the scene that earned its place plus a trace of every element kept or
dropped and why. It refuses any value not bound to evidence from this session, drops elements
with no justification or with markup in their text, enforces the attention budget, strips
personal fields unless the context says the task needs contact details, and always keeps the
Answer. When nothing else survives, the scene is the Answer plus a drill-down back to the
evidence it checked.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.scenes.evidence import Evidence, FieldKind, evidence_map
from app.scenes.scene import (
    AcceptedScene,
    Answer,
    Collection,
    Comparison,
    Entity,
    EvidenceRef,
    Finding,
    Measure,
    MeasureRef,
    Proposal,
    Question,
    ScenePlan,
    Timeline,
    Trend,
)

MAX_FURTHER_ELEMENTS = 3
MAX_COLLECTION_ROWS = 8

_MARKUP_RE = re.compile(r"<[a-zA-Z/][^<>]*>|\*\*[^*]+\*\*|^#{1,6}\s|\[[^\]]+\]\([^)]+\)")


@dataclass(frozen=True)
class TraceEntry:
    """One line of the decision trace: what was looked at, whether it survived, and why."""

    element: str
    kept: bool
    reason: str


@dataclass(frozen=True)
class ValidationContext:
    """What the validator is allowed to assume about this turn: the evidence handles this
    session actually produced, and whether the task needs contact details or an explicit list."""

    session_evidence_handles: frozenset[str]
    needs_contact_details: bool = False
    explicit_list_request: bool = False


def _has_markup(text: str) -> bool:
    return bool(_MARKUP_RE.search(text))


def _ref_valid(ref: EvidenceRef, ev_map: dict[str, Evidence], context: ValidationContext) -> bool:
    if ref.handle not in context.session_evidence_handles:
        return False
    evidence = ev_map.get(ref.handle)
    return evidence is not None and evidence.field(ref.field) is not None


def _measure_ref_valid(ref: MeasureRef, ev_map: dict[str, Evidence], context: ValidationContext) -> bool:
    return _ref_valid(ref.evidence, ev_map, context)


def _filter_refs(
    refs: list[EvidenceRef], ev_map: dict[str, Evidence], context: ValidationContext
) -> tuple[list[EvidenceRef], list[EvidenceRef]]:
    kept: list[EvidenceRef] = []
    dropped: list[EvidenceRef] = []
    for ref in refs:
        (kept if _ref_valid(ref, ev_map, context) else dropped).append(ref)
    return kept, dropped


def _bound_evidence(handle: str, ev_map: dict[str, Evidence], context: ValidationContext) -> Evidence | None:
    if handle not in context.session_evidence_handles:
        return None
    return ev_map.get(handle)


def _strip_pii(
    names: list[str], evidence: Evidence, context: ValidationContext
) -> tuple[list[str], list[str]]:
    if context.needs_contact_details:
        return names, []
    kept: list[str] = []
    dropped: list[str] = []
    for name in names:
        descriptor = evidence.field(name)
        if descriptor is not None and descriptor.pii:
            dropped.append(name)
        else:
            kept.append(name)
    return kept, dropped


def _reduce_element(
    element: Any, ev_map: dict[str, Evidence], context: ValidationContext, name: str, trace: list[TraceEntry]
) -> Any | None:
    """One further element, checked against the evidence this session actually holds and
    reduced to what it may keep. Returns None when nothing about it can be kept."""

    if isinstance(element, Finding):
        kept_refs, dropped_refs = _filter_refs(element.evidence, ev_map, context)
        for ref in dropped_refs:
            trace.append(TraceEntry(f"{name}.evidence:{ref.handle}.{ref.field}", False, "not bound to evidence from this session"))
        if not kept_refs:
            trace.append(TraceEntry(name, False, "no evidence bound to this session"))
            return None
        return element.model_copy(update={"evidence": kept_refs})

    if isinstance(element, Entity):
        evidence = _bound_evidence(element.handle, ev_map, context)
        if evidence is None:
            trace.append(TraceEntry(name, False, "evidence handle not bound to this session"))
            return None
        if element.record >= len(evidence.records):
            trace.append(TraceEntry(name, False, "evidence record does not exist"))
            return None
        known = [f for f in element.fields if f in evidence.field_names()]
        for f in element.fields:
            if f not in evidence.field_names():
                trace.append(TraceEntry(f"{name}.field:{f}", False, "field not described by this evidence"))
        kept_fields, dropped_pii = _strip_pii(known, evidence, context)
        for f in dropped_pii:
            trace.append(TraceEntry(f"{name}.field:{f}", False, "pii field stripped"))
        if not kept_fields:
            trace.append(TraceEntry(name, False, "no fields left after validation"))
            return None
        return element.model_copy(update={"fields": kept_fields})

    if isinstance(element, Collection):
        evidence = _bound_evidence(element.handle, ev_map, context)
        if evidence is None:
            trace.append(TraceEntry(name, False, "evidence handle not bound to this session"))
            return None
        known = [c for c in element.columns if c in evidence.field_names()]
        for c in element.columns:
            if c not in evidence.field_names():
                trace.append(TraceEntry(f"{name}.column:{c}", False, "column not described by this evidence"))
        kept_columns, dropped_pii = _strip_pii(known, evidence, context)
        for c in dropped_pii:
            trace.append(TraceEntry(f"{name}.column:{c}", False, "pii column stripped"))
        if not kept_columns:
            trace.append(TraceEntry(name, False, "no columns left after validation"))
            return None
        limit = element.limit
        if limit > MAX_COLLECTION_ROWS and not context.explicit_list_request:
            trace.append(TraceEntry(f"{name}.limit", False, f"reduced to the attention budget of {MAX_COLLECTION_ROWS} rows"))
            limit = MAX_COLLECTION_ROWS
        return element.model_copy(update={"columns": kept_columns, "limit": limit})

    if isinstance(element, Measure):
        if not _measure_ref_valid(element.ref, ev_map, context):
            trace.append(TraceEntry(name, False, "evidence not bound to this session"))
            return None
        return element

    if isinstance(element, Comparison):
        if not (_measure_ref_valid(element.baseline, ev_map, context) and _measure_ref_valid(element.current, ev_map, context)):
            trace.append(TraceEntry(name, False, "evidence not bound to this session"))
            return None
        return element

    if isinstance(element, Trend):
        if not _ref_valid(element.evidence, ev_map, context):
            trace.append(TraceEntry(name, False, "evidence not bound to this session"))
            return None
        descriptor = ev_map[element.evidence.handle].field(element.evidence.field)
        if descriptor is None or descriptor.kind != FieldKind.SERIES:
            trace.append(TraceEntry(name, False, "field is not a series"))
            return None
        return element

    if isinstance(element, Timeline):
        evidence = _bound_evidence(element.handle, ev_map, context)
        if evidence is None:
            trace.append(TraceEntry(name, False, "evidence handle not bound to this session"))
            return None
        at_descriptor = evidence.field(element.at_field)
        if at_descriptor is None or at_descriptor.kind != FieldKind.DATETIME:
            trace.append(TraceEntry(name, False, "at_field is not a datetime field"))
            return None
        label_field = element.label_field
        if label_field is not None and label_field not in evidence.field_names():
            trace.append(TraceEntry(f"{name}.label_field", False, "field not described by this evidence"))
            label_field = None
        limit = element.limit
        if limit > MAX_COLLECTION_ROWS and not context.explicit_list_request:
            trace.append(TraceEntry(f"{name}.limit", False, f"reduced to the attention budget of {MAX_COLLECTION_ROWS} rows"))
            limit = MAX_COLLECTION_ROWS
        return element.model_copy(update={"label_field": label_field, "limit": limit})

    if isinstance(element, Proposal):
        return element

    if isinstance(element, Question):
        kept_refs, dropped_refs = _filter_refs(element.evidence, ev_map, context)
        for ref in dropped_refs:
            trace.append(TraceEntry(f"{name}.evidence:{ref.handle}.{ref.field}", False, "not bound to evidence from this session"))
        return element.model_copy(update={"evidence": kept_refs})

    trace.append(TraceEntry(name, False, "unknown element kind"))
    return None


def validate_scene(
    plan: ScenePlan, evidence: Sequence[Evidence], context: ValidationContext
) -> tuple[AcceptedScene, tuple[TraceEntry, ...]]:
    """Reduce a proposed plan to what earned its place, against the evidence this session
    actually holds. Returns the accepted scene and a trace of every element kept or dropped."""

    ev_map = evidence_map(evidence)
    trace: list[TraceEntry] = []

    answer_kept_refs, answer_dropped_refs = _filter_refs(plan.answer.evidence, ev_map, context)
    for ref in answer_dropped_refs:
        trace.append(TraceEntry(f"answer.evidence:{ref.handle}.{ref.field}", False, "not bound to evidence from this session"))
    kept_answer: Answer = plan.answer.model_copy(update={"evidence": answer_kept_refs})
    trace.append(TraceEntry("answer", True, "the answer is always kept"))

    survivors: list[tuple[int, Any]] = []
    for index, element in enumerate(plan.elements):
        name = f"{element.kind}:{index}"
        if not element.justification.strip():
            trace.append(TraceEntry(name, False, "no justification"))
            continue
        text = getattr(element, "text", None)
        if isinstance(text, str) and _has_markup(text):
            trace.append(TraceEntry(name, False, "text contains markup"))
            continue
        adjusted = _reduce_element(element, ev_map, context, name, trace)
        if adjusted is None:
            continue
        survivors.append((index, adjusted))

    kept: list[Any] = []
    for order, (index, element) in enumerate(survivors):
        name = f"{element.kind}:{index}"
        if order < MAX_FURTHER_ELEMENTS:
            kept.append(element)
            trace.append(TraceEntry(name, True, "kept"))
        else:
            trace.append(TraceEntry(name, False, "over the attention budget"))

    drilldown: list[EvidenceRef] = []
    if not kept:
        seen: set[tuple[str, str]] = set()
        for ref in kept_answer.evidence:
            key = (ref.handle, ref.field)
            if key not in seen:
                seen.add(key)
                drilldown.append(ref)
        trace.append(TraceEntry("drilldown", True, "answer only; evidence kept as a drill-down"))

    scene = AcceptedScene(answer=kept_answer, elements=kept, drilldown=drilldown)
    return scene, tuple(trace)
