"""Deciding what a scene may show. Pure functions: no I/O, no clock, no model.

`validate_scene(plan, evidence, context)` takes a proposed ScenePlan, the evidence this
session's reads produced and what the request allows, and returns the scene that may be shown
with a trace of every decision. It refuses any value not bound to this session's evidence,
drops elements with no justification, strips pii unless the task needs contact details — a
field marked pii, and any value that is an email address or a phone number whatever its field
is called — keeps
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
    Record,
    Series,
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
# ...and prose is only words a scene may use, so it cannot carry a name or a place a plan
# makes up — a street, a town, a person, a business — whatever form it is written in: the
# vocabulary is closed, and a value is shown from evidence, through a slot, or not at all. A
# capital is allowed only where a sentence starts ("I" aside), since a capital within one is a
# name. The words are the plain words of an answer about a shop, with no street or place word
# and no connector's words; an ordinary word that is also someone's name ("will", "may") is
# the one thing a vocabulary cannot tell apart, and written as a name, capitalised within a
# sentence, it is refused.
PROSE_WORDS = frozenset("""
a an the and or but nor so yet if then than that this these those there here it its itself
they them their theirs themselves we us our ours ourselves you your yours yourself i me my
mine myself he him his she her hers who whom whose which what whatever when whenever where
wherever why how whether while whilst as at by for from in into of off on onto out over under
up down with within without about above across after against along among around before behind
below beneath beside besides between beyond during except inside near outside past per since
through throughout till to toward towards until upon via not no none nobody nothing nowhere
neither either each every everyone everybody everything everywhere all any anyone anybody
anything anywhere some someone somebody something somewhere both few fewer less least more
most much many several such own other others another same only just also even still already
again ever never always often sometimes usually rather quite very too enough almost nearly
roughly instead perhaps maybe probably possibly otherwise however therefore although though
because unless yes please thanks
be am is are was were been being have has had having do does did done doing will would shall
should can could may might must need ought cannot can't don't doesn't didn't isn't aren't
wasn't weren't won't wouldn't shouldn't couldn't haven't hasn't hadn't mustn't i'm i've i'll
i'd we're we've we'll we'd you're you've you'll you'd they're they've they'll they'd
go goes went gone get got gotten make made take took taken give gave given keep kept want ask
tell told say said see saw seen show shown know knew known think thought seem look mean meant
help come came wait expect happen start stop finish arrive leave left move hold held put run
ran use work matter decide choose chose chosen confirm approve review chase follow handle sort
fix resolve raise flag remain stay buy bought sell sold order pay paid read write wrote written
send sent receive answer reply check find found search try tried let call reach cover mention
note list add remove include miss lose lost gain rise risen fall fell fallen drop grow grew
grown increase decrease change compare improve slow plan draft prepare update reopen cancel
refund return exchange ship dispatch deliver fulfil fulfill track pack earn spend spent cost
owe carry lead led
owner customer buyer shopper person people team staff supplier visitor visit traffic audience
item line product variant size colour color stock price sale sales revenue income profit
margin money amount total value budget payment charge discount tax shipping shipment delivery
fulfilment fulfillment tracking parcel courier package postage label status email mail message
thread inbox subject contact address phone detail details store shop site website page listing
catalogue range trend rate share average growth percentage quantity count number figure series
data evidence result finding problem issue question reason context information word kind type
way thing part rest point case sentence action decision risk limitation interest attention
priority proposal job task step request complaint query queries backlog delay session record
row field column table chart summary advertising advert marketing promotion click conversion
week weekend month year day hour minute morning afternoon evening night today tonight
yesterday tomorrow time period date ago now
new newer newest old older oldest big bigger biggest small smaller smallest large larger
largest good better best bad worse worst great poor strong stronger strongest weak weaker
weakest slower slowest fast faster fastest quick quicker quickest high higher highest low
lower lowest long longer longest short shorter shortest early earlier earliest late later
latest recent soon next previous prior current last usual unusual normal typical steady stable
similar different main key whole entire full empty partial complete incomplete missing
available unavailable ready due overdue open closed pending unpaid cancelled canceled urgent
important worrying worried likely unlikely possible certain uncertain unclear clear sure unsure
safe risky busy quiet right wrong fine okay well barely mostly largely slightly sharply
steadily daily weekly monthly yearly ahead behind together apart away back forward first
second outstanding unanswered unread unfulfilled
""".split())
# The marks prose may use between its words.
_PUNCTUATION = frozenset(".,;:!?'’‘\"“”()-–—…")
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_SENTENCE_END = frozenset(".!?:")
_INFLECTIONS = (("ies", "y"), ("ied", "y"), ("es", ""), ("s", ""), ("ed", ""), ("ed", "e"), ("d", ""),
                ("ing", ""), ("ing", "e"), ("ly", ""))
# A value can be a contact detail whatever its field is called: a sender with no display name
# is their email address, and a customer with no name is known by their email address or phone
# number. Such a value is as personal as a field marked pii, and is stripped the same way. An
# address can be quoted, a domain literal or in any script, so this fails closed: any value
# with an at sign in it, in any of its forms, is taken for an email address.
_AT_SIGNS = frozenset("@＠﹫")
_PHONE = re.compile(r"(?<![\w/-])\+?\(?\d[\d ().-]{7,}\d(?![\w/-])")
_PHONE_DIGITS = 9
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
        # A reference, not the evidence: what was read, when, and its summary, which is made
        # of registered words only and so has no contact details in it, whatever was asked.
        drilldown = DrillDown(tuple(
            Source(ev.handle, ev.tool, ev.query, ev.observed_at, len(ev.records)) for ev in pool.values()
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


def _contact(d: FieldDescriptor, value: object) -> bool:
    """Whether a value is, or has in it, an email address or — in a name or in words — a
    phone number, whatever its descriptor says."""
    if not isinstance(value, str):
        return False
    if any(c in _AT_SIGNS for c in value):
        return True
    return d.kind in (Kind.PERSON, Kind.TEXT) and any(
        sum(c.isdigit() for c in m.group()) >= _PHONE_DIGITS for m in _PHONE.finditer(value)
    )


def _bound(ev: Evidence, record: str | None, d: FieldDescriptor, value: object, context: SceneContext) -> Bound:
    """A value of evidence as it may be shown; nothing personal unless the task needs it."""
    contact = _contact(d, value)
    if not context.contact_details:
        if d.pii:
            raise _Refused(f"{d.name} is pii and the task does not need contact details")
        if contact:
            raise _Refused(f"{d.name} holds a contact detail, which is pii, and the task does not need contact details")
    return Bound(evidence=ev.handle, record=record, field=d.name, kind=d.kind, label=d.label, value=value, pii=d.pii or contact, unit=d.unit)


def _bind(ref, pool: Mapping[str, Evidence], context: SceneContext) -> Bound:
    """The value a reference points at, or the reason it may not be shown."""
    ev = _evidence(pool, ref.evidence)
    if ref.record is None:
        d = ev.descriptor(ref.field, fact=True)
        values = ev.facts
    else:
        record = ev.record(ref.record)
        if record is None:
            # The reference is the plan's own, and is not repeated.
            raise _Refused(f"{ev.handle} has no such record")
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
    """Words a scene may use, within its lines: every value through a slot, every bound value
    placed, no markup. What is refused is never repeated in the reason."""
    if not text.strip():
        raise _Refused("no words in the text, only whitespace")
    if len(text.strip().splitlines()) > lines:
        raise _Refused(f"more than {lines} line(s) of text")
    placed = {int(n) for n in SLOT.findall(text)}
    if any(n >= bound for n in placed):
        raise _Refused("a slot in the text has no value bound to it")
    # A slot is three characters, so the rest keeps every word where it is in the text.
    rest = SLOT.sub("   ", text)
    if _MARKUP.search(rest):
        raise _Refused("markup in the text")
    if _NUMBER.search(rest):
        raise _Refused("a number in the text that is not bound to evidence")
    if _ADDRESS.search(rest):
        raise _Refused("an email or web address in the text that is not bound to evidence")
    _words(text, rest)
    if len(placed) != bound:
        raise _Refused("a bound value is not placed in the text")


def _words(text: str, rest: str) -> None:
    """Every word one a scene may use, capitalised only where a sentence starts (a word after
    a slot does not start one)."""
    between = _WORD.sub(" ", rest)
    if any(not c.isspace() and c not in _PUNCTUATION for c in between):
        raise _Refused("a mark in the text that is not a word or punctuation")
    for match in _WORD.finditer(rest):
        word = match.group()
        if word in ("I", "I'm", "I’m", "I've", "I’ve", "I'll", "I’ll", "I'd", "I’d"):
            continue
        before = text[: match.start()].rstrip().rstrip("\"'’‘“(").rstrip()
        starts = not before or before[-1] in _SENTENCE_END
        if any(c.isupper() for c in word[1:]) or (word[0].isupper() and not starts):
            raise _Refused("a capitalised name or place in the text that is not bound to evidence")
        if not _known(word):
            raise _Refused("a word in the text a scene may not use: a name, a place or any other value is bound to evidence")


def _known(word: str) -> bool:
    """Whether a word is in PROSE_WORDS, as it is or as a plural, a past, an -ing or an -ly."""
    word = word.lower().replace("’", "'")
    if word.endswith("'s"):
        word = word[:-2]
    if word in PROSE_WORDS:
        return True
    for suffix, back in _INFLECTIONS:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            stem = word[: -len(suffix)] + back
            if stem in PROSE_WORDS:
                return True
            # A doubled consonant: shipped, planning.
            if not back and len(stem) > 2 and stem[-1] == stem[-2] and stem[:-1] in PROSE_WORDS:
                return True
    return False


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


def _columns(
    target: str, ev: Evidence, names: list[str], context: SceneContext, trace: _Trace, records: Iterable[Record],
) -> list[FieldDescriptor]:
    """The chosen fields that may be shown as columns of `records`, the rows to be shown;
    every one left out is in the trace."""
    records = tuple(records)
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
        elif not context.contact_details and any(_contact(d, r.values.get(d.name)) for r in records):
            trace.add(target, "reduced", f"{name}: a value in it is a contact detail; pii stripped, the task does not need contact details")
        else:
            kept.append(d)
    return kept


def _row_cap(context: SceneContext) -> int:
    return context.list_rows if context.list_requested else context.collection_rows


def _rows_allowed(target: str, asked: int, context: SceneContext, trace: _Trace) -> int:
    cap = _row_cap(context)
    if asked <= cap:
        return asked
    why = "the most a list shows" if context.list_requested else "the most shown unless the request asks to see a list"
    trace.add(target, "reduced", f"rows {asked} → {cap}: {why}")
    return cap


def _entity(target: str, element: Entity, pool: Mapping[str, Evidence], context: SceneContext, trace: _Trace) -> Shown:
    ev = _evidence(pool, element.evidence)
    record = ev.record(element.record)
    if record is None:
        raise _Refused(f"{ev.handle} has no such record")
    fields = _columns(target, ev, element.fields, context, trace, (record,))
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
    columns = _columns(target, ev, element.columns, context, trace, ev.records[: min(element.limit, _row_cap(context))])
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
    dated = sorted((r for r in ev.records if r.values.get(at.name) is not None), key=lambda r: r.values[at.name])
    shown = dated[-min(element.limit, _row_cap(context)):]
    # The time is shown as much as the label is, and is as personal as its descriptor says.
    if not _columns(target, ev, [element.at], context, trace, shown):
        raise _Refused("its time may not be shown")
    labels = _columns(target, ev, [element.label], context, trace, shown)
    if not labels:
        raise _Refused("its label may not be shown")
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
