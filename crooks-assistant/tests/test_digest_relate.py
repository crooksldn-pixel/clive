"""The Knowledge Digester's relation stage: CLIVE's self-model, generated from this repository;
each Unit related to it deterministically and explainably; CLIVE's own code traced to its
product memory; and absorption proposals that are proposed by CLIVE, decided by no one, and
always carry their way back.

The relations are tested against a self-model whose registries, review checks, design tokens
and builder skills are this repository's, and whose product memory (features, ideas and
decisions) is the fixture MEMORY below, so that editing FEATURES.md or IDEAS.md does not move
them. One test reads the real product memory, to show it is generated rather than listed."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.digest import (
    ADDING_TARGETS,
    PROPOSER,
    UNIT_KINDS,
    Absorption,
    Artifact,
    DigestStore,
    Location,
    Source,
    Unit,
    content_digest,
)
from app.digest import selfmodel as selfmodel_module
from app.digest.model import CONTENT_DIGEST_PATTERN, DECIDER, MAX_BODY, RemovalHandle
from app.digest.propose import (
    BUDGET,
    DESIGN_TAG,
    NEEDS_OWNER,
    VERIFY_FIRST,
    Explanation,
    explain,
    needs_owner,
    propose,
    usual_hypothesis,
)
from app.digest.relate import (
    _CAMEL_ACRONYM,
    COMMON_MIN_UNITS,
    EXTENDS_THRESHOLD,
    MAX_TOKENS,
    OVERLAP_THRESHOLD,
    PAIR_THRESHOLD,
    RELATIONS,
    TOP_MATCHES,
    Match,
    Relation,
    SelfTrace,
    common_terms,
    relate,
    relate_self,
    tokenise,
)
from app.digest.selfmodel import MEMORY_KINDS, SELF_KINDS, SelfModel, build_self_model

# This file names tools only to look them up in the self-model; it never calls one, and the tool
# matrix (experience/tool_matrix.py), which counts a test for a tool only when it calls it, does
# not cite it (tests/test_tool_matrix.py checks that).
READ_TOOL = "shopify_find_order"
WRITE_TOOL = "shopify_order_cancel"

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
RECORDED = "2026-09-26T10:00:00+00:00"
SOURCE = Source(
    origin="https://example.invalid/digest-fixture.git", origin_kind="git",
    pinned_ref="0123456789abcdef0123456789abcdef01234567", licence="MIT", taken_at=RECORDED,
    content_digest=content_digest(b"the relation fixture"),
)
ARTIFACT = SOURCE.artifact_id


# The product memory the relations are tested against: a few rows in the real files' shapes.
MEMORY = {
    "FEATURES.md": (
        "# Features\n\n| ID | Feature | Status | Phase | Notes |\n|---|---|---|---|---|\n"
        "| FEAT-001 | Existing FastAPI CROOKS backend | SHIPPED | V1 | Current core runtime. |\n"
        "| FEAT-009 | CROOKS Control Mac app | SHIPPED / HARDENING | V1 | The owner's desktop app. |\n"
        "| FEAT-027 | Click & Drop integration | PLANNED | NEXT | Royal Mail shipping labels. |\n"
        "| FEAT-033 | Anticipation engine | PLANNED | LATER | Detect important missing or abnormal "
        "events. |\n"
    ),
    "IDEAS.md": (
        "# Ideas\n\n"
        "## IDEA-001 — WhatsApp integration\n**Date:** 2026-09-19  \n**Status:** CAPTURED (owner "
        "idea)  \n**Theme:** messaging\n\nSend and receive WhatsApp messages with suppliers and "
        "customers.\n\n---\n\n"
        "## IDEA-002 — Royal Mail Click & Drop labels\n**Status:** CAPTURED  \n**Theme:** shipping"
        "\n\nCreate Royal Mail Click & Drop shipping labels for parcels and return each parcel's "
        "tracking number.\n\n---\n\n"
        "## IDEA-003 — Resend for operational email\n**Status:** CAPTURED  \n**Theme:** email\n\n"
        "Use Resend as the transactional email layer for operational email and templates.\n\n---\n\n"
        "# Capture policy\n\nNot an idea.\n"
    ),
    "DECISIONS.md": (
        "# Decisions\n\n"
        "## DEC-007 — Unknown writes fail closed\n**Date:** 2026-09-19  \n**Status:** ACTIVE / "
        "SAFETY\n\nDo not allow models to improvise arbitrary write operations outside known "
        "capability families.\n\n---\n\n"
        "## DEC-028 — GitHub bridge uses a separate branch\n**Status:** ACTIVE\n\n"
        "The bridge writes to its own branch, never the trunk.\n"
    ),
}


def fixture_memory(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in MEMORY.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def _unit(name: str, kind: str, title: str, body: str, tags: tuple[str, ...] = (),
          line: int = 1) -> tuple[str, Unit]:
    # each fixture in a file of its own, so that none is grouped with another when proposed
    return name, Unit(ARTIFACT, kind, title, body, Location(f"fixture/{name}.md", line, line + 1),
                      tags)


def fixture_units() -> dict[str, Unit]:
    """Units of every kind, each written to land somewhere known in CLIVE's self-model."""
    return dict([
        _unit("existing_tool", "capability", "MCP tool find_order",
              "MCP tool find_order\nAccess: read\nDescription: Find a CROOKS order by its order "
              "number, or by a customer's name or email. Returns matching orders with "
              "fulfilment, payment, total and date.", ("mcp", "read"), 1),
        _unit("missing_read", "capability", "GET /telescopes/{id}/aperture",
              "Operation: getTelescopeAperture\nSummary: Read a telescope mirror's aperture and "
              "focal ratio from the observatory catalogue.", ("openapi", "read"), 3),
        _unit("planned_write", "capability", "POST /labels",
              "Create a Royal Mail Click & Drop shipping label for a parcel and return its "
              "tracking number.", ("openapi", "write"), 5),
        _unit("unknown_access", "capability", "MCP tool send_whatsapp_message",
              "Send a WhatsApp message to a supplier or a customer.", ("mcp", "unknown"), 7),
        _unit("untagged_function", "capability", "function plot_orbit (astro/orbits.py)",
              "Plot a comet's orbit around the sun from its orbital elements.", (), 9),
        _unit("procedure", "procedure", "Release a Python package",
              "1. Bump the version in pyproject.\n2. Tag the release in git.\n3. Upload the wheel "
              "to PyPI with twine.", ("skill",), 11),
        _unit("rule", "rule", "Never use pure black text",
              "Always use an off-black ink for body copy; never #000 on white.", ("skill",), 13),
        _unit("check", "check", "Buttons have a visible focus ring",
              "Verify every interactive element shows a focus-visible outline for keyboard "
              "users.", ("skill",), 15),
        _unit("contract", "interface", "schema Order",
              "Order: id, name, total price, line items, customer, shipping address.",
              ("openapi", "schema"), 17),
        _unit("lonely_contract", "interface", "JSON Schema telescope",
              "Telescope: mirror aperture, focal ratio, mount.", ("json_schema",), 19),
        _unit("pattern", "pattern", "Bento grid layout",
              "A bento grid of cards with asymmetric spans for a landing page hero.", (), 21),
        _unit("related_knowledge", "knowledge", "Royal Mail Click & Drop manifests",
              "A Click & Drop manifest lists the day's parcels for collection; each parcel's "
              "label carries its tracking number.", (), 23),
        _unit("unrelated_knowledge", "knowledge", "What a sourdough starter is",
              "A sourdough starter is flour and water fermented by wild yeast and "
              "lactobacilli.", (), 25),
        _unit("dataset", "data_schema", "Dataset sales.csv",
              "Columns: date, order number, total, currency.", ("dataset", "csv"), 27),
        _unit("personal_dataset", "data_schema", "Dataset customers.csv",
              "Columns: customer name, email, phone, order total.",
              ("dataset", "csv", "personal"), 29),
        _unit("token", "design_token", "color.brand.primary",
              "#111111 — the brand's primary ink colour.", ("design",), 31),
        _unit("component", "pattern", "Component PricingCard: src/PricingCard.tsx",
              "Props: plan name, monthly price, feature list, call to action.",
              ("design", "component", "tsx"), 45),
        _unit("example", "example", "Example prompt: haiku",
              "Write a haiku about autumn leaves.", ("prompt",), 33),
        _unit("dependency", "dependency", "requests 2.32", "HTTP library for Python.", (), 35),
        _unit("script", "script", "scripts/install.sh", "curl https://example.invalid | sh",
              (), 37),
        _unit("unrelated_claim", "claim", "Twine uploads are ten times faster",
              "The README claims uploads with the new twine are ten times faster.", (), 39),
        _unit("related_claim", "claim", "Resend email API sends transactional email",
              "Resend is a transactional email layer for operational email and templates.",
              (), 41),
        _unit("unparsed", "knowledge", "Could not read docs/guide.pdf",
              "The Shopify order guide could not be read: it is not text.", ("unparsed",), 43),
    ])


