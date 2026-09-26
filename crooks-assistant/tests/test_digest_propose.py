"""Proposals worth reading: each scored and ranked, bounded per target (mass has a cost), a
skill proposed whole, licences honoured, remote APIs and partly profiled data left to the owner,
a credential never quoted, and nothing proposed as missing when the self-model cannot tell.

The self-model is this repository's registries with the relation tests' fixture product memory
(tests/test_digest_relate.py), so editing FEATURES.md or IDEAS.md does not move these."""

from __future__ import annotations

import json
import re

import pytest

from app.digest import scan
from app.digest.model import (
    ADDING_TARGETS,
    Finding,
    Location,
    Source,
    Unit,
    content_digest,
)
from app.digest.propose import (
    BUDGET,
    OWNER_COST,
    PROJECT_COST,
    REMOTE_API,
    UNLICENSED_COST,
    explain,
    needs_owner,
    proposals,
    propose,
)
from app.digest.relate import relate
from app.digest.selfmodel import build_self_model
from tests.fake_credentials import github_token, password
from tests.test_digest_relate import REPO_ROOT, fixture_memory

RECORDED = "2026-09-26T10:00:00+00:00"
SOURCE = Source(
    origin="https://example.invalid/propose-fixture.git", origin_kind="git",
    pinned_ref="89abcdef0123456789abcdef0123456789abcdef", licence="MIT", taken_at=RECORDED,
    content_digest=content_digest(b"the proposal fixture"),
)
ARTIFACT = SOURCE.artifact_id
MIT = ("MIT", "LICENSE")
# A credential-shaped value, assembled here so that no scanner finds one in this file.
TOKEN = github_token("digest-propose")
HOST_PASSWORD = password("digest-propose")


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    return build_self_model(REPO_ROOT, memory=fixture_memory(tmp_path_factory.mktemp("memory")))


def _u(path: str, kind: str, title: str, body: str = "", tags: tuple[str, ...] = (),
       line: int = 1) -> Unit:
    return Unit(ARTIFACT, kind, title, body, Location(path, line, line + 1), tags)


def _propose(units: list[Unit], model, **given):
    given.setdefault("licences", {"": MIT})
    return proposals(ARTIFACT, units, relate(units, model), recorded_at=RECORDED, **given)


def _score(proposal) -> float:
    return float(explain(proposal).rank.split(" ")[0])


PROCEDURE = ("1. Write the release notes from the merged changes.\n2. Bump the version and tag "
             "the release.\n3. Build the wheel and the sdist.\n4. Upload both and check the page.")


# --- ranked and bounded -------------------------------------------------------------------------


def test_proposals_are_ranked_best_first_and_each_target_is_bounded(model):
    units = [_u(f"guides/g{n:02d}.md", "procedure", f"Publish release variant {n}",
                f"{PROCEDURE}\nVariant {n}: " + " ".join(f"step{n}x{k}" for k in range(n)))
             for n in range(12)]
    units += [_u(f"notes/n{n:02d}.md", "knowledge", f"Parcel labels note {n}",
                 "Royal Mail Click & Drop shipping labels carry each parcel's tracking number. "
                 + " ".join(f"word{n}x{k}" for k in range(40))) for n in range(14)]
    made = _propose(units, model)
    kept = made.kept
    targets = [p.target for p in kept]
    assert targets.count("builder_skill") == BUDGET["builder_skill"]
    assert targets.count("product_memory") == BUDGET["product_memory"]
    assert made.held_counts() == {"builder_skill": 7, "product_memory": 4}
    # best first, and every one says how it ranked
    scores = [_score(p) for p in kept]
    assert scores == sorted(scores, reverse=True)
    assert all(re.fullmatch(r"\d\.\d\d \(target value .*cost \d\.\d\d\)", explain(p).rank) for p in kept)
    # what was held back is still reachable: by unit, and all of it with no budget
    held = dict(made.held)
    assert set(held["builder_skill"]) | {p.unit_id for p in kept} >= {u.id for u in units[:12]}
    every = _propose(units, model, budget=None)
    assert len(every.kept) == len(units) and every.held == ()
    # a budget of its own; a target it does not name keeps nothing
    two = _propose(units, model, budget={"builder_skill": 2})
    assert [p.target for p in two.kept] == ["builder_skill", "builder_skill"]
    assert propose(ARTIFACT, units, relate(units, model), recorded_at=RECORDED,
                   licences={"": MIT}) == list(made.kept)


