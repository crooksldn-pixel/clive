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
      command: no contract tag)                      registered as a tool, which would run it);
                                                     one per file, for all of its code
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

A skill is proposed whole: every unit read out of one skill (the skills adapter tags each with
skill:<name>) is one builder_skill proposal — or one pointer, when CLIVE already has the skill
— never one per procedure, rule or check in it; the procedures of one file outside a skill
are one builder skill for that file, its rules and checks (three or more) one review-check set,
and its code one native objective. A lone rule or check is a set of one, and ranks as thin.
A builder skill from another artifact needs the owner: its
instructions are the artifact's words and steer every builder that loads it.

Licences decide what may be taken (scan.licence_map gives each folder's): one that forbids
reuse makes a proposal a pointer; none, one not recognised, or one with conditions (copyleft,
share-alike) makes it the owner's to decide; a permissive one travels with what is added, as
the reasoning's Licence part says (keep the notice, from the file named). A capability of a
remote API — read or write — is a connector with its client module, the owner's to approve: it
brings a credential and sends requests off the host. A dataset profiled only in part may hold
personal data the profile did not see, and is not fed anywhere. Relating against a self-model
whose registries could not be read cannot tell a gap from something CLIVE has, so a gap is then
only a pointer. A unit whose file, title or path carries a credential is never quoted: its
reasoning names its kind and place, and its additions are named from its id.

Mass has a cost (KNOWLEDGE_DIGESTER_V1.md principle 5). Every candidate is scored — the value
of its target, the strength of its relation (a gap, new but unvouched for, counts
GAP_STRENGTH), its substance and what it costs the owner — near-duplicates are folded into the
best of them, and each target keeps at most its BUDGET, best first. The rest are held back:
counted and listed by unit in Proposals.held, still reachable (propose with budget=None
proposes every one, repeats included), but not recorded as proposals the owner has to read.

Curated (propose with curated=True; OWNER_DECISIONS_2026-09-30): the owner listed this
artifact's skills himself, so its builder skills need no further sign-off and are not budgeted —
every one is kept, best first, and none is held back. Nothing else changes: every other target
keeps its budget and its reasons to need the owner, and the licence still decides what may be
taken and whether the owner must.

Deterministic: the same units, relations and inputs give the same proposals, best first, ties
in reading order."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from app.digest import scan
from app.digest.model import (
    ABSORPTION_TARGETS,
    ADDING_TARGETS,
    MAX_REASONING,
    PROPOSER,
    UNIT_KINDS,
    Absorption,
    Addition,
    Finding,
    RemovalHandle,
    Unit,
    utc_now,
)
from app.digest.relate import Match, Relation, tokenise
from app.digest.selfmodel import SelfModel

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
SKILL_TAG = "skill:"       # the skills adapter's tag for the skill a unit was read from
SKILL_FILE = "SKILL.md"
MAX_SLUG = 40

# Each target's budget of proposals for one artifact, best first; the rest are held back.
BUDGET: Mapping[str, int] = {
    "builder_skill": 5, "tool_connector": 5, "review_check": 15, "design_system": 5,
    "native_objective": 5, "product_memory": 10, "reference_only": 5, "rejected": 0,
}
# What a proposal for each target is worth to CLIVE, before its relation, substance and cost.
TARGET_VALUE: Mapping[str, float] = {
    "builder_skill": 1.0, "tool_connector": 0.9, "review_check": 0.7, "design_system": 0.6,
    "native_objective": 0.6, "product_memory": 0.5, "reference_only": 0.1, "rejected": 0.0,
}
GAP_STRENGTH = 0.3         # a gap is new to CLIVE, but nothing in CLIVE vouches for it
OWNER_COST = 0.85          # a proposal the owner must decide costs the owner a decision
CLAIM_COST = 0.8           # a claim must be verified before anything else
UNLICENSED_COST = 0.6      # no licence, or one not recognised, grants nothing without the owner
CONDITIONAL_COST = 0.8     # conditions that travel with what is built from it
DUPLICATE = 0.8            # token overlap (Jaccard) at which one candidate repeats another
# Words of body that make a unit of each kind substantial; below a third of it, it is thin.
SUBSTANCE_WORDS: Mapping[str, int] = {
    "rule": 10, "check": 10, "design_token": 10, "capability": 15, "interface": 15,
    "procedure": 30, "pattern": 20, "data_schema": 20, "knowledge": 40, "claim": 25,
}
SKILL_SUBSTANCE = 12       # procedures, rules and checks that make a skill substantial
MIN_CHECK_SET = 3          # a file's rules and checks, from this many, are one review-check set
PROJECT_COST = 0.5         # a skill for developing the artifact itself, in its own agent folder
# The artifact's own agent folders: a skill there is how its maintainers work on it.
PROJECT_SKILL = re.compile(r"(^|/)\.(claude|cursor|codex|windsurf|agents)/")
# Housekeeping every project carries: what it says is about the project, not guidance for CLIVE.
HOUSEKEEPING = re.compile(
    r"(^|/)(changelog|changes|history|releases?|release[-_]notes|contributing|code[-_]of[-_]conduct"
    r"|security|licen[cs]e|copying|notice|authors|contributors|third[-_]party[-_]notices|funding"
    r"|codeowners)(\.[^/]*)?$",
    re.IGNORECASE,
)

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
    licence: str = ""           # what the licence asks of what is added, when it asks anything
    cost: float = 1.0           # what deciding and keeping it costs, as a factor on its score


@dataclass(frozen=True)
class _Candidate:
    """What one proposal would speak for: one unit, or every unit of a skill (or the procedures
    of one file), with the anchor it is recorded against and the relation its plan rests on."""

    anchor: Unit
    members: tuple[Unit, ...]
    relation: Relation
    group: str = ""             # "skill", "procedures", "checks" or "code"; "" for one unit
    name: str = ""              # the skill's name, or the file's path


@dataclass(frozen=True)
class Proposals:
    """What propose makes of an artifact: the proposals kept, best first, and what the budget
    held back — (target, anchor unit ids, best first) — reachable with budget=None."""

    kept: tuple[Absorption, ...]
    held: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def held_counts(self) -> dict[str, int]:
        return {target: len(ids) for target, ids in self.held}


def _a(word: str) -> str:
    return f"{'an' if word[:1] in 'aeiou' else 'a'} {word}"


def _slug(unit: Unit, separator: str, name: str | None = None, withheld: bool = False) -> str:
    """A name for what a proposal adds, from the unit's title (or the name given) and its id;
    from its kind and id alone when the title is withheld."""
    words = [] if withheld else re.findall(r"[a-z0-9]+", (name or unit.title).lower())
    base = separator.join(words)[:MAX_SLUG].strip(separator) or unit.kind
    return f"{base}{separator}{unit.id[5:13]}"


def _identifier(unit: Unit, withheld: bool = False) -> str:
    """A Python module and tool name for the unit: digested_<words>_<id part>."""
    return f"digested_{_slug(unit, '_', withheld=withheld)}"


def _access(unit: Unit) -> str:
    tags = set(unit.tags)
    if "write" in tags:
        return "write"
    if "read" in tags:
        return "read"
    return "unknown"


def _entry(match: Match) -> str:
    named = ("named by the unit; " if match.named
             else "matched by the artifact as a whole; " if match.context else "")
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


def _connector(unit: Unit, withheld: bool = False) -> tuple[Addition, ...]:
    name = _identifier(unit, withheld)
    return (
        Addition("connector", name),
        Addition("file", f"{CLIENTS_DIR}/{name}.py"),
        Addition("file", f"{TESTS_DIR}/test_{name}.py"),
    )


def _reference(why: str) -> _Plan:
    return _Plan("reference_only", why)


REMOTE_API = ("a connector brings a new credential and sends requests off the host, which is the "
              "owner's to approve")
CURATED = (" The owner listed this artifact's skills himself (OWNER_DECISIONS_2026-09-30), so it "
           "needs no further sign-off and does not count against the budget.")


def _plan(unit: Unit, relation: Relation, withheld: bool = False) -> _Plan:
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
    slug = _slug(unit, "-", withheld=withheld)
    if kind == "procedure":            # a procedure alone, as a group of one: see _group_plan
        return _Plan("builder_skill", "A procedure becomes a builder skill: a skill folder with a "
                     "provenance header citing this unit's Source.",
                     (Addition("skill", f"{SKILLS_DIR}/{slug}"),))
    if kind == "check" and "test" in tags:
        return _reference("A test of the artifact's own code is pointed at: it checks that "
                          "project, not work CLIVE reviews.")
    if kind in ("rule", "check"):
        return _Plan("review_check", f"A {kind} becomes a review check: a rule in the reviewer's "
                     "rubric or an automated check.",
                     (Addition("check", f"review-check:{slug}"),))
    if kind == "capability" and not tags & CONTRACT_TAGS:
        return _Plan("native_objective", "A capability read from code is built natively as a "
                     "loop objective citing this unit's Source: another project's function, "
                     "module or command is never registered as a CLIVE tool, since calling it "
                     "would run that project's code.",
                     (Addition("objective", f"objective:{slug}"),))
    if kind == "capability":
        access = _access(unit)
        additions = _connector(unit, withheld)
        if access == "read":
            return _Plan("tool_connector", "A capability of a remote API that only reads becomes "
                         "a connector: its client module, a registered read tool, and tests.",
                         additions, needs_owner=REMOTE_API)
        said = "writes" if access == "write" else "does not say whether it writes"
        return _Plan(
            "tool_connector", f"A capability of a remote API that {said} becomes a connector, "
            "registered only behind the action gate.", additions,
            needs_owner=f"{REMOTE_API}; and it {said}, so it is registered only with a complete "
                        f"WriteSpec behind the action gate ({GATE}) and every call is staged for "
                        "the owner's tap",
        )
    if kind == "interface":
        if relation.relation == "extends" and tags & CONTRACT_TAGS:
            return _Plan(
                "tool_connector", "An API contract that extends what CLIVE has becomes a "
                "connector built from it, with its tests.", _connector(unit, withheld),
                needs_owner=f"{REMOTE_API}, and any write it offers goes behind the action gate "
                            f"({GATE})",
            )
        return _reference("A contract on its own is kept as a pointer; the capabilities that "
                          "use it are proposed on their own.")
    if kind == "data_schema":
        if "personal" in tags:
            return _reference("The dataset holds personal data, so it is not fed into CLIVE; "
                              "the owner can ask for it explicitly.")
        if "partial" in tags:
            return _reference("Only part of the dataset was profiled, so it may hold personal "
                              "data the profile did not see: it is not fed into CLIVE, and the "
                              "owner can ask for it explicitly.")
        return _Plan("tool_connector", "A dataset's shape becomes a read-only business-memory "
                     "feed: a connector that reads it, with its tests.", _connector(unit, withheld))
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
            cost=CLAIM_COST,
        )
    if kind == "design_token":
        return _Plan(
            "design_system", "Design tokens become a token set in the Generative UI's token "
            f"sheet ({TOKEN_SHEET}), in one named block whose header cites this unit's Source.",
            (Addition("token_set", f"{TOKEN_SHEET}#{slug}"),),
            needs_owner="a token set changes how every scene that uses it looks, and CLIVE's "
                        "look is the owner's: the sheet takes no new colour or font without "
                        "the owner's say",
        )
    if kind == "pattern" and DESIGN_TAG in tags:
        return _Plan(
            "design_system", "A design pattern becomes a Generative UI component: a folder "
            f"beside the scene renderer ({COMPONENTS_DIR}) with a provenance header citing this "
            "unit's Source; no scene uses it until one is built to.",
            (Addition("component", f"{COMPONENTS_DIR}/{slug}"),),
        )
    if kind == "pattern":
        return _Plan("native_objective", "A code pattern is built natively as a loop objective, "
                     "citing this unit's Source.",
                     (Addition("objective", f"objective:{slug}"),))
    return _reference(f"No target takes {_a(kind)}.")   # pragma: no cover — every kind is above