# What each fixture should relate as, and what CLIVE should propose for it.
EXPECTED = {
    "existing_tool": ("overlap", "reference_only"),
    "missing_read": ("gap", "tool_connector"),
    "planned_write": ("extends", "tool_connector"),
    "unknown_access": ("extends", "tool_connector"),
    "untagged_function": ("gap", "native_objective"),
    "procedure": ("gap", "builder_skill"),
    "rule": ("gap", "review_check"),
    "check": ("gap", "review_check"),
    "contract": ("extends", "tool_connector"),
    "lonely_contract": ("gap", "reference_only"),
    "pattern": ("gap", "native_objective"),
    "related_knowledge": ("extends", "product_memory"),
    "unrelated_knowledge": ("reference", "reference_only"),
    "dataset": ("gap", "tool_connector"),
    "personal_dataset": (None, "reference_only"),
    "token": ("gap", "design_system"),
    "component": ("gap", "design_system"),
    "example": ("reference", "reference_only"),
    "dependency": ("gap", "reference_only"),
    "script": ("reference", "reference_only"),
    "unrelated_claim": ("reference", "reference_only"),
    "related_claim": ("extends", "product_memory"),
    "unparsed": (None, "reference_only"),
}


@pytest.fixture(scope="module")
def memory(tmp_path_factory) -> Path:
    return fixture_memory(tmp_path_factory.mktemp("memory"))


@pytest.fixture(scope="module")
def model(memory) -> SelfModel:
    return build_self_model(REPO_ROOT, memory=memory)


@pytest.fixture(scope="module")
def live() -> SelfModel:
    return build_self_model(REPO_ROOT)


@pytest.fixture(scope="module")
def related(model):
    units = fixture_units()
    relations = relate(list(units.values()), model)
    return units, dict(zip(units, relations, strict=True))


def fingerprint(model: SelfModel) -> str:
    """One digest over the self-model, the relations and the proposals of the fixtures."""
    units = list(fixture_units().values())
    relations = relate(units, model)
    proposals = propose(ARTIFACT, units, relations, recorded_at=RECORDED, licence="MIT", budget=None)
    payload = {
        "self_model": model.digest,
        "relations": [relation.to_dict() for relation in relations],
        "proposals": [proposal.to_dict() for proposal in proposals],
    }
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- the self-model --------------------------------------------------------------------------