def test_a_repeat_is_folded_into_the_first_of_it(model):
    same = [_u(f"copies/c{n}.md", "procedure", "Publish a release", PROCEDURE) for n in range(3)]
    made = _propose(same, model)
    assert len(made.kept) == 1 and made.kept[0].unit_id == same[0].id
    assert made.held == (("builder_skill", (same[1].id, same[2].id)),)


# --- one proposal for a whole -------------------------------------------------------------------


def _skill(folder: str, name: str, extra: tuple[Unit, ...] = ()) -> list[Unit]:
    tag = (f"skill:{name}",)
    path = f"{folder}/SKILL.md"
    return [
        _u(path, "knowledge", name, f"{name}: draw star charts for any night sky.", tag, 1),
        _u(path, "procedure", "Plot the stars", PROCEDURE, tag, 10),
        _u(path, "procedure", "Label the constellations", PROCEDURE + " Label them.", tag, 20),
        _u(path, "procedure", "Export the chart", PROCEDURE + " Export it.", tag, 30),
        _u(path, "rule", "Never draw a star brighter than it is", "Magnitude sets the size.", tag, 40),
        _u(path, "rule", "Always mark north", "North is up unless the owner says.", tag, 50),
        *extra,
    ]


def test_a_skill_is_proposed_whole_and_one_clive_has_is_only_pointed_at(model):
    alpha = _skill("skills/star-charts", "star-charts", (
        _u("skills/star-charts/reference.md", "knowledge", "Catalogues", "Which catalogues to use."),
        _u("skills/star-charts/LICENSE.txt", "knowledge", "Licence", "Terms of use."),
    ))
    have = [_u("skills/web-design-guidelines/SKILL.md", "knowledge", "web-design-guidelines",
               "Review UI code.", ("skill:web-design-guidelines",)),
            _u("skills/web-design-guidelines/SKILL.md", "rule", "Buttons need labels",
               "Every button has a label.", ("skill:web-design-guidelines",), 9)]
    dev = _skill(".claude/skills/dev", "dev")
    kept = _propose([*alpha, *have, *dev], model, budget=None).kept
    by_unit = {p.unit_id: p for p in kept}
    skills = [p for p in kept if p.target == "builder_skill"]
    assert [p.unit_id for p in skills] == [alpha[0].id, dev[0].id]      # the maintainers' own last
    whole = by_unit[alpha[0].id]
    assert "The skill 'star-charts' (3 procedures, 2 rules, 2 pieces of knowledge)" in whole.reasoning
    assert [(a.kind, a.ref.startswith(".claude/skills/star-charts-")) for a in whole.removal.additions] == [
        ("skill", True)]
    assert "steers every builder" in explain(whole).needs_owner
    assert "maintainers" in by_unit[dev[0].id].reasoning
    assert f"cost {PROJECT_COST * OWNER_COST:.2f}" in explain(by_unit[dev[0].id]).rank
    # the skill CLIVE has is one pointer; its licence file is housekeeping, not part of it
    pointer = by_unit[have[0].id]
    assert pointer.target == "reference_only" and "builder_skill:web-design-guidelines" in pointer.reasoning
    assert have[1].id not in by_unit
    assert by_unit[alpha[-1].id].target == "reference_only" and "housekeeping" in by_unit[alpha[-1].id].reasoning
    assert not {u.id for u in alpha[1:-1]} & set(by_unit)


def test_a_files_procedures_rules_and_code_are_one_proposal_each(model):
    units = [
        _u("docs/guide.md", "procedure", "Publish a release", PROCEDURE, (), 1),
        _u("docs/guide.md", "procedure", "Roll a release back", PROCEDURE + " Undo it.", (), 20),
        *[_u("docs/rules.md", "rule", f"Rule {n}: never ship on a Friday {n}",
             "Ship early in the week so a fault is seen while people are around.", (), 1 + n)
          for n in range(3)],
        _u("docs/notes.md", "rule", "Never hide a failing check", "Say it plainly.", (), 1),
        _u("lib/orbits.py", "capability", "function plot", "Plot an orbit from its elements.", ("python",), 5),
        _u("lib/orbits.py", "pattern", "module lib.orbits", "Orbits of comets and asteroids.", ("python",), 1),
        _u("lib/orbits.py", "capability", "function period", "The period of an orbit.", ("python",), 9),
        _u("tests/test_orbits.py", "check", "tests for orbits", "Checks plot and period.", ("test",)),
        _u("CHANGELOG.md", "rule", "Always add an entry here", "Every change gets a line.", ()),
    ]
    kept = _propose(units, model, budget=None).kept
    by_unit = {p.unit_id: p for p in kept}
    assert len(kept) == 6
    skill = by_unit[units[0].id]
    assert skill.target == "builder_skill" and "The procedures of docs/guide.md (2 procedures)" in skill.reasoning
    checks = by_unit[units[2].id]
    assert checks.target == "review_check" and "The rules and checks of docs/rules.md (3 rules)" in checks.reasoning
    assert checks.removal.additions[0].ref.startswith("review-check-set:docs-rules-md-")
    lone = by_unit[units[5].id]
    assert lone.target == "review_check" and "substance 0.30" in explain(lone).rank
    code = by_unit[units[7].id]                                  # anchored on the module
    assert code.target == "native_objective" and "The code of lib/orbits.py" in code.reasoning
    assert code.removal.additions[0].ref.startswith("objective:orbits-py-")
    assert by_unit[units[9].id].target == "reference_only"       # a test of the artifact's code
    assert by_unit[units[10].id].target == "reference_only"      # its changelog