def _reasoning(subject: str, relation: Relation, plan: _Plan, digest: str, rank: str) -> str:
    hypothesis, measure = _HYPOTHESIS_MEASURE[plan.target]
    hypothesis, measure = plan.hypothesis or hypothesis, plan.measure or measure
    if plan.additions:
        taken = "; ".join(f"{a.kind} {a.ref}" for a in plan.additions)
        removal = (f"take out {taken} (the digest of each is recorded when it is written); "
                   "the suite stays green afterwards.")
    else:
        removal = "nothing is added, so there is nothing to remove."
    parts = [
        f"{subject} {_related(relation)}.",
        f"Target {plan.target}: {plan.why}",
    ]
    if plan.needs_owner:
        parts.append(f"{NEEDS_OWNER}: {plan.needs_owner}.")
    if plan.licence:
        parts.append(f"Licence: {plan.licence}")
    parts += [
        f"Hypothesis: {hypothesis}",
        f"Measure: {measure}",
        f"Removal: {removal}",
        f"Rank: {rank}",
        f"Self-model {digest}. Proposed by CLIVE; the owner decides.",
    ]
    text = " ".join(parts)
    return text if len(text) <= MAX_REASONING else text[: MAX_REASONING - 1] + "…"


@dataclass(frozen=True)
class Explanation:
    """A proposal's reasoning in its parts, as _reasoning wrote them: why (the unit, its
    relation and why this target), why the owner must decide it (empty when nothing says so),
    the hypothesis, the measure and the removal; and what its licence asks and how it ranked,
    when it says."""

    why: str
    needs_owner: str
    hypothesis: str
    measure: str
    removal: str
    licence: str = ""
    rank: str = ""


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
    for label in ("Self-model ", "Rank: ", "Removal: ", "Measure: ", "Hypothesis: ", "Licence: ",
                  f"{NEEDS_OWNER}: "):
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
        licence=found.get("Licence: ", ""), rank=found.get("Rank: ", ""),
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


