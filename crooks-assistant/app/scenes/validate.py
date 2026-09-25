"""Deciding what a scene may show. Pure functions: no I/O, no clock, no model.

`validate_scene(plan, evidence, context)` takes a proposed ScenePlan, the evidence this
session's reads produced and what the request allows, and returns the scene that may be shown
with a trace of every decision. It refuses any value not bound to this session's evidence,
drops elements with no justification, strips pii unless the task needs contact details, keeps
within an attention budget and always keeps the Answer. The screen shows findings, not
sources: a list of rows is kept only beside a finding about them, or when the request asked
for a list. When only the Answer survives, the scene is the Answer and a drill-down reference
to the evidence it checked — never the evidence itself.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.scenes.evidence import (
    QUANTITIES,
    Evidence,
    FieldDescriptor,
    Kind,
    Money,
    Series,
    summarise,
)
from app.scenes.scene import (
    SLOT,
    Answer,
    Bound,
    Collection,
    Comparison,
    Decision,
    DrillDown,
    Entity,
    Finding,
    Measure,
    Proposal,
    Question,
    Scene,
    ScenePlan,
    Shown,
    Source,
    Timeline,
    TraceEntry,
    Trend,
)

# One Answer, and at most this many further elements beside it.
ATTENTION_BUDGET = 3
# A Collection or Timeline shows at most this many rows, unless the request asked for a list.
COLLECTION_ROWS = 8
# ...and at most this many when it did.
LIST_ROWS = 25

# The Answer is always kept. When what was planned cannot be shown, it says only this, and the
# drill-down beneath it carries what was checked.
FALLBACK_ANSWER = "I can't put that in a sentence from what I checked; what I checked is below."
# ...and when only its justification cannot be shown, this stands in for it.
FALLBACK_JUSTIFICATION = "The answer to what was asked."

# Prose is words. A digit, a currency sign, a number in words, a fraction or a multiple is a
# value, and a value comes from evidence through a slot; so does an email or web address.
# Markup is the renderer's to add, never the plan's.
_NUMBER = re.compile(
    r"\d|[£$€¥¢%‰½⅓⅔¼¾⅛]"
    r"|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    r"|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fourty|fifty|sixty|seventy|eighty|ninety"
    r"|hundreds?|thousands?|millions?|billions?|trillions?|dozens?|nil|nought|naught"
    r"|half|halves|halve[ds]?|halving|thirds?|quarters?|fifths?|sixths?|sevenths?|eighths?|ninths?|tenths?"
    r"|double[ds]?|doubling|twice|triple[ds]?|tripling|treble[ds]?|thrice|quadruple[ds]?"
    r"|(?:two|three|four|five|six|seven|eight|nine|ten|twenty|hundred|thousand|many|multi)-?fold"
    r"|percent|per\s+cent|pct)\b",
    re.I,
)
_ADDRESS = re.compile(r"@|\b[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")
_MARKUP = re.compile(r"<[^>]*>|&#?[A-Za-z0-9]+;|https?://|www\.|[`*_#|\\<>\[\]{}~^]")
_LIST_ASK = re.compile(
    r"\b(?:list|lists|listing)\b|\bshow (?:me )?(?:all|every|the whole)\b|\ball of (?:them|the)\b", re.I,
)


def asks_for_list(request: str) -> bool:
    """Whether the owner's words explicitly ask to see a list."""
    return bool(_LIST_ASK.search(str(request or "")))


@dataclass(frozen=True, slots=True)
class SceneContext:
    """What the request allows. `contact_details` is true only when the task itself needs an
    address, a phone number or an email address; `actions` are the ids of the actions that
    already exist this session, the only ones a Proposal may name. `session_id` is this
    session's: without it no evidence is this session's, and nothing is bound."""

    request: str = ""
    session_id: str | None = None
    list_requested: bool = False
    contact_details: bool = False
    actions: frozenset[str] = frozenset()
    max_elements: int = ATTENTION_BUDGET
    collection_rows: int = COLLECTION_ROWS
    list_rows: int = LIST_ROWS

    @classmethod
    def for_request(cls, request: str, **kwargs) -> SceneContext:
        return cls(request=request, list_requested=asks_for_list(request), **kwargs)


class _Refused(Exception):
    """Why an element (or a value in it) cannot be shown."""


class _Trace:
    def __init__(self) -> None:
        self.entries: list[TraceEntry] = []

    def add(self, target: str, decision: Decision, reason: str) -> None:
        self.entries.append(TraceEntry(target, decision, reason))


