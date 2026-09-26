"""The Knowledge Digester's relation stage: CLIVE's self-model, generated from this repository;
each Unit related to it deterministically and explainably; and absorption proposals that are
proposed by CLIVE, decided by no one, and always carry their way back."""

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
from app.digest.model import CONTENT_DIGEST_PATTERN, MAX_BODY
from app.digest.propose import NEEDS_OWNER, VERIFY_FIRST, propose
from app.digest.relate import (
    EXTENDS_THRESHOLD,
    MAX_TOKENS,
    OVERLAP_THRESHOLD,
    RELATIONS,
    TOP_MATCHES,
    Match,
    Relation,
    relate,
    tokenise,
)
from app.digest.selfmodel import SELF_KINDS, SelfModel, build_self_model

# The tool matrix (experience/tool_matrix.py) counts a test file that names a tool or an intent
# family as testing it. This file only looks them up in the self-model, so their names are
# assembled here rather than written out, and the matrix stays honest.
READ_TOOL = "shopify_" + "find_order"
WRITE_TOOL = "shopify_" + "order_cancel"
FAMILY = "order_" + "lookup"

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
RECORDED = "2026-09-26T10:00:00+00:00"
SOURCE = Source(
    origin="https://example.invalid/digest-fixture.git", origin_kind="git",
    pinned_ref="0123456789abcdef0123456789abcdef01234567", licence="MIT", taken_at=RECORDED,
    content_digest=content_digest(b"the relation fixture"),
)
ARTIFACT = SOURCE.artifact_id


def _unit(name: str, kind: str, title: str, body: str, tags: tuple[str, ...] = (),
          line: int = 1) -> tuple[str, Unit]:
    return name, Unit(ARTIFACT, kind, title, body, Location("fixture/README.md", line, line + 1),
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
        _unit("related_knowledge", "knowledge", "Shopify order fulfilment",
              "In Shopify an order is fulfilled when its line items ship; a fulfilment carries "
              "the tracking number.", (), 23),
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
    "untagged_function": ("gap", "tool_connector"),
    "procedure": ("gap", "builder_skill"),
    "rule": ("gap", "review_check"),
    "check": ("gap", "review_check"),
    "contract": ("extends", "tool_connector"),
    "lonely_contract": ("gap", "reference_only"),
    "pattern": ("gap", "native_objective"),
    "related_knowledge": ("extends", "product_memory"),
    "unrelated_knowledge": ("reference", "reference_only"),
    "dataset": ("extends", "tool_connector"),
    "personal_dataset": (None, "reference_only"),
    "token": ("gap", "native_objective"),
    "example": ("reference", "reference_only"),
    "dependency": ("gap", "reference_only"),
    "script": ("reference", "reference_only"),
    "unrelated_claim": ("reference", "reference_only"),
    "related_claim": ("extends", "product_memory"),
    "unparsed": (None, "reference_only"),
}


@pytest.fixture(scope="module")
def model() -> SelfModel:
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
    proposals = propose(ARTIFACT, units, relations, recorded_at=RECORDED)
    payload = {
        "self_model": model.digest,
        "relations": [relation.to_dict() for relation in relations],
        "proposals": [proposal.to_dict() for proposal in proposals],
    }
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- the self-model --------------------------------------------------------------------------


def test_the_self_model_is_generated_from_this_repository(model):
    from app.tools import registry

    assert model.get(f"tool:{READ_TOOL}").access == "read"
    assert model.get(f"tool:{WRITE_TOOL}").access == "write"
    assert model.get(f"intent_family:{FAMILY}").kind == "intent_family"
    assert READ_TOOL in model.get(f"intent_family:{FAMILY}").description
    assert {"scene_primitive:answer", "scene_primitive:trend", "scene_primitive:proposal"} <= {
        entry.key for entry in model.of_kind("scene_primitive")}
    feature = model.get("feature:FEAT-001")
    assert (feature.name, feature.status) == ("Existing FastAPI CROOKS backend", "SHIPPED")
    idea = model.get("idea:IDEA-001")
    assert (idea.name, idea.status) == ("WhatsApp integration", "CAPTURED")
    assert model.get("idea:IDEA-060").status == "CAPTURED"   # the note after the status is not it
    assert model.get("builder_skill:web-design-guidelines").description.startswith("Review UI code")

    # generated, not listed: every registered tool, every FEAT row and every IDEA heading
    assert {e.name for e in model.of_kind("tool")} == {
        name for name in registry.names() if not name.startswith("mock_")}
    memory = APP_ROOT / "docs" / "product-memory"
    features = set(re.findall(r"^\| (FEAT-\d+) \|", (memory / "FEATURES.md").read_text(), re.M))
    ideas = set(re.findall(r"^## (IDEA-\d+) ", (memory / "IDEAS.md").read_text(), re.M))
    assert {e.key for e in model.of_kind("feature")} == {f"feature:{i}" for i in features}
    assert {e.key for e in model.of_kind("idea")} == {f"idea:{i}" for i in ideas}
    assert all(model.counts()[kind] for kind in SELF_KINDS)
    assert all(not source.note for source in model.sources)