# --- candidates: one unit, one skill, or one file's procedures ---------------------------------


def _skill_of(unit: Unit) -> str:
    return next((tag[len(SKILL_TAG):] for tag in unit.tags if tag.startswith(SKILL_TAG)), "")


def _skill_folders(units: list[Unit]) -> dict[str, str]:
    """Each folder holding a skill's SKILL.md, as {folder: skill name} ("" for the top)."""
    folders: dict[str, str] = {}
    for unit in units:
        name = _skill_of(unit)
        path = unit.location.path
        if name and (path == SKILL_FILE or path.endswith("/" + SKILL_FILE)):
            folders.setdefault(path[: -len(SKILL_FILE)].rstrip("/"), name)
    return folders


def _skill_for(unit: Unit, folders: dict[str, str]) -> str:
    """The skill a unit belongs to: its skill:<name> tag, or the deepest skill folder it is in,
    whichever adapter read it."""
    name = _skill_of(unit)
    if name:
        return name
    folder = unit.location.path
    while "/" in folder:
        folder = folder.rsplit("/", 1)[0]
        if folder in folders:
            return folders[folder]
    return folders.get("", "")


def _candidates(units: list[Unit], relations: dict[str, Relation]) -> list[_Candidate]:
    """Every unit of one skill — read out of its SKILL.md or anything else in its folder — is
    one candidate, anchored on the skill's own knowledge unit (its front matter); outside a
    skill, the procedures of one file are one, so are the rules and checks of one file when
    there are MIN_CHECK_SET or more, and so is the code of one file that would be built natively
    (anchored on its module); every other unit is its own."""
    folders = _skill_folders(units)
    skills: dict[str, list[Unit]] = {}
    procedures: dict[str, list[Unit]] = {}
    checks: dict[str, list[Unit]] = {}
    code: dict[str, list[Unit]] = {}
    out: list[_Candidate] = []
    for unit in units:
        name = _skill_for(unit, folders)
        if name and HOUSEKEEPING.search(unit.location.path):
            out.append(_Candidate(unit, (unit,), relations[unit.id]))   # its licence, its notes
        elif name:
            skills.setdefault(name, []).append(unit)
        elif unit.kind == "procedure":
            procedures.setdefault(unit.location.path, []).append(unit)
        elif unit.kind in ("rule", "check") and "unparsed" not in unit.tags:
            checks.setdefault(unit.location.path, []).append(unit)
        elif _native(unit):
            code.setdefault(unit.location.path, []).append(unit)
        else:
            out.append(_Candidate(unit, (unit,), relations[unit.id]))
    for name, members in skills.items():
        anchor = next((u for u in members if u.kind == "knowledge" and "unparsed" not in u.tags
                       and _skill_of(u) == name and u.location.path.endswith(SKILL_FILE)),
                      members[0])
        out.append(_Candidate(anchor, tuple(members), _group_relation(anchor, members, relations),
                              "skill", name))
    for path, members in procedures.items():
        out.append(_Candidate(members[0], tuple(members),
                              _group_relation(members[0], members, relations), "procedures", path))
    for path, members in checks.items():
        if len(members) < MIN_CHECK_SET:
            out += [_Candidate(unit, (unit,), relations[unit.id]) for unit in members]
        else:
            out.append(_Candidate(members[0], tuple(members),
                                  _group_relation(members[0], members, relations), "checks", path))
    for path, members in code.items():
        if len(members) == 1:
            out.append(_Candidate(members[0], (members[0],), relations[members[0].id]))
            continue
        anchor = next((u for u in members if u.title.startswith("module ")), members[0])
        out.append(_Candidate(anchor, tuple(members), _group_relation(anchor, members, relations),
                              "code", path))
    return out


