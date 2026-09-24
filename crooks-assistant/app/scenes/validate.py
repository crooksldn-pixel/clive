"""The scene validator: pure functions, no I/O.

`validate_scene` takes a proposed plan, the evidence the session actually holds and a small
context, and returns the scene that earned its place plus a trace of every element kept or
dropped and why. It refuses any value not bound to a grounded field of evidence from this
session, drops elements with no justification, with markup anywhere in their user-visible text,
or with a number or period that no bound evidence can back, enforces the attention budget,
strips personal fields — including bare evidence references, not only chosen columns — unless
the context says the task needs contact details, and always keeps the Answer (though its wording
is itself held to the same no-invention rule). When nothing else survives, the scene is the
Answer plus a drill-down back to the evidence it checked.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
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
    Proposal,
    Question,
    ScenePlan,
    Timeline,
    Trend,
)

MAX_FURTHER_ELEMENTS = 3
MAX_COLLECTION_ROWS = 8

_FALLBACK_ANSWER_LINE = "See the evidence below for details."

_MARKUP_RE = re.compile(r"<[a-zA-Z/][^<>]*>|\*\*[^*]+\*\*|^#{1,6}\s|\[[^\]]+\]\([^)]+\)")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PERIOD_RE = re.compile(
    r"\b(this|last|next|past)\s+(day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TraceEntry:
    """One line of the decision trace: what was looked at, whether it survived, and why."""

    element: str
    kept: bool
    reason: str


@dataclass(frozen=True)
class ValidationContext:
    """What the validator is allowed to assume about this turn: the evidence handles this
    session actually produced, the action references that actually exist to propose, and
    whether the task needs contact details or an explicit list."""

    session_evidence_handles: frozenset[str]
    needs_contact_details: bool = False
    explicit_list_request: bool = False
    known_action_refs: frozenset[str] = field(default_factory=frozenset)


def _has_markup(text: str) -> bool:
    return bool(_MARKUP_RE.search(text))


def _has_unsupported_period(text: str) -> bool:
    return bool(_PERIOD_RE.search(text))


def _clean_label(label: str | None, name: str, attr: str, trace: list[TraceEntry]) -> str | None:
    """A label or title is user-visible text too: markup in it is stripped, not shown, the
    same as anywhere else — it is just not load-bearing enough to take the whole element with it."""
    if label is None or not _has_markup(label):
        return label
    trace.append(TraceEntry(f"{name}.{attr}", False, "markup in user-visible text"))
    return None


def _stringify_record_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        if "amount" in value:
            amount = value["amount"]
            return [str(amount), f"{float(amount):.2f}"]
        if "at" in value and "value" in value:
            return [str(value["value"]), str(value["at"])]
        return [str(v) for v in value.values() if v is not None]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_stringify_record_value(item))
        return out
    return [str(value)]


def _verifiable_haystack(refs: list[EvidenceRef], ev_map: dict[str, Evidence]) -> str:
    parts: list[str] = []
    for ref in refs:
        evidence = ev_map.get(ref.handle)
        if evidence is None:
            continue
        for record in evidence.records:
            parts.extend(_stringify_record_value(record.get(ref.field)))
    return " | ".join(parts).replace(",", "")


def _has_unverifiable_number(text: str, refs: list[EvidenceRef], ev_map: dict[str, Evidence]) -> bool:
    numbers = _NUMBER_RE.findall(text)
    if not numbers:
        return False
    haystack = _verifiable_haystack(refs, ev_map)
    return any(number.replace(",", "") not in haystack for number in numbers)


def _display_text_reason(text: str, refs: list[EvidenceRef], ev_map: dict[str, Evidence]) -> str | None:
    """None when `text` is safe to show as written: no markup, no number and no period it is
    not possible to check against the evidence bound to it. Otherwise, why it is not."""

    if _has_markup(text):
        return "markup in user-visible text"
    if _has_unverifiable_number(text, refs, ev_map):
        return "text carries a value no bound evidence can verify"
    if _has_unsupported_period(text):
        return "text carries a period no bound evidence backs"
    return None


def _ref_status(ref: EvidenceRef, ev_map: dict[str, Evidence], context: ValidationContext) -> str:
    """'ok', 'pii', 'ungrounded' or 'unbound' — never just whether the descriptor exists."""

    if ref.handle not in context.session_evidence_handles:
        return "unbound"
    evidence = ev_map.get(ref.handle)
    if evidence is None:
        return "unbound"
    descriptor = evidence.field(ref.field)
    if descriptor is None:
        return "unbound"
    if not evidence.has_value(ref.field):
        return "ungrounded"
    if descriptor.pii and not context.needs_contact_details:
        return "pii"
    return "ok"


_REF_STATUS_REASON = {
    "unbound": "not bound to evidence from this session",
    "ungrounded": "no recorded value grounds this reference",
    "pii": "pii field stripped",
}


def _filter_refs(
    refs: list[EvidenceRef],
    ev_map: dict[str, Evidence],
    context: ValidationContext,
    name_prefix: str,
    trace: list[TraceEntry],
) -> list[EvidenceRef]:
    kept: list[EvidenceRef] = []
    for ref in refs:
        status = _ref_status(ref, ev_map, context)
        if status == "ok":
            kept.append(ref)
        else:
            trace.append(TraceEntry(f"{name_prefix}:{ref.handle}.{ref.field}", False, _REF_STATUS_REASON[status]))
    return kept


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
        kept_refs = _filter_refs(element.evidence, ev_map, context, f"{name}.evidence", trace)
        if not kept_refs:
            trace.append(TraceEntry(name, False, "no evidence bound to this session"))
            return None
        reason = _display_text_reason(element.text, kept_refs, ev_map)
        if reason is not None:
            trace.append(TraceEntry(name, False, reason))
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
        label = _clean_label(element.label, name, "label", trace)
        return element.model_copy(update={"fields": kept_fields, "label": label})

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
        title = _clean_label(element.title, name, "title", trace)
        return element.model_copy(update={"columns": kept_columns, "limit": limit, "title": title})

    if isinstance(element, Measure):
        status = _ref_status(element.ref.evidence, ev_map, context)
        if status != "ok":
            trace.append(TraceEntry(name, False, _REF_STATUS_REASON[status]))
            return None
        label = _clean_label(element.label, name, "label", trace)
        return element.model_copy(update={"label": label})

    if isinstance(element, Comparison):
        baseline_status = _ref_status(element.baseline.evidence, ev_map, context)
        current_status = _ref_status(element.current.evidence, ev_map, context)
        if baseline_status != "ok" or current_status != "ok":
            bad = baseline_status if baseline_status != "ok" else current_status
            trace.append(TraceEntry(name, False, _REF_STATUS_REASON[bad]))
            return None
        label = _clean_label(element.label, name, "label", trace)
        return element.model_copy(update={"label": label})

    if isinstance(element, Trend):
        status = _ref_status(element.evidence, ev_map, context)
        if status != "ok":
            trace.append(TraceEntry(name, False, _REF_STATUS_REASON[status]))
            return None
        descriptor = ev_map[element.evidence.handle].field(element.evidence.field)
        if descriptor is None or descriptor.kind != FieldKind.SERIES:
            trace.append(TraceEntry(name, False, "field is not a series"))
            return None
        label = _clean_label(element.label, name, "label", trace)
        return element.model_copy(update={"label": label})

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
        if label_field is not None:
            label_descriptor = evidence.field(label_field)
            if label_descriptor is None:
                trace.append(TraceEntry(f"{name}.label_field", False, "field not described by this evidence"))
                label_field = None
            elif label_descriptor.pii and not context.needs_contact_details:
                trace.append(TraceEntry(f"{name}.label_field", False, "pii field stripped"))
                label_field = None
        limit = element.limit
        if limit > MAX_COLLECTION_ROWS and not context.explicit_list_request:
            trace.append(TraceEntry(f"{name}.limit", False, f"reduced to the attention budget of {MAX_COLLECTION_ROWS} rows"))
            limit = MAX_COLLECTION_ROWS
        return element.model_copy(update={"label_field": label_field, "limit": limit})

    if isinstance(element, Proposal):
        if element.action_ref not in context.known_action_refs:
            trace.append(TraceEntry(name, False, "action_ref does not identify an existing action"))
            return None
        label = _clean_label(element.label, name, "label", trace)
        return element.model_copy(update={"label": label})

    if isinstance(element, Question):
        kept_refs = _filter_refs(element.evidence, ev_map, context, f"{name}.evidence", trace)
        if element.evidence and not kept_refs:
            trace.append(TraceEntry(name, False, "no evidence bound to this session"))
            return None
        reason = _display_text_reason(element.text, kept_refs, ev_map)
        if reason is not None:
            trace.append(TraceEntry(name, False, reason))
            return None
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

    answer_kept_refs = _filter_refs(plan.answer.evidence, ev_map, context, "answer.evidence", trace)

    clean_lines: list[str] = []
    for index, line in enumerate(plan.answer.lines):
        reason = _display_text_reason(line, answer_kept_refs, ev_map)
        if reason is None:
            clean_lines.append(line)
        else:
            trace.append(TraceEntry(f"answer.lines:{index}", False, reason))
    if not clean_lines:
        clean_lines = [_FALLBACK_ANSWER_LINE]

    kept_answer: Answer = plan.answer.model_copy(update={"evidence": answer_kept_refs, "lines": clean_lines})
    trace.append(TraceEntry("answer", True, "the answer is always kept"))

    survivors: list[tuple[int, Any]] = []
    for index, element in enumerate(plan.elements):
        name = f"{element.kind}:{index}"
        if not element.justification.strip():
            trace.append(TraceEntry(name, False, "no justification"))
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