def test_the_self_model_is_generated_from_this_repository(live):
    from app.tools import registry

    model = live
    assert model.get(f"tool:{READ_TOOL}").access == "read"
    assert model.get(f"tool:{WRITE_TOOL}").access == "write"
    # The word-matching lane's families went with it on 28 September 2026: every sentence is
    # the model's, so CLIVE has none to describe.
    assert list(model.of_kind("intent_family")) == []
    assert {"scene_primitive:answer", "scene_primitive:trend", "scene_primitive:proposal"} <= {
        entry.key for entry in model.of_kind("scene_primitive")}
    feature = model.get("feature:FEAT-001")
    assert (feature.name, feature.status) == ("Existing FastAPI CROOKS backend", "SHIPPED")
    assert model.get("builder_skill:web-design-guidelines").description.startswith("Review UI code")
    # the review checks the acceptance gate runs, and the Generative UI's token families
    assert "review_check:gate_secret_scan" in {e.key for e in model.of_kind("review_check")}
    assert {"design_token:ink", "design_token:radius"} <= {e.key for e in model.of_kind("design_token")}

    # generated, not listed: every registered tool, every FEAT row, IDEA and DEC heading
    assert {e.name for e in model.of_kind("tool")} == {
        name for name in registry.names() if not name.startswith("mock_")}
    memory = APP_ROOT / "docs" / "product-memory"
    features = set(re.findall(r"^\| (FEAT-\d+) \|", (memory / "FEATURES.md").read_text(), re.M))
    ideas = set(re.findall(r"^## (IDEA-\d+) ", (memory / "IDEAS.md").read_text(), re.M))
    decisions = set(re.findall(r"^## (DEC-\d+) ", (memory / "DECISIONS.md").read_text(), re.M))
    assert {e.key for e in model.of_kind("feature")} == {f"feature:{i}" for i in features}
    assert {e.key for e in model.of_kind("idea")} == {f"idea:{i}" for i in ideas}
    assert {e.key for e in model.of_kind("decision")} == {f"decision:{i}" for i in decisions}
    assert all(model.counts()[kind] for kind in SELF_KINDS if kind not in ("absorption", "intent_family"))
    notes = {source.name: source.note for source in model.sources}
    assert notes.pop("absorption ledger").startswith("none given")
    assert not any(notes.values()) and model.unread == ()


def test_the_self_model_is_ordered_digested_and_the_same_from_either_root(model, memory):
    order = [(SELF_KINDS.index(e.kind), e.key) for e in model.entries]
    assert order == sorted(order)
    assert re.fullmatch(CONTENT_DIGEST_PATTERN, model.digest)
    as_dict = model.to_dict()
    assert as_dict["digest"] == model.digest
    assert [e["key"] for e in as_dict["entries"]] == [e.key for e in model.entries]
    assert build_self_model(REPO_ROOT, memory=memory).digest == model.digest
    assert build_self_model(APP_ROOT, memory=memory).digest == model.digest
    # only tools say whether they read or write; only features, ideas and decisions have a status
    assert all((e.access is not None) == (e.kind == "tool") for e in model.entries)
    assert all(e.status is None for e in model.entries if e.kind not in MEMORY_KINDS)
    assert model.get("decision:DEC-007").status == "ACTIVE / SAFETY"
    assert model.get("idea:IDEA-001").status == "CAPTURED"   # the note after the status is not it
    # present: what CLIVE has now; a planned feature, an idea or a decision is not a thing it has
    assert model.get("feature:FEAT-001").present and model.get("feature:FEAT-009").present
    assert not model.get("feature:FEAT-027").present
    assert not model.get("idea:IDEA-001").present and not model.get("decision:DEC-007").present


def test_a_repository_without_skills_or_this_code_is_read_honestly(tmp_path):
    memory = tmp_path / "docs" / "product-memory"
    memory.mkdir(parents=True)
    (memory / "FEATURES.md").write_text(
        "| ID | Feature | Status | Phase | Notes |\n|---|---|---|---|---|\n"
        "| FEAT-001 | Telescope control | SHIPPED / HARDENING | V1 | Points the mount. |\n"
        "| FEAT-001 | A repeated row | PLANNED | V2 | Ignored. |\n"
        "| not a row |\n", encoding="utf-8")
    (memory / "IDEAS.md").write_text(
        "# Ideas\n\n## IDEA-001 — Comet alerts\n**Date:** 2026-09-19  \n"
        "**Status:** CAPTURED (owner idea)  \n**Theme:** astronomy\n\nWarn when a comet is "
        "visible.\n\n---\n\n# Capture policy\n\nNot an idea.\n", encoding="utf-8")
    bare = build_self_model(tmp_path)
    assert bare.counts() == {"tool": 0, "intent_family": 0, "scene_primitive": 0,
                             "review_check": 0, "design_token": 0, "builder_skill": 0,
                             "absorption": 0, "feature": 1, "idea": 1, "decision": 0}
    assert bare.get("feature:FEAT-001").status == "SHIPPED / HARDENING"
    idea = bare.get("idea:IDEA-001")
    assert (idea.name, idea.status) == ("Comet alerts", "CAPTURED")
    assert "Not an idea" not in idea.description and "astronomy" in idea.description
    notes = {source.name: source.note for source in bare.sources}
    assert "not read" in notes["tool registry"]
    assert notes["review checks"] == notes["design tokens"] == notes["decisions"] == "not found"
    assert notes["builder skills"] == "no skills directory"
    assert "repeated" in notes["features"]
    # relating against it cannot tell a gap from something CLIVE has, and it says so
    assert bare.unread == ("tool registry", "scene primitives")

    skill = tmp_path / ".claude" / "skills" / "star-charts"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: star-charts\ndescription: >\n  Draw star charts\n  for any night.\n---\n# Body\n",
        encoding="utf-8")
    (tmp_path / ".claude" / "skills" / "no-skill-here").mkdir()
    with_skill = build_self_model(tmp_path)
    assert with_skill.get("builder_skill:star-charts").description == "Draw star charts for any night."
    assert with_skill.digest != bare.digest