def _native(unit: Unit) -> bool:
    """Whether a unit is code that would be built natively: a capability with no API contract,
    or a pattern that is not a design pattern."""
    tags = set(unit.tags)
    if "unparsed" in tags:
        return False
    return ((unit.kind == "capability" and not tags & CONTRACT_TAGS)
            or (unit.kind == "pattern" and DESIGN_TAG not in tags))


def _group_relation(anchor: Unit, members: list[Unit], relations: dict[str, Relation]) -> Relation:
    """What a group rests on: the anchor's overlap when CLIVE has it already; otherwise the
    strongest extension among its members; otherwise the anchor's own relation."""
    own = relations[anchor.id]
    if own.relation == "overlap":
        return own
    extending = [relations[u.id] for u in members if relations[u.id].relation == "extends"]
    if extending:
        return max(extending, key=lambda r: (r.score, r.unit_id))
    return own


def _group_plan(candidate: _Candidate, withheld: bool) -> _Plan:
    anchor, relation = candidate.anchor, candidate.relation
    if relation.relation == "overlap":
        basis = _basis(relation)
        name = f"{basis.key} '{basis.name[:80]}'" if basis else "it"
        return _reference(f"CLIVE already has {name}, so nothing is added; this is kept as a "
                          "pointer beside it.")
    if candidate.group == "checks":
        slug = _slug(anchor, "-", name=candidate.name, withheld=withheld)
        return _Plan(
            "review_check", "The rules and checks of one file become one review-check set: "
            "a check file whose header cites this artifact's Source, one check per rule, kept or "
            "removed together.",
            (Addition("check", f"review-check-set:{slug}"),),
        )
    if candidate.group == "code":
        slug = _slug(anchor, "-", name=candidate.name.rsplit("/", 1)[-1], withheld=withheld)
        return _Plan(
            "native_objective", "The code of one file is built natively as one loop objective "
            "citing this artifact's Source: another project's functions are never registered "
            "as CLIVE tools, since calling them would run that project's code.",
            (Addition("objective", f"objective:{slug}"),),
        )
    what = "skill" if candidate.group == "skill" else "set of procedures"
    slug = _slug(anchor, "-", name=candidate.name.rsplit("/", 1)[-1], withheld=withheld)
    own = candidate.group == "skill" and bool(PROJECT_SKILL.search(anchor.location.path))
    return _Plan(
        "builder_skill", f"The {what} becomes one builder skill: a skill folder with a "
        "provenance header citing this artifact's Source, its procedures, rules, checks and "
        "the files it references together." + (
            " It sits in the artifact's own agent folder, so it is how its maintainers work on "
            "that project, and is worth less to CLIVE." if own else ""),
        (Addition("skill", f"{SKILLS_DIR}/{slug}"),),
        needs_owner="a builder skill from another artifact steers every builder that loads it, "
                    "and its instructions are that artifact's words, not CLIVE's",
        cost=PROJECT_COST if own else 1.0,
    )


