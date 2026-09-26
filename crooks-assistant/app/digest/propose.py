"""Absorption proposals: what CLIVE proposes to take from each Unit, and nothing more.

Every proposal is proposed by CLIVE (model.PROPOSER) and decided by no one: deciding is the
owner's (model.DECIDER), later, as a new record in the ledger. Each says why — the relation
and the self-model entries it rests on, and the digest of the self-model it was made against —
states a hypothesis and the measure that would prove or drop it (in the reasoning: the
Absorption record has no fields of its own for them), and carries a removal handle naming
exactly what it would add. A proposal that adds nothing has an empty handle, as the model
requires of every target outside ADDING_TARGETS.

    unit kind                      target            what it would add
    procedure                      builder_skill     a skill folder
    rule, check                    review_check      a review-check rule id
    capability with an API         tool_connector    the registry entry, its module and tests
      contract tag (openapi,
      graphql, mcp), tagged read
    the same, tagged write or      tool_connector    the same, and marked as needing the owner:
      unknown (or neither)                           behind the action gate, owner-decided
    capability read from code      native_objective  an objective built natively (section 4 of
      (a function, module or                         the design: code is built natively, never
      command: no contract tag)                      registered as a tool, which would run it)
    interface with an API          tool_connector    a connector, its client module and tests,
      contract tag that extends                      marked as needing the owner
      what CLIVE has
    other interfaces               reference_only    nothing: a contract on its own is a pointer
    data_schema                    tool_connector    a read-only feed connector, module and tests
      (tagged personal)            reference_only    nothing: personal data is not fed anywhere
    knowledge that extends         product_memory    an entry citing its Source
    claim that extends             product_memory    the same, verified first
    knowledge or a claim that      reference_only    nothing: it would be mass without a use
      relates to nothing
    design_token                   design_system     a token set in the Generative UI's token
                                                     sheet (web/style.css), marked as needing
                                                     the owner: the look is the owner's
    pattern read by the design     design_system     a component folder beside the scene
      adapter (tagged design)                        renderer (web/components/<name>)
    any other pattern              native_objective  an objective built natively
    dependency, script, example    reference_only    nothing
    anything that overlaps         reference_only    nothing: CLIVE already has it
    anything the adapter could     reference_only    nothing
      not read (tagged unparsed)

Deterministic: the same units and relations give the same proposals, in reading order."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.digest.model import (
    MAX_REASONING,
    PROPOSER,
    UNIT_KINDS,
    Absorption,
    Addition,
    RemovalHandle,
    Unit,
    utc_now,
)
from app.digest.relate import Match, Relation

# Where an absorption would put what it adds, relative to the repository root.
SKILLS_DIR = ".claude/skills"
TOOLS_DIR = "crooks-assistant/app/tools"
CLIENTS_DIR = "crooks-assistant/app/clients"
TESTS_DIR = "crooks-assistant/tests"
GATE = "crooks-assistant/app/tools/gate.py"
# The Generative UI: every colour, font, radius, space and motion its scenes use is a token in
# this sheet (web/scenes.css says so), and web/scenes.js draws the scene primitives.
TOKEN_SHEET = "crooks-assistant/web/style.css"
COMPONENTS_DIR = "crooks-assistant/web/components"

NEEDS_OWNER = "Needs the owner"
VERIFY_FIRST = "verify first"
REFERENCE_KINDS = frozenset({"dependency", "script", "example"})
CONTRACT_TAGS = frozenset({"openapi", "graphql", "json_schema", "mcp", "asyncapi"})
DESIGN_TAG = "design"      # the design adapter's NAME, which it tags every Unit it reads with
MAX_SLUG = 40

_HYPOTHESIS_MEASURE = {
    "builder_skill": (
        "builders given this skill need fewer review rounds on the objectives it applies to.",
        "review rounds and findings on the next objectives that load the skill, against "
        "comparable objectives without it; kept only if still in use after 30 days.",
    ),
    "review_check": (
        "the check catches a class of defect that review misses today.",
        "findings it raises that the reviewer confirms, and its false positives, over the next "
        "ten reviews; dropped if it catches nothing real.",
    ),
    "tool_connector": (
        "the owner can do this through CLIVE instead of by hand.",
        "calls in real turns, the error rate and the owner's approve, edit and decline rates "
        "over 30 days; the suite stays green when it is removed.",
    ),
    "product_memory": (
        "CLIVE answers the questions this touches correctly, citing the entry.",
        "times the entry is cited in 30 days and any correction the owner makes to it; "
        "removed if it is never cited.",
    ),
    "native_objective": (
        "building this natively makes the surface it touches better than it is now.",
        "the objective's acceptance checks, screenshot review and the owner's verdict; what it "
        "adds is still in use after 30 days.",
    ),
    "design_system": (
        "the scenes that use it read better than they do now, inside the taste rules: no "
        "colour or font the owner has not approved.",
        "a before-and-after screenshot review of the scenes gallery (web/scenes-gallery.html) "
        "and the owner's verdict; removed if no scene uses it after 30 days.",
    ),
    "reference_only": (
        "a pointer costs nothing and lets a later objective, review or digestion find this.",
        "whether anything cites the pointer; nothing is added, so there is nothing to prove "
        "or drop.",
    ),
}


@dataclass(frozen=True)
class _Plan:
    target: str
    why: str
    additions: tuple[Addition, ...] = ()
    needs_owner: str = ""       # why the owner must decide it, when the owner must
    hypothesis: str = ""        # overrides the target's usual hypothesis when set
    measure: str = ""


def _a(word: str) -> str:
    return f"{'an' if word[:1] in 'aeiou' else 'a'} {word}"


def _slug(unit: Unit, separator: str) -> str:
    words = re.findall(r"[a-z0-9]+", unit.title.lower())
    base = separator.join(words)[:MAX_SLUG].strip(separator) or unit.kind
    return f"{base}{separator}{unit.id[5:13]}"


def _identifier(unit: Unit) -> str:
    """A Python module and tool name for the unit: digested_<words>_<id part>."""
    return f"digested_{_slug(unit, '_')}"


def _access(unit: Unit) -> str:
    tags = set(unit.tags)
    if "write" in tags:
        return "write"
    if "read" in tags:
        return "read"
    return "unknown"


def _entry(match: Match) -> str:
    named = "named by the unit; " if match.named else ""
    return f"{match.key} '{match.name[:80]}' ({named}score {match.score:.2f}" + (
        f"; shared terms: {', '.join(match.terms)})" if match.terms else ")"
    )


def _basis(relation: Relation) -> Match | None:
    return next((m for m in relation.matches if m.key == relation.basis), None)


def _related(relation: Relation) -> str:
    basis = _basis(relation)
    closest = ", ".join(f"{m.key} {m.score:.2f}" for m in relation.matches) or "none"
    if relation.relation == "overlap" and basis is not None:
        return f"overlaps what CLIVE already has: {_entry(basis)}"
    if relation.relation == "extends" and basis is not None:
        planned = "" if basis.present else ", which CLIVE plans or has thought of but does not have yet"
        return f"extends {_entry(basis)}{planned}"
    if relation.relation == "gap":
        return f"is a gap: nothing in CLIVE shares enough with it (closest: {closest})"
    if relation.unit_kind == "script":
        return f"is a script, which is only ever pointed at (closest: {closest})"
    return f"relates to nothing CLIVE has (closest: {closest})"


def _tool(unit: Unit) -> tuple[Addition, ...]:
    name = _identifier(unit)
    return (
        Addition("tool", name),
        Addition("file", f"{TOOLS_DIR}/{name}.py"),
        Addition("file", f"{TESTS_DIR}/test_{name}.py"),
    )


def _connector(unit: Unit) -> tuple[Addition, ...]:
    name = _identifier(unit)
    return (
        Addition("connector", name),
        Addition("file", f"{CLIENTS_DIR}/{name}.py"),
        Addition("file", f"{TESTS_DIR}/test_{name}.py"),
    )


def _reference(why: str) -> _Plan:
    return _Plan("reference_only", why)


def _plan(unit: Unit, relation: Relation) -> _Plan:
    kind, tags = unit.kind, set(unit.tags)
    if relation.relation == "overlap":
        basis = _basis(relation)
        name = f"{basis.key} '{basis.name[:80]}'" if basis else "it"
        return _reference(f"CLIVE already has {name}, so nothing is added; this is kept as a "
                          "pointer beside it.")
    if "unparsed" in tags:
        return _reference("The adapter could not read this, so there is nothing to absorb.")
    if kind in REFERENCE_KINDS:
        return _reference(f"{_a(kind).capitalize()} is only ever pointed at: nothing is taken "
                          "from it into CLIVE.")
    if relation.relation == "reference":
        return _reference(f"This {kind} relates to nothing CLIVE has; adding it would be mass "
                          "without a use, so it is kept as a pointer.")
    if kind == "procedure":
        return _Plan("builder_skill", "A procedure becomes a builder skill: a skill folder with a "
                     "provenance header citing this unit's Source.",
                     (Addition("skill", f"{SKILLS_DIR}/{_slug(unit, '-')}"),))
    if kind in ("rule", "check"):
        return _Plan("review_check", f"A {kind} becomes a review check: a rule in the reviewer's "
                     "rubric or an automated check.",
                     (Addition("check", f"review-check:{_slug(unit, '-')}"),))
    if kind == "capability" and not tags & CONTRACT_TAGS:
        return _Plan("native_objective", "A capability read from code is built natively as a "
                     "loop objective citing this unit's Source: another project's function, "
                     "module or command is never registered as a CLIVE tool, since calling it "
                     "would run that project's code.",
                     (Addition("objective", f"objective:{_slug(unit, '-')}"),))
    if kind == "capability":
        access = _access(unit)
        additions = _connector(unit) if "server" in tags else _tool(unit)
        if access == "read":
            return _Plan("tool_connector", "A capability that only reads becomes a registered "
                         "read tool with its tests.", additions)
        said = "writes" if access == "write" else "does not say whether it writes"
        return _Plan(
            "tool_connector", f"A capability that {said} becomes a registered tool only behind "
            "the action gate.", additions,
            needs_owner=f"it {said}, so it is registered only with a complete WriteSpec behind "
                        f"the action gate ({GATE}), every call is staged for the owner's tap, and "
                        "it is not absorbed without the owner's decision",
        )
    if kind == "interface":
        if relation.relation == "extends" and tags & CONTRACT_TAGS:
            return _Plan(
                "tool_connector", "An API contract that extends what CLIVE has becomes a "
                "connector built from it, with its tests.", _connector(unit),
                needs_owner="a connector brings a new credential and sends requests off the "
                            "host, and any write it offers goes behind the action gate "
                            f"({GATE}); both are the owner's to approve",
            )
        return _reference("A contract on its own is kept as a pointer; the capabilities that "
                          "use it are proposed on their own.")
    if kind == "data_schema":
        if "personal" in tags:
            return _reference("The dataset holds personal data, so it is not fed into CLIVE; "
                              "the owner can ask for it explicitly.")
        return _Plan("tool_connector", "A dataset's shape becomes a read-only business-memory "
                     "feed: a connector that reads it, with its tests.", _connector(unit))
    if kind == "knowledge":
        return _Plan("product_memory", "Knowledge that bears on CLIVE becomes a product-memory "
                     "entry citing its Source.",
                     (Addition("memory", f"product-memory:{unit.id}"),))
    if kind == "claim":
        return _Plan(
            "product_memory", f"A claim is its source's assertion, not a fact: {VERIFY_FIRST}, "
            "and only then a product-memory entry citing its Source.",
            (Addition("memory", f"product-memory:{unit.id}"),),
            hypothesis="the claim holds, and once verified it saves looking it up again.",
            measure="verified against its source or a test before it is entered; then times it "
                    "is cited in 30 days, and removed if never cited.",
        )
    if kind == "design_token":
        return _Plan(
            "design_system", "Design tokens become a token set in the Generative UI's token "
            f"sheet ({TOKEN_SHEET}), in one named block whose header cites this unit's Source.",
            (Addition("token_set", f"{TOKEN_SHEET}#{_slug(unit, '-')}"),),
            needs_owner="a token set changes how every scene that uses it looks, and CLIVE's "
                        "look is the owner's: the sheet takes no new colour or font without "
                        "the owner's say",
        )
    if kind == "pattern" and DESIGN_TAG in tags:
        return _Plan(
            "design_system", "A design pattern becomes a Generative UI component: a folder "
            f"beside the scene renderer ({COMPONENTS_DIR}) with a provenance header citing this "
            "unit's Source; no scene uses it until one is built to.",
            (Addition("component", f"{COMPONENTS_DIR}/{_slug(unit, '-')}"),),
        )
    if kind == "pattern":
        return _Plan("native_objective", "A code pattern is built natively as a loop objective, "
                     "citing this unit's Source.",
                     (Addition("objective", f"objective:{_slug(unit, '-')}"),))
    return _reference(f"No target takes {_a(kind)}.")   # pragma: no cover — every kind is above


def _reasoning(unit: Unit, relation: Relation, plan: _Plan, digest: str) -> str:
    hypothesis, measure = _HYPOTHESIS_MEASURE[plan.target]
    hypothesis, measure = plan.hypothesis or hypothesis, plan.measure or measure
    if plan.additions:
        taken = "; ".join(f"{a.kind} {a.ref}" for a in plan.additions)
        removal = (f"take out {taken} (the digest of each is recorded when it is written); "
                   "the suite stays green afterwards.")
    else:
        removal = "nothing is added, so there is nothing to remove."
    parts = [
        f"The {unit.kind} '{unit.title[:120]}' {_related(relation)}.",
        f"Target {plan.target}: {plan.why}",
    ]
    if plan.needs_owner:
        parts.append(f"{NEEDS_OWNER}: {plan.needs_owner}.")
    parts += [
        f"Hypothesis: {hypothesis}",
        f"Measure: {measure}",
        f"Removal: {removal}",
        f"Self-model {digest}. Proposed by CLIVE; the owner decides.",
    ]
    text = " ".join(parts)
    return text if len(text) <= MAX_REASONING else text[: MAX_REASONING - 1] + "…"


@dataclass(frozen=True)
class Explanation:
    """A proposal's reasoning in its parts, as _reasoning wrote them: why (the unit, its
    relation and why this target), why the owner must decide it (empty when nothing says so),
    the hypothesis, the measure and the removal."""

    why: str
    needs_owner: str
    hypothesis: str
    measure: str
    removal: str


def explain(absorption: Absorption) -> Explanation:
    """The parts of a proposal's reasoning. They are read from after its target: everything
    from there on is CLIVE's own words, while the unit's title, which comes first, is the
    artifact's text and cannot speak for the proposal — a title that says "Needs the owner:"
    or "Hypothesis:" says it only inside `why`. Reasoning not in _reasoning's shape (clipped,
    or written by hand) is all `why`."""
    text = absorption.reasoning
    marker = text.rfind(f" Target {absorption.target}: ")
    if marker < 0:
        return Explanation(text, "", "", "", "")
    head, tail = text[:marker], text[marker + 1:]
    found: dict[str, str] = {}
    for label in ("Self-model ", "Removal: ", "Measure: ", "Hypothesis: ", f"{NEEDS_OWNER}: "):
        at = tail.rfind(f" {label}")
        if at >= 0:
            found[label] = tail[at + 1 + len(label):].strip()
            tail = tail[:at]
    if not all(label in found for label in ("Hypothesis: ", "Measure: ", "Removal: ")):
        return Explanation(text, "", "", "", "")
    reason = found.get(f"{NEEDS_OWNER}: ", "")
    return Explanation(
        why=f"{head} {tail}".strip(), needs_owner=reason.removesuffix("."),
        hypothesis=found["Hypothesis: "], measure=found["Measure: "], removal=found["Removal: "],
    )


def needs_owner(absorption: Absorption) -> bool:
    """Whether the proposal says the owner must decide it (see explain)."""
    return bool(explain(absorption).needs_owner)


def usual_hypothesis(target: str) -> tuple[str, str]:
    """The hypothesis and measure a proposal for this target states unless it says otherwise."""
    return _HYPOTHESIS_MEASURE.get(target, ("", ""))


def _reading_order(unit: Unit) -> tuple:
    where = unit.location
    return (where.path, where.line_start or 0, where.line_end or 0, UNIT_KINDS.index(unit.kind),
            unit.id)


def propose(artifact_id: str, units: Iterable[Unit], relations: Iterable[Relation], *,
            recorded_at: str | None = None) -> list[Absorption]:
    """One proposal per distinct Unit, in reading order. `recorded_at` defaults to now; pass it
    to make the records, and so their ids, exactly repeatable."""
    recorded_at = recorded_at or utc_now()
    by_unit: dict[str, Relation] = {}
    for relation in relations:
        if not isinstance(relation, Relation):
            raise ValueError("propose takes Relation records")
        by_unit.setdefault(relation.unit_id, relation)
    distinct: dict[str, Unit] = {}
    for unit in units:
        if not isinstance(unit, Unit):
            raise ValueError("propose takes Unit records")
        if unit.artifact_id != artifact_id:
            raise ValueError(f"unit {unit.id} belongs to {unit.artifact_id}, not {artifact_id}")
        distinct.setdefault(unit.id, unit)
    proposals = []
    for unit in sorted(distinct.values(), key=_reading_order):
        relation = by_unit.get(unit.id)
        if relation is None:
            raise ValueError(f"unit {unit.id} has no relation: relate it before proposing")
        if relation.unit_kind != unit.kind:
            raise ValueError(f"the relation for {unit.id} is for a {relation.unit_kind}, "
                             f"not a {unit.kind}")
        plan = _plan(unit, relation)
        proposals.append(Absorption(
            artifact_id=artifact_id, unit_id=unit.id, target=plan.target,
            reasoning=_reasoning(unit, relation, plan, relation.self_model),
            removal=RemovalHandle(plan.additions), recorded_at=recorded_at,
            proposed_by=PROPOSER, decided_by=None,
        ))
    return proposals