def validate_scene(
    plan: ScenePlan | Mapping, evidence: Iterable[Evidence] | Mapping[str, Evidence], context: SceneContext | None = None,
) -> tuple[Scene, tuple[TraceEntry, ...]]:
    """The scene that may be shown, and every decision that made it.

    A plan that is not a ScenePlan is parsed as one first; a plan of the wrong shape raises
    pydantic's ValidationError and nothing is shown from it. Everything after that is a
    decision about an element, recorded in the trace, and never an error."""
    if not isinstance(plan, ScenePlan):
        plan = ScenePlan.model_validate(plan)
    context = context or SceneContext()
    trace = _Trace()
    pool = _session_evidence(evidence, context, trace)
    answer, replaced = _answer(plan.answer, pool, context, trace)
    candidates: list[tuple[str, Shown]] = []
    for index, element in enumerate(plan.elements):
        target = f"elements[{index}] {element.type}"
        try:
            candidates.append((target, _check(target, element, pool, context, trace)))
        except _Refused as refused:
            trace.add(target, "dropped", str(refused))
    kept = _attention(candidates, context, trace)
    for target, shown in kept:
        trace.add(target, "kept", shown.element.justification.strip())
    drilldown = None
    if (not kept or replaced) and pool:
        # A reference, not the evidence: what was read, when, and a summary with no contact
        # details in it, whatever the request allows.
        drilldown = DrillDown(tuple(
            Source(ev.handle, ev.tool, summarise(ev.query, ev.vocabulary()), ev.observed_at, len(ev.records)) for ev in pool.values()
        ))
        why = "the planned answer was replaced" if replaced else "only the answer is shown"
        trace.add("drilldown", "kept", f"{why}; a reference to the {len(pool)} evidence it checked, not the evidence")
    return Scene(answer, tuple(shown for _, shown in kept), drilldown), tuple(trace.entries)


# ----------------------------------------------------------------------- evidence


def _session_evidence(evidence: Iterable[Evidence] | Mapping[str, Evidence], context: SceneContext, trace: _Trace) -> dict[str, Evidence]:
    pool: dict[str, Evidence] = {}
    for ev in (evidence.values() if isinstance(evidence, Mapping) else evidence):
        if not isinstance(ev, Evidence):
            raise TypeError("Evidence is given as Evidence objects.")
        target = f"evidence {ev.handle}"
        # Provenance fails closed: evidence is this session's only when both carry the same id.
        if not context.session_id:
            trace.add(target, "ignored", "no session is established for this scene; nothing may be bound to it")
        elif not ev.session_id:
            trace.add(target, "ignored", "it carries no session, so it is not from this session; nothing may be bound to it")
        elif ev.session_id != context.session_id:
            trace.add(target, "ignored", "not from this session; nothing may be bound to it")
        elif ev.handle in pool:
            trace.add(target, "ignored", "a second evidence with the same handle; the first stands")
        else:
            pool[ev.handle] = ev
    return pool


def _evidence(pool: Mapping[str, Evidence], handle: str) -> Evidence:
    ev = pool.get(handle)
    if ev is None:
        raise _Refused(f"{handle} is not evidence from this session")
    return ev


def _bound(ev: Evidence, record: str | None, d: FieldDescriptor, value: object, context: SceneContext) -> Bound:
    """A value of evidence as it may be shown; nothing personal unless the task needs it."""
    if d.pii and not context.contact_details:
        raise _Refused(f"{d.name} is pii and the task does not need contact details")
    return Bound(evidence=ev.handle, record=record, field=d.name, kind=d.kind, label=d.label, value=value, pii=d.pii, unit=d.unit)


def _bind(ref, pool: Mapping[str, Evidence], context: SceneContext) -> Bound:
    """The value a reference points at, or the reason it may not be shown."""
    ev = _evidence(pool, ref.evidence)
    if ref.record is None:
        d = ev.descriptor(ref.field, fact=True)
        values = ev.facts
    else:
        record = ev.record(ref.record)
        if record is None:
            raise _Refused(f"{ev.handle} has no record {ref.record}")
        d = ev.descriptor(ref.field)
        values = record.values
    if d is None:
        raise _Refused(f"{ev.handle} has no field {ref.field}")
    if d.pii and not context.contact_details:
        raise _Refused(f"{ref.field} is pii and the task does not need contact details")
    value = values.get(ref.field)
    if value is None:
        raise _Refused(f"{ev.handle} has no value for {ref.field}")
    return _bound(ev, ref.record, d, value, context)


# -------------------------------------------------------------------------- prose