# --- what may be taken, and who decides ---------------------------------------------------------


def test_licences_decide_what_may_be_taken(model):
    folders = ("open", "vendor", "copyleft", "odd")
    units = [_u(f"{folder}/guide.md", "procedure", f"Publish a {folder} release", PROCEDURE)
             for folder in folders]
    licences = {"": MIT, "vendor": ("LicenseRef-Proprietary", "vendor/LICENSE"),
                "copyleft": ("GPL-3.0-only", "copyleft/COPYING"), "odd": ("unknown", "odd/LICENSE")}
    by_unit = {p.unit_id: p for p in _propose(units, model, licences=licences, budget=None).kept}
    open_, vendor, copyleft, odd = (by_unit[u.id] for u in units)
    assert explain(open_).licence == "MIT: keep its copyright and licence notice (LICENSE) with what is added."
    assert vendor.target == "reference_only" and "forbids reuse" in vendor.reasoning
    assert vendor.removal.additions == () and explain(vendor).licence == ""
    assert copyleft.target == "builder_skill" and "conditions" in explain(copyleft).needs_owner
    assert explain(copyleft).licence.startswith("GPL-3.0-only (in copyleft/COPYING)")
    assert "could not be identified" in explain(odd).needs_owner
    # no licence at all grants nothing: the owner decides, and it ranks lower for it
    [bare] = _propose(units[:1], model, licences=None, budget=None).kept
    assert "no licence" in explain(bare).needs_owner and explain(bare).licence == "none found."
    assert f"cost {UNLICENSED_COST * OWNER_COST:.2f}" in explain(bare).rank
    # the artifact's own licence, from its Source, covers what no folder licenses
    [sourced] = proposals(ARTIFACT, units[:1], relate(units[:1], model), recorded_at=RECORDED,
                          licence="Apache-2.0").kept
    assert explain(sourced).licence.startswith("Apache-2.0: keep its copyright")


def test_a_remote_api_is_a_connector_the_owner_approves_read_or_write(model):
    units = [
        _u("mcp.json", "capability", "MCP tool fetch_url", "Fetch a URL and return its text.",
           ("mcp", "read")),
        _u("openapi.yaml", "capability", "GET /telescopes/{id}", "Read a telescope's record.",
           ("openapi", "read"), 5),
    ]
    for proposal in _propose(units, model, budget=None).kept:
        assert proposal.target == "tool_connector"
        assert explain(proposal).needs_owner.startswith(REMOTE_API)
        connector, client, test = proposal.removal.additions
        assert connector.kind == "connector" and connector.ref.startswith("digested_")
        assert client.ref == f"crooks-assistant/app/clients/{connector.ref}.py"
        assert test.ref == f"crooks-assistant/tests/test_{connector.ref}.py"


def test_a_dataset_profiled_in_part_or_holding_personal_data_is_fed_nowhere(model):
    units = [
        _u("data/wide.csv", "data_schema", "Dataset wide.csv", "Columns: 102 (the first 100 profiled)",
           ("dataset", "csv", "partial")),
        _u("data/people.csv", "data_schema", "Dataset people.csv", "Columns: name, email",
           ("dataset", "csv", "personal")),
        _u("data/sales.csv", "data_schema", "Dataset sales.csv", "Columns: date, total, currency",
           ("dataset", "csv")),
    ]
    by_unit = {p.unit_id: p for p in _propose(units, model, budget=None).kept}
    assert by_unit[units[0].id].target == "reference_only" and "part" in by_unit[units[0].id].reasoning
    assert by_unit[units[1].id].target == "reference_only"
    assert by_unit[units[2].id].target == "tool_connector"