def test_the_self_model_is_ordered_digested_and_the_same_from_either_root(model):
    order = [(SELF_KINDS.index(e.kind), e.key) for e in model.entries]
    assert order == sorted(order)
    assert re.fullmatch(CONTENT_DIGEST_PATTERN, model.digest)
    as_dict = model.to_dict()
    assert as_dict["digest"] == model.digest
    assert [e["key"] for e in as_dict["entries"]] == [e.key for e in model.entries]
    assert build_self_model(REPO_ROOT).digest == model.digest
    assert build_self_model(APP_ROOT).digest == model.digest
    # only tools say whether they read or write; only features and ideas have a status
    assert all((e.access is not None) == (e.kind == "tool") for e in model.entries)
    assert all(e.status is None for e in model.entries if e.kind not in ("feature", "idea"))


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
                             "feature": 1, "idea": 1, "builder_skill": 0}
    assert bare.get("feature:FEAT-001").status == "SHIPPED / HARDENING"
    idea = bare.get("idea:IDEA-001")
    assert (idea.name, idea.status) == ("Comet alerts", "CAPTURED")
    assert "Not an idea" not in idea.description and "astronomy" in idea.description
    notes = {source.name: source.note for source in bare.sources}
    assert "not read" in notes["tool registry"]
    assert notes["builder skills"] == "no skills directory"
    assert "repeated" in notes["features"]

    skill = tmp_path / ".claude" / "skills" / "star-charts"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: star-charts\ndescription: >\n  Draw star charts\n  for any night.\n---\n# Body\n",
        encoding="utf-8")
    (tmp_path / ".claude" / "skills" / "no-skill-here").mkdir()
    with_skill = build_self_model(tmp_path)
    assert with_skill.get("builder_skill:star-charts").description == "Draw star charts for any night."
    assert with_skill.digest != bare.digest


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
    assert tokenise("getOrderStatus shopify_find_orders HTTPServerError") == [
        "order", "status", "shopify", "find", "order", "http", "server", "error"]
    assert tokenise("The orders were being shipped and the queries ran") == [
        "order", "ship", "query", "ran"]
    assert tokenise("word " * 10_000) == ["word"] * MAX_TOKENS
    assert tokenise("") == []


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


def test_the_same_answers_come_from_another_process(model):
    """Across runs: a different interpreter with a different hash seed gives the same
    self-model, relations and proposals."""
    here = fingerprint(model)
    code = ("from pathlib import Path\nfrom app.digest.selfmodel import build_self_model\n"
            "from tests.test_digest_relate import REPO_ROOT, fingerprint\n"
            "print(fingerprint(build_self_model(REPO_ROOT)))\n")
    for seed in ("1", "2"):
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=APP_ROOT, capture_output=True, text=True,
            env={**os.environ, "PYTHONHASHSEED": seed}, timeout=120, check=False,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert result.stdout.strip().splitlines()[-1] == here


# --- proposals -------------------------------------------------------------------------------


def test_every_proposal_is_undecided_proposed_by_clive_and_reversible(model, related, tmp_path):
    units, relations = related
    proposals = propose(ARTIFACT, list(units.values()), list(relations.values()),
                        recorded_at=RECORDED)
    by_unit = {proposal.unit_id: proposal for proposal in proposals}
    assert len(proposals) == len(by_unit) == len(units)
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

    for name in ("planned_write", "unknown_access", "untagged_function", "contract"):
        assert NEEDS_OWNER in reasoning(name) and "action gate" in reasoning(name), name
    for name in ("missing_read", "dataset", "procedure", "rule"):
        assert NEEDS_OWNER not in reasoning(name), name
    assert VERIFY_FIRST in reasoning("related_claim")
    assert f"tool:{READ_TOOL}" in reasoning("existing_tool")
    assert "idea:IDEA-002" in reasoning("planned_write")

    read_tool = by_unit[units["missing_read"].id].removal.additions
    assert [addition.kind for addition in read_tool] == ["tool", "file", "file"]
    assert read_tool[1].ref.startswith("crooks-assistant/app/tools/digested_")
    assert read_tool[2].ref.startswith("crooks-assistant/tests/test_digested_")
    skill = by_unit[units["procedure"].id].removal.additions
    assert [(a.kind, a.ref.startswith(".claude/skills/")) for a in skill] == [("skill", True)]
    assert by_unit[units["related_knowledge"].id].removal.additions[0].kind == "memory"
    assert by_unit[units["token"].id].removal.additions[0].kind == "objective"

    # the proposals are ledger records the store accepts as they are
    store = DigestStore(tmp_path / "ledger")
    store.put(Artifact(SOURCE, ("document",), tuple(units.values())))
    assert all(store.add_absorption(proposal) for proposal in proposals)
    assert store.absorptions(ARTIFACT) == tuple(proposals)


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
    elapsed = time.perf_counter() - started
    assert len(relations) == len(proposals) == len(units)
    assert elapsed < 30, f"relating and proposing {len(units)} large units took {elapsed:.1f}s"
