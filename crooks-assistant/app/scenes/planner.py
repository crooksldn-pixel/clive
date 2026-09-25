"""The scene planner: a scene plan for every turn, by rules (Generative UI V1, objective 3a).

`plan_scene(question, answer, calls, context)` proposes a ScenePlan for one turn from what the
turn itself read and nothing else: its tool results, made into evidence through the registered
descriptors (app/scenes/descriptors.py). No model is asked, and nothing in the plan depends on
when it is made, so the same turn always gives the same plan:

- the turn's answer is the Answer;
- a Collection only when the question asks to see a list;
- a Finding only where a read carries a reason for attention — a signal the reads already
  derive (someone waiting on a reply from us, an attention line on a record) — and never for
  a source merely because it was read;
- everything else is reachable through the drill-down the validator attaches.

A planner is anything that is a `Planner`. The model-proposed planner in
docs/product-memory/GENERATIVE_UI_V1.md takes the same four arguments and returns the same
ScenePlan, and `scene_for_turn` takes it in place of this one. Whatever a planner proposes,
app/scenes/validate.py decides what may be shown.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.scenes.evidence import DEFAULT, MAX_RECORDS, Evidence, Kind, Registry, lookup
from app.scenes.payload import scene_payload
from app.scenes.scene import Answer, Collection, FieldRef, Finding, ScenePlan
from app.scenes.validate import FALLBACK_ANSWER, SceneContext, asks_for_list, validate_scene

# (the question, the turn's answer, the turn's tool calls, what the request allows) → a plan.
Planner = Callable[[str, str, Sequence[Any], SceneContext], ScenePlan]

# What the schema holds: an Answer of at most this many characters, and this many elements.
MAX_ANSWER_CHARS = 280
MAX_ELEMENTS = 12
# A list shows at most this many columns, chosen in the order its read describes them.
MAX_COLUMNS = 5
MAX_ROWS = 50

ANSWER_WHY = "The answer to what was asked."
LIST_WHY = "The request asked to see a list."
WAITING_WHY = "A read found someone waiting on a reply from us."
ATTENTION_WHY = "A read carries a reason for the owner's attention."

# The derived signals that someone is waiting on us, by field name: a count of them on the
# whole result, or a yes on the result or on one of its records.
WAITING_FIELDS = ("needs_reply", "awaiting_reply")
# An attention line's level, as the reads write it. Green is context, not attention.
_ATTENTION = {
    "red": ("ACTION_REQUIRED", "Something here needs your attention now."),
    "amber": ("RISK", "Something here may need your attention."),
}
_LEVELS = ("red", "amber", "green")
_RANK = {s: n for n, s in enumerate(("ACTION_REQUIRED", "DECISION_REQUIRED", "RISK", "UNCERTAINTY", "LIMITATION", "CONTEXT"))}
# An id says nothing to the owner, and a series is a Trend, not a column.
_NOT_COLUMNS = frozenset({Kind.LINK, Kind.SERIES})
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


# ----------------------------------------------------------------------- evidence


def turn_evidence(
    calls: Sequence[Any] | None, *, session_id: str | None, observed_at: datetime | None = None, registry: Registry = DEFAULT,
) -> tuple[Evidence, ...]:
    """The turn's reads as evidence, through their registered descriptors alone. Each is known
    by the call's place in the turn ("ev1", "ev2", …), so a planner and the validator that
    checks it name the same read the same way. A failed call, a write and a read with no
    descriptors are not evidence."""
    return tuple(ev for ev, _ in _reads(calls, session_id, observed_at, registry))


def _reads(
    calls: Sequence[Any] | None, session_id: str | None, observed_at: datetime | None, registry: Registry,
) -> Iterator[tuple[Evidence, Mapping[str, Any]]]:
    for index, call in enumerate(calls or ()):
        name = str(getattr(call, "name", "") or "")
        result = getattr(call, "result", None)
        if not getattr(call, "ok", False) or not isinstance(result, Mapping) or registry.get(name) is None:
            continue
        args = getattr(call, "args", None)
        try:
            ev = registry.to_evidence(
                name, result, handle=f"ev{index + 1}", args=args if isinstance(args, Mapping) else None,
                observed_at=observed_at, session_id=session_id,
            )
        except (AttributeError, TypeError, ValueError, ArithmeticError):
            # A result its descriptors cannot describe is not evidence; the turn's other reads are.
            continue
        yield ev, result


# -------------------------------------------------------------------------- plan


def plan_scene(question: str, answer: str, calls: Sequence[Any], context: SceneContext) -> ScenePlan:
    """The scene this turn's own reads support, by rule. Deterministic: the same question,
    answer and reads always give the same plan."""
    reads = list(_reads(calls, context.session_id, None, DEFAULT))
    elements: list[Collection | Finding] = []
    if context.list_requested or asks_for_list(question):
        # What was asked for goes first; the findings beside it earn what room is left.
        listed = _collection([ev for ev, _ in reads], context)
        if listed is not None:
            elements.append(listed)
    findings = [f for ev, raw in reads for f in _findings(ev, raw)]
    # Most significant first; within a significance, in the order the turn read them.
    findings.sort(key=lambda f: _RANK[f.significance])
    elements.extend(findings)
    return ScenePlan(
        answer=Answer(text=_answer_text(answer), justification=ANSWER_WHY),
        elements=elements[:MAX_ELEMENTS],
    )


def _answer_text(answer: str) -> str:
    """The turn's answer as an Answer can hold it: one line, and when it is longer than an
    Answer, the whole sentences that fit. What it says is the validator's to judge."""
    text = " ".join(str(answer or "").split())
    if not text:
        return FALLBACK_ANSWER
    if len(text) <= MAX_ANSWER_CHARS:
        return text
    ends = [m.end() for m in _SENTENCE_END.finditer(text) if m.end() <= MAX_ANSWER_CHARS]
    if ends:
        return text[: ends[-1]]
    return text[: MAX_ANSWER_CHARS - 1].rsplit(" ", 1)[0].rstrip() + "…"