def _plural(kind: str) -> str:
    kind = kind.replace("_", " ")
    if kind == "knowledge":
        return "pieces of knowledge"
    return kind[:-1] + "ies" if kind.endswith("y") else kind + "s"


def _count(members: tuple[Unit, ...]) -> str:
    counts: dict[str, int] = {}
    for unit in members:
        if "unparsed" not in unit.tags:
            counts[unit.kind] = counts.get(unit.kind, 0) + 1
    shown = [f"{n} {kind if n == 1 else _plural(kind)}" for kind, n in
             sorted(counts.items(), key=lambda item: (-item[1], UNIT_KINDS.index(item[0])))]
    return ", ".join(shown) or "nothing readable"


# --- licences, the self-model, credentials -----------------------------------------------------


def _licence_plan(plan: _Plan, licence: tuple[str, str] | None) -> _Plan:
    """What the licence covering a proposal's units makes of it (see the module's docstring)."""
    if plan.target not in ADDING_TARGETS:
        return plan
    expression, where = licence if licence else ("", "")
    rank = scan.licence_rank(expression or None)
    if rank == 2:
        return replace(_reference(f"Its licence ({expression}, in {where}) forbids reuse, so "
                                  "nothing is taken from it; it is kept as a pointer, and the "
                                  "owner decides anything more."),
                       needs_owner=f"its licence ({expression}) forbids reuse, so taking anything "
                                   "from it is the owner's to decide")
    if rank is None:
        return _more(plan, "no licence grants the right to reuse it: the artifact declares none",
                     UNLICENSED_COST, "none found")
    if expression == scan.UNKNOWN or scan.UNKNOWN in expression.split("; "):
        return _more(plan, f"its licence (in {where}) could not be identified, so what it allows "
                     "is unknown", UNLICENSED_COST, f"not identified (in {where})")
    if rank == 1:
        return _more(plan, f"its licence ({expression}) sets conditions — copyleft, share-alike or "
                     "source-available terms — that travel with anything built from it",
                     CONDITIONAL_COST, f"{expression} (in {where}): its conditions travel with "
                     "what is added")
    return replace(plan, licence=f"{expression}: keep its copyright and licence notice ({where}) "
                                 "with what is added.")