def _prose(text: str, bound: int, lines: int = 1) -> None:
    """Words only, within its lines: every value through a slot, every bound value placed, no
    markup."""
    if not text.strip():
        raise _Refused("no words in the text, only whitespace")
    if len(text.strip().splitlines()) > lines:
        raise _Refused(f"more than {lines} line(s) of text")
    placed = {int(n) for n in SLOT.findall(text)}
    if any(n >= bound for n in placed):
        raise _Refused("a slot in the text has no value bound to it")
    rest = SLOT.sub(" ", text)
    if _MARKUP.search(rest):
        raise _Refused("markup in the text")
    if _NUMBER.search(rest):
        raise _Refused("a number in the text that is not bound to evidence")
    if _ADDRESS.search(rest):
        raise _Refused("an email or web address in the text that is not bound to evidence")
    if len(placed) != bound:
        raise _Refused("a bound value is not placed in the text")


def _one_line(text: str) -> bool:
    return len(text.strip().splitlines()) == 1


def _justification(text: str) -> str:
    """Why an element is shown: one line of plain words, with no markup and no value in it,
    since it is kept beside the element and in the trace."""
    if not isinstance(text, str) or not _one_line(text):
        raise _Refused("no one-line justification")
    try:
        _prose(text, 0)
    except _Refused as refused:
        raise _Refused(f"its justification is not plain words: {refused}") from None
    return text.strip()


# ------------------------------------------------------------------------ elements


def _answer(answer: Answer, pool: Mapping[str, Evidence], context: SceneContext, trace: _Trace) -> tuple[Shown, bool]:
    try:
        _prose(answer.text, len(answer.values), 2)
        values = tuple(_bind(ref, pool, context) for ref in answer.values)
    except _Refused as refused:
        trace.add("answer", "replaced", f"{refused}; the answer is always kept, so it says only that what was checked is below")
        return Shown(Answer(text=FALLBACK_ANSWER, justification="The planned answer could not be shown as written.")), True
    try:
        reason = _justification(answer.justification)
    except _Refused as refused:
        trace.add("answer", "reduced", f"{refused}; the answer is always kept, so its justification is replaced")
        answer = answer.model_copy(update={"justification": FALLBACK_JUSTIFICATION})
        reason = "the answer is always kept"
    trace.add("answer", "kept", reason)
    return Shown(answer, values), False


def _check(target: str, element, pool: Mapping[str, Evidence], context: SceneContext, trace: _Trace) -> Shown:
    _justification(element.justification)
    if isinstance(element, Finding):
        _prose(element.text, len(element.values))
        values = tuple(_bind(ref, pool, context) for ref in element.values)
        for handle in element.evidence:
            _evidence(pool, handle)
        if not element.evidence and not values:
            raise _Refused("a finding that cites no evidence")
        return Shown(element, values)
    if isinstance(element, Question):
        _prose(element.text, 0)
        for option in element.options:
            _prose(option, 0)
        return Shown(element)
    if isinstance(element, Proposal):
        if element.action not in context.actions:
            raise _Refused(f"{element.action} is not an existing action")
        return Shown(element)
    if isinstance(element, Measure):
        value = _bind(element.value, pool, context)
        if value.kind not in QUANTITIES:
            raise _Refused(f"{value.field} is {value.kind}, not a quantity")
        return Shown(element, (value,))
    if isinstance(element, Comparison):
        current, previous = _bind(element.current, pool, context), _bind(element.previous, pool, context)
        if current.kind not in QUANTITIES or current.kind != previous.kind:
            raise _Refused("a comparison is of two quantities of the same kind")
        if isinstance(current.value, Money) and current.value.currency != previous.value.currency:
            raise _Refused("a comparison of amounts in two currencies")
        return Shown(element, (current, previous))
    if isinstance(element, Trend):
        series = _bind(element.series, pool, context)
        if series.kind is not Kind.SERIES or not isinstance(series.value, Series):
            raise _Refused(f"{series.field} is {series.kind}, not a series")
        if len(series.value.points) < 2:
            raise _Refused(f"{series.field} has fewer than two points")
        return Shown(element, (series,))
    if isinstance(element, Entity):
        return _entity(target, element, pool, context, trace)
    if isinstance(element, Collection):
        return _collection(target, element, pool, context, trace)
    if isinstance(element, Timeline):
        return _timeline(target, element, pool, context, trace)
    raise _Refused(f"{element.type} is not a scene primitive")


def _columns(target: str, ev: Evidence, names: list[str], context: SceneContext, trace: _Trace) -> list[FieldDescriptor]:
    """The chosen fields that may be shown as columns; every one left out is in the trace."""
    kept: list[FieldDescriptor] = []
    for name in names:
        d = ev.descriptor(name)
        if d is None:
            trace.add(target, "reduced", f"{name}: {ev.handle} has no such field")
        elif d in kept:
            trace.add(target, "reduced", f"{name}: chosen twice, shown once")
        elif d.kind is Kind.SERIES:
            trace.add(target, "reduced", f"{name}: a series is shown as a Trend, not a column")
        elif d.pii and not context.contact_details:
            trace.add(target, "reduced", f"{name}: pii stripped; the task does not need contact details")
        else:
            kept.append(d)
    return kept


