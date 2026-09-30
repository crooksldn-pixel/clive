"""The owner's curated skill list (OWNER_DECISIONS_2026-09-30, 'The owner's curated skill list is
the owner's decision'): with curated, every builder skill of the artifact is proposed, none held
back by the budget and none waiting on the owner's sign-off; every other target keeps its budget
and its reasons to need the owner, the licence still decides, and without curated nothing
changes.

Units and the self-model are built as tests/test_digest_propose.py builds them."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from app.digest import scan
from app.digest.model import Location, Source, Unit, content_digest
from app.digest.pipeline import digest, tree_digest
from app.digest.propose import BUDGET, REMOTE_API, explain, needs_owner, proposals
from app.digest.relate import relate
from app.digest.report import render
from app.digest.selfmodel import build_self_model
from tests.test_digest_relate import REPO_ROOT, fixture_memory

RECORDED = "2026-09-30T10:00:00+00:00"
SOURCE = Source(
    origin="https://example.invalid/curated-fixture.git", origin_kind="git",
    pinned_ref="0123456789abcdef0123456789abcdef01234567", licence="MIT", taken_at=RECORDED,
    content_digest=content_digest(b"the curated fixture"),
)
ARTIFACT = SOURCE.artifact_id
MIT = ("MIT", "LICENSE")
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
LISTED = "The owner listed this artifact's skills himself (OWNER_DECISIONS_2026-09-30)"

# Seven skills, each a SKILL.md with front matter and a few steps, on nothing CLIVE has.
SKILLS = {
    "star-charts": ("Draw star charts for any night sky.",
                    ("Plot the stars", "Label the constellations", "Export the chart")),
    "tide-tables": ("Read tide tables for a stretch of coast.",
                    ("Find the harbour", "Read high water", "Allow for the moon")),
    "beekeeping": ("Keep a hive of honey bees healthy.",
                   ("Open the hive", "Inspect the brood frames", "Feed the colony syrup")),
    "sourdough": ("Bake a sourdough loaf from a starter.",
                  ("Feed the starter", "Shape the dough", "Bake in a hot oven")),
    "knots": ("Tie sailing knots that hold and untie.",
              ("Tie a bowline", "Tie a clove hitch", "Whip a rope end")),
    "bird-ringing": ("Ring wild birds for migration records.",
                     ("Raise the mist net", "Fit the ring", "Record the wing length")),
    "cheese-ageing": ("Age hard cheese in a cellar.",
                      ("Salt the rind", "Turn the wheels", "Check the humidity")),
}
# Remote API reads, more than the connector budget, and a design token set.
APIS = ("GET /telescopes/{id}", "GET /observatories", "GET /comets/{designation}",
        "GET /eclipses/{year}", "GET /meteor-showers", "GET /satellites/{norad}",
        "GET /planets/{name}/moons")


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    return build_self_model(REPO_ROOT, memory=fixture_memory(tmp_path_factory.mktemp("memory")))


def _u(path: str, kind: str, title: str, body: str = "", tags: tuple[str, ...] = (),
       line: int = 1) -> Unit:
    return Unit(ARTIFACT, kind, title, body, Location(path, line, line + 1), tags)


def _skill(name: str, folder: str = "skills") -> list[Unit]:
    description, steps = SKILLS[name]
    tag = (f"skill:{name}",)
    path = f"{folder}/{name}/SKILL.md"
    return [
        _u(path, "knowledge", name, f"{name}: {description}", tag, 1),
        *[_u(path, "procedure", step, f"1. {step}.\n2. Note it in the {name} log.\n3. Check it "
             "again the next morning before going on.", tag, 10 * (n + 1))
          for n, step in enumerate(steps)],
    ]


def _connectors() -> list[Unit]:
    return [_u("api/openapi.yaml", "capability", title, f"Read the {title.split('/')[1]} records.",
               ("openapi", "read"), 10 * (n + 1)) for n, title in enumerate(APIS)]


TOKENS = (("Colour tokens", "night-blue #0b1d3a; star-white #f5f5f0; comet-amber #f2a900"),
          ("Spacing tokens", "gap-small 4px; gap-medium 12px; gap-wide 32px; gutter 48px"))


def _artifact() -> list[Unit]:
    units = [unit for name in SKILLS for unit in _skill(name)]
    units += _connectors()
    units += [_u(f"tokens/{title.split()[0].lower()}.json", "design_token", title, body, ("design",))
              for title, body in TOKENS]
    return units


def _propose(units: list[Unit], model, **given):
    given.setdefault("licences", {"": MIT})
    return proposals(ARTIFACT, units, relate(units, model), recorded_at=RECORDED, **given)


def _skills(kept) -> list:
    return [p for p in kept if p.target == "builder_skill"]


def _others(kept) -> list:
    return [p for p in kept if p.target != "builder_skill"]


def _held_others(held) -> list:
    return [(target, ids) for target, ids in held if target != "builder_skill"]


# --- propose ------------------------------------------------------------------------------------


def test_without_curated_at_most_five_builder_skills_each_needing_the_owner(model):
    units = _artifact()
    made = _propose(units, model)
    skills = _skills(made.kept)
    assert len(skills) == BUDGET["builder_skill"] == 5
    assert made.held_counts()["builder_skill"] == len(SKILLS) - 5
    for proposal in skills:
        assert needs_owner(proposal) and "steers every builder" in explain(proposal).needs_owner
        assert LISTED not in proposal.reasoning
    # off by default: curated=False is what it always was
    assert _propose(units, model, curated=False) == made


def test_with_curated_every_builder_skill_is_proposed_and_none_needs_the_owner(model):
    units = _artifact()
    made = _propose(units, model, curated=True)
    skills = _skills(made.kept)
    assert {p.unit_id for p in skills} == {_skill(name)[0].id for name in SKILLS}
    assert len(skills) == len(SKILLS) == 7
    assert "builder_skill" not in made.held_counts()
    for proposal in skills:
        parts = explain(proposal)
        assert not needs_owner(proposal) and parts.needs_owner == ""
        assert LISTED in parts.why
        assert parts.hypothesis and parts.measure and parts.removal
        assert proposal.decided_by is None and [a.kind for a in proposal.removal.additions] == ["skill"]
    # best first
    scores = [float(explain(p).rank.split(" ")[0]) for p in skills]
    assert scores == sorted(scores, reverse=True)


def test_under_curated_every_other_target_keeps_its_budget_and_needs_the_owner(model):
    units = _artifact()
    plain, curated = _propose(units, model), _propose(units, model, curated=True)
    # exactly as without curated: the same proposals, and the same held back
    assert _others(curated.kept) == _others(plain.kept)
    assert _held_others(curated.held) == _held_others(plain.held)
    connectors = [p for p in curated.kept if p.target == "tool_connector"]
    assert len(connectors) == BUDGET["tool_connector"]
    assert curated.held_counts()["tool_connector"] == len(APIS) - BUDGET["tool_connector"]
    assert all(explain(p).needs_owner.startswith(REMOTE_API) for p in connectors)
    tokens = [p for p in curated.kept if p.target == "design_system"]
    assert len(tokens) == len(TOKENS)
    assert all("CLIVE's look is the owner's" in explain(p).needs_owner for p in tokens)
    assert not any(LISTED in p.reasoning for p in _others(curated.kept))


def test_under_curated_the_licence_still_decides_and_still_needs_the_owner(model):
    units = [*_skill("star-charts"), *_skill("tide-tables", "vendor"), *_skill("sourdough", "copyleft")]
    licences = {"": MIT, "vendor": ("LicenseRef-Proprietary", "vendor/LICENSE"),
                "copyleft": ("GPL-3.0-only", "copyleft/COPYING")}
    plain = {p.unit_id: p for p in _propose(units, model, licences=licences).kept}
    curated = {p.unit_id: p for p in _propose(units, model, licences=licences, curated=True).kept}
    open_, vendor, copyleft = (units[0].id, units[4].id, units[8].id)
    # a licence that forbids reuse: nothing is taken and anything more is the owner's, curated
    # or not — the same proposal either way
    assert curated[vendor] == plain[vendor]
    assert curated[vendor].target == "reference_only" and curated[vendor].removal.additions == ()
    assert "forbids reuse" in curated[vendor].reasoning
    assert "the owner decides anything more" in curated[vendor].reasoning
    # conditions that travel with it are still the owner's to accept
    assert curated[copyleft].target == "builder_skill"
    assert "conditions" in explain(curated[copyleft]).needs_owner
    assert "steers every builder" not in explain(curated[copyleft]).needs_owner
    # a permissive licence: the owner's list is the sign-off
    assert not needs_owner(curated[open_]) and explain(curated[open_]).licence.startswith("MIT")
    # no licence at all grants nothing: the owner's, curated or not
    [bare] = _propose(_skill("knots"), model, licences=None, curated=True).kept
    assert bare.target == "builder_skill" and "no licence" in explain(bare).needs_owner


# --- the pipeline and the report -----------------------------------------------------------------

LICENCE_TEXT = (
    "MIT License\n\nCopyright (c) 2026 Example\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
    "of this software and associated documentation files (the \"Software\"), to deal\n"
    "in the Software without restriction, including without limitation the rights\n"
    "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
    "copies of the Software.\n"
)
FILES = {
    "LICENSE": LICENCE_TEXT,
    **{f"skills/{name}/SKILL.md": (
        f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n\n## Steps\n\n"
        + "".join(f"{n}. {step}.\n" for n, step in enumerate(steps, 1))
    ) for name, (description, steps) in SKILLS.items()},
}


def _tree(base: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return base


def _source(root: Path) -> Source:
    return Source("https://example.invalid/curated.git", "git",
                  "0123456789abcdef0123456789abcdef01234567", "MIT", RECORDED, tree_digest(root))


def test_digest_passes_curated_through_to_proposing(model, tmp_path):
    root = _tree(tmp_path / "tree", FILES)
    plain = digest(root, _source(root), self_model=model, recorded_at=RECORDED)
    curated = digest(root, _source(root), self_model=model, recorded_at=RECORDED, curated=True)
    assert curated.units == plain.units and curated.relations == plain.relations
    made = proposals(curated.artifact.id, curated.units, curated.relations, recorded_at=RECORDED,
                     licence="MIT", licences=scan.licence_map(root), findings=curated.findings,
                     self_model=model, curated=True)
    assert list(curated.proposals) == list(made.kept) and curated.held == made.held
    assert len(_skills(plain.proposals)) == 5 and len(dict(plain.held)["builder_skill"]) == 2
    skills = _skills(curated.proposals)
    assert len(skills) == 7 and not any(needs_owner(p) for p in skills)
    assert "builder_skill" not in dict(curated.held)

    # the report says so in its Proposals section, and names only budgeted targets as held back
    report = render(curated, curated=True)
    proposals_section = report.split("## Proposals")[1]
    assert f"{LISTED}, so its builder skills need no further sign-off" in proposals_section
    assert "Held back by the budget" not in report
    before = render(plain)
    assert "skills himself" not in before and "builder_skill 2" in before
    held = replace(curated, held=(("builder_skill", ("a", "b")), ("tool_connector", ("c",))))
    line = next(x for x in render(held, curated=True).splitlines() if x.startswith("Held back"))
    assert "tool_connector 1" in line and "builder_skill" not in line


# --- the command line ----------------------------------------------------------------------------


def _cli(script: str, *args: object, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, timeout=180, check=False)


def _counted(line: str) -> dict[str, str]:
    found = re.search(r"; proposals: (.+) \(\d+ need the owner\)(; curated)?$", line)
    assert found, line
    return dict(item.rsplit(" ", 1) for item in found.group(1).split(", "))


def test_the_scripts_pass_curated_through(tmp_path):
    root = _tree(tmp_path / "tree", FILES)
    report = tmp_path / "report.md"
    done = _cli("digest.py", root, "--origin", "https://example.invalid/curated.git",
                "--licence", "MIT", "--curated", "--report", report, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    [line] = done.stdout.splitlines()
    assert line.endswith("; curated") and _counted(line)["builder_skill"] == "7"
    assert LISTED in report.read_text(encoding="utf-8")
    plain = _cli("digest.py", root, "--origin", "https://example.invalid/curated.git",
                 "--licence", "MIT", cwd=tmp_path)
    assert plain.returncode == 0, plain.stderr
    assert "curated" not in plain.stdout and _counted(plain.stdout.strip())["builder_skill"] == "5"

    taken = _cli("digest_intake.py", root, "--quarantine", tmp_path / "q", "--curated", cwd=tmp_path)
    assert taken.returncode == 0, taken.stderr
    [line] = taken.stdout.splitlines()
    assert line.endswith("; curated") and _counted(line)["builder_skill"] == "7"


@pytest.mark.parametrize("other", ["--self", "--no-relate"])
def test_the_scripts_refuse_curated_with_self_or_no_relate(tmp_path, other):
    root = _tree(tmp_path / "tree", FILES)
    done = _cli("digest.py", root, "--origin", "x", "--curated", other, cwd=tmp_path)
    assert done.returncode == 1 and f"--curated is not allowed with {other}" in done.stderr
    taken = _cli("digest_intake.py", root, "--quarantine", tmp_path / "q", "--curated", other,
                 cwd=tmp_path)
    assert taken.returncode == 1 and f"--curated is not allowed with {other}" in taken.stderr
    assert not (tmp_path / "q").exists()