def _more(plan: _Plan, reason: str, cost: float, licence: str) -> _Plan:
    needs = f"{plan.needs_owner}; and {reason}" if plan.needs_owner else reason
    return replace(plan, needs_owner=needs, cost=plan.cost * cost, licence=licence + ".")


def _secret_places(findings: Iterable[Finding]) -> set[str]:
    """Paths where the scanner found a credential, of any severity (pipeline._from_scan starts
    each safety finding's explanation with its scan rule)."""
    return {finding.location.path for finding in findings
            if finding.category == "safety" and finding.explanation.startswith("secret.")}


def _withheld(unit: Unit, secret_paths: set[str]) -> bool:
    return (unit.location.path in secret_paths or scan.holds_secret(unit.title)
            or scan.holds_secret(unit.location.path))


def _subject(candidate: _Candidate, withheld: bool) -> str:
    anchor = candidate.anchor
    if withheld:
        return (f"A {anchor.kind} (its title and place are withheld: a credential was found "
                "there)")
    if candidate.group == "skill":
        return f"The skill '{candidate.name[:120]}' ({_count(candidate.members)})"
    if candidate.group in ("procedures", "checks", "code") and len(candidate.members) > 1:
        what = {"procedures": "procedures", "checks": "rules and checks", "code": "code"}[
            candidate.group]
        return f"The {what} of {candidate.name[:120]} ({_count(candidate.members)})"
    return f"The {anchor.kind} '{anchor.title[:120]}'"