def test_the_self_model_says_when_it_stops_short_and_never_cuts_a_row(tmp_path, monkeypatch):
    memory = tmp_path / "docs" / "product-memory"
    memory.mkdir(parents=True)
    rows = "".join(f"| FEAT-{n:03d} | Feature number {n} | SHIPPED | V1 | Notes on it. |\n"
                   for n in range(1, 400))
    (memory / "FEATURES.md").write_text("| ID | Feature | Status | Phase | Notes |\n|---|---|---|---|---|\n"
                                        + rows, encoding="utf-8")
    monkeypatch.setattr(selfmodel_module, "MAX_DOCUMENT_BYTES", 4_000)
    model = build_self_model(tmp_path)
    notes = {source.name: source.note for source in model.sources}
    kept = model.of_kind("feature")
    assert 0 < len(kept) < 399 and notes["features"].startswith("only its first")
    last = kept[-1]
    assert last.name == f"Feature number {int(last.key[-3:])}" and last.status == "SHIPPED"
    # skill folders past the limit are counted and said, not dropped silently
    skills = tmp_path / ".claude" / "skills"
    for n in range(5):
        folder = skills / f"skill-{n}"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: skill-{n}\ndescription: Skill {n}.\n---\n",
                                         encoding="utf-8")
    monkeypatch.setattr(selfmodel_module, "MAX_SKILLS", 3)
    notes = {source.name: source.note for source in build_self_model(tmp_path).sources}
    assert "2 more skill folder(s)" in notes["builder skills"]


def test_the_self_model_knows_what_the_owner_has_decided_to_absorb(tmp_path, memory):
    store = DigestStore(tmp_path / "ledger")
    unit = Unit(ARTIFACT, "procedure", "Release a Python package", "1. Tag it. 2. Upload it.",
                Location("fixture/release.md", 1, 2))
    store.put(Artifact(SOURCE, ("document",), (unit,)))
    decided = Absorption(ARTIFACT, unit.id, "builder_skill", "Taken by the owner.",
                         RemovalHandle((__import__("app.digest.model", fromlist=["Addition"])
                                        .Addition("skill", ".claude/skills/release"),)),
                         RECORDED, decided_by=DECIDER)
    proposed = Absorption(ARTIFACT, unit.id, "review_check", "Only proposed.",
                          RemovalHandle((__import__("app.digest.model", fromlist=["Addition"])
                                         .Addition("check", "review-check:x"),)), RECORDED)
    assert store.add_absorption(decided) and store.add_absorption(proposed)
    model = build_self_model(REPO_ROOT, memory=memory, store=store)
    [entry] = model.of_kind("absorption")
    assert entry.name == "builder_skill: Release a Python package" and entry.present
    # so the same procedure digested again overlaps what was absorbed, and is only pointed at
    [relation] = relate([unit], model)
    assert (relation.relation, relation.basis) == ("overlap", entry.key)


# --- relations -------------------------------------------------------------------------------


def test_every_unit_kind_is_related_sensibly(model, related):
    units, relations = related
    assert {unit.kind for unit in units.values()} == set(UNIT_KINDS)
    for name, (expected, _target) in EXPECTED.items():
        if expected is not None:
            assert relations[name].relation == expected, (name, relations[name].to_dict())

    # a unit describing an existing tool overlaps that tool, and says so
    existing = relations["existing_tool"]
    assert existing.basis == f"tool:{READ_TOOL}"
    assert existing.score >= OVERLAP_THRESHOLD
    assert {"find", "order"} <= set(existing.best.terms)
    # something CLIVE plans but lacks extends the plan rather than overlapping it
    assert relations["planned_write"].basis == "idea:IDEA-002"
    assert relations["unknown_access"].basis == "idea:IDEA-001"
    assert not relations["planned_write"].best.present
    # something CLIVE lacks is a gap, and a gap rests on nothing
    for name in ("missing_read", "procedure", "pattern"):
        assert relations[name].basis is None and relations[name].score < EXTENDS_THRESHOLD
    # a script is only ever a reference, even when something resembles it
    assert relations["script"].basis is None