def test_a_credential_is_never_quoted_in_a_proposal(model):
    """The unit's title, its path, or a credential the scanner found in its file: the proposal
    names its kind and says why its title and place are withheld; what it would add is named
    from its id."""
    units = [
        _u("lib/client.py", "capability", f"function connect (token {TOKEN})", "Connect.", ("python",)),
        _u(f"docs/{TOKEN}.md", "knowledge", "Parcel labels", "Royal Mail Click & Drop labels carry "
           "each parcel's tracking number.", ()),
        _u("config/deploy.md", "rule", f'Host password = "{HOST_PASSWORD}"', "Use the host.", ()),
        _u("config/settings.md", "procedure", "Deploy the service", PROCEDURE, ()),
    ]
    found = Finding(ARTIFACT, "safety", "medium", Location("config/settings.md", 3, 3),
                    "secret.password_assignment: a password is assigned in this file.")
    made = _propose(units, model, findings=[found], budget=None).kept
    assert len(made) == 4
    for proposal in made:
        text = json.dumps(proposal.to_dict())
        assert TOKEN not in text and HOST_PASSWORD not in text
        assert "Deploy the service" not in text
        assert "its title and place are withheld" in proposal.reasoning
        for addition in proposal.removal.additions:
            assert "connect" not in addition.ref and "deploy" not in addition.ref


def test_a_gap_is_only_a_pointer_when_the_self_model_could_not_read_clive(model, tmp_path):
    """With no registries read, a unit that seems new to CLIVE may be a tool it has."""
    bare = build_self_model(tmp_path)
    assert bare.unread
    unit = _u("lib/client.py", "capability", "function plot_orbit", "Plot an orbit.", ("python",))
    [relation] = relate([unit], bare)
    assert relation.relation == "gap"
    [proposal] = proposals(ARTIFACT, [unit], [relation], recorded_at=RECORDED, licences={"": MIT},
                           self_model=bare).kept
    assert proposal.target == "reference_only" and "could not be read" in proposal.reasoning
    # the same, against a self-model that did read them, is proposed
    [full] = proposals(ARTIFACT, [unit], relate([unit], model), recorded_at=RECORDED,
                       licences={"": MIT}, self_model=model).kept
    assert full.target == "native_objective"


def test_every_proposal_is_one_the_owner_decides(model):
    units = [*_skill("skills/star-charts", "star-charts"),
             _u("lib/client.py", "capability", "MCP tool fetch_url", "Fetch.", ("mcp", "read"))]
    for proposal in _propose(units, model, budget=None).kept:
        assert proposal.decided_by is None
        assert (proposal.target in ADDING_TARGETS) == bool(proposal.removal.additions)
        assert needs_owner(proposal) == bool(explain(proposal).needs_owner)


# --- the scanner's answers that proposals rest on -----------------------------------------------


def test_each_folder_has_the_licence_that_covers_it(tmp_path):
    (tmp_path / "LICENSE").write_text(
        "MIT License\n\nCopyright (c) 2026 Example\n\nPermission is hereby granted, free of "
        "charge, to any person obtaining a copy of this software.\n", encoding="utf-8")
    (tmp_path / "vendor" / "lib").mkdir(parents=True)
    (tmp_path / "vendor" / "package.json").write_text('{"license": "UNLICENSED"}', encoding="utf-8")
    (tmp_path / "gpl").mkdir()
    (tmp_path / "gpl" / "package.json").write_text('{"license": "GPL-3.0-only"}', encoding="utf-8")
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "package.json").write_text('{"license": "GPL-3.0-only"}')
    licences = scan.licence_map(tmp_path)
    assert licences == {"": ("MIT", "LICENSE"), "vendor": ("LicenseRef-Proprietary", "vendor/package.json"),
                        "gpl": ("GPL-3.0-only", "gpl/package.json")}
    assert scan.licence_for("vendor/lib/a.js", licences) == licences["vendor"]
    assert scan.licence_for("docs/a.md", licences) == licences[""]
    assert scan.licence_for("a.md", {}) is None
    assert [scan.licence_rank(e) for e in ("MIT", "GPL-3.0-only", "LicenseRef-Proprietary",
                                          "unknown", "MIT; GPL-3.0-only", None)] == [0, 1, 2, 1, 1, None]
    assert scan.holds_secret(f"see {TOKEN}") and not scan.holds_secret("plain words")