def _rows_allowed(target: str, asked: int, context: SceneContext, trace: _Trace) -> int:
    cap = context.list_rows if context.list_requested else context.collection_rows
    if asked <= cap:
        return asked
    why = "the most a list shows" if context.list_requested else "the most shown unless the request asks to see a list"
    trace.add(target, "reduced", f"rows {asked} → {cap}: {why}")
    return cap


def _entity(target: str, element: Entity, pool: Mapping[str, Evidence], context: SceneContext, trace: _Trace) -> Shown:
    ev = _evidence(pool, element.evidence)
    record = ev.record(element.record)
    if record is None:
        raise _Refused(f"{ev.handle} has no record {element.record}")
    fields = _columns(target, ev, element.fields, context, trace)
    if not fields:
        raise _Refused("no chosen field may be shown")
    names = [d.name for d in fields]
    if names != element.fields:
        element = element.model_copy(update={"fields": names})
    return Shown(element, rows=(tuple(_bound(ev, record.id, d, record.values.get(d.name), context) for d in fields),))


def _collection(target: str, element: Collection, pool: Mapping[str, Evidence], context: SceneContext, trace: _Trace) -> Shown:
    ev = _evidence(pool, element.evidence)
    if not ev.records:
        raise _Refused(f"{ev.handle} has no records to list")
    columns = _columns(target, ev, element.columns, context, trace)
    if not columns:
        raise _Refused("no chosen column may be shown")
    limit = _rows_allowed(target, element.limit, context, trace)
    names = [d.name for d in columns]
    if names != element.columns or limit != element.limit:
        element = element.model_copy(update={"columns": names, "limit": limit})
    rows = tuple(tuple(_bound(ev, r.id, d, r.values.get(d.name), context) for d in columns) for r in ev.records[:limit])
    return Shown(element, rows=rows)


def _timeline(target: str, element: Timeline, pool: Mapping[str, Evidence], context: SceneContext, trace: _Trace) -> Shown:
    ev = _evidence(pool, element.evidence)
    at = ev.descriptor(element.at)
    if at is None or at.kind is not Kind.DATETIME:
        raise _Refused(f"{element.at} is not a time in {ev.handle}")
    # The time is shown as much as the label is, and is as personal as its descriptor says.
    if not _columns(target, ev, [element.at], context, trace):
        raise _Refused("its time may not be shown")
    labels = _columns(target, ev, [element.label], context, trace)
    if not labels:
        raise _Refused("its label may not be shown")
    dated = sorted((r for r in ev.records if r.values.get(at.name) is not None), key=lambda r: r.values[at.name])
    if not dated:
        raise _Refused(f"{ev.handle} has no dated records")
    limit = _rows_allowed(target, element.limit, context, trace)
    if limit != element.limit:
        element = element.model_copy(update={"limit": limit})
    rows = tuple(
        (_bound(ev, r.id, at, r.values[at.name], context), _bound(ev, r.id, labels[0], r.values.get(labels[0].name), context))
        for r in dated[-limit:]
    )
    return Shown(element, rows=rows)


# ---------------------------------------------------------------------- attention


def _about(handle: str, findings: list[Shown]) -> bool:
    return any(handle in s.element.evidence or any(b.evidence == handle for b in s.values) for s in findings)


def _attention(candidates: list[tuple[str, Shown]], context: SceneContext, trace: _Trace) -> list[tuple[str, Shown]]:
    """Findings, not sources, within the budget. Plan order is the planner's priority."""
    listed = context.list_requested

    def sources_only(shown: Shown, findings: list[Shown]) -> bool:
        return not listed and isinstance(shown.element, (Collection, Timeline)) and not _about(shown.element.evidence, findings)

    findings = [s for _, s in candidates if isinstance(s.element, Finding)]
    survivors: list[tuple[str, Shown]] = []
    for target, shown in candidates:
        if sources_only(shown, findings):
            trace.add(target, "dropped", "lists a source with no finding about it; the screen shows findings, not sources")
        else:
            survivors.append((target, shown))
    budget = max(0, context.max_elements)
    for target, _ in survivors[budget:]:
        trace.add(target, "dropped", f"over the attention budget: the answer and at most {budget} more")
    kept_findings = [s for _, s in survivors[:budget] if isinstance(s.element, Finding)]
    kept: list[tuple[str, Shown]] = []
    for target, shown in survivors[:budget]:
        if sources_only(shown, kept_findings):
            trace.add(target, "dropped", "the finding it lists the rows of did not fit the attention budget")
        else:
            kept.append((target, shown))
    return kept