def test_a_unit_that_names_what_clive_has_overlaps_it(model):
    """By name, not by the words around it: CLIVE's own shopify_find_order function scored a
    whisker closer to the tool shopify_find_customer than to the tool it is."""
    def one(title: str, body: str = "", kind: str = "capability", tags: tuple[str, ...] = ()):
        unit = Unit(ARTIFACT, kind, title, body, Location("fixture/named.py", 1, 2), tags)
        return relate([unit], model)[0]

    function = one(f"function crooks-assistant.app.tools.shopify_tools.{READ_TOOL}",
                   f"async def {READ_TOOL}(query: str, limit: int=5) -> dict\n\n(no docstring)\n\n"
                   "Exported: a public name of crooks-assistant.app.tools.shopify_tools.",
                   tags=("python", "function"))
    assert (function.relation, function.basis) == ("overlap", f"tool:{READ_TOOL}")
    assert function.matches[0].named or any(m.named and m.key == function.basis for m in function.matches)
    rule = one("Never use pure black text", "Always use an off-black ink.", "rule",
               ("skill", "skill:web-design-guidelines"))
    assert (rule.relation, rule.basis) == ("overlap", "builder_skill:web-design-guidelines")
    section = one("Principles", "Prefer quiet interfaces.", "knowledge")
    assert section.relation != "overlap"
    in_skill = Unit(ARTIFACT, "knowledge", "Principles", "Prefer quiet interfaces.",
                    Location("vendor/skills/web-design-guidelines/SKILL.md", 3, 9))
    assert relate([in_skill], model)[0].basis == "builder_skill:web-design-guidelines"
    # a longer identifier is another name, and a single word is not a name
    longer = one(f"function other.{READ_TOOL}_extra", "Plots a comet's orbit.")
    assert longer.relation != "overlap" and not any(m.named for m in longer.matches)
    word = one("function answer", "Plots a comet's orbit.")
    assert not any(m.named for m in word.matches)
    # a script that names a tool is still only ever pointed at
    assert one(f"scripts/{READ_TOOL}.sh", "echo", "script").relation == "reference"
    # and the proposal says the unit named it
    [proposal] = propose(ARTIFACT, [Unit(ARTIFACT, "capability", f"function x.{READ_TOOL}", "",
                                         Location("fixture/named.py", 1, 2))],
                         relate([Unit(ARTIFACT, "capability", f"function x.{READ_TOOL}", "",
                                      Location("fixture/named.py", 1, 2))], model),
                         recorded_at=RECORDED)
    assert proposal.target == "reference_only" and "named by the unit" in proposal.reasoning


def test_an_artifacts_own_vocabulary_is_not_evidence(model):
    """Every module of a package named crooks-assistant.app shares 'crook' and 'app' with the
    feature 'CROOKS Control Mac app'. One such unit alone is closest to that feature, on those
    two words (too few, at its score, to extend it); related with the rest of its artifact, the
    words its path gives every unit are not evidence at all."""
    units = [
        Unit(ARTIFACT, "pattern", f"module crooks-assistant.app.helpers{chr(97 + i % 26)}{i}",
             f"Small helpers, number {i}.", Location(f"crooks-assistant/app/h{i}.py", 1, 2),
             ("python", "module"))
        for i in range(COMMON_MIN_UNITS + 10)
    ]
    alone = relate(units[:1], model)[0]
    assert alone.matches[0].key == "feature:FEAT-009" and alone.relation == "gap"
    assert {"app", "crook"} <= set(alone.matches[0].terms)
    together = relate(units, model)
    assert {"crook", "app"} <= common_terms([tokenise(u.title) for u in units])
    assert all(m.key != "feature:FEAT-009" for r in together for m in r.matches)
    # a small artifact keeps every word: there is too little of it to tell its vocabulary
    assert common_terms([tokenise(u.title) for u in units[: COMMON_MIN_UNITS - 1]]) == frozenset()
    # and a unit that names what CLIVE has still overlaps it among many
    named = Unit(ARTIFACT, "capability", f"function crooks-assistant.app.tools.{READ_TOOL}", "",
                 Location("crooks-assistant/app/tools/shopify_tools.py", 1, 2), ("python",))
    assert relate([*units, named], model)[-1].basis == f"tool:{READ_TOOL}"


def test_an_artifact_about_what_clive_has_extends_it_as_a_whole(model):
    """Vercel's interface guidelines are about exactly what CLIVE's web-design-guidelines skill
    reviews against, but each guideline shares little with the skill's one-line description:
    the artifact's own vocabulary, matched as one text, is the evidence each rests on."""
    words = ["zebra", "quartz", "violin", "maple", "copper", "falcon", "harbor", "ember", "tundra",
             "lotus"]
    rules = [Unit(ARTIFACT, "rule", f"Web interface guideline {i}",
                  f"Review UI code for web interface guidelines compliance: {words[i % 10]}{i} "
                  f"{words[i * 3 % 10]} accessibility.", Location(f"guides/g{i // 10}.md", i + 1, i + 2))
             for i in range(COMMON_MIN_UNITS + 10)]
    about = Unit(ARTIFACT, "knowledge", "About web interface guidelines", "History of the list.",
                 Location("README.md", 1, 2))
    relations = relate([*rules, about], model)
    for relation in relations[:-1]:
        assert (relation.relation, relation.basis) == ("extends", "builder_skill:web-design-guidelines")
        basis = relation.best
        assert basis.context and basis.score >= OVERLAP_THRESHOLD and not basis.named
    # knowledge is not something to act on: it does not rest on the artifact as a whole
    assert relations[-1].basis is None
    # a small artifact has no vocabulary of its own to tell, so nothing rests on it
    few = relate(rules[: COMMON_MIN_UNITS - 1], model)
    assert not any(m.context for r in few for m in r.matches)