# --- scoring --------------------------------------------------------------------------------------


def _substance(candidate: _Candidate) -> float:
    """How much there is to it: a skill or a set of rules and checks by how many procedures,
    rules and checks it holds (a lone rule or check is a set of one); anything else by the words
    of its bodies, against what makes a unit of its kind substantial."""
    if candidate.group in ("skill", "checks") or candidate.anchor.kind in ("rule", "check"):
        n = sum(1 for u in candidate.members
                if u.kind in ("procedure", "rule", "check") and "unparsed" not in u.tags)
        return max(0.3, min(1.0, n / SKILL_SUBSTANCE))
    words = sum(len(re.findall(r"\w+", u.body)) for u in candidate.members)
    return max(0.3, min(1.0, words / SUBSTANCE_WORDS.get(candidate.anchor.kind, 20)))


def _score(candidate: _Candidate, plan: _Plan) -> tuple[float, str]:
    relation = candidate.relation
    value = TARGET_VALUE[plan.target]
    strength = relation.score if relation.relation in ("overlap", "extends") else GAP_STRENGTH
    substance = _substance(candidate)
    cost = plan.cost * (OWNER_COST if plan.needs_owner else 1.0)
    score = value * (0.4 + 0.6 * strength) * substance * cost
    return score, (f"{score:.2f} (target value {value:.2f}, relation {strength:.2f}, substance "
                   f"{substance:.2f}, cost {cost:.2f})")


def _words(candidate: _Candidate) -> frozenset[str]:
    """What a candidate says, to tell a repeat: its anchor's title and body — a skill's own
    front matter, a file's first rule — and the titles of the rest of it."""
    anchor = candidate.anchor
    words = set(tokenise(f"{anchor.title} {anchor.body}"))
    for unit in candidate.members[1:50]:
        words.update(tokenise(unit.title, 16))
    return frozenset(words)


# --- proposing -----------------------------------------------------------------------------------


def propose(artifact_id: str, units: Iterable[Unit], relations: Iterable[Relation], *,
            recorded_at: str | None = None, licence: str | None = None,
            licences: Mapping[str, tuple[str, str]] | None = None,
            findings: Iterable[Finding] = (), self_model: SelfModel | None = None,
            budget: Mapping[str, int] | None = BUDGET, curated: bool = False) -> list[Absorption]:
    """The proposals kept for an artifact, best first (see proposals)."""
    return list(proposals(artifact_id, units, relations, recorded_at=recorded_at,
                          licence=licence, licences=licences, findings=findings,
                          self_model=self_model, budget=budget, curated=curated).kept)