def _collection(evidence: Sequence[Evidence], context: SceneContext) -> Collection | None:
    """The read with the most rows (the first, on a tie), as a bounded list of the columns
    that may be shown and have a value to show."""
    ev = max((e for e in evidence if e.records), key=lambda e: len(e.records), default=None)
    if ev is None:
        return None
    limit = max(1, min(len(ev.records), context.list_rows, MAX_ROWS))
    shown = ev.records[:limit]
    columns = [
        d.name for d in ev.fields
        if not d.pii and d.kind not in _NOT_COLUMNS and any(r.values.get(d.name) is not None for r in shown)
    ][:MAX_COLUMNS]
    if not columns:
        return None
    return Collection(evidence=ev.handle, columns=columns, limit=limit, justification=LIST_WHY)


def _findings(ev: Evidence, raw: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    waiting = _waiting(ev)
    if waiting is not None:
        out.append(waiting)
    levels = set(_levels(ev.tool, raw))
    for level, (significance, text) in _ATTENTION.items():
        if level in levels:
            out.append(Finding(significance=significance, text=text, evidence=[ev.handle], justification=ATTENTION_WHY))
            break
    return out


def _waiting(ev: Evidence) -> Finding | None:
    """Someone waiting on a reply from us, as the read counted it or flagged it."""
    for name in WAITING_FIELDS:
        d = ev.descriptor(name, fact=True)
        value = ev.facts.get(name)
        if d is not None and d.kind is Kind.COUNT and isinstance(value, int) and value > 0:
            return Finding(
                significance="ACTION_REQUIRED", text="Waiting on a reply from us: {0}.",
                values=[FieldRef(evidence=ev.handle, field=name)], evidence=[ev.handle], justification=WAITING_WHY,
            )
    for name in WAITING_FIELDS:
        fact, row = ev.descriptor(name, fact=True), ev.descriptor(name)
        flagged = (fact is not None and fact.kind is Kind.STATUS and ev.facts.get(name) == "yes") or (
            row is not None and row.kind is Kind.STATUS and any(r.values.get(name) == "yes" for r in ev.records)
        )
        if flagged:
            return Finding(
                significance="ACTION_REQUIRED", text="Someone is waiting on a reply from us.",
                evidence=[ev.handle], justification=WAITING_WHY,
            )
    return None


def _levels(tool: str, raw: Mapping[str, Any]) -> Iterator[str]:
    """The levels of the attention lines a read already carries — on the whole result or on
    its records, where the read found them — and of any record that is itself one."""
    spec = DEFAULT.get(tool)
    if spec is None:
        return
    data = spec.extract(raw) if spec.extract is not None else raw
    found = lookup(data, spec.records) if spec.records else None
    rows: list[Mapping[str, Any]] = []
    if isinstance(found, Mapping):
        rows = [found]
    elif isinstance(found, (list, tuple)):
        rows = [r for r in found if isinstance(r, Mapping)][:MAX_RECORDS]
    for holder in (data, *rows):
        lines = holder.get("attention")
        for line in lines if isinstance(lines, (list, tuple)) else ():
            if isinstance(line, Mapping) and line.get("title"):
                # A line with no level of its own is amber, as the cards have always drawn it.
                yield line.get("level") if line.get("level") in _LEVELS else "amber"
        if holder is not data and holder.get("level") in _ATTENTION and (holder.get("headline") or holder.get("title")):
            yield holder["level"]


# ------------------------------------------------------------------------- turn


def scene_for_turn(
    question: str, answer: str, calls: Sequence[Any] | None, *, session_id: str,
    planner: Planner | None = None, observed_at: datetime | None = None,
) -> dict[str, Any]:
    """One turn's scene as the renderer draws it, with the decision trace beside it: planned,
    validated against the turn's own evidence and resolved for display. Whatever a planner
    raises is raised; what a failure costs is the caller's to decide."""
    context = SceneContext.for_request(question, session_id=session_id or None)
    observed_at = observed_at or datetime.now(UTC)
    evidence = turn_evidence(calls, session_id=context.session_id, observed_at=observed_at)
    plan = (planner or plan_scene)(question, answer, list(calls or ()), context)
    scene, trace = validate_scene(plan, evidence, context)
    return {
        **scene_payload(scene, evidence, now=observed_at),
        "trace": [{"target": e.target, "decision": e.decision, "reason": e.reason} for e in trace],
    }