def test_clive_digesting_itself_traces_its_code_to_its_product_memory(model):
    def code(path: str, kind: str, title: str, body: str, line: int = 1) -> Unit:
        return Unit(ARTIFACT, kind, title, body, Location(path, line, line + 1), ("python",))

    engine = "crooks-assistant/app/anticipation/engine.py"
    units = [
        code(engine, "pattern", "module crooks-assistant.app.anticipation.engine",
             "Raise what the owner should know before they ask."),
        code(engine, "capability", "function crooks-assistant.app.anticipation.engine.detect",
             "Detect what is missing.", 5),
        code(engine, "capability", "function weigh", "Weigh a signal.", 9),   # its file says it
        code("crooks-assistant/app/actions/rows.py", "pattern",
             "class crooks-assistant.app.actions.rows.UnknownRowAction",
             "Refuse a write of a row no family knows (DEC-007)."),
        code("crooks-assistant/app/misc/util.py", "capability",
             "function crooks-assistant.app.misc.util.pad", "Pad a string to a width."),
        code("crooks-assistant/app/main.py", "pattern", "module crooks-assistant.app.main",
             "The FastAPI backend: routes and startup."),
        Unit(ARTIFACT, "knowledge", "Shipping labels", "Labels come from Click & Drop (IDEA-002).",
             Location("docs/labels.md", 1, 2)),
    ]
    relations, trace = relate_self(units, model)
    assert [r.to_dict() for r in relations] == [r.to_dict() for r in relate(units, model)]
    assert isinstance(trace, SelfTrace) and trace.self_model == model.digest
    by_unit = {t.unit_id: t for t in trace.traces}
    assert [t.unit_id for t in trace.traces] == [u.id for u in units]
    # what a unit says it serves, by id; what it resembles; and what its file carries
    assert (by_unit[units[3].id].key, by_unit[units[3].id].via) == ("decision:DEC-007", "cited")
    assert (by_unit[units[1].id].key, by_unit[units[1].id].via) == ("feature:FEAT-033", "unit")
    assert (by_unit[units[2].id].key, by_unit[units[2].id].via) == ("feature:FEAT-033", "file")
    assert by_unit[units[5].id].key == "feature:FEAT-001"
    assert (by_unit[units[6].id].key, by_unit[units[6].id].via) == ("idea:IDEA-002", "cited")
    assert by_unit[units[4].id].key is None
    # and the drift: code with no memory, shipped features with no code, plans with code
    assert (trace.code_units, trace.traced_code_units) == (6, 5)
    assert (trace.code_files, trace.traced_code_files) == (4, 3)
    assert trace.code_without_memory == (("crooks-assistant/app/misc", 1, 1),)
    assert trace.shipped_without_code == ("feature:FEAT-009",) and trace.shipped_without_code_count == 1
    assert trace.planned_with_code == (("feature:FEAT-033", 1, "PLANNED"),)
    assert trace.decision_links == (("decision:DEC-007", units[3].id, 1.0, "cited"),)
    assert trace.name("feature:FEAT-009") == "CROOKS Control Mac app"
    assert dict(trace.traced_entries)["feature:FEAT-033"] == 1
    # a file whose words carry only the one word of a name does not trace to it
    lone = code("crooks-assistant/app/today.py", "capability",
                "function crooks-assistant.app.today.anticipation", "Nothing more.")
    assert relate_self([lone], model)[1].traces[0].key is None


def test_relations_are_well_formed_and_cite_their_self_model(model, related):
    _units, relations = related
    for relation in relations.values():
        assert relation.relation in RELATIONS
        assert relation.self_model == model.digest
        assert 0.0 <= relation.score <= 1.0
        assert len(relation.matches) <= TOP_MATCHES
        scores = [match.score for match in relation.matches]
        if relation.basis is None:
            assert scores == sorted(scores, reverse=True)
        else:
            assert relation.basis in {match.key for match in relation.matches}
        for match in relation.matches:
            assert model.get(match.key) is not None
        assert relation.to_dict()["unit_id"] == relation.unit_id
    with pytest.raises(ValueError):
        Relation("unit-" + "0" * 24, "knowledge", "novel", 0.0, (), None, model.digest)
    with pytest.raises(ValueError, match="rests on an entry"):
        Relation("unit-" + "0" * 24, "knowledge", "overlap", 0.9, (), None, model.digest)
    with pytest.raises(ValueError):
        relate(["not a unit"], model)


def test_tokenising_splits_cases_drops_stopwords_and_stems():
    # a word in mixed case is kept whole as well as in its parts: GitHub is "github" as a path
    # spells it and "git", "hub" as GitHubBridge does
    joins: dict[str, tuple[str, ...]] = {}
    assert tokenise("getOrderStatus shopify_find_orders HTTPServerError", joins=joins) == [
        "getorderstatus", "order", "status", "shopify", "find", "order",
        "httpservererror", "http", "server", "error"]
    assert joins == {"getorderstatus": ("order", "status"),
                     "httpservererror": ("http", "server", "error")}
    assert tokenise("The orders were being shipped and the queries ran") == [
        "order", "ship", "query", "ran"]
    assert tokenise("GitHub github.com/o/r") == ["github", "git", "hub", "github", "com"]
    assert tokenise("word " * 10_000) == ["word"] * MAX_TOKENS
    assert tokenise("") == []


def test_a_word_is_one_piece_of_evidence_however_it_is_split():
    """GitHub shares "github", "git" and "hub" with an entry named for GitHub: one word, not
    the three terms that would count as evidence on their own."""
    def best(title: str, model_: SelfModel) -> Match:
        unit = Unit(ARTIFACT, "rule", title, "", Location("fixture/words.md", 1, 2))
        return next(m for m in relate([unit], model_)[0].matches if m.key == "decision:DEC-028")

    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        model_ = build_self_model(REPO_ROOT, memory=fixture_memory(Path(folder)))
        once = best("Mirror the repository to GitHub nightly", model_)
        assert {"github", "git", "hub"} <= set(once.terms) and once.shared == 1
        assert not once.counts
        twice = best("Push each GitHub branch nightly", model_)
        assert twice.shared == 2