def proposals(artifact_id: str, units: Iterable[Unit], relations: Iterable[Relation], *,
              recorded_at: str | None = None, licence: str | None = None,
              licences: Mapping[str, tuple[str, str]] | None = None,
              findings: Iterable[Finding] = (), self_model: SelfModel | None = None,
              budget: Mapping[str, int] | None = BUDGET, curated: bool = False) -> Proposals:
    """What CLIVE proposes to take from an artifact: one candidate per skill, per file of
    procedures, or per other unit; each planned, licensed, scored and, within its target's
    budget, recorded — best first, ties in reading order — and the rest held back.

    `licence` is the artifact's (its Source's); `licences` each folder's own (scan.licence_map),
    which covers what is under it. `findings` are the digest's, for the places a credential was
    found. `self_model` is the one related against, for the registries it could not read.
    `budget` maps each target to how many proposals it keeps (None: every one). `curated` says
    the owner listed this artifact's skills himself: its builder skills need no sign-off and
    are not budgeted (see the module's docstring). `recorded_at` defaults to now; pass it to
    make the records, and so their ids, exactly repeatable."""
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
    ordered = sorted(distinct.values(), key=_reading_order)
    for unit in ordered:
        relation = by_unit.get(unit.id)
        if relation is None:
            raise ValueError(f"unit {unit.id} has no relation: relate it before proposing")
        if relation.unit_kind != unit.kind:
            raise ValueError(f"the relation for {unit.id} is for a {relation.unit_kind}, "
                             f"not a {unit.kind}")
    folders = dict(licences or {})
    if licence and "" not in folders:
        folders[""] = (licence, "the artifact's Source")
    secret_paths = _secret_places(findings)
    unread = self_model.unread if self_model is not None else ()

    scored: list[tuple[float, tuple, _Candidate, _Plan, str, bool]] = []
    for candidate in _candidates(ordered, by_unit):
        withheld = any(_withheld(u, secret_paths) for u in (candidate.anchor,))
        if HOUSEKEEPING.search(candidate.anchor.location.path):
            plan = _reference("It comes from the project's housekeeping (a changelog, a "
                              "contribution guide, a licence or notice): what it says is about "
                              "the project, not guidance for CLIVE, so it is kept as a pointer.")
        elif candidate.group:
            plan = _group_plan(candidate, withheld)
        else:
            plan = _plan(candidate.anchor, candidate.relation, withheld)
        if unread and candidate.relation.relation == "gap" and plan.target in ADDING_TARGETS:
            plan = _reference(f"CLIVE's {', '.join(unread)} could not be read into the "
                              "self-model, so whether CLIVE lacks this is unknown; it is kept as "
                              "a pointer.")
        if curated and plan.target == "builder_skill":
            plan = replace(plan, why=plan.why + CURATED, needs_owner="")
        plan = _licence_plan(plan, scan.licence_for(candidate.anchor.location.path, folders))
        score, rank = _score(candidate, plan)
        scored.append((score, (-len(candidate.members), *_reading_order(candidate.anchor)),
                       candidate, plan, rank, withheld))
    scored.sort(key=lambda item: (-item[0], item[1]))    # ties: the larger, then reading order

    kept: list[Absorption] = []
    held: dict[str, list[str]] = {}
    taken: dict[str, list[frozenset[str]]] = {}
    for _score_value, _order, candidate, plan, rank, withheld in scored:
        words = _words(candidate)
        same = taken.setdefault(plan.target, [])
        budgeted = budget is not None and not (curated and plan.target == "builder_skill")
        duplicate = budgeted and any(
            words and other and len(words & other) / len(words | other) >= DUPLICATE for other in same)
        room = not budgeted or len(same) < budget.get(plan.target, 0)
        if duplicate or not room:
            held.setdefault(plan.target, []).append(candidate.anchor.id)
            continue
        same.append(words)
        kept.append(Absorption(
            artifact_id=artifact_id, unit_id=candidate.anchor.id, target=plan.target,
            reasoning=_reasoning(_subject(candidate, withheld), candidate.relation, plan,
                                 candidate.relation.self_model, rank),
            removal=RemovalHandle(plan.additions), recorded_at=recorded_at,
            proposed_by=PROPOSER, decided_by=None,
        ))
    return Proposals(
        kept=tuple(kept),
        held=tuple((target, tuple(held[target])) for target in ABSORPTION_TARGETS if target in held),
    )