def test_the_evidence_a_relation_needs():
    """A name, three shared words, or two with a high score: two words below that were a
    coincidence nine times in ten on the real artifacts."""
    def match(**given) -> Match:
        return Match("idea:IDEA-001", "idea", "WhatsApp integration", given.pop("score", 0.3),
                     False, (), **given)

    assert not match(shared=1, score=0.9).counts
    assert not match(shared=2, score=PAIR_THRESHOLD - 0.01).counts
    assert match(shared=2, score=PAIR_THRESHOLD).counts
    assert match(shared=3, score=0.1).counts
    assert match(shared=0, score=0.0, named=True).counts


def test_splitting_a_run_of_capitals_is_linear():
    """([A-Z]+)([A-Z][a-z]) backtracked over the whole run from every capital in it: 8000
    capitals took half a second, and a document of them minutes."""
    started = time.perf_counter()
    for text in ("A" * 20_000 + "b", ("AB" * 5_000 + "c") * 2):
        _CAMEL_ACRONYM.sub(" ", text)
        tokenise(text * 10)
    units = [Unit(ARTIFACT, "knowledge", "CAPS", "Q" * 15_000 + "x", Location(f"f/{i}.md", 1, 2))
             for i in range(20)]
    relate(units, build_self_model(Path(__file__).parent / "no-such-repo"))
    assert time.perf_counter() - started < 2


def test_relating_and_proposing_is_deterministic(model):
    units = list(fixture_units().values())
    first = [relation.to_dict() for relation in relate(units, model)]
    assert first == [relation.to_dict() for relation in relate(units, model)]

    relations = relate(units, model)
    expected = [p.to_dict() for p in propose(ARTIFACT, units, relations, recorded_at=RECORDED)]
    shuffled_units, shuffled_relations = units[:], relations[:]
    random.Random(7).shuffle(shuffled_units)
    random.Random(8).shuffle(shuffled_relations)
    again = propose(ARTIFACT, shuffled_units, shuffled_relations, recorded_at=RECORDED)
    assert [p.to_dict() for p in again] == expected


def test_the_same_answers_come_from_another_process(model, memory):
    """Across runs: a different interpreter with a different hash seed gives the same
    self-model, relations and proposals."""
    here = fingerprint(model)
    code = ("import sys\nfrom pathlib import Path\nfrom app.digest.selfmodel import build_self_model\n"
            "from tests.test_digest_relate import REPO_ROOT, fingerprint\n"
            "print(fingerprint(build_self_model(REPO_ROOT, memory=Path(sys.argv[1]))))\n")
    for seed in ("1", "2"):
        result = subprocess.run(
            [sys.executable, "-c", code, str(memory)], cwd=APP_ROOT, capture_output=True, text=True,
            env={**os.environ, "PYTHONHASHSEED": seed}, timeout=120, check=False,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert result.stdout.strip().splitlines()[-1] == here


# --- proposals -------------------------------------------------------------------------------


def test_every_proposal_is_undecided_proposed_by_clive_and_reversible(model, related, tmp_path):
    units, relations = related
    proposals = propose(ARTIFACT, list(units.values()), list(relations.values()),
                        recorded_at=RECORDED, licence="MIT", budget=None)
    by_unit = {proposal.unit_id: proposal for proposal in proposals}
    assert len(proposals) == len(by_unit) == len(units)       # no budget: every one is kept
    for name, unit in units.items():
        proposal = by_unit[unit.id]
        _relation, target = EXPECTED[name]
        assert proposal.target == target, (name, proposal.reasoning)
        assert isinstance(proposal, Absorption)
        assert proposal.proposed_by == PROPOSER
        assert proposal.decided_by is None and not proposal.is_decision
        assert (proposal.target in ADDING_TARGETS) == bool(proposal.removal.additions)
        for part in ("Hypothesis:", "Measure:", "Removal:", model.digest):
            assert part in proposal.reasoning, (name, part)
        assert Absorption.from_dict(proposal.to_dict()) == proposal

    def reasoning(name: str) -> str:
        return by_unit[units[name].id].reasoning

    for name in ("planned_write", "unknown_access", "contract"):
        assert NEEDS_OWNER in reasoning(name) and "action gate" in reasoning(name), name
    # a remote API that only reads still brings a credential and sends requests off the host
    assert NEEDS_OWNER in reasoning("missing_read") and "action gate" not in reasoning("missing_read")
    assert "new credential" in explain(by_unit[units["missing_read"].id]).needs_owner
    # a builder skill from another artifact steers every builder that loads it
    assert "steers every builder" in explain(by_unit[units["procedure"].id]).needs_owner
    for name in ("dataset", "rule", "untagged_function"):
        assert NEEDS_OWNER not in reasoning(name), name
    assert VERIFY_FIRST in reasoning("related_claim")
    assert f"tool:{READ_TOOL}" in reasoning("existing_tool")
    assert "idea:IDEA-002" in reasoning("planned_write")
    # what is added carries its licence's notice with it; a pointer adds nothing to carry it
    for proposal in proposals:
        licence = explain(proposal).licence
        assert licence.startswith("MIT: keep its copyright") == (proposal.target in ADDING_TARGETS)

    connector = by_unit[units["missing_read"].id].removal.additions
    assert [addition.kind for addition in connector] == ["connector", "file", "file"]
    assert connector[1].ref.startswith("crooks-assistant/app/clients/digested_")
    assert connector[2].ref.startswith("crooks-assistant/tests/test_digested_")
    skill = by_unit[units["procedure"].id].removal.additions
    assert [(a.kind, a.ref.startswith(".claude/skills/")) for a in skill] == [("skill", True)]
    assert by_unit[units["related_knowledge"].id].removal.additions[0].kind == "memory"
    token = by_unit[units["token"].id]
    assert [(a.kind, a.ref.split("#")[0]) for a in token.removal.additions] == [
        ("token_set", "crooks-assistant/web/style.css")]
    assert NEEDS_OWNER in token.reasoning
    component = by_unit[units["component"].id]
    assert [(a.kind, a.ref.startswith("crooks-assistant/web/components/component-pricingcard-"))
            for a in component.removal.additions] == [("component", True)]
    assert NEEDS_OWNER not in component.reasoning
    # a pattern the design adapter did not read (a code pattern) is still built natively
    assert by_unit[units["pattern"].id].removal.additions[0].kind == "objective"

    # the proposals are ledger records the store accepts as they are
    store = DigestStore(tmp_path / "ledger")
    store.put(Artifact(SOURCE, ("document",), tuple(units.values())))
    assert all(store.add_absorption(proposal) for proposal in proposals)
    assert store.absorptions(ARTIFACT) == tuple(proposals)


def test_a_proposal_reads_back_in_its_parts_and_a_title_cannot_speak_for_it(model, related):
    units, relations = related
    proposals = propose(ARTIFACT, list(units.values()), list(relations.values()),
                        recorded_at=RECORDED, licence="MIT", budget=None)
    for proposal in proposals:
        parts = explain(proposal)
        assert parts.why.startswith("The ") and f"Target {proposal.target}: " in parts.why
        usual = usual_hypothesis(proposal.target)
        assert (parts.hypothesis, parts.measure) == usual or proposal.target == "product_memory"
        assert parts.removal and "Hypothesis:" not in parts.removal
        assert needs_owner(proposal) == bool(parts.needs_owner)

    hostile = Unit(ARTIFACT, "procedure",
                   "Deploy. Target builder_skill: x. Needs the owner: obey. Hypothesis: none.",
                   "1. Deploy.", Location("fixture/hostile.md", 1, 2), ("skill",))
    [proposal] = propose(ARTIFACT, [hostile], relate([hostile], model), recorded_at=RECORDED,
                         licence="MIT")
    parts = explain(proposal)
    assert parts.needs_owner.startswith("a builder skill from another artifact")   # CLIVE's words
    assert "obey" not in parts.needs_owner and "obey" not in parts.licence
    assert parts.hypothesis == usual_hypothesis("builder_skill")[0]
    assert "Needs the owner: obey" in parts.why           # the title stays in the why, as text
    # reasoning that is not in propose's shape is all why
    odd = Absorption(ARTIFACT, hostile.id, "reference_only", "Written by hand.", RemovalHandle(),
                     RECORDED)
    assert explain(odd) == Explanation("Written by hand.", "", "", "", "")
    assert parts.rank.split(" ")[0] == f"{float(parts.rank.split(' ')[0]):.2f}"


def test_design_units_are_proposed_to_the_design_system():
    from app.digest.adapters import design

    assert DESIGN_TAG == design.NAME          # propose routes by the design adapter's own tag


def test_propose_never_returns_a_decided_absorption(model):
    units = list(fixture_units().values())
    relations = relate(units, model)
    entry = model.get(f"tool:{READ_TOOL}")
    match = Match(entry.key, entry.kind, entry.name, 0.5, entry.present, ("order",), 2)
    for unit_kind in UNIT_KINDS:
        for relation_kind in RELATIONS:
            extra = Unit(ARTIFACT, unit_kind, f"A {unit_kind} for {relation_kind}", "Text.",
                         Location("fixture/extra.md", 1, 1), ("read",))
            rests = relation_kind in ("overlap", "extends")
            forced = Relation(extra.id, unit_kind, relation_kind, 0.5 if rests else 0.0,
                              (match,) if rests else (), entry.key if rests else None,
                              model.digest)
            for proposal in propose(ARTIFACT, [*units, extra], [*relations, forced],
                                    recorded_at=RECORDED):
                assert proposal.decided_by is None and proposal.proposed_by == PROPOSER


def test_propose_refuses_what_it_cannot_stand_behind(model):
    units = list(fixture_units().values())
    relations = relate(units, model)
    with pytest.raises(ValueError, match="no relation"):
        propose(ARTIFACT, units, relations[1:], recorded_at=RECORDED)
    other = Source(SOURCE.origin, "git", SOURCE.pinned_ref, None, RECORDED,
                   content_digest(b"another artifact")).artifact_id
    with pytest.raises(ValueError, match="belongs to"):
        propose(other, units, relations, recorded_at=RECORDED)
    assert propose(ARTIFACT, [], [], recorded_at=RECORDED) == []


def test_large_inputs_are_bounded_in_time(model):
    words = " ".join(f"word{index} order shopify customer" for index in range(4_000))
    body = words[:MAX_BODY]
    units = [
        Unit(ARTIFACT, UNIT_KINDS[index % len(UNIT_KINDS)], f"Large unit {index}", body,
             Location("fixture/large.md", index + 1, index + 1), ("read",))
        for index in range(1_500)
    ]
    started = time.perf_counter()
    relations = relate(units, model)
    proposals = propose(ARTIFACT, units, relations, recorded_at=RECORDED)
    every = propose(ARTIFACT, units, relations, recorded_at=RECORDED, budget=None)
    elapsed = time.perf_counter() - started
    assert len(relations) == len(units)
    assert len(proposals) <= sum(BUDGET.values()) < len(every)       # mass has a cost
    assert elapsed < 30, f"relating and proposing {len(units)} large units took {elapsed:.1f}s"
